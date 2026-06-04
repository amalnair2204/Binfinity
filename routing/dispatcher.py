"""Real-time route dispatcher — event-driven re-optimization with stability buffer."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import asyncpg
import redis.asyncio as aioredis
from loguru import logger
from pydantic import BaseModel

from routing.schemas import OptimizedRoute, VRPInput, VRPSolution
from routing.ws import push_overflow_alert
from infra.metrics import REOPTIMIZATIONS_TOTAL

# Minimum minutes between re-optimizations per truck (unless override=True)
_DEFAULT_MIN_INTERVAL_MIN = 15
_REDIS_ROUTE_TTL = 7200  # 2 hours

# Per-event-type rules: min_interval_min=0 means always trigger immediately
REOPTIMIZE_RULES: dict[str, dict] = {
    "overflow_alert":     {"min_interval_min": 15, "priority_override": False},
    "tip_over":           {"min_interval_min": 0,  "priority_override": True},
    "truck_capacity_hit": {"min_interval_min": 0,  "priority_override": True},
    "truck_shift_ending": {"min_interval_min": 0,  "priority_override": True},
    "new_bins_flagged":   {"min_interval_min": 15, "priority_override": False},
    "manual_override":    {"min_interval_min": 0,  "priority_override": True},
}

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS optimized_routes (
    route_id            TEXT PRIMARY KEY,
    truck_id            TEXT NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    triggered_by        TEXT,
    solver              TEXT,
    solve_time_ms       INTEGER,
    stops_json          JSONB,
    total_distance_m    DOUBLE PRECISION,
    total_duration_sec  INTEGER,
    bins_collected      INTEGER,
    dump_yard_visits    INTEGER,
    is_complete         BOOLEAN DEFAULT FALSE,
    objective_value     DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS route_events (
    event_id        TEXT PRIMARY KEY,
    route_id        TEXT REFERENCES optimized_routes(route_id),
    event_type      TEXT,
    triggered_at    TIMESTAMPTZ,
    affected_bin_id TEXT,
    truck_id        TEXT,
    resolved        BOOLEAN DEFAULT FALSE
);
"""


class DispatchEvent(BaseModel):
    event_id: str
    event_type: Literal[
        "overflow_alert",
        "tip_over",
        "truck_capacity_hit",
        "truck_shift_ending",
        "new_bins_flagged",
        "manual_override",
    ]
    triggered_at: datetime
    affected_bin_id: Optional[str] = None
    affected_truck_id: Optional[str] = None
    priority: int  # 1=low, 2=medium, 3=critical


