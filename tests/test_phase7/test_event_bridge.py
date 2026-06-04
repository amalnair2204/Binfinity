"""Tests for routing/event_bridge.py."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from routing.event_bridge import EventBridge


@pytest.fixture
def bridge(fake_redis, mock_dispatcher):
    return EventBridge(fake_redis, mock_dispatcher)


# ---------------------------------------------------------------------------
# bins:flagged → DispatchEvent emission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overflow_alert_on_critical_bin(fake_redis, bridge, mock_dispatcher):
    """New flagged bin with fill ≥ 95% → overflow_alert priority 3."""
    await fake_redis.set(
        "bin:B001:state",
        json.dumps({"fill_pct": 97.0, "status": "operational"}).encode(),
    )
    await fake_redis.sadd("bins:flagged", b"B001")

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_called_once()
    evt = mock_dispatcher.on_event.call_args[0][0]
    assert evt.event_type == "overflow_alert"
    assert evt.priority == 3
    assert evt.affected_bin_id == "B001"


@pytest.mark.asyncio
async def test_new_bins_flagged_on_non_critical_bin(fake_redis, bridge, mock_dispatcher):
    """New flagged bin with low fill → new_bins_flagged priority 1."""
    await fake_redis.set(
        "bin:B002:state",
        json.dumps({"fill_pct": 60.0, "status": "operational"}).encode(),
    )
    await fake_redis.sadd("bins:flagged", b"B002")

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_called_once()
    evt = mock_dispatcher.on_event.call_args[0][0]
    assert evt.event_type == "new_bins_flagged"
    assert evt.priority == 1
    assert evt.affected_bin_id == "B002"


@pytest.mark.asyncio
async def test_known_flagged_bin_emits_no_event(fake_redis, bridge, mock_dispatcher):
    """Bin already in dispatch:known_flagged → no event re-emitted."""
    await fake_redis.sadd("bins:flagged", b"B003")
    await fake_redis.sadd("dispatch:known_flagged", b"B003")

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_not_called()


@pytest.mark.asyncio
async def test_faulted_bin_no_dispatch_event(fake_redis, bridge, mock_dispatcher):
    """New entry in bins:faulted → no dispatch event, only log."""
    await fake_redis.sadd("bins:faulted", b"B004")

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_events_list_consumed(fake_redis, bridge, mock_dispatcher):
    """LPUSH to dispatch:events → event consumed and forwarded to dispatcher."""
    event_payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "manual_override",
        "triggered_at": datetime.now(tz=timezone.utc).isoformat(),
        "priority": 2,
    }
    await fake_redis.lpush("dispatch:events", json.dumps(event_payload).encode())

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_called_once()
    evt = mock_dispatcher.on_event.call_args[0][0]
    assert evt.event_type == "manual_override"


@pytest.mark.asyncio
async def test_known_flagged_updated_after_poll(fake_redis, bridge, mock_dispatcher):
    """After poll, dispatch:known_flagged includes newly flagged bins."""
    await fake_redis.set(
        "bin:B005:state",
        json.dumps({"fill_pct": 90.0}).encode(),
    )
    await fake_redis.sadd("bins:flagged", b"B005")

    await bridge._poll_once()

    members_raw = await fake_redis.smembers("dispatch:known_flagged")
    members = {m.decode() if isinstance(m, bytes) else m for m in members_raw}
    assert "B005" in members


@pytest.mark.asyncio
async def test_tip_alert_translated_to_tip_over(fake_redis, bridge, mock_dispatcher):
    """tip_alert packet in dispatch:events → tip_over DispatchEvent."""
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "tip_alert",
        "triggered_at": datetime.now(tz=timezone.utc).isoformat(),
        "affected_bin_id": "B010",
        "priority": 1,
    }
    await fake_redis.lpush("dispatch:events", json.dumps(payload).encode())

    await bridge._poll_once()

    mock_dispatcher.on_event.assert_called_once()
    evt = mock_dispatcher.on_event.call_args[0][0]
    assert evt.event_type == "tip_over"
    assert evt.priority == 3
    assert evt.affected_bin_id == "B010"


@pytest.mark.asyncio
async def test_multiple_new_bins_emits_multiple_events(fake_redis, bridge, mock_dispatcher):
    """Three newly flagged bins → three separate on_event calls."""
    for i in range(3):
        bid = f"B10{i}"
        await fake_redis.set(
            f"bin:{bid}:state",
            json.dumps({"fill_pct": 60.0}).encode(),
        )
        await fake_redis.sadd("bins:flagged", bid.encode())

    await bridge._poll_once()

    assert mock_dispatcher.on_event.call_count == 3
