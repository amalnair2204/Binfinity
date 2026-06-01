"""Pydantic v2 models for telemetry ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_pct: float = Field(ge=0.0, le=100.0)
    fill_liters: float
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int
    temp_c: float
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]


class BinState(BaseModel):
    bin_id: str
    last_updated: datetime
    fill_pct: float
    fill_liters: float
    status: Literal[
        "operational",
        "tipped",
        "sensor_fault",
        "low_battery",
        "overflow_risk",
        "pending_collection",
        "emptied",
    ]
    battery_mv: int
    consecutive_fault_ticks: int = 0
    flagged_for_collection: bool = False
    last_emptied: Optional[datetime] = None
