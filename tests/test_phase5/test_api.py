"""FastAPI endpoint tests for exogenous/api.py — fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from exogenous.api import app
from exogenous.connectors.calendar import CalendarSnapshot
from exogenous.connectors.traffic import TrafficSnapshot
from exogenous.connectors.weather import WeatherSnapshot
from exogenous.injector import NEUTRAL_DEFAULTS


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_weather_snap(**overrides) -> WeatherSnapshot:
    defaults = dict(
        temp_c=32.0, condition_code=800, condition_description="clear sky",
        is_raining=False, is_hot=False, forecast_rain_6h=False,
        weather_fill_multiplier=1.0, outdoor_activity_score=0.7,
        fetched_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return WeatherSnapshot(**defaults)


def _make_traffic_snap(**overrides) -> TrafficSnapshot:
    defaults = dict(
        zone_id="", congestion_ratio=0.7, is_congested=False,
        fill_rate_multiplier=1.09, delay_minutes_per_10km=4.3,
        estimated_truck_delay_min=8.6,
        fetched_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return TrafficSnapshot(**defaults)


def _make_calendar_snap(**overrides) -> CalendarSnapshot:
    defaults = dict(
        is_holiday_today=False, is_active_event_now=False,
        active_event_name=None, calendar_fill_multiplier=1.0,
        days_until_next_high_impact=10,
        fetched_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return CalendarSnapshot(**defaults)


@pytest.fixture(autouse=True)
def mock_services(monkeypatch):
    import exogenous.api as api_module

    mock_weather = MagicMock()
    mock_weather.get_weather_snapshot = AsyncMock(return_value=_make_weather_snap())
    mock_weather.get_multiplier = AsyncMock(return_value=1.0)

    mock_traffic = MagicMock()
    mock_traffic.get_traffic_snapshot = AsyncMock(return_value=_make_traffic_snap())
    mock_traffic.get_multiplier = AsyncMock(return_value=1.09)

    mock_calendar = MagicMock()
    mock_calendar.get_calendar_snapshot = MagicMock(return_value=_make_calendar_snap())
    mock_calendar.multiplier_for_date = MagicMock(return_value=1.0)
    mock_calendar._event_name_for_date = MagicMock(return_value=None)
    mock_calendar.get_multiplier = AsyncMock(return_value=1.0)

    mock_injector = MagicMock()
    mock_injector.get_all_features = AsyncMock(return_value=NEUTRAL_DEFAULTS.copy())

    monkeypatch.setattr(api_module, "_weather", mock_weather)
    monkeypatch.setattr(api_module, "_traffic", mock_traffic)
    monkeypatch.setattr(api_module, "_calendar", mock_calendar)
    monkeypatch.setattr(api_module, "injector", mock_injector)

    return mock_weather, mock_traffic, mock_calendar, mock_injector


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["connectors"]["weather"]["ready"] is True
    assert data["connectors"]["traffic"]["ready"] is True
    assert data["connectors"]["calendar"]["ready"] is True


def test_health_degraded_when_injector_none(monkeypatch):
    import exogenous.api as api_module
    monkeypatch.setattr(api_module, "injector", None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /weather
# ---------------------------------------------------------------------------

def test_get_weather_ok():
    r = client.get("/weather")
    assert r.status_code == 200
    data = r.json()
    assert "condition_code" in data
    assert "is_raining" in data
    assert "weather_fill_multiplier" in data
    assert "temp_c" in data


def test_get_weather_service_not_ready(monkeypatch):
    import exogenous.api as api_module
    monkeypatch.setattr(api_module, "injector", None)
    r = client.get("/weather")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /weather/features
# ---------------------------------------------------------------------------

def test_get_weather_features_ok():
    r = client.get("/weather/features")
    assert r.status_code == 200
    data = r.json()
    assert "weather_fill_multiplier" in data
    assert "is_raining" in data
    assert "forecast_rain_6h" in data
    assert "outdoor_activity_score" in data


# ---------------------------------------------------------------------------
# GET /traffic
# ---------------------------------------------------------------------------

def test_get_traffic_ok():
    r = client.get("/traffic")
    assert r.status_code == 200
    data = r.json()
    assert "congestion_ratio" in data
    assert "is_congested" in data
    assert "delay_minutes_per_10km" in data


# ---------------------------------------------------------------------------
# GET /traffic/{zone_id}
# ---------------------------------------------------------------------------

def test_get_traffic_zone_ok():
    r = client.get("/traffic/Z-COMMERCIAL")
    assert r.status_code == 200
    data = r.json()
    assert "congestion_ratio" in data


# ---------------------------------------------------------------------------
# GET /traffic/features/{zone_id}
# ---------------------------------------------------------------------------

def test_get_traffic_features_ok():
    r = client.get("/traffic/features/Z-COMMERCIAL")
    assert r.status_code == 200
    data = r.json()
    assert data["zone_id"] == "Z-COMMERCIAL"
    assert "zone_congestion_ratio" in data
    assert "estimated_truck_delay_min" in data


# ---------------------------------------------------------------------------
# GET /calendar
# ---------------------------------------------------------------------------

def test_get_calendar_ok():
    r = client.get("/calendar")
    assert r.status_code == 200
    data = r.json()
    assert "today" in data
    assert "is_holiday_today" in data
    assert "calendar_fill_multiplier" in data
    assert "days_until_next_high_impact" in data


def test_get_calendar_service_not_ready(monkeypatch):
    import exogenous.api as api_module
    monkeypatch.setattr(api_module, "injector", None)
    r = client.get("/calendar")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /calendar/features/{zone_id}
# ---------------------------------------------------------------------------

def test_get_calendar_features_ok():
    r = client.get("/calendar/features/Z-COMMERCIAL")
    assert r.status_code == 200
    data = r.json()
    assert data["zone_id"] == "Z-COMMERCIAL"
    assert "calendar_fill_multiplier" in data
    assert "is_holiday_today" in data
    assert "days_until_next_high_impact" in data


# ---------------------------------------------------------------------------
# GET /inject/{zone_id}
# ---------------------------------------------------------------------------

def test_inject_ok():
    r = client.get("/inject/Z-COMMERCIAL")
    assert r.status_code == 200
    data = r.json()
    assert data["zone_id"] == "Z-COMMERCIAL"
    features = data["features"]
    for key in NEUTRAL_DEFAULTS:
        assert key in features


def test_inject_service_not_ready(monkeypatch):
    import exogenous.api as api_module
    monkeypatch.setattr(api_module, "injector", None)
    r = client.get("/inject/Z-COMMERCIAL")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------

def test_refresh_all_ok():
    r = client.post("/refresh")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "weather" in data["refreshed"]
    assert "traffic" in data["refreshed"]
    assert "calendar" in data["refreshed"]


def test_refresh_all_service_not_ready(monkeypatch):
    import exogenous.api as api_module
    monkeypatch.setattr(api_module, "injector", None)
    r = client.post("/refresh")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /refresh/{source}
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", ["weather", "traffic", "calendar"])
def test_refresh_single_source_ok(source):
    r = client.post(f"/refresh/{source}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert source in data["refreshed"]


def test_refresh_unknown_source_returns_422():
    r = client.post("/refresh/unknown_source")
    assert r.status_code == 422
