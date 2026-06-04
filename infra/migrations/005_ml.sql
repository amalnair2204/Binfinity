-- Phase 5: ML prediction tracking tables
CREATE TABLE IF NOT EXISTS prediction_accuracy (
    bin_id                  TEXT NOT NULL,
    predicted_at            TIMESTAMPTZ NOT NULL,
    emptied_at              TIMESTAMPTZ NOT NULL,
    predicted_hours         DOUBLE PRECISION,
    actual_hours            DOUBLE PRECISION,
    absolute_error_hours    DOUBLE PRECISION,
    within_1h               BOOLEAN,
    within_2h               BOOLEAN,
    model_used              TEXT,
    fill_pct_at_prediction  DOUBLE PRECISION,
    zone_id                 TEXT,
    PRIMARY KEY (bin_id, predicted_at)
);

CREATE TABLE IF NOT EXISTS bin_predictions (
    bin_id               TEXT NOT NULL,
    predicted_at         TIMESTAMPTZ NOT NULL,
    hours_until_critical DOUBLE PRECISION,
    fill_pct_current     DOUBLE PRECISION,
    model_used           TEXT,
    confidence           DOUBLE PRECISION,
    zone_id              TEXT,
    PRIMARY KEY (bin_id, predicted_at)
);

CREATE INDEX IF NOT EXISTS idx_prediction_accuracy_bin    ON prediction_accuracy(bin_id);
CREATE INDEX IF NOT EXISTS idx_prediction_accuracy_time   ON prediction_accuracy(emptied_at DESC);
CREATE INDEX IF NOT EXISTS idx_bin_predictions_bin        ON bin_predictions(bin_id);
CREATE INDEX IF NOT EXISTS idx_bin_predictions_time       ON bin_predictions(predicted_at DESC);
