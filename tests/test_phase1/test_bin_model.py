"""Tests for BinNode state machine — fill logic, edge cases, battery."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from emulator.bin_model import (
    BinNode,
    BATTERY_CRITICAL_MV,
    FILL_THRESHOLD_CRITICAL,
    FILL_THRESHOLD_WARNING,
    _tod_multiplier,
    _zone_multiplier,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

MONDAY_6AM = datetime(2025, 1, 6, 6, 0, tzinfo=timezone.utc)   # morning peak
MONDAY_3AM = datetime(2025, 1, 6, 3, 0, tzinfo=timezone.utc)   # night


def make_bin(**kwargs) -> BinNode:
    defaults = dict(
        bin_id="BIN-TEST",
        lat=25.2048,
        lng=55.2708,
        zone="residential",
        base_fill_rate=2.0,
        capacity_liters=120.0,
        current_fill_pct=10.0,
        battery_mv=4000,
    )
    defaults.update(kwargs)
    return BinNode(**defaults)


# ── time-of-day multiplier ────────────────────────────────────────────────────

def test_tod_multiplier_morning_peak():
    assert _tod_multiplier(7.5) == 2.0

def test_tod_multiplier_evening_peak():
    assert _tod_multiplier(18.0) == 1.8

def test_tod_multiplier_night():
    assert _tod_multiplier(2.0) == 0.3

def test_tod_multiplier_normal():
    assert _tod_multiplier(12.0) == 1.0


# ── zone multiplier ───────────────────────────────────────────────────────────

def test_zone_multiplier_park_weekend():
    assert _zone_multiplier("park", 12.0, 5) == 2.5  # Saturday

def test_zone_multiplier_park_weekday():
    assert _zone_multiplier("park", 12.0, 0) == 0.8  # Monday

def test_zone_multiplier_transit_rush():
    assert _zone_multiplier("transit_hub", 8.0, 0) == 2.0

def test_zone_multiplier_commercial_daytime():
    assert _zone_multiplier("commercial", 11.0, 0) == 1.2

def test_zone_multiplier_residential_default():
    assert _zone_multiplier("residential", 14.0, 2) == 1.0


# ── fill accumulation ─────────────────────────────────────────────────────────

def test_fill_accumulates_per_tick():
    """Fill increases after a normal tick at morning peak with no noise."""
    b = make_bin(current_fill_pct=10.0, base_fill_rate=2.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=0.0):
        b.tick(MONDAY_6AM)
    # tod_multiplier(6.0)=2.0, zone_multiplier(residential,6,Mon)=1.0, noise=0
    # delta = 2.0 * 2.0 * 1.0 = 4.0 → fill = 14.0
    assert abs(b.current_fill_pct - 14.0) < 0.01


def test_morning_peak_faster_than_night():
    """Morning peak produces more fill than night for same base rate."""
    b_morning = make_bin(current_fill_pct=10.0)
    b_night = make_bin(current_fill_pct=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5, 0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=0.0):
        b_morning.tick(MONDAY_6AM)
        b_night.tick(MONDAY_3AM)
    assert b_morning.current_fill_pct > b_night.current_fill_pct


def test_fill_clamped_at_100():
    """Fill never exceeds 100.0."""
    b = make_bin(current_fill_pct=99.5, base_fill_rate=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=5.0):
        b.tick(MONDAY_6AM)
    assert b.current_fill_pct == 100.0


def test_fill_clamped_at_0():
    """Fill never goes below 0.0 even with large negative noise."""
    b = make_bin(current_fill_pct=0.1, base_fill_rate=0.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=-50.0):
        b.tick(MONDAY_6AM)
    assert b.current_fill_pct == 0.0


# ── battery ───────────────────────────────────────────────────────────────────

def test_battery_decrements_each_tick():
    b = make_bin(battery_mv=4000)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=0.0):
        b.tick(MONDAY_6AM)
    assert b.battery_mv == 3995


def test_wake_interval_normal():
    b = make_bin(battery_mv=4000)
    assert b.wake_interval_minutes == 30


def test_wake_interval_low_battery():
    b = make_bin(battery_mv=BATTERY_CRITICAL_MV - 1)
    assert b.wake_interval_minutes == 60


def test_wake_interval_at_exact_critical_mv():
    """At exactly 3200mV (not below), interval should be 30 (normal), not 60."""
    b = make_bin(battery_mv=BATTERY_CRITICAL_MV)
    assert b.wake_interval_minutes == 30


def test_battery_does_not_go_below_zero():
    b = make_bin(battery_mv=2)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=0.0):
        b.tick(MONDAY_6AM)
    assert b.battery_mv >= 0


# ── volatile spike ────────────────────────────────────────────────────────────

def test_volatile_spike_increases_fill():
    """Spike increases fill by 30–70%."""
    b = make_bin(current_fill_pct=10.0)
    # random calls: randint(battery)=5, random[tip]=0.5(miss), random[fault]=0.5(miss),
    # random[spike]=0.001(hit), uniform(spike)=50.0
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=50.0):
        packets = b.tick(MONDAY_6AM)
    assert b.current_fill_pct == 60.0
    assert packets[0].event_type == "spike"


def test_volatile_spike_does_not_set_sensor_fault():
    b = make_bin(current_fill_pct=10.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.001]), \
         patch("random.uniform", return_value=50.0):
        packets = b.tick(MONDAY_6AM)
    assert not b.sensor_fault
    assert not packets[0].sensor_fault


# ── sensor blockage ───────────────────────────────────────────────────────────

def test_sensor_blockage_triggers_sensor_fault():
    """When fault triggers, fill=100.0 and sensor_fault=True."""
    b = make_bin(current_fill_pct=50.0)
    # random calls: randint(battery)=5, random[tip]=0.5(miss), random[fault]=0.001(hit),
    # randint(fault_duration)=2
    with patch("random.randint", side_effect=[5, 2]), \
         patch("random.random", side_effect=[0.5, 0.001]):
        packets = b.tick(MONDAY_6AM)
    assert b.sensor_fault
    assert b.current_fill_pct == 100.0
    assert packets[0].sensor_fault


def test_sensor_blockage_self_clears_after_2_ticks():
    """Fault with duration=2 clears after exactly 2 fault ticks."""
    b = make_bin(current_fill_pct=50.0)
    b.sensor_fault = True
    b._fault_ticks_remaining = 2

    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        p1 = b.tick(MONDAY_6AM)
    assert b.sensor_fault
    assert b._fault_ticks_remaining == 1
    assert p1[0].sensor_fault

    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        p2 = b.tick(MONDAY_6AM)
    assert not b.sensor_fault
    assert b._fault_ticks_remaining == 0


def test_single_fault_tick_does_not_clear_fault():
    """After 1 fault tick, fault still active."""
    b = make_bin()
    b.sensor_fault = True
    b._fault_ticks_remaining = 3
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.5):
        b.tick(MONDAY_6AM)
    assert b.sensor_fault


# ── tip-over ──────────────────────────────────────────────────────────────────

def test_tip_over_resets_fill_to_zero():
    b = make_bin(current_fill_pct=75.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):   # tip fires (< 0.005)
        b.tick(MONDAY_6AM)
    assert b.current_fill_pct == 0.0
    assert b.tipped


def test_tip_over_emits_tip_alert_event():
    b = make_bin(current_fill_pct=75.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):
        packets = b.tick(MONDAY_6AM)
    assert packets[0].event_type == "tip_alert"


def test_tip_over_clears_collection_flag():
    b = make_bin(current_fill_pct=90.0, marked_for_collection=True)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):
        b.tick(MONDAY_6AM)
    assert not b.marked_for_collection


def test_tip_over_returns_single_packet():
    """Tip-over is out-of-cycle — only 1 packet, no normal fill packet."""
    b = make_bin(current_fill_pct=40.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", return_value=0.001):
        packets = b.tick(MONDAY_6AM)
    assert len(packets) == 1


# ── emptying event ────────────────────────────────────────────────────────────

def test_emptying_resets_fill_to_zero():
    b = make_bin(current_fill_pct=90.0, marked_for_collection=True)
    packet = b.apply_emptying(MONDAY_6AM)
    assert b.current_fill_pct == 0.0


def test_emptying_emits_emptied_event():
    b = make_bin(current_fill_pct=90.0)
    packet = b.apply_emptying(MONDAY_6AM)
    assert packet.event_type == "emptied"


def test_emptying_clears_collection_flag():
    b = make_bin(current_fill_pct=90.0, marked_for_collection=True)
    b.apply_emptying(MONDAY_6AM)
    assert not b.marked_for_collection


def test_emptying_clears_tipped_flag():
    b = make_bin(current_fill_pct=90.0, tipped=True)
    b.apply_emptying(MONDAY_6AM)
    assert not b.tipped


# ── collection flag ───────────────────────────────────────────────────────────

def test_collection_flagged_when_fill_reaches_critical():
    b = make_bin(current_fill_pct=84.5, base_fill_rate=5.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=1.0):
        b.tick(MONDAY_6AM)
    # 84.5 + 5.0*2.0*1.0 + 1.0 = 95.5 → >= 85.0 → flagged
    assert b.marked_for_collection
