"""Step 6: Inhomogeneous Poisson DR event sampler.

D20 (locked): rate λ(t) = λ_base × seasonal(month) × dow(weekday) × temp(maxT) × tod(hour).
D63: each factor normalized so λ_base retains intuitive units (events/hour during
peak conditions).
D64: Lewis's thinning (modified Ogata) for sampling.
D65: per-month caps + per-season caps applied chronologically after sampling.
D70: program calibration constants live here, sourced from PG&E tariff docs +
CAISO DR reports. Not loaded from external data files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

ProgramName = Literal["CBP", "BIP", "ELRP"]


@dataclass(frozen=True)
class DRProgramSpec:
    """Static calibration constants per program."""
    name: str
    season_months: tuple[int, ...]
    notification_lead_hours: float
    duration_hours: float
    max_events_per_month: int
    max_events_per_season: int | None
    base_magnitude_kw_range: tuple[float, float]


PROGRAM_SPECS: dict[str, DRProgramSpec] = {
    "CBP": DRProgramSpec(
        name="CBP",
        season_months=(5, 6, 7, 8, 9, 10),
        notification_lead_hours=24.0,
        duration_hours=4.0,
        max_events_per_month=6,
        max_events_per_season=None,
        base_magnitude_kw_range=(50.0, 200.0),
    ),
    "BIP": DRProgramSpec(
        name="BIP",
        season_months=tuple(range(1, 13)),  # year-round
        notification_lead_hours=2.0,
        duration_hours=4.0,
        max_events_per_month=4,
        max_events_per_season=None,
        base_magnitude_kw_range=(100.0, 500.0),
    ),
    "ELRP": DRProgramSpec(
        name="ELRP",
        season_months=(5, 6, 7, 8, 9, 10),
        notification_lead_hours=2.0,
        duration_hours=4.0,
        max_events_per_month=10,
        max_events_per_season=10,
        base_magnitude_kw_range=(50.0, 300.0),
    ),
}

# Upper bound on the product of all per-factor multipliers. Used for thinning.
# seasonal ≤ 1, dow ≤ 1, temp ≤ 3 (cap above 100°F), tod ≤ 1 → 3.0 envelope.
_LAMBDA_FACTOR_MAX = 3.0

# Minimum tail rate for thinning safety: keeps the homogeneous candidate process
# productive even when lambda_base is tiny. Has no effect on retained events —
# only on candidate density.
_THINNING_FLOOR = 1e-6


def _seasonal_factor(month: int, spec: DRProgramSpec) -> float:
    return 1.0 if month in spec.season_months else 0.0


def _dow_factor(weekday: int) -> float:
    """0=Monday..6=Sunday. Weekdays favored 3:1 over weekends."""
    return 1.0 if weekday < 5 else 0.33


def _temp_factor(max_temp_f: float) -> float:
    """Heat-correlated dispatch ramp (D63).
    < 80°F → 0.1; 80–90 → 0.1→1.0; 90–100 → 1.0→3.0; ≥100 → 3.0.
    """
    if max_temp_f < 80:
        return 0.1
    if max_temp_f < 90:
        return 0.1 + 0.9 * (max_temp_f - 80) / 10
    if max_temp_f < 100:
        return 1.0 + 2.0 * (max_temp_f - 90) / 10
    return 3.0


def _tod_factor(hour: int) -> float:
    """Afternoon-clustered dispatch (D63). Peak 15-17, zero outside 12-20."""
    if hour < 12 or hour >= 20:
        return 0.0
    if 15 <= hour <= 17:
        return 1.0
    if 12 <= hour < 15:
        return 0.3 + 0.7 * (hour - 12) / 3
    return 1.0 - 0.7 * (hour - 17) / 3


def compute_rate(
    timestamp: pd.Timestamp,
    max_temp_f_today: float,
    program_spec: DRProgramSpec,
    lambda_base: float,
) -> float:
    """λ(t) in events/hour at the given instant."""
    return (
        lambda_base
        * _seasonal_factor(timestamp.month, program_spec)
        * _dow_factor(timestamp.weekday())
        * _temp_factor(max_temp_f_today)
        * _tod_factor(timestamp.hour)
    )


def sample_dr_events(
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
    daily_max_temp_f: pd.Series,
    program: str,
    lambda_base: float,
    magnitude_kw_range: tuple[float, float],
    rng: np.random.Generator,
) -> list[dict]:
    """Sample DR events via Lewis's thinning (D64).

    Returns a list of dicts ready for DataFrame construction:
      {event_id, start, end, magnitude_kw, notified_at}
    """
    if program not in PROGRAM_SPECS:
        raise ValueError(
            f"unsupported DR program {program!r}; "
            f"choices: {sorted(PROGRAM_SPECS)}"
        )
    spec = PROGRAM_SPECS[program]
    sim_window_start = pd.Timestamp(sim_window_start)
    sim_window_end = pd.Timestamp(sim_window_end)

    lambda_max = max(lambda_base * _LAMBDA_FACTOR_MAX, _THINNING_FLOOR)

    # Build a date→temp lookup keyed by python date (matches `pd.Timestamp.date()`).
    temp_lookup = {pd.Timestamp(idx).date(): float(val)
                   for idx, val in daily_max_temp_f.items()}

    candidates: list[pd.Timestamp] = []
    t = sim_window_start
    # Inhomogeneous Poisson via thinning: homogeneous candidate at lambda_max,
    # accept with prob λ(t)/λ_max.
    while True:
        gap_hours = float(rng.exponential(1.0 / lambda_max))
        t = t + pd.Timedelta(hours=gap_hours)
        if t >= sim_window_end:
            break
        max_temp = temp_lookup.get(t.date(), 70.0)
        rate = compute_rate(t, max_temp, spec, lambda_base)
        if rate <= 0.0:
            continue
        if rng.uniform() < rate / lambda_max:
            candidates.append(t)

    kept = _apply_caps(candidates, spec)
    events: list[dict] = []
    for idx, start_time in enumerate(kept):
        end_time = start_time + pd.Timedelta(hours=spec.duration_hours)
        notified_at = start_time - pd.Timedelta(hours=spec.notification_lead_hours)
        magnitude = float(rng.uniform(magnitude_kw_range[0], magnitude_kw_range[1]))
        events.append({
            "event_id": idx + 1,
            "start": start_time,
            "end": end_time,
            "magnitude_kw": magnitude,
            "notified_at": notified_at,
        })
    return events


def _apply_caps(
    candidates: list[pd.Timestamp], spec: DRProgramSpec,
) -> list[pd.Timestamp]:
    """Trim chronologically to enforce per-month and per-season caps."""
    candidates = sorted(candidates)
    kept: list[pd.Timestamp] = []
    by_month: dict[tuple[int, int], int] = {}
    by_season: dict[int, int] = {}
    for t in candidates:
        ym = (t.year, t.month)
        if by_month.get(ym, 0) >= spec.max_events_per_month:
            continue
        if spec.max_events_per_season is not None:
            if by_season.get(t.year, 0) >= spec.max_events_per_season:
                continue
        kept.append(t)
        by_month[ym] = by_month.get(ym, 0) + 1
        by_season[t.year] = by_season.get(t.year, 0) + 1
    return kept
