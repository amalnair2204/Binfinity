"""Tests for routing/truck_manager.py."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from routing.schemas import Truck
from routing.truck_manager import TruckManager, _load_key, _status_key


def _make_truck(truck_id: str = "T1", shift_end_offset: int = 28800) -> Truck:
    return Truck(
        truck_id=truck_id,
        capacity_liters=10_000,
        depot_lat=25.2048,
        depot_lng=55.2708,
        shift_start_seconds=0,
        shift_end_seconds=shift_end_offset,
    )


@pytest.fixture
def manager(fake_redis, mock_db_pool):
    pool, _ = mock_db_pool
    return TruckManager(fake_redis, pool)


# ---------------------------------------------------------------------------
# Registration and lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_truck_writes_to_redis(fake_redis, manager):
    truck = _make_truck("T1")
    await manager.register_truck(truck)

    raw = await fake_redis.get("dispatch:truck:T1:state")
    assert raw is not None
    result = Truck.model_validate_json(raw)
    assert result.truck_id == "T1"


@pytest.mark.asyncio
async def test_register_truck_writes_to_db(mock_db_pool, manager):
    _, conn = mock_db_pool
    truck = _make_truck("T2")
    await manager.register_truck(truck)
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_register_truck_initialises_load_as_zero(fake_redis, manager):
    await manager.register_truck(_make_truck("T3"))
    raw = await fake_redis.get(_load_key("T3"))
    assert float(raw) == 0.0


# ---------------------------------------------------------------------------
# Position updates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_position_stores_lat_lng(fake_redis, manager):
    import json
    await manager.register_truck(_make_truck("T1"))
    await manager.update_position("T1", 25.30, 55.40)

    pos = await manager.get_position("T1")
    assert pos is not None
    assert pos["lat"] == pytest.approx(25.30)
    assert pos["lng"] == pytest.approx(55.40)
    assert "updated_at" in pos


# ---------------------------------------------------------------------------
# Load updates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_load_stores_value(fake_redis, manager):
    await manager.register_truck(_make_truck("T1"))
    await manager.update_load("T1", 500.0)
    assert await manager.get_current_load("T1") == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Collection and dump
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_collection_increments_load(fake_redis, manager):
    await manager.register_truck(_make_truck("T1"))
    await manager.update_load("T1", 200.0)
    await manager.record_collection("T1", "B001", 80.0)
    assert await manager.get_current_load("T1") == pytest.approx(280.0)


@pytest.mark.asyncio
async def test_record_collection_logs_to_db(mock_db_pool, manager):
    _, conn = mock_db_pool
    await manager.register_truck(_make_truck("T1"))
    await manager.record_collection("T1", "B001", 80.0)
    # register_truck + record_collection each call execute
    assert conn.execute.call_count >= 2


@pytest.mark.asyncio
async def test_record_dump_resets_load(fake_redis, manager):
    await manager.register_truck(_make_truck("T1"))
    await manager.update_load("T1", 800.0)
    await manager.record_dump("T1", "YARD1")
    assert await manager.get_current_load("T1") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_record_dump_logs_to_db(mock_db_pool, manager):
    _, conn = mock_db_pool
    await manager.register_truck(_make_truck("T1"))
    await manager.record_dump("T1", "YARD1")
    assert conn.execute.call_count >= 2


# ---------------------------------------------------------------------------
# Shift status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_shift_status_returns_ending_trucks(fake_redis, manager):
    now = datetime.now(tz=timezone.utc)
    secs = now.hour * 3600 + now.minute * 60 + now.second
    # Shift ends in 10 minutes (well within 30-min threshold)
    truck = _make_truck("T10", shift_end_offset=secs + 600)
    await manager.register_truck(truck)
    await manager.update_status("T10", "active")

    result = await manager.check_shift_status()
    assert "T10" in result


@pytest.mark.asyncio
async def test_check_shift_status_ignores_trucks_with_time_remaining(fake_redis, manager):
    now = datetime.now(tz=timezone.utc)
    secs = now.hour * 3600 + now.minute * 60 + now.second
    # Shift ends in 2 hours
    truck = _make_truck("T11", shift_end_offset=secs + 7200)
    await manager.register_truck(truck)
    await manager.update_status("T11", "active")

    result = await manager.check_shift_status()
    assert "T11" not in result


# ---------------------------------------------------------------------------
# Active trucks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_trucks_excludes_off_shift(fake_redis, manager):
    await manager.register_truck(_make_truck("T20"))
    await manager.register_truck(_make_truck("T21"))
    await manager.update_status("T20", "off_shift")
    await manager.update_status("T21", "active")

    active = await manager.get_active_trucks()
    ids = [t.truck_id for t in active]
    assert "T21" in ids
    assert "T20" not in ids


@pytest.mark.asyncio
async def test_get_active_trucks_excludes_idle(fake_redis, manager):
    await manager.register_truck(_make_truck("T30"))
    await manager.update_status("T30", "idle")

    active = await manager.get_active_trucks()
    assert all(t.truck_id != "T30" for t in active)
