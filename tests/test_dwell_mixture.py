"""Task 4 — 2-component Weibull dwell mixture.

Mirrors the arrival mixture: a KS-beats-single gate decides whether the mixture
ships; the renderer inverts it by bisection on the SHARED copula uniform
(`_weibull_mixture_ppf_u`); the sampler exposes it on f_dwell.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from v2b_syndata.calibration.distribution_fitter import (
    fit_weibull_dwell,
    fit_weibull_mixture_dwell,
)
from v2b_syndata.renderers.sessions import _weibull_mixture_ppf_u


# --------------------------------------------------------------------------- #
# Renderer inverse-CDF
# --------------------------------------------------------------------------- #
def test_weibull_mixture_ppf_monotone_and_inverts():
    comps = [(0.6, 1.5, 3.0), (0.4, 2.5, 9.0)]  # (w, k, lambda)
    us = np.linspace(0.001, 0.999, 60)
    xs = [_weibull_mixture_ppf_u(u, comps) for u in us]
    assert all(x >= 0 for x in xs)
    assert all(b >= a - 1e-6 for a, b in zip(xs, xs[1:]))  # monotone

    def cdf(x):
        return sum(w * stats.weibull_min.cdf(x, k, scale=lam) for w, k, lam in comps)

    for u in (0.1, 0.5, 0.9):
        assert abs(cdf(_weibull_mixture_ppf_u(u, comps)) - u) < 1e-3


def test_weibull_mixture_ppf_single_component_matches_weibull():
    comps = [(1.0, 2.0, 8.0)]
    for u in (0.2, 0.5, 0.8):
        got = _weibull_mixture_ppf_u(u, comps)
        exp = float(stats.weibull_min.ppf(u, 2.0, scale=8.0))
        assert abs(got - exp) < 1e-3


# --------------------------------------------------------------------------- #
# Fitter selection gate
# --------------------------------------------------------------------------- #
def test_fitter_selects_dwell_mixture_on_bimodal():
    rng = np.random.default_rng(0)
    # short top-ups (~1.5h) + long workday dwells (~9h) → genuinely bimodal
    short = rng.weibull(2.0, 700) * 1.5
    long = rng.weibull(2.5, 500) * 11.0
    arr = np.concatenate([short, long])
    fit = fit_weibull_mixture_dwell(arr)
    assert fit is not None, "bimodal dwell should select the mixture"
    assert fit["dist"] == "weibull_mixture"
    assert {"w1", "k1", "lambda1", "k2", "lambda2"} <= set(fit)
    assert 0.0 <= fit["w1"] <= 1.0
    # mean-ordered components (lambda1 <= lambda2 as the proxy)
    assert fit["lambda1"] <= fit["lambda2"]


def test_fitter_keeps_single_on_unimodal_dwell():
    rng = np.random.default_rng(1)
    arr = rng.weibull(2.0, 1000) * 8.0
    assert fit_weibull_mixture_dwell(arr) is None
    single = fit_weibull_dwell(arr)
    assert single is not None and single["dist"] == "weibull"


def test_fitter_dwell_mixture_too_few_samples():
    rng = np.random.default_rng(2)
    assert fit_weibull_mixture_dwell(rng.weibull(2.0, 40) * 8.0) is None


def test_fitter_dwell_mixture_params_in_range():
    rng = np.random.default_rng(3)
    short = rng.weibull(2.0, 700) * 1.5
    long = rng.weibull(2.5, 500) * 11.0
    fit = fit_weibull_mixture_dwell(np.concatenate([short, long]))
    if fit is not None:
        for leaf, key in [("dwell.k", "k1"), ("dwell.k", "k2"),
                          ("dwell.lambda", "lambda1"), ("dwell.lambda", "lambda2")]:
            from v2b_syndata.knob_loader import DIST_PARAM_RANGES
            lo, hi = DIST_PARAM_RANGES[leaf]
            assert lo <= fit[key] <= hi
