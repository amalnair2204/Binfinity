"""Simulated Annealing metaheuristic solver for CVRPTW."""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from routing.distance import haversine_m, travel_time_seconds
from routing.schemas import OptimizedRoute, RouteNode, RouteStop, Truck, VRPInput, VRPSolution

_SERVICE_TIME_S = 300
_DUMP_YARD_SERVICE_S = 600
_DUMP_YARD_TRIGGER = 0.85

# SA cost weights (same as OR-Tools objective)
_W_DIST = 0.4
_W_DUR = 0.3
_W_URGENCY = 0.3


class SimulatedAnnealingSolver:
    def __init__(
        self,
        initial_temp: float = 1000.0,
        cooling_rate: float = 0.995,
        min_temp: float = 1.0,
        max_iterations: int = 50_000,
    ) -> None:
        self.initial_temp = initial_temp
        self.cooling_rate = cooling_rate
        self.min_temp = min_temp
        self.max_iterations = max_iterations

    def solve(self, vrp_input: VRPInput) -> VRPSolution:
        t0 = time.monotonic()

        from routing.solver_greedy import solve_greedy

        greedy_sol = solve_greedy(vrp_input)
        bin_map = {b.node_id: b for b in vrp_input.bins}

        # Internal state: list[list[bin_id]] — one list per truck
        state = _solution_to_state(greedy_sol, vrp_input)
        best_state = [r[:] for r in state]

        current_cost = _cost(state, vrp_input, bin_map)
        best_cost = current_cost

        temp = self.initial_temp

        log_interval = max(1, self.max_iterations // 10)

        for iteration in range(self.max_iterations):
            if temp < self.min_temp:
                break

            if iteration % log_interval == 0:
                logger.debug(
                    "SA iter={} cost={:.1f} temp={:.2f} best={:.1f}",
                    iteration, current_cost, temp, best_cost,
                )

            new_state = _apply_move(state, vrp_input)
            if new_state is None:
                temp *= self.cooling_rate
                continue

            if not _is_feasible(new_state, vrp_input, bin_map):
                temp *= self.cooling_rate
                continue

            new_cost = _cost(new_state, vrp_input, bin_map)
            delta = new_cost - current_cost

            if delta < 0 or random.random() < math.exp(-delta / temp):
                state = new_state
                current_cost = new_cost
                if current_cost < best_cost:
                    best_cost = current_cost
                    best_state = [r[:] for r in state]

            temp *= self.cooling_rate

        solve_ms = (time.monotonic() - t0) * 1000
        return _state_to_solution(best_state, vrp_input, bin_map, solve_ms)


# ---------------------------------------------------------------------------
# State ↔ solution conversions
# ---------------------------------------------------------------------------

def _solution_to_state(sol: VRPSolution, vrp: VRPInput) -> list[list[str]]:
    """Extract per-truck bin sequences from a VRPSolution."""
    truck_order = {t.truck_id: i for i, t in enumerate(vrp.trucks)}
    state: list[list[str]] = [[] for _ in vrp.trucks]
    for route in sol.routes:
        idx = truck_order.get(route.truck_id)
        if idx is not None:
            state[idx] = [s.node_id for s in route.stops if s.node_type == "bin"]
    return state


def _state_to_solution(
    state: list[list[str]],
    vrp: VRPInput,
    bin_map: dict[str, RouteNode],
    solve_ms: float,
) -> VRPSolution:
    routes: list[OptimizedRoute] = []
    served: set[str] = set()

    for truck_idx, bin_ids in enumerate(state):
        if not bin_ids:
            continue
        truck = vrp.trucks[truck_idx]
        stops, dist, final_time, dump_visits, load = _build_route_stops(
            bin_ids, truck, vrp, bin_map
        )
        for bid in bin_ids:
            served.add(bid)
        routes.append(OptimizedRoute(
            truck_id=truck.truck_id,
            stops=stops,
            total_distance_m=dist,
            total_duration_seconds=max(0, final_time - truck.shift_start_seconds),
            total_load_liters=load,
            dump_yard_visits=dump_visits,
        ))

    unserved = [b.node_id for b in vrp.bins if b.node_id not in served]
    total_dist = sum(r.total_distance_m for r in routes)
    total_dur = max((r.total_duration_seconds for r in routes), default=0)

    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="simulated_annealing",
        routes=routes,
        unserved_bins=unserved,
        total_distance_m=total_dist,
        total_duration_seconds=total_dur,
        solve_time_ms=solve_ms,
        status="feasible" if routes else "infeasible",
        objective_value=_cost(state, vrp, bin_map),
    )


