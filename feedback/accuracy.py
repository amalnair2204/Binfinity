"""Prediction accuracy tracking — DB persistence and Redis rolling stats."""
from __future__ import annotations

from datetime import datetime

import asyncpg
from loguru import logger
from pydantic import BaseModel


_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS prediction_accuracy (
    bin_id                  TEXT NOT NULL,
    predicted_at            TIMESTAMPTZ NOT NULL,
    emptied_at              TIMESTAMPTZ NOT NULL,
    predicted_hours         DOUBLE PRECISION,
    actual_hours            DOUBLE PRECISION,
    absolute_error_hours    DOUBLE PRECISION,
    within_1h               BOOLEAN,
    within_2h               BOOLEAN,
    model_used              TEXT,
    fill_pct_at_prediction  DOUBLE PRECISION,
    zone_id                 TEXT,
    PRIMARY KEY (bin_id, predicted_at)
);

CREATE TABLE IF NOT EXISTS bin_predictions (
    bin_id                  TEXT NOT NULL,
    predicted_at            TIMESTAMPTZ NOT NULL,
    hours_until_critical    DOUBLE PRECISION,
    fill_pct_current        DOUBLE PRECISION,
    model_used              TEXT,
    confidence              DOUBLE PRECISION,
    zone_id                 TEXT,
    PRIMARY KEY (bin_id, predicted_at)
);

CREATE TABLE IF NOT EXISTS retrain_jobs_log (
    id              SERIAL PRIMARY KEY,
    job_id          TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    enqueued_at     TIMESTAMPTZ NOT NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL,
    error           TEXT,
    trigger_reason  TEXT
);
"""

_ACCURACY_CACHE_TTL = 8 * 3600  # 8 hours


class PredictionAccuracyRecord(BaseModel):
    bin_id: str
    prediction_id: str
    predicted_at: datetime
    emptied_at: datetime
    predicted_hours: float
    actual_hours: float
    absolute_error_hours: float
    within_1h: bool
    within_2h: bool
    model_used: str
    fill_pct_at_prediction: float
    zone_id: str


async def ensure_tables(pool: asyncpg.Pool) -> None:
    """Create prediction_accuracy, bin_predictions, retrain_jobs_log tables.

    Also attempts create_hypertable for time-series tables; silently skips
    on plain PostgreSQL.
    """
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_TABLES_SQL)
        for table, col in [
            ("prediction_accuracy", "predicted_at"),
            ("bin_predictions", "predicted_at"),
        ]:
            try:
                await conn.execute(
                    f"SELECT create_hypertable('{table}', '{col}', if_not_exists => TRUE)"
                )
                logger.info("Hypertable confirmed: {}", table)
            except asyncpg.PostgresError:
                logger.debug(
                    "create_hypertable skipped for {} — plain PostgreSQL", table
                )


async def insert_accuracy_record(
    pool: asyncpg.Pool, record: PredictionAccuracyRecord
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO prediction_accuracy
                (bin_id, predicted_at, emptied_at, predicted_hours, actual_hours,
                 absolute_error_hours, within_1h, within_2h, model_used,
                 fill_pct_at_prediction, zone_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT (bin_id, predicted_at) DO NOTHING
            """,
            record.bin_id,
            record.predicted_at,
            record.emptied_at,
            record.predicted_hours,
            record.actual_hours,
            record.absolute_error_hours,
            record.within_1h,
            record.within_2h,
            record.model_used,
            record.fill_pct_at_prediction,
            record.zone_id,
        )


async def get_rolling_stats_7d(pool: asyncpg.Pool, bin_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                AVG(absolute_error_hours)                              AS mae,
                AVG(CASE WHEN within_1h THEN 1.0 ELSE 0.0 END)       AS within1h_pct,
                COUNT(*)                                               AS n_events
            FROM prediction_accuracy
            WHERE bin_id = $1
              AND emptied_at >= NOW() - INTERVAL '7 days'
            """,
            bin_id,
        )
    if row is None or row["n_events"] == 0:
        return {"mae": None, "within1h_pct": None, "n_events": 0}
    return {
        "mae": float(row["mae"]),
        "within1h_pct": float(row["within1h_pct"]),
        "n_events": int(row["n_events"]),
    }


async def get_fleet_rolling_stats_7d(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                AVG(absolute_error_hours)                              AS mae,
                AVG(CASE WHEN within_1h THEN 1.0 ELSE 0.0 END)       AS within1h_pct,
                COUNT(*)                                               AS n_events
            FROM prediction_accuracy
            WHERE emptied_at >= NOW() - INTERVAL '7 days'
            """
        )
    if row is None or row["n_events"] == 0:
        return {"mae": None, "within1h_pct": None, "n_events": 0}
    return {
        "mae": float(row["mae"]),
        "within1h_pct": float(row["within1h_pct"]),
        "n_events": int(row["n_events"]),
    }


async def update_redis_accuracy_cache(
    redis, pool: asyncpg.Pool, bin_id: str
) -> None:
    """Refresh per-bin rolling stats in Redis after a new accuracy record."""
    stats = await get_rolling_stats_7d(pool, bin_id)
    if stats["mae"] is not None:
        await redis.setex(
            f"ml:accuracy:{bin_id}:mae_7d", _ACCURACY_CACHE_TTL, str(stats["mae"])
        )
        await redis.setex(
            f"ml:accuracy:{bin_id}:within1h_7d",
            _ACCURACY_CACHE_TTL,
            str(stats["within1h_pct"]),
        )
    await redis.setex(
        f"ml:accuracy:{bin_id}:n_events_7d", _ACCURACY_CACHE_TTL, str(stats["n_events"])
    )


async def refresh_fleet_accuracy_cache(redis, pool: asyncpg.Pool) -> None:
    """Refresh fleet-wide rolling stats in Redis."""
    stats = await get_fleet_rolling_stats_7d(pool)
    if stats["mae"] is not None:
        await redis.setex(
            "ml:accuracy:fleet:mae_7d", _ACCURACY_CACHE_TTL, str(stats["mae"])
        )
        await redis.setex(
            "ml:accuracy:fleet:within1h_7d",
            _ACCURACY_CACHE_TTL,
            str(stats["within1h_pct"]),
        )
    await redis.setex(
        "ml:accuracy:fleet:n_events_7d",
        _ACCURACY_CACHE_TTL,
        str(stats["n_events"]),
    )
