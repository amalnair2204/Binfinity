from __future__ import annotations
import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from pydantic import BaseModel

if TYPE_CHECKING:
    from emulator.bin_model import BinNode

class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_pct: float
    fill_liters: float
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int
    temp_c: float
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]

def build_packet(bin_node: BinNode, sim_dt: datetime, event_type: str) -> TelemetryPacket:
    ts = sim_dt if sim_dt.tzinfo else sim_dt.replace(tzinfo=timezone.utc)
    # NOTE: rssi_dbm and temp_c use fixed stub values here; Task 4 will replace
    # with realistic random sampling. Using fixed values avoids interference with
    # tests that mock random.randint / random.uniform for bin_model logic.
    return TelemetryPacket(
        bin_id=bin_node.bin_id,
        timestamp=ts,
        fill_pct=round(bin_node.current_fill_pct, 2),
        fill_liters=round(bin_node.current_fill_pct / 100.0 * bin_node.capacity_liters, 2),
        tipped=bin_node.tipped,
        sensor_fault=bin_node.sensor_fault,
        battery_mv=bin_node.battery_mv,
        rssi_dbm=-85,
        temp_c=30.0,
        event_type=event_type,  # type: ignore[arg-type]
    )
