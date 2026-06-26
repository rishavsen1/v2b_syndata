"""End-to-end calibration test using a synthetic ACN-Data fixture.

No ACN_API_TOKEN required — fixture is generated programmatically with
realistic structure (RFC 1123 dates, userInputs blocks).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml as pyyaml


def _make_fake_acn_session(uid: int, day_offset: int, arr_hour: float,
                           dwell_hours: float, miles: float, wpm: int,
                           kwh_req: float) -> dict:
    """Build one raw ACN-style session dict."""
    base = pd.Timestamp("2020-01-06", tz="UTC") + pd.Timedelta(days=day_offset)
    arr = base + pd.Timedelta(hours=arr_hour)
    dep = arr + pd.Timedelta(hours=dwell_hours)
    fmt = "%a, %d %b %Y %H:%M:%S GMT"
    return {
        "userID": uid,
        "connectionTime": arr.strftime(fmt),
        "disconnectTime": dep.strftime(fmt),
        "kWhDelivered": kwh_req * 0.95,  # delivered ~ requested
        "userInputs": [
            {
                "milesRequested": miles,
                "WhPerMile": wpm,
                "kWhRequested": kwh_req,
                "minutesAvailable": int(dwell_hours * 60),
            }
        ],
    }


def _build_synthetic_fixture(cache_dir: Path,
                             sites=("caltech", "jpl", "office001"),
                             year_start=2019, year_end=2021,
                             n_users_per_site=10, sessions_per_user=15) -> None:
    """Write per-site cached JSON files mimicking what fetch_all_sessions returns."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    rng_uid = 0
    for site in sites:
        sessions: list[dict] = []
        for _ in range(n_users_per_site):
            rng_uid += 1
            for d in range(sessions_per_user):
                day_offset = d * 7  # weekly
                arr_hour = 8.5 + (rng_uid % 3) * 0.3 + (d % 5) * 0.05
                dwell = 8.0 + (rng_uid % 5) * 0.3
                miles = 30.0 + (rng_uid % 10) * 5
                wpm = 250 + (rng_uid % 4) * 10
                kwh_req = miles * wpm / 1000.0
                sessions.append(_make_fake_acn_session(
                    rng_uid, day_offset, arr_hour, dwell, miles, wpm, kwh_req,
                ))
        path = cache_dir / f"{site}_{year_start}_{year_end}.json"
        path.write_text(json.dumps(sessions))


@pytest.fixture
def populated_cache(tmp_path: Path, monkeypatch) -> Path:
    """Synthetic ACN cache + a copy of populations.yaml in tmp.

    NOTE: also sets a dummy ACN_API_TOKEN — workaround for B1 bug
    (acn_fetcher reads token at function entry even when cache hits).
    See docs/archive/AUDIT_REPORT.md.
    """
    monkeypatch.setenv("ACN_API_TOKEN", "dummy_for_cache_only")
    cache = tmp_path / "acn_cache"
    _build_synthetic_fixture(cache)
    return cache


@pytest.fixture
def tmp_populations_yaml(tmp_path: Path) -> Path:
    """Copy of repo populations.yaml into tmp so we can modify safely."""
    src = Path(__file__).resolve().parents[2] / "configs" / "populations.yaml"
    dst = tmp_path / "populations.yaml"
    shutil.copy(src, dst)
    return dst


def test_e2e_calibration_pipeline(populated_cache, tmp_populations_yaml, tmp_path):
    from v2b_syndata.calibration import calibrate_populations

    summary = calibrate_populations(
        populations_yaml_path=tmp_populations_yaml,
        population_names=["acn_workplace_baseline"],
        sites=("caltech", "jpl", "office001"),
        year_start=2019,
        year_end=2021,
        cache_dir=populated_cache,
        artifact_dir=tmp_path / "artifacts",
        write_yaml=True,
    )

    assert summary["n_users_total"] > 0
    assert summary["n_sessions_total"] > 0
    assert "acn_workplace_baseline" in summary["populations"]
    assert summary["provenance"].startswith("calibration:acn_data_2019_2021_")

    # Verify populations.yaml got the new blocks
    data = pyyaml.safe_load(tmp_populations_yaml.read_text())
    pop = data["acn_workplace_baseline"]
    assert "region_distributions" in pop
    assert "calibration_metadata" in pop
    assert pop["calibration_metadata"]["source"].startswith("calibration:acn_data_")

    # KS values present and finite for any region that fit
    for region, dists in pop["region_distributions"].items():
        for dname, dvals in dists.items():
            if dname == "copula":
                continue
            if "ks_fit_quality" in dvals:
                assert 0.0 <= dvals["ks_fit_quality"] <= 1.0


