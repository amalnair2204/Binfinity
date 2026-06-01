# Phase 1 — Binfinity IoT Edge Emulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python async emulator of 200 smart bin IoT nodes streaming telemetry via SQLite, STDOUT, SSE, and a FastAPI REST server.

**Architecture:** `BinNode` dataclass models each bin's state machine (fill %, battery, fault flags). `SimEngine` owns 200 `BinNode` instances, runs an async tick loop every configurable N seconds (default 2s = 30 sim-minutes), and shares state with a FastAPI server in the same process via `asyncio.gather`. SSE uses per-client `asyncio.Queue` fan-out.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, asyncio, aiosqlite, Pydantic v2, loguru, pytest, pytest-asyncio, httpx, pytest-cov

---

## File Map

| File | Responsibility |
|------|---------------|
| `scripts/generate_bins.py` | One-time 200-bin registry generator |
| `config/bins.json` | Static bin registry (generated artifact) |
| `emulator/bin_model.py` | `BinNode` dataclass — all fill/event/battery logic, no I/O |
| `emulator/telemetry.py` | `TelemetryPacket` Pydantic model + `TelemetryDB` aiosqlite writer |
| `emulator/api.py` | FastAPI app — 6 endpoints, module-level engine reference |
| `emulator/sim_engine.py` | `SimEngine` — tick loop, SSE fan-out, snapshot writer, entry point |
| `tests/test_phase1/conftest.py` | Shared test fixtures |
| `tests/test_phase1/test_bin_model.py` | BinNode unit tests |
| `tests/test_phase1/test_telemetry.py` | TelemetryPacket + SQLite writer tests |
| `tests/test_phase1/test_api.py` | FastAPI endpoint tests |
| `tests/test_phase1/test_edge_cases.py` | Edge case integration tests |
| `pytest.ini` | asyncio_mode=auto |
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Environment variable template |
| `README.md` | Setup and run instructions |

---

## Domain Constants (from CLAUDE.md)

```python
FILL_THRESHOLD_CRITICAL    = 85.0   # % — triggers collection flag
FILL_THRESHOLD_WARNING     = 70.0   # % — overflow_warning event
BATTERY_CRITICAL_MV        = 3200   # mV — triggers power-save mode
WAKE_INTERVAL_MINUTES      = 30
WAKE_INTERVAL_LOW_BAT_MIN  = 60
```

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `emulator/__init__.py`
- Create: `scripts/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_phase1/__init__.py`
- Create: `data/.gitkeep`
- Create: `config/.gitkeep`

- [ ] **Step 1: Create directories**

```bash
mkdir -p emulator scripts tests/test_phase1 data config
```

- [ ] **Step 2: Create requirements.txt**

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0
pydantic-settings>=2.2.0
aiosqlite>=0.20.0
loguru>=0.7.2
pytest>=8.1.0
pytest-asyncio>=0.23.6
httpx>=0.27.0
pytest-cov>=5.0.0
```

- [ ] **Step 3: Create .env.example**

```
SIM_TICK_REAL_SECONDS=2.0
CITY_LAT=25.2048
CITY_LNG=55.2708
```

Copy to `.env`: `cp .env.example .env`

- [ ] **Step 4: Create pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: Create empty init files**

Create empty files: `emulator/__init__.py`, `scripts/__init__.py`, `tests/__init__.py`, `tests/test_phase1/__init__.py`, `data/.gitkeep`, `config/.gitkeep`

- [ ] **Step 6: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors, `fastapi`, `aiosqlite`, `loguru` all importable.

- [ ] **Step 7: Commit**

```bash
git init
git add .
git commit -m "feat: project scaffold — dirs, requirements, pytest config"
```

---

### Task 2: Bin Registry Generator

**Files:**
- Create: `scripts/generate_bins.py`
- Create: `config/bins.json` (generated)
- Create: `tests/test_phase1/test_bins.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_phase1/test_bins.py`:

```python
import json
import pytest
from pathlib import Path
from scripts.generate_bins import generate_bins

def test_generates_correct_count():
    bins = generate_bins(200)
    assert len(bins) == 200

def test_bin_ids_unique_and_formatted():
    bins = generate_bins(200)
    ids = [b["bin_id"] for b in bins]
    assert ids[0] == "BIN-0001"
    assert ids[199] == "BIN-0200"
    assert len(set(ids)) == 200

