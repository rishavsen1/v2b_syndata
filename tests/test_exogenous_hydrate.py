"""Tests for samplers/exogenous._hydrate_region_distributions.

Covers: empty, partial regions, partial dist within region, round-trip
flatten/hydrate.
"""
from __future__ import annotations

from v2b_syndata.samplers.exogenous import _hydrate_region_distributions
from v2b_syndata.types import KnobValue, ResolvedKnobs


def _resolved(items: dict[str, float]) -> ResolvedKnobs:
    r = ResolvedKnobs()
    for k, v in items.items():
        r.values[k] = KnobValue(value=v, source="calibration:test")
    return r


def test_hydrate_empty_region_distributions():
    r = _resolved({"unrelated.knob": 1.0})
    out = _hydrate_region_distributions(r)
    assert out == {}


def test_hydrate_single_leaf():
    r = _resolved({
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 8.7,
    })
    out = _hydrate_region_distributions(r)
    assert out == {"stable_commuter": {"arrival": {"mu": 8.7}}}


def test_hydrate_partial_distribution_within_region():
    r = _resolved({
        "user_behavior.region_distributions.stable_commuter.dwell.k": 2.5,
    })
    out = _hydrate_region_distributions(r)
    assert out == {"stable_commuter": {"dwell": {"k": 2.5}}}
    assert "lambda" not in out["stable_commuter"]["dwell"]


def test_hydrate_partial_regions():
    r = _resolved({
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 8.7,
        "user_behavior.region_distributions.stable_commuter.arrival.sigma": 0.6,
        "user_behavior.region_distributions.flexible_local.arrival.mu": 10.5,
    })
    out = _hydrate_region_distributions(r)
    assert "stable_commuter" in out
    assert "flexible_local" in out
    assert out["stable_commuter"]["arrival"] == {"mu": 8.7, "sigma": 0.6}
    assert out["flexible_local"]["arrival"] == {"mu": 10.5}
    assert "dwell" not in out["stable_commuter"]
    assert "dwell" not in out["flexible_local"]


def test_hydrate_full_region():
    r = _resolved({
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 8.7,
        "user_behavior.region_distributions.stable_commuter.arrival.sigma": 0.6,
        "user_behavior.region_distributions.stable_commuter.dwell.k": 2.1,
        "user_behavior.region_distributions.stable_commuter.dwell.lambda": 9.2,
        "user_behavior.region_distributions.stable_commuter.soc_arrival.alpha": 4.5,
        "user_behavior.region_distributions.stable_commuter.soc_arrival.beta": 6.1,
        "user_behavior.region_distributions.stable_commuter.copula.rho_gaussian": -0.187,
    })
    out = _hydrate_region_distributions(r)
    sc = out["stable_commuter"]
    assert sc["arrival"] == {"mu": 8.7, "sigma": 0.6}
    assert sc["dwell"] == {"k": 2.1, "lambda": 9.2}
    assert sc["soc_arrival"] == {"alpha": 4.5, "beta": 6.1}
    assert sc["copula"] == {"rho_gaussian": -0.187}


def test_hydrate_round_trip():
    """Flatten an arbitrary nested dict, hydrate back, expect equality."""
    nested = {
        "stable_commuter": {
            "arrival": {"mu": 8.7, "sigma": 0.6},
            "dwell": {"k": 2.1, "lambda": 9.2},
        },
        "flexible_local": {
            "arrival": {"mu": 10.5, "sigma": 1.5},
        },
    }
    flat = {}
    for region, dists in nested.items():
        for dist, params in dists.items():
            for p, v in params.items():
                flat[f"user_behavior.region_distributions.{region}.{dist}.{p}"] = v
    r = _resolved(flat)
    out = _hydrate_region_distributions(r)
    assert out == nested


def test_hydrate_ignores_unrelated_keys():
    r = _resolved({
        "user_behavior.region_distributions.stable_commuter.arrival.mu": 8.7,
        "ev_fleet.ev_count": 20,
        "noise.profile": "clean",
        "user_behavior.axes_distribution": "scrambled",
    })
    out = _hydrate_region_distributions(r)
    assert out == {"stable_commuter": {"arrival": {"mu": 8.7}}}


def test_hydrate_drops_too_short_paths():
    """Path with too few segments should not crash; should be ignored."""
    r = _resolved({
        "user_behavior.region_distributions.short": 1.0,
        "user_behavior.region_distributions.too.short": 2.0,
    })
    out = _hydrate_region_distributions(r)
    assert out == {}
