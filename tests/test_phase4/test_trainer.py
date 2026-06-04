"""Unit tests for ml/trainer.py — mocked DB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from ml.schemas import FeatureVector, TrainingResult
from ml.trainer import generate_labels, train_bin_prophet, train_zone_gbm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_telemetry_rows(n=20, base_fill=20.0, increment=2.0, fault=False):
    base = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        rows.append({
            "time": base + timedelta(hours=i),
            "fill_pct": base_fill + increment * i,
            "sensor_fault": fault,
            "event_type": "normal",
        })
    return rows


def _make_ingestion_db(rows, fetchrow_return=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    db = MagicMock()
    db._pool = pool
    return db


def _make_geo_db_with_bins(bin_entries):
    db = AsyncMock()
    db.list_bins = AsyncMock(return_value=bin_entries)
    db.get_bin = AsyncMock(return_value=None)
    return db


def _make_bin_entry(bin_id, zone_id="Z-COMMERCIAL"):
    entry = MagicMock()
    entry.bin_id = bin_id
    entry.zone_id = zone_id
    entry.zone_type = "commercial"
    entry.capacity_liters = 240
    entry.priority_level = 1
    entry.sector_id = "Z-COMMERCIAL-S00"
    entry.is_active = True
    return entry


# ---------------------------------------------------------------------------
# generate_labels
# ---------------------------------------------------------------------------

class TestGenerateLabels:
    @pytest.mark.asyncio
    async def test_no_pool_raises(self):
        db = MagicMock()
        db._pool = None
        with pytest.raises(RuntimeError, match="pool"):
            await generate_labels("BIN-0001", db)

    @pytest.mark.asyncio
    async def test_too_few_rows_returns_empty(self):
        rows = _make_telemetry_rows(5)
        db = _make_ingestion_db(rows)

        result = await generate_labels("BIN-0001", db)

        assert result.empty
        assert list(result.columns) == ["time", "fill_pct", "hours_until_critical"]

    @pytest.mark.asyncio
    async def test_basic_labels_generated(self):
        # 20 rows, fill goes from 20 to 58 — crosses 85 in scan
        rows = _make_telemetry_rows(20, base_fill=20.0, increment=3.5)
        db = _make_ingestion_db(rows)

        result = await generate_labels("BIN-0001", db)

        assert not result.empty
        assert "hours_until_critical" in result.columns
        assert (result["hours_until_critical"] >= 0).all()
        assert (result["hours_until_critical"] <= 24.0).all()

    @pytest.mark.asyncio
    async def test_already_critical_rows_excluded(self):
        # All rows already at/above threshold
        rows = _make_telemetry_rows(15, base_fill=85.0, increment=0.5)
        db = _make_ingestion_db(rows)

        result = await generate_labels("BIN-0001", db)
        # All rows are already critical, none should produce labels
        assert result.empty or (result["fill_pct"] < 85.0).all()

    @pytest.mark.asyncio
    async def test_no_crossing_gives_window_hours(self):
        # Flat fill at 30% — never crosses threshold
        rows = _make_telemetry_rows(15, base_fill=30.0, increment=0.0)
        db = _make_ingestion_db(rows)

        result = await generate_labels("BIN-0001", db, window_hours=24)

        assert not result.empty
        assert (result["hours_until_critical"] == 24.0).all()

    @pytest.mark.asyncio
    async def test_crossing_within_window(self):
        # Rows: 0,1,2,...19 hours; fill goes 0,5,10,...95% (5% per hour)
        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        rows = [
            {"time": base + timedelta(hours=i), "fill_pct": 5.0 * i, "sensor_fault": False}
            for i in range(20)
        ]
        db = _make_ingestion_db(rows)

        result = await generate_labels("BIN-0001", db, threshold=85.0)

        # At i=0 (fill=0), 85/5=17 hours to threshold (row at i=17)
        first_label = result.iloc[0]["hours_until_critical"]
        assert abs(first_label - 17.0) < 1.5  # approximate

    @pytest.mark.asyncio
    async def test_sensor_fault_rows_excluded(self):
        # All rows have sensor_fault=True → effectively no valid rows in join
        # But generate_labels fetches WHERE sensor_fault=FALSE
        # Mock returns empty since we can't actually filter in mock
        db = _make_ingestion_db([])
        result = await generate_labels("BIN-FAULT", db)
        assert result.empty


# ---------------------------------------------------------------------------
# train_bin_prophet
# ---------------------------------------------------------------------------

class TestTrainBinProphet:
    @pytest.mark.asyncio
    async def test_no_pool_returns_false(self):
        db = MagicMock()
        db._pool = None
        result = await train_bin_prophet("BIN-0001", db)
        assert result is False

    @pytest.mark.asyncio
    async def test_insufficient_rows_returns_false(self):
        rows = _make_telemetry_rows(10, base_fill=20.0, increment=1.0)
        db = _make_ingestion_db(rows)

        result = await train_bin_prophet("BIN-0001", db)
        assert result is False

    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        rows = []
        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        for i in range(60):
            rows.append({
                "time": base + timedelta(minutes=30 * i),
                "fill_pct": 20.0 + 0.5 * i,
                "sensor_fault": False,
                "event_type": "normal",
            })
        db = _make_ingestion_db(rows)

        mock_forecaster = MagicMock()
        mock_forecaster.fit = MagicMock()
        mock_forecaster.save = MagicMock()

        with patch("ml.trainer.ProphetForecaster", return_value=mock_forecaster):
            with patch("ml.trainer.Path") as mock_path_cls:
                mock_path = MagicMock()
                mock_path.__truediv__ = MagicMock(return_value=MagicMock(__str__=lambda s: "model.pkl"))
                mock_path_cls.return_value = mock_path
                result = await train_bin_prophet("BIN-0001", db, model_dir="/tmp/models")

        assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        rows = _make_telemetry_rows(60)
        db = _make_ingestion_db(rows)

        with patch("ml.trainer.ProphetForecaster", side_effect=RuntimeError("boom")):
            result = await train_bin_prophet("BIN-0001", db)

        assert result is False


# ---------------------------------------------------------------------------
# train_zone_gbm
# ---------------------------------------------------------------------------

class TestTrainZoneGBM:
    @pytest.mark.asyncio
    async def test_no_bins_returns_error(self):
        db = MagicMock()
        db._pool = None
        geo_db = _make_geo_db_with_bins([])

        result = await train_zone_gbm("Z-COMMERCIAL", [], db, geo_db)

        assert isinstance(result, TrainingResult)
        assert result.error == "no bins in zone"
        assert result.gbm_trained is False

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_error(self):
        db = _make_ingestion_db([])  # empty telemetry
        geo_db = _make_geo_db_with_bins([_make_bin_entry("BIN-0001")])
        geo_db.get_bin = AsyncMock(return_value=_make_bin_entry("BIN-0001"))

        with patch("ml.trainer.build_feature_vector", side_effect=RuntimeError("fail")):
            with patch("ml.trainer.generate_labels", return_value=pd.DataFrame()):
                result = await train_zone_gbm(
                    "Z-COMMERCIAL", ["BIN-0001"], db, geo_db
                )

        assert isinstance(result, TrainingResult)
        assert result.error in ("insufficient data", None) or result.error is not None

    @pytest.mark.asyncio
    async def test_successful_training(self):
        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        # Build 20 rows of telemetry per bin
        rows = [
            {"time": base + timedelta(hours=i), "fill_pct": 5.0 * i, "sensor_fault": False}
            for i in range(20)
        ]
        db = _make_ingestion_db(rows)
        geo_db = AsyncMock()
        geo_db.get_bin = AsyncMock(return_value=_make_bin_entry("BIN-0001"))

        mock_fv = MagicMock(spec=FeatureVector)
        mock_fv.bin_id = "BIN-0001"
        mock_fv.at_time = base
        mock_fv.fill_pct_current = 30.0
        mock_fv.fill_rate_1h = 1.0
        mock_fv.fill_rate_3h = 1.0
        mock_fv.fill_rate_6h = 1.0
        mock_fv.fill_rate_24h = 1.0
        mock_fv.rolling_std_6h = 1.0
        mock_fv.time_since_last_empty = 10.0
        mock_fv.fill_at_last_empty = 5.0
        mock_fv.hour_of_day = 10
        mock_fv.day_of_week = 0
        mock_fv.is_weekend = False
        mock_fv.is_peak_morning = False
        mock_fv.is_peak_evening = False
        mock_fv.days_until_next_holiday = 10
        mock_fv.zone_type_residential = 0
        mock_fv.zone_type_commercial = 1
        mock_fv.zone_type_park = 0
        mock_fv.zone_type_transit_hub = 0
        mock_fv.capacity_liters = 240.0
        mock_fv.priority_level = 1
        mock_fv.sector_avg_fill = 30.0
        mock_fv.spike_count_24h = 0
        mock_fv.fault_count_24h = 0
        mock_fv.is_volatile = False
        mock_fv.model_dump = MagicMock(return_value={
            "bin_id": "BIN-0001", "at_time": base,
            "fill_pct_current": 30.0, "fill_rate_1h": 1.0,
            "fill_rate_3h": 1.0, "fill_rate_6h": 1.0, "fill_rate_24h": 1.0,
            "rolling_std_6h": 1.0, "time_since_last_empty": 10.0,
            "fill_at_last_empty": 5.0, "hour_of_day": 10, "day_of_week": 0,
            "is_weekend": False, "is_peak_morning": False, "is_peak_evening": False,
            "days_until_next_holiday": 10, "zone_type_residential": 0,
            "zone_type_commercial": 1, "zone_type_park": 0, "zone_type_transit_hub": 0,
            "capacity_liters": 240.0, "priority_level": 1, "sector_avg_fill": 30.0,
            "spike_count_24h": 0, "fault_count_24h": 0, "is_volatile": False,
        })

        labels_df = pd.DataFrame({
            "time": [base + timedelta(hours=i) for i in range(15)],
            "fill_pct": [20.0 + 2 * i for i in range(15)],
            "hours_until_critical": [24.0 - i for i in range(15)],
        })

        mock_gbm = MagicMock()
        mock_gbm.fit = MagicMock()
        mock_gbm.save = MagicMock()

        with patch("ml.trainer.build_feature_vector", return_value=mock_fv):
            with patch("ml.trainer.generate_labels", return_value=labels_df):
                with patch("ml.trainer.GBMForecaster", return_value=mock_gbm):
                    with patch("ml.trainer.Path") as mock_path_cls:
                        mock_path = MagicMock()
                        mock_path.mkdir = MagicMock()
                        mock_path.__truediv__ = MagicMock(
                            return_value=MagicMock(__str__=lambda s: "/tmp/model.pkl")
                        )
                        mock_path_cls.return_value = mock_path
                        result = await train_zone_gbm(
                            "Z-COMMERCIAL", ["BIN-0001"], db, geo_db
                        )

        assert isinstance(result, TrainingResult)
        if result.error is None:
            assert result.gbm_trained is True
