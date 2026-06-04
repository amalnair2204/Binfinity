# Phase 4 — ML Forecasting Engine — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Given a bin's fill history and context, predict "hours until 85% fill threshold". This triggers proactive collection flagging before overflow.

**Architecture:** Three-stage pipeline — Prophet baseline (time-series) + GBM (feature-based) + weighted ensemble. Served by FastAPI on port 8003. Training orchestrator reads from existing telemetry hypertable and bin_states.

**Note on missing spec:** The original prompt was truncated at Stage 2. Stages 2–7 are inferred from context.

**Environment:**
- Python 3.12, PostgreSQL 15 native
- Telemetry in `telemetry` table (Phase 2): time, bin_id, fill_pct, sensor_fault, event_type, etc.
- Bin registry in `bin_registry` table (Phase 3): zone_type, capacity_liters, sector_id
- Current states in `bin_states` table (Phase 2)
- `geospatial/schemas.py`: `BinRegistryEntry` (NOT `BinRegistryRecord`)
- `geospatial/db.py`: `bins_by_sector()`, `get_bin()` (NOT a `queries.py` file)
- Models saved to `data/models/` directory

**New dependencies to add to requirements.txt:**
- `scikit-learn>=1.4.0`
- `pandas>=2.2.0`
- `numpy>=1.26.0`
- `prophet>=1.1.5`
- `joblib>=1.3.0`

---

## File Map

| File | Responsibility |
|------|---------------|
| `ml/__init__.py` | Package init |
| `ml/schemas.py` | Pydantic v2: FeatureVector, PredictionResult, TrainingResult, ModelStatus |
| `ml/features.py` | Build feature vectors from telemetry + bin_registry + bin_states |
| `ml/models/__init__.py` | Package init |
| `ml/models/prophet_model.py` | ProphetForecaster: fit, predict_hours_until_critical, save, load |
| `ml/models/gbm_model.py` | GBMForecaster: fit, predict_hours_until_critical, save, load |
| `ml/models/ensemble.py` | EnsembleForecaster: weighted combination + fallback extrapolation |
| `ml/trainer.py` | generate_labels, train_bin, train_zone, train_all |
| `ml/predictor.py` | ModelRegistry: load models from disk, predict single/fleet |
| `ml/api.py` | FastAPI on port 8003 — 8 endpoints |
| `tests/test_phase4/__init__.py` | Package init |
| `tests/test_phase4/test_features.py` | Feature engineering unit tests (mock DB) |
| `tests/test_phase4/test_models.py` | Prophet/GBM/Ensemble unit tests (synthetic data) |
| `tests/test_phase4/test_trainer.py` | Trainer unit tests (mock DB) |
| `tests/test_phase4/test_api.py` | FastAPI endpoint tests (mock predictor) |

---

## Schemas (`ml/schemas.py`)

```python
class FeatureVector(BaseModel):
    bin_id: str
    at_time: datetime
    # Temporal fill rates
    fill_pct_current: float
    fill_rate_1h: float      # mean fill increase over last 2 readings
    fill_rate_3h: float      # mean fill increase over last 6 readings
    fill_rate_6h: float      # mean fill increase over last 12 readings
    fill_rate_24h: float     # mean fill increase over last 48 readings
    rolling_std_6h: float    # std of fill_pct over last 12 readings
    time_since_last_empty: float   # hours; default 168.0 if never emptied
    fill_at_last_empty: float      # default 0.0
    # Time context
    hour_of_day: int
    day_of_week: int
    is_weekend: bool
    is_peak_morning: bool    # 07:00–09:00
    is_peak_evening: bool    # 17:00–20:00
    days_until_next_holiday: int   # from hardcoded UAE calendar
    # Bin context
    zone_type_residential: int     # one-hot encoded
    zone_type_commercial: int
    zone_type_park: int
    zone_type_transit_hub: int
    capacity_liters: float
    priority_level: int
    sector_avg_fill: float         # mean fill_pct of sector peers
    # Anomaly
    spike_count_24h: int
    fault_count_24h: int
    is_volatile: bool              # rolling_std_6h > 8.0


class PredictionResult(BaseModel):
    bin_id: str
    predicted_at: datetime
    hours_until_critical: float   # hours until 85% threshold; capped at 24.0
    fill_pct_current: float
    model_used: str               # "ensemble" | "prophet" | "gbm" | "extrapolation"
    confidence: float             # 0.0–1.0
    prophet_hours: Optional[float] = None
    gbm_hours: Optional[float] = None


class TrainingResult(BaseModel):
    bin_id: str
    zone_id: str
    trained_at: datetime
    prophet_trained: bool
    gbm_trained: bool
    n_samples: int
    error: Optional[str] = None


class ModelStatus(BaseModel):
    bin_id: str
    has_prophet: bool
    has_gbm: bool
    last_trained: Optional[datetime] = None
```

