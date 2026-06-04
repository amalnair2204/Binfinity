"""Calibration and retraining inspection API — prefix /calibration."""
from __future__ import annotations

from typing import Optional

import asyncpg
from fastapi import APIRouter, FastAPI, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from feedback.consumer import RETRAINING_MAE_THRESHOLD, RETRAINING_MIN_EVENTS
from feedback.job_queue import QUEUE_KEY, RetrainJob, RetrainJobQueue
from feedback.model_registry import FeedbackModelRegistry

_redis = None
_pool: asyncpg.Pool | None = None
_job_queue: RetrainJobQueue | None = None
_model_registry: FeedbackModelRegistry | None = None
_consumer = None


def configure(
    redis,
    pool: asyncpg.Pool,
    job_queue: RetrainJobQueue,
    model_registry: FeedbackModelRegistry,
    consumer=None,
) -> None:
    global _redis, _pool, _job_queue, _model_registry, _consumer
    _redis = redis
    _pool = pool
    _job_queue = job_queue
    _model_registry = model_registry
    _consumer = consumer


def _check_ready() -> None:
    if _redis is None or _pool is None or _job_queue is None or _model_registry is None:
        raise HTTPException(status_code=503, detail="service not ready")


router = APIRouter(prefix="/calibration", tags=["calibration"])


class TriggerRequest(BaseModel):
    models: list[str] = ["prophet", "gbm"]
    reason: str = "manual"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
async def health() -> dict:
    _check_ready()
    queue_size = await _job_queue.size()
    return {
        "status": "ok" if (_consumer and _consumer._running) else "idle",
        "consumer_running": _consumer._running if _consumer else False,
        "consumer_processed": _consumer._processed if _consumer else 0,
        "consumer_errors": _consumer._errors if _consumer else 0,
        "queue_size": queue_size,
        "last_event_at": (
            _consumer._last_event_at.isoformat()
            if (_consumer and _consumer._last_event_at)
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Accuracy — literal routes before parameterized
# ---------------------------------------------------------------------------


async def _accuracy_ranked(limit: int, desc: bool) -> list[dict]:
    order_clause = "DESC" if desc else "ASC"
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                bin_id,
                AVG(absolute_error_hours)                              AS mae,
                AVG(CASE WHEN within_1h THEN 1.0 ELSE 0.0 END)       AS within1h_pct,
                COUNT(*)                                               AS n_events,
                MAX(model_used)                                        AS model_used,
                MAX(emptied_at)                                        AS last_seen
            FROM prediction_accuracy
            WHERE emptied_at >= NOW() - INTERVAL '7 days'
            GROUP BY bin_id
            HAVING COUNT(*) >= 1
            ORDER BY mae {order_clause}
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


@router.get("/accuracy/fleet")
async def accuracy_fleet() -> dict:
    _check_ready()
    from feedback.accuracy import get_fleet_rolling_stats_7d

    return await get_fleet_rolling_stats_7d(_pool)


@router.get("/accuracy/worst")
async def accuracy_worst(limit: int = Query(default=20, ge=1, le=100)) -> list:
    _check_ready()
    return await _accuracy_ranked(limit, desc=True)


@router.get("/accuracy/best")
async def accuracy_best(limit: int = Query(default=20, ge=1, le=100)) -> list:
    _check_ready()
    return await _accuracy_ranked(limit, desc=False)


@router.get("/accuracy/{bin_id}/history")
async def accuracy_bin_history(
    bin_id: str,
    limit: int = Query(default=50, ge=1, le=500),
) -> list:
    _check_ready()
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT bin_id, predicted_at, emptied_at, predicted_hours, actual_hours,
                   absolute_error_hours, within_1h, within_2h, model_used,
                   fill_pct_at_prediction, zone_id
            FROM prediction_accuracy
            WHERE bin_id = $1
            ORDER BY emptied_at DESC
            LIMIT $2
            """,
            bin_id,
            limit,
        )
    return [dict(r) for r in rows]


@router.get("/accuracy/{bin_id}")
async def accuracy_bin(bin_id: str) -> dict:
    _check_ready()
    from feedback.accuracy import get_rolling_stats_7d

    stats = await get_rolling_stats_7d(_pool, bin_id)
    return {"bin_id": bin_id, **stats}


# ---------------------------------------------------------------------------
# Retrain — /fleet before /{bin_id}
# ---------------------------------------------------------------------------


@router.get("/retrain/queue")
async def retrain_queue() -> list:
    _check_ready()
    raw_items = await _redis.lrange(QUEUE_KEY, 0, -1)
    jobs = []
    for raw in raw_items:
        try:
            job = RetrainJob.from_json(raw)
            jobs.append(
                {
                    "job_id": job.job_id,
                    "target_type": job.target_type,
                    "target_id": job.target_id,
                    "enqueued_at": job.enqueued_at.isoformat(),
                    "trigger_reason": job.trigger_reason,
                }
            )
        except Exception:
            pass
    return jobs


@router.get("/retrain/jobs")
async def retrain_jobs(limit: int = Query(default=50, ge=1, le=200)) -> list:
    _check_ready()
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT job_id, target_type, target_id, enqueued_at, started_at,
                   completed_at, status, error, trigger_reason
            FROM retrain_jobs_log
            ORDER BY enqueued_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


@router.post("/retrain/trigger/fleet")
async def trigger_retrain_fleet() -> dict:
    _check_ready()
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT bin_id, AVG(absolute_error_hours) AS mae, COUNT(*) AS n_events
            FROM prediction_accuracy
            WHERE emptied_at >= NOW() - INTERVAL '7 days'
            GROUP BY bin_id
            HAVING COUNT(*) >= $1 AND AVG(absolute_error_hours) > $2
            """,
            RETRAINING_MIN_EVENTS,
            float(RETRAINING_MAE_THRESHOLD),
        )
    queued = 0
    for row in rows:
        ok = await _job_queue.enqueue(
            "bin",
            row["bin_id"],
            f"fleet manual retrain (MAE={float(row['mae']):.2f}h)",
        )
        if ok:
            queued += 1
    return {"queued": queued, "degraded_bins": len(rows)}


@router.post("/retrain/trigger/{bin_id}")
async def trigger_retrain_bin(
    bin_id: str,
    body: Optional[TriggerRequest] = None,
) -> dict:
    _check_ready()
    reason = (body.reason if body else None) or "manual"
    queued = await _job_queue.enqueue("bin", bin_id, f"manual: {reason}")
    return {"queued": queued, "bin_id": bin_id}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@router.get("/registry")
async def registry_list() -> dict:
    _check_ready()
    return await _model_registry.list_all()


@router.get("/registry/{bin_id}")
async def registry_bin(bin_id: str) -> dict:
    _check_ready()
    result = {}
    for prefix in ("prophet", "gbm"):
        key = f"{prefix}_{bin_id}"
        meta = await _model_registry.get_meta(key)
        if meta:
            result[prefix] = meta
    if not result:
        raise HTTPException(status_code=404, detail=f"no models for bin {bin_id!r}")
    return result


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.get("/events/recent")
async def events_recent(limit: int = Query(default=50, ge=1, le=500)) -> list:
    _check_ready()
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT bin_id, predicted_at, emptied_at, predicted_hours, actual_hours,
                   absolute_error_hours, within_1h, within_2h, model_used,
                   fill_pct_at_prediction, zone_id
            FROM prediction_accuracy
            ORDER BY emptied_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


app = FastAPI(title="Binfinity Calibration API")
app.include_router(router)
