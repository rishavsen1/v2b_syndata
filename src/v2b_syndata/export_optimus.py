"""Pure, deterministic adapter: native v2b CSVs → optimus-persist-multi schema.

The native single-building generator (`runner.generate`) writes its own CSV
schema. The `optimus-persist-multi` optimizer ingests a *different* set of
column names and file shapes (reference:
`optimus-persist-multi/data/input_csvs/RISHAV_15_USERS_2024/SEP2024/0`). This
module is a one-way export layer: given a building's native CSV set (+ resolved
knob values) it returns DataFrames in the optimus schema. It runs no RNG, no
EnergyPlus, and no I/O beyond reading the cached EPW for the weather export —
so the mapping is a deterministic function of its inputs.

Layout / index conventions (see `multi_building.generate_multi`):
- `INDEX_COL_FILES` are written with a leading pandas index column because the
  optimizer reads them with `read_csv(index_col=0)`.
- `WEATHER_OCCUPANCY` carry `building_id` only in *shared* mode; in
  per-building mode they match the reference (no `building_id`).
"""
from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd

from .load_pipeline import leap_weather, weather

# Optimizer loaders read these four with read_csv(index_col=0): they MUST be
# written with a leading (unnamed) index column.
INDEX_COL_FILES = frozenset({
    "cars.csv", "chargers.csv", "sessions.csv", "grid_prices.csv",
})
# These two match the reference exactly (no building_id) in per-building mode;
# in shared mode they gain a building_id column like every other file.
WEATHER_OCCUPANCY = frozenset({"weather_data.csv", "occupancy.csv"})

_TICK_SECONDS = 900  # 15-min grid (also the optimus time_seconds offset)


def _region_index_map(users: pd.DataFrame) -> dict[str, int]:
    """Map region name → integer `user_type`, by first-appearance order in
    `users.csv` (sorted by car_id for determinism)."""
    ordered = users.sort_values("car_id")["region"].tolist()
    mapping: dict[str, int] = {}
    for r in ordered:
        if r not in mapping:
            mapping[r] = len(mapping)
    return mapping


def build_building_load(native_bl: pd.DataFrame, building_id: int) -> pd.DataFrame:
    """native (datetime, power_flex_kw, power_inflex_kw, power_kw) →
    optimus building_load with derived energy + time_seconds columns."""
    dt = pd.to_datetime(native_bl["datetime"])
    year_start = datetime(dt.iloc[0].year, 1, 1)
    # time_seconds: seconds since start-of-year + one tick (matches reference).
    time_seconds = ((dt - pd.Timestamp(year_start)).dt.total_seconds()
                    + _TICK_SECONDS).astype("int64")
    power_kw = native_bl["power_kw"].astype(float)
    flex = native_bl["power_flex_kw"].astype(float)
    inflex = native_bl["power_inflex_kw"].astype(float)
    h = _TICK_SECONDS / 3600.0  # 0.25 h
    return pd.DataFrame({
        "datetime": native_bl["datetime"].values,
        "time_seconds": time_seconds.values,
        "power_kw": power_kw.values,
        "energy_kwh": (power_kw * h).values,
        "power_kw_flexible": flex.values,
        "energy_kwh_flexible": (flex * h).values,
        "power_kw_inflexible": inflex.values,
        "energy_kwh_inflexible": (inflex * h).values,
        "building_id": building_id,
    })


def build_cars(
    native_cars: pd.DataFrame,
    native_users: pd.DataFrame,
    native_sessions: pd.DataFrame,
    building_id: int,
) -> pd.DataFrame:
    """native cars + users (φ, region) + sessions (first arrival_soc) →
    optimus cars. `soc` = each car's first-session arrival_soc (min_allowed_soc
    if the car has no session); `frequency` = φ; `user_type` = region index."""
    region_map = _region_index_map(native_users)
    users_by_car = native_users.set_index("car_id")

    # First-session arrival_soc per car (earliest arrival).
    first_soc: dict = {}
    if not native_sessions.empty:
        s = native_sessions.copy()
        s["_arr"] = pd.to_datetime(s["arrival"])
        s = s.sort_values("_arr")
        for car_id, grp in s.groupby("car_id", sort=False):
            first_soc[car_id] = float(grp.iloc[0]["arrival_soc"])

    rows = []
    for _, c in native_cars.iterrows():
        car_id = c["car_id"]
        u = users_by_car.loc[car_id]
        rows.append({
            "car_id": car_id,
            "capacity_kwh": c["capacity_kwh"],
            "soc": first_soc.get(car_id, float(c["min_allowed_soc"])),
            "min_allowed_soc": c["min_allowed_soc"],
            "max_allowed_soc": c["max_allowed_soc"],
            "building_id": building_id,
            "frequency": float(u["phi"]),
            "user_type": region_map[u["region"]],
        })
    return pd.DataFrame(rows, columns=[
        "car_id", "capacity_kwh", "soc", "min_allowed_soc", "max_allowed_soc",
        "building_id", "frequency", "user_type",
    ])


def build_chargers(native_chargers: pd.DataFrame, building_id: int) -> pd.DataFrame:
    """native (charger_id, directionality, min_rate_kw, max_rate_kw) → optimus
    chargers with `charge_rates_kw` as a string tuple "(min, max)"."""
    rates = [
        f"({float(lo)}, {float(hi)})"
        for lo, hi in zip(native_chargers["min_rate_kw"],
                          native_chargers["max_rate_kw"], strict=True)
    ]
    return pd.DataFrame({
        "charger_id": native_chargers["charger_id"].values,
        "directionality": native_chargers["directionality"].values,
        "charge_rates_kw": rates,
        "building_id": building_id,
    })


