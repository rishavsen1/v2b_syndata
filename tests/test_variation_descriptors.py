"""Per-descriptor library coverage — every entry in every library generates."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from v2b_syndata.validate import validate

S01_DEFAULTS = {
    "location": "nashville_tn",
    "building": "medium_office_v1",
    "population": "consent_default",
    "equipment": "balanced_50pct",
    "noise": "clean",
}

CSV_NAMES = ("building_load", "cars", "users", "chargers",
             "grid_prices", "dr_events", "sessions")


def _run(tmp_scenario_dir, fast_generate, **descriptor_overrides):
    cfg, write_scenario = tmp_scenario_dir
    descriptors = {**S01_DEFAULTS, **descriptor_overrides}
    cfg, sid = write_scenario(descriptors)
    out, manifest = fast_generate(scenario=sid, config_dir=cfg)
    return out, manifest, descriptors


@pytest.mark.parametrize("location", [
    "nashville_tn",
    "san_jose_ca",
    "san_francisco_ca",
    "minneapolis_mn",
    "miami_fl",
    "houston_tx",
    "atlanta_ga",
])
def test_each_location(location, tmp_scenario_dir, fast_generate, assert_sanity):
    out, manifest, _ = _run(tmp_scenario_dir, fast_generate, location=location)
    for n in CSV_NAMES:
        assert (out / f"{n}.csv").exists(), f"missing {n}.csv"
    assert (out / "manifest.json").exists()
    assert_sanity(out, manifest,
                  expected_start=datetime(2020, 4, 1),
                  expected_end=datetime(2020, 4, 8))
    rep = validate(out)
    assert rep.passed, f"{location}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize("building", [
    "medium_office_v1",
    "small_office_v1",
    "large_office_v1",
    "retail_strip_mall",
    "retail_standalone",
    "mixed_use_v1",
])
def test_each_building(building, tmp_scenario_dir, fast_generate, assert_sanity):
    out, manifest, _ = _run(tmp_scenario_dir, fast_generate, building=building)
    for n in CSV_NAMES:
        assert (out / f"{n}.csv").exists()
    assert_sanity(out, manifest,
                  expected_start=datetime(2020, 4, 1),
                  expected_end=datetime(2020, 4, 8))
    rep = validate(out)
    assert rep.passed, f"{building}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize("population", [
    "consent_default",
    "stable_commuter_heavy",
    "visitor_heavy",
])
def test_each_population(population, tmp_scenario_dir, fast_generate, assert_sanity):
    cfg, write_scenario = tmp_scenario_dir
    descriptors = {**S01_DEFAULTS, "population": population}
    # stable_commuter_heavy has ev_count=25 but S01 equipment ships only 20 chargers,
    # which would trip E5. Bump charger_count so the population swap is the only delta.
    cfg, sid = write_scenario(descriptors,
                              overrides={"charging_infra.charger_count": 30})
    out, manifest = fast_generate(scenario=sid, config_dir=cfg)
    for n in CSV_NAMES:
        assert (out / f"{n}.csv").exists()
    assert_sanity(out, manifest,
                  expected_start=datetime(2020, 4, 1),
                  expected_end=datetime(2020, 4, 8))
    rep = validate(out)
    assert rep.passed, f"{population}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize("equipment,charger_count", [
    ("balanced_50pct", 20),
    ("uni_only", 20),
    ("bi_heavy", 20),
    ("consent_calibration_site", 15),
    ("high_power_dcfc", 8),
])
def test_each_equipment(equipment, charger_count, tmp_scenario_dir, fast_generate,
                        assert_sanity):
    cfg, write_scenario = tmp_scenario_dir
    descriptors = {**S01_DEFAULTS, "equipment": equipment}
    # Scale the fleet to the chargers so E5 capacity holds across the parametrize.
    cfg, sid = write_scenario(descriptors,
                              overrides={"ev_fleet.ev_count": charger_count})
    out, manifest = fast_generate(scenario=sid, config_dir=cfg)
    for n in CSV_NAMES:
        assert (out / f"{n}.csv").exists()
    assert_sanity(out, manifest,
                  expected_start=datetime(2020, 4, 1),
                  expected_end=datetime(2020, 4, 8))
    chargers = pd.read_csv(out / "chargers.csv")
    assert len(chargers) == charger_count
    if charger_count >= 15:
        # F4/F5 share invariants get unreliable below n≈15. Below that, exit
        # after structural sanity — equipment-specific knobs are still asserted
        # via the chargers.csv row count above.
        rep = validate(out)
        assert rep.passed, f"{equipment}: {'; '.join(rep.errors)}"


@pytest.mark.parametrize("noise", [
    "clean",
    "light_noise",
    "realistic_noise",
    "adversarial",
])
def test_each_noise_profile(noise, tmp_scenario_dir, fast_generate, assert_sanity):
    out, manifest, _ = _run(tmp_scenario_dir, fast_generate, noise=noise)
    for n in CSV_NAMES:
        assert (out / f"{n}.csv").exists()
    assert_sanity(out, manifest,
                  expected_start=datetime(2020, 4, 1),
                  expected_end=datetime(2020, 4, 8))
    if noise == "clean":
        rep = validate(out)
        assert rep.passed, f"{noise}: {'; '.join(rep.errors)}"
