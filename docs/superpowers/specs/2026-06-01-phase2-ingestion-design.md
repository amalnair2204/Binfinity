# Phase 2 Design — Binfinity Cloud Ingestion Pipeline & State Engine

**Date:** 2026-06-01  
**Status:** Approved  
**Module:** `ingestion/`  
**Depends on:** Phase 1 emulator running at `EMULATOR_URL` (default `http://localhost:8000`)

---

## Overview

Persistent async worker that consumes Phase 1's SSE telemetry stream, validates packets, runs state machine logic, writes to TimescaleDB (time-series store) and Redis (fast state cache), and exposes a REST API for downstream phases.

---

## Architecture

```
binfinity/
├── ingestion/
│   ├── schemas.py         # Pydantic v2: TelemetryPacket, BinState
│   ├── db.py              # asyncpg pool, hypertable inserts, batched writes, upserts
│   ├── cache.py           # redis.asyncio: state mirror + sorted sets
│   ├── state_machine.py   # 6 rules, status priority chain, pure function
│   ├── worker.py          # SSE consumer, exponential backoff, batch queue, main entry
│   └── api.py             # FastAPI 8 endpoints, reads from Redis (not DB)
├── infra/
│   └── docker-compose.yml # TimescaleDB + Redis services
└── tests/test_phase2/
    ├── test_schemas.py
    ├── test_state_machine.py
    ├── test_db.py
    ├── test_cache.py
    └── test_api.py
```

---

## Components

### Schemas (`ingestion/schemas.py`)

```python
class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    fill_liters: float
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int
    temp_c: float
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]

class BinState(BaseModel):
    bin_id: str
    last_updated: datetime
    fill_pct: float
    fill_liters: float
    status: Literal["operational", "tipped", "sensor_fault", "low_battery",
                    "overflow_risk", "pending_collection", "emptied"]
    battery_mv: int
    consecutive_fault_ticks: int
    flagged_for_collection: bool
    last_emptied: Optional[datetime]
```

### Database (`ingestion/db.py`)

asyncpg connection pool: min=5, max=20.

Tables:
- `telemetry` — hypertable partitioned by `time`; bulk-inserted in batches
- `bin_states` — one row per bin; upserted immediately on every packet
- `spill_incidents` — one row per tip-over event

`create_hypertable` wrapped in try/except — falls back gracefully on plain PostgreSQL (for test environments without TimescaleDB extension).

Write strategy:
- `telemetry`: batched — packets queued in `asyncio.Queue`, flusher task drains every 5s and bulk-inserts in single transaction
- `bin_states`: immediate upsert — `INSERT ... ON CONFLICT (bin_id) DO UPDATE SET ...`
- `spill_incidents`: immediate insert on tip-over

**Known limitation:** buffered telemetry packets lost on process crash (acceptable — emulator regenerates data).

### Redis Cache (`ingestion/cache.py`)

redis.asyncio client. No TTL on state keys.

Keys:
- `bin:{bin_id}:state` — JSON-serialized `BinState`
- `bins:by_fill` — sorted set; score=`fill_pct`, member=`bin_id`
- `bins:flagged` — set of `bin_id` values with `flagged_for_collection=True`
- `bins:faulted` — set of `bin_id` values with `status=sensor_fault`

All four updated atomically (pipeline) after every `bin_states` upsert.

### State Machine (`ingestion/state_machine.py`)

Pure function: `transition(current: BinState, packet: TelemetryPacket) -> BinState`

No I/O. Fully testable in isolation.

**6 Rules applied in order:**

**Rule 1 — Sensor Blockage:**
```
if fill_pct == 100.0:
    consecutive_fault_ticks += 1
if consecutive_fault_ticks >= 2:
    status = "sensor_fault"
else if fill_pct < 100.0 and consecutive_fault_ticks > 0:
    consecutive_fault_ticks = 0
    clear sensor_fault status
```
Faulted bins excluded from collection flagging.

**Rule 2 — Volatile Spike:**
```
if fill_delta > 40.0 and not sensor_fault:
    log event_type=spike (valid reading, no fault)
```

