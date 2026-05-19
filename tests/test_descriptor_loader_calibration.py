"""Tests for descriptor_loader region_distributions flattening (C2).

Covers: calibrated leaf flatten with calibration: source, metadata filter
(n_samples / ks_fit_quality NOT in expansion), uncalibrated population path
(no deep-channel keys), partial calibration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from v2b_syndata.descriptor_loader import expand_descriptors


_BASE_LIBS = {
    "locations.yaml": """
test_loc:
  climate: temperate
  tariff:
    type: TOU
    energy_price_offpeak: 0.137
    energy_price_peak: 0.178
    peak_window: [14, 19]
    demand_charge_per_kw: 11.67
    dr_program: none
""",
    "buildings.yaml": """
test_bld:
  archetype: office
  size: med
  occupancy_source: ashrae_90_1_office
  peak_kw: 500.0
""",
    "equipment.yaml": """
test_eq:
  charger_count: 20
  directionality_frac: 0.5
  uni_rate_kw: 20.0
  bi_rate_kw: 20.0
""",
    "noise_profiles.yaml": """
clean:
  building_load_jitter_pct: 0.0
  arrival_time_jitter_min: 0.0
  soc_arrival_jitter_pct: 0.0
  dr_notification_dropout_prob: 0.0
  price_jitter_pct: 0.0
  occupancy_jitter_pct: 0.0
""",
}


def _write_libs(tmp_path: Path, populations_yaml: str) -> Path:
    cfg = tmp_path / "configs"
    cfg.mkdir()
    for name, text in _BASE_LIBS.items():
        (cfg / name).write_text(text)
    (cfg / "populations.yaml").write_text(populations_yaml)
    return cfg


_POP_FULLY_CALIBRATED = """
testpop:
  description: "test"
  axes_distribution:
    - {name: stable_commuter, freq: [0.85, 1.0], consist: [0.75, 1.0], dist_km: [40, 80], weight: 0.5}
    - {name: flexible_local, freq: [0.7, 0.95], consist: [0.5, 0.8], dist_km: [5, 15], weight: 0.5}
  negotiation:
    cluster_mix: [0.1, 0.5, 0.3, 0.1]
    w_multiplier: [1.0, 1.0]
  fleet:
    ev_count: 10
    battery_mix: [0.2, 0.3, 0.4, 0.1]
    battery_heterogeneity: het
  region_distributions:
    stable_commuter:
      arrival: {dist: truncnorm, mu: 8.7, sigma: 0.6, n_samples: 412, ks_fit_quality: 0.04}
      dwell:   {dist: weibull,   k: 2.1, lambda: 9.2, n_samples: 412, ks_fit_quality: 0.06}
      soc_arrival: {dist: beta,  alpha: 4.5, beta: 6.1, n_samples: 380, ks_fit_quality: 0.05}
      copula: {rho_spearman: -0.18, rho_gaussian: -0.187, n_samples: 412}
    flexible_local:
      arrival: {dist: truncnorm, mu: 10.5, sigma: 1.5, n_samples: 230, ks_fit_quality: 0.07}
      dwell: {dist: weibull, k: 1.6, lambda: 5.0, n_samples: 230, ks_fit_quality: 0.08}
  calibration_metadata:
    source: "calibration:acn_data_2019_2021_20260506"
    dataset: ACN-Data
    sites: [caltech, jpl, office001]
    year_range: [2019, 2021]
"""

_POP_UNCALIBRATED = """
testpop:
  description: "test"
  axes_distribution:
    - {name: stable_commuter, freq: [0.85, 1.0], consist: [0.75, 1.0], dist_km: [40, 80], weight: 1.0}
  negotiation:
    cluster_mix: [0.1, 0.5, 0.3, 0.1]
    w_multiplier: [1.0, 1.0]
  fleet:
    ev_count: 10
    battery_mix: [0.2, 0.3, 0.4, 0.1]
    battery_heterogeneity: het
