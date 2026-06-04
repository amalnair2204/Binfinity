"""FastAPI endpoint tests for routing/api.py."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import routing.api as api_module
from routing.api import app, receive_solution
from routing.dispatcher import DispatchEvent
from routing.schemas import OptimizedRoute, RouteStop, Truck, VRPInput, VRPSolution
from tests.test_phase6.conftest import make_depot, make_truck, make_vrp


def _make_route(truck_id: str = "T1", n_bins: int = 2) -> OptimizedRoute:
    stops = [
        RouteStop(node_id="depot", node_type="depot",
                  arrival_time_seconds=0, departure_time_seconds=0),
    ]
    for i in range(n_bins):
        stops.append(RouteStop(
            node_id=f"B{i:03}",
            node_type="bin",
            arrival_time_seconds=600 + i * 400,
            departure_time_seconds=900 + i * 400,
            fill_collected_liters=80.0,
            cumulative_load_liters=80.0 * (i + 1),
            sequence=i + 1,
        ))
    stops.append(RouteStop(node_id="depot", node_type="depot",
                           arrival_time_seconds=4000, departure_time_seconds=4000))
    return OptimizedRoute(
        truck_id=truck_id,
        stops=stops,
        total_distance_m=5000.0,
        total_duration_seconds=3600,
        total_load_liters=80.0 * n_bins,
    )


def _make_solution(truck_id: str = "T1") -> VRPSolution:
    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="ortools",
        routes=[_make_route(truck_id)],
        unserved_bins=["B099"],
        total_distance_m=5000.0,
        total_duration_seconds=3600,
        solve_time_ms=120.0,
        status="feasible",
    )


@pytest.fixture(autouse=True)
def reset_api_state():
    """Clear all module-level state before each test."""
    api_module._active_routes.clear()
    api_module._route_by_id.clear()
    api_module._trucks.clear()
    api_module._events_log.clear()
    api_module._last_solve_time = None
    api_module._last_unserved = []
    api_module._solve_stats.update({
        "count": 0, "total_ms": 0.0, "bins_collected_today": 0,
        "by_solver": {"ortools": 0, "simulated_annealing": 0, "greedy_fallback": 0},
    })
    yield


@pytest.fixture(autouse=True)
def mock_orchestrator(monkeypatch):
    mock = MagicMock()
    mock.solve = AsyncMock(return_value=_make_solution())
    monkeypatch.setattr(api_module, "_orchestrator", mock)
    monkeypatch.setattr(api_module, "_dispatcher", None)
    monkeypatch.setattr(api_module, "_last_vrp_input", make_vrp(n_bins=3))
    yield mock


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok():
    r = client.get("/routing/health")
    assert r.status_code == 200
    data = r.json()
    assert data["orchestrator_ready"] is True


def test_health_degraded_when_no_orchestrator(monkeypatch):
    monkeypatch.setattr(api_module, "_orchestrator", None)
    r = client.get("/routing/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /routes
# ---------------------------------------------------------------------------

def test_list_routes_empty():
    r = client.get("/routing/routes")
    assert r.status_code == 200
    assert r.json() == []


def test_list_routes_returns_active():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/routes")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# GET /routes/truck/{truck_id}
# ---------------------------------------------------------------------------

def test_get_route_for_truck_not_found():
    r = client.get("/routing/routes/truck/T99")
    assert r.status_code == 404


def test_get_route_for_truck_found():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/routes/truck/T1")
    assert r.status_code == 200
    assert r.json()["truck_id"] == "T1"


# ---------------------------------------------------------------------------
# GET /routes/truck/{truck_id}/next-stop
# ---------------------------------------------------------------------------

def test_next_stop_returns_first_bin():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/routes/truck/T1/next-stop")
    assert r.status_code == 200
    data = r.json()
    assert data["node_type"] == "bin"


def test_next_stop_404_when_no_route():
    r = client.get("/routing/routes/truck/T99/next-stop")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /routes/{route_id}
# ---------------------------------------------------------------------------

def test_get_route_by_id():
    receive_solution(_make_solution("T1"))
    route = api_module._active_routes["T1"]
    r = client.get(f"/routing/routes/{route.route_id}")
    assert r.status_code == 200
    assert r.json()["truck_id"] == "T1"


def test_get_route_by_id_not_found():
    r = client.get("/routing/routes/nonexistent-uuid")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /routes/generate
# ---------------------------------------------------------------------------

def test_generate_routes_ok():
    r = client.post("/routing/routes/generate", json={"window_hours": 6.0, "threshold": 70.0})
    assert r.status_code == 200
    data = r.json()
    assert "solver" in data
    assert "routes" in data


def test_generate_routes_503_when_no_vrp_input(monkeypatch):
    monkeypatch.setattr(api_module, "_last_vrp_input", None)
    r = client.post("/routing/routes/generate", json={})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# POST /routes/truck/{truck_id}/stop/{bin_id}/complete
# ---------------------------------------------------------------------------

def test_complete_stop_ok():
    receive_solution(_make_solution("T1"))
    r = client.post("/routing/routes/truck/T1/stop/B000/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # Verify stop removed
    route = api_module._active_routes["T1"]
    assert all(s.node_id != "B000" for s in route.stops)


def test_complete_stop_404_on_unknown_bin():
    receive_solution(_make_solution("T1"))
    r = client.post("/routing/routes/truck/T1/stop/UNKNOWN/complete")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_post_event_and_get_events():
    event_data = {
        "event_id": "evt-test-1",
        "event_type": "overflow_alert",
        "triggered_at": datetime.now(tz=timezone.utc).isoformat(),
        "priority": 2,
    }
    r = client.post("/routing/events", json=event_data)
    assert r.status_code == 200

    r2 = client.get("/routing/events")
    assert r2.status_code == 200
    events = r2.json()
    assert len(events) >= 1
    assert events[0]["event_id"] == "evt-test-1"


# ---------------------------------------------------------------------------
# GET /trucks
# ---------------------------------------------------------------------------

def test_list_trucks_empty():
    r = client.get("/routing/trucks")
    assert r.status_code == 200
    assert r.json() == []


def test_list_trucks_with_active_route():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/trucks")
    assert r.status_code == 200
    trucks = r.json()
    assert len(trucks) == 1
    assert trucks[0]["truck_id"] == "T1"
    assert trucks[0]["is_active"] is True


# ---------------------------------------------------------------------------
# PATCH /trucks/{truck_id}
# ---------------------------------------------------------------------------

def test_patch_truck_ok():
    t = make_truck("T1")
    api_module._trucks["T1"] = t
    r = client.patch("/routing/trucks/T1", json={"capacity_liters": 999})
    assert r.status_code == 200
    assert r.json()["capacity_liters"] == 999


def test_patch_truck_not_found():
    r = client.patch("/routing/trucks/NOEXIST", json={"capacity_liters": 999})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

def test_get_stats_ok():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total_routes_generated" in data
    assert "solver_usage" in data
    assert data["total_routes_generated"] >= 1


# ---------------------------------------------------------------------------
# GET /unassigned
# ---------------------------------------------------------------------------

def test_get_unassigned():
    receive_solution(_make_solution("T1"))
    r = client.get("/routing/unassigned")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert "B099" in data


# ---------------------------------------------------------------------------
# 503 when orchestrator None
# ---------------------------------------------------------------------------

def test_routes_503_when_not_ready(monkeypatch):
    monkeypatch.setattr(api_module, "_orchestrator", None)
    for path in ["/routing/routes", "/routing/trucks", "/routing/stats", "/routing/unassigned"]:
        r = client.get(path)
        assert r.status_code == 503, f"{path} should be 503"
