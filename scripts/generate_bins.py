"""One-time 200-bin registry generator for the Binfinity emulator."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

CITY_LAT: float = float(os.getenv("CITY_LAT", "25.2048"))
CITY_LNG: float = float(os.getenv("CITY_LNG", "55.2708"))
SPREAD: float = 0.15

ZONES = ["residential", "commercial", "park", "transit_hub"]
ZONE_WEIGHTS = [0.40, 0.30, 0.20, 0.10]
CAPACITY_BY_ZONE: dict[str, float] = {
    "residential": 120.0,
    "commercial": 240.0,
    "park": 80.0,
    "transit_hub": 120.0,
}
FILL_RATE_RANGE: dict[str, tuple[float, float]] = {
    "residential": (1.0, 2.0),
    "commercial": (2.0, 4.0),
    "park": (0.5, 3.0),
    "transit_hub": (2.5, 5.0),
}


def generate_bins(count: int = 200, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    bins: list[dict] = []
    for i in range(1, count + 1):
        zone: str = rng.choices(ZONES, weights=ZONE_WEIGHTS)[0]
        low, high = FILL_RATE_RANGE[zone]
        bins.append(
            {
                "bin_id": f"BIN-{i:04d}",
                "lat": round(CITY_LAT + rng.uniform(-SPREAD, SPREAD), 6),
                "lng": round(CITY_LNG + rng.uniform(-SPREAD, SPREAD), 6),
                "zone": zone,
                "base_fill_rate": round(rng.uniform(low, high), 2),
                "capacity_liters": CAPACITY_BY_ZONE[zone],
                "current_fill_pct": round(rng.uniform(0.0, 60.0), 1),
                "battery_mv": rng.randint(3800, 4200),
            }
        )
    return bins


if __name__ == "__main__":
    Path("config").mkdir(exist_ok=True)
    bins = generate_bins()
    out = Path("config/bins.json")
    out.write_text(json.dumps(bins, indent=2))
    print(f"Generated {len(bins)} bins -> {out}")
