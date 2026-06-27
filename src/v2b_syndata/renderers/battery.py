"""Render battery.csv — stationary storage SPECS only (no dispatch schedule).

Native single-building schema (no building_id — added by the optimus export
layer, matching cars.csv convention).
"""
from __future__ import annotations

import pandas as pd

from ..der_catalog import resolve_battery
from ..types import ScenarioContext

BATTERY_SPEC_COLUMNS = [
    "battery_id", "battery_type", "capacity_kwh", "power_kw",
    "round_trip_efficiency", "min_soc_pct", "max_soc_pct", "initial_soc_pct",
]


def battery_spec_from_ctx(ctx: ScenarioContext) -> dict:
    return resolve_battery(
        enabled=bool(ctx.knobs.get("battery.enabled")) if ctx.knobs.has("battery.enabled") else False,
        battery_type=str(ctx.knobs.get("battery.battery_type")),
        capacity_kwh=float(ctx.knobs.get("battery.capacity_kwh")),
        power_kw=float(ctx.knobs.get("battery.power_kw")),
        round_trip_efficiency=float(ctx.knobs.get("battery.round_trip_efficiency")),
        min_soc_pct=float(ctx.knobs.get("battery.min_soc_pct")),
        max_soc_pct=float(ctx.knobs.get("battery.max_soc_pct")),
        initial_soc_pct=float(ctx.knobs.get("battery.initial_soc_pct")),
    )


def render(ctx: ScenarioContext) -> None:
    spec = battery_spec_from_ctx(ctx)
    ctx.rendered["battery.csv"] = pd.DataFrame([{c: spec[c] for c in BATTERY_SPEC_COLUMNS}])
