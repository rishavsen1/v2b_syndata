"""Tier 2 — per-user session distribution parameters.

Per-leaf fallback chain (C3): for each parameter, prefer the calibrated value
from `ctx.roots.U["region_distributions"][region][dist][param]` if present;
else fall back to the placeholder formula (kept bit-identical to Step 4).

Canonical YAML/CLI/manifest keys: `dwell.lambda`, `copula.rho_gaussian`.
Runtime-dict field names map to the existing renderer:
  lambda → lam   (renderers/sessions.py reads dw_p["lam"])
  rho_gaussian → rho

The YAML→runtime rename happens here so renderer code is unchanged.
"""
from __future__ import annotations

from typing import Any

from ..types import ScenarioContext


def _region_dist(ctx: ScenarioContext, region: str, dist: str) -> dict[str, Any]:
    """Return the calibrated dict for (region, dist), or empty dict if absent."""
    if ctx.roots is None:
        return {}
    rd = ctx.roots.U.get("region_distributions") or {}
    return rd.get(region, {}).get(dist, {})


def sample_f_arr(ctx: ScenarioContext) -> None:
    """Per-user arrival-hour parameters. Calibrated leaf wins; placeholder fallback.

    A region whose calibrated `arrival` block carries the mixture leaves
    (`w1, mu1, sigma1, mu2, sigma2`) gets a 2-component TruncNorm mixture;
    otherwise the single TruncNorm(μ, σ) (default / hand-authored path,
    bit-identical to before)."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        cal = _region_dist(ctx, u.region, "arrival")
        # Truncation window: read the calibrated block's trunc_lo/trunc_hi when
        # present (KDD task 6 widened the fit window to [4,22]); default to the
        # historical 6/20 so synthetic / hand-authored populations — which carry
        # no trunc_lo/hi leaf — stay BITWISE-IDENTICAL.
        trunc_lo = float(cal.get("trunc_lo", 6.0))
        trunc_hi = float(cal.get("trunc_hi", 20.0))
        if "w1" in cal and "mu1" in cal:
            w1 = float(cal["w1"])
            params[car_id] = {
                "mixture": [
                    (w1, float(cal["mu1"]), float(cal["sigma1"])),
                    (1.0 - w1, float(cal["mu2"]), float(cal["sigma2"])),
                ],
                "trunc_lo": trunc_lo, "trunc_hi": trunc_hi, "phi": u.phi,
            }
        else:
            mu = float(cal.get("mu", 8.5))
            sigma_default = max(2.0 * (1.0 - u.kappa), 1e-3)
            sigma = float(cal.get("sigma", sigma_default))
            params[car_id] = {"mu": mu, "sigma": sigma, "trunc_lo": trunc_lo,
                              "trunc_hi": trunc_hi, "phi": u.phi}
    ctx.latents["f_arr"] = params


def sample_f_dwell(ctx: ScenarioContext) -> None:
    """Per-user Weibull(k, λ) parameters + copula ρ. Calibrated leaf wins."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        dwell_cal = _region_dist(ctx, u.region, "dwell")
        copula_cal = _region_dist(ctx, u.region, "copula")
        # Copula default 0.0 → independent sampling (Step 4 RNG-equivalent).
        rho = float(copula_cal.get("rho_gaussian", 0.0))
        k = float(dwell_cal.get("k", 2.0))
        # YAML "lambda" → runtime "lam" rename.
        lam = float(dwell_cal.get("lambda", 8.0 * (0.5 + u.phi)))
        entry = {"k": k, "lam": lam,
                 "clip_lo": 0.5, "clip_hi": 14.0,
                 "rho": rho}
        # A region whose calibrated `dwell` block carries the mixture leaves
        # (w1, k1, lambda1, k2, lambda2) gets a 2-component Weibull mixture;
        # otherwise the single Weibull above (default / hand-authored path,
        # bit-identical to before). k/lam are still populated as a safe fallback.
        if "w1" in dwell_cal and "k1" in dwell_cal:
            w1 = float(dwell_cal["w1"])
            entry["mixture"] = [
                (w1, float(dwell_cal["k1"]), float(dwell_cal["lambda1"])),
                (1.0 - w1, float(dwell_cal["k2"]), float(dwell_cal["lambda2"])),
            ]
        params[car_id] = entry
    ctx.latents["f_dwell"] = params


def sample_f_soc(ctx: ScenarioContext) -> None:
    """Per-user arrival-SoC Beta(α, β) shifted by -δ * 0.003, plus the
    departure-SoC requirement Beta when calibrated. Calibrated leaf wins."""
    assert ctx.a_user is not None
    assert ctx.a_fleet is not None
    params = {}
    depart_params: dict[Any, dict[str, float] | None] = {}
    for car_id, u in ctx.a_user.items():
        car = ctx.a_fleet[car_id]
        soc_cal = _region_dist(ctx, u.region, "soc_arrival")
        alpha = float(soc_cal.get("alpha", 4.0))
        beta = float(soc_cal.get("beta", 6.0))
        params[car_id] = {
            "alpha": alpha, "beta": beta,
            "shift": -u.delta_km * 0.003,
            "clip_lo": car.min_allowed_soc / 100.0,
            "clip_hi": car.max_allowed_soc / 100.0,
        }
        # Departure-SoC requirement: None → renderer keeps the hardcoded
        # N(85, 5) fallback (bit-identical for uncalibrated populations).
        dep_cal = _region_dist(ctx, u.region, "soc_depart")
        depart_params[car_id] = (
            {"alpha": float(dep_cal["alpha"]), "beta": float(dep_cal["beta"])}
            if "alpha" in dep_cal and "beta" in dep_cal else None
        )
    ctx.latents["f_soc"] = params
    ctx.latents["f_soc_depart"] = depart_params
