"""Tests for Tier 0 → Tier 1 descriptor expansion."""
from __future__ import annotations

import pytest

from v2b_syndata.descriptor_loader import expand_descriptors


def test_all_four_descriptors_resolve(config_dir):
    out = expand_descriptors(
        {
            "location": "nashville_tn",
            "building": "medium_office_v1",
            "population": "consent_default",
            "equipment": "balanced_50pct",
        },
        config_dir,
    )
    # Sample a few expected paths from each descriptor
    assert out["building_load.climate"][0] == "subtropical"
    assert out["building_load.climate"][1] == "nashville_tn"
    assert out["building_load.archetype"][0] == "office"
    assert out["building_load.archetype"][1] == "medium_office_v1"
    assert out["ev_fleet.ev_count"][0] == 20
    assert out["ev_fleet.ev_count"][1] == "consent_default"
    assert out["charging_infra.charger_count"][0] == 20
    assert out["charging_infra.charger_count"][1] == "balanced_50pct"
    # Default noise descriptor (clean) auto-applied
    assert out["noise.profile"][0] == "clean"


def test_unknown_location_raises(config_dir):
    with pytest.raises(KeyError):
        expand_descriptors(
            {"location": "atlantis", "building": "medium_office_v1",
             "population": "consent_default", "equipment": "balanced_50pct"},
            config_dir,
        )


def test_noise_descriptor_overrides(config_dir):
    out = expand_descriptors(
        {"location": "nashville_tn", "building": "medium_office_v1",
         "population": "consent_default", "equipment": "balanced_50pct",
         "noise": "light_noise"},
        config_dir,
    )
    assert out["noise.profile"][0] == "light_noise"
    assert out["noise.building_load_jitter_pct"][0] > 0
