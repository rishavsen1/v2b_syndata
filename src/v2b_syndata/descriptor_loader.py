"""Tier 0 descriptor → Tier 1 knob expansion.

Each scenario names a Location, Building, Population, Equipment, and Noise
descriptor. Each descriptor maps to a subset of knob paths via its library file.

Population entries with a `region_distributions:` block AND a
`calibration_metadata.source` carrying a `calibration:*` provenance string
get their leaf parameters flattened into deep-channel paths
(`user_behavior.region_distributions.<region>.<dist>.<param>`). The
`calibration:*` source string flows through resolve_knobs and is stamped on
the resolved knob verbatim. Per-region metadata fields (`n_samples`,
`ks_fit_quality`, etc.) are filtered here so they never enter knob_resolution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .knob_loader import DIST_PARAM_RANGES


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
    if "tmyx_station" in loc:
        out["building_load.tmyx_station"] = (loc["tmyx_station"], loc_name)
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

    # Calibrated weekend appearance factor (written into calibration_metadata by
    # `v2b-syndata calibrate`). Absent for hand-authored populations → the knob
    # falls back to its 1.0 default.
    waf = (pop.get("calibration_metadata") or {}).get("weekend_activity_factor")
    if waf is not None:
        out["user_behavior.weekend_activity_factor"] = (float(waf), pop_name)

    # region_distributions overlay (Step 5 / D47, D51, C2; Step 5.5 policy split).
    # Per-population calibration_policy controls source stamping:
    #   acn_data  → source = calibration_metadata.source ("calibration:<provenance>")
    #   synthetic → source = "hand_specified:<population_name>"
    # Defaults to acn_data when calibration_metadata.source present (legacy path),
    # else synthetic. Metadata leaves (n_samples, ks_fit_quality, dist, etc.)
    # are filtered — only DIST_PARAM_RANGES leaves propagate.
    rd = pop.get("region_distributions")
    if rd and isinstance(rd, dict):
        from .calibration.sources import CALIBRATION_SOURCES
        policy = pop.get("calibration_policy")
        cal_meta = pop.get("calibration_metadata") or {}
        if policy in CALIBRATION_SOURCES:
            provenance = cal_meta.get("source")
            if not provenance or not str(provenance).startswith("calibration:"):
                provenance = None  # not yet calibrated; skip the overlay
        elif policy == "synthetic":
            provenance = f"hand_specified:{pop_name}"
        else:
            # Legacy fallback: pre-Step-5.5 entries used calibration_metadata.source directly.
            provenance = cal_meta.get("source")
            if provenance and not str(provenance).startswith("calibration:"):
                provenance = None
        if provenance is not None:
            for region_name, dist_blocks in rd.items():
                if not isinstance(dist_blocks, dict):
                    continue
                for dist_name, params in dist_blocks.items():
                    if not isinstance(params, dict):
                        continue
                    for param_name, value in params.items():
                        leaf = f"{dist_name}.{param_name}"
                        if leaf not in DIST_PARAM_RANGES:
                            continue
                        path = (
                            f"user_behavior.region_distributions."
                            f"{region_name}.{dist_name}.{param_name}"
                        )
                        out[path] = (float(value), provenance)

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
        "load_flex_jitter_pct",
        "load_inflex_jitter_pct",
    ):
        # .get keeps a profile that omits an (optional) jitter field from
        # crashing — the knob default (0.0) applies, matching knobs.yaml.
        if key in noise:
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
