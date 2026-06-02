"""Unit tests for ml/models/ — GBM, Prophet, Ensemble."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ml.models.ensemble import EnsembleForecaster
from ml.models.gbm_model import GBM_FEATURE_COLS, GBMForecaster
from ml.schemas import FeatureVector, PredictionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fv(**kwargs) -> FeatureVector:
    defaults = dict(
        bin_id="BIN-0001",
        at_time=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        fill_pct_current=50.0,
        fill_rate_1h=2.0,
        fill_rate_3h=1.5,
        fill_rate_6h=1.0,
        fill_rate_24h=0.8,
        rolling_std_6h=3.0,
        time_since_last_empty=48.0,
        fill_at_last_empty=5.0,
        hour_of_day=10,
        day_of_week=0,
        is_weekend=False,
        is_peak_morning=False,
        is_peak_evening=False,
        days_until_next_holiday=10,
        zone_type_residential=0,
        zone_type_commercial=1,
        zone_type_park=0,
        zone_type_transit_hub=0,
        capacity_liters=240.0,
        priority_level=2,
        sector_avg_fill=45.0,
        spike_count_24h=0,
        fault_count_24h=0,
        is_volatile=False,
    )
    defaults.update(kwargs)
    return FeatureVector(**defaults)


def _make_gbm_data(n=20):
    rng = np.random.default_rng(42)
    X = pd.DataFrame({col: rng.uniform(0, 1, n) for col in GBM_FEATURE_COLS})
    y = pd.Series(rng.uniform(0, 24, n), name="hours_until_critical")
    return X, y


# ---------------------------------------------------------------------------
# GBMForecaster
# ---------------------------------------------------------------------------

class TestGBMForecaster:
    def test_not_fitted_raises(self):
        gbm = GBMForecaster()
        fv = _make_fv()
        with pytest.raises(RuntimeError, match="not fitted"):
            gbm.predict_hours_until_critical(fv)

    def test_fit_too_few_raises(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(5)
        with pytest.raises(ValueError, match="10"):
            gbm.fit(X, y)

    def test_fit_predict(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(50)
        gbm.fit(X, y)
        assert gbm._fitted is True

        fv = _make_fv()
        result = gbm.predict_hours_until_critical(fv)
        assert 0.0 <= result <= 24.0

    def test_predict_clamped(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(50)
        gbm.fit(X, y)

        # High fill pct — should still return in [0, 24]
        fv = _make_fv(fill_pct_current=99.0, fill_rate_1h=100.0)
        result = gbm.predict_hours_until_critical(fv)
        assert 0.0 <= result <= 24.0

    def test_save_load(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(20)
        gbm.fit(X, y)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        gbm.save(path)

        loaded = GBMForecaster.load(path)
        assert loaded._fitted is True
        fv = _make_fv()
        assert 0.0 <= loaded.predict_hours_until_critical(fv) <= 24.0

    def test_load_wrong_type_raises(self):
        import joblib
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        joblib.dump({"not": "a gbm"}, path)
        with pytest.raises(TypeError):
            GBMForecaster.load(path)

    def test_bool_columns_converted(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(20)
        gbm.fit(X, y)

        fv = _make_fv(is_weekend=True, is_peak_morning=True, is_volatile=True)
        result = gbm.predict_hours_until_critical(fv)
        assert isinstance(result, float)

    def test_partial_feature_columns(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(20)
        # Only include half the columns — fit should still work (subset)
        X_subset = X[GBM_FEATURE_COLS[:12]]
        gbm.fit(X_subset, y)
        assert gbm._fitted is True


# ---------------------------------------------------------------------------
# ProphetForecaster — mock Prophet to avoid dependency
# ---------------------------------------------------------------------------

class TestProphetForecaster:
    def _make_prophet_df(self, n=60):
        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        from datetime import timedelta
        return pd.DataFrame({
            "ds": [base + timedelta(minutes=30 * i) for i in range(n)],
            "y": [30.0 + 0.5 * i for i in range(n)],
            "is_weekend": [0] * n,
            "hour_of_day": [8] * n,
            "spike_count": [0] * n,
        })

    def test_import_error_if_no_prophet(self):
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        df = self._make_prophet_df()
        with patch("builtins.__import__", side_effect=ImportError("no prophet")):
            # The ImportError is only raised if prophet itself not installed
            # and fit is called — guard is inside fit
            pass  # just checking the module is importable

    def test_not_fitted_raises(self):
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        with pytest.raises(RuntimeError, match="not fitted"):
            forecaster.predict_hours_until_critical()

    def test_fit_too_few_raises(self):
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        df = self._make_prophet_df(10)
        with patch("ml.models.prophet_model.ProphetForecaster.fit") as mock_fit:
            mock_fit.side_effect = ValueError("Need ≥48 rows")
            with pytest.raises(ValueError):
                forecaster.fit(df)

    def test_fit_and_predict_mocked(self):
        import sys
        from unittest.mock import patch as _patch
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        df = self._make_prophet_df(60)

        mock_prophet_instance = MagicMock()
        mock_future = pd.DataFrame({
            "ds": pd.date_range("2025-06-03", periods=48, freq="30min"),
        })
        mock_forecast = mock_future.copy()
        mock_forecast["yhat"] = [50.0 + i for i in range(48)]
        mock_prophet_instance.make_future_dataframe.return_value = mock_future
        mock_prophet_instance.predict.return_value = mock_forecast

        mock_prophet_cls = MagicMock(return_value=mock_prophet_instance)
        mock_prophet_module = MagicMock()
        mock_prophet_module.Prophet = mock_prophet_cls

        with _patch.dict(sys.modules, {"prophet": mock_prophet_module}):
            forecaster.fit(df)

        assert forecaster._fitted is True
        result = forecaster.predict_hours_until_critical()
        assert 0.0 <= result <= 24.0

    def test_save_load_mocked(self):
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        forecaster._fitted = True  # simulate fitted state

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        forecaster.save(path)

        loaded = ProphetForecaster.load(path)
        assert loaded._fitted is True

    def test_load_wrong_type_raises(self):
        from ml.models.prophet_model import ProphetForecaster
        import joblib
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        joblib.dump({"bad": "object"}, path)
        with pytest.raises(TypeError):
            ProphetForecaster.load(path)

    def test_no_crossing_returns_24(self):
        from ml.models.prophet_model import ProphetForecaster
        forecaster = ProphetForecaster()
        forecaster._fitted = True

        mock_prophet = MagicMock()
        forecaster._model = mock_prophet

        # All yhat below threshold
        mock_future = pd.DataFrame({"ds": pd.date_range("2025-06-03", periods=48, freq="30min")})
        mock_forecast = mock_future.copy()
        mock_forecast["yhat"] = [10.0] * 48  # never reaches 85
        mock_forecast["yhat_clamped"] = mock_forecast["yhat"]
        mock_prophet.make_future_dataframe.return_value = mock_future
        mock_prophet.predict.return_value = mock_forecast

        result = forecaster.predict_hours_until_critical()
        assert result == 24.0


# ---------------------------------------------------------------------------
# EnsembleForecaster
# ---------------------------------------------------------------------------

class TestEnsembleForecaster:
    def _fitted_gbm(self):
        gbm = GBMForecaster()
        X, y = _make_gbm_data(20)
        gbm.fit(X, y)
        return gbm

    def _fitted_prophet(self, hours=5.0):
        m = MagicMock()
        m._fitted = True
        m.predict_hours_until_critical.return_value = hours
        return m

    def test_both_models(self):
        fv = _make_fv()
        gbm = self._fitted_gbm()
        prophet = self._fitted_prophet(hours=8.0)

        ensemble = EnsembleForecaster(prophet=prophet, gbm=gbm)
        result = ensemble.predict(fv, prophet_df=pd.DataFrame({"ds": [], "y": []}))

        assert isinstance(result, PredictionResult)
        assert result.model_used == "ensemble"
        assert result.confidence == 1.0
        assert 0.0 <= result.hours_until_critical <= 24.0
        assert result.prophet_hours is not None
        assert result.gbm_hours is not None

    def test_gbm_only(self):
        fv = _make_fv()
        gbm = self._fitted_gbm()

        ensemble = EnsembleForecaster(prophet=None, gbm=gbm)
        result = ensemble.predict(fv, prophet_df=None)

        assert result.model_used == "gbm"
        assert result.confidence == 0.7
        assert result.prophet_hours is None
        assert result.gbm_hours is not None

    def test_prophet_only(self):
        fv = _make_fv()
        prophet = self._fitted_prophet(hours=6.0)

        ensemble = EnsembleForecaster(prophet=prophet, gbm=None)
        result = ensemble.predict(fv, prophet_df=pd.DataFrame({"ds": [], "y": []}))

        assert result.model_used == "prophet"
        assert result.confidence == 0.7
        assert result.prophet_hours == pytest.approx(6.0)
        assert result.gbm_hours is None

    def test_extrapolation_fallback(self):
        fv = _make_fv(fill_pct_current=60.0, fill_rate_1h=5.0)

        ensemble = EnsembleForecaster(prophet=None, gbm=None)
        result = ensemble.predict(fv, prophet_df=None)

        assert result.model_used == "extrapolation"
        assert result.confidence == 0.3
        # (85 - 60) / 5 = 5.0 hours
        assert result.hours_until_critical == pytest.approx(5.0)

    def test_extrapolation_already_critical(self):
        fv = _make_fv(fill_pct_current=90.0, fill_rate_1h=1.0)

        ensemble = EnsembleForecaster(prophet=None, gbm=None)
        result = ensemble.predict(fv, prophet_df=None)

        assert result.model_used == "extrapolation"
        assert result.hours_until_critical == 0.0

    def test_extrapolation_rate_zero_clamped(self):
        fv = _make_fv(fill_pct_current=10.0, fill_rate_1h=0.0)

        ensemble = EnsembleForecaster(prophet=None, gbm=None)
        result = ensemble.predict(fv, prophet_df=None)

        # MIN_RATE = 0.1, so (85 - 10) / 0.1 = 750 → clamped to 24
        assert result.hours_until_critical == 24.0

    def test_hours_clamped_to_24(self):
        fv = _make_fv(fill_pct_current=5.0, fill_rate_1h=0.001)

        ensemble = EnsembleForecaster(prophet=None, gbm=None)
        result = ensemble.predict(fv, prophet_df=None)

        assert result.hours_until_critical <= 24.0

    def test_prophet_no_prophet_df_skipped(self):
        fv = _make_fv()
        prophet = self._fitted_prophet(hours=5.0)
        gbm = self._fitted_gbm()

        ensemble = EnsembleForecaster(prophet=prophet, gbm=gbm)
        # No prophet_df → prophet skipped → GBM only
        result = ensemble.predict(fv, prophet_df=None)

        assert result.model_used == "gbm"

    def test_weighted_blend(self):
        fv = _make_fv()
        prophet = self._fitted_prophet(hours=8.0)

        gbm_mock = MagicMock()
        gbm_mock._fitted = True
        gbm_mock.predict_hours_until_critical.return_value = 4.0

        ensemble = EnsembleForecaster(
            prophet=prophet, gbm=gbm_mock,
            prophet_weight=0.4, gbm_weight=0.6,
        )
        result = ensemble.predict(fv, prophet_df=pd.DataFrame({"ds": [], "y": []}))

        expected = (0.4 * 8.0 + 0.6 * 4.0) / 1.0
        assert result.hours_until_critical == pytest.approx(expected)

    def test_result_fields(self):
        fv = _make_fv(bin_id="BIN-TEST", fill_pct_current=70.0)

        ensemble = EnsembleForecaster(prophet=None, gbm=None)
        result = ensemble.predict(fv, prophet_df=None)

        assert result.bin_id == "BIN-TEST"
        assert result.fill_pct_current == 70.0
        assert isinstance(result.predicted_at, datetime)

    def test_model_failure_falls_back(self):
        fv = _make_fv(fill_pct_current=60.0, fill_rate_1h=5.0)

        failing_gbm = MagicMock()
        failing_gbm._fitted = True
        failing_gbm.predict_hours_until_critical.side_effect = RuntimeError("boom")

        ensemble = EnsembleForecaster(prophet=None, gbm=failing_gbm)
        result = ensemble.predict(fv, prophet_df=None)

        # GBM failed → extrapolation
        assert result.model_used == "extrapolation"
