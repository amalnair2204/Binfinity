"""Shared fixtures for Phase 7 tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from routing.schemas import Truck

# Re-export Phase 6 helpers so Phase 7 tests can import from one place
from tests.test_phase6.conftest import (  # noqa: F401
    make_bin, make_depot, make_dump_yard, make_truck, make_vrp,
)


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def mock_db_pool():
    """Returns (pool, conn) where conn's execute/fetch are AsyncMocks."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.on_event = AsyncMock()
    d.mark_stop_complete = AsyncMock()
    d.get_active_routes = AsyncMock(return_value=[])
    d.get_route_for_truck = AsyncMock(return_value=None)
    d.apply_solution = AsyncMock()
    d.replace_route = AsyncMock()
    d._get_last_reopt_time = AsyncMock(return_value=None)
    d._push_route_to_redis = AsyncMock()
    d._active_routes = {}
    return d


@pytest.fixture
def mock_orchestrator():
    from datetime import datetime, timezone
    from routing.schemas import VRPSolution

    def _make_solution(vrp_input=None):
        trucks = vrp_input.trucks if vrp_input else []
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

    orch = MagicMock()
    orch.solve = AsyncMock(side_effect=_make_solution)
    return orch


@pytest.fixture
def mock_truck_manager():
    tm = MagicMock()
    tm.get_truck = AsyncMock(return_value=None)
    tm.get_all_trucks = AsyncMock(return_value=[])
    tm.get_active_trucks = AsyncMock(return_value=[])
    tm.get_current_load = AsyncMock(return_value=0.0)
    tm.get_status = AsyncMock(return_value="active")
    tm.get_position = AsyncMock(return_value=None)
    tm.update_position = AsyncMock()
    tm.update_load = AsyncMock()
    tm.update_status = AsyncMock()
    tm.record_collection = AsyncMock()
    tm.record_dump = AsyncMock()
    tm.check_shift_status = AsyncMock(return_value=[])
    tm.get_collections_today = AsyncMock(return_value=[])
    return tm