class RouteDispatcher:
    def __init__(
        self,
        orchestrator,  # SolverOrchestrator
        redis: aioredis.Redis,
        db_pool: asyncpg.Pool,
    ) -> None:
        self._orchestrator = orchestrator
        self._redis = redis
        self._db_pool = db_pool
        self._active_routes: dict[str, OptimizedRoute] = {}
        self._vrp_input: Optional[VRPInput] = None
        self._deferred_events: list[DispatchEvent] = []

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

    async def init_schema(self) -> None:
        async with self._db_pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES_SQL)
        logger.info("RouteDispatcher: DB schema ready")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def set_vrp_input(self, vrp_input: VRPInput) -> None:
        """Update the current problem definition used when re-optimizing."""
        self._vrp_input = vrp_input

    async def get_active_routes(self) -> list[OptimizedRoute]:
        return list(self._active_routes.values())

    async def get_route_for_truck(self, truck_id: str) -> Optional[OptimizedRoute]:
        return self._active_routes.get(truck_id)

    async def mark_stop_complete(self, truck_id: str, bin_id: str) -> None:
        """Remove a completed bin stop from the truck's active route."""
        route = self._active_routes.get(truck_id)
        if route is None:
            logger.warning("mark_stop_complete: no route for truck {}", truck_id)
            return
        new_stops = [s for s in route.stops if not (s.node_type == "bin" and s.node_id == bin_id)]
        updated = route.model_copy(update={"stops": new_stops})
        self._active_routes[truck_id] = updated
        await self._push_route_to_redis(truck_id, updated)
        logger.debug("mark_stop_complete: truck={} bin={} removed", truck_id, bin_id)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def on_event(self, event: DispatchEvent) -> None:
        logger.info(
            "DispatchEvent: type={} truck={} bin={} priority={}",
            event.event_type, event.affected_truck_id, event.affected_bin_id, event.priority,
        )

        await self._persist_event(event, route_id=None)

        # Push overflow alert to the affected driver before re-optimizing
        if event.event_type == "overflow_alert" and event.affected_truck_id:
            try:
                await push_overflow_alert(
                    event.affected_truck_id,
                    event.affected_bin_id or "",
                    "Bin near overflow — route being updated",
                )
            except Exception as exc:
                logger.warning("RouteDispatcher: WS overflow push failed: {}", exc)

        if await self._should_reoptimize(event):
            await self._trigger_reoptimization(reason=event.event_type)
        else:
            self._deferred_events.append(event)
            logger.debug("DispatchEvent deferred (stability buffer): {}", event.event_type)

    async def _should_reoptimize(self, event: DispatchEvent) -> bool:
        rule = REOPTIMIZE_RULES.get(event.event_type, {"min_interval_min": _DEFAULT_MIN_INTERVAL_MIN, "priority_override": False})

        if rule["priority_override"] or event.priority >= 3:
            return True

        truck_id = event.affected_truck_id
        if truck_id is None:
            # Global event — check last global reopt time
            truck_id = "_global"

        last_reopt = await self._get_last_reopt_time(truck_id)
        if last_reopt is None:
            return True

        elapsed_min = (datetime.now(tz=timezone.utc) - last_reopt).total_seconds() / 60
        return elapsed_min >= rule["min_interval_min"]

    async def _trigger_reoptimization(self, reason: str) -> None:
        if self._vrp_input is None:
            logger.warning("_trigger_reoptimization: no VRPInput set, skipping")
            return

        REOPTIMIZATIONS_TOTAL.labels(trigger_type=reason).inc()
        logger.info("Triggering re-optimization: reason={}", reason)
        solution: VRPSolution = await self._orchestrator.solve(self._vrp_input)
        await self._apply_solution(solution, triggered_by=reason)

        # Update last-reopt timestamps for all affected trucks
        now = datetime.now(tz=timezone.utc)
        for route in solution.routes:
            await self._set_last_reopt_time(route.truck_id, now)
        await self._set_last_reopt_time("_global", now)

        # Flush deferred events that are now stale
        self._deferred_events.clear()

    # ------------------------------------------------------------------
    # Solution application and persistence
    # ------------------------------------------------------------------

    async def apply_solution(self, solution: VRPSolution, triggered_by: str = "scheduled") -> None:
        """Public method for the scheduler to push a freshly computed solution."""
        await self._apply_solution(solution, triggered_by)

    async def replace_route(self, truck_id: str, route: OptimizedRoute) -> None:
        """Replace a truck's active route in-place without triggering re-optimization."""
        self._active_routes[truck_id] = route
        await self._push_route_to_redis(truck_id, route)
        logger.debug("replace_route: truck={} route updated in-place", truck_id)

    async def _apply_solution(self, solution: VRPSolution, triggered_by: str) -> None:
        for route in solution.routes:
            self._active_routes[route.truck_id] = route
            await self._push_route_to_redis(route.truck_id, route)

        await self._persist_solution(solution, triggered_by)
        logger.info(
            "Solution applied: solver={} routes={} unserved={} status={}",
            solution.solver, len(solution.routes), len(solution.unserved_bins), solution.status,
        )

    async def _push_route_to_redis(self, truck_id: str, route: OptimizedRoute) -> None:
        key = f"dispatch:truck:{truck_id}:current_route"
        await self._redis.set(key, route.model_dump_json(), ex=_REDIS_ROUTE_TTL)

    async def _persist_solution(self, solution: VRPSolution, triggered_by: str) -> None:
        if self._db_pool is None:
            return
        try:
            async with self._db_pool.acquire() as conn:
                for route in solution.routes:
                    route_id = str(uuid.uuid4())
                    bin_stops = [s for s in route.stops if s.node_type == "bin"]
                    await conn.execute(
                        """
                        INSERT INTO optimized_routes
                            (route_id, truck_id, triggered_by, solver, solve_time_ms,
                             stops_json, total_distance_m, total_duration_sec,
                             bins_collected, dump_yard_visits, objective_value)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                        """,
                        route_id,
                        route.truck_id,
                        triggered_by,
                        solution.solver,
                        int(solution.solve_time_ms),
                        json.dumps([s.model_dump() for s in route.stops]),
                        route.total_distance_m,
                        route.total_duration_seconds,
                        len(bin_stops),
                        route.dump_yard_visits,
                        solution.objective_value,
                    )
        except Exception as exc:
            logger.error("Failed to persist solution to DB: {}", exc)

    async def _persist_event(self, event: DispatchEvent, route_id: Optional[str]) -> None:
        if self._db_pool is None:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO route_events
                        (event_id, route_id, event_type, triggered_at, affected_bin_id, truck_id)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    event.event_id,
                    route_id,
                    event.event_type,
                    event.triggered_at,
                    event.affected_bin_id,
                    event.affected_truck_id,
                )
        except Exception as exc:
            logger.error("Failed to persist event {}: {}", event.event_id, exc)

    # ------------------------------------------------------------------
    # Redis helpers for last-reopt timestamps
    # ------------------------------------------------------------------

    async def _get_last_reopt_time(self, truck_id: str) -> Optional[datetime]:
        key = f"dispatch:truck:{truck_id}:last_reopt"
        val = await self._redis.get(key)
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    async def _set_last_reopt_time(self, truck_id: str, ts: datetime) -> None:
        key = f"dispatch:truck:{truck_id}:last_reopt"
        # Keep for 24h — well beyond any shift
        await self._redis.set(key, ts.isoformat(), ex=86400)
