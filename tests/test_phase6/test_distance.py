"""Tests for routing/distance.py."""
from __future__ import annotations

import pytest

from routing.distance import (
    _BIG_INT,
    build_time_matrix,
    build_time_matrix_for_truck,
    get_service_times,
    haversine_m,
    travel_time_seconds,
)
from routing.schemas import RouteNode, Truck


def _node(node_id: str, lat: float, lng: float, node_type: str = "bin", road_access: str = "standard") -> RouteNode:
    return RouteNode(node_id=node_id, lat=lat, lng=lng, node_type=node_type, road_access=road_access)


def _truck(can_access_narrow: bool = True) -> Truck:
    return Truck(
        truck_id="T1",
        capacity_liters=500,
        depot_lat=25.2048,
        depot_lng=55.2708,
        can_access_narrow=can_access_narrow,
    )


# ---------------------------------------------------------------------------
# haversine_m
# ---------------------------------------------------------------------------

def test_haversine_known_distance():
    # Dubai Mall → Burj Khalifa (≈ 250m apart)
    d = haversine_m(25.1972, 55.2744, 25.1975, 55.2796)
    assert 200 < d < 700, f"Expected ~250-500m, got {d:.0f}m"


def test_haversine_zero_distance():
    assert haversine_m(25.2, 55.3, 25.2, 55.3) == pytest.approx(0.0, abs=0.1)


def test_haversine_symmetry():
    a = haversine_m(25.2048, 55.2708, 25.21, 55.28)
    b = haversine_m(25.21, 55.28, 25.2048, 55.2708)
    assert a == pytest.approx(b, rel=1e-6)


# ---------------------------------------------------------------------------
# travel_time_seconds
# ---------------------------------------------------------------------------

def test_travel_time_scales_with_distance():
    t1 = travel_time_seconds(1000.0)
    t2 = travel_time_seconds(2000.0)
    assert t2 == pytest.approx(t1 * 2, abs=2)


def test_traffic_factor_doubles_travel_time():
    t1 = travel_time_seconds(5000.0, traffic_factor=1.0)
    t2 = travel_time_seconds(5000.0, traffic_factor=2.0)
    assert t2 == pytest.approx(t1 * 2, abs=2)


# ---------------------------------------------------------------------------
# build_time_matrix_for_truck — narrow alley
# ---------------------------------------------------------------------------

def test_narrow_alley_unreachable_for_incapable_truck():
    nodes = [
        _node("depot", 25.2048, 55.2708, node_type="depot"),
        _node("B001", 25.21, 55.28),                               # standard
        _node("B002", 25.22, 55.29, road_access="narrow_alley"),   # narrow
    ]
    truck = _truck(can_access_narrow=False)
    matrix = build_time_matrix_for_truck(nodes, truck)
    # column 2 (narrow alley) should be _BIG_INT for all rows
    for i in range(len(nodes)):
        assert matrix[i][2] == _BIG_INT


def test_narrow_alley_reachable_for_capable_truck():
    nodes = [
        _node("depot", 25.2048, 55.2708, node_type="depot"),
        _node("B002", 25.22, 55.29, road_access="narrow_alley"),
    ]
    truck = _truck(can_access_narrow=True)
    matrix = build_time_matrix_for_truck(nodes, truck)
    assert matrix[0][1] < _BIG_INT


# ---------------------------------------------------------------------------
# get_service_times
# ---------------------------------------------------------------------------

def test_service_times_length_equals_nodes():
    nodes = [
        _node("depot", 25.2048, 55.2708, node_type="depot"),
        _node("B001", 25.21, 55.28),
        _node("YARD1", 25.19, 55.26, node_type="dump_yard"),
    ]
    times = get_service_times(nodes)
    assert len(times) == len(nodes)


def test_depot_and_dump_yard_have_zero_service_time():
    nodes = [
        _node("depot", 25.2048, 55.2708, node_type="depot"),
        _node("B001", 25.21, 55.28),
        _node("YARD1", 25.19, 55.26, node_type="dump_yard"),
    ]
    times = get_service_times(nodes)
    assert times[0] == 0   # depot
    assert times[1] == 300  # bin default
    assert times[2] == 0   # dump yard
