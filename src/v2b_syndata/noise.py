"""Post-render perturbation per noise_profiles.yaml.

Profile knobs (resolved into ctx.noise) drive the perturbation. With the
`clean` profile (all zeros) every block below is a no-op and CSV bytes are
unchanged.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .seeding import rng_for_node
from .types import ScenarioContext

_MIN_SESSION_DURATION_SEC = 15 * 60  # 15 min — matches building_load grid resolution

# Sampler + validator both use 1.05 headroom for D5. Use a slightly tighter
# factor for the post-jitter truncator so floating-point doesn't push the
# rebuilt `required_soc` over validator's strict `need > avail * 1.05` check.
_D5_HEADROOM = 1.04
_D5_FLOOR_EPSILON = 0.01  # SoC-percent gap between arrival_soc and required_soc


def _enforce_d5_post_jitter(
    sessions: pd.DataFrame,
    cars: pd.DataFrame,
    chargers: pd.DataFrame,
    min_depart_soc_pct: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Truncate required_soc_at_depart to enforce D5 reachability after
    arrival/SoC jitter has potentially shrunk the feasibility budget.

    Uses max(chargers.max_rate_kw) as the feasibility envelope — matches
    sessions.py:170 sampler pre-check (simulator picks the best charger
    available).

    Returns (sessions_df_kept, stats_dict).
    """
    if len(sessions) == 0:
        return sessions, {
            "max_charger_rate_kw": float(chargers["max_rate_kw"].max()) if len(chargers) else 0.0,
            "total_input_sessions": 0,
            "truncated_count": 0,
            "d7_relaxed_count": 0,
            "dropped_count": 0,
            "total_output_sessions": 0,
        }

    max_charger_rate = float(chargers["max_rate_kw"].max())
    merged = sessions.merge(
        cars[["car_id", "capacity_kwh"]],
        on="car_id", how="left", suffixes=("", "_car"),
    )
    dwell_hr = (
        pd.to_datetime(merged["departure"]) - pd.to_datetime(merged["arrival"])
    ).dt.total_seconds() / 3600.0
    available_kwh = max_charger_rate * dwell_hr * _D5_HEADROOM
    max_delta_soc_pct = (available_kwh / merged["capacity_kwh"]) * 100.0
    max_feasible_required = merged["arrival_soc"] + max_delta_soc_pct
    original_required = merged["required_soc_at_depart"]
    floor = merged["arrival_soc"] + _D5_FLOOR_EPSILON

    drop_mask = (max_feasible_required < floor).to_numpy()
    truncate_mask = (
        (max_feasible_required < original_required) & ~pd.Series(drop_mask, index=merged.index)
    ).to_numpy()

    new_required = original_required.to_numpy().copy()
    new_required = np.where(
        truncate_mask, max_feasible_required.to_numpy(), new_required,
    )
    new_required = np.maximum(new_required, floor.to_numpy())

    d7_relaxed_mask = truncate_mask & (new_required < min_depart_soc_pct)

    keep = ~drop_mask
    kept = sessions.loc[keep].copy()
    kept["required_soc_at_depart"] = new_required[keep]

    stats = {
        "max_charger_rate_kw": max_charger_rate,
        "total_input_sessions": int(len(sessions)),
        "truncated_count": int(truncate_mask.sum()),
        "d7_relaxed_count": int(d7_relaxed_mask.sum()),
        "dropped_count": int(drop_mask.sum()),
        "total_output_sessions": int(len(kept)),
    }
    return kept, stats


def _all_zero(d: dict[str, float]) -> bool:
    return all(float(v) == 0.0 for v in d.values())


