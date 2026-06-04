"""Gradient Boosting forecaster for bin fill prediction."""
from __future__ import annotations

import numpy as np
import pandas as pd
import joblib
from loguru import logger
from sklearn.ensemble import HistGradientBoostingRegressor

from ml.schemas import FeatureVector


# Feature columns used for GBM (ordered, matches FeatureVector fields)
GBM_FEATURE_COLS: list[str] = [
    "fill_pct_current", "fill_rate_1h", "fill_rate_3h", "fill_rate_6h",
    "fill_rate_24h", "rolling_std_6h", "time_since_last_empty",
    "fill_at_last_empty", "hour_of_day", "day_of_week",
    "is_weekend", "is_peak_morning", "is_peak_evening",
    "days_until_next_holiday", "zone_type_residential", "zone_type_commercial",
    "zone_type_park", "zone_type_transit_hub", "capacity_liters",
    "priority_level", "sector_avg_fill", "spike_count_24h",
    "fault_count_24h", "is_volatile",
]


class GBMForecaster:
    """HistGradientBoosting model predicting hours until 85% fill threshold."""

    THRESHOLD = 85.0
    MAX_HOURS = 24.0

    def __init__(self) -> None:
        self._model = HistGradientBoostingRegressor(
            max_iter=200,
            max_depth=6,
            min_samples_leaf=5,
            random_state=42,
        )
        self._fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Fit on feature matrix X and label vector y (hours_until_critical).

        Args:
            X: DataFrame with columns matching GBM_FEATURE_COLS (subset ok)
            y: Series of float labels in [0, MAX_HOURS]
        Raises:
            ValueError: if X has fewer than 10 samples
        """
        if len(X) < 10:
            raise ValueError(f"Need ≥10 samples to fit GBM, got {len(X)}")
        cols = [c for c in GBM_FEATURE_COLS if c in X.columns]
        # Convert bool columns to int for sklearn
        X_fit = X[cols].copy()
        for col in ["is_weekend", "is_peak_morning", "is_peak_evening", "is_volatile"]:
            if col in X_fit.columns:
                X_fit[col] = X_fit[col].astype(int)
        self._model.fit(X_fit, y)
        self._fitted = True
        logger.debug("GBMForecaster fitted on {} samples, {} features", len(X), len(cols))

    def predict_hours_until_critical(self, features: FeatureVector) -> float:
        """Predict hours until bin reaches THRESHOLD % fill.

        Returns float in [0.0, MAX_HOURS]. Clamps output.
        Raises RuntimeError if not fitted.
        """
        if not self._fitted:
            raise RuntimeError("GBMForecaster is not fitted — call fit() first")

        row = {}
        for col in GBM_FEATURE_COLS:
            val = getattr(features, col, 0)
            # Convert bool to int
            row[col] = int(val) if isinstance(val, bool) else val

        X = pd.DataFrame([row])
        pred = self._model.predict(X)[0]
        return float(np.clip(pred, 0.0, self.MAX_HOURS))

    def save(self, path: str) -> None:
        joblib.dump(self, path)
        logger.debug("GBMForecaster saved to {}", path)

    @classmethod
    def load(cls, path: str) -> "GBMForecaster":
        obj = joblib.load(path)
        if not isinstance(obj, cls):
            raise TypeError(f"Expected GBMForecaster, got {type(obj)}")
        return obj
