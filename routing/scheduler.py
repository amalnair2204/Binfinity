"""Background routing loop — generates routes every 15 min and polls dispatch events."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from geospatial.db import GeospatialDB
from ingestion.db import IngestionDB
from routing.dispatcher import DispatchEvent, RouteDispatcher
from routing.input_builder import build_vrp_input
from routing.schemas import RouteNode, Truck
from routing.solver_orchestrator import SolverOrchestrator

_ROUTING_INTERVAL_SECONDS = 900  # 15 minutes
_EVENT_POLL_INTERVAL_SECONDS = 5
_REDIS_EVENTS_KEY = "dispatch:events"

_DEPOT_LAT = float(os.getenv("CITY_LAT", "25.2048"))
_DEPOT_LNG = float(os.getenv("CITY_LNG", "55.2708"))


async def run_routing_loop(
    geo_db: GeospatialDB,
    ingestion_db: IngestionDB,
    orchestrator: SolverOrchestrator,
    dispatcher: RouteDispatcher,
    redis: aioredis.Redis,
    trucks: list[Truck],
    depot: Optional[RouteNode] = None,
    traffic_delay_factor: float = 1.0,
) -> None:
    """Main background task — runs until cancelled.

    Spawns two concurrent loops:
    - Route generation every 15 minutes
    - Redis event polling every 5 seconds
    """
    if depot is None:
        depot = RouteNode(
            node_id="depot",
            lat=_DEPOT_LAT,
            lng=_DEPOT_LNG,
            node_type="depot",
        )

    await asyncio.gather(
        _route_generation_loop(
            geo_db, ingestion_db, orchestrator, dispatcher, trucks, depot, traffic_delay_factor
        ),
        _event_poll_loop(dispatcher, redis),
        return_exceptions=True,
    )


async def _route_generation_loop(
    geo_db: GeospatialDB,
    ingestion_db: IngestionDB,
    orchestrator: SolverOrchestrator,
    dispatcher: RouteDispatcher,
    trucks: list[Truck],
    depot: RouteNode,
    traffic_delay_factor: float,
) -> None:
    while True:
        try:
            await _run_single_optimization(
                geo_db, ingestion_db, orchestrator, dispatcher, trucks, depot, traffic_delay_factor
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Routing loop error: {}", exc)

        logger.debug("Routing loop sleeping {}s", _ROUTING_INTERVAL_SECONDS)
        await asyncio.sleep(_ROUTING_INTERVAL_SECONDS)


async def _run_single_optimization(
    geo_db: GeospatialDB,
    ingestion_db: IngestionDB,
    orchestrator: SolverOrchestrator,
    dispatcher: RouteDispatcher,
    trucks: list[Truck],
    depot: RouteNode,
    traffic_delay_factor: float,
) -> None:
    logger.info("Routing loop: building VRPInput at {}", datetime.now(tz=timezone.utc).isoformat())

    vrp_input = await build_vrp_input(
        geo_db=geo_db,
        ingestion_db=ingestion_db,
        trucks=trucks,
        depot=depot,
        traffic_delay_factor=traffic_delay_factor,
    )

    if not vrp_input.bins:
        logger.info("Routing loop: no flagged bins, skipping optimization")
        return

    # Update dispatcher's problem definition for event-triggered re-opts
    await dispatcher.set_vrp_input(vrp_input)

    solution = await orchestrator.solve(vrp_input)

    logger.info(
        "Routing loop: solver={} routes={} unserved={} dist_km={:.1f} status={}",
        solution.solver,
        len(solution.routes),
        len(solution.unserved_bins),
        solution.total_distance_m / 1000,
        solution.status,
    )

    await dispatcher.apply_solution(solution, triggered_by="scheduled")

    # Push each truck's route to Redis for driver app polling
    for route in solution.routes:
        key = f"dispatch:truck:{route.truck_id}:current_route"
        await _redis_set_from_dispatcher(dispatcher, route.truck_id, key)


async def _redis_set_from_dispatcher(dispatcher: RouteDispatcher, truck_id: str, key: str) -> None:
    # Route already pushed inside dispatcher.apply_solution; this is a no-op marker
    # kept for clarity — Redis push happens in RouteDispatcher._push_route_to_redis
    pass


async def _event_poll_loop(
    dispatcher: RouteDispatcher,
    redis: aioredis.Redis,
) -> None:
    """Poll Redis list `dispatch:events` and forward events to the dispatcher."""
    while True:
        try:
            await _drain_event_queue(dispatcher, redis)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Event poll loop error: {}", exc)

        await asyncio.sleep(_EVENT_POLL_INTERVAL_SECONDS)


async def _drain_event_queue(
    dispatcher: RouteDispatcher,
    redis: aioredis.Redis,
) -> None:
    while True:
        raw = await redis.rpop(_REDIS_EVENTS_KEY)
        if raw is None:
            break
        try:
            data = json.loads(raw)
            event = DispatchEvent.model_validate(data)
            await dispatcher.on_event(event)
        except Exception as exc:
            logger.warning("Failed to process dispatch event: {} — raw={}", exc, raw)


if __name__ == "__main__":
    import asyncio as _asyncio
    import uvicorn as _uvicorn
    import asyncpg as _asyncpg
    from fastapi import FastAPI as _FastAPI
    from routing.truck_manager import TruckManager as _TruckManager
    from routing.solver_orchestrator import SolverOrchestrator as _SolverOrchestrator
    from routing.schemas import Truck as _Truck
    from ingestion.db import IngestionDB as _IngestionDB
    from geospatial.db import GeospatialDB as _GeospatialDB

    _DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:binfinity@localhost:5432/binfinity")
    _REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    _PORT = int(os.getenv("ROUTING_PORT", "8005"))
    _TRUCK_COUNT = int(os.getenv("TRUCK_COUNT", "5"))

    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator
    _app = _FastAPI(title="Binfinity Routing")
    _Instrumentator().instrument(_app).expose(_app, endpoint="/metrics")

    @_app.get("/health")
    async def _health():
        return {"status": "ok"}

    async def _main() -> None:
        pool = await _asyncpg.create_pool(_DATABASE_URL, min_size=2, max_size=10)
        redis = aioredis.from_url(_REDIS_URL, decode_responses=True)

        truck_mgr = _TruckManager(redis, pool)
        await truck_mgr.init_schema()

        orchestrator = _SolverOrchestrator()
        dispatcher = RouteDispatcher(orchestrator, redis, pool)
        await dispatcher.init_schema()

        ingestion_db = _IngestionDB(_DATABASE_URL)
        await ingestion_db.connect()

        geo_db = _GeospatialDB(_DATABASE_URL)
        await geo_db.connect()

        depot_lat = _DEPOT_LAT
        depot_lng = _DEPOT_LNG
        trucks = [
            _Truck(
                truck_id=f"truck_{i:02d}",
                capacity_liters=2000,
                depot_lat=depot_lat,
                depot_lng=depot_lng,
            )
            for i in range(1, _TRUCK_COUNT + 1)
        ]
        for truck in trucks:
            await truck_mgr.register_truck(truck)

        config = _uvicorn.Config(_app, host="0.0.0.0", port=_PORT, log_level="info")
        server = _uvicorn.Server(config)
        await _asyncio.gather(
            server.serve(),
            run_routing_loop(geo_db, ingestion_db, orchestrator, dispatcher, redis, trucks),
            return_exceptions=True,
        )

    _asyncio.run(_main())
