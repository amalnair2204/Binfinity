-- Phase 4: Routing and truck management tables
CREATE TABLE IF NOT EXISTS truck_registry (
    truck_id            TEXT PRIMARY KEY,
    capacity_liters     INTEGER NOT NULL,
    depot_lat           DOUBLE PRECISION NOT NULL,
    depot_lng           DOUBLE PRECISION NOT NULL,
    shift_start_seconds INTEGER NOT NULL DEFAULT 0,
    shift_end_seconds   INTEGER NOT NULL DEFAULT 28800,
    can_access_narrow   BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collections_log (
    id               BIGSERIAL PRIMARY KEY,
    truck_id         TEXT NOT NULL,
    bin_id           TEXT NOT NULL,
    collected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    liters_collected DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS dump_events_log (
    id            BIGSERIAL PRIMARY KEY,
    truck_id      TEXT NOT NULL,
    yard_id       TEXT NOT NULL,
    dumped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    liters_dumped DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS optimized_routes (
    route_id            TEXT PRIMARY KEY,
    truck_id            TEXT NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    triggered_by        TEXT,
    solver              TEXT,
    solve_time_ms       INTEGER,
    stops_json          JSONB,
    total_distance_m    DOUBLE PRECISION,
    total_duration_sec  INTEGER,
    bins_collected      INTEGER,
    dump_yard_visits    INTEGER,
    is_complete         BOOLEAN DEFAULT FALSE,
    objective_value     DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS route_events (
    event_id        TEXT PRIMARY KEY,
    route_id        TEXT REFERENCES optimized_routes(route_id),
    event_type      TEXT,
    triggered_at    TIMESTAMPTZ,
    affected_bin_id TEXT,
    truck_id        TEXT,
    resolved        BOOLEAN DEFAULT FALSE
);
