"""Unit tests for inhomogeneous Poisson DR sampler (Step 6)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from v2b_syndata.samplers.dr_sampler import (
    PROGRAM_SPECS,
    _apply_caps,
    _dow_factor,
    _seasonal_factor,
    _temp_factor,
    _tod_factor,
    compute_rate,
    sample_dr_events,
)


def test_seasonal_factor_in_season():
    spec = PROGRAM_SPECS["CBP"]
    assert _seasonal_factor(7, spec) == 1.0   # July
    assert _seasonal_factor(2, spec) == 0.0   # February


def test_seasonal_factor_bip_year_round():
    spec = PROGRAM_SPECS["BIP"]
    for month in range(1, 13):
        assert _seasonal_factor(month, spec) == 1.0


def test_dow_factor_weekday_vs_weekend():
    assert _dow_factor(0) == 1.0
    assert _dow_factor(4) == 1.0
    assert _dow_factor(5) < 1.0
    assert _dow_factor(6) < 1.0


def test_temp_factor_monotonic_and_capped():
    assert _temp_factor(70) == 0.1
    assert _temp_factor(70) < _temp_factor(85) < _temp_factor(95) < _temp_factor(110)
    assert _temp_factor(110) == 3.0
    assert _temp_factor(150) == 3.0


def test_tod_factor_peaks_afternoon():
    assert _tod_factor(8) == 0.0
    assert _tod_factor(11) == 0.0
    assert _tod_factor(15) == 1.0
    assert _tod_factor(16) == 1.0
    assert _tod_factor(17) == 1.0
    assert _tod_factor(20) == 0.0
    assert _tod_factor(22) == 0.0
    assert 0 < _tod_factor(12) < 1.0
    assert 0 < _tod_factor(19) < 1.0


def test_compute_rate_combines_factors():
    spec = PROGRAM_SPECS["CBP"]
    # In-season weekday afternoon hot day:
    # 0.1 × 1.0 × 1.0 × 2.5 (95°F) × 1.0 = 0.25
    t = pd.Timestamp("2020-07-15 15:00")  # Wed, July, 3pm
    rate = compute_rate(t, max_temp_f_today=95.0, program_spec=spec, lambda_base=0.1)
    assert 0.20 <= rate <= 0.30


def test_compute_rate_zero_out_of_season():
    spec = PROGRAM_SPECS["CBP"]
    t = pd.Timestamp("2020-02-15 15:00")
    rate = compute_rate(t, max_temp_f_today=95.0, program_spec=spec, lambda_base=0.1)
    assert rate == 0.0


def test_compute_rate_zero_outside_tod_window():
    spec = PROGRAM_SPECS["BIP"]  # year-round
    t = pd.Timestamp("2020-07-15 03:00")  # 3am
    rate = compute_rate(t, max_temp_f_today=95.0, program_spec=spec, lambda_base=0.1)
    assert rate == 0.0


def test_sample_dr_events_deterministic_given_seed():
    daily_temps = pd.Series(
        [95.0, 100.0, 92.0, 88.0, 105.0, 90.0, 85.0] * 13,
        index=pd.date_range("2020-06-01", periods=91, freq="D"),
    )
    args = dict(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP",
        lambda_base=0.05,
        magnitude_kw_range=(50.0, 200.0),
    )
    e1 = sample_dr_events(rng=np.random.default_rng(42), **args)
    e2 = sample_dr_events(rng=np.random.default_rng(42), **args)
    assert len(e1) == len(e2)
    for a, b in zip(e1, e2):
        assert a["start"] == b["start"]
        assert a["magnitude_kw"] == b["magnitude_kw"]


def test_sample_dr_events_respects_monthly_cap():
    daily_temps = pd.Series(
        [110.0] * 91,
        index=pd.date_range("2020-06-01", periods=91, freq="D"),
    )
    events = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP",
        lambda_base=1.0,
        magnitude_kw_range=(50.0, 200.0),
        rng=np.random.default_rng(0),
    )
    assert len(events) <= 18  # CBP cap 6/month × 3 months
    df = pd.DataFrame(events)
    df["month"] = pd.to_datetime(df["start"]).dt.month
    for month, count in df.groupby("month").size().items():
        assert count <= 6, f"month {month}: {count} > 6"


def test_sample_dr_events_zero_out_of_season():
    daily_temps = pd.Series(
        [95.0] * 60,
        index=pd.date_range("2020-01-01", periods=60, freq="D"),
    )
    events = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-01-01"),
        sim_window_end=pd.Timestamp("2020-03-01"),
        daily_max_temp_f=daily_temps,
        program="CBP",
        lambda_base=1.0,
        magnitude_kw_range=(50.0, 200.0),
        rng=np.random.default_rng(0),
    )
    assert events == []


def test_sample_dr_events_weekday_skew():
    daily_temps = pd.Series(
        [95.0] * 91,
        index=pd.date_range("2020-06-01", periods=91, freq="D"),
    )
    events = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP",
        lambda_base=0.1,
        magnitude_kw_range=(50.0, 200.0),
        rng=np.random.default_rng(0),
    )
    if len(events) > 10:
        weekday = sum(1 for e in events if pd.to_datetime(e["start"]).weekday() < 5)
        assert weekday / len(events) > 0.6


def test_sample_dr_events_elrp_season_cap():
    daily_temps = pd.Series(
        [110.0] * 153,
        index=pd.date_range("2020-05-01", periods=153, freq="D"),
    )
    events = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-05-01"),
        sim_window_end=pd.Timestamp("2020-10-01"),
        daily_max_temp_f=daily_temps,
        program="ELRP",
        lambda_base=2.0,
        magnitude_kw_range=(50.0, 300.0),
        rng=np.random.default_rng(0),
    )
    assert len(events) <= 10


def test_sample_dr_events_magnitude_within_range():
    daily_temps = pd.Series(
        [100.0] * 91,
        index=pd.date_range("2020-06-01", periods=91, freq="D"),
    )
    events = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP",
        lambda_base=0.5,
        magnitude_kw_range=(120.0, 180.0),
        rng=np.random.default_rng(0),
    )
    assert len(events) > 0
    for e in events:
        assert 120.0 <= e["magnitude_kw"] <= 180.0


def test_sample_dr_events_notification_lead_per_program():
    daily_temps = pd.Series(
        [100.0] * 91,
        index=pd.date_range("2020-06-01", periods=91, freq="D"),
    )
    for program, expected_lead in (("CBP", 24), ("BIP", 2), ("ELRP", 2)):
        events = sample_dr_events(
            sim_window_start=pd.Timestamp("2020-06-01"),
            sim_window_end=pd.Timestamp("2020-08-31"),
            daily_max_temp_f=daily_temps,
            program=program,
            lambda_base=0.3,
            magnitude_kw_range=(50.0, 200.0),
            rng=np.random.default_rng(0),
        )
        assert len(events) > 0, program
        for e in events:
            lead_hours = (e["start"] - e["notified_at"]).total_seconds() / 3600
            assert lead_hours == pytest.approx(expected_lead), f"{program}: {lead_hours} != {expected_lead}"


def test_sample_dr_events_event_duration_per_program():
    daily_temps = pd.Series([100.0] * 91, index=pd.date_range("2020-06-01", periods=91, freq="D"))
    for program in ("CBP", "BIP", "ELRP"):
        events = sample_dr_events(
            sim_window_start=pd.Timestamp("2020-06-01"),
            sim_window_end=pd.Timestamp("2020-08-31"),
            daily_max_temp_f=daily_temps,
            program=program, lambda_base=0.3,
            magnitude_kw_range=(50.0, 200.0),
            rng=np.random.default_rng(0),
        )
        for e in events:
            dur = (e["end"] - e["start"]).total_seconds() / 3600
            assert dur == 4.0


def test_sample_dr_events_unknown_program_raises():
    with pytest.raises(ValueError, match="unsupported DR program"):
        sample_dr_events(
            sim_window_start=pd.Timestamp("2020-06-01"),
            sim_window_end=pd.Timestamp("2020-07-01"),
            daily_max_temp_f=pd.Series(dtype=float),
            program="DRAM",
            lambda_base=0.1,
            magnitude_kw_range=(50.0, 200.0),
            rng=np.random.default_rng(0),
        )


def test_apply_caps_chronological_retention():
    spec = PROGRAM_SPECS["CBP"]
    candidates = [pd.Timestamp(f"2020-07-{d:02d} 15:00") for d in range(1, 11)]
    kept = _apply_caps(candidates, spec)
    # CBP cap = 6/month. First 6 chronologically retained.
    assert len(kept) == 6
    assert kept == candidates[:6]


def test_sample_dr_events_higher_lambda_more_events():
    daily_temps = pd.Series([95.0] * 91, index=pd.date_range("2020-06-01", periods=91, freq="D"))
    low = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP", lambda_base=0.01,
        magnitude_kw_range=(50.0, 200.0),
        rng=np.random.default_rng(0),
    )
    high = sample_dr_events(
        sim_window_start=pd.Timestamp("2020-06-01"),
        sim_window_end=pd.Timestamp("2020-08-31"),
        daily_max_temp_f=daily_temps,
        program="CBP", lambda_base=0.5,
        magnitude_kw_range=(50.0, 200.0),
        rng=np.random.default_rng(0),
    )
    assert len(high) > len(low)
