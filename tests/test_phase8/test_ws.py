"""Tests for routing/ws.py — WebSocket connection manager and push helpers."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from routing.ws import ConnectionManager, push_to_driver, push_overflow_alert, push_reroute, push_shift_warning


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def mock_ws():
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock(return_value="ping")
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_accepts_websocket(manager, mock_ws):
    await manager.connect("T1", mock_ws)
    mock_ws.accept.assert_called_once()


@pytest.mark.asyncio
async def test_connect_registers_truck(manager, mock_ws):
    await manager.connect("T1", mock_ws)
    assert manager.active_count == 1


@pytest.mark.asyncio
async def test_disconnect_removes_truck(manager, mock_ws):
    await manager.connect("T1", mock_ws)
    manager.disconnect("T1")
    assert manager.active_count == 0


def test_disconnect_unknown_truck_is_noop(manager):
    manager.disconnect("GHOST")  # should not raise


@pytest.mark.asyncio
async def test_push_sends_json_frame(manager, mock_ws):
    await manager.connect("T1", mock_ws)
    result = await manager.push("T1", "reroute", {"reason": "overflow_alert"})
    assert result is True
    sent = json.loads(mock_ws.send_text.call_args[0][0])
    assert sent["type"] == "reroute"
    assert sent["payload"]["reason"] == "overflow_alert"


@pytest.mark.asyncio
async def test_push_returns_false_for_unknown_truck(manager):
    result = await manager.push("GHOST", "reroute", {})
    assert result is False


@pytest.mark.asyncio
async def test_push_removes_truck_on_send_failure(manager, mock_ws):
    await manager.connect("T1", mock_ws)
    mock_ws.send_text.side_effect = RuntimeError("connection lost")
    result = await manager.push("T1", "reroute", {})
    assert result is False
    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connected_trucks(manager):
    ws1, ws2 = MagicMock(), MagicMock()
    for ws in (ws1, ws2):
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
    await manager.connect("T1", ws1)
    await manager.connect("T2", ws2)
    count = await manager.broadcast("shift_warning", {"minutes_remaining": 30})
    assert count == 2
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_on_empty_manager_returns_zero(manager):
    count = await manager.broadcast("reroute", {})
    assert count == 0


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_to_driver_delegates_to_manager(monkeypatch):
    from routing import ws as ws_module
    mock_push = AsyncMock(return_value=True)
    monkeypatch.setattr(ws_module.manager, "push", mock_push)
    result = await push_to_driver("T1", "reroute", {"route": {}})
    assert result is True
    mock_push.assert_called_once_with("T1", "reroute", {"route": {}})


@pytest.mark.asyncio
async def test_push_overflow_alert_sends_correct_payload(monkeypatch):
    from routing import ws as ws_module
    sent_args = {}
    async def capture(truck_id, msg_type, payload):
        sent_args.update({"truck_id": truck_id, "type": msg_type, "payload": payload})
        return True
    monkeypatch.setattr(ws_module.manager, "push", capture)
    await push_overflow_alert("T1", "B001", "Bin near overflow")
    assert sent_args["type"] == "overflow_alert"
    assert sent_args["payload"]["bin_id"] == "B001"
    assert sent_args["payload"]["message"] == "Bin near overflow"


@pytest.mark.asyncio
async def test_push_reroute_sends_correct_payload(monkeypatch):
    from routing import ws as ws_module
    sent_args = {}
    async def capture(truck_id, msg_type, payload):
        sent_args.update({"type": msg_type, "payload": payload})
        return True
    monkeypatch.setattr(ws_module.manager, "push", capture)
    route = {"truck_id": "T1", "stops": []}
    await push_reroute("T1", route, "overflow_alert")
    assert sent_args["type"] == "reroute"
    assert sent_args["payload"]["reason"] == "overflow_alert"
    assert sent_args["payload"]["route"] == route


@pytest.mark.asyncio
async def test_push_shift_warning_sends_minutes(monkeypatch):
    from routing import ws as ws_module
    sent_args = {}
    async def capture(truck_id, msg_type, payload):
        sent_args.update({"type": msg_type, "payload": payload})
        return True
    monkeypatch.setattr(ws_module.manager, "push", capture)
    await push_shift_warning("T1", 30)
    assert sent_args["type"] == "shift_warning"
    assert sent_args["payload"]["minutes_remaining"] == 30
