"""Tests for routing/input_builder.py — mock DB calls."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routing.input_builder import build_vrp_input
from routing.schemas import Truck
from tests.test_phase6.conftest import make_depot, make_truck


def _make_geo_db(bins=None, yards=None):
    geo = MagicMock()
    bins = bins or []
    yards = yards or []

    async def _get_bin(bin_id):
        return next((b for b in bins if b.bin_id == bin_id), None)

    async def _list_yards():
        return yards

    geo.get_bin = _get_bin
    geo.list_dump_yards = _list_yards
    return geo


def _make_bin_registry(bin_id: str, lat: float = 25.21, lng: float = 55.28,
                       capacity_liters: int = 240, priority_level: int = 2,
                       road_access: str = "standard"):
    entry = MagicMock()
    entry.bin_id = bin_id
    entry.lat = lat
    entry.lng = lng
    entry.capacity_liters = capacity_liters
    entry.priority_level = priority_level
    entry.road_access = road_access
    return entry


def _make_dump_yard(yard_id: str = "YARD1"):
    y = MagicMock()
    y.yard_id = yard_id
    y.lat = 25.19
    y.lng = 55.26
    y.is_active = True
    return y


def _make_ingestion_db():
    db = MagicMock()
    db._pool = MagicMock()
    return db


def _fake_bin_states(*rows):
    """Return rows as list of dicts, bypassing real DB."""
    return rows


@pytest.mark.asyncio
async def test_build_vrp_excludes_sensor_fault_bins():
    trucks = [make_truck()]
    registry = [_make_bin_registry("B001"), _make_bin_registry("B002")]
    geo = _make_geo_db(bins=registry, yards=[_make_dump_yard()])
    ingestion = _make_ingestion_db()

    states = [
        {"bin_id": "B001", "fill_pct": 90.0, "fill_liters": 216.0, "status": "operational"},
        {"bin_id": "B002", "fill_pct": 85.0, "fill_liters": 204.0, "status": "sensor_fault"},
    ]
    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=states)):
        result = await build_vrp_input(geo, ingestion, trucks)

    bin_ids = {b.node_id for b in result.bins}
    assert "B001" in bin_ids
    assert "B002" not in bin_ids


@pytest.mark.asyncio
async def test_build_vrp_excludes_tipped_bins():
    trucks = [make_truck()]
    registry = [_make_bin_registry("B001"), _make_bin_registry("B003")]
    geo = _make_geo_db(bins=registry, yards=[_make_dump_yard()])
    ingestion = _make_ingestion_db()

    states = [
        {"bin_id": "B001", "fill_pct": 92.0, "fill_liters": 220.0, "status": "operational"},
        {"bin_id": "B003", "fill_pct": 80.0, "fill_liters": 192.0, "status": "tipped"},
    ]
    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=states)):
        result = await build_vrp_input(geo, ingestion, trucks)

    bin_ids = {b.node_id for b in result.bins}
    assert "B001" in bin_ids
    assert "B003" not in bin_ids


@pytest.mark.asyncio
async def test_build_vrp_filters_by_window_hours():
    trucks = [make_truck()]
    registry = [_make_bin_registry("B001"), _make_bin_registry("B002")]
    geo = _make_geo_db(bins=registry, yards=[_make_dump_yard()])
    ingestion = _make_ingestion_db()

    # B001: 95% fill → ~0.5h critical; B002: 40% fill → ~12h
    states = [
        {"bin_id": "B001", "fill_pct": 95.0, "fill_liters": 228.0, "status": "operational"},
        {"bin_id": "B002", "fill_pct": 40.0, "fill_liters": 96.0,  "status": "operational"},
    ]
    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=states)):
        result = await build_vrp_input(geo, ingestion, trucks, window_hours=6.0)

    bin_ids = {b.node_id for b in result.bins}
    assert "B001" in bin_ids   # 0.5h <= 6h
    assert "B002" not in bin_ids  # 12h > 6h


@pytest.mark.asyncio
async def test_build_vrp_depot_always_present():
    trucks = [make_truck()]
    geo = _make_geo_db(bins=[], yards=[_make_dump_yard()])
    ingestion = _make_ingestion_db()

    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=[])):
        result = await build_vrp_input(geo, ingestion, trucks)

    assert result.depot is not None
    assert result.depot.node_type == "depot"


@pytest.mark.asyncio
async def test_build_vrp_dump_yard_included():
    trucks = [make_truck()]
    registry = [_make_bin_registry("B001")]
    geo = _make_geo_db(bins=registry, yards=[_make_dump_yard("YARD1")])
    ingestion = _make_ingestion_db()

    states = [{"bin_id": "B001", "fill_pct": 90.0, "fill_liters": 216.0, "status": "operational"}]
    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=states)):
        result = await build_vrp_input(geo, ingestion, trucks)

    assert len(result.dump_yards) >= 1
    assert result.dump_yards[0].node_type == "dump_yard"


@pytest.mark.asyncio
async def test_build_vrp_traffic_delay_factor_from_congestion():
    trucks = [make_truck()]
    registry = [_make_bin_registry("B001")]
    geo = _make_geo_db(bins=registry, yards=[_make_dump_yard()])
    ingestion = _make_ingestion_db()

    states = [{"bin_id": "B001", "fill_pct": 90.0, "fill_liters": 216.0, "status": "operational"}]
    with patch("routing.input_builder._get_flagged_bin_states", new=AsyncMock(return_value=states)):
        result = await build_vrp_input(geo, ingestion, trucks, zone_congestion_ratio=1.5)

    assert result.traffic_delay_factor == pytest.approx(1.5)
