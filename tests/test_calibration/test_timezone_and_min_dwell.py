"""Timezone correctness + <30-min dwell filter across calibration sources.

ACN-Data ships *true* UTC (GMT) for California sites → arrival hour must be read
in Pacific. ElaadNL / EV WATTS / INL ship naive *local* timestamps → relabelling
as UTC preserves the local clock hour, so those must NOT be shifted. All sources
drop sessions shorter than 30 minutes before fitting.
"""
from __future__ import annotations

import pytest

from v2b_syndata.calibration.feature_extractor import extract_session
from v2b_syndata.calibration.sources.elaadnl import _extract_session_elaadnl
from v2b_syndata.calibration.sources.evwatts import _extract_session_evwatts
from v2b_syndata.calibration.sources.inl import _extract_session_inl


def _acn(conn: str, disc: str) -> dict:
    return {"userID": "u", "connectionTime": conn, "disconnectTime": disc,
            "kWhDelivered": 5.0, "userInputs": None}


# ---- ACN: true UTC → Pacific conversion (the bug) ----

def test_acn_winter_arrival_converted_to_pst():
    # 16:00 UTC, 6 Jan 2020 (PST, UTC-8) → 08:00 Pacific: a real morning commute.
    sf = extract_session(_acn("Mon, 06 Jan 2020 16:00:00 GMT",
                              "Mon, 06 Jan 2020 22:00:00 GMT"), site="caltech")
    assert sf is not None
    assert sf.arrival_hour == pytest.approx(8.0, abs=0.01)
    assert sf.arrival_time.tzinfo is None  # naive local, no tz leaks downstream


def test_acn_summer_arrival_converted_to_pdt():
    # 16:00 UTC, 6 Jul 2020 (PDT, UTC-7) → 09:00 Pacific.
    sf = extract_session(_acn("Mon, 06 Jul 2020 16:00:00 GMT",
                              "Mon, 06 Jul 2020 22:00:00 GMT"), site="jpl")
    assert sf is not None
    assert sf.arrival_hour == pytest.approx(9.0, abs=0.01)


def test_acn_dwell_is_tz_invariant():
    sf = extract_session(_acn("Mon, 06 Jan 2020 16:00:00 GMT",
                              "Tue, 07 Jan 2020 00:00:00 GMT"), site="caltech")
    assert sf is not None and sf.dwell_hours == pytest.approx(8.0, abs=0.01)


def test_acn_under_30min_dropped():
    assert extract_session(_acn("Mon, 06 Jan 2020 16:00:00 GMT",
                                "Mon, 06 Jan 2020 16:20:00 GMT"), site="caltech") is None


def test_acn_exactly_30min_kept():
    sf = extract_session(_acn("Mon, 06 Jan 2020 16:00:00 GMT",
                              "Mon, 06 Jan 2020 16:30:00 GMT"), site="caltech")
    assert sf is not None and sf.dwell_hours == pytest.approx(0.5, abs=0.01)


# ---- Naive-local sources: hour preserved, NOT shifted ----

def test_elaadnl_local_hour_preserved():
    row = {"card_id": "C1", "evse_id": "E1", "venue": "workplace",
           "evse_power_kw": 11.0, "start_time": "2020-02-03T17:00:00",
           "end_time": "2020-02-03T21:00:00", "energy_kwh": 30.0}
    sf = _extract_session_elaadnl(row, venue_filter=None, min_kw=None, max_kw=None)
    assert sf is not None and sf.arrival_hour == pytest.approx(17.0, abs=0.01)


def test_inl_local_hour_preserved():
    row = {"vehicle_id": "V1", "evse_id": "E1", "venue": "residential",
           "evse_power_kw": 3.3, "start_time": "2012-02-01T18:00:00",
           "end_time": "2012-02-01T23:00:00", "energy_kwh": 12.0}
    sf = _extract_session_inl(row, venue_filter=None, min_kw=None, max_kw=None)
    assert sf is not None and sf.arrival_hour == pytest.approx(18.0, abs=0.01)


@pytest.mark.parametrize("extractor,row", [
    (_extract_session_elaadnl, {"card_id": "C1", "evse_id": "E1", "venue": "workplace",
        "evse_power_kw": 11.0, "start_time": "2020-02-03T17:00:00",
        "end_time": "2020-02-03T17:20:00", "energy_kwh": 2.0}),
    (_extract_session_inl, {"vehicle_id": "V1", "evse_id": "E1", "venue": "residential",
        "evse_power_kw": 3.3, "start_time": "2012-02-01T18:00:00",
        "end_time": "2012-02-01T18:20:00", "energy_kwh": 1.0}),
    (_extract_session_evwatts, {"evse_id": "E1", "venue_type": "workplace",
        "rated_power_kw": 7.0, "start_time_utc": "2024-01-08T08:00:00",
        "end_time_utc": "2024-01-08T08:20:00", "energy_kwh": 2.0}),
])
def test_naive_sources_drop_under_30min(extractor, row):
    assert extractor(row, venue_filter=None, min_kw=None, max_kw=None) is None
