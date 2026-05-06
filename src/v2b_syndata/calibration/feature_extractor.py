"""Per-session and per-user feature extraction from raw ACN-Data session dicts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MIN_SESSIONS_PER_USER = 5  # Drop users with fewer; statistical noise.


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
        connection = pd.to_datetime(raw["connectionTime"], format="%a, %d %b %Y %H:%M:%S GMT", utc=True)
        disconnect = pd.to_datetime(raw["disconnectTime"], format="%a, %d %b %Y %H:%M:%S GMT", utc=True)
    except (KeyError, ValueError, TypeError):
        return None

    dwell = (disconnect - connection).total_seconds() / 3600.0
    if dwell <= 0 or dwell > 168.0:  # > 1 week is bogus
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


def aggregate_user_features(
    sessions: list[SessionFeatures],
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> list[UserFeatures]:
    """Compute (φ, κ, δ_km) per user across sessions.

    Filters users with < MIN_SESSIONS_PER_USER sessions.
    """
    if not sessions:
        return []

    df = pd.DataFrame([s.__dict__ for s in sessions])
    weekday_dates = pd.date_range(window_start.normalize(), window_end.normalize(), freq="D", tz="UTC")
    weekday_dates = weekday_dates[weekday_dates.dayofweek < 5]
    n_weekdays_total = int(len(weekday_dates))

    out: list[UserFeatures] = []
    for uid, g in df.groupby("user_id"):
        n = len(g)
        if n < MIN_SESSIONS_PER_USER:
            continue

        unique_weekdays = set()
        for ts in g["arrival_time"]:
            ts_pd = pd.Timestamp(ts)
            if ts_pd.dayofweek < 5:
                unique_weekdays.add(ts_pd.date())
        n_obs = len(unique_weekdays)
        phi = (n_obs / n_weekdays_total) if n_weekdays_total > 0 else 0.0
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
            n_weekdays_total=n_weekdays_total,
            phi=phi,
            kappa=kappa,
            delta_km=delta_km,
        ))

    return out
