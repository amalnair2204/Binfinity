"""BinNode — stateful IoT bin simulator. Pure state machine, no I/O."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emulator.telemetry import TelemetryPacket

FILL_THRESHOLD_CRITICAL: float = 85.0
FILL_THRESHOLD_WARNING: float = 70.0
BATTERY_CRITICAL_MV: int = 3200
WAKE_INTERVAL_MINUTES: int = 30
WAKE_INTERVAL_LOW_BAT_MINUTES: int = 60


def _tod_multiplier(hour: float) -> float:
    """Time-of-day fill rate multiplier based on simulated hour."""
    if 6.0 <= hour < 9.0:
        return 2.0
    if 17.0 <= hour < 20.0:
        return 1.8
    if 0.0 <= hour < 5.0:
        return 0.3
    return 1.0


def _zone_multiplier(zone: str, hour: float, weekday: int) -> float:
    """Zone-specific fill rate multiplier. weekday: 0=Mon … 6=Sun."""
    is_weekend = weekday >= 5
    if zone == "park":
        return 2.5 if is_weekend else 0.8
    if zone == "transit_hub":
        return 2.0 if (7.0 <= hour < 9.0 or 17.0 <= hour < 19.0) else 1.0
    if zone == "commercial":
        return 1.2 if 9.0 <= hour < 18.0 else 1.0
    return 1.0


@dataclass
class BinNode:
    bin_id: str
    lat: float
    lng: float
    zone: str
    base_fill_rate: float
    capacity_liters: float
    current_fill_pct: float
    battery_mv: int = 4200
    marked_for_collection: bool = False
    sensor_fault: bool = False
    tipped: bool = False
    _fault_ticks_remaining: int = field(default=0, repr=False)

    @property
    def wake_interval_minutes(self) -> int:
        return (
            WAKE_INTERVAL_LOW_BAT_MINUTES
            if self.battery_mv < BATTERY_CRITICAL_MV
            else WAKE_INTERVAL_MINUTES
        )

    def tick(self, sim_dt: datetime) -> list[TelemetryPacket]:
        """
        Advance bin one 30-minute simulated tick.
        Returns list of TelemetryPacket — normally 1, immediately 1 on tip-over.
        """
        from emulator.telemetry import build_packet

        hour = sim_dt.hour + sim_dt.minute / 60.0
        weekday = sim_dt.weekday()

        # Battery drain (always, before any event rolls)
        self.battery_mv = max(0, self.battery_mv - random.randint(3, 7))

        # ── Tip-over event (0.5%) ─────────────────────────────────────────────
        if random.random() < 0.005:
            self.tipped = True
            self.current_fill_pct = 0.0
            self.marked_for_collection = False
            return [build_packet(self, sim_dt, "tip_alert")]

        # ── Sensor blockage (1%) — only tries if not already faulted ─────────
        if not self.sensor_fault and random.random() < 0.01:
            self._fault_ticks_remaining = random.randint(2, 4)
            self.sensor_fault = True

        if self.sensor_fault:
            self.current_fill_pct = 100.0
            packet = build_packet(self, sim_dt, "scheduled")
            self._fault_ticks_remaining -= 1
            if self._fault_ticks_remaining <= 0:
                self.sensor_fault = False
            return [packet]

        # ── Volatile spike (2%) ───────────────────────────────────────────────
        if random.random() < 0.02:
            spike = random.uniform(30.0, 70.0)
            self.current_fill_pct = min(100.0, self.current_fill_pct + spike)
            if self.current_fill_pct >= FILL_THRESHOLD_CRITICAL:
                self.marked_for_collection = True
            return [build_packet(self, sim_dt, "spike")]

        # ── Normal fill ───────────────────────────────────────────────────────
        delta = (
            self.base_fill_rate
            * _tod_multiplier(hour)
            * _zone_multiplier(self.zone, hour, weekday)
            + random.gauss(0.0, 1.5)
        )
        self.current_fill_pct = max(0.0, min(100.0, self.current_fill_pct + delta))

        if self.current_fill_pct >= FILL_THRESHOLD_CRITICAL:
            self.marked_for_collection = True

        event_type = "scheduled"
        if self.current_fill_pct >= FILL_THRESHOLD_WARNING:
            event_type = "overflow_warning"

        return [build_packet(self, sim_dt, event_type)]

    def apply_emptying(self, sim_dt: datetime) -> TelemetryPacket:
        """Simulate truck emptying this bin. Call when marked_for_collection and fill>=85."""
        from emulator.telemetry import build_packet

        self.current_fill_pct = 0.0
        self.marked_for_collection = False
        self.tipped = False
        return build_packet(self, sim_dt, "emptied")
