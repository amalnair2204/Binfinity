"""Tests that Reoptimizer calls push_reroute for each route after re-optimization."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routing.dispatcher import DispatchEvent
from routing.reoptimizer import Reoptimizer
from routing.schemas import OptimizedRoute, VRPSolution

from tests.test_phase6.conftest import make_bin, make_depot, make_dump_yard, make_truck
from routing.schemas import VRPInput


def _make_vrp(truck_id: str = "T1", bin_id: str = "B001") -> VRPInput:
    return VRPInput(
        bins=[make_bin(bin_id)],
        trucks=[make_truck(truck_id)],
        depot=make_depot(),
        dump_yards=[make_dump_yard()],
    )


def _make_solution(truck_id: str) -> VRPSolution:
    route = OptimizedRoute(
        route_id="r1",
        truck_id=truck_id,
        stops=[],
        total_distance_m=0.0,
        total_duration_seconds=0,
        total_load_liters=0.0,
        dump_yard_visits=0,
        objective_value=0.0,
        solver="greedy_fallback",
        solved_at=datetime.now(tz=timezone.utc),
    )
    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="greedy_fallback",
        routes=[route],
        unserved_bins=[],
        total_distance_m=0.0,
        total_duration_seconds=0,
        solve_time_ms=5.0,
        status="feasible",
    )


@pytest.fixture
def reopt(mock_dispatcher, mock_truck_manager, fake_redis, mock_orchestrator):
    """Reoptimizer wired to fresh mocks; uses test_phase7 conftest fixtures."""
    orch = mock_orchestrator
    orch.solve = AsyncMock(return_value=_make_solution("T1"))
    mock_dispatcher.get_active_routes = AsyncMock(return_value=[])
    mock_dispatcher.get_route_for_truck = AsyncMock(return_value=None)
    return Reoptimizer(orch, mock_dispatcher, mock_truck_manager, fake_redis)


@pytest.fixture
def fake_redis():
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.on_event = AsyncMock()
    d.mark_stop_complete = AsyncMock()
    d.get_active_routes = AsyncMock(return_value=[])
    d.get_route_for_truck = AsyncMock(return_value=None)
    d.apply_solution = AsyncMock()
    d.replace_route = AsyncMock()
    d._push_route_to_redis = AsyncMock()
    d._active_routes = {}
    return d


@pytest.fixture
def mock_truck_manager():
    tm = MagicMock()
    tm.get_position = AsyncMock(return_value=None)
    return tm


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.solve = AsyncMock(return_value=_make_solution("T1"))
    return orch


@pytest.fixture
def overflow_event():
    return DispatchEvent(
        event_id="e1",
        event_type="overflow_alert",
        triggered_at=datetime.now(tz=timezone.utc),
        affected_bin_id="B001",
        affected_truck_id="T1",
        priority=3,
    )


@pytest.fixture
def manual_event():
    return DispatchEvent(
        event_id="e2",
        event_type="manual_override",
        triggered_at=datetime.now(tz=timezone.utc),
        priority=3,
    )


@pytest.mark.asyncio
async def test_push_reroute_called_after_single_truck_solve(reopt, fake_redis, overflow_event):
    vrp = _make_vrp("T1", "B001")
    # Seed Redis so _sync_bins doesn't remove the bin
    await fake_redis.sadd("bins:flagged", "B001")
    with patch("routing.reoptimizer.push_reroute", new_callable=AsyncMock) as mock_push:
        await reopt.handle_event(overflow_event, vrp)
    mock_push.assert_called_once()
    call_kwargs = mock_push.call_args
    assert call_kwargs[0][0] == "T1"
    assert call_kwargs[0][2] == "overflow_alert"


@pytest.mark.asyncio
async def test_push_reroute_called_after_manual_override(reopt, manual_event):
    vrp = _make_vrp("T1", "B001")
    with patch("routing.reoptimizer.push_reroute", new_callable=AsyncMock) as mock_push:
        await reopt.handle_event(manual_event, vrp)
    mock_push.assert_called_once()


@pytest.mark.asyncio
async def test_push_reroute_skipped_when_solution_is_none(reopt):
    """truck_capacity_hit returns None solution — no WS push should happen."""
    event = DispatchEvent(
        event_id="e3",
        event_type="truck_capacity_hit",
        triggered_at=datetime.now(tz=timezone.utc),
        affected_truck_id="T1",
        priority=3,
    )
    vrp = _make_vrp("T1", "B001")
    with patch("routing.reoptimizer.push_reroute", new_callable=AsyncMock) as mock_push:
        await reopt.handle_event(event, vrp)
    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_ws_push_failure_does_not_crash_reoptimizer(reopt, overflow_event):
    """If WS push fails, the ReOptResult is still returned."""
    vrp = _make_vrp("T1", "B001")
    with patch("routing.reoptimizer.push_reroute", side_effect=RuntimeError("WS down")):
        result = await reopt.handle_event(overflow_event, vrp)
    assert result is not None
    assert result.event_type == "overflow_alert"
