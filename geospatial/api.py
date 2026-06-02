"""Geospatial registry FastAPI server. Handles zones, sectors, bins, and dump yards."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from loguru import logger

from geospatial.db import GeospatialDB
from geospatial.schemas import (
    BinRegistryEntry,
    DumpYard,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    Sector,
    Zone,
)

app = FastAPI(title="Binfinity Geospatial API", version="1.0.0")

_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:binfinity@localhost:5432/binfinity",
)

geo_db: GeospatialDB | None = None


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global geo_db
    geo_db = GeospatialDB(_DATABASE_URL)
    await geo_db.connect()
    await geo_db.init_schema()
    from geospatial.seeder import run_seed
    await run_seed(geo_db)
    logger.info("Geospatial API ready on port 8002")


@app.on_event("shutdown")
async def shutdown():
    if geo_db:
        await geo_db.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_db() -> GeospatialDB:
    if geo_db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return geo_db


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    _get_db()
    return {"status": "ok", "tables": ["zones", "sectors", "bin_registry", "dump_yards"]}


# ---------------------------------------------------------------------------
# Bins
# ---------------------------------------------------------------------------

@app.get("/bins")
async def list_bins() -> list[BinRegistryEntry]:
    db = _get_db()
    return await db.list_bins()


# NOTE: /bins/nearest and /bins/within MUST be defined before /bins/{bin_id}

@app.get("/bins/nearest")
async def nearest_bins(
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[BinRegistryEntry]:
    db = _get_db()
    return await db.nearest_bins(lat, lng, limit)


@app.get("/bins/within")
async def bins_within(
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
    radius_m: float = Query(default=500.0, gt=0),
) -> list[BinRegistryEntry]:
    db = _get_db()
    return await db.bins_within(lat, lng, radius_m)


@app.get("/bins/{bin_id}")
async def get_bin(bin_id: str) -> BinRegistryEntry:
    db = _get_db()
    entry = await db.get_bin(bin_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Bin {bin_id!r} not found")
    return entry


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@app.get("/zones")
async def list_zones() -> list[Zone]:
    db = _get_db()
    return await db.list_zones()


@app.get("/zones/{zone_id}")
async def get_zone(zone_id: str) -> Zone:
    db = _get_db()
    zone = await db.get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone {zone_id!r} not found")
    return zone


@app.get("/zones/{zone_id}/bins")
async def bins_by_zone(zone_id: str) -> list[BinRegistryEntry]:
    db = _get_db()
    return await db.bins_by_zone(zone_id)


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------

@app.get("/sectors")
async def list_sectors() -> list[Sector]:
    db = _get_db()
    return await db.list_sectors()


@app.get("/sectors/{sector_id}")
async def get_sector(sector_id: str) -> Sector:
    db = _get_db()
    sector = await db.get_sector(sector_id)
    if sector is None:
        raise HTTPException(status_code=404, detail=f"Sector {sector_id!r} not found")
    return sector


@app.get("/sectors/{sector_id}/bins")
async def bins_by_sector(sector_id: str) -> list[BinRegistryEntry]:
    db = _get_db()
    return await db.bins_by_sector(sector_id)


# ---------------------------------------------------------------------------
# Dump yards
# ---------------------------------------------------------------------------

@app.get("/dump_yards")
async def list_dump_yards() -> list[DumpYard]:
    db = _get_db()
    return await db.list_dump_yards()


# NOTE: /dump_yards/nearest MUST be defined before any parameterised route

@app.get("/dump_yards/nearest")
async def nearest_dump_yard(
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
) -> DumpYard:
    db = _get_db()
    yard = await db.nearest_dump_yard(lat, lng)
    if yard is None:
        raise HTTPException(status_code=404, detail="No dump yards found")
    return yard


# ---------------------------------------------------------------------------
# GeoJSON exports
# ---------------------------------------------------------------------------

@app.get("/export/bins.geojson")
async def export_bins_geojson() -> GeoJSONFeatureCollection:
    db = _get_db()
    bins = await db.list_bins()
    features = [
        GeoJSONFeature(
            geometry={"type": "Point", "coordinates": [b.lng, b.lat]},
            properties={
                "bin_id": b.bin_id,
                "zone_id": b.zone_id,
                "sector_id": b.sector_id,
                "capacity_liters": b.capacity_liters,
                "is_active": b.is_active,
            },
        )
        for b in bins
    ]
    return GeoJSONFeatureCollection(features=features)


@app.get("/export/zones.geojson")
async def export_zones_geojson() -> GeoJSONFeatureCollection:
    db = _get_db()
    zones = await db.list_zones()
    features = []
    for zone in zones:
        if None in (zone.min_lat, zone.max_lat, zone.min_lng, zone.max_lng):
            continue
        ring = [
            [zone.min_lng, zone.min_lat],  # SW
            [zone.max_lng, zone.min_lat],  # SE
            [zone.max_lng, zone.max_lat],  # NE
            [zone.min_lng, zone.max_lat],  # NW
            [zone.min_lng, zone.min_lat],  # closed
        ]
        features.append(
            GeoJSONFeature(
                geometry={"type": "Polygon", "coordinates": [ring]},
                properties={
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "zone_type": zone.zone_type,
                },
            )
        )
    return GeoJSONFeatureCollection(features=features)


@app.get("/export/sectors.geojson")
async def export_sectors_geojson() -> GeoJSONFeatureCollection:
    db = _get_db()
    sectors = await db.list_sectors()
    features = []
    for sector in sectors:
        if None in (sector.min_lat, sector.max_lat, sector.min_lng, sector.max_lng):
            continue
        ring = [
            [sector.min_lng, sector.min_lat],  # SW
            [sector.max_lng, sector.min_lat],  # SE
            [sector.max_lng, sector.max_lat],  # NE
            [sector.min_lng, sector.max_lat],  # NW
            [sector.min_lng, sector.min_lat],  # closed
        ]
        features.append(
            GeoJSONFeature(
                geometry={"type": "Polygon", "coordinates": [ring]},
                properties={
                    "sector_id": sector.sector_id,
                    "name": sector.name,
                },
            )
        )
    return GeoJSONFeatureCollection(features=features)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="warning")
