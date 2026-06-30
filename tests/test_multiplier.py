"""Tests for the per-building `multiplier` expansion in multi-building configs.

`multiplier: N` on a building entry expands it into N DISTINCT realizations of
the same config, replica k (k=0..N-1) getting seed `base_seed + k`. building_id
is assigned sequentially across the fully expanded ordered list. The recorded
`multi_building_config.json` stores the expanded list (no `multiplier`), so
`--from-config` reproduces byte-identically without re-expanding.

Reuses the synthetic-EPW `stub_weather` fixture pattern from
`test_multi_building.py` (no EnergyPlus; non-leap window).
"""
from __future__ import annotations

import filecmp
import json
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata import export_optimus as exp
from v2b_syndata.multi_building import (
    BuildingSpec,
    MultiConfig,
    config_from_dict,
    generate_multi,
    generate_multi_batch,
    regenerate_from_config,
)

_FAST = {
    "sim_window.mode": "custom",
    "sim_window.start": "2021-09-01",
    "sim_window.custom_end": "2021-09-08",
    "ev_fleet.ev_count": 4,
    "charging_infra.charger_count": 4,
}


def _write_epw(path: Path, year: int = 2021) -> Path:
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    lines = ["LOCATION,Test"] + ["HEADER"] * 7
    for ts in idx:
        cols = ["0"] * 22
        cols[1], cols[2], cols[3] = str(ts.month), str(ts.day), str(ts.hour + 1)
        cols[6], cols[7], cols[8], cols[21] = "15.0", "5.0", "50.0", "2.5"
        if 6 <= ts.hour <= 20:
            cols[13] = cols[14] = cols[15] = "300"
        lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def stub_weather(tmp_path, monkeypatch):
    epw = _write_epw(tmp_path / "fixture.epw", year=2021)
    monkeypatch.setattr(exp.weather, "get_weather_epw", lambda *a, **k: epw)
    return epw


def _entry(seed: int, *, multiplier: int | None = None, overrides_extra=None) -> dict:
    ov = dict(_FAST)
    if overrides_extra:
        ov.update(overrides_extra)
    e: dict = {
        "base_scenario": "S01",
        "descriptors": {"location": "nashville_tn"},
        "overrides": ov,
        "seed": seed,
    }
    if multiplier is not None:
        e["multiplier"] = multiplier
    return e


# ── parsing / expansion semantics (no generation needed) ────────────────────

def test_multiplier_default_one_matches_no_multiplier():
    """multiplier=1 and an absent multiplier produce identical specs (back-compat)."""
    plain = config_from_dict({"buildings": [_entry(42), _entry(7)]})
    explicit = config_from_dict({
        "buildings": [_entry(42, multiplier=1), _entry(7, multiplier=1)]
    })
    assert [s.seed for s in plain.buildings] == [42, 7]
    assert [s.seed for s in explicit.buildings] == [42, 7]
    assert [s.base_scenario for s in plain.buildings] == \
           [s.base_scenario for s in explicit.buildings]


def test_multiplier_n_expands_to_n_distinct_seeds():
    """multiplier=N → exactly N specs, contiguous seeds base..base+N-1, distinct."""
    cfg = config_from_dict({"buildings": [_entry(100, multiplier=4)]})
    assert len(cfg.buildings) == 4
    seeds = [s.seed for s in cfg.buildings]
    assert seeds == [100, 101, 102, 103]
    assert len(set(seeds)) == 4
    # same config otherwise (descriptors/overrides/scenario shared)
    for s in cfg.buildings:
        assert s.base_scenario == "S01"
        assert s.descriptors == {"location": "nashville_tn"}


