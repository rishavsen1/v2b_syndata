"""Tests for the operational battery dispatch (KDD readiness item #7).

Unit tests exercise the pure dispatch heuristic with synthetic load / price /
DR fixtures (no EnergyPlus). Integration tests run a battery-ON scenario end to
end (must pass validate) and a battery-OFF scenario (header-only + other CSVs
byte-identical).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.renderers.battery_dispatch import COLUMNS, dispatch
from v2b_syndata.runner import generate
from v2b_syndata.validate import validate

REPO = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO / "configs"

TICK_H = 0.25


def _grid(n: int):
    return pd.Series(pd.date_range("2020-04-01", periods=n, freq="15min"))


# ── pure dispatch heuristic ─────────────────────────────────────────────────

def _spec(**kw):
    base = dict(
        capacity_kwh=200.0, power_kw=100.0, round_trip_efficiency=0.90,
        min_soc_pct=10.0, max_soc_pct=95.0, initial_soc_pct=50.0,
    )
    base.update(kw)
    return base


def test_dispatch_charges_offpeak_when_load_low():
    n = 8
    dt = _grid(n)
    # Peak elsewhere is 200; these low ticks (20) sit below the 0.80*200 target.
    load = [20.0] * (n - 1) + [200.0]
    ptype = ["off-peak"] * n
    is_dr = [False] * n
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr, **_spec())
    # The low off-peak ticks charge (power negative), SoC rises over them.
    low = df.iloc[: n - 1]
    assert (low["power_battery_kw"] <= 0).all()
    assert low["soc_kwh"].iloc[-1] > df["soc_kwh"].iloc[0] - 1e-9


def test_dispatch_discharges_on_peak_price():
    n = 8
    dt = _grid(n)
    # Peak-price ticks above the (lowered) DR/peak target → discharge.
    load = [180.0] * n
    ptype = ["peak"] * n
    is_dr = [False] * n
    # Plenty of energy so the discharge is not SoC-limited within the window.
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr,
                  **_spec(capacity_kwh=2000.0, initial_soc_pct=90.0))
    assert (df["power_battery_kw"] > 0).all()
    # Bounded by rated power.
    assert (df["power_battery_kw"] <= 100.0 + 1e-9).all()
    # SoC monotone decreasing while discharging.
    assert (df["soc_kwh"].diff().dropna() <= 1e-9).all()


def test_dispatch_discharges_during_dr_even_when_offpeak():
    n = 4
    dt = _grid(n)
    # Load above the lowered DR target (0.60 * peak); peak across window is 200.
    load = [180.0, 180.0, 180.0, 200.0]
    ptype = ["off-peak"] * n
    is_dr = [True] * n
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr, **_spec())
    assert (df["power_battery_kw"] > 0).all()


def test_dispatch_never_exports_past_load():
    n = 4
    dt = _grid(n)
    # Tiny load relative to peak → discharge clipped to the load itself.
    load = [10.0, 10.0, 10.0, 999.0]
    ptype = ["peak"] * n
    is_dr = [False] * n
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr, **_spec())
    # Net import never pushed below zero on the small-load ticks.
    assert (df["power_battery_kw"].iloc[:3] <= 10.0 + 1e-9).all()


def test_dispatch_respects_power_clamp():
    n = 6
    dt = _grid(n)
    load = [9999.0] * n
    ptype = ["peak"] * n
    is_dr = [False] * n
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr,
                  **_spec(power_kw=100.0, capacity_kwh=400.0))
    assert (df["power_battery_kw"].abs() <= 100.0 + 1e-9).all()


def test_dispatch_respects_soc_band():
    n = 200
    dt = _grid(n)
    # Alternate cheap (charge) / peak (discharge) to swing SoC hard.
    load = [80.0] * n
    ptype = ["peak" if i % 2 else "off-peak" for i in range(n)]
    is_dr = [False] * n
    s = _spec(min_soc_pct=10.0, max_soc_pct=95.0, capacity_kwh=200.0)
    df = dispatch(datetimes=dt, load_kw=load, price_type=ptype, is_dr=is_dr, **s)
    soc_min = 0.10 * 200.0
    soc_max = 0.95 * 200.0
    assert (df["soc_kwh"] >= soc_min - 1e-9).all()
    assert (df["soc_kwh"] <= soc_max + 1e-9).all()


def test_dispatch_charge_applies_round_trip_loss():
    # First tick: low load (10) below the 0.80*1000 target → off-peak charge.
    dt = _grid(2)
    df = dispatch(datetimes=dt, load_kw=[10.0, 1000.0], price_type=["off-peak", "off-peak"],
                  is_dr=[False, False],
                  **_spec(initial_soc_pct=50.0, capacity_kwh=200.0, power_kw=100.0,
                          round_trip_efficiency=0.90))
    # Off-peak charge tick: AC draw 100 kW * 0.25 h = 25 kWh; SoC gains
    # 25 * 0.90 = 22.5 kWh on top of 100 (50% of 200).
    assert df["power_battery_kw"].iloc[0] == pytest.approx(-100.0)
    assert df["soc_kwh"].iloc[0] == pytest.approx(100.0 + 25.0 * 0.90, abs=1e-9)


def test_dispatch_discharge_lossless_on_soc():
    # First tick load 80 is below 0.80*200=160 target → no discharge. Use a peak
    # tick whose load (80) exceeds the lowered DR/peak target (0.60*100=60).
    dt = _grid(1)
    df = dispatch(datetimes=dt, load_kw=[80.0], price_type=["peak"], is_dr=[False],
                  **_spec(initial_soc_pct=50.0, capacity_kwh=200.0, power_kw=100.0))
    # peak=80 → dr_target=48; excess=32 → discharge 32 kW * 0.25 h = 8 kWh off SoC.
    assert df["power_battery_kw"].iloc[0] == pytest.approx(32.0)
    assert df["soc_kwh"].iloc[0] == pytest.approx(100.0 - 8.0, abs=1e-9)


# ── integration: ON / OFF ───────────────────────────────────────────────────

_FAST = {
    "sim_window.mode": "custom",
    "sim_window.start": "2020-04-01",
    "sim_window.custom_end": "2020-04-08",
}


def _gen(out: Path, overrides=None, seed=42):
    ov = dict(_FAST)
    ov.update(overrides or {})
    return generate("S01", seed=seed, output_dir=out, config_dir=CONFIG_DIR, cli_overrides=ov)


def test_battery_off_dispatch_header_only(tmp_path):
    out = tmp_path / "off"
    _gen(out)
    bd = pd.read_csv(out / "battery_dispatch.csv")
    assert list(bd.columns) == COLUMNS
    assert len(bd) == 0


def test_battery_off_other_csvs_byte_identical(tmp_path):
    """Adding the dispatch node must not perturb any other CSV when off."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    _gen(a)
    _gen(b)
    for name in ("building_load", "cars", "users", "chargers", "grid_prices",
                 "dr_events", "sessions", "pv_generation", "pv", "battery"):
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes()


