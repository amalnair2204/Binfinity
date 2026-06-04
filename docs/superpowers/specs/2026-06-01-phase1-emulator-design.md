# Phase 1 Design — Binfinity IoT Edge Emulator

**Date:** 2026-06-01  
**Status:** Approved  
**Module:** `emulator/`

---

## Overview

Python-based simulator acting as stand-in for a deployed fleet of 200 smart bin sensor nodes. Streams telemetry via STDOUT, SQLite, SSE, and a REST API. Feeds all downstream phases.

---

## Architecture

```
binfinity/
├── config/bins.json              # 200-bin registry (generated once by scripts/generate_bins.py)
├── emulator/
│   ├── bin_model.py              # BinNode — all fill/event/battery logic, pure state machine
│   ├── sim_engine.py             # Async tick loop + SSE fan-out + entry point
│   ├── telemetry.py              # TelemetryPacket (Pydantic) + aiosqlite writer
│   └── api.py                    # FastAPI server (6 endpoints)
├── data/
│   ├── telemetry.db              # SQLite telemetry store
│   └── bin_states.json           # Live state snapshot (atomic write)
├── scripts/generate_bins.py      # One-time bin registry generator
├── tests/test_phase1/
│   ├── test_bin_model.py
│   ├── test_telemetry.py
│   ├── test_api.py
│   └── test_edge_cases.py
└── .env                          # SIM_TICK_REAL_SECONDS, CITY_LAT, CITY_LNG
```

---

## Components

### BinNode (`emulator/bin_model.py`)
Pure state machine — no I/O. All fill/event logic. Deterministic given a seed (for testing).

State fields:
- `bin_id`, `lat`, `lng`, `zone`, `base_fill_rate`, `capacity_liters`
- `current_fill_pct: float` — clamped [0.0, 100.0]
- `battery_mv: int` — decrements each tick
- `marked_for_collection: bool`
- `_fault_ticks_remaining: int` — internal counter for sensor blockage duration
- `sensor_fault: bool`, `tipped: bool`
- `wake_interval_minutes: int` — 30 normal, 60 when battery < 3200mV

Key methods:
- `tick(simulated_hour: float) -> list[TelemetryPacket]` — returns 1 packet normally, 2 if tip-over fires
- `apply_emptying() -> TelemetryPacket` — triggered by POST /collect when fill >= 85%

### SimEngine (`emulator/sim_engine.py`)
Owns `dict[str, BinNode]`. Runs async tick loop. Entry point via `python -m emulator.sim_engine`.

- `asyncio.gather(run_sim(), start_api())` — sim + FastAPI in same process
- Maintains `_sse_subscribers: set[asyncio.Queue]` — fan-out to all SSE clients
- Writes `data/bin_states.json` atomically (write to `.tmp`, rename) after every tick
- Configurable tick speed via `SIM_TICK_REAL_SECONDS` env var (default: 2.0)

### TelemetryPacket (`emulator/telemetry.py`)
Pydantic model. Validated schema. Written to SQLite via `aiosqlite`.

```python
class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime          # UTC ISO 8601
    fill_pct: float              # [0.0, 100.0]
    fill_liters: float           # fill_pct/100 * capacity_liters
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int                # random [-100, -70]
    temp_c: float                # random [20.0, 45.0] Dubai range
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]
```

SQLite schema — `telemetry` table with all fields + auto-increment `rowid`.

### FastAPI (`emulator/api.py`)

| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/bins` | List all 200 bins current state |
| GET | `/bins/{bin_id}` | Single bin; 404 on unknown id |
| GET | `/telemetry/stream` | SSE `text/event-stream`; per-client asyncio.Queue |
| POST | `/bins/{bin_id}/collect` | Sets `marked_for_collection=True`; sim detects ≥85% and empties |
| GET | `/stats` | `{avg_fill_pct, bins_over_80, faulted_count, total_bins}` |
| POST | `/sim/speed` | `{"ticks_per_second": float}` — updates sleep duration live |

SSE: per-client `asyncio.Queue` in subscriber set. Engine pushes to all. Client disconnect → queue removed.

---

## Bin Registry

**Generated once** by `scripts/generate_bins.py`. Saved to `config/bins.json`.

- 200 bins, IDs `BIN-0001` to `BIN-0200`
- GPS: Dubai center `(25.2048, 55.2708)` ± 0.15° spread (configurable via `CITY_LAT`, `CITY_LNG`)
- Zones: `residential` (40%), `commercial` (30%), `park` (20%), `transit_hub` (10%)
- Capacity by zone: residential=120L, commercial=240L, park=80L, transit_hub=120L
- `base_fill_rate` by zone (% per 30-min tick):
  - residential: 1.0–2.0%
  - commercial: 2.0–4.0%
  - park: 0.5–3.0% (spikes weekends)
  - transit_hub: 2.5–5.0% (spikes rush hours)
- Initial `current_fill_pct`: random [0, 60]

---

## Fill Rate Logic

Per tick:
```
fill_delta = base_fill_rate × tod_multiplier × zone_multiplier + gaussian_noise(σ=1.5%)
new_fill = clamp(current_fill + fill_delta, 0.0, 100.0)
```

**Time-of-day multipliers** (simulated_hour):
- 06:00–09:00 (morning peak): 2.0×
- 17:00–20:00 (evening peak): 1.8×
- 00:00–05:00 (night): 0.3×
- otherwise: 1.0×

**Zone multipliers** (day-of-week aware):
- park weekend: 2.5×; park weekday: 0.8×
- transit_hub 07:00–09:00 or 17:00–19:00: 2.0×
- commercial daytime: 1.2×
- others: 1.0×

---

## Edge Cases

All 5 implemented. Rolled per tick via `random.random()`.

| Edge Case | Prob | Behavior | event_type | sensor_fault |
|-----------|------|----------|------------|--------------|
| Volatile spike | 2% | fill += rand(30,70)%, clamped | `spike` | false |
| Sensor blockage | 1% | stuck at 100.0% for 2–4 ticks, then self-clears | `scheduled` | **true** |
| Tip-over | 0.5% | fill=0, immediate out-of-cycle packet | `tip_alert` | false |
| Battery drain | always | mv decrements ~5mV/tick; <3200mV → wake_interval=60min | — | — |
| Emptying | on API call + ≥85% | fill=0, `emptied` packet | `emptied` | false |

Sensor blockage: `_fault_ticks_remaining` set to random int [2,4] when triggered. Each tick while >0: report 100.0%, sensor_fault=True, decrement. When reaches 0: self-clear.

Volatile spike does NOT set sensor_fault. CLAUDE.md: spikes are valid real-world readings.

---

## Domain Constants (from CLAUDE.md)

```python
FILL_THRESHOLD_CRITICAL = 85.0
FILL_THRESHOLD_WARNING   = 70.0
SENSOR_FAULT_THRESHOLD   = 100.0
WAKE_INTERVAL_MINUTES    = 30
WAKE_INTERVAL_LOW_BAT_MINUTES = 60
BATTERY_CRITICAL_MV      = 3200
```

---

## Testing Strategy

4 test files, target ≥80% coverage. All edge cases have dedicated test functions.

- `test_bin_model.py` — pure unit tests on `BinNode`; seed random for determinism
- `test_telemetry.py` — Pydantic validation + aiosqlite writes (in-memory SQLite)
- `test_api.py` — `httpx` + `TestClient`; 200-bin fleet pre-loaded in fixture
- `test_edge_cases.py` — deterministic edge case triggers via monkeypatched `random`

Run: `pytest tests/test_phase1/ --cov=emulator --cov-report=term-missing`

---

## Known Limitations

- SQLite not suitable for multi-process access; single-writer only (sim engine owns it)
- `bin_states.json` atomic write via rename — safe on same filesystem, not across network mounts
- Battery does not recharge; bins eventually enter power-save permanently (by design for simulation)

---

## Start Command

```bash
python -m emulator.sim_engine
```

Requires `.env` with `SIM_TICK_REAL_SECONDS` (default 2.0), `CITY_LAT` (default 25.2048), `CITY_LNG` (default 55.2708).
