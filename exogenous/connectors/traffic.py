"""TomTom Traffic API connector with time-of-day heuristic fallback."""
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


class _TrafficSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    TOMTOM_API_KEY: str = ""
    CITY_LAT: float = 25.2048
    CITY_LNG: float = 55.2708


_SETTINGS = _TrafficSettings()

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_FREE_FLOW_SPEED_KMH = 60.0   # assumed free-flow for delay math
_TRUCK_ROUTE_KM = 20.0         # typical collection route for delay estimate
_CONGESTED_THRESHOLD = 0.5     # congestion_ratio < 0.5 → is_congested

# Dubai local hour (UTC+4) → congestion ratio (current_speed / free_flow_speed).
# 0 = fully stopped, 1 = free flow.  Peak morning (08:00) = 0.40.
_HOUR_CONGESTION: dict[int, float] = {
    0: 0.95,  1: 0.98,  2: 0.99,  3: 0.99,  4: 0.98,
    5: 0.88,  6: 0.72,  7: 0.55,  8: 0.40,  9: 0.48,
    10: 0.68, 11: 0.72, 12: 0.62, 13: 0.55, 14: 0.65,
    15: 0.70, 16: 0.58, 17: 0.42, 18: 0.35, 19: 0.48,
    20: 0.60, 21: 0.70, 22: 0.82, 23: 0.90,
}


@dataclass
class TrafficSnapshot:
    zone_id: str
    congestion_ratio: float          # current_speed / free_flow_speed
    is_congested: bool               # congestion_ratio < 0.5
    fill_rate_multiplier: float      # 1.0 + (1 - ratio) * 0.3
    delay_minutes_per_10km: float    # extra minutes vs free flow for 10 km
    estimated_truck_delay_min: float # delay for typical route
    fetched_at: datetime

    @staticmethod
    def compute_delay(congestion_ratio: float) -> float:
        """Extra minutes vs free-flow for 10 km."""
        if congestion_ratio <= 0:
            return 60.0  # fully stopped — cap at 60 min
        free_time = 10.0 / _FREE_FLOW_SPEED_KMH * 60.0
        actual_time = 10.0 / (_FREE_FLOW_SPEED_KMH * congestion_ratio) * 60.0
        return max(0.0, actual_time - free_time)


def _neutral_traffic_snapshot(zone_id: str = "") -> TrafficSnapshot:
    return TrafficSnapshot(
        zone_id=zone_id,
        congestion_ratio=0.7,
        is_congested=False,
        fill_rate_multiplier=1.0,
        delay_minutes_per_10km=0.0,
        estimated_truck_delay_min=0.0,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class TrafficConnector(ExogenousConnector):
    """Fetches traffic flow from TomTom Flow API and maps to fill-rate signals.

    Falls back to a time-of-day heuristic (congestion_ratio lookup by Dubai hour)
    when the API is unavailable or unauthenticated.
    """

    TTL = 600  # 10 min

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
        self._api_key = api_key or _SETTINGS.TOMTOM_API_KEY
        self._last_snapshot: TrafficSnapshot | None = None

    @property
    def connector_name(self) -> str:
        return "traffic_multiplier"

    async def fetch(self) -> float:
        snapshot = await self._call_api(zone_id="")
        self._last_snapshot = snapshot
        return snapshot.fill_rate_multiplier

    async def get_traffic_snapshot(self, zone_id: str = "") -> TrafficSnapshot:
        """Return a TrafficSnapshot for *zone_id* (currently city-level until zone centroids added)."""
        cached_float = await self._read_cache()
        if cached_float is not None and self._last_snapshot is not None:
            return self._last_snapshot
        try:
            snapshot = await self._call_api(zone_id=zone_id)
            self._last_snapshot = snapshot
            await self._write_cache(snapshot.fill_rate_multiplier)
            return snapshot
        except Exception as exc:
            logger.warning("TrafficConnector.get_traffic_snapshot failed: {} — returning neutral", exc)
            return _neutral_traffic_snapshot(zone_id)

    async def _call_api(self, zone_id: str) -> TrafficSnapshot:
        if not self._api_key:
            logger.debug("TOMTOM_API_KEY not set — using time-of-day heuristic")
            return self._heuristic_snapshot(zone_id=zone_id)

        url = (
            "https://api.tomtom.com/traffic/services/4/flowSegmentData/"
            "absolute/10/json"
        )
        params: dict[str, Any] = {
            "key": self._api_key,
            "point": f"{self._lat},{self._lng}",
        }

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    return self._parse_snapshot(resp.json(), zone_id=zone_id)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (401, 403):
                        logger.warning("TomTom auth error — falling back to heuristic")
                        return self._heuristic_snapshot(zone_id=zone_id)
                    last_exc = exc
                except Exception as exc:
                    last_exc = exc

                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))

        logger.warning(
            "TomTom fetch failed after {} retries: {} — using heuristic fallback",
            _MAX_RETRIES,
            last_exc,
        )
        return self._heuristic_snapshot(zone_id=zone_id)

    def _parse_snapshot(self, data: dict[str, Any], zone_id: str) -> TrafficSnapshot:
        try:
            flow = data["flowSegmentData"]
            current = float(flow["currentSpeed"])
            free_flow = float(flow["freeFlowSpeed"])
            ratio = current / max(free_flow, 0.01)
        except (KeyError, TypeError, ValueError):
            ratio = 0.7

        ratio = max(0.01, min(1.0, ratio))
        return self._snapshot_from_ratio(ratio, zone_id)

    def _heuristic_snapshot(
        self, zone_id: str = "", at_time: datetime | None = None
    ) -> TrafficSnapshot:
        """Time-of-day proxy using Dubai local time (UTC+4)."""
        now = at_time or datetime.now(tz=timezone.utc)
        hour_dubai = (now.hour + 4) % 24
        ratio = _HOUR_CONGESTION.get(hour_dubai, 0.7)
        return self._snapshot_from_ratio(ratio, zone_id)

    def _snapshot_from_ratio(self, ratio: float, zone_id: str) -> TrafficSnapshot:
        delay_per_10km = TrafficSnapshot.compute_delay(ratio)
        return TrafficSnapshot(
            zone_id=zone_id,
            congestion_ratio=ratio,
            is_congested=ratio < _CONGESTED_THRESHOLD,
            fill_rate_multiplier=self.clamp(1.0 + (1.0 - ratio) * 0.3),
            delay_minutes_per_10km=delay_per_10km,
            estimated_truck_delay_min=delay_per_10km * (_TRUCK_ROUTE_KM / 10.0),
            fetched_at=datetime.now(tz=timezone.utc),
        )
