"""Database seeder for geospatial registry — zones, sectors, bins, dump yards."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from loguru import logger

from geospatial.db import GeospatialDB
from geospatial.schemas import BinRegistryEntry, DumpYard, Sector, Zone

_BINS_PATH = Path(__file__).parent.parent / "config" / "bins.json"

# Priority and truck assignments per zone type
_PRIORITY: dict[str, int] = {
    "commercial": 2,
    "transit_hub": 2,
    "residential": 1,
    "park": 1,
}

_TRUCKS: dict[str, int] = {
    "commercial": 3,
    "transit_hub": 3,
    "residential": 2,
    "park": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_zone_bbox(bins: list[dict]) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) for the given bin dicts."""
    lats = [b["lat"] for b in bins]
    lngs = [b["lng"] for b in bins]
    return min(lats), max(lats), min(lngs), max(lngs)


def _zone_id(zone_type: str) -> str:
    """Convert zone_type string to canonical zone_id."""
    return "Z-" + zone_type.upper().replace("_", "-")


def _zone_name(zone_type: str) -> str:
    """Return human-readable zone name (title-case words + ' Zone')."""
    words = zone_type.replace("_", " ").title()
    return f"{words} Zone"


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

async def seed_zones(db: GeospatialDB) -> dict[str, Zone]:
    """Seed zone records derived from bins.json.

    Returns a dict mapping zone_type -> Zone.
    """
    bins: list[dict] = json.loads(_BINS_PATH.read_text(encoding="utf-8"))

    # Group bins by zone type
    by_zone: dict[str, list[dict]] = defaultdict(list)
    for b in bins:
        by_zone[b["zone"]].append(b)

    zones: dict[str, Zone] = {}
    for zone_type, zone_bins in by_zone.items():
        min_lat, max_lat, min_lng, max_lng = _compute_zone_bbox(zone_bins)
        zone = Zone(
            zone_id=_zone_id(zone_type),
            name=_zone_name(zone_type),
            zone_type=zone_type,
            priority_level=_PRIORITY.get(zone_type, 1),
            assigned_trucks=_TRUCKS.get(zone_type, 2),
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=min_lng,
            max_lng=max_lng,
        )
        await db.upsert_zone(zone)
        zones[zone_type] = zone
        logger.debug(f"Seeded zone {zone.zone_id!r} ({len(zone_bins)} bins)")

    logger.info(f"seed_zones: {len(zones)} zones upserted")
    return zones


async def seed_sectors(
    db: GeospatialDB, zones: dict[str, Zone]
) -> dict[str, Sector]:
    """Create a 2×2 grid of sectors for each zone (16 sectors total).

    Returns a dict mapping sector_id -> Sector.
    """
    sectors: dict[str, Sector] = {}

    for zone_type, zone in zones.items():
        assert zone.min_lat is not None and zone.max_lat is not None
        assert zone.min_lng is not None and zone.max_lng is not None

        mid_lat = (zone.min_lat + zone.max_lat) / 2
        mid_lng = (zone.min_lng + zone.max_lng) / 2

        # Grid: (row, col) → (lat_lo, lat_hi, lng_lo, lng_hi)
        grid = {
            (0, 0): (zone.min_lat, mid_lat, zone.min_lng, mid_lng),  # bottom-left
            (0, 1): (zone.min_lat, mid_lat, mid_lng, zone.max_lng),  # bottom-right
            (1, 0): (mid_lat, zone.max_lat, zone.min_lng, mid_lng),  # top-left
            (1, 1): (mid_lat, zone.max_lat, mid_lng, zone.max_lng),  # top-right
        }

        for (row, col), (lat_lo, lat_hi, lng_lo, lng_hi) in grid.items():
            sector_id = f"{zone.zone_id}-S{row}{col}"
            sector = Sector(
                sector_id=sector_id,
                zone_id=zone.zone_id,
                name=f"{zone.name} Sector {row}{col}",
                bin_count=0,
                min_lat=lat_lo,
                max_lat=lat_hi,
                min_lng=lng_lo,
                max_lng=lng_hi,
            )
            await db.upsert_sector(sector)
            sectors[sector_id] = sector

    logger.info(f"seed_sectors: {len(sectors)} sectors upserted")
    return sectors


