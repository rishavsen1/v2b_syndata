"""Validator invariant tests — construct violations, assert validator catches.

Each invariant from validate_spec.md gets a synthetic violation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate


@pytest.fixture(scope="module")
def baseline_dir(tmp_path_factory, config_dir) -> Path:
    out = tmp_path_factory.mktemp("baseline")
    generate("S01", seed=42, output_dir=out, config_dir=config_dir)
    return out


def test_baseline_passes(baseline_dir):
    rep = validate(baseline_dir)
    assert rep.passed, "S01 baseline failed: " + "; ".join(rep.errors)


def _copy_dir(src: Path, dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            (dst / f.name).write_bytes(f.read_bytes())
    return dst


def test_a1_missing_csv(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    (d / "cars.csv").unlink()
    rep = validate(d)
    assert any("A1" in e for e in rep.errors)


def test_a2_extra_column(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "users.csv")
    df["extra"] = 0
    df.to_csv(d / "users.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("A2" in e for e in rep.errors)


def test_a5_invalid_battery_class(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "cars.csv")
    df.loc[0, "battery_class"] = "model_x_999"
    df.to_csv(d / "cars.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("A5" in e for e in rep.errors)


def test_b1_user_car_id_mismatch(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "users.csv")
    df.loc[0, "car_id"] = 99999
    df.to_csv(d / "users.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("B1" in e or "B4" in e for e in rep.errors)


def test_b3_duplicate_car_id(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "cars.csv")
    df.loc[0, "car_id"] = df.loc[1, "car_id"]
    df.to_csv(d / "cars.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("B3" in e for e in rep.errors)


def test_c1_non_monotone_datetime(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "building_load.csv")
    # Swap two rows
    df.iloc[[0, 5]] = df.iloc[[5, 0]].values
    df.to_csv(d / "building_load.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("C1" in e for e in rep.errors)


def test_c4_arrival_after_departure(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "sessions.csv")
    if len(df) == 0:
        pytest.skip("baseline has no sessions")
    df.loc[0, "arrival"], df.loc[0, "departure"] = df.loc[0, "departure"], df.loc[0, "arrival"]
    df.to_csv(d / "sessions.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("C4" in e or "C5" in e or "C6" in e for e in rep.errors)


def test_c7_overlapping_sessions(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "sessions.csv")
    if len(df) < 2:
        pytest.skip("baseline has < 2 sessions")
    # Find two same-car sessions
    car_groups = df.groupby("car_id")
    target_car = next((c for c, g in car_groups if len(g) >= 2), None)
    if target_car is None:
        pytest.skip("no car with ≥ 2 sessions")
    g = df[df["car_id"] == target_car].sort_values("arrival")
    idx_a, idx_b = g.index[0], g.index[1]
    df.loc[idx_a, "departure"] = df.loc[idx_b, "departure"]  # extend to overlap
    df.loc[idx_a, "duration_sec"] = int((pd.to_datetime(df.loc[idx_a, "departure"]) -
                                          pd.to_datetime(df.loc[idx_a, "arrival"])).total_seconds())
    df.to_csv(d / "sessions.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("C7" in e for e in rep.errors)


def test_d6_required_above_arrival(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "sessions.csv")
    if len(df) == 0:
        pytest.skip("baseline has no sessions")
    # Force required <= arrival on first session
    df.loc[0, "required_soc_at_depart"] = float(df.loc[0, "arrival_soc"])
    df.to_csv(d / "sessions.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("D6" in e for e in rep.errors), f"D6 not caught: {rep.errors}"


def test_d7_required_above_min_depart(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "sessions.csv")
    if len(df) == 0:
        pytest.skip("baseline has no sessions")
    # min_depart_soc default is 0.80 → 80%. Force required to be just below floor.
    # Pick a row where arrival is low enough that required can drop below 80
    # without colliding with D6 (required > arrival). Otherwise inject after
    # raising arrival downward too.
    target_idx = None
    for i in range(len(df)):
        if float(df.loc[i, "arrival_soc"]) < 70:
            target_idx = i
            break
    if target_idx is None:
        df.loc[0, "arrival_soc"] = 50.0
        target_idx = 0
    df.loc[target_idx, "required_soc_at_depart"] = 75.0  # below 80% floor, above arrival
    df.to_csv(d / "sessions.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("D7" in e for e in rep.errors), f"D7 not caught: {rep.errors}"


def test_required_soc_invariants_on_s01(baseline_dir):
    """S01/seed=42 generated output: D6 and D7 hold for every session."""
    df = pd.read_csv(baseline_dir / "sessions.csv")
    if len(df) == 0:
        pytest.skip("baseline has no sessions")
    with (baseline_dir / "manifest.json").open() as f:
        manifest = json.load(f)
    mds_pct = float(manifest["knob_resolution"]["user_behavior.min_depart_soc"]["value"]) * 100.0
    # D6
    assert (df["required_soc_at_depart"] > df["arrival_soc"]).all(), \
        "D6 violated on baseline: required_soc_at_depart not > arrival_soc"
    # D7
    assert (df["required_soc_at_depart"] >= mds_pct).all(), \
        f"D7 violated on baseline: required_soc_at_depart < min_depart_soc*100={mds_pct}"


def test_d1_invalid_soc_bounds(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "cars.csv")
    df.loc[0, "min_allowed_soc"] = 100
    df.loc[0, "max_allowed_soc"] = 50
    df.to_csv(d / "cars.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("D1" in e for e in rep.errors)


def test_e3_bidirectional_with_zero_min(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "chargers.csv")
    bi_idx = df[df["directionality"] == "bidirectional"].index
    if len(bi_idx) == 0:
        pytest.skip("no bidirectional chargers")
    df.loc[bi_idx[0], "min_rate_kw"] = 0
    df.to_csv(d / "chargers.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("E3" in e for e in rep.errors)


def test_g1_phi_out_of_range(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    df = pd.read_csv(d / "users.csv")
    df.loc[0, "phi"] = 1.5
    df.to_csv(d / "users.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("G1" in e for e in rep.errors)


def test_h4_dr_program_none_with_events(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    # Inject events where program=none
    bl = pd.read_csv(d / "building_load.csv")
    fake = pd.DataFrame([{
        "event_id": 1,
        "start": bl["datetime"].iloc[10],
        "end": bl["datetime"].iloc[20],
        "magnitude_kw": 100.0,
        "notified_at": bl["datetime"].iloc[2],
    }])
    fake.to_csv(d / "dr_events.csv", index=False, lineterminator="\n")
    rep = validate(d)
    assert any("H4" in e for e in rep.errors)


def test_i1_missing_manifest(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    (d / "manifest.json").unlink()
    rep = validate(d)
    assert any("I1" in e for e in rep.errors)


def test_i3_sha256_mismatch(baseline_dir, tmp_path):
    d = _copy_dir(baseline_dir, tmp_path / "case")
    # Tamper with a CSV after manifest is written
    p = d / "users.csv"
    content = p.read_text()
    p.write_text(content + "\n")  # append blank line
    rep = validate(d)
    # Either sha256 mismatch or row count mismatch
    assert any("I2" in e or "I3" in e for e in rep.errors)


def test_i4_all_knobs_in_manifest(baseline_dir):
    with (baseline_dir / "manifest.json").open() as f:
        manifest = json.load(f)
    from v2b_syndata.knob_loader import all_knob_paths, load_knob_registry
    reg = load_knob_registry(Path(__file__).resolve().parent.parent / "configs" / "knobs.yaml")
    res = manifest["knob_resolution"]
    for path in all_knob_paths(reg):
        assert path in res
        assert res[path]["source"] in ("explicit", "default") or res[path]["source"].startswith("descriptor:")
