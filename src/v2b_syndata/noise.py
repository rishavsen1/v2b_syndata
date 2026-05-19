"""Post-render perturbation per noise_profiles.yaml.

Profile knobs (resolved into ctx.noise) drive the perturbation. With the
`clean` profile (all zeros) every block below is a no-op and CSV bytes are
unchanged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .seeding import rng_for_node
from .types import ScenarioContext

_MIN_SESSION_DURATION_SEC = 15 * 60  # 15 min — matches building_load grid resolution


def _all_zero(d: dict[str, float]) -> bool:
    return all(float(v) == 0.0 for v in d.values())


def apply_noise(ctx: ScenarioContext) -> None:
    n = ctx.noise
    if _all_zero(n):
        return

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
                # Round shifts to whole seconds. CSV stores arrival at second
                # precision (strftime '%H:%M:%S' truncates fractions); leaving
                # microsecond-level shifts in the in-memory timestamp would
                # make duration_sec disagree with (departure - reloaded_arrival)
                # → C6 mismatch on validate.
                shifts_sec = np.round(rng.normal(0.0, t_jit, size=len(df)) * 60.0).astype(int)
                arrivals = pd.to_datetime(df["arrival"])
                deps = pd.to_datetime(df["departure"])
                # Forward bound — keep departure - new_arrival >= 15 minutes.
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

    if float(n.get("dr_notification_dropout_prob", 0.0)) > 0:
        df = ctx.rendered["dr_events.csv"]
        if len(df) > 0:
            rng = rng_for_node(ctx.seed, "noise:dr_events")
            p = float(n["dr_notification_dropout_prob"])
            mask = rng.random(size=len(df)) >= p
            ctx.rendered["dr_events.csv"] = df.loc[mask].reset_index(drop=True)
