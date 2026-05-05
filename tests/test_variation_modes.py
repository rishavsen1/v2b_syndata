"""Knob-mode and categorical-branch coverage."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from v2b_syndata.renderers.dr_events import _NOTIF_LEAD_HOURS
from v2b_syndata.validate import validate


@pytest.mark.parametrize(
    "mode,extra,expected_start,expected_end,run_validate",
    [
        ("month", {}, datetime(2020, 4, 1), datetime(2020, 5, 1), True),
        ("full_year", {"ev_fleet.ev_count": 5}, datetime(2020, 1, 1), datetime(2021, 1, 1), False),
        (
            "custom",
            {"sim_window.start": "2020-04-01", "sim_window.custom_end": "2020-04-08"},
            datetime(2020, 4, 1),
            datetime(2020, 4, 8),
            True,
        ),
    ],
)
def test_sim_window_modes(mode, extra, expected_start, expected_end, run_validate, fast_generate, assert_sanity):
    overrides: dict = {"sim_window.mode": mode, **extra}
    if mode != "custom":
        overrides.update({"sim_window.start": None, "sim_window.custom_end": None})
    out, manifest = fast_generate(overrides=overrides)
    assert_sanity(out, manifest, expected_start=expected_start, expected_end=expected_end)
    if run_validate:
        rep = validate(out)
        assert rep.passed, f"mode={mode}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize("tariff", ["flat", "TOU", "demand_charge", "DR"])
def test_each_tariff(tariff, fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"utility_rate.tariff_type": tariff})
    assert_sanity(out, manifest)
    gp = pd.read_csv(out / "grid_prices.csv")
    if tariff == "flat":
        assert (gp["type"] == "off_peak").all()
        assert gp["price_per_kwh"].nunique() == 1
    rep = validate(out)
    assert rep.passed, f"tariff={tariff}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize(
    "program,lead_h",
    [
        ("none", None),
        ("CBP", _NOTIF_LEAD_HOURS["CBP"]),
        ("BIP", _NOTIF_LEAD_HOURS["BIP"]),
        ("ELRP", _NOTIF_LEAD_HOURS["ELRP"]),
    ],
)
def test_each_dr_program(program, lead_h, fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "utility_rate.dr_program": program,
            "sim_window.start": "2020-07-01",
            "sim_window.custom_end": "2020-08-01",
        }
    )
    assert_sanity(out, manifest, expected_start=datetime(2020, 7, 1), expected_end=datetime(2020, 8, 1))
    dr = pd.read_csv(out / "dr_events.csv")
    if program == "none":
        assert len(dr) == 0
    else:
        assert len(dr) > 0, f"expected DR events for {program}, got 0"
        leads = pd.to_datetime(dr["start"]) - pd.to_datetime(dr["notified_at"])
        assert (leads == pd.Timedelta(hours=lead_h)).all(), f"{program}: notification lead doesn't match {lead_h}h"


@pytest.mark.parametrize("hetero", ["homog", "mixed"])
def test_battery_heterogeneity(hetero, fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"ev_fleet.battery_heterogeneity": hetero})
    assert_sanity(out, manifest)
    cars = pd.read_csv(out / "cars.csv")
    if hetero == "homog":
        assert (
            cars["battery_class"].nunique() == 1
        ), f"homog should yield one battery_class; got {cars['battery_class'].unique()}"
    rep = validate(out)
    assert rep.passed, f"hetero={hetero}: {'; '.join(rep.errors)}"


def test_peak_window_wraparound(fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "utility_rate.tariff_type": "TOU",
            "utility_rate.peak_window": [22, 6],
        }
    )
    assert_sanity(out, manifest)
    gp = pd.read_csv(out / "grid_prices.csv")
    hours = pd.to_datetime(gp["datetime"]).dt.hour
    expected_peak = (hours >= 22) | (hours < 6)
    assert (
        (gp["type"] == "peak") == expected_peak
    ).all(), "peak/off_peak labels don't match wraparound peak_window=[22, 6]"
    rep = validate(out)
    assert rep.passed, f"wraparound: {'; '.join(rep.errors)}"


def test_weekdays_only_false(fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"sim_window.weekdays_only": False})
    assert_sanity(out, manifest)
    sess = pd.read_csv(out / "sessions.csv")
    if len(sess) > 0:
        weekday = pd.to_datetime(sess["arrival"]).dt.weekday
        assert (weekday >= 5).any(), "weekdays_only=False should produce at least one weekend session"
    rep = validate(out)
    assert rep.passed, f"weekdays_only=False: {'; '.join(rep.errors)}"


def test_month_mode_anchored_at_arbitrary_start(fast_generate, assert_sanity):
    """mode=month + start=2021-08-15 → window snaps to Aug 1, 2021 → Sep 1, 2021."""
    out, manifest = fast_generate(
        overrides={
            "sim_window.mode": "month",
            "sim_window.start": "2021-08-15",
            "sim_window.custom_end": None,
        }
    )
    assert_sanity(out, manifest, expected_start=datetime(2021, 8, 1), expected_end=datetime(2021, 9, 1))


def test_full_year_mode_anchored_at_arbitrary_start(fast_generate, assert_sanity):
    """mode=full_year + start=2021-08-15 → window snaps to Jan 1, 2021 → Jan 1, 2022."""
    out, manifest = fast_generate(
        overrides={
            "sim_window.mode": "full_year",
            "sim_window.start": "2021-08-15",
            "sim_window.custom_end": None,
            "ev_fleet.ev_count": 5,
        }
    )
    assert_sanity(out, manifest, expected_start=datetime(2021, 1, 1), expected_end=datetime(2022, 1, 1))
