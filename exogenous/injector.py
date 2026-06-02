"""Redis-first exogenous multiplier injector."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import redis.asyncio as aioredis
from loguru import logger

from exogenous.connectors.calendar import CalendarConnector
from exogenous.connectors.traffic import TrafficConnector
from exogenous.connectors.weather import WeatherConnector

_COMBINED_TTL = 300  # 5 min

NEUTRAL_DEFAULTS: dict[str, Any] = {
    "weather_fill_multiplier": 1.0,
    "outdoor_activity_score": 0.5,
    "is_raining": False,
    "forecast_rain_6h": False,
    "zone_congestion_ratio": 0.7,
    "estimated_truck_delay_min": 0.0,
    "calendar_fill_multiplier": 1.0,
    "days_until_next_high_impact": 30,
    "is_holiday_today": False,
}


@dataclass
class ExogenousSnapshot:
    weather: float
    traffic: float
    calendar: float
    combined: float


class ExogenousInjector:
    """Aggregates weather, traffic, and calendar multipliers into one signal.

    combined = geometric mean of the three components, clamped to [0.5, 3.0].
    Neutral default: 1.0 for all components.
    """

    _COMBINED_KEY = "exogenous:{city}:combined_multiplier"

    def __init__(
        self,
        redis_client: aioredis.Redis,
        city: str = "dubai",
        weather: Optional[WeatherConnector] = None,
        traffic: Optional[TrafficConnector] = None,
        calendar: Optional[CalendarConnector] = None,
    ) -> None:
        self._redis = redis_client
        self._city = city.lower()
        self._weather = weather or WeatherConnector(redis_client, city)
        self._traffic = traffic or TrafficConnector(redis_client, city)
        self._calendar = calendar or CalendarConnector(redis_client, city)
        self._combined_key = self._COMBINED_KEY.format(city=self._city)

    async def get_snapshot(self, force_refresh: bool = False) -> ExogenousSnapshot:
        """Return exogenous snapshot, using Redis cache when available."""
        if not force_refresh:
            cached = await self._read_combined_cache()
            if cached is not None:
                return ExogenousSnapshot(
                    weather=1.0, traffic=1.0, calendar=1.0, combined=cached
                )

        weather_m = await self._weather.get_multiplier()
        traffic_m = await self._traffic.get_multiplier()
        calendar_m = await self._calendar.get_multiplier()

        combined = self._combine(weather_m, traffic_m, calendar_m)
        await self._write_combined_cache(combined)

        logger.debug(
            "Exogenous snapshot — weather={:.3f} traffic={:.3f} calendar={:.3f} combined={:.3f}",
            weather_m, traffic_m, calendar_m, combined,
        )
        return ExogenousSnapshot(
            weather=weather_m,
            traffic=traffic_m,
            calendar=calendar_m,
            combined=combined,
        )

    async def get_combined_multiplier(self) -> float:
        return (await self.get_snapshot()).combined

    async def get_all_features(self, zone_id: str = "") -> dict[str, Any]:
        """Return the 9 exogenous ML features for *zone_id*.

        Returns NEUTRAL_DEFAULTS on any failure — never raises.
        """
        try:
            w_snap = await self._weather.get_weather_snapshot()
            t_snap = await self._traffic.get_traffic_snapshot(zone_id)
            c_snap = self._calendar.get_calendar_snapshot(zone_id)

            return {
                "weather_fill_multiplier": w_snap.weather_fill_multiplier,
                "outdoor_activity_score": w_snap.outdoor_activity_score,
                "is_raining": w_snap.is_raining,
                "forecast_rain_6h": w_snap.forecast_rain_6h,
                "zone_congestion_ratio": t_snap.congestion_ratio,
                "estimated_truck_delay_min": t_snap.estimated_truck_delay_min,
                "calendar_fill_multiplier": c_snap.calendar_fill_multiplier,
                "days_until_next_high_impact": c_snap.days_until_next_high_impact,
                "is_holiday_today": c_snap.is_holiday_today,
            }
        except Exception as exc:
            logger.warning("get_all_features failed for zone {}: {} — returning neutral defaults", zone_id, exc)
            return NEUTRAL_DEFAULTS.copy()

    @staticmethod
    def _combine(weather: float, traffic: float, calendar: float) -> float:
        combined = (weather * traffic * calendar) ** (1.0 / 3.0)
        return max(0.5, min(3.0, combined))

    async def _read_combined_cache(self) -> Optional[float]:
        try:
            raw = await self._redis.get(self._combined_key)
            if raw is not None:
                return float(raw)
        except Exception as exc:
            logger.debug("Redis read (combined) failed: {}", exc)
        return None

    async def _write_combined_cache(self, value: float) -> None:
        try:
            await self._redis.set(self._combined_key, str(value), ex=_COMBINED_TTL)
        except Exception as exc:
            logger.debug("Redis write (combined) failed: {}", exc)
