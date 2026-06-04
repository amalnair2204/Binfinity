"""Live bridge between ingestion Redis state and the routing dispatcher."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from routing.dispatcher import DispatchEvent, RouteDispatcher

_POLL_INTERVAL_SECONDS = 10
_HEARTBEAT_INTERVAL_SECONDS = 60
_REDIS_EVENTS_KEY = "dispatch:events"
_KNOWN_FLAGGED_KEY = "dispatch:known_flagged"
_KNOWN_FAULTED_KEY = "dispatch:known_faulted"
_OVERFLOW_CRITICAL_HOURS = 2.0
_HOURS_PER_PCT_ABOVE_50 = 0.2  # mirrors input_builder estimate


class EventBridge:
    """Polls Redis for bin state changes and translates them into DispatchEvents.

    Runs two concurrent coroutines:
    - poll_loop: every 10s drains dispatch:events + diffs bin state sets
    - heartbeat: every 60s logs bridge status
    """

    def __init__(self, redis_client: aioredis.Redis, dispatcher: RouteDispatcher) -> None:
        self._redis = redis_client
        self._dispatcher = dispatcher
        self._events_processed: int = 0
        self._last_poll: Optional[datetime] = None

    async def start(self) -> None:
        """Run poll_loop and heartbeat concurrently until cancelled."""
        await asyncio.gather(self.poll_loop(), self.heartbeat(), return_exceptions=True)

    async def poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
                self._last_poll = datetime.now(tz=timezone.utc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("EventBridge poll error: {}", exc)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            logger.info(
                "EventBridge heartbeat: events_processed={} last_poll={}",
                self._events_processed,
                self._last_poll.isoformat() if self._last_poll else "never",
            )

    # ------------------------------------------------------------------
    # Core polling
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        await self._drain_dispatch_events()
        await self._check_newly_flagged()
        await self._check_newly_faulted()

    async def _drain_dispatch_events(self) -> None:
        """Non-blocking drain of dispatch:events list."""
        while True:
            raw = await self._redis.rpop(_REDIS_EVENTS_KEY)
            if raw is None:
                break
            try:
                data = json.loads(raw)
                event = self._translate_packet(data)
                if event is not None:
                    await self._dispatcher.on_event(event)
                    self._events_processed += 1
            except Exception as exc:
                logger.warning("EventBridge: failed to parse event: {} — raw={}", exc, raw)

    async def _check_newly_flagged(self) -> None:
        """Diff bins:flagged against known set; emit DispatchEvents for new entries."""
        current: set[str] = await self._smembers_decoded("bins:flagged")
        known: set[str] = await self._smembers_decoded(_KNOWN_FLAGGED_KEY)
        new_bins = current - known

        for bin_id in new_bins:
            hours = await self._estimate_hours_until_critical(bin_id)
            if hours is not None and hours <= _OVERFLOW_CRITICAL_HOURS:
                event_type, priority = "overflow_alert", 3
            else:
                event_type, priority = "new_bins_flagged", 1

            event = DispatchEvent(
                event_id=str(uuid.uuid4()),
                event_type=event_type,
                triggered_at=datetime.now(tz=timezone.utc),
                affected_bin_id=bin_id,
                priority=priority,
            )
            await self._dispatcher.on_event(event)
            self._events_processed += 1
            logger.debug("EventBridge: bin={} newly flagged → {}", bin_id, event_type)

        # Sync known_flagged to current state
        pipe = self._redis.pipeline()
        pipe.delete(_KNOWN_FLAGGED_KEY)
        if current:
            pipe.sadd(_KNOWN_FLAGGED_KEY, *current)
        pipe.expire(_KNOWN_FLAGGED_KEY, 86400)
        await pipe.execute()

    async def _check_newly_faulted(self) -> None:
        """Diff bins:faulted; log only — do not dispatch routing events for faults."""
        current: set[str] = await self._smembers_decoded("bins:faulted")
        known: set[str] = await self._smembers_decoded(_KNOWN_FAULTED_KEY)
        new_faults = current - known

        for bin_id in new_faults:
            logger.warning(
                "EventBridge: sensor fault on bin={}, excluded from routing", bin_id
            )

        pipe = self._redis.pipeline()
        pipe.delete(_KNOWN_FAULTED_KEY)
        if current:
            pipe.sadd(_KNOWN_FAULTED_KEY, *current)
        pipe.expire(_KNOWN_FAULTED_KEY, 86400)
        await pipe.execute()

    # ------------------------------------------------------------------
    # Packet translation
    # ------------------------------------------------------------------

    def _translate_packet(self, data: dict) -> Optional[DispatchEvent]:
        """Translate a raw event dict into a DispatchEvent, or None to discard."""
        raw_type = data.get("event_type", "")
        now = datetime.now(tz=timezone.utc)

        # tip_alert from ingestion layer → tip_over dispatch event
        if raw_type == "tip_alert":
            return DispatchEvent(
                event_id=data.get("event_id", str(uuid.uuid4())),
                event_type="tip_over",
                triggered_at=_parse_dt(data.get("triggered_at"), now),
                affected_bin_id=data.get("affected_bin_id"),
                affected_truck_id=data.get("affected_truck_id"),
                priority=3,
            )

        # Already-formed DispatchEvent payloads
        valid_types = {
            "overflow_alert", "tip_over", "truck_capacity_hit",
            "truck_shift_ending", "new_bins_flagged", "manual_override",
        }
        if raw_type in valid_types:
            try:
                return DispatchEvent.model_validate(data)
            except Exception as exc:
                logger.warning("EventBridge: invalid DispatchEvent payload: {}", exc)
                return None

        logger.debug("EventBridge: unrecognized event_type={}, discarding", raw_type)
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _estimate_hours_until_critical(self, bin_id: str) -> Optional[float]:
        """Estimate hours_until_critical from bin's current fill_pct in Redis."""
        try:
            raw = await self._redis.get(f"bin:{bin_id}:state")
            if raw is None:
                return None
            data = json.loads(raw)
            fill_pct = float(data.get("fill_pct", 0.0))
            if fill_pct >= 95:
                return 0.5
            if fill_pct >= 80:
                return max(0.5, (100.0 - fill_pct) * _HOURS_PER_PCT_ABOVE_50)
            return max(2.0, (100.0 - fill_pct) * _HOURS_PER_PCT_ABOVE_50)
        except Exception:
            return None

    async def _smembers_decoded(self, key: str) -> set[str]:
        members = await self._redis.smembers(key)
        return {m.decode() if isinstance(m, bytes) else m for m in members}


def _parse_dt(value: Optional[str], fallback: datetime) -> datetime:
    if value is None:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback
