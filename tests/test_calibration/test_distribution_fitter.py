"""Tests for distribution_fitter — synthetic data with known params → recover."""
from __future__ import annotations

import numpy as np
import scipy.stats as st

from v2b_syndata.calibration.distribution_fitter import (
    fit_beta_soc,
    fit_copula_rho,
    fit_truncnorm_arrival,
    fit_weibull_dwell,
)


def test_fit_truncnorm_recovers():
    rng = np.random.default_rng(0)
    a, b = 6.0, 20.0
    mu, sig = 9.0, 1.5
    a_std, b_std = (a - mu) / sig, (b - mu) / sig
    samples = st.truncnorm.rvs(a_std, b_std, loc=mu, scale=sig, size=5000, random_state=rng)
    fit = fit_truncnorm_arrival(samples)
    assert fit["dist"] == "truncnorm"
    assert abs(fit["mu"] - mu) < 0.1
    assert abs(fit["sigma"] - sig) < 0.15
    assert fit["n_samples"] == 5000
    assert "ks_fit_quality" in fit


def test_fit_weibull_recovers():
    rng = np.random.default_rng(1)
    k_true, lam_true = 2.0, 8.0
    samples = st.weibull_min.rvs(k_true, scale=lam_true, size=5000, random_state=rng)
    fit = fit_weibull_dwell(samples)
    assert fit["dist"] == "weibull"
    assert abs(fit["k"] - k_true) / k_true < 0.10
    assert abs(fit["lambda"] - lam_true) / lam_true < 0.10


def test_fit_beta_recovers():
    rng = np.random.default_rng(2)
    a_true, b_true = 4.0, 6.0
    samples = st.beta.rvs(a_true, b_true, size=5000, random_state=rng)
    fit = fit_beta_soc(samples)
    assert fit["dist"] == "beta"
    assert abs(fit["alpha"] - a_true) / a_true < 0.15
    assert abs(fit["beta"] - b_true) / b_true < 0.15


def test_copula_independent():
    rng = np.random.default_rng(3)
    a = rng.uniform(0, 10, 1000)
    d = rng.uniform(0, 10, 1000)
    fit = fit_copula_rho(a, d)
    assert abs(fit["rho_spearman"]) < 0.1
    assert abs(fit["rho_gaussian"]) < 0.15


def test_copula_correlated():
    rng = np.random.default_rng(4)
    z = rng.standard_normal((1000, 2))
    rho_target = 0.7
    z[:, 1] = rho_target * z[:, 0] + (1 - rho_target**2) ** 0.5 * z[:, 1]
    fit = fit_copula_rho(z[:, 0], z[:, 1])
    assert fit["rho_spearman"] > 0.5
    assert fit["rho_gaussian"] > 0.5
