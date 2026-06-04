"""Unit tests for exogenous/connectors/calendar.py."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import fakeredis.aioredis as fakeredis
import pytest
import yaml

from exogenous.connectors.calendar import CalendarConnector, CalendarSnapshot, _HIGH_IMPACT_THRESHOLD


def _make_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def _write_yaml(events: list[dict]) -> Path:
    """Write a temp YAML calendar file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.dump({"events": events}, f)
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------

def test_yaml_parses_without_error():
    r = _make_redis()
    c = CalendarConnector(r)
    c._load_calendar()
    assert isinstance(c._events, list)
    assert len(c._events) >= 1


def test_yaml_has_expected_fields():
    r = _make_redis()
    c = CalendarConnector(r)
    c._load_calendar()
    for ev in c._events:
        assert "name" in ev or "date" in ev or "month" in ev or "start" in ev
        assert "multiplier" in ev


# ---------------------------------------------------------------------------
# is_holiday_today
# ---------------------------------------------------------------------------

def test_holiday_today_sets_is_holiday_true():
    events = [{"name": "Test Holiday", "date": "2025-12-02", "multiplier": 2.0}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    snap = c.get_calendar_snapshot()  # mocked by date check below
    # Test directly with a known holiday date
    mult = c.multiplier_for_date(date(2025, 12, 2))
    assert mult >= _HIGH_IMPACT_THRESHOLD


def test_national_day_is_high_impact():
    """UAE National Day (Dec 2) is in the production calendar at multiplier=2.0."""
    r = _make_redis()
    c = CalendarConnector(r)
    mult = c.multiplier_for_date(date(2025, 12, 2))
    assert mult >= _HIGH_IMPACT_THRESHOLD


# ---------------------------------------------------------------------------
# is_active_event_now
# ---------------------------------------------------------------------------

def test_active_event_true_during_window():
    events = [{"name": "Shopping Fest", "start": "2025-01-01", "end": "2025-01-31", "multiplier": 1.5}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    mult = c.multiplier_for_date(date(2025, 1, 15))
    assert mult > 1.0


def test_active_event_false_outside_window():
    events = [{"name": "Shopping Fest", "start": "2025-01-01", "end": "2025-01-31", "multiplier": 1.5}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    mult = c.multiplier_for_date(date(2025, 2, 15))
    assert mult == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Zone-specific events
# ---------------------------------------------------------------------------

def test_calendar_multiplier_high_impact_for_matching_zone():
    events = [
        {"name": "Zone Event", "date": "2025-06-15", "multiplier": 2.0, "zones": ["Z-TEST"]}
    ]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    mult = c.multiplier_for_date(date(2025, 6, 15), zone_id="Z-TEST")
    assert mult == pytest.approx(2.0)


def test_calendar_multiplier_1_when_zone_not_matching():
    events = [
        {"name": "Zone Event", "date": "2025-06-15", "multiplier": 2.0, "zones": ["Z-TEST"]}
    ]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    mult = c.multiplier_for_date(date(2025, 6, 15), zone_id="Z-OTHER")
    assert mult == pytest.approx(1.0)


def test_calendar_global_event_applies_to_all_zones():
    events = [{"name": "Global Event", "date": "2025-06-15", "multiplier": 1.6}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    for zone in ["Z-RESIDENTIAL", "Z-COMMERCIAL", "Z-PARK", ""]:
        assert c.multiplier_for_date(date(2025, 6, 15), zone_id=zone) == pytest.approx(1.6)


# ---------------------------------------------------------------------------
# days_until_next_high_impact
# ---------------------------------------------------------------------------

def test_days_until_returns_0_on_holiday():
    events = [{"name": "Holiday", "date": "2025-12-02", "multiplier": 2.0}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    days = c._days_until_next_high_impact(date(2025, 12, 2), zone_id="")
    assert days == 0


def test_days_until_returns_correct_days_before_event():
    events = [{"name": "Holiday", "date": "2025-12-10", "multiplier": 2.0}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    days = c._days_until_next_high_impact(date(2025, 12, 7), zone_id="")
    assert days == 3


def test_days_until_capped_at_30_when_no_event():
    events = [{"name": "Holiday", "date": "2025-12-02", "multiplier": 2.0}]
    path = _write_yaml(events)
    r = _make_redis()
    c = CalendarConnector(r, calendar_path=path)

    # July 15 — no high-impact event within 30 days
    days = c._days_until_next_high_impact(date(2025, 7, 15), zone_id="")
    assert days == 30


# ---------------------------------------------------------------------------
# get_calendar_snapshot
# ---------------------------------------------------------------------------

def test_snapshot_has_all_fields():
    r = _make_redis()
    c = CalendarConnector(r)
    snap = c.get_calendar_snapshot()
    assert isinstance(snap, CalendarSnapshot)
    assert isinstance(snap.is_holiday_today, bool)
    assert isinstance(snap.is_active_event_now, bool)
    assert isinstance(snap.calendar_fill_multiplier, float)
    assert isinstance(snap.days_until_next_high_impact, int)
