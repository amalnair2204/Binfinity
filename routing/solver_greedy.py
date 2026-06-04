"""Greedy nearest-neighbour CVRPTW fallback solver."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from routing.distance import haversine_m, travel_time_seconds
from routing.schemas import (
    OptimizedRoute,
    RouteNode,
    RouteStop,
    Truck,
    VRPInput,
    VRPSolution,
)

_DUMP_YARD_CAPACITY_TRIGGER = 0.85
_SERVICE_TIME_S = 300
_DUMP_YARD_SERVICE_S = 600


def solve_greedy(vrp: VRPInput) -> VRPSolution:
    t0 = time.monotonic()

    sorted_bins = sorted(
        vrp.bins,
        key=lambda b: (b.hours_until_critical if b.hours_until_critical is not None else 999.0, -b.priority_level),
    )

    unvisited: set[str] = {b.node_id for b in sorted_bins}
    routes: list[OptimizedRoute] = []

    for truck in vrp.trucks:
        if not unvisited:
            break

        stops: list[RouteStop] = []
        cur_lat, cur_lng = truck.depot_lat, truck.depot_lng
        cur_time = truck.shift_start_seconds
        cur_load = 0.0
        total_dist = 0.0
        dump_visits = 0

        stops.append(RouteStop(
            node_id=vrp.depot.node_id,
            node_type="depot",
            arrival_time_seconds=cur_time,
            departure_time_seconds=cur_time,
            fill_collected_liters=0.0,
            cumulative_load_liters=0.0,
        ))

        while True:
            # Dump before next pick-up if load threshold reached
            if vrp.dump_yards and cur_load >= truck.capacity_liters * _DUMP_YARD_CAPACITY_TRIGGER:
                yard, yard_dist = _nearest_node(cur_lat, cur_lng, vrp.dump_yards)
                travel_t = travel_time_seconds(yard_dist, vrp.traffic_delay_factor)
                arrival = cur_time + travel_t
                departure = arrival + _DUMP_YARD_SERVICE_S
                if departure <= truck.shift_end_seconds:
                    total_dist += yard_dist
                    cur_time = departure
                    cur_lat, cur_lng = yard.lat, yard.lng
                    cur_load = 0.0
                    dump_visits += 1
                    stops.append(RouteStop(
                        node_id=yard.node_id,
                        node_type="dump_yard",
                        arrival_time_seconds=arrival,
                        departure_time_seconds=departure,
                        fill_collected_liters=0.0,
                        cumulative_load_liters=0.0,
                    ))

            best_bin: Optional[RouteNode] = None
            best_dist = float("inf")

            for bin_node in sorted_bins:
                if bin_node.node_id not in unvisited:
                    continue

                dist = haversine_m(cur_lat, cur_lng, bin_node.lat, bin_node.lng)
                travel_t = travel_time_seconds(dist, vrp.traffic_delay_factor)
                arrival = cur_time + travel_t
                departure = arrival + _SERVICE_TIME_S
                new_load = cur_load + (bin_node.fill_liters or 0.0)

                if new_load > truck.capacity_liters:
                    continue

                deadline = int((bin_node.hours_until_critical or 24.0) * 3600)
                if arrival > deadline:
                    continue

                # Ensure truck can return to depot after serving this bin
                ret_dist = haversine_m(bin_node.lat, bin_node.lng, truck.depot_lat, truck.depot_lng)
                ret_t = travel_time_seconds(ret_dist, vrp.traffic_delay_factor)
                if departure + ret_t > truck.shift_end_seconds:
                    continue

                if dist < best_dist:
                    best_dist = dist
                    best_bin = bin_node

            if best_bin is None:
                break

            dist = haversine_m(cur_lat, cur_lng, best_bin.lat, best_bin.lng)
            travel_t = travel_time_seconds(dist, vrp.traffic_delay_factor)
            arrival = cur_time + travel_t
            departure = arrival + _SERVICE_TIME_S
            fill = best_bin.fill_liters or 0.0
            cur_load += fill
            total_dist += dist
            cur_time = departure
            cur_lat, cur_lng = best_bin.lat, best_bin.lng
            unvisited.discard(best_bin.node_id)

            stops.append(RouteStop(
                node_id=best_bin.node_id,
                node_type="bin",
                arrival_time_seconds=arrival,
                departure_time_seconds=departure,
                fill_collected_liters=fill,
                cumulative_load_liters=cur_load,
            ))

        # Return to depot
        depot_dist = haversine_m(cur_lat, cur_lng, truck.depot_lat, truck.depot_lng)
        depot_travel = travel_time_seconds(depot_dist, vrp.traffic_delay_factor)
        total_dist += depot_dist
        final_time = cur_time + depot_travel

        stops.append(RouteStop(
            node_id=vrp.depot.node_id,
            node_type="depot",
            arrival_time_seconds=final_time,
            departure_time_seconds=final_time,
            fill_collected_liters=0.0,
            cumulative_load_liters=cur_load,
        ))

        if any(s.node_type == "bin" for s in stops):
            routes.append(OptimizedRoute(
                truck_id=truck.truck_id,
                stops=stops,
                total_distance_m=total_dist,
                total_duration_seconds=max(0, final_time - truck.shift_start_seconds),
                total_load_liters=cur_load,
                dump_yard_visits=dump_visits,
            ))

    solve_ms = (time.monotonic() - t0) * 1000
    total_dist_m = sum(r.total_distance_m for r in routes)
    total_duration = max((r.total_duration_seconds for r in routes), default=0)

    return VRPSolution(
        solved_at=datetime.now(tz=timezone.utc),
        solver="greedy_fallback",
        routes=routes,
        unserved_bins=list(unvisited),
        total_distance_m=total_dist_m,
        total_duration_seconds=total_duration,
        solve_time_ms=solve_ms,
        status="feasible" if routes else "infeasible",
        objective_value=total_dist_m,
    )


def _nearest_node(lat: float, lng: float, nodes: list[RouteNode]) -> tuple[RouteNode, float]:
    best = min(nodes, key=lambda n: haversine_m(lat, lng, n.lat, n.lng))
    return best, haversine_m(lat, lng, best.lat, best.lng)
