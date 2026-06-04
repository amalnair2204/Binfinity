"""Exogenous data FastAPI server. Runs on port 8004."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

from exogenous.connectors.calendar import CalendarConnector, CalendarSnapshot
from exogenous.connectors.traffic import TrafficConnector, TrafficSnapshot
from exogenous.connectors.weather import WeatherConnector, WeatherSnapshot
from exogenous.injector import NEUTRAL_DEFAULTS, ExogenousInjector
from exogenous.scheduler import run_refresh_loop

app = FastAPI(title="Binfinity Exogenous Data API", version="1.0.0")

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_CITY = os.getenv("CITY_NAME", "dubai").lower()

injector: ExogenousInjector | None = None
_weather: WeatherConnector | None = None
_traffic: TrafficConnector | None = None
_calendar: CalendarConnector | None = None
_refresh_task: asyncio.Task | None = None  # type: ignore[type-arg]
_last_fetch: dict[str, Optional[str]] = {
    "weather": None,
    "traffic": None,
    "calendar": None,
}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    global injector, _weather, _traffic, _calendar, _refresh_task
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(_REDIS_URL, decode_responses=True)
    _weather = WeatherConnector(redis_client, city=_CITY)
    _traffic = TrafficConnector(redis_client, city=_CITY)
    _calendar = CalendarConnector(redis_client, city=_CITY)
    injector = ExogenousInjector(
        redis_client,
        city=_CITY,
        weather=_weather,
        traffic=_traffic,
        calendar=_calendar,
    )
    _refresh_task = asyncio.create_task(
        run_refresh_loop(_weather, _traffic, _calendar)
    )
    logger.info("Exogenous API ready on port 8004")


@app.on_event("shutdown")
async def shutdown() -> None:
    if _refresh_task is not None:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class WeatherResponse(BaseModel):
    temp_c: float
    condition_code: int
    condition_description: str
    is_raining: bool
    is_hot: bool
    forecast_rain_6h: bool
    weather_fill_multiplier: float
    outdoor_activity_score: float
    fetched_at: datetime


class WeatherFeaturesResponse(BaseModel):
    weather_fill_multiplier: float
    outdoor_activity_score: float
    is_raining: bool
    forecast_rain_6h: bool


class TrafficResponse(BaseModel):
    zone_id: str
    congestion_ratio: float
    is_congested: bool
    fill_rate_multiplier: float
    delay_minutes_per_10km: float
    estimated_truck_delay_min: float
    fetched_at: datetime


class TrafficFeaturesResponse(BaseModel):
    zone_id: str
    zone_congestion_ratio: float
    estimated_truck_delay_min: float
    is_congested: bool


class CalendarEventItem(BaseModel):
    name: Optional[str] = None
    multiplier: float
    is_high_impact: bool


class CalendarResponse(BaseModel):
    today: str
    tomorrow: str
    is_holiday_today: bool
    is_active_event_now: bool
    active_event_name: Optional[str] = None
    calendar_fill_multiplier: float
    days_until_next_high_impact: int
    today_events: list[CalendarEventItem] = []
    tomorrow_events: list[CalendarEventItem] = []


class CalendarFeaturesResponse(BaseModel):
    zone_id: str
    calendar_fill_multiplier: float
    days_until_next_high_impact: int
    is_holiday_today: bool


class InjectResponse(BaseModel):
    zone_id: str
    features: dict[str, Any]


class RefreshResponse(BaseModel):
    status: str
    refreshed: list[str]


def _snapshot_to_weather_response(s: WeatherSnapshot) -> WeatherResponse:
    return WeatherResponse(
        temp_c=s.temp_c,
        condition_code=s.condition_code,
        condition_description=s.condition_description,
        is_raining=s.is_raining,
        is_hot=s.is_hot,
        forecast_rain_6h=s.forecast_rain_6h,
        weather_fill_multiplier=s.weather_fill_multiplier,
        outdoor_activity_score=s.outdoor_activity_score,
        fetched_at=s.fetched_at,
    )


def _snapshot_to_traffic_response(s: TrafficSnapshot) -> TrafficResponse:
    return TrafficResponse(
        zone_id=s.zone_id,
        congestion_ratio=s.congestion_ratio,
        is_congested=s.is_congested,
        fill_rate_multiplier=s.fill_rate_multiplier,
        delay_minutes_per_10km=s.delay_minutes_per_10km,
        estimated_truck_delay_min=s.estimated_truck_delay_min,
        fetched_at=s.fetched_at,
    )


def _require_ready() -> None:
    if injector is None or _weather is None or _traffic is None or _calendar is None:
        raise HTTPException(status_code=503, detail="exogenous service not ready")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if injector is not None else "degraded",
        "connectors": {
            "weather": {"ready": _weather is not None, "last_fetch": _last_fetch["weather"]},
            "traffic": {"ready": _traffic is not None, "last_fetch": _last_fetch["traffic"]},
            "calendar": {"ready": _calendar is not None, "last_fetch": _last_fetch["calendar"]},
        },
    }


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

@app.get("/weather", response_model=WeatherResponse)
async def get_weather() -> WeatherResponse:
    _require_ready()
    assert _weather is not None
    snap = await _weather.get_weather_snapshot()
    _last_fetch["weather"] = snap.fetched_at.isoformat()
    return _snapshot_to_weather_response(snap)


@app.get("/weather/features", response_model=WeatherFeaturesResponse)
async def get_weather_features() -> WeatherFeaturesResponse:
    _require_ready()
    assert _weather is not None
    snap = await _weather.get_weather_snapshot()
    return WeatherFeaturesResponse(
        weather_fill_multiplier=snap.weather_fill_multiplier,
        outdoor_activity_score=snap.outdoor_activity_score,
        is_raining=snap.is_raining,
        forecast_rain_6h=snap.forecast_rain_6h,
    )


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------

@app.get("/traffic", response_model=TrafficResponse)
async def get_traffic() -> TrafficResponse:
    _require_ready()
    assert _traffic is not None
    snap = await _traffic.get_traffic_snapshot()
    _last_fetch["traffic"] = snap.fetched_at.isoformat()
    return _snapshot_to_traffic_response(snap)


@app.get("/traffic/{zone_id}", response_model=TrafficResponse)
async def get_traffic_zone(zone_id: str) -> TrafficResponse:
    _require_ready()
    assert _traffic is not None
    snap = await _traffic.get_traffic_snapshot(zone_id=zone_id)
    return _snapshot_to_traffic_response(snap)


@app.get("/traffic/features/{zone_id}", response_model=TrafficFeaturesResponse)
async def get_traffic_features(zone_id: str) -> TrafficFeaturesResponse:
    _require_ready()
    assert _traffic is not None
    snap = await _traffic.get_traffic_snapshot(zone_id=zone_id)
    return TrafficFeaturesResponse(
        zone_id=zone_id,
        zone_congestion_ratio=snap.congestion_ratio,
        estimated_truck_delay_min=snap.estimated_truck_delay_min,
        is_congested=snap.is_congested,
    )


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

@app.get("/calendar", response_model=CalendarResponse)
async def get_calendar() -> CalendarResponse:
    _require_ready()
    assert _calendar is not None
    from datetime import timedelta
    today = datetime.now(tz=timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    today_snap = _calendar.get_calendar_snapshot()
    today_mult = today_snap.calendar_fill_multiplier
    tomorrow_mult = _calendar.multiplier_for_date(tomorrow)

    today_event = CalendarEventItem(
        name=today_snap.active_event_name,
        multiplier=today_mult,
        is_high_impact=today_mult >= 1.5,
    )
    tomorrow_snap = _calendar.get_calendar_snapshot.__func__(_calendar) if False else None
    del tomorrow_snap
    tomorrow_name = _calendar._event_name_for_date(tomorrow, "")

    return CalendarResponse(
        today=today.isoformat(),
        tomorrow=tomorrow.isoformat(),
        is_holiday_today=today_snap.is_holiday_today,
        is_active_event_now=today_snap.is_active_event_now,
        active_event_name=today_snap.active_event_name,
        calendar_fill_multiplier=today_mult,
        days_until_next_high_impact=today_snap.days_until_next_high_impact,
        today_events=[today_event] if today_mult > 1.0 else [],
        tomorrow_events=(
            [CalendarEventItem(name=tomorrow_name, multiplier=tomorrow_mult, is_high_impact=tomorrow_mult >= 1.5)]
            if tomorrow_mult > 1.0 else []
        ),
    )


@app.get("/calendar/features/{zone_id}", response_model=CalendarFeaturesResponse)
async def get_calendar_features(zone_id: str) -> CalendarFeaturesResponse:
    _require_ready()
    assert _calendar is not None
    snap = _calendar.get_calendar_snapshot(zone_id=zone_id)
    return CalendarFeaturesResponse(
        zone_id=zone_id,
        calendar_fill_multiplier=snap.calendar_fill_multiplier,
        days_until_next_high_impact=snap.days_until_next_high_impact,
        is_holiday_today=snap.is_holiday_today,
    )


# ---------------------------------------------------------------------------
# Inject
# ---------------------------------------------------------------------------

@app.get("/inject/{zone_id}", response_model=InjectResponse)
async def inject_features(zone_id: str) -> InjectResponse:
    _require_ready()
    assert injector is not None
    features = await injector.get_all_features(zone_id=zone_id)
    return InjectResponse(zone_id=zone_id, features=features)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

@app.post("/refresh", response_model=RefreshResponse)
async def refresh_all() -> RefreshResponse:
    _require_ready()
    assert _weather is not None and _traffic is not None and _calendar is not None
    results: list[str] = []
    for name, connector in [("weather", _weather), ("traffic", _traffic), ("calendar", _calendar)]:
        try:
            await connector.get_multiplier()
            results.append(name)
        except Exception as exc:
            logger.warning("Force refresh failed for {}: {}", name, exc)
    return RefreshResponse(status="ok", refreshed=results)


@app.post("/refresh/{source}", response_model=RefreshResponse)
async def refresh_source(source: str) -> RefreshResponse:
    _require_ready()
    connector_map = {
        "weather": _weather,
        "traffic": _traffic,
        "calendar": _calendar,
    }
    connector = connector_map.get(source)
    if connector is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source {source!r}. Valid: weather, traffic, calendar",
        )
    try:
        await connector.get_multiplier()
    except Exception as exc:
        logger.warning("Force refresh failed for {}: {}", source, exc)
        return RefreshResponse(status="error", refreshed=[])
    return RefreshResponse(status="ok", refreshed=[source])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
