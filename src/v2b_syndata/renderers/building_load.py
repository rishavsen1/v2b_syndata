"""Render building_load.csv."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    flex = ctx.latents["L_flex"]
    inflex = ctx.latents["L_inflex"]
    target_peak = float(ctx.knobs.get("building_load.peak_kw"))
    total = flex + inflex
    current_peak = float(total.max())
    if current_peak <= 0:
        scale = 1.0
    else:
        scale = target_peak / current_peak
    df = pd.DataFrame({
        "datetime": flex.index.strftime("%Y-%m-%d %H:%M:%S"),
        "power_flex_kw": (flex * scale).to_numpy(),
        "power_inflex_kw": (inflex * scale).to_numpy(),
    })
    ctx.rendered["building_load.csv"] = df
