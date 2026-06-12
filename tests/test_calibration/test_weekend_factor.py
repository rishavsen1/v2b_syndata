"""population_weekend_factor: weekend:weekday session-density ratio."""
from __future__ import annotations

import pandas as pd

from v2b_syndata.calibration.feature_extractor import (
    SessionFeatures,
    population_weekend_factor,
)

# April 2020: 4=Sat, 5=Sun, 6=Mon, 7=Tue, 8=Wed, 9=Thu, 10=Fri.


def _sf(day: int, hour: int = 9) -> SessionFeatures:
    ts = pd.Timestamp(f"2020-04-{day:02d} {hour:02d}:00:00")
    return SessionFeatures(
        user_id="u", site="s", arrival_time=ts, arrival_hour=float(hour),
        dwell_hours=4.0, kwh_delivered=10.0, miles_requested=None,
        wh_per_mile=None, kwh_requested=None, minutes_available=None,
    )


def test_empty_is_zero():
    assert population_weekend_factor([]) == 0.0


def test_no_weekend_sessions_is_zero():
    weekdays_only = [_sf(d) for d in (6, 7, 8, 9, 10)]
    assert population_weekend_factor(weekdays_only) == 0.0


def test_equal_density_is_one():
    sess = []
    for d in (6, 7):            # 2 sessions on each of 2 weekdays
        sess += [_sf(d, 9), _sf(d, 17)]
    for d in (4, 5):            # 2 sessions on each of 2 weekend days
        sess += [_sf(d, 9), _sf(d, 17)]
    assert abs(population_weekend_factor(sess) - 1.0) < 1e-9


def test_half_weekend_density():
    sess = []
    for d in (6, 7):            # weekday: 2/day
        sess += [_sf(d, 9), _sf(d, 17)]
    for d in (4, 5):            # weekend: 1/day → factor 0.5
        sess += [_sf(d, 9)]
    assert abs(population_weekend_factor(sess) - 0.5) < 1e-9
