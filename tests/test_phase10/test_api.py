"""Tests for feedback/api.py — fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from feedback.api import app
from feedback.job_queue import RetrainJobQueue
from feedback.model_registry import FeedbackModelRegistry


@pytest.fixture(autouse=True)
def mock_services(fake_redis, mock_db_pool, monkeypatch):
    pool, conn = mock_db_pool
    job_queue = RetrainJobQueue(fake_redis)
    registry = FeedbackModelRegistry(fake_redis)

    import feedback.api as api_module

    monkeypatch.setattr(api_module, "_redis", fake_redis)
    monkeypatch.setattr(api_module, "_pool", pool)
    monkeypatch.setattr(api_module, "_job_queue", job_queue)
    monkeypatch.setattr(api_module, "_model_registry", registry)
    monkeypatch.setattr(api_module, "_consumer", None)

    return fake_redis, pool, conn, job_queue, registry


client = TestClient(app)


def test_health_returns_200():
    r = client.get("/calibration/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "queue_size" in data
    assert data["consumer_running"] is False


def test_accuracy_fleet_returns_200(mock_db_pool, monkeypatch):
    _, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={"mae": 1.5, "within1h_pct": 0.7, "n_events": 50}
    )
    import feedback.api as api_module
    monkeypatch.setattr(api_module, "_pool", mock_db_pool[0])

    r = client.get("/calibration/accuracy/fleet")
    assert r.status_code == 200
    data = r.json()
    assert "mae" in data or "n_events" in data


def test_accuracy_worst_returns_list(mock_db_pool, monkeypatch):
    _, conn = mock_db_pool
    conn.fetch = AsyncMock(return_value=[])
    import feedback.api as api_module
    monkeypatch.setattr(api_module, "_pool", mock_db_pool[0])

    r = client.get("/calibration/accuracy/worst?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_accuracy_bin_returns_200(mock_db_pool, monkeypatch):
    _, conn = mock_db_pool
    conn.fetchrow = AsyncMock(
        return_value={"mae": 2.0, "within1h_pct": 0.5, "n_events": 8}
    )
    import feedback.api as api_module
    monkeypatch.setattr(api_module, "_pool", mock_db_pool[0])

    r = client.get("/calibration/accuracy/BIN-001")
    assert r.status_code == 200
    data = r.json()
    assert data["bin_id"] == "BIN-001"


def test_retrain_queue_returns_list():
    r = client.get("/calibration/retrain/queue")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_retrain_jobs_returns_list():
    r = client.get("/calibration/retrain/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trigger_retrain_bin_enqueues_job():
    r = client.post(
        "/calibration/retrain/trigger/BIN-001",
        json={"reason": "test trigger"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["bin_id"] == "BIN-001"
    assert "queued" in data


def test_registry_returns_dict():
    r = client.get("/calibration/registry")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_service_not_ready_returns_503(monkeypatch):
    import feedback.api as api_module
    monkeypatch.setattr(api_module, "_redis", None)
    r = client.get("/calibration/health")
    assert r.status_code == 503
