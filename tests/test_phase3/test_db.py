"""Integration tests for GeospatialDB against live PostgreSQL."""
from __future__ import annotations

import pytest
import pytest_asyncio

from geospatial.db import GeospatialDB, haversine_km
from geospatial.schemas import BinRegistryEntry, DumpYard, Sector, Zone

DSN = "postgresql://postgres:binfinity@localhost:5432/binfinity"

# All async tests in this module share the same event loop (module scope)
# so they can share the module-scoped db fixture.
pytestmark = pytest.mark.asyncio(loop_scope="module")


# ---------------------------------------------------------------------------
# Module-scoped DB fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db():
    geo_db = GeospatialDB(DSN)
    await geo_db.connect()
    await geo_db.init_schema()
    yield geo_db
    # Cleanup: remove test data (tables remain)
    async with geo_db._pool.acquire() as conn:
        await conn.execute("DELETE FROM bin_registry")
        await conn.execute("DELETE FROM sectors")
        await conn.execute("DELETE FROM zones")
        await conn.execute("DELETE FROM dump_yards")
    await geo_db.close()


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_zone(zone_id: str = "Z-TEST", zone_type: str = "test", **kwargs) -> Zone:
    defaults = dict(
        zone_id=zone_id,
        name=f"Test Zone {zone_id}",
        zone_type=zone_type,
        priority_level=1,
        assigned_trucks=2,
        min_lat=25.0,
        max_lat=25.5,
        min_lng=55.0,
        max_lng=55.5,
    )
    defaults.update(kwargs)
    return Zone(**defaults)


def make_sector(sector_id: str, zone_id: str, **kwargs) -> Sector:
    defaults = dict(
        sector_id=sector_id,
        zone_id=zone_id,
        name=f"Sector {sector_id}",
        bin_count=0,
        min_lat=25.0,
        max_lat=25.25,
        min_lng=55.0,
        max_lng=55.25,
    )
    defaults.update(kwargs)
    return Sector(**defaults)


def make_bin(bin_id: str, lat: float, lng: float, zone_id: str, sector_id: str, **kwargs) -> BinRegistryEntry:
    defaults = dict(
        bin_id=bin_id,
        lat=lat,
        lng=lng,
        zone_type="test",
        zone_id=zone_id,
        sector_id=sector_id,
        capacity_liters=240,
        priority_level=1,
        is_active=True,
        road_access="standard",
    )
    defaults.update(kwargs)
    return BinRegistryEntry(**defaults)


def make_dump_yard(yard_id: str, lat: float, lng: float, **kwargs) -> DumpYard:
    defaults = dict(
        yard_id=yard_id,
        name=f"Yard {yard_id}",
        lat=lat,
        lng=lng,
        capacity_tons=1000,
        operating_hours="06:00-22:00",
        is_active=True,
    )
    defaults.update(kwargs)
    return DumpYard(**defaults)


# ---------------------------------------------------------------------------
# Zone tests
# ---------------------------------------------------------------------------

async def test_upsert_and_get_zone(db):
    zone = make_zone(zone_id="Z-ALPHA", zone_type="commercial", priority_level=2)
    await db.upsert_zone(zone)
    result = await db.get_zone("Z-ALPHA")
    assert result is not None
    assert result.zone_id == "Z-ALPHA"
    assert result.zone_type == "commercial"
    assert result.priority_level == 2
    assert result.min_lat == 25.0
    assert result.max_lng == 55.5


async def test_list_zones(db):
    await db.upsert_zone(make_zone(zone_id="Z-BETA", zone_type="residential"))
    await db.upsert_zone(make_zone(zone_id="Z-GAMMA", zone_type="park"))
    zones = await db.list_zones()
    zone_ids = {z.zone_id for z in zones}
    assert "Z-BETA" in zone_ids
    assert "Z-GAMMA" in zone_ids


async def test_get_zone_not_found(db):
    result = await db.get_zone("Z-DOES-NOT-EXIST")
    assert result is None


# ---------------------------------------------------------------------------
# Sector tests
# ---------------------------------------------------------------------------

async def test_upsert_and_get_sector(db):
    await db.upsert_zone(make_zone(zone_id="Z-SECTOR-TEST", zone_type="test"))
    sector = make_sector("Z-SECTOR-TEST-S00", "Z-SECTOR-TEST")
    await db.upsert_sector(sector)
    result = await db.get_sector("Z-SECTOR-TEST-S00")
    assert result is not None
    assert result.sector_id == "Z-SECTOR-TEST-S00"
    assert result.zone_id == "Z-SECTOR-TEST"


