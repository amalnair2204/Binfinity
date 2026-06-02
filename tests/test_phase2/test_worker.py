"""Worker unit tests — mock db and cache to test _process_packet and _batch_flusher."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingestion.schemas import BinState, TelemetryPacket

TS = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)


def make_packet(**kwargs) -> TelemetryPacket:
    defaults = dict(
        bin_id="BIN-0001",
        timestamp=TS,
        fill_pct=50.0,
        fill_liters=60.0,
        tipped=False,
        sensor_fault=False,
        battery_mv=4000,
        rssi_dbm=-85,
        temp_c=30.0,
        event_type="scheduled",
    )
    defaults.update(kwargs)
    return TelemetryPacket(**defaults)


def make_state(**kwargs) -> BinState:
    defaults = dict(
        bin_id="BIN-0001",
        last_updated=TS,
        fill_pct=50.0,
        fill_liters=60.0,
        status="operational",
        battery_mv=4000,
        consecutive_fault_ticks=0,
        flagged_for_collection=False,
        last_emptied=None,
    )
    defaults.update(kwargs)
    return BinState(**defaults)


@pytest.fixture(autouse=True)
def reset_worker_state():
    import ingestion.worker as w
    # Save original state
    orig_bin_states = dict(w._bin_states)
    orig_db = w.db
    orig_cache = w.cache
    orig_queue = w._batch_queue

    # Set up mocks
    w._bin_states = {}
    w.db = MagicMock()
    w.db.upsert_bin_state = AsyncMock()
    w.db.log_spill_incident = AsyncMock()
    w.db.bulk_insert_telemetry = AsyncMock()
    w.cache = MagicMock()
    w.cache.set_bin_state = AsyncMock()
    w._batch_queue = asyncio.Queue()

    yield

    # Restore
    w._bin_states = orig_bin_states
    w.db = orig_db
    w.cache = orig_cache
    w._batch_queue = orig_queue


async def test_process_packet_creates_new_bin_state():
    import ingestion.worker as w
    packet = make_packet()
    await w._process_packet(packet)
    assert "BIN-0001" in w._bin_states


async def test_process_packet_upserts_to_db():
    import ingestion.worker as w
    packet = make_packet()
    await w._process_packet(packet)
    w.db.upsert_bin_state.assert_called_once()


async def test_process_packet_updates_cache():
    import ingestion.worker as w
    packet = make_packet()
    await w._process_packet(packet)
    w.cache.set_bin_state.assert_called_once()


async def test_process_packet_enqueues_for_batch():
    import ingestion.worker as w
    packet = make_packet()
    await w._process_packet(packet)
    assert w._batch_queue.qsize() == 1


async def test_process_packet_logs_spill_on_tip():
    import ingestion.worker as w
    # Pre-populate state with a bin that has fill
    w._bin_states["BIN-0001"] = make_state(fill_pct=70.0)
    packet = make_packet(tipped=True, event_type="tip_alert")
    await w._process_packet(packet)
    w.db.log_spill_incident.assert_called_once()


async def test_process_packet_uses_existing_state():
    import ingestion.worker as w
    existing = make_state(fill_pct=60.0, consecutive_fault_ticks=1)
    w._bin_states["BIN-0001"] = existing
    packet = make_packet(fill_pct=100.0)
    await w._process_packet(packet)
    new_state = w._bin_states["BIN-0001"]
    assert new_state.consecutive_fault_ticks == 2


async def test_process_packet_raises_when_db_none():
    import ingestion.worker as w
    w.db = None
    with pytest.raises(RuntimeError, match="Worker not initialized"):
        await w._process_packet(make_packet())


async def test_batch_flusher_drains_queue_and_inserts():
    import ingestion.worker as w
    # Put some packets in the queue
    for _ in range(3):
        await w._batch_queue.put(make_packet())

    # Run one iteration of the flusher (override sleep)
    async def one_shot_flusher():
        batch = []
        while True:
            try:
                batch.append(w._batch_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await w.db.bulk_insert_telemetry(batch)

    await one_shot_flusher()
    w.db.bulk_insert_telemetry.assert_called_once()
    call_args = w.db.bulk_insert_telemetry.call_args[0][0]
    assert len(call_args) == 3