def test_e2e_calibration_writeback_preserves_region_bounds_and_other_blocks(
    populated_cache, tmp_populations_yaml, tmp_path,
):
    """Calibration rewrites axes_distribution *weights* from empirical user share
    but must preserve region identity + bounds (freq/consist/dist_km), keep the
    vector normalized to 1.0, and leave negotiation / fleet byte-equivalent."""
    from v2b_syndata.calibration import calibrate_populations

    before = pyyaml.safe_load(tmp_populations_yaml.read_text())
    pre = before["acn_workplace_baseline"]
    pre_axes = list(pre["axes_distribution"])
    pre_neg = dict(pre["negotiation"])
    pre_fleet = dict(pre["fleet"])

    calibrate_populations(
        populations_yaml_path=tmp_populations_yaml,
        population_names=["acn_workplace_baseline"],
        sites=("caltech", "jpl", "office001"),
        year_start=2019, year_end=2021,
        cache_dir=populated_cache,
        artifact_dir=tmp_path / "artifacts",
        write_yaml=True,
    )

    after = pyyaml.safe_load(tmp_populations_yaml.read_text())
    post = after["acn_workplace_baseline"]

    # Region identity + bounds preserved; only weights are recalibrated.
    assert [r["name"] for r in post["axes_distribution"]] == [r["name"] for r in pre_axes]
    for r_post, r_pre in zip(post["axes_distribution"], pre_axes, strict=True):
        assert r_post["freq"] == r_pre["freq"]
        assert r_post["consist"] == r_pre["consist"]
        assert r_post["dist_km"] == r_pre["dist_km"]
    assert abs(sum(r["weight"] for r in post["axes_distribution"]) - 1.0) < 1e-6
    # negotiation + fleet untouched by calibration.
    assert post["negotiation"] == pre_neg
    assert post["fleet"] == pre_fleet


def test_e2e_calibration_metadata_block_format(populated_cache, tmp_populations_yaml, tmp_path):
    from v2b_syndata.calibration import calibrate_populations
    import re

    calibrate_populations(
        populations_yaml_path=tmp_populations_yaml,
        population_names=["acn_workplace_baseline"],
        sites=("caltech", "jpl", "office001"),
        year_start=2019, year_end=2021,
        cache_dir=populated_cache,
        artifact_dir=tmp_path / "artifacts",
        write_yaml=True,
    )

    data = pyyaml.safe_load(tmp_populations_yaml.read_text())
    meta = data["acn_workplace_baseline"]["calibration_metadata"]
    src = meta["source"]
    assert re.match(r"^calibration:acn_data_\d{4}_\d{4}_\d{8}$", src), src
    assert meta["dataset"] == "ACN-Data"
    assert sorted(meta["sites"]) == ["caltech", "jpl", "office001"]
    assert meta["year_range"] == [2019, 2021]
    assert meta["n_users_total"] > 0
    assert meta["n_sessions_total"] > 0
    assert 0.0 <= meta["capacity_inference_fallback_rate"] <= 1.0


def test_e2e_calibration_handles_missing_token_with_cache(tmp_path, tmp_populations_yaml, monkeypatch):
    """B1 fix: cache hits bypass token resolution entirely."""
    monkeypatch.delenv("ACN_API_TOKEN", raising=False)
    cache = tmp_path / "acn_cache"
    _build_synthetic_fixture(cache)
    from v2b_syndata.calibration import calibrate_populations
    summary = calibrate_populations(
        populations_yaml_path=tmp_populations_yaml,
        population_names=["acn_workplace_baseline"],
        sites=("caltech", "jpl", "office001"),
        year_start=2019, year_end=2021,
        cache_dir=cache,
        artifact_dir=tmp_path / "artifacts",
        write_yaml=True,
    )
    assert summary["n_sessions_total"] > 0