---

## Feature Engineering (`ml/features.py`)

```python
async def build_feature_vector(
    bin_id: str,
    ingestion_db: IngestionDB,
    geo_db: GeospatialDB,
    at_time: datetime = None,
) -> FeatureVector
```

Queries needed:
1. **Last 48 telemetry rows** for bin_id, ordered by time DESC — for fill rates, std, spike/fault counts
2. **Last emptied event** — `SELECT time, fill_pct FROM telemetry WHERE bin_id=$1 AND event_type='emptied' ORDER BY time DESC LIMIT 1`
3. **Bin registry** — `geo_db.get_bin(bin_id)` for zone_type, capacity_liters, priority_level, sector_id
4. **Sector peer fill** — `SELECT AVG(fill_pct) FROM bin_states WHERE bin_id IN (sector peers from bin_registry)` (query bin_registry for sector peers, then avg from bin_states)

**Handling sparse data:**
- If < 2 readings: fill_rate_1h = 0.0
- If < 6 readings: fill_rate_3h = fill_rate_1h
- If < 12 readings: fill_rate_6h = fill_rate_3h
- rolling_std_6h = 0.0 if < 2 readings

**UAE Holiday calendar** (hardcoded dict of 2025–2026 holiday dates):
```python
_UAE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 3, 30), date(2026, 4, 2), date(2026, 6, 6),
    date(2026, 8, 10), date(2026, 9, 2), date(2026, 10, 9), date(2026, 12, 1),
    date(2026, 12, 2), date(2026, 12, 3),
}
```

**`build_feature_matrix`:**
```python
async def build_feature_matrix(
    bin_ids: list[str],
    ingestion_db: IngestionDB,
    geo_db: GeospatialDB,
    at_time: datetime = None,
) -> pd.DataFrame
```
Returns DataFrame with one row per bin, columns = FeatureVector fields minus `bin_id`/`at_time`.

---

## Stage 1 — Prophet (`ml/models/prophet_model.py`)

```python
class ProphetForecaster:
    def __init__(self):
        self.model = None
        self._fitted = False

    def fit(self, df: pd.DataFrame) -> None:
        # df: columns = ds (datetime), y (fill_pct), is_weekend, hour_of_day, spike_count_24h
        # Add regressors before fit
        # Seasonality: daily + weekly

    def predict_hours_until_critical(self, threshold: float = 85.0) -> float:
        # forecast 24h into the future at 30-min intervals
        # return hours until first crossing of threshold
        # if no crossing: return 24.0

    def save(self, path: str) -> None:  # joblib.dump
    @classmethod
    def load(cls, path: str) -> "ProphetForecaster"  # joblib.load
```

Fit on the `df` structure shown. If `prophet` library not installed, raise `ImportError` with install instructions.

---

## Stage 2 — GBM (`ml/models/gbm_model.py`)

```python
class GBMForecaster:
    def __init__(self):
        self.model = HistGradientBoostingRegressor(max_iter=200, random_state=42)
        self._fitted = False
        self.feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        # X: feature matrix (from build_feature_matrix)
        # y: hours_until_critical labels

    def predict_hours_until_critical(self, features: FeatureVector) -> float:
        # Convert FeatureVector to DataFrame row, predict, clamp to [0, 24]

    def save(self, path: str) -> None
    @classmethod
    def load(cls, path: str) -> "GBMForecaster"
```

Feature columns to use: all numeric fields from FeatureVector (exclude bin_id, at_time, bool fields convert to int).

---

## Stage 3 — Ensemble (`ml/models/ensemble.py`)

```python
class EnsembleForecaster:
    def __init__(
        self,
        prophet: ProphetForecaster | None = None,
        gbm: GBMForecaster | None = None,
        prophet_weight: float = 0.4,
        gbm_weight: float = 0.6,
    ):

    def predict(self, features: FeatureVector, prophet_df: pd.DataFrame | None) -> PredictionResult:
        # Collect available predictions:
        # - prophet: call prophet.predict_hours_until_critical() if available + prophet_df provided
        # - gbm: call gbm.predict_hours_until_critical(features) if available
        # Ensemble: weighted average of available predictions
        # Fallback (both unavailable): extrapolation
        #   rate = max(features.fill_rate_1h, 0.1)  # avoid div by zero
        #   hours = (85.0 - features.fill_pct_current) / rate
        #   hours = max(0.0, min(24.0, hours))
        # confidence: 1.0 if ensemble, 0.7 if single model, 0.3 if extrapolation
        # model_used: "ensemble" | "prophet" | "gbm" | "extrapolation"
```

---

## Trainer (`ml/trainer.py`)

