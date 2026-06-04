"""Unit tests for ml/features.py — fully mocked DB."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ml.features import (
    _days_until_next_holiday,
    _UAE_HOLIDAYS,
    _rate,
    build_feature_matrix,
    build_feature_vector,
)
from ml.schemas import FeatureVector


# ---------------------------------------------------------------------------
# _days_until_next_holiday
# ---------------------------------------------------------------------------

def test_days_until_holiday_on_holiday():
    holiday = next(iter(_UAE_HOLIDAYS))
    assert _days_until_next_holiday(holiday) == 0


def test_days_until_holiday_capped_at_30():
    # A date far from any holiday
    d = date(2025, 7, 15)
    result = _days_until_next_holiday(d)
    assert 0 <= result <= 30


def test_days_until_holiday_approaching():
    # Day before UAE National Day 2026 (Dec 2)
    d = date(2026, 12, 1)
    result = _days_until_next_holiday(d)
    assert result == 0  # Dec 1 is itself a holiday


def test_days_until_holiday_one_day_before():
    # Nov 30 2026 — next holiday is Dec 1
    d = date(2026, 11, 30)
    result = _days_until_next_holiday(d)
    assert result == 1


# ---------------------------------------------------------------------------
# _rate
# ---------------------------------------------------------------------------

def _make_rows(fills, base_time=None):
    base_time = base_time or datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, f in enumerate(fills):
        rows.append({
            "time": base_time + timedelta(minutes=30 * i),
            "fill_pct": f,
            "sensor_fault": False,
        })
    return rows


def test_rate_zero_with_one_row():
    rows = _make_rows([50.0])
    assert _rate(rows, 2) == 0.0


def test_rate_zero_with_empty():
    assert _rate([], 2) == 0.0


def test_rate_positive():
    rows = _make_rows([10.0, 20.0])  # +10% in 0.5 hours = 20 %/hr
    result = _rate(rows, 2)
    assert abs(result - 20.0) < 0.01


def test_rate_negative():
    rows = _make_rows([80.0, 40.0])  # bin was emptied
    result = _rate(rows, 2)
    assert result < 0


def test_rate_zero_delta_time():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"time": base, "fill_pct": 50.0, "sensor_fault": False},
        {"time": base, "fill_pct": 60.0, "sensor_fault": False},
    ]
    assert _rate(rows, 2) == 0.0


def test_rate_uses_last_n():
    rows = _make_rows([10.0, 20.0, 30.0, 40.0, 50.0])
    rate = _rate(rows, 2)
    # Only last 2 rows: 40->50 in 0.5h = 20 %/hr
    assert abs(rate - 20.0) < 0.01


# ---------------------------------------------------------------------------
# Helpers for mocked DB
# ---------------------------------------------------------------------------

def _make_pool_conn(rows):
    """Return a minimal asyncpg pool mock that returns *rows* from fetch/fetchrow."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.fetchrow = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool, conn


def _make_ingestion_db(telemetry_rows, empty_row=None, avg_row=None):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=telemetry_rows)
    if empty_row is not None or avg_row is not None:
        conn.fetchrow = AsyncMock(side_effect=[empty_row, avg_row])
    else:
        conn.fetchrow = AsyncMock(return_value=None)

    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))

    db = MagicMock()
    db._pool = pool
    return db


def _make_geo_db(entry=None):
    db = AsyncMock()
    db.get_bin = AsyncMock(return_value=entry)
    return db


def _make_bin_entry():
    entry = MagicMock()
    entry.capacity_liters = 240
    entry.priority_level = 2
    entry.zone_type = "commercial"
    entry.sector_id = "Z-COMMERCIAL-S00"
    return entry


def _make_telemetry(n=48, base_fill=30.0, increment=0.5):
    base = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        rows.append({
            "time": base + timedelta(minutes=30 * i),
            "fill_pct": base_fill + increment * i,
            "sensor_fault": False,
            "event_type": "normal",
        })
    return rows


# ---------------------------------------------------------------------------
# build_feature_vector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_feature_vector_no_pool():
    from unittest.mock import MagicMock
    ingestion_db = MagicMock()
    ingestion_db._pool = None
    geo_db = _make_geo_db()
    with pytest.raises(RuntimeError, match="pool"):
        await build_feature_vector("BIN-0001", ingestion_db, geo_db)


@pytest.mark.asyncio
async def test_build_feature_vector_basic():
    rows = _make_telemetry(48)
    ingestion_db = _make_ingestion_db(rows, empty_row=None, avg_row=None)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    at = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert isinstance(fv, FeatureVector)
    assert fv.bin_id == "BIN-0001"
    assert 0.0 <= fv.fill_pct_current <= 100.0
    assert fv.hour_of_day == 8
    assert fv.capacity_liters == 240.0
    assert fv.priority_level == 2
    assert fv.zone_type_commercial == 1
    assert fv.zone_type_residential == 0


