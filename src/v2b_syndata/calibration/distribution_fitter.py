"""MLE fits for per-region marginals + Gaussian copula correlation.

Output schema (canonical, matches DIST_PARAM_RANGES keys in knob_loader):
  arrival     -> {"dist": "truncnorm", "mu", "sigma", "n_samples", "ks_fit_quality"}
  dwell       -> {"dist": "weibull",   "k",  "lambda", "n_samples", "ks_fit_quality"}
  soc_arrival -> {"dist": "beta",      "alpha", "beta", "n_samples", "ks_fit_quality"}
  copula      -> {"rho_spearman", "rho_gaussian", "n_samples"}

Note: ks_fit_quality is goodness-of-fit on the training set, NOT held-out. C11.

Every fit is post-clamped to the runtime DIST_PARAM_RANGES validity window
(B4 fix). When clamping fires on any required parameter the distribution is
dropped from the output, so a degenerate fit cannot break generation. Drop
events are logged via warnings so calibration runs surface the issue.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import scipy.stats as st
from scipy.optimize import minimize

from ..knob_loader import DIST_PARAM_RANGES

ARRIVAL_LO = 6.0
ARRIVAL_HI = 20.0
MIN_SAMPLES = 30


def _within(leaf: str, value: float) -> bool:
    lo, hi = DIST_PARAM_RANGES[leaf]
    return lo <= value <= hi


def _drop_if_oor(name: str, fit: dict[str, Any], leaves: dict[str, str]) -> dict[str, Any] | None:
    """Return fit if every (key, leaf) pair is within DIST_PARAM_RANGES.
    Else warn and return None so the caller skips this distribution.
    """
    bad = []
    for key, leaf in leaves.items():
        v = fit.get(key)
        if v is None or not _within(leaf, float(v)):
            bad.append(f"{leaf}={v}")
    if bad:
        warnings.warn(
            f"calibration: {name} fit out-of-range, dropping distribution: {bad}",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    return fit


def fit_truncnorm_arrival(arrival_hours: np.ndarray) -> dict[str, Any] | None:
    """Fit TruncNorm(μ, σ) on [6, 20] via MLE. Returns canonical dict, or None
    if any param falls outside DIST_PARAM_RANGES (B4 guard).
    """
    n = int(len(arrival_hours))
    a, b = ARRIVAL_LO, ARRIVAL_HI
    arr = np.clip(arrival_hours, a + 1e-6, b - 1e-6)
    mu_init = float(arr.mean())
    sig_init = float(arr.std()) if arr.std() > 0 else 1.0

    mu_lo, mu_hi = DIST_PARAM_RANGES["arrival.mu"]
    sig_lo, sig_hi = DIST_PARAM_RANGES["arrival.sigma"]

    def neg_ll(params: np.ndarray) -> float:
        mu, sig = params
        if sig <= sig_lo or sig > sig_hi:
            return 1e10
        if mu < mu_lo or mu > mu_hi:
            return 1e10
        a_std = (a - mu) / sig
        b_std = (b - mu) / sig
        ll = st.truncnorm.logpdf(arr, a_std, b_std, loc=mu, scale=sig)
        if not np.all(np.isfinite(ll)):
            return 1e10
        return -float(ll.sum())

    res = minimize(neg_ll, [mu_init, sig_init], method="Nelder-Mead")
    mu = float(res.x[0])
    sig = float(max(sig_lo, res.x[1]))
    a_std, b_std = (a - mu) / sig, (b - mu) / sig
    ks = float(st.kstest(arr, "truncnorm", args=(a_std, b_std, mu, sig)).statistic)
    fit = {"dist": "truncnorm", "mu": mu, "sigma": sig,
           "n_samples": n, "ks_fit_quality": ks}
    return _drop_if_oor("arrival", fit, {"mu": "arrival.mu", "sigma": "arrival.sigma"})


def fit_weibull_dwell(dwell_hours: np.ndarray) -> dict[str, Any] | None:
    """Fit Weibull(k, λ) via scipy weibull_min. Returns canonical dict, or None
    if any param falls outside DIST_PARAM_RANGES (B4 guard).
    """
    n = int(len(dwell_hours))
    arr = np.asarray(dwell_hours, dtype=float)
    arr = arr[arr > 0]
    if len(arr) < 2:
        return None
    k, _, lam = st.weibull_min.fit(arr, floc=0)
    k = float(k)
    lam = float(lam)
    if k <= 0 or lam <= 0:
        return None
    ks = float(st.kstest(arr, "weibull_min", args=(k, 0, lam)).statistic)
    fit = {"dist": "weibull", "k": k, "lambda": lam,
           "n_samples": n, "ks_fit_quality": ks}
    return _drop_if_oor("dwell", fit, {"k": "dwell.k", "lambda": "dwell.lambda"})


def fit_beta_soc(soc_fractions: np.ndarray, leaf_prefix: str = "soc_arrival") -> dict[str, Any] | None:
    """Fit Beta(α, β) on [0, 1]. Returns canonical dict, or None if any param
    falls outside DIST_PARAM_RANGES (B4 guard).

    ``leaf_prefix`` selects the range table entry to validate against —
    ``soc_arrival`` (arrival SoC) or ``soc_depart`` (departure-SoC requirement).
    """
    n = int(len(soc_fractions))
    arr = np.clip(np.asarray(soc_fractions, dtype=float), 1e-6, 1 - 1e-6)
    if len(arr) < 2:
        return None
    try:
        alpha, beta, _, _ = st.beta.fit(arr, floc=0, fscale=1)
    except st.FitError:
        # MLE failed to converge (e.g. departure SoC piled near 1.0). Skip the
        # distribution rather than crash — same posture as the B4 range guard.
        warnings.warn(
            f"calibration: {leaf_prefix} Beta MLE did not converge (n={n}); "
            "dropping distribution",
            RuntimeWarning, stacklevel=2,
        )
        return None
    alpha = float(alpha)
    beta = float(beta)
    if alpha <= 0 or beta <= 0:
        return None
    ks = float(st.kstest(arr, "beta", args=(alpha, beta, 0, 1)).statistic)
    fit = {"dist": "beta", "alpha": alpha, "beta": beta,
           "n_samples": n, "ks_fit_quality": ks}
    return _drop_if_oor(leaf_prefix, fit,
                        {"alpha": f"{leaf_prefix}.alpha", "beta": f"{leaf_prefix}.beta"})


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
    soc_departs: np.ndarray | None = None,
) -> dict[str, Any]:
    """Fit (arrival, dwell, soc_arrival, soc_depart, copula) for one region.

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
    if soc_departs is not None and len(soc_departs) >= MIN_SAMPLES:
        out["soc_depart"] = fit_beta_soc(soc_departs, leaf_prefix="soc_depart")
    else:
        out["soc_depart"] = None
    if len(arrivals) >= MIN_SAMPLES and len(dwells) >= MIN_SAMPLES:
        out["copula"] = fit_copula_rho(arrivals, dwells)
    else:
        out["copula"] = None
    return out
