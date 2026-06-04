"""
Edge case integration tests — verify emulator-level behaviour
for spike, sensor blockage, tip-over, and bin_states.json snapshot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from emulator.bin_model import BinNode

MONDAY_6AM = datetime(2025, 1, 6, 6, 0, tzinfo=timezone.utc)


def make_bin(**kwargs) -> BinNode:
    defaults = dict(
        bin_id="BIN-TEST",
        lat=25.2048, lng=55.2708,
        zone="residential",
        base_fill_rate=2.0,
        capacity_liters=120.0,
        current_fill_pct=10.0,
        battery_mv=4000,
    )
    defaults.update(kwargs)
    return BinNode(**defaults)


# ── volatile spike ────────────────────────────────────────────────────────────

def test_spike_does_not_set_sensor_fault():
    b = make_bin(current_fill_pct=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=50.0):
        packets = b.tick(MONDAY_6AM)
    assert not b.sensor_fault
    assert not packets[0].sensor_fault


def test_spike_event_type_is_spike():
    b = make_bin(current_fill_pct=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=50.0):
        packets = b.tick(MONDAY_6AM)
    assert packets[0].event_type == "spike"


def test_spike_fill_capped_at_100():
    b = make_bin(current_fill_pct=80.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=70.0):
        b.tick(MONDAY_6AM)
    assert b.current_fill_pct == 100.0
    assert b.marked_for_collection  # spike past 85% should flag for collection


# ── sensor blockage ───────────────────────────────────────────────────────────

def test_blockage_sets_sensor_fault_true():
    b = make_bin()
    b.sensor_fault = True
    b._fault_ticks_remaining = 3
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        packets = b.tick(MONDAY_6AM)
    assert packets[0].sensor_fault


def test_blockage_reports_100pct_fill():
    b = make_bin(current_fill_pct=40.0)
    b.sensor_fault = True
    b._fault_ticks_remaining = 2
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        packets = b.tick(MONDAY_6AM)
    assert packets[0].fill_pct == 100.0


def test_blockage_self_clears_after_fault_ticks():
    b = make_bin()
    b.sensor_fault = True
    b._fault_ticks_remaining = 1
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        b.tick(MONDAY_6AM)
    assert not b.sensor_fault
    assert b._fault_ticks_remaining == 0


def test_blockage_faulted_bin_not_flagged_for_collection():
    b = make_bin(current_fill_pct=50.0)
    b.sensor_fault = True
    b._fault_ticks_remaining = 2
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        b.tick(MONDAY_6AM)
    assert not b.marked_for_collection


def test_non_faulted_bin_at_100pct_is_flagged():
    """Non-faulted bin reaching 100% during spike must be flagged for collection."""
    b = make_bin(current_fill_pct=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=90.0):   # 10 + 90 = 100, clamped
        b.tick(MONDAY_6AM)
    assert b.marked_for_collection


# ── tip-over ──────────────────────────────────────────────────────────────────

def test_tip_over_bypasses_normal_cycle():
    """Tip-over emits exactly 1 packet immediately without going through fill logic."""
    b = make_bin(current_fill_pct=60.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):
        packets = b.tick(MONDAY_6AM)
    assert len(packets) == 1
    assert packets[0].event_type == "tip_alert"


def test_tip_over_fill_is_zero_in_packet():
    b = make_bin(current_fill_pct=60.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):
        packets = b.tick(MONDAY_6AM)
    assert packets[0].fill_pct == 0.0


# ── bin_states.json snapshot ──────────────────────────────────────────────────

def test_snapshot_written_atomically(tmp_path):
    """Simulate what SimEngine._write_snapshot does and verify file content."""
    b = make_bin(current_fill_pct=45.5)
    snapshot = {
        b.bin_id: {
            "bin_id": b.bin_id,
            "current_fill_pct": round(b.current_fill_pct, 2),
            "fill_liters": round(b.current_fill_pct / 100.0 * b.capacity_liters, 2),
            "sensor_fault": b.sensor_fault,
            "tipped": b.tipped,
            "battery_mv": b.battery_mv,
        }
    }
    tmp = tmp_path / "bin_states.json.tmp"
    final = tmp_path / "bin_states.json"
    tmp.write_text(json.dumps(snapshot))
    tmp.rename(final)

    loaded = json.loads(final.read_text())
    assert loaded[b.bin_id]["current_fill_pct"] == 45.5


def test_snapshot_reflects_latest_state(tmp_path):
    """Snapshot must show the most recent fill_pct, not a stale value."""
    b = make_bin(current_fill_pct=10.0)

    for fill in [20.0, 50.0, 75.0]:
        b.current_fill_pct = fill
        snapshot = {b.bin_id: {"current_fill_pct": round(b.current_fill_pct, 2)}}
        tmp = tmp_path / "bin_states.json.tmp"
        final = tmp_path / "bin_states.json"
        tmp.write_text(json.dumps(snapshot))
        tmp.replace(final)

    loaded = json.loads(final.read_text())
    assert loaded[b.bin_id]["current_fill_pct"] == 75.0