def build_sessions(native_sessions: pd.DataFrame, building_id: int) -> pd.DataFrame:
    """native sessions → optimus sessions: `duration` = duration_sec, drop
    arrival_soc/departure, re-id building_id."""
    if native_sessions.empty:
        return pd.DataFrame(columns=[
            "car_id", "arrival", "required_soc_at_depart",
            "previous_day_external_use_soc", "duration", "session_id",
            "building_id",
        ])
    return pd.DataFrame({
        "car_id": native_sessions["car_id"].values,
        "arrival": native_sessions["arrival"].values,
        "required_soc_at_depart": native_sessions["required_soc_at_depart"].values,
        "previous_day_external_use_soc":
            native_sessions["previous_day_external_use_soc"].values,
        "duration": native_sessions["duration_sec"].values,
        "session_id": native_sessions["session_id"].values,
        "building_id": building_id,
    })


def build_grid_prices(native_grid: pd.DataFrame, building_id: int) -> pd.DataFrame:
    """native grid_prices + building_id (columns unchanged otherwise)."""
    out = native_grid.copy()
    out["building_id"] = building_id
    return out[["datetime", "price_per_kwh", "type", "building_id"]]


def build_weather(
    tmyx_station: str,
    sim_start: pd.Timestamp,
    sim_end: pd.Timestamp,
    building_id: int,
    *,
    temp_offset_c: float = 0.0,
    solar_scale: float = 1.0,
    fetcher: Callable[[str], bytes] | None = None,
) -> pd.DataFrame:
    """Reconstruct hourly weather over [sim_start, sim_end) from the same EPW
    EnergyPlus consumed (leap-injected for leap years), matching the optimus
    weather_data schema.

    ``temp_offset_c`` / ``solar_scale`` apply the weather *realization* transform
    — they MUST match the values passed to ``simulate_building_load`` so the
    exported weather stays faithful to the simulated load.
    """
    sim_start = pd.Timestamp(sim_start)
    sim_end = pd.Timestamp(sim_end)
    year = sim_start.year
    epw_path = weather.get_weather_epw(tmyx_station, "tmyx", None, fetcher=fetcher)
    if leap_weather.is_leap(year):
        with tempfile.TemporaryDirectory(prefix="v2b_wx_") as tmp:
            leap_epw = leap_weather.make_leap_epw(
                epw_path, Path(tmp) / "weather.epw", year
            )
            wx = weather.parse_epw_weather(leap_epw, year=year)
    else:
        wx = weather.parse_epw_weather(epw_path, year=year)

    wx = weather.perturb_weather_frame(wx, temp_offset_c, solar_scale)
    wx = wx[(wx.index >= sim_start) & (wx.index < sim_end)]
    out = pd.DataFrame({
        "datetime": wx.index.strftime("%Y-%m-%d %H:%M:%S"),
        "dry_bulb_temp_c": wx["dry_bulb_temp_c"].values,
        "dew_point_temp_c": wx["dew_point_temp_c"].values,
        "relative_humidity_pct": wx["relative_humidity_pct"].values,
        "wind_speed_m_s": wx["wind_speed_m_s"].values,
        "global_horizontal_w_m2": wx["global_horizontal_w_m2"].values,
        "direct_normal_w_m2": wx["direct_normal_w_m2"].values,
        "diffuse_horizontal_w_m2": wx["diffuse_horizontal_w_m2"].values,
        "building_id": building_id,
    })
    return out


def build_occupancy(
    occupancy_source: str, year: int, building_id: int
) -> pd.DataFrame:
    """Full-year hourly fractional occupancy via the same ASHRAE schedules the
    load pipeline uses (`samplers.load._build_occupancy_series`)."""
    from .samplers.load import _build_occupancy_series

    idx = pd.date_range(
        start=pd.Timestamp(year=year, month=1, day=1),
        end=pd.Timestamp(year=year + 1, month=1, day=1),
        freq="h", inclusive="left",
    )
    series = _build_occupancy_series(str(occupancy_source), idx)
    return pd.DataFrame({
        "timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "occupancy": series.values,
        "date": idx.strftime("%Y-%m-%d"),
        "building_id": building_id,
    })


def build_dso_commands(
    native_dr: pd.DataFrame,
    program: str,
    incentive: float,
    penalty: float,
) -> pd.DataFrame:
    """native dr_events → unified, global dso_commands.csv (no building_id).
    `fsl` = magnitude_kw; `program`/`incentive`/`penalty` constant per run."""
    cols = ["start_datetime", "end_datetime", "fsl", "program",
            "incentive", "penalty"]
    if native_dr.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({
        "start_datetime": native_dr["start"].values,
        "end_datetime": native_dr["end"].values,
        "fsl": native_dr["magnitude_kw"].values,
        "program": program,
        "incentive": float(incentive),
        "penalty": float(penalty),
    })[cols]


def build_policies(rows: list[tuple[int, str]]) -> pd.DataFrame:
    """[(building_id, policy), ...] → policies.csv."""
    return pd.DataFrame(rows, columns=["building_id", "policy"])
