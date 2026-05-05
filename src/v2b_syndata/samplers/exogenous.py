"""Tier 1 root samplers — pack resolved knobs into a RootBundle.

Roots are deterministic. Each `sample_*` function writes its slice of the
RootBundle into ctx.roots; building the full bundle once after all root
samplers have fired keeps the DAG structure honest while avoiding repeated
work.
"""
from __future__ import annotations

from ..types import RootBundle, ScenarioContext


def _ensure_bundle(ctx: ScenarioContext) -> RootBundle:
    if ctx.roots is None:
        # Build the bundle eagerly the first time any root sampler fires.
        k = ctx.knobs
        ctx.roots = RootBundle(
            C=k.get("building_load.climate"),
            W={
                "lat": k.get("building_load.weather_lat"),
                "lon": k.get("building_load.weather_lon"),
                "year": k.get("building_load.weather_year"),
            },
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
def sample_W(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_A(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_S(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_O(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_T(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_U(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_F(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
def sample_X(ctx: ScenarioContext) -> None: _ensure_bundle(ctx)
