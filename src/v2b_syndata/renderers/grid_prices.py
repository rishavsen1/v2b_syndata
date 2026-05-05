"""Render grid_prices.csv."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    assert ctx.roots is not None
    T = ctx.roots.T
    idx = ctx.datetime_index()
    tariff = T["tariff_type"]
    off_p = float(T["energy_price_offpeak"])
    peak_p = float(T["energy_price_peak"])
    pw_lo, pw_hi = T["peak_window"]

    if tariff == "flat":
        prices = [off_p] * len(idx)
        types = ["off_peak"] * len(idx)
    else:
        prices = []
        types = []
        for ts in idx:
            h = ts.hour
            in_peak = (pw_lo <= h < pw_hi) if pw_lo <= pw_hi else (h >= pw_lo or h < pw_hi)
            if in_peak:
                prices.append(peak_p)
                types.append("peak")
            else:
                prices.append(off_p)
                types.append("off_peak")
    df = pd.DataFrame({
        "datetime": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "price_per_kwh": prices,
        "type": types,
    })
    ctx.rendered["grid_prices.csv"] = df
