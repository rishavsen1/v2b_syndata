"""Tests for battery_inference."""
from __future__ import annotations

import numpy as np
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


def test_reconstruct_arrival_soc_prior_draw_ignores_requested():
    # Arrival SoC is drawn from the prior regardless of requested energy
    # (uniform across sources — no 1-requested/capacity path).
    rng = np.random.default_rng(0)
    s = _make_session(kwh_requested=12.0)          # would have been 0.8 under 1-req/cap
    vals = [reconstruct_arrival_soc(s, 60.0, rng=rng) for _ in range(300)]
    assert all(0.05 <= v <= 0.95 for v in vals)
    assert 0.30 < float(np.mean(vals)) < 0.50      # ~prior mean 0.40, not 0.8


def test_reconstruct_arrival_soc_no_rng_is_none():
    # Without an rng, arrival can't be drawn → None, with or without requested.
    assert reconstruct_arrival_soc(_make_session(kwh_requested=12.0), 60.0) is None
    assert reconstruct_arrival_soc(_make_session(), 60.0) is None


def test_reconstruct_arrival_soc_invalid_capacity_is_none():
    assert reconstruct_arrival_soc(
        _make_session(kwh_requested=12.0), 0.0, rng=np.random.default_rng(0)
    ) is None
