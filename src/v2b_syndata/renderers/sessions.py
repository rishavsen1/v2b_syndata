"""Render sessions.csv: per-car_id × weekday joint sample with rejection sampling.

Constraints enforced atomically per session-day:
- Non-overlap with prior session for same car_id
- Inside building_load datetime range
- No overnight stay: departure on same calendar day as arrival (C12)
- required_soc_at_depart > arrival_soc           (D6, structural)
- required_soc_at_depart >= min_depart_soc * 100 (D7, behavioral floor)
- required - arrival reachable by max charger × dwell × 1.05 (D5)

If any constraint fails after _MAX_RETRIES attempts, the session is dropped
for that car-day. Reachability is enforced by *rejection*, not clamping.

Departure-SoC requirement (`required_soc_at_depart`) — the only departure-side
SoC the dataset carries, i.e. departure SoC *is* required SoC:
  * Calibrated cohorts: drawn from the per-region empirical Beta
    `region_distributions.<region>.soc_depart`, fit to the SoC cars left at in
    the source (arrival_soc + delivered/capacity). These scenarios set
    `min_depart_soc = 0`, so the empirical distribution flows through unclamped;
    only D6 (> arrival) constrains it. The 80% floor is a discretionary prior,
    not a physical requirement, so it is dropped where real data is available.
  * Fallback (hand-authored populations, and sources without the data to
    reconstruct departure SoC such as ElaadNL — no kWhRequested → no arrival
    SoC): no `soc_depart` block, so required_soc is drawn from the prior
    truncnorm(`user_behavior.depart_soc_mu`, `user_behavior.depart_soc_sigma`;
    defaults 85/5) floored at `min_depart_soc` (default 0.80). The prior
    required_soc thus serves as the departure SoC.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from ..seeding import rng_for_car
from ..types import ScenarioContext

logger = logging.getLogger(__name__)

_COLUMNS = [
    "session_id", "car_id", "building_id", "arrival", "departure",
    "duration_sec", "arrival_soc", "required_soc_at_depart",
    "previous_day_external_use_soc",
]
_BUILDING_ID = "B001"
_MAX_RETRIES = 5
_FLOOR_EPSILON = 0.01  # ensures required > arrival even when arrival is high


def _sample_truncnorm(rng: np.random.Generator, mu: float, sigma: float,
                      lo: float, hi: float) -> float:
    if hi <= lo:
        return lo
    a = (lo - mu) / sigma
    b = (hi - mu) / sigma
    rv = stats.truncnorm.rvs(a, b, loc=mu, scale=sigma, random_state=rng)
    return float(rv)


def _gaussian_copula_pair(rng: np.random.Generator, rho: float) -> tuple[float, float]:
    """Draw (u1, u2) ∈ [0,1]^2 with bivariate normal copula at correlation ρ."""
    z = rng.standard_normal(2)
    z2 = rho * z[0] + (1.0 - rho * rho) ** 0.5 * z[1]
    u1 = float(stats.norm.cdf(z[0]))
    u2 = float(stats.norm.cdf(z2))
    return u1, u2


def _truncnorm_ppf_u(u: float, mu: float, sigma: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return lo
    a = (lo - mu) / sigma
    b = (hi - mu) / sigma
    return float(stats.truncnorm.ppf(u, a, b, loc=mu, scale=sigma))


def _weibull_ppf_u(u: float, k: float, lam: float) -> float:
    """Weibull(k, λ) inverse CDF at u."""
    return float(stats.weibull_min.ppf(u, k, scale=lam))


def _mixture_ppf(u: float, cdf, a: float, b: float, iters: int = 60) -> float:
    """Generic inverse of a monotone CDF on [a, b] via bisection at `u`.

    Pure function of u — the copula's shared uniform is consumed once and
    transformed deterministically, preserving the bitwise-determinism contract.
    Used by every mixture marginal (TruncNorm arrival, Weibull dwell)."""
    if b <= a:
        return a
    u = min(1.0 - 1e-9, max(1e-9, u))
    lo, hi = a, b
    for _ in range(iters):
        m = 0.5 * (lo + hi)
        if cdf(m) < u:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def _mixture_ppf_u(u: float, comps: list, lo: float, hi: float) -> float:
    """Inverse CDF at `u` of a 2-component TruncNorm mixture, each component
    truncated to [lo, hi]. `comps` = [(w, mu, sigma), ...]. Pure function of u
    (preserves the copula's shared uniform + determinism). Bisection on the
    monotone mixture CDF — no closed form."""
    if hi <= lo:
        return lo

    def cdf(x: float) -> float:
        return sum(
            w * float(stats.truncnorm.cdf(
                x, (lo - mu) / sg, (hi - mu) / sg, loc=mu, scale=sg))
            for (w, mu, sg) in comps
        )

    return _mixture_ppf(u, cdf, lo, hi)  # ~1e-18 resolution over a 14h window


def _weibull_mixture_ppf_u(u: float, comps: list) -> float:
    """Inverse CDF at `u` of a Weibull mixture. `comps` = [(w, k, lambda), ...].
    Pure function of u (shared copula uniform → one transform → one draw), so the
    dwell mixture preserves determinism exactly like the arrival mixture.

    The upper bisection bound is the 1-1e-9 quantile of the heaviest component —
    a finite, monotone-CDF-covering ceiling (the renderer clips to clip_hi after
    this regardless)."""
    if not comps:
        return 0.0

    def cdf(x: float) -> float:
        return sum(
            w * float(stats.weibull_min.cdf(x, k, scale=lam))
            for (w, k, lam) in comps
        )

    hi = max(
        float(stats.weibull_min.ppf(1.0 - 1e-9, k, scale=lam))
        for (_w, k, lam) in comps
    )
    return _mixture_ppf(u, cdf, 0.0, hi)


def render(ctx: ScenarioContext) -> None:
    assert ctx.a_user is not None and ctx.a_fleet is not None
    f_arr = ctx.latents["f_arr"]
    f_dwell = ctx.latents["f_dwell"]
    f_soc = ctx.latents["f_soc"]
    f_soc_depart = ctx.latents.get("f_soc_depart", {})
    min_depart_soc_pct = float(ctx.knobs.get("user_behavior.min_depart_soc")) * 100.0
    # Fallback departure-SoC TruncNorm params (uncalibrated/synthetic populations
    # only; calibrated cohorts use the fitted soc_depart Beta). Defaults 85/5
    # reproduce the prior hardcoded literals bit-for-bit.
    depart_soc_mu = float(ctx.knobs.get("user_behavior.depart_soc_mu"))
    depart_soc_sigma = float(ctx.knobs.get("user_behavior.depart_soc_sigma"))

    # Footgun guard: required_soc is drawn in [floor, ceiling] with
    # floor >= min_depart_soc% and ceiling = car.max_allowed_soc. If the
    # departure floor meets or exceeds the SoC cap, every session-day is dropped
    # (floor >= ceiling). Warn loudly rather than silently emit zero sessions.
    if ctx.a_fleet:
        fleet_max_soc = max(c.max_allowed_soc for c in ctx.a_fleet.values())
        if min_depart_soc_pct >= fleet_max_soc:
            logger.warning(
                "min_depart_soc (%.1f%%) >= max_allowed_soc (%.1f%%): the "
                "departure-SoC floor meets the cap, so ALL sessions will be "
                "dropped (empty sessions.csv). Lower user_behavior.min_depart_soc "
                "or raise ev_fleet.max_allowed_soc.",
                min_depart_soc_pct, fleet_max_soc,
            )

    # Grid bounds — sessions must be within building_load datetime range.
    bl = ctx.rendered["building_load.csv"]
    dt_min = pd.to_datetime(bl["datetime"].iloc[0])
    dt_max = pd.to_datetime(bl["datetime"].iloc[-1])

    # Charger max rate for D5 reachability check.
    chargers = ctx.rendered["chargers.csv"]
    max_charger_rate = float(chargers["max_rate_kw"].max())

    weekdays_only = bool(ctx.knobs.get("sim_window.weekdays_only"))
    # weekdays_only forces a synthetic 5-day week (factor 0). Otherwise weekend
    # appearance scales the weekday rate φ by the calibrated weekend factor.
    weekend_factor = 0.0 if weekdays_only else float(
        ctx.knobs.get("user_behavior.weekend_activity_factor")
    )

    # Iterate days in sim window (use the date of dt_min through dt_max).
    days = pd.date_range(dt_min.normalize(), dt_max.normalize(), freq="D")
    if weekend_factor <= 0.0:
        # No weekend activity → skip weekend days entirely. Bitwise-identical to
        # the pre-weekend-factor behavior (the default for every scenario that
        # does not opt in via weekdays_only=false).
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
        soc_depart_p = f_soc_depart.get(car_id)

        # Region-stable copula dispatch (C4): decide once per car BEFORE entering
        # the day/retry loops so RNG consumption is deterministic across retries.
        # ρ ≈ 0 → independent sampling branch, RNG-equivalent to Step 4. Calibrated
        # ρ → bivariate Gaussian copula. Region itself is fixed per car (set in
        # sample_a_user), so this is naturally stable; caching here hardens against
        # future refactors that might re-evaluate region inside the loop.
        rho = float(dw_p.get("rho", 0.0))
        use_copula = abs(rho) >= 1e-9

        prior_departure: pd.Timestamp | None = None
        prior_required_soc: float | None = None

        for day in days:
            rng = rng_for_car(ctx.seed, f"sessions:{day.date().isoformat()}", car_id)
            # Per-day appearance: φ on weekdays, φ·weekend_factor on Sat/Sun.
            # Each date keys an independent RNG stream, so weekday decisions are
            # unaffected by enabling weekend days.
            appear_p = u.phi if day.weekday() < 5 else u.phi * weekend_factor
            if rng.random() >= appear_p:
                continue  # No appearance

            arrival_ts: pd.Timestamp | None = None
            departure_ts: pd.Timestamp | None = None
            arrival_soc: float | None = None
            required_soc: float | None = None

            arr_mix = arr_p.get("mixture")  # 2-component mixture, or None (single TruncNorm)
            dw_mix = dw_p.get("mixture")    # 2-component Weibull mixture, or None (single Weibull)
            for _ in range(_MAX_RETRIES):
                # 1. Sample arrival hour + dwell, build window. A calibrated
                #    mixture region uses the mixture quantile on the SAME uniform
                #    (copula path) or a single fresh draw (independent path); the
                #    single-TruncNorm / single-Weibull path is byte-identical to
                #    before. Each draw still consumes EXACTLY ONE uniform.
                if use_copula:
                    u_arr, u_dwell = _gaussian_copula_pair(rng, rho)
                    if arr_mix is not None:
                        arr_hour = _mixture_ppf_u(u_arr, arr_mix,
                                                  arr_p["trunc_lo"], arr_p["trunc_hi"])
                    else:
                        arr_hour = _truncnorm_ppf_u(
                            u_arr, mu=arr_p["mu"], sigma=arr_p["sigma"],
                            lo=arr_p["trunc_lo"], hi=arr_p["trunc_hi"],
                        )
                    if dw_mix is not None:
                        dwell_hr = _weibull_mixture_ppf_u(u_dwell, dw_mix)
                    else:
                        dwell_hr = _weibull_ppf_u(u_dwell, k=dw_p["k"], lam=dw_p["lam"])
                else:
                    if arr_mix is not None:
                        arr_hour = _mixture_ppf_u(float(rng.random()), arr_mix,
                                                  arr_p["trunc_lo"], arr_p["trunc_hi"])
                    else:
                        arr_hour = _sample_truncnorm(
                            rng, mu=arr_p["mu"], sigma=arr_p["sigma"],
                            lo=arr_p["trunc_lo"], hi=arr_p["trunc_hi"],
                        )
                    if dw_mix is not None:
                        # One fresh uniform → mixture quantile (NOT rng.weibull),
                        # so RNG consumption stays one-draw-per-dwell.
                        dwell_hr = _weibull_mixture_ppf_u(float(rng.random()), dw_mix)
                    else:
                        dwell_hr = float(rng.weibull(dw_p["k"]) * dw_p["lam"])
                dwell_hr = max(dw_p["clip_lo"], min(dwell_hr, dw_p["clip_hi"]))

                total_min = int(round(arr_hour * 60.0 / 15.0)) * 15
                arrival = day + pd.Timedelta(minutes=total_min)
                # Floor dwell to 15-min grid so departure lands on a 15-min
                # tick (arrival already snapped above). Enforces a min of 1
                # tick (900s) so a dwell that rounds down to zero still
                # produces a non-degenerate session.
                duration_sec = max(900, int(dwell_hr * 3600.0) // 900 * 900)
                departure = arrival + pd.Timedelta(seconds=duration_sec)

                # 2. Inside sim window + non-overlap with prior session.
                if arrival < dt_min or departure > dt_max + pd.Timedelta(minutes=15):
                    continue
                if prior_departure is not None and arrival < prior_departure:
                    continue
                # No overnight stays (C12): departure must land on the same
                # calendar day as arrival. Reject-and-retry rather than clamp,
                # so the dwell distribution stays intact for same-day sessions.
                if departure.date() != arrival.date():
                    continue

                # 3. Sample arrival_soc; clamp to car's allowed band.
                beta = float(rng.beta(soc_p["alpha"], soc_p["beta"]))
                a_soc_pct = (max(soc_p["clip_lo"], min(soc_p["clip_hi"], beta + soc_p["shift"]))) * 100.0
                a_soc_pct = max(car.min_allowed_soc, min(car.max_allowed_soc, a_soc_pct))

                # 4. Determine valid required-SoC band.
                #    floor = max(min_depart_soc, arrival + epsilon) → enforces D6 + D7.
                #    ceiling = car.max_allowed_soc.
                floor = max(min_depart_soc_pct, a_soc_pct + _FLOOR_EPSILON)
                ceiling = car.max_allowed_soc
                if floor >= ceiling:
                    # User arrived too charged for any valid target → drop session-day.
                    break

                # Departure-SoC requirement: calibrated Beta per region when
                # available (sample on [0,1], clamp into the D6/D7 band), else
                # the hardcoded N(85, 5) — kept bit-identical for uncalibrated
                # populations (same single RNG draw).
                if soc_depart_p is not None:
                    beta_d = float(rng.beta(soc_depart_p["alpha"], soc_depart_p["beta"])) * 100.0
                    r_soc_pct = max(floor, min(ceiling, beta_d))
                else:
                    r_soc_pct = _sample_truncnorm(
                        rng, mu=depart_soc_mu, sigma=depart_soc_sigma,
                        lo=floor, hi=ceiling,
                    )

                # 5. D5 reachability via rejection.
                duration_hr = duration_sec / 3600.0
                required_kwh = (r_soc_pct - a_soc_pct) / 100.0 * car.capacity_kwh
                available_kwh = max_charger_rate * duration_hr * 1.05
                if required_kwh > available_kwh:
                    continue  # retry whole session

                arrival_ts, departure_ts = arrival, departure
                arrival_soc, required_soc = a_soc_pct, r_soc_pct
                break

            if arrival_ts is None:
                continue  # All retries failed (or floor>=ceiling); drop this day

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
