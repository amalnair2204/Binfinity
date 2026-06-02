"""ML Forecasting FastAPI server. Runs on port 8003."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from ingestion.db import IngestionDB
from geospatial.db import GeospatialDB
from ml.predictor import ModelRegistry
from ml.schemas import ModelStatus, PredictionResult, TrainingResult
from ml.trainer import train_all, train_bin_prophet

app = FastAPI(title="Binfinity ML Forecasting API", version="1.0.0")

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:binfinity@localhost:5432/binfinity",
)

ingestion_db: IngestionDB | None = None
geo_db: GeospatialDB | None = None
registry: ModelRegistry | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    global ingestion_db, geo_db, registry
    ingestion_db = IngestionDB(_DATABASE_URL)
    await ingestion_db.connect()
    geo_db = GeospatialDB(_DATABASE_URL)
    await geo_db.connect()
    registry = ModelRegistry()
    registry.load_all()
    logger.info("ML Forecasting API ready on port 8003")


@app.on_event("shutdown")
async def shutdown() -> None:
    if ingestion_db:
        await ingestion_db.close()
    if geo_db:
        await geo_db.close()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    ingestion_ok = ingestion_db is not None and ingestion_db._pool is not None
    geo_ok = geo_db is not None and geo_db._pool is not None
    n_prophet = len(registry._prophet) if registry else 0
    n_gbm = len(registry._gbm) if registry else 0
    registry_ok = registry is not None
    return {
        "status": "ok" if (ingestion_ok and geo_ok and registry_ok) else "degraded",
        "ingestion_db": ingestion_ok,
        "geo_db": geo_ok,
        "prophet_models": n_prophet,
        "gbm_models": n_gbm,
    }


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

@app.get("/predict/{bin_id}", response_model=PredictionResult)
async def predict_bin(bin_id: str) -> PredictionResult:
    if registry is None or ingestion_db is None or geo_db is None:
        raise HTTPException(status_code=503, detail="service not ready")
    entry = await geo_db.get_bin(bin_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"bin {bin_id!r} not found")
    try:
        return await registry.predict(bin_id, entry.zone_id or "", ingestion_db, geo_db)
    except Exception as exc:
        logger.error("predict_bin failed for {}: {}", bin_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


class BatchPredictRequest(BaseModel):
    bin_ids: list[str]


@app.post("/predict/batch", response_model=list[PredictionResult])
async def predict_batch(body: BatchPredictRequest) -> list[PredictionResult]:
    if registry is None or ingestion_db is None or geo_db is None:
        raise HTTPException(status_code=503, detail="service not ready")
    results: list[PredictionResult] = []
    for bin_id in body.bin_ids:
        entry = await geo_db.get_bin(bin_id)
        if entry is None:
            continue
        try:
            r = await registry.predict(bin_id, entry.zone_id or "", ingestion_db, geo_db)
            results.append(r)
        except Exception as exc:
            logger.warning("predict_batch: skipping bin {} — {}", bin_id, exc)
    return results


@app.get("/fleet/at_risk", response_model=list[PredictionResult])
async def fleet_at_risk(
    hours: float = Query(default=4.0, gt=0.0, le=24.0),
) -> list[PredictionResult]:
    if registry is None or ingestion_db is None or geo_db is None:
        raise HTTPException(status_code=503, detail="service not ready")
    all_predictions = await registry.predict_fleet(ingestion_db, geo_db)
    return [p for p in all_predictions if p.hours_until_critical <= hours]


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

async def _run_train_all() -> None:
    if ingestion_db is None or geo_db is None or registry is None:
        return
    results = await train_all(ingestion_db, geo_db)
    registry.load_all()
    logger.info("Background train_all complete: {} results", len(results))


@app.post("/train/all", response_model=dict)
async def train_all_bins(background_tasks: BackgroundTasks) -> dict:
    if ingestion_db is None or geo_db is None or registry is None:
        raise HTTPException(status_code=503, detail="service not ready")
    background_tasks.add_task(_run_train_all)
    return {"status": "training started"}


@app.post("/train/{bin_id}", response_model=dict)
async def train_bin(bin_id: str) -> dict:
    if ingestion_db is None or geo_db is None or registry is None:
        raise HTTPException(status_code=503, detail="service not ready")
    entry = await geo_db.get_bin(bin_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"bin {bin_id!r} not found")
    ok = await train_bin_prophet(bin_id, ingestion_db)
    if ok:
        registry.load_all()
    return {"bin_id": bin_id, "trained": ok}


# ---------------------------------------------------------------------------
# Model status
# ---------------------------------------------------------------------------

@app.get("/models/status", response_model=list[ModelStatus])
async def models_status() -> list[ModelStatus]:
    if registry is None:
        raise HTTPException(status_code=503, detail="service not ready")
    return registry.list_model_status()


@app.get("/models/status/{bin_id}", response_model=ModelStatus)
async def model_status_bin(bin_id: str) -> ModelStatus:
    if registry is None:
        raise HTTPException(status_code=503, detail="service not ready")
    for s in registry.list_model_status():
        if s.bin_id == bin_id:
            return s
    raise HTTPException(status_code=404, detail=f"no model found for bin {bin_id!r}")
