"""Tests for routing/reoptimizer.py."""
from __future__ import annotations

import json

import pytest

from routing.dispatcher import DispatchEvent
from routing.reoptimizer import ReOptResult, Reoptimizer
from routing.schemas import OptimizedRoute, RouteStop, VRPInput
from tests.test_phase7.conftest import make_bin, make_depot, make_dump_yard, make_truck


def _make_event(event_type: str, bin_id: str = None, truck_id: str = None,
                priority: int = 2) -> DispatchEvent:
    from datetime import datetime, timezone
    return DispatchEvent(
        event_id="evt-test",
        event_type=event_type,
        triggered_at=datetime.now(tz=timezone.utc),
        affected_bin_id=bin_id,
        affected_truck_id=truck_id,
        priority=priority,
    )


def _make_route(truck_id: str, bin_ids: list[str]) -> OptimizedRoute:
    stops = [RouteStop(node_id="depot", node_type="depot",
                       arrival_time_seconds=0, departure_time_seconds=0)]
    for i, bid in enumerate(bin_ids):
        stops.append(RouteStop(
            node_id=bid, node_type="bin",
            arrival_time_seconds=600 + i * 300,
            departure_time_seconds=900 + i * 300,
            fill_collected_liters=50.0,
            cumulative_load_liters=50.0 * (i + 1),
        ))
    stops.append(RouteStop(node_id="depot", node_type="depot",
                           arrival_time_seconds=3600, departure_time_seconds=3600))
    return OptimizedRoute(truck_id=truck_id, stops=stops,
                          total_distance_m=2000.0, total_duration_seconds=3600,
                          total_load_liters=50.0 * len(bin_ids))


def _small_vrp(n_bins: int = 4, n_trucks: int = 1) -> VRPInput:
    depot = make_depot()
    bins = [make_bin(f"B{i:03}", lat=25.21 + i * 0.002, lng=55.28,
                     fill_liters=70.0, hours_until_critical=4.0)
            for i in range(1, n_bins + 1)]
    trucks = [make_truck(f"T{j}") for j in range(1, n_trucks + 1)]
    dump = make_dump_yard()
    return VRPInput(bins=bins, trucks=trucks, depot=depot, dump_yards=[dump])


@pytest.fixture
def reoptimizer(fake_redis, mock_orchestrator, mock_dispatcher, mock_truck_manager):
    return Reoptimizer(mock_orchestrator, mock_dispatcher, mock_truck_manager, fake_redis)


# ---------------------------------------------------------------------------
# Scope rules
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overflow_alert_scope_single_truck(fake_redis, reoptimizer):
    vrp = _small_vrp(n_bins=3, n_trucks=2)
    # All bins flagged so _sync_bins keeps them
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    result = await reoptimizer.handle_event(
        _make_event("overflow_alert", bin_id="B001", priority=3), vrp
    )
    assert result.scope == "single_truck"


@pytest.mark.asyncio
async def test_overflow_alert_nearest_truck_selected(fake_redis, mock_orchestrator,
                                                      mock_dispatcher, mock_truck_manager):
    """Nearest truck to the flagged bin is selected for single-truck re-solve."""
    from routing.schemas import Truck
    # T1 depot is close to B001, T2 depot is far
    t1 = Truck(truck_id="T1", capacity_liters=1000, depot_lat=25.212, depot_lng=55.280,
               shift_start_seconds=0, shift_end_seconds=28800)
    t2 = Truck(truck_id="T2", capacity_liters=1000, depot_lat=25.500, depot_lng=55.700,
               shift_start_seconds=0, shift_end_seconds=28800)
    depot = make_depot()
    b1 = make_bin("B001", lat=25.213, lng=55.280, fill_liters=70.0, hours_until_critical=1.0)
    vrp = VRPInput(bins=[b1], trucks=[t1, t2], depot=depot, dump_yards=[])

    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    await redis.sadd("bins:flagged", b"B001")

    reopt = Reoptimizer(mock_orchestrator, mock_dispatcher, mock_truck_manager, redis)
    await reopt.handle_event(_make_event("overflow_alert", bin_id="B001", priority=3), vrp)

    # orchestrator.solve should have been called with only T1
    call_args = mock_orchestrator.solve.call_args
    solved_vrp: VRPInput = call_args[0][0]
    assert len(solved_vrp.trucks) == 1
    assert solved_vrp.trucks[0].truck_id == "T1"