def _build_route_stops(
    bin_ids: list[str],
    truck: Truck,
    vrp: VRPInput,
    bin_map: dict[str, RouteNode],
) -> tuple[list[RouteStop], float, int, int, float]:
    """Build stop sequence for a truck, inserting dump yard visits at trigger threshold."""
    stops: list[RouteStop] = []
    cur_lat, cur_lng = truck.depot_lat, truck.depot_lng
    cur_time = truck.shift_start_seconds
    cumulative = 0.0
    total_dist = 0.0
    dump_visits = 0
    trigger = truck.capacity_liters * _DUMP_YARD_TRIGGER

    stops.append(RouteStop(
        node_id=vrp.depot.node_id,
        node_type="depot",
        arrival_time_seconds=cur_time,
        departure_time_seconds=cur_time,
        fill_collected_liters=0.0,
        cumulative_load_liters=0.0,
    ))

    for bid in bin_ids:
        # Insert dump yard if at trigger threshold
        if vrp.dump_yards and cumulative >= trigger:
            best_yard = min(vrp.dump_yards, key=lambda y: haversine_m(cur_lat, cur_lng, y.lat, y.lng))
            yard_dist = haversine_m(cur_lat, cur_lng, best_yard.lat, best_yard.lng)
            yard_travel = travel_time_seconds(yard_dist, vrp.traffic_delay_factor)
            yard_arr = cur_time + yard_travel
            yard_dep = yard_arr + _DUMP_YARD_SERVICE_S
            stops.append(RouteStop(
                node_id=best_yard.node_id,
                node_type="dump_yard",
                arrival_time_seconds=yard_arr,
                departure_time_seconds=yard_dep,
                fill_collected_liters=0.0,
                cumulative_load_liters=0.0,
            ))
            total_dist += yard_dist
            cur_time = yard_dep
            cur_lat, cur_lng = best_yard.lat, best_yard.lng
            cumulative = 0.0
            dump_visits += 1

        node = bin_map[bid]
        dist = haversine_m(cur_lat, cur_lng, node.lat, node.lng)
        travel_t = travel_time_seconds(dist, vrp.traffic_delay_factor)
        arrival = cur_time + travel_t
        departure = arrival + _SERVICE_TIME_S
        fill = node.fill_liters or 0.0
        cumulative += fill
        total_dist += dist
        cur_time = departure
        cur_lat, cur_lng = node.lat, node.lng

        stops.append(RouteStop(
            node_id=bid,
            node_type="bin",
            arrival_time_seconds=arrival,
            departure_time_seconds=departure,
            fill_collected_liters=fill,
            cumulative_load_liters=cumulative,
        ))

    depot_dist = haversine_m(cur_lat, cur_lng, truck.depot_lat, truck.depot_lng)
    total_dist += depot_dist
    final_time = cur_time + travel_time_seconds(depot_dist, vrp.traffic_delay_factor)

    stops.append(RouteStop(
        node_id=vrp.depot.node_id,
        node_type="depot",
        arrival_time_seconds=final_time,
        departure_time_seconds=final_time,
        fill_collected_liters=0.0,
        cumulative_load_liters=cumulative,
    ))

    return stops, total_dist, final_time, dump_visits, cumulative


# ---------------------------------------------------------------------------
# Cost and feasibility
# ---------------------------------------------------------------------------

def _route_metrics(
    bin_ids: list[str],
    truck: Truck,
    vrp: VRPInput,
    bin_map: dict[str, RouteNode],
) -> tuple[float, int]:
    if not bin_ids:
        return 0.0, 0
    dist = 0.0
    t = truck.shift_start_seconds
    cur_lat, cur_lng = truck.depot_lat, truck.depot_lng
    for bid in bin_ids:
        node = bin_map[bid]
        d = haversine_m(cur_lat, cur_lng, node.lat, node.lng)
        dist += d
        t += travel_time_seconds(d, vrp.traffic_delay_factor) + _SERVICE_TIME_S
        cur_lat, cur_lng = node.lat, node.lng
    d = haversine_m(cur_lat, cur_lng, truck.depot_lat, truck.depot_lng)
    dist += d
    t += travel_time_seconds(d, vrp.traffic_delay_factor)
    return dist, max(0, t - truck.shift_start_seconds)


