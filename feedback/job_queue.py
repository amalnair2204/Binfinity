"""Redis-backed retrain job queue with deduplication."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger


QUEUE_KEY = "ml:retrain:queue"
DEDUPE_PREFIX = "ml:retrain:enqueued:"
DEDUPE_TTL = 3600  # 1 hour — won't re-enqueue the same target within this window


@dataclass
class RetrainJob:
    job_id: str
    target_type: str  # 'bin' or 'zone'
    target_id: str
    enqueued_at: datetime
    trigger_reason: str

    def to_json(self) -> str:
        return json.dumps({
            "job_id": self.job_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "enqueued_at": self.enqueued_at.isoformat(),
            "trigger_reason": self.trigger_reason,
        })

    @classmethod
    def from_json(cls, data: str | bytes) -> "RetrainJob":
        d = json.loads(data)
        return cls(
            job_id=d["job_id"],
            target_type=d["target_type"],
            target_id=d["target_id"],
            enqueued_at=datetime.fromisoformat(d["enqueued_at"]),
            trigger_reason=d["trigger_reason"],
        )


class RetrainJobQueue:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def enqueue(
        self, target_type: str, target_id: str, reason: str
    ) -> bool:
        """Enqueue a retrain job. Returns False if already enqueued (dedup TTL active)."""
        dedupe_key = f"{DEDUPE_PREFIX}{target_type}:{target_id}"
        acquired = await self._redis.set(dedupe_key, "1", nx=True, ex=DEDUPE_TTL)
        if not acquired:
            logger.debug(
                "RetrainJobQueue: dedup skip {} {} — already enqueued",
                target_type,
                target_id,
            )
            return False

        job = RetrainJob(
            job_id=str(uuid.uuid4()),
            target_type=target_type,
            target_id=target_id,
            enqueued_at=datetime.now(timezone.utc),
            trigger_reason=reason,
        )
        await self._redis.lpush(QUEUE_KEY, job.to_json())
        logger.info(
            "RetrainJobQueue: enqueued {} {} (reason: {})",
            target_type,
            target_id,
            reason,
        )
        return True

    async def dequeue(self, timeout: int = 5) -> RetrainJob | None:
        """BLPOP with timeout. Returns None on timeout."""
        result = await self._redis.blpop(QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return RetrainJob.from_json(raw)

    async def size(self) -> int:
        return await self._redis.llen(QUEUE_KEY)
