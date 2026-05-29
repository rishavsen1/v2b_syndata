"""Unit tests for ElaadNL Open Charging Transactions fetcher + extractor (fixture-driven)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from v2b_syndata.calibration.elaadnl_fetcher import fetch_all_sessions
from v2b_syndata.calibration.feature_extractor import aggregate_user_features
from v2b_syndata.calibration.sources.elaadnl import (
    ElaadNLSource,
    _extract_session_elaadnl,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "elaadnl_fixture.csv"


def _stage_fixture(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "elaadnl_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_PATH, cache_dir / "elaadnl_fixture.csv")
    return cache_dir


def test_fetch_uses_cache(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    assert isinstance(rows, list)
    assert len(rows) == 75
    venues = {r["venue"] for r in rows}
    assert venues == {"public", "semi_public", "fastcharge"}


def test_extract_basic(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    rows = fetch_all_sessions("fixture", cache_dir)
    sf = _extract_session_elaadnl(rows[0], None, None, None)
    assert sf is not None
    assert sf.user_id.startswith("elaadnl:card:")
    assert sf.dwell_hours > 0
    assert sf.kwh_delivered > 0


def test_venue_filter_public(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = ElaadNLSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "public",
    })
    sites = {s.site for s in sessions}
    assert "fastcharge" not in sites
    assert "public" in sites
    assert "semi_public" in sites


def test_aggregate_user_features_runs(tmp_path):
    cache_dir = _stage_fixture(tmp_path)
    src = ElaadNLSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "public",
    })
    assert sessions
    arrivals = [s.arrival_time for s in sessions]
    users = aggregate_user_features(sessions, min(arrivals), max(arrivals))
    assert users, "no users aggregated — check fixture active window"
    for u in users:
        assert 0.0 <= u.phi <= 1.0
        assert 0.0 <= u.kappa <= 1.0


def test_provenance_format():
    src = ElaadNLSource()
    prov = src.provenance_prefix({"archive_tag": "fixture"})
    today = dt.date.today().isoformat().replace("-", "")
    assert prov.startswith("calibration:elaadnl_open_2020_fixture_")
    assert prov.endswith(today)


def test_extra_metadata_user_id_strategy():
    src = ElaadNLSource()
    meta = src.extra_metadata({"archive_tag": "fixture", "venue_filter": "public"})
    assert meta["user_id_strategy"] == "card_proxy"
    assert meta["archive_tag"] == "fixture"
    assert meta["venue_filter"] == "public"
    assert meta["dataset_release"] == "open_2020"
    assert meta["geography"] == "NL_EU"
    assert meta["schema_version"]


def test_token_help_message_mentions_env_var():
    msg = ElaadNLSource().token_help_message()
    assert "ELAADNL_BULK_URL" in msg


def test_missing_url_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ELAADNL_BULK_URL", raising=False)
    monkeypatch.delenv("ELAADNL_API_TOKEN", raising=False)
    cache_dir = tmp_path / "empty_cache"
    cache_dir.mkdir()
    with pytest.raises(RuntimeError) as exc:
        fetch_all_sessions("nope", cache_dir)
    assert "ELAADNL_BULK_URL" in str(exc.value)


def test_card_fallback_to_port_proxy(tmp_path):
    """Row with missing card_id falls back to elaadnl:port:<evse> user_id."""
    row_missing_card = {
        "card_id": "",
        "evse_id": "EVSE_P99",
        "venue": "public",
        "evse_power_kw": 11.0,
        "start_time": "2020-02-21T20:00:00",
        "end_time": "2020-02-22T07:00:00",
        "energy_kwh": 38.5,
    }
    sf = _extract_session_elaadnl(row_missing_card, "public", None, None)
    assert sf is not None
    assert sf.user_id == "elaadnl:port:EVSE_P99"

    # Fixture includes one row with missing card_id; source-level
    # extra_metadata stays card_proxy because that single row doesn't
    # dominate the 74-session card cohort.
    cache_dir = _stage_fixture(tmp_path)
    src = ElaadNLSource()
    sessions = src.fetch_sessions({
        "archive_tag": "fixture",
        "cache_dir": cache_dir,
        "venue_filter": "public",
    })
    assert any(s.user_id.startswith("elaadnl:port:") for s in sessions)
    assert any(s.user_id.startswith("elaadnl:card:") for s in sessions)
    meta = src.extra_metadata({"archive_tag": "fixture", "venue_filter": "public"})
    assert meta["user_id_strategy"] == "card_proxy"

    # When the cohort is dominated by port-proxy rows, the source flips.
    src2 = ElaadNLSource()
    for _ in range(3):
        src2._n_port += 1  # simulate dominant fallback
    src2._n_card += 1
    meta2 = src2.extra_metadata({"archive_tag": "fixture"})
    assert meta2["user_id_strategy"] == "port_proxy"


def test_parse_args_typed():
    src = ElaadNLSource()
    parsed = src.parse_args([
        "archive_tag=open_2020",
        "venue_filter=public",
        "min_power_kw=3",
        "max_power_kw=150",
    ])
    assert parsed["archive_tag"] == "open_2020"
    assert parsed["venue_filter"] == "public"
    assert parsed["min_power_kw"] == pytest.approx(3.0)
    assert parsed["max_power_kw"] == pytest.approx(150.0)
