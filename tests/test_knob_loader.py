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


# ---------- deep-channel (region_distributions) override tests ----------


def test_deep_override_cli_resolves(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    cli = {"user_behavior.region_distributions.stable_commuter.dwell.lambda": 12.0}
    resolved = resolve_knobs(reg, {}, {}, cli)
    path = "user_behavior.region_distributions.stable_commuter.dwell.lambda"
    assert resolved.get(path) == 12.0
    assert resolved.source(path) == "explicit"


def test_deep_override_scenario_resolves(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    sc = {"user_behavior.region_distributions.flexible_local.arrival.mu": 10.5}
    resolved = resolve_knobs(reg, {}, sc, {})
    path = "user_behavior.region_distributions.flexible_local.arrival.mu"
    assert resolved.get(path) == 10.5
    assert resolved.source(path) == "explicit"


def test_deep_override_cli_beats_scenario(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    path = "user_behavior.region_distributions.stable_commuter.arrival.mu"
    sc = {path: 10.0}
    cli = {path: 11.0}
    resolved = resolve_knobs(reg, {}, sc, cli)
    assert resolved.get(path) == 11.0


def test_deep_override_descriptor_calibration_source_propagates(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    desc = {
        "user_behavior.region_distributions.stable_commuter.arrival.mu":
            (8.7, "calibration:acn_data_2019_2021_20260506"),
    }
    resolved = resolve_knobs(reg, desc, {}, {})
    path = "user_behavior.region_distributions.stable_commuter.arrival.mu"
    assert resolved.get(path) == 8.7
    assert resolved.source(path) == "calibration:acn_data_2019_2021_20260506"


def test_deep_override_out_of_range_rejected(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    cli = {"user_behavior.region_distributions.stable_commuter.dwell.lambda": 999.0}
    with pytest.raises(KnobValidationError, match="outside range"):
        resolve_knobs(reg, {}, {}, cli)


def test_deep_override_unknown_leaf_rejected(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    cli = {"user_behavior.region_distributions.stable_commuter.dwell.bogus": 1.0}
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {}, cli)


def test_deep_override_too_short_path_rejected(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    cli = {"user_behavior.region_distributions.dwell.lambda": 5.0}
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {}, cli)


def test_deep_override_explicit_beats_calibration(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    path = "user_behavior.region_distributions.stable_commuter.dwell.lambda"
    desc = {path: (9.2, "calibration:acn_data_2019_2021_20260506")}
    cli = {path: 12.0}
    resolved = resolve_knobs(reg, desc, {}, cli)
    assert resolved.get(path) == 12.0
    assert resolved.source(path) == "explicit"


@pytest.mark.parametrize("knob_path,bad_value,error_substr", [
    ("ev_fleet.ev_count", "not_an_int", "expected int"),
    ("ev_fleet.ev_count", True, "expected int"),
    ("ev_fleet.ev_count", -1, "outside range"),
    ("ev_fleet.ev_count", 999, "outside range"),
    ("user_behavior.min_depart_soc", 1.5, "outside range"),
    ("user_behavior.min_depart_soc", "0.8", "expected float"),
    ("user_behavior.min_depart_soc", True, "expected float"),
    ("ev_fleet.battery_mix", [0.5, 0.5, 0.5, 0.5], "must sum to 1"),
    ("ev_fleet.battery_mix", [1.0, 0.0, 0.0], "expected 4 components"),
    ("ev_fleet.battery_mix", "not_a_list", "expected list"),
    ("ev_fleet.battery_mix", [-0.1, 0.4, 0.4, 0.3], "non-negative"),
    ("ev_fleet.battery_heterogeneity", "invalid", "not in"),
    ("ev_fleet.battery_heterogeneity", 42, "not in"),
    ("utility_rate.peak_window", [25, 30], "outside range"),
    ("utility_rate.peak_window", "not_a_vec", "length-2"),
    ("utility_rate.peak_window", [6], "length-2"),
    ("sim_window.weekdays_only", "true", "expected bool"),
    ("sim_window.weekdays_only", 1, "expected bool"),
    ("building_load.tmyx_station", 42, "expected string path"),
])
def test_check_type_and_range_rejects_malformed(config_dir, knob_path, bad_value, error_substr):
    """Single parametrized sweep covers every type-check branch of
    ``_check_type_and_range`` (sub-85% line gap from COVERAGE_REPORT §6)."""
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError, match=error_substr):
        resolve_knobs(
            registry=reg,
            descriptor_values={},
            scenario_overrides={knob_path: bad_value},
            cli_overrides={},
        )


def test_deep_channel_rejects_non_numeric():
    """Deep-override values must be numeric."""
    from v2b_syndata.knob_loader import _check_deep_range
    with pytest.raises(KnobValidationError, match="numeric"):
        _check_deep_range(
            "user_behavior.region_distributions.stable_commuter.dwell.lambda",
            "not_a_float",
        )


def test_deep_channel_rejects_unknown_leaf():
    from v2b_syndata.knob_loader import _check_deep_range
    with pytest.raises(KnobValidationError, match="not in"):
        _check_deep_range(
            "user_behavior.region_distributions.stable_commuter.unknown.param",
            0.5,
        )


def test_deep_channel_rejects_out_of_range():
    from v2b_syndata.knob_loader import _check_deep_range
    with pytest.raises(KnobValidationError, match="outside range"):
        _check_deep_range(
            "user_behavior.region_distributions.stable_commuter.dwell.lambda",
            9999.0,
        )


def test_parse_overrides_rejects_malformed_string():
    with pytest.raises(KnobValidationError, match="not in form"):
        parse_overrides(["malformed_no_equals"])
