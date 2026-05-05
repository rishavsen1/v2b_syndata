"""Render chargers.csv."""
from __future__ import annotations

import pandas as pd

from ..types import ScenarioContext


def render(ctx: ScenarioContext) -> None:
    k = ctx.knobs
    n = int(k.get("charging_infra.charger_count"))
    frac = float(k.get("charging_infra.directionality_frac"))
    bi_rate = float(k.get("charging_infra.bi_rate_kw"))
    uni_rate = float(k.get("charging_infra.uni_rate_kw"))
    n_bi = int(round(n * frac))
    n_uni = n - n_bi
    rows = []
    cid = 1
    for _ in range(n_bi):
        rows.append({
            "charger_id": cid, "directionality": "bidirectional",
            "min_rate_kw": -bi_rate, "max_rate_kw": bi_rate,
        })
        cid += 1
    for _ in range(n_uni):
        rows.append({
            "charger_id": cid, "directionality": "unidirectional",
            "min_rate_kw": 0.0, "max_rate_kw": uni_rate,
        })
        cid += 1
    ctx.rendered["chargers.csv"] = pd.DataFrame(rows)
