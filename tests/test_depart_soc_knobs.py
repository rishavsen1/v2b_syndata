"""The fallback departure-SoC TruncNorm μ/σ are now knobs.

Defaults (85/5) must reproduce the prior hardcoded behavior bit-for-bit;
overriding them must move required_soc_at_depart for an uncalibrated
population (S01 / consent_default uses the fallback, not a fitted soc_depart).
"""
from __future__ import annotations

import filecmp

import pandas as pd


def test_default_knobs_bit_identical(fast_generate):
    """Explicitly setting μ=85/σ=5 == not setting them (defaults preserved)."""
    out_default, _ = fast_generate(seed=123)
    out_explicit, _ = fast_generate(seed=123, overrides={
        "user_behavior.depart_soc_mu": 85.0,
        "user_behavior.depart_soc_sigma": 5.0,
    })
    assert filecmp.cmp(out_default / "sessions.csv",
                       out_explicit / "sessions.csv", shallow=False)


def test_override_shifts_required_soc(fast_generate):
    """Lowering μ (no floor) lowers required_soc_at_depart for the fallback."""
    common = {"user_behavior.min_depart_soc": 0.0}  # drop the 80% floor
    out_hi, _ = fast_generate(seed=123, overrides={
        **common, "user_behavior.depart_soc_mu": 85.0,
    })
    out_lo, _ = fast_generate(seed=123, overrides={
        **common, "user_behavior.depart_soc_mu": 50.0,
    })
    hi = pd.read_csv(out_hi / "sessions.csv")["required_soc_at_depart"]
    lo = pd.read_csv(out_lo / "sessions.csv")["required_soc_at_depart"]
    assert len(hi) and len(lo)
    assert lo.mean() < hi.mean(), (lo.mean(), hi.mean())
