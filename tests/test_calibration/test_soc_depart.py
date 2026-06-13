"""Departure-SoC requirement calibration (soc_depart)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from v2b_syndata.calibration.battery_inference import reconstruct_arrival_soc
from v2b_syndata.calibration.distribution_fitter import fit_beta_soc, fit_region
from v2b_syndata.calibration.feature_extractor import SessionFeatures

REPO = Path(__file__).resolve().parents[2]
ACN_COHORTS = [
    "acn_workplace_baseline", "acn_caltech_baseline",
    "acn_jpl_baseline", "acn_office001_baseline",
]
# ElaadNL is calibrated via the estimated-arrival path (no requested energy).
CALIBRATED_COHORTS = ACN_COHORTS + ["elaadnl_public_eu"]
CALIBRATED_SCENARIOS = [
    "S_acn_workplace", "S_acn_caltech", "S_acn_jpl", "S_acn_office001",
    "S_elaadnl_public_eu",
]


def _sess(kwh_requested, kwh_delivered=10.0):
    return SessionFeatures(
        user_id="u", site="s", arrival_time=pd.Timestamp("2020-04-06 09:00:00"),
        arrival_hour=9.0, dwell_hours=4.0, kwh_delivered=kwh_delivered,
        miles_requested=None, wh_per_mile=None,
        kwh_requested=kwh_requested, minutes_available=None,
    )


def test_reconstruct_arrival_soc_exact_with_requested():
    assert abs(reconstruct_arrival_soc(_sess(30.0), 60.0) - 0.5) < 1e-9


def test_reconstruct_arrival_soc_estimated_without_requested():
    s = _sess(kwh_requested=None)
    assert reconstruct_arrival_soc(s, 60.0) is None          # no rng → None
    rng = np.random.default_rng(0)
    vals = [reconstruct_arrival_soc(s, 60.0, rng=rng) for _ in range(300)]
    assert all(0.05 <= v <= 0.95 for v in vals)
    assert 0.30 < float(np.mean(vals)) < 0.50                # ~prior mean 0.40


def test_fit_beta_soc_depart_leaf_prefix():
    """soc_depart fits a Beta and validates against the soc_depart range table."""
    rng = np.random.default_rng(0)
    socs = rng.beta(2.0, 0.6, size=500)          # mean ~0.77, spread to 1.0
    fit = fit_beta_soc(socs, leaf_prefix="soc_depart")
    assert fit is not None
    assert fit["dist"] == "beta" and fit["alpha"] > 0 and fit["beta"] > 0


def test_fit_beta_soc_nonconvergence_returns_none():
    """Degenerate (piled at 1.0) data must not crash — MLE failure → None."""
    socs = np.full(500, 1.0 - 1e-9)              # constant after clip → FitError
    assert fit_beta_soc(socs, leaf_prefix="soc_depart") is None


def test_fit_region_emits_soc_depart_when_provided():
    rng = np.random.default_rng(1)
    arrivals = np.clip(rng.normal(9.0, 1.5, 200), 6.1, 19.9)
    dwells = np.clip(rng.weibull(2.0, 200) * 8.0, 0.6, 13.0)
    soc_arr = rng.beta(4.0, 6.0, 200)
    soc_dep = rng.beta(2.0, 0.6, 200)
    fit = fit_region(arrivals, dwells, soc_arr, soc_departs=soc_dep)
    assert fit["soc_depart"] is not None and fit["soc_depart"]["dist"] == "beta"
    # No soc_departs → no soc_depart block (backward compatible).
    assert fit_region(arrivals, dwells, soc_arr)["soc_depart"] is None


def test_calibrated_cohorts_have_soc_depart_and_no_floor():
    """Config guard: every data-calibrated cohort (ACN + ElaadNL) carries a
    soc_depart block and drops the arbitrary 80% floor (min_depart_soc=0)."""
    pops = yaml.safe_load((REPO / "configs" / "populations.yaml").read_text())
    for pop in CALIBRATED_COHORTS:
        rd = pops[pop]["region_distributions"]
        assert any("soc_depart" in b for b in rd.values()), f"{pop}: no soc_depart"

    for scen in CALIBRATED_SCENARIOS:
        sc = yaml.safe_load((REPO / "configs" / "scenarios" / f"{scen}.yaml").read_text())
        assert sc["overrides"]["user_behavior.min_depart_soc"] == 0.0