@pytest.mark.asyncio
async def test_tip_over_removes_tipped_bin(fake_redis, reoptimizer, mock_orchestrator):
    """tip_over event: tipped bin excluded from re-solve VRP."""
    vrp = _small_vrp(n_bins=3)
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    await reoptimizer.handle_event(
        _make_event("tip_over", bin_id="B002", truck_id="T1", priority=3), vrp
    )

    call_args = mock_orchestrator.solve.call_args
    solved_vrp: VRPInput = call_args[0][0]
    assert all(b.node_id != "B002" for b in solved_vrp.bins)


@pytest.mark.asyncio
async def test_tip_over_scope_single_truck(fake_redis, reoptimizer):
    vrp = _small_vrp(n_bins=3)
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    result = await reoptimizer.handle_event(
        _make_event("tip_over", bin_id="B001", truck_id="T1", priority=3), vrp
    )
    assert result.scope == "single_truck"


@pytest.mark.asyncio
async def test_truck_capacity_hit_no_full_resolve(fake_redis, reoptimizer, mock_orchestrator):
    """truck_capacity_hit: dump yard injected, orchestrator NOT called."""
    vrp = _small_vrp()
    mock_orchestrator.solve.reset_mock()

    result = await reoptimizer.handle_event(
        _make_event("truck_capacity_hit", truck_id="T1", priority=3), vrp
    )

    assert result.scope == "single_truck"
    mock_orchestrator.solve.assert_not_called()


@pytest.mark.asyncio
async def test_truck_capacity_hit_dump_yard_prepended(fake_redis, mock_orchestrator,
                                                       mock_dispatcher, mock_truck_manager):
    """truck_capacity_hit: dump yard inserted at position 1 in active route."""
    vrp = _small_vrp()
    existing_route = _make_route("T1", ["B001", "B002"])
    mock_dispatcher.get_route_for_truck.return_value = existing_route

    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    reopt = Reoptimizer(mock_orchestrator, mock_dispatcher, mock_truck_manager, redis)

    await reopt.handle_event(_make_event("truck_capacity_hit", truck_id="T1", priority=3), vrp)

    # replace_route was called with a route having dump_yard as stop[1]
    mock_dispatcher.replace_route.assert_called_once()
    new_route: OptimizedRoute = mock_dispatcher.replace_route.call_args[0][1]
    assert new_route.stops[1].node_type == "dump_yard"


@pytest.mark.asyncio
async def test_truck_shift_ending_scope_full_fleet(fake_redis, reoptimizer):
    vrp = _small_vrp(n_bins=3, n_trucks=2)
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    result = await reoptimizer.handle_event(
        _make_event("truck_shift_ending", truck_id="T1", priority=3), vrp
    )
    assert result.scope == "full_fleet"


@pytest.mark.asyncio
async def test_truck_shift_ending_excludes_ending_truck(fake_redis, reoptimizer,
                                                         mock_orchestrator):
    """truck_shift_ending: ending truck excluded from re-solve."""
    vrp = _small_vrp(n_bins=3, n_trucks=2)
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    await reoptimizer.handle_event(
        _make_event("truck_shift_ending", truck_id="T1", priority=3), vrp
    )

    call_args = mock_orchestrator.solve.call_args
    solved_vrp: VRPInput = call_args[0][0]
    assert all(t.truck_id != "T1" for t in solved_vrp.trucks)


@pytest.mark.asyncio
async def test_new_bins_flagged_full_fleet_when_3_or_more(fake_redis, reoptimizer,
                                                            mock_dispatcher):
    """new_bins_flagged with 3+ new bins → full_fleet scope."""
    vrp = _small_vrp(n_bins=4)
    # Flag all bins but none in active routes → all 4 are "new"
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())
    mock_dispatcher.get_active_routes.return_value = []

    result = await reoptimizer.handle_event(
        _make_event("new_bins_flagged", priority=1), vrp
    )
    assert result.scope == "full_fleet"
    assert len(result.bins_added) >= 3


