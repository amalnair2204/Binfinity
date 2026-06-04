"""Unit tests for geospatial/seeder.py — fully mocked, no live DB."""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from geospatial.db import GeospatialDB
from geospatial.seeder import (
    run_seed,
    seed_bins,
    seed_dump_yards,
    seed_sectors,
    seed_zones,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = AsyncMock(spec=GeospatialDB)
    db.upsert_zone = AsyncMock(return_value=None)
    db.upsert_sector = AsyncMock(return_value=None)
    db.upsert_bin = AsyncMock(return_value=None)
    db.upsert_dump_yard = AsyncMock(return_value=None)
    return db


# ---------------------------------------------------------------------------
# seed_zones tests
# ---------------------------------------------------------------------------

async def test_seed_zones_creates_4_zones(mock_db):
    zones = await seed_zones(mock_db)
    assert mock_db.upsert_zone.call_count == 4
    assert len(zones) == 4


async def test_seed_zones_zone_ids(mock_db):
    zones = await seed_zones(mock_db)
    zone_ids = {z.zone_id for z in zones.values()}
    assert zone_ids == {"Z-COMMERCIAL", "Z-RESIDENTIAL", "Z-PARK", "Z-TRANSIT-HUB"}


async def test_seed_zones_priority(mock_db):
    zones = await seed_zones(mock_db)
    commercial = zones["commercial"]
    assert commercial.priority_level == 2

    transit = zones["transit_hub"]
    assert transit.priority_level == 2

    residential = zones["residential"]
    assert residential.priority_level == 1

    park = zones["park"]
    assert park.priority_level == 1


async def test_seed_zones_returns_zone_objects(mock_db):
    from geospatial.schemas import Zone
    zones = await seed_zones(mock_db)
    for zone in zones.values():
        assert isinstance(zone, Zone)
        assert zone.min_lat is not None
        assert zone.max_lat is not None
        assert zone.min_lng is not None
        assert zone.max_lng is not None


async def test_seed_zones_truck_assignments(mock_db):
    zones = await seed_zones(mock_db)
    assert zones["commercial"].assigned_trucks == 3
    assert zones["transit_hub"].assigned_trucks == 3
    assert zones["residential"].assigned_trucks == 2
    assert zones["park"].assigned_trucks == 1


# ---------------------------------------------------------------------------
# seed_sectors tests
# ---------------------------------------------------------------------------

async def test_seed_sectors_creates_16_sectors(mock_db):
    zones = await seed_zones(mock_db)
    mock_db.upsert_sector.reset_mock()
    sectors = await seed_sectors(mock_db, zones)
    assert mock_db.upsert_sector.call_count == 16
    assert len(sectors) == 16


async def test_seed_sectors_naming(mock_db):
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    # Z-COMMERCIAL should have 4 sectors: S00, S01, S10, S11
    commercial_ids = {sid for sid in sectors if sid.startswith("Z-COMMERCIAL-S")}
    assert commercial_ids == {
        "Z-COMMERCIAL-S00",
        "Z-COMMERCIAL-S01",
        "Z-COMMERCIAL-S10",
        "Z-COMMERCIAL-S11",
    }


async def test_seed_sectors_all_zones_covered(mock_db):
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    # Each zone (4) should have exactly 4 sectors
    for zone in zones.values():
        zone_sectors = [sid for sid in sectors if sid.startswith(zone.zone_id)]
        assert len(zone_sectors) == 4, f"Zone {zone.zone_id} expected 4 sectors, got {len(zone_sectors)}"


async def test_seed_sectors_return_sector_objects(mock_db):
    from geospatial.schemas import Sector
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    for sector in sectors.values():
        assert isinstance(sector, Sector)
        assert sector.zone_id is not None


# ---------------------------------------------------------------------------
# seed_bins tests
# ---------------------------------------------------------------------------

async def test_seed_bins_upserts_200(mock_db):
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    mock_db.upsert_bin.reset_mock()
    # seed_bins also calls upsert_sector to update bin_counts, so reset that too
    mock_db.upsert_sector.reset_mock()
    count = await seed_bins(mock_db, zones, sectors)
    assert count == 200
    assert mock_db.upsert_bin.call_count == 200


async def test_seed_bins_returns_count(mock_db):
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    count = await seed_bins(mock_db, zones, sectors)
    assert isinstance(count, int)
    assert count > 0


async def test_seed_bins_all_bins_have_zone(mock_db):
    from geospatial.schemas import BinRegistryEntry
    zones = await seed_zones(mock_db)
    sectors = await seed_sectors(mock_db, zones)
    await seed_bins(mock_db, zones, sectors)
    # Each call to upsert_bin should be given a BinRegistryEntry with a zone_id
    for upsert_call in mock_db.upsert_bin.call_args_list:
        entry = upsert_call.args[0]
        assert isinstance(entry, BinRegistryEntry)
        assert entry.zone_id is not None


# ---------------------------------------------------------------------------
# seed_dump_yards tests
# ---------------------------------------------------------------------------

async def test_seed_dump_yards(mock_db):
    await seed_dump_yards(mock_db)
    assert mock_db.upsert_dump_yard.call_count == 3


async def test_seed_dump_yards_yard_ids(mock_db):
    await seed_dump_yards(mock_db)
    called_ids = [c.args[0].yard_id for c in mock_db.upsert_dump_yard.call_args_list]
    assert set(called_ids) == {"YARD-001", "YARD-002", "YARD-003"}


async def test_seed_dump_yards_all_active(mock_db):
    await seed_dump_yards(mock_db)
    for c in mock_db.upsert_dump_yard.call_args_list:
        yard = c.args[0]
        assert yard.is_active is True


async def test_seed_dump_yards_have_coordinates(mock_db):
    await seed_dump_yards(mock_db)
    for c in mock_db.upsert_dump_yard.call_args_list:
        yard = c.args[0]
        assert yard.lat is not None
        assert yard.lng is not None


# ---------------------------------------------------------------------------
# run_seed tests
# ---------------------------------------------------------------------------

async def test_run_seed_calls_all(mock_db):
    await run_seed(mock_db)
    assert mock_db.upsert_zone.called
    assert mock_db.upsert_sector.called
    assert mock_db.upsert_bin.called
    assert mock_db.upsert_dump_yard.called


async def test_run_seed_upserts_4_zones(mock_db):
    await run_seed(mock_db)
    assert mock_db.upsert_zone.call_count == 4


async def test_run_seed_upserts_16_sectors(mock_db):
    await run_seed(mock_db)
    # seed_sectors calls upsert_sector 16 times,
    # seed_bins may call upsert_sector additional times to update bin_count
    # We just check at least 16 sector upserts happened
    assert mock_db.upsert_sector.call_count >= 16


async def test_run_seed_upserts_200_bins(mock_db):
    await run_seed(mock_db)
    assert mock_db.upsert_bin.call_count == 200


async def test_run_seed_upserts_3_dump_yards(mock_db):
    await run_seed(mock_db)
    assert mock_db.upsert_dump_yard.call_count == 3
