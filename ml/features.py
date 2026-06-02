"""ML feature engineering pipeline for Binfinity bin fill prediction."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ml.schemas import FeatureVector

if TYPE_CHECKING:
    from geospatial.db import GeospatialDB
    from ingestion.db import IngestionDB

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# UAE public holidays (approximate Islamic dates for 2025–2026)
# ---------------------------------------------------------------------------
_UAE_HOLIDAYS: set[date] = {
    # 2026
    date(2026, 1, 1),   # New Year
    date(2026, 3, 30),  # Eid Al Fitr approx
    date(2026, 4, 2),   # Eid Al Fitr holiday
    date(2026, 6, 6),   # Arafat (Eid Al Adha eve)
    date(2026, 6, 7),   # Eid Al Adha
    date(2026, 8, 10),  # Islamic New Year approx
    date(2026, 9, 2),   # Prophet's Birthday approx
    date(2026, 12, 1),  # Commemoration Day
    date(2026, 12, 2),  # UAE National Day
    date(2026, 12, 3),  # UAE National Day (holiday)
    # 2025
    date(2025, 1, 1),
    date(2025, 3, 30),
    date(2025, 4, 2),
    date(2025, 6, 6),
    date(2025, 12, 1),
    date(2025, 12, 2),
    date(2025, 12, 3),
}


def _days_until_next_holiday(d: date) -> int:
    """Return the minimum days from *d* to any holiday in _UAE_HOLIDAYS.

    Returns 0 if *d* is itself a holiday.  Capped at 30.
    """
    if d in _UAE_HOLIDAYS:
        return 0
    min_days = 30
    for h in _UAE_HOLIDAYS:
        delta = (h - d).days
        if 0 < delta < min_days:
            min_days = delta
    return min(min_days, 30)


def _rate(rows_asc: list[dict], n_readings: int) -> float:
    """Compute fill rate (%/hr) from the last *n_readings* valid ascending rows."""
    if len(rows_asc) < 2:
        return 0.0
    subset = rows_asc[-n_readings:]
    if len(subset) < 2:
        return 0.0
    delta_fill = subset[-1]["fill_pct"] - subset[0]["fill_pct"]
    delta_hours = (subset[-1]["time"] - subset[0]["time"]).total_seconds() / 3600
    if delta_hours <= 0:
        return 0.0
    return delta_fill / delta_hours


async def build_feature_vector(
    bin_id: str,
    ingestion_db: "IngestionDB",
    geo_db: "GeospatialDB",
    at_time: datetime | None = None,
) -> FeatureVector:
    """Build a :class:`FeatureVector` for *bin_id* at *at_time*.

    Parameters
    ----------
    bin_id:
        The bin identifier to compute features for.
    ingestion_db:
        Open :class:`IngestionDB` whose pool must already be connected.
    geo_db:
        Open :class:`GeospatialDB`.
    at_time:
        Reference timestamp (UTC).  Defaults to ``datetime.now(timezone.utc)``.

    Raises
    ------
    RuntimeError
        If ``ingestion_db._pool`` is ``None`` (pool not connected).
    """
    if ingestion_db._pool is None:
        raise RuntimeError("IngestionDB pool is not connected")

    at_time = at_time or datetime.now(timezone.utc)
    window_24h_start = at_time - timedelta(hours=24)

    # ------------------------------------------------------------------
    # 1. Fetch last 48 telemetry rows (DESC → most-recent first)
    # ------------------------------------------------------------------
    rows_raw: list[dict] = []
    async with ingestion_db._pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT time, fill_pct, sensor_fault, event_type
            FROM telemetry
            WHERE bin_id = $1 AND time <= $2
            ORDER BY time DESC
            LIMIT 48
            """,
            bin_id,
            at_time,
        )
        for r in records:
            rows_raw.append(dict(r))

    # ------------------------------------------------------------------
    # 2. fill_pct_current — most-recent row regardless of fault status
    # ------------------------------------------------------------------
    fill_pct_current: float = rows_raw[0]["fill_pct"] if rows_raw else 0.0

    # ------------------------------------------------------------------
    # 3. Separate valid (non-fault) rows; sort ascending for rate math
    # ------------------------------------------------------------------
    valid_rows = [r for r in rows_raw if not r["sensor_fault"]]
    valid_rows_asc = list(reversed(valid_rows))  # ascending by time

    # ------------------------------------------------------------------
    # 4. Fill rates using the _rate helper
    # ------------------------------------------------------------------
    fill_rate_1h = _rate(valid_rows_asc, 2)
    fill_rate_3h = _rate(valid_rows_asc, 6)
    fill_rate_6h = _rate(valid_rows_asc, 12)
    fill_rate_24h = _rate(valid_rows_asc, 48)

    # ------------------------------------------------------------------
    # 5. Rolling std over last 12 valid readings
    # ------------------------------------------------------------------
    last_12_valid = valid_rows_asc[-12:]
    if len(last_12_valid) >= 2:
        rolling_std_6h = float(np.std([r["fill_pct"] for r in last_12_valid]))
    else:
        rolling_std_6h = 0.0

    # ------------------------------------------------------------------
    # 6. Last emptied event
    # ------------------------------------------------------------------
    time_since_last_empty = 168.0
    fill_at_last_empty = 0.0
    async with ingestion_db._pool.acquire() as conn:
        empty_row = await conn.fetchrow(
            """
            SELECT time, fill_pct FROM telemetry
            WHERE bin_id = $1 AND event_type = 'emptied'
            ORDER BY time DESC
            LIMIT 1
            """,
            bin_id,
        )
    if empty_row is not None:
        time_since_last_empty = (
            at_time - empty_row["time"]
        ).total_seconds() / 3600
        fill_at_last_empty = empty_row["fill_pct"]

    # ------------------------------------------------------------------
    # 7. Spike / fault counts (last 24 h window from already-fetched rows)
    # ------------------------------------------------------------------
    spike_count_24h = sum(
        1
        for r in rows_raw
        if r["time"] >= window_24h_start and r["event_type"] == "spike"
    )
    fault_count_24h = sum(
        1
        for r in rows_raw
        if r["time"] >= window_24h_start and r["sensor_fault"] is True
    )

    # ------------------------------------------------------------------
    # 8. Time context
    # ------------------------------------------------------------------
    h = at_time.hour
    dow = at_time.weekday()
    is_weekend = dow >= 5
    is_peak_morning = 7 <= h < 9
    is_peak_evening = 17 <= h < 20
    days_until_next_holiday = _days_until_next_holiday(at_time.date())

    # ------------------------------------------------------------------
    # 9. Bin context from geo registry
    # ------------------------------------------------------------------
    entry = await geo_db.get_bin(bin_id)

    if entry is not None:
        capacity_liters = float(entry.capacity_liters)
        priority_level = int(entry.priority_level)
        zone_type_residential = int(entry.zone_type == "residential")
        zone_type_commercial = int(entry.zone_type == "commercial")
        zone_type_park = int(entry.zone_type == "park")
        zone_type_transit_hub = int(entry.zone_type == "transit_hub")
        sector_id = entry.sector_id
    else:
        capacity_liters = 120.0
        priority_level = 1
        zone_type_residential = 0
        zone_type_commercial = 0
        zone_type_park = 0
        zone_type_transit_hub = 0
        sector_id = None

    # ------------------------------------------------------------------
    # 10. Sector average fill from bin_states (ingestion schema)
    # ------------------------------------------------------------------
    sector_avg_fill = 0.0
    if entry is not None and sector_id is not None:
        async with ingestion_db._pool.acquire() as conn:
            avg_row = await conn.fetchrow(
                """
                SELECT AVG(bs.fill_pct)
                FROM bin_states bs
                JOIN bin_registry br ON bs.bin_id = br.bin_id
                WHERE br.sector_id = $1 AND bs.fill_pct IS NOT NULL
                """,
                sector_id,
            )
        if avg_row is not None and avg_row[0] is not None:
            sector_avg_fill = float(avg_row[0])

    # ------------------------------------------------------------------
    # 11. Volatility flag
    # ------------------------------------------------------------------
    is_volatile = rolling_std_6h > 8.0

    # ------------------------------------------------------------------
    # 12. Assemble and return FeatureVector
    # ------------------------------------------------------------------
    return FeatureVector(
        bin_id=bin_id,
        at_time=at_time,
        fill_pct_current=fill_pct_current,
        fill_rate_1h=fill_rate_1h,
        fill_rate_3h=fill_rate_3h,
        fill_rate_6h=fill_rate_6h,
        fill_rate_24h=fill_rate_24h,
        rolling_std_6h=rolling_std_6h,
        time_since_last_empty=time_since_last_empty,
        fill_at_last_empty=fill_at_last_empty,
        hour_of_day=h,
        day_of_week=dow,
        is_weekend=is_weekend,
        is_peak_morning=is_peak_morning,
        is_peak_evening=is_peak_evening,
        days_until_next_holiday=days_until_next_holiday,
        zone_type_residential=zone_type_residential,
        zone_type_commercial=zone_type_commercial,
        zone_type_park=zone_type_park,
        zone_type_transit_hub=zone_type_transit_hub,
        capacity_liters=capacity_liters,
        priority_level=priority_level,
        sector_avg_fill=sector_avg_fill,
        spike_count_24h=spike_count_24h,
        fault_count_24h=fault_count_24h,
        is_volatile=is_volatile,
    )


