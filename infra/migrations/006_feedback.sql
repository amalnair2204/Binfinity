-- Phase 6: Feedback pipeline tables
CREATE TABLE IF NOT EXISTS retrain_jobs_log (
    id             SERIAL PRIMARY KEY,
    job_id         TEXT NOT NULL,
    target_type    TEXT NOT NULL,
    target_id      TEXT NOT NULL,
    enqueued_at    TIMESTAMPTZ NOT NULL,
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ,
    status         TEXT NOT NULL,
    error          TEXT,
    trigger_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_retrain_jobs_enqueued ON retrain_jobs_log(enqueued_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrain_jobs_status   ON retrain_jobs_log(status);
