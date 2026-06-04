"""Tests for feedback/accuracy.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from feedback.accuracy import (
    PredictionAccuracyRecord,
    refresh_fleet_accuracy_cache,
    update_redis_accuracy_cache,
)


def _make_record(predicted_hours=2.0, actual_hours=3.5, bin_id="BIN-001"):
    abs_err = abs(predicted_hours - actual_hours)
    return PredictionAccuracyRecord(
        bin_id=bin_id,
        prediction_id=f"{bin_id}:2026-06-03T08:00:00+00:00",
        predicted_at=datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc),
        emptied_at=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
        predicted_hours=predicted_hours,
        actual_hours=actual_hours,
        absolute_error_hours=abs_err,
        within_1h=abs_err <= 1.0,
        within_2h=abs_err <= 2.0,
        model_used="ensemble",
        fill_pct_at_prediction=75.0,
        zone_id="Z-01",
    )


def test_absolute_error_computed_correctly():
    record = _make_record(predicted_hours=2.0, actual_hours=3.5)
    assert record.absolute_error_hours == pytest.approx(1.5)


def test_within_1h_true_when_error_at_most_1h():
    record = _make_record(predicted_hours=2.0, actual_hours=2.8)
    assert record.within_1h is True


def test_within_1h_false_when_error_exceeds_1h():
    record = _make_record(predicted_hours=2.0, actual_hours=3.5)
    assert record.within_1h is False


def test_actual_hours_from_timestamp_delta():
    predicted_at = datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)
    emptied_at = datetime(2026, 6, 3, 11, 30, tzinfo=timezone.utc)
    actual_hours = (emptied_at - predicted_at).total_seconds() / 3600.0
    assert actual_hours == pytest.approx(3.5)


@pytest.mark.asyncio
async def test_update_redis_mae_7d_key(fake_redis, mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={"mae": 1.5, "within1h_pct": 0.6, "n_events": 10}
    )
    await update_redis_accuracy_cache(fake_redis, pool, "BIN-001")
    val = await fake_redis.get("ml:accuracy:BIN-001:mae_7d")
    assert val is not None
    assert float(val) == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_update_redis_within1h_7d_key(fake_redis, mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={"mae": 1.5, "within1h_pct": 0.6, "n_events": 10}
    )
    await update_redis_accuracy_cache(fake_redis, pool, "BIN-001")
    val = await fake_redis.get("ml:accuracy:BIN-001:within1h_7d")
    assert val is not None
    assert float(val) == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_refresh_fleet_cache_sets_fleet_mae_key(fake_redis, mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={"mae": 2.1, "within1h_pct": 0.55, "n_events": 200}
    )
    await refresh_fleet_accuracy_cache(fake_redis, pool)
    val = await fake_redis.get("ml:accuracy:fleet:mae_7d")
    assert val is not None
    assert float(val) == pytest.approx(2.1)
