"""Cross-source integration tests for the CalibrationSource protocol.

Covers gaps after PR1-PR4: registry completeness, cross-source isolation,
CLI --source-arg [policy:]key=value scoping, descriptor_loader provenance
strings for evwatts + inl policies.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml as pyyaml

from v2b_syndata.calibration import calibrate_populations
from v2b_syndata.calibration.sources import (
    CALIBRATION_SOURCES,
    AcnSource,
    CalibrationSource,
    ElaadNLSource,
    EvWattsSource,
    InlSource,
)
from v2b_syndata.cli import main
from v2b_syndata.descriptor_loader import expand_descriptors

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "configs"
FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _block_sha(populations_yaml_text: str, pop_name: str) -> str:
    """Return sha256 of the YAML-dumped population block for stable diffing."""
    doc = pyyaml.safe_load(populations_yaml_text)
    block = pyyaml.safe_dump(doc[pop_name], sort_keys=True).encode()
    return hashlib.sha256(block).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Registry completeness
# ──────────────────────────────────────────────────────────────────────
def test_registry_contains_four_real_data_sources():
    assert set(CALIBRATION_SOURCES) == {
        "acn_data", "evwatts", "inl_ev_project", "elaadnl_open_2020",
    }


def test_registry_values_are_calibration_sources():
    for policy, cls in CALIBRATION_SOURCES.items():
        inst = cls()
        for attr in ("fetch_sessions", "dataset_name", "provenance_prefix",
                     "extra_metadata", "token_help_message", "parse_args"):
            assert callable(getattr(inst, attr)), f"{policy}: missing {attr}"
        assert isinstance(inst.dataset_name(), str) and inst.dataset_name()


def test_registry_matches_shipped_populations_policies():
    pops = pyyaml.safe_load((CONFIG_DIR / "populations.yaml").read_text())
    valid = set(CALIBRATION_SOURCES) | {"synthetic"}
    for name, entry in pops.items():
        assert entry["calibration_policy"] in valid, \
            f"{name}: policy {entry['calibration_policy']!r} not in {valid}"


def test_dataset_names_distinct():
    names = {policy: cls().dataset_name() for policy, cls in CALIBRATION_SOURCES.items()}
    assert len(set(names.values())) == len(names), names


# ──────────────────────────────────────────────────────────────────────
# Cross-source isolation: calibrating one source must not touch others
# ──────────────────────────────────────────────────────────────────────
def _seed_evwatts_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_DIR / "evwatts_fixture.csv", cache_dir / "evwatts_fixture.csv")


def _seed_inl_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_DIR / "inl_fixture.csv", cache_dir / "inl_fixture.csv")


def _seed_elaadnl_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_DIR / "elaadnl_fixture.csv", cache_dir / "elaadnl_fixture.csv")


def test_evwatts_calibrate_leaves_acn_block_untouched(tmp_path):
    pops_dst = tmp_path / "populations.yaml"
    shutil.copy(CONFIG_DIR / "populations.yaml", pops_dst)
    acn_sha_before = _block_sha(pops_dst.read_text(), "acn_workplace_baseline")
    inl_sha_before = _block_sha(pops_dst.read_text(), "inl_residential_legacy")

    cache = tmp_path / "evwatts_cache"
    _seed_evwatts_cache(cache)

    calibrate_populations(
        populations_yaml_path=pops_dst,
        population_names=["evwatts_workplace_public"],
        cache_dir=cache,
        artifact_dir=tmp_path / "art",
        source_configs={"evwatts": {
            "release_tag": "fixture",
            "venue_filter": "workplace_public",
            "cache_dir": cache,
        }},
    )

    assert _block_sha(pops_dst.read_text(), "acn_workplace_baseline") == acn_sha_before
    assert _block_sha(pops_dst.read_text(), "inl_residential_legacy") == inl_sha_before


def test_inl_calibrate_leaves_acn_and_evwatts_blocks_untouched(tmp_path):
    pops_dst = tmp_path / "populations.yaml"
    shutil.copy(CONFIG_DIR / "populations.yaml", pops_dst)
    acn_sha_before = _block_sha(pops_dst.read_text(), "acn_workplace_baseline")
    ev_sha_before = _block_sha(pops_dst.read_text(), "evwatts_workplace_public")
    ev_dcfc_sha_before = _block_sha(pops_dst.read_text(), "evwatts_dcfc_public")
    el_sha_before = _block_sha(pops_dst.read_text(), "elaadnl_public_eu")

    cache = tmp_path / "inl_cache"
    _seed_inl_cache(cache)

    calibrate_populations(
        populations_yaml_path=pops_dst,
        population_names=["inl_residential_legacy"],
        cache_dir=cache,
        artifact_dir=tmp_path / "art",
        source_configs={"inl_ev_project": {
            "archive_tag": "fixture",
            "venue_filter": "residential",
            "cache_dir": cache,
        }},
    )

    assert _block_sha(pops_dst.read_text(), "acn_workplace_baseline") == acn_sha_before
    assert _block_sha(pops_dst.read_text(), "evwatts_workplace_public") == ev_sha_before
    assert _block_sha(pops_dst.read_text(), "evwatts_dcfc_public") == ev_dcfc_sha_before
    assert _block_sha(pops_dst.read_text(), "elaadnl_public_eu") == el_sha_before


def test_elaadnl_calibrate_leaves_other_blocks_untouched(tmp_path):
    pops_dst = tmp_path / "populations.yaml"
    shutil.copy(CONFIG_DIR / "populations.yaml", pops_dst)
    acn_sha_before = _block_sha(pops_dst.read_text(), "acn_workplace_baseline")
    ev_sha_before = _block_sha(pops_dst.read_text(), "evwatts_workplace_public")
    inl_sha_before = _block_sha(pops_dst.read_text(), "inl_residential_legacy")

    cache = tmp_path / "elaadnl_cache"
    _seed_elaadnl_cache(cache)

    calibrate_populations(
        populations_yaml_path=pops_dst,
        population_names=["elaadnl_public_eu"],
        cache_dir=cache,
        artifact_dir=tmp_path / "art",
        source_configs={"elaadnl_open_2020": {
            "archive_tag": "fixture",
            "venue_filter": "public",
            "cache_dir": cache,
        }},
    )

    assert _block_sha(pops_dst.read_text(), "acn_workplace_baseline") == acn_sha_before
    assert _block_sha(pops_dst.read_text(), "evwatts_workplace_public") == ev_sha_before
    assert _block_sha(pops_dst.read_text(), "inl_residential_legacy") == inl_sha_before


def test_evwatts_calibrate_writes_only_target_block(tmp_path):
    """Calibrating evwatts_workplace_public must NOT also write to evwatts_dcfc_public."""
    pops_dst = tmp_path / "populations.yaml"
    shutil.copy(CONFIG_DIR / "populations.yaml", pops_dst)
    dcfc_sha_before = _block_sha(pops_dst.read_text(), "evwatts_dcfc_public")

    cache = tmp_path / "evwatts_cache"
    _seed_evwatts_cache(cache)

    calibrate_populations(
        populations_yaml_path=pops_dst,
        population_names=["evwatts_workplace_public"],
        cache_dir=cache,
        artifact_dir=tmp_path / "art",
        source_configs={"evwatts": {
            "release_tag": "fixture",
            "venue_filter": "workplace_public",
            "cache_dir": cache,
        }},
    )
    assert _block_sha(pops_dst.read_text(), "evwatts_dcfc_public") == dcfc_sha_before


# ──────────────────────────────────────────────────────────────────────
# CLI --source-arg [policy:]key=value scoping
# ──────────────────────────────────────────────────────────────────────
def _populations_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / "configs"
    cfg.mkdir()
    for f in CONFIG_DIR.glob("*.yaml"):
        if f.name == "populations.yaml":
            shutil.copy(f, cfg / f.name)
        else:
            (cfg / f.name).symlink_to(f)
    return cfg


def test_source_arg_evwatts_scoping_via_cli(tmp_path):
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "evwatts_cache"
    _seed_evwatts_cache(cache)

    rc = main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "evwatts_workplace_public",
        "--source-arg", "evwatts:release_tag=fixture",
        "--source-arg", "evwatts:venue_filter=workplace_public",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])
    assert rc == 0
    data = pyyaml.safe_load((cfg / "populations.yaml").read_text())
    meta = data["evwatts_workplace_public"]["calibration_metadata"]
    assert meta["dataset"] == "EV WATTS (DOE/EPRI)"
    assert meta["user_id_strategy"] == "port_proxy"


def test_inl_alias_routes_to_inl_ev_project_policy(tmp_path):
    """`inl:` prefix is shorthand for the full `inl_ev_project:` policy key."""
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "inl_cache"
    _seed_inl_cache(cache)

    rc = main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "inl_residential_legacy",
        "--source-arg", "inl:archive_tag=fixture",
        "--source-arg", "inl:venue_filter=residential",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])
    assert rc == 0
    data = pyyaml.safe_load((cfg / "populations.yaml").read_text())
    meta = data["inl_residential_legacy"]["calibration_metadata"]
    assert meta["dataset"] == "INL EV Project Phase 1"
    assert meta["fleet_era"] == "phase1_2011_2013"
    assert meta["user_id_strategy"] == "vin_proxy"


def test_elaadnl_alias_routes_to_elaadnl_open_2020_policy(tmp_path):
    """`elaadnl:` prefix is shorthand for the full `elaadnl_open_2020:` policy key."""
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "elaadnl_cache"
    _seed_elaadnl_cache(cache)

    rc = main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "elaadnl_public_eu",
        "--source-arg", "elaadnl:archive_tag=fixture",
        "--source-arg", "elaadnl:venue_filter=public",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])
    assert rc == 0
    data = pyyaml.safe_load((cfg / "populations.yaml").read_text())
    meta = data["elaadnl_public_eu"]["calibration_metadata"]
    # dataset name updated to reflect real-data source (4TU Utrecht), but
    # the ElaadNL/4TU prefix is preserved for substring identification.
    assert "ElaadNL" in meta["dataset"]
    assert meta["geography"] == "NL_EU"
    assert meta["user_id_strategy"] == "card_proxy"


def test_unscoped_source_arg_routes_to_population_policy(tmp_path):
    """`--source-arg key=value` (no prefix) routes to the targeted population's policy."""
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "evwatts_cache"
    _seed_evwatts_cache(cache)

    rc = main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "evwatts_workplace_public",
        "--source-arg", "release_tag=fixture",
        "--source-arg", "venue_filter=workplace_public",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])
    assert rc == 0
    data = pyyaml.safe_load((cfg / "populations.yaml").read_text())
    assert data["evwatts_workplace_public"]["calibration_metadata"]["release_tag"] == "fixture"


