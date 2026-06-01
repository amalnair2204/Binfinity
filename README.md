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