def test_all_required_fields_present():
    bins = generate_bins(5)
    required = {"bin_id", "lat", "lng", "zone", "base_fill_rate",
                "capacity_liters", "current_fill_pct", "battery_mv"}
    for b in bins:
        assert required.issubset(b.keys()), f"Missing fields: {required - b.keys()}"

def test_zones_are_valid():
    valid_zones = {"residential", "commercial", "park", "transit_hub"}
    bins = generate_bins(200)
    for b in bins:
        assert b["zone"] in valid_zones

def test_capacity_matches_zone():
    expected = {"residential": 120.0, "commercial": 240.0, "park": 80.0, "transit_hub": 120.0}
    bins = generate_bins(200)
    for b in bins:
        assert b["capacity_liters"] == expected[b["zone"]]

def test_initial_fill_within_range():
    bins = generate_bins(200)
    for b in bins:
        assert 0.0 <= b["current_fill_pct"] <= 60.0

def test_coordinates_within_dubai_spread():
    bins = generate_bins(200)
    for b in bins:
        assert 25.0 <= b["lat"] <= 25.5
        assert 55.0 <= b["lng"] <= 55.5

def test_deterministic_with_same_seed():
    bins_a = generate_bins(10, seed=42)
    bins_b = generate_bins(10, seed=42)
    assert bins_a == bins_b

def test_different_seeds_give_different_results():
    bins_a = generate_bins(10, seed=42)
    bins_b = generate_bins(10, seed=99)
    assert bins_a != bins_b
```

- [ ] **Step 2: Run test — verify failure**

```bash
pytest tests/test_phase1/test_bins.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.generate_bins'`

- [ ] **Step 3: Implement scripts/generate_bins.py**

```python
"""One-time 200-bin registry generator for the Binfinity emulator."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

CITY_LAT: float = float(os.getenv("CITY_LAT", "25.2048"))
CITY_LNG: float = float(os.getenv("CITY_LNG", "55.2708"))
SPREAD: float = 0.15

ZONES = ["residential", "commercial", "park", "transit_hub"]
ZONE_WEIGHTS = [0.40, 0.30, 0.20, 0.10]
CAPACITY_BY_ZONE: dict[str, float] = {
    "residential": 120.0,
    "commercial": 240.0,
    "park": 80.0,
    "transit_hub": 120.0,
}
FILL_RATE_RANGE: dict[str, tuple[float, float]] = {
    "residential": (1.0, 2.0),
    "commercial": (2.0, 4.0),
    "park": (0.5, 3.0),
    "transit_hub": (2.5, 5.0),
}


def generate_bins(count: int = 200, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    bins: list[dict] = []
    for i in range(1, count + 1):
        zone: str = rng.choices(ZONES, weights=ZONE_WEIGHTS)[0]
        low, high = FILL_RATE_RANGE[zone]
        bins.append(
            {
                "bin_id": f"BIN-{i:04d}",
                "lat": round(CITY_LAT + rng.uniform(-SPREAD, SPREAD), 6),
                "lng": round(CITY_LNG + rng.uniform(-SPREAD, SPREAD), 6),
                "zone": zone,
                "base_fill_rate": round(rng.uniform(low, high), 2),
                "capacity_liters": CAPACITY_BY_ZONE[zone],
                "current_fill_pct": round(rng.uniform(0.0, 60.0), 1),
                "battery_mv": rng.randint(3800, 4200),
            }
        )
    return bins


if __name__ == "__main__":
    Path("config").mkdir(exist_ok=True)
    bins = generate_bins()
    out = Path("config/bins.json")
    out.write_text(json.dumps(bins, indent=2))
    print(f"Generated {len(bins)} bins → {out}")
```

- [ ] **Step 4: Run test — verify pass**

```bash
pytest tests/test_phase1/test_bins.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Generate config/bins.json**

```bash
python scripts/generate_bins.py
```

Expected: `Generated 200 bins → config/bins.json`

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_bins.py config/bins.json tests/test_phase1/test_bins.py
git commit -m "feat: bin registry generator — 200 Dubai bins across 4 zone types"
```

---

### Task 3: BinNode — Fill Logic & Edge Cases

