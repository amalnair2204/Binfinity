"""Model registry and prediction engine."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from loguru import logger

from ml.features import build_feature_vector
from ml.models.ensemble import EnsembleForecaster
from ml.models.gbm_model import GBMForecaster
from ml.models.prophet_model import ProphetForecaster
from ml.schemas import ModelStatus, PredictionResult

if TYPE_CHECKING:
    from ingestion.db import IngestionDB
    from geospatial.db import GeospatialDB


class ModelRegistry:
    def __init__(self, model_dir: str = "data/models") -> None:
        self.model_dir = Path(model_dir)
        self._prophet: dict[str, ProphetForecaster] = {}   # keyed by bin_id
        self._gbm: dict[str, GBMForecaster] = {}           # keyed by zone_id
        self._load_timestamps: dict[str, datetime] = {}    # bin_id -> when loaded

    def load_all(self) -> None:
        """Scan model_dir for prophet_*.pkl and gbm_*.pkl files and load them.

        Idempotent — safe to call multiple times (reloads all found models).
        """
        if not self.model_dir.exists():
            logger.warning("ModelRegistry: model_dir {} does not exist", self.model_dir)
            return

        self._prophet.clear()
        self._gbm.clear()
        self._load_timestamps.clear()

        prophet_count = 0
        gbm_count = 0

        for pkl_path in self.model_dir.glob("prophet_*.pkl"):
            key = pkl_path.stem[len("prophet_"):]  # strip "prophet_" prefix
            try:
                self._prophet[key] = ProphetForecaster.load(str(pkl_path))
                self._load_timestamps[key] = datetime.now(timezone.utc)
                prophet_count += 1
            except Exception as exc:
                logger.warning(
                    "ModelRegistry: failed to load Prophet model {} — {}",
                    pkl_path,
                    exc,
                )

        for pkl_path in self.model_dir.glob("gbm_*.pkl"):
            key = pkl_path.stem[len("gbm_"):]  # strip "gbm_" prefix
            try:
                self._gbm[key] = GBMForecaster.load(str(pkl_path))
                gbm_count += 1
            except Exception as exc:
                logger.warning(
                    "ModelRegistry: failed to load GBM model {} — {}",
                    pkl_path,
                    exc,
                )

        logger.info(
            "ModelRegistry.load_all: loaded {} Prophet models, {} GBM models",
            prophet_count,
            gbm_count,
        )

    def get_ensemble(self, bin_id: str, zone_id: str) -> EnsembleForecaster:
        """Return an EnsembleForecaster for the given bin and zone."""
        return EnsembleForecaster(
            prophet=self._prophet.get(bin_id),
            gbm=self._gbm.get(zone_id),
        )

    def list_model_status(self) -> list[ModelStatus]:
        """Return ModelStatus for every bin/zone that has at least one model.

        Returns one entry per bin_id in _prophet, and one per zone_id in _gbm
        (with bin_id=zone_id for GBM-only entries).
        """
        statuses: dict[str, ModelStatus] = {}

        for bin_id in self._prophet:
            statuses[bin_id] = ModelStatus(
                bin_id=bin_id,
                has_prophet=True,
                has_gbm=False,
                last_trained=self._load_timestamps.get(bin_id),
            )

        for zone_id in self._gbm:
            if zone_id in statuses:
                # Update existing entry with GBM flag
                existing = statuses[zone_id]
                statuses[zone_id] = ModelStatus(
                    bin_id=existing.bin_id,
                    has_prophet=existing.has_prophet,
                    has_gbm=True,
                    last_trained=existing.last_trained,
                )
            else:
                statuses[zone_id] = ModelStatus(
                    bin_id=zone_id,
                    has_prophet=False,
                    has_gbm=True,
                    last_trained=None,
                )

        return list(statuses.values())

    async def predict(
        self,
        bin_id: str,
        zone_id: str,
        ingestion_db: "IngestionDB",
        geo_db: "GeospatialDB",
    ) -> PredictionResult:
        """Build a prediction for a single bin.

        Fetches current features, constructs the ensemble, and returns a
        PredictionResult.
        """
        fv = await build_feature_vector(bin_id, ingestion_db, geo_db)
        ensemble = self.get_ensemble(bin_id, zone_id)

        prophet_df = None
        if bin_id in self._prophet:
            prophet_df = pd.DataFrame(
                {"ds": [fv.at_time], "y": [fv.fill_pct_current]}
            )

        return ensemble.predict(fv, prophet_df)

    async def predict_fleet(
        self,
        ingestion_db: "IngestionDB",
        geo_db: "GeospatialDB",
    ) -> list[PredictionResult]:
        """Predict for every active bin in the registry.

        Skips bins that fail prediction (logs a warning per failure).
        """
        bins = await geo_db.list_bins()
        active_bins = [b for b in bins if b.is_active]

        results: list[PredictionResult] = []
        for b in active_bins:
            try:
                result = await self.predict(
                    b.bin_id,
                    b.zone_id or "",
                    ingestion_db,
                    geo_db,
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "predict_fleet: prediction failed for bin {} — {}",
                    b.bin_id,
                    exc,
                )

        return results
