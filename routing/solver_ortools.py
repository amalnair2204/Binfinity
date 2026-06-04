"""OR-Tools CVRPTW primary solver with greedy fallback."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from routing.distance import build_time_matrix, haversine_m, travel_time_seconds
from routing.schemas import (
    OptimizedRoute,
    RouteNode,
    RouteStop,
    Truck,
    VRPInput,
    VRPSolution,
)
from routing.solver_greedy import _nearest_node, solve_greedy

_DUMP_YARD_CAPACITY_TRIGGER = 0.85
_SERVICE_TIME_S = 300
_DUMP_YARD_SERVICE_S = 600
_PENALTY = 100_000_000


def solve_ortools(vrp: VRPInput) -> VRPSolution:
    """CVRPTW via OR-Tools; falls back to greedy on import error or solver failure."""
    t0 = time.monotonic()

    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # noqa: F401
    except ImportError:
        logger.warning("OR-Tools not available; falling back to greedy solver")
        return solve_greedy(vrp)

    try:
        solution = _solve_with_ortools(vrp, t0)
        if solution is not None:
            return solution
    except Exception as exc:
        logger.warning("OR-Tools solver error ({}); falling back to greedy", exc)

    greedy = solve_greedy(vrp)
    solve_ms = (time.monotonic() - t0) * 1000
    return greedy.model_copy(update={"solve_time_ms": solve_ms, "solver": "greedy_fallback"})


# ---------------------------------------------------------------------------
# Internal OR-Tools implementation
# ---------------------------------------------------------------------------

def _solve_with_ortools(vrp: VRPInput, t0: float) -> Optional[VRPSolution]:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    bins = vrp.bins
    n_bins = len(bins)

    if n_bins == 0:
        return VRPSolution(
            solved_at=datetime.now(tz=timezone.utc),
            solver="ortools",
            routes=[],
            unserved_bins=[],
            total_distance_m=0.0,
            total_duration_seconds=0,
            solve_time_ms=(time.monotonic() - t0) * 1000,
            status="optimal",
            objective_value=0.0,
        )

    # Node ordering: 0 = depot, 1..n_bins = bins
    nodes: list[RouteNode] = [vrp.depot] + bins
    n_nodes = len(nodes)
    n_vehicles = len(vrp.trucks)

    time_matrix = build_time_matrix(nodes, vrp.traffic_delay_factor)
    # Bake service time into transit FROM each bin node
    time_with_service = [row[:] for row in time_matrix]
    for i in range(1, n_nodes):
        for j in range(n_nodes):
            time_with_service[i][j] += _SERVICE_TIME_S

    manager = pywrapcp.RoutingIndexManager(n_nodes, n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_idx: int, to_idx: int) -> int:
        return time_with_service[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    transit_cb = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    max_shift = max(t.shift_end_seconds for t in vrp.trucks)
    routing.AddDimension(transit_cb, 0, max_shift, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    for v_idx, truck in enumerate(vrp.trucks):
        time_dim.CumulVar(routing.Start(v_idx)).SetRange(
            truck.shift_start_seconds, truck.shift_end_seconds
        )
        time_dim.CumulVar(routing.End(v_idx)).SetRange(0, truck.shift_end_seconds)

    for b_idx, bin_node in enumerate(bins):
        routing_idx = manager.NodeToIndex(b_idx + 1)
        deadline = int((bin_node.hours_until_critical or 24.0) * 3600)
        time_dim.CumulVar(routing_idx).SetRange(0, deadline)

    def demand_callback(from_idx: int) -> int:
        i = manager.IndexToNode(from_idx)
        return 0 if i == 0 else int(bins[i - 1].fill_liters or 0)

    demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb,
        0,
        [t.capacity_liters for t in vrp.trucks],
        True,
        "Capacity",
    )

    for b_idx in range(n_bins):
        routing.AddDisjunction([manager.NodeToIndex(b_idx + 1)], _PENALTY)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = vrp.max_solve_seconds

    ort_sol = routing.SolveWithParameters(params)
    solve_ms = (time.monotonic() - t0) * 1000

    if ort_sol is None:
        logger.warning("OR-Tools returned no solution; falling back to greedy")
        return None

    # OR-Tools 9.x status integers: 0=NOT_SOLVED, 1=SUCCESS, 3=FAIL,
    # 4=FAIL_TIMEOUT, 5=INVALID, 6=PARTIAL_SUCCESS, 7=OPTIMAL
    _STATUS = {0: "infeasible", 1: "feasible", 3: "infeasible",
               4: "timeout", 5: "infeasible", 6: "feasible", 7: "optimal"}
    solve_status = _STATUS.get(routing.status(), "feasible")

    routes: list[OptimizedRoute] = []
    served_bins: set[str] = set()

    for v_idx, truck in enumerate(vrp.trucks):
        raw_stops: list[RouteStop] = []
        cur_lat, cur_lng = truck.depot_lat, truck.depot_lng
        cur_time = truck.shift_start_seconds
        total_dist = 0.0
        total_load = 0.0

        raw_stops.append(RouteStop(
            node_id=vrp.depot.node_id,
            node_type="depot",
            arrival_time_seconds=cur_time,
            departure_time_seconds=cur_time,
            fill_collected_liters=0.0,
            cumulative_load_liters=0.0,
        ))

        index = routing.Start(v_idx)
        while not routing.IsEnd(index):
            next_index = ort_sol.Value(routing.NextVar(index))
            if not routing.IsEnd(next_index):
                node_j = manager.IndexToNode(next_index)
                bin_node = nodes[node_j]
                dist = haversine_m(cur_lat, cur_lng, bin_node.lat, bin_node.lng)
                travel_t = travel_time_seconds(dist, vrp.traffic_delay_factor)
                arrival = cur_time + travel_t
                departure = arrival + _SERVICE_TIME_S
                fill = bin_node.fill_liters or 0.0
                total_load += fill
                total_dist += dist
                cur_time = departure
                cur_lat, cur_lng = bin_node.lat, bin_node.lng
                served_bins.add(bin_node.node_id)
                raw_stops.append(RouteStop(
                    node_id=bin_node.node_id,
                    node_type="bin",
                    arrival_time_seconds=arrival,
                    departure_time_seconds=departure,
                    fill_collected_liters=fill,
                    cumulative_load_liters=total_load,
                ))
            index = next_index

        depot_dist = haversine_m(cur_lat, cur_lng, truck.depot_lat, truck.depot_lng)
        total_dist += depot_dist
        final_time = cur_time + travel_time_seconds(depot_dist, vrp.traffic_delay_factor)

        raw_stops.append(RouteStop(
            node_id=vrp.depot.node_id,
            node_type="depot",
            arrival_time_seconds=final_time,
            departure_time_seconds=final_time,
            fill_collected_liters=0.0,
            cumulative_load_liters=total_load,
        ))

        if not any(s.node_type == "bin" for s in raw_stops):
            continue

        final_stops, extra_dist, dump_visits = _insert_dump_yards(raw_stops, vrp, truck)
        routes.append(OptimizedRoute(
            truck_id=truck.truck_id,
            stops=final_stops,
            total_distance_m=total_dist + extra_dist,
            total_duration_seconds=max(0, final_time - truck.shift_start_seconds),
            total_load_liters=total_load,
            dump_yard_visits=dump_visits,
        ))

    unserved = [b.node_id for b in bins if b.node_id not in served_bins]
    total_dist_m = sum(r.total_distance_m for r in routes)
    total_duration = max((r.total_duration_seconds for r in routes), default=0)

    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="ortools",
        routes=routes,
        unserved_bins=unserved,
        total_distance_m=total_dist_m,
        total_duration_seconds=total_duration,
        solve_time_ms=solve_ms,
        status=solve_status,
        objective_value=float(ort_sol.ObjectiveValue()),
    )


# ---------------------------------------------------------------------------
# Post-processing: dump yard insertion
# ---------------------------------------------------------------------------

def _insert_dump_yards(
    stops: list[RouteStop],
    vrp: VRPInput,
    truck: Truck,
) -> tuple[list[RouteStop], float, int]:
    """Insert dump yard visits whenever cumulative load crosses the trigger threshold."""
    if not vrp.dump_yards:
        return stops, 0.0, 0

    new_stops: list[RouteStop] = []
    cumulative = 0.0
    extra_dist = 0.0
    dump_visits = 0
    trigger = truck.capacity_liters * _DUMP_YARD_CAPACITY_TRIGGER

    for stop in stops:
        if stop.node_type == "bin" and cumulative >= trigger:
            prev = new_stops[-1]
            prev_lat, prev_lng = _stop_coords(prev, vrp)
            yard, yard_dist = _nearest_node(prev_lat, prev_lng, vrp.dump_yards)
            yard_travel = travel_time_seconds(yard_dist, vrp.traffic_delay_factor)
            yard_arrival = prev.departure_time_seconds + yard_travel
            yard_depart = yard_arrival + _DUMP_YARD_SERVICE_S
            new_stops.append(RouteStop(
                node_id=yard.node_id,
                node_type="dump_yard",
                arrival_time_seconds=yard_arrival,
                departure_time_seconds=yard_depart,
                fill_collected_liters=0.0,
                cumulative_load_liters=0.0,
            ))
            extra_dist += yard_dist
            cumulative = 0.0
            dump_visits += 1

        cumulative = cumulative + stop.fill_collected_liters if stop.node_type == "bin" else cumulative
        new_stops.append(RouteStop(
            node_id=stop.node_id,
            node_type=stop.node_type,
            arrival_time_seconds=stop.arrival_time_seconds,
            departure_time_seconds=stop.departure_time_seconds,
            fill_collected_liters=stop.fill_collected_liters,
            cumulative_load_liters=cumulative,
        ))

    return new_stops, extra_dist, dump_visits


def _stop_coords(stop: RouteStop, vrp: VRPInput) -> tuple[float, float]:
    if stop.node_type == "depot":
        return vrp.depot.lat, vrp.depot.lng
    for b in vrp.bins:
        if b.node_id == stop.node_id:
            return b.lat, b.lng
    for y in vrp.dump_yards:
        if y.node_id == stop.node_id:
            return y.lat, y.lng
    return vrp.depot.lat, vrp.depot.lng
