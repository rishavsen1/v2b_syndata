"""Unit tests for the across-family model-selection harness
(tools/repro_paper.py step `family_selection`).

Pure-computation tests on synthetic data — no calibration caches, no
EnergyPlus, no network. The harness itself must be deterministic (fixed EM
init, Scott-factor KDE on a fixed grid, no free RNG), so two invocations on
the same array must return bit-identical scores.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import repro_paper as rp  # noqa: E402

# ── synthetic cells (seeded once; the harness itself consumes no RNG) ──

def _bimodal_arrival(n: int = 3000) -> np.ndarray:
    rng = np.random.default_rng(42)
    x = np.concatenate([rng.normal(8.0, 1.0, n // 2),
                        rng.normal(15.0, 2.0, n - n // 2)])
    return x[(x >= 4.0) & (x <= 22.0)]


def _bimodal_dwell(n: int = 3000) -> np.ndarray:
    rng = np.random.default_rng(43)
    x = np.concatenate([rng.weibull(2.0, n // 2) * 2.0,
                        rng.weibull(3.0, n - n // 2) * 9.0])
    return x[x > 0]


def _beta_soc(n: int = 2000) -> np.ndarray:
    rng = np.random.default_rng(44)
    return rng.beta(4.0, 6.0, n)


# ── arrival ────────────────────────────────────────────────────────────

def test_arrival_candidates_families_and_flags():
    rows = rp._family_candidates("arrival_hour", _bimodal_arrival())
    by = {r["family"]: r for r in rows}
    assert set(by) == {"truncnorm", "truncnorm_mix2", "gmm2_free", "kde"}
    # Deployment-constraint flags: KDE and the free GMM are scored only.
    assert by["truncnorm"]["shippable"] and by["truncnorm_mix2"]["shippable"]
    assert not by["gmm2_free"]["shippable"] and not by["kde"]["shippable"]
    # KDE carries no parametric likelihood → no AIC/BIC.
    assert by["kde"]["k_params"] is None
    assert by["truncnorm"]["k_params"] == 2
    assert by["truncnorm_mix2"]["k_params"] == 5
    # The free GMM records its out-of-window tail mass.
    assert "mass outside" in by["gmm2_free"]["note"]
    for r in rows:
        assert np.isfinite(r["ks"]) and 0.0 <= r["ks"] <= 1.0


def test_arrival_mixture_beats_single_on_bimodal_data():
    rows = {r["family"]: r for r in
            rp._family_candidates("arrival_hour", _bimodal_arrival())}
    assert rows["truncnorm_mix2"]["ks"] < rows["truncnorm"]["ks"] - 0.02
    # Likelihood must agree with KS on strongly bimodal data.
    assert rows["truncnorm_mix2"]["loglik"] > rows["truncnorm"]["loglik"]


def test_arrival_no_lognormal_candidate():
    """Lognormal is deliberately skipped for arrival (bounded clock window:
    the support origin would be a clock-zero artifact)."""
    fams = {r["family"] for r in
            rp._family_candidates("arrival_hour", _bimodal_arrival())}
    assert "lognorm" not in fams


# ── dwell ──────────────────────────────────────────────────────────────

def test_dwell_candidates_families_and_scores():
    rows = rp._family_candidates("dwell_hours", _bimodal_dwell())
    by = {r["family"]: r for r in rows}
    assert set(by) == {"weibull", "weibull_mix2", "lognorm", "gamma", "expon"}
    assert all(r["shippable"] for r in rows)
    assert by["expon"]["k_params"] == 1
    assert by["weibull_mix2"]["k_params"] == 5
    assert by["weibull_mix2"]["ks"] < by["weibull"]["ks"] - 0.02
    for r in rows:
        assert np.isfinite(r["ks"])


# ── SoC ────────────────────────────────────────────────────────────────

def test_soc_candidates_beta_beats_uniform_null():
    rows = {r["family"]: r for r in
            rp._family_candidates("soc_arrival", _beta_soc())}
    assert set(rows) == {"beta", "truncnorm01", "uniform01"}
    assert rows["beta"]["ks"] < rows["uniform01"]["ks"]
    # Uniform null: zero parameters, zero log-density on [0,1].
    assert rows["uniform01"]["k_params"] == 0
    assert rows["uniform01"]["loglik"] == 0.0


def test_unknown_variable_raises():
    with pytest.raises(ValueError, match="unknown variable"):
        rp._family_candidates("nope", np.ones(100))


# ── determinism ────────────────────────────────────────────────────────

@pytest.mark.parametrize("variable,data_fn", [
    ("arrival_hour", _bimodal_arrival),
    ("dwell_hours", _bimodal_dwell),
    ("soc_arrival", _beta_soc),
])
def test_candidates_are_deterministic(variable, data_fn):
    vals = data_fn()
    a = rp._family_candidates(variable, vals)
    b = rp._family_candidates(variable, vals)
    assert a == b  # bit-identical scores, notes and flags
