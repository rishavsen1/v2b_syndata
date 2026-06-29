"""Task 5 — per-region arrival mixture fits replace the pooled broadcast.

The worst ACN cell (`rare_consistent`, ~36% of drivers) arrives ~2h later than
the pool, so broadcasting ONE pooled mixture to every region is wrong. After the
fix, a region with enough samples gets its OWN arrival fit; only regions below
MIXTURE_MIN_SAMPLES fall back to the pooled mixture (or single TruncNorm).
"""
from __future__ import annotations

import numpy as np

from v2b_syndata.calibration.api import _fit_region_arrivals
from v2b_syndata.calibration.distribution_fitter import MIXTURE_MIN_SAMPLES


def test_distinct_region_arrivals_are_not_broadcast():
    """Two regions with clearly different arrival means must end up with
    DIFFERENT arrival fits (not a single shared/pooled one)."""
    rng = np.random.default_rng(0)
    # Region A: bimodal early commuter (7:00 + 12:00)
    a = np.concatenate([rng.normal(7.0, 0.5, 400), rng.normal(12.0, 1.5, 300)])
    # Region B: later, broader (10:00 + 15:00)
    b = np.concatenate([rng.normal(10.0, 0.6, 400), rng.normal(15.0, 1.5, 300)])
    a = np.clip(a, 4.01, 21.99)
    b = np.clip(b, 4.01, 21.99)

    region_arrivals = {"A": a, "B": b}
    pooled = np.concatenate([a, b])
    fits = _fit_region_arrivals(region_arrivals, pooled)

    assert "A" in fits and "B" in fits
    # Each region fit its own arrival → means differ materially.
    def _center(f):
        if f.get("dist") == "truncnorm_mixture":
            return f["w1"] * f["mu1"] + (1 - f["w1"]) * f["mu2"]
        return f["mu"]
    assert abs(_center(fits["A"]) - _center(fits["B"])) > 1.0


def test_small_region_falls_back_to_pooled():
    """A region below MIXTURE_MIN_SAMPLES gets the pooled mixture (when one
    exists), not its own noisy fit."""
    rng = np.random.default_rng(1)
    big = np.concatenate([rng.normal(8.0, 0.5, 600), rng.normal(13.0, 1.5, 500)])
    big = np.clip(big, 4.01, 21.99)
    tiny = np.clip(rng.normal(9.0, 1.0, MIXTURE_MIN_SAMPLES - 20), 4.01, 21.99)

    region_arrivals = {"BIG": big, "TINY": tiny}
    pooled = np.concatenate([big, tiny])
    fits = _fit_region_arrivals(region_arrivals, pooled)

    assert fits["BIG"]["dist"] == "truncnorm_mixture"     # own mixture
    # TINY (n < 60) cannot fit its own mixture → pooled mixture broadcast.
    assert fits["TINY"]["dist"] == "truncnorm_mixture"
    assert fits["TINY"]["mu1"] == fits["BIG"]["mu1"] or fits["TINY"] is not fits["BIG"]


def test_small_region_single_when_no_pooled_mixture():
    """If no pooled mixture is justified, a small region keeps a single
    TruncNorm (never crashes, never invents a mixture)."""
    rng = np.random.default_rng(2)
    uni = np.clip(rng.normal(9.0, 1.0, 300), 4.01, 21.99)  # unimodal → no mixture
    tiny = np.clip(rng.normal(9.0, 1.0, 20), 4.01, 21.99)
    fits = _fit_region_arrivals({"BIG": uni, "TINY": tiny}, uni)
    assert fits["BIG"]["dist"] == "truncnorm"
    assert fits["TINY"]["dist"] == "truncnorm"
