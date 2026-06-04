"""Abstract base connector for exogenous data sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger


class ExogenousConnector(ABC):
    """Base class for all exogenous data connectors.

    Subclasses implement fetch() which returns a fill-rate multiplier.
    1.0 = neutral, >1.0 = higher fill rate expected, <1.0 = lower.
    """

    TTL: int = 1800  # default Redis cache TTL (seconds)
    REDIS_KEY_PREFIX: str = "exogenous"

    def __init__(self, redis_client: aioredis.Redis, city: str = "dubai") -> None:
        self._redis = redis_client
        self._city = city.lower()

    @property
    def _cache_key(self) -> str:
        return f"{self.REDIS_KEY_PREFIX}:{self._city}:{self.connector_name}"

    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Unique name for this connector (used as Redis key suffix)."""
        ...

    @abstractmethod
    async def fetch(self) -> float:
        """Fetch fresh multiplier from external source.

        Must return a float in [0.5, 3.0]. Raise on unrecoverable error.
        """
        ...

    async def get_multiplier(self) -> float:
        """Return cached multiplier or fetch fresh if stale."""
        cached = await self._read_cache()
        if cached is not None:
            return cached
        try:
            value = await self.fetch()
            await self._write_cache(value)
            return value
        except Exception as exc:
            logger.warning(
                "{} fetch failed: {}. Returning neutral 1.0.",
                self.__class__.__name__,
                exc,
            )
            return 1.0

    async def _read_cache(self) -> Optional[float]:
        try:
            raw = await self._redis.get(self._cache_key)
            if raw is not None:
                return float(raw)
        except Exception as exc:
            logger.debug("Redis read failed for {}: {}", self._cache_key, exc)
        return None

    async def _write_cache(self, value: float) -> None:
        try:
            await self._redis.set(self._cache_key, str(value), ex=self.TTL)
        except Exception as exc:
            logger.debug("Redis write failed for {}: {}", self._cache_key, exc)

    @staticmethod
    def clamp(value: float, lo: float = 0.5, hi: float = 3.0) -> float:
        return max(lo, min(hi, value))
