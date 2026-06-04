"""Tests for routing/solver_ortools.py — 1 truck, 5 bins, 1 dump yard."""
from __future__ import annotations

import pytest

from routing.schemas import RouteStop, VRPInput, VRPSolution
from routing.solver_ortools import solve_ortools
from tests.test_phase6.conftest import make_bin, make_depot, make_dump_yard, make_truck


def _small_vrp(n_bins: int = 5, capacity: int = 1000, narrow_bin: bool = False) -> VRPInput:
    depot = make_depot()
    bins = [
        make_bin(f"B{i:03}", lat=25.2048 + i * 0.005, lng=55.2708 + i * 0.003,
                 fill_liters=80.0, hours_until_critical=8.0)
        for i in range(1, n_bins + 1)
    ]
    if narrow_bin:
        bins.append(
            make_bin("NARROW", lat=25.23, lng=55.28, fill_liters=60.0, road_access="narrow_alley")
        )
    dump = make_dump_yard()
    truck = make_truck("T1", capacity_liters=capacity)
    return VRPInput(bins=bins, trucks=[truck], depot=depot, dump_yards=[dump], max_solve_seconds=10)


def test_ortools_returns_solution():
    vrp = _small_vrp()
    sol = solve_ortools(vrp)
    assert isinstance(sol, VRPSolution)


def test_ortools_all_stops_are_valid():
    vrp = _small_vrp()
    sol = solve_ortools(vrp)
    for route in sol.routes:
        for stop in route.stops:
            assert isinstance(stop, RouteStop)
            assert stop.node_type in ("bin", "dump_yard", "depot")


def test_ortools_no_truck_exceeds_capacity():
    vrp = _small_vrp(capacity=500)
    sol = solve_ortools(vrp)
    for route in sol.routes:
        truck = next(t for t in vrp.trucks if t.truck_id == route.truck_id)
        # cumulative load at any bin stop should not exceed truck capacity
        for stop in route.stops:
            if stop.node_type == "bin":
                assert stop.cumulative_load_liters <= truck.capacity_liters + 1


def test_ortools_no_route_exceeds_shift_time():
    vrp = _small_vrp()
    sol = solve_ortools(vrp)
    for route in sol.routes:
        truck = next(t for t in vrp.trucks if t.truck_id == route.truck_id)
        duration = route.total_duration_seconds
        shift = truck.shift_end_seconds - truck.shift_start_seconds
        assert duration <= shift + 60  # 1-minute tolerance


def test_ortools_empty_input_returns_empty_solution():
    from routing.schemas import RouteNode
    depot = make_depot()
    truck = make_truck()
    vrp = VRPInput(bins=[], trucks=[truck], depot=depot, dump_yards=[], max_solve_seconds=5)
    sol = solve_ortools(vrp)
    assert sol.unserved_bins == []
    assert all(
        sum(1 for s in r.stops if s.node_type == "bin") == 0
        for r in sol.routes
    )


def test_ortools_solution_has_solver_label():
    vrp = _small_vrp()
    sol = solve_ortools(vrp)
    # OR-Tools may fall back to greedy but must always label correctly
    assert sol.solver in ("ortools", "greedy_fallback", "simulated_annealing")
