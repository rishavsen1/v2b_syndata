"""Solar irradiance columns parsed from a real cached EPW (no EnergyPlus run)."""
from __future__ import annotations

from pathlib import Path

import pytest

from v2b_syndata.load_pipeline.weather import parse_epw_weather

REPO = Path(__file__).resolve().parents[1]
EPW = REPO / "data/stations/USA_TN_Nashville.Intl.AP.723270_TMYx.epw"

SOLAR = ["global_horizontal_w_m2", "direct_normal_w_m2", "diffuse_horizontal_w_m2"]


@pytest.mark.skipif(not EPW.exists(), reason="Nashville EPW not cached")
def test_real_epw_has_plausible_solar():
    df = parse_epw_weather(EPW, year=2021)
    for c in SOLAR:
        assert c in df.columns
        assert (df[c] >= 0).all()                       # irradiance is non-negative
    # nights dark, days bright
    assert df["global_horizontal_w_m2"][df.index.hour == 0].max() == 0
    assert df["global_horizontal_w_m2"][df.index.hour == 13].max() > 100
    # GHI ≈ DHI + DNI·cos(z) → GHI should generally exceed DHI midday
    midday = df[df.index.hour == 13]
    assert (midday["global_horizontal_w_m2"] >= midday["diffuse_horizontal_w_m2"]).mean() > 0.8
