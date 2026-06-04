"""Tests for dispatch sub-router in routing/api.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import routing.api as api_module
from routing.api import app
from routing.schemas import OptimizedRoute, RouteStop, Truck, VRPSolution
from tests.test_phase6.conftest import make_vrp


def _make_solution() -> VRPSolution:
    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="greedy_fallback",
        routes=[],
        unserved_bins=[],
        total_distance_m=0.0,
        total_duration_seconds=0,
        solve_time_ms=5.0,
        status="feasible",
    )


def _stub_truck(truck_id: str = "T1") -> Truck:
    return Truck(
        truck_id=truck_id,
        capacity_liters=10_000,
        depot_lat=25.2048,
        depot_lng=55.2708,
        shift_start_seconds=0,
        shift_end_seconds=28800,
    )


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_api_state():
    api_module._active_routes.clear()
    api_module._route_by_id.clear()
    api_module._trucks.clear()
    api_module._events_log.clear()
    api_module._last_solve_time = None
    api_module._last_unserved = []
    api_module._reopt_history.clear()
    api_module._solve_stats.update({
        "count": 0, "total_ms": 0.0, "bins_collected_today": 0,
        "by_solver": {"ortools": 0, "simulated_annealing": 0, "greedy_fallback": 0},
    })
    yield


@pytest.fixture(autouse=True)
def setup_orchestrator(monkeypatch):
    mock_orch = MagicMock()
    mock_orch.solve = AsyncMock(return_value=_make_solution())
    monkeypatch.setattr(api_module, "_orchestrator", mock_orch)
    monkeypatch.setattr(api_module, "_dispatcher", None)
    monkeypatch.setattr(api_module, "_last_vrp_input", make_vrp(n_bins=3))
    monkeypatch.setattr(api_module, "_truck_manager", None)
    monkeypatch.setattr(api_module, "_feedback_handler", None)
    monkeypatch.setattr(api_module, "_dispatch_redis", None)
    return mock_orch


@pytest.fixture
def mock_tm(monkeypatch):
    truck = _stub_truck("T1")
    tm = MagicMock()
    tm.get_truck = AsyncMock(side_effect=lambda tid: truck if tid == "T1" else None)
    tm.get_all_trucks = AsyncMock(return_value=[truck])
    tm.get_current_load = AsyncMock(return_value=250.0)
    tm.get_status = AsyncMock(return_value="active")
    tm.get_position = AsyncMock(return_value={"lat": 25.2, "lng": 55.2, "updated_at": "now"})
    tm.update_position = AsyncMock()
    tm.update_load = AsyncMock()
    tm.update_status = AsyncMock()
    tm.record_collection = AsyncMock()
    tm.record_dump = AsyncMock()
    tm.get_collections_today = AsyncMock(return_value=[])
    monkeypatch.setattr(api_module, "_truck_manager", tm)
    return tm


@pytest.fixture
def mock_fh(monkeypatch):
    fh = MagicMock()
    fh.on_bin_emptied = AsyncMock()
    fh.on_dump_completed = AsyncMock()
    monkeypatch.setattr(api_module, "_feedback_handler", fh)
    return fh


# ---------------------------------------------------------------------------
# GET /routing/dispatch/status
# ---------------------------------------------------------------------------

def test_dispatch_status_returns_200(mock_tm):
    r = client.get("/routing/dispatch/status")
    assert r.status_code == 200
    data = r.json()
    assert "active_trucks" in data
    assert isinstance(data["active_trucks"], list)


def test_dispatch_status_contains_registered_trucks(mock_tm):
    r = client.get("/routing/dispatch/status")
    assert r.status_code == 200
    ids = [t["truck_id"] for t in r.json()["active_trucks"]]
    assert "T1" in ids


def test_dispatch_status_without_truck_manager_returns_empty():
    r = client.get("/routing/dispatch/status")
    assert r.status_code == 200
    assert r.json()["active_trucks"] == []


# ---------------------------------------------------------------------------
# PATCH /routing/dispatch/trucks/{id}/position
# ---------------------------------------------------------------------------

def test_update_position_ok(mock_tm):
    r = client.patch("/routing/dispatch/trucks/T1/position", json={"lat": 25.30, "lng": 55.40})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["lat"] == pytest.approx(25.30)
    assert data["lng"] == pytest.approx(55.40)
    mock_tm.update_position.assert_called_once_with("T1", 25.30, 55.40)


def test_update_position_404_unknown_truck(mock_tm):
    r = client.patch("/routing/dispatch/trucks/UNKNOWN/position", json={"lat": 1.0, "lng": 2.0})
    assert r.status_code == 404


def test_update_position_503_without_truck_manager():
    r = client.patch("/routing/dispatch/trucks/T1/position", json={"lat": 1.0, "lng": 2.0})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# PATCH /routing/dispatch/trucks/{id}/load
# ---------------------------------------------------------------------------

def test_update_load_ok(mock_tm):
    r = client.patch("/routing/dispatch/trucks/T1/load", json={"load_liters": 400.0})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["load_liters"] == pytest.approx(400.0)
    mock_tm.update_load.assert_called_once_with("T1", 400.0)


def test_update_load_404_unknown_truck(mock_tm):
    r = client.patch("/routing/dispatch/trucks/UNKNOWN/load", json={"load_liters": 100.0})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /routing/dispatch/trucks/{id}/collect/{bin_id}
# ---------------------------------------------------------------------------

def test_collect_bin_ok(mock_tm, mock_fh):
    r = client.post(
        "/routing/dispatch/trucks/T1/collect/B001",
        json={"actual_liters": 75.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["truck_id"] == "T1"
    assert data["bin_id"] == "B001"
    mock_fh.on_bin_emptied.assert_called_once_with("T1", "B001", 75.0)


def test_collect_bin_404_unknown_truck(mock_tm, mock_fh):
    r = client.post("/routing/dispatch/trucks/UNKNOWN/collect/B001", json={"actual_liters": 0.0})
    assert r.status_code == 404


def test_collect_bin_503_without_feedback_handler(mock_tm):
    r = client.post("/routing/dispatch/trucks/T1/collect/B001", json={"actual_liters": 0.0})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /routing/dispatch/trucks/{id}/dump/{yard_id}
# ---------------------------------------------------------------------------

def test_dump_at_yard_ok(mock_tm, mock_fh):
    r = client.post("/routing/dispatch/trucks/T1/dump/YARD1")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["yard_id"] == "YARD1"
    mock_fh.on_dump_completed.assert_called_once_with("T1", "YARD1")


def test_dump_at_yard_404_unknown_truck(mock_tm, mock_fh):
    r = client.post("/routing/dispatch/trucks/UNKNOWN/dump/YARD1")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /routing/dispatch/reopt/trigger
# ---------------------------------------------------------------------------

def test_reopt_trigger_returns_202():
    r = client.post("/routing/dispatch/reopt/trigger", json={"scope": "full_fleet"})
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "accepted"
    assert data["scope"] == "full_fleet"


def test_reopt_trigger_503_without_vrp_input(monkeypatch):
    monkeypatch.setattr(api_module, "_last_vrp_input", None)
    r = client.post("/routing/dispatch/reopt/trigger", json={"scope": "full_fleet"})
    assert r.status_code == 503


def test_reopt_trigger_records_history():
    api_module._reopt_history.clear()
    client.post("/routing/dispatch/reopt/trigger", json={"scope": "single_truck", "reason": "test"})
    assert len(api_module._reopt_history) == 1
    entry = api_module._reopt_history[0]
    assert entry["scope"] == "single_truck"


# ---------------------------------------------------------------------------
# GET /routing/dispatch/feedback/queue
# ---------------------------------------------------------------------------

def test_feedback_queue_length_returns_0_without_redis():
    r = client.get("/routing/dispatch/feedback/queue")
    assert r.status_code == 200
    assert r.json()["queue_length"] == 0


def test_feedback_queue_length_with_redis(monkeypatch):
    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(api_module, "_dispatch_redis", redis)
    # Synchronously push items using fakeredis event loop trick via asyncio
    import asyncio
    asyncio.get_event_loop().run_until_complete(redis.lpush("ml:feedback:queue", b"a", b"b"))
    r = client.get("/routing/dispatch/feedback/queue")
    assert r.status_code == 200
    assert r.json()["queue_length"] == 2


# ---------------------------------------------------------------------------
# GET /routing/dispatch/collections/today
# ---------------------------------------------------------------------------

def test_collections_today_without_truck_manager():
    r = client.get("/routing/dispatch/collections/today")
    assert r.status_code == 200
    assert r.json() == []


def test_collections_today_with_truck_manager(mock_tm):
    r = client.get("/routing/dispatch/collections/today")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    mock_tm.get_collections_today.assert_called_once()
