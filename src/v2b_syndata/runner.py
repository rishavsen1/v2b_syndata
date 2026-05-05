"""End-to-end generation pipeline.

Resolves knobs, builds context, runs the DAG, applies noise, writes CSVs +
manifest, and validates.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import noise as noise_mod
from .dag import SamplerRegistry, build_graph
from .descriptor_loader import expand_descriptors, load_scenario
from .knob_loader import _normalize, load_knob_registry, resolve_knobs
from .manifest import CSV_NAMES, write_manifest
from .renderers import building_load as r_building_load
from .renderers import cars as r_cars
from .renderers import chargers as r_chargers
from .renderers import dr_events as r_dr
from .renderers import grid_prices as r_grid
from .renderers import sessions as r_sessions
from .renderers import users as r_users
from .samplers import exogenous, per_entity, sessions_dist
from .samplers import load as load_sampler
from .types import ResolvedKnobs, ScenarioContext

DEFAULT_SIM_START = datetime(2020, 4, 1)  # April 2020 = full calendar month. See DESIGN_NOTES §1.


def build_registry() -> SamplerRegistry:
    reg = SamplerRegistry()
    reg.register("C", exogenous.sample_C)
    reg.register("W", exogenous.sample_W)
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
    }


def generate(
    scenario_id: str,
    seed: int,
    output_dir: Path,
    config_dir: Path,
    cli_overrides: dict[str, Any] | None = None,
    noise_profile_override: str | None = None,
) -> dict[str, Any]:
    """Run end-to-end generation. Returns the manifest dict."""
    # Normalize so direct-API callers can pass dates / tuples — keeps the
    # manifest JSON-serializable and matches the shape parse_overrides emits.
    cli_overrides = _normalize(dict(cli_overrides or {}))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario = load_scenario(config_dir / "scenarios" / f"{scenario_id}.yaml")
    descriptors = dict(scenario["descriptors"])
    if noise_profile_override is not None:
        descriptors["noise"] = noise_profile_override

    registry = load_knob_registry(config_dir / "knobs.yaml")
    descriptor_values = expand_descriptors(descriptors, config_dir)
    scenario_overrides = scenario.get("overrides") or {}

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

    noise_mod.apply_noise(ctx)

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
    return manifest