@pytest.mark.asyncio
async def test_build_feature_vector_no_rows():
    ingestion_db = _make_ingestion_db([], empty_row=None, avg_row=None)
    geo_db = _make_geo_db()

    fv = await build_feature_vector("BIN-EMPTY", ingestion_db, geo_db)

    assert fv.fill_pct_current == 0.0
    assert fv.fill_rate_1h == 0.0
    assert fv.rolling_std_6h == 0.0
    assert fv.time_since_last_empty == 168.0


@pytest.mark.asyncio
async def test_build_feature_vector_with_empty_event():
    rows = _make_telemetry(10)
    base = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc)
    empty_row_mock = MagicMock()
    empty_row_mock.__getitem__ = lambda self, k: base if k == "time" else 5.0
    # simpler: use dict
    empty_row = {"time": base, "fill_pct": 5.0}

    ingestion_db = _make_ingestion_db(rows, empty_row=empty_row, avg_row=None)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    at = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert fv.time_since_last_empty == pytest.approx(12.0)
    assert fv.fill_at_last_empty == 5.0


@pytest.mark.asyncio
async def test_build_feature_vector_weekend():
    rows = _make_telemetry(10)
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    # Saturday = weekday 5
    at = datetime(2025, 6, 7, 10, 0, tzinfo=timezone.utc)  # Saturday
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert fv.is_weekend is True
    assert fv.day_of_week == 5


@pytest.mark.asyncio
async def test_build_feature_vector_peak_morning():
    rows = _make_telemetry(10)
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    at = datetime(2025, 6, 2, 8, 0, tzinfo=timezone.utc)  # Monday 08:00
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert fv.is_peak_morning is True
    assert fv.is_peak_evening is False


@pytest.mark.asyncio
async def test_build_feature_vector_peak_evening():
    rows = _make_telemetry(10)
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    at = datetime(2025, 6, 2, 18, 0, tzinfo=timezone.utc)  # 18:00
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert fv.is_peak_morning is False
    assert fv.is_peak_evening is True


@pytest.mark.asyncio
async def test_build_feature_vector_peak_boundary_excluded():
    rows = _make_telemetry(10)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    # Hour 9 is NOT peak morning (exclusive upper bound)
    ingestion_db = _make_ingestion_db(rows)
    at = datetime(2025, 6, 2, 9, 0, tzinfo=timezone.utc)
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)
    assert fv.is_peak_morning is False

    # Hour 20 is NOT peak evening (exclusive upper bound)
    ingestion_db2 = _make_ingestion_db(rows)
    at = datetime(2025, 6, 2, 20, 0, tzinfo=timezone.utc)
    fv = await build_feature_vector("BIN-0001", ingestion_db2, geo_db, at_time=at)
    assert fv.is_peak_evening is False


@pytest.mark.asyncio
async def test_build_feature_vector_volatile():
    # Create rows with high variance fill_pct
    base = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(24):
        fill = 10.0 if i % 2 == 0 else 90.0  # alternating — high std
        rows.append({
            "time": base + timedelta(minutes=30 * i),
            "fill_pct": fill,
            "sensor_fault": False,
            "event_type": "normal",
        })

    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db)
    assert fv.is_volatile is True
    assert fv.rolling_std_6h > 8.0


@pytest.mark.asyncio
async def test_build_feature_vector_no_geo_entry():
    rows = _make_telemetry(10)
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=None)

    fv = await build_feature_vector("BIN-UNKNOWN", ingestion_db, geo_db)

    assert fv.capacity_liters == 120.0
    assert fv.priority_level == 1
    assert fv.sector_avg_fill == 0.0


@pytest.mark.asyncio
async def test_build_feature_vector_spike_and_fault_counts():
    base = datetime(2025, 6, 1, 8, 0, tzinfo=timezone.utc)
    rows = [
        {"time": base + timedelta(hours=i), "fill_pct": 50.0,
         "sensor_fault": (i == 1), "event_type": "spike" if i == 2 else "normal"}
        for i in range(10)
    ]
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    at = base + timedelta(hours=10)
    fv = await build_feature_vector("BIN-0001", ingestion_db, geo_db, at_time=at)

    assert fv.spike_count_24h == 1
    assert fv.fault_count_24h == 1


# ---------------------------------------------------------------------------
# build_feature_matrix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_feature_matrix_empty_on_all_fail():
    ingestion_db = MagicMock()
    ingestion_db._pool = None  # will cause RuntimeError in build_feature_vector
    geo_db = _make_geo_db()

    df = await build_feature_matrix(["BIN-X"], ingestion_db, geo_db)
    assert df.empty


@pytest.mark.asyncio
async def test_build_feature_matrix_two_bins():
    rows = _make_telemetry(10)
    ingestion_db = _make_ingestion_db(rows)
    geo_db = _make_geo_db(entry=_make_bin_entry())

    df = await build_feature_matrix(["BIN-A", "BIN-B"], ingestion_db, geo_db)

    assert len(df) == 2
    assert "bin_id" not in df.columns
    assert "at_time" not in df.columns
    assert "fill_pct_current" in df.columns
