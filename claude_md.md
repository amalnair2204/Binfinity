# CLAUDE.md — Binfinity Project

## Project Identity
**Binfinity** is an end-to-end, IoT-enabled, AI-driven Smart Waste Management and Dynamic Logistics Fleet Optimization Ecosystem. It transitions municipal waste collection from fixed-schedule routing to real-time, demand-driven, predictive routing using IoT telemetry and ML-based forecasting.

---

## Operational Directives

- **Always read this file (`CLAUDE.md`) at the start of every session before touching any code.** Scan the phase registry to understand current state, then read the relevant module directory.
- Work **fully autonomously**. Do not ask for confirmation mid-task. Only report at task completion.
- When resuming a session, **scan the current file tree and read key files** to understand state before making any changes. Never assume previous state.
- Prefer **extending existing modules** over creating new files unless a new module is architecturally justified.
- All code must be **production-quality**: typed, documented, with error handling and logging.
- Never leave placeholder comments like `# TODO` or `# implement later` in delivered code. Implement it or raise a specific blocker note in the completion report.

---

## Architecture Overview

```
binfinity/
├── config/             # Static configuration (bin registry, zone rules, thresholds)
├── emulator/           # Phase 1 — IoT edge simulation layer
├── ingestion/          # Phase 2 — Cloud data pipeline & state machine
├── geospatial/         # Phase 3 — PostGIS bin registry & zone mapping
├── ml/                 # Phase 4-5 — Forecasting engine + exogenous data connectors
├── routing/            # Phase 6-7 — VRP solver + real-time dispatch engine
├── driver_app/         # Phase 8 — In-cabin PWA / React Native interface
├── dashboard/          # Phase 9 — Operations command center (Next.js)
├── feedback/           # Phase 10 — Closed-loop calibration pipeline
├── infra/              # Phase 11 — Docker, K8s, CI/CD, monitoring configs
├── data/               # Runtime data artifacts (SQLite, snapshots, model artifacts)
├── scripts/            # One-time setup and utility scripts
├── tests/              # Unit and integration tests per module
├── docs/               # Architecture diagrams and API specs
└── CLAUDE.md
```

---

## Phase Registry

| Phase | Module | Status | Description |
|-------|--------|--------|-------------|
| 1 | `emulator/` | 🔄 Active | IoT edge emulator — bin fleet simulation, telemetry streaming, FastAPI |
| 2 | `ingestion/` | ⬜ Pending | Cloud ingestion pipeline, state machine, anomaly filtering |
| 3 | `geospatial/` | ⬜ Pending | PostGIS bin registry, GPS mapping, zone/sector classification |
| 4 | `ml/forecasting/` | ⬜ Pending | Fill-rate time-series forecasting (Prophet → XGBoost → LSTM) |
| 5 | `ml/exogenous/` | ⬜ Pending | Weather, traffic, calendar event connectors + feature joins |
| 6 | `routing/vrp/` | ⬜ Pending | CVRPTW solver — OR-Tools primary, metaheuristic fallback |
| 7 | `routing/dispatch/` | ⬜ Pending | Real-time re-optimization engine with stability buffer |
| 8 | `driver_app/` | ⬜ Pending | In-cabin distraction-compliant navigation PWA |
| 9 | `dashboard/` | ⬜ Pending | Ops command center — Next.js + Mapbox GL |
| 10 | `feedback/` | ⬜ Pending | Closed-loop emptying event → ML retraining pipeline |
| 11 | `infra/` | ⬜ Pending | Docker, K8s, Grafana/Prometheus, CI/CD |

Update phase status in this file as phases complete.

---

## Tech Stack

| Layer | Stack |
|-------|-------|
| Simulation / Backend | Python 3.11+, FastAPI, asyncio, aiosqlite |
| Data Ingestion | Apache Kafka or MQTT broker → TimescaleDB / InfluxDB |
| Geospatial | PostGIS (PostgreSQL extension), GeoJSON, Shapely |
| ML Forecasting | Prophet, LightGBM/XGBoost, PyTorch (LSTM), scikit-learn |
| Exogenous Data | OpenWeatherMap API, HERE Maps / Google Maps API |
| VRP Optimization | Google OR-Tools (primary), custom SA/GA fallback |
| Driver Interface | React Native / PWA, WebSocket push |
| Dashboard | Next.js 14, Mapbox GL JS / Deck.gl, Recharts |
| Infrastructure | Docker, Kubernetes, Grafana, Prometheus, GitHub Actions |
| Database | PostgreSQL + PostGIS, TimescaleDB, Redis (state cache), SQLite (dev/emulator) |

