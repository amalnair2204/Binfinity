"""Tests for TelemetryPacket schema and TelemetryDB SQLite writer."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from emulator.bin_model import BinNode
from emulator.telemetry import TelemetryDB, TelemetryPacket, build_packet


def make_bin(**kwargs) -> BinNode:
    defaults = dict(
        bin_id="BIN-TEST",
        lat=25.2048, lng=55.2708,
        zone="residential",
        base_fill_rate=2.0,
        capacity_liters=120.0,
        current_fill_pct=50.0,
        battery_mv=4000,
    )
    defaults.update(kwargs)
    return BinNode(**defaults)


SIM_DT = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)


# ── packet schema ─────────────────────────────────────────────────────────────

def test_packet_contains_all_required_fields():
    b = make_bin()
    p = build_packet(b, SIM_DT, "scheduled")
    assert p.bin_id == "BIN-TEST"
    assert p.event_type == "scheduled"
    assert p.timestamp == SIM_DT


def test_fill_liters_derived_from_fill_pct_and_capacity():
    b = make_bin(current_fill_pct=75.0, capacity_liters=240.0)
    p = build_packet(b, SIM_DT, "scheduled")
    assert abs(p.fill_liters - 180.0) < 0.01   # 75/100 * 240


def test_fill_liters_50pct_120l():
    b = make_bin(current_fill_pct=50.0, capacity_liters=120.0)
    p = build_packet(b, SIM_DT, "scheduled")
    assert abs(p.fill_liters - 60.0) < 0.01


def test_timestamp_has_utc_timezone():
    b = make_bin()
    p = build_packet(b, SIM_DT, "scheduled")
    assert p.timestamp.tzinfo == timezone.utc


def test_timestamp_is_iso8601():
    b = make_bin()
    p = build_packet(b, SIM_DT, "scheduled")
    # Should not raise
    datetime.fromisoformat(p.timestamp.isoformat())


def test_field_types():
    b = make_bin()
    p = build_packet(b, SIM_DT, "scheduled")
    assert isinstance(p.fill_pct, float)
    assert isinstance(p.fill_liters, float)
    assert isinstance(p.sensor_fault, bool)
    assert isinstance(p.tipped, bool)
    assert isinstance(p.battery_mv, int)
    assert isinstance(p.rssi_dbm, int)
    assert isinstance(p.temp_c, float)


def test_rssi_within_realistic_range():
    b = make_bin()
    for _ in range(20):
        p = build_packet(b, SIM_DT, "scheduled")
        assert -100 <= p.rssi_dbm <= -70


def test_temp_within_dubai_range():
    b = make_bin()
    for _ in range(20):
        p = build_packet(b, SIM_DT, "scheduled")
        assert 20.0 <= p.temp_c <= 45.0


def test_valid_event_types():
    b = make_bin()
    for et in ["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]:
        p = build_packet(b, SIM_DT, et)
        assert p.event_type == et


# ── SQLite writer ─────────────────────────────────────────────────────────────

async def test_sqlite_row_insertion():
    db = TelemetryDB(":memory:")
    await db.connect()
    b = make_bin()
    p = build_packet(b, SIM_DT, "scheduled")
    await db.insert(p)
    assert await db.count() == 1
    await db.close()


async def test_sqlite_row_count_increments():
    db = TelemetryDB(":memory:")
    await db.connect()
    b = make_bin()
    for _ in range(5):
        await db.insert(build_packet(b, SIM_DT, "scheduled"))
    assert await db.count() == 5
    await db.close()


async def test_sqlite_insert_preserves_bin_id():
    db = TelemetryDB(":memory:")
    await db.connect()
    b = make_bin(bin_id="BIN-0042")
    p = build_packet(b, SIM_DT, "scheduled")
    await db.insert(p)
    rows = await db.fetch_all()
    assert rows[0]["bin_id"] == "BIN-0042"
    await db.close()
