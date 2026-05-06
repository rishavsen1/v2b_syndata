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
    """Per-user TruncNorm(μ, σ) parameters. Calibrated leaf wins; placeholder fallback."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        cal = _region_dist(ctx, u.region, "arrival")
        mu = float(cal.get("mu", 8.5))
        sigma_default = max(2.0 * (1.0 - u.kappa), 1e-3)
        sigma = float(cal.get("sigma", sigma_default))
        params[car_id] = {"mu": mu, "sigma": sigma, "trunc_lo": 6.0, "trunc_hi": 20.0,
                          "phi": u.phi}
    ctx.latents["f_arr"] = params


def sample_f_dwell(ctx: ScenarioContext) -> None:
    """Per-user Weibull(k, λ) parameters + copula ρ. Calibrated leaf wins."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        dwell_cal = _region_dist(ctx, u.region, "dwell")
        copula_cal = _region_dist(ctx, u.region, "copula")
        k = float(dwell_cal.get("k", 2.0))
        # YAML "lambda" → runtime "lam" rename.
        lam = float(dwell_cal.get("lambda", 8.0 * (0.5 + u.phi)))
        # Copula default 0.0 → independent sampling (Step 4 RNG-equivalent).
        rho = float(copula_cal.get("rho_gaussian", 0.0))
        params[car_id] = {"k": k, "lam": lam,
                          "clip_lo": 0.5, "clip_hi": 14.0,
                          "rho": rho}
    ctx.latents["f_dwell"] = params


def sample_f_soc(ctx: ScenarioContext) -> None:
    """Per-user Beta(α, β) shifted by -δ * 0.003. Calibrated leaf wins."""
    assert ctx.a_user is not None
    assert ctx.a_fleet is not None
    params = {}
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
    ctx.latents["f_soc"] = params
