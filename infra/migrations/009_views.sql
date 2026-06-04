-- Phase 9: Operational views
CREATE OR REPLACE VIEW v_bin_fill_latest AS
SELECT
    bs.bin_id,
    bs.fill_pct,
    bs.fill_liters,
    bs.status,
    bs.flagged_for_collection,
    bs.last_updated,
    br.lat,
    br.lng,
    br.zone_id,
    br.zone_type,
    br.capacity_liters
FROM bin_states bs
LEFT JOIN bin_registry br USING (bin_id);

CREATE OR REPLACE VIEW v_fleet_accuracy_7d AS
SELECT
    bin_id,
    COUNT(*)                                            AS n_events,
    AVG(absolute_error_hours)                          AS mae_hours,
    AVG(CASE WHEN within_1h THEN 1.0 ELSE 0.0 END)   AS within_1h_pct,
    AVG(CASE WHEN within_2h THEN 1.0 ELSE 0.0 END)   AS within_2h_pct,
    MAX(emptied_at)                                    AS last_seen
FROM prediction_accuracy
WHERE emptied_at >= NOW() - INTERVAL '7 days'
GROUP BY bin_id;

CREATE OR REPLACE VIEW v_retrain_queue_depth AS
SELECT
    status,
    COUNT(*) AS count,
    MIN(enqueued_at) AS oldest_enqueued
FROM retrain_jobs_log
GROUP BY status;
