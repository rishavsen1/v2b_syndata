"""Render battery_dispatch.csv — operational charge/discharge timeseries for the
stationary battery (KDD readiness item #7).

This complements ``battery.csv`` (specs only) with an *operational* dispatch on
the same 15-minute grid as ``building_load.csv``. The dispatch is a deterministic
peak-shaving + TOU-arbitrage heuristic over the already-rendered building load,
grid prices and DR events — NO RNG, so enabling the battery cannot perturb any
other CSV's bytes.

Columns
-------
``datetime``           tick start, ``YYYY-MM-DD HH:MM:SS`` (identical grid to building_load.csv)
``power_battery_kw``   battery AC power at the point of common coupling.
                       SIGN CONVENTION: ``> 0`` = DISCHARGE to the building
                       (reduces net grid import), ``< 0`` = CHARGE from the grid.
``soc_kwh``            usable state of charge (kWh) at the END of the tick.

Dispatch rule (deterministic threshold-targeting heuristic, v1)
--------------------------------------------------------------
A per-tick *discharge target threshold* is derived from the window's peak load:

    target = PEAK_SHAVE_FRACTION * peak_load          (default 0.80 * peak)

During DR-event windows or price-"peak" ticks the target is lowered further
(``DR_PEAK_SHAVE_FRACTION``, default 0.60 * peak) so the battery works harder
when energy is costly/curtailed. Then, per tick, subject to the clamps below:

1. If the building load exceeds the tick's target, DISCHARGE just enough to pull
   net import down toward the target (bounded by rated power, the load itself —
   never export past zero net — and available SoC). This reserves stored energy
   for the genuinely high-load ticks instead of spending it on every peak-price
   tick, so the *real* daily peak gets shaved rather than an early one.
2. Otherwise, if the price is off-peak and SoC is below the ceiling, CHARGE
   (replenish cheaply for the next peak).
3. Otherwise idle (0 kW).

Clamps
------
* ``|power_battery_kw| <= power_kw`` (rated power).
* ``soc_kwh`` stays within ``[min_soc_pct, max_soc_pct] * capacity_kwh``.

Round-trip efficiency convention
--------------------------------
The full round-trip loss is applied on the CHARGE leg: grid energy drawn while
charging is ``energy_into_soc / round_trip_efficiency`` at the AC meter, while
the SoC gains exactly ``energy_into_soc``. DISCHARGE is lossless w.r.t. SoC
(``soc`` drops by exactly the AC energy delivered). This is one consistent
convention (all loss on charge); ``soc_kwh`` therefore moves by:
    charge tick:    Δsoc = +|power| * rte * Δt        (power<0)
    discharge tick: Δsoc = -power * Δt                (power>0)

Default-OFF contract
--------------------
When the battery is inactive (``battery_type='none'`` and no explicit
capacity/power), the CSV is header-only (mirrors ``dr_events.csv`` when the DR
program is none), so existing scenarios' other outputs stay byte-identical.
"""
from __future__ import annotations

import pandas as pd

from ..der_catalog import resolve_battery
from ..types import ScenarioContext

COLUMNS = ["datetime", "power_battery_kw", "soc_kwh"]

# Discharge to hold net import at/below this fraction of the window's peak load.
# Picked so the battery clips the top of the demand curve without thrashing.
_PEAK_SHAVE_FRACTION = 0.80
# Lower (more aggressive) target during DR windows / peak-price ticks.
_DR_PEAK_SHAVE_FRACTION = 0.60

_TICK_HOURS = 0.25  # 15-minute grid


def battery_spec_from_ctx(ctx: ScenarioContext) -> dict:
    return resolve_battery(
        battery_type=str(ctx.knobs.get("battery.battery_type")),
        capacity_kwh=float(ctx.knobs.get("battery.capacity_kwh")),
        power_kw=float(ctx.knobs.get("battery.power_kw")),
        round_trip_efficiency=float(ctx.knobs.get("battery.round_trip_efficiency")),
        min_soc_pct=float(ctx.knobs.get("battery.min_soc_pct")),
        max_soc_pct=float(ctx.knobs.get("battery.max_soc_pct")),
        initial_soc_pct=float(ctx.knobs.get("battery.initial_soc_pct")),
    )


