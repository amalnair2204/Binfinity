"""Tests for feedback/job_queue.py."""
from __future__ import annotations

import pytest

from feedback.job_queue import DEDUPE_PREFIX, QUEUE_KEY, RetrainJob, RetrainJobQueue


@pytest.fixture
def queue(fake_redis):
    return RetrainJobQueue(fake_redis)


@pytest.mark.asyncio
async def test_enqueue_adds_to_redis_list(queue, fake_redis):
    ok = await queue.enqueue("bin", "BIN-001", "test reason")
    assert ok is True
    length = await fake_redis.llen(QUEUE_KEY)
    assert length == 1


@pytest.mark.asyncio
async def test_enqueue_returns_true_first_time(queue):
    ok = await queue.enqueue("bin", "BIN-001", "first")
    assert ok is True


@pytest.mark.asyncio
async def test_enqueue_returns_false_duplicate(queue):
    await queue.enqueue("bin", "BIN-001", "first")
    ok = await queue.enqueue("bin", "BIN-001", "second")
    assert ok is False


@pytest.mark.asyncio
async def test_enqueue_dedup_key_set(queue, fake_redis):
    await queue.enqueue("zone", "Z-01", "reason")
    val = await fake_redis.get(f"{DEDUPE_PREFIX}zone:Z-01")
    assert val is not None


@pytest.mark.asyncio
async def test_dequeue_returns_retrain_job(queue, fake_redis):
    await queue.enqueue("bin", "BIN-002", "trigger")
    job = await queue.dequeue(timeout=1)
    assert job is not None
    assert isinstance(job, RetrainJob)
    assert job.target_type == "bin"
    assert job.target_id == "BIN-002"
    assert job.trigger_reason == "trigger"


@pytest.mark.asyncio
async def test_size_returns_queue_length(queue, fake_redis):
    assert await queue.size() == 0
    await queue.enqueue("bin", "BIN-001", "r1")
    await queue.enqueue("bin", "BIN-002", "r2")
    assert await queue.size() == 2
