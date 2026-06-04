"""Tests that RouteDispatcher calls push_overflow_alert on overflow events."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routing.dispatcher import DispatchEvent, RouteDispatcher


@pytest.fixture
def fake_redis():
    import fakeredis.aioredis
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def mock_db_pool():
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool, conn


@pytest.fixture
def mock_orchestrator():
    from routing.schemas import VRPSolution
    sol = VRPSolution(
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
    orch.solve = AsyncMock(return_value=sol)
    return orch


@pytest.fixture
def dispatcher(fake_redis, mock_db_pool, mock_orchestrator):
    pool, _ = mock_db_pool
    return RouteDispatcher(mock_orchestrator, fake_redis, pool)


def _overflow_event(truck_id="T1", bin_id="B001"):
    return DispatchEvent(
        event_id="e1",
        event_type="overflow_alert",
        triggered_at=datetime.now(tz=timezone.utc),
        affected_bin_id=bin_id,
        affected_truck_id=truck_id,
        priority=3,
    )


@pytest.mark.asyncio
async def test_overflow_event_calls_push_overflow_alert(dispatcher):
    event = _overflow_event()
    with patch("routing.dispatcher.push_overflow_alert", new_callable=AsyncMock) as mock_push:
        await dispatcher.on_event(event)
    mock_push.assert_called_once_with("T1", "B001", "Bin near overflow — route being updated")


@pytest.mark.asyncio
async def test_non_overflow_event_does_not_call_push(dispatcher):
    event = DispatchEvent(
        event_id="e2",
        event_type="new_bins_flagged",
        triggered_at=datetime.now(tz=timezone.utc),
        priority=1,
    )
    with patch("routing.dispatcher.push_overflow_alert", new_callable=AsyncMock) as mock_push:
        await dispatcher.on_event(event)
    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_overflow_without_truck_id_does_not_call_push(dispatcher):
    event = DispatchEvent(
        event_id="e3",
        event_type="overflow_alert",
        triggered_at=datetime.now(tz=timezone.utc),
        affected_bin_id="B001",
        affected_truck_id=None,  # no truck yet assigned
        priority=2,
    )
    with patch("routing.dispatcher.push_overflow_alert", new_callable=AsyncMock) as mock_push:
        await dispatcher.on_event(event)
    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_ws_push_failure_does_not_block_dispatch(dispatcher):
    """Push failure must not prevent re-optimization from running."""
    event = _overflow_event()
    with patch("routing.dispatcher.push_overflow_alert", side_effect=RuntimeError("ws down")):
        # Should complete without raising
        await dispatcher.on_event(event)
