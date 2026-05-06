"""Tests for feature_extractor."""
from __future__ import annotations

import pandas as pd
import pytest

from v2b_syndata.calibration.feature_extractor import (
    aggregate_user_features,
    extract_session,
)


def test_extract_session_with_userinputs(raw_acn_session):
    sf = extract_session(raw_acn_session, site="caltech")
    assert sf is not None
    assert sf.user_id == "12345"
    assert sf.arrival_hour == pytest.approx(9.0, abs=0.01)
    assert sf.dwell_hours == pytest.approx(8.0, abs=0.01)
    assert sf.kwh_delivered == pytest.approx(12.3)
    assert sf.miles_requested == 40.0
    assert sf.wh_per_mile == 250.0
    assert sf.kwh_requested == 10.0


def test_extract_session_without_userinputs():
    raw = {
        "userID": "u1",
        "connectionTime": "Mon, 06 Jan 2020 09:00:00 GMT",
        "disconnectTime": "Mon, 06 Jan 2020 11:00:00 GMT",
        "kWhDelivered": 5.0,
        "userInputs": None,
    }
    sf = extract_session(raw, site="jpl")
    assert sf is not None
    assert sf.miles_requested is None
    assert sf.wh_per_mile is None
    assert sf.kwh_requested is None


def test_extract_session_invalid_dates_returns_none():
    raw = {
        "userID": "u1",
        "connectionTime": "garbage",
        "disconnectTime": "garbage",
        "kWhDelivered": 1.0,
    }
    assert extract_session(raw, "caltech") is None


def test_extract_session_negative_dwell_returns_none():
    raw = {
        "userID": "u1",
        "connectionTime": "Mon, 06 Jan 2020 11:00:00 GMT",
        "disconnectTime": "Mon, 06 Jan 2020 09:00:00 GMT",
        "kWhDelivered": 1.0,
    }
    assert extract_session(raw, "caltech") is None


def test_aggregate_user_features_filters_low_session_users(synthetic_sessions):
    # Add a sparse user (< 5 sessions)
    synthetic_sessions = list(synthetic_sessions)
    base = pd.Timestamp("2020-02-01", tz="UTC")
    for i in range(3):
        synthetic_sessions.append(synthetic_sessions[0].__class__(
            user_id="sparse_user",
            site="caltech",
            arrival_time=base + pd.Timedelta(days=i),
            arrival_hour=9.0,
            dwell_hours=8.0,
            kwh_delivered=10.0,
            miles_requested=None,
            wh_per_mile=None,
            kwh_requested=None,
            minutes_available=None,
        ))
    window_start = pd.Timestamp("2020-01-01", tz="UTC")
    window_end = pd.Timestamp("2020-12-31", tz="UTC")
    users = aggregate_user_features(synthetic_sessions, window_start, window_end)
    user_ids = {u.user_id for u in users}
    assert "user_a" in user_ids
    assert "sparse_user" not in user_ids


def test_aggregate_user_features_phi_kappa(synthetic_sessions):
    window_start = pd.Timestamp("2020-01-01", tz="UTC")
    window_end = pd.Timestamp("2020-03-31", tz="UTC")
    users = aggregate_user_features(synthetic_sessions, window_start, window_end)
    assert len(users) == 1
    u = users[0]
    assert 0.0 <= u.phi <= 1.0
    assert 0.0 <= u.kappa <= 1.0
    # arrival_hour ~ 9 ± 0.1, very consistent → kappa close to 1
    assert u.kappa > 0.9
    # delta_km from 40 mi requested
    assert u.delta_km == pytest.approx(40 * 1.609344, abs=0.01)
