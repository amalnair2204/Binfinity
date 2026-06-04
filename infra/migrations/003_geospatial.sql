-- Phase 3: Geospatial registry tables
CREATE TABLE IF NOT EXISTS zones (
    zone_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    zone_type       TEXT NOT NULL,
    priority_level  INTEGER DEFAULT 1,
    assigned_trucks INTEGER DEFAULT 2,
    min_lat         DOUBLE PRECISION,
    max_lat         DOUBLE PRECISION,
    min_lng         DOUBLE PRECISION,
    max_lng         DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS sectors (
    sector_id   TEXT PRIMARY KEY,
    zone_id     TEXT REFERENCES zones(zone_id) ON DELETE SET NULL,
    name        TEXT NOT NULL,
    bin_count   INTEGER DEFAULT 0,
    min_lat     DOUBLE PRECISION,
    max_lat     DOUBLE PRECISION,
    min_lng     DOUBLE PRECISION,
    max_lng     DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS bin_registry (
    bin_id          TEXT PRIMARY KEY,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    zone_type       TEXT NOT NULL,
    zone_id         TEXT REFERENCES zones(zone_id) ON DELETE SET NULL,
    sector_id       TEXT REFERENCES sectors(sector_id) ON DELETE SET NULL,
    capacity_liters INTEGER NOT NULL,
    priority_level  INTEGER DEFAULT 1,
    is_active       BOOLEAN DEFAULT TRUE,
    road_access     TEXT DEFAULT 'standard'
);

CREATE INDEX IF NOT EXISTS idx_bin_registry_zone    ON bin_registry(zone_id);
CREATE INDEX IF NOT EXISTS idx_bin_registry_sector  ON bin_registry(sector_id);
CREATE INDEX IF NOT EXISTS idx_bin_registry_lat_lng ON bin_registry(lat, lng);

CREATE TABLE IF NOT EXISTS dump_yards (
    yard_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    capacity_tons   INTEGER,
    operating_hours TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);