```python
async def generate_labels(
    bin_id: str,
    db: IngestionDB,
    window_hours: int = 24,
    threshold: float = 85.0,
) -> pd.DataFrame:
    # Fetch all telemetry for bin_id
    # For each row at time t, scan forward to find first timestamp where fill_pct >= threshold
    # Label = hours between t and that timestamp; cap at window_hours if no crossing found
    # Return DataFrame with columns: time, fill_pct, hours_until_critical

async def train_bin_prophet(
    bin_id: str,
    ingestion_db: IngestionDB,
    geo_db: GeospatialDB,
    model_dir: str = "data/models",
) -> bool:
    # Build Prophet df from last 30 days, fit, save to data/models/prophet_{bin_id}.pkl
    # Return True if trained, False if insufficient data (< 48 rows)

async def train_zone_gbm(
    zone_id: str,
    bin_ids: list[str],
    ingestion_db: IngestionDB,
    geo_db: GeospatialDB,
    model_dir: str = "data/models",
) -> TrainingResult:
    # Build feature matrix for all bins in zone
    # Generate labels for all bins in zone
    # Fit single GBM per zone (better generalization)
    # Save to data/models/gbm_{zone_id}.pkl

async def train_all(
    ingestion_db: IngestionDB,
    geo_db: GeospatialDB,
    model_dir: str = "data/models",
) -> list[TrainingResult]:
    # 1. Group bins by zone (from geo_db)
    # 2. For each zone: train_zone_gbm
    # 3. For each bin: train_bin_prophet
    # Return list of TrainingResult
```

---

## Predictor (`ml/predictor.py`)

```python
class ModelRegistry:
    def __init__(self, model_dir: str = "data/models"):
        self.model_dir = model_dir
        self._prophet: dict[str, ProphetForecaster] = {}
        self._gbm: dict[str, GBMForecaster] = {}  # keyed by zone_id

    def load_all(self) -> None:
        # Scan model_dir for prophet_*.pkl and gbm_*.pkl, load all

    def get_ensemble(self, bin_id: str, zone_id: str) -> EnsembleForecaster:
        # Build EnsembleForecaster with available models

    async def predict(
        self,
        bin_id: str,
        ingestion_db: IngestionDB,
        geo_db: GeospatialDB,
    ) -> PredictionResult:
        # build_feature_vector → get ensemble → predict
        # For prophet: build prophet df (last 30 days) too

    async def predict_fleet(
        self,
        ingestion_db: IngestionDB,
        geo_db: GeospatialDB,
    ) -> list[PredictionResult]:
        # All active bins from bin_registry
```

---

## API (`ml/api.py`)

FastAPI on port 8004 (8001=ingestion, 8002=geospatial, 8003 reserved).

Wait — check: ingestion=8001, geospatial=8002 → use port **8003**.

Module-level singletons:
```python
ingestion_db: IngestionDB | None = None
geo_db: GeospatialDB | None = None
registry: ModelRegistry | None = None
```

Startup: connect both DBs, load models from `data/models/`.

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | DB status + model count |
| GET | /predict/{bin_id} | Single bin prediction |
| POST | /predict/batch | Body: `{"bin_ids": [...]}` → list[PredictionResult] |
| GET | /fleet/at_risk | ?hours=4.0 → bins predicted critical within N hours |
| POST | /train/{bin_id} | Trigger Prophet training for one bin |
| POST | /train/all | Background task: train all bins/zones |
| GET | /models/status | List ModelStatus for all bins |
| GET | /models/status/{bin_id} | ModelStatus for single bin |

---

## Label Generation Design

For training the GBM:
```
For each (timestamp t, fill_pct f) in bin's history:
    scan forward until fill_pct >= 85.0
    label = (first_crossing_time - t).total_seconds() / 3600
    if no crossing within 24h window: label = 24.0
```

Minimum data for training:
- Prophet: ≥ 48 rows (24 hours at 30-min intervals)
- GBM per zone: ≥ 100 labeled samples across all zone bins

---

## Tasks

- [ ] **Task 1:** requirements.txt + `ml/schemas.py` + `ml/__init__.py` + `ml/models/__init__.py` + `data/models/.gitkeep`
- [ ] **Task 2:** Feature engineering (`ml/features.py`)
- [ ] **Task 3:** Prophet model (`ml/models/prophet_model.py`)
- [ ] **Task 4:** GBM + Ensemble (`ml/models/gbm_model.py` + `ml/models/ensemble.py`)
- [ ] **Task 5:** Trainer + Predictor (`ml/trainer.py` + `ml/predictor.py`)
- [ ] **Task 6:** FastAPI (`ml/api.py`)
- [ ] **Task 7:** Tests — ≥80% coverage on `ml/` module

**Coverage target: ≥ 80% on `ml/` module**