def _cost(
    state: list[list[str]],
    vrp: VRPInput,
    bin_map: dict[str, RouteNode],
) -> float:
    total_dist = 0.0
    total_duration = 0
    served: set[str] = set()

    for truck_idx, bin_ids in enumerate(state):
        for bid in bin_ids:
            served.add(bid)
        truck = vrp.trucks[truck_idx]
        dist, dur = _route_metrics(bin_ids, truck, vrp, bin_map)
        total_dist += dist
        total_duration = max(total_duration, dur)

    urgency_penalty = sum(
        (bin_map[b.node_id].hours_until_critical or 24.0) * 3600
        for b in vrp.bins
        if b.node_id not in served
    )

    return _W_DIST * total_dist + _W_DUR * total_duration + _W_URGENCY * urgency_penalty


def _is_feasible(
    state: list[list[str]],
    vrp: VRPInput,
    bin_map: dict[str, RouteNode],
) -> bool:
    for truck_idx, bin_ids in enumerate(state):
        if not bin_ids:
            continue
        truck = vrp.trucks[truck_idx]
        trigger = truck.capacity_liters * _DUMP_YARD_TRIGGER

        # Capacity: check segment-by-segment, resetting at dump yard trigger threshold
        seg_load = 0.0
        for bid in bin_ids:
            fill = bin_map[bid].fill_liters or 0.0
            if vrp.dump_yards and seg_load >= trigger:
                seg_load = 0.0
            seg_load += fill
            if seg_load > truck.capacity_liters:
                return False

        # Shift time
        _, dur = _route_metrics(bin_ids, truck, vrp, bin_map)
        if truck.shift_start_seconds + dur > truck.shift_end_seconds:
            return False

    return True


# ---------------------------------------------------------------------------
# Neighborhood operators
# ---------------------------------------------------------------------------

def _apply_move(
    state: list[list[str]],
    vrp: VRPInput,
) -> Optional[list[list[str]]]:
    op = random.randint(0, 3)
    new_state = [r[:] for r in state]

    if op == 0:
        # 2-opt: reverse a segment within a route
        eligible = [(i, r) for i, r in enumerate(new_state) if len(r) >= 2]
        if not eligible:
            return None
        i, route = random.choice(eligible)
        a, b = sorted(random.sample(range(len(route)), 2))
        new_state[i] = route[:a] + route[a:b + 1][::-1] + route[b + 1:]

    elif op == 1:
        # Or-opt: move 1-2 consecutive stops to another route
        eligible = [(i, r) for i, r in enumerate(new_state) if r]
        if not eligible:
            return None
        si, src = random.choice(eligible)
        k = min(random.randint(1, 2), len(src))
        idx = random.randint(0, len(src) - k)
        segs = src[idx:idx + k]
        others = [(j, r) for j, r in enumerate(new_state) if j != si]
        new_state[si] = src[:idx] + src[idx + k:]
        if others:
            di, dst = random.choice(others)
            ins = random.randint(0, len(dst))
            new_state[di] = dst[:ins] + segs + dst[ins:]
        else:
            # Only one route — reinsert at a different position
            ins = random.randint(0, len(new_state[si]))
            new_state[si] = new_state[si][:ins] + segs + new_state[si][ins:]

    elif op == 2:
        # Relocate: move a single stop to a random position in any route
        eligible = [(i, r) for i, r in enumerate(new_state) if r]
        if not eligible:
            return None
        si, src = random.choice(eligible)
        idx = random.randint(0, len(src) - 1)
        seg = src[idx]
        new_state[si] = src[:idx] + src[idx + 1:]
        di = random.randint(0, len(new_state) - 1)
        ins = random.randint(0, len(new_state[di]))
        new_state[di] = new_state[di][:ins] + [seg] + new_state[di][ins:]

    else:
        # Swap: exchange stops between two different routes
        eligible = [(i, r) for i, r in enumerate(new_state) if r]
        if len(eligible) < 2:
            return None
        (si, sr), (di, dr) = random.sample(eligible, 2)
        a = random.randint(0, len(sr) - 1)
        b = random.randint(0, len(dr) - 1)
        new_state[si] = sr[:a] + [dr[b]] + sr[a + 1:]
        new_state[di] = dr[:b] + [sr[a]] + dr[b + 1:]

    return new_state
