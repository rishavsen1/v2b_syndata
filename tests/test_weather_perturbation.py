"""Weather-realization faithfulness: the perturbation EnergyPlus consumes and
the one the export writes are the SAME transform, the `clean` profile yields a
deterministic load = f(weather), and per-sample weather draws drive the load.

The EPW-perturb + parity + clean-determinism layers need no EnergyPlus (the
conftest load stub carries a +3%/°C sensitivity); the physical coupling is
additionally asserted end-to-end under `real_energyplus` in the webapp/browser
suites.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from v2b_syndata.load_pipeline import weather
from v2b_syndata.runner import generate

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


def _write_epw(path: Path) -> Path:
    """Minimal EPW: 8 header lines + a year of hourly rows with a diurnal
    temperature + daytime solar pattern (cols 6, 13/14/15, 21 populated)."""
    idx = pd.date_range("2021-06-01", "2021-06-04", freq="h", inclusive="left")
    lines = ["LOCATION,Test,-,-,-,0,0.0,0.0,0.0,0.0"] + ["HEADER"] * 7
    for ts in idx:
        cols = ["0"] * 22
        cols[0] = "2021"
        cols[1], cols[2], cols[3] = str(ts.month), str(ts.day), str(ts.hour + 1)
        cols[6] = f"{15.0 + 8.0 * np.sin((ts.hour - 6) / 24 * 2 * np.pi):.1f}"  # dry-bulb
        cols[7], cols[8] = "5.0", "50.0"
        if 6 <= ts.hour <= 20:
            cols[13] = cols[14] = cols[15] = "400"
        cols[21] = "2.5"
        lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    return path


# ── the shared frame transform ───────────────────────────────────────────────

def test_perturb_frame_temp_and_solar():
    df = pd.DataFrame({
        "dry_bulb_temp_c": [10.0, 20.0],
        "dew_point_temp_c": [5.0, 6.0],
        "relative_humidity_pct": [50.0, 60.0],
        "wind_speed_m_s": [2.0, 3.0],
        "global_horizontal_w_m2": [0.0, 400.0],
        "direct_normal_w_m2": [0.0, 300.0],
        "diffuse_horizontal_w_m2": [0.0, 100.0],
    })
    out = weather.perturb_weather_frame(df, temp_offset_c=2.5, solar_scale=0.5)
    assert list(out["dry_bulb_temp_c"]) == [12.5, 22.5]
    assert list(out["global_horizontal_w_m2"]) == [0.0, 200.0]
    assert list(out["direct_normal_w_m2"]) == [0.0, 150.0]
    # untouched channels
    assert list(out["relative_humidity_pct"]) == [50.0, 60.0]
    # input not mutated
    assert list(df["dry_bulb_temp_c"]) == [10.0, 20.0]


def test_perturb_frame_noop_returns_same_object():
    df = pd.DataFrame({"dry_bulb_temp_c": [1.0], "global_horizontal_w_m2": [2.0],
                       "direct_normal_w_m2": [0.0], "diffuse_horizontal_w_m2": [0.0]})
    assert weather.perturb_weather_frame(df, 0.0, 1.0) is df


def test_perturb_solar_clips_at_zero():
    df = pd.DataFrame({"dry_bulb_temp_c": [10.0], "global_horizontal_w_m2": [100.0],
                       "direct_normal_w_m2": [50.0], "diffuse_horizontal_w_m2": [10.0]})
    out = weather.perturb_weather_frame(df, 0.0, -1.0)  # negative scale → clip 0
    assert (out[["global_horizontal_w_m2", "direct_normal_w_m2",
                 "diffuse_horizontal_w_m2"]].to_numpy() >= 0).all()


# ── EPW-file transform == frame transform (the faithfulness invariant) ────────

def test_perturb_epw_file_noop_returns_input(tmp_path):
    epw = _write_epw(tmp_path / "w.epw")
    assert weather.perturb_epw_file(epw, tmp_path / "out.epw", 0.0, 1.0) == epw


def test_epw_perturb_matches_frame_perturb(tmp_path):
    """parse(perturb_epw(epw)) must equal perturb_frame(parse(epw)) — i.e. what
    EnergyPlus simulates and what the export writes are identical."""
    epw = _write_epw(tmp_path / "w.epw")
    dT, ssc = 3.0, 0.8
    perturbed = weather.perturb_epw_file(epw, tmp_path / "p.epw", dT, ssc)
    from_file = weather.parse_epw_weather(perturbed, year=2021)
    from_frame = weather.perturb_weather_frame(
        weather.parse_epw_weather(epw, year=2021), dT, ssc)
    for col in ("dry_bulb_temp_c", "global_horizontal_w_m2",
                "direct_normal_w_m2", "diffuse_horizontal_w_m2"):
        np.testing.assert_allclose(
            from_file[col].to_numpy(), from_frame[col].to_numpy(), rtol=1e-9, atol=1e-9,
            err_msg=f"EPW-input vs export transform diverged on {col}")
    # header preserved verbatim
    assert perturbed.read_text().splitlines()[0].startswith("LOCATION,Test")


# ── A: the `clean` profile makes load a deterministic f(weather) ──────────────

def test_clean_profile_load_is_seed_independent(tmp_path):
    """Under clean, building_load no longer carries the per-seed ±5/±3 jitter —
    it's the exact f(weather) the model should learn."""
    a = tmp_path / "a"; b = tmp_path / "b"
    generate("S01", 1, a, CONFIG_DIR)            # clean is the S01 default
    generate("S01", 999, b, CONFIG_DIR)
    assert (a / "building_load.csv").read_bytes() == (b / "building_load.csv").read_bytes()


def test_noisy_profile_load_is_seed_dependent(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    generate("S01", 1, a, CONFIG_DIR, noise_profile_override="tmyx_stochastic")
    generate("S01", 2, b, CONFIG_DIR, noise_profile_override="tmyx_stochastic")
    assert (a / "building_load.csv").read_bytes() != (b / "building_load.csv").read_bytes()


# ── B: a weather offset perturbs BOTH the (stub) load and the export ──────────

def test_weather_offset_couples_load_and_is_logged(tmp_path):
    base = tmp_path / "base"; warm = tmp_path / "warm"
    m0 = generate("S01", 7, base, CONFIG_DIR)
    m1 = generate("S01", 7, warm, CONFIG_DIR,
                  cli_overrides={"building_load.weather_temp_offset_c": 5.0})
    # logged in the manifest
    assert m1["knob_resolution"]["building_load.weather_temp_offset_c"]["value"] == 5.0
    # the (stubbed) flex/HVAC load responds to the warmer weather
    bl0 = pd.read_csv(base / "building_load.csv")
    bl1 = pd.read_csv(warm / "building_load.csv")
    assert bl1["power_flex_kw"].sum() > bl0["power_flex_kw"].sum()
