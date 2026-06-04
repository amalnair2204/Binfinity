"""TelemetryPacket schema and async SQLite writer."""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

import aiosqlite
from pydantic import BaseModel

if TYPE_CHECKING:
    from emulator.bin_model import BinNode

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS telemetry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id       TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    fill_pct     REAL,
    fill_liters  REAL,
    tipped       INTEGER,
    sensor_fault INTEGER,
    battery_mv   INTEGER,
    rssi_dbm     INTEGER,
    temp_c       REAL,
    event_type   TEXT
)
"""

_INSERT = """
INSERT INTO telemetry
    (bin_id, timestamp, fill_pct, fill_liters, tipped, sensor_fault,
     battery_mv, rssi_dbm, temp_c, event_type)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class TelemetryPacket(BaseModel):
    bin_id: str
    timestamp: datetime
    fill_pct: float
    fill_liters: float
    tipped: bool
    sensor_fault: bool
    battery_mv: int
    rssi_dbm: int
    temp_c: float
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"]


def build_packet(
    bin_node: BinNode,
    sim_dt: datetime,
    event_type: Literal["scheduled", "tip_alert", "overflow_warning", "emptied", "spike"],
) -> TelemetryPacket:
    """Build a validated TelemetryPacket from current BinNode state."""
    ts = sim_dt if sim_dt.tzinfo else sim_dt.replace(tzinfo=timezone.utc)
    return TelemetryPacket(
        bin_id=bin_node.bin_id,
        timestamp=ts,
        fill_pct=round(bin_node.current_fill_pct, 2),
        fill_liters=round(bin_node.current_fill_pct / 100.0 * bin_node.capacity_liters, 2),
        tipped=bin_node.tipped,
        sensor_fault=bin_node.sensor_fault,
        battery_mv=bin_node.battery_mv,
        rssi_dbm=random.randint(-100, -70),
        temp_c=round(random.uniform(20.0, 45.0), 1),
        event_type=event_type,
    )


class TelemetryDB:
    """Async SQLite writer backed by a single persistent connection."""

    def __init__(self, db_path: str = "data/telemetry.db") -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert(self, packet: TelemetryPacket) -> None:
        if self._db is None:
            raise RuntimeError("Call connect() first")
        await self._db.execute(
            _INSERT,
            (
                packet.bin_id,
                packet.timestamp.isoformat(),
                packet.fill_pct,
                packet.fill_liters,
                int(packet.tipped),
                int(packet.sensor_fault),
                packet.battery_mv,
                packet.rssi_dbm,
                packet.temp_c,
                packet.event_type,
            ),
        )
        await self._db.commit()

    async def count(self) -> int:
        if self._db is None:
            raise RuntimeError("Call connect() first")
        async with self._db.execute("SELECT COUNT(*) FROM telemetry") as cur:
            row = await cur.fetchone()
            return row[0]

    async def fetch_all(self) -> list[dict]:
        if self._db is None:
            raise RuntimeError("Call connect() first")
        async with self._db.execute("SELECT * FROM telemetry ORDER BY id") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
