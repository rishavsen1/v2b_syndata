"""End-to-end generation pipeline.

Resolves knobs, builds context, runs the DAG, applies noise, writes CSVs +
manifest, and validates.
"""

from __future__ import annotations

import calendar
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import noise as noise_mod
from .dag import SamplerRegistry, build_graph
from .descriptor_loader import expand_descriptors, load_scenario
from .e5_metrics import InfeasibilityError, compute_concurrency
from .knob_loader import _normalize, load_knob_registry, resolve_knobs
from .manifest import CSV_NAMES, write_manifest
from .renderers import battery as r_battery
from .renderers import building_load as r_building_load
from .renderers import cars as r_cars
from .renderers import chargers as r_chargers
from .renderers import dr_events as r_dr
from .renderers import grid_prices as r_grid
from .renderers import pv as r_pv
from .renderers import sessions as r_sessions
from .renderers import users as r_users
from .samplers import exogenous, per_entity, sessions_dist
from .samplers import load as load_sampler
from .samplers import pv as pv_sampler
from .types import ResolvedKnobs, ScenarioContext

logger = logging.getLogger(__name__)

DEFAULT_SIM_START = datetime(2020, 4, 1)  # April 2020 = full calendar month. See DESIGN_NOTES Section 1.


def build_registry() -> SamplerRegistry:
    reg = SamplerRegistry()
    reg.register("C", exogenous.sample_C)
    reg.register("A", exogenous.sample_A)
    reg.register("S", exogenous.sample_S)
    reg.register("O", exogenous.sample_O)
    reg.register("T", exogenous.sample_T)
    reg.register("U", exogenous.sample_U)
    reg.register("F", exogenous.sample_F)
    reg.register("X", exogenous.sample_X)
    reg.register("A_user", per_entity.sample_a_user)
    reg.register("A_fleet", per_entity.sample_a_fleet)
    reg.register("L_flex", load_sampler.sample_l_flex)
    reg.register("L_inflex", load_sampler.sample_l_inflex)
    reg.register("f_arr", sessions_dist.sample_f_arr)
    reg.register("f_dwell", sessions_dist.sample_f_dwell)
    reg.register("f_soc", sessions_dist.sample_f_soc)
    reg.register("chargers.csv", r_chargers.render)
    reg.register("grid_prices.csv", r_grid.render)
    reg.register("dr_events.csv", r_dr.render)
    reg.register("users.csv", r_users.render)
    reg.register("cars.csv", r_cars.render)
    reg.register("building_load.csv", r_building_load.render)
    reg.register("sessions.csv", r_sessions.render)
    reg.register("PV_gen", pv_sampler.sample_pv_gen)
    reg.register("pv_generation.csv", r_pv.render_generation)
    reg.register("pv.csv", r_pv.render_specs)
    reg.register("battery.csv", r_battery.render)
    reg.validate(build_graph())
    return reg


def _resolve_sim_window(knobs: ResolvedKnobs) -> tuple[datetime, datetime]:
    mode = knobs.get("sim_window.mode")
    raw_start = knobs.get("sim_window.start")
    anchor = pd.to_datetime(raw_start).to_pydatetime() if raw_start is not None else DEFAULT_SIM_START

    if mode == "month":
        start = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        return start, start + timedelta(days=days_in_month)
    if mode == "full_year":
        start = anchor.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, start.replace(year=start.year + 1)
    if mode == "custom":
        ce = knobs.get("sim_window.custom_end")
        if raw_start is None or ce is None:
            raise ValueError("sim_window.mode=custom requires sim_window.start and sim_window.custom_end")
        return anchor, pd.to_datetime(ce).to_pydatetime()
    raise ValueError(f"unknown sim_window.mode={mode}")


def _resolve_noise(knobs: ResolvedKnobs) -> dict[str, float]:
    return {
        "building_load_jitter_pct": float(knobs.get("noise.building_load_jitter_pct")),
        "arrival_time_jitter_min": float(knobs.get("noise.arrival_time_jitter_min")),
        "soc_arrival_jitter_pct": float(knobs.get("noise.soc_arrival_jitter_pct")),
        "dr_notification_dropout_prob": float(knobs.get("noise.dr_notification_dropout_prob")),
        "price_jitter_pct": float(knobs.get("noise.price_jitter_pct")),
        "occupancy_jitter_pct": float(knobs.get("noise.occupancy_jitter_pct")),
        "load_flex_jitter_pct": float(knobs.get("noise.load_flex_jitter_pct")),
        "load_inflex_jitter_pct": float(knobs.get("noise.load_inflex_jitter_pct")),
    }


