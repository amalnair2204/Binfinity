-- Phase 1: PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'
    ) THEN
        RAISE NOTICE 'timescaledb extension not available — skipping';
    ELSE
        CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
    END IF;
END $$;
