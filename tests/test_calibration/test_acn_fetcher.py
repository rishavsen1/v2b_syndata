"""Mocked HTTP tests for acn_fetcher. No network access."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

from v2b_syndata.calibration.acn_fetcher import (
    fetch_all_sessions,
    filter_with_userid,
)


def _mock_response(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        r.raise_for_status.return_value = None
    return r


def test_pagination_across_multiple_pages(tmp_path):
    page1 = {"_items": [{"userID": 1, "_id": "a"}, {"userID": 2, "_id": "b"}],
             "_links": {"next": "/api/v1/sessions/caltech?page=2"}}
    page2 = {"_items": [{"userID": 3, "_id": "c"}],
             "_links": {"next": "/api/v1/sessions/caltech?page=3"}}
    page3 = {"_items": [], "_links": {}}

    with patch("v2b_syndata.calibration.acn_fetcher.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(page1),
            _mock_response(page2),
            _mock_response(page3),
        ]
        out = fetch_all_sessions(
            "caltech", 2019, 2021, cache_dir=tmp_path,
            token="fake_token",
        )
        assert len(out) == 3
        assert {s["userID"] for s in out} == {1, 2, 3}
        assert mock_get.call_count == 3


def test_cache_hit_skips_http_call(tmp_path):
    cache_path = tmp_path / "caltech_2019_2021.json"
    cached_payload = [{"userID": 99, "_id": "cached"}]
    cache_path.write_text(json.dumps(cached_payload))

    with patch("v2b_syndata.calibration.acn_fetcher.requests.get") as mock_get:
        out = fetch_all_sessions(
            "caltech", 2019, 2021, cache_dir=tmp_path,
            token="should_not_be_used",
        )
        assert mock_get.call_count == 0
        assert out == cached_payload


def test_auth_failure_raises(tmp_path):
    with patch("v2b_syndata.calibration.acn_fetcher.requests.get") as mock_get:
        mock_get.return_value = _mock_response({"error": "unauthorized"}, status=401)
        with pytest.raises(requests.HTTPError):
            fetch_all_sessions(
                "caltech", 2019, 2021, cache_dir=tmp_path, token="bad",
            )


def test_writes_cache_after_fetch(tmp_path):
    payload = {"_items": [{"userID": 7, "_id": "z"}], "_links": {}}
    with patch("v2b_syndata.calibration.acn_fetcher.requests.get") as mock_get:
        mock_get.return_value = _mock_response(payload)
        out = fetch_all_sessions(
            "jpl", 2019, 2021, cache_dir=tmp_path, token="fake",
        )
    cache_file = tmp_path / "jpl_2019_2021.json"
    assert cache_file.exists()
    assert json.loads(cache_file.read_text()) == out


def test_no_cache_dir_skips_persistence(tmp_path):
    payload = {"_items": [{"userID": 1, "_id": "a"}], "_links": {}}
    with patch("v2b_syndata.calibration.acn_fetcher.requests.get") as mock_get:
        mock_get.return_value = _mock_response(payload)
        out = fetch_all_sessions("jpl", 2019, 2021, cache_dir=None, token="t")
    assert len(out) == 1
    assert not list(tmp_path.iterdir())


def test_filter_with_userid_drops_null():
    sessions = [
        {"userID": 1},
        {"userID": None},
        {"userID": "abc"},
        {},
    ]
    out = filter_with_userid(sessions)
    assert len(out) == 2
    assert all(s.get("userID") is not None for s in out)


def test_filter_with_userid_empty():
    assert filter_with_userid([]) == []
