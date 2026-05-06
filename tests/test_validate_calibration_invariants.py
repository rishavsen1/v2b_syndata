"""Tests for validate.py G5/G5b/I4-inverse/S2 calibration-related invariants.

These exercise validate functions with synthesized manifest dicts; no
generation needed.
"""
from __future__ import annotations

from v2b_syndata.validate import (
    ValidationReport,
    _check_g5_calibration_consistency,
    _check_i,
    _check_soft,
    _is_valid_source,
)


def _axes():
    return [
        {"name": "stable_commuter", "freq": [0.85, 1.0], "consist": [0.75, 1.0],
         "dist_km": [40, 80], "weight": 0.5},
        {"name": "flexible_local", "freq": [0.70, 0.95], "consist": [0.50, 0.80],
         "dist_km": [5, 15], "weight": 0.5},
    ]


def _base_resolution(axes=None, deep=None, calibrated=False):
    """Build a minimal manifest knob_resolution dict for validator tests."""
    res = {}
    res["user_behavior.axes_distribution"] = {
        "value": axes if axes is not None else _axes(),
        "source": "descriptor:fake_pop",
    }
    src = "calibration:acn_data_2019_2021_20260506" if calibrated else "default"
    if deep:
        for path, val in deep.items():
            res[path] = {"value": val, "source": src}
    return res


def test_g5_orphan_region_distribution_blocks():
    rep = ValidationReport()
    res = _base_resolution(deep={
        "user_behavior.region_distributions.NOPE.arrival.mu": 9.0,
    }, calibrated=True)
    _check_g5_calibration_consistency(rep, {"knob_resolution": res})
    assert any("G5:" in e for e in rep.errors), rep.errors


def test_g5b_warns_only_when_calibration_metadata_present():
    """Calibration source present + region missing → warning. No calibration source → silent."""
    # Case A: calibrated, missing flexible_local
    rep = ValidationReport()
    res = _base_resolution(deep={
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 9.0,
    }, calibrated=True)
    _check_g5_calibration_consistency(rep, {"knob_resolution": res})
    assert any("G5b" in w and "flexible_local" in w for w in rep.warnings), rep.warnings
    assert not rep.errors

    # Case B: no calibration source → silent on missing regions
    rep2 = ValidationReport()
    res2 = _base_resolution()  # no deep paths, no calibration
    _check_g5_calibration_consistency(rep2, {"knob_resolution": res2})
    assert not any("G5b" in w for w in rep2.warnings), rep2.warnings


def test_g5_clean_when_all_regions_calibrated():
    rep = ValidationReport()
    res = _base_resolution(deep={
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 9.0,
        "user_behavior.region_distributions.flexible_local.arrival.mu": 10.0,
    }, calibrated=True)
    _check_g5_calibration_consistency(rep, {"knob_resolution": res})
    assert not rep.errors
    assert not rep.warnings


def test_is_valid_source_accepts_calibration():
    assert _is_valid_source("explicit")
    assert _is_valid_source("default")
    assert _is_valid_source("descriptor:foo")
    assert _is_valid_source("calibration:acn_data_2019_2021_20260506")
    assert not _is_valid_source("garbage")
    assert not _is_valid_source("")


def test_i4_inverse_unknown_path_caught(tmp_path):
    """Synthetic manifest in tmp dir; _check_i raises on unknown deep-path leaf."""
    import json
    out = tmp_path / "out"
    out.mkdir()
    res = _base_resolution()
    # Inject a bogus deep path that matches the prefix but has unknown leaf.
    res["user_behavior.region_distributions.stable_commuter.dwell.bogus"] = {
        "value": 5.0, "source": "calibration:test",
    }
    # Need every registry knob present too. Let _check_i still find missing
    # knobs separately; we just test the inverse-check behavior here.
    manifest = {
        "scenario_id": "S01", "seed": 42,
        "knob_overrides": {}, "knob_resolution": res,
        "noise_profile": "clean", "generator_git_sha": "0", "generator_version": "x",
        "generated_at": "2026-05-06T00:00:00.000000Z",
        "csv_row_counts": {n: 0 for n in (
            "building_load", "cars", "users", "chargers",
            "grid_prices", "dr_events", "sessions",
        )},
        "csv_sha256": {n: "0" for n in (
            "building_load", "cars", "users", "chargers",
            "grid_prices", "dr_events", "sessions",
        )},
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    rep = ValidationReport()
    _check_i(rep, out)
    matched = [e for e in rep.errors if "bogus" in e]
    assert matched, f"I4 inverse did not catch unknown leaf. errors={rep.errors}"


def test_i4_inverse_metadata_keys_caught(tmp_path):
    """Metadata leak into knob_resolution must trip I4 inverse."""
    import json
    out = tmp_path / "out"
    out.mkdir()
    res = _base_resolution()
    res["user_behavior.region_distributions.stable_commuter.arrival.n_samples"] = {
        "value": 412, "source": "calibration:test",
    }
    manifest = {
        "scenario_id": "S01", "seed": 42,
        "knob_overrides": {}, "knob_resolution": res,
        "noise_profile": "clean", "generator_git_sha": "0", "generator_version": "x",
        "generated_at": "2026-05-06T00:00:00.000000Z",
        "csv_row_counts": {n: 0 for n in (
            "building_load", "cars", "users", "chargers",
            "grid_prices", "dr_events", "sessions",
        )},
        "csv_sha256": {n: "0" for n in (
            "building_load", "cars", "users", "chargers",
            "grid_prices", "dr_events", "sessions",
        )},
    }
    (out / "manifest.json").write_text(json.dumps(manifest))
    rep = ValidationReport()
    _check_i(rep, out)
    matched = [e for e in rep.errors if "n_samples" in e]
    assert matched, f"I4 inverse did not catch metadata leak. errors={rep.errors}"


def test_s2_warning_when_calibration_present():
    """S2 placeholder warning fires when any calibration: source present."""
    rep = ValidationReport()
    res = _base_resolution(deep={
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 9.0,
    }, calibrated=True)
    # Build minimal csvs dict — _check_soft handles missing sessions/chargers gracefully.
    import pandas as pd
    csvs = {
        "sessions": pd.DataFrame(columns=["session_id", "car_id", "duration_sec",
                                            "arrival_soc", "required_soc_at_depart"]),
        "chargers": pd.DataFrame(columns=["max_rate_kw"]),
        "cars": pd.DataFrame(columns=["car_id", "capacity_kwh"]),
    }
    _check_soft(rep, csvs, {"knob_resolution": res})
    assert any("S2" in w and "Step 5.5" in w for w in rep.warnings), rep.warnings


def test_s2_silent_when_no_calibration():
    rep = ValidationReport()
    res = _base_resolution()  # no calibration sources
    import pandas as pd
    csvs = {
        "sessions": pd.DataFrame(columns=["session_id", "car_id", "duration_sec",
                                            "arrival_soc", "required_soc_at_depart"]),
        "chargers": pd.DataFrame(columns=["max_rate_kw"]),
        "cars": pd.DataFrame(columns=["car_id", "capacity_kwh"]),
    }
    _check_soft(rep, csvs, {"knob_resolution": res})
    assert not any("S2" in w for w in rep.warnings)
