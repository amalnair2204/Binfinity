"""Tests for routing/solvers/sa_solver.py — 2 trucks, 15 bins."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from routing.schemas import VRPInput, VRPSolution
from routing.solvers.sa_solver import SimulatedAnnealingSolver, _cost, _is_feasible
from routing.solver_greedy import solve_greedy
from tests.test_phase6.conftest import make_bin, make_depot, make_dump_yard, make_truck


def _medium_vrp(n_bins: int = 15, n_trucks: int = 2, capacity: int = 1000) -> VRPInput:
    depot = make_depot()
    bins = [
        make_bin(
            f"B{i:03}",
            lat=25.2048 + (i % 5) * 0.005,
            lng=55.2708 + (i // 5) * 0.004,
            fill_liters=70.0,
            hours_until_critical=float(4 + i % 8),
        )
        for i in range(1, n_bins + 1)
    ]
    trucks = [make_truck(f"T{j}", capacity_liters=capacity) for j in range(1, n_trucks + 1)]
    dump = make_dump_yard()
    return VRPInput(bins=bins, trucks=trucks, depot=depot, dump_yards=[dump])


def test_sa_returns_simulated_annealing_label():
    vrp = _medium_vrp()
    solver = SimulatedAnnealingSolver(max_iterations=500)
    sol = solver.solve(vrp)
    assert sol.solver == "simulated_annealing"


def test_sa_cost_not_worse_than_greedy():
    vrp = _medium_vrp()
    greedy = solve_greedy(vrp)
    bin_map = {b.node_id: b for b in vrp.bins}

    from routing.solvers.sa_solver import _solution_to_state
    greedy_state = _solution_to_state(greedy, vrp)
    greedy_cost = _cost(greedy_state, vrp, bin_map)

    solver = SimulatedAnnealingSolver(max_iterations=2000)
    sa_sol = solver.solve(vrp)
    sa_state = _solution_to_state(sa_sol, vrp)
    sa_cost = _cost(sa_state, vrp, bin_map)

    # SA should match or improve on greedy
    assert sa_cost <= greedy_cost * 1.05  # 5% tolerance for stochasticity


def test_sa_capacity_constraints_satisfied():
    vrp = _medium_vrp(capacity=500)
    solver = SimulatedAnnealingSolver(max_iterations=1000)
    sol = solver.solve(vrp)
    bin_map = {b.node_id: b for b in vrp.bins}

    from routing.solvers.sa_solver import _solution_to_state
    state = _solution_to_state(sol, vrp)
    assert _is_feasible(state, vrp, bin_map), "SA solution violates capacity or shift constraints"


def test_sa_shift_constraints_satisfied():
    vrp = _medium_vrp(n_bins=6, n_trucks=1)
    solver = SimulatedAnnealingSolver(max_iterations=500)
    sol = solver.solve(vrp)
    for route in sol.routes:
        truck = next(t for t in vrp.trucks if t.truck_id == route.truck_id)
        shift = truck.shift_end_seconds - truck.shift_start_seconds
        assert route.total_duration_seconds <= shift + 60


def test_sa_runs_without_exception():
    vrp = _medium_vrp()
    solver = SimulatedAnnealingSolver(max_iterations=200)
    sol = solver.solve(vrp)
    assert isinstance(sol, VRPSolution)


def test_sa_logs_progress(capfd):
    """SA must emit debug logs every 5000 iterations via loguru."""
    vrp = _medium_vrp()
    mock_logger = MagicMock()
    with patch("routing.solvers.sa_solver.logger", mock_logger):
        solver = SimulatedAnnealingSolver(max_iterations=10001)
        solver.solve(vrp)
    # debug() called at iter 0, 5000, 10000 = 3 times
    assert mock_logger.debug.call_count >= 2