# ──────────────────────────────────────────────────────────────────────
# Descriptor loader provenance strings for evwatts + inl
# ──────────────────────────────────────────────────────────────────────
def test_descriptor_loader_emits_evwatts_calibration_source(tmp_path):
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "evwatts_cache"
    _seed_evwatts_cache(cache)
    main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "evwatts_workplace_public",
        "--source-arg", "evwatts:release_tag=fixture",
        "--source-arg", "evwatts:venue_filter=workplace_public",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])

    out = expand_descriptors(
        descriptors={
            "location": "nashville_tn",
            "building": "medium_office_v1",
            "population": "evwatts_workplace_public",
            "equipment": "balanced_50pct",
            "noise": "clean",
        },
        config_dir=cfg,
    )
    deep = {k: v for k, v in out.items()
            if k.startswith("user_behavior.region_distributions.")}
    assert deep, "evwatts_workplace_public should expose calibrated region_distributions"
    sources = {v[1] for v in deep.values()}
    assert all(s.startswith("calibration:evwatts_") for s in sources), sources


def test_descriptor_loader_emits_inl_calibration_source(tmp_path):
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "inl_cache"
    _seed_inl_cache(cache)
    main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "inl_residential_legacy",
        "--source-arg", "inl:archive_tag=fixture",
        "--source-arg", "inl:venue_filter=residential",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])

    out = expand_descriptors(
        descriptors={
            "location": "nashville_tn",
            "building": "medium_office_v1",
            "population": "inl_residential_legacy",
            "equipment": "balanced_50pct",
            "noise": "clean",
        },
        config_dir=cfg,
    )
    deep = {k: v for k, v in out.items()
            if k.startswith("user_behavior.region_distributions.")}
    assert deep, "inl_residential_legacy should expose calibrated region_distributions"
    sources = {v[1] for v in deep.values()}
    assert all(s.startswith("calibration:inl_ev_project_") for s in sources), sources


