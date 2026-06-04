"""Async worker that drains ml:feedback:queue and processes emptying events."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from loguru import logger
from pydantic import BaseModel

from feedback.accuracy import (
    PredictionAccuracyRecord,
    insert_accuracy_record,
    update_redis_accuracy_cache,
)
from feedback.job_queue import RetrainJobQueue
from infra.metrics import FEEDBACK_EVENTS_PROCESSED

QUEUE_KEY = "ml:feedback:queue"
LAST_PREDICTION_PREFIX = "ml:last_prediction:"

RETRAINING_MAE_THRESHOLD = 3.0  # trigger retrain if 7-day MAE exceeds this (hours)
RETRAINING_MIN_EVENTS = 5       # require this many events before evaluating threshold


class FeedbackEvent(BaseModel):
    bin_id: str
    emptied_at: datetime
    feedback_type: str = "emptied"
    # Optional fields — existing routing/feedback.py payload may omit these
    route_id: str = ""
    actual_fill_pct: Optional[float] = None
    actual_liters: Optional[float] = None
    truck_id: Optional[str] = None


class FeedbackConsumer:
    def __init__(
        self,
        redis_client,
        pool: asyncpg.Pool,
        job_queue: RetrainJobQueue,
    ) -> None:
        self._redis = redis_client
        self._pool = pool
        self._job_queue = job_queue
        self._processed = 0
        self._errors = 0
        self._last_event_at: datetime | None = None
        self._running = False

    async def start(self) -> None:
        """Main BLPOP loop — runs until stop() is called or task is cancelled."""
        self._running = True
        logger.info("FeedbackConsumer: starting")
        while self._running:
            try:
                result = await self._redis.blpop(QUEUE_KEY, timeout=5)
                if result is None:
                    continue
                _, raw = result
                payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                event = FeedbackEvent(**payload)
                await self.process_event(event)
                self._processed += 1
                self._last_event_at = datetime.now(timezone.utc)
                FEEDBACK_EVENTS_PROCESSED.inc()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._errors += 1
                logger.error("FeedbackConsumer: error processing event: {}", exc)
        logger.info(
            "FeedbackConsumer: stopped (processed={}, errors={})",
            self._processed,
            self._errors,
        )

    def stop(self) -> None:
        self._running = False

    async def process_event(self, event: FeedbackEvent) -> None:
        """Compute prediction accuracy for an emptying event and persist results."""
        prediction = await self._lookup_last_prediction(event.bin_id, event.emptied_at)
        if prediction is None:
            logger.debug(
                "FeedbackConsumer: no prediction found for bin {} at {}",
                event.bin_id,
                event.emptied_at,
            )
            return

        predicted_at = datetime.fromisoformat(str(prediction["predicted_at"]))
        predicted_hours = float(prediction["hours_until_critical"])
        model_used = prediction.get("model_used", "unknown")
        fill_pct_at_prediction = float(prediction.get("fill_pct_current") or 0.0)
        zone_id = str(prediction.get("zone_id") or "")

        actual_hours = (event.emptied_at - predicted_at).total_seconds() / 3600.0
        abs_error = abs(predicted_hours - actual_hours)

        record = PredictionAccuracyRecord(
            bin_id=event.bin_id,
            prediction_id=f"{event.bin_id}:{predicted_at.isoformat()}",
            predicted_at=predicted_at,
            emptied_at=event.emptied_at,
            predicted_hours=predicted_hours,
            actual_hours=actual_hours,
            absolute_error_hours=abs_error,
            within_1h=abs_error <= 1.0,
            within_2h=abs_error <= 2.0,
            model_used=model_used,
            fill_pct_at_prediction=fill_pct_at_prediction,
            zone_id=zone_id,
        )

        await insert_accuracy_record(self._pool, record)
        await update_redis_accuracy_cache(self._redis, self._pool, event.bin_id)
        await self._check_retrain_threshold(event.bin_id, zone_id)

        logger.debug(
            "FeedbackConsumer: bin={} error={:.2f}h within_1h={}",
            event.bin_id,
            abs_error,
            record.within_1h,
        )

    async def _lookup_last_prediction(
        self, bin_id: str, before: datetime
    ) -> dict | None:
        """Return the most recent bin_predictions row before `before`, or None."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT predicted_at, hours_until_critical, fill_pct_current,
                           model_used, confidence, zone_id
                    FROM bin_predictions
                    WHERE bin_id = $1 AND predicted_at < $2
                    ORDER BY predicted_at DESC
                    LIMIT 1
                    """,
                    bin_id,
                    before,
                )
            if row is not None:
                return dict(row)
        except asyncpg.UndefinedTableError:
            pass
        except Exception as exc:
            logger.warning(
                "FeedbackConsumer: bin_predictions lookup failed for {}: {}", bin_id, exc
            )

        # Fallback: latest prediction stored in Redis by the ML API
        raw = await self._redis.get(f"{LAST_PREDICTION_PREFIX}{bin_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            return None

    async def _check_retrain_threshold(self, bin_id: str, zone_id: str) -> None:
        """Enqueue retrain jobs when per-bin 7-day MAE exceeds the threshold."""
        n_raw = await self._redis.get(f"ml:accuracy:{bin_id}:n_events_7d")
        if n_raw is None:
            return
        n_events = int(n_raw.decode() if isinstance(n_raw, bytes) else n_raw)
        if n_events < RETRAINING_MIN_EVENTS:
            return

        mae_raw = await self._redis.get(f"ml:accuracy:{bin_id}:mae_7d")
        if mae_raw is None:
            return
        mae = float(mae_raw.decode() if isinstance(mae_raw, bytes) else mae_raw)
        if mae > RETRAINING_MAE_THRESHOLD:
            reason = (
                f"MAE={mae:.2f}h > threshold={RETRAINING_MAE_THRESHOLD}h "
                f"(7d window, n={n_events})"
            )
            await self._job_queue.enqueue("bin", bin_id, reason)
            if zone_id:
                await self._job_queue.enqueue("zone", zone_id, reason)