def generate(
    scenario_id: str,
    seed: int,
    output_dir: Path,
    config_dir: Path,
    cli_overrides: dict[str, Any] | None = None,
    noise_profile_override: str | None = None,
    strict_e5: bool = False,
    strict_validate: bool = False,
    descriptor_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run end-to-end generation. Returns the manifest dict.

    `descriptor_overrides` (optional) replaces individual Tier-0 descriptor
    picks (location/building/population/equipment) from the base scenario —
    used by multi-building generation to vary each building's config without
    authoring a scenario file per building. Default None → identical to the
    scenario's own descriptors (bit-identical output preserved).
    """
    # Normalize so direct-API callers can pass dates / tuples — keeps the
    # manifest JSON-serializable and matches the shape parse_overrides emits.
    cli_overrides = _normalize(dict(cli_overrides or {}))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario = load_scenario(config_dir / "scenarios" / f"{scenario_id}.yaml")
    descriptors = dict(scenario["descriptors"])
    for _k, _v in (descriptor_overrides or {}).items():
        if _v:
            descriptors[_k] = _v
    scenario_overrides = scenario.get("overrides") or {}

    # noise.profile is a fan-out knob: setting it MUST also set every
    # per-jitter knob (noise.building_load_jitter_pct, etc.) from
    # noise_profiles.yaml. Resolution priority for the profile name:
    # CLI override > --noise-profile flag > scenario.overrides > scenario descriptor.
    # Whichever wins drives the descriptor expansion so the per-jitter knobs
    # come from the matching profile entry. Individual jitter overrides
    # still beat the profile via the standard resolution chain.
    if "noise.profile" in cli_overrides:
        descriptors["noise"] = str(cli_overrides["noise.profile"])
    elif noise_profile_override is not None:
        descriptors["noise"] = noise_profile_override
    elif "noise.profile" in scenario_overrides:
        descriptors["noise"] = str(scenario_overrides["noise.profile"])

    registry = load_knob_registry(config_dir / "knobs.yaml")
    descriptor_values = expand_descriptors(descriptors, config_dir)

    resolved = resolve_knobs(
        registry=registry,
        descriptor_values=descriptor_values,
        scenario_overrides=scenario_overrides,
        cli_overrides=cli_overrides,
    )

    sim_start, sim_end = _resolve_sim_window(resolved)
    ctx = ScenarioContext(
        scenario_id=scenario_id,
        seed=seed,
        knobs=resolved,
        sim_start=sim_start,
        sim_end=sim_end,
        noise=_resolve_noise(resolved),
        noise_profile_name=str(resolved.get("noise.profile")),
    )

    reg = build_registry()
    reg.run(ctx)

    noise_stats = noise_mod.apply_noise(ctx)

    # E5 hybrid enforcement: compute realized concurrency before writing CSVs
    # so we can warn/error at generation time rather than waiting on validate.
    e5 = compute_concurrency(
        ctx.rendered["sessions.csv"],
        ctx.sim_start, ctx.sim_end,
        n_chargers=len(ctx.rendered["chargers.csv"]),
    )
    if e5.infeasible:
        logger.warning(
            "E5 infeasibility: realized max concurrent sessions %d > chargers %d. "
            "%d/%d ticks affected (%.1f%%). Generation continues; resize fleet/chargers "
            "for physical realism.",
            e5.realized_max_concurrent, e5.n_chargers,
            e5.infeasible_tick_count, e5.total_tick_count,
            e5.infeasible_tick_fraction * 100,
        )

    # Write CSVs in deterministic order.
    for name in CSV_NAMES:
        df = ctx.rendered[f"{name}.csv"]
        path = output_dir / f"{name}.csv"
        df.to_csv(path, index=False, lineterminator="\n")

    manifest = write_manifest(
        output_dir=output_dir,
        scenario_id=scenario_id,
        seed=seed,
        resolved=resolved,
        cli_overrides=cli_overrides,
        noise_profile=ctx.noise_profile_name,
    )
    # Augment manifest with E5 metrics + noise post-render stats, re-serialize.
    manifest["e5"] = {
        "realized_max_concurrent": e5.realized_max_concurrent,
        "n_chargers": e5.n_chargers,
        "infeasible": bool(e5.infeasible),
        "infeasible_tick_count": e5.infeasible_tick_count,
        "total_tick_count": e5.total_tick_count,
        "infeasible_tick_fraction": e5.infeasible_tick_fraction,
    }
    if noise_stats:
        manifest["noise"] = noise_stats
    if ctx.realized_axes_weights is not None or ctx.realized_battery_mix is not None:
        manifest["realized_distributions"] = {
            "axes_distribution_sampled": ctx.realized_axes_weights,
            "battery_mix_sampled": ctx.realized_battery_mix,
        }

    # Automatic post-generation validation. Runs the NATIVE-schema invariant
    # checker (A–I incl. D5 reachability) on the CSVs we just wrote, and records
    # the result in the manifest BEFORE it is serialized. Import lazily to avoid
    # an import cycle (validate.py imports from renderers/samplers). Never raises
    # here unless strict_validate=True — generation must complete and report so
    # callers/UI can surface failures. For NOISY runs some invariants (D5/H2)
    # can fail by the documented noise contract; `noise_applied` records whether
    # any jitter knob was non-zero so callers can note that nuance.
    from .validate import ValidationError, validate  # lazy import — breaks the cycle

    report = validate(output_dir, strict=False)
    noise_applied = any(v != 0 for v in ctx.noise.values())
    manifest["validation"] = {
        "passed": not report.errors,
        "n_errors": len(report.errors),
        "n_warnings": len(report.warnings),
        "errors": report.errors[:50],
        "warnings": report.warnings[:50],
        "noise_applied": noise_applied,
    }
    if report.errors:
        logger.warning(
            "post-generation validation flagged %d error(s) (noise_applied=%s): %s",
            len(report.errors), noise_applied, report.errors[:3],
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    if strict_e5 and e5.infeasible:
        raise InfeasibilityError(
            f"E5 infeasibility: realized max concurrent sessions "
            f"{e5.realized_max_concurrent} > chargers {e5.n_chargers} "
            f"({e5.infeasible_tick_count}/{e5.total_tick_count} ticks affected)."
        )

    if strict_validate and report.errors:
        raise ValidationError(
            f"post-generation validation failed with {len(report.errors)} "
            f"error(s): {report.errors[:5]}"
        )

    return manifest
