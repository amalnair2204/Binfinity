-- Phase 2: Ingestion tables
CREATE TABLE IF NOT EXISTS telemetry (
    time         TIMESTAMPTZ NOT NULL,
    bin_id       TEXT        NOT NULL,
    fill_pct     DOUBLE PRECISION,
    fill_liters  DOUBLE PRECISION,
    tipped       BOOLEAN,
    sensor_fault BOOLEAN,
    battery_mv   INTEGER,
    rssi_dbm     INTEGER,
    temp_c       DOUBLE PRECISION,
    event_type   TEXT
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('telemetry', 'time', if_not_exists => TRUE);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS bin_states (
    bin_id                  TEXT PRIMARY KEY,
    last_updated            TIMESTAMPTZ,
    fill_pct                DOUBLE PRECISION,
    fill_liters             DOUBLE PRECISION,
    status                  TEXT,
    battery_mv              INTEGER,
    consecutive_fault_ticks INTEGER DEFAULT 0,
    flagged_for_collection  BOOLEAN DEFAULT FALSE,
    last_emptied            TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS spill_incidents (
    id            SERIAL PRIMARY KEY,
    bin_id        TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    fill_at_spill DOUBLE PRECISION,
    lat           DOUBLE PRECISION,
    lng           DOUBLE PRECISION
);
