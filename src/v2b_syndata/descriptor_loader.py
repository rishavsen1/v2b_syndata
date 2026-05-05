"""Tier 0 descriptor → Tier 1 knob expansion.

Each scenario names a Location, Building, Population, Equipment, and Noise
descriptor. Each descriptor maps to a subset of knob paths via its library file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def expand_descriptors(
    descriptors: dict[str, str],
    config_dir: Path,
) -> dict[str, tuple[Any, str]]:
    """Return path → (value, descriptor_name) for every knob filled by a descriptor.

    Required descriptors: location, building, population, equipment.
    Optional: noise (defaults to "clean").
    """
    out: dict[str, tuple[Any, str]] = {}

    locs = _load(config_dir / "locations.yaml")
    bldgs = _load(config_dir / "buildings.yaml")
    pops = _load(config_dir / "populations.yaml")
    eqpts = _load(config_dir / "equipment.yaml")
    noises = _load(config_dir / "noise_profiles.yaml")

    loc_name = descriptors["location"]
    if loc_name not in locs:
        raise KeyError(f"location descriptor {loc_name!r} not in locations.yaml")
    loc = locs[loc_name]
    out["building_load.climate"] = (loc["climate"], loc_name)
    out["building_load.weather_lat"] = (loc["weather"]["lat"], loc_name)
    out["building_load.weather_lon"] = (loc["weather"]["lon"], loc_name)
    out["building_load.weather_year"] = (loc["weather"]["year"], loc_name)
    t = loc["tariff"]
    out["utility_rate.tariff_type"] = (t["type"], loc_name)
    out["utility_rate.energy_price_offpeak"] = (t["energy_price_offpeak"], loc_name)
    out["utility_rate.energy_price_peak"] = (t["energy_price_peak"], loc_name)
    out["utility_rate.peak_window"] = (list(t["peak_window"]), loc_name)
    out["utility_rate.demand_charge_per_kw"] = (t["demand_charge_per_kw"], loc_name)
    out["utility_rate.dr_program"] = (t["dr_program"], loc_name)

    bld_name = descriptors["building"]
    if bld_name not in bldgs:
        raise KeyError(f"building descriptor {bld_name!r} not in buildings.yaml")
    bld = bldgs[bld_name]
    out["building_load.archetype"] = (bld["archetype"], bld_name)
    out["building_load.size"] = (bld["size"], bld_name)
    out["building_load.occupancy_source"] = (bld["occupancy_source"], bld_name)
    out["building_load.peak_kw"] = (float(bld["peak_kw"]), bld_name)

    pop_name = descriptors["population"]
    if pop_name not in pops:
        raise KeyError(f"population descriptor {pop_name!r} not in populations.yaml")
    pop = pops[pop_name]
    out["user_behavior.axes_distribution"] = (
        [dict(r) for r in pop["axes_distribution"]],
        pop_name,
    )
    out["user_behavior.negotiation_mix"] = (list(pop["negotiation"]["cluster_mix"]), pop_name)
    out["user_behavior.w_multiplier"] = (list(pop["negotiation"]["w_multiplier"]), pop_name)
    out["ev_fleet.ev_count"] = (int(pop["fleet"]["ev_count"]), pop_name)
    out["ev_fleet.battery_mix"] = (list(pop["fleet"]["battery_mix"]), pop_name)
    out["ev_fleet.battery_heterogeneity"] = (pop["fleet"]["battery_heterogeneity"], pop_name)

    eq_name = descriptors["equipment"]
    if eq_name not in eqpts:
        raise KeyError(f"equipment descriptor {eq_name!r} not in equipment.yaml")
    eq = eqpts[eq_name]
    out["charging_infra.charger_count"] = (int(eq["charger_count"]), eq_name)
    out["charging_infra.directionality_frac"] = (float(eq["directionality_frac"]), eq_name)
    out["charging_infra.uni_rate_kw"] = (float(eq["uni_rate_kw"]), eq_name)
    out["charging_infra.bi_rate_kw"] = (float(eq["bi_rate_kw"]), eq_name)

    noise_name = descriptors.get("noise", "clean")
    if noise_name not in noises:
        raise KeyError(f"noise descriptor {noise_name!r} not in noise_profiles.yaml")
    noise = noises[noise_name]
    out["noise.profile"] = (noise_name, noise_name)
    for key in (
        "building_load_jitter_pct",
        "arrival_time_jitter_min",
        "soc_arrival_jitter_pct",
        "dr_notification_dropout_prob",
        "price_jitter_pct",
        "occupancy_jitter_pct",
    ):
        out[f"noise.{key}"] = (float(noise[key]), noise_name)

    return out


def load_scenario(path: Path) -> dict[str, Any]:
    """Load a scenario YAML; normalize fields."""
    with path.open() as f:
        sc = yaml.safe_load(f)
    sc.setdefault("overrides", {}) or {}
    if sc.get("overrides") is None:
        sc["overrides"] = {}
    return sc
