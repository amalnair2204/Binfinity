"""Redis hash registry tracking active model file paths."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger


REGISTRY_KEY = "ml:model_registry"
REGISTRY_META_KEY = "ml:model_registry:meta"


class FeedbackModelRegistry:
    """Redis-backed registry that tracks which model files are currently active.

    Separate from ml/predictor.py's in-memory ModelRegistry — this persists
    across restarts and is updated atomically on every successful retrain swap.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def register(
        self, key: str, path: str, trained_at: datetime | None = None
    ) -> None:
        """Register or update an active model path."""
        await self._redis.hset(REGISTRY_KEY, key, path)
        meta = {
            "path": path,
            "trained_at": (trained_at or datetime.now(timezone.utc)).isoformat(),
        }
        await self._redis.hset(REGISTRY_META_KEY, key, json.dumps(meta))
        logger.info("FeedbackModelRegistry: {} → {}", key, path)

    async def get(self, key: str) -> str | None:
        val = await self._redis.hget(REGISTRY_KEY, key)
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else val

    async def get_meta(self, key: str) -> dict | None:
        val = await self._redis.hget(REGISTRY_META_KEY, key)
        if val is None:
            return None
        raw = val.decode() if isinstance(val, bytes) else val
        return json.loads(raw)

    async def list_all(self) -> dict[str, str]:
        raw = await self._redis.hgetall(REGISTRY_KEY)
        return {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in raw.items()
        }

    async def remove(self, key: str) -> None:
        await self._redis.hdel(REGISTRY_KEY, key)
        await self._redis.hdel(REGISTRY_META_KEY, key)
