"""Smoke tests for the TSTR forecasting utility-proof harness.

These exercise the pure pieces (session->load aggregation, feature building,
metrics, and the full TRTR/TSTR/TRTS experiment) on tiny synthetic fixtures.
They deliberately do NOT run `runner.generate` or load the multi-thousand-row
real caches (too slow for CI) — those paths are covered by the manual baseline
run documented in the harness report.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "tstr_forecasting", REPO / "tools" / "tstr_forecasting.py")
tstr = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module by name.
sys.modules["tstr_forecasting"] = tstr
_spec.loader.exec_module(tstr)


# --------------------------------------------------------------------------- #
# sessions_to_load_series
# --------------------------------------------------------------------------- #
def test_single_session_energy_conserved():
    """A 10 kWh session over exactly 2h => 5 kW for two 1h bins."""
    s = tstr.Session(connect=pd.Timestamp("2020-04-01 00:00"), dwell_hours=2.0, kwh=10.0)
    load = tstr.sessions_to_load_series([s], freq="1h")
    assert list(load.values) == pytest.approx([5.0, 5.0])
    # total energy = sum(kW * bin_hours) preserved
    assert load.sum() * 1.0 == pytest.approx(10.0)


def test_partial_bin_overlap_prorated():
    """Session from 00:30 to 01:30 (1h, 6 kWh => 6 kW) splits across two bins:
    half an hour in each => 3 kWh each => mean 3 kW in bin0, 3 kW in bin1."""
    s = tstr.Session(connect=pd.Timestamp("2020-04-01 00:30"), dwell_hours=1.0, kwh=6.0)
    load = tstr.sessions_to_load_series([s], freq="1h")
    # bin0 [00:00,01:00) gets 0.5h*6kW=3kWh => 3kW; bin1 likewise.
    assert load.iloc[0] == pytest.approx(3.0)
    assert load.iloc[1] == pytest.approx(3.0)
    assert load.sum() == pytest.approx(6.0)


def test_concurrent_sessions_sum():
    a = tstr.Session(connect=pd.Timestamp("2020-04-01 00:00"), dwell_hours=1.0, kwh=4.0)
    b = tstr.Session(connect=pd.Timestamp("2020-04-01 00:00"), dwell_hours=1.0, kwh=6.0)
    load = tstr.sessions_to_load_series([a, b], freq="1h")
    assert load.iloc[0] == pytest.approx(10.0)


def test_15min_freq():
    s = tstr.Session(connect=pd.Timestamp("2020-04-01 00:00"), dwell_hours=1.0, kwh=8.0)
    load = tstr.sessions_to_load_series([s], freq="15min")
    # 8 kWh over 1h => constant 8 kW across four 15-min bins.
    assert len(load) == 4
    assert list(load.values) == pytest.approx([8.0, 8.0, 8.0, 8.0])


def test_tz_aware_connect_handled():
    s = tstr.Session(connect=pd.Timestamp("2020-04-01 00:00", tz="UTC"),
                     dwell_hours=2.0, kwh=10.0)
    load = tstr.sessions_to_load_series([s], freq="1h")
    assert load.index.tz is None
    assert load.sum() == pytest.approx(10.0)


def test_empty_or_invalid_raises():
    with pytest.raises(ValueError):
        tstr.sessions_to_load_series([], freq="1h")
    with pytest.raises(ValueError):
        tstr.sessions_to_load_series(
            [tstr.Session(connect=pd.Timestamp("2020-04-01"), dwell_hours=0.0, kwh=5.0)])


# --------------------------------------------------------------------------- #
# build_features
# --------------------------------------------------------------------------- #
def test_build_features_shapes_and_cols():
    idx = pd.date_range("2020-04-01", periods=50, freq="1h")
    load = pd.Series(np.arange(50, dtype=float), index=idx)
    X, y = tstr.build_features(load, lags=(1, 2, 24))
    assert list(X.columns) == ["hour", "dow", "lag_1", "lag_2", "lag_24"]
    # first 24 rows dropped (max lag = 24)
    assert len(X) == 50 - 24
    assert len(y) == len(X)
    assert not X.isna().any().any()


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_metrics_perfect_prediction():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    m = tstr.metrics(y, y.copy())
    assert m["mae"] == pytest.approx(0.0)
    assert m["rmse"] == pytest.approx(0.0)
    assert m["mape"] == pytest.approx(0.0)


def test_metrics_known_values():
    y = np.array([10.0, 10.0])
    p = np.array([12.0, 8.0])
    m = tstr.metrics(y, p)
    assert m["mae"] == pytest.approx(2.0)
    assert m["rmse"] == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# full experiment on synthetic fixtures
# --------------------------------------------------------------------------- #
def _toy_load(n: int, seed: int, scale: float = 1.0) -> pd.Series:
    """A learnable daily-periodic series with noise."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="1h")
    hour = idx.hour.values
    base = scale * (5 + 4 * np.sin(2 * np.pi * hour / 24.0))
    return pd.Series(base + rng.normal(0, 0.3, n), index=idx)


def test_run_tstr_end_to_end_smoke():
    load_real = _toy_load(400, seed=0, scale=1.0)
    load_synth = _toy_load(400, seed=1, scale=1.0)  # same generative law
    res = tstr.run_tstr(load_real, load_synth, seed=tstr.SEED)
    for setting in ("TRTR", "TSTR", "TRTS"):
        assert set(res[setting]) == {"mae", "rmse", "mape"}
        assert res[setting]["mae"] >= 0
    # When synth follows the same law, TSTR should be in the same ballpark as
    # TRTR (transfer works) — not catastrophically worse.
    assert res["TSTR"]["mae"] < 5 * res["TRTR"]["mae"] + 1.0
    assert "TSTR_minus_TRTR" in res
    assert "TSTR_over_TRTR_ratio" in res


def test_run_tstr_calendar_only_feature_set():
    """lags=() => calendar-only probe; columns are just hour+dow."""
    load = _toy_load(400, seed=0)
    X, y = tstr.build_features(load, lags=())
    assert list(X.columns) == ["hour", "dow"]
    assert len(X) == len(load)  # nothing dropped without lags
    res = tstr.run_tstr(load, _toy_load(400, seed=1), seed=tstr.SEED, lags=())
    for setting in ("TRTR", "TSTR", "TRTS"):
        assert res[setting]["mae"] >= 0


def test_run_tstr_insufficient_samples_raises():
    load_real = _toy_load(30, seed=0)
    load_synth = _toy_load(30, seed=1)
    with pytest.raises(ValueError):
        tstr.run_tstr(load_real, load_synth)


def test_run_tstr_deterministic():
    load_real = _toy_load(400, seed=0)
    load_synth = _toy_load(400, seed=1)
    r1 = tstr.run_tstr(load_real, load_synth, seed=7)
    r2 = tstr.run_tstr(load_real, load_synth, seed=7)
    assert r1["TSTR"] == r2["TSTR"]
    assert r1["TRTR"] == r2["TRTR"]


def test_format_table_runs():
    load_real = _toy_load(400, seed=0)
    load_synth = _toy_load(400, seed=1)
    res = tstr.run_tstr(load_real, load_synth)
    table = tstr.format_table(res)
    assert "TRTR" in table and "TSTR" in table and "TRTS" in table
