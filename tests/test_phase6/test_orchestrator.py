"""Tests for routing/solver_orchestrator.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

from routing.schemas import VRPInput, VRPSolution
from routing.solver_orchestrator import SolverOrchestrator
from tests.test_phase6.conftest import make_vrp


def _greedy_solution(n_bins: int = 0) -> VRPSolution:
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


def _ortools_solution(status: str = "optimal") -> VRPSolution:
    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="ortools",
        routes=[],
        unserved_bins=[],
        total_distance_m=0.0,
        total_duration_seconds=0,
        solve_time_ms=100.0,
        status=status,
    )


@pytest.mark.asyncio
async def test_small_input_tries_ortools():
    vrp = make_vrp(n_bins=5)
    orch = SolverOrchestrator(ortools_time_limit=5)
    with patch("routing.solver_ortools.solve_ortools", return_value=_ortools_solution()) as mock_ot:
        sol = await orch.solve(vrp)
    mock_ot.assert_called_once()
    assert sol.solver == "ortools"


@pytest.mark.asyncio
async def test_small_input_falls_back_to_sa_when_ortools_fails():
    vrp = make_vrp(n_bins=5)
    orch = SolverOrchestrator(ortools_time_limit=5)
    # OR-Tools returns a greedy_fallback (i.e. it internally fell back)
    with patch("routing.solver_ortools.solve_ortools", return_value=_greedy_solution()):
        with patch.object(orch, "_sa") as mock_sa:
            mock_sa.return_value = _greedy_solution()
            await orch.solve(vrp)
    mock_sa.assert_called_once()


@pytest.mark.asyncio
async def test_large_input_skips_ortools():
    vrp = make_vrp(n_bins=201, capacity_liters=100_000)
    orch = SolverOrchestrator()
    with patch("routing.solver_ortools.solve_ortools") as mock_ot:
        with patch.object(orch, "_sa", return_value=_greedy_solution()):
            await orch.solve(vrp)
    mock_ot.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_always_returns_valid_solution():
    for n in [1, 5, 10]:
        vrp = make_vrp(n_bins=n)
        orch = SolverOrchestrator(ortools_time_limit=3)
        sol = await orch.solve(vrp)
        assert isinstance(sol, VRPSolution)
        assert sol.solver in ("ortools", "simulated_annealing", "greedy_fallback")


@pytest.mark.asyncio
async def test_orchestrator_returns_greedy_when_all_fail():
    vrp = make_vrp(n_bins=5)
    orch = SolverOrchestrator()
    with patch("routing.solver_ortools.solve_ortools", side_effect=RuntimeError("ot fail")):
        with patch.object(orch, "_sa", side_effect=RuntimeError("sa fail")):
            # Falls through to _greedy
            sol = await orch.solve(vrp)
    assert sol.solver == "greedy_fallback"
