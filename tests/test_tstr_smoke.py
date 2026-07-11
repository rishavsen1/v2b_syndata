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


# --------------------------------------------------------------------------- #
# normalization + matched-scenario default
# --------------------------------------------------------------------------- #
def test_normalize_series_unit_mean_and_zero_preserved():
    idx = pd.date_range("2020-04-01", periods=4, freq="1h")
    load = pd.Series([0.0, 10.0, 20.0, 30.0], index=idx)
    norm = tstr.normalize_series(load, float(load.mean()))
    assert norm.mean() == pytest.approx(1.0)
    assert norm.iloc[0] == 0.0  # zeros preserved (unlike z-scoring)
    # invalid reference means raise
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            tstr.normalize_series(load, bad)


def test_normalization_removes_pure_scale_mismatch():
    """Same generative law at 50x magnitude (pure rescale): raw TSTR is
    scale-dominated; after per-cohort unit-mean normalization TSTR ~ TRTR."""
    load_real = _toy_load(400, seed=0) * 50.0
    load_synth = _toy_load(400, seed=1)
    raw = tstr.run_tstr(load_real, load_synth, seed=tstr.SEED)
    real_train_mean = float(tstr.split_real(load_real)[0].mean())
    norm = tstr.run_tstr(
        tstr.normalize_series(load_real, real_train_mean),
        tstr.normalize_series(load_synth, float(load_synth.mean())),
        seed=tstr.SEED,
    )
    assert raw["TSTR_over_TRTR_ratio"]["mae"] > 10  # scale mismatch dominates raw
    assert norm["TSTR_over_TRTR_ratio"]["mae"] < 3  # shape transfer recovered


def test_default_scenario_matched_to_real_source():
    """Regression for the adverse results_elaadnl.json artifact: the scenario
    default must follow --real, never silently cross-pair."""
    assert tstr.DEFAULT_SCENARIO["acn"] == "S_acn_caltech"
    assert tstr.DEFAULT_SCENARIO["elaadnl"] == "S_elaadnl_public_eu"
    # every --real choice has a matched default
    assert set(tstr.DEFAULT_SCENARIO) == {"acn", "elaadnl"}


# --------------------------------------------------------------------------- #
# multi-month generation (--months) + knob-override passthrough
# --------------------------------------------------------------------------- #
def test_month_starts_tiling():
    starts = tstr.month_starts(pd.Timestamp("2020-04-17 09:30"), 12)
    assert len(starts) == 12
    assert starts[0] == pd.Timestamp("2020-04-01")   # snapped to first-of-month
    assert starts[1] == pd.Timestamp("2020-05-01")
    assert starts[-1] == pd.Timestamp("2021-03-01")  # wraps the year boundary
    # consecutive months tile the calendar: each start is the next month's 1st
    for a, b in zip(starts, starts[1:], strict=False):
        assert b == a + pd.DateOffset(months=1)
    with pytest.raises(ValueError):
        tstr.month_starts(pd.Timestamp("2020-04-01"), 0)


def _fake_generate_factory(calls: list[dict]):
    """A stand-in for v2b_syndata.runner.generate that records its call args
    and writes a minimal per-month sessions.csv/cars.csv (2 sessions)."""
    def fake_generate(*, scenario_id, seed, output_dir, config_dir,
                      cli_overrides=None, **kw):
        calls.append({"scenario_id": scenario_id, "seed": seed,
                      "cli_overrides": cli_overrides})
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        start = pd.Timestamp((cli_overrides or {}).get(
            "sim_window.start", "2020-04-01"))
        pd.DataFrame({
            "car_id": [1, 2],
            "arrival": [start + pd.Timedelta(hours=8),
                        start + pd.Timedelta(hours=9)],
            "departure": [start + pd.Timedelta(hours=12),
                          start + pd.Timedelta(hours=17)],
            "arrival_soc": [40.0, 50.0],
            "required_soc_at_depart": [80.0, 90.0],
        }).to_csv(output_dir / "sessions.csv", index=False)
        pd.DataFrame({"car_id": [1, 2], "capacity_kwh": [60.0, 80.0]}
                     ).to_csv(output_dir / "cars.csv", index=False)
        return {
            "generator_version": "test", "generator_git_sha": "deadbeef",
            "e5": {"realized_max_concurrent": 2, "n_chargers": 20,
                   "infeasible": False},
            "validation": {"passed": True, "n_errors": 0, "n_warnings": 0},
        }
    return fake_generate


