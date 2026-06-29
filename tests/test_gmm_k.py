"""Task 4 — generalized GMM-k EM (`_gmm_em(x, k)`).

`_gmm2_em` is kept as a thin k=2 wrapper for back-compat. The generalized form
must:
  * reduce EXACTLY to the old k=2 behavior (same init, same iteration) so the
    shipped 2-component arrival mixture is unchanged;
  * fit k>2 components, mean-ordered on return is the caller's job, but params
    are finite and weights sum to 1;
  * be deterministic (no RNG) — pure function of the data + k.
"""
from __future__ import annotations

import numpy as np

from v2b_syndata.calibration.distribution_fitter import _gmm2_em, _gmm_em


def test_gmm_em_k2_matches_legacy_gmm2():
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(8.0, 0.5, 400), rng.normal(14.0, 1.0, 300)])
    mu_a, sd_a, w_a, ll_a = _gmm2_em(x)
    mu_b, sd_b, w_b, ll_b = _gmm_em(x, 2)
    np.testing.assert_allclose(np.sort(mu_a), np.sort(mu_b), rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(np.sort(sd_a), np.sort(sd_b), rtol=1e-9, atol=1e-9)
    assert abs(ll_a - ll_b) < 1e-6


def test_gmm_em_k3_finite_and_normalized():
    rng = np.random.default_rng(1)
    x = np.concatenate([
        rng.normal(6.0, 0.4, 300),
        rng.normal(10.0, 0.6, 300),
        rng.normal(16.0, 1.0, 300),
    ])
    mu, sd, w, ll = _gmm_em(x, 3)
    assert len(mu) == len(sd) == len(w) == 3
    assert np.all(np.isfinite(mu)) and np.all(np.isfinite(sd))
    assert np.all(sd > 0)
    assert abs(float(w.sum()) - 1.0) < 1e-9
    assert np.isfinite(ll)


def test_gmm_em_deterministic():
    rng = np.random.default_rng(2)
    x = rng.normal(10.0, 2.0, 500)
    a = _gmm_em(x, 3)
    b = _gmm_em(x, 3)
    np.testing.assert_array_equal(a[0], b[0])
    np.testing.assert_array_equal(a[1], b[1])
    np.testing.assert_array_equal(a[2], b[2])
