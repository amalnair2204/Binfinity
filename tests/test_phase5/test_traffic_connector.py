"""Unit tests for exogenous/connectors/traffic.py — mock httpx."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis
import pytest

from exogenous.connectors.traffic import (
    TrafficConnector,
    TrafficSnapshot,
    _HOUR_CONGESTION,
    _CONGESTED_THRESHOLD,
)


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_tomtom_response(current_speed: float, free_flow_speed: float) -> dict:
    return {
        "flowSegmentData": {
            "currentSpeed": current_speed,
            "freeFlowSpeed": free_flow_speed,
        }
    }


def _mock_client(response_data: dict, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = __import__("httpx").HTTPStatusError(
            message="error",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    else:
        mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


# ---------------------------------------------------------------------------
# TrafficSnapshot.compute_delay
# ---------------------------------------------------------------------------

def test_compute_delay_at_40pct_congestion():
    """At ratio=0.4, delay = (1/0.4 - 1) * 10 = 15 min/10km."""
    delay = TrafficSnapshot.compute_delay(0.4)
    assert delay == pytest.approx(15.0, abs=0.1)


def test_compute_delay_at_free_flow():
    delay = TrafficSnapshot.compute_delay(1.0)
    assert delay == pytest.approx(0.0, abs=0.01)


def test_compute_delay_fully_stopped():
    delay = TrafficSnapshot.compute_delay(0.0)
    assert delay == pytest.approx(60.0)  # capped


# ---------------------------------------------------------------------------
# Valid TomTom API response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_response_correct_congestion_ratio():
    """current=30, free_flow=75 → ratio=0.4."""
    r = _make_redis()
    c = TrafficConnector(r, api_key="test")
    data = _make_tomtom_response(30.0, 75.0)

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_traffic_snapshot()

    assert snap.congestion_ratio == pytest.approx(0.4, abs=0.001)


@pytest.mark.asyncio
async def test_is_congested_true_when_ratio_below_threshold():
    r = _make_redis()
    c = TrafficConnector(r, api_key="test")
    data = _make_tomtom_response(20.0, 75.0)  # ratio ≈ 0.267

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_traffic_snapshot()

    assert snap.is_congested is True
    assert snap.congestion_ratio < _CONGESTED_THRESHOLD


@pytest.mark.asyncio
async def test_is_congested_false_when_ratio_above_threshold():
    r = _make_redis()
    c = TrafficConnector(r, api_key="test")
    data = _make_tomtom_response(60.0, 75.0)  # ratio = 0.8

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_traffic_snapshot()

    assert snap.is_congested is False


@pytest.mark.asyncio
async def test_delay_minutes_computed_correctly():
    """current=30, free_flow=75 → ratio=0.4 → delay=15 min/10km."""
    r = _make_redis()
    c = TrafficConnector(r, api_key="test")
    data = _make_tomtom_response(30.0, 75.0)

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_traffic_snapshot()

    assert snap.delay_minutes_per_10km == pytest.approx(15.0, abs=0.5)


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------

def test_heuristic_peak_morning_congestion_ratio():
    """Hour 8 Dubai (4AM UTC) → congestion_ratio == 0.40."""
    r = _make_redis()
    c = TrafficConnector(r, api_key="")  # no key → heuristic
    at_time = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)  # 4AM UTC = 8AM Dubai
    snap = c._heuristic_snapshot(at_time=at_time)
    assert snap.congestion_ratio == pytest.approx(0.40)


def test_heuristic_peak_morning_is_congested():
    r = _make_redis()
    c = TrafficConnector(r, api_key="")
    at_time = datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc)
    snap = c._heuristic_snapshot(at_time=at_time)
    assert snap.is_congested is True


@pytest.mark.asyncio
async def test_api_unavailable_uses_heuristic():
    """When API returns 503, should fall back to heuristic (not raise)."""
    import httpx as _httpx

    r = _make_redis()
    c = TrafficConnector(r, api_key="test")

    async def _server_error(*args, **kwargs):
        raise _httpx.HTTPStatusError(
            message="503",
            request=MagicMock(),
            response=MagicMock(status_code=503),
        )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = _server_error

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            snap = await c.get_traffic_snapshot()

    assert isinstance(snap, TrafficSnapshot)
    assert 0.0 < snap.congestion_ratio <= 1.0


@pytest.mark.asyncio
async def test_warning_logged_when_fallback_used():
    """TomTom failure must emit a warning before falling back."""
    import httpx as _httpx

    r = _make_redis()
    c = TrafficConnector(r, api_key="test")

    async def _timeout(*args, **kwargs):
        raise _httpx.TimeoutException("timeout")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = _timeout

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("exogenous.connectors.traffic.logger") as mock_logger:
                snap = await c._call_api(zone_id="")

    # logger.warning must have been called with a message containing "heuristic" or "fallback"
    assert mock_logger.warning.called
    warned_text = " ".join(str(a) for a in mock_logger.warning.call_args_list).lower()
    assert "heuristic" in warned_text or "fallback" in warned_text
    assert isinstance(snap, TrafficSnapshot)


# ---------------------------------------------------------------------------
# Hour congestion table sanity
# ---------------------------------------------------------------------------

def test_hour_congestion_table_has_24_entries():
    assert len(_HOUR_CONGESTION) == 24


def test_all_congestion_ratios_in_valid_range():
    for h, ratio in _HOUR_CONGESTION.items():
        assert 0.0 < ratio <= 1.0, f"Hour {h} has invalid congestion ratio {ratio}"
