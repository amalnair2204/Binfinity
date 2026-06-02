"""Ingestion pipeline FastAPI server. Reads from Redis for fast queries."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from loguru import logger

app = FastAPI(title="Binfinity Ingestion API", version="1.0.0")


def _get_worker():
    import ingestion.worker as w
    return w


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    w = _get_worker()
    return {
        "worker_running": w.worker_running,
        "packets_processed": w.packets_processed,
        "status": "ok",
    }


# ── GET /bins ─────────────────────────────────────────────────────────────────

@app.get("/bins")
async def list_bins() -> list[dict]:
    w = _get_worker()
    return [s.model_dump(mode="json") for s in w._bin_states.values()]


# ── GET /bins/{bin_id} ────────────────────────────────────────────────────────

@app.get("/bins/{bin_id}")
async def get_bin(bin_id: str) -> dict:
    w = _get_worker()
    state = w._bin_states.get(bin_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    return state.model_dump(mode="json")


# ── GET /bins/{bin_id}/history ────────────────────────────────────────────────

@app.get("/bins/{bin_id}/history")
async def get_history(bin_id: str, limit: int = 100) -> list[dict]:
    w = _get_worker()
    if bin_id not in w._bin_states:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    rows = await w.db.get_bin_history(bin_id, limit=limit)
    return rows


# ── GET /fleet/stats ──────────────────────────────────────────────────────────

@app.get("/fleet/stats")
async def fleet_stats() -> dict:
    w = _get_worker()
    states = list(w._bin_states.values())
    from collections import Counter
    status_counts = Counter(s.status for s in states)
    return {
        "total": len(states),
        "operational": status_counts.get("operational", 0),
        "flagged": sum(1 for s in states if s.flagged_for_collection),
        "faulted": status_counts.get("sensor_fault", 0),
        "tipped": status_counts.get("tipped", 0),
        "low_battery": status_counts.get("low_battery", 0),
        "overflow_risk": status_counts.get("overflow_risk", 0),
        "pending_collection": status_counts.get("pending_collection", 0),
    }


# ── GET /fleet/flagged ────────────────────────────────────────────────────────

@app.get("/fleet/flagged")
async def fleet_flagged() -> list[dict]:
    w = _get_worker()
    flagged = [s for s in w._bin_states.values() if s.flagged_for_collection]
    flagged.sort(key=lambda s: s.fill_pct, reverse=True)
    return [s.model_dump(mode="json") for s in flagged]


# ── GET /fleet/critical ───────────────────────────────────────────────────────

@app.get("/fleet/critical")
async def fleet_critical() -> list[dict]:
    w = _get_worker()
    critical = [
        s for s in w._bin_states.values()
        if s.fill_pct >= 85.0 or s.status == "tipped"
    ]
    return [s.model_dump(mode="json") for s in critical]


# ── POST /bins/{bin_id}/acknowledge ──────────────────────────────────────────

@app.post("/bins/{bin_id}/acknowledge")
async def acknowledge_bin(bin_id: str) -> dict:
    w = _get_worker()
    state = w._bin_states.get(bin_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")

    # Clear tipped or sensor_fault — ops override
    new_state = state.model_copy(deep=True)
    if new_state.status in ("tipped", "sensor_fault"):
        new_state.status = "operational"
        new_state.consecutive_fault_ticks = 0
        w._bin_states[bin_id] = new_state
        await w.db.upsert_bin_state(new_state)
        if w.cache:
            await w.cache.set_bin_state(new_state)
        logger.info(f"Acknowledged {bin_id} — status reset to operational")

    return {"bin_id": bin_id, "status": new_state.status, "acknowledged": True}
