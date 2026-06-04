"""FastAPI endpoint tests for ml/api.py — fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ml.api import app
from ml.schemas import ModelStatus, PredictionResult, TrainingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prediction(bin_id="BIN-0001", hours=5.0, fill=50.0):
    return PredictionResult(
        bin_id=bin_id,
        predicted_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
        hours_until_critical=hours,
        fill_pct_current=fill,
        model_used="ensemble",
        confidence=1.0,
    )


def _make_model_status(bin_id="BIN-0001", has_prophet=True, has_gbm=True):
    return ModelStatus(
        bin_id=bin_id,
        has_prophet=has_prophet,
        has_gbm=has_gbm,
        last_trained=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )


def _make_bin_entry(bin_id="BIN-0001", zone_id="Z-COMMERCIAL"):
    entry = MagicMock()
    entry.bin_id = bin_id
    entry.zone_id = zone_id
    entry.is_active = True
    return entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_services(monkeypatch):
    mock_registry = MagicMock()
    mock_registry._prophet = {"BIN-0001": MagicMock()}
    mock_registry._gbm = {"Z-COMMERCIAL": MagicMock()}
    mock_registry.list_model_status.return_value = [
        _make_model_status("BIN-0001"),
        _make_model_status("BIN-0002"),
    ]
    mock_registry.predict = AsyncMock(return_value=_make_prediction())
    mock_registry.predict_fleet = AsyncMock(return_value=[
        _make_prediction("BIN-0001", hours=2.0),
        _make_prediction("BIN-0002", hours=6.0),
    ])
    mock_registry.load_all = MagicMock()

    mock_ingestion = MagicMock()
    mock_ingestion._pool = MagicMock()

    mock_geo = AsyncMock()
    mock_geo._pool = MagicMock()
    mock_geo.get_bin = AsyncMock(return_value=_make_bin_entry())
    mock_geo.list_bins = AsyncMock(return_value=[])

    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", mock_registry)
    monkeypatch.setattr(api_module, "ingestion_db", mock_ingestion)
    monkeypatch.setattr(api_module, "geo_db", mock_geo)

    return mock_registry, mock_ingestion, mock_geo


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["ingestion_db"] is True
    assert data["geo_db"] is True
    assert data["prophet_models"] == 1
    assert data["gbm_models"] == 1


def test_health_no_registry(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


def test_health_degraded_no_pool(monkeypatch):
    import ml.api as api_module
    mock_ingestion = MagicMock()
    mock_ingestion._pool = None
    monkeypatch.setattr(api_module, "ingestion_db", mock_ingestion)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /predict/{bin_id}
# ---------------------------------------------------------------------------

def test_predict_bin_ok():
    r = client.get("/predict/BIN-0001")
    assert r.status_code == 200
    data = r.json()
    assert data["bin_id"] == "BIN-0001"
    assert "hours_until_critical" in data
    assert "model_used" in data


def test_predict_bin_not_found(monkeypatch):
    import ml.api as api_module
    mock_geo = AsyncMock()
    mock_geo._pool = MagicMock()
    mock_geo.get_bin = AsyncMock(return_value=None)
    monkeypatch.setattr(api_module, "geo_db", mock_geo)

    r = client.get("/predict/BIN-GHOST")
    assert r.status_code == 404


def test_predict_bin_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", None)

    r = client.get("/predict/BIN-0001")
    assert r.status_code == 503


def test_predict_bin_registry_error(monkeypatch):
    import ml.api as api_module
    mock_reg = MagicMock()
    mock_reg._prophet = {}
    mock_reg._gbm = {}
    mock_reg.predict = AsyncMock(side_effect=RuntimeError("DB error"))
    monkeypatch.setattr(api_module, "registry", mock_reg)

    r = client.get("/predict/BIN-0001")
    assert r.status_code == 500


# ---------------------------------------------------------------------------
# POST /predict/batch
# ---------------------------------------------------------------------------

def test_predict_batch_ok():
    r = client.post("/predict/batch", json={"bin_ids": ["BIN-0001", "BIN-0002"]})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_predict_batch_empty_list():
    r = client.post("/predict/batch", json={"bin_ids": []})
    assert r.status_code == 200
    assert r.json() == []


def test_predict_batch_skips_missing_bins(monkeypatch):
    import ml.api as api_module
    mock_geo = AsyncMock()
    mock_geo._pool = MagicMock()
    mock_geo.get_bin = AsyncMock(return_value=None)  # all bins missing
    monkeypatch.setattr(api_module, "geo_db", mock_geo)

    r = client.post("/predict/batch", json={"bin_ids": ["BIN-X", "BIN-Y"]})
    assert r.status_code == 200
    assert r.json() == []


def test_predict_batch_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "ingestion_db", None)

    r = client.post("/predict/batch", json={"bin_ids": ["BIN-0001"]})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /fleet/at_risk
# ---------------------------------------------------------------------------

def test_fleet_at_risk_default():
    r = client.get("/fleet/at_risk")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Default hours=4.0 — only BIN-0001 with 2.0 hours should be returned
    assert all(p["hours_until_critical"] <= 4.0 for p in data)


def test_fleet_at_risk_custom_hours():
    r = client.get("/fleet/at_risk?hours=10.0")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert all(p["hours_until_critical"] <= 10.0 for p in data)


def test_fleet_at_risk_zero_hours():
    r = client.get("/fleet/at_risk?hours=0.5")
    assert r.status_code == 200


def test_fleet_at_risk_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", None)

    r = client.get("/fleet/at_risk")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /train/{bin_id}
# ---------------------------------------------------------------------------

def test_train_bin_ok(monkeypatch):
    import ml.api as api_module
    with patch("ml.api.train_bin_prophet", new_callable=AsyncMock, return_value=True):
        r = client.post("/train/BIN-0001")
    assert r.status_code == 200
    data = r.json()
    assert data["bin_id"] == "BIN-0001"
    assert data["trained"] is True


def test_train_bin_not_found(monkeypatch):
    import ml.api as api_module
    mock_geo = AsyncMock()
    mock_geo._pool = MagicMock()
    mock_geo.get_bin = AsyncMock(return_value=None)
    monkeypatch.setattr(api_module, "geo_db", mock_geo)

    r = client.post("/train/BIN-GHOST")
    assert r.status_code == 404


def test_train_bin_insufficient_data(monkeypatch):
    with patch("ml.api.train_bin_prophet", new_callable=AsyncMock, return_value=False):
        r = client.post("/train/BIN-0001")
    assert r.status_code == 200
    assert r.json()["trained"] is False


def test_train_bin_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "ingestion_db", None)

    r = client.post("/train/BIN-0001")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /train/all
# ---------------------------------------------------------------------------

def test_train_all_starts_background():
    r = client.post("/train/all")
    assert r.status_code == 200
    assert r.json()["status"] == "training started"


def test_train_all_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "geo_db", None)

    r = client.post("/train/all")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /models/status
# ---------------------------------------------------------------------------

def test_models_status_ok():
    r = client.get("/models/status")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert all("bin_id" in s for s in data)


def test_models_status_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", None)

    r = client.get("/models/status")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# GET /models/status/{bin_id}
# ---------------------------------------------------------------------------

def test_models_status_bin_found():
    r = client.get("/models/status/BIN-0001")
    assert r.status_code == 200
    data = r.json()
    assert data["bin_id"] == "BIN-0001"
    assert "has_prophet" in data
    assert "has_gbm" in data


def test_models_status_bin_not_found():
    r = client.get("/models/status/BIN-GHOST")
    assert r.status_code == 404


def test_models_status_bin_service_not_ready(monkeypatch):
    import ml.api as api_module
    monkeypatch.setattr(api_module, "registry", None)

    r = client.get("/models/status/BIN-0001")
    assert r.status_code == 503
