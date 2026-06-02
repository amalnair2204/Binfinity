"""
asyncpg database layer tests.
Requires live PostgreSQL. Set TEST_DATABASE_URL env var.
Tests use transactions that rollback — no persistent state.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import asyncpg
import pytest

from ingestion.db import IngestionDB
from ingestion.schemas import BinState, TelemetryPacket

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:binfinity@localhost:5432/binfinity",
)

TS = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)


def make_packet(**kwargs) -> TelemetryPacket:
    defaults = dict(
        bin_id="BIN-0001",
        timestamp=TS,
        fill_pct=67.4,
        fill_liters=80.9,
        tipped=False,
        sensor_fault=False,
        battery_mv=3720,
        rssi_dbm=-89,
        temp_c=34.1,
        event_type="scheduled",
    )
    defaults.update(kwargs)
    return TelemetryPacket(**defaults)


def make_state(**kwargs) -> BinState:
    defaults = dict(
        bin_id="BIN-0001",
        last_updated=TS,
        fill_pct=67.4,
        fill_liters=80.9,
        status="operational",
        battery_mv=3720,
        consecutive_fault_ticks=0,
        flagged_for_collection=False,
        last_emptied=None,
    )
    defaults.update(kwargs)
    return BinState(**defaults)


@pytest.fixture
async def db():
    """IngestionDB connected to test DB, tables created, torn down after test."""
    instance = IngestionDB(TEST_DB_URL)
    await instance.connect()
    yield instance
    # Cleanup test data
    async with instance._pool.acquire() as conn:
        await conn.execute("DELETE FROM spill_incidents WHERE bin_id = 'BIN-0001'")
        await conn.execute("DELETE FROM bin_states WHERE bin_id = 'BIN-0001'")
        await conn.execute("DELETE FROM telemetry WHERE bin_id = 'BIN-0001'")
    await instance.close()


# ── telemetry inserts ─────────────────────────────────────────────────────────

async def test_bulk_insert_telemetry(db: IngestionDB):
    packets = [make_packet() for _ in range(3)]
    await db.bulk_insert_telemetry(packets)
    async with db._pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM telemetry WHERE bin_id='BIN-0001'"
        )
    assert count == 3


async def test_bulk_insert_preserves_all_fields(db: IngestionDB):
    p = make_packet(fill_pct=55.5, event_type="spike")
    await db.bulk_insert_telemetry([p])
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM telemetry WHERE bin_id='BIN-0001' ORDER BY time DESC LIMIT 1"
        )
    assert abs(row["fill_pct"] - 55.5) < 0.01
    assert row["event_type"] == "spike"


# ── bin_states upsert ─────────────────────────────────────────────────────────

async def test_upsert_bin_state_inserts_new_row(db: IngestionDB):
    state = make_state()
    await db.upsert_bin_state(state)
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bin_states WHERE bin_id='BIN-0001'"
        )
    assert row is not None
    assert abs(row["fill_pct"] - 67.4) < 0.01


async def test_upsert_bin_state_updates_not_duplicates(db: IngestionDB):
    state1 = make_state(fill_pct=50.0)
    state2 = make_state(fill_pct=80.0)
    await db.upsert_bin_state(state1)
    await db.upsert_bin_state(state2)
    async with db._pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM bin_states WHERE bin_id='BIN-0001'"
        )
        row = await conn.fetchrow(
            "SELECT fill_pct FROM bin_states WHERE bin_id='BIN-0001'"
        )
    assert count == 1
    assert abs(row["fill_pct"] - 80.0) < 0.01


# ── spill incidents ───────────────────────────────────────────────────────────

async def test_log_spill_incident_creates_row(db: IngestionDB):
    await db.log_spill_incident("BIN-0001", TS, fill_at_spill=72.0)
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM spill_incidents WHERE bin_id='BIN-0001'"
        )
    assert row is not None
    assert abs(row["fill_at_spill"] - 72.0) < 0.01


# ── history query ─────────────────────────────────────────────────────────────

async def test_get_bin_history_returns_correct_limit(db: IngestionDB):
    packets = [make_packet() for _ in range(15)]
    await db.bulk_insert_telemetry(packets)
    rows = await db.get_bin_history("BIN-0001", limit=10)
    assert len(rows) == 10


async def test_get_bin_history_ordered_newest_first(db: IngestionDB):
    from datetime import timedelta
    packets = [
        make_packet(timestamp=TS + timedelta(minutes=30 * i))
        for i in range(5)
    ]
    await db.bulk_insert_telemetry(packets)
    rows = await db.get_bin_history("BIN-0001", limit=5)
    timestamps = [r["time"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
