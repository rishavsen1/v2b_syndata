"""Render users.csv from A_user."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    assert ctx.a_user is not None
    rows = []
    for car_id in sorted(ctx.a_user.keys()):
        u = ctx.a_user[car_id]
        rows.append({
            "car_id": u.car_id,
            "region": u.region,
            "phi": u.phi,
            "kappa": u.kappa,
            "delta_km": u.delta_km,
            "negotiation_type": u.negotiation_type,
            "w1": u.w1,
            "w2": u.w2,
        })
    ctx.rendered["users.csv"] = pd.DataFrame(rows)
