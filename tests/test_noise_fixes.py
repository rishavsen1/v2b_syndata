"""Tests for V2 jitter-bound fixes (C4 + D6 preservation under max noise)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _gen(tmp_path: Path, overrides: dict) -> Path:
    out = tmp_path / "out"
    generate(
        scenario_id="S01", seed=42, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=overrides,
        noise_profile_override=None,
    )
    return out


def test_jitter_preserves_temporal_ordering(tmp_path: Path):
    """High arrival_time_jitter_min must not produce arrival >= departure (C4)."""
    out = _gen(tmp_path, {"noise.arrival_time_jitter_min": 60.0})
    sess = pd.read_csv(out / "sessions.csv")
    dur = (pd.to_datetime(sess["departure"]) - pd.to_datetime(sess["arrival"])).dt.total_seconds()
    assert (dur > 0).all(), "non-positive duration after jitter"
    assert (dur >= 15 * 60).all(), "sessions shorter than 15 min after jitter"


def test_jitter_keeps_sessions_in_window(tmp_path: Path):
    """Backward jitter must not push arrival before sim_window.start."""
    out = _gen(tmp_path, {"noise.arrival_time_jitter_min": 60.0})
    sess = pd.read_csv(out / "sessions.csv")
    bl = pd.read_csv(out / "building_load.csv")
    bl_start = pd.to_datetime(bl["datetime"].iloc[0])
    assert (pd.to_datetime(sess["arrival"]) >= bl_start).all(), \
        "session arrives before sim_window.start after jitter"


def test_soc_jitter_preserves_d6(tmp_path: Path):
    """High soc_arrival_jitter_pct must keep arrival_soc < required_soc (D6)
    and >= min_allowed_soc (floor)."""
    out = _gen(tmp_path, {"noise.soc_arrival_jitter_pct": 0.30})
    sess = pd.read_csv(out / "sessions.csv")
    assert (sess["arrival_soc"] < sess["required_soc_at_depart"]).all(), \
        "arrival_soc >= required_soc after jitter"
    cars = pd.read_csv(out / "cars.csv")
    merged = sess.merge(cars[["car_id", "min_allowed_soc"]], on="car_id")
    assert (merged["arrival_soc"] >= merged["min_allowed_soc"]).all(), \
        "arrival_soc < min_allowed_soc after jitter"


def test_validate_passes_under_max_arrival_jitter(tmp_path: Path):
    """C4 fix must propagate through to validate() passing."""
    from v2b_syndata.validate import validate
    out = _gen(tmp_path, {"noise.arrival_time_jitter_min": 60.0})
    rep = validate(out, strict=False)
    # C4 and C6 must pass; D5 may still flag (arrival shift changes overlap/energy budget).
    serious = [e for e in rep.errors if e.startswith(("C4", "C6"))]
    assert not serious, f"C-class regression: {serious}"


def test_validate_passes_under_max_soc_jitter(tmp_path: Path):
    """D6 fix must propagate through to validate() passing."""
    from v2b_syndata.validate import validate
    out = _gen(tmp_path, {"noise.soc_arrival_jitter_pct": 0.30})
    rep = validate(out, strict=False)
    d6 = [e for e in rep.errors if e.startswith("D6")]
    assert not d6, f"D6 regression: {d6}"


def _assert_d5_holds(out: Path) -> None:
    sess = pd.read_csv(out / "sessions.csv")
    cars = pd.read_csv(out / "cars.csv")
    chargers = pd.read_csv(out / "chargers.csv")
    if len(sess) == 0:
        return
    max_rate = float(chargers["max_rate_kw"].max())
    merged = sess.merge(cars[["car_id", "capacity_kwh"]], on="car_id")
    dwell_hr = (
        pd.to_datetime(merged["departure"]) - pd.to_datetime(merged["arrival"])
    ).dt.total_seconds() / 3600.0
    required_kwh = (
        (merged["required_soc_at_depart"] - merged["arrival_soc"]) / 100.0
        * merged["capacity_kwh"]
    )
    available_kwh = max_rate * dwell_hr * 1.05
    bad = required_kwh > available_kwh + 1e-6
    assert not bad.any(), f"{int(bad.sum())} sessions violate D5 post-jitter"


def test_d5_held_under_arrival_jitter(tmp_path: Path):
    out = _gen(tmp_path, {"noise.arrival_time_jitter_min": 60.0})
    _assert_d5_holds(out)


def test_d5_held_under_soc_jitter(tmp_path: Path):
    out = _gen(tmp_path, {"noise.soc_arrival_jitter_pct": 0.30})
    _assert_d5_holds(out)


def test_d5_held_under_combined_jitter(tmp_path: Path):
    out = _gen(tmp_path, {
        "noise.arrival_time_jitter_min": 60.0,
        "noise.soc_arrival_jitter_pct": 0.30,
    })
    _assert_d5_holds(out)


def test_d5_enforcement_stats_populated(tmp_path: Path):
    """Manifest reports counts of truncated/relaxed/dropped sessions."""
    import json
    out = _gen(tmp_path, {
        "noise.arrival_time_jitter_min": 60.0,
        "noise.soc_arrival_jitter_pct": 0.30,
    })
    m = json.loads((out / "manifest.json").read_text())
    assert "noise" in m and "d5_enforcement" in m["noise"]
    s = m["noise"]["d5_enforcement"]
    assert s["max_charger_rate_kw"] > 0
    assert s["total_input_sessions"] >= s["total_output_sessions"]
    for k in ("truncated_count", "d7_relaxed_count", "dropped_count"):
        assert s[k] >= 0


def test_d5_no_enforcement_when_clean(tmp_path: Path):
    """No session jitter → no D5 enforcement block in manifest."""
    import json
    out = _gen(tmp_path, {})  # clean
    m = json.loads((out / "manifest.json").read_text())
    if "noise" in m and "d5_enforcement" in m.get("noise", {}):
        s = m["noise"]["d5_enforcement"]
        assert s["truncated_count"] == 0
        assert s["dropped_count"] == 0
