"""Tests for feedback/model_registry.py."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from feedback.model_registry import REGISTRY_KEY, REGISTRY_META_KEY, FeedbackModelRegistry


@pytest.fixture
def registry(fake_redis):
    return FeedbackModelRegistry(fake_redis)


@pytest.mark.asyncio
async def test_register_stores_path(registry, fake_redis):
    await registry.register("prophet_BIN-001", "/models/prophet_BIN-001.pkl")
    val = await fake_redis.hget(REGISTRY_KEY, "prophet_BIN-001")
    assert val is not None
    path = val.decode() if isinstance(val, bytes) else val
    assert path == "/models/prophet_BIN-001.pkl"


@pytest.mark.asyncio
async def test_get_retrieves_path(registry):
    await registry.register("gbm_BIN-001", "/models/gbm_BIN-001.pkl")
    path = await registry.get("gbm_BIN-001")
    assert path == "/models/gbm_BIN-001.pkl"


@pytest.mark.asyncio
async def test_get_meta_retrieves_trained_at(registry):
    trained = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    await registry.register("prophet_BIN-001", "/models/prophet_BIN-001.pkl", trained)
    meta = await registry.get_meta("prophet_BIN-001")
    assert meta is not None
    assert meta["path"] == "/models/prophet_BIN-001.pkl"
    assert "trained_at" in meta
    assert "2026-06-03" in meta["trained_at"]


@pytest.mark.asyncio
async def test_list_all_returns_all_entries(registry):
    await registry.register("prophet_BIN-001", "/models/p1.pkl")
    await registry.register("gbm_Z-01", "/models/g1.pkl")
    entries = await registry.list_all()
    assert "prophet_BIN-001" in entries
    assert "gbm_Z-01" in entries
    assert entries["prophet_BIN-001"] == "/models/p1.pkl"


@pytest.mark.asyncio
async def test_remove_deletes_entry(registry, fake_redis):
    await registry.register("prophet_BIN-001", "/models/p1.pkl")
    await registry.remove("prophet_BIN-001")
    path = await registry.get("prophet_BIN-001")
    assert path is None
    meta = await registry.get_meta("prophet_BIN-001")
    assert meta is None
