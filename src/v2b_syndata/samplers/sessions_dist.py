"""Tier 2 — per-user session distribution parameters.

We don't materialize the distributions here; we record the parameter dict per
user_id so the sessions renderer can sample from them with deterministic
per-(car, day) seeds.
"""
from __future__ import annotations

from ..types import ScenarioContext


def sample_f_arr(ctx: ScenarioContext) -> None:
    """Per-user TruncNorm(μ_arr, σ_arr) parameters. σ shrinks with κ."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        mu = 8.5
        sigma = 2.0 * (1.0 - u.kappa)
        sigma = max(sigma, 1e-3)
        params[car_id] = {"mu": mu, "sigma": sigma, "trunc_lo": 6.0, "trunc_hi": 20.0,
                          "phi": u.phi}
    ctx.latents["f_arr"] = params


def sample_f_dwell(ctx: ScenarioContext) -> None:
    """Per-user Weibull(k=2, λ=8*(0.5+φ)) parameters."""
    assert ctx.a_user is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        params[car_id] = {"k": 2.0, "lam": 8.0 * (0.5 + u.phi),
                          "clip_lo": 0.5, "clip_hi": 14.0,
                          "rho": 0.0}  # copula correlation; stub uses independent
    ctx.latents["f_dwell"] = params


def sample_f_soc(ctx: ScenarioContext) -> None:
    """Per-user Beta(α=4, β=6) shifted by -δ * 0.003."""
    assert ctx.a_user is not None
    assert ctx.a_fleet is not None
    params = {}
    for car_id, u in ctx.a_user.items():
        car = ctx.a_fleet[car_id]
        params[car_id] = {
            "alpha": 4.0, "beta": 6.0,
            "shift": -u.delta_km * 0.003,
            "clip_lo": car.min_allowed_soc / 100.0,
            "clip_hi": car.max_allowed_soc / 100.0,
        }
    ctx.latents["f_soc"] = params
