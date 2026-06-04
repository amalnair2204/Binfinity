"""Tests for feedback/consumer.py."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feedback.consumer import FeedbackConsumer, FeedbackEvent, QUEUE_KEY
from feedback.job_queue import RetrainJobQueue


def _make_prediction_row(bin_id="BIN-001", hours=2.0):
    return {
        "predicted_at": datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc),
        "hours_until_critical": hours,
        "fill_pct_current": 75.0,
        "model_used": "ensemble",
        "confidence": 0.9,
        "zone_id": "Z-01",
    }


def _make_event(bin_id="BIN-001"):
    return FeedbackEvent(
        bin_id=bin_id,
        emptied_at=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def consumer(fake_redis, mock_db_pool):
    pool, _ = mock_db_pool
    job_queue = RetrainJobQueue(fake_redis)
    return FeedbackConsumer(fake_redis, pool, job_queue)


@pytest.mark.asyncio
async def test_process_event_calls_insert_accuracy_record(fake_redis, mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(return_value=_make_prediction_row())
    job_queue = RetrainJobQueue(fake_redis)
    consumer = FeedbackConsumer(fake_redis, pool, job_queue)

    with patch("feedback.consumer.insert_accuracy_record", new_callable=AsyncMock) as mock_insert, \
         patch("feedback.consumer.update_redis_accuracy_cache", new_callable=AsyncMock):
        await consumer.process_event(_make_event())
        mock_insert.assert_called_once()
        record = mock_insert.call_args[0][1]
        assert record.bin_id == "BIN-001"
        assert record.absolute_error_hours >= 0


@pytest.mark.asyncio
async def test_process_event_enqueues_retrain_when_mae_above_threshold(
    fake_redis, mock_db_pool
):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(return_value=_make_prediction_row())
    job_queue = RetrainJobQueue(fake_redis)
    consumer = FeedbackConsumer(fake_redis, pool, job_queue)

    # Pre-populate Redis with MAE above threshold
    await fake_redis.setex("ml:accuracy:BIN-001:n_events_7d", 3600, b"10")
    await fake_redis.setex("ml:accuracy:BIN-001:mae_7d", 3600, b"5.0")

    with patch("feedback.consumer.insert_accuracy_record", new_callable=AsyncMock), \
         patch("feedback.consumer.update_redis_accuracy_cache", new_callable=AsyncMock):
        await consumer.process_event(_make_event())

    from feedback.job_queue import QUEUE_KEY as Q
    depth = await fake_redis.llen(Q)
    assert depth >= 1


@pytest.mark.asyncio
async def test_process_event_no_prediction_returns_early(consumer, mock_db_pool):
    _, conn = mock_db_pool
    conn.fetchrow = AsyncMock(return_value=None)

    with patch("feedback.consumer.insert_accuracy_record", new_callable=AsyncMock) as mock_insert:
        await consumer.process_event(_make_event("BIN-GHOST"))
        mock_insert.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_payload_skipped_without_crash(fake_redis, mock_db_pool):
    pool, _ = mock_db_pool
    job_queue = RetrainJobQueue(fake_redis)
    consumer = FeedbackConsumer(fake_redis, pool, job_queue)

    await fake_redis.lpush(QUEUE_KEY, b"not_valid_json{{{")

    task = asyncio.create_task(consumer.start())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert consumer._errors >= 1
    assert consumer._processed == 0


@pytest.mark.asyncio
async def test_consumer_processes_multiple_events(fake_redis, mock_db_pool):
    pool, conn = mock_db_pool
    conn.fetchrow = AsyncMock(return_value=_make_prediction_row())
    job_queue = RetrainJobQueue(fake_redis)
    consumer = FeedbackConsumer(fake_redis, pool, job_queue)

    import json

    events = [
        {"bin_id": f"BIN-{i:03d}", "emptied_at": "2026-06-03T10:00:00+00:00"}
        for i in range(3)
    ]
    for ev in events:
        await fake_redis.lpush(QUEUE_KEY, json.dumps(ev).encode())

    with patch("feedback.consumer.insert_accuracy_record", new_callable=AsyncMock), \
         patch("feedback.consumer.update_redis_accuracy_cache", new_callable=AsyncMock):
        task = asyncio.create_task(consumer.start())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert consumer._processed == 3
