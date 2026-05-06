"""TMYx weather fetch + cache behavior."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from v2b_syndata.load_pipeline.exceptions import WeatherStationNotFound
from v2b_syndata.load_pipeline.weather import (
    _build_url,
    _parse_station,
    get_weather_epw,
)


def test_amy_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="AMY"):
        get_weather_epw("USA_TN_Nashville.Intl.AP.723270_TMYx", weather_type="amy", weather_year=2020)


def test_unknown_weather_type_raises():
    with pytest.raises(ValueError, match="unknown weather_type"):
        get_weather_epw("X", weather_type="bogus")


def test_weather_year_with_tmyx_rejected():
    with pytest.raises(ValueError, match="weather_year"):
        get_weather_epw("USA_TN_Nashville.Intl.AP.723270_TMYx", weather_year=2020)


def test_parse_station_pattern():
    assert _parse_station("USA_TN_Nashville.Intl.AP.723270_TMYx") == (
        "TN",
        "USA_TN_Nashville.Intl.AP.723270_TMYx",
    )


def test_parse_station_invalid():
    with pytest.raises(ValueError, match="does not match"):
        _parse_station("Random_Junk_TMYx")


def test_url_pattern():
    url = _build_url("USA_TN_Nashville.Intl.AP.723270_TMYx")
    assert url.endswith("/TN_Tennessee/USA_TN_Nashville.Intl.AP.723270_TMYx.zip")
    assert "WMO_Region_4" in url


def test_fetch_uses_local_cache(tmp_path, monkeypatch):
    """If the cache hit exists, no fetch is attempted."""
    monkeypatch.setenv("V2B_WEATHER_CACHE", str(tmp_path))
    cached = tmp_path / "USA_TN_Nashville.Intl.AP.723270_TMYx.epw"
    cached.write_text("MOCK EPW")

    def _fail(_url):
        raise AssertionError("fetcher should not be called when cache hit")

    out = get_weather_epw("USA_TN_Nashville.Intl.AP.723270_TMYx", fetcher=_fail)
    assert out == cached
    assert out.read_text() == "MOCK EPW"


def test_fetch_writes_epw(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_WEATHER_CACHE", str(tmp_path))
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("station.epw", "EPW BODY")
        zf.writestr("station.stat", "STAT BODY")

    out = get_weather_epw(
        "USA_TN_Nashville.Intl.AP.723270_TMYx",
        fetcher=lambda _url: payload.getvalue(),
    )
    assert out.exists()
    assert out.read_text() == "EPW BODY"
    assert out.parent == Path(str(tmp_path))


def test_fetch_failure_raises_weather_station_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_WEATHER_CACHE", str(tmp_path))

    def _fail(_url):
        raise RuntimeError("network down")

    with pytest.raises(WeatherStationNotFound):
        get_weather_epw(
            "USA_TN_Nashville.Intl.AP.723270_TMYx", fetcher=_fail
        )
