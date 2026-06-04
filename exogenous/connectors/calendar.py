"""Calendar event connector — reads config/city_calendar.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
import yaml
from loguru import logger

from exogenous.base import ExogenousConnector

_DEFAULT_CALENDAR = (
    Path(__file__).resolve().parent.parent.parent / "config" / "city_calendar.yaml"
)

_HIGH_IMPACT_THRESHOLD = 1.5  # multiplier >= this → "high-impact" event/holiday
_MAX_LOOKAHEAD_DAYS = 30


@dataclass
class CalendarSnapshot:
    is_holiday_today: bool        # any event with multiplier >= HIGH_IMPACT_THRESHOLD
    is_active_event_now: bool     # any event (any multiplier > 1.0) covers today
    active_event_name: str | None
    calendar_fill_multiplier: float
    days_until_next_high_impact: int
    fetched_at: datetime


def _neutral_calendar_snapshot() -> CalendarSnapshot:
    return CalendarSnapshot(
        is_holiday_today=False,
        is_active_event_now=False,
        active_event_name=None,
        calendar_fill_multiplier=1.0,
        days_until_next_high_impact=_MAX_LOOKAHEAD_DAYS,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class CalendarConnector(ExogenousConnector):
    """Returns fill-rate multiplier and event metadata for the current date.

    Reads a YAML file with holidays and recurring events.  When multiple events
    overlap, the highest multiplier wins.  Events can be zone-restricted via an
    optional ``zones`` list field; if absent, the event applies to all zones.
    """

    TTL = 3600  # 1 hour

    def __init__(
        self,
        redis_client: aioredis.Redis,
        city: str = "dubai",
        calendar_path: str | Path | None = None,
    ) -> None:
        super().__init__(redis_client, city)
        self._calendar_path = Path(calendar_path) if calendar_path else _DEFAULT_CALENDAR
        self._events: list[dict[str, Any]] = []
        self._loaded = False

    @property
    def connector_name(self) -> str:
        return "calendar_multiplier"

    def _load_calendar(self) -> None:
        if self._loaded:
            return
        if not self._calendar_path.exists():
            logger.warning("Calendar file not found: {}", self._calendar_path)
            self._events = []
            self._loaded = True
            return
        with open(self._calendar_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._events = data.get("events", [])
        self._loaded = True
        logger.debug("Loaded {} calendar events from {}", len(self._events), self._calendar_path)

    async def fetch(self) -> float:
        self._load_calendar()
        today = datetime.now(tz=timezone.utc).date()
        return self.clamp(self._multiplier_for_date(today, zone_id=""))

    def multiplier_for_date(self, d: date, zone_id: str = "") -> float:
        """Synchronous helper — highest multiplier for *d* in *zone_id* (or global)."""
        self._load_calendar()
        return self.clamp(self._multiplier_for_date(d, zone_id))

    def get_calendar_snapshot(self, zone_id: str = "") -> CalendarSnapshot:
        """Return a CalendarSnapshot for today in *zone_id*."""
        self._load_calendar()
        today = datetime.now(tz=timezone.utc).date()
        mult = self._multiplier_for_date(today, zone_id)
        is_holiday = mult >= _HIGH_IMPACT_THRESHOLD
        is_active = mult > 1.0
        active_name = self._event_name_for_date(today, zone_id)
        days_until = self._days_until_next_high_impact(today, zone_id)

        return CalendarSnapshot(
            is_holiday_today=is_holiday,
            is_active_event_now=is_active,
            active_event_name=active_name,
            calendar_fill_multiplier=self.clamp(mult),
            days_until_next_high_impact=days_until,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    async def get_calendar_snapshot_async(self, zone_id: str = "") -> CalendarSnapshot:
        self._load_calendar()
        return self.get_calendar_snapshot(zone_id)

    def _multiplier_for_date(self, d: date, zone_id: str) -> float:
        self._load_calendar()
        best = 1.0
        for event in self._events:
            if not self._zone_matches(event, zone_id):
                continue
            m = self._match_event(event, d)
            if m is not None and m > best:
                best = m
        return best

    def _event_name_for_date(self, d: date, zone_id: str) -> str | None:
        best_mult = 1.0
        best_name: str | None = None
        for event in self._events:
            if not self._zone_matches(event, zone_id):
                continue
            m = self._match_event(event, d)
            if m is not None and m > best_mult:
                best_mult = m
                best_name = event.get("name")
        return best_name

    def _days_until_next_high_impact(self, from_date: date, zone_id: str) -> int:
        if self._multiplier_for_date(from_date, zone_id) >= _HIGH_IMPACT_THRESHOLD:
            return 0
        for days in range(1, _MAX_LOOKAHEAD_DAYS + 1):
            d = from_date + timedelta(days=days)
            if self._multiplier_for_date(d, zone_id) >= _HIGH_IMPACT_THRESHOLD:
                return days
        return _MAX_LOOKAHEAD_DAYS

    def _zone_matches(self, event: dict[str, Any], zone_id: str) -> bool:
        """Return True if event has no zone restriction or zone_id is in its zones list."""
        zones = event.get("zones")
        if not zones:
            return True
        return zone_id in zones

    def _match_event(self, event: dict[str, Any], d: date) -> float | None:
        """Return the event's multiplier if it covers *d*, else None."""
        mult = float(event.get("multiplier", 1.0))

        if "date" in event:
            try:
                if date.fromisoformat(str(event["date"])) == d:
                    return mult
            except ValueError:
                pass

        if "start" in event and "end" in event:
            try:
                start = date.fromisoformat(str(event["start"]))
                end = date.fromisoformat(str(event["end"]))
                if start <= d <= end:
                    return mult
            except ValueError:
                pass

        if "month" in event and "day" in event:
            try:
                if d.month == int(event["month"]) and d.day == int(event["day"]):
                    return mult
            except (ValueError, TypeError):
                pass

        return None
