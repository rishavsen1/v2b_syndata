"""Unit tests for the optimus export adapter (pure mapping, no generation)."""
from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata import export_optimus as exp

# ── synthetic native CSVs ────────────────────────────────────────────────────

def _native_building_load() -> pd.DataFrame:
    idx = pd.date_range("2021-09-01", periods=4, freq="15min")
    return pd.DataFrame({
        "datetime": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "power_flex_kw": [10.0, 12.0, 8.0, 6.0],
        "power_inflex_kw": [20.0, 20.0, 20.0, 20.0],
        "power_kw": [30.0, 32.0, 28.0, 26.0],
    })


def _native_cars() -> pd.DataFrame:
    return pd.DataFrame({
        "car_id": [1, 2, 3],
        "capacity_kwh": [60.0, 75.0, 100.0],
        "min_allowed_soc": [10.0, 10.0, 10.0],
        "max_allowed_soc": [90.0, 90.0, 100.0],
        "battery_class": ["bolt_40", "m3_75", "rivian_100"],
    })


def _native_users() -> pd.DataFrame:
    return pd.DataFrame({
        "car_id": [1, 2, 3],
        "region": ["stable_commuter", "flexible_local", "stable_commuter"],
        "phi": [0.9, 0.7, 0.85],
        "kappa": [0.8, 0.6, 0.75],
        "delta_km": [50, 10, 60],
        "negotiation_type": ["type_ii"] * 3,
        "w1": [1.0] * 3, "w2": [1.0] * 3,
    })


def _native_sessions() -> pd.DataFrame:
    return pd.DataFrame({
        "session_id": [1, 2, 3],
        "car_id": [1, 1, 2],
        "building_id": ["B001"] * 3,
        "arrival": ["2021-09-02 08:00:00", "2021-09-01 09:00:00", "2021-09-02 07:30:00"],
        "departure": ["2021-09-02 17:00:00", "2021-09-01 18:00:00", "2021-09-02 16:00:00"],
        "duration_sec": [32400, 32400, 30600],
        "arrival_soc": [40.0, 35.0, 55.0],
        "required_soc_at_depart": [85.0, 80.0, 82.0],
        "previous_day_external_use_soc": [0.0, 5.0, 0.0],
    })


def _native_chargers() -> pd.DataFrame:
    return pd.DataFrame({
        "charger_id": [1, 2],
        "directionality": ["bidirectional", "unidirectional"],
        "min_rate_kw": [-20.0, 0.0],
        "max_rate_kw": [20.0, 7.2],
    })


def _native_grid() -> pd.DataFrame:
    return pd.DataFrame({
        "datetime": ["2021-09-01 00:00:00", "2021-09-01 06:00:00"],
        "price_per_kwh": [0.137, 0.178],
        "type": ["off-peak", "peak"],
    })


def _native_dr() -> pd.DataFrame:
    return pd.DataFrame({
        "event_id": [1, 2],
        "start": ["2021-09-02 16:00:00", "2021-09-03 16:00:00"],
        "end": ["2021-09-02 20:00:00", "2021-09-03 20:00:00"],
        "magnitude_kw": [30.0, 45.0],
        "notified_at": ["2021-09-02 08:00:00", "2021-09-03 08:00:00"],
    })


# ── synthetic EPW fixture so build_weather needs no real station ──────────────

def _write_epw(path: Path, year: int = 2021) -> Path:
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    header = ["LOCATION,Test,-,-,-,-,-,-,-,-"] + ["HEADER"] * 7
    lines = list(header)
    for i, ts in enumerate(idx):
        cols = ["0"] * 22
        cols[1] = str(ts.month)
        cols[2] = str(ts.day)
        cols[3] = str(ts.hour + 1)  # EPW hour is 1-24
        cols[6] = f"{15.0 + (i % 24) * 0.1:.1f}"   # dry bulb
        cols[7] = f"{5.0 + (i % 12) * 0.1:.1f}"    # dew point
        cols[8] = f"{40.0 + (i % 30):.1f}"         # RH %
        cols[21] = f"{2.0 + (i % 5) * 0.5:.1f}"    # wind speed
        lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    return path


# ── tests ────────────────────────────────────────────────────────────────────

def test_building_load_mapping():
    out = exp.build_building_load(_native_building_load(), building_id=2)
    assert list(out.columns) == [
        "datetime", "time_seconds", "power_kw", "energy_kwh",
        "power_kw_flexible", "energy_kwh_flexible",
        "power_kw_inflexible", "energy_kwh_inflexible", "building_id",
    ]
    # energy = power * 0.25 (15-min)
    assert (out["energy_kwh"] == out["power_kw"] * 0.25).all()
    assert (out["energy_kwh_flexible"] == out["power_kw_flexible"] * 0.25).all()
    assert (out["building_id"] == 2).all()
    # time_seconds = seconds since year start + one 900s tick; +900 per row.
    year_start = pd.Timestamp("2021-01-01")
    first = int((pd.Timestamp("2021-09-01 00:00:00") - year_start).total_seconds()) + 900
    assert out["time_seconds"].iloc[0] == first
    assert (out["time_seconds"].diff().dropna() == 900).all()


