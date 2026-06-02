"""Prophet-based time-series forecaster for bin fill prediction."""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from loguru import logger


class ProphetForecaster:
    """Wraps Facebook Prophet for bin fill-rate forecasting.

    Expects a DataFrame with columns:
        ds          - datetime (timezone-aware or naive UTC)
        y           - fill_pct float
        is_weekend  - int (0/1)
        hour_of_day - int 0-23
        spike_count - int (spike events in that interval)
    """

    THRESHOLD = 85.0          # % fill considered critical
    HORIZON_HOURS = 24        # max forecast horizon
    FREQ = "30min"            # expected telemetry interval

    def __init__(self) -> None:
        self._model = None
        self._fitted = False
        self._future_df: pd.DataFrame | None = None   # saved after fit for predict

    def fit(self, df: pd.DataFrame) -> None:
        """Fit Prophet on historical fill_pct data.

        Args:
            df: must have columns: ds, y, is_weekend, hour_of_day, spike_count
                Minimum 48 rows required.
        """
        try:
            from prophet import Prophet  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "prophet is required: pip install prophet"
            ) from exc

        if len(df) < 48:
            raise ValueError(f"Need ≥48 rows to fit Prophet, got {len(df)}")

        # Ensure ds is timezone-naive for Prophet
        df = df.copy()
        if hasattr(df["ds"].dtype, "tz") and df["ds"].dtype.tz is not None:
            df["ds"] = df["ds"].dt.tz_localize(None)

        m = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            interval_width=0.80,
        )
        m.add_regressor("is_weekend")
        m.add_regressor("hour_of_day")
        m.add_regressor("spike_count")
        m.fit(df)
        self._model = m
        self._fitted = True
        logger.debug("ProphetForecaster fitted on {} rows", len(df))

    def predict_hours_until_critical(self, threshold: float = THRESHOLD) -> float:
        """Forecast 24h ahead and return hours until fill_pct >= threshold.

        Returns 24.0 if no crossing found within the horizon.
        Raises RuntimeError if not fitted.
        """
        if not self._fitted or self._model is None:
            raise RuntimeError("ProphetForecaster is not fitted — call fit() first")

        # Build future DataFrame at 30-min intervals for HORIZON_HOURS
        future = self._model.make_future_dataframe(
            periods=self.HORIZON_HOURS * 2,  # 2 periods per hour at 30-min freq
            freq=self.FREQ,
            include_history=False,
        )
        # Fill regressors for future: hour_of_day from ds, is_weekend, spike_count=0
        future["hour_of_day"] = future["ds"].dt.hour
        future["is_weekend"] = future["ds"].dt.dayofweek.isin([5, 6]).astype(int)
        future["spike_count"] = 0

        forecast = self._model.predict(future)
        # Use yhat (point forecast) — clamp to [0, 100]
        forecast["yhat_clamped"] = forecast["yhat"].clip(lower=0.0, upper=100.0)

        # Find first row where yhat_clamped >= threshold
        crossings = forecast[forecast["yhat_clamped"] >= threshold]
        if crossings.empty:
            return float(self.HORIZON_HOURS)

        first_crossing = crossings.iloc[0]["ds"]
        # Calculate hours from first forecast row
        t0 = forecast.iloc[0]["ds"]
        hours = (first_crossing - t0).total_seconds() / 3600.0
        return float(np.clip(hours, 0.0, self.HORIZON_HOURS))

    def save(self, path: str) -> None:
        """Serialize the forecaster to disk with joblib."""
        joblib.dump(self, path)
        logger.debug("ProphetForecaster saved to {}", path)

    @classmethod
    def load(cls, path: str) -> "ProphetForecaster":
        """Load a previously saved ProphetForecaster from disk."""
        obj = joblib.load(path)
        if not isinstance(obj, cls):
            raise TypeError(f"Expected ProphetForecaster, got {type(obj)}")
        return obj
