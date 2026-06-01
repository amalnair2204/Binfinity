import json
import pytest
from pathlib import Path
from scripts.generate_bins import generate_bins

def test_generates_correct_count():
    bins = generate_bins(200)
    assert len(bins) == 200

def test_bin_ids_unique_and_formatted():
    bins = generate_bins(200)
    ids = [b["bin_id"] for b in bins]
    assert ids[0] == "BIN-0001"
    assert ids[199] == "BIN-0200"
    assert len(set(ids)) == 200

def test_all_required_fields_present():
    bins = generate_bins(5)
    required = {"bin_id", "lat", "lng", "zone", "base_fill_rate",
                "capacity_liters", "current_fill_pct", "battery_mv"}
    for b in bins:
        assert required.issubset(b.keys()), f"Missing fields: {required - b.keys()}"

def test_zones_are_valid():
    valid_zones = {"residential", "commercial", "park", "transit_hub"}
    bins = generate_bins(200)
    for b in bins:
        assert b["zone"] in valid_zones

def test_capacity_matches_zone():
    expected = {"residential": 120.0, "commercial": 240.0, "park": 80.0, "transit_hub": 120.0}
    bins = generate_bins(200)
    for b in bins:
        assert b["capacity_liters"] == expected[b["zone"]]

def test_initial_fill_within_range():
    bins = generate_bins(200)
    for b in bins:
        assert 0.0 <= b["current_fill_pct"] <= 60.0

def test_coordinates_within_dubai_spread():
    bins = generate_bins(200)
    for b in bins:
        assert 25.0 <= b["lat"] <= 25.5
        assert 55.0 <= b["lng"] <= 55.5

def test_deterministic_with_same_seed():
    bins_a = generate_bins(10, seed=42)
    bins_b = generate_bins(10, seed=42)
    assert bins_a == bins_b

def test_different_seeds_give_different_results():
    bins_a = generate_bins(10, seed=42)
    bins_b = generate_bins(10, seed=99)
    assert bins_a != bins_b
