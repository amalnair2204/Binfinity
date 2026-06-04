"""State machine rule tests — all pure, no I/O."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestion.schemas import BinState, TelemetryPacket
from ingestion.state_machine import transition

TS = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)
TS2 = datetime(2025, 1, 6, 8, 30, tzinfo=timezone.utc)


def make_state(**kwargs) -> BinState:
    defaults = dict(
        bin_id="BIN-TEST",
        last_updated=TS,
        fill_pct=30.0,
        fill_liters=36.0,
        status="operational",
        battery_mv=4000,
        consecutive_fault_ticks=0,
        flagged_for_collection=False,
        last_emptied=None,
    )
    defaults.update(kwargs)
    return BinState(**defaults)


def make_packet(**kwargs) -> TelemetryPacket:
    defaults = dict(
        bin_id="BIN-TEST",
        timestamp=TS2,
        fill_pct=30.0,
        fill_liters=36.0,
        tipped=False,
        sensor_fault=False,
        battery_mv=4000,
        rssi_dbm=-85,
        temp_c=32.0,
        event_type="scheduled",
    )
    defaults.update(kwargs)
    return TelemetryPacket(**defaults)


# ── Rule 1: Sensor Blockage ───────────────────────────────────────────────────

def test_100pct_for_1_tick_increments_counter_but_no_fault():
    state = make_state(consecutive_fault_ticks=0)
    packet = make_packet(fill_pct=100.0, fill_liters=120.0)
    new, _ = transition(state, packet)
    assert new.consecutive_fault_ticks == 1
    assert new.status != "sensor_fault"


def test_100pct_for_2_ticks_sets_sensor_fault():
    state = make_state(consecutive_fault_ticks=1)
    packet = make_packet(fill_pct=100.0, fill_liters=120.0)
    new, _ = transition(state, packet)
    assert new.consecutive_fault_ticks == 2
    assert new.status == "sensor_fault"


def test_fault_self_clears_when_fill_drops():
    state = make_state(consecutive_fault_ticks=3, status="sensor_fault")
    packet = make_packet(fill_pct=55.0, fill_liters=66.0)
    new, _ = transition(state, packet)
    assert new.consecutive_fault_ticks == 0
    assert new.status != "sensor_fault"


def test_faulted_bin_not_flagged_for_collection():
    state = make_state(consecutive_fault_ticks=1)
    packet = make_packet(fill_pct=100.0, fill_liters=120.0)
    new, _ = transition(state, packet)
    assert not new.flagged_for_collection


# ── Rule 2: Spike ─────────────────────────────────────────────────────────────

def test_spike_does_not_set_sensor_fault():
    state = make_state(fill_pct=30.0)
    packet = make_packet(fill_pct=75.0, event_type="spike")
    new, _ = transition(state, packet)
    assert new.status != "sensor_fault"
    assert new.consecutive_fault_ticks == 0


def test_spike_updates_fill_normally():
    state = make_state(fill_pct=30.0)
    packet = make_packet(fill_pct=75.0, event_type="spike")
    new, _ = transition(state, packet)
    assert new.fill_pct == 75.0


# ── Rule 3: Collection Flagging ───────────────────────────────────────────────

def test_fill_at_85_flags_for_collection():
    state = make_state()
    packet = make_packet(fill_pct=85.0, fill_liters=102.0)
    new, _ = transition(state, packet)
    assert new.flagged_for_collection


def test_fill_at_84_does_not_flag():
    state = make_state()
    packet = make_packet(fill_pct=84.9, fill_liters=101.9)
    new, _ = transition(state, packet)
    assert not new.flagged_for_collection


def test_emptied_event_clears_collection_flag():
    state = make_state(fill_pct=90.0, flagged_for_collection=True, status="pending_collection")
    packet = make_packet(fill_pct=0.0, fill_liters=0.0, event_type="emptied")
    new, _ = transition(state, packet)
    assert not new.flagged_for_collection
    assert new.fill_pct == 0.0
    assert new.last_emptied == TS2


def test_emptied_records_last_emptied_timestamp():
    state = make_state(fill_pct=90.0, flagged_for_collection=True)
    packet = make_packet(fill_pct=0.0, event_type="emptied", timestamp=TS2)
    new, _ = transition(state, packet)
    assert new.last_emptied == TS2


# ── Rule 4: Tip-Over ──────────────────────────────────────────────────────────

def test_tipped_sets_status_tipped():
    state = make_state()
    packet = make_packet(tipped=True, event_type="tip_alert")
    new, is_spill = transition(state, packet)
    assert new.status == "tipped"
    assert is_spill


def test_tipped_resets_fill_to_zero():
    state = make_state(fill_pct=70.0)
    packet = make_packet(tipped=True, fill_pct=70.0, event_type="tip_alert")
    new, _ = transition(state, packet)
    assert new.fill_pct == 0.0


def test_tipped_clears_collection_flag():
    state = make_state(fill_pct=90.0, flagged_for_collection=True)
    packet = make_packet(tipped=True, event_type="tip_alert")
    new, _ = transition(state, packet)
    assert not new.flagged_for_collection


# ── Rule 5: Low Battery ───────────────────────────────────────────────────────

def test_low_battery_sets_status():
    state = make_state(battery_mv=3300)
    packet = make_packet(battery_mv=3199)
    new, _ = transition(state, packet)
    assert new.status == "low_battery"


def test_normal_battery_not_low_battery():
    state = make_state(battery_mv=4000)
    packet = make_packet(battery_mv=4000)
    new, _ = transition(state, packet)
    assert new.status != "low_battery"


# ── Rule 6: Overflow Risk ─────────────────────────────────────────────────────

def test_fill_70_to_84_sets_overflow_risk():
    state = make_state(fill_pct=60.0)
    packet = make_packet(fill_pct=72.0, fill_liters=86.4)
    new, _ = transition(state, packet)
    assert new.status == "overflow_risk"


# ── Status Priority ───────────────────────────────────────────────────────────

def test_sensor_fault_beats_low_battery():
    """sensor_fault has higher priority than low_battery."""
    state = make_state(consecutive_fault_ticks=1, battery_mv=3100)
    packet = make_packet(fill_pct=100.0, battery_mv=3100)
    new, _ = transition(state, packet)
    assert new.status == "sensor_fault"


def test_tipped_beats_overflow_risk():
    state = make_state(fill_pct=75.0)
    packet = make_packet(tipped=True, fill_pct=75.0, event_type="tip_alert")
    new, _ = transition(state, packet)
    assert new.status == "tipped"


def test_low_battery_beats_pending_collection():
    """A bin at 90% fill with low battery shows low_battery, not pending_collection."""
    state = make_state(fill_pct=85.0)
    packet = make_packet(fill_pct=90.0, battery_mv=3100)
    new, _ = transition(state, packet)
    assert new.status == "low_battery"