async def build_feature_matrix(
    bin_ids: list[str],
    ingestion_db: "IngestionDB",
    geo_db: "GeospatialDB",
    at_time: datetime | None = None,
) -> pd.DataFrame:
    """Build a feature matrix for multiple bins.

    Each row corresponds to one bin.  The ``bin_id`` and ``at_time`` columns
    are excluded (they are identifiers, not model features).

    Parameters
    ----------
    bin_ids:
        List of bin identifiers to include.
    ingestion_db:
        Open :class:`IngestionDB`.
    geo_db:
        Open :class:`GeospatialDB`.
    at_time:
        Reference timestamp (UTC).  Defaults to ``datetime.now(timezone.utc)``.

    Returns
    -------
    pd.DataFrame
        One row per successfully computed bin.  Empty DataFrame if all fail.
    """
    vectors: list[FeatureVector] = []
    for bid in bin_ids:
        try:
            fv = await build_feature_vector(bid, ingestion_db, geo_db, at_time)
            vectors.append(fv)
        except Exception as exc:
            logger.warning("Failed to build feature vector for bin %s: %s", bid, exc)

    if not vectors:
        return pd.DataFrame()

    # Convert to dicts, then drop identifier columns
    records = [fv.model_dump() for fv in vectors]
    for rec in records:
        rec.pop("bin_id", None)
        rec.pop("at_time", None)

    return pd.DataFrame(records)
