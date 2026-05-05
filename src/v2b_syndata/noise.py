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
                shifts = rng.normal(0.0, t_jit, size=len(df))
                arrivals = pd.to_datetime(df["arrival"])
                new_arrivals = arrivals + pd.to_timedelta(shifts, unit="m")
                df["arrival"] = new_arrivals.dt.strftime("%Y-%m-%d %H:%M:%S")
                # Update duration to keep departure stable, since renderer
                # already stored departure as text. Recompute duration_sec.
                deps = pd.to_datetime(df["departure"])
                df["duration_sec"] = (deps - new_arrivals).dt.total_seconds().astype(int)
            if s_jit > 0:
                additive = rng.normal(0.0, s_jit * 100.0, size=len(df))
                df["arrival_soc"] = np.clip(df["arrival_soc"].to_numpy() + additive, 0, 100)
        ctx.rendered["sessions.csv"] = df

    if float(n.get("dr_notification_dropout_prob", 0.0)) > 0:
        df = ctx.rendered["dr_events.csv"]
        if len(df) > 0:
            rng = rng_for_node(ctx.seed, "noise:dr_events")
            p = float(n["dr_notification_dropout_prob"])
            mask = rng.random(size=len(df)) >= p
            ctx.rendered["dr_events.csv"] = df.loc[mask].reset_index(drop=True)
