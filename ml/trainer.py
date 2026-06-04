"""Training orchestrator for ML forecasting models."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from loguru import logger

from ml.features import build_feature_matrix, build_feature_vector
from ml.models.gbm_model import GBMForecaster
from ml.models.prophet_model import ProphetForecaster
from ml.schemas import TrainingResult

if TYPE_CHECKING:
    from ingestion.db import IngestionDB
    from geospatial.db import GeospatialDB


async def generate_labels(
    bin_id: str,
    ingestion_db: "IngestionDB",
    window_hours: int = 24,
    threshold: float = 85.0,
) -> pd.DataFrame:
    """For each historical telemetry row, compute hours until threshold was reached.

    Returns DataFrame with columns: time, fill_pct, hours_until_critical.
    Rows with sensor_fault=TRUE are excluded.
    Label capped at window_hours if threshold never reached within that window.
    """
    if ingestion_db._pool is None:
        raise RuntimeError("IngestionDB pool is not connected")

    async with ingestion_db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, fill_pct FROM telemetry
            WHERE bin_id = $1 AND sensor_fault = FALSE
            ORDER BY time ASC
            """,
            bin_id,
        )

    if len(rows) < 10:
        logger.warning(
            "generate_labels: only {} rows for bin {} (need >=10), returning empty",
            len(rows),
            bin_id,
        )
        return pd.DataFrame(columns=["time", "fill_pct", "hours_until_critical"])

    times = [r["time"] for r in rows]
    fills = [r["fill_pct"] for r in rows]
    n = len(times)

    labels = []
    for i in range(n):
        if fills[i] >= threshold:
            # Already critical — skip
            continue

        label = float(window_hours)  # default: threshold not reached within window
        for j in range(i + 1, n):
            elapsed_hours = (times[j] - times[i]).total_seconds() / 3600.0
            if elapsed_hours > window_hours:
                # Exceeded window; stop scanning
                break
            if fills[j] >= threshold:
                label = elapsed_hours
                break

        labels.append({
            "time": times[i],
            "fill_pct": fills[i],
            "hours_until_critical": label,
        })

    return pd.DataFrame(labels)


