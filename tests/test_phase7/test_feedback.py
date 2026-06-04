"""Tests for routing/feedback.py."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from routing.feedback import FeedbackHandler


@pytest.fixture
def feedback(fake_redis, mock_dispatcher, mock_truck_manager, mock_db_pool):
    pool, _ = mock_db_pool
    return FeedbackHandler(fake_redis, pool, mock_dispatcher, mock_truck_manager)


@pytest.fixture
def feedback_with_ingestion(fake_redis, mock_dispatcher, mock_truck_manager, mock_db_pool):
    routing_pool, _ = mock_db_pool
    ingestion_conn = MagicMock()
    ingestion_conn.execute = AsyncMock(return_value=None)
    ingestion_cm = MagicMock()
    ingestion_cm.__aenter__ = AsyncMock(return_value=ingestion_conn)
    ingestion_cm.__aexit__ = AsyncMock(return_value=None)
    ingestion_pool = MagicMock()
    ingestion_pool.acquire = MagicMock(return_value=ingestion_cm)
    return (
        FeedbackHandler(
            fake_redis, routing_pool, mock_dispatcher, mock_truck_manager, ingestion_pool
        ),
        ingestion_conn,
    )


# ---------------------------------------------------------------------------
# on_bin_emptied — Redis state changes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_bin_emptied_removes_from_bins_flagged(fake_redis, feedback):
    await fake_redis.sadd("bins:flagged", b"B001")
    await feedback.on_bin_emptied("T1", "B001", 80.0)
    members = await fake_redis.smembers("bins:flagged")
    assert b"B001" not in members


@pytest.mark.asyncio
async def test_on_bin_emptied_removes_from_known_flagged(fake_redis, feedback):
    await fake_redis.sadd("dispatch:known_flagged", b"B001")
    await feedback.on_bin_emptied("T1", "B001", 80.0)
    members = await fake_redis.smembers("dispatch:known_flagged")
    assert b"B001" not in members


# ---------------------------------------------------------------------------
# on_bin_emptied — ML feedback queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_bin_emptied_pushes_ml_feedback(fake_redis, feedback):
    await feedback.on_bin_emptied("T1", "B001", 80.0)
    length = await fake_redis.llen("ml:feedback:queue")
    assert length == 1
    raw = await fake_redis.rpop("ml:feedback:queue")
    payload = json.loads(raw)
    assert payload["feedback_type"] == "emptied"
    assert payload["bin_id"] == "B001"
    assert payload["truck_id"] == "T1"
    assert payload["actual_liters"] == 80.0


@pytest.mark.asyncio
async def test_ml_queue_increments_per_emptied(fake_redis, feedback):
    await feedback.on_bin_emptied("T1", "B001", 50.0)
    await feedback.on_bin_emptied("T1", "B002", 60.0)
    length = await fake_redis.llen("ml:feedback:queue")
    assert length == 2


# ---------------------------------------------------------------------------
# on_bin_emptied — ingestion DB flag clear
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_bin_emptied_clears_ingestion_flag(feedback_with_ingestion):
    handler, ingestion_conn = feedback_with_ingestion
    await handler.on_bin_emptied("T1", "B001", 80.0)
    ingestion_conn.execute.assert_called_once()
    sql, bin_id_arg = ingestion_conn.execute.call_args[0]
    assert "flagged_for_collection" in sql
    assert bin_id_arg == "B001"


@pytest.mark.asyncio
async def test_on_bin_emptied_no_ingestion_call_without_pool(feedback, mock_db_pool):
    _, routing_conn = mock_db_pool
    routing_conn.execute.reset_mock()
    await feedback.on_bin_emptied("T1", "B001", 80.0)
    # routing DB pool should not be called (it's not the ingestion pool)
    routing_conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# on_dump_completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_dump_completed_calls_record_dump(mock_truck_manager, feedback):
    await feedback.on_dump_completed("T1", "YARD1")
    mock_truck_manager.record_dump.assert_called_once_with("T1", "YARD1")


@pytest.mark.asyncio
async def test_on_dump_completed_sets_en_route_status(mock_truck_manager, feedback):
    await feedback.on_dump_completed("T1", "YARD1")
    mock_truck_manager.update_status.assert_called_once_with("T1", "en_route")


@pytest.mark.asyncio
async def test_on_dump_completed_pushes_ml_feedback(fake_redis, feedback):
    await feedback.on_dump_completed("T1", "YARD1", dump_liters=500.0)
    length = await fake_redis.llen("ml:feedback:queue")
    assert length == 1
    raw = await fake_redis.rpop("ml:feedback:queue")
    payload = json.loads(raw)
    assert payload["feedback_type"] == "dump"
    assert payload["truck_id"] == "T1"
    assert payload["yard_id"] == "YARD1"
    assert payload["liters_dumped"] == 500.0


@pytest.mark.asyncio
async def test_on_dump_completed_uses_current_load_if_not_provided(
    mock_truck_manager, feedback
):
    mock_truck_manager.get_current_load.return_value = 750.0
    await feedback.on_dump_completed("T1", "YARD1")
    mock_truck_manager.get_current_load.assert_called_once_with("T1")
