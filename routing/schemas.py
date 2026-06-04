"""Pydantic models for the VRP routing layer."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RouteNode(BaseModel):
    node_id: str
    lat: float
    lng: float
    node_type: Literal["bin", "dump_yard", "depot"]
    capacity_liters: Optional[int] = None
    fill_pct: Optional[float] = None
    fill_liters: Optional[float] = None
    priority_level: int = 1
    hours_until_critical: Optional[float] = None
    service_time_seconds: int = 300
    road_access: str = "standard"  # "standard" | "narrow_alley"

    @model_validator(mode="after")
    def _enforce_service_time(self) -> "RouteNode":
        if self.node_type != "bin":
            self.service_time_seconds = 0
        return self


class Truck(BaseModel):
    truck_id: str
    capacity_liters: int
    depot_lat: float
    depot_lng: float
    shift_start_seconds: int = 0
    shift_end_seconds: int = 28800  # 8 hours
    can_access_narrow: bool = True

    @field_validator("shift_end_seconds")
    @classmethod
    def _validate_shift(cls, v: int, info) -> int:
        start = info.data.get("shift_start_seconds", 0)
        if v < start:
            raise ValueError(
                f"shift_end_seconds ({v}) must be >= shift_start_seconds ({start})"
            )
        return v


class RouteStop(BaseModel):
    node_id: str
    node_type: Literal["bin", "dump_yard", "depot"]
    arrival_time_seconds: int
    departure_time_seconds: int
    fill_collected_liters: float = 0.0
    cumulative_load_liters: float = 0.0
    sequence: int = 0


class OptimizedRoute(BaseModel):
    route_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    truck_id: str
    stops: list[RouteStop]
    total_distance_m: float
    total_duration_seconds: int
    total_load_liters: float
    dump_yard_visits: int = 0


class VRPInput(BaseModel):
    bins: list[RouteNode]
    trucks: list[Truck]
    depot: RouteNode
    dump_yards: list[RouteNode] = Field(default_factory=list)
    traffic_delay_factor: float = 1.0
    max_solve_seconds: int = 30


class VRPSolution(BaseModel):
    solved_at: datetime
    solver: Literal["ortools", "simulated_annealing", "greedy_fallback"]
    routes: list[OptimizedRoute]
    unserved_bins: list[str]
    total_distance_m: float
    total_duration_seconds: int
    solve_time_ms: float
    status: Literal["optimal", "feasible", "infeasible", "timeout"]
    objective_value: Optional[float] = None