async def train_bin_prophet(
    bin_id: str,
    ingestion_db: "IngestionDB",
    model_dir: str = "data/models",
) -> bool:
    """Train Prophet on last 30 days of telemetry. Returns True if trained."""
    try:
        if ingestion_db._pool is None:
            raise RuntimeError("IngestionDB pool is not connected")

        async with ingestion_db._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time, fill_pct, event_type FROM telemetry
                WHERE bin_id = $1 AND sensor_fault = FALSE
                AND time >= NOW() - INTERVAL '30 days'
                ORDER BY time ASC
                """,
                bin_id,
            )

        if len(rows) < 48:
            logger.warning(
                "train_bin_prophet: only {} rows for bin {} (need >=48), skipping",
                len(rows),
                bin_id,
            )
            return False

        df = pd.DataFrame([dict(r) for r in rows])
        df["ds"] = pd.to_datetime(df["time"])
        df["y"] = df["fill_pct"].astype(float)
        df["is_weekend"] = df["ds"].dt.dayofweek.isin([5, 6]).astype(int)
        df["hour_of_day"] = df["ds"].dt.hour
        df["spike_count"] = (df["event_type"] == "spike").astype(int)

        forecaster = ProphetForecaster()
        forecaster.fit(df[["ds", "y", "is_weekend", "hour_of_day", "spike_count"]])

        Path(model_dir).mkdir(parents=True, exist_ok=True)
        save_path = str(Path(model_dir) / f"prophet_{bin_id}.pkl")
        forecaster.save(save_path)

        logger.info("Trained Prophet for bin {} → {}", bin_id, save_path)
        return True

    except Exception as exc:
        logger.error("train_bin_prophet failed for bin {}: {}", bin_id, exc)
        return False


async def train_zone_gbm(
    zone_id: str,
    bin_ids: list[str],
    ingestion_db: "IngestionDB",
    geo_db: "GeospatialDB",
    model_dir: str = "data/models",
) -> TrainingResult:
    """Train a single GBM model on all bins in a zone."""
    trained_at = datetime.now(timezone.utc)
    try:
        if not bin_ids:
            return TrainingResult(
                bin_id=zone_id,
                zone_id=zone_id,
                trained_at=trained_at,
                error="no bins in zone",
            )

        # Step 1: generate labels for each bin
        bin_labels: list[pd.DataFrame] = []
        for bin_id in bin_ids:
            try:
                labels_df = await generate_labels(bin_id, ingestion_db)
                if labels_df.empty:
                    continue
                labels_df = labels_df.copy()
                labels_df["bin_id"] = bin_id
                bin_labels.append(labels_df)
            except Exception as exc:
                logger.warning("generate_labels failed for bin {}: {}", bin_id, exc)

        # Step 2: build features per-bin individually (keyed dict avoids alignment bugs)
        bin_feature_rows: dict[str, pd.Series] = {}
        for bin_id in bin_ids:
            try:
                fv = await build_feature_vector(bin_id, ingestion_db, geo_db)
                row = fv.model_dump()
                row.pop("bin_id", None)
                row.pop("at_time", None)
                bin_feature_rows[bin_id] = pd.Series(row)
            except Exception as exc:
                logger.warning("Feature build failed for bin {}: {}", bin_id, exc)

        # Step 3: align — replicate each bin's current feature vector for all its label rows
        X_rows: list[pd.Series] = []
        y_rows: list[float] = []

        for bin_id in bin_ids:
            bin_label_df = next(
                (df for df in bin_labels if not df.empty and (df["bin_id"] == bin_id).any()),
                None,
            )
            if bin_label_df is None or bin_label_df.empty:
                continue
            feature_row = bin_feature_rows.get(bin_id)
            if feature_row is None:
                continue
            n_samples = len(bin_label_df)
            X_rows.extend([feature_row] * n_samples)
            y_rows.extend(bin_label_df["hours_until_critical"].tolist())

        if len(y_rows) < 10:
            return TrainingResult(
                bin_id=zone_id,
                zone_id=zone_id,
                trained_at=trained_at,
                error="insufficient data",
            )

        X_all = pd.DataFrame(X_rows).reset_index(drop=True)
        y_all = pd.Series(y_rows, name="hours_until_critical")

        # Step 4: fit GBM
        forecaster = GBMForecaster()
        forecaster.fit(X_all, y_all)

        # Step 5: save
        Path(model_dir).mkdir(parents=True, exist_ok=True)
        save_path = str(Path(model_dir) / f"gbm_{zone_id}.pkl")
        forecaster.save(save_path)

        logger.info(
            "Trained GBM for zone {} on {} samples → {}",
            zone_id,
            len(y_all),
            save_path,
        )
        return TrainingResult(
            bin_id=zone_id,
            zone_id=zone_id,
            trained_at=trained_at,
            gbm_trained=True,
            n_samples=len(y_all),
        )

    except Exception as exc:
        logger.error("train_zone_gbm failed for zone {}: {}", zone_id, exc)
        return TrainingResult(
            bin_id=zone_id,
            zone_id=zone_id,
            trained_at=trained_at,
            error=str(exc),
        )


async def train_all(
    ingestion_db: "IngestionDB",
    geo_db: "GeospatialDB",
    model_dir: str = "data/models",
) -> list[TrainingResult]:
    """Train all bins (Prophet) and all zones (GBM)."""
    results: list[TrainingResult] = []

    # Step 1: get all bins
    bins = await geo_db.list_bins()
    n_bins = len(bins)

    # Step 2: group bins by zone_id
    zone_to_bins: dict[str, list[str]] = {}
    for b in bins:
        zid = b.zone_id or "__no_zone__"
        zone_to_bins.setdefault(zid, []).append(b.bin_id)
    n_zones = len(zone_to_bins)

    # Step 3: train GBM per zone
    zone_results: dict[str, TrainingResult] = {}
    for zone_id, bin_ids in zone_to_bins.items():
        zr = await train_zone_gbm(zone_id, bin_ids, ingestion_db, geo_db, model_dir)
        zone_results[zone_id] = zr

    # Step 4: train Prophet per bin; combine with zone GBM result
    for b in bins:
        prophet_ok = await train_bin_prophet(b.bin_id, ingestion_db, model_dir)
        zid = b.zone_id or "__no_zone__"
        zone_gbm_trained = zone_results.get(zid, TrainingResult(
            bin_id=zid, zone_id=zid, trained_at=datetime.now(timezone.utc)
        )).gbm_trained

        results.append(TrainingResult(
            bin_id=b.bin_id,
            zone_id=zid,
            trained_at=datetime.now(timezone.utc),
            prophet_trained=prophet_ok,
            gbm_trained=zone_gbm_trained,
        ))

    # Also append the zone-level results (GBM summaries with n_samples)
    for zr in zone_results.values():
        results.append(zr)

    logger.info("Training complete: {} bins, {} zones", n_bins, n_zones)
    return results
