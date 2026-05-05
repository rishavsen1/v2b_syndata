"""Render sessions.csv: per-car_id × weekday joint sample with non-overlap rejection."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..seeding import rng_for_car
from ..types import ScenarioContext

_COLUMNS = [
    "session_id", "car_id", "building_id", "arrival", "departure",
    "duration_sec", "arrival_soc", "required_soc_at_depart",
    "previous_day_external_use_soc",
]
_BUILDING_ID = "B001"
_MAX_RETRIES = 5


def _sample_truncnorm(rng: np.random.Generator, mu: float, sigma: float,
                      lo: float, hi: float) -> float:
    a = (lo - mu) / sigma
    b = (hi - mu) / sigma
    rv = stats.truncnorm.rvs(a, b, loc=mu, scale=sigma, random_state=rng)
    return float(rv)


def _sample_required_soc(rng: np.random.Generator, min_depart_soc: float,
                         max_allowed_soc: float) -> float:
    """TruncNorm(85, 5) clipped to [min_depart_soc * 100, max_allowed_soc]."""
    lo = min_depart_soc * 100.0
    hi = max_allowed_soc
    if hi <= lo:
        return lo
    return _sample_truncnorm(rng, mu=85.0, sigma=5.0, lo=lo, hi=hi)


def render(ctx: ScenarioContext) -> None:
    assert ctx.a_user is not None and ctx.a_fleet is not None
    f_arr = ctx.latents["f_arr"]
    f_dwell = ctx.latents["f_dwell"]
    f_soc = ctx.latents["f_soc"]
    min_depart_soc = float(ctx.knobs.get("user_behavior.min_depart_soc"))

    # Grid bounds — sessions must be within building_load datetime range.
    bl = ctx.rendered["building_load.csv"]
    dt_min = pd.to_datetime(bl["datetime"].iloc[0])
    dt_max = pd.to_datetime(bl["datetime"].iloc[-1])

    # Charger max rate for D5 reachability clamp.
    chargers = ctx.rendered["chargers.csv"]
    max_charger_rate = float(chargers["max_rate_kw"].max())

    weekdays_only = bool(ctx.knobs.get("sim_window.weekdays_only"))

    # Iterate days in sim window (use the date of dt_min through dt_max).
    days = pd.date_range(dt_min.normalize(), dt_max.normalize(), freq="D")
    if weekdays_only:
        days = [d for d in days if d.weekday() < 5]
    else:
        days = list(days)

    rows = []
    sid = 1
    for car_id in sorted(ctx.a_user.keys()):
        u = ctx.a_user[car_id]
        car = ctx.a_fleet[car_id]
        arr_p = f_arr[car_id]
        dw_p = f_dwell[car_id]
        soc_p = f_soc[car_id]

        prior_departure: pd.Timestamp | None = None
        prior_required_soc: float | None = None

        for day in days:
            rng = rng_for_car(ctx.seed, f"sessions:{day.date().isoformat()}", car_id)
            if rng.random() >= u.phi:
                continue  # No appearance

            arrival_ts: pd.Timestamp | None = None
            departure_ts: pd.Timestamp | None = None
            arrival_soc: float | None = None
            required_soc: float | None = None

            for _ in range(_MAX_RETRIES):
                arr_hour = _sample_truncnorm(
                    rng, mu=arr_p["mu"], sigma=arr_p["sigma"],
                    lo=arr_p["trunc_lo"], hi=arr_p["trunc_hi"],
                )
                dwell_hr = float(rng.weibull(dw_p["k"]) * dw_p["lam"])
                dwell_hr = max(dw_p["clip_lo"], min(dwell_hr, dw_p["clip_hi"]))

                # Snap arrival to a 15-min grid step within the day
                total_min = int(round(arr_hour * 60.0 / 15.0)) * 15
                arrival = day + pd.Timedelta(minutes=total_min)
                duration_sec = int(round(dwell_hr * 3600.0))
                departure = arrival + pd.Timedelta(seconds=duration_sec)

                # Constraint: stay inside building_load range; non-overlap with prior.
                if arrival < dt_min or departure > dt_max + pd.Timedelta(minutes=15):
                    continue
                if prior_departure is not None and arrival < prior_departure:
                    continue

                # Sample arrival_soc and required_soc
                beta = float(rng.beta(soc_p["alpha"], soc_p["beta"]))
                a_soc_pct = max(soc_p["clip_lo"], min(soc_p["clip_hi"], beta + soc_p["shift"])) * 100.0
                r_soc_pct = _sample_required_soc(rng, min_depart_soc, car.max_allowed_soc)
                # Clamp required to be reachable (D5).
                duration_hr = duration_sec / 3600.0
                # Clamp to exactly reachable (no slack) so validator's 1.05 tolerance has headroom
                # against floating-point rounding.
                reachable_max = a_soc_pct + (max_charger_rate * duration_hr / car.capacity_kwh) * 100.0
                if r_soc_pct > reachable_max:
                    r_soc_pct = reachable_max
                # Keep required within car SoC bounds (D4).
                r_soc_pct = max(car.min_allowed_soc, min(car.max_allowed_soc, r_soc_pct))
                a_soc_pct = max(car.min_allowed_soc, min(car.max_allowed_soc, a_soc_pct))

                arrival_ts, departure_ts = arrival, departure
                arrival_soc, required_soc = a_soc_pct, r_soc_pct
                break

            if arrival_ts is None:
                continue  # All retries failed; drop this day

            assert departure_ts is not None and arrival_soc is not None and required_soc is not None
            prev_ext = 0.0
            if prior_required_soc is not None:
                prev_ext = max(0.0, prior_required_soc - arrival_soc)

            rows.append({
                "session_id": sid,
                "car_id": car_id,
                "building_id": _BUILDING_ID,
                "arrival": arrival_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "departure": departure_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_sec": int((departure_ts - arrival_ts).total_seconds()),
                "arrival_soc": arrival_soc,
                "required_soc_at_depart": required_soc,
                "previous_day_external_use_soc": prev_ext,
            })
            sid += 1
            prior_departure = departure_ts
            prior_required_soc = required_soc

    df = pd.DataFrame(rows, columns=_COLUMNS) if rows else pd.DataFrame(columns=_COLUMNS)
    ctx.rendered["sessions.csv"] = df


# Suppress unused-import warning for math in case of future use.
_ = math
