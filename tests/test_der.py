"""Tests for the PV + stationary-battery (DER) feature.

Covers the pure physics (der_catalog, pv_model, parse_epw_location), the
default-OFF reproducibility contract, weather-consistency, and the end-to-end
generation / multi-building / validation / web wiring.

PV reads the real EPW (the building-load stub does not cover it), and
data/stations is git-ignored — so EPW-dependent tests write a synthetic
full-year EPW into a temp V2B_WEATHER_CACHE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from v2b_syndata.der_catalog import resolve_battery, resolve_pv
from v2b_syndata.load_pipeline import weather as weather_mod
from v2b_syndata.load_pipeline.pv_model import pv_ac_series
from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO / "configs"
DEFAULT_STATION = "USA_TN_Nashville.Intl.AP.723270_TMYx"
NASH_LAT, NASH_LON, NASH_TZ = 36.12, -86.69, -6.0


# ── synthetic weather ──────────────────────────────────────────────────────

def _write_full_year_epw(path: Path, lat: float, lon: float, tz: float,
                         year: int = 2021) -> Path:
    """A valid EPW: LOCATION header (lat/lon/tz) + 8 header lines + a full
    non-leap year of hourly rows with constant daytime irradiance (so a PV
    curve's peak is purely geometry-driven → solar noon)."""
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    loc = f"LOCATION,Test,TN,USA,TMYx,723270,{lat},{lon},{tz},180.0"
    lines = [loc] + ["HEADER"] * 7
    for ts in idx:
        cols = ["0"] * 22
        cols[0] = str(year)
        cols[1], cols[2], cols[3] = str(ts.month), str(ts.day), str(ts.hour + 1)
        cols[6] = "20.0"            # dry-bulb
        cols[7], cols[8] = "5.0", "40.0"
        if 6 <= ts.hour <= 18:      # constant daytime irradiance
            cols[13] = "500"        # GHI
            cols[14] = "700"        # DNI
            cols[15] = "120"        # DHI
        cols[21] = "2.5"
        lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture()
def epw_cache(tmp_path, monkeypatch):
    """Point V2B_WEATHER_CACHE at a temp dir holding a synthetic Nashville EPW."""
    cache = tmp_path / "stations"
    cache.mkdir()
    _write_full_year_epw(cache / f"{DEFAULT_STATION}.epw", NASH_LAT, NASH_LON, NASH_TZ)
    monkeypatch.setenv("V2B_WEATHER_CACHE", str(cache))
    return cache


def _gen(out: Path, overrides=None, seed=0):
    # Pin a non-leap year so the synthetic EPW needs no Feb-29 injection.
    ov = {"sim_window.start": "2021-04-01"}
    ov.update(overrides or {})
    return generate("S01", seed=seed, output_dir=out, config_dir=CONFIG_DIR, cli_overrides=ov)


# ── der_catalog (pure) ─────────────────────────────────────────────────────

def test_resolve_pv_preset_and_override():
    spec = resolve_pv(pv_type="rooftop_medium", dc_capacity_kw=0.0,
                      module_type="standard", dc_ac_ratio=1.2, tilt_deg=10.0,
                      azimuth_deg=180.0, system_derate=0.86, albedo=0.2)
    assert spec["dc_capacity_kw"] == 100.0           # preset
    assert spec["ac_capacity_kw"] == pytest.approx(100.0 / 1.2, abs=1e-3)
    # explicit kW overrides the preset
    spec2 = resolve_pv(pv_type="rooftop_medium", dc_capacity_kw=333.0,
                       module_type="premium", dc_ac_ratio=1.2, tilt_deg=10.0,
                       azimuth_deg=180.0, system_derate=0.86, albedo=0.2)
    assert spec2["dc_capacity_kw"] == 333.0
    assert spec2["temp_coeff_per_c"] == -0.0030      # premium module


def test_resolve_pv_none_is_zero():
    spec = resolve_pv(pv_type="none", dc_capacity_kw=0.0,
                      module_type="standard", dc_ac_ratio=1.2, tilt_deg=10.0,
                      azimuth_deg=180.0, system_derate=0.86, albedo=0.2)
    assert spec["dc_capacity_kw"] == 0.0 and spec["pv_type"] == "none"


def test_resolve_battery_preset_and_override():
    b = resolve_battery(battery_type="lfp_4h", capacity_kwh=0.0,
                        power_kw=0.0, round_trip_efficiency=0.9, min_soc_pct=10.0,
                        max_soc_pct=95.0, initial_soc_pct=50.0)
    assert (b["capacity_kwh"], b["power_kw"]) == (400.0, 100.0)
    b2 = resolve_battery(battery_type="none", capacity_kwh=0.0,
                         power_kw=0.0, round_trip_efficiency=0.9, min_soc_pct=10.0,
                         max_soc_pct=95.0, initial_soc_pct=50.0)
    assert (b2["capacity_kwh"], b2["power_kw"]) == (0.0, 0.0)


# ── pv_model (pure) ────────────────────────────────────────────────────────

def _clearsky_day(year=2021, month=4, day=15):
    """One day of constant daytime irradiance, hourly."""
    idx = pd.date_range(f"{year}-{month:02d}-{day:02d}", periods=24, freq="h")
    ghi = np.where((idx.hour >= 6) & (idx.hour <= 18), 500.0, 0.0)
    dni = np.where((idx.hour >= 6) & (idx.hour <= 18), 700.0, 0.0)
    dhi = np.where((idx.hour >= 6) & (idx.hour <= 18), 120.0, 0.0)
    return pd.DataFrame({
        "global_horizontal_w_m2": ghi, "direct_normal_w_m2": dni,
        "diffuse_horizontal_w_m2": dhi, "dry_bulb_temp_c": 20.0,
    }, index=idx)


def _expected_solar_noon_hour(lat, lon, tz, n):
    b = 2 * np.pi * (n - 1) / 365
    eot = 229.18 * (0.000075 + 0.001868 * np.cos(b) - 0.032077 * np.sin(b)
                    - 0.014615 * np.cos(2 * b) - 0.040849 * np.sin(2 * b))
    return 12.0 - (lon - 15.0 * tz) / 15.0 - eot / 60.0


def test_pv_peak_near_solar_noon():
    wx = _clearsky_day()
    idx15 = pd.date_range("2021-04-15", periods=96, freq="15min")
    s = pv_ac_series(wx, idx15, lat_deg=NASH_LAT, lon_deg=NASH_LON, tz_hours=NASH_TZ,
                     dc_capacity_kw=100.0, ac_capacity_kw=1000.0, tilt_deg=10.0,
                     azimuth_deg=180.0, system_derate=0.86, temp_coeff_per_c=-0.0035,
                     noct_c=45.0, albedo=0.2)
    peak_ts = s.idxmax()
    peak_hour = peak_ts.hour + peak_ts.minute / 60 + 7.5 / 60  # tick midpoint
    expected = _expected_solar_noon_hour(NASH_LAT, NASH_LON, NASH_TZ, n=105)
    assert abs(peak_hour - expected) <= 0.25, f"peak {peak_hour:.2f} vs noon {expected:.2f}"


def test_pv_night_zero_and_ac_clip():
    wx = _clearsky_day()
    idx15 = pd.date_range("2021-04-15", periods=96, freq="15min")
    s = pv_ac_series(wx, idx15, lat_deg=NASH_LAT, lon_deg=NASH_LON, tz_hours=NASH_TZ,
                     dc_capacity_kw=100.0, ac_capacity_kw=50.0, tilt_deg=10.0,
                     azimuth_deg=180.0, system_derate=0.86, temp_coeff_per_c=-0.0035,
                     noct_c=45.0, albedo=0.2)
    assert s.max() <= 50.0 + 1e-9                       # AC clip respected
    night = s[(s.index.hour < 4) | (s.index.hour >= 22)]
    assert (night == 0.0).all()                        # zero at night


def test_pv_zero_capacity_is_zero():
    wx = _clearsky_day()
    idx15 = pd.date_range("2021-04-15", periods=96, freq="15min")
    s = pv_ac_series(wx, idx15, lat_deg=NASH_LAT, lon_deg=NASH_LON, tz_hours=NASH_TZ,
                     dc_capacity_kw=0.0, ac_capacity_kw=0.0, tilt_deg=10.0,
                     azimuth_deg=180.0, system_derate=0.86, temp_coeff_per_c=-0.0035,
                     noct_c=45.0, albedo=0.2)
    assert (s == 0.0).all()


# ── parse_epw_location ─────────────────────────────────────────────────────

def test_parse_epw_location(tmp_path):
    epw = _write_full_year_epw(tmp_path / "w.epw", NASH_LAT, NASH_LON, NASH_TZ)
    lat, lon, tz = weather_mod.parse_epw_location(epw)
    assert (lat, lon, tz) == (NASH_LAT, NASH_LON, NASH_TZ)


def test_parse_epw_location_bad_header(tmp_path):
    p = tmp_path / "bad.epw"
    p.write_text("NOTLOCATION,x\n" + "H\n" * 7)
    with pytest.raises(ValueError):
        weather_mod.parse_epw_location(p)
    p2 = tmp_path / "bad2.epw"
    p2.write_text("LOCATION,c,s,USA,TMYx,0,999.0,0.0,0.0,0.0\n" + "H\n" * 7)
    with pytest.raises(ValueError):  # latitude out of range
        weather_mod.parse_epw_location(p2)


# ── default-OFF reproducibility ────────────────────────────────────────────

def test_pv_disabled_default_is_zeros_no_epw(tmp_path, monkeypatch):
    """PV off (default) → all-zero curve, zero-capacity specs, and NO EPW read
    (works with an empty weather cache)."""
    monkeypatch.setenv("V2B_WEATHER_CACHE", str(tmp_path / "empty"))
    out = tmp_path / "off"
    _gen(out)
    pg = pd.read_csv(out / "pv_generation.csv")
    assert list(pg.columns) == ["datetime", "power_pv_kw"]
    assert (pg["power_pv_kw"] == 0.0).all()
    assert pd.read_csv(out / "pv.csv")["dc_capacity_kw"].iloc[0] == 0.0
    assert pd.read_csv(out / "battery.csv")["capacity_kwh"].iloc[0] == 0.0


def test_pv_does_not_change_other_csvs(tmp_path, epw_cache):
    """Enabling PV/battery must not perturb the other 7 CSVs (separate file,
    no RNG, building_load unchanged)."""
    off = tmp_path / "off"
    on = tmp_path / "on"
    _gen(off)
    _gen(on, overrides={"pv.pv_type": "rooftop_large", "battery.battery_type": "lfp_4h"})
    for name in ("building_load", "cars", "users", "chargers", "grid_prices",
                 "dr_events", "sessions"):
        a = (off / f"{name}.csv").read_bytes()
        b = (on / f"{name}.csv").read_bytes()
        assert a == b, f"{name}.csv changed when PV/battery enabled"


def test_pv_reproducible(tmp_path, epw_cache):
    a = tmp_path / "a"
    b = tmp_path / "b"
    ov = {"pv.dc_capacity_kw": 250.0}
    _gen(a, overrides=ov, seed=7)
    _gen(b, overrides=ov, seed=7)
    assert (a / "pv_generation.csv").read_bytes() == (b / "pv_generation.csv").read_bytes()


def test_pv_enabled_generates_curve(tmp_path, epw_cache):
    out = tmp_path / "on"
    _gen(out, overrides={"pv.pv_type": "rooftop_medium"})
    pg = pd.read_csv(out / "pv_generation.csv", parse_dates=["datetime"])
    assert pg["power_pv_kw"].sum() > 0
    spec = pd.read_csv(out / "pv.csv").iloc[0]
    assert pg["power_pv_kw"].max() <= float(spec["ac_capacity_kw"]) + 1e-6
    # peak is during the day
    peak_hour = pg.loc[pg["power_pv_kw"].idxmax(), "datetime"].hour
    assert 9 <= peak_hour <= 15


def test_validate_passes_with_pv(tmp_path, epw_cache):
    from v2b_syndata.validate import validate
    out = tmp_path / "on"
    _gen(out, overrides={"pv.pv_type": "carport", "battery.battery_type": "nmc_2h"})
    rep = validate(out)
    assert not rep.errors, rep.errors


# ── multi-building per-building ────────────────────────────────────────────

def test_multibuilding_per_building_pv(tmp_path, epw_cache):
    from v2b_syndata.multi_building import BuildingSpec, MultiConfig, generate_multi
    out = tmp_path / "mb"
    cfg = MultiConfig(buildings=[
        BuildingSpec(base_scenario="S01", seed=1, overrides={
            "sim_window.start": "2021-04-01", "pv.pv_type": "rooftop_medium",
            "battery.battery_type": "lfp_2h"}),
        BuildingSpec(base_scenario="S01", seed=2,
                     overrides={"sim_window.start": "2021-04-01"}),
    ], output_mode="shared")
    generate_multi(cfg, out, CONFIG_DIR)
    pv = pd.read_csv(out / "pv.csv")
    assert set(pv["building_id"]) == {0, 1}
    by_bid = pv.set_index("building_id")["dc_capacity_kw"]
    assert by_bid[0] == 100.0 and by_bid[1] == 0.0
    pg = pd.read_csv(out / "pv_generation.csv")
    assert "energy_kwh_pv" in pg.columns and "building_id" in pg.columns
    assert pg[pg.building_id == 0]["power_pv_kw"].sum() > 0
    assert pg[pg.building_id == 1]["power_pv_kw"].sum() == 0


# ── web exposure ───────────────────────────────────────────────────────────

def test_web_serves_pv_battery_knobs():
    sys.path.insert(0, str(REPO / "tools" / "web"))
    from app import app
    k = app.test_client().get("/api/knobs").get_json()
    assert "pv" in k and "battery" in k
    assert "pv_type" in k["pv"] and "dc_capacity_kw" in k["pv"]
    assert "battery_type" in k["battery"] and "capacity_kwh" in k["battery"]
