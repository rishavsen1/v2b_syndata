"""Per-session and per-user feature extraction from raw ACN-Data session dicts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MIN_SESSIONS_PER_USER = 5  # Drop users with fewer; statistical noise.

# ACN-Data ships connection/disconnect in true UTC (the "GMT" suffix is real).
# All three ACN sites (Caltech, JPL, Office001) are in California, so arrival
# *clock hour* must be read in Pacific time — otherwise an 08:00 PT commute
# arrival is recorded as 16:00 and the fitted distribution clips at the 20:00
# truncnorm ceiling. (bench/runner.py already anchors ACN at America/Los_Angeles.)
ACN_TZ = "America/Los_Angeles"

# Sessions shorter than this are dropped before fitting — sub-30-min plug-ins
# are dominated by metering noise / failed connects and bias the dwell fit.
MIN_DWELL_HOURS = 0.5


@dataclass
class SessionFeatures:
    user_id: str
    site: str
    arrival_time: pd.Timestamp
    arrival_hour: float
    dwell_hours: float
    kwh_delivered: float
    miles_requested: float | None
    wh_per_mile: float | None
    kwh_requested: float | None
    minutes_available: float | None


@dataclass
class UserFeatures:
    user_id: str
    n_sessions: int
    n_weekdays_observed: int
    n_weekdays_total: int
    phi: float
    kappa: float
    delta_km: float | None


def extract_session(raw: dict[str, Any], site: str) -> SessionFeatures | None:
    """Convert one raw ACN session dict to SessionFeatures.

    Returns None if essential fields cannot be parsed.
    """
    try:
        # Parse as true UTC, convert to Pacific wall-clock, then drop the tz so
        # arrival_time is naive *local* (no timezone in any downstream CSV).
        connection = (pd.to_datetime(raw["connectionTime"], format="%a, %d %b %Y %H:%M:%S GMT", utc=True)
                      .tz_convert(ACN_TZ).tz_localize(None))
        disconnect = (pd.to_datetime(raw["disconnectTime"], format="%a, %d %b %Y %H:%M:%S GMT", utc=True)
                      .tz_convert(ACN_TZ).tz_localize(None))
    except (KeyError, ValueError, TypeError):
        return None

    dwell = (disconnect - connection).total_seconds() / 3600.0
    if dwell < MIN_DWELL_HOURS or dwell > 168.0:  # < 30 min noise; > 1 week bogus
        return None

    arr_hour = connection.hour + connection.minute / 60.0 + connection.second / 3600.0

    user_inputs = raw.get("userInputs")
    miles = wpm = kwh_req = mins = None
    if isinstance(user_inputs, list) and user_inputs:
        ui = user_inputs[0]
    elif isinstance(user_inputs, dict):
        ui = user_inputs
    else:
        ui = None
    if ui is not None:
        miles = _safe_float(ui.get("milesRequested"))
        wpm = _safe_float(ui.get("WhPerMile"))
        kwh_req = _safe_float(ui.get("kWhRequested"))
        mins = _safe_float(ui.get("minutesAvailable"))

    kwh_del = _safe_float(raw.get("kWhDelivered")) or 0.0

    return SessionFeatures(
        user_id=str(raw["userID"]),
        site=site,
        arrival_time=connection,
        arrival_hour=float(arr_hour),
        dwell_hours=float(dwell),
        kwh_delivered=float(kwh_del),
        miles_requested=miles,
        wh_per_mile=wpm,
        kwh_requested=kwh_req,
        minutes_available=mins,
    )


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


MIN_WEEKDAYS_IN_USER_WINDOW = 5  # filter out users with too short an active window


def _count_weekdays(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Count weekdays in inclusive [start, end] range."""
    if end < start:
        return 0
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz=start.tz)
    return int((days.dayofweek < 5).sum())


def aggregate_user_features(
    sessions: list[SessionFeatures],
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> list[UserFeatures]:
    """Compute (φ, κ, δ_km) per user across sessions.

    φ uses a **per-user active window** [first_session, last_session] rather
    than the global calibration window. A user with 22 sessions over 6 months
    (4 weekdays/week) is recognized as high-frequency even if the global
    calibration window spans 3 years; using the global denominator would
    artificially crush φ to ~0.07.

    Filters: users with < MIN_SESSIONS_PER_USER sessions OR < MIN_WEEKDAYS_IN_USER_WINDOW
    weekdays in their active window (statistically noisy).

    `window_start`/`window_end` are kept for backwards compatibility with
    existing callers and recorded on UserFeatures.n_weekdays_total for
    diagnostic purposes only.
    """
    if not sessions:
        return []

    df = pd.DataFrame([s.__dict__ for s in sessions])

    out: list[UserFeatures] = []
    for uid, g in df.groupby("user_id"):
        n = len(g)
        if n < MIN_SESSIONS_PER_USER:
            continue

        # Per-user active window (Step 5.5 fix).
        arrival_times = pd.to_datetime(g["arrival_time"])
        user_first = arrival_times.min()
        user_last = arrival_times.max()
        n_weekdays_user = _count_weekdays(user_first, user_last)
        if n_weekdays_user < MIN_WEEKDAYS_IN_USER_WINDOW:
            continue

        unique_weekdays = set()
        for ts in g["arrival_time"]:
            ts_pd = pd.Timestamp(ts)
            if ts_pd.dayofweek < 5:
                unique_weekdays.add(ts_pd.date())
        n_obs = len(unique_weekdays)
        phi = (n_obs / n_weekdays_user) if n_weekdays_user > 0 else 0.0
        phi = float(min(1.0, max(0.0, phi)))

        arr_hours = g["arrival_hour"].to_numpy()
        if arr_hours.std() == 0 or arr_hours.mean() == 0:
            kappa = 1.0
        else:
            cv = arr_hours.std() / arr_hours.mean()
            kappa = float(max(0.0, min(1.0, 1.0 - cv)))

        miles = g["miles_requested"].dropna()
        if len(miles) > 0:
            delta_km = float(miles.mean() * 1.609344)
        else:
            delta_km = None

        out.append(UserFeatures(
            user_id=str(uid),
            n_sessions=int(n),
            n_weekdays_observed=int(n_obs),
            n_weekdays_total=int(n_weekdays_user),  # per-user active window
            phi=phi,
            kappa=kappa,
            delta_km=delta_km,
        ))

    return out
