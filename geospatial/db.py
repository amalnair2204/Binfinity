"""AsyncPg-backed geospatial registry database layer."""
from __future__ import annotations

import math
from pathlib import Path

import asyncpg
from loguru import logger

from geospatial.schemas import BinRegistryEntry, DumpYard, Sector, Zone


# ---------------------------------------------------------------------------
# Haversine distance helper
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_UPSERT_ZONE = """
INSERT INTO zones
    (zone_id, name, zone_type, priority_level, assigned_trucks,
     min_lat, max_lat, min_lng, max_lng)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (zone_id) DO UPDATE SET
    name            = EXCLUDED.name,
    zone_type       = EXCLUDED.zone_type,
    priority_level  = EXCLUDED.priority_level,
    assigned_trucks = EXCLUDED.assigned_trucks,
    min_lat         = EXCLUDED.min_lat,
    max_lat         = EXCLUDED.max_lat,
    min_lng         = EXCLUDED.min_lng,
    max_lng         = EXCLUDED.max_lng
"""

_UPSERT_SECTOR = """
INSERT INTO sectors
    (sector_id, zone_id, name, bin_count, min_lat, max_lat, min_lng, max_lng)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (sector_id) DO UPDATE SET
    zone_id   = EXCLUDED.zone_id,
    name      = EXCLUDED.name,
    bin_count = EXCLUDED.bin_count,
    min_lat   = EXCLUDED.min_lat,
    max_lat   = EXCLUDED.max_lat,
    min_lng   = EXCLUDED.min_lng,
    max_lng   = EXCLUDED.max_lng
"""

_UPSERT_BIN = """
INSERT INTO bin_registry
    (bin_id, lat, lng, zone_type, zone_id, sector_id,
     capacity_liters, priority_level, is_active, road_access)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (bin_id) DO UPDATE SET
    lat             = EXCLUDED.lat,
    lng             = EXCLUDED.lng,
    zone_type       = EXCLUDED.zone_type,
    zone_id         = EXCLUDED.zone_id,
    sector_id       = EXCLUDED.sector_id,
    capacity_liters = EXCLUDED.capacity_liters,
    priority_level  = EXCLUDED.priority_level,
    is_active       = EXCLUDED.is_active,
    road_access     = EXCLUDED.road_access
"""

_UPSERT_DUMP_YARD = """
INSERT INTO dump_yards
    (yard_id, name, lat, lng, capacity_tons, operating_hours, is_active)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (yard_id) DO UPDATE SET
    name            = EXCLUDED.name,
    lat             = EXCLUDED.lat,
    lng             = EXCLUDED.lng,
    capacity_tons   = EXCLUDED.capacity_tons,
    operating_hours = EXCLUDED.operating_hours,
    is_active       = EXCLUDED.is_active
"""


# ---------------------------------------------------------------------------
# GeospatialDB
# ---------------------------------------------------------------------------

