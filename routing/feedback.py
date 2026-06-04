"""Closed-loop feedback handler — bin emptying and dump completion events.

Ground-truth events from drivers/sensors close the loop back to:
- Routing dispatcher (stop completion)
- TruckManager (load accounting)
- Redis bin state (fill reset + unflagging)
- Ingestion DB (flagged_for_collection = FALSE)
- ML feedback queue (retraining signal)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import redis.asyncio as aioredis
from loguru import logger

from routing.dispatcher import RouteDispatcher
from routing.truck_manager import TruckManager

_ML_FEEDBACK_QUEUE = "ml:feedback:queue"


class FeedbackHandler:
    """Bridges confirmed real-world events back to system state and ML pipeline."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        db_pool: asyncpg.Pool,
        dispatcher: RouteDispatcher,
        truck_manager: TruckManager,
        ingestion_db_pool: Optional[asyncpg.Pool] = None,
    ) -> None:
        self._redis = redis_client
        self._db_pool = db_pool
        self._dispatcher = dispatcher
        self._truck_manager = truck_manager
        self._ingestion_db_pool = ingestion_db_pool

    async def on_bin_emptied(
        self,
        truck_id: str,
        bin_id: str,
        actual_liters: float,
        emptied_at: Optional[datetime] = None,
    ) -> None:
        """Handle confirmed bin emptying event.

        - Removes bin stop from dispatcher's active route
        - Increments truck load via TruckManager (record_collection)
        - Resets bin fill state in Redis to 0, removes from bins:flagged and
          dispatch:known_flagged
        - Sets flagged_for_collection = FALSE in ingestion DB (if pool provided)
        - Pushes ML feedback payload to ml:feedback:queue
        """
        if emptied_at is None:
            emptied_at = datetime.now(tz=timezone.utc)

        await self._dispatcher.mark_stop_complete(truck_id, bin_id)
        await self._truck_manager.record_collection(truck_id, bin_id, actual_liters)
        await self._reset_bin_state(bin_id, emptied_at)

        if self._ingestion_db_pool is not None:
            await self._clear_ingestion_flag(bin_id)

        await self._push_ml_feedback({
            "feedback_type": "emptied",
            "bin_id": bin_id,
            "truck_id": truck_id,
            "actual_liters": actual_liters,
            "emptied_at": emptied_at.isoformat(),
        })

        logger.info(
            "FeedbackHandler: bin={} emptied by truck={} actual={:.1f}L",
            bin_id, truck_id, actual_liters,
        )

    async def on_dump_completed(
        self,
        truck_id: str,
        yard_id: str,
        dump_liters: Optional[float] = None,
        dumped_at: Optional[datetime] = None,
    ) -> None:
        """Handle truck dump yard visit.

        - Captures current truck load if dump_liters not provided
        - Resets truck load to 0 via TruckManager (record_dump)
        - Sets truck status to en_route (driver heads back on route)
        - Pushes dump telemetry to ml:feedback:queue
        """
        if dumped_at is None:
            dumped_at = datetime.now(tz=timezone.utc)

        if dump_liters is None:
            dump_liters = await self._truck_manager.get_current_load(truck_id)

        await self._truck_manager.record_dump(truck_id, yard_id)
        await self._truck_manager.update_status(truck_id, "en_route")

        await self._push_ml_feedback({
            "feedback_type": "dump",
            "truck_id": truck_id,
            "yard_id": yard_id,
            "liters_dumped": dump_liters,
            "dumped_at": dumped_at.isoformat(),
        })

        logger.info(
            "FeedbackHandler: truck={} dump complete {:.1f}L at yard={} → en_route",
            truck_id, dump_liters, yard_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _reset_bin_state(self, bin_id: str, emptied_at: datetime) -> None:
        """Reset bin fill to 0 in Redis, remove from flagged sets, update sorted set."""
        key = f"bin:{bin_id}:state"
        raw = await self._redis.get(key)

        pipe = self._redis.pipeline()
        if raw is not None:
            try:
                data = json.loads(raw)
                data["fill_pct"] = 0.0
                data["fill_liters"] = 0.0
                data["status"] = "emptied"
                data["flagged_for_collection"] = False
                data["last_emptied"] = emptied_at.isoformat()
                data["last_updated"] = emptied_at.isoformat()
                pipe.set(key, json.dumps(data))
            except Exception as exc:
                logger.error("FeedbackHandler: failed to serialise bin={} reset: {}", bin_id, exc)

        # Always remove from both flagging sets regardless of state presence
        pipe.srem("bins:flagged", bin_id)
        pipe.srem("dispatch:known_flagged", bin_id)
        pipe.zadd("bins:by_fill", {bin_id: 0.0})
        await pipe.execute()

        logger.debug("FeedbackHandler: bin={} state reset to 0%", bin_id)

    async def _clear_ingestion_flag(self, bin_id: str) -> None:
        """Set flagged_for_collection = FALSE in ingestion DB."""
        try:
            async with self._ingestion_db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE bin_states SET flagged_for_collection = FALSE WHERE bin_id = $1",
                    bin_id,
                )
        except Exception as exc:
            logger.error(
                "FeedbackHandler: failed to clear ingestion flag for bin={}: {}", bin_id, exc
            )

    async def _push_ml_feedback(self, payload: dict) -> None:
        """LPUSH feedback payload to ml:feedback:queue for ML pipeline consumption."""
        try:
            await self._redis.lpush(_ML_FEEDBACK_QUEUE, json.dumps(payload))
            logger.debug(
                "FeedbackHandler: pushed type={} to {}",
                payload.get("feedback_type"), _ML_FEEDBACK_QUEUE,
            )
        except Exception as exc:
            logger.error("FeedbackHandler: failed to push ML feedback: {}", exc)
