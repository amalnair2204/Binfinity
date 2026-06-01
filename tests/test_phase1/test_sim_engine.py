"""Tests for SimEngine — covers _load_bins, _tick, _process_bin, _write_snapshot,
and the run() loop (partial, via cancellation)."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emulator.bin_model import BinNode
from emulator.sim_engine import SimEngine
from emulator.telemetry import TelemetryDB, TelemetryPacket


# ── helpers ───────────────────────────────────────────────────────────────────

def _bin_data(bin_id="BIN-0001", fill_pct=10.0) -> dict:
    return dict(
        bin_id=bin_id,
        lat=25.2048,
        lng=55.2708,
        zone="residential",
        base_fill_rate=2.0,
        capacity_liters=120.0,
        current_fill_pct=fill_pct,
        battery_mv=4000,
    )


@pytest.fixture
def bins_json(tmp_path) -> Path:
    """Write a tiny 2-bin config file and return its path."""
    data = [_bin_data("BIN-0001"), _bin_data("BIN-0002", fill_pct=50.0)]
    p = tmp_path / "bins.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def engine(bins_json, tmp_path) -> SimEngine:
    """Return a SimEngine pointed at tmp_path db and bins_json."""
    db_path = str(tmp_path / "telemetry.db")
    eng = SimEngine(config_path=str(bins_json), db_path=db_path)
    return eng


# ── _load_bins ────────────────────────────────────────────────────────────────

def test_load_bins_populates_dict(engine):
    assert len(engine.bins) == 2
    assert "BIN-0001" in engine.bins
    assert "BIN-0002" in engine.bins


def test_load_bins_creates_bin_node_instances(engine):
    for b in engine.bins.values():
        assert isinstance(b, BinNode)


def test_load_bins_preserves_fill_pct(bins_json, tmp_path):
    eng = SimEngine(config_path=str(bins_json), db_path=str(tmp_path / "t.db"))
    assert eng.bins["BIN-0002"].current_fill_pct == 50.0


# ── initial state ─────────────────────────────────────────────────────────────

def test_sim_time_starts_monday_6am(engine):
    expected = datetime(2025, 1, 6, 6, 0, 0, tzinfo=timezone.utc)
    assert engine.sim_time == expected


def test_tick_interval_default(engine):
    assert engine.tick_interval == float(os.getenv("SIM_TICK_REAL_SECONDS", "2.0"))


# ── _process_bin ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_bin_returns_packets(engine):
    bin_node = engine.bins["BIN-0001"]
    packets = await engine._process_bin(bin_node)
    assert isinstance(packets, list)
    assert len(packets) >= 1


@pytest.mark.asyncio
async def test_process_bin_triggers_emptying_when_flagged_and_over_85(engine):
    bin_node = engine.bins["BIN-0001"]
    bin_node.current_fill_pct = 90.0
    bin_node.marked_for_collection = True
    packets = await engine._process_bin(bin_node)
    # Should include at least the tick packet plus an emptied packet
    event_types = {p.event_type for p in packets}
    assert "emptied" in event_types


@pytest.mark.asyncio
async def test_process_bin_no_emptying_below_85(engine):
    bin_node = engine.bins["BIN-0001"]
    bin_node.current_fill_pct = 50.0
    bin_node.marked_for_collection = True
    packets = await engine._process_bin(bin_node)
    event_types = {p.event_type for p in packets}
    assert "emptied" not in event_types


@pytest.mark.asyncio
async def test_process_bin_no_emptying_not_flagged(engine):
    bin_node = engine.bins["BIN-0001"]
    # Keep fill well below 85 so normal tick doesn't auto-flag for collection
    bin_node.current_fill_pct = 30.0
    bin_node.marked_for_collection = False
    packets = await engine._process_bin(bin_node)
    event_types = {p.event_type for p in packets}
    assert "emptied" not in event_types


# ── _write_snapshot ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_snapshot_creates_file(engine, tmp_path):
    # Patch the paths inside _write_snapshot to use tmp_path
    with patch("emulator.sim_engine.Path") as mock_path_cls:
        tmp_file = MagicMock()
        final_file = MagicMock()
        mock_path_cls.side_effect = lambda p: tmp_file if "tmp" in p else final_file
        tmp_file.__str__ = lambda self: "tmp"

        with patch("emulator.sim_engine.os.replace") as mock_replace:
            await engine._write_snapshot()
            mock_replace.assert_called_once()


@pytest.mark.asyncio
async def test_write_snapshot_real_file(engine, tmp_path):
    """Write snapshot to real tmp files and verify content."""
    snap_tmp = tmp_path / "bin_states.json.tmp"
    snap_final = tmp_path / "bin_states.json"

    orig_path = __import__("pathlib").Path

    def path_factory(p):
        if str(p).endswith(".tmp"):
            return snap_tmp
        if str(p).endswith("bin_states.json"):
            return snap_final
        return orig_path(p)

    with patch("emulator.sim_engine.Path", side_effect=path_factory), \
         patch("emulator.sim_engine.os.replace", side_effect=lambda s, d: snap_tmp.rename(d)):
        await engine._write_snapshot()

    assert snap_final.exists()
    data = json.loads(snap_final.read_text())
    assert "BIN-0001" in data
    assert "current_fill_pct" in data["BIN-0001"]
    assert "sim_time" in data["BIN-0001"]


# ── _tick ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_advances_sim_time(engine):
    initial_time = engine.sim_time
    engine._db = AsyncMock()
    with patch.object(engine, "_write_snapshot", new_callable=AsyncMock):
        await engine._tick()
    assert engine.sim_time == initial_time + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_tick_calls_db_insert(engine):
    engine._db = AsyncMock()
    with patch.object(engine, "_write_snapshot", new_callable=AsyncMock):
        await engine._tick()
    # At least one insert should have been called (one per packet)
    assert engine._db.insert.call_count >= 1


@pytest.mark.asyncio
async def test_tick_fans_out_to_sse_subscribers(engine):
    engine._db = AsyncMock()
    queue = asyncio.Queue()
    engine.sse_subscribers.add(queue)

    with patch.object(engine, "_write_snapshot", new_callable=AsyncMock):
        await engine._tick()

    assert not queue.empty()


@pytest.mark.asyncio
async def test_tick_removes_full_sse_queues(engine):
    engine._db = AsyncMock()
    # Create a queue with maxsize=0 (blocks put_nowait by filling it)
    full_queue = asyncio.Queue(maxsize=1)
    # Pre-fill so put_nowait raises QueueFull
    full_queue.put_nowait(MagicMock())
    engine.sse_subscribers.add(full_queue)

    with patch.object(engine, "_write_snapshot", new_callable=AsyncMock):
        await engine._tick()

    # Dead queue should have been removed
    assert full_queue not in engine.sse_subscribers


# ── run() — single tick then cancel ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_calls_db_connect_and_close(engine):
    engine._db = AsyncMock()
    tick_count = 0

    async def fake_tick():
        nonlocal tick_count
        tick_count += 1
        if tick_count >= 1:
            raise asyncio.CancelledError()

    engine._tick = fake_tick
    engine.tick_interval = 0

    with pytest.raises(asyncio.CancelledError):
        await engine.run()

    engine._db.connect.assert_called_once()
    engine._db.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_tick_error_does_not_stop_loop(engine):
    """A tick exception should be caught and the loop continue."""
    engine._db = AsyncMock()
    call_count = 0

    async def fake_tick():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("boom")
        raise asyncio.CancelledError()

    engine._tick = fake_tick
    engine.tick_interval = 0

    with pytest.raises(asyncio.CancelledError):
        await engine.run()

    assert call_count == 2  # ran twice: once errored, once cancelled
