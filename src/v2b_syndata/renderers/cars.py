"""Render cars.csv from A_fleet."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    assert ctx.a_fleet is not None
    rows = []
    for car_id in sorted(ctx.a_fleet.keys()):
        f = ctx.a_fleet[car_id]
        rows.append({
            "car_id": f.car_id,
            "capacity_kwh": f.capacity_kwh,
            "min_allowed_soc": f.min_allowed_soc,
            "max_allowed_soc": f.max_allowed_soc,
            "battery_class": f.battery_class,
        })
    ctx.rendered["cars.csv"] = pd.DataFrame(rows)