"""

_POP_PARTIAL = """
testpop:
  description: "test"
  axes_distribution:
    - {name: stable_commuter, freq: [0.85, 1.0], consist: [0.75, 1.0], dist_km: [40, 80], weight: 0.6}
    - {name: flexible_local, freq: [0.7, 0.95], consist: [0.5, 0.8], dist_km: [5, 15], weight: 0.4}
  negotiation:
    cluster_mix: [0.1, 0.5, 0.3, 0.1]
    w_multiplier: [1.0, 1.0]
  fleet:
    ev_count: 10
    battery_mix: [0.2, 0.3, 0.4, 0.1]
    battery_heterogeneity: het
  region_distributions:
    stable_commuter:
      arrival: {mu: 8.7, sigma: 0.6, n_samples: 412, ks_fit_quality: 0.04}
      # no dwell, no soc, no copula
  calibration_metadata:
    source: "calibration:acn_data_2019_2021_20260506"
"""


def _descriptors():
    return {
        "location": "test_loc",
        "building": "test_bld",
        "population": "testpop",
        "equipment": "test_eq",
        "noise": "clean",
    }


def test_calibrated_leaves_flatten_with_calibration_source(tmp_path):
    cfg = _write_libs(tmp_path, _POP_FULLY_CALIBRATED)
    out = expand_descriptors(_descriptors(), cfg)
    key = "user_behavior.region_distributions.stable_commuter.arrival.mu"
    assert key in out
    value, source = out[key]
    assert value == 8.7
    assert source == "calibration:acn_data_2019_2021_20260506"


def test_metadata_fields_filtered_from_expansion(tmp_path):
    cfg = _write_libs(tmp_path, _POP_FULLY_CALIBRATED)
    out = expand_descriptors(_descriptors(), cfg)
    leaks = [k for k in out if any(t in k for t in
        (".n_samples", ".ks_fit_quality", ".dist", ".rho_spearman"))]
    assert leaks == [], f"metadata leaked: {leaks}"


def test_calibrated_leaves_only_in_dist_param_ranges(tmp_path):
    """Every emitted region_distributions key has trailing leaf in DIST_PARAM_RANGES."""
    from v2b_syndata.knob_loader import DIST_PARAM_RANGES
    cfg = _write_libs(tmp_path, _POP_FULLY_CALIBRATED)
    out = expand_descriptors(_descriptors(), cfg)
    for k in out:
        if not k.startswith("user_behavior.region_distributions."):
            continue
        tail = k[len("user_behavior.region_distributions."):]
        parts = tail.split(".")
        leaf = ".".join(parts[-2:])
        assert leaf in DIST_PARAM_RANGES, f"unexpected leaf {leaf} in {k}"


def test_uncalibrated_population_no_region_distributions_keys(tmp_path):
    cfg = _write_libs(tmp_path, _POP_UNCALIBRATED)
    out = expand_descriptors(_descriptors(), cfg)
    deep = [k for k in out if k.startswith("user_behavior.region_distributions.")]
    assert deep == []


def test_partial_calibration_population(tmp_path):
    cfg = _write_libs(tmp_path, _POP_PARTIAL)
    out = expand_descriptors(_descriptors(), cfg)
    deep_keys = [k for k in out if k.startswith("user_behavior.region_distributions.")]
    # Only stable_commuter.arrival.{mu,sigma} should appear.
    assert "user_behavior.region_distributions.stable_commuter.arrival.mu" in out
    assert "user_behavior.region_distributions.stable_commuter.arrival.sigma" in out
    # flexible_local has no calibrated entries.
    assert not any("flexible_local" in k for k in deep_keys)
    # No dwell/soc/copula leaves for stable_commuter.
    assert not any(".dwell." in k for k in deep_keys)
    assert not any(".soc_arrival." in k for k in deep_keys)
    assert not any(".copula." in k for k in deep_keys)


def test_calibration_source_propagates_uniformly(tmp_path):
    cfg = _write_libs(tmp_path, _POP_FULLY_CALIBRATED)
    out = expand_descriptors(_descriptors(), cfg)
    deep = {k: v for k, v in out.items()
            if k.startswith("user_behavior.region_distributions.")}
    assert deep, "expected calibrated leaves"
    sources = {v[1] for v in deep.values()}
    assert sources == {"calibration:acn_data_2019_2021_20260506"}, sources