**Files:**
- Create: `emulator/bin_model.py`
- Create: `tests/test_phase1/test_bin_model.py`

- [ ] **Step 1: Write failing tests for core fill logic**

Create `tests/test_phase1/test_bin_model.py`:

```python
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
SATURDAY_NOON = datetime(2025, 1, 11, 12, 0, tzinfo=timezone.utc)  # weekend


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


def normal_tick_patches():
    """Patches that suppress all random events: tip=miss, fault=miss, spike=miss."""
    return (
        patch("random.randint", return_value=5),       # battery drain = 5mV
        patch("random.random", side_effect=[0.5, 0.5, 0.5]),  # tip/fault/spike all miss
        patch("random.gauss", return_value=0.0),        # no noise
    )


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


# ── collection flag ───────────────────────────────────────────────────────────

def test_collection_flagged_when_fill_reaches_critical():
    b = make_bin(current_fill_pct=84.5, base_fill_rate=5.0)
    with patch("random.randint", return_value=5), \
         patch("random.random", side_effect=[0.5, 0.5, 0.5]), \
         patch("random.gauss", return_value=1.0):
        b.tick(MONDAY_6AM)
    # 84.5 + 5.0*2.0*1.0 + 1.0 = 95.5 → >= 85.0 → flagged
    assert b.marked_for_collection
```

- [ ] **Step 2: Run test — verify failure**

```bash
pytest tests/test_phase1/test_bin_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'emulator.bin_model'`

- [ ] **Step 3: Implement emulator/bin_model.py**

```python
"""BinNode — stateful IoT bin simulator. Pure state machine, no I/O."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emulator.telemetry import TelemetryPacket

FILL_THRESHOLD_CRITICAL: float = 85.0
FILL_THRESHOLD_WARNING: float = 70.0
BATTERY_CRITICAL_MV: int = 3200
WAKE_INTERVAL_MINUTES: int = 30
WAKE_INTERVAL_LOW_BAT_MINUTES: int = 60


def _tod_multiplier(hour: float) -> float:
    """Time-of-day fill rate multiplier based on simulated hour."""
    if 6.0 <= hour < 9.0:
        return 2.0
    if 17.0 <= hour < 20.0:
        return 1.8
    if 0.0 <= hour < 5.0:
        return 0.3
    return 1.0


def _zone_multiplier(zone: str, hour: float, weekday: int) -> float:
    """Zone-specific fill rate multiplier. weekday: 0=Mon … 6=Sun."""
    is_weekend = weekday >= 5
    if zone == "park":
        return 2.5 if is_weekend else 0.8
    if zone == "transit_hub":
        return 2.0 if (7.0 <= hour < 9.0 or 17.0 <= hour < 19.0) else 1.0
    if zone == "commercial":
        return 1.2 if 9.0 <= hour < 18.0 else 1.0
    return 1.0


@dataclass
class BinNode:
    bin_id: str
    lat: float
    lng: float
    zone: str
    base_fill_rate: float
    capacity_liters: float
    current_fill_pct: float
    battery_mv: int = 4200
    marked_for_collection: bool = False
    sensor_fault: bool = False
    tipped: bool = False
    _fault_ticks_remaining: int = field(default=0, repr=False)

    @property
    def wake_interval_minutes(self) -> int:
        return (
            WAKE_INTERVAL_LOW_BAT_MINUTES
            if self.battery_mv < BATTERY_CRITICAL_MV
            else WAKE_INTERVAL_MINUTES
        )

    def tick(self, sim_dt: datetime) -> list[TelemetryPacket]:
        """
        Advance bin one 30-minute simulated tick.
        Returns list of TelemetryPacket — normally 1, immediately 1 on tip-over.
        """
        from emulator.telemetry import build_packet

        hour = sim_dt.hour + sim_dt.minute / 60.0
        weekday = sim_dt.weekday()

        # Battery drain (always, before any event rolls)
        self.battery_mv = max(0, self.battery_mv - random.randint(3, 7))

        # ── Tip-over event (0.5%) ─────────────────────────────────────────────
        if random.random() < 0.005:
            self.tipped = True
            self.current_fill_pct = 0.0
            self.marked_for_collection = False
            return [build_packet(self, sim_dt, "tip_alert")]

        # ── Sensor blockage (1%) — only tries if not already faulted ─────────
        if not self.sensor_fault and random.random() < 0.01:
            self._fault_ticks_remaining = random.randint(2, 4)
            self.sensor_fault = True

        if self.sensor_fault:
            self.current_fill_pct = 100.0
            packet = build_packet(self, sim_dt, "scheduled")
            self._fault_ticks_remaining -= 1
            if self._fault_ticks_remaining <= 0:
                self.sensor_fault = False
            return [packet]

        # ── Volatile spike (2%) ───────────────────────────────────────────────
        if random.random() < 0.02:
            spike = random.uniform(30.0, 70.0)
            self.current_fill_pct = min(100.0, self.current_fill_pct + spike)
            if self.current_fill_pct >= FILL_THRESHOLD_CRITICAL:
                self.marked_for_collection = True
            return [build_packet(self, sim_dt, "spike")]

        # ── Normal fill ───────────────────────────────────────────────────────
        delta = (
            self.base_fill_rate
            * _tod_multiplier(hour)
            * _zone_multiplier(self.zone, hour, weekday)
            + random.gauss(0.0, 1.5)
        )
        self.current_fill_pct = max(0.0, min(100.0, self.current_fill_pct + delta))

        if self.current_fill_pct >= FILL_THRESHOLD_CRITICAL:
            self.marked_for_collection = True

        event_type = "scheduled"
        if self.current_fill_pct >= FILL_THRESHOLD_WARNING:
            event_type = "overflow_warning"

        return [build_packet(self, sim_dt, event_type)]

    def apply_emptying(self, sim_dt: datetime) -> TelemetryPacket:
        """Simulate truck emptying this bin. Call when marked_for_collection and fill>=85."""
        from emulator.telemetry import build_packet

        self.current_fill_pct = 0.0
        self.marked_for_collection = False
        self.tipped = False
        return build_packet(self, sim_dt, "emptied")
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/test_phase1/test_bin_model.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add emulator/bin_model.py tests/test_phase1/test_bin_model.py
git commit -m "feat: BinNode state machine — fill logic, edge cases, battery drain"
```