def test_generate_cohort_single_month_default_path(tmp_path, monkeypatch):
    """months=1, no overrides => exactly one generate() call with
    cli_overrides=None and NO sim_window.start injection (the byte-identical
    historical path)."""
    import v2b_syndata.runner as runner
    calls: list[dict] = []
    monkeypatch.setattr(runner, "generate", _fake_generate_factory(calls))
    sessions, stamp = tstr.generate_synthetic_cohort(
        "S_elaadnl_public_eu", 1234, 1, tmp_path / "syn")
    assert len(calls) == 1
    assert calls[0]["cli_overrides"] is None
    assert len(sessions) == 2
    assert stamp["sim_months"] == 1
    assert stamp["knob_overrides"] == {}
    assert len(stamp["per_month"]) == 1
    assert stamp["per_month"][0]["month_start"] == "scenario-default"


def test_generate_cohort_multi_month_consecutive_and_overrides(tmp_path, monkeypatch):
    """months=3 + knob overrides: month 0 keeps the scenario anchor (no
    injected start), months 1..2 advance sim_window.start by one calendar
    month; the knob overrides are forwarded to EVERY call; sessions
    concatenate across months."""
    import v2b_syndata.runner as runner
    calls: list[dict] = []
    monkeypatch.setattr(runner, "generate", _fake_generate_factory(calls))
    sessions, stamp = tstr.generate_synthetic_cohort(
        "S_elaadnl_public_eu", 1234, 3, tmp_path / "syn",
        overrides={"ev_fleet.ev_count": 1000,
                   "charging_infra.charger_count": 500})
    assert len(calls) == 3
    # month 0: scenario anchor, no injected start; overrides still forwarded
    assert "sim_window.start" not in calls[0]["cli_overrides"]
    assert calls[0]["cli_overrides"]["ev_fleet.ev_count"] == 1000
    # months 1..2: consecutive first-of-month anchors from the scenario's
    # own sim_window.start (S_elaadnl_public_eu => 2020-04-01)
    assert calls[1]["cli_overrides"]["sim_window.start"] == "2020-05-01"
    assert calls[2]["cli_overrides"]["sim_window.start"] == "2020-06-01"
    for c in calls:
        assert c["cli_overrides"]["charging_infra.charger_count"] == 500
        assert c["seed"] == 1234  # same fleet: seed constant across months
    assert len(sessions) == 6  # 2 per month, concatenated
    assert stamp["sim_months"] == 3
    assert stamp["n_sessions"] == 6
    assert [pm["n_sessions"] for pm in stamp["per_month"]] == [2, 2, 2]
    assert stamp["knob_overrides"] == {
        "charging_infra.charger_count": "500", "ev_fleet.ev_count": "1000"}


def test_cli_months_flag_and_alias():
    """--months and the legacy --sim-months spelling parse to the same dest;
    --override is repeatable; defaults preserve the historical behavior."""
    ap = tstr.build_arg_parser()
    a = ap.parse_args(["--months", "12", "--override", "a.b=1",
                       "--override", "c.d=2"])
    assert a.months == 12 and a.override == ["a.b=1", "c.d=2"]
    b = ap.parse_args(["--sim-months", "3"])
    assert b.months == 3
    d = ap.parse_args([])
    assert d.months == 1 and d.override == []


def test_format_table_runs():
    load_real = _toy_load(400, seed=0)
    load_synth = _toy_load(400, seed=1)
    res = tstr.run_tstr(load_real, load_synth)
    table = tstr.format_table(res)
    assert "TRTR" in table and "TSTR" in table and "TRTS" in table