def apply_noise(ctx: ScenarioContext) -> dict[str, Any]:
    """Apply post-render perturbations. Returns a stats dict (currently
    ``{"d5_enforcement": {...}}`` when session jitter ran, else ``{}``)
    that ``runner.generate()`` folds into ``manifest["noise"]``."""
    stats: dict[str, Any] = {}
    n = ctx.noise
    if _all_zero(n):
        return stats

    if float(n.get("building_load_jitter_pct", 0.0)) > 0 or \
       float(n.get("occupancy_jitter_pct", 0.0)) > 0:
        df = ctx.rendered["building_load.csv"].copy()
        rng = rng_for_node(ctx.seed, "noise:building_load")
        b_jit = float(n.get("building_load_jitter_pct", 0.0))
        o_jit = float(n.get("occupancy_jitter_pct", 0.0))
        if b_jit > 0:
            f_noise = rng.normal(1.0, b_jit, size=len(df))
            i_noise = rng.normal(1.0, b_jit, size=len(df))
            df["power_flex_kw"] = np.clip(df["power_flex_kw"].to_numpy() * f_noise, 0, None)
            df["power_inflex_kw"] = np.clip(df["power_inflex_kw"].to_numpy() * i_noise, 0, None)
        if o_jit > 0:
            o_noise = rng.normal(1.0, o_jit, size=len(df))
            df["power_inflex_kw"] = np.clip(df["power_inflex_kw"].to_numpy() * o_noise, 0, None)
        df["power_kw"] = df["power_flex_kw"].to_numpy() + df["power_inflex_kw"].to_numpy()
        ctx.rendered["building_load.csv"] = df

    if float(n.get("price_jitter_pct", 0.0)) > 0:
        df = ctx.rendered["grid_prices.csv"].copy()
        rng = rng_for_node(ctx.seed, "noise:grid_prices")
        jit = float(n["price_jitter_pct"])
        df["price_per_kwh"] = np.clip(
            df["price_per_kwh"].to_numpy() * rng.normal(1.0, jit, size=len(df)),
            0, None,
        )
        ctx.rendered["grid_prices.csv"] = df

    if float(n.get("arrival_time_jitter_min", 0.0)) > 0 or \
       float(n.get("soc_arrival_jitter_pct", 0.0)) > 0:
        df = ctx.rendered["sessions.csv"].copy()
        if len(df) > 0:
            rng = rng_for_node(ctx.seed, "noise:sessions")
            t_jit = float(n.get("arrival_time_jitter_min", 0.0))
            s_jit = float(n.get("soc_arrival_jitter_pct", 0.0))
            if t_jit > 0:
                # Snap jitter to multiples of 15 minutes so arrival stays on
                # the 15-min tick grid (matches renderer invariant: both
                # arrival and departure live on 15-min boundaries, and
                # duration_sec is a multiple of 900).
                shifts_900 = np.round(rng.normal(0.0, t_jit, size=len(df)) / 15.0).astype(int)
                shifts_sec = shifts_900 * 900
                arrivals = pd.to_datetime(df["arrival"])
                deps = pd.to_datetime(df["departure"])
                # Forward bound — keep departure - new_arrival >= 15 minutes
                # (already a 900-multiple since both endpoints are on ticks).
                max_forward = (deps - arrivals).dt.total_seconds().astype(int) - _MIN_SESSION_DURATION_SEC
                shifts_sec = np.minimum(shifts_sec, max_forward.to_numpy())
                # Backward bound — keep new_arrival >= sim_window.start.
                sim_start_ts = pd.Timestamp(ctx.sim_start)
                min_backward = (sim_start_ts - arrivals).dt.total_seconds().astype(int)
                shifts_sec = np.maximum(shifts_sec, min_backward.to_numpy())
                new_arrivals = arrivals + pd.to_timedelta(shifts_sec, unit="s")
                df["arrival"] = new_arrivals.dt.strftime("%Y-%m-%d %H:%M:%S")
                df["duration_sec"] = (deps - new_arrivals).dt.total_seconds().astype(int)
            if s_jit > 0:
                additive = rng.normal(0.0, s_jit * 100.0, size=len(df))
                jittered = df["arrival_soc"].to_numpy() + additive
                # B3 fix: clamp per-car to [min_allowed_soc, max_allowed_soc]
                # so noise cannot violate D3. Looking up bounds from cars.csv
                # (already rendered) keeps this deterministic per car_id.
                cars = ctx.rendered["cars.csv"]
                bounds = cars.set_index("car_id")[
                    ["min_allowed_soc", "max_allowed_soc"]
                ].to_dict("index")
                car_ids = df["car_id"].to_numpy()
                lo = np.array([bounds[int(c)]["min_allowed_soc"] for c in car_ids])
                hi = np.array([bounds[int(c)]["max_allowed_soc"] for c in car_ids])
                df["arrival_soc"] = np.clip(jittered, lo, hi)
                # D6 preservation: arrival_soc must stay strictly below required_soc_at_depart.
                # Also re-enforce the per-car min_allowed_soc floor in case the B3 clamp was
                # done before this knob's interaction. Use min_allowed_soc from cars.csv.
                required = df["required_soc_at_depart"].to_numpy()
                cars = ctx.rendered["cars.csv"]
                min_floor_lookup = dict(zip(cars["car_id"].to_numpy(), cars["min_allowed_soc"].to_numpy()))
                min_floor = np.array([min_floor_lookup[c] for c in df["car_id"].to_numpy()])
                df["arrival_soc"] = np.maximum(
                    min_floor,
                    np.minimum(df["arrival_soc"].to_numpy(), required - 0.1),
                )
        ctx.rendered["sessions.csv"] = df

        # D5 post-jitter enforcement: arrival/SoC jitter can shrink the
        # feasibility budget below the session's required_soc target. Truncate
        # required_soc to the maximum feasible value (or drop if no valid
        # top-up target). Sampler's pre-jitter D5 check used max_charger_rate
        # — match it here.
        min_depart_soc_pct = float(ctx.knobs.get("user_behavior.min_depart_soc")) * 100.0
        kept, d5_stats = _enforce_d5_post_jitter(
            ctx.rendered["sessions.csv"],
            ctx.rendered["cars.csv"],
            ctx.rendered["chargers.csv"],
            min_depart_soc_pct,
        )
        ctx.rendered["sessions.csv"] = kept.reset_index(drop=True)
        stats["d5_enforcement"] = d5_stats

    if float(n.get("dr_notification_dropout_prob", 0.0)) > 0:
        df = ctx.rendered["dr_events.csv"]
        if len(df) > 0:
            rng = rng_for_node(ctx.seed, "noise:dr_events")
            p = float(n["dr_notification_dropout_prob"])
            mask = rng.random(size=len(df)) >= p
            ctx.rendered["dr_events.csv"] = df.loc[mask].reset_index(drop=True)

    return stats
