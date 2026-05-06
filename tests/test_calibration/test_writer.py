"""Tests for writer — round-trip populations.yaml entry without losing structure."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

from v2b_syndata.calibration.writer import write_region_distributions

SAMPLE_YAML = """
test_pop:
  description: "Test"
  axes_distribution:
    - {name: stable_commuter, freq: [0.85, 1.0], consist: [0.75, 1.0], dist_km: [40, 80], weight: 0.5}
    - {name: flexible_local, freq: [0.70, 0.95], consist: [0.50, 0.80], dist_km: [5, 15], weight: 0.5}
  negotiation:
    cluster_mix: [0.1, 0.5, 0.3, 0.1]
    w_multiplier: [1.0, 1.0]
  fleet:
    ev_count: 10
    battery_mix: [0.2, 0.3, 0.4, 0.1]
    battery_heterogeneity: het
"""


def test_writer_round_trip(tmp_path: Path):
    p = tmp_path / "populations.yaml"
    p.write_text(SAMPLE_YAML)

    region_fits = {
        "stable_commuter": {
            "arrival": {"dist": "truncnorm", "mu": 8.7, "sigma": 0.6,
                        "n_samples": 412, "ks_fit_quality": 0.04},
            "dwell": {"dist": "weibull", "k": 2.1, "lambda": 9.2,
                      "n_samples": 412, "ks_fit_quality": 0.06},
            "soc_arrival": {"dist": "beta", "alpha": 4.5, "beta": 6.1,
                            "n_samples": 380, "ks_fit_quality": 0.05},
            "copula": {"rho_spearman": -0.18, "rho_gaussian": -0.187, "n_samples": 412},
        },
    }
    metadata = {
        "source": "calibration:acn_data_2019_2021_20260506",
        "dataset": "ACN-Data",
        "sites": ["caltech", "jpl", "office001"],
        "year_range": [2019, 2021],
        "calibration_date": "2026-05-06",
        "n_users_total": 1542,
        "capacity_inference_fallback_rate": 0.34,
    }

    write_region_distributions(p, "test_pop", region_fits, metadata)

    # Read back via pyyaml — verifies output is valid YAML.
    data = pyyaml.safe_load(p.read_text())
    pop = data["test_pop"]

    # Original blocks preserved.
    assert "axes_distribution" in pop
    assert len(pop["axes_distribution"]) == 2
    assert pop["fleet"]["ev_count"] == 10

    # New blocks present.
    assert "region_distributions" in pop
    assert "stable_commuter" in pop["region_distributions"]
    arr = pop["region_distributions"]["stable_commuter"]["arrival"]
    assert arr["mu"] == 8.7
    assert arr["sigma"] == 0.6
    assert arr["ks_fit_quality"] == 0.04

    assert pop["calibration_metadata"]["source"] == "calibration:acn_data_2019_2021_20260506"


def test_writer_preserves_yaml_comments(tmp_path: Path):
    """ruamel.yaml round-trip must preserve hand-written # comments."""
    p = tmp_path / "populations.yaml"
    p.write_text("""# Top-level comment
test_pop:
  description: "Test"
  # comment above axes
  axes_distribution:
    - {name: stable_commuter, freq: [0.85, 1.0], consist: [0.75, 1.0], dist_km: [40, 80], weight: 0.5}
    - {name: flexible_local, freq: [0.70, 0.95], consist: [0.50, 0.80], dist_km: [5, 15], weight: 0.5}
  negotiation:
    cluster_mix: [0.1, 0.5, 0.3, 0.1]
    w_multiplier: [1.0, 1.0]
  fleet:
    ev_count: 10
    battery_mix: [0.2, 0.3, 0.4, 0.1]
    battery_heterogeneity: het
""")

    write_region_distributions(p, "test_pop",
        {"stable_commuter": {"arrival": {"mu": 8.7}}},
        {"source": "calibration:test"},
    )
    text = p.read_text()
    assert "# Top-level comment" in text
    assert "# comment above axes" in text


def test_writer_missing_population_key_raises(tmp_path: Path):
    p = tmp_path / "populations.yaml"
    p.write_text(SAMPLE_YAML)
    with pytest.raises(KeyError, match="absent_pop"):
        write_region_distributions(p, "absent_pop",
            {"stable_commuter": {"arrival": {"mu": 8.7}}},
            {"source": "calibration:test"},
        )


def test_writer_replaces_existing_block(tmp_path: Path):
    p = tmp_path / "populations.yaml"
    p.write_text(SAMPLE_YAML)

    write_region_distributions(p, "test_pop",
        {"stable_commuter": {"arrival": {"mu": 1.0}}},
        {"source": "calibration:run1"},
    )
    write_region_distributions(p, "test_pop",
        {"flexible_local": {"arrival": {"mu": 2.0}}},
        {"source": "calibration:run2"},
    )

    data = pyyaml.safe_load(p.read_text())
    rd = data["test_pop"]["region_distributions"]
    assert "stable_commuter" not in rd  # old block replaced
    assert "flexible_local" in rd
    assert data["test_pop"]["calibration_metadata"]["source"] == "calibration:run2"
