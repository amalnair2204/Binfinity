"""WebSocket server for real-time notifications.

Driver endpoint: /ws/driver/{truck_id}
    {"type": "reroute", "payload": {"route": {...}, "reason": "overflow_alert"}}
    {"type": "overflow_alert", "payload": {"bin_id": "B001", "message": "..."}}
    {"type": "shift_warning", "payload": {"minutes_remaining": 30}}
    {"type": "stop_injected", "payload": {"yard_id": "Y1"}}

Ops endpoint: /ws/ops
    {"type": "alert", "payload": <DispatchEvent dict>}
    {"type": "truck_pos", "payload": {"truck_id": "T1", "lat": 0.0, "lng": 0.0}}
    {"type": "routes", "payload": {"routes": [...]}}
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class ConnectionManager:
    """Registry of active per-truck WebSocket connections."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, truck_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[truck_id] = ws
        logger.info("WS: truck={} connected (active={})", truck_id, len(self._connections))

    def disconnect(self, truck_id: str) -> None:
        self._connections.pop(truck_id, None)
        logger.info("WS: truck={} disconnected (active={})", truck_id, len(self._connections))

    async def push(self, truck_id: str, msg_type: str, payload: Any) -> bool:
        """Push a JSON message to a specific truck. Returns True if delivered."""
        ws = self._connections.get(truck_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps({"type": msg_type, "payload": payload}))
            return True
        except Exception as exc:
            logger.warning("WS: failed to push to truck={}: {}", truck_id, exc)
            self.disconnect(truck_id)
            return False

    async def broadcast(self, msg_type: str, payload: Any) -> int:
        """Push to all connected trucks. Returns count of successful deliveries."""
        truck_ids = list(self._connections.keys())
        count = 0
        for tid in truck_ids:
            if await self.push(tid, msg_type, payload):
                count += 1
        return count

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def driver_ws_endpoint(websocket: WebSocket, truck_id: str) -> None:
    """FastAPI WebSocket endpoint handler — mount with app.add_api_websocket_route."""
    await manager.connect(truck_id, websocket)
    try:
        while True:
            # Keep connection alive; ignore any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(truck_id)


async def push_to_driver(truck_id: str, msg_type: str, payload: Any) -> bool:
    """Push a typed message to the given truck's active WS connection."""
    return await manager.push(truck_id, msg_type, payload)


async def push_overflow_alert(truck_id: str, bin_id: str, message: str = "") -> None:
    await push_to_driver(truck_id, "overflow_alert", {"bin_id": bin_id, "message": message})


async def push_reroute(truck_id: str, route_dict: dict, reason: str) -> None:
    await push_to_driver(truck_id, "reroute", {"route": route_dict, "reason": reason})


async def push_shift_warning(truck_id: str, minutes_remaining: int) -> None:
    await push_to_driver(truck_id, "shift_warning", {"minutes_remaining": minutes_remaining})


# ---------------------------------------------------------------------------
# Ops dashboard WebSocket — /ws/ops
# ---------------------------------------------------------------------------

class OpsConnectionManager:
    """Registry for ops dashboard connections (multiple concurrent clients)."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._counter: int = 0

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        self._counter += 1
        conn_id = f"ops_{self._counter}"
        self._connections[conn_id] = ws
        logger.info("WS/ops: client {} connected (active={})", conn_id, len(self._connections))
        return conn_id

    def disconnect(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
        logger.info("WS/ops: client {} disconnected (active={})", conn_id, len(self._connections))

    async def broadcast(self, msg_type: str, payload: Any) -> int:
        conn_ids = list(self._connections.keys())
        count = 0
        for cid in conn_ids:
            ws = self._connections.get(cid)
            if ws is None:
                continue
            try:
                await ws.send_text(json.dumps({"type": msg_type, "payload": payload}))
                count += 1
            except Exception as exc:
                logger.warning("WS/ops: broadcast failed for {}: {}", cid, exc)
                self.disconnect(cid)
        return count

    @property
    def active_count(self) -> int:
        return len(self._connections)


ops_manager = OpsConnectionManager()


async def ops_ws_endpoint(websocket: WebSocket) -> None:
    """FastAPI WebSocket endpoint handler for ops dashboard clients."""
    conn_id = await ops_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ops_manager.disconnect(conn_id)


async def broadcast_to_ops(event_type: str, payload: Any) -> int:
    """Broadcast an event to all connected ops dashboard clients."""
    return await ops_manager.broadcast(event_type, payload)
