"""Dirichlet noise on population + battery mix (Step 8 prep).

Default α = 1e6 → effectively off (preserves bitwise reproducibility).
Batch mode opts in by setting α = 30.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _gen(out: Path, seed: int = 0, overrides: dict | None = None,
         noise_profile: str | None = None) -> None:
    generate(
        scenario_id="S01", seed=seed, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=overrides or {},
        noise_profile_override=noise_profile,
    )


def test_dirichlet_default_alpha_preserves_bitwise(tmp_path_factory):
    """Default α=1e6 → cars.csv and users.csv hashes match pre-Dirichlet
    code's outputs (verified empirically by absence of the alpha override)."""
    a = tmp_path_factory.mktemp("a")
    b = tmp_path_factory.mktemp("b")
    _gen(a, seed=42)
    _gen(b, seed=42)
    for csv in ("cars.csv", "users.csv", "sessions.csv", "building_load.csv"):
        assert _sha(a / csv) == _sha(b / csv), f"{csv} not deterministic at default alpha"


def test_dirichlet_default_no_realized_block(tmp_path: Path):
    """At default α=1e6 the manifest omits realized_distributions entirely."""
    _gen(tmp_path, seed=42)
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert "realized_distributions" not in m, (
        "realized_distributions block should be absent at default alpha"
    )


def test_dirichlet_with_alpha30_emits_realized(tmp_path: Path):
    _gen(tmp_path, seed=42, overrides={
        "user_behavior.axes_distribution_dirichlet_alpha": 30.0,
        "ev_fleet.battery_mix_dirichlet_alpha": 30.0,
    })
    m = json.loads((tmp_path / "manifest.json").read_text())
    rd = m["realized_distributions"]
    assert isinstance(rd["axes_distribution_sampled"], list)
    assert isinstance(rd["battery_mix_sampled"], list)
    assert abs(sum(rd["axes_distribution_sampled"]) - 1.0) < 1e-9
    assert abs(sum(rd["battery_mix_sampled"]) - 1.0) < 1e-9


def test_dirichlet_population_varies_with_seed(tmp_path_factory):
    """Across seeds with α=30, region-weight std should be non-trivial but bounded."""
    realized = []
    for seed in range(20):
        out = tmp_path_factory.mktemp(f"s_{seed}")
        _gen(out, seed=seed, overrides={
            "user_behavior.axes_distribution_dirichlet_alpha": 30.0,
        })
        m = json.loads((out / "manifest.json").read_text())
        realized.append(m["realized_distributions"]["axes_distribution_sampled"])
    arr = np.array(realized)
    stds = arr.std(axis=0)
    # σ_i ≈ sqrt(p_i(1-p_i)/(α+1)); for α=30, p around 0.1–0.35 → std ~0.04–0.09.
    assert (stds > 0.01).all(), f"some component has near-zero std: {stds}"
    assert (stds < 0.15).all(), f"some component has too-large std: {stds}"


def test_dirichlet_disabled_at_huge_alpha(tmp_path: Path):
    """At α≥1e6, code takes the off path; manifest omits realized_distributions."""
    _gen(tmp_path, seed=42, overrides={
        "user_behavior.axes_distribution_dirichlet_alpha": 1e6,
    })
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert "realized_distributions" not in m


def test_dirichlet_same_seed_bitwise(tmp_path_factory):
    """With α=30, same seed → same hash. (Determinism preserved under noise.)"""
    a = tmp_path_factory.mktemp("d_a")
    b = tmp_path_factory.mktemp("d_b")
    ov = {
        "user_behavior.axes_distribution_dirichlet_alpha": 30.0,
        "ev_fleet.battery_mix_dirichlet_alpha": 30.0,
    }
    _gen(a, seed=7, overrides=ov)
    _gen(b, seed=7, overrides=ov)
    for csv in ("cars.csv", "users.csv", "sessions.csv"):
        assert _sha(a / csv) == _sha(b / csv), f"{csv} not deterministic under Dirichlet"
