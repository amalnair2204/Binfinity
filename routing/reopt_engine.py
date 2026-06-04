"""Re-optimization decision engine with stability buffer and partial fleet support."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from routing.dispatcher import REOPTIMIZE_RULES, DispatchEvent, RouteDispatcher
from routing.schemas import OptimizedRoute, VRPInput, VRPSolution

_ROUTE_STABILITY_BUFFER = 0.15  # 15% delta threshold — see CLAUDE.md ROUTE_STABILITY_BUFFER
_DEFAULT_MIN_INTERVAL_MIN = 15

# Events that trigger a single-truck re-opt rather than full fleet re-solve
_SINGLE_TRUCK_EVENTS = {"truck_capacity_hit", "truck_shift_ending"}


class ReoptEngine:
    """Wraps the orchestrator with the full re-optimization decision tree.

    Decision tree:
    1. Priority override or priority >= 3 → bypass stability buffer, immediate re-opt
    2. Non-critical events → check per-event min_interval (stability buffer)
    3. After solving: compute distance delta vs current active routes
       - delta > ROUTE_STABILITY_BUFFER (15%) → apply new routes
       - delta <= 15% and force=False → discard (routes stable enough)
    4. truck_capacity_hit / truck_shift_ending → single-truck re-opt using
       only the affected truck's remaining bins
    """

    def __init__(
        self,
        orchestrator,  # SolverOrchestrator — typed loosely to avoid circular import
        dispatcher: RouteDispatcher,
    ) -> None:
        self._orchestrator = orchestrator
        self._dispatcher = dispatcher

    async def maybe_reoptimize(
        self,
        event: DispatchEvent,
        vrp_input: VRPInput,
        force: bool = False,
    ) -> Optional[VRPSolution]:
        """Run re-optimization decision tree.

        Returns the applied VRPSolution if routes were updated, None if skipped.
        """
        if not force and not await self._should_reoptimize(event):
            logger.debug(
                "ReoptEngine: skipped (stability buffer) event_type={}", event.event_type
            )
            return None

        if event.event_type in _SINGLE_TRUCK_EVENTS and event.affected_truck_id is not None:
            return await self._single_truck_reopt(event, vrp_input)

        return await self._fleet_reopt(event, vrp_input, force=force)

    # ------------------------------------------------------------------
    # Re-opt paths
    # ------------------------------------------------------------------

    async def _fleet_reopt(
        self,
        event: DispatchEvent,
        vrp_input: VRPInput,
        force: bool,
    ) -> Optional[VRPSolution]:
        """Full fleet re-optimization."""
        logger.info("ReoptEngine: fleet re-opt triggered by event_type={}", event.event_type)
        solution: VRPSolution = await self._orchestrator.solve(vrp_input)
        current_routes = await self._dispatcher.get_active_routes()

        if not force and not self._delta_exceeds_threshold(current_routes, solution):
            logger.info(
                "ReoptEngine: new solution within {}% stability buffer, discarding",
                int(_ROUTE_STABILITY_BUFFER * 100),
            )
            return None

        await self._dispatcher.apply_solution(solution, triggered_by=event.event_type)
        logger.info(
            "ReoptEngine: applied fleet re-opt solver={} routes={} unserved={}",
            solution.solver, len(solution.routes), len(solution.unserved_bins),
        )
        return solution

    async def _single_truck_reopt(
        self,
        event: DispatchEvent,
        vrp_input: VRPInput,
    ) -> Optional[VRPSolution]:
        """Re-optimize only the affected truck's remaining route.

        Builds a single-truck VRPInput from the unfinished bins in that truck's
        current route, solves, and applies only the affected truck's new route.
        """
        truck_id = event.affected_truck_id
        assert truck_id is not None

        target_truck = next((t for t in vrp_input.trucks if t.truck_id == truck_id), None)
        if target_truck is None:
            logger.warning(
                "ReoptEngine: truck={} not in VRPInput, falling back to fleet re-opt", truck_id
            )
            return await self._fleet_reopt(event, vrp_input, force=True)

        current_route = await self._dispatcher.get_route_for_truck(truck_id)
        remaining_bin_ids: set[str] = set()
        if current_route is not None:
            remaining_bin_ids = {s.node_id for s in current_route.stops if s.node_type == "bin"}

        bins_for_truck = [b for b in vrp_input.bins if b.node_id in remaining_bin_ids]
        if not bins_for_truck:
            logger.info("ReoptEngine: no remaining bins for truck={}, skipping", truck_id)
            return None

        single_vrp = VRPInput(
            bins=bins_for_truck,
            trucks=[target_truck],
            depot=vrp_input.depot,
            dump_yards=vrp_input.dump_yards,
            traffic_delay_factor=vrp_input.traffic_delay_factor,
            max_solve_seconds=min(vrp_input.max_solve_seconds, 15),
        )

        solution = await self._orchestrator.solve(single_vrp)
        await self._dispatcher.apply_solution(solution, triggered_by=event.event_type)
        logger.info(
            "ReoptEngine: applied single-truck re-opt truck={} solver={} bins={}",
            truck_id, solution.solver, len(bins_for_truck),
        )
        return solution

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    async def _should_reoptimize(self, event: DispatchEvent) -> bool:
        """Check stability buffer rules for this event."""
        rule = REOPTIMIZE_RULES.get(
            event.event_type,
            {"min_interval_min": _DEFAULT_MIN_INTERVAL_MIN, "priority_override": False},
        )

        if rule["priority_override"] or event.priority >= 3:
            return True

        truck_id = event.affected_truck_id or "_global"
        last_reopt = await self._dispatcher._get_last_reopt_time(truck_id)
        if last_reopt is None:
            return True

        elapsed_min = (datetime.now(tz=timezone.utc) - last_reopt).total_seconds() / 60
        return elapsed_min >= rule["min_interval_min"]

    def _delta_exceeds_threshold(
        self,
        current_routes: list[OptimizedRoute],
        new_solution: VRPSolution,
    ) -> bool:
        """Return True if total distance delta exceeds ROUTE_STABILITY_BUFFER."""
        old_cost = sum(r.total_distance_m for r in current_routes)
        new_cost = sum(r.total_distance_m for r in new_solution.routes)

        if old_cost == 0.0:
            return True  # No current routes — always apply

        delta = abs(new_cost - old_cost) / old_cost
        logger.debug(
            "ReoptEngine: cost delta={:.1%} old={:.0f}m new={:.0f}m threshold={}%",
            delta, old_cost, new_cost, int(_ROUTE_STABILITY_BUFFER * 100),
        )
        return delta > _ROUTE_STABILITY_BUFFER
