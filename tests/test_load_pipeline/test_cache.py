"""Cache key stability + parquet round-trip."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.load_pipeline.cache import cache_key, get_cached, put_cached


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("V2B_LOAD_CACHE_DIR", str(tmp_path))


def _two_files(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.idf"
    b = tmp_path / "b.epw"
    a.write_text("idf content")
    b.write_text("epw content")
    return a, b


def _series() -> pd.Series:
    idx = pd.date_range("2020-04-01", periods=96, freq="15min")
    return pd.Series([0.5] * 96, index=idx, name="occupancy")


def test_cache_key_stable_for_same_inputs(tmp_path):
    idf, epw = _two_files(tmp_path)
    s = _series()
    k1 = cache_key(idf, epw, s, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    k2 = cache_key(idf, epw, s, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    assert k1 == k2


def test_cache_key_differs_for_changed_idf(tmp_path):
    idf, epw = _two_files(tmp_path)
    s = _series()
    k1 = cache_key(idf, epw, s, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    idf.write_text("idf content modified")
    k2 = cache_key(idf, epw, s, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    assert k1 != k2


def test_cache_key_differs_for_changed_occupancy(tmp_path):
    idf, epw = _two_files(tmp_path)
    s = _series()
    k1 = cache_key(idf, epw, s, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    s2 = s.copy()
    s2.iloc[0] = 0.0
    k2 = cache_key(idf, epw, s2, pd.Timestamp("2020-04-01"), pd.Timestamp("2020-04-02"))
    assert k1 != k2


def test_cache_roundtrip():
    idx = pd.date_range("2020-04-01", periods=96, freq="15min")
    flex = pd.Series([1.0 * i for i in range(96)], index=idx, name="L_flex")
    inflex = pd.Series([0.5 * i for i in range(96)], index=idx, name="L_inflex")

    assert get_cached("nope") is None
    put_cached("test_key", flex, inflex)
    out = get_cached("test_key")
    assert out is not None
    out_flex, out_inflex = out
    pd.testing.assert_series_equal(flex, out_flex, check_names=False, check_freq=False)
    pd.testing.assert_series_equal(inflex, out_inflex, check_names=False, check_freq=False)
