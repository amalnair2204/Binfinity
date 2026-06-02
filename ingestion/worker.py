"""
Ingestion worker — consumes Phase 1 SSE stream, runs state machine,
writes to TimescaleDB + Redis, exposes FastAPI.

Start: python -m ingestion.worker
"""
from __future__ import annotations

import asyncio
import os

import httpx
from loguru import logger
from pydantic import ValidationError

from ingestion.cache import BinStateCache
from ingestion.db import IngestionDB
from ingestion.schemas import BinState, TelemetryPacket
from ingestion.state_machine import transition

_EMULATOR_URL = os.getenv("EMULATOR_URL", "http://localhost:8000")
_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:binfinity@localhost:5432/binfinity",
)
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_BATCH_FLUSH_SECONDS = float(os.getenv("BATCH_FLUSH_SECONDS", "5"))

# Shared state — populated at startup for API layer
db: IngestionDB | None = None
cache: BinStateCache | None = None
packets_processed: int = 0
worker_running: bool = False
_batch_queue: asyncio.Queue[TelemetryPacket] = asyncio.Queue()
_bin_states: dict[str, BinState] = {}   # in-memory fallback for API when Redis slow


async def _consume_sse() -> None:
    global packets_processed, worker_running
    backoff = 1.0
    worker_running = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET", f"{_EMULATOR_URL}/telemetry/stream"
                ) as response:
                    logger.info("SSE stream connected")
                    backoff = 1.0
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            packet = TelemetryPacket.model_validate_json(raw)
                        except ValidationError as exc:
                            logger.warning(f"Invalid packet skipped: {exc}")
                            continue

                        await _process_packet(packet)
                        packets_processed += 1

        except Exception as exc:
            logger.warning(f"SSE disconnected: {exc}. Reconnecting in {backoff:.1f}s")
            worker_running = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            worker_running = True


async def _process_packet(packet: TelemetryPacket) -> None:
    current = _bin_states.get(packet.bin_id)
    if current is None:
        current = BinState(
            bin_id=packet.bin_id,
            last_updated=packet.timestamp,
            fill_pct=packet.fill_pct,
            fill_liters=packet.fill_liters,
            status="operational",
            battery_mv=packet.battery_mv,
        )

    new_state, is_spill = transition(current, packet)
    _bin_states[packet.bin_id] = new_state

    # Immediate writes (state consistency)
    await db.upsert_bin_state(new_state)
    await cache.set_bin_state(new_state)

    if is_spill:
        await db.log_spill_incident(
            packet.bin_id, packet.timestamp, fill_at_spill=current.fill_pct
        )
        logger.warning(f"SPILL INCIDENT — {packet.bin_id} at {current.fill_pct:.1f}%")

    # Enqueue for batch telemetry insert
    await _batch_queue.put(packet)


async def _batch_flusher() -> None:
    while True:
        await asyncio.sleep(_BATCH_FLUSH_SECONDS)
        batch: list[TelemetryPacket] = []
        while not _batch_queue.empty():
            batch.append(_batch_queue.get_nowait())
        if batch:
            await db.bulk_insert_telemetry(batch)
            logger.debug(f"Flushed {len(batch)} telemetry rows to DB")


async def _main() -> None:
    global db, cache

    db = IngestionDB(_DATABASE_URL)
    await db.connect()

    cache = BinStateCache(_REDIS_URL)
    logger.info("Ingestion pipeline ready")

    from ingestion.api import app as api_app
    import uvicorn

    config = uvicorn.Config(api_app, host="0.0.0.0", port=8001, log_level="warning")
    server = uvicorn.Server(config)

    await asyncio.gather(
        _consume_sse(),
        _batch_flusher(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(_main())
