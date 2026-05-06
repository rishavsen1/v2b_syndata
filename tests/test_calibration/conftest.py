"""Calibration test fixtures."""
from __future__ import annotations

import pandas as pd
import pytest

from v2b_syndata.calibration.feature_extractor import SessionFeatures


@pytest.fixture
def synthetic_sessions() -> list[SessionFeatures]:
    """A small set of sessions for one user, on weekdays at ~9 AM."""
    base = pd.Timestamp("2020-01-06", tz="UTC")  # Monday
    out = []
    for d in range(0, 30, 1):
        ts = base + pd.Timedelta(days=d)
        if ts.dayofweek >= 5:
            continue
        arr_hour = 9.0 + (d % 3) * 0.1
        out.append(SessionFeatures(
            user_id="user_a",
            site="caltech",
            arrival_time=ts + pd.Timedelta(hours=arr_hour),
            arrival_hour=arr_hour,
            dwell_hours=8.0,
            kwh_delivered=15.0,
            miles_requested=40.0,
            wh_per_mile=250.0,
            kwh_requested=10.0,
            minutes_available=480.0,
        ))
    return out


@pytest.fixture
def raw_acn_session() -> dict:
    """Raw ACN-Data-like session dict."""
    return {
        "userID": 12345,
        "connectionTime": "Mon, 06 Jan 2020 09:00:00 GMT",
        "disconnectTime": "Mon, 06 Jan 2020 17:00:00 GMT",
        "kWhDelivered": 12.3,
        "userInputs": [
            {
                "milesRequested": 40,
                "WhPerMile": 250,
                "kWhRequested": 10.0,
                "minutesAvailable": 480,
            }
        ],
    }
