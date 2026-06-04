"""Redis cache layer tests — uses fakeredis, no live Redis required."""
from __future__ import annotations

from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from ingestion.cache import BinStateCache
from ingestion.schemas import BinState

TS = datetime(2025, 1, 6, 8, 0, tzinfo=timezone.utc)


def make_state(**kwargs) -> BinState:
    defaults = dict(
        bin_id="BIN-0001",
        last_updated=TS,
        fill_pct=67.4,
        fill_liters=80.9,
        status="operational",
        battery_mv=3720,
        consecutive_fault_ticks=0,
        flagged_for_collection=False,
        last_emptied=None,
    )
    defaults.update(kwargs)
    return BinState(**defaults)


@pytest.fixture
async def cache():
    fake_redis = fakeredis.aioredis.FakeRedis()
    c = BinStateCache.__new__(BinStateCache)
    c._redis = fake_redis
    yield c
    await fake_redis.aclose()


# ── state serialisation ───────────────────────────────────────────────────────

async def test_set_and_get_bin_state(cache: BinStateCache):
    state = make_state()
    await cache.set_bin_state(state)
    retrieved = await cache.get_bin_state("BIN-0001")
    assert retrieved is not None
    assert retrieved.bin_id == "BIN-0001"
    assert abs(retrieved.fill_pct - 67.4) < 0.01


async def test_get_nonexistent_returns_none(cache: BinStateCache):
    result = await cache.get_bin_state("BIN-XXXX")
    assert result is None


async def test_state_roundtrip_preserves_all_fields(cache: BinStateCache):
    state = make_state(
        fill_pct=85.0, status="pending_collection",
        flagged_for_collection=True, consecutive_fault_ticks=0
    )
    await cache.set_bin_state(state)
    out = await cache.get_bin_state("BIN-0001")
    assert out.status == "pending_collection"
    assert out.flagged_for_collection


# ── sorted set: bins:by_fill ──────────────────────────────────────────────────

async def test_by_fill_score_matches_fill_pct(cache: BinStateCache):
    state = make_state(fill_pct=72.5)
    await cache.set_bin_state(state)
    score = await cache._redis.zscore("bins:by_fill", "BIN-0001")
    assert abs(score - 72.5) < 0.01


async def test_by_fill_updated_on_second_set(cache: BinStateCache):
    await cache.set_bin_state(make_state(fill_pct=50.0))
    await cache.set_bin_state(make_state(fill_pct=90.0))
    score = await cache._redis.zscore("bins:by_fill", "BIN-0001")
    assert abs(score - 90.0) < 0.01


# ── set: bins:flagged ─────────────────────────────────────────────────────────

async def test_flagged_bin_added_to_flagged_set(cache: BinStateCache):
    state = make_state(fill_pct=90.0, flagged_for_collection=True, status="pending_collection")
    await cache.set_bin_state(state)
    members = await cache._redis.smembers("bins:flagged")
    assert b"BIN-0001" in members


async def test_unflagged_bin_not_in_flagged_set(cache: BinStateCache):
    state = make_state(fill_pct=50.0, flagged_for_collection=False)
    await cache.set_bin_state(state)
    members = await cache._redis.smembers("bins:flagged")
    assert b"BIN-0001" not in members


async def test_clearing_flag_removes_from_set(cache: BinStateCache):
    await cache.set_bin_state(make_state(flagged_for_collection=True))
    await cache.set_bin_state(make_state(flagged_for_collection=False))
    members = await cache._redis.smembers("bins:flagged")
    assert b"BIN-0001" not in members


# ── set: bins:faulted ─────────────────────────────────────────────────────────

async def test_faulted_bin_added_to_faulted_set(cache: BinStateCache):
    state = make_state(status="sensor_fault", consecutive_fault_ticks=2)
    await cache.set_bin_state(state)
    members = await cache._redis.smembers("bins:faulted")
    assert b"BIN-0001" in members


async def test_clearing_fault_removes_from_faulted_set(cache: BinStateCache):
    await cache.set_bin_state(make_state(status="sensor_fault"))
    await cache.set_bin_state(make_state(status="operational"))
    members = await cache._redis.smembers("bins:faulted")
    assert b"BIN-0001" not in members


# ── additional method coverage ─────────────────────────────────────────────────

async def test_get_flagged_bins_returns_ids(cache: BinStateCache):
    await cache.set_bin_state(make_state(bin_id="BIN-0001", flagged_for_collection=True))
    await cache.set_bin_state(make_state(bin_id="BIN-0002", flagged_for_collection=False))
    flagged = await cache.get_flagged_bins()
    assert "BIN-0001" in flagged
    assert "BIN-0002" not in flagged


async def test_get_faulted_bins_returns_ids(cache: BinStateCache):
    await cache.set_bin_state(make_state(bin_id="BIN-0001", status="sensor_fault"))
    await cache.set_bin_state(make_state(bin_id="BIN-0002", status="operational"))
    faulted = await cache.get_faulted_bins()
    assert "BIN-0001" in faulted
    assert "BIN-0002" not in faulted


async def test_get_all_bin_states_returns_all(cache: BinStateCache):
    await cache.set_bin_state(make_state(bin_id="BIN-0001", fill_pct=55.0))
    await cache.set_bin_state(make_state(bin_id="BIN-0002", fill_pct=75.0))
    all_states = await cache.get_all_bin_states()
    ids = {s.bin_id for s in all_states}
    assert "BIN-0001" in ids
    assert "BIN-0002" in ids


async def test_get_all_bin_states_empty_returns_empty_list(cache: BinStateCache):
    all_states = await cache.get_all_bin_states()
    assert all_states == []
