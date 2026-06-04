# Phase 3 — Binfinity Geospatial Database & Bin Registry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build the spatial backbone for bin locations, zone assignments, and sector groupings. Every downstream phase (ML forecasting, VRP routing, dashboard) queries this layer.

**Architecture:** New `geospatial/` package with asyncpg DB layer, Pydantic schemas, seeder, and FastAPI. No separate database — extends the same PostgreSQL instance used by Phase 2. PostGIS optional; all spatial queries fall back to Haversine math if extension unavailable.

**Environment notes:**
- PostgreSQL 15 native (Windows), no Docker
- PostGIS NOT installed — fallback to Haversine / lat-lng bounding-box queries
- 200 bins in `config/bins.json` (Dubai lat 25.05–25.35, lng 55.12–55.42)
- Zone types: commercial (69), residential (77), park (35), transit_hub (19)

**Tech Stack:** Python 3.12, asyncpg, FastAPI, Pydantic v2, loguru, pytest, pytest-asyncio

---

## File Map

| File | Responsibility |
|------|---------------|
| `geospatial/__init__.py` | Package init |
| `geospatial/schemas.py` | Pydantic v2: BinRegistryEntry, Zone, Sector, DumpYard, GeoJSON types |
| `geospatial/db.py` | asyncpg pool, DDL, CRUD, spatial queries (Haversine fallback) |
| `geospatial/seeder.py` | Seed zones, sectors (2×2 grid), all 200 bins, 3 dump yards |
| `geospatial/api.py` | FastAPI — 14 endpoints |
| `geospatial/migrations/001_geospatial.sql` | DDL (no GEOMETRY columns; lat/lng DOUBLE PRECISION) |
| `tests/test_phase3/__init__.py` | Package init |
| `tests/test_phase3/test_db.py` | asyncpg integration tests |
| `tests/test_phase3/test_seeder.py` | Seeder unit tests (mocked DB) |
| `tests/test_phase3/test_api.py` | FastAPI endpoint tests |

---

## Database Schema

No PostGIS GEOMETRY columns (extension unavailable). Spatial data as lat/lng DOUBLE PRECISION + bbox JSON.

```sql
CREATE TABLE zones (
    zone_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    zone_type       TEXT NOT NULL,   -- residential, commercial, park, transit_hub
    priority_level  INTEGER DEFAULT 1,
    assigned_trucks INTEGER DEFAULT 2,
    min_lat         DOUBLE PRECISION,
    max_lat         DOUBLE PRECISION,
    min_lng         DOUBLE PRECISION,
    max_lng         DOUBLE PRECISION
);

CREATE TABLE sectors (
    sector_id   TEXT PRIMARY KEY,
    zone_id     TEXT REFERENCES zones(zone_id),
    name        TEXT NOT NULL,
    bin_count   INTEGER DEFAULT 0,
    min_lat     DOUBLE PRECISION,
    max_lat     DOUBLE PRECISION,
    min_lng     DOUBLE PRECISION,
    max_lng     DOUBLE PRECISION
);

CREATE TABLE bin_registry (
    bin_id              TEXT PRIMARY KEY,
    lat                 DOUBLE PRECISION NOT NULL,
    lng                 DOUBLE PRECISION NOT NULL,
    zone_type           TEXT NOT NULL,
    zone_id             TEXT REFERENCES zones(zone_id),
    sector_id           TEXT REFERENCES sectors(sector_id),
    capacity_liters     INTEGER NOT NULL,
    priority_level      INTEGER DEFAULT 1,
    is_active           BOOLEAN DEFAULT TRUE,
    road_access         TEXT DEFAULT 'standard'
);
CREATE INDEX idx_bin_registry_zone ON bin_registry(zone_id);
CREATE INDEX idx_bin_registry_lat_lng ON bin_registry(lat, lng);

CREATE TABLE dump_yards (
    yard_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    capacity_tons   INTEGER,
    operating_hours TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);

ALTER TABLE spill_incidents ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE spill_incidents ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION;
```

---

## Seeder Logic

**Zones (4):** One per zone_type. Bbox = min/max of all bins in that zone.

