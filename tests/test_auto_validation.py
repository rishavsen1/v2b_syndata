"""Automatic post-generation validation: manifest block, D5 strictness,
multi/batch aggregation, and strict_validate raising.

Covers the hook added to runner.generate() plus the validation_summary rollups
in multi_building / batch. These are structural checks — the CSV outputs are
unchanged (byte-identity is covered by the reproducibility/determinism suites);
here we only assert the new manifest keys and the tightened D5 envelope.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from v2b_syndata.validate import ValidationError, ValidationReport, validate

# ── 1. manifest always carries a validation block ────────────────────────────

def test_generate_manifest_has_validation_block(fast_generate):
    out_dir, manifest = fast_generate()
    assert "validation" in manifest
    v = manifest["validation"]
    for key in ("passed", "n_errors", "n_warnings", "errors", "warnings",
                "noise_applied"):
        assert key in v, f"missing validation key {key}"
    assert isinstance(v["passed"], bool)
    assert isinstance(v["n_errors"], int)
    assert v["noise_applied"] is False  # clean profile by default
    # Same block is persisted to disk (not just returned in-memory).
    on_disk = json.loads((out_dir / "manifest.json").read_text())
    assert on_disk["validation"] == v


def test_clean_run_validation_passes(fast_generate):
    _out, manifest = fast_generate()
    assert manifest["validation"]["passed"] is True
    assert manifest["validation"]["n_errors"] == 0


def test_noise_applied_flag_set_for_noisy_profile(fast_generate):
    """A profile with non-zero jitter records noise_applied=True regardless of
    whether the invariants pass — the flag is the noise-contract signal."""
    _out, manifest = fast_generate(noise_profile="realistic_noise")
    assert manifest["validation"]["noise_applied"] is True


# ── 2. D5 is now strict (headroom 1.0, not 1.05) ─────────────────────────────

def _write_minimal_output(d: Path, *, arrival_soc: float, required_soc: float,
                          duration_sec: int, capacity_kwh: float,
                          max_rate_kw: float) -> None:
    """Write the smallest CSV set validate() needs to exercise D5.

    Only D5 correctness matters here; other invariants are satisfied loosely so
    the D5 branch is reached (validate short-circuits only on schema errors).
    """
    dts = pd.date_range("2020-04-01", periods=4, freq="15min")
    bl = pd.DataFrame({
        "datetime": dts, "power_flex_kw": [1.0] * 4,
        "power_inflex_kw": [1.0] * 4, "power_kw": [2.0] * 4,
    })
    bl.to_csv(d / "building_load.csv", index=False)
    pd.DataFrame({
        "datetime": dts, "price_per_kwh": [0.1] * 4,
        "type": ["off-peak"] * 4,
    }).to_csv(d / "grid_prices.csv", index=False)
    pd.DataFrame({
        "car_id": [1], "capacity_kwh": [capacity_kwh],
        "min_allowed_soc": [0.0], "max_allowed_soc": [100.0],
        "battery_class": ["m3_75"],
    }).to_csv(d / "cars.csv", index=False)
    pd.DataFrame({
        "car_id": [1], "region": ["us_west"], "phi": [0.5], "kappa": [0.5],
        "delta_km": [10.0], "negotiation_type": ["type_i"], "w1": [0.5],
        "w2": [0.5],
    }).to_csv(d / "users.csv", index=False)
    pd.DataFrame({
        "charger_id": [1], "directionality": ["unidirectional"],
        "min_rate_kw": [0.0], "max_rate_kw": [max_rate_kw],
    }).to_csv(d / "chargers.csv", index=False)
    pd.DataFrame({
        "event_id": [], "start": [], "end": [], "magnitude_kw": [],
        "notified_at": [],
    }).to_csv(d / "dr_events.csv", index=False)
    arr = dts[0]
    dep = arr + pd.Timedelta(seconds=duration_sec)
    pd.DataFrame({
        "session_id": [1], "car_id": [1], "building_id": [0],
        "arrival": [arr], "departure": [dep], "duration_sec": [duration_sec],
        "arrival_soc": [arrival_soc],
        "required_soc_at_depart": [required_soc],
        "previous_day_external_use_soc": [10.0],
    }).to_csv(d / "sessions.csv", index=False)
    pd.DataFrame({
        "datetime": dts, "power_pv_kw": [0.0] * 4,
    }).to_csv(d / "pv_generation.csv", index=False)
    pd.DataFrame({
        "pv_id": [], "pv_type": [], "dc_capacity_kw": [], "ac_capacity_kw": [],
        "dc_ac_ratio": [], "tilt_deg": [], "azimuth_deg": [], "module_type": [],
        "system_derate": [], "temp_coeff_per_c": [], "noct_c": [], "albedo": [],
    }).to_csv(d / "pv.csv", index=False)
    pd.DataFrame({
        "battery_id": [], "battery_type": [], "capacity_kwh": [], "power_kw": [],
        "round_trip_efficiency": [], "min_soc_pct": [], "max_soc_pct": [],
        "initial_soc_pct": [],
    }).to_csv(d / "battery.csv", index=False)
    (d / "manifest.json").write_text(json.dumps({"knob_resolution": {}}))


def _d5_errors(rep: ValidationReport) -> list[str]:
    return [e for e in rep.errors if e.startswith("D5")]


def test_d5_strict_flags_need_just_above_avail(tmp_path):
    """need = 1.02 * avail now FAILS (old 1.05 slack would have passed).

    avail = max_rate * dur_hr = 10 kW * 1 h = 10 kWh.
    need  = (r-a)/100 * cap = 20.4/100 * 50 = 10.2 kWh = 1.02 * avail.
    """
    d = tmp_path / "d5fail"
    d.mkdir()
    _write_minimal_output(
        d, arrival_soc=0.0, required_soc=20.4, duration_sec=3600,
        capacity_kwh=50.0, max_rate_kw=10.0,
    )
    rep = validate(d, strict=False)
    d5 = _d5_errors(rep)
    assert d5, f"expected a D5 error; got errors={rep.errors}"


def test_d5_strict_passes_when_need_within_avail(tmp_path):
    """need = 0.98 * avail still passes (reachable within the dwell)."""
    d = tmp_path / "d5ok"
    d.mkdir()
    _write_minimal_output(
        d, arrival_soc=0.0, required_soc=19.6, duration_sec=3600,
        capacity_kwh=50.0, max_rate_kw=10.0,
    )
    rep = validate(d, strict=False)
    assert not _d5_errors(rep), f"unexpected D5 error: {rep.errors}"


# ── strict_validate raises ────────────────────────────────────────────────────

def test_strict_validate_raises_on_error(monkeypatch, fast_generate, tmp_path):
    """strict_validate=True raises ValidationError when validate finds errors,
    but only AFTER writing the manifest (so the failure is still recorded)."""
    from v2b_syndata import runner

    # Force validate() to report an error regardless of the real output.
    def _fake_validate(output_dir, strict=False):  # noqa: ARG001
        rep = ValidationReport()
        rep.errors.append("D5: synthetic failure for test")
        return rep

    monkeypatch.setattr(runner, "validate", _fake_validate, raising=False)
    # Patch the lazily-imported symbol in the validate module namespace too.
    import v2b_syndata.validate as vmod
    monkeypatch.setattr(vmod, "validate", _fake_validate)

    out = tmp_path / "strict_out"
    with pytest.raises(ValidationError, match="synthetic failure"):
        runner.generate(
            scenario_id="S01", seed=42, output_dir=out,
            config_dir=Path(__file__).resolve().parents[1] / "configs",
            cli_overrides={
                "sim_window.mode": "custom",
                "sim_window.start": "2020-04-01",
                "sim_window.custom_end": "2020-04-08",
            },
            strict_validate=True,
        )
    # Manifest was written before the raise and records the failure.
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["validation"]["passed"] is False
    assert manifest["validation"]["n_errors"] >= 1


# NOTE: multi-building / batch validation_summary aggregation is tested in
# tests/test_multi_building.py and tests/test_batch.py where the EnergyPlus/
# weather stubs and fast-window fixtures already live.


def test_validation_summary_helper_rolls_up():
    """Unit-test the aggregation helper directly (no generation needed)."""
    from v2b_syndata.multi_building import _validation_summary

    manifests: list[dict[str, Any]] = [
        {"validation": {"passed": True, "n_errors": 0, "errors": []}},
        {"validation": {"passed": False, "n_errors": 2,
                        "errors": ["D5: x", "D6: y"]}},
    ]
    labels = [{"building_id": 0, "seed": 1}, {"building_id": 1, "seed": 2}]
    vs = _validation_summary(manifests, labels)
    assert vs["n_units"] == 2
    assert vs["n_passed"] == 1
    assert vs["n_failed"] == 1
    assert vs["total_errors"] == 2
    assert vs["failed_units"][0]["building_id"] == 1
    assert vs["failed_units"][0]["errors"] == ["D5: x", "D6: y"]
