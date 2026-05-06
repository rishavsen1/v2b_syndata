"""Orchestration smoke tests for calibrate_populations()."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest


def _make_small_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    rng_uid = 0
    for site in ("caltech", "jpl", "office001"):
        sessions = []
        for _ in range(6):
            rng_uid += 1
            for d in range(10):
                base = pd.Timestamp("2020-01-06", tz="UTC") + pd.Timedelta(days=d * 7)
                arr = base + pd.Timedelta(hours=9.0 + (rng_uid % 3) * 0.2)
                dep = arr + pd.Timedelta(hours=8.0)
                fmt = "%a, %d %b %Y %H:%M:%S GMT"
                miles = 25 + (rng_uid % 6) * 5
                wpm = 240 + (rng_uid % 5) * 8
                sessions.append({
                    "userID": rng_uid,
                    "connectionTime": arr.strftime(fmt),
                    "disconnectTime": dep.strftime(fmt),
                    "kWhDelivered": 10.0,
                    "userInputs": [{
                        "milesRequested": miles, "WhPerMile": wpm,
                        "kWhRequested": miles * wpm / 1000.0,
                        "minutesAvailable": 480,
                    }],
                })
        (cache_dir / f"{site}_2019_2021.json").write_text(json.dumps(sessions))


def _empty_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for site in ("caltech", "jpl", "office001"):
        (cache_dir / f"{site}_2019_2021.json").write_text(json.dumps([]))


@pytest.fixture
def tmp_pops(tmp_path):
    src = Path(__file__).resolve().parents[2] / "configs" / "populations.yaml"
    dst = tmp_path / "populations.yaml"
    shutil.copy(src, dst)
    return dst


def test_summary_dict_keys(tmp_pops, tmp_path, monkeypatch):
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _make_small_cache(cache)
    from v2b_syndata.calibration import calibrate_populations
    summary = calibrate_populations(
        populations_yaml_path=tmp_pops,
        population_names=["consent_default"],
        cache_dir=cache, artifact_dir=tmp_path / "art",
        year_start=2019, year_end=2021, write_yaml=False,
    )
    expected = {"n_users_total", "n_sessions_total",
                "capacity_inference_fallback_rate", "provenance",
                "populations"}
    assert expected.issubset(summary.keys())
    assert "consent_default" in summary["populations"]
    pop_sum = summary["populations"]["consent_default"]
    assert "regions" in pop_sum
    assert "unassigned_user_rate" in pop_sum
    assert "metadata" in pop_sum


def test_zero_sessions_year_window_raises(tmp_pops, tmp_path, monkeypatch):
    """Empty cache → calibrate raises a helpful runtime error."""
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _empty_cache(cache)
    from v2b_syndata.calibration import calibrate_populations
    with pytest.raises(RuntimeError, match="no sessions extracted"):
        calibrate_populations(
            populations_yaml_path=tmp_pops,
            population_names=["consent_default"],
            cache_dir=cache, artifact_dir=tmp_path / "art",
            year_start=2019, year_end=2021, write_yaml=False,
        )


def test_default_population_names_inferred_from_yaml(tmp_pops, tmp_path, monkeypatch):
    """population_names=None calibrates every population with axes_distribution."""
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _make_small_cache(cache)
    from v2b_syndata.calibration import calibrate_populations
    summary = calibrate_populations(
        populations_yaml_path=tmp_pops,
        population_names=None,  # all
        cache_dir=cache, artifact_dir=tmp_path / "art",
        year_start=2019, year_end=2021, write_yaml=False,
    )
    # populations.yaml has at least: consent_default, stable_commuter_heavy,
    # occasional_visitor_dominant
    assert len(summary["populations"]) >= 1
    assert "consent_default" in summary["populations"]


def test_artifact_csv_written(tmp_pops, tmp_path, monkeypatch):
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _make_small_cache(cache)
    art = tmp_path / "art"
    from v2b_syndata.calibration import calibrate_populations
    calibrate_populations(
        populations_yaml_path=tmp_pops,
        population_names=["consent_default"],
        cache_dir=cache, artifact_dir=art,
        year_start=2019, year_end=2021, write_yaml=False,
    )
    assert (art / "acn_per_user.csv").exists()
    df = pd.read_csv(art / "acn_per_user.csv")
    expected = {"user_id", "n_sessions", "phi", "kappa", "delta_km"}
    assert expected.issubset(df.columns)


def test_provenance_format(tmp_pops, tmp_path, monkeypatch):
    import re
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _make_small_cache(cache)
    from v2b_syndata.calibration import calibrate_populations
    summary = calibrate_populations(
        populations_yaml_path=tmp_pops,
        population_names=["consent_default"],
        cache_dir=cache, artifact_dir=tmp_path / "art",
        year_start=2019, year_end=2021, write_yaml=False,
    )
    assert re.match(r"^calibration:acn_data_2019_2021_\d{8}$", summary["provenance"])
