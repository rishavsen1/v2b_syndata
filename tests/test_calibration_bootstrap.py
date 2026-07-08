"""Tests for the seeded bootstrap CIs + S3 family-matched holdout refit in
tools/validate_calibration.py (KDD_READINESS #11 / tracker F3).

Pure-math tests: the vectorized KS/W1 kernel must agree with scipy exactly,
and the bootstrap must be bit-deterministic given the fixed seed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import scipy.stats as st

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "validate_calibration", REPO / "tools" / "validate_calibration.py"
)
vc = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules["validate_calibration"] = vc
_SPEC.loader.exec_module(vc)


# ──────────────────────────────────────────────────────────────────────
# Vectorized KS / W1 kernel vs scipy (exactness)
# ──────────────────────────────────────────────────────────────────────

def test_ks_w1_matches_scipy_continuous():
    rng = np.random.default_rng(7)
    gen = rng.normal(10.0, 3.0, size=1200)
    rows = rng.normal(9.5, 2.5, size=(5, 400))
    ks, w1 = vc.ks_w1_vs_fixed(rows, gen)
    for i in range(rows.shape[0]):
        ks_ref = st.ks_2samp(rows[i], gen).statistic
        w1_ref = st.wasserstein_distance(rows[i], gen)
        assert ks[i] == pytest.approx(ks_ref, abs=1e-12)
        assert w1[i] == pytest.approx(w1_ref, rel=1e-10)


def test_ks_w1_matches_scipy_with_ties():
    # Heavy ties on both sides (bootstrap resamples always contain ties).
    rng = np.random.default_rng(11)
    gen = rng.integers(0, 12, size=800).astype(float)
    rows = rng.integers(0, 12, size=(4, 300)).astype(float)
    ks, w1 = vc.ks_w1_vs_fixed(rows, gen)
    for i in range(rows.shape[0]):
        assert ks[i] == pytest.approx(st.ks_2samp(rows[i], gen).statistic, abs=1e-12)
        assert w1[i] == pytest.approx(st.wasserstein_distance(rows[i], gen), rel=1e-10)


def test_ks_w1_accepts_1d_row():
    rng = np.random.default_rng(3)
    src = rng.exponential(4.0, size=250)
    gen = rng.exponential(4.5, size=900)
    ks, w1 = vc.ks_w1_vs_fixed(src, gen)
    assert ks.shape == (1,) and w1.shape == (1,)
    assert ks[0] == pytest.approx(st.ks_2samp(src, gen).statistic, abs=1e-12)
    assert w1[0] == pytest.approx(st.wasserstein_distance(src, gen), rel=1e-10)


def test_identical_samples_zero():
    x = np.linspace(0.0, 24.0, 500)
    ks, w1 = vc.ks_w1_vs_fixed(x, x)
    assert ks[0] == pytest.approx(0.0, abs=1e-12)
    assert w1[0] == pytest.approx(0.0, abs=1e-12)


# ──────────────────────────────────────────────────────────────────────
# Bootstrap: determinism + CI sanity
# ──────────────────────────────────────────────────────────────────────

def _toy_samples() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    src = rng.normal(10.0, 3.0, size=600)
    gen = rng.normal(10.4, 2.8, size=2000)
    return src, gen


def test_bootstrap_deterministic_given_seed():
    src, gen = _toy_samples()
    a = vc.bootstrap_ks_w1(src, gen, 200, vc._cell_rng("acn", "r1", "arrival_hour"))
    b = vc.bootstrap_ks_w1(src, gen, 200, vc._cell_rng("acn", "r1", "arrival_hour"))
    assert a == b  # bitwise-identical floats, not approx


def test_cell_rng_is_order_independent_and_cell_specific():
    # Same cell key → identical stream regardless of construction order.
    r1 = vc._cell_rng("acn", "r1", "arrival_hour").integers(0, 1 << 30, 8)
    _ = vc._cell_rng("acn", "zzz", "dwell_hours")  # interleave another cell
    r2 = vc._cell_rng("acn", "r1", "arrival_hour").integers(0, 1 << 30, 8)
    assert np.array_equal(r1, r2)
    # Different cells → different streams.
    r3 = vc._cell_rng("acn", "r2", "arrival_hour").integers(0, 1 << 30, 8)
    assert not np.array_equal(r1, r3)


def test_bootstrap_chunk_size_does_not_change_result():
    src, gen = _toy_samples()
    a = vc.bootstrap_ks_w1(src, gen, 150,
                           vc._cell_rng("s", "r", "v"), chunk=7)
    b = vc.bootstrap_ks_w1(src, gen, 150,
                           vc._cell_rng("s", "r", "v"), chunk=1000)
    assert a == b


def test_bootstrap_ci_sanity():
    src, gen = _toy_samples()
    ci = vc.bootstrap_ks_w1(src, gen, 300, vc._cell_rng("s", "r", "v"))
    assert 0.0 <= ci["ks_ci_lo"] <= ci["ks_ci_hi"] <= 1.0
    assert 0.0 <= ci["w1_ci_lo"] <= ci["w1_ci_hi"]
    # The CI should sit in the neighbourhood of the point statistic.
    ks_point = st.ks_2samp(src, gen).statistic
    assert ci["ks_ci_lo"] <= ks_point * 2.0
    assert ci["ks_ci_hi"] >= ks_point * 0.5


# ──────────────────────────────────────────────────────────────────────
# S1 wiring: CI columns appear (and are absent when disabled)
# ──────────────────────────────────────────────────────────────────────

def _fake_frames(n_src: int = 400, n_gen: int = 800) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(5)
    src = pd.DataFrame({
        "region": "regionA",
        "arrival_hour": rng.normal(9.0, 2.0, n_src).clip(0, 24),
        "dwell_hours": rng.gamma(3.0, 2.0, n_src).clip(0.1, 24),
    })
    gen = pd.DataFrame({
        "region": "regionA",
        "arrival_hour": rng.normal(9.2, 2.1, n_gen).clip(0, 24),
        "dwell_hours": rng.gamma(3.1, 2.0, n_gen).clip(0.1, 24),
    })
    return src, gen


def test_s1_marginals_ci_columns(tmp_path):
    src, gen = _fake_frames()
    out = vc.s1_marginals("toy", src, gen, tmp_path, n_boot=50)
    assert len(out) == 2
    for col in ("ks_ci_lo", "ks_ci_hi", "w1_ci_lo", "w1_ci_hi",
                "n_boot", "bootstrap_seed"):
        assert col in out.columns
    assert (out["n_boot"] == 50).all()
    assert (out["bootstrap_seed"] == vc.BOOTSTRAP_SEED).all()
    assert (out["ks_ci_lo"] <= out["ks_ci_hi"]).all()
    # Deterministic: a second run reproduces the CIs bitwise.
    out2 = vc.s1_marginals("toy", src, gen, tmp_path, n_boot=50)
    for col in ("ks_ci_lo", "ks_ci_hi", "w1_ci_lo", "w1_ci_hi"):
        assert out[col].tolist() == out2[col].tolist()


def test_s1_marginals_bootstrap_off(tmp_path):
    src, gen = _fake_frames()
    out = vc.s1_marginals("toy", src, gen, tmp_path, n_boot=0)
    assert "ks_ci_lo" not in out.columns
    assert "ks_statistic" in out.columns


# ──────────────────────────────────────────────────────────────────────
# S3: family-matched refit (F3 protocol repair)
# ──────────────────────────────────────────────────────────────────────

def test_s3_holdout_refits_shipped_family_protocol():
    # Strongly bimodal arrival + dwell so the mixture gate fires on the
    # train split, exactly as calibration's own selection would.
    rng = np.random.default_rng(13)
    rows = []
    for uid in range(300):
        early = uid % 2 == 0  # interleave modes so the 80/20 user split keeps both
        for _ in range(10):
            rows.append({
                "user_id": f"u{uid:04d}",
                "region": "regionA",
                "arrival_hour": float(np.clip(
                    rng.normal(8.0 if early else 15.5, 0.7), 4.1, 21.9)),
                "dwell_hours": float(np.clip(
                    rng.normal(1.2 if early else 9.0, 0.3 if early else 1.0),
                    0.2, 23.0)),
            })
    src_df = pd.DataFrame(rows)

    out = vc.s3_holdout("acn", src_df)
    assert not out.empty
    assert {"fit_family", "shipped_family", "delta"} <= set(out.columns)
    arr = out[out["variable"] == "arrival_hour"].iloc[0]
    dwl = out[out["variable"] == "dwell_hours"].iloc[0]
    # The protocol must be able to select the mixture family (the old code
    # could only ever produce 'truncnorm'/'weibull' here).
    assert arr["fit_family"] == "truncnorm_mixture"
    assert dwl["fit_family"] in ("weibull", "weibull_mixture")
    assert np.isfinite(float(arr["delta"]))
    # regionA is not a real ACN region → shipped family unknown/blank.
    assert arr["shipped_family"] == ""
