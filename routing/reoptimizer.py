"""Event-driven re-optimization engine with 6 scope rules and pre-solve bin sync."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal, Optional

import redis.asyncio as aioredis
from loguru import logger
from pydantic import BaseModel, Field

from routing.dispatcher import DispatchEvent, RouteDispatcher
from routing.distance import haversine_m, travel_time_seconds
from routing.schemas import OptimizedRoute, RouteStop, VRPInput, VRPSolution
from routing.ws import push_reroute


class ReOptResult(BaseModel):
    scope: Literal["full_fleet", "single_truck", "zone"]
    event_type: str
    solution: Optional[VRPSolution] = None
    bins_added: list[str] = Field(default_factory=list)
    bins_removed: list[str] = Field(default_factory=list)
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    solve_time_ms: float = 0.0


class Reoptimizer:
    """Event-aware re-optimization engine.

    Scope rules:
    1. overflow_alert    → single_truck (nearest truck to the flagged bin)
    2. tip_over          → single_truck (affected truck; tipped bin excluded from VRP)
    3. truck_capacity_hit → single_truck (dump yard injected, no re-solve)
    4. truck_shift_ending → full_fleet  (ending truck excluded; bins redistributed)
    5. new_bins_flagged, 3+ new bins → full_fleet
    6. new_bins_flagged, < 3 new bins → zone
    7. manual_override   → full_fleet  (stability buffer bypassed)

    Pre-solve sync (all re-solve cases):
    - bins in `bins:faulted` → removed from VRP (bins_removed)
    - bins in VRP but no longer in `bins:flagged` → treated as collected, removed (bins_removed)
    - bins in VRP not in any current active route → newly flagged (bins_added)
    """

    def __init__(
        self,
        orchestrator,           # SolverOrchestrator
        dispatcher: RouteDispatcher,
        truck_manager,          # TruckManager
        redis_client: aioredis.Redis,
    ) -> None:
        self._orchestrator = orchestrator
        self._dispatcher = dispatcher
        self._truck_manager = truck_manager
        self._redis = redis_client
        self._history: deque[ReOptResult] = deque(maxlen=20)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_event(
        self, event: DispatchEvent, vrp_input: VRPInput
    ) -> ReOptResult:
        """Run the re-optimization decision tree for a given dispatch event."""
        t0 = time.monotonic()
        triggered_at = datetime.now(tz=timezone.utc)

        synced_vrp, bins_added, bins_removed = await self._sync_bins(vrp_input)

        scope, solution = await self._route_event(event, synced_vrp, bins_added)

        result = ReOptResult(
            scope=scope,
            event_type=event.event_type,
            solution=solution,
            bins_added=bins_added,
            bins_removed=bins_removed,
            triggered_at=triggered_at,
            solve_time_ms=(time.monotonic() - t0) * 1000,
        )
        self._history.appendleft(result)

        # Push updated routes to connected drivers
        if solution is not None:
            for route in solution.routes:
                try:
                    await push_reroute(
                        route.truck_id,
                        route.model_dump(),
                        event.event_type,
                    )
                except Exception as exc:
                    logger.warning("Reoptimizer: WS push failed for truck={}: {}", route.truck_id, exc)

        return result

    def get_history(self) -> list[ReOptResult]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Event routing
    # ------------------------------------------------------------------

    async def _route_event(
        self,
        event: DispatchEvent,
        vrp: VRPInput,
        bins_added: list[str],
    ) -> tuple[str, Optional[VRPSolution]]:
        et = event.event_type

        if et == "overflow_alert":
            truck_id = await self._nearest_truck(event.affected_bin_id, vrp)
            sol = await self._single_truck_solve(truck_id, vrp, et)
            return "single_truck", sol

        if et == "tip_over":
            # Remove tipped bin from problem before re-solving
            if event.affected_bin_id:
                vrp = vrp.model_copy(
                    update={"bins": [b for b in vrp.bins if b.node_id != event.affected_bin_id]}
                )
            truck_id = event.affected_truck_id
            sol = await self._single_truck_solve(truck_id, vrp, et)
            return "single_truck", sol

        if et == "truck_capacity_hit":
            if event.affected_truck_id:
                await self._inject_dump_yard(event.affected_truck_id, vrp)
            return "single_truck", None

        if et == "truck_shift_ending":
            sol = await self._redistribute_from_truck(event.affected_truck_id, vrp)
            return "full_fleet", sol

        if et == "new_bins_flagged":
            sol = await self._orchestrator.solve(vrp)
            await self._dispatcher.apply_solution(sol, triggered_by=et)
            scope = "full_fleet" if len(bins_added) >= 3 else "zone"
            return scope, sol

        if et == "manual_override":
            sol = await self._orchestrator.solve(vrp)
            await self._dispatcher.apply_solution(sol, triggered_by=et)
            return "full_fleet", sol

        raise ValueError(f"Reoptimizer: unknown event_type={et!r}")

    # ------------------------------------------------------------------
    # Solver helpers
    # ------------------------------------------------------------------

    async def _single_truck_solve(
        self, truck_id: Optional[str], vrp: VRPInput, event_type: str
    ) -> Optional[VRPSolution]:
        if truck_id is None:
            return None

        target = next((t for t in vrp.trucks if t.truck_id == truck_id), None)
        if target is None:
            return None

        # Only include bins remaining on this truck's current route
        route = await self._dispatcher.get_route_for_truck(truck_id)
        if route is not None:
            remaining = {s.node_id for s in route.stops if s.node_type == "bin"}
            bins = [b for b in vrp.bins if b.node_id in remaining] or vrp.bins
        else:
            bins = vrp.bins

        if not bins:
            return None

        single_vrp = VRPInput(
            bins=bins,
            trucks=[target],
            depot=vrp.depot,
            dump_yards=vrp.dump_yards,
            traffic_delay_factor=vrp.traffic_delay_factor,
            max_solve_seconds=min(vrp.max_solve_seconds, 15),
        )
        sol = await self._orchestrator.solve(single_vrp)
        await self._dispatcher.apply_solution(sol, triggered_by=event_type)
        return sol

    async def _redistribute_from_truck(
        self, truck_id: Optional[str], vrp: VRPInput
    ) -> Optional[VRPSolution]:
        """Re-solve with ending truck excluded; remaining trucks absorb its bins."""
        remaining_trucks = [t for t in vrp.trucks if t.truck_id != truck_id]
        if not remaining_trucks:
            return None

        new_vrp = vrp.model_copy(update={"trucks": remaining_trucks})
        sol = await self._orchestrator.solve(new_vrp)
        await self._dispatcher.apply_solution(sol, triggered_by="truck_shift_ending")
        return sol

    async def _inject_dump_yard(self, truck_id: str, vrp: VRPInput) -> None:
        """Insert nearest dump yard as next stop in truck's active route (no re-solve)."""
        if not vrp.dump_yards:
            return

        route = await self._dispatcher.get_route_for_truck(truck_id)
        if route is None:
            return

        truck = next((t for t in vrp.trucks if t.truck_id == truck_id), None)
        cur_lat = truck.depot_lat if truck else vrp.depot.lat
        cur_lng = truck.depot_lng if truck else vrp.depot.lng

        # Use last known position if available
        try:
            pos = await self._truck_manager.get_position(truck_id)
            if pos:
                cur_lat, cur_lng = pos["lat"], pos["lng"]
        except Exception:
            pass

        nearest = min(
            vrp.dump_yards,
            key=lambda y: haversine_m(cur_lat, cur_lng, y.lat, y.lng),
        )
        dist = haversine_m(cur_lat, cur_lng, nearest.lat, nearest.lng)
        travel = travel_time_seconds(dist, vrp.traffic_delay_factor)
        base_time = route.stops[0].departure_time_seconds if route.stops else 0

        dump_stop = RouteStop(
            node_id=nearest.node_id,
            node_type="dump_yard",
            arrival_time_seconds=base_time + travel,
            departure_time_seconds=base_time + travel + 600,
            fill_collected_liters=0.0,
            cumulative_load_liters=0.0,
        )

        # Insert after the leading depot stop (position 1)
        if route.stops:
            new_stops = [route.stops[0], dump_stop] + list(route.stops[1:])
        else:
            new_stops = [dump_stop]

        new_route = route.model_copy(update={"stops": new_stops})
        await self._dispatcher.replace_route(truck_id, new_route)
        logger.info("Reoptimizer: dump yard injected as next stop for truck={}", truck_id)

    # ------------------------------------------------------------------
    # Nearest-truck selection
    # ------------------------------------------------------------------

    async def _nearest_truck(
        self, bin_id: Optional[str], vrp: VRPInput
    ) -> Optional[str]:
        """Return the truck_id whose depot is nearest to the given bin."""
        if not vrp.trucks:
            return None

        bin_node = next((b for b in vrp.bins if b.node_id == bin_id), None)
        if bin_node is None:
            return vrp.trucks[0].truck_id

        nearest_id = min(
            vrp.trucks,
            key=lambda t: haversine_m(t.depot_lat, t.depot_lng, bin_node.lat, bin_node.lng),
        ).truck_id
        return nearest_id

    # ------------------------------------------------------------------
    # Pre-solve bin sync
    # ------------------------------------------------------------------

    async def _sync_bins(
        self, vrp_input: VRPInput
    ) -> tuple[VRPInput, list[str], list[str]]:
        """Identify and remove stale bins before solving.

        Returns:
            (cleaned_vrp, bins_added, bins_removed)
        """
        faulted: set[str] = await self._smembers_decoded("bins:faulted")
        flagged: set[str] = await self._smembers_decoded("bins:flagged")

        # Bins in current active routes (still pending collection)
        active_bin_ids: set[str] = set()
        try:
            for route in await self._dispatcher.get_active_routes():
                for stop in route.stops:
                    if stop.node_type == "bin":
                        active_bin_ids.add(stop.node_id)
        except Exception:
            pass

        bins_removed: list[str] = []
        bins_added: list[str] = []
        clean_bins = []

        for b in vrp_input.bins:
            if b.node_id in faulted:
                bins_removed.append(b.node_id)
                continue
            if b.node_id not in flagged:
                # No longer flagged — collected since VRP was built
                bins_removed.append(b.node_id)
                continue
            clean_bins.append(b)
            if b.node_id not in active_bin_ids:
                bins_added.append(b.node_id)

        return vrp_input.model_copy(update={"bins": clean_bins}), bins_added, bins_removed

    async def _smembers_decoded(self, key: str) -> set[str]:
        members = await self._redis.smembers(key)
        return {m.decode() if isinstance(m, bytes) else m for m in members}
