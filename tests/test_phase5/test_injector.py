"""Unit tests for exogenous/injector.py — fakeredis."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis
import pytest

from exogenous.connectors.calendar import CalendarSnapshot
from exogenous.connectors.traffic import TrafficSnapshot
from exogenous.connectors.weather import WeatherSnapshot
from exogenous.injector import NEUTRAL_DEFAULTS, ExogenousInjector


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _mock_weather(multiplier: float = 1.0, is_raining: bool = False, is_hot: bool = False) -> MagicMock:
    from datetime import datetime, timezone
    m = MagicMock()
    snap = WeatherSnapshot(
        temp_c=30.0,
        condition_code=800,
        condition_description="clear",
        is_raining=is_raining,
        is_hot=is_hot,
        forecast_rain_6h=is_raining,
        weather_fill_multiplier=multiplier,
        outdoor_activity_score=0.5,
        fetched_at=datetime.now(tz=timezone.utc),
    )
    m.get_multiplier = AsyncMock(return_value=multiplier)
    m.get_weather_snapshot = AsyncMock(return_value=snap)
    return m


def _mock_traffic(ratio: float = 0.7) -> MagicMock:
    from datetime import datetime, timezone
    m = MagicMock()
    snap = TrafficSnapshot(
        zone_id="",
        congestion_ratio=ratio,
        is_congested=ratio < 0.5,
        fill_rate_multiplier=1.0 + (1.0 - ratio) * 0.3,
        delay_minutes_per_10km=5.0,
        estimated_truck_delay_min=10.0,
        fetched_at=datetime.now(tz=timezone.utc),
    )
    m.get_multiplier = AsyncMock(return_value=snap.fill_rate_multiplier)
    m.get_traffic_snapshot = AsyncMock(return_value=snap)
    return m


def _mock_calendar(
    multiplier: float = 1.0,
    is_holiday: bool = False,
    days_until: int = 30,
) -> MagicMock:
    from datetime import datetime, timezone
    m = MagicMock()
    snap = CalendarSnapshot(
        is_holiday_today=is_holiday,
        is_active_event_now=multiplier > 1.0,
        active_event_name=None,
        calendar_fill_multiplier=multiplier,
        days_until_next_high_impact=days_until,
        fetched_at=datetime.now(tz=timezone.utc),
    )
    m.get_multiplier = AsyncMock(return_value=multiplier)
    m.get_calendar_snapshot = MagicMock(return_value=snap)
    return m


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_skips_fetch():
    """If combined key exists in Redis, get_snapshot returns without calling fetch."""
    r = _make_redis()
    weather = _mock_weather(1.1)
    traffic = _mock_traffic(0.8)
    calendar = _mock_calendar(1.2)

    inj = ExogenousInjector(r, city="dubai", weather=weather, traffic=traffic, calendar=calendar)

    # Pre-populate cache
    await r.set("exogenous:dubai:combined_multiplier", "1.3", ex=300)

    snap = await inj.get_snapshot()

    assert snap.combined == pytest.approx(1.3)
    weather.get_multiplier.assert_not_called()
    traffic.get_multiplier.assert_not_called()
    calendar.get_multiplier.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_triggers_fetch_and_populates_redis():
    r = _make_redis()
    weather = _mock_weather(1.2)
    traffic = _mock_traffic(0.6)
    calendar = _mock_calendar(1.5)

    inj = ExogenousInjector(r, city="dubai", weather=weather, traffic=traffic, calendar=calendar)

    snap = await inj.get_snapshot(force_refresh=True)

    weather.get_multiplier.assert_called_once()
    traffic.get_multiplier.assert_called_once()
    calendar.get_multiplier.assert_called_once()

    # Combined value should now be in Redis
    cached = await r.get("exogenous:dubai:combined_multiplier")
    assert cached is not None
    assert abs(float(cached) - snap.combined) < 0.001


# ---------------------------------------------------------------------------
# All-sources failure → NEUTRAL_DEFAULTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_sources_failing_returns_neutral_defaults():
    r = _make_redis()
    weather = MagicMock()
    weather.get_multiplier = AsyncMock(side_effect=RuntimeError("boom"))
    weather.get_weather_snapshot = AsyncMock(side_effect=RuntimeError("boom"))
    traffic = MagicMock()
    traffic.get_multiplier = AsyncMock(side_effect=RuntimeError("boom"))
    traffic.get_traffic_snapshot = AsyncMock(side_effect=RuntimeError("boom"))
    calendar = MagicMock()
    calendar.get_multiplier = AsyncMock(side_effect=RuntimeError("boom"))
    calendar.get_calendar_snapshot = MagicMock(side_effect=RuntimeError("boom"))

    inj = ExogenousInjector(r, city="test", weather=weather, traffic=traffic, calendar=calendar)

    features = await inj.get_all_features("Z-TEST")

    # Must not raise, must return neutral defaults
    assert features["weather_fill_multiplier"] == pytest.approx(1.0)
    assert features["is_raining"] is False
    assert features["is_holiday_today"] is False


# ---------------------------------------------------------------------------
# get_all_features
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_all_features_returns_9_keys():
    r = _make_redis()
    weather = _mock_weather(1.3)
    traffic = _mock_traffic(0.4)
    calendar = _mock_calendar(1.9, is_holiday=True, days_until=0)

    inj = ExogenousInjector(r, city="dubai", weather=weather, traffic=traffic, calendar=calendar)
    features = await inj.get_all_features("Z-COMMERCIAL")

    expected_keys = {
        "weather_fill_multiplier",
        "outdoor_activity_score",
        "is_raining",
        "forecast_rain_6h",
        "zone_congestion_ratio",
        "estimated_truck_delay_min",
        "calendar_fill_multiplier",
        "days_until_next_high_impact",
        "is_holiday_today",
    }
    assert expected_keys == set(features.keys())


@pytest.mark.asyncio
async def test_get_all_features_correct_types():
    r = _make_redis()
    weather = _mock_weather(1.0)
    traffic = _mock_traffic(0.7)
    calendar = _mock_calendar(1.0)

    inj = ExogenousInjector(r, city="dubai", weather=weather, traffic=traffic, calendar=calendar)
    features = await inj.get_all_features("")

    assert isinstance(features["weather_fill_multiplier"], float)
    assert isinstance(features["outdoor_activity_score"], float)
    assert isinstance(features["is_raining"], bool)
    assert isinstance(features["forecast_rain_6h"], bool)
    assert isinstance(features["zone_congestion_ratio"], float)
    assert isinstance(features["estimated_truck_delay_min"], float)
    assert isinstance(features["calendar_fill_multiplier"], float)
    assert isinstance(features["days_until_next_high_impact"], int)
    assert isinstance(features["is_holiday_today"], bool)


@pytest.mark.asyncio
async def test_get_all_features_values_propagate_correctly():
    r = _make_redis()
    weather = _mock_weather(multiplier=0.8, is_raining=True)
    traffic = _mock_traffic(ratio=0.4)
    calendar = _mock_calendar(multiplier=1.9, is_holiday=True, days_until=0)

    inj = ExogenousInjector(r, city="dubai", weather=weather, traffic=traffic, calendar=calendar)
    features = await inj.get_all_features("Z-COMMERCIAL")

    assert features["is_raining"] is True
    assert features["zone_congestion_ratio"] == pytest.approx(0.4)
    assert features["is_holiday_today"] is True
    assert features["days_until_next_high_impact"] == 0
    assert features["calendar_fill_multiplier"] == pytest.approx(1.9)


# ---------------------------------------------------------------------------
# NEUTRAL_DEFAULTS
# ---------------------------------------------------------------------------

def test_neutral_defaults_has_all_9_keys():
    expected = {
        "weather_fill_multiplier", "outdoor_activity_score",
        "is_raining", "forecast_rain_6h",
        "zone_congestion_ratio", "estimated_truck_delay_min",
        "calendar_fill_multiplier", "days_until_next_high_impact",
        "is_holiday_today",
    }
    assert set(NEUTRAL_DEFAULTS.keys()) == expected


def test_neutral_defaults_are_sane():
    assert NEUTRAL_DEFAULTS["weather_fill_multiplier"] == pytest.approx(1.0)
    assert NEUTRAL_DEFAULTS["calendar_fill_multiplier"] == pytest.approx(1.0)
    assert NEUTRAL_DEFAULTS["is_raining"] is False
    assert NEUTRAL_DEFAULTS["is_holiday_today"] is False
