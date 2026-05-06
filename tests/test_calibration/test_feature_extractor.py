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


def test_phi_uses_per_user_active_window():
    """Step 5.5 phi fix: a user concentrated in a short span gets a high phi
    even when the global window is wide.
    """
    from v2b_syndata.calibration.feature_extractor import SessionFeatures
    # 8 sessions over 2 weeks, all in early 2020. Calibration window = 3 years.
    base = pd.Timestamp("2020-01-06", tz="UTC")  # Monday
    sessions = []
    for d in (0, 1, 2, 3, 7, 8, 9, 10):  # 4 weekdays in week 1, 4 in week 2
        ts = base + pd.Timedelta(days=d)
        sessions.append(SessionFeatures(
            user_id="concentrated",
            site="caltech",
            arrival_time=ts + pd.Timedelta(hours=9),
            arrival_hour=9.0,
            dwell_hours=8.0,
            kwh_delivered=10.0,
            miles_requested=None,
            wh_per_mile=None,
            kwh_requested=None,
            minutes_available=None,
        ))
    window_start = pd.Timestamp("2019-01-01", tz="UTC")
    window_end = pd.Timestamp("2021-12-31", tz="UTC")  # 3-year wide window
    users = aggregate_user_features(sessions, window_start, window_end)
    assert len(users) == 1
    u = users[0]
    # Active window = 11 days = 9 weekdays. 8 unique observed → phi ~ 0.89.
    assert u.phi > 0.8, f"per-user-window phi = {u.phi}, expected > 0.8"


def test_phi_filter_short_active_window():
    """Users with active windows shorter than 5 weekdays are dropped."""
    from v2b_syndata.calibration.feature_extractor import SessionFeatures
    # 5 sessions all on consecutive days within 4 weekdays
    base = pd.Timestamp("2020-01-06", tz="UTC")
    sessions = []
    for d in range(5):
        ts = base + pd.Timedelta(days=d, hours=d * 0.5)
        sessions.append(SessionFeatures(
            user_id="short_user",
            site="caltech",
            arrival_time=ts + pd.Timedelta(hours=9),
            arrival_hour=9.0 + d * 0.5,
            dwell_hours=4.0,
            kwh_delivered=5.0,
            miles_requested=None, wh_per_mile=None,
            kwh_requested=None, minutes_available=None,
        ))
    window_start = pd.Timestamp("2020-01-01", tz="UTC")
    window_end = pd.Timestamp("2020-12-31", tz="UTC")
    users = aggregate_user_features(sessions, window_start, window_end)
    # Active window Jan 6-10 = 5 calendar days = 5 weekdays. Boundary case
    # passes the >= 5 filter. (Tested >= filter below.)
    assert len(users) == 1


def test_phi_filter_drops_3_weekday_window():
    """Active window < 5 weekdays → dropped."""
    from v2b_syndata.calibration.feature_extractor import SessionFeatures
    base = pd.Timestamp("2020-01-06", tz="UTC")  # Monday
    sessions = []
    for d in range(5):  # 5 sessions all on Monday-Wednesday
        ts = base + pd.Timedelta(days=d % 3, hours=d * 0.1)
        sessions.append(SessionFeatures(
            user_id="too_short",
            site="caltech",
            arrival_time=ts + pd.Timedelta(hours=9),
            arrival_hour=9.0,
            dwell_hours=4.0,
            kwh_delivered=5.0,
            miles_requested=None, wh_per_mile=None,
            kwh_requested=None, minutes_available=None,
        ))
    window_start = pd.Timestamp("2020-01-01", tz="UTC")
    window_end = pd.Timestamp("2020-12-31", tz="UTC")
    users = aggregate_user_features(sessions, window_start, window_end)
    # Active window = 3 weekdays < 5 → user dropped.
    assert len(users) == 0
