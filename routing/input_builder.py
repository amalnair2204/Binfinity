"""Build VRPInput from live ingestion and geospatial data."""
from __future__ import annotations

import os
from typing import Optional

from loguru import logger

from geospatial.db import GeospatialDB
from ingestion.db import IngestionDB
from routing.schemas import RouteNode, Truck, VRPInput

_DEPOT_LAT = float(os.getenv("CITY_LAT", "25.2048"))
_DEPOT_LNG = float(os.getenv("CITY_LNG", "55.2708"))

_HOURS_PER_PCT_ABOVE_50 = 0.2
_EXCLUDED_STATUSES = {"sensor_fault", "tipped"}


def _estimate_hours_until_critical(fill_pct: float) -> float:
    """Rough estimate when no ML prediction is available."""
    if fill_pct >= 95:
        return 0.5
    if fill_pct >= 80:
        return max(0.5, (100.0 - fill_pct) * _HOURS_PER_PCT_ABOVE_50)
    return max(2.0, (100.0 - fill_pct) * _HOURS_PER_PCT_ABOVE_50)


async def build_vrp_input(
    geo_db: GeospatialDB,
    ingestion_db: IngestionDB,
    trucks: list[Truck],
    depot: Optional[RouteNode] = None,
    zone_id: Optional[str] = None,
    window_hours: float = 24.0,
    hours_until_critical_map: Optional[dict[str, float]] = None,
    zone_congestion_ratio: float = 1.0,
    max_solve_seconds: int = 30,
) -> VRPInput:
    """Assemble a VRPInput from live DB state.

    Args:
        geo_db: geospatial registry (bin locations, dump yards)
        ingestion_db: live bin states (fill levels, flagged status)
        trucks: truck fleet for this dispatch run
        depot: starting node (defaults to env-configured depot)
        zone_id: filter to a specific zone; None = all zones
        window_hours: only include bins where hours_until_critical <= window_hours
        hours_until_critical_map: ML predictions keyed by bin_id; falls back to estimate
        zone_congestion_ratio: used directly as traffic_delay_factor
        max_solve_seconds: solver time budget
    """
    if depot is None:
        depot = RouteNode(
            node_id="depot",
            lat=_DEPOT_LAT,
            lng=_DEPOT_LNG,
            node_type="depot",
        )

    bin_states = await _get_flagged_bin_states(ingestion_db)
    if not bin_states:
        logger.warning("build_vrp_input: no flagged bins found for zone={}", zone_id)
        return VRPInput(
            bins=[],
            trucks=trucks,
            depot=depot,
            dump_yards=[],
            traffic_delay_factor=zone_congestion_ratio,
            max_solve_seconds=max_solve_seconds,
        )

    bin_ids = {row["bin_id"] for row in bin_states}
    registry_rows = await _get_registry_entries(geo_db, bin_ids)
    registry_map = {r.bin_id: r for r in registry_rows}

    yards = await geo_db.list_dump_yards()
    dump_nodes = [
        RouteNode(
            node_id=y.yard_id,
            lat=y.lat,
            lng=y.lng,
            node_type="dump_yard",
        )
        for y in yards
        if y.is_active
    ]

    bins: list[RouteNode] = []
    for row in bin_states:
        bid = row["bin_id"]
        if row.get("status") in _EXCLUDED_STATUSES:
            continue
        reg = registry_map.get(bid)
        if reg is None:
            continue

        fill_pct = float(row.get("fill_pct") or 0.0)
        fill_liters = float(row.get("fill_liters") or 0.0)

        if hours_until_critical_map and bid in hours_until_critical_map:
            hours_crit = float(hours_until_critical_map[bid])
        else:
            hours_crit = _estimate_hours_until_critical(fill_pct)

        if hours_crit > window_hours:
            continue

        bins.append(RouteNode(
            node_id=bid,
            lat=reg.lat,
            lng=reg.lng,
            node_type="bin",
            capacity_liters=reg.capacity_liters,
            fill_pct=fill_pct,
            fill_liters=fill_liters,
            priority_level=reg.priority_level,
            hours_until_critical=hours_crit,
            road_access=reg.road_access,
        ))

    logger.info(
        "build_vrp_input: {} bins, {} trucks, {} dump yards, zone={}, window_hours={}",
        len(bins), len(trucks), len(dump_nodes), zone_id, window_hours,
    )
    return VRPInput(
        bins=bins,
        trucks=trucks,
        depot=depot,
        dump_yards=dump_nodes,
        traffic_delay_factor=zone_congestion_ratio,
        max_solve_seconds=max_solve_seconds,
    )


async def _get_flagged_bin_states(db: IngestionDB) -> list[dict]:
    if db._pool is None:
        raise RuntimeError("IngestionDB not connected")
    query = (
        "SELECT bin_id, fill_pct, fill_liters, status "
        "FROM bin_states "
        "WHERE flagged_for_collection = TRUE "
        f"AND status NOT IN ({', '.join(repr(s) for s in _EXCLUDED_STATUSES)})"
    )
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [dict(r) for r in rows]


async def _get_registry_entries(db: GeospatialDB, bin_ids: set[str]):
    results = []
    for bid in bin_ids:
        entry = await db.get_bin(bid)
        if entry is not None:
            results.append(entry)
    return results
