"""
State machine for bin state transitions.
Pure function — no I/O. All domain logic lives here.
"""
from __future__ import annotations

from ingestion.schemas import BinState, TelemetryPacket

FILL_THRESHOLD_CRITICAL = 85.0
FILL_THRESHOLD_WARNING = 70.0
BATTERY_CRITICAL_MV = 3200


def transition(
    current: BinState,
    packet: TelemetryPacket,
) -> tuple[BinState, bool]:
    """
    Apply one telemetry packet to the current bin state.

    Returns (new_state, is_spill_event).
    is_spill_event is True when a tip-over fires (caller must log spill_incident).
    """
    new = current.model_copy(deep=True)
    new.last_updated = packet.timestamp
    new.fill_pct = packet.fill_pct
    new.fill_liters = packet.fill_liters
    new.battery_mv = packet.battery_mv

    # ── Rule 1: Sensor blockage counter ──────────────────────────────────────
    if packet.fill_pct == 100.0:
        new.consecutive_fault_ticks += 1
    else:
        new.consecutive_fault_ticks = 0

    # ── Rule 4: Tip-over (highest priority, early return) ────────────────────
    if packet.tipped:
        new.fill_pct = 0.0
        new.fill_liters = 0.0
        new.flagged_for_collection = False
        new.status = "tipped"
        return new, True

    # ── Rule 3: Emptied event (early return to operational) ───────────────────
    if packet.event_type == "emptied":
        new.fill_pct = 0.0
        new.fill_liters = 0.0
        new.flagged_for_collection = False
        new.last_emptied = packet.timestamp
        new.status = "operational"
        return new, False

    # ── Rule 3: Collection flagging ───────────────────────────────────────────
    # Only flag if not faulted (consecutive_fault_ticks < 2 means no confirmed fault)
    if new.fill_pct >= FILL_THRESHOLD_CRITICAL and new.consecutive_fault_ticks < 2:
        new.flagged_for_collection = True

    # ── Status priority: sensor_fault > tipped > low_battery
    #                    > pending_collection > overflow_risk > operational ────
    if new.consecutive_fault_ticks >= 2:
        new.status = "sensor_fault"
    elif packet.battery_mv < BATTERY_CRITICAL_MV:
        new.status = "low_battery"
    elif new.fill_pct >= FILL_THRESHOLD_CRITICAL and new.flagged_for_collection:
        new.status = "pending_collection"
    elif new.fill_pct >= FILL_THRESHOLD_WARNING:
        new.status = "overflow_risk"
    else:
        new.status = "operational"

    return new, False
