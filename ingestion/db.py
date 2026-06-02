"""AsyncPg-backed TimescaleDB integration layer."""
from __future__ import annotations

from datetime import datetime

import asyncpg
from loguru import logger

from ingestion.schemas import BinState, TelemetryPacket

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS telemetry (
    time         TIMESTAMPTZ NOT NULL,
    bin_id       TEXT        NOT NULL,
    fill_pct     DOUBLE PRECISION,
    fill_liters  DOUBLE PRECISION,
    tipped       BOOLEAN,
    sensor_fault BOOLEAN,
    battery_mv   INTEGER,
    rssi_dbm     INTEGER,
    temp_c       DOUBLE PRECISION,
    event_type   TEXT
);

CREATE TABLE IF NOT EXISTS bin_states (
    bin_id                  TEXT PRIMARY KEY,
    last_updated            TIMESTAMPTZ,
    fill_pct                DOUBLE PRECISION,
    fill_liters             DOUBLE PRECISION,
    status                  TEXT,
    battery_mv              INTEGER,
    consecutive_fault_ticks INTEGER DEFAULT 0,
    flagged_for_collection  BOOLEAN DEFAULT FALSE,
    last_emptied            TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS spill_incidents (
    id            SERIAL PRIMARY KEY,
    bin_id        TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    fill_at_spill DOUBLE PRECISION
);
"""

_UPSERT_BIN_STATE = """
INSERT INTO bin_states
    (bin_id, last_updated, fill_pct, fill_liters, status, battery_mv,
     consecutive_fault_ticks, flagged_for_collection, last_emptied)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (bin_id) DO UPDATE SET
    last_updated            = EXCLUDED.last_updated,
    fill_pct                = EXCLUDED.fill_pct,
    fill_liters             = EXCLUDED.fill_liters,
    status                  = EXCLUDED.status,
    battery_mv              = EXCLUDED.battery_mv,
    consecutive_fault_ticks = EXCLUDED.consecutive_fault_ticks,
    flagged_for_collection  = EXCLUDED.flagged_for_collection,
    last_emptied            = EXCLUDED.last_emptied
"""


class IngestionDB:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self.dsn, min_size=5, max_size=20)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES)
            try:
                await conn.execute(
                    "SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE)"
                )
                logger.info("TimescaleDB hypertable confirmed")
            except asyncpg.PostgresError:
                logger.warning("create_hypertable skipped — running on plain PostgreSQL")
        logger.info("Database pool ready")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def bulk_insert_telemetry(self, packets: list[TelemetryPacket]) -> None:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        if not packets:
            return
        rows = [
            (
                p.timestamp,
                p.bin_id,
                p.fill_pct,
                p.fill_liters,
                p.tipped,
                p.sensor_fault,
                p.battery_mv,
                p.rssi_dbm,
                p.temp_c,
                p.event_type,
            )
            for p in packets
        ]
        async with self._pool.acquire() as conn:
            try:
                await conn.executemany(
                    """INSERT INTO telemetry
                       (time, bin_id, fill_pct, fill_liters, tipped, sensor_fault,
                        battery_mv, rssi_dbm, temp_c, event_type)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    rows,
                )
            except Exception as exc:
                logger.error(f"bulk_insert_telemetry failed for {len(rows)} rows: {exc}")
                raise

    async def upsert_bin_state(self, state: BinState) -> None:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_BIN_STATE,
                state.bin_id,
                state.last_updated,
                state.fill_pct,
                state.fill_liters,
                state.status,
                state.battery_mv,
                state.consecutive_fault_ticks,
                state.flagged_for_collection,
                state.last_emptied,
            )

    async def log_spill_incident(
        self, bin_id: str, occurred_at: datetime, fill_at_spill: float
    ) -> None:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO spill_incidents (bin_id, occurred_at, fill_at_spill) VALUES ($1,$2,$3)",
                bin_id,
                occurred_at,
                fill_at_spill,
            )

    async def get_bin_history(self, bin_id: str, limit: int = 100) -> list[dict]:
        if self._pool is None:
            raise RuntimeError("Database not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM telemetry WHERE bin_id=$1 ORDER BY time DESC LIMIT $2",
                bin_id,
                limit,
            )
        return [dict(r) for r in rows]