def test_cars_mapping():
    out = exp.build_cars(_native_cars(), _native_users(), _native_sessions(), building_id=0)
    assert list(out.columns) == [
        "car_id", "capacity_kwh", "soc", "min_allowed_soc", "max_allowed_soc",
        "building_id", "frequency", "user_type",
    ]
    by_car = out.set_index("car_id")
    # soc = first-session arrival_soc (car 1's earliest session is 09-01 09:00 → 35.0)
    assert by_car.loc[1, "soc"] == 35.0
    assert by_car.loc[2, "soc"] == 55.0
    # car 3 has no session → falls back to min_allowed_soc
    assert by_car.loc[3, "soc"] == 10.0
    # frequency = phi
    assert by_car.loc[1, "frequency"] == 0.9
    # user_type = region index by first-appearance order (stable=0, flexible=1)
    assert by_car.loc[1, "user_type"] == 0
    assert by_car.loc[2, "user_type"] == 1
    assert by_car.loc[3, "user_type"] == 0
    assert "battery_class" not in out.columns


def test_chargers_charge_rates_tuple():
    out = exp.build_chargers(_native_chargers(), building_id=1)
    assert list(out.columns) == ["charger_id", "directionality", "charge_rates_kw", "building_id"]
    assert out["charge_rates_kw"].iloc[0] == "(-20.0, 20.0)"
    assert ast.literal_eval(out["charge_rates_kw"].iloc[0]) == (-20.0, 20.0)
    assert ast.literal_eval(out["charge_rates_kw"].iloc[1]) == (0.0, 7.2)


def test_sessions_mapping():
    out = exp.build_sessions(_native_sessions(), building_id=3)
    assert list(out.columns) == [
        "car_id", "arrival", "required_soc_at_depart",
        "previous_day_external_use_soc", "duration", "session_id", "building_id",
    ]
    assert "arrival_soc" not in out.columns and "departure" not in out.columns
    assert out["duration"].iloc[0] == 32400  # seconds, from duration_sec
    assert (out["building_id"] == 3).all()


def test_sessions_empty():
    empty = pd.DataFrame(columns=_native_sessions().columns)
    out = exp.build_sessions(empty, building_id=0)
    assert len(out) == 0
    assert "duration" in out.columns


def test_grid_prices_adds_building_id():
    out = exp.build_grid_prices(_native_grid(), building_id=5)
    assert list(out.columns) == ["datetime", "price_per_kwh", "type", "building_id"]
    assert (out["building_id"] == 5).all()


def test_dso_commands_unified():
    out = exp.build_dso_commands(_native_dr(), program="CBP", incentive=5.0, penalty=12.0)
    assert list(out.columns) == [
        "start_datetime", "end_datetime", "fsl", "program", "incentive", "penalty",
    ]
    assert out["fsl"].iloc[0] == 30.0  # magnitude_kw → fsl
    assert (out["program"] == "CBP").all()
    assert (out["incentive"] == 5.0).all()
    assert (out["penalty"] == 12.0).all()
    assert "building_id" not in out.columns


def test_dso_commands_empty_program():
    empty = pd.DataFrame(columns=_native_dr().columns)
    out = exp.build_dso_commands(empty, program="none", incentive=0.0, penalty=0.0)
    assert len(out) == 0
    assert list(out.columns) == [
        "start_datetime", "end_datetime", "fsl", "program", "incentive", "penalty",
    ]


def test_policies():
    out = exp.build_policies([(0, "POL-A"), (1, "POL-B")])
    assert list(out.columns) == ["building_id", "policy"]
    assert out["policy"].tolist() == ["POL-A", "POL-B"]


@pytest.mark.parametrize("year,rows", [(2021, 8760), (2020, 8784)])
def test_occupancy_full_year(year, rows):
    out = exp.build_occupancy("ashrae_90_1_office", year=year, building_id=0)
    assert list(out.columns) == ["timestamp", "occupancy", "date", "building_id"]
    assert len(out) == rows
    assert (out["occupancy"] >= 0).all() and (out["occupancy"] <= 1).all()
    assert out["timestamp"].iloc[0] == f"{year}-01-01 00:00:00"
    assert out["date"].iloc[0] == f"{year}-01-01"


def test_weather_window(tmp_path, monkeypatch):
    epw = _write_epw(tmp_path / "test.epw", year=2021)
    monkeypatch.setattr(exp.weather, "get_weather_epw",
                        lambda *a, **k: epw)
    out = exp.build_weather(
        "USA_TN_X_TMYx",
        pd.Timestamp("2021-09-01"), pd.Timestamp("2021-10-01"),
        building_id=1,
    )
    assert list(out.columns) == [
        "datetime", "dry_bulb_temp_c", "dew_point_temp_c",
        "relative_humidity_pct", "wind_speed_m_s", "building_id",
    ]
    assert len(out) == 30 * 24  # September, hourly
    assert out["datetime"].iloc[0] == "2021-09-01 00:00:00"
    assert out["datetime"].iloc[-1] == "2021-09-30 23:00:00"
    assert (out["building_id"] == 1).all()


def test_index_col_constants():
    assert exp.INDEX_COL_FILES == frozenset(
        {"cars.csv", "chargers.csv", "sessions.csv", "grid_prices.csv"}
    )
    assert exp.WEATHER_OCCUPANCY == frozenset({"weather_data.csv", "occupancy.csv"})