---

## Testing Standards

Every phase must include a `pytest` test suite under `tests/test_phase{N}/` with ≥ 80% coverage.

### Rules
- Tests must be runnable with `pytest tests/test_phase{N}/` from the project root with no extra setup beyond `.env`
- Use `httpx` + FastAPI `TestClient` for all API endpoint tests
- Use `pytest-asyncio` for any async function tests
- Each test file maps to one module (e.g., `test_bin_model.py` → `emulator/bin_model.py`)
- Edge case behaviors must each have a dedicated test — do not bundle multiple edge cases into one test function
- All tests must pass before the phase is considered complete
- Add `pytest`, `pytest-asyncio`, `httpx`, and `pytest-cov` to `requirements.txt`

### Coverage Report
Run with: `pytest tests/test_phase{N}/ --cov=. --cov-report=term-missing`
Include the coverage summary in the completion report.

---

### Python
- Type hints on all function signatures
- Pydantic models for all data schemas (telemetry packets, API request/response bodies)
- `loguru` for logging (not `print`)
- `pytest` for all tests — aim for ≥ 80% coverage per module
- Async-first: use `asyncio` / `aiohttp` / `aiosqlite` wherever I/O is involved
- Environment config via `.env` + `pydantic-settings`

### TypeScript / Next.js (Phases 8–9)
- Strict TypeScript throughout
- Component-level state via Zustand or React Query
- API calls via typed fetch wrappers
- Tailwind CSS for styling

### General
- All timestamps: ISO 8601 UTC
- All GPS: WGS84 (EPSG:4326)
- Numeric fill values: always float, clamped to [0.0, 100.0]
- Never hardcode credentials — use `.env` exclusively

---

## Key Domain Constants

```python
FILL_THRESHOLD_CRITICAL = 85.0      # % — triggers collection flag
FILL_THRESHOLD_WARNING   = 70.0      # % — triggers predictive alert
SENSOR_FAULT_THRESHOLD   = 100.0     # % reported for 2+ consecutive ticks = fault
WAKE_INTERVAL_MINUTES    = 30        # Normal deep-sleep interval
WAKE_INTERVAL_LOW_BAT_MINUTES = 60  # Battery < 3200mV
BATTERY_CRITICAL_MV      = 3200      # mV — triggers power-save mode
TRUCK_CAPACITY_LITERS    = 10_000    # Default truck payload capacity
ROUTE_STABILITY_BUFFER   = 0.15      # Re-optimize only if delta > 15% change in load
```

---

## Key Edge Cases — Always Handle

1. **Sensor blockage** — 100.0% reported for ≥ 2 consecutive ticks → flag `sensor_fault: true`, exclude from routing logic until self-cleared
2. **Volatile spike** — fill jumps > 40% in a single tick → do NOT treat as sensor fault; log as `event_type: spike`, update state, trigger re-evaluation
3. **Truck capacity overflow mid-route** — detect when truck payload ≥ 95% capacity; inject dump yard waypoint and reassign remaining route bins
4. **Route stability** — routes must not recompute more frequently than every 15 minutes per driver unless an emergency overflow event fires
5. **Tipping event** — accelerometer fires `tipped: true` → immediate distress packet, fill reset to 0, log as spill incident
6. **Closed-loop validation** — `emptied` event is ground truth; always reset bin state to 0% in DB and log to ML feedback table

---

## Development Workflow

1. Always run `python -m emulator.sim_engine` first — it is the data source for all downstream phases
2. Each phase module exposes a `/health` endpoint (FastAPI) or equivalent
3. Use `docker-compose up` from `infra/` once Phase 11 scaffolding exists
4. ML models saved to `data/models/{model_name}_{bin_id}_{version}.pkl` or `.pt`
5. All API specs documented in `docs/api/{phase}.yaml` (OpenAPI 3.0)

---

## Completion Report Format

When finishing a phase, output this exact box format — no prose, no preamble:

```
╔══════════════════════════════════════════════╗
║   ✅ PHASE N COMPLETE — [Module Name]        ║
║                                              ║
║  FILES CREATED:                              ║
║  - path/to/file.py                           ║
║                                              ║
║  ENDPOINTS LIVE:                             ║
║  - METHOD /endpoint                          ║
║                                              ║
║  TESTS: [X/X passing] [XX% coverage]         ║
║                                              ║
║  ➡️  READY FOR PHASE N+1                     ║
║     [Next phase name]                        ║
╚══════════════════════════════════════════════╝
```

Fill in real test count and coverage % from `pytest --cov` output before printing. If any tests are failing, do not print the completion box — fix the failures first.