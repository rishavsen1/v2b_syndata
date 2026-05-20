"""Render building_load.csv."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    flex = ctx.latents["L_flex"]
    inflex = ctx.latents["L_inflex"]
    # When peak_kw_scaling is true (default), normalize so max(total) == peak_kw.
    # When false, pass raw EnergyPlus magnitudes through — peak_kw becomes inert.
    scaling_on = (
        bool(ctx.knobs.get("building_load.peak_kw_scaling"))
        if ctx.knobs.has("building_load.peak_kw_scaling")
        else True
    )
    if scaling_on:
        target_peak = float(ctx.knobs.get("building_load.peak_kw"))
        total = flex + inflex
        current_peak = float(total.max())
        scale = (target_peak / current_peak) if current_peak > 0 else 1.0
    else:
        scale = 1.0
    flex_scaled = (flex * scale).to_numpy()
    inflex_scaled = (inflex * scale).to_numpy()
    df = pd.DataFrame({
        "datetime": flex.index.strftime("%Y-%m-%d %H:%M:%S"),
        "power_flex_kw": flex_scaled,
        "power_inflex_kw": inflex_scaled,
        "power_kw": flex_scaled + inflex_scaled,
    })
    ctx.rendered["building_load.csv"] = df