def test_multiplier_composes_with_multiple_entries_contiguous_ids():
    """Multipliers compose across entries; building_id is sequential over the
    fully expanded list (verified via the recorded config)."""
    cfg = config_from_dict({"buildings": [
        _entry(10, multiplier=3),   # seeds 10,11,12
        _entry(50, multiplier=2),   # seeds 50,51
        _entry(99),                 # seed 99
    ]})
    assert [s.seed for s in cfg.buildings] == [10, 11, 12, 50, 51, 99]
    rec = generate_multi.__globals__["_config_dict"](cfg)
    ids = [b["building_id"] for b in rec["buildings"]]
    assert ids == [0, 1, 2, 3, 4, 5]
    # multiplier must NOT leak into the recorded expanded config
    assert all("multiplier" not in b for b in rec["buildings"])


def test_recorded_config_has_no_multiplier_and_reexpands_to_same():
    """The recorded expanded config, fed back through config_from_dict (each
    entry now multiplier-less => default 1), yields the SAME spec list."""
    cfg = config_from_dict({"buildings": [_entry(200, multiplier=3)]})
    rec = generate_multi.__globals__["_config_dict"](cfg)
    cfg2 = config_from_dict(rec)
    assert [s.seed for s in cfg2.buildings] == [s.seed for s in cfg.buildings]
    assert len(cfg2.buildings) == 3


# ── validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [0, -1, -5])
def test_multiplier_less_than_one_raises(bad):
    with pytest.raises(ValueError, match=r"multiplier must be >= 1"):
        config_from_dict({"buildings": [_entry(1, multiplier=bad)]})


@pytest.mark.parametrize("bad", [2.0, "3", None, [2]])
def test_multiplier_non_int_raises(bad):
    with pytest.raises(ValueError, match=r"multiplier must be an integer"):
        config_from_dict({"buildings": [{
            "base_scenario": "S01", "seed": 1, "multiplier": bad,
        }]})


def test_multiplier_true_bool_rejected():
    """bool is an int subclass but is not a valid multiplier."""
    with pytest.raises(ValueError, match=r"multiplier must be an integer"):
        config_from_dict({"buildings": [{
            "base_scenario": "S01", "seed": 1, "multiplier": True,
        }]})


def test_duplicate_seed_across_expanded_list_warns():
    """Overlapping seed ranges across entries → duplicate-seed warning."""
    with pytest.warns(UserWarning, match=r"duplicate seed"):
        cfg = config_from_dict({"buildings": [
            _entry(100, multiplier=3),  # 100,101,102
            _entry(102, multiplier=2),  # 102,103  → 102 collides
        ]})
    assert [s.seed for s in cfg.buildings] == [100, 101, 102, 102, 103]


def test_no_warning_when_seeds_spaced():
    """Spaced seed ranges → no warning."""
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("error")  # any warning becomes an error
        cfg = config_from_dict({"buildings": [
            _entry(100, multiplier=3),   # 100,101,102
            _entry(200, multiplier=2),   # 200,201
        ]})
    assert [s.seed for s in cfg.buildings] == [100, 101, 102, 200, 201]


# ── end-to-end generation ────────────────────────────────────────────────────

def test_generate_multiplier_n_buildings_and_distinct_outputs(
    tmp_path, config_dir, stub_weather
):
    """multiplier=3 → 3 buildings (ids 0,1,2) whose sessions DIFFER (distinct
    realizations, not byte-identical copies)."""
    cfg = config_from_dict({
        "output_mode": "shared",
        "buildings": [_entry(500, multiplier=3)],
    })
    out = tmp_path / "mult"
    config = generate_multi(cfg, out, config_dir)

    # exactly 3 buildings, contiguous ids, 3 distinct seeds in the recorded config
    assert len(config["buildings"]) == 3
    assert [b["building_id"] for b in config["buildings"]] == [0, 1, 2]
    assert sorted(b["seed"] for b in config["buildings"]) == [500, 501, 502]
    assert all("multiplier" not in b for b in config["buildings"])

    cars = pd.read_csv(out / "cars.csv", index_col=0)
    assert sorted(cars["building_id"].unique()) == [0, 1, 2]

    # the three replicas are DISTINCT: per-building session payload differs.
    sessions = pd.read_csv(out / "sessions.csv")
    cols = [c for c in sessions.columns if c != "building_id"]
    sigs = {
        bid: sessions[sessions["building_id"] == bid][cols]
        .reset_index(drop=True).to_csv(index=False)
        for bid in (0, 1, 2)
    }
    assert sigs[0] != sigs[1] != sigs[2] and sigs[0] != sigs[2], \
        "replicas are byte-identical copies, not distinct realizations"


