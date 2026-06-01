"""Pydantic v2 schema validation tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ingestion.schemas import BinState, TelemetryPacket


def valid_packet_data() -> dict:
    return {
        "bin_id": "BIN-0001",
        "timestamp": datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc),
        "fill_pct": 67.4,
        "fill_liters": 80.9,
        "tipped": False,
        "sensor_fault": False,
        "battery_mv": 3720,
        "rssi_dbm": -89,
        "temp_c": 34.1,
        "event_type": "scheduled",
    }


def valid_state_data() -> dict:
    return {
        "bin_id": "BIN-0001",
        "last_updated": datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc),
        "fill_pct": 67.4,
        "fill_liters": 80.9,
        "status": "operational",
        "battery_mv": 3720,
        "consecutive_fault_ticks": 0,
        "flagged_for_collection": False,
        "last_emptied": None,
    }


# ── TelemetryPacket ───────────────────────────────────────────────────────────

def test_valid_packet_passes():
    p = TelemetryPacket(**valid_packet_data())
    assert p.bin_id == "BIN-0001"


def test_fill_pct_above_100_raises():
    data = valid_packet_data()
    data["fill_pct"] = 100.1
    with pytest.raises(ValidationError):
        TelemetryPacket(**data)


def test_fill_pct_below_0_raises():
    data = valid_packet_data()
    data["fill_pct"] = -0.1
    with pytest.raises(ValidationError):
        TelemetryPacket(**data)


def test_fill_pct_exactly_0_passes():
    data = valid_packet_data()
    data["fill_pct"] = 0.0
    TelemetryPacket(**data)


def test_fill_pct_exactly_100_passes():
    data = valid_packet_data()
    data["fill_pct"] = 100.0
    TelemetryPacket(**data)


def test_missing_bin_id_raises():
    data = valid_packet_data()
    del data["bin_id"]
    with pytest.raises(ValidationError):
        TelemetryPacket(**data)


def test_missing_timestamp_raises():
    data = valid_packet_data()
    del data["timestamp"]
    with pytest.raises(ValidationError):
        TelemetryPacket(**data)


def test_invalid_event_type_raises():
    data = valid_packet_data()
    data["event_type"] = "unknown_event"
    with pytest.raises(ValidationError):
        TelemetryPacket(**data)


def test_all_valid_event_types_pass():
    for et in ["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]:
        data = valid_packet_data()
        data["event_type"] = et
        p = TelemetryPacket(**data)
        assert p.event_type == et


# ── BinState ──────────────────────────────────────────────────────────────────

def test_valid_state_passes():
    s = BinState(**valid_state_data())
    assert s.bin_id == "BIN-0001"


def test_invalid_status_raises():
    data = valid_state_data()
    data["status"] = "on_fire"
    with pytest.raises(ValidationError):
        BinState(**data)


def test_all_valid_statuses_pass():
    for st in ["operational", "tipped", "sensor_fault", "low_battery",
               "overflow_risk", "pending_collection", "emptied"]:
        data = valid_state_data()
        data["status"] = st
        s = BinState(**data)
        assert s.status == st


def test_last_emptied_optional():
    data = valid_state_data()
    data["last_emptied"] = None
    s = BinState(**data)
    assert s.last_emptied is None
