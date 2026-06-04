<<<<<<< HEAD
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

---

## Phase 2: Cloud Ingestion Pipeline

### Prerequisites

```bash
docker-compose -f infra/docker-compose.yml up -d   # TimescaleDB + Redis
python -m emulator.sim_engine                       # Phase 1 must be running first
```

### Run

```bash
python -m ingestion.worker
```

Ingestion API available at `http://localhost:8001`.

### API

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Worker + DB + Redis status |
| `GET /bins` | All bins current BinState |
| `GET /bins/{bin_id}` | Single bin state |
| `GET /bins/{bin_id}/history?limit=N` | Last N telemetry rows |
| `GET /fleet/stats` | Counts per status category |
| `GET /fleet/flagged` | Bins flagged for collection (fill desc) |
| `GET /fleet/critical` | Bins fill ≥ 85% or tipped |
| `POST /bins/{bin_id}/acknowledge` | Ops override — clear fault/tip |

### Phase 2 Tests

```bash
pytest tests/test_phase2/ --cov=ingestion --cov-report=term-missing
```

> `test_db.py` requires a live PostgreSQL instance (`DATABASE_URL` in `.env`).
=======
# Binfinity
>>>>>>> 5f3bd49265bf6111dfd31116e5dbb7936a5ea09f