def dispatch(
    *,
    datetimes: pd.Series,
    load_kw,
    price_type,
    is_dr,
    capacity_kwh: float,
    power_kw: float,
    round_trip_efficiency: float,
    min_soc_pct: float,
    max_soc_pct: float,
    initial_soc_pct: float,
) -> pd.DataFrame:
    """Pure dispatch heuristic. Returns a DataFrame with COLUMNS.

    ``load_kw`` / ``price_type`` / ``is_dr`` are per-tick sequences aligned with
    ``datetimes``. ``price_type`` entries are 'peak'/'off-peak'; ``is_dr`` is a
    boolean mask of ticks falling inside a DR-event window.
    """
    n = len(datetimes)
    load = [float(x) for x in load_kw]
    ptype = list(price_type)
    dr = [bool(x) for x in is_dr]

    soc_min = (min_soc_pct / 100.0) * capacity_kwh
    soc_max = (max_soc_pct / 100.0) * capacity_kwh
    # Clamp the initial SoC into the usable band.
    soc = min(max((initial_soc_pct / 100.0) * capacity_kwh, soc_min), soc_max)

    peak_load = max(load) if load else 0.0
    base_target = _PEAK_SHAVE_FRACTION * peak_load
    dr_target = _DR_PEAK_SHAVE_FRACTION * peak_load

    powers: list[float] = []
    socs: list[float] = []

    for i in range(n):
        p = 0.0
        target = dr_target if (dr[i] or ptype[i] == "peak") else base_target
        excess = load[i] - target
        if excess > 0.0:
            # Discharge just enough to pull net import toward the target.
            # Bounded by rated power, available SoC headroom (lossless on SoC),
            # and the building load (never push net import negative).
            soc_avail = max(soc - soc_min, 0.0)
            max_by_soc = soc_avail / _TICK_HOURS
            p = min(power_kw, max_by_soc, excess, max(load[i], 0.0))
            soc -= p * _TICK_HOURS
        elif ptype[i] == "off-peak" and soc < soc_max:
            # Charge: full round-trip loss on the charge leg. Cap the AC draw so
            # the SoC gain does not overshoot the ceiling.
            soc_room = soc_max - soc
            max_ac_by_soc = (soc_room / round_trip_efficiency) / _TICK_HOURS
            ac = min(power_kw, max_ac_by_soc)
            p = -ac
            soc += ac * round_trip_efficiency * _TICK_HOURS
        # Guard against tiny float drift outside the band.
        soc = min(max(soc, soc_min), soc_max)
        powers.append(p)
        socs.append(soc)

    return pd.DataFrame({
        "datetime": list(datetimes),
        "power_battery_kw": powers,
        "soc_kwh": socs,
    })


def render(ctx: ScenarioContext) -> None:
    spec = battery_spec_from_ctx(ctx)
    capacity = float(spec["capacity_kwh"])

    # Default-OFF: header-only when battery inactive (mirrors dr_events.csv).
    if spec["battery_type"] == "none" or capacity <= 0.0:
        ctx.rendered["battery_dispatch.csv"] = pd.DataFrame(columns=COLUMNS)
        return

    bl = ctx.rendered["building_load.csv"]
    gp = ctx.rendered["grid_prices.csv"]
    dr = ctx.rendered["dr_events.csv"]

    datetimes = bl["datetime"]
    tick = pd.to_datetime(datetimes)

    # Map DR windows onto the 15-min grid: a tick is "in DR" if it overlaps
    # [start, end). Tick covers [t, t+15min).
    is_dr = pd.Series(False, index=range(len(tick)))
    if len(dr) > 0:
        starts = pd.to_datetime(dr["start"])
        ends = pd.to_datetime(dr["end"])
        tick_end = tick + pd.Timedelta(minutes=15)
        for s, e in zip(starts, ends, strict=True):
            overlap = (tick < e) & (tick_end > s)
            is_dr = is_dr | overlap.to_numpy()

    df = dispatch(
        datetimes=datetimes,
        load_kw=bl["power_kw"],
        price_type=gp["type"],
        is_dr=is_dr,
        capacity_kwh=capacity,
        power_kw=float(spec["power_kw"]),
        round_trip_efficiency=float(spec["round_trip_efficiency"]),
        min_soc_pct=float(spec["min_soc_pct"]),
        max_soc_pct=float(spec["max_soc_pct"]),
        initial_soc_pct=float(spec["initial_soc_pct"]),
    )
    ctx.rendered["battery_dispatch.csv"] = df
