"""Tests for battery_inference."""
from __future__ import annotations

import pandas as pd

from v2b_syndata.calibration.battery_inference import (
    DEFAULT_CAPACITY_KWH,
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.feature_extractor import SessionFeatures


def _make_session(**kwargs) -> SessionFeatures:
    base = dict(
        user_id="u",
        site="caltech",
        arrival_time=pd.Timestamp("2020-01-06 09:00", tz="UTC"),
        arrival_hour=9.0,
        dwell_hours=8.0,
        kwh_delivered=10.0,
        miles_requested=None,
        wh_per_mile=None,
        kwh_requested=None,
        minutes_available=None,
    )
    base.update(kwargs)
    return SessionFeatures(**base)


def test_infer_capacity_default_wpm_falls_back():
    s = _make_session(wh_per_mile=299, miles_requested=50, kwh_requested=10)
    cap, src = infer_capacity(s)
    assert src == "fallback"
    assert cap == DEFAULT_CAPACITY_KWH


def test_infer_capacity_no_userinputs_falls_back():
    s = _make_session()
    cap, src = infer_capacity(s)
    assert src == "fallback"
    assert cap == DEFAULT_CAPACITY_KWH


def test_infer_capacity_inferred_in_range():
    # 1.5 * 100 mi * 250 Wh/mi / 1000 = 37.5 kWh — in [20, 130]
    s = _make_session(wh_per_mile=250, miles_requested=100, kwh_requested=25)
    cap, src = infer_capacity(s)
    assert src == "inferred"
    assert 35.0 < cap < 40.0


def test_infer_capacity_oversize_falls_back():
    # 1.5 * 500 mi * 300 Wh/mi / 1000 = 225 kWh — out of range
    s = _make_session(wh_per_mile=300, miles_requested=500, kwh_requested=100)
    cap, src = infer_capacity(s)
    assert src == "fallback"
    assert cap == DEFAULT_CAPACITY_KWH


def test_reconstruct_arrival_soc():
    s = _make_session(kwh_requested=12.0)
    soc = reconstruct_arrival_soc(s, capacity_kwh=60.0)
    assert soc == 0.8  # 1 - 12/60


def test_reconstruct_arrival_soc_no_kwh_requested():
    s = _make_session()
    assert reconstruct_arrival_soc(s, 60.0) is None


def test_reconstruct_arrival_soc_clamps():
    s = _make_session(kwh_requested=80.0)  # exceeds capacity
    soc = reconstruct_arrival_soc(s, capacity_kwh=60.0)
    assert soc == 0.0
