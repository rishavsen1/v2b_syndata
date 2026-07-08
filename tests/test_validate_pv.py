"""Tests for tools/validate_pv.py (WS-B PV validation harness).

Metric-math tests use synthetic series (no PySAM, no EPW). The end-to-end
comparison against PySAM Pvwattsv8 skips when PySAM or the cached San Jose
EPW is unavailable, so the default suite stays network-free.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_pv", REPO / "tools" / "validate_pv.py"
)
vpv = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
# Register before exec so dataclasses can resolve the module's __dict__ under
# ``from __future__ import annotations``.
sys.modules["validate_pv"] = vpv
_SPEC.loader.exec_module(vpv)

_EPW = REPO / "data" / "stations" / f"{vpv.DEFAULT_STATION}.epw"
_HAS_PYSAM = importlib.util.find_spec("PySAM") is not None


def _bell(idx: pd.DatetimeIndex, peak_kw: float = 80.0) -> pd.Series:
    """Synthetic clear-sky-ish diurnal bell on an hourly index."""
    h = idx.hour.to_numpy().astype(float)
    p = peak_kw * np.maximum(0.0, np.sin((h - 6.0) / 12.0 * np.pi))
    return pd.Series(p, index=idx)


# ──────────────────────────────────────────────────────────────────────
# Pure metric maths
# ──────────────────────────────────────────────────────────────────────

def test_metrics_identical_series_are_zero_error():
    idx = pd.date_range("2021-01-01", periods=24 * 30, freq="1h")
    s = _bell(idx)
    m = vpv.compute_metrics(s, s.copy())
    assert m.annual_err_pct == pytest.approx(0.0)
    assert m.cvrmse_pct == pytest.approx(0.0)
    assert m.nmbe_pct == pytest.approx(0.0)
    assert m.best_lag_h == 0
    assert m.r_hourly == pytest.approx(1.0)


def test_metrics_known_bias():
    # ours = 1.1 × ref everywhere → annual error +10%, NMBE +10%, CV(RMSE) ~ 10·CV shape
    idx = pd.date_range("2021-01-01", periods=24 * 30, freq="1h")
    ref = _bell(idx)
    m = vpv.compute_metrics(ref * 1.1, ref)
    assert m.annual_err_pct == pytest.approx(10.0)
    assert m.nmbe_pct == pytest.approx(10.0)
    assert m.nmbe_day_pct == pytest.approx(10.0)
    # RMSE = 0.1·sqrt(mean(ref²)); CV(RMSE) = RMSE/mean(ref)
    expected_cv = 10.0 * float(np.sqrt((ref**2).mean()) / ref.mean())
    assert m.cvrmse_pct == pytest.approx(expected_cv)


def test_lag_scan_detects_shift():
    idx = pd.date_range("2021-01-01", periods=24 * 30, freq="1h")
    ref = _bell(idx)
    shifted = ref.shift(2).fillna(0.0)  # ours lags ref by 2h
    best, corrs = vpv.lag_scan(shifted, ref)
    assert best == 2
    assert corrs[2] > corrs[0]


def test_metrics_monthly_table_shape():
    idx = pd.date_range("2021-01-01", periods=24 * 365, freq="1h")
    ref = _bell(idx)
    m = vpv.compute_metrics(ref * 1.02, ref)
    assert list(m.monthly.index) == list(range(1, 13))
    assert set(m.monthly.columns) == {"ours_kwh", "ref_kwh", "err_pct"}
    assert m.monthly["err_pct"].to_numpy() == pytest.approx(np.full(12, 2.0))


def test_metrics_length_mismatch_raises():
    idx = pd.date_range("2021-01-01", periods=48, freq="1h")
    with pytest.raises(ValueError, match="length mismatch"):
        vpv.compute_metrics(_bell(idx), _bell(idx[:24]))


# ──────────────────────────────────────────────────────────────────────
# End-to-end vs PySAM (skips without PySAM or the cached EPW)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_PYSAM, reason="PySAM not installed")
@pytest.mark.skipif(not _EPW.exists(), reason="San Jose TMYx EPW not cached")
def test_end_to_end_gate(tmp_path):
    rc = vpv.main([
        "--strict",
        "--out-md", str(tmp_path / "pv_validation.md"),
        "--out-csv", str(tmp_path / "pv_validation_hourly.csv"),
    ])
    assert rc == 0  # <5% annual gate passes
    md = (tmp_path / "pv_validation.md").read_text()
    assert "**PASS**" in md
    pair = pd.read_csv(tmp_path / "pv_validation_hourly.csv", index_col=0)
    assert len(pair) == 8760
    assert {"ours_kw", "sam_primary_kw", "sam_equalized_kw"} <= set(pair.columns)
