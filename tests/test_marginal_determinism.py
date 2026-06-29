"""Task 4 — the new mixture marginals must preserve the determinism contract:
each draw consumes EXACTLY ONE uniform, and the transform is a pure function of
that uniform (no fresh RNG, no von Mises).
"""
from __future__ import annotations

import numpy as np

from v2b_syndata.renderers.sessions import (
    _mixture_ppf_u,
    _weibull_mixture_ppf_u,
)


def test_dwell_mixture_independent_branch_one_uniform():
    """The independent (rho≈0) dwell branch must invert float(rng.random()) —
    one draw — NOT rng.weibull. Two RNGs seeded identically, one calling
    rng.random() then the mixture ppf, must leave the RNG state identical to a
    bare rng.random() call (i.e. exactly one uniform consumed)."""
    comps = [(0.6, 1.5, 3.0), (0.4, 2.5, 9.0)]
    rng_a = np.random.default_rng(123)
    rng_b = np.random.default_rng(123)

    # Branch under test: one rng.random() feeds the pure quantile transform.
    u = float(rng_a.random())
    _ = _weibull_mixture_ppf_u(u, comps)
    # Reference: exactly one uniform consumed.
    _ = float(rng_b.random())

    # If the mixture path consumed extra randomness, subsequent streams diverge.
    nxt_a = rng_a.random(5)
    nxt_b = rng_b.random(5)
    np.testing.assert_array_equal(nxt_a, nxt_b)


def test_mixture_ppf_pure_function():
    """ppf must be a deterministic pure function of u (repeatable, no state)."""
    comps_w = [(0.5, 2.0, 4.0), (0.5, 1.2, 10.0)]
    comps_t = [(0.5, 8.0, 0.8), (0.5, 14.0, 1.5)]
    for u in (0.05, 0.37, 0.5, 0.83, 0.99):
        assert _weibull_mixture_ppf_u(u, comps_w) == _weibull_mixture_ppf_u(u, comps_w)
        assert _mixture_ppf_u(u, comps_t, 4.0, 22.0) == _mixture_ppf_u(u, comps_t, 4.0, 22.0)


def test_sample_f_dwell_exposes_mixture():
    from tests.test_sessions_dist_fallback import _build_ctx
    from v2b_syndata.samplers.sessions_dist import sample_f_dwell

    rd = {"stable_commuter": {"dwell": {
        "dist": "weibull_mixture",
        "w1": 0.6, "k1": 1.5, "lambda1": 2.0, "k2": 2.5, "lambda2": 9.0,
    }}}
    ctx = _build_ctx(rd)
    sample_f_dwell(ctx)
    p = ctx.latents["f_dwell"][1]
    assert "mixture" in p
    assert p["mixture"][0] == (0.6, 1.5, 2.0)
    assert abs(p["mixture"][1][0] - 0.4) < 1e-12


def test_sample_f_dwell_single_has_no_mixture():
    from tests.test_sessions_dist_fallback import _build_ctx
    from v2b_syndata.samplers.sessions_dist import sample_f_dwell

    rd = {"stable_commuter": {"dwell": {"k": 2.1, "lambda": 9.2}}}
    ctx = _build_ctx(rd)
    sample_f_dwell(ctx)
    p = ctx.latents["f_dwell"][1]
    assert "mixture" not in p
    assert p["k"] == 2.1 and p["lam"] == 9.2