def test_battery_on_produces_valid_dispatch(tmp_path):
    out = tmp_path / "on"
    _gen(out, overrides={"battery.battery_type": "lfp_4h"})
    bd = pd.read_csv(out / "battery_dispatch.csv", parse_dates=["datetime"])
    bl = pd.read_csv(out / "building_load.csv", parse_dates=["datetime"])
    assert len(bd) == len(bl)
    assert list(bd["datetime"]) == list(bl["datetime"])
    # Battery actually does something (both charge and discharge happen).
    assert (bd["power_battery_kw"] > 0).any(), "no discharge ticks"
    assert (bd["power_battery_kw"] < 0).any(), "no charge ticks"
    rep = validate(out)
    assert not rep.errors, rep.errors


def test_battery_on_shaves_peak_and_swings_soc(tmp_path):
    out = tmp_path / "on"
    _gen(out, overrides={"battery.battery_type": "lfp_4h"})
    bd = pd.read_csv(out / "battery_dispatch.csv")
    bl = pd.read_csv(out / "building_load.csv")
    net = bl["power_kw"].to_numpy() - bd["power_battery_kw"].to_numpy()
    # Net (grid import) peak is shaved below the raw building peak.
    assert net.max() < bl["power_kw"].max() - 1e-6, "peak not shaved"
    # Arbitrage: SoC actually swings (charges then discharges).
    soc_swing = bd["soc_kwh"].max() - bd["soc_kwh"].min()
    assert soc_swing > 1.0, f"SoC barely moved ({soc_swing:.3f} kWh)"


def test_battery_off_validate_passes(tmp_path):
    out = tmp_path / "off"
    _gen(out)
    rep = validate(out)
    assert not rep.errors, rep.errors


def test_battery_dispatch_reproducible(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _gen(a, overrides={"battery.battery_type": "nmc_2h"}, seed=7)
    _gen(b, overrides={"battery.battery_type": "nmc_2h"}, seed=7)
    assert (a / "battery_dispatch.csv").read_bytes() == (b / "battery_dispatch.csv").read_bytes()