class GeospatialDB:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        logger.info("GeospatialDB pool ready")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            logger.info("GeospatialDB pool closed")

    async def init_schema(self) -> None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        sql_path = Path(__file__).parent / "migrations" / "001_geospatial.sql"
        sql = sql_path.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        logger.info("Geospatial schema initialised")

    # ------------------------------------------------------------------
    # Zone methods
    # ------------------------------------------------------------------

    async def upsert_zone(self, zone: Zone) -> None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_ZONE,
                zone.zone_id,
                zone.name,
                zone.zone_type,
                zone.priority_level,
                zone.assigned_trucks,
                zone.min_lat,
                zone.max_lat,
                zone.min_lng,
                zone.max_lng,
            )
        logger.debug(f"Upserted zone {zone.zone_id!r}")

    async def list_zones(self) -> list[Zone]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM zones")
        return [Zone(**dict(r)) for r in rows]

    async def get_zone(self, zone_id: str) -> Zone | None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM zones WHERE zone_id = $1", zone_id)
        if row is None:
            return None
        return Zone(**dict(row))

    # ------------------------------------------------------------------
    # Sector methods
    # ------------------------------------------------------------------

    async def upsert_sector(self, sector: Sector) -> None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_SECTOR,
                sector.sector_id,
                sector.zone_id,
                sector.name,
                sector.bin_count,
                sector.min_lat,
                sector.max_lat,
                sector.min_lng,
                sector.max_lng,
            )
        logger.debug(f"Upserted sector {sector.sector_id!r}")

    async def list_sectors(self) -> list[Sector]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM sectors")
        return [Sector(**dict(r)) for r in rows]

    async def get_sector(self, sector_id: str) -> Sector | None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sectors WHERE sector_id = $1", sector_id
            )
        if row is None:
            return None
        return Sector(**dict(row))

    # ------------------------------------------------------------------
    # Bin registry methods
    # ------------------------------------------------------------------

    async def upsert_bin(self, entry: BinRegistryEntry) -> None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_BIN,
                entry.bin_id,
                entry.lat,
                entry.lng,
                entry.zone_type,
                entry.zone_id,
                entry.sector_id,
                entry.capacity_liters,
                entry.priority_level,
                entry.is_active,
                entry.road_access,
            )
        logger.debug(f"Upserted bin {entry.bin_id!r}")

    async def get_bin(self, bin_id: str) -> BinRegistryEntry | None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bin_registry WHERE bin_id = $1", bin_id
            )
        if row is None:
            return None
        return BinRegistryEntry(**dict(row))

    async def list_bins(self) -> list[BinRegistryEntry]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM bin_registry")
        return [BinRegistryEntry(**dict(r)) for r in rows]

    async def bins_by_zone(self, zone_id: str) -> list[BinRegistryEntry]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bin_registry WHERE zone_id = $1", zone_id
            )
        return [BinRegistryEntry(**dict(r)) for r in rows]

    async def bins_by_sector(self, sector_id: str) -> list[BinRegistryEntry]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bin_registry WHERE sector_id = $1", sector_id
            )
        return [BinRegistryEntry(**dict(r)) for r in rows]

    async def nearest_bins(
        self, lat: float, lng: float, limit: int = 10
    ) -> list[BinRegistryEntry]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bin_registry WHERE is_active = TRUE"
            )
        entries: list[tuple[float, BinRegistryEntry]] = []
        for r in rows:
            entry = BinRegistryEntry(**dict(r))
            dist = haversine_km(lat, lng, entry.lat, entry.lng)
            entries.append((dist, entry))
        entries.sort(key=lambda t: t[0])
        result = []
        for dist, entry in entries[:limit]:
            entry.distance_km = dist
            result.append(entry)
        return result

    async def bins_within(
        self, lat: float, lng: float, radius_m: float
    ) -> list[BinRegistryEntry]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bin_registry WHERE is_active = TRUE"
            )
        entries: list[tuple[float, BinRegistryEntry]] = []
        for r in rows:
            entry = BinRegistryEntry(**dict(r))
            dist_km = haversine_km(lat, lng, entry.lat, entry.lng)
            if dist_km * 1000 <= radius_m:
                entries.append((dist_km, entry))
        entries.sort(key=lambda t: t[0])
        result = []
        for dist, entry in entries:
            entry.distance_km = dist
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Dump yard methods
    # ------------------------------------------------------------------

    async def upsert_dump_yard(self, yard: DumpYard) -> None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            await conn.execute(
                _UPSERT_DUMP_YARD,
                yard.yard_id,
                yard.name,
                yard.lat,
                yard.lng,
                yard.capacity_tons,
                yard.operating_hours,
                yard.is_active,
            )
        logger.debug(f"Upserted dump yard {yard.yard_id!r}")

    async def list_dump_yards(self) -> list[DumpYard]:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM dump_yards")
        return [DumpYard(**dict(r)) for r in rows]

    async def nearest_dump_yard(self, lat: float, lng: float) -> DumpYard | None:
        if self._pool is None:
            raise RuntimeError("Not connected — call connect() first")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM dump_yards WHERE is_active = TRUE"
            )
        if not rows:
            return None
        best_dist: float | None = None
        best_yard: DumpYard | None = None
        for r in rows:
            yard = DumpYard(**dict(r))
            dist = haversine_km(lat, lng, yard.lat, yard.lng)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_yard = yard
        if best_yard is not None:
            best_yard.distance_km = best_dist
        return best_yard