async def test_get_sector_not_found(db):
    result = await db.get_sector("Z-NONEXISTENT-S99")
    assert result is None


# ---------------------------------------------------------------------------
# Bin tests
# ---------------------------------------------------------------------------

async def test_upsert_and_get_bin(db):
    await db.upsert_zone(make_zone(zone_id="Z-BIN-TEST", zone_type="test"))
    await db.upsert_sector(make_sector("Z-BIN-TEST-S00", "Z-BIN-TEST"))
    entry = make_bin("BIN-T001", 25.1, 55.1, "Z-BIN-TEST", "Z-BIN-TEST-S00", capacity_liters=360)
    await db.upsert_bin(entry)
    result = await db.get_bin("BIN-T001")
    assert result is not None
    assert result.bin_id == "BIN-T001"
    assert result.lat == 25.1
    assert result.lng == 55.1
    assert result.capacity_liters == 360


async def test_get_bin_not_found(db):
    result = await db.get_bin("BIN-NONEXISTENT")
    assert result is None


async def test_list_bins(db):
    await db.upsert_zone(make_zone(zone_id="Z-LIST-TEST", zone_type="test"))
    await db.upsert_sector(make_sector("Z-LIST-TEST-S00", "Z-LIST-TEST"))
    await db.upsert_bin(make_bin("BIN-L001", 25.2, 55.2, "Z-LIST-TEST", "Z-LIST-TEST-S00"))
    await db.upsert_bin(make_bin("BIN-L002", 25.3, 55.3, "Z-LIST-TEST", "Z-LIST-TEST-S00"))
    bins = await db.list_bins()
    bin_ids = {b.bin_id for b in bins}
    assert "BIN-L001" in bin_ids
    assert "BIN-L002" in bin_ids


async def test_bins_by_zone(db):
    await db.upsert_zone(make_zone(zone_id="Z-ZONE-FILTER", zone_type="test"))
    await db.upsert_zone(make_zone(zone_id="Z-OTHER-ZONE", zone_type="test"))
    await db.upsert_sector(make_sector("Z-ZONE-FILTER-S00", "Z-ZONE-FILTER"))
    await db.upsert_bin(make_bin("BIN-ZF001", 25.1, 55.1, "Z-ZONE-FILTER", "Z-ZONE-FILTER-S00"))
    await db.upsert_bin(make_bin("BIN-ZF002", 25.2, 55.2, "Z-ZONE-FILTER", "Z-ZONE-FILTER-S00"))
    # No bins in Z-OTHER-ZONE
    zone_bins = await db.bins_by_zone("Z-ZONE-FILTER")
    bin_ids = {b.bin_id for b in zone_bins}
    assert "BIN-ZF001" in bin_ids
    assert "BIN-ZF002" in bin_ids
    # Other zone should have none from this zone
    other_bins = await db.bins_by_zone("Z-OTHER-ZONE")
    other_ids = {b.bin_id for b in other_bins}
    assert "BIN-ZF001" not in other_ids


async def test_bins_by_sector(db):
    await db.upsert_zone(make_zone(zone_id="Z-SEC-FILTER", zone_type="test"))
    await db.upsert_sector(make_sector("Z-SEC-FILTER-S00", "Z-SEC-FILTER"))
    await db.upsert_sector(make_sector("Z-SEC-FILTER-S01", "Z-SEC-FILTER"))
    await db.upsert_bin(make_bin("BIN-SF001", 25.1, 55.1, "Z-SEC-FILTER", "Z-SEC-FILTER-S00"))
    await db.upsert_bin(make_bin("BIN-SF002", 25.2, 55.2, "Z-SEC-FILTER", "Z-SEC-FILTER-S01"))
    s00_bins = await db.bins_by_sector("Z-SEC-FILTER-S00")
    s00_ids = {b.bin_id for b in s00_bins}
    assert "BIN-SF001" in s00_ids
    assert "BIN-SF002" not in s00_ids


# ---------------------------------------------------------------------------
# Nearest / within tests
# ---------------------------------------------------------------------------

