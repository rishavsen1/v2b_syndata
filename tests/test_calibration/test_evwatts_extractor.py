"""Unit tests for EV WATTS fetcher + extractor (CSV-fixture-driven, no network)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.calibration.evwatts_fetcher import fetch_all_sessions
from v2b_syndata.calibration.feature_extractor import aggregate_user_features
from v2b_syndata.calibration.sources.evwatts import (
    EvWattsSource,
    _extract_session_evwatts,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "evwatts_fixture.csv"


def _stage_fixture(tmp_path: Path) -> Path:
    """Copy the CSV fixture into a tmp cache dir under the expected name."""
    cache_dir = tmp_path / "evwatts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_PATH, cache_dir / "evwatts_fixture.csv")
    return cache_dir


def test_fetch_uses_cache(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    assert isinstance(rows, list)
    assert len(rows) == 80
    venues = {r["venue_type"] for r in rows}
    assert venues == {"workplace", "public", "residential"}


def test_extract_basic(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    sf = _extract_session_evwatts(rows[0], None, None, None)
    assert sf is not None
    assert sf.user_id.startswith("evwatts:port:")
    assert sf.dwell_hours > 0
    assert sf.kwh_delivered > 0


def test_venue_filter_workplace_public(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = EvWattsSource()
    sessions = src.fetch_sessions({
        "release_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "workplace_public",
    })
    # Residential rows must be excluded; workplace + public remain.
    sites = {s.site for s in sessions}
    assert "residential" not in sites
    assert "workplace" in sites
    assert "public" in sites


def test_venue_filter_dcfc(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = EvWattsSource()
    sessions = src.fetch_sessions({
        "release_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "dcfc_public",
        "min_power_kw": 50.0,
    })
    # Only DCFC (50 kW) ports survive the power filter.
    sites = {s.site for s in sessions}
    assert sites == {"public"}
    assert all(s.user_id.startswith("evwatts:port:EVSE_D") for s in sessions)


def test_aggregate_user_features_runs(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = EvWattsSource()
    sessions = src.fetch_sessions({
        "release_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "workplace_public",
    })
    assert sessions
    arrivals = [s.arrival_time for s in sessions]
    users = aggregate_user_features(sessions, min(arrivals), max(arrivals))
    assert users, "no users aggregated — check fixture active window"
    for u in users:
        assert 0.0 <= u.phi <= 1.0
        assert 0.0 <= u.kappa <= 1.0


def test_provenance_format():
    src = EvWattsSource()
    prov = src.provenance_prefix({"release_tag": "fixture"})
    today = dt.date.today().isoformat().replace("-", "")
    assert prov.startswith("calibration:evwatts_fixture_")
    assert prov.endswith(today)


def test_extra_metadata_user_id_strategy():
    src = EvWattsSource()
    meta = src.extra_metadata({"release_tag": "fixture", "venue_filter": "workplace_public"})
    assert meta["user_id_strategy"] == "port_proxy"
    assert meta["release_tag"] == "fixture"
    assert meta["venue_filter"] == "workplace_public"
    assert meta["schema_version"]


def test_token_help_message_mentions_env_var():
    msg = EvWattsSource().token_help_message()
    assert "EVWATTS_BULK_URL" in msg


def test_missing_url_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("EVWATTS_BULK_URL", raising=False)
    monkeypatch.delenv("EVWATTS_API_TOKEN", raising=False)
    cache_dir = tmp_path / "empty_cache"
    cache_dir.mkdir()
    with pytest.raises(RuntimeError) as exc:
        fetch_all_sessions("nope", cache_dir)
    assert "EVWATTS_BULK_URL" in str(exc.value)


def test_parse_args_typed():
    src = EvWattsSource()
    parsed = src.parse_args([
        "release_tag=fixture",
        "venue_filter=workplace_public",
        "min_power_kw=7",
        "max_power_kw=22",
    ])
    assert parsed["release_tag"] == "fixture"
    assert parsed["venue_filter"] == "workplace_public"
    assert parsed["min_power_kw"] == pytest.approx(7.0)
    assert parsed["max_power_kw"] == pytest.approx(22.0)