async def seed_bins(
    db: GeospatialDB,
    zones: dict[str, Zone],
    sectors: dict[str, Sector],
) -> int:
    """Seed bin registry entries from bins.json.

    Assigns each bin to a sector based on bbox containment, then updates
    sector bin_counts.  Returns the count of bins seeded.
    """
    bins: list[dict] = json.loads(_BINS_PATH.read_text(encoding="utf-8"))

    # Pre-build a lookup: zone_type -> list[Sector] for fast filtering
    zone_sectors: dict[str, list[Sector]] = defaultdict(list)
    for sector in sectors.values():
        # Map zone_id back to zone_type
        for zt, z in zones.items():
            if z.zone_id == sector.zone_id:
                zone_sectors[zt].append(sector)
                break

    # Track how many bins each sector gets
    sector_counts: dict[str, int] = defaultdict(int)

    count = 0
    for b in bins:
        zone_type: str = b["zone"]
        zone = zones[zone_type]
        zone_id = zone.zone_id
        lat: float = b["lat"]
        lng: float = b["lng"]

        # Find containing sector
        sector_id: str | None = None
        for sector in zone_sectors.get(zone_type, []):
            assert sector.min_lat is not None
            assert sector.max_lat is not None
            assert sector.min_lng is not None
            assert sector.max_lng is not None
            if (
                sector.min_lat <= lat <= sector.max_lat
                and sector.min_lng <= lng <= sector.max_lng
            ):
                sector_id = sector.sector_id
                break

        # Fallback to S00 of the zone
        if sector_id is None:
            sector_id = f"{zone_id}-S00"

        entry = BinRegistryEntry(
            bin_id=b["bin_id"],
            lat=lat,
            lng=lng,
            zone_type=zone_type,
            zone_id=zone_id,
            sector_id=sector_id,
            capacity_liters=int(b["capacity_liters"]),
            priority_level=1,
            is_active=True,
            road_access="standard",
        )
        await db.upsert_bin(entry)
        sector_counts[sector_id] += 1
        count += 1

    # Update sector bin_counts
    for sector_id, bin_count in sector_counts.items():
        sector = sectors.get(sector_id)
        if sector is None:
            continue
        await db.upsert_sector(sector.model_copy(update={"bin_count": bin_count}))

    logger.info(f"seed_bins: {count} bins upserted")
    return count


async def seed_dump_yards(db: GeospatialDB) -> None:
    """Upsert the three fixed dump yards."""
    yards = [
        DumpYard(
            yard_id="YARD-001",
            name="Al Quoz Waste Management",
            lat=25.1451,
            lng=55.2311,
            capacity_tons=5000,
            operating_hours="06:00-22:00",
            is_active=True,
        ),
        DumpYard(
            yard_id="YARD-002",
            name="Jebel Ali Disposal Facility",
            lat=25.0050,
            lng=55.1200,
            capacity_tons=8000,
            operating_hours="00:00-24:00",
            is_active=True,
        ),
        DumpYard(
            yard_id="YARD-003",
            name="Al Muhaisnah Transfer Station",
            lat=25.2933,
            lng=55.3611,
            capacity_tons=3000,
            operating_hours="06:00-20:00",
            is_active=True,
        ),
    ]
    for yard in yards:
        await db.upsert_dump_yard(yard)
    logger.info("seed_dump_yards: 3 dump yards upserted")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_seed(db: GeospatialDB) -> None:
    """Orchestrate all seed steps in order.

    Idempotent — safe to call multiple times thanks to ON CONFLICT DO UPDATE.
    The caller owns the db lifecycle (connect/close).
    """
    zones = await seed_zones(db)
    sectors = await seed_sectors(db, zones)
    count = await seed_bins(db, zones, sectors)
    await seed_dump_yards(db)
    logger.info(f"Seeded: {len(zones)} zones, {len(sectors)} sectors, {count} bins, 3 dump yards")
