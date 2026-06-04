"""Tests for routing/schemas.py."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from routing.schemas import (
    OptimizedRoute,
    RouteNode,
    RouteStop,
    Truck,
    VRPInput,
    VRPSolution,
)
from routing.dispatcher import DispatchEvent
from datetime import datetime, timezone


def _make_stop(seq: int, node_type: str = "bin", node_id: str | None = None) -> RouteStop:
    return RouteStop(
        node_id=node_id or f"N{seq}",
        node_type=node_type,
        arrival_time_seconds=seq * 300,
        departure_time_seconds=seq * 300 + 300,
        sequence=seq,
    )


# ---------------------------------------------------------------------------
# RouteNode
# ---------------------------------------------------------------------------

def test_route_node_bin_validates():
    n = RouteNode(node_id="B001", lat=25.2, lng=55.3, node_type="bin")
    assert n.node_type == "bin"
    assert n.service_time_seconds == 300


def test_route_node_depot_has_zero_service_time():
    n = RouteNode(node_id="depot", lat=25.2, lng=55.3, node_type="depot")
    assert n.service_time_seconds == 0


def test_route_node_dump_yard_has_zero_service_time():
    n = RouteNode(node_id="yard1", lat=25.2, lng=55.3, node_type="dump_yard")
    assert n.service_time_seconds == 0


def test_route_node_road_access_default():
    n = RouteNode(node_id="B001", lat=25.2, lng=55.3, node_type="bin")
    assert n.road_access == "standard"


def test_route_node_narrow_alley():
    n = RouteNode(
        node_id="B001", lat=25.2, lng=55.3, node_type="bin", road_access="narrow_alley"
    )
    assert n.road_access == "narrow_alley"


# ---------------------------------------------------------------------------
# Truck
# ---------------------------------------------------------------------------

def test_truck_validates_normally():
    t = Truck(truck_id="T1", capacity_liters=500, depot_lat=25.2, depot_lng=55.3)
    assert t.shift_end_seconds > t.shift_start_seconds


def test_truck_invalid_shift_raises():
    with pytest.raises(ValidationError):
        Truck(
            truck_id="T1",
            capacity_liters=500,
            depot_lat=25.2,
            depot_lng=55.3,
            shift_start_seconds=5000,
            shift_end_seconds=1000,
        )


def test_truck_can_access_narrow_default():
    t = Truck(truck_id="T1", capacity_liters=500, depot_lat=25.2, depot_lng=55.3)
    assert t.can_access_narrow is True


# ---------------------------------------------------------------------------
# RouteStop — sequence ordering
# ---------------------------------------------------------------------------

def test_route_stop_sequence_preserved():
    stops = [_make_stop(i) for i in range(4)]
    route = OptimizedRoute(
        truck_id="T1",
        stops=stops,
        total_distance_m=1000.0,
        total_duration_seconds=3600,
        total_load_liters=200.0,
    )
    for i, stop in enumerate(route.stops):
        assert stop.sequence == i


def test_route_has_auto_route_id():
    stops = [_make_stop(0, node_type="depot")]
    route = OptimizedRoute(
        truck_id="T1",
        stops=stops,
        total_distance_m=0.0,
        total_duration_seconds=0,
        total_load_liters=0.0,
    )
    assert isinstance(route.route_id, str)
    assert len(route.route_id) == 36  # UUID format


# ---------------------------------------------------------------------------
# VRPSolution
# ---------------------------------------------------------------------------

def test_vrpsolution_empty_routes_valid():
    sol = VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="greedy_fallback",
        routes=[],
        unserved_bins=["B001", "B002"],
        total_distance_m=0.0,
        total_duration_seconds=0,
        solve_time_ms=5.0,
        status="infeasible",
    )
    assert sol.unserved_bins == ["B001", "B002"]
    assert sol.routes == []


# ---------------------------------------------------------------------------
# DispatchEvent
# ---------------------------------------------------------------------------

def test_dispatch_event_valid():
    e = DispatchEvent(
        event_id="evt-1",
        event_type="overflow_alert",
        triggered_at=datetime.now(tz=timezone.utc),
        priority=2,
    )
    assert e.event_type == "overflow_alert"


def test_dispatch_event_invalid_type_raises():
    with pytest.raises(ValidationError):
        DispatchEvent(
            event_id="evt-1",
            event_type="invalid_event_type",
            triggered_at=datetime.now(tz=timezone.utc),
            priority=1,
        )
