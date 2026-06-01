"""FastAPI endpoint tests using TestClient with a mock SimEngine."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from emulator.api import app, set_engine
from emulator.bin_model import BinNode


def _make_fleet(n: int = 200, *, bins_over_80: int = 10, faulted: int = 5) -> dict[str, BinNode]:
    """Build a known-state fleet for predictable stats assertions."""
    fleet: dict[str, BinNode] = {}
    for i in range(1, n + 1):
        fill = 90.0 if i <= bins_over_80 else 50.0
        b = BinNode(
            bin_id=f"BIN-{i:04d}",
            lat=25.2048, lng=55.2708,
            zone="residential",
            base_fill_rate=2.0,
            capacity_liters=120.0,
            current_fill_pct=fill,
            battery_mv=4000,
        )
        if bins_over_80 < i <= bins_over_80 + faulted:
            b.sensor_fault = True
        fleet[b.bin_id] = b
    return fleet


@pytest.fixture(autouse=True)
def engine():
    mock = MagicMock()
    mock.bins = _make_fleet()
    mock.tick_interval = 2.0
    mock.sse_subscribers = set()
    set_engine(mock)
    yield mock
    set_engine(None)


client = TestClient(app)


# ── GET /bins ─────────────────────────────────────────────────────────────────

def test_list_bins_returns_200_items():
    r = client.get("/bins")
    assert r.status_code == 200
    assert len(r.json()) == 200


def test_list_bins_contain_bin_id():
    r = client.get("/bins")
    ids = {b["bin_id"] for b in r.json()}
    assert "BIN-0001" in ids
    assert "BIN-0200" in ids


# ── GET /bins/{bin_id} ────────────────────────────────────────────────────────

def test_get_bin_returns_correct_state():
    r = client.get("/bins/BIN-0001")
    assert r.status_code == 200
    assert r.json()["bin_id"] == "BIN-0001"


def test_get_bin_fill_pct_in_response():
    r = client.get("/bins/BIN-0001")
    assert "current_fill_pct" in r.json()


def test_get_bin_invalid_id_returns_404():
    r = client.get("/bins/BIN-9999")
    assert r.status_code == 404


# ── POST /bins/{bin_id}/collect ───────────────────────────────────────────────

def test_collect_marks_bin_for_collection(engine):
    r = client.post("/bins/BIN-0001/collect")
    assert r.status_code == 200
    assert engine.bins["BIN-0001"].marked_for_collection


def test_collect_invalid_id_returns_404():
    r = client.post("/bins/BIN-9999/collect")
    assert r.status_code == 404


# ── GET /stats ────────────────────────────────────────────────────────────────

def test_stats_returns_required_fields():
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    assert {"total_bins", "avg_fill_pct", "bins_over_80", "faulted_count"}.issubset(data)


def test_stats_total_bins_is_200():
    r = client.get("/stats")
    assert r.json()["total_bins"] == 200


def test_stats_bins_over_80_correct():
    r = client.get("/stats")
    # Fleet has 10 bins at 90%, rest at 50%
    assert r.json()["bins_over_80"] == 10


def test_stats_faulted_count_correct():
    r = client.get("/stats")
    assert r.json()["faulted_count"] == 5


# ── POST /sim/speed ───────────────────────────────────────────────────────────

def test_sim_speed_updates_tick_interval(engine):
    r = client.post("/sim/speed", json={"ticks_per_second": 5.0})
    assert r.status_code == 200
    assert abs(engine.tick_interval - 0.2) < 0.001


def test_sim_speed_low_value_does_not_crash():
    r = client.post("/sim/speed", json={"ticks_per_second": 0.1})
    assert r.status_code == 200


# ── invalid bin_id on all endpoints ──────────────────────────────────────────

def test_any_endpoint_invalid_bin_id_returns_404():
    assert client.get("/bins/INVALID").status_code == 404
    assert client.post("/bins/INVALID/collect").status_code == 404