---

### Task 4: TelemetryPacket Schema & SQLite Writer

**Files:**
- Create: `emulator/telemetry.py`
- Create: `tests/test_phase1/test_telemetry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_phase1/test_telemetry.py`:

```python
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
```

- [ ] **Step 2: Run test — verify failure**

```bash
pytest tests/test_phase1/test_telemetry.py -v
```

Expected: `ModuleNotFoundError: No module named 'emulator.telemetry'`

- [ ] **Step 3: Implement emulator/telemetry.py**

```python
"""TelemetryPacket schema and async SQLite writer."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

import aiosqlite
from pydantic import BaseModel

if TYPE_CHECKING:
    from emulator.bin_model import BinNode

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS telemetry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id       TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    fill_pct     REAL,
    fill_liters  REAL,
    tipped       INTEGER,
    sensor_fault INTEGER,
    battery_mv   INTEGER,
    rssi_dbm     INTEGER,
    temp_c       REAL,
    event_type   TEXT
)
"""

_INSERT = """
INSERT INTO telemetry
    (bin_id, timestamp, fill_pct, fill_liters, tipped, sensor_fault,
     battery_mv, rssi_dbm, temp_c, event_type)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_pct: float
    fill_liters: float
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int
    temp_c: float
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]


def build_packet(
    bin_node: BinNode,
    sim_dt: datetime,
    event_type: str,
) -> TelemetryPacket:
    """Build a validated TelemetryPacket from current BinNode state."""
    ts = sim_dt if sim_dt.tzinfo else sim_dt.replace(tzinfo=timezone.utc)
    return TelemetryPacket(
        bin_id=bin_node.bin_id,
        timestamp=ts,
        fill_pct=round(bin_node.current_fill_pct, 2),
        fill_liters=round(bin_node.current_fill_pct / 100.0 * bin_node.capacity_liters, 2),
        tipped=bin_node.tipped,
        sensor_fault=bin_node.sensor_fault,
        battery_mv=bin_node.battery_mv,
        rssi_dbm=random.randint(-100, -70),
        temp_c=round(random.uniform(20.0, 45.0), 1),
        event_type=event_type,  # type: ignore[arg-type]
    )


class TelemetryDB:
    """Async SQLite writer backed by a single persistent connection."""

    def __init__(self, db_path: str = "data/telemetry.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert(self, packet: TelemetryPacket) -> None:
        assert self._db is not None, "Call connect() first"
        await self._db.execute(
            _INSERT,
            (
                packet.bin_id,
                packet.timestamp.isoformat(),
                packet.fill_pct,
                packet.fill_liters,
                int(packet.tipped),
                int(packet.sensor_fault),
                packet.battery_mv,
                packet.rssi_dbm,
                packet.temp_c,
                packet.event_type,
            ),
        )
        await self._db.commit()

    async def count(self) -> int:
        assert self._db is not None
        async with self._db.execute("SELECT COUNT(*) FROM telemetry") as cur:
            row = await cur.fetchone()
            return row[0]

    async def fetch_all(self) -> list[dict]:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM telemetry ORDER BY id") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/test_phase1/test_telemetry.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add emulator/telemetry.py tests/test_phase1/test_telemetry.py
git commit -m "feat: TelemetryPacket Pydantic schema and aiosqlite writer"
```

