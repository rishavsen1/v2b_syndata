"""Tier 1 root samplers — pack resolved knobs into a RootBundle.

Roots are deterministic. Each `sample_*` function writes its slice of the
RootBundle into ctx.roots; building the full bundle once after all root
samplers have fired keeps the DAG structure honest while avoiding repeated
work.
"""
from __future__ import annotations

from ..types import ResolvedKnobs, RootBundle, ScenarioContext


_REGION_DIST_PREFIX = "user_behavior.region_distributions."


def _hydrate_region_distributions(k: ResolvedKnobs) -> dict:
    """Reverse the deep-channel flattening from descriptor_loader: collect every
    `user_behavior.region_distributions.<region>.<dist>.<param>` resolved leaf
    into a nested {region: {dist: {param: value}}} dict.

    Empty dict if no calibrated leaves present (placeholder fallback path).
    """
    out: dict[str, dict[str, dict[str, float]]] = {}
    for path, kv in k.values.items():
        if not path.startswith(_REGION_DIST_PREFIX):
            continue
        tail = path[len(_REGION_DIST_PREFIX):]
        parts = tail.split(".")
        if len(parts) < 3:
            continue
        region = parts[0]
        dist = parts[1]
        param = ".".join(parts[2:])
        out.setdefault(region, {}).setdefault(dist, {})[param] = float(kv.value)
    return out


def _ensure_bundle(ctx: ScenarioContext) -> RootBundle:
    if ctx.roots is None:
        # Build the bundle eagerly the first time any root sampler fires.
        k = ctx.knobs
        ctx.roots = RootBundle(
            C=k.get("building_load.climate"),
            A=k.get("building_load.archetype"),
            S=k.get("building_load.size"),
            O=k.get("building_load.occupancy_source"),
            T={
                "tariff_type": k.get("utility_rate.tariff_type"),
                "energy_price_offpeak": k.get("utility_rate.energy_price_offpeak"),
                "energy_price_peak": k.get("utility_rate.energy_price_peak"),
                "peak_window": k.get("utility_rate.peak_window"),
                "demand_charge_per_kw": k.get("utility_rate.demand_charge_per_kw"),
                "dr_program": k.get("utility_rate.dr_program"),
                "dr_magnitude_kw_range": k.get("utility_rate.dr_magnitude_kw_range"),
                "dr_lambda_base": k.get("utility_rate.dr_lambda_base"),
            },
            U={
                "axes_distribution": k.get("user_behavior.axes_distribution"),
                "negotiation_mix": k.get("user_behavior.negotiation_mix"),
                "w_multiplier": k.get("user_behavior.w_multiplier"),
                "min_depart_soc": k.get("user_behavior.min_depart_soc"),
                "external_charge_cost": k.get("user_behavior.external_charge_cost"),
                "menu_levels": k.get("user_behavior.menu_levels"),
                "region_distributions": _hydrate_region_distributions(k),
            },
            F={
                "ev_count": k.get("ev_fleet.ev_count"),
                "battery_mix": k.get("ev_fleet.battery_mix"),
                "battery_heterogeneity": k.get("ev_fleet.battery_heterogeneity"),
            },
            X={
                "charger_count": k.get("charging_infra.charger_count"),
                "directionality_frac": k.get("charging_infra.directionality_frac"),
                "uni_rate_kw": k.get("charging_infra.uni_rate_kw"),
                "bi_rate_kw": k.get("charging_infra.bi_rate_kw"),
            },
        )
    return ctx.roots


# Each root sampler is a no-op that ensures the bundle is built. The DAG
# topology requires a registered sampler per node, but Tier 1 roots are
# deterministic packing only.
def sample_C(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_A(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_S(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_O(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_T(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_U(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_F(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_X(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