@pytest.mark.asyncio
async def test_new_bins_flagged_zone_when_fewer_than_3(fake_redis, reoptimizer,
                                                        mock_dispatcher):
    """new_bins_flagged with < 3 new bins → zone scope."""
    vrp = _small_vrp(n_bins=2)
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())
    mock_dispatcher.get_active_routes.return_value = []

    result = await reoptimizer.handle_event(
        _make_event("new_bins_flagged", priority=1), vrp
    )
    assert result.scope == "zone"
    assert len(result.bins_added) < 3


@pytest.mark.asyncio
async def test_manual_override_always_full_fleet(fake_redis, reoptimizer):
    vrp = _small_vrp()
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    result = await reoptimizer.handle_event(
        _make_event("manual_override", priority=3), vrp
    )
    assert result.scope == "full_fleet"


# ---------------------------------------------------------------------------
# Pre-solve bin sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_faulted_bins_removed_before_solve(fake_redis, reoptimizer, mock_orchestrator):
    """Bins in bins:faulted removed from VRP before solve."""
    vrp = _small_vrp(n_bins=3)
    # Flag all, fault B002
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())
    await fake_redis.sadd("bins:faulted", b"B002")

    result = await reoptimizer.handle_event(
        _make_event("manual_override", priority=3), vrp
    )

    assert "B002" in result.bins_removed
    call_args = mock_orchestrator.solve.call_args
    solved_vrp: VRPInput = call_args[0][0]
    assert all(b.node_id != "B002" for b in solved_vrp.bins)


@pytest.mark.asyncio
async def test_collected_bins_removed_before_solve(fake_redis, reoptimizer, mock_orchestrator):
    """Bins in VRP but not in bins:flagged (collected) removed before solve."""
    vrp = _small_vrp(n_bins=3)
    # Only flag B001 and B003 — B002 is "collected" (not in flagged set)
    await fake_redis.sadd("bins:flagged", b"B001")
    await fake_redis.sadd("bins:flagged", b"B003")

    result = await reoptimizer.handle_event(
        _make_event("manual_override", priority=3), vrp
    )

    assert "B002" in result.bins_removed
    call_args = mock_orchestrator.solve.call_args
    solved_vrp: VRPInput = call_args[0][0]
    assert all(b.node_id != "B002" for b in solved_vrp.bins)


@pytest.mark.asyncio
async def test_bins_added_contains_newly_flagged(fake_redis, mock_orchestrator,
                                                  mock_dispatcher, mock_truck_manager):
    """bins_added = bins in VRP not in any current active route."""
    vrp = _small_vrp(n_bins=4)
    # Existing routes already have B001, B002 assigned
    existing = _make_route("T1", ["B001", "B002"])
    mock_dispatcher.get_active_routes.return_value = [existing]

    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    for b in vrp.bins:
        await redis.sadd("bins:flagged", b.node_id.encode())

    reopt = Reoptimizer(mock_orchestrator, mock_dispatcher, mock_truck_manager, redis)
    result = await reopt.handle_event(_make_event("manual_override", priority=3), vrp)

    # B003 and B004 are new (not in existing routes)
    assert "B003" in result.bins_added
    assert "B004" in result.bins_added
    assert "B001" not in result.bins_added
    assert "B002" not in result.bins_added


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_records_results(fake_redis, reoptimizer):
    vrp = _small_vrp()
    for b in vrp.bins:
        await fake_redis.sadd("bins:flagged", b.node_id.encode())

    await reoptimizer.handle_event(_make_event("manual_override", priority=3), vrp)
    await reoptimizer.handle_event(_make_event("manual_override", priority=3), vrp)

    history = reoptimizer.get_history()
    assert len(history) == 2
    assert all(isinstance(r, ReOptResult) for r in history)
