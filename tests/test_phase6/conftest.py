"""Shared fixtures for Phase 6 tests."""
from __future__ import annotations

import pytest

from routing.schemas import RouteNode, Truck, VRPInput


def make_depot() -> RouteNode:
    return RouteNode(node_id="depot", lat=25.2048, lng=55.2708, node_type="depot")


def make_dump_yard(yard_id: str = "YARD1") -> RouteNode:
    return RouteNode(node_id=yard_id, lat=25.19, lng=55.26, node_type="dump_yard")


def make_bin(
    bin_id: str,
    lat: float = 25.21,
    lng: float = 55.28,
    fill_liters: float = 80.0,
    capacity_liters: int = 240,
    priority_level: int = 2,
    hours_until_critical: float = 8.0,
    road_access: str = "standard",
) -> RouteNode:
    return RouteNode(
        node_id=bin_id,
        lat=lat,
        lng=lng,
        node_type="bin",
        fill_liters=fill_liters,
        capacity_liters=capacity_liters,
        priority_level=priority_level,
        hours_until_critical=hours_until_critical,
        road_access=road_access,
    )


def make_truck(
    truck_id: str = "T1",
    capacity_liters: int = 800,
    can_access_narrow: bool = True,
    shift_end_seconds: int = 28800,
) -> Truck:
    return Truck(
        truck_id=truck_id,
        capacity_liters=capacity_liters,
        depot_lat=25.2048,
        depot_lng=55.2708,
        shift_end_seconds=shift_end_seconds,
        can_access_narrow=can_access_narrow,
    )


def make_vrp(
    n_bins: int = 5,
    n_trucks: int = 1,
    capacity_liters: int = 1000,
) -> VRPInput:
    depot = make_depot()
    bins = [
        make_bin(
            f"B{i:03}",
            lat=25.2048 + i * 0.005,
            lng=55.2708 + i * 0.003,
            fill_liters=80.0,
            hours_until_critical=float(6 + i % 4),
        )
        for i in range(1, n_bins + 1)
    ]
    trucks = [
        make_truck(f"T{j}", capacity_liters=capacity_liters)
        for j in range(1, n_trucks + 1)
    ]
    dump = make_dump_yard()
    return VRPInput(bins=bins, trucks=trucks, depot=depot, dump_yards=[dump])