def test_multiplier_composes_with_batch_samples(tmp_path, config_dir, stub_weather):
    """multiplier expands buildings; the batch samples layer then offsets each
    replica seed by seed_base+sample, staying distinct & deterministic."""
    cfg = config_from_dict({
        "output_mode": "shared",
        "buildings": [{
            "base_scenario": "S01",
            "descriptors": {"location": "nashville_tn"},
            "overrides": {"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
            "seed": 1000,
            "multiplier": 2,   # replicas seeds 1000, 1001
        }],
    })
    out = tmp_path / "batch"
    manifest = generate_multi_batch(
        cfg, out, config_dir, start_month="2021-09", end_month="2021-09",
        samples_per_month=2, workers=1, noise_profile="clean",
    )
    assert manifest["status"] == "succeeded"
    assert manifest["n_buildings"] == 2

    for s in (0, 1):
        unit_cfg = json.loads(
            (out / "SEP2021" / str(s) / "multi_building_config.json").read_text())
        seeds = sorted(b["seed"] for b in unit_cfg["buildings"])
        # replica seed (1000/1001) + seed_base(0) + sample(s)
        assert seeds == [1000 + s, 1001 + s], f"sample {s}: {seeds}"
        cars = pd.read_csv(out / "SEP2021" / str(s) / "cars.csv", index_col=0)
        assert sorted(cars["building_id"].unique()) == [0, 1]


def test_regenerate_from_multiplier_config_byte_identical(
    tmp_path, config_dir, stub_weather
):
    """A run that USED multiplier regenerates byte-identically from its recorded
    (expanded) config."""
    cfg = config_from_dict({
        "output_mode": "shared",
        "dr_program": "CBP",
        "buildings": [_entry(700, multiplier=3)],
    })
    out1 = tmp_path / "run1"
    generate_multi(cfg, out1, config_dir)

    out2 = tmp_path / "run2"
    regenerate_from_config(out1 / "multi_building_config.json", out2, config_dir)

    for name in ("building_load.csv", "cars.csv", "sessions.csv", "chargers.csv",
                 "grid_prices.csv", "weather_data.csv", "occupancy.csv",
                 "dso_commands.csv", "policies.csv"):
        assert filecmp.cmp(out1 / name, out2 / name, shallow=False), \
            f"{name} not byte-identical after regenerate from multiplier config"


def test_multiplier_one_equals_explicit_specs(tmp_path, config_dir, stub_weather):
    """End-to-end: a single entry with multiplier=1 produces the same CSVs as a
    single hand-written BuildingSpec with that seed (back-compat)."""
    cfg_mult = config_from_dict({
        "output_mode": "shared",
        "buildings": [_entry(321, multiplier=1)],
    })
    out_a = tmp_path / "a"
    generate_multi(cfg_mult, out_a, config_dir)

    cfg_plain = MultiConfig(
        [BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                      overrides=dict(_FAST), seed=321)],
        output_mode="shared",
    )
    out_b = tmp_path / "b"
    generate_multi(cfg_plain, out_b, config_dir)

    for name in ("building_load.csv", "cars.csv", "sessions.csv",
                 "weather_data.csv", "occupancy.csv"):
        assert filecmp.cmp(out_a / name, out_b / name, shallow=False), \
            f"{name} differs between multiplier=1 and explicit spec"
