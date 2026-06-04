"""FastAPI endpoint tests for geospatial API — fully mocked geo_db."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from geospatial.api import app
from geospatial.db import GeospatialDB
from geospatial.schemas import BinRegistryEntry, DumpYard, Sector, Zone


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_zone(zone_id: str = "Z-COMMERCIAL", zone_type: str = "commercial", **kwargs) -> Zone:
    defaults = dict(
        zone_id=zone_id,
        name="Commercial Zone",
        zone_type=zone_type,
        priority_level=2,
        assigned_trucks=3,
        min_lat=25.0,
        max_lat=25.5,
        min_lng=55.0,
        max_lng=55.5,
    )
    defaults.update(kwargs)
    return Zone(**defaults)


def make_sector(sector_id: str = "Z-COMMERCIAL-S00", zone_id: str = "Z-COMMERCIAL", **kwargs) -> Sector:
    defaults = dict(
        sector_id=sector_id,
        zone_id=zone_id,
        name="Test Sector",
        bin_count=10,
        min_lat=25.0,
        max_lat=25.25,
        min_lng=55.0,
        max_lng=55.25,
    )
    defaults.update(kwargs)
    return Sector(**defaults)


def make_bin(bin_id: str = "BIN-0001", lat: float = 25.1, lng: float = 55.2, **kwargs) -> BinRegistryEntry:
    defaults = dict(
        bin_id=bin_id,
        lat=lat,
        lng=lng,
        zone_type="commercial",
        zone_id="Z-COMMERCIAL",
        sector_id="Z-COMMERCIAL-S00",
        capacity_liters=240,
        priority_level=1,
        is_active=True,
        road_access="standard",
        distance_km=None,
    )
    defaults.update(kwargs)
    return BinRegistryEntry(**defaults)


def make_dump_yard(yard_id: str = "YARD-001", **kwargs) -> DumpYard:
    defaults = dict(
        yard_id=yard_id,
        name="Al Quoz Waste Management",
        lat=25.1451,
        lng=55.2311,
        capacity_tons=5000,
        operating_hours="06:00-22:00",
        is_active=True,
        distance_km=None,
    )
    defaults.update(kwargs)
    return DumpYard(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_geo_db(monkeypatch):
    mock = AsyncMock(spec=GeospatialDB)
    # Default return values that make sense for most tests
    mock.list_bins.return_value = [make_bin("BIN-0001"), make_bin("BIN-0002")]
    mock.get_bin.return_value = make_bin("BIN-0001")
    mock.nearest_bins.return_value = [make_bin("BIN-0001", distance_km=0.5)]
    mock.bins_within.return_value = [make_bin("BIN-0001", distance_km=0.1)]
    mock.bins_by_zone.return_value = [make_bin("BIN-0001")]
    mock.bins_by_sector.return_value = [make_bin("BIN-0001")]
    mock.list_zones.return_value = [make_zone("Z-COMMERCIAL"), make_zone("Z-RESIDENTIAL", zone_type="residential")]
    mock.get_zone.return_value = make_zone("Z-COMMERCIAL")
    mock.list_sectors.return_value = [make_sector("Z-COMMERCIAL-S00"), make_sector("Z-COMMERCIAL-S01")]
    mock.get_sector.return_value = make_sector("Z-COMMERCIAL-S00")
    mock.list_dump_yards.return_value = [make_dump_yard("YARD-001")]
    mock.nearest_dump_yard.return_value = make_dump_yard("YARD-001", distance_km=2.3)

    import geospatial.api as api_module
    monkeypatch.setattr(api_module, "geo_db", mock)
    return mock


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "tables" in data


# ---------------------------------------------------------------------------
# Bins
# ---------------------------------------------------------------------------

def test_list_bins(mock_geo_db):
    mock_geo_db.list_bins.return_value = [make_bin("BIN-0001"), make_bin("BIN-0002")]
    r = client.get("/bins")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["bin_id"] == "BIN-0001"


def test_get_bin_found(mock_geo_db):
    mock_geo_db.get_bin.return_value = make_bin("BIN-0001")
    r = client.get("/bins/BIN-0001")
    assert r.status_code == 200
    assert r.json()["bin_id"] == "BIN-0001"


def test_get_bin_not_found(mock_geo_db):
    mock_geo_db.get_bin.return_value = None
    r = client.get("/bins/BIN-9999")
    assert r.status_code == 404


def test_bins_nearest(mock_geo_db):
    mock_geo_db.nearest_bins.return_value = [make_bin("BIN-0001", distance_km=0.5)]
    r = client.get("/bins/nearest?lat=25.1&lng=55.2")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["bin_id"] == "BIN-0001"


def test_bins_nearest_invalid_lat():
    r = client.get("/bins/nearest?lat=200&lng=55.2")
    assert r.status_code == 422


def test_bins_nearest_invalid_lng():
    r = client.get("/bins/nearest?lat=25.1&lng=300")
    assert r.status_code == 422


def test_bins_nearest_with_limit(mock_geo_db):
    mock_geo_db.nearest_bins.return_value = []
    r = client.get("/bins/nearest?lat=25.1&lng=55.2&limit=5")
    assert r.status_code == 200


def test_bins_within(mock_geo_db):
    mock_geo_db.bins_within.return_value = [make_bin("BIN-0001", distance_km=0.1)]
    r = client.get("/bins/within?lat=25.1&lng=55.2")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1


def test_bins_within_invalid_radius():
    r = client.get("/bins/within?lat=25.1&lng=55.2&radius_m=0")
    assert r.status_code == 422


def test_bins_within_custom_radius(mock_geo_db):
    mock_geo_db.bins_within.return_value = []
    r = client.get("/bins/within?lat=25.1&lng=55.2&radius_m=1000")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

def test_list_zones(mock_geo_db):
    mock_geo_db.list_zones.return_value = [
        make_zone("Z-COMMERCIAL"),
        make_zone("Z-RESIDENTIAL", zone_type="residential"),
    ]
    r = client.get("/zones")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    zone_ids = {z["zone_id"] for z in data}
    assert "Z-COMMERCIAL" in zone_ids


def test_get_zone_found(mock_geo_db):
    mock_geo_db.get_zone.return_value = make_zone("Z-COMMERCIAL")
    r = client.get("/zones/Z-COMMERCIAL")
    assert r.status_code == 200
    assert r.json()["zone_id"] == "Z-COMMERCIAL"


def test_get_zone_not_found(mock_geo_db):
    mock_geo_db.get_zone.return_value = None
    r = client.get("/zones/Z-NONEXISTENT")
    assert r.status_code == 404


def test_get_zone_bins(mock_geo_db):
    mock_geo_db.bins_by_zone.return_value = [make_bin("BIN-0001"), make_bin("BIN-0002")]
    r = client.get("/zones/Z-COMMERCIAL/bins")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------

def test_list_sectors(mock_geo_db):
    mock_geo_db.list_sectors.return_value = [
        make_sector("Z-COMMERCIAL-S00"),
        make_sector("Z-COMMERCIAL-S01"),
    ]
    r = client.get("/sectors")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2


def test_get_sector_found(mock_geo_db):
    mock_geo_db.get_sector.return_value = make_sector("Z-COMMERCIAL-S00")
    r = client.get("/sectors/Z-COMMERCIAL-S00")
    assert r.status_code == 200
    assert r.json()["sector_id"] == "Z-COMMERCIAL-S00"


def test_get_sector_not_found(mock_geo_db):
    mock_geo_db.get_sector.return_value = None
    r = client.get("/sectors/Z-NONEXISTENT-S99")
    assert r.status_code == 404


def test_get_sector_bins(mock_geo_db):
    mock_geo_db.bins_by_sector.return_value = [make_bin("BIN-0001")]
    r = client.get("/sectors/Z-COMMERCIAL-S00/bins")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Dump yards
# ---------------------------------------------------------------------------

def test_list_dump_yards(mock_geo_db):
    mock_geo_db.list_dump_yards.return_value = [make_dump_yard("YARD-001")]
    r = client.get("/dump_yards")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["yard_id"] == "YARD-001"


def test_nearest_dump_yard_found(mock_geo_db):
    mock_geo_db.nearest_dump_yard.return_value = make_dump_yard("YARD-001", distance_km=2.3)
    r = client.get("/dump_yards/nearest?lat=25.1&lng=55.2")
    assert r.status_code == 200
    data = r.json()
    assert data["yard_id"] == "YARD-001"
    assert data["distance_km"] == pytest.approx(2.3)


def test_nearest_dump_yard_not_found(mock_geo_db):
    mock_geo_db.nearest_dump_yard.return_value = None
    r = client.get("/dump_yards/nearest?lat=25.1&lng=55.2")
    assert r.status_code == 404


def test_nearest_dump_yard_invalid_lat():
    r = client.get("/dump_yards/nearest?lat=100&lng=55.2")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GeoJSON exports
# ---------------------------------------------------------------------------

def test_export_bins_geojson(mock_geo_db):
    mock_geo_db.list_bins.return_value = [make_bin("BIN-0001", lat=25.1, lng=55.2)]
    r = client.get("/export/bins.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    assert len(data["features"]) == 1
    feat = data["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    assert feat["properties"]["bin_id"] == "BIN-0001"


def test_export_bins_geojson_empty(mock_geo_db):
    mock_geo_db.list_bins.return_value = []
    r = client.get("/export/bins.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []


def test_export_zones_geojson(mock_geo_db):
    mock_geo_db.list_zones.return_value = [make_zone("Z-COMMERCIAL")]
    r = client.get("/export/zones.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    feat = data["features"][0]
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["zone_id"] == "Z-COMMERCIAL"


def test_export_zones_geojson_skips_missing_bbox(mock_geo_db):
    """Zones with None bbox should be skipped."""
    zone_no_bbox = Zone(
        zone_id="Z-NOBBOX",
        name="No BBox Zone",
        zone_type="test",
        priority_level=1,
        assigned_trucks=1,
        min_lat=None, max_lat=None, min_lng=None, max_lng=None,
    )
    mock_geo_db.list_zones.return_value = [zone_no_bbox]
    r = client.get("/export/zones.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["features"] == []


def test_export_sectors_geojson(mock_geo_db):
    mock_geo_db.list_sectors.return_value = [make_sector("Z-COMMERCIAL-S00")]
    r = client.get("/export/sectors.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    feat = data["features"][0]
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["sector_id"] == "Z-COMMERCIAL-S00"


def test_export_sectors_geojson_skips_missing_bbox(mock_geo_db):
    """Sectors with None bbox should be skipped."""
    sector_no_bbox = Sector(
        sector_id="Z-NOBBOX-S00",
        zone_id="Z-NOBBOX",
        name="No BBox Sector",
        bin_count=0,
        min_lat=None, max_lat=None, min_lng=None, max_lng=None,
    )
    mock_geo_db.list_sectors.return_value = [sector_no_bbox]
    r = client.get("/export/sectors.geojson")
    assert r.status_code == 200
    data = r.json()
    assert data["features"] == []


# ---------------------------------------------------------------------------
# Edge cases / extra coverage
# ---------------------------------------------------------------------------

def test_health_when_db_none(monkeypatch):
    import geospatial.api as api_module
    monkeypatch.setattr(api_module, "geo_db", None)
    r = client.get("/health")
    assert r.status_code == 503


def test_list_bins_empty(mock_geo_db):
    mock_geo_db.list_bins.return_value = []
    r = client.get("/bins")
    assert r.status_code == 200
    assert r.json() == []


def test_list_zones_empty(mock_geo_db):
    mock_geo_db.list_zones.return_value = []
    r = client.get("/zones")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sectors_empty(mock_geo_db):
    mock_geo_db.list_sectors.return_value = []
    r = client.get("/sectors")
    assert r.status_code == 200
    assert r.json() == []


def test_list_dump_yards_empty(mock_geo_db):
    mock_geo_db.list_dump_yards.return_value = []
    r = client.get("/dump_yards")
    assert r.status_code == 200
    assert r.json() == []
