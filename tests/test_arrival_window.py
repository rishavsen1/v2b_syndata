"""Task 6 — widened [6,20] → [4,22] arrival clip, gated behind calibrated leaves.

The widened window must:
  * be the new fitter / range-table support ([4, 22]);
  * be READ from the calibrated `arrival.trunc_lo/trunc_hi` block when present;
  * default to 6/20 for synthetic / hand-authored populations so they stay
    BITWISE-IDENTICAL (no trunc_lo/hi leaf → 6/20).
"""
from __future__ import annotations

import numpy as np

from v2b_syndata.calibration.distribution_fitter import (
    ARRIVAL_HI,
    ARRIVAL_LO,
    fit_truncnorm_arrival,
)
from v2b_syndata.knob_loader import DIST_PARAM_RANGES


def test_fitter_window_widened():
    assert ARRIVAL_LO == 4.0
    assert ARRIVAL_HI == 22.0


def test_range_table_widened():
    for leaf in ("arrival.mu", "arrival.mu1", "arrival.mu2"):
        lo, hi = DIST_PARAM_RANGES[leaf]
        assert (lo, hi) == (4.0, 22.0), leaf


def test_fitter_accepts_arrivals_in_widened_window():
    """An arrival cohort centred near 5:00 (inside [4,22], outside [6,20]) must
    fit without being dropped for out-of-range mu."""
    rng = np.random.default_rng(0)
    arr = np.clip(rng.normal(5.0, 0.8, 500), 4.01, 21.99)
    fit = fit_truncnorm_arrival(arr)
    assert fit is not None
    assert fit["dist"] == "truncnorm"
    assert 4.0 <= fit["mu"] <= 22.0
    assert fit["mu"] < 6.0  # genuinely below the old floor


def test_default_trunc_bounds_unchanged_for_synthetic():
    """sample_f_arr: a region with NO trunc_lo/hi leaf keeps 6/20 (bitwise
    identity for hand-authored populations)."""
    from tests.test_sessions_dist_fallback import _build_ctx
    from v2b_syndata.samplers.sessions_dist import sample_f_arr

    rd = {"stable_commuter": {"arrival": {"mu": 8.7, "sigma": 0.6}}}
    ctx = _build_ctx(rd)
    sample_f_arr(ctx)
    p = ctx.latents["f_arr"][1]
    assert p["trunc_lo"] == 6.0
    assert p["trunc_hi"] == 20.0


def test_calibrated_trunc_bounds_are_read():
    """sample_f_arr: a region WITH trunc_lo/hi leaves uses them."""
    from tests.test_sessions_dist_fallback import _build_ctx
    from v2b_syndata.samplers.sessions_dist import sample_f_arr

    rd = {"stable_commuter": {
        "arrival": {"mu": 5.0, "sigma": 0.6, "trunc_lo": 4.0, "trunc_hi": 22.0},
    }}
    ctx = _build_ctx(rd)
    sample_f_arr(ctx)
    p = ctx.latents["f_arr"][1]
    assert p["trunc_lo"] == 4.0
    assert p["trunc_hi"] == 22.0
    assert p["mu"] == 5.0


def test_calibrated_mixture_reads_trunc_bounds():
    from tests.test_sessions_dist_fallback import _build_ctx
    from v2b_syndata.samplers.sessions_dist import sample_f_arr

    rd = {"stable_commuter": {
        "arrival": {
            "dist": "truncnorm_mixture",
            "w1": 0.5, "mu1": 5.0, "sigma1": 0.8,
            "mu2": 13.0, "sigma2": 2.0,
            "trunc_lo": 4.0, "trunc_hi": 22.0,
        },
    }}
    ctx = _build_ctx(rd)
    sample_f_arr(ctx)
    p = ctx.latents["f_arr"][1]
    assert p["trunc_lo"] == 4.0
    assert p["trunc_hi"] == 22.0
    assert p["mixture"][0][1] == 5.0
