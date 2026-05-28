"""Unit tests for INL EV Project Phase 1 fetcher + extractor (fixture-driven)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from v2b_syndata.calibration.feature_extractor import aggregate_user_features
from v2b_syndata.calibration.inl_fetcher import fetch_all_sessions
from v2b_syndata.calibration.sources.inl import (
    InlSource,
    _extract_session_inl,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "inl_fixture.csv"


def _stage_fixture(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "inl_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_PATH, cache_dir / "inl_fixture.csv")
    return cache_dir


def test_fetch_uses_cache(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    assert isinstance(rows, list)
    assert len(rows) == 77
    venues = {r["venue"] for r in rows}
    assert venues == {"residential", "workplace"}


def test_extract_basic(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    sf = _extract_session_inl(rows[0], None, None, None)
    assert sf is not None
    assert sf.user_id.startswith("inl:vin:")
    assert sf.dwell_hours > 0
    assert sf.kwh_delivered > 0


def test_venue_filter_residential(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = InlSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "residential",
    })
    sites = {s.site for s in sessions}
    assert "workplace" not in sites
    assert "residential" in sites


def test_aggregate_user_features_runs(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = InlSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "residential",
    })
    assert sessions
    arrivals = [s.arrival_time for s in sessions]
    users = aggregate_user_features(sessions, min(arrivals), max(arrivals))
    assert users, "no users aggregated — check fixture active window"
    for u in users:
        assert 0.0 <= u.phi <= 1.0
        assert 0.0 <= u.kappa <= 1.0


def test_provenance_format():
    src = InlSource()
    prov = src.provenance_prefix({"archive_tag": "fixture"})
    today = dt.date.today().isoformat().replace("-", "")
    assert prov.startswith("calibration:inl_ev_project_fixture_")
    assert prov.endswith(today)


def test_extra_metadata_user_id_strategy():
    src = InlSource()
    meta = src.extra_metadata({"archive_tag": "fixture", "venue_filter": "residential"})
    assert meta["user_id_strategy"] == "vin_proxy"
    assert meta["archive_tag"] == "fixture"
    assert meta["venue_filter"] == "residential"
    assert meta["fleet_era"] == "phase1_2011_2013"
    assert meta["schema_version"]


def test_token_help_message_mentions_env_var():
    msg = InlSource().token_help_message()
    assert "INL_BULK_URL" in msg


def test_missing_url_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("INL_BULK_URL", raising=False)
    monkeypatch.delenv("INL_API_TOKEN", raising=False)
    cache_dir = tmp_path / "empty_cache"
    cache_dir.mkdir()
    with pytest.raises(RuntimeError) as exc:
        fetch_all_sessions("nope", cache_dir)
    assert "INL_BULK_URL" in str(exc.value)


def test_vin_fallback_to_port_proxy(tmp_path):
    """Row with missing vehicle_id falls back to inl:port:<evse> user_id."""
    row_missing_vin = {
        "vehicle_id": "",
        "evse_id": "EVSE_R99",
        "venue": "residential",
        "evse_power_kw": 3.3,
        "start_time": "2012-03-01T18:00:00",
        "end_time": "2012-03-02T06:00:00",
        "energy_kwh": 14.0,
    }
    sf = _extract_session_inl(row_missing_vin, "residential", None, None)
    assert sf is not None
    assert sf.user_id == "inl:port:EVSE_R99"

    # The fixture already includes one row with missing vehicle_id; the
    # source-level extra_metadata stays vin_proxy because that single row
    # does not dominate the 65-session cohort.
    cache_dir = _stage_fixture(tmp_path)
    src = InlSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "residential",
    })
    assert any(s.user_id.startswith("inl:port:") for s in sessions)
    assert any(s.user_id.startswith("inl:vin:") for s in sessions)
    meta = src.extra_metadata({"archive_tag": "fixture", "venue_filter": "residential"})
    assert meta["user_id_strategy"] == "vin_proxy"

    # When the cohort is dominated by port-proxy rows, the source flips.
    src2 = InlSource()
    for _ in range(3):
        src2._n_port += 1  # simulate dominant fallback
    src2._n_vin += 1
    meta2 = src2.extra_metadata({"archive_tag": "fixture"})
    assert meta2["user_id_strategy"] == "port_proxy"


def test_parse_args_typed():
    src = InlSource()
    parsed = src.parse_args([
        "archive_tag=phase1",
        "venue_filter=residential",
        "min_power_kw=3",
        "max_power_kw=22",
    ])
    assert parsed["archive_tag"] == "phase1"
    assert parsed["venue_filter"] == "residential"
    assert parsed["min_power_kw"] == pytest.approx(3.0)
    assert parsed["max_power_kw"] == pytest.approx(22.0)
