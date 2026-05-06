"""Tier 2 building load latents: L_flex, L_inflex.

Calls the EnergyPlus pipeline (``v2b_syndata.load_pipeline``) and applies the
post-simulation realism noise from BAYES_NET.md (±5% on flex, ±3% on inflex).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..load_pipeline import simulate_building_load
from ..seeding import rng_for_node
from ..types import ScenarioContext

# Hourly occupancy fraction by archetype (ASHRAE 90.1 typical-week shapes).
# Values are weekday hourly fractions; weekend overrides below.
_WEEKDAY_OCC_BY_SOURCE: dict[str, list[float]] = {
    "ashrae_90_1_office": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.10, 0.20, 1.00, 1.00, 1.00, 1.00,
        0.50, 1.00, 1.00, 1.00, 1.00, 0.30,
        0.10, 0.10, 0.10, 0.10, 0.05, 0.00,
    ],
    "ashrae_90_1_retail": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.10, 0.40, 0.50, 0.60, 0.70,
        0.70, 0.70, 0.80, 0.90, 0.90, 0.90,
        0.70, 0.50, 0.30, 0.10, 0.00, 0.00,
    ],
    "ashrae_90_1_mixed": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.05, 0.15, 0.70, 0.75, 0.80, 0.85,
        0.60, 0.85, 0.90, 0.95, 0.95, 0.60,
        0.40, 0.30, 0.20, 0.10, 0.03, 0.00,
    ],
}
_WEEKEND_OCC_BY_SOURCE: dict[str, list[float]] = {
    "ashrae_90_1_office": [0.0] * 24,
    "ashrae_90_1_retail": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.10, 0.30, 0.50, 0.70, 0.80,
        0.85, 0.90, 0.90, 0.90, 0.85, 0.70,
        0.50, 0.30, 0.10, 0.00, 0.00, 0.00,
    ],
    "ashrae_90_1_mixed": [
        0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
        0.00, 0.05, 0.15, 0.30, 0.40, 0.50,
        0.55, 0.55, 0.55, 0.55, 0.50, 0.40,
        0.30, 0.20, 0.10, 0.00, 0.00, 0.00,
    ],
}


def _build_occupancy_series(
    occupancy_source: str, idx: pd.DatetimeIndex
) -> pd.Series:
    """Build a 15-min occupancy Series from a base ASHRAE schedule label."""
    weekday = _WEEKDAY_OCC_BY_SOURCE.get(
        occupancy_source, _WEEKDAY_OCC_BY_SOURCE["ashrae_90_1_office"]
    )
    weekend = _WEEKEND_OCC_BY_SOURCE.get(
        occupancy_source, _WEEKEND_OCC_BY_SOURCE["ashrae_90_1_office"]
    )
    is_weekend = idx.dayofweek >= 5
    hours = idx.hour
    values = np.where(
        is_weekend,
        np.array(weekend)[hours],
        np.array(weekday)[hours],
    )
    return pd.Series(values.astype(float), index=idx, name="occupancy")


def _resolve_loads(ctx: ScenarioContext) -> tuple[pd.Series, pd.Series]:
    """Cache the simulate_building_load call once per ScenarioContext."""
    if "_load_pipeline" in ctx.latents:
        return ctx.latents["_load_pipeline"]

    archetype = ctx.knobs.get("building_load.archetype")
    size = ctx.knobs.get("building_load.size")
    tmyx_station = ctx.knobs.get("building_load.tmyx_station")
    occupancy_source = ctx.knobs.get("building_load.occupancy_source")
    idx = ctx.datetime_index()
    occupancy = _build_occupancy_series(str(occupancy_source), idx)

    flex, inflex = simulate_building_load(
        archetype=str(archetype),
        size=str(size),
        tmyx_station=str(tmyx_station),
        occupancy=occupancy,
        sim_window_start=pd.Timestamp(ctx.sim_start),
        sim_window_end=pd.Timestamp(ctx.sim_end),
    )
    # Reindex to the canonical sim window grid; fill missing with 0 (rare,
    # only at year boundaries when EP emits one fewer/extra row).
    flex = flex.reindex(idx).ffill().fillna(0.0)
    inflex = inflex.reindex(idx).ffill().fillna(0.0)
    ctx.latents["_load_pipeline"] = (flex, inflex)
    return flex, inflex


def sample_l_flex(ctx: ScenarioContext) -> None:
    flex, _ = _resolve_loads(ctx)
    rng = rng_for_node(ctx.seed, "L_flex")
    noise = rng.normal(0.0, 0.05, size=len(flex))  # ±5% per BAYES_NET
    series = pd.Series(
        np.clip(flex.to_numpy() * (1.0 + noise), 0.0, None),
        index=flex.index,
        name="L_flex",
    )
    ctx.latents["L_flex"] = series


def sample_l_inflex(ctx: ScenarioContext) -> None:
    _, inflex = _resolve_loads(ctx)
    rng = rng_for_node(ctx.seed, "L_inflex")
    noise = rng.normal(0.0, 0.03, size=len(inflex))  # ±3% per BAYES_NET
    series = pd.Series(
        np.clip(inflex.to_numpy() * (1.0 + noise), 0.0, None),
        index=inflex.index,
        name="L_inflex",
    )
    ctx.latents["L_inflex"] = series