**Sectors (16):** Each zone split into 2×2 lat/lng grid. Naming: `{ZONE_ID}-S{row}{col}` (e.g., `Z-COMMERCIAL-S00`).

**Bins (200):** Read `config/bins.json`, upsert each. Sector assigned by checking which sector bbox contains the bin's lat/lng. Fallback to `{zone_id}-S00` if no match.

**Dump yards (3):**
- YARD-001: Al Quoz, lat=25.1451, lng=55.2311, capacity_tons=5000
- YARD-002: Jebel Ali, lat=25.0050, lng=55.1200, capacity_tons=8000
- YARD-003: Al Muhaisnah, lat=25.2933, lng=55.3611, capacity_tons=3000

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | DB connectivity check |
| GET | /bins | List all registered bins |
| GET | /bins/{bin_id} | Single bin by ID |
| GET | /bins/nearest | ?lat=&lng=&limit=10 — nearest N (Haversine sort) |
| GET | /bins/within | ?lat=&lng=&radius_m=500 — within radius |
| GET | /zones | List all zones |
| GET | /zones/{zone_id} | Single zone |
| GET | /zones/{zone_id}/bins | Bins in zone |
| GET | /sectors | List all sectors |
| GET | /sectors/{sector_id} | Single sector |
| GET | /sectors/{sector_id}/bins | Bins in sector |
| GET | /dump_yards | List all dump yards |
| GET | /dump_yards/nearest | ?lat=&lng= — nearest yard (Haversine) |
| GET | /export/bins.geojson | GeoJSON FeatureCollection of all bins |
| GET | /export/zones.geojson | GeoJSON FeatureCollection of zones (bbox Polygons) |
| GET | /export/sectors.geojson | GeoJSON FeatureCollection of sectors (bbox Polygons) |

---

## Haversine Helper

```python
import math

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

---

## Tasks

- [ ] **Task 1:** SQL migration + Pydantic schemas
  - Create `geospatial/migrations/001_geospatial.sql` (full DDL as above)
  - Create `geospatial/schemas.py` (BinRegistryEntry, Zone, Sector, DumpYard + GeoJSON models)
  - Create `geospatial/__init__.py` (empty)

- [ ] **Task 2:** PostGIS DB layer
  - Create `geospatial/db.py` (GeospatialDB class)
  - `connect()` / `close()` — asyncpg pool
  - `init_schema()` — read + execute 001_geospatial.sql
  - `upsert_bin()`, `get_bin()`, `list_bins()`
  - `upsert_zone()`, `list_zones()`
  - `upsert_sector()`, `list_sectors()`
  - `upsert_dump_yard()`, `list_dump_yards()`
  - `nearest_bins(lat, lng, limit)` — Haversine sort via Python (fetch all, sort)
  - `bins_within(lat, lng, radius_m)` — filter by Haversine distance
  - `nearest_dump_yard(lat, lng)` — Haversine sort

- [ ] **Task 3:** Seeder
  - Create `geospatial/seeder.py`
  - `seed_zones(db)` — 4 zones, compute bbox from bins.json
  - `seed_sectors(db, zones)` — 2×2 grid per zone
  - `seed_bins(db, zones, sectors)` — upsert all 200 from bins.json, assign sector
  - `seed_dump_yards(db)` — 3 fixed yards
  - `run_seed(db)` — orchestrates all four in order

- [ ] **Task 4:** FastAPI layer
  - Create `geospatial/api.py`
  - All 16 endpoints per table above
  - Startup event: `await geo_db.init_schema(); await run_seed(geo_db)`
  - Run on port 8002 (alongside ingestion on 8001)

- [ ] **Task 5:** Tests + coverage ≥ 80%
  - `tests/test_phase3/__init__.py`
  - `tests/test_phase3/test_db.py` — integration tests vs live PostgreSQL
  - `tests/test_phase3/test_seeder.py` — unit tests (mock DB via AsyncMock)
  - `tests/test_phase3/test_api.py` — FastAPI TestClient with mocked geo_db

**Coverage target: ≥ 80% on `geospatial/` module**