---

### Task 5: FastAPI Server

**Files:**
- Create: `emulator/api.py`
- Create: `tests/test_phase1/test_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_phase1/test_api.py`:

```python
"""FastAPI endpoint tests using TestClient with a mock SimEngine."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from emulator.api import app, set_engine
from emulator.bin_model import BinNode


def _make_fleet(n: int = 200, *, bins_over_80: int = 10, faulted: int = 5) -> dict[str, BinNode]:
    """Build a known-state fleet for predictable stats assertions."""
    fleet: dict[str, BinNode] = {}
    for i in range(1, n + 1):
        fill = 90.0 if i <= bins_over_80 else 50.0
        b = BinNode(
            bin_id=f"BIN-{i:04d}",
            lat=25.2048, lng=55.2708,
            zone="residential",
            base_fill_rate=2.0,
            capacity_liters=120.0,
            current_fill_pct=fill,
            battery_mv=4000,
        )
        if bins_over_80 < i <= bins_over_80 + faulted:
            b.sensor_fault = True
        fleet[b.bin_id] = b
    return fleet


@pytest.fixture(autouse=True)
def engine():
    mock = MagicMock()
    mock.bins = _make_fleet()
    mock.tick_interval = 2.0
    mock.sse_subscribers = set()
    set_engine(mock)
    yield mock
    set_engine(None)


client = TestClient(app)


# ── GET /bins ─────────────────────────────────────────────────────────────────

def test_list_bins_returns_200_items():
    r = client.get("/bins")
    assert r.status_code == 200
    assert len(r.json()) == 200


def test_list_bins_contain_bin_id():
    r = client.get("/bins")
    ids = {b["bin_id"] for b in r.json()}
    assert "BIN-0001" in ids
    assert "BIN-0200" in ids


# ── GET /bins/{bin_id} ────────────────────────────────────────────────────────

def test_get_bin_returns_correct_state():
    r = client.get("/bins/BIN-0001")
    assert r.status_code == 200
    assert r.json()["bin_id"] == "BIN-0001"


def test_get_bin_fill_pct_in_response():
    r = client.get("/bins/BIN-0001")
    assert "current_fill_pct" in r.json()


def test_get_bin_invalid_id_returns_404():
    r = client.get("/bins/BIN-9999")
    assert r.status_code == 404


# ── POST /bins/{bin_id}/collect ───────────────────────────────────────────────

def test_collect_marks_bin_for_collection(engine):
    r = client.post("/bins/BIN-0001/collect")
    assert r.status_code == 200
    assert engine.bins["BIN-0001"].marked_for_collection


def test_collect_invalid_id_returns_404():
    r = client.post("/bins/BIN-9999/collect")
    assert r.status_code == 404


# ── GET /stats ────────────────────────────────────────────────────────────────

def test_stats_returns_required_fields():
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert {"total_bins", "avg_fill_pct", "bins_over_80", "faulted_count"}.issubset(data)


def test_stats_total_bins_is_200():
    r = client.get("/stats")
    assert r.json()["total_bins"] == 200


def test_stats_bins_over_80_correct():
    r = client.get("/stats")
    # Fleet has 10 bins at 90%, rest at 50%
    assert r.json()["bins_over_80"] == 10


def test_stats_faulted_count_correct():
    r = client.get("/stats")
    assert r.json()["faulted_count"] == 5


# ── POST /sim/speed ───────────────────────────────────────────────────────────

def test_sim_speed_updates_tick_interval(engine):
    r = client.post("/sim/speed", json={"ticks_per_second": 5.0})
    assert r.status_code == 200
    assert abs(engine.tick_interval - 0.2) < 0.001


def test_sim_speed_zero_does_not_crash():
    # ticks_per_second=0 would divide by zero — server should handle gracefully
    r = client.post("/sim/speed", json={"ticks_per_second": 0.1})
    assert r.status_code == 200


# ── invalid bin_id on all endpoints ──────────────────────────────────────────

def test_any_endpoint_invalid_bin_id_returns_404():
    assert client.get("/bins/INVALID").status_code == 404
    assert client.post("/bins/INVALID/collect").status_code == 404
```

- [ ] **Step 2: Run test — verify failure**

```bash
pytest tests/test_phase1/test_api.py -v
```

Expected: `ModuleNotFoundError: No module named 'emulator.api'`

- [ ] **Step 3: Implement emulator/api.py**

```python
"""FastAPI server for the Binfinity emulator. Engine injected by sim_engine at startup."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

app = FastAPI(title="Binfinity Emulator API", version="1.0.0")

_engine: Any = None   # Set by sim_engine.set_engine()


def set_engine(engine: Any) -> None:
    global _engine
    _engine = engine


def _require_engine():
    if _engine is None:
        raise RuntimeError("Engine not initialised — call set_engine() first")
    return _engine


def _bin_to_dict(b) -> dict:
    return {
        "bin_id": b.bin_id,
        "lat": b.lat,
        "lng": b.lng,
        "zone": b.zone,
        "capacity_liters": b.capacity_liters,
        "current_fill_pct": round(b.current_fill_pct, 2),
        "fill_liters": round(b.current_fill_pct / 100.0 * b.capacity_liters, 2),
        "sensor_fault": b.sensor_fault,
        "tipped": b.tipped,
        "battery_mv": b.battery_mv,
        "marked_for_collection": b.marked_for_collection,
        "wake_interval_minutes": b.wake_interval_minutes,
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/bins")
async def list_bins() -> list[dict]:
    engine = _require_engine()
    return [_bin_to_dict(b) for b in engine.bins.values()]


@app.get("/bins/{bin_id}")
async def get_bin(bin_id: str) -> dict:
    engine = _require_engine()
    if bin_id not in engine.bins:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    return _bin_to_dict(engine.bins[bin_id])


@app.get("/telemetry/stream")
async def telemetry_stream():
    import asyncio
    engine = _require_engine()
    queue: asyncio.Queue = asyncio.Queue()
    engine.sse_subscribers.add(queue)

    async def _generate():
        try:
            while True:
                packet = await queue.get()
                yield f"data: {packet.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            engine.sse_subscribers.discard(queue)

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/bins/{bin_id}/collect")
async def collect_bin(bin_id: str) -> dict:
    engine = _require_engine()
    if bin_id not in engine.bins:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    engine.bins[bin_id].marked_for_collection = True
    logger.info(f"Bin {bin_id} marked for collection")
    return {"status": "marked_for_collection", "bin_id": bin_id}


@app.get("/stats")
async def stats() -> dict:
    engine = _require_engine()
    bins = list(engine.bins.values())
    total = len(bins)
    return {
        "total_bins": total,
        "avg_fill_pct": round(sum(b.current_fill_pct for b in bins) / total, 2),
        "bins_over_80": sum(1 for b in bins if b.current_fill_pct > 80.0),
        "faulted_count": sum(1 for b in bins if b.sensor_fault),
    }


class _SpeedBody(BaseModel):
    ticks_per_second: float = 1.0


@app.post("/sim/speed")
async def set_speed(body: _SpeedBody) -> dict:
    engine = _require_engine()
    tps = max(0.01, body.ticks_per_second)   # floor at 0.01 to avoid /0
    engine.tick_interval = 1.0 / tps
    logger.info(f"Sim speed set to {tps} tps (interval={engine.tick_interval:.3f}s)")
    return {"ticks_per_second": tps, "tick_interval_seconds": engine.tick_interval}
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/test_phase1/test_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add emulator/api.py tests/test_phase1/test_api.py
git commit -m "feat: FastAPI server — 6 endpoints, engine injection, SSE fan-out"
```

---

### Task 6: SimEngine & Entry Point

**Files:**
- Create: `emulator/sim_engine.py`

No unit tests for SimEngine (async I/O orchestrator — covered by integration via the API and edge case tests). Verify manually after implementation.

- [ ] **Step 1: Implement emulator/sim_engine.py**

```python
"""
Simulation engine — owns 200 BinNode instances, runs async tick loop,
streams telemetry via SQLite + STDOUT + SSE, writes bin_states.json snapshot.

Start with: python -m emulator.sim_engine
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from loguru import logger

from emulator.api import app, set_engine
from emulator.bin_model import BinNode
from emulator.telemetry import TelemetryDB, TelemetryPacket


class SimEngine:
    def __init__(
        self,
        config_path: str = "config/bins.json",
        db_path: str = "data/telemetry.db",
    ) -> None:
        self.bins: dict[str, BinNode] = {}
        self.sse_subscribers: set[asyncio.Queue] = set()
        self.tick_interval: float = float(os.getenv("SIM_TICK_REAL_SECONDS", "2.0"))
        # Simulation starts on a Monday at 06:00 UTC (morning peak)
        self.sim_time: datetime = datetime(2025, 1, 6, 6, 0, 0, tzinfo=timezone.utc)
        self._db = TelemetryDB(db_path)
        self._load_bins(config_path)

    def _load_bins(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        for b in data:
            self.bins[b["bin_id"]] = BinNode(**b)
        logger.info(f"Loaded {len(self.bins)} bins from {path}")

    async def run(self) -> None:
        await self._db.connect()
        logger.info("Simulation started")
        while True:
            await self._tick()
            await asyncio.sleep(self.tick_interval)

    async def _tick(self) -> None:
        tasks = [
            asyncio.create_task(self._process_bin(bin_node))
            for bin_node in self.bins.values()
        ]
        all_packets: list[TelemetryPacket] = []
        for result in await asyncio.gather(*tasks):
            all_packets.extend(result)

        # Persist + stream
        for packet in all_packets:
            await self._db.insert(packet)
            print(packet.model_dump_json(), flush=True)   # STDOUT newline-delimited JSON

        # SSE fan-out
        dead: set[asyncio.Queue] = set()
        for queue in list(self.sse_subscribers):
            for packet in all_packets:
                try:
                    queue.put_nowait(packet)
                except asyncio.QueueFull:
                    dead.add(queue)
        self.sse_subscribers -= dead

        await self._write_snapshot()
        self.sim_time += timedelta(minutes=30)
        logger.debug(f"Tick complete — {len(all_packets)} packets — sim_time={self.sim_time}")

    async def _process_bin(self, bin_node: BinNode) -> list[TelemetryPacket]:
        """Tick a bin and trigger emptying if truck-ready."""
        packets = bin_node.tick(self.sim_time)
        if bin_node.marked_for_collection and bin_node.current_fill_pct >= 85.0:
            emptied = bin_node.apply_emptying(self.sim_time)
            packets.append(emptied)
        return packets

    async def _write_snapshot(self) -> None:
        snapshot = {
            bid: {
                "bin_id": b.bin_id,
                "lat": b.lat,
                "lng": b.lng,
                "zone": b.zone,
                "capacity_liters": b.capacity_liters,
                "current_fill_pct": round(b.current_fill_pct, 2),
                "fill_liters": round(b.current_fill_pct / 100.0 * b.capacity_liters, 2),
                "sensor_fault": b.sensor_fault,
                "tipped": b.tipped,
                "battery_mv": b.battery_mv,
                "marked_for_collection": b.marked_for_collection,
                "sim_time": self.sim_time.isoformat(),
            }
            for bid, b in self.bins.items()
        }
        tmp = Path("data/bin_states.json.tmp")
        final = Path("data/bin_states.json")
        tmp.write_text(json.dumps(snapshot))
        tmp.rename(final)


async def _main() -> None:
    engine = SimEngine()
    set_engine(engine)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await asyncio.gather(engine.run(), server.serve())


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 2: Smoke-test the engine**

```bash
python -m emulator.sim_engine
```

Expected output (first few lines):
```
{"bin_id":"BIN-0001","timestamp":"2025-01-06T06:00:00+00:00",...}
{"bin_id":"BIN-0002",...}
```

API should respond at `http://localhost:8000/bins` and `http://localhost:8000/stats`.

