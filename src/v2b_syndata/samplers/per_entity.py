"""Tier 1.5 — per-entity instantiation. Real (non-stub) implementations."""
from __future__ import annotations

import numpy as np

from ..seeding import rng_for_car
from ..types import FleetAttrs, ScenarioContext, UserAttrs

# CONSENT k-means cluster parameters (n=28 survey).
CONSENT_CLUSTERS: dict[str, dict[str, float]] = {
    "type_i":   {"w1_mean": 0.0489, "w1_std": 0.02, "w2_mean": 0.1250, "w2_std": 0.01},
    "type_ii":  {"w1_mean": 0.0133, "w1_std": 0.01, "w2_mean": 0.0346, "w2_std": 0.02},
    "type_iii": {"w1_mean": 0.0362, "w1_std": 0.01, "w2_mean": 0.0673, "w2_std": 0.01},
    "type_iv":  {"w1_mean": 0.0,    "w1_std": 0.0,  "w2_mean": 0.1083, "w2_std": 0.0},
}

# Battery class spec.
BATTERY_SPECS: dict[str, dict[str, float]] = {
    "leaf_24":     {"capacity_kwh": 24.0,  "min_soc": 10.0, "max_soc": 100.0},
    "bolt_40":     {"capacity_kwh": 40.0,  "min_soc": 10.0, "max_soc": 100.0},
    "m3_75":       {"capacity_kwh": 75.0,  "min_soc": 10.0, "max_soc": 100.0},
    "rivian_100":  {"capacity_kwh": 100.0, "min_soc": 10.0, "max_soc": 100.0},
}

NEG_TYPES = ["type_i", "type_ii", "type_iii", "type_iv"]
BATTERY_CLASSES = ["leaf_24", "bolt_40", "m3_75", "rivian_100"]


def sample_a_user(ctx: ScenarioContext) -> None:
    """Sample per-car user attributes from U."""
    assert ctx.roots is not None
    U = ctx.roots.U
    F = ctx.roots.F
    ev_count = int(F["ev_count"])
    axes = U["axes_distribution"]
    region_names = [r["name"] for r in axes]
    region_weights = np.array([float(r["weight"]) for r in axes], dtype=float)
    region_weights = region_weights / region_weights.sum()
    neg_mix = np.array([float(p) for p in U["negotiation_mix"]], dtype=float)
    neg_mix = neg_mix / neg_mix.sum()
    alpha_w1, alpha_w2 = U["w_multiplier"]

    out: dict[int, UserAttrs] = {}
    for car_id in range(1, ev_count + 1):
        rng = rng_for_car(ctx.seed, "A_user", car_id)
        # Region
        ridx = int(rng.choice(len(region_names), p=region_weights))
        region = axes[ridx]
        rname = region["name"]
        phi = float(rng.uniform(region["freq"][0], region["freq"][1]))
        kappa = float(rng.uniform(region["consist"][0], region["consist"][1]))
        delta = float(rng.uniform(region["dist_km"][0], region["dist_km"][1]))
        # Negotiation
        nidx = int(rng.choice(len(NEG_TYPES), p=neg_mix))
        ntype = NEG_TYPES[nidx]
        cl = CONSENT_CLUSTERS[ntype]
        w1 = float(rng.normal(cl["w1_mean"], cl["w1_std"]))
        w2 = float(rng.normal(cl["w2_mean"], cl["w2_std"]))
        w1 = max(0.0, w1) * float(alpha_w1)
        w2 = max(0.0, w2) * float(alpha_w2)
        out[car_id] = UserAttrs(
            car_id=car_id, region=rname, phi=phi, kappa=kappa,
            delta_km=delta, negotiation_type=ntype, w1=w1, w2=w2,
        )
    ctx.a_user = out


def sample_a_fleet(ctx: ScenarioContext) -> None:
    """Sample per-car battery class from F."""
    assert ctx.roots is not None
    F = ctx.roots.F
    ev_count = int(F["ev_count"])
    battery_mix = np.array([float(p) for p in F["battery_mix"]], dtype=float)
    battery_mix = battery_mix / battery_mix.sum()
    homog = (F["battery_heterogeneity"] == "homog")
    if homog:
        mode_class = BATTERY_CLASSES[int(np.argmax(battery_mix))]

    out: dict[int, FleetAttrs] = {}
    for car_id in range(1, ev_count + 1):
        if homog:
            cls = mode_class
        else:
            rng = rng_for_car(ctx.seed, "A_fleet", car_id)
            cls = BATTERY_CLASSES[int(rng.choice(len(BATTERY_CLASSES), p=battery_mix))]
        spec = BATTERY_SPECS[cls]
        out[car_id] = FleetAttrs(
            car_id=car_id, battery_class=cls,
            capacity_kwh=spec["capacity_kwh"],
            min_allowed_soc=spec["min_soc"],
            max_allowed_soc=spec["max_soc"],
        )
    ctx.a_fleet = out
