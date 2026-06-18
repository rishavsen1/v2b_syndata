"""2-component arrival mixture: quantile math + BIC-gated fit selection."""
from __future__ import annotations

import numpy as np

from v2b_syndata.calibration.distribution_fitter import (
    fit_truncnorm_arrival,
    fit_truncnorm_mixture_arrival,
)
from v2b_syndata.renderers.sessions import _mixture_ppf_u


def test_mixture_ppf_monotone_and_inverts():
    comps = [(0.6, 8.0, 0.8), (0.4, 14.0, 1.2)]
    lo, hi = 6.0, 20.0
    us = np.linspace(0.001, 0.999, 50)
    xs = [_mixture_ppf_u(u, comps, lo, hi) for u in us]
    # within support + monotone non-decreasing
    assert all(lo <= x <= hi for x in xs)
    assert all(b >= a - 1e-6 for a, b in zip(xs, xs[1:]))
    # round-trip: cdf(ppf(u)) ≈ u
    from scipy import stats

    def cdf(x):
        return sum(w * stats.truncnorm.cdf(x, (lo - m) / s, (hi - m) / s, loc=m, scale=s)
                   for w, m, s in comps)
    for u in (0.1, 0.5, 0.9):
        assert abs(cdf(_mixture_ppf_u(u, comps, lo, hi)) - u) < 1e-3


def test_fitter_selects_mixture_on_bimodal():
    rng = np.random.default_rng(0)
    arr = np.concatenate([rng.normal(8.0, 0.5, 600), rng.normal(14.0, 1.0, 400)])
    arr = np.clip(arr, 6.01, 19.99)
    fit = fit_truncnorm_mixture_arrival(arr)
    assert fit is not None, "bimodal sample should select the mixture"
    assert fit["dist"] == "truncnorm_mixture"
    assert fit["mu1"] < fit["mu2"]                       # mean-ordered
    assert 0.0 <= fit["w1"] <= 1.0
    assert 6.0 <= fit["mu1"] <= 20.0 and 6.0 <= fit["mu2"] <= 20.0
    assert {"w1", "mu1", "sigma1", "mu2", "sigma2"} <= set(fit)


def test_fitter_keeps_single_on_unimodal():
    rng = np.random.default_rng(1)
    arr = np.clip(rng.normal(9.0, 1.0, 1000), 6.01, 19.99)
    # unimodal → mixture not justified → None → caller falls back to single
    assert fit_truncnorm_mixture_arrival(arr) is None
    single = fit_truncnorm_arrival(arr)
    assert single is not None and single["dist"] == "truncnorm"


def test_fitter_too_few_samples():
    rng = np.random.default_rng(2)
    assert fit_truncnorm_mixture_arrival(rng.normal(9, 1, 40)) is None
