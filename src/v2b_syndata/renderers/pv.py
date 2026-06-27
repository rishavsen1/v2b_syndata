"""Render pv_generation.csv (15-min AC power timeseries) and pv.csv (specs).

Native single-building schema (no building_id — added by the optimus export
layer, matching cars.csv / building_load.csv convention).
"""
from __future__ import annotations

import pandas as pd

from ..samplers.pv import pv_spec_from_ctx
from ..types import ScenarioContext

PV_SPEC_COLUMNS = [
    "pv_id", "pv_type", "dc_capacity_kw", "ac_capacity_kw", "dc_ac_ratio",
    "tilt_deg", "azimuth_deg", "module_type", "system_derate",
    "temp_coeff_per_c", "noct_c", "albedo",
]


def render_generation(ctx: ScenarioContext) -> None:
    series = ctx.latents["PV_gen"]
    ctx.rendered["pv_generation.csv"] = pd.DataFrame({
        "datetime": series.index.strftime("%Y-%m-%d %H:%M:%S"),
        "power_pv_kw": series.to_numpy(),
    })


def render_specs(ctx: ScenarioContext) -> None:
    spec = ctx.latents.get("_pv_spec") or pv_spec_from_ctx(ctx)
    ctx.rendered["pv.csv"] = pd.DataFrame([{c: spec[c] for c in PV_SPEC_COLUMNS}])
