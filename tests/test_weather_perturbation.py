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
    out = weather.perturb_weather_frame(
        df, temp_offset_c=2.5, solar_scale=0.5, dewpoint_offset_c=1.0, wind_scale=0.5)
    assert list(out["dry_bulb_temp_c"]) == [12.5, 22.5]
    assert list(out["dew_point_temp_c"]) == [6.0, 7.0]            # +1°C dew-point
    assert list(out["global_horizontal_w_m2"]) == [0.0, 200.0]
    assert list(out["direct_normal_w_m2"]) == [0.0, 150.0]
    assert list(out["wind_speed_m_s"]) == [1.0, 1.5]             # ×0.5 wind
    # RH recomputed from the perturbed dry-bulb + dew-point (Magnus), in range
    rh = out["relative_humidity_pct"].to_numpy()
    assert list(rh) != [50.0, 60.0] and ((rh >= 0) & (rh <= 100)).all()
    expected = weather._rh_from_t_td(np.array([12.5, 22.5]), np.array([6.0, 7.0]))
    np.testing.assert_allclose(rh, expected, rtol=1e-9)
    # input not mutated
    assert list(df["dry_bulb_temp_c"]) == [10.0, 20.0]


def test_perturb_frame_noop_returns_same_object():
    df = pd.DataFrame({"dry_bulb_temp_c": [1.0], "global_horizontal_w_m2": [2.0],
                       "direct_normal_w_m2": [0.0], "diffuse_horizontal_w_m2": [0.0]})
    assert weather.perturb_weather_frame(df, 0.0, 1.0, 0.0, 1.0) is df


def test_perturb_solar_and_wind_clip_at_zero():
    df = pd.DataFrame({"dry_bulb_temp_c": [10.0], "dew_point_temp_c": [5.0],
                       "relative_humidity_pct": [70.0], "wind_speed_m_s": [3.0],
                       "global_horizontal_w_m2": [100.0],
                       "direct_normal_w_m2": [50.0], "diffuse_horizontal_w_m2": [10.0]})
    out = weather.perturb_weather_frame(df, 0.0, -1.0, 0.0, -1.0)  # negatives → clip 0
    assert (out[["global_horizontal_w_m2", "direct_normal_w_m2",
                 "diffuse_horizontal_w_m2", "wind_speed_m_s"]].to_numpy() >= 0).all()


# ── EPW-file transform == frame transform (the faithfulness invariant) ────────

def test_perturb_epw_file_noop_returns_input(tmp_path):
    epw = _write_epw(tmp_path / "w.epw")
    assert weather.perturb_epw_file(epw, tmp_path / "out.epw", 0.0, 1.0, 0.0, 1.0) == epw


def test_epw_perturb_matches_frame_perturb(tmp_path):
    """parse(perturb_epw(epw)) must equal perturb_frame(parse(epw)) for EVERY
    perturbed channel — i.e. what EnergyPlus simulates and what the export writes
    are identical (temp, dew-point, RH, solar, wind)."""
    epw = _write_epw(tmp_path / "w.epw")
    dT, ssc, dTd, wsc = 3.0, 0.8, 1.5, 0.7
    perturbed = weather.perturb_epw_file(epw, tmp_path / "p.epw", dT, ssc, dTd, wsc)
    from_file = weather.parse_epw_weather(perturbed, year=2021)
    from_frame = weather.perturb_weather_frame(
        weather.parse_epw_weather(epw, year=2021), dT, ssc, dTd, wsc)
    for col in ("dry_bulb_temp_c", "dew_point_temp_c", "relative_humidity_pct",
                "wind_speed_m_s", "global_horizontal_w_m2",
                "direct_normal_w_m2", "diffuse_horizontal_w_m2"):
        np.testing.assert_allclose(
            from_file[col].to_numpy(), from_frame[col].to_numpy(), rtol=1e-6, atol=1e-6,
            err_msg=f"EPW-input vs export transform diverged on {col}")
    # header preserved verbatim
    assert perturbed.read_text().splitlines()[0].startswith("LOCATION,Test")


# ── weather perturbation profiles ─────────────────────────────────────────────

def test_weather_profile_loader():
    from v2b_syndata.descriptor_loader import load_weather_profile
    assert load_weather_profile(CONFIG_DIR, "none") == {
        "temp_sigma_c": 0.0, "solar_sigma": 0.0, "dewpoint_sigma_c": 0.0, "wind_sigma": 0.0}
    mod = load_weather_profile(CONFIG_DIR, "moderate")
    assert mod["temp_sigma_c"] == 2.5 and mod["solar_sigma"] == 0.05
    assert mod["dewpoint_sigma_c"] == 1.5 and mod["wind_sigma"] == 0.10
    # strength is monotone across presets
    sigs = [load_weather_profile(CONFIG_DIR, p)["temp_sigma_c"]
            for p in ("none", "slight", "moderate", "strong")]
    assert sigs == sorted(sigs) and sigs[0] == 0.0 and sigs[-1] > 0
    with pytest.raises(KeyError):
        load_weather_profile(CONFIG_DIR, "nonexistent")


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
