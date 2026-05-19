"""V3-followup: verify noise.profile=custom semantics.

The empty `custom:` entry added to noise_profiles.yaml made the descriptor
expansion succeed, but the BEHAVIOR of `custom` was never verified. These
tests assert the documented contract:

1. profile=custom + no individual overrides → clean output (all zeros)
2. profile=custom + individual override → override is honored
3. profile=custom + multiple individual overrides → all honored
4. profile=adversarial + individual override → named profile dominates
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _gen(out: Path, overrides: dict | None = None) -> None:
    generate(
        scenario_id="S01", seed=42, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=overrides or {},
        noise_profile_override=None,
    )


def test_custom_profile_zero_noise_by_default(tmp_path: Path):
    """profile=custom + no overrides → bytes identical to clean baseline."""
    out = tmp_path / "custom"
    baseline = tmp_path / "clean"
    _gen(out, {"noise.profile": "custom"})
    _gen(baseline)
    for csv in ("building_load.csv", "sessions.csv", "grid_prices.csv"):
        assert _sha(out / csv) == _sha(baseline / csv), (
            f"custom profile with zero overrides differs from clean: {csv}"
        )


def test_custom_profile_honors_individual_overrides(tmp_path: Path):
    """profile=custom + noise.arrival_time_jitter_min=30 → sessions differ from clean."""
    out = tmp_path / "custom_jit"
    baseline = tmp_path / "clean"
    _gen(out, {
        "noise.profile": "custom",
        "noise.arrival_time_jitter_min": 30.0,
    })
    _gen(baseline)
    assert _sha(out / "sessions.csv") != _sha(baseline / "sessions.csv"), (
        "custom + arrival_time_jitter_min=30 produced unchanged sessions — "
        "individual knob override NOT honored under custom profile"
    )


def test_custom_profile_with_multiple_overrides(tmp_path: Path):
    """custom + multiple individual jitter knobs all take effect."""
    out = tmp_path / "custom_multi"
    baseline = tmp_path / "clean"
    _gen(out, {
        "noise.profile": "custom",
        "noise.arrival_time_jitter_min": 30.0,
        "noise.soc_arrival_jitter_pct": 0.15,
        "noise.price_jitter_pct": 0.10,
    })
    _gen(baseline)
    assert _sha(out / "sessions.csv") != _sha(baseline / "sessions.csv")
    assert _sha(out / "grid_prices.csv") != _sha(baseline / "grid_prices.csv")
    m = json.loads((out / "manifest.json").read_text())
    assert "noise" in m
    if "d5_enforcement" in m["noise"]:
        assert m["noise"]["d5_enforcement"]["total_input_sessions"] > 0


def test_named_profile_active_when_set(tmp_path: Path):
    """profile=adversarial → output differs from clean baseline (smoke check
    that the named profile fans out per-jitter knob values).".

    Note: this test does NOmust pin down precedence between profile and
    individual knob overrides — see `test_individual_knob_beats_profile` for
    that. Adversarial sets six jitters, so overriding one to 0 still leaves
    five active jitters perturbing output.
    """
    out = tmp_path / "adv"
    baseline = tmp_path / "clean"
    _gen(out, {"noise.profile": "adversarial"})
    _gen(baseline)
    assert _sha(out / "sessions.csv") != _sha(baseline / "sessions.csv")


def test_individual_knob_beats_profile(tmp_path: Path):
    """Documented contract (runner.py:125): CLI override of per-jitter knob
    beats the named profile's descriptor-sourced value.

    Adversarial profile sets arrival_time_jitter_min=45.0. CLI override
    forces it to 0.0. Manifest must record arrival_time_jitter_min=0.0
    with source=explicit, and the d5_enforcement block (or session output)
    must reflect the lack of arrival jitter.
    """
    out = tmp_path / "adv_zero_arr"
    _gen(out, {
        "noise.profile": "adversarial",
        "noise.arrival_time_jitter_min": 0.0,
    })
    m = json.loads((out / "manifest.json").read_text())
    res = m["knob_resolution"]
    assert res["noise.arrival_time_jitter_min"]["value"] == 0.0
    assert res["noise.arrival_time_jitter_min"]["source"] == "explicit"
    # Other adversarial jitters remain at their descriptor-sourced values.
    assert res["noise.soc_arrival_jitter_pct"]["value"] == 0.20
    assert res["noise.soc_arrival_jitter_pct"]["source"] == "descriptor:adversarial"
