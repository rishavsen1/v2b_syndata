"""tmyx_stochastic noise profile — bounded per-seed variation."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _gen(out: Path, seed: int, profile: str | None) -> pd.DataFrame:
    generate(
        scenario_id="S01", seed=seed, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides={},
        noise_profile_override=profile,
    )
    return pd.read_csv(out / "building_load.csv")


def test_tmyx_stochastic_varies_building_load(tmp_path: Path):
    df0 = _gen(tmp_path / "s0", seed=0, profile="tmyx_stochastic")
    df1 = _gen(tmp_path / "s1", seed=1, profile="tmyx_stochastic")
    assert df0["power_kw"].sum() != df1["power_kw"].sum()
    # Means within 10% of each other
    m0, m1 = df0["power_kw"].mean(), df1["power_kw"].mean()
    base = (m0 + m1) / 2
    assert abs(m0 - base) / base < 0.10
    assert abs(m1 - base) / base < 0.10
    # Shape preserved
    assert df0["power_kw"].corr(df1["power_kw"]) > 0.85


def test_clean_profile_no_postrender_jitter(tmp_path: Path):
    """Clean profile zeros post-render noise. Building load STILL varies
    across seeds because the L_flex/L_inflex samplers carry ±5%/±3% per
    BAYES_NET spec. Same seed + clean → identical."""
    a = _gen(tmp_path / "a", seed=42, profile="clean")
    b = _gen(tmp_path / "b", seed=42, profile="clean")
    pd.testing.assert_frame_equal(a, b)


def test_tmyx_stochastic_same_seed_bitwise(tmp_path: Path):
    df0 = _gen(tmp_path / "a", seed=42, profile="tmyx_stochastic")
    df1 = _gen(tmp_path / "b", seed=42, profile="tmyx_stochastic")
    pd.testing.assert_frame_equal(df0, df1)


def test_power_kw_identity_preserved_under_noise(tmp_path: Path):
    df = _gen(tmp_path, seed=0, profile="tmyx_stochastic")
    diff = (df["power_kw"] - (df["power_flex_kw"] + df["power_inflex_kw"])).abs()
    assert diff.max() < 1e-9, f"power_kw drifts from sum: max |diff|={diff.max()}"
