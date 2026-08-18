"""E5 hybrid enforcement — generation-time observability of concurrent-session
infeasibility. Sampler stays per-car independent; this module surfaces
realized fleet-level concurrency so users see infeasibility before validation.
See DESIGN_NOTES.md #30.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class E5Report:
    realized_max_concurrent: int
    n_chargers: int
    infeasible: bool
    infeasible_tick_count: int
    total_tick_count: int

    @property
    def infeasible_tick_fraction(self) -> float:
        return self.infeasible_tick_count / self.total_tick_count if self.total_tick_count else 0.0


class InfeasibilityError(RuntimeError):
    """Raised when --strict-e5 is set and realized concurrent occupancy
    exceeds charger count."""


def compute_concurrency(
    sessions: pd.DataFrame,
    sim_start: datetime,
    sim_end: datetime,
    n_chargers: int,
    freq: str = "15min",
) -> E5Report:
    """Sweep the sim window at ``freq`` ticks; count concurrent active sessions
    and infeasible ticks against ``n_chargers``."""
    ticks = pd.date_range(pd.Timestamp(sim_start), pd.Timestamp(sim_end), freq=freq, inclusive="left")
    total = len(ticks)
    if len(sessions) == 0 or total == 0:
        return E5Report(0, n_chargers, False, 0, total)
    arrivals = pd.to_datetime(sessions["arrival"]).to_numpy()
    departures = pd.to_datetime(sessions["departure"]).to_numpy()
    # Vectorized broadcast: ticks[None,:] vs arrivals[:,None] — O(N×T). For
    # typical scenarios N×T < 1e6 (e.g. 500 sessions × 2900 ticks ≈ 1.5e6), so
    # acceptable. Switch to event-sweep if profiling shows hot spot.
    tick_np = ticks.to_numpy()
    active = (arrivals[:, None] <= tick_np[None, :]) & (departures[:, None] > tick_np[None, :])
    counts = active.sum(axis=0).astype(int)
    max_concurrent = int(counts.max())
    infeasible_count = int((counts > n_chargers).sum())
    return E5Report(
        realized_max_concurrent=max_concurrent,
        n_chargers=n_chargers,
        infeasible=max_concurrent > n_chargers,
        infeasible_tick_count=infeasible_count,
        total_tick_count=total,
    )
