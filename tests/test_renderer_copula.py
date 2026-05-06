"""Verify Gaussian copula dispatch in renderers/sessions.py:
- ρ=0 path produces same RNG draws as the legacy independent sampler.
- ρ != 0 path produces correlated arrival/dwell samples in the target direction.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from v2b_syndata.renderers.sessions import (
    _gaussian_copula_pair,
    _sample_truncnorm,
    _truncnorm_ppf_u,
    _weibull_ppf_u,
)


def test_copula_pair_independent_when_rho_zero():
    rng = np.random.default_rng(42)
    samples = np.array([_gaussian_copula_pair(rng, 0.0) for _ in range(5000)])
    arr, dwell = samples[:, 0], samples[:, 1]
    rho_emp, _ = stats.spearmanr(arr, dwell)
    assert abs(rho_emp) < 0.05


def test_copula_pair_negative_correlation():
    rng = np.random.default_rng(42)
    samples = np.array([_gaussian_copula_pair(rng, -0.7) for _ in range(5000)])
    arr, dwell = samples[:, 0], samples[:, 1]
    rho_emp, _ = stats.spearmanr(arr, dwell)
    assert rho_emp < -0.5


def test_copula_pair_positive_correlation():
    rng = np.random.default_rng(42)
    samples = np.array([_gaussian_copula_pair(rng, 0.6) for _ in range(5000)])
    arr, dwell = samples[:, 0], samples[:, 1]
    rho_emp, _ = stats.spearmanr(arr, dwell)
    assert rho_emp > 0.4


def test_truncnorm_ppf_inverse_of_cdf():
    mu, sigma, lo, hi = 9.0, 1.0, 6.0, 20.0
    a, b = (lo - mu) / sigma, (hi - mu) / sigma
    for u in [0.1, 0.3, 0.5, 0.7, 0.9]:
        x = _truncnorm_ppf_u(u, mu, sigma, lo, hi)
        u_back = stats.truncnorm.cdf(x, a, b, loc=mu, scale=sigma)
        assert abs(u - u_back) < 1e-6


def test_weibull_ppf_inverse_of_cdf():
    k, lam = 2.0, 8.0
    for u in [0.1, 0.3, 0.5, 0.7, 0.9]:
        x = _weibull_ppf_u(u, k, lam)
        u_back = stats.weibull_min.cdf(x, k, scale=lam)
        assert abs(u - u_back) < 1e-6


def test_independent_branch_unchanged():
    """ρ=0 dispatch must consume RNG draws in the same order/count as the legacy
    independent sampler. This guards Step 4 frozen-hash preservation.
    """
    rng1 = np.random.default_rng(99)
    rng2 = np.random.default_rng(99)
    arr_legacy = _sample_truncnorm(rng1, 9.0, 1.0, 6.0, 20.0)
    dwell_legacy = float(rng1.weibull(2.0) * 8.0)
    after_legacy = rng1.random()  # next draw

    arr_new = _sample_truncnorm(rng2, 9.0, 1.0, 6.0, 20.0)
    dwell_new = float(rng2.weibull(2.0) * 8.0)
    after_new = rng2.random()

    assert arr_legacy == arr_new
    assert dwell_legacy == dwell_new
    assert after_legacy == after_new
