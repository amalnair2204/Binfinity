"""Wire all feedback pipeline components into 5 concurrent asyncio tasks."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg
from loguru import logger

from feedback.accuracy import ensure_tables, refresh_fleet_accuracy_cache
from feedback.consumer import FeedbackConsumer
from feedback.job_queue import RetrainJobQueue
from feedback.model_registry import FeedbackModelRegistry
from feedback.retrain_worker import RetrainWorker

if TYPE_CHECKING:
    from ingestion.db import IngestionDB
    from geospatial.db import GeospatialDB

FLEET_STATS_INTERVAL = 300   # 5 min — refresh fleet-wide accuracy cache
HEARTBEAT_INTERVAL = 600     # 10 min — log pipeline health
QUEUE_MONITOR_INTERVAL = 60  # 1 min — warn if retrain queue depth grows large
QUEUE_DEPTH_WARN = 20


async def _stats_refresher(redis, pool: asyncpg.Pool) -> None:
    """Task 3: Periodically refresh fleet-wide accuracy stats in Redis."""
    while True:
        try:
            await asyncio.sleep(FLEET_STATS_INTERVAL)
            await refresh_fleet_accuracy_cache(redis, pool)
            logger.debug("StatsRefresher: fleet accuracy cache refreshed")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("StatsRefresher: error: {}", exc)


async def _heartbeat(
    consumer: FeedbackConsumer, job_queue: RetrainJobQueue
) -> None:
    """Task 4: Log periodic pipeline health stats."""
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            queue_depth = await job_queue.size()
            logger.info(
                "Feedback pipeline health: processed={} errors={} "
                "retrain_queue={} last_event={}",
                consumer._processed,
                consumer._errors,
                queue_depth,
                consumer._last_event_at,
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Heartbeat: error: {}", exc)


async def _queue_monitor(job_queue: RetrainJobQueue) -> None:
    """Task 5: Warn when retrain queue depth grows large."""
    while True:
        try:
            await asyncio.sleep(QUEUE_MONITOR_INTERVAL)
            depth = await job_queue.size()
            if depth > QUEUE_DEPTH_WARN:
                logger.warning(
                    "RetrainJobQueue: depth={} — worker may be falling behind",
                    depth,
                )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("QueueMonitor: error: {}", exc)


async def start_all(
    redis_client,
    pool: asyncpg.Pool,
    ingestion_db: "IngestionDB",
    geo_db: "GeospatialDB",
    model_dir: str = "data/models",
) -> None:
    """Create all components, ensure DB tables, and run all 5 tasks concurrently.

    Tasks:
        1. FeedbackConsumer  — drains ml:feedback:queue, computes accuracy
        2. RetrainWorker     — executes retrain jobs with atomic model swap
        3. StatsRefresher    — refreshes fleet accuracy cache every 5 min
        4. Heartbeat         — logs pipeline health every 10 min
        5. QueueMonitor      — warns if retrain queue depth exceeds threshold

    Blocks until all tasks complete or one raises an unhandled exception.
    """
    await ensure_tables(pool)

    job_queue = RetrainJobQueue(redis_client)
    model_registry = FeedbackModelRegistry(redis_client)
    consumer = FeedbackConsumer(redis_client, pool, job_queue)
    worker = RetrainWorker(
        redis_client,
        pool,
        job_queue,
        model_registry,
        ingestion_db,
        geo_db,
        model_dir,
    )

    logger.info("Feedback pipeline: starting all 5 tasks")

    await asyncio.gather(
        consumer.start(),          # task 1
        worker.start(),            # task 2
        _stats_refresher(redis_client, pool),  # task 3
        _heartbeat(consumer, job_queue),        # task 4
        _queue_monitor(job_queue),              # task 5
        return_exceptions=False,
    )


if __name__ == "__main__":
    import os as _os
    import asyncio as _asyncio
    import uvicorn as _uvicorn
    import asyncpg as _asyncpg
    import redis.asyncio as _aioredis
    from fastapi import FastAPI as _FastAPI
    from feedback.api import router as _calibration_router, configure as _configure_api
    from feedback.job_queue import RetrainJobQueue as _RetrainJobQueue
    from feedback.model_registry import FeedbackModelRegistry as _FeedbackModelRegistry
    from ingestion.db import IngestionDB as _IngestionDB
    from geospatial.db import GeospatialDB as _GeospatialDB

    _DATABASE_URL = _os.getenv("DATABASE_URL", "postgresql://postgres:binfinity@localhost:5432/binfinity")
    _REDIS_URL = _os.getenv("REDIS_URL", "redis://localhost:6379")
    _PORT = int(_os.getenv("FEEDBACK_PORT", "8006"))
    _MODEL_DIR = _os.getenv("MODEL_DIR", "data/models")

    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator
    _app = _FastAPI(title="Binfinity Feedback API")
    _app.include_router(_calibration_router)
    _Instrumentator().instrument(_app).expose(_app, endpoint="/metrics")

    async def _main() -> None:
        pool = await _asyncpg.create_pool(_DATABASE_URL, min_size=2, max_size=10)
        redis = _aioredis.from_url(_REDIS_URL, decode_responses=False)

        ingestion_db = _IngestionDB(_DATABASE_URL)
        await ingestion_db.connect()

        geo_db = _GeospatialDB(_DATABASE_URL)
        await geo_db.connect()

        job_queue = _RetrainJobQueue(redis)
        model_registry = _FeedbackModelRegistry(redis)
        _configure_api(redis, pool, job_queue, model_registry)

        config = _uvicorn.Config(_app, host="0.0.0.0", port=_PORT, log_level="info")
        server = _uvicorn.Server(config)
        await _asyncio.gather(
            server.serve(),
            start_all(redis, pool, ingestion_db, geo_db, _MODEL_DIR),
            return_exceptions=True,
        )

    _asyncio.run(_main())
