"""Ingestion API endpoint tests — fakeredis, mocked DB."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from ingestion.api import app
from ingestion.cache import BinStateCache
from ingestion.schemas import BinState

TS = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)


def make_state(bin_id: str = "BIN-0001", **kwargs) -> BinState:
    defaults = dict(
        bin_id=bin_id,
        last_updated=TS,
        fill_pct=67.4,
        fill_liters=80.9,
        status="operational",
        battery_mv=3720,
        consecutive_fault_ticks=0,
        flagged_for_collection=False,
        last_emptied=None,
    )
    defaults.update(kwargs)
    return BinState(**defaults)


def _build_fleet(n: int = 5, *, flagged: int = 2, faulted: int = 1) -> dict[str, BinState]:
    fleet = {}
    for i in range(1, n + 1):
        fill = 90.0 if i <= flagged else 50.0
        status = "sensor_fault" if i == flagged + 1 else (
            "pending_collection" if i <= flagged else "operational"
        )
        fleet[f"BIN-{i:04d}"] = make_state(
            bin_id=f"BIN-{i:04d}",
            fill_pct=fill,
            status=status,
            flagged_for_collection=(i <= flagged),
        )
    return fleet


@pytest.fixture(autouse=True)
def mock_worker_state(monkeypatch):
    fleet = _build_fleet()
    import ingestion.worker as worker_module
    monkeypatch.setattr(worker_module, "_bin_states", fleet)
    monkeypatch.setattr(worker_module, "packets_processed", 42)
    monkeypatch.setattr(worker_module, "worker_running", True)

    fake_redis = fakeredis.aioredis.FakeRedis()
    fake_cache = BinStateCache.__new__(BinStateCache)
    fake_cache._redis = fake_redis
    monkeypatch.setattr(worker_module, "cache", fake_cache)

    fake_db = MagicMock()
    fake_db.get_bin_history = AsyncMock(return_value=[{"time": TS, "fill_pct": 67.4}] * 10)
    fake_db.upsert_bin_state = AsyncMock()
    monkeypatch.setattr(worker_module, "db", fake_db)

    return fleet


client = TestClient(app)


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health_returns_200():
    r = client.get("/health")
    assert r.status_code == 200


def test_health_contains_required_fields():
    r = client.get("/health")
    data = r.json()
    assert {"worker_running", "packets_processed"}.issubset(data)


# ── GET /bins ─────────────────────────────────────────────────────────────────

def test_get_bins_returns_all():
    r = client.get("/bins")
    assert r.status_code == 200
    assert len(r.json()) == 5


# ── GET /bins/{bin_id} ────────────────────────────────────────────────────────

def test_get_bin_returns_correct_state():
    r = client.get("/bins/BIN-0001")
    assert r.status_code == 200
    assert r.json()["bin_id"] == "BIN-0001"


def test_get_bin_unknown_returns_404():
    r = client.get("/bins/BIN-9999")
    assert r.status_code == 404


# ── GET /bins/{bin_id}/history ────────────────────────────────────────────────

def test_get_history_returns_rows():
    r = client.get("/bins/BIN-0001/history?limit=10")
    assert r.status_code == 200
    assert len(r.json()) == 10


def test_get_history_unknown_bin_returns_404():
    r = client.get("/bins/BIN-9999/history")
    assert r.status_code == 404


# ── GET /fleet/stats ──────────────────────────────────────────────────────────

def test_fleet_stats_returns_counts():
    r = client.get("/fleet/stats")
    assert r.status_code == 200
    data = r.json()
    assert {"total", "flagged", "faulted", "tipped", "low_battery", "overflow_risk"}.issubset(data)


# ── GET /fleet/flagged ────────────────────────────────────────────────────────

def test_fleet_flagged_returns_only_flagged():
    r = client.get("/fleet/flagged")
    assert r.status_code == 200
    items = r.json()
    assert all(b["flagged_for_collection"] for b in items)


# ── GET /fleet/critical ───────────────────────────────────────────────────────

def test_fleet_critical_includes_high_fill():
    r = client.get("/fleet/critical")
    assert r.status_code == 200
    for b in r.json():
        assert b["fill_pct"] >= 85.0 or b["status"] == "tipped"


# ── POST /bins/{bin_id}/acknowledge ──────────────────────────────────────────

def test_acknowledge_unknown_bin_returns_404():
    r = client.post("/bins/BIN-9999/acknowledge")
    assert r.status_code == 404


def test_acknowledge_returns_200_on_known_bin():
    r = client.post("/bins/BIN-0001/acknowledge")
    assert r.status_code == 200
