"""Tests for tools/validate_buildingload.py.

Most tests use synthetic reference fixtures (no live downloads, no EnergyPlus).
The single end-to-end test that needs a real EnergyPlus run is marked
``@pytest.mark.real_energyplus`` and skips if the binary / reference data is
absent.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_buildingload", REPO / "tools" / "validate_buildingload.py"
)
vbl = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
# Register before exec so dataclasses can resolve the module's __dict__ under
# ``from __future__ import annotations``.
sys.modules["validate_buildingload"] = vbl
_SPEC.loader.exec_module(vbl)


# ──────────────────────────────────────────────────────────────────────
# Pure metric maths
# ──────────────────────────────────────────────────────────────────────

def test_cv_rmse_zero_for_identical():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert vbl.cv_rmse(x, x) == pytest.approx(0.0)


def test_cv_rmse_known_value():
    # measured mean = 2.0; predicted off by +1 everywhere => RMSE = 1.0
    measured = np.array([1.0, 2.0, 3.0])
    predicted = measured + 1.0
    # mean(measured) = 2.0, RMSE = 1.0 => CV(RMSE) = 50%
    assert vbl.cv_rmse(measured, predicted) == pytest.approx(50.0)


def test_nmbe_sign_and_zero():
    measured = np.array([10.0, 10.0, 10.0])
    assert vbl.nmbe(measured, measured) == pytest.approx(0.0)
    # predicted under-predicts by 1 => positive NMBE (measured - predicted > 0)
    assert vbl.nmbe(measured, measured - 1.0) == pytest.approx(10.0)
    # predicted over-predicts => negative NMBE
    assert vbl.nmbe(measured, measured + 1.0) == pytest.approx(-10.0)


def test_cv_rmse_shape_mismatch_raises():
    with pytest.raises(ValueError):
        vbl.cv_rmse(np.array([1.0, 2.0]), np.array([1.0]))


def test_shape_correlation_perfect_and_anti():
    a = np.sin(np.linspace(0, 2 * np.pi, 24))
    assert vbl.shape_correlation(a, a) == pytest.approx(1.0)
    assert vbl.shape_correlation(a, -a) == pytest.approx(-1.0)


def test_peak_hour_error_wraps():
    s1 = np.zeros(24); s1[2] = 1.0
    s2 = np.zeros(24); s2[5] = 1.0
    assert vbl.peak_hour_error(s1, s2) == 3
    # wrap-around: hour 1 vs hour 23 => 2 apart, not 22
    s3 = np.zeros(24); s3[1] = 1.0
    s4 = np.zeros(24); s4[23] = 1.0
    assert vbl.peak_hour_error(s3, s4) == 2


def test_load_factor_constant_is_one():
    assert vbl.load_factor(np.array([5.0, 5.0, 5.0])) == pytest.approx(1.0)
    assert vbl.load_factor(np.array([0.0, 10.0])) == pytest.approx(0.5)


def test_normalized_weekday_shape_excludes_weekend_and_peaks_at_one():
    idx = pd.date_range("2018-01-01", "2018-01-15", freq="1h", inclusive="left")
    # office-like: high midday, zero at night
    hour = idx.hour
    vals = np.where((hour >= 8) & (hour <= 17), 100.0, 5.0).astype(float)
    s = pd.Series(vals, index=idx)
    wd = vbl.normalized_weekday_shape(s)
    assert wd.shape == (24,)
    assert wd.max() == pytest.approx(1.0)
    # peak hour should be within the working window
    assert 8 <= int(np.argmax(wd)) <= 17


# ──────────────────────────────────────────────────────────────────────
# compute_metrics end-to-end (synthetic series, calendar-aligned)
# ──────────────────────────────────────────────────────────────────────

def _synthetic_office(year: int, *, scale: float = 1.0, noise: float = 0.0,
                      seed: int = 0) -> pd.Series:
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="1h", inclusive="left")
    hour = idx.hour
    weekday = idx.dayofweek < 5
    base = np.where((hour >= 8) & (hour <= 18), 100.0, 10.0).astype(float)
    base = np.where(weekday, base, base * 0.3)
    rng = np.random.default_rng(seed)
    base = base * scale * (1.0 + noise * rng.standard_normal(len(idx)))
    return pd.Series(np.clip(base, 0, None), index=idx)


def test_compute_metrics_identical_series_passes():
    gen = _synthetic_office(2018)
    ref = _synthetic_office(2018)
    m = vbl.compute_metrics(gen, ref, archetype="office", size="med", climate_zone="5B")
    assert m.cv_rmse_pct == pytest.approx(0.0, abs=1e-6)
    assert m.nmbe_pct == pytest.approx(0.0, abs=1e-6)
    assert m.shape_corr_weekday == pytest.approx(1.0, abs=1e-6)
    assert m.peak_hour_err_h == 0
    assert m.passes()


def test_compute_metrics_aligns_across_years():
    # Different reference year must still overlay on (month,day,hour).
    gen = _synthetic_office(2020)
    ref = _synthetic_office(2018)
    m = vbl.compute_metrics(gen, ref, archetype="office", size="med", climate_zone="5B")
    # shapes are identical hour-of-day so correlation must be ~1 and CVRMSE small
    assert m.shape_corr_weekday > 0.99
    assert m.n_hours > 8000  # most of the year overlaps


def test_compute_metrics_biased_generator_fails_nmbe():
    ref = _synthetic_office(2018)
    gen = _synthetic_office(2018, scale=0.5)  # generator at half magnitude
    m = vbl.compute_metrics(gen, ref, archetype="office", size="med", climate_zone="5B")
    assert m.nmbe_pct > 10.0  # under-predicts badly
    assert not m.nmbe_pass


# ──────────────────────────────────────────────────────────────────────
# Reference parquet loading
# ──────────────────────────────────────────────────────────────────────

def _write_fixture_parquet(tmp_path: Path) -> Path:
    """Build a tiny ComStock-like reference parquet."""
    rows = []
    idx = pd.date_range("2018-01-01 00:15", "2018-01-08 00:00", freq="15min")
    for (arch, size) in [("office", "med"), ("retail", "large")]:
        hour = idx.hour
        total = np.where((hour >= 8) & (hour <= 18), 80.0, 12.0).astype(float)
        for t, v in zip(idx, total):
            rows.append({
                "source": "comstock", "archetype": arch, "size": size,
                "climate_zone": "5B", "building_id": "",
                "timestamp": t, "flex_kw": v * 0.4, "inflex_kw": v * 0.6,
                "total_kw": v, "floor_area_m2": 5000.0,
            })
    df = pd.DataFrame(rows)
    rd = tmp_path / "buildingload_reference"
    rd.mkdir()
    df.to_parquet(rd / "comstock_timeseries.parquet")
    return rd


def test_load_reference_hourly_reads_cell(tmp_path):
    rd = _write_fixture_parquet(tmp_path)
    s = vbl.load_reference_hourly("office", "med", "5B", reference_dir=rd)
    assert isinstance(s, pd.Series)
    assert len(s) > 100
    assert s.max() == pytest.approx(80.0, rel=0.01)


def test_load_reference_missing_parquet_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        vbl.load_reference_hourly("office", "med", "5B", reference_dir=tmp_path)


def test_load_reference_missing_cell_raises(tmp_path):
    rd = _write_fixture_parquet(tmp_path)
    with pytest.raises(KeyError):
        vbl.load_reference_hourly("office", "small", "5B", reference_dir=rd)


# ──────────────────────────────────────────────────────────────────────
# validate_all orchestration with a stubbed generator (no EnergyPlus)
# ──────────────────────────────────────────────────────────────────────

def test_validate_all_with_stubbed_generator(tmp_path, monkeypatch):
    rd = _write_fixture_parquet(tmp_path)

    def fake_gen(archetype, size, **kw):
        # mirror the fixture's office/med shape so it passes
        idx = pd.date_range("2018-01-01", "2018-01-08", freq="15min", inclusive="left")
        hour = idx.hour
        total = np.where((hour >= 8) & (hour <= 18), 80.0, 12.0).astype(float)
        return pd.Series(total, index=idx, name="total_kw")

    monkeypatch.setattr(vbl, "generate_generator_load", fake_gen)
    results = vbl.validate_all(
        reference_dir=rd,
        prototypes=[("office", "med", "med"), ("retail", "large", "large")],
    )
    assert len(results) == 2
    for m in results:
        assert m.cv_rmse_pct < 30.0
        assert abs(m.nmbe_pct) < 10.0
        assert m.passes()
    table = vbl.format_table(results)
    assert "CVRMSE%" in table
    assert "2/2 archetypes pass" in table


def test_validate_all_skips_missing_reference(tmp_path, monkeypatch):
    rd = _write_fixture_parquet(tmp_path)
    monkeypatch.setattr(vbl, "generate_generator_load",
                        lambda *a, **k: pytest.fail("should not generate"))
    # office/small is absent from the fixture => skipped, no generation attempted
    results = vbl.validate_all(
        reference_dir=rd, prototypes=[("office", "small", "small")],
    )
    assert results == []


# ──────────────────────────────────────────────────────────────────────
# Real EnergyPlus end-to-end (heavy; opt-in)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.real_energyplus
def test_generate_generator_load_real_ep():
    if shutil.which("energyplus") is None and not Path("/usr/local/bin/energyplus").exists():
        pytest.skip("EnergyPlus binary not available")
    # Short 8-day window to keep it cheap.
    s = vbl.generate_generator_load(
        "office", "small",
        sim_start="2018-07-01", sim_end="2018-07-09",
    )
    assert isinstance(s, pd.Series)
    assert len(s) > 0
    assert float(s.max()) > 0.0
    # small office peak should be physically plausible (a few kW .. ~100 kW)
    assert 1.0 < float(s.max()) < 500.0
