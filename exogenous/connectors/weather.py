"""OpenWeatherMap weather connector."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict

from exogenous.base import ExogenousConnector


class _WeatherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    OWM_API_KEY: str = ""
    CITY_LAT: float = 25.2048
    CITY_LNG: float = 55.2708


_SETTINGS = _WeatherSettings()

# OWM condition code ranges for rain detection
_RAIN_CODE_RANGES: list[tuple[int, int]] = [
    (200, 299),  # Thunderstorm
    (300, 399),  # Drizzle
    (500, 599),  # Rain
]

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_HOT_TEMP_C = 35.0

# UAE weekend: Friday (4) and Saturday (5)
_UAE_WEEKEND_DAYS = {4, 5}


@dataclass
class WeatherSnapshot:
    temp_c: float
    condition_code: int
    condition_description: str
    is_raining: bool
    is_hot: bool               # temp_c > 35°C
    forecast_rain_6h: bool     # simplified: mirrors is_raining
    weather_fill_multiplier: float
    outdoor_activity_score: float
    fetched_at: datetime

    @staticmethod
    def compute_fill_multiplier(
        is_raining: bool, is_hot: bool, is_weekend: bool
    ) -> float:
        """Compute weather-driven fill-rate multiplier.

        Rain reduces public bin usage (people stay inside).
        Hot weather + weekend increases outdoor activity → higher fill rates.
        """
        if is_raining:
            return 0.8
        base = 1.0
        if is_hot:
            base += 0.3
        if is_weekend:
            base += 0.2
        return min(base, 3.0)

    @staticmethod
    def compute_outdoor_activity_score(
        is_raining: bool, is_hot: bool, temp_c: float
    ) -> float:
        if is_raining:
            return 0.2
        if is_hot:
            return 0.4
        if temp_c > 28:
            return 0.6
        return 0.8


def _neutral_snapshot() -> WeatherSnapshot:
    return WeatherSnapshot(
        temp_c=30.0,
        condition_code=800,
        condition_description="neutral",
        is_raining=False,
        is_hot=False,
        forecast_rain_6h=False,
        weather_fill_multiplier=1.0,
        outdoor_activity_score=0.5,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class WeatherConnector(ExogenousConnector):
    """Fetches current weather from OpenWeatherMap and derives fill-rate signals."""

    TTL = 1800  # 30 min

    def __init__(
        self,
        redis_client: aioredis.Redis,
        city: str = "dubai",
        lat: float | None = None,
        lng: float | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(redis_client, city)
        self._lat = lat if lat is not None else _SETTINGS.CITY_LAT
        self._lng = lng if lng is not None else _SETTINGS.CITY_LNG
        self._api_key = api_key or _SETTINGS.OWM_API_KEY
        self._last_snapshot: WeatherSnapshot | None = None

    @property
    def connector_name(self) -> str:
        return "weather_multiplier"

    async def fetch(self) -> float:
        snapshot = await self._call_api()
        self._last_snapshot = snapshot
        return snapshot.weather_fill_multiplier

    async def get_weather_snapshot(self) -> WeatherSnapshot:
        """Return a WeatherSnapshot, using in-memory cache when available."""
        cached_float = await self._read_cache()
        if cached_float is not None and self._last_snapshot is not None:
            return self._last_snapshot
        try:
            snapshot = await self._call_api()
            self._last_snapshot = snapshot
            await self._write_cache(snapshot.weather_fill_multiplier)
            return snapshot
        except Exception as exc:
            logger.warning("WeatherConnector.get_weather_snapshot failed: {} — returning neutral", exc)
            return _neutral_snapshot()

    async def _call_api(self) -> WeatherSnapshot:
        if not self._api_key:
            logger.warning("OWM_API_KEY not set — returning neutral weather snapshot")
            return _neutral_snapshot()

        url = "https://api.openweathermap.org/data/2.5/weather"
        params: dict[str, Any] = {
            "lat": self._lat,
            "lon": self._lng,
            "appid": self._api_key,
            "units": "metric",
        }

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    return self._parse_snapshot(resp.json())
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (401, 403):
                        logger.error("OWM auth error ({}): {}", exc.response.status_code, exc)
                        return _neutral_snapshot()
                    last_exc = exc
                except Exception as exc:
                    last_exc = exc

                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))

        raise RuntimeError(
            f"OWM fetch failed after {_MAX_RETRIES} retries: {last_exc}"
        ) from last_exc

    def _parse_snapshot(self, data: dict[str, Any]) -> WeatherSnapshot:
        try:
            code = int(data["weather"][0]["id"])
            description = str(data["weather"][0].get("description", ""))
        except (KeyError, IndexError, TypeError, ValueError):
            code, description = 800, ""

        try:
            temp_c = float(data["main"]["temp"])
        except (KeyError, TypeError, ValueError):
            temp_c = 30.0

        is_raining = any(lo <= code <= hi for lo, hi in _RAIN_CODE_RANGES)
        is_hot = temp_c > _HOT_TEMP_C
        is_weekend = datetime.now(tz=timezone.utc).weekday() in _UAE_WEEKEND_DAYS

        fill_mult = WeatherSnapshot.compute_fill_multiplier(is_raining, is_hot, is_weekend)
        activity = WeatherSnapshot.compute_outdoor_activity_score(is_raining, is_hot, temp_c)

        return WeatherSnapshot(
            temp_c=temp_c,
            condition_code=code,
            condition_description=description,
            is_raining=is_raining,
            is_hot=is_hot,
            forecast_rain_6h=is_raining,
            weather_fill_multiplier=self.clamp(fill_mult),
            outdoor_activity_score=activity,
            fetched_at=datetime.now(tz=timezone.utc),
        )