def test_descriptor_loader_emits_elaadnl_calibration_source(tmp_path):
    cfg = _populations_dir(tmp_path)
    cache = tmp_path / "elaadnl_cache"
    _seed_elaadnl_cache(cache)
    main([
        "--config-dir", str(cfg), "calibrate",
        "--population", "elaadnl_public_eu",
        "--source-arg", "elaadnl:archive_tag=fixture",
        "--source-arg", "elaadnl:venue_filter=public",
        "--cache-dir", str(cache),
        "--artifact-dir", str(tmp_path / "art"),
    ])

    out = expand_descriptors(
        descriptors={
            "location": "nashville_tn",
            "building": "medium_office_v1",
            "population": "elaadnl_public_eu",
            "equipment": "balanced_50pct",
            "noise": "clean",
        },
        config_dir=cfg,
    )
    deep = {k: v for k, v in out.items()
            if k.startswith("user_behavior.region_distributions.")}
    assert deep, "elaadnl_public_eu should expose calibrated region_distributions"
    sources = {v[1] for v in deep.values()}
    assert all(s.startswith("calibration:elaadnl_open_2020_") for s in sources), sources


# ──────────────────────────────────────────────────────────────────────
# Multi-source orchestration: calibrate ALL eligible policies in one call
# ──────────────────────────────────────────────────────────────────────
def test_calibrate_multiple_sources_in_one_orchestration_call(tmp_path):
    """Single calibrate_populations call with evwatts + inl source_configs
    populates BOTH populations without crashing."""
    pops_dst = tmp_path / "populations.yaml"
    shutil.copy(CONFIG_DIR / "populations.yaml", pops_dst)
    acn_sha_before = _block_sha(pops_dst.read_text(), "acn_workplace_baseline")

    ev_cache = tmp_path / "evwatts_cache"
    in_cache = tmp_path / "inl_cache"
    _seed_evwatts_cache(ev_cache)
    _seed_inl_cache(in_cache)

    calibrate_populations(
        populations_yaml_path=pops_dst,
        population_names=["evwatts_workplace_public", "inl_residential_legacy"],
        cache_dir=tmp_path,
        artifact_dir=tmp_path / "art",
        source_configs={
            "evwatts": {
                "release_tag": "fixture", "venue_filter": "workplace_public",
                "cache_dir": ev_cache,
            },
            "inl_ev_project": {
                "archive_tag": "fixture", "venue_filter": "residential",
                "cache_dir": in_cache,
            },
        },
    )

    data = pyyaml.safe_load(pops_dst.read_text())
    assert data["evwatts_workplace_public"].get("calibration_metadata", {}).get("dataset") \
        == "EV WATTS (DOE/EPRI)"
    assert data["inl_residential_legacy"].get("calibration_metadata", {}).get("dataset") \
        == "INL EV Project Phase 1"
    # ACN untouched by the multi-source run.
    assert _block_sha(pops_dst.read_text(), "acn_workplace_baseline") == acn_sha_before