Stop with `Ctrl+C`.

- [ ] **Step 3: Commit**

```bash
git add emulator/sim_engine.py
git commit -m "feat: SimEngine async tick loop — SQLite, STDOUT, SSE fan-out, bin_states.json"
```

---

### Task 7: Edge Case Integration Tests

**Files:**
- Create: `tests/test_phase1/test_edge_cases.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_phase1/test_edge_cases.py`:

```python
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
        tmp.rename(final)

    loaded = json.loads(final.read_text())
    assert loaded[b.bin_id]["current_fill_pct"] == 75.0
```

- [ ] **Step 2: Run tests — verify pass**

```bash
pytest tests/test_phase1/test_edge_cases.py -v
```

Expected: all tests PASS (no new implementation needed — tests validate existing bin_model.py).

- [ ] **Step 3: Commit**

```bash
git add tests/test_phase1/test_edge_cases.py
git commit -m "test: edge case integration tests — spike, blockage, tip-over, snapshot"
```

---

### Task 8: Full Coverage Check & README

**Files:**
- Create: `README.md`
- Modify: none

- [ ] **Step 1: Run full test suite with coverage**

```bash
pytest tests/test_phase1/ --cov=emulator --cov-report=term-missing -v
```

Expected: ≥ 80% coverage on `emulator/`. All tests PASS.

If coverage is below 80%, identify uncovered lines in the report and add targeted tests.

- [ ] **Step 2: Create README.md**

```markdown
# Binfinity — Phase 1: IoT Edge Emulator

Simulates a fleet of 200 smart bin sensor nodes across Dubai.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/generate_bins.py    # generates config/bins.json
```

## Run

```bash
python -m emulator.sim_engine
```

Emulator starts at `http://localhost:8000`. Telemetry streams to:
- **STDOUT** — newline-delimited JSON packets
- **SQLite** — `data/telemetry.db`
- **SSE** — `GET /telemetry/stream`
- **Snapshot** — `data/bin_states.json` (updated every tick)

## API

| Endpoint | Description |
|----------|-------------|
| `GET /bins` | All 200 bins current state |
| `GET /bins/{bin_id}` | Single bin state |
| `GET /telemetry/stream` | Live SSE telemetry stream |
| `POST /bins/{bin_id}/collect` | Mark bin for collection |
| `GET /stats` | Fleet summary |
| `POST /sim/speed` | `{"ticks_per_second": N}` — adjust sim speed |

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `SIM_TICK_REAL_SECONDS` | `2.0` | Real seconds per 30-min sim tick |
| `CITY_LAT` | `25.2048` | City center latitude |
| `CITY_LNG` | `55.2708` | City center longitude |

## Tests

```bash
pytest tests/test_phase1/ --cov=emulator --cov-report=term-missing
```
```

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: Phase 1 README with setup, run, API, and config instructions"
```

---

## Self-Review

**Spec coverage:**
- ✅ 200-bin registry with zones, GPS, fill rates, capacities
- ✅ TelemetryPacket schema with all required fields + `spike` event_type
- ✅ Async tick loop with tod/zone multipliers + Gaussian noise
- ✅ All 5 edge cases: spike, blockage, tip-over, battery drain, emptying
- ✅ STDOUT JSON stream
- ✅ SQLite telemetry logging
- ✅ `bin_states.json` atomic snapshot
- ✅ All 6 FastAPI endpoints
- ✅ All 4 test files with required test cases
- ✅ `python -m emulator.sim_engine` entry point

**Known limitation:** Emptying via `POST /collect` sets `marked_for_collection=True` immediately, but the bin only actually empties on the next `_tick()` when the sim loop calls `_process_bin()`. This is by design — the API marks intent, the sim loop executes.