**Rule 3 — Collection Flagging:**
```
if fill_pct >= 85.0 and not sensor_fault and not tipped:
    flagged_for_collection = True
if event_type == "emptied":
    flagged_for_collection = False
    fill_pct = 0.0
    last_emptied = packet.timestamp
```

**Rule 4 — Tip-Over:**
```
if tipped:
    status = "tipped"
    fill_pct = 0.0
    flagged_for_collection = False
    → insert spill_incident row
```

**Rule 5 — Low Battery:**
```
if battery_mv < 3200 and status not in ["sensor_fault", "tipped"]:
    status = "low_battery"
```

**Rule 6 — Overflow Risk:**
```
if 70.0 <= fill_pct < 85.0 and status == "operational":
    status = "overflow_risk"
```

**Status Priority (highest wins):**
`sensor_fault` > `tipped` > `low_battery` > `pending_collection` > `overflow_risk` > `operational`

`pending_collection` corresponds to `flagged_for_collection=True` + fill >= 85%.

### Worker (`ingestion/worker.py`)

Entry point: `python -m ingestion.worker`. Runs `asyncio.gather(run_worker(), start_api(), run_batch_flusher())`.

SSE consumer:
- `httpx.AsyncClient` with `stream()` for SSE
- Parse `data:` lines, validate via `TelemetryPacket`
- Invalid packets: log warning + increment error counter, do not crash
- Auto-reconnect on disconnect: exponential backoff starting 1s, max 30s

Per packet pipeline:
```
parse + validate → state_machine.transition() → db.upsert_bin_state() → cache.update() → batch_queue.put()
```

Batch flusher: separate `asyncio.Task`; sleeps 5s, drains queue, bulk-inserts to `telemetry`.

### FastAPI (`ingestion/api.py`)

All read endpoints pull from Redis — not TimescaleDB — for low latency.
Only `/bins/{bin_id}/history` hits TimescaleDB.

| Method | Endpoint | Source | Notes |
|--------|----------|--------|-------|
| GET | `/health` | live checks | worker status, DB ping, Redis ping, packets_processed |
| GET | `/bins` | Redis | all 200 BinState objects |
| GET | `/bins/{bin_id}` | Redis | 404 on unknown |
| GET | `/bins/{bin_id}/history?limit=100` | TimescaleDB | last N rows ordered by time desc |
| GET | `/fleet/stats` | Redis | counts per status category |
| GET | `/fleet/flagged` | Redis `bins:flagged` | sorted by fill_pct desc |
| GET | `/fleet/critical` | Redis | fill >= 85% OR status=tipped |
| POST | `/bins/{bin_id}/acknowledge` | Redis + DB | clears tipped/sensor_fault; updates both stores |

---

## Docker Compose (`infra/docker-compose.yml`)

```yaml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    environment:
      POSTGRES_PASSWORD: binfinity
      POSTGRES_DB: binfinity
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

---

## Environment Variables

```
DATABASE_URL=postgresql://postgres:binfinity@localhost:5432/binfinity
REDIS_URL=redis://localhost:6379
EMULATOR_URL=http://localhost:8000
BATCH_FLUSH_SECONDS=5
```

---

## Testing Strategy

5 test files, target ≥80% coverage.

- `test_schemas.py` — pure Pydantic validation; no I/O
- `test_state_machine.py` — pure unit tests on `transition()`; all 6 rules + priority chain
- `test_db.py` — asyncpg against real PostgreSQL test DB (transactions rollback after each test); `create_hypertable` in try/except for plain PG compat
- `test_cache.py` — `fakeredis` for all assertions
- `test_api.py` — `TestClient` with `fakeredis` injected; DB mocked via fixtures

Run: `pytest tests/test_phase2/ --cov=ingestion --cov-report=term-missing`

---

## Startup Order

1. `docker-compose up` (TimescaleDB + Redis)
2. `python -m emulator.sim_engine` (Phase 1)
3. `python -m ingestion.worker` (Phase 2)

Phase 2 worker will retry SSE connection with backoff if Phase 1 not yet ready.

---

## Known Limitations

- No durability for buffered telemetry batch (5s window); process crash = packet loss
- Worker does not backfill missed packets after reconnect (gap in telemetry is acceptable for emulator)
- `POST /bins/{bin_id}/acknowledge` ops override is not propagated back to Phase 1 emulator state
