"""Synthetic eplusmtr.csv → correct units + slicing."""
from __future__ import annotations

import pandas as pd
import pytest

from v2b_syndata.load_pipeline.output_parser import (
    J_PER_KWH_15MIN,
    parse_eplusout,
)


def _write_synthetic_eplus_csv(path, n_rows: int = 96 * 7) -> pd.DatetimeIndex:
    """Emit a fake eplusmtr.csv for one week (7 days × 96 timesteps).

    EnergyPlus rows look like '04/01  00:15:00, 9.0, 18.0, ...' (no year).
    """
    idx = pd.date_range("2020-04-01 00:15:00", periods=n_rows, freq="15min")

    def fmt(ts: pd.Timestamp) -> str:
        return f" {ts.month:02d}/{ts.day:02d}  {ts.hour:02d}:{ts.minute:02d}:00"

    headers = [
        "Date/Time",
        "Cooling:Electricity [J](TimeStep)",
        "Heating:Electricity [J](TimeStep)",
        "Fans:Electricity [J](TimeStep)",
        "WaterSystems:Electricity [J](TimeStep)",
        "InteriorLights:Electricity [J](TimeStep)",
        "ExteriorLights:Electricity [J](TimeStep)",
        "InteriorEquipment:Electricity [J](TimeStep)",
        "ExteriorEquipment:Electricity [J](TimeStep)",
    ]

    rows = []
    # Each meter: J/15-min. Per-meter values picked so that:
    #   flex per timestep = (1+2+3+4) * J_PER_KWH_15MIN = 10 * J_PER_KWH_15MIN
    #   → flex_kw = 10
    # inflex = (5+6+7+8) * J_PER_KWH_15MIN = 26 * J_PER_KWH_15MIN
    #   → inflex_kw = 26
    flex_meter_values = [1, 2, 3, 4]
    inflex_meter_values = [5, 6, 7, 8]
    for ts in idx:
        rows.append(
            [fmt(ts)]
            + [f"{m * J_PER_KWH_15MIN:.6f}" for m in flex_meter_values]
            + [f"{m * J_PER_KWH_15MIN:.6f}" for m in inflex_meter_values]
        )

    df = pd.DataFrame(rows, columns=headers)
    df.to_csv(path, index=False)
    return idx


def test_parse_synthetic_csv(tmp_path):
    csv = tmp_path / "eplusmtr.csv"
    _write_synthetic_eplus_csv(csv)
    flex, inflex = parse_eplusout(
        csv,
        sim_window_start=pd.Timestamp("2020-04-01"),
        sim_window_end=pd.Timestamp("2020-04-08"),
    )
    # EP emits end-of-interval timestamps starting 04/01 00:15. The 04/08 00:00
    # row exists in the CSV but coincides with sim_window_end (exclusive), so 671.
    assert len(flex) == 671
    assert len(inflex) == 671
    assert (flex == 10).all(), flex.head().to_string()
    assert (inflex == 26).all()


def test_parse_slices_to_window(tmp_path):
    csv = tmp_path / "eplusmtr.csv"
    _write_synthetic_eplus_csv(csv, n_rows=96 * 7)
    flex, _ = parse_eplusout(
        csv,
        sim_window_start=pd.Timestamp("2020-04-03"),
        sim_window_end=pd.Timestamp("2020-04-05"),
    )
    assert len(flex) == 96 * 2
    assert flex.index.min() >= pd.Timestamp("2020-04-03")
    assert flex.index.max() < pd.Timestamp("2020-04-05")


def test_parse_handles_24_hour_boundary(tmp_path):
    csv = tmp_path / "eplusmtr.csv"
    headers = [
        "Date/Time",
        "Cooling:Electricity [J](TimeStep)",
        "InteriorLights:Electricity [J](TimeStep)",
    ]
    # Single row at the end of day 1 expressed as 24:00:00 — EP uses this.
    df = pd.DataFrame(
        [[" 04/01  24:00:00", str(J_PER_KWH_15MIN), str(J_PER_KWH_15MIN * 2)]],
        columns=headers,
    )
    df.to_csv(csv, index=False)
    flex, inflex = parse_eplusout(
        csv,
        sim_window_start=pd.Timestamp("2020-04-02"),
        sim_window_end=pd.Timestamp("2020-04-03"),
    )
    # 24:00 normalizes to 04/02 00:00 — included in window.
    assert len(flex) == 1
    assert flex.iloc[0] == pytest.approx(1.0)
    assert inflex.iloc[0] == pytest.approx(2.0)
