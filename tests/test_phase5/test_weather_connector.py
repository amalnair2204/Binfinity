"""Unit tests for exogenous/connectors/weather.py — mock httpx."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis as fakeredis
import pytest

from exogenous.connectors.weather import (
    WeatherConnector,
    WeatherSnapshot,
    _RAIN_CODE_RANGES,
)


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _make_owm_response(code: int, temp_c: float = 30.0, description: str = "") -> dict:
    return {
        "weather": [{"id": code, "description": description}],
        "main": {"temp": temp_c},
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
# WeatherSnapshot static helpers
# ---------------------------------------------------------------------------

def test_compute_fill_multiplier_rain_returns_0_8():
    m = WeatherSnapshot.compute_fill_multiplier(is_raining=True, is_hot=False, is_weekend=False)
    assert m == pytest.approx(0.8)


def test_compute_fill_multiplier_rain_overrides_hot_weekend():
    m = WeatherSnapshot.compute_fill_multiplier(is_raining=True, is_hot=True, is_weekend=True)
    assert m == pytest.approx(0.8)


def test_compute_fill_multiplier_clear_hot_weekend_returns_1_5():
    m = WeatherSnapshot.compute_fill_multiplier(is_raining=False, is_hot=True, is_weekend=True)
    assert m == pytest.approx(1.5)


def test_compute_fill_multiplier_clear_not_hot_not_weekend():
    m = WeatherSnapshot.compute_fill_multiplier(is_raining=False, is_hot=False, is_weekend=False)
    assert m == pytest.approx(1.0)


def test_compute_outdoor_activity_rain():
    s = WeatherSnapshot.compute_outdoor_activity_score(is_raining=True, is_hot=False, temp_c=25.0)
    assert s == pytest.approx(0.2)


def test_compute_outdoor_activity_hot():
    s = WeatherSnapshot.compute_outdoor_activity_score(is_raining=False, is_hot=True, temp_c=40.0)
    assert s == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# is_raining detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [200, 230, 299, 300, 399, 500, 520, 599])
def test_is_raining_true_for_rain_codes(code):
    """Thunderstorm, drizzle, and rain condition codes all set is_raining."""
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    snap = c._parse_snapshot(_make_owm_response(code))
    assert snap.is_raining is True


@pytest.mark.parametrize("code", [800, 801, 804, 700, 781])
def test_is_raining_false_for_non_rain_codes(code):
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    snap = c._parse_snapshot(_make_owm_response(code))
    assert snap.is_raining is False


# ---------------------------------------------------------------------------
# is_hot
# ---------------------------------------------------------------------------

def test_is_hot_true_when_temp_above_35():
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    snap = c._parse_snapshot(_make_owm_response(800, temp_c=36.0))
    assert snap.is_hot is True


def test_is_hot_false_when_temp_below_35():
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    snap = c._parse_snapshot(_make_owm_response(800, temp_c=34.9))
    assert snap.is_hot is False


# ---------------------------------------------------------------------------
# weather_fill_multiplier via connector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_response_gives_correct_snapshot():
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    data = _make_owm_response(800, temp_c=25.0, description="clear sky")

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_weather_snapshot()

    assert isinstance(snap, WeatherSnapshot)
    assert snap.condition_code == 800
    assert snap.condition_description == "clear sky"
    assert snap.is_raining is False
    assert snap.temp_c == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_weather_fill_multiplier_rain():
    """Rain code → multiplier == 0.8."""
    r = _make_redis()
    c = WeatherConnector(r, api_key="test")
    data = _make_owm_response(500, temp_c=28.0)

    with patch("httpx.AsyncClient", return_value=_mock_client(data)):
        snap = await c.get_weather_snapshot()

    assert snap.weather_fill_multiplier == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeout_retries_exactly_3_times():
    import httpx as _httpx

    r = _make_redis()
    c = WeatherConnector(r, api_key="test")

    call_count = 0

    async def _failing_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _httpx.TimeoutException("timeout")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = _failing_get

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # fetch() raises after all retries
            with pytest.raises(RuntimeError, match="retries"):
                await c._call_api()

    assert call_count == 3


@pytest.mark.asyncio
async def test_after_3_failed_retries_get_multiplier_returns_neutral():
    """get_multiplier() must never raise — returns 1.0 on all-retry failure."""
    import httpx as _httpx

    r = _make_redis()
    c = WeatherConnector(r, api_key="test")

    async def _failing_get(*args, **kwargs):
        raise _httpx.TimeoutException("timeout")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = _failing_get

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await c.get_multiplier()

    assert result == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_after_3_failed_retries_get_snapshot_returns_neutral():
    """get_weather_snapshot() must never raise — returns neutral snapshot."""
    import httpx as _httpx

    r = _make_redis()
    c = WeatherConnector(r, api_key="test")

    async def _failing_get(*args, **kwargs):
        raise _httpx.TimeoutException("timeout")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = _failing_get

    with patch("httpx.AsyncClient", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            snap = await c.get_weather_snapshot()

    assert isinstance(snap, WeatherSnapshot)
    assert snap.weather_fill_multiplier == pytest.approx(1.0)
    assert snap.is_raining is False
