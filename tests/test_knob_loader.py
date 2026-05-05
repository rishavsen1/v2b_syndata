"""Tests for the knob registry + resolution chain."""
from __future__ import annotations

import pytest

from v2b_syndata.knob_loader import (
    KnobValidationError,
    load_knob_registry,
    parse_overrides,
    resolve_knobs,
)


def test_load_registry_has_expected_buckets(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    paths = list(reg.keys())
    for expected in ("ev_fleet.ev_count", "user_behavior.axes_distribution",
                     "utility_rate.tariff_type", "noise.profile"):
        assert expected in paths


def test_resolution_priority_cli_beats_descriptor(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    descriptor_values = {"ev_fleet.ev_count": (10, "fake_pop")}
    cli = {"ev_fleet.ev_count": 30}
    resolved = resolve_knobs(reg, descriptor_values, {}, cli)
    assert resolved.get("ev_fleet.ev_count") == 30
    assert resolved.source("ev_fleet.ev_count") == "explicit"


def test_resolution_descriptor_beats_default(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    descriptor_values = {"ev_fleet.ev_count": (10, "fake_pop")}
    resolved = resolve_knobs(reg, descriptor_values, {}, {})
    assert resolved.get("ev_fleet.ev_count") == 10
    assert resolved.source("ev_fleet.ev_count") == "descriptor:fake_pop"


def test_resolution_default_used_when_no_override(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    resolved = resolve_knobs(reg, {}, {}, {})
    assert resolved.get("ev_fleet.ev_count") == 20
    assert resolved.source("ev_fleet.ev_count") == "default"


def test_resolution_scenario_overrides_beats_descriptor(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    descriptor_values = {"ev_fleet.ev_count": (10, "fake_pop")}
    resolved = resolve_knobs(reg, descriptor_values, {"ev_fleet.ev_count": 5}, {})
    assert resolved.get("ev_fleet.ev_count") == 5
    assert resolved.source("ev_fleet.ev_count") == "explicit"


def test_range_validation(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {"ev_fleet.ev_count": 9999}, {})


def test_categorical_validation(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {"utility_rate.tariff_type": "bogus"}, {})


def test_simplex_must_sum_to_one(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {"ev_fleet.battery_mix": [0.5, 0.5, 0.5, 0.5]}, {})


def test_unknown_override_path_rejected(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {}, {"nonexistent.knob": 1})


def test_parse_overrides_yaml_value():
    out = parse_overrides(["utility_rate.peak_window=[14, 19]", "ev_fleet.ev_count=10"])
    assert out["utility_rate.peak_window"] == [14, 19]
    assert out["ev_fleet.ev_count"] == 10


def test_parse_overrides_rejects_malformed():
    with pytest.raises(KnobValidationError):
        parse_overrides(["badform"])
