"""Tests for routing/solver_greedy.py."""
from __future__ import annotations

import pytest

from routing.schemas import VRPInput
from routing.solver_greedy import solve_greedy
from tests.test_phase6.conftest import (
    make_bin, make_depot, make_dump_yard, make_truck, make_vrp,
)


def test_greedy_always_returns_valid_solution():
    for n in [0, 1, 3, 10, 25]:
        vrp = make_vrp(n_bins=n)
        sol = solve_greedy(vrp)
        assert sol.solver == "greedy_fallback"
        assert sol.status in ("feasible", "infeasible")


def test_greedy_never_exceeds_truck_capacity():
    vrp = make_vrp(n_bins=10, capacity_liters=400)
    sol = solve_greedy(vrp)
    for route in sol.routes:
        truck = next(t for t in vrp.trucks if t.truck_id == route.truck_id)
        for stop in route.stops:
            assert stop.cumulative_load_liters <= truck.capacity_liters


def test_greedy_inserts_dump_yard_when_load_exceeds_trigger():
    """Set capacity so 3 bins fill 90%+, expecting a dump yard visit."""
    # 3 bins × 100L = 300L; trigger = 85% of 340 = 289L
    # After 2 bins: 200L < 289, after 3 bins: 300L > 289 — but trigger fires BEFORE 3rd
    # Need: after 2 bins cumulative >= trigger → capacity = ceil(200 / 0.85) = 236
    # Actually: trigger = 0.85 * 236 = 200.6 — so after 2nd bin (200L) it's just below
    # Use capacity=220: trigger=187L. After 2nd bin: 200L > 187 → dump fires before 3rd
    depot = make_depot()
    bins = [
        make_bin(f"B{i}", lat=25.21 + i * 0.003, lng=55.28, fill_liters=100.0, hours_until_critical=8.0)
        for i in range(1, 4)
    ]
    dump = make_dump_yard()
    truck = make_truck(capacity_liters=220)
    vrp = VRPInput(bins=bins, trucks=[truck], depot=depot, dump_yards=[dump])

    sol = solve_greedy(vrp)
    total_dump_visits = sum(r.dump_yard_visits for r in sol.routes)
    assert total_dump_visits >= 1, "Expected at least one dump yard visit"


def test_greedy_respects_shift_end():
    """Truck with very short shift must return to depot without overrunning."""
    depot = make_depot()
    # Bin is 30km away — at 40km/h, takes ~45 min to reach + return
    far_bin = make_bin("FAR", lat=25.5, lng=55.5, fill_liters=50.0, hours_until_critical=12.0)
    # Shift = 10 minutes — cannot reach far bin and return
    truck = make_truck(capacity_liters=1000, shift_end_seconds=600)
    vrp = VRPInput(bins=[far_bin], trucks=[truck], depot=depot)
    sol = solve_greedy(vrp)
    # Far bin should be unserved
    assert "FAR" in sol.unserved_bins


def test_greedy_single_bin_returns_one_bin_stop():
    depot = make_depot()
    b = make_bin("B001", fill_liters=50.0, hours_until_critical=6.0)
    truck = make_truck(capacity_liters=500)
    vrp = VRPInput(bins=[b], trucks=[truck], depot=depot)
    sol = solve_greedy(vrp)
    assert len(sol.routes) == 1
    bin_stops = [s for s in sol.routes[0].stops if s.node_type == "bin"]
    assert len(bin_stops) == 1
    assert bin_stops[0].node_id == "B001"
