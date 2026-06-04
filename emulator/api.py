"""FastAPI server for the Binfinity emulator. Engine injected by sim_engine at startup."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

app = FastAPI(title="Binfinity Emulator API", version="1.0.0")

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

_engine: Any = None   # Set by sim_engine.set_engine()


def set_engine(engine: Any) -> None:
    global _engine
    _engine = engine


def _require_engine():
    if _engine is None:
        raise RuntimeError("Engine not initialised — call set_engine() first")
    return _engine


def _bin_to_dict(b) -> dict:
    return {
        "bin_id": b.bin_id,
        "lat": b.lat,
        "lng": b.lng,
        "zone": b.zone,
        "capacity_liters": b.capacity_liters,
        "current_fill_pct": round(b.current_fill_pct, 2),
        "fill_liters": round(b.current_fill_pct / 100.0 * b.capacity_liters, 2),
        "sensor_fault": b.sensor_fault,
        "tipped": b.tipped,
        "battery_mv": b.battery_mv,
        "marked_for_collection": b.marked_for_collection,
        "wake_interval_minutes": b.wake_interval_minutes,
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/bins")
async def list_bins() -> list[dict]:
    engine = _require_engine()
    return [_bin_to_dict(b) for b in engine.bins.values()]


@app.get("/bins/{bin_id}")
async def get_bin(bin_id: str) -> dict:
    engine = _require_engine()
    if bin_id not in engine.bins:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    return _bin_to_dict(engine.bins[bin_id])


@app.get("/telemetry/stream")
async def telemetry_stream():
    import asyncio
    engine = _require_engine()
    queue: asyncio.Queue = asyncio.Queue()
    engine.sse_subscribers.add(queue)

    async def _generate():
        try:
            while True:
                packet = await queue.get()
                try:
                    yield f"data: {packet.model_dump_json()}\n\n"
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            engine.sse_subscribers.discard(queue)

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.post("/bins/{bin_id}/collect")
async def collect_bin(bin_id: str) -> dict:
    engine = _require_engine()
    if bin_id not in engine.bins:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    engine.bins[bin_id].marked_for_collection = True
    logger.info(f"Bin {bin_id} marked for collection")
    return {"status": "marked_for_collection", "bin_id": bin_id}


@app.get("/stats")
async def stats() -> dict:
    engine = _require_engine()
    bins = list(engine.bins.values())
    if not bins:
        return {"total_bins": 0, "avg_fill_pct": 0.0, "bins_over_80": 0, "faulted_count": 0}
    total = len(bins)
    return {
        "total_bins": total,
        "avg_fill_pct": round(sum(b.current_fill_pct for b in bins) / total, 2),
        "bins_over_80": sum(1 for b in bins if b.current_fill_pct > 80.0),
        "faulted_count": sum(1 for b in bins if b.sensor_fault),
    }


class _SpeedBody(BaseModel):
    ticks_per_second: float = 1.0


@app.post("/sim/speed")
async def set_speed(body: _SpeedBody) -> dict:
    engine = _require_engine()
    tps = max(0.01, body.ticks_per_second)   # floor at 0.01 to avoid /0
    engine.tick_interval = 1.0 / tps
    logger.info(f"Sim speed set to {tps} tps (interval={engine.tick_interval:.3f}s)")
    return {"ticks_per_second": tps, "tick_interval_seconds": engine.tick_interval}
