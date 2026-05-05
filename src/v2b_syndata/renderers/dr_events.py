"""STUB: Render dr_events.csv.

Real inhomogeneous Poisson sampler lands in Step 6. This stub:
- For dr_program == none: emits header-only file (zero rows)
- Else: emits 4 mock events per summer month (Jun/Jul/Aug) at 14:00 on first
  4 weekdays, magnitude = midpoint of dr_magnitude_kw_range, notification lead
  set per program (CBP=24h, BIP=2h, ELRP=24h).
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..types import ScenarioContext

_NOTIF_LEAD_HOURS = {"CBP": 24, "BIP": 2, "ELRP": 24}
_SUMMER_MONTHS = {6, 7, 8}
_COLUMNS = ["event_id", "start", "end", "magnitude_kw", "notified_at"]


def render(ctx: ScenarioContext) -> None:
    assert ctx.roots is not None
    T = ctx.roots.T
    program = T["dr_program"]
    if program == "none":
        ctx.rendered["dr_events.csv"] = pd.DataFrame(columns=_COLUMNS)
        return

    lead = timedelta(hours=_NOTIF_LEAD_HOURS.get(program, 24))
    mag_lo, mag_hi = T["dr_magnitude_kw_range"]
    magnitude = float((float(mag_lo) + float(mag_hi)) / 2.0)

    bl = ctx.rendered.get("building_load.csv")
    if bl is None or len(bl) == 0:
        ctx.rendered["dr_events.csv"] = pd.DataFrame(columns=_COLUMNS)
        return
    dt_min = pd.to_datetime(bl["datetime"].iloc[0])
    dt_max = pd.to_datetime(bl["datetime"].iloc[-1])

    rows = []
    eid = 1
    months = pd.date_range(dt_min.normalize(), dt_max.normalize(), freq="MS")
    for first_of_month in months:
        if first_of_month.month not in _SUMMER_MONTHS:
            continue
        # First 4 weekdays of the month
        d = first_of_month
        picked = 0
        while picked < 4 and d.month == first_of_month.month:
            if d.weekday() < 5:  # Mon=0..Fri=4
                start = d.replace(hour=14, minute=0, second=0, microsecond=0)
                end = start + timedelta(hours=2)
                notified = start - lead
                # Need event start, end inside building_load datetime range (C10).
                if start >= dt_min and end <= (dt_max + pd.Timedelta(minutes=15)):
                    rows.append({
                        "event_id": eid,
                        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                        "magnitude_kw": magnitude,
                        "notified_at": notified.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    eid += 1
                    picked += 1
            d = d + pd.Timedelta(days=1)

    ctx.rendered["dr_events.csv"] = pd.DataFrame(rows, columns=_COLUMNS)
