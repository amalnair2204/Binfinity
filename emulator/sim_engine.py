"""
Simulation engine — owns 200 BinNode instances, runs async tick loop,
streams telemetry via SQLite + STDOUT + SSE, writes bin_states.json snapshot.

Start with: python -m emulator.sim_engine
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from loguru import logger

from emulator.api import app, set_engine
from emulator.bin_model import BinNode
from emulator.telemetry import TelemetryDB, TelemetryPacket


class SimEngine:
    def __init__(
        self,
        config_path: str = "config/bins.json",
        db_path: str = "data/telemetry.db",
    ) -> None:
        self.bins: dict[str, BinNode] = {}
        self.sse_subscribers: set[asyncio.Queue] = set()
        self.tick_interval: float = float(os.getenv("SIM_TICK_REAL_SECONDS", "2.0"))
        # Simulation starts on a Monday at 06:00 UTC (morning peak)
        self.sim_time: datetime = datetime(2025, 1, 6, 6, 0, 0, tzinfo=timezone.utc)
        self._db = TelemetryDB(db_path)
        self._load_bins(config_path)

    def _load_bins(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        for b in data:
            self.bins[b["bin_id"]] = BinNode(**b)
        logger.info(f"Loaded {len(self.bins)} bins from {path}")

    async def run(self) -> None:
        await self._db.connect()
        logger.info("Simulation started")
        try:
            while True:
                try:
                    await self._tick()
                except Exception as exc:
                    logger.error(f"Tick error: {exc}")
                await asyncio.sleep(self.tick_interval)
        finally:
            await self._db.close()

    async def _tick(self) -> None:
        tasks = [
            asyncio.create_task(self._process_bin(bin_node))
            for bin_node in self.bins.values()
        ]
        all_packets: list[TelemetryPacket] = []
        for result in await asyncio.gather(*tasks):
            all_packets.extend(result)

        # Persist + stream
        for packet in all_packets:
            await self._db.insert(packet)
            print(packet.model_dump_json(), flush=True)   # STDOUT newline-delimited JSON

        # SSE fan-out
        dead: set[asyncio.Queue] = set()
        for queue in list(self.sse_subscribers):
            for packet in all_packets:
                try:
                    queue.put_nowait(packet)
                except asyncio.QueueFull:
                    dead.add(queue)
        self.sse_subscribers -= dead

        await self._write_snapshot()
        self.sim_time += timedelta(minutes=30)
        logger.debug(f"Tick complete — {len(all_packets)} packets — sim_time={self.sim_time}")

    async def _process_bin(self, bin_node: BinNode) -> list[TelemetryPacket]:
        """Tick a bin and trigger emptying if truck-ready."""
        packets = bin_node.tick(self.sim_time)
        if bin_node.marked_for_collection and bin_node.current_fill_pct >= 85.0:
            emptied = bin_node.apply_emptying(self.sim_time)
            packets.append(emptied)
        return packets

    async def _write_snapshot(self) -> None:
        snapshot = {
            bid: {
                "bin_id": b.bin_id,
                "lat": b.lat,
                "lng": b.lng,
                "zone": b.zone,
                "capacity_liters": b.capacity_liters,
                "current_fill_pct": round(b.current_fill_pct, 2),
                "fill_liters": round(b.current_fill_pct / 100.0 * b.capacity_liters, 2),
                "sensor_fault": b.sensor_fault,
                "tipped": b.tipped,
                "battery_mv": b.battery_mv,
                "marked_for_collection": b.marked_for_collection,
                "sim_time": self.sim_time.isoformat(),
            }
            for bid, b in self.bins.items()
        }
        tmp = Path("data/bin_states.json.tmp")
        final = Path("data/bin_states.json")
        tmp.write_text(json.dumps(snapshot))
        os.replace(tmp, final)


async def _main() -> None:
    engine = SimEngine()
    set_engine(engine)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await asyncio.gather(engine.run(), server.serve())


if __name__ == "__main__":
    asyncio.run(_main())
