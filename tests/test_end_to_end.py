"""End-to-end: generate S01, every artifact present, validator passes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_s01_generate_validate(tmp_path, config_dir):
    out = tmp_path / "S01_seed42"
    manifest = generate("S01", seed=42, output_dir=out, config_dir=config_dir)
    for name in ("building_load", "cars", "users", "chargers",
                 "grid_prices", "dr_events", "sessions"):
        assert (out / f"{name}.csv").exists(), f"missing {name}.csv"
    assert (out / "manifest.json").exists()
    rep = validate(out)
    assert rep.passed, "S01 hard invariants failed: " + "; ".join(rep.errors)
    assert manifest["scenario_id"] == "S01"
    assert manifest["seed"] == 42


def test_override_recorded_explicit(tmp_path, config_dir):
    out = tmp_path / "out"
    generate(
        "S01", seed=42, output_dir=out, config_dir=config_dir,
        cli_overrides={"ev_fleet.ev_count": 10},
    )
    with (out / "manifest.json").open() as f:
        m = json.load(f)
    assert m["knob_resolution"]["ev_fleet.ev_count"]["value"] == 10
    assert m["knob_resolution"]["ev_fleet.ev_count"]["source"] == "explicit"


def test_noise_profile_changes_output(tmp_path, config_dir):
    """Override on noise.profile must fan out to per-jitter knobs and change bytes."""
    clean = tmp_path / "clean"
    noisy = tmp_path / "noisy"
    clean2 = tmp_path / "clean2"

    generate("S01", seed=42, output_dir=clean, config_dir=config_dir)
    generate("S01", seed=42, output_dir=noisy, config_dir=config_dir,
             cli_overrides={"noise.profile": "light_noise"})
    generate("S01", seed=42, output_dir=clean2, config_dir=config_dir,
             cli_overrides={"noise.profile": "clean"})

    # Light noise must alter both building_load and sessions
    assert _sha(clean / "building_load.csv") != _sha(noisy / "building_load.csv"), \
        "noise.profile=light_noise did not change building_load.csv bytes"
    assert _sha(clean / "sessions.csv") != _sha(noisy / "sessions.csv"), \
        "noise.profile=light_noise did not change sessions.csv bytes"

    # Explicit clean override matches default (no override)
    for n in ("building_load", "sessions", "grid_prices", "dr_events"):
        assert _sha(clean / f"{n}.csv") == _sha(clean2 / f"{n}.csv"), \
            f"clean override changed {n}.csv vs default"

    # Manifest reflects fan-out: per-jitter knobs source = descriptor:light_noise
    with (noisy / "manifest.json").open() as f:
        m = json.load(f)
    res = m["knob_resolution"]
    assert res["noise.profile"]["value"] == "light_noise"
    assert res["noise.profile"]["source"] == "explicit"
    for k in ("building_load_jitter_pct", "arrival_time_jitter_min",
             "soc_arrival_jitter_pct", "occupancy_jitter_pct"):
        assert res[f"noise.{k}"]["source"] == "descriptor:light_noise", \
            f"noise.{k} source != descriptor:light_noise"


def test_noise_profile_repro_within_profile(tmp_path, config_dir):
    """Same seed + same profile → bitwise-identical bytes."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    for d in (a, b):
        generate("S01", seed=42, output_dir=d, config_dir=config_dir,
                 cli_overrides={"noise.profile": "light_noise"})
    for n in ("building_load", "sessions", "grid_prices", "dr_events"):
        assert _sha(a / f"{n}.csv") == _sha(b / f"{n}.csv"), \
            f"{n}.csv reproducibility broken under light_noise"


def test_clean_noise_idempotent_when_overrides_zero(tmp_path, config_dir):
    """Overriding noise jitters to 0 with light_noise profile gives same CSV bytes as clean."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    # Clean profile
    generate("S01", seed=42, output_dir=a, config_dir=config_dir,
             noise_profile_override="clean")
    # Light noise + zero overrides on every jitter
    generate(
        "S01", seed=42, output_dir=b, config_dir=config_dir,
        noise_profile_override="light_noise",
        cli_overrides={
            "noise.building_load_jitter_pct": 0.0,
            "noise.arrival_time_jitter_min": 0.0,
            "noise.soc_arrival_jitter_pct": 0.0,
            "noise.dr_notification_dropout_prob": 0.0,
            "noise.price_jitter_pct": 0.0,
            "noise.occupancy_jitter_pct": 0.0,
        },
    )
    for n in ("building_load", "sessions", "grid_prices", "dr_events"):
        assert Path(a / f"{n}.csv").read_bytes() == Path(b / f"{n}.csv").read_bytes(), \
            f"{n}.csv differs despite zeroed noise"
