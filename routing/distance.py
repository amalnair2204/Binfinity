"""Distance and time matrix utilities for the routing layer."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from routing.schemas import RouteNode

if TYPE_CHECKING:
    from routing.schemas import Truck

_EARTH_R_M = 6_371_000.0
_TRUCK_SPEED_MS = 40_000 / 3600  # 40 km/h in m/s
_BIG_INT = 100_000_000  # unreachable sentinel for incompatible nodes


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(math.sqrt(a))


def travel_time_seconds(dist_m: float, traffic_factor: float = 1.0) -> int:
    """Travel time in whole seconds at average truck speed, scaled by traffic_factor."""
    return int((dist_m / _TRUCK_SPEED_MS) * traffic_factor)


def build_distance_matrix_m(nodes: list[RouteNode]) -> list[list[float]]:
    """n×n matrix of haversine distances in metres."""
    n = len(nodes)
    return [
        [haversine_m(nodes[i].lat, nodes[i].lng, nodes[j].lat, nodes[j].lng) for j in range(n)]
        for i in range(n)
    ]


def build_time_matrix(nodes: list[RouteNode], traffic_factor: float = 1.0) -> list[list[int]]:
    """n×n travel-time matrix in seconds (no service time)."""
    n = len(nodes)
    dist = build_distance_matrix_m(nodes)
    return [
        [travel_time_seconds(dist[i][j], traffic_factor) for j in range(n)]
        for i in range(n)
    ]


def build_time_matrix_for_truck(
    nodes: list[RouteNode],
    truck: "Truck",
    traffic_factor: float = 1.0,
) -> list[list[int]]:
    """n×n travel-time matrix with narrow-alley bins blocked for incapable trucks.

    Narrow alley columns get _BIG_INT when truck.can_access_narrow is False,
    making those nodes effectively unreachable in OR-Tools or greedy selection.
    """
    matrix = build_time_matrix(nodes, traffic_factor)
    if truck.can_access_narrow:
        return matrix
    n = len(nodes)
    result = [row[:] for row in matrix]
    for j, node in enumerate(nodes):
        if node.road_access == "narrow_alley":
            for i in range(n):
                result[i][j] = _BIG_INT
    return result


def get_service_times(nodes: list[RouteNode]) -> list[int]:
    """Return per-node service time in seconds.

    Bins use their configured service_time_seconds; depot and dump yards return 0
    (enforced by the RouteNode model validator).
    """
    return [n.service_time_seconds for n in nodes]
