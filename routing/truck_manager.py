"""Truck state machine — lifecycle management throughout a shift."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import redis.asyncio as aioredis
from loguru import logger

from routing.schemas import Truck

_TRUCK_STATE_TTL = 86400  # 24h
_SHIFT_ENDING_THRESHOLD_SEC = 1800  # 30 minutes

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS truck_registry (
    truck_id            TEXT PRIMARY KEY,
    capacity_liters     INTEGER NOT NULL,
    depot_lat           DOUBLE PRECISION NOT NULL,
    depot_lng           DOUBLE PRECISION NOT NULL,
    shift_start_seconds INTEGER NOT NULL DEFAULT 0,
    shift_end_seconds   INTEGER NOT NULL DEFAULT 28800,
    can_access_narrow   BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collections_log (
    id               BIGSERIAL PRIMARY KEY,
    truck_id         TEXT NOT NULL,
    bin_id           TEXT NOT NULL,
    collected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    liters_collected DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS dump_events_log (
    id            BIGSERIAL PRIMARY KEY,
    truck_id      TEXT NOT NULL,
    yard_id       TEXT NOT NULL,
    dumped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    liters_dumped DOUBLE PRECISION NOT NULL DEFAULT 0.0
);
"""


class TruckManager:
    """Manages truck state across Redis (real-time) and PostgreSQL (audit log).

    Redis keys per truck:
        dispatch:truck:{id}:state    — JSON Truck schema (TTL 24h)
        dispatch:truck:{id}:load     — current load in liters as float string
        dispatch:truck:{id}:position — JSON {lat, lng, updated_at}
        dispatch:truck:{id}:status   — string: idle | active | collecting | dumping | off_shift
    """

    def __init__(self, redis_client: aioredis.Redis, db_pool: asyncpg.Pool) -> None:
        self._redis = redis_client
        self._db_pool = db_pool

    async def init_schema(self) -> None:
        async with self._db_pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES_SQL)
        logger.info("TruckManager: DB schema ready")

    # ------------------------------------------------------------------
    # Registration and lookup
    # ------------------------------------------------------------------

    async def register_truck(self, truck: Truck) -> None:
        """Persist truck definition to Redis and DB. Upserts on conflict."""
        await self._redis.set(_state_key(truck.truck_id), truck.model_dump_json(), ex=_TRUCK_STATE_TTL)
        await self._redis.set(_load_key(truck.truck_id), "0.0", ex=_TRUCK_STATE_TTL)
        await self._redis.set(_status_key(truck.truck_id), "idle", ex=_TRUCK_STATE_TTL)

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO truck_registry
                        (truck_id, capacity_liters, depot_lat, depot_lng,
                         shift_start_seconds, shift_end_seconds, can_access_narrow)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (truck_id) DO UPDATE SET
                        capacity_liters     = EXCLUDED.capacity_liters,
                        depot_lat           = EXCLUDED.depot_lat,
                        depot_lng           = EXCLUDED.depot_lng,
                        shift_start_seconds = EXCLUDED.shift_start_seconds,
                        shift_end_seconds   = EXCLUDED.shift_end_seconds,
                        can_access_narrow   = EXCLUDED.can_access_narrow
                    """,
                    truck.truck_id,
                    truck.capacity_liters,
                    truck.depot_lat,
                    truck.depot_lng,
                    truck.shift_start_seconds,
                    truck.shift_end_seconds,
                    truck.can_access_narrow,
                )
        except Exception as exc:
            logger.error("TruckManager.register_truck DB error: {}", exc)

        logger.info("TruckManager: registered truck={}", truck.truck_id)

    async def get_truck(self, truck_id: str) -> Optional[Truck]:
        raw = await self._redis.get(_state_key(truck_id))
        if raw is None:
            return None
        try:
            return Truck.model_validate_json(raw)
        except Exception:
            return None

    async def get_all_trucks(self) -> list[Truck]:
        """Return all trucks currently registered in Redis."""
        trucks: list[Truck] = []
        cursor = 0
        pattern = "dispatch:truck:*:state"
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await self._redis.get(key)
                if raw:
                    try:
                        trucks.append(Truck.model_validate_json(raw))
                    except Exception:
                        pass
            if cursor == 0:
                break
        return trucks

    # ------------------------------------------------------------------
    # Real-time state updates
    # ------------------------------------------------------------------

    async def update_position(self, truck_id: str, lat: float, lng: float) -> None:
        payload = json.dumps({
            "lat": lat,
            "lng": lng,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        await self._redis.set(_position_key(truck_id), payload, ex=_TRUCK_STATE_TTL)
        logger.debug("TruckManager: truck={} position ({:.5f}, {:.5f})", truck_id, lat, lng)

    async def update_load(self, truck_id: str, load_liters: float) -> None:
        await self._redis.set(_load_key(truck_id), str(load_liters), ex=_TRUCK_STATE_TTL)
        logger.debug("TruckManager: truck={} load={:.1f}L", truck_id, load_liters)

    async def update_status(self, truck_id: str, status: str) -> None:
        await self._redis.set(_status_key(truck_id), status, ex=_TRUCK_STATE_TTL)
        logger.debug("TruckManager: truck={} status={}", truck_id, status)

    async def get_current_load(self, truck_id: str) -> float:
        raw = await self._redis.get(_load_key(truck_id))
        if raw is None:
            return 0.0
        try:
            return float(raw.decode() if isinstance(raw, bytes) else raw)
        except ValueError:
            return 0.0

    async def get_status(self, truck_id: str) -> str:
        raw = await self._redis.get(_status_key(truck_id))
        if raw is None:
            return "idle"
        return raw.decode() if isinstance(raw, bytes) else raw

    # ------------------------------------------------------------------
    # Collection and dump events
    # ------------------------------------------------------------------

    async def record_collection(
        self, truck_id: str, bin_id: str, liters: float
    ) -> None:
        """Increment truck load, remove bin from flagged set, log to DB."""
        current_load = await self.get_current_load(truck_id)
        new_load = current_load + liters
        await self.update_load(truck_id, new_load)
        await self.update_status(truck_id, "collecting")
        await self._redis.srem("bins:flagged", bin_id)

        collected_at = datetime.now(tz=timezone.utc)
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO collections_log (truck_id, bin_id, collected_at, liters_collected) "
                    "VALUES ($1, $2, $3, $4)",
                    truck_id, bin_id, collected_at, liters,
                )
        except Exception as exc:
            logger.error("TruckManager.record_collection DB error: {}", exc)

        logger.info(
            "TruckManager: truck={} collected bin={} +{:.1f}L total={:.1f}L",
            truck_id, bin_id, liters, new_load,
        )

    async def get_position(self, truck_id: str) -> Optional[dict]:
        """Return last known position as {lat, lng, updated_at}, or None."""
        raw = await self._redis.get(_position_key(truck_id))
        if raw is None:
            return None
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            return None

    async def get_collections_today(self) -> list[dict]:
        """Return all collection events logged today from collections_log."""
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT truck_id, bin_id, collected_at, liters_collected "
                    "FROM collections_log "
                    "WHERE collected_at >= CURRENT_DATE ORDER BY collected_at DESC"
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("TruckManager.get_collections_today error: {}", exc)
            return []

    async def record_dump(self, truck_id: str, yard_id: str) -> None:
        """Reset truck load to 0 and log dump event to DB.

        Status is NOT updated here — caller is responsible for setting
        the appropriate post-dump status (e.g. "en_route").
        """
        previous_load = await self.get_current_load(truck_id)
        await self.update_load(truck_id, 0.0)

        dumped_at = datetime.now(tz=timezone.utc)
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO dump_events_log (truck_id, yard_id, dumped_at, liters_dumped) "
                    "VALUES ($1, $2, $3, $4)",
                    truck_id, yard_id, dumped_at, previous_load,
                )
        except Exception as exc:
            logger.error("TruckManager.record_dump DB error: {}", exc)

        logger.info(
            "TruckManager: truck={} dumped {:.1f}L at yard={}", truck_id, previous_load, yard_id
        )

    # ------------------------------------------------------------------
    # Fleet-level queries
    # ------------------------------------------------------------------

    async def check_shift_status(self) -> list[str]:
        """Return truck_ids whose shifts end within 30 minutes.

        Uses seconds-since-midnight as proxy for shift position. Skips
        trucks already off_shift or idle.
        """
        trucks = await self.get_all_trucks()
        now = datetime.now(tz=timezone.utc)
        secs_since_midnight = now.hour * 3600 + now.minute * 60 + now.second

        ending_soon: list[str] = []
        for truck in trucks:
            status = await self.get_status(truck.truck_id)
            if status in ("off_shift", "idle"):
                continue
            remaining = truck.shift_end_seconds - secs_since_midnight
            if 0 < remaining <= _SHIFT_ENDING_THRESHOLD_SEC:
                ending_soon.append(truck.truck_id)
                logger.info(
                    "TruckManager: truck={} shift ends in {:.0f}min",
                    truck.truck_id, remaining / 60,
                )
        return ending_soon

    async def get_active_trucks(self) -> list[Truck]:
        """Return trucks with status not in ['off_shift', 'idle']."""
        trucks = await self.get_all_trucks()
        active: list[Truck] = []
        for truck in trucks:
            status = await self.get_status(truck.truck_id)
            if status not in ("off_shift", "idle"):
                active.append(truck)
        return active


# ------------------------------------------------------------------
# Redis key helpers
# ------------------------------------------------------------------

def _state_key(truck_id: str) -> str:
    return f"dispatch:truck:{truck_id}:state"

def _load_key(truck_id: str) -> str:
    return f"dispatch:truck:{truck_id}:load"

def _position_key(truck_id: str) -> str:
    return f"dispatch:truck:{truck_id}:position"

def _status_key(truck_id: str) -> str:
    return f"dispatch:truck:{truck_id}:status"
