"""Redis state cache — mirrors BinState and maintains fleet-level sorted sets."""
from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from ingestion.schemas import BinState


class BinStateCache:
    def __init__(self, redis_url: str) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(
            redis_url, encoding="utf-8", decode_responses=False
        )

    async def close(self) -> None:
        await self._redis.aclose()

    async def set_bin_state(self, state: BinState) -> None:
        """Mirror state to Redis atomically: JSON key + sorted/membership sets."""
        key = f"bin:{state.bin_id}:state"
        pipe = self._redis.pipeline(transaction=True)

        # State JSON
        pipe.set(key, state.model_dump_json())

        # bins:by_fill sorted set
        pipe.zadd("bins:by_fill", {state.bin_id: state.fill_pct})

        # bins:flagged membership set
        if state.flagged_for_collection:
            pipe.sadd("bins:flagged", state.bin_id)
        else:
            pipe.srem("bins:flagged", state.bin_id)

        # bins:faulted membership set
        if state.status == "sensor_fault":
            pipe.sadd("bins:faulted", state.bin_id)
        else:
            pipe.srem("bins:faulted", state.bin_id)

        await pipe.execute()

    async def get_bin_state(self, bin_id: str) -> Optional[BinState]:
        raw = await self._redis.get(f"bin:{bin_id}:state")
        if raw is None:
            return None
        return BinState.model_validate_json(raw)

    async def get_all_bin_states(self) -> list[BinState]:
        keys = await self._redis.keys("bin:*:state")
        if not keys:
            return []
        raw_values = await self._redis.mget(*keys)
        states = []
        for raw in raw_values:
            if raw:
                states.append(BinState.model_validate_json(raw))
        return states

    async def get_flagged_bins(self) -> list[str]:
        members = await self._redis.smembers("bins:flagged")
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def get_faulted_bins(self) -> list[str]:
        members = await self._redis.smembers("bins:faulted")
        return [m.decode() if isinstance(m, bytes) else m for m in members]
