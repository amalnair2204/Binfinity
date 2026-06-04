"""Shared Prometheus metrics for all Binfinity services."""
from prometheus_client import Counter, Gauge, Histogram

# Ingestion
TELEMETRY_PACKETS_RECEIVED = Counter(
    "binfinity_telemetry_packets_total",
    "Total telemetry packets ingested",
    ["zone"],
)
SENSOR_FAULTS_TOTAL = Counter(
    "binfinity_sensor_faults_total",
    "Total sensor fault events",
)
BINS_FLAGGED_GAUGE = Gauge(
    "binfinity_bins_flagged",
    "Current bins flagged for collection",
)

# ML
PREDICTION_MAE_GAUGE = Gauge(
    "binfinity_prediction_mae_hours",
    "Current fleet-wide prediction MAE",
)
RETRAIN_JOBS_QUEUED = Gauge(
    "binfinity_retrain_jobs_queued",
    "Current retrain job queue depth",
)

# Routing
VRP_SOLVE_DURATION = Histogram(
    "binfinity_vrp_solve_seconds",
    "VRP solve time in seconds",
    buckets=[1, 5, 10, 30, 60],
)
REOPTIMIZATIONS_TOTAL = Counter(
    "binfinity_reoptimizations_total",
    "Total route re-optimizations",
    ["trigger_type"],
)
ACTIVE_TRUCKS_GAUGE = Gauge(
    "binfinity_active_trucks",
    "Trucks currently on shift",
)

# Feedback
FEEDBACK_EVENTS_PROCESSED = Counter(
    "binfinity_feedback_events_total",
    "Total feedback events processed",
)
