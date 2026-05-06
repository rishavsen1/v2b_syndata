"""MLE fits for per-region marginals + Gaussian copula correlation.

Output schema (canonical, matches DIST_PARAM_RANGES keys in knob_loader):
  arrival     -> {"dist": "truncnorm", "mu", "sigma", "n_samples", "ks_fit_quality"}
  dwell       -> {"dist": "weibull",   "k",  "lambda", "n_samples", "ks_fit_quality"}
  soc_arrival -> {"dist": "beta",      "alpha", "beta", "n_samples", "ks_fit_quality"}
  copula      -> {"rho_spearman", "rho_gaussian", "n_samples"}

Note: ks_fit_quality is goodness-of-fit on the training set, NOT held-out. C11.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import scipy.stats as st
from scipy.optimize import minimize

ARRIVAL_LO = 6.0
ARRIVAL_HI = 20.0
MIN_SAMPLES = 30


def fit_truncnorm_arrival(arrival_hours: np.ndarray) -> dict[str, Any]:
    """Fit TruncNorm(μ, σ) on [6, 20] via MLE. Returns canonical dict."""
    n = int(len(arrival_hours))
    a, b = ARRIVAL_LO, ARRIVAL_HI
    arr = np.clip(arrival_hours, a + 1e-6, b - 1e-6)
    mu_init = float(arr.mean())
    sig_init = float(arr.std()) if arr.std() > 0 else 1.0

    def neg_ll(params: np.ndarray) -> float:
        mu, sig = params
        if sig <= 0 or sig > 6:
            return 1e10
        a_std = (a - mu) / sig
        b_std = (b - mu) / sig
        ll = st.truncnorm.logpdf(arr, a_std, b_std, loc=mu, scale=sig)
        if not np.all(np.isfinite(ll)):
            return 1e10
        return -float(ll.sum())

    res = minimize(neg_ll, [mu_init, sig_init], method="Nelder-Mead")
    mu, sig = float(res.x[0]), float(max(1e-3, res.x[1]))
    a_std, b_std = (a - mu) / sig, (b - mu) / sig
    ks = float(st.kstest(arr, "truncnorm", args=(a_std, b_std, mu, sig)).statistic)
    return {"dist": "truncnorm", "mu": mu, "sigma": sig, "n_samples": n, "ks_fit_quality": ks}


def fit_weibull_dwell(dwell_hours: np.ndarray) -> dict[str, Any]:
    """Fit Weibull(k, λ) via scipy weibull_min. Returns canonical dict."""
    n = int(len(dwell_hours))
    arr = np.asarray(dwell_hours, dtype=float)
    arr = arr[arr > 0]
    if len(arr) < 2:
        return {"dist": "weibull", "k": 1.0, "lambda": 1.0, "n_samples": n, "ks_fit_quality": 1.0}
    k, _, lam = st.weibull_min.fit(arr, floc=0)
    k = float(max(1e-3, k))
    lam = float(max(1e-3, lam))
    ks = float(st.kstest(arr, "weibull_min", args=(k, 0, lam)).statistic)
    return {"dist": "weibull", "k": k, "lambda": lam, "n_samples": n, "ks_fit_quality": ks}


def fit_beta_soc(soc_fractions: np.ndarray) -> dict[str, Any]:
    """Fit Beta(α, β) on [0, 1]. Returns canonical dict."""
    n = int(len(soc_fractions))
    arr = np.clip(np.asarray(soc_fractions, dtype=float), 1e-6, 1 - 1e-6)
    if len(arr) < 2:
        return {"dist": "beta", "alpha": 1.0, "beta": 1.0, "n_samples": n, "ks_fit_quality": 1.0}
    alpha, beta, _, _ = st.beta.fit(arr, floc=0, fscale=1)
    alpha = float(max(1e-3, alpha))
    beta = float(max(1e-3, beta))
    ks = float(st.kstest(arr, "beta", args=(alpha, beta, 0, 1)).statistic)
    return {"dist": "beta", "alpha": alpha, "beta": beta, "n_samples": n, "ks_fit_quality": ks}


def fit_copula_rho(arrivals: np.ndarray, dwells: np.ndarray) -> dict[str, Any]:
    """Compute Spearman ρ + Gaussian-copula correlation."""
    n = int(min(len(arrivals), len(dwells)))
    if n < 2:
        return {"rho_spearman": 0.0, "rho_gaussian": 0.0, "n_samples": n}
    rho_s, _ = st.spearmanr(arrivals, dwells)
    if np.isnan(rho_s):
        rho_s = 0.0
    rho_s = float(rho_s)
    rho_g = float(2.0 * np.sin(np.pi * rho_s / 6.0))
    rho_g = float(max(-0.99, min(0.99, rho_g)))
    return {"rho_spearman": rho_s, "rho_gaussian": rho_g, "n_samples": n}


def fit_region(
    arrivals: np.ndarray,
    dwells: np.ndarray,
    soc_arrivals: np.ndarray | None,
) -> dict[str, Any]:
    """Fit all four (arrival, dwell, soc_arrival, copula) for one region.

    Skips a distribution and returns it as None if MIN_SAMPLES not met.
    """
    out: dict[str, Any] = {}
    if len(arrivals) >= MIN_SAMPLES:
        out["arrival"] = fit_truncnorm_arrival(arrivals)
    else:
        out["arrival"] = None
    if len(dwells) >= MIN_SAMPLES:
        out["dwell"] = fit_weibull_dwell(dwells)
    else:
        out["dwell"] = None
    if soc_arrivals is not None and len(soc_arrivals) >= MIN_SAMPLES:
        out["soc_arrival"] = fit_beta_soc(soc_arrivals)
    else:
        out["soc_arrival"] = None
    if len(arrivals) >= MIN_SAMPLES and len(dwells) >= MIN_SAMPLES:
        out["copula"] = fit_copula_rho(arrivals, dwells)
    else:
        out["copula"] = None
    return out
