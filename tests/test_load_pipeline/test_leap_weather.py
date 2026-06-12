"""Leap-aware EPW transform + the day-of-week regression it fixes.

Pure-transform tests always run. The end-to-end weekday/weekend assertion opts
in to a real EnergyPlus run (the repo-wide stub would otherwise replace
``simulate_building_load``).
"""
from __future__ import annotations

import pandas as pd
import pytest

from v2b_syndata.load_pipeline import simulate_building_load
from v2b_syndata.load_pipeline.leap_weather import is_leap, make_leap_epw
from v2b_syndata.load_pipeline.weather import get_weather_epw

from .conftest import skip_if_no_energyplus

NASHVILLE = "USA_TN_Nashville.Intl.AP.723270_TMYx"
_N_HEADER = 8


def _data_rows(epw_path) -> list[str]:
    return epw_path.read_text().splitlines()[_N_HEADER:]


# ── Pure transform (no EnergyPlus) ──────────────────────────────────────────

def test_make_leap_epw_inserts_feb29(tmp_path):
    src = get_weather_epw(NASHVILLE)
    dst = make_leap_epw(src, tmp_path / "leap.epw", 2020)

    rows = _data_rows(dst)
    assert len(rows) == 366 * 24  # 8784: a real leap year of hourly data

    feb29 = [r.split(",") for r in rows if r.split(",")[1] == "2" and r.split(",")[2] == "29"]
    assert len(feb29) == 24
    assert sorted(int(p[3]) for p in feb29) == list(range(1, 25))  # hours 1..24

    # DATA PERIODS start day-of-week realigned to the leap year's Jan 1 (Wed).
    data_periods = dst.read_text().splitlines()[7]
    assert data_periods.split(",")[4] == "Wednesday"

    # Line terminator preserved (CRLF source → CRLF output, not silently LF).
    if b"\r\n" in src.read_bytes():
        assert b"\r\n" in dst.read_bytes()


def test_make_leap_epw_noop_for_nonleap(tmp_path):
    src = get_weather_epw(NASHVILLE)
    dst = make_leap_epw(src, tmp_path / "nonleap.epw", 2021)
    # Non-leap years are byte-for-byte unchanged (TMYx already aligns).
    assert dst.read_bytes() == src.read_bytes()
    assert not is_leap(2021) and is_leap(2020)


def test_make_leap_epw_deterministic(tmp_path):
    src = get_weather_epw(NASHVILLE)
    a = make_leap_epw(src, tmp_path / "a.epw", 2020).read_bytes()
    b = make_leap_epw(src, tmp_path / "b.epw", 2020).read_bytes()
    assert a == b


# ── End-to-end day-of-week correctness (real EnergyPlus) ─────────────────────

def _office_occupancy(start: str, end: str) -> pd.Series:
    """Realistic office occupancy: ~0.9 on weekdays, 0 on weekends."""
    idx = pd.date_range(start, end, freq="15min", inclusive="left")
    vals = [0.0 if ts.dayofweek >= 5 else 0.9 for ts in idx]
    return pd.Series(vals, index=idx, name="occupancy")


def _weekday_weekend_ratio(start: str, end: str, monkeypatch, tmp_cache) -> tuple[float, pd.Series]:
    monkeypatch.setenv("V2B_LOAD_CACHE_DIR", str(tmp_cache))
    occ = _office_occupancy(start, end)
    flex, inflex = simulate_building_load(
        archetype="office", size="small", tmyx_station=NASHVILLE,
        occupancy=occ, sim_window_start=pd.Timestamp(start), sim_window_end=pd.Timestamp(end),
    )
    total = (flex + inflex).rename("kw")
    dow = total.index.dayofweek
    weekday = float(total[dow < 5].mean())
    weekend = float(total[dow >= 5].mean())
    return weekday / weekend, total


@skip_if_no_energyplus
@pytest.mark.real_energyplus
def test_office_weekday_weekend_separation_leap_and_nonleap(tmp_path, monkeypatch):
    """The office must drop sharply on real Sat/Sun in BOTH a leap year (2020,
    the regression) and a non-leap year (2021, the control). Pre-fix, 2020 read
    ~1.27 because EnergyPlus applied the weekday schedule to calendar Saturday.
    """
    # Leap year 2020 — the previously-broken case.
    ratio_2020, total_2020 = _weekday_weekend_ratio(
        "2020-04-01", "2020-04-29", monkeypatch, tmp_path / "c2020"
    )
    # Non-leap control 2021 — must still be correct.
    ratio_2021, _ = _weekday_weekend_ratio(
        "2021-04-01", "2021-04-29", monkeypatch, tmp_path / "c2021"
    )

    assert ratio_2020 >= 2.5, f"leap-year office ww ratio {ratio_2020:.2f} < 2.5 (leap-day fix failed)"
    assert ratio_2021 >= 2.5, f"non-leap office ww ratio {ratio_2021:.2f} < 2.5"

    # Crisp leap-specific check: a calendar Saturday must sit in the weekend
    # (low) regime, well below an adjacent Wednesday.
    sat = float(total_2020["2020-04-04"].mean())   # Saturday
    wed = float(total_2020["2020-04-08"].mean())    # Wednesday
    assert sat < 0.6 * wed, f"calendar Saturday load {sat:.1f} not in weekend regime vs Wed {wed:.1f}"
