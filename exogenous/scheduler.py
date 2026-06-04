"""Background refresh scheduler for exogenous connectors."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from exogenous.connectors.calendar import CalendarConnector
    from exogenous.connectors.traffic import TrafficConnector
    from exogenous.connectors.weather import WeatherConnector

_WEATHER_INTERVAL = 1800    # 30 min
_TRAFFIC_INTERVAL = 900     # 15 min
_CALENDAR_INTERVAL = 21600  # 6 hours


async def _refresh_loop(connector: object, interval: int, name: str) -> None:
    """Run one connector on a fixed interval, logging latency each cycle."""
    while True:
        t0 = time.monotonic()
        try:
            await connector.get_multiplier()  # type: ignore[attr-defined]
            latency_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "Exogenous refresh — source={} latency={:.1f}ms next_in={}s",
                name,
                latency_ms,
                interval,
            )
        except Exception as exc:
            logger.warning("Exogenous refresh failed — source={}: {}", name, exc)
        await asyncio.sleep(interval)


async def run_refresh_loop(
    weather: "WeatherConnector",
    traffic: "TrafficConnector",
    calendar: "CalendarConnector",
) -> None:
    """Run weather (30 min), traffic (15 min), and calendar (6 h) loops concurrently."""
    await asyncio.gather(
        _refresh_loop(weather, _WEATHER_INTERVAL, "weather"),
        _refresh_loop(traffic, _TRAFFIC_INTERVAL, "traffic"),
        _refresh_loop(calendar, _CALENDAR_INTERVAL, "calendar"),
        return_exceptions=True,
    )
