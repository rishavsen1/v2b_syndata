"""STUB: Tier 2 building load latents (L_flex, L_inflex).

Sinusoid-based dummy loads. Real EnergyPlus pipeline lands in Step 4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..seeding import rng_for_node
from ..types import ScenarioContext


def _sinusoid(idx: pd.DatetimeIndex, base: float, amp: float) -> np.ndarray:
    hour = idx.hour + idx.minute / 60.0
    return np.clip(base + amp * np.sin(2 * np.pi * (hour - 6) / 24), 0, None)


def sample_l_flex(ctx: ScenarioContext) -> None:
    idx = ctx.datetime_index()
    rng = rng_for_node(ctx.seed, "L_flex")
    base = _sinusoid(idx, base=120.0, amp=60.0)
    noise = rng.normal(0.0, 0.05, size=len(idx))  # ±5% multiplicative
    series = pd.Series(np.clip(base * (1.0 + noise), 0, None), index=idx, name="L_flex")
    ctx.latents["L_flex"] = series


def sample_l_inflex(ctx: ScenarioContext) -> None:
    idx = ctx.datetime_index()
    rng = rng_for_node(ctx.seed, "L_inflex")
    base = _sinusoid(idx, base=40.0, amp=15.0)
    noise = rng.normal(0.0, 0.03, size=len(idx))  # ±3%
    series = pd.Series(np.clip(base * (1.0 + noise), 0, None), index=idx, name="L_inflex")
    ctx.latents["L_inflex"] = series
