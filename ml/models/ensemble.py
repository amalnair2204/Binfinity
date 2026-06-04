"""Weighted ensemble of Prophet + GBM forecasters with extrapolation fallback."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from loguru import logger

from ml.schemas import FeatureVector, PredictionResult

# TYPE_CHECKING import to avoid circular/optional deps
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import pandas as pd
    from ml.models.prophet_model import ProphetForecaster
    from ml.models.gbm_model import GBMForecaster


class EnsembleForecaster:
    """Combines Prophet + GBM predictions; falls back to linear extrapolation."""

    MAX_HOURS = 24.0
    MIN_RATE = 0.1       # %/hr minimum to avoid div-by-zero in extrapolation

    def __init__(
        self,
        prophet: "ProphetForecaster | None" = None,
        gbm: "GBMForecaster | None" = None,
        prophet_weight: float = 0.4,
        gbm_weight: float = 0.6,
    ) -> None:
        self.prophet = prophet
        self.gbm = gbm
        self.prophet_weight = prophet_weight
        self.gbm_weight = gbm_weight

    def predict(
        self,
        features: FeatureVector,
        prophet_df: "pd.DataFrame | None" = None,
    ) -> PredictionResult:
        """Combine available model predictions into a single PredictionResult.

        Args:
            features: current feature vector for the bin
            prophet_df: historical DataFrame for Prophet (ds, y, regressors)
                        If None or Prophet not fitted, Prophet is skipped.

        Returns:
            PredictionResult with hours_until_critical, confidence, model_used.
        """
        prophet_hours: float | None = None
        gbm_hours: float | None = None

        # --- Prophet prediction ---
        if self.prophet is not None and self.prophet._fitted and prophet_df is not None:
            try:
                prophet_hours = self.prophet.predict_hours_until_critical()
            except Exception as exc:
                logger.warning("Prophet prediction failed for {}: {}", features.bin_id, exc)

        # --- GBM prediction ---
        if self.gbm is not None and self.gbm._fitted:
            try:
                gbm_hours = self.gbm.predict_hours_until_critical(features)
            except Exception as exc:
                logger.warning("GBM prediction failed for {}: {}", features.bin_id, exc)

        # --- Combine ---
        if prophet_hours is not None and gbm_hours is not None:
            # Weighted ensemble
            total_weight = self.prophet_weight + self.gbm_weight
            hours = (
                self.prophet_weight * prophet_hours + self.gbm_weight * gbm_hours
            ) / total_weight
            model_used = "ensemble"
            confidence = 1.0
        elif gbm_hours is not None:
            hours = gbm_hours
            model_used = "gbm"
            confidence = 0.7
        elif prophet_hours is not None:
            hours = prophet_hours
            model_used = "prophet"
            confidence = 0.7
        else:
            # Fallback: linear extrapolation from current fill rate
            rate = max(features.fill_rate_1h, self.MIN_RATE)
            remaining = 85.0 - features.fill_pct_current
            if remaining <= 0.0:
                hours = 0.0
            else:
                hours = remaining / rate
            model_used = "extrapolation"
            confidence = 0.3
            logger.debug(
                "Extrapolation fallback for {} — rate={:.2f} %/hr, remaining={:.1f}%",
                features.bin_id, rate, remaining,
            )

        hours = float(np.clip(hours, 0.0, self.MAX_HOURS))

        return PredictionResult(
            bin_id=features.bin_id,
            predicted_at=datetime.now(timezone.utc),
            hours_until_critical=hours,
            fill_pct_current=features.fill_pct_current,
            model_used=model_used,
            confidence=confidence,
            prophet_hours=prophet_hours,
            gbm_hours=gbm_hours,
        )
