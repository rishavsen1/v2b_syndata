"""End-to-end EnergyPlus pipeline. Skipped without a runnable EP binary.

These tests **opt in** to the real EnergyPlus run via ``@pytest.mark.real_energyplus``.
The repo-wide stub fixture would otherwise replace ``simulate_building_load``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.load_pipeline import simulate_building_load
from v2b_syndata.load_pipeline.cache import _cache_root

from .conftest import skip_if_no_energyplus

NASHVILLE = "USA_TN_Nashville.Intl.AP.723270_TMYx"


def _occupancy(start: str, end: str, val: float = 1.0) -> pd.Series:
    idx = pd.date_range(start, end, freq="15min", inclusive="left")
    return pd.Series(val, index=idx, name="occupancy")


@skip_if_no_energyplus
@pytest.mark.real_energyplus
def test_simulate_office_small_april_2020(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_LOAD_CACHE_DIR", str(tmp_path / "cache"))
    start = pd.Timestamp("2020-04-01")
    end = pd.Timestamp("2020-04-08")  # one week, sufficient signal
    occ = _occupancy(str(start), str(end), val=0.8)

    flex, inflex = simulate_building_load(
        archetype="office",
        size="small",
        tmyx_station=NASHVILLE,
        occupancy=occ,
        sim_window_start=start,
        sim_window_end=end,
    )
    assert len(flex) == 96 * 7
    assert len(inflex) == 96 * 7
    assert (flex >= 0).all()
    assert (inflex >= 0).all()
    # Plausible magnitudes for a small office (PNNL ~500 m²): a few kW.
    assert flex.max() < 1000.0
    assert inflex.max() < 1000.0
    assert (flex.max() + inflex.max()) > 0.5


@skip_if_no_energyplus
@pytest.mark.real_energyplus
def test_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_LOAD_CACHE_DIR", str(tmp_path / "cache"))
    start = pd.Timestamp("2020-04-01")
    end = pd.Timestamp("2020-04-08")
    occ = _occupancy(str(start), str(end), val=0.5)

    import time

    t0 = time.time()
    flex_a, _ = simulate_building_load(
        archetype="office", size="small", tmyx_station=NASHVILLE,
        occupancy=occ, sim_window_start=start, sim_window_end=end,
    )
    t_first = time.time() - t0

    t0 = time.time()
    flex_b, _ = simulate_building_load(
        archetype="office", size="small", tmyx_station=NASHVILLE,
        occupancy=occ, sim_window_start=start, sim_window_end=end,
    )
    t_second = time.time() - t0

    pd.testing.assert_series_equal(flex_a, flex_b, check_names=False)
    # Cache hit must be at least 5× faster than the EnergyPlus run.
    assert t_second * 5 < t_first


@skip_if_no_energyplus
@pytest.mark.real_energyplus
def test_modified_occupancy_breaks_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_LOAD_CACHE_DIR", str(tmp_path / "cache"))
    start = pd.Timestamp("2020-04-01")
    end = pd.Timestamp("2020-04-08")
    occ_a = _occupancy(str(start), str(end), val=0.3)
    occ_b = _occupancy(str(start), str(end), val=0.9)

    flex_a, _ = simulate_building_load(
        archetype="office", size="small", tmyx_station=NASHVILLE,
        occupancy=occ_a, sim_window_start=start, sim_window_end=end,
    )
    flex_b, _ = simulate_building_load(
        archetype="office", size="small", tmyx_station=NASHVILLE,
        occupancy=occ_b, sim_window_start=start, sim_window_end=end,
    )
    # Different occupancy → measurably different load (especially HVAC).
    assert not flex_a.equals(flex_b)


def test_amy_path_raises():
    """No EP binary needed — pure code-path verification of the AMY stub."""
    from v2b_syndata.load_pipeline.weather import get_weather_epw

    with pytest.raises(NotImplementedError):
        get_weather_epw(NASHVILLE, weather_type="amy", weather_year=2020)
