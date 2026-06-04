"""Retrain job executor with atomic model swap and smoke test."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
from loguru import logger

from feedback.job_queue import RetrainJob, RetrainJobQueue
from feedback.model_registry import FeedbackModelRegistry

if TYPE_CHECKING:
    from ingestion.db import IngestionDB
    from geospatial.db import GeospatialDB


async def _log_job_start(
    pool: asyncpg.Pool, job: RetrainJob, started_at: datetime
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO retrain_jobs_log
                (job_id, target_type, target_id, enqueued_at, started_at,
                 status, trigger_reason)
            VALUES ($1, $2, $3, $4, $5, 'running', $6)
            ON CONFLICT DO NOTHING
            """,
            job.job_id,
            job.target_type,
            job.target_id,
            job.enqueued_at,
            started_at,
            job.trigger_reason,
        )


async def _log_job_done(
    pool: asyncpg.Pool,
    job_id: str,
    completed_at: datetime,
    status: str,
    error: str | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE retrain_jobs_log
            SET completed_at = $1, status = $2, error = $3
            WHERE job_id = $4
            """,
            completed_at,
            status,
            error,
            job_id,
        )


class RetrainWorker:
    def __init__(
        self,
        redis_client,
        pool: asyncpg.Pool,
        job_queue: RetrainJobQueue,
        model_registry: FeedbackModelRegistry,
        ingestion_db: "IngestionDB",
        geo_db: "GeospatialDB",
        model_dir: str = "data/models",
    ) -> None:
        self._redis = redis_client
        self._pool = pool
        self._job_queue = job_queue
        self._model_registry = model_registry
        self._ingestion_db = ingestion_db
        self._geo_db = geo_db
        self._model_dir = Path(model_dir)
        self._running = False

    async def start(self) -> None:
        """Dequeue and execute retrain jobs until stop() or cancellation."""
        self._running = True
        logger.info("RetrainWorker: starting")
        while self._running:
            try:
                job = await self._job_queue.dequeue(timeout=5)
                if job is None:
                    continue
                await self.execute_job(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("RetrainWorker: unexpected error: {}", exc)
        logger.info("RetrainWorker: stopped")

    def stop(self) -> None:
        self._running = False

    async def execute_job(self, job: RetrainJob) -> None:
        started_at = datetime.now(timezone.utc)
        logger.info(
            "RetrainWorker: executing {} {} (job_id={})",
            job.target_type,
            job.target_id,
            job.job_id,
        )
        try:
            await _log_job_start(self._pool, job, started_at)
        except Exception as exc:
            logger.warning("RetrainWorker: failed to log job start: {}", exc)

        try:
            if job.target_type == "bin":
                await self._retrain_bin(job)
            elif job.target_type == "zone":
                await self._retrain_zone(job)
            else:
                raise ValueError(f"unknown target_type: {job.target_type!r}")

            completed_at = datetime.now(timezone.utc)
            await _log_job_done(self._pool, job.job_id, completed_at, "done")
            logger.info(
                "RetrainWorker: job {} done in {:.1f}s",
                job.job_id,
                (completed_at - started_at).total_seconds(),
            )
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            logger.error("RetrainWorker: job {} failed: {}", job.job_id, exc)
            try:
                await _log_job_done(
                    self._pool, job.job_id, completed_at, "failed", str(exc)
                )
            except Exception:
                pass

    async def _retrain_bin(self, job: RetrainJob) -> None:
        from ml.trainer import train_bin_prophet
        from ml.models.prophet_model import ProphetForecaster

        bin_id = job.target_id
        tmp_dir = self._model_dir / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        final_path = self._model_dir / f"prophet_{bin_id}.pkl"

        ok = await train_bin_prophet(
            bin_id, self._ingestion_db, model_dir=str(tmp_dir)
        )
        if not ok:
            raise RuntimeError(
                f"train_bin_prophet returned False for bin {bin_id!r}"
            )

        tmp_trained = tmp_dir / f"prophet_{bin_id}.pkl"
        if not tmp_trained.exists():
            raise FileNotFoundError(f"trained model not found at {tmp_trained}")

        model = ProphetForecaster.load(str(tmp_trained))
        if not model._fitted:
            raise RuntimeError("smoke test failed: loaded Prophet model is not fitted")

        self._model_dir.mkdir(parents=True, exist_ok=True)
        os.replace(str(tmp_trained), str(final_path))
        await self._model_registry.register(
            f"prophet_{bin_id}", str(final_path), datetime.now(timezone.utc)
        )
        self._cleanup_tmp_dir(tmp_dir)

    async def _retrain_zone(self, job: RetrainJob) -> None:
        from ml.trainer import train_zone_gbm
        from ml.models.gbm_model import GBMForecaster

        zone_id = job.target_id
        tmp_dir = self._model_dir / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        final_path = self._model_dir / f"gbm_{zone_id}.pkl"

        bins = await self._geo_db.list_bins()
        bin_ids = [
            b.bin_id
            for b in bins
            if (b.zone_id or "__no_zone__") == zone_id
        ]
        if not bin_ids:
            raise RuntimeError(f"no bins found for zone {zone_id!r}")

        result = await train_zone_gbm(
            zone_id,
            bin_ids,
            self._ingestion_db,
            self._geo_db,
            model_dir=str(tmp_dir),
        )
        if result.error:
            raise RuntimeError(f"train_zone_gbm error: {result.error}")

        tmp_trained = tmp_dir / f"gbm_{zone_id}.pkl"
        if not tmp_trained.exists():
            raise FileNotFoundError(f"trained model not found at {tmp_trained}")

        model = GBMForecaster.load(str(tmp_trained))
        if not model._fitted:
            raise RuntimeError("smoke test failed: loaded GBM model is not fitted")

        self._model_dir.mkdir(parents=True, exist_ok=True)
        os.replace(str(tmp_trained), str(final_path))
        await self._model_registry.register(
            f"gbm_{zone_id}", str(final_path), datetime.now(timezone.utc)
        )
        self._cleanup_tmp_dir(tmp_dir)

    def _cleanup_tmp_dir(self, tmp_dir: Path) -> None:
        try:
            if tmp_dir.exists() and not any(tmp_dir.iterdir()):
                tmp_dir.rmdir()
        except Exception:
            pass
