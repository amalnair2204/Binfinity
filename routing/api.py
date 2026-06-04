"""Routing FastAPI — prefix /routing."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket
from loguru import logger
from pydantic import BaseModel

from routing.dispatcher import DispatchEvent
from routing.schemas import OptimizedRoute, RouteStop, Truck, VRPInput, VRPSolution
from routing.ws import broadcast_to_ops, driver_ws_endpoint, ops_ws_endpoint

app = FastAPI(title="Binfinity Routing API")
router = APIRouter(prefix="/routing")
dispatch_router = APIRouter(prefix="/dispatch")

# ---------------------------------------------------------------------------
# Module-level singletons — monkeypatched in tests
# ---------------------------------------------------------------------------

_dispatcher = None          # RouteDispatcher | None
_orchestrator = None        # SolverOrchestrator | None
_last_vrp_input: Optional[VRPInput] = None
_active_routes: dict[str, OptimizedRoute] = {}   # truck_id → route
_route_by_id: dict[str, str] = {}               # route_id → truck_id
_trucks: dict[str, Truck] = {}
_events_log: deque = deque(maxlen=50)
_last_solve_time: Optional[datetime] = None
_last_unserved: list[str] = []
_solve_stats: dict[str, Any] = {
    "count": 0,
    "total_ms": 0.0,
    "bins_collected_today": 0,
    "by_solver": {"ortools": 0, "simulated_annealing": 0, "greedy_fallback": 0},
}

# Phase 7 dispatch singletons
_truck_manager = None       # TruckManager | None
_feedback_handler = None    # FeedbackHandler | None
_dispatch_redis = None      # aioredis.Redis | None (for feedback queue peek)
_reopt_history: deque = deque(maxlen=20)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    active_routes: int
    last_solve_time: Optional[datetime]
    dispatcher_ready: bool
    orchestrator_ready: bool


class TruckStatus(BaseModel):
    truck_id: str
    capacity_liters: int
    shift_start_seconds: int
    shift_end_seconds: int
    can_access_narrow: bool
    route_id: Optional[str] = None
    bins_remaining: int = 0
    is_active: bool = False


class TruckUpdate(BaseModel):
    shift_start_seconds: Optional[int] = None
    shift_end_seconds: Optional[int] = None
    capacity_liters: Optional[int] = None
    can_access_narrow: Optional[bool] = None


class GenerateRequest(BaseModel):
    window_hours: float = 6.0
    threshold: float = 70.0


class RoutingStats(BaseModel):
    total_routes_generated: int
    bins_collected_today: int
    avg_solve_ms: float
    solver_usage: dict[str, int]
    last_solve_time: Optional[datetime]
    active_route_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_ready():
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Routing service not ready")


def receive_solution(solution: VRPSolution, triggered_by: str = "scheduled") -> None:
    """Called by scheduler/dispatcher after every solve to update in-memory API state."""
    global _last_solve_time, _last_unserved

    _last_solve_time = solution.solved_at
    _last_unserved = list(solution.unserved_bins)

    # Update active routes
    for route in solution.routes:
        _active_routes[route.truck_id] = route
        _route_by_id[route.route_id] = route.truck_id

    # Update stats
    _solve_stats["count"] += 1
    _solve_stats["total_ms"] += solution.solve_time_ms
    _solve_stats["by_solver"][solution.solver] = (
        _solve_stats["by_solver"].get(solution.solver, 0) + 1
    )
    bins_in_solution = sum(
        sum(1 for s in r.stops if s.node_type == "bin")
        for r in solution.routes
    )
    _solve_stats["bins_collected_today"] += bins_in_solution

    logger.debug(
        "API state updated: {} active routes, solver={}", len(_active_routes), solution.solver
    )


def _truck_status(truck_id: str) -> TruckStatus:
    truck = _trucks.get(truck_id)
    route = _active_routes.get(truck_id)
    if truck is None:
        return TruckStatus(
            truck_id=truck_id,
            capacity_liters=0,
            shift_start_seconds=0,
            shift_end_seconds=28800,
            can_access_narrow=True,
            route_id=route.route_id if route else None,
            bins_remaining=sum(1 for s in route.stops if s.node_type == "bin") if route else 0,
            is_active=route is not None,
        )
    return TruckStatus(
        truck_id=truck_id,
        capacity_liters=truck.capacity_liters,
        shift_start_seconds=truck.shift_start_seconds,
        shift_end_seconds=truck.shift_end_seconds,
        can_access_narrow=truck.can_access_narrow,
        route_id=route.route_id if route else None,
        bins_remaining=sum(1 for s in route.stops if s.node_type == "bin") if route else 0,
        is_active=route is not None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok" if _orchestrator is not None else "degraded",
        active_routes=len(_active_routes),
        last_solve_time=_last_solve_time,
        dispatcher_ready=_dispatcher is not None,
        orchestrator_ready=_orchestrator is not None,
    )


@router.get("/routes", response_model=list[OptimizedRoute])
async def list_routes():
    _require_ready()
    return list(_active_routes.values())


@router.get("/routes/truck/{truck_id}/next-stop", response_model=RouteStop)
async def get_next_stop(truck_id: str):
    _require_ready()
    route = _active_routes.get(truck_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"No active route for truck {truck_id!r}")
    nxt = next((s for s in route.stops if s.node_type == "bin"), None)
    if nxt is None:
        raise HTTPException(status_code=404, detail="No remaining stops on route")
    return nxt


@router.get("/routes/truck/{truck_id}", response_model=OptimizedRoute)
async def get_route_for_truck(truck_id: str):
    _require_ready()
    route = _active_routes.get(truck_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"No active route for truck {truck_id!r}")
    return route


@router.get("/routes/{route_id}", response_model=OptimizedRoute)
async def get_route_by_id(route_id: str):
    _require_ready()
    truck_id = _route_by_id.get(route_id)
    if truck_id is None:
        raise HTTPException(status_code=404, detail=f"Route {route_id!r} not found")
    route = _active_routes.get(truck_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"Route {route_id!r} no longer active")
    return route


@router.post("/routes/generate")
async def generate_routes(req: GenerateRequest):
    _require_ready()
    if _last_vrp_input is None:
        raise HTTPException(status_code=503, detail="No VRP problem loaded yet")
    solution: VRPSolution = await _orchestrator.solve(_last_vrp_input)
    receive_solution(solution, triggered_by="manual_generate")
    if _dispatcher is not None:
        await _dispatcher.apply_solution(solution, triggered_by="manual_generate")
    await broadcast_to_ops("routes", {"routes": [r.model_dump(mode="json") for r in solution.routes]})
    return solution


@router.post("/routes/truck/{truck_id}/stop/{bin_id}/complete")
async def complete_stop(truck_id: str, bin_id: str):
    _require_ready()
    route = _active_routes.get(truck_id)
    if route is None:
        raise HTTPException(status_code=404, detail=f"No active route for truck {truck_id!r}")
    new_stops = [s for s in route.stops if not (s.node_type == "bin" and s.node_id == bin_id)]
    if len(new_stops) == len(route.stops):
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not on truck {truck_id!r} route")
    _active_routes[truck_id] = route.model_copy(update={"stops": new_stops})
    if _dispatcher is not None:
        await _dispatcher.mark_stop_complete(truck_id, bin_id)
    return {"status": "ok", "truck_id": truck_id, "bin_id": bin_id}


@router.get("/events", response_model=list[DispatchEvent])
async def list_events():
    _require_ready()
    return list(_events_log)


@router.post("/events", response_model=DispatchEvent)
async def inject_event(event: DispatchEvent):
    _require_ready()
    _events_log.appendleft(event)
    if _dispatcher is not None:
        await _dispatcher.on_event(event)
    await broadcast_to_ops("alert", event.model_dump(mode="json"))
    return event


@router.get("/trucks", response_model=list[TruckStatus])
async def list_trucks():
    _require_ready()
    all_ids = set(_trucks.keys()) | set(_active_routes.keys())
    return [_truck_status(tid) for tid in sorted(all_ids)]


@router.patch("/trucks/{truck_id}", response_model=Truck)
async def update_truck(truck_id: str, update: TruckUpdate):
    _require_ready()
    truck = _trucks.get(truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    patch = update.model_dump(exclude_none=True)
    updated = truck.model_copy(update=patch)
    _trucks[truck_id] = updated
    return updated


@router.get("/stats", response_model=RoutingStats)
async def get_stats():
    _require_ready()
    count = _solve_stats["count"]
    avg_ms = (_solve_stats["total_ms"] / count) if count > 0 else 0.0
    return RoutingStats(
        total_routes_generated=count,
        bins_collected_today=_solve_stats["bins_collected_today"],
        avg_solve_ms=avg_ms,
        solver_usage=dict(_solve_stats["by_solver"]),
        last_solve_time=_last_solve_time,
        active_route_count=len(_active_routes),
    )


@router.get("/unassigned", response_model=list[str])
async def get_unassigned():
    _require_ready()
    return list(_last_unserved)


# ---------------------------------------------------------------------------
# Dispatch sub-router — /routing/dispatch/*
# ---------------------------------------------------------------------------

class DispatchTruckState(BaseModel):
    truck_id: str
    status: str
    load_liters: float
    position: Optional[dict] = None
    capacity_liters: int = 0


class PositionUpdate(BaseModel):
    lat: float
    lng: float


class LoadUpdate(BaseModel):
    load_liters: float


class CollectRequest(BaseModel):
    actual_liters: float = 0.0


class ReoptTriggerRequest(BaseModel):
    scope: Literal["full_fleet", "single_truck", "zone"] = "full_fleet"
    reason: str = "manual"


class ReoptHistoryEntry(BaseModel):
    scope: str
    event_type: str
    triggered_at: datetime
    solve_time_ms: float
    bins_added: list[str] = []
    bins_removed: list[str] = []


class FeedbackQueueStatus(BaseModel):
    queue_length: int


class DispatchStatus(BaseModel):
    active_trucks: list[DispatchTruckState]
    open_events: int
    last_reopt_times: dict[str, Optional[str]]


def _require_truck_manager():
    if _truck_manager is None:
        raise HTTPException(status_code=503, detail="Truck manager not initialised")


def _require_feedback_handler():
    if _feedback_handler is None:
        raise HTTPException(status_code=503, detail="Feedback handler not initialised")


@dispatch_router.get("/status", response_model=DispatchStatus)
async def dispatch_status():
    _require_ready()
    trucks: list[DispatchTruckState] = []
    all_ids = set(_active_routes.keys())
    if _truck_manager is not None:
        try:
            registered = await _truck_manager.get_all_trucks()
            all_ids |= {t.truck_id for t in registered}
        except Exception:
            pass

    for tid in sorted(all_ids):
        load = 0.0
        status = "unknown"
        pos = None
        cap = 0
        if _truck_manager is not None:
            try:
                load = await _truck_manager.get_current_load(tid)
                status = await _truck_manager.get_status(tid)
                pos = await _truck_manager.get_position(tid)
                t = await _truck_manager.get_truck(tid)
                if t:
                    cap = t.capacity_liters
            except Exception:
                pass
        route = _active_routes.get(tid)
        if route and status == "unknown":
            status = "active"
        trucks.append(DispatchTruckState(
            truck_id=tid, status=status, load_liters=load,
            position=pos, capacity_liters=cap,
        ))

    return DispatchStatus(
        active_trucks=trucks,
        open_events=len(_events_log),
        last_reopt_times={},
    )


@dispatch_router.get("/trucks", response_model=list[DispatchTruckState])
async def list_dispatch_trucks():
    _require_ready()
    if _truck_manager is None:
        return []
    all_trucks = await _truck_manager.get_all_trucks()
    result = []
    for t in all_trucks:
        load = await _truck_manager.get_current_load(t.truck_id)
        status = await _truck_manager.get_status(t.truck_id)
        pos = await _truck_manager.get_position(t.truck_id)
        result.append(DispatchTruckState(
            truck_id=t.truck_id, status=status, load_liters=load,
            position=pos, capacity_liters=t.capacity_liters,
        ))
    return result


@dispatch_router.get("/trucks/{truck_id}", response_model=DispatchTruckState)
async def get_dispatch_truck(truck_id: str):
    _require_ready()
    _require_truck_manager()
    truck = await _truck_manager.get_truck(truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    load = await _truck_manager.get_current_load(truck_id)
    status = await _truck_manager.get_status(truck_id)
    pos = await _truck_manager.get_position(truck_id)
    return DispatchTruckState(
        truck_id=truck_id, status=status, load_liters=load,
        position=pos, capacity_liters=truck.capacity_liters,
    )


@dispatch_router.patch("/trucks/{truck_id}/position")
async def update_truck_position(truck_id: str, body: PositionUpdate):
    _require_ready()
    _require_truck_manager()
    truck = await _truck_manager.get_truck(truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    await _truck_manager.update_position(truck_id, body.lat, body.lng)
    await broadcast_to_ops("truck_pos", {"truck_id": truck_id, "lat": body.lat, "lng": body.lng})
    return {"status": "ok", "truck_id": truck_id, "lat": body.lat, "lng": body.lng}


@dispatch_router.patch("/trucks/{truck_id}/load")
async def update_truck_load(truck_id: str, body: LoadUpdate):
    _require_ready()
    _require_truck_manager()
    truck = await _truck_manager.get_truck(truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    await _truck_manager.update_load(truck_id, body.load_liters)
    return {"status": "ok", "truck_id": truck_id, "load_liters": body.load_liters}


@dispatch_router.post("/trucks/{truck_id}/collect/{bin_id}")
async def collect_bin(truck_id: str, bin_id: str, req: Optional[CollectRequest] = None):
    _require_ready()
    _require_feedback_handler()
    if _truck_manager is not None:
        truck = await _truck_manager.get_truck(truck_id)
        if truck is None:
            raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    liters = req.actual_liters if req else 0.0
    await _feedback_handler.on_bin_emptied(truck_id, bin_id, liters)
    return {"status": "ok", "truck_id": truck_id, "bin_id": bin_id, "liters": liters}


@dispatch_router.post("/trucks/{truck_id}/dump/{yard_id}")
async def dump_at_yard(truck_id: str, yard_id: str):
    _require_ready()
    _require_feedback_handler()
    if _truck_manager is not None:
        truck = await _truck_manager.get_truck(truck_id)
        if truck is None:
            raise HTTPException(status_code=404, detail=f"Truck {truck_id!r} not found")
    await _feedback_handler.on_dump_completed(truck_id, yard_id)
    return {"status": "ok", "truck_id": truck_id, "yard_id": yard_id}


@dispatch_router.get("/reopt/history", response_model=list[ReoptHistoryEntry])
async def reopt_history():
    _require_ready()
    return [
        ReoptHistoryEntry(
            scope=r.get("scope", "full_fleet"),
            event_type=r.get("event_type", "manual"),
            triggered_at=r.get("triggered_at", datetime.now(tz=timezone.utc)),
            solve_time_ms=r.get("solve_time_ms", 0.0),
            bins_added=r.get("bins_added", []),
            bins_removed=r.get("bins_removed", []),
        )
        for r in _reopt_history
    ]


@dispatch_router.post("/reopt/trigger", status_code=202)
async def trigger_reopt(req: ReoptTriggerRequest):
    _require_ready()
    if _last_vrp_input is None:
        raise HTTPException(status_code=503, detail="No VRP problem loaded")

    solution: VRPSolution = await _orchestrator.solve(_last_vrp_input)
    receive_solution(solution, triggered_by=req.reason)
    if _dispatcher is not None:
        await _dispatcher.apply_solution(solution, triggered_by=req.reason)

    entry = {
        "scope": req.scope,
        "event_type": "manual_override",
        "triggered_at": datetime.now(tz=timezone.utc),
        "solve_time_ms": solution.solve_time_ms,
        "bins_added": [],
        "bins_removed": [],
    }
    _reopt_history.appendleft(entry)
    await broadcast_to_ops("routes", {"routes": [r.model_dump(mode="json") for r in solution.routes]})
    return {"status": "accepted", "scope": req.scope, "solver": solution.solver}


@dispatch_router.get("/feedback/queue", response_model=FeedbackQueueStatus)
async def feedback_queue_length():
    _require_ready()
    length = 0
    if _dispatch_redis is not None:
        try:
            length = await _dispatch_redis.llen("ml:feedback:queue")
        except Exception:
            pass
    return FeedbackQueueStatus(queue_length=length)


@dispatch_router.get("/collections/today")
async def collections_today():
    _require_ready()
    if _truck_manager is None:
        return []
    return await _truck_manager.get_collections_today()


# ---------------------------------------------------------------------------
# Mount routers + WebSocket
# ---------------------------------------------------------------------------

router.include_router(dispatch_router)
app.include_router(router)


@app.websocket("/ws/driver/{truck_id}")
async def ws_driver(websocket: WebSocket, truck_id: str):
    await driver_ws_endpoint(websocket, truck_id)


@app.websocket("/ws/ops")
async def ws_ops(websocket: WebSocket):
    await ops_ws_endpoint(websocket)