async def test_nearest_bins(db):
    await db.upsert_zone(make_zone(zone_id="Z-NEAR-TEST", zone_type="test"))
    await db.upsert_sector(make_sector("Z-NEAR-TEST-S00", "Z-NEAR-TEST"))
    # 3 bins at increasing distances from (25.0, 55.0)
    # BIN-N001: closest (~0 km)
    # BIN-N002: ~11 km north
    # BIN-N003: ~22 km north
    await db.upsert_bin(make_bin("BIN-N001", 25.0, 55.0, "Z-NEAR-TEST", "Z-NEAR-TEST-S00"))
    await db.upsert_bin(make_bin("BIN-N002", 25.1, 55.0, "Z-NEAR-TEST", "Z-NEAR-TEST-S00"))
    await db.upsert_bin(make_bin("BIN-N003", 25.2, 55.0, "Z-NEAR-TEST", "Z-NEAR-TEST-S00"))

    results = await db.nearest_bins(25.0, 55.0, limit=3)
    assert len(results) >= 1
    # First should be closest (BIN-N001)
    assert results[0].bin_id == "BIN-N001"
    assert results[0].distance_km is not None
    assert results[0].distance_km < results[1].distance_km
    # All have distance set
    for r in results:
        assert r.distance_km is not None


async def test_nearest_bins_limit(db):
    results = await db.nearest_bins(25.0, 55.0, limit=2)
    assert len(results) <= 2


async def test_bins_within(db):
    await db.upsert_zone(make_zone(zone_id="Z-WITHIN-TEST", zone_type="test"))
    await db.upsert_sector(make_sector("Z-WITHIN-TEST-S00", "Z-WITHIN-TEST"))
    # BIN-W001 at origin — should be within 1000m
    # BIN-W002 ~11km away — should NOT be within 1000m
    await db.upsert_bin(make_bin("BIN-W001", 24.0, 54.0, "Z-WITHIN-TEST", "Z-WITHIN-TEST-S00"))
    await db.upsert_bin(make_bin("BIN-W002", 24.1, 54.0, "Z-WITHIN-TEST", "Z-WITHIN-TEST-S00"))

    results = await db.bins_within(24.0, 54.0, radius_m=1000)
    bin_ids = {b.bin_id for b in results}
    assert "BIN-W001" in bin_ids
    assert "BIN-W002" not in bin_ids
    # All results have distance_km set
    for b in results:
        assert b.distance_km is not None


# ---------------------------------------------------------------------------
# Dump yard tests
# ---------------------------------------------------------------------------

async def test_upsert_and_list_dump_yards(db):
    yard = make_dump_yard("YARD-T001", 25.1, 55.1)
    await db.upsert_dump_yard(yard)
    yards = await db.list_dump_yards()
    yard_ids = {y.yard_id for y in yards}
    assert "YARD-T001" in yard_ids


async def test_nearest_dump_yard(db):
    # Upsert two yards at different distances from (25.0, 55.0)
    await db.upsert_dump_yard(make_dump_yard("YARD-NEAR", 25.01, 55.01))  # ~1.5 km
    await db.upsert_dump_yard(make_dump_yard("YARD-FAR", 25.5, 55.5))    # ~70 km

    result = await db.nearest_dump_yard(25.0, 55.0)
    assert result is not None
    assert result.yard_id == "YARD-NEAR"
    assert result.distance_km is not None
    assert result.distance_km < 5.0  # must be close


async def test_nearest_dump_yard_none(db):
    """With no dump yards, nearest_dump_yard returns None."""
    async with db._pool.acquire() as conn:
        await conn.execute("DELETE FROM dump_yards")
    result = await db.nearest_dump_yard(25.0, 55.0)
    assert result is None


# ---------------------------------------------------------------------------
# Haversine function tests (sync — explicitly no asyncio mark)
# ---------------------------------------------------------------------------

def test_haversine_same_point():
    """Distance from a point to itself must be 0."""
    assert haversine_km(25.1, 55.2, 25.1, 55.2) == pytest.approx(0.0, abs=1e-9)


def test_haversine_dubai_to_london():
    """Dubai (25.2, 55.3) to London (51.5, -0.12) ~ 5500 km."""
    dist = haversine_km(25.2, 55.3, 51.5, -0.12)
    assert 5000 < dist < 6000


def test_haversine_small_distance():
    """Two points ~1.1 km apart should return ~1.1 km."""
    dist = haversine_km(25.0, 55.0, 25.01, 55.0)
    assert 1.0 < dist < 1.2


def test_haversine_symmetry():
    """haversine(A, B) == haversine(B, A)."""
    d1 = haversine_km(25.0, 55.0, 26.0, 56.0)
    d2 = haversine_km(26.0, 56.0, 25.0, 55.0)
    assert d1 == pytest.approx(d2)
