"""V4: determinism stress tests.

Asserts D53 bitwise reproducibility under: repeated invocation, knob overrides,
noise, seed variation, cross-scenario isolation, subprocess invocations, and
edge-case seeds (0, negative, very large).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"

CSV_FILES = [
    "building_load.csv", "cars.csv", "users.csv", "chargers.csv",
    "sessions.csv", "grid_prices.csv",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gen(out: Path, scenario: str = "S01", seed: int = 42,
         overrides: dict | None = None) -> None:
    generate(
        scenario_id=scenario, seed=seed, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=overrides or {},
        noise_profile_override=None,
    )


def test_bitwise_determinism_10_runs(tmp_path_factory: pytest.TempPathFactory):
    """Same scenario + seed, 10 runs → every CSV hashes identical."""
    outs = []
    for i in range(10):
        out = tmp_path_factory.mktemp(f"det_{i}")
        _gen(out)
        outs.append(out)
    for csv in CSV_FILES:
        hashes = [_sha(d / csv) for d in outs]
        assert len(set(hashes)) == 1, (
            f"{csv} produced {len(set(hashes))} distinct hashes across 10 runs"
        )


def test_bitwise_determinism_with_overrides(tmp_path_factory: pytest.TempPathFactory):
    overrides = {
        "ev_fleet.ev_count": 30,
        "user_behavior.min_depart_soc": 0.85,
        "charging_infra.directionality_frac": 0.75,
    }
    outs = []
    for i in range(5):
        out = tmp_path_factory.mktemp(f"det_ov_{i}")
        _gen(out, overrides=overrides)
        outs.append(out)
    for csv in CSV_FILES:
        hashes = [_sha(d / csv) for d in outs]
        assert len(set(hashes)) == 1, f"{csv} non-deterministic under overrides"


def test_bitwise_determinism_under_noise(tmp_path_factory: pytest.TempPathFactory):
    outs = []
    for i in range(5):
        out = tmp_path_factory.mktemp(f"det_noise_{i}")
        _gen(out, overrides={"noise.profile": "adversarial"})
        outs.append(out)
    for csv in CSV_FILES:
        hashes = [_sha(d / csv) for d in outs]
        assert len(set(hashes)) == 1, f"{csv} non-deterministic under noise"


def test_seed_variation_produces_distinct_outputs(tmp_path_factory: pytest.TempPathFactory):
    """10 different seeds → ≥9 distinct sessions.csv hashes. All pass validate."""
    hashes_by_seed: dict[int, str] = {}
    for seed in range(10):
        out = tmp_path_factory.mktemp(f"seed_{seed}")
        _gen(out, seed=seed)
        rep = validate(out, strict=False)
        # F4/F5 may flag small-sample share drift; accept schema/referential only.
        serious = [e for e in rep.errors if e.startswith(("A", "B", "C", "I", "D"))]
        assert not serious, f"seed {seed}: {serious[:2]}"
        hashes_by_seed[seed] = _sha(out / "sessions.csv")
    unique = len(set(hashes_by_seed.values()))
    assert unique >= 9, (
        f"only {unique} distinct session hashes across 10 seeds — seed may not be varying outputs"
    )


def test_cross_scenario_seed_isolation(tmp_path_factory: pytest.TempPathFactory):
    out_a = tmp_path_factory.mktemp("xa")
    out_b = tmp_path_factory.mktemp("xb")
    _gen(out_a, scenario="S01")
    _gen(out_b, scenario="S_dr_cbp")
    a = _sha(out_a / "sessions.csv")
    b = _sha(out_b / "sessions.csv")
    assert a != b, "same seed across different scenarios produced identical sessions"


def test_determinism_across_process_invocations(tmp_path_factory: pytest.TempPathFactory):
    """Subprocess re-invocation — catches PYTHONHASHSEED / lazy-init non-determinism."""
    hashes: list[dict[str, str]] = []
    for i in range(5):
        out = tmp_path_factory.mktemp(f"proc_{i}")
        r = subprocess.run(
            [sys.executable, "-m", "v2b_syndata.cli",
             "--config-dir", str(CONFIG_DIR), "generate",
             "--scenario", "S01", "--seed", "42",
             "--output-dir", str(out)],
            capture_output=True, text=True, cwd=REPO,
        )
        assert r.returncode == 0, f"subprocess {i}: {r.stderr[-500:]}"
        hashes.append({c: _sha(out / c) for c in CSV_FILES})
    for csv in CSV_FILES:
        col = [h[csv] for h in hashes]
        assert len(set(col)) == 1, f"{csv} non-deterministic across subprocess starts"


def test_seed_zero_is_valid(tmp_path: Path):
    out_a = tmp_path / "z_a"
    out_b = tmp_path / "z_b"
    _gen(out_a, seed=0)
    _gen(out_b, seed=0)
    for csv in CSV_FILES:
        assert _sha(out_a / csv) == _sha(out_b / csv), f"seed=0 non-deterministic for {csv}"


def test_negative_seed_handled(tmp_path: Path):
    """Negative seed accepted → must be deterministic; or rejected consistently."""
    try:
        out_a = tmp_path / "n_a"
        _gen(out_a, seed=-1)
    except (ValueError, OverflowError, TypeError) as e:
        # Re-raise must be consistent
        with pytest.raises(type(e)):
            out_b = tmp_path / "n_b"
            _gen(out_b, seed=-1)
        return
    # Accepted — assert determinism
    out_b = tmp_path / "n_b"
    _gen(out_b, seed=-1)
    for csv in CSV_FILES:
        assert _sha(out_a / csv) == _sha(out_b / csv), f"seed=-1 non-deterministic for {csv}"


@pytest.mark.parametrize("seed", [2**31 - 1, 2**31, 2**32 - 1])
def test_large_seed_handled(seed: int, tmp_path: Path):
    """Large seeds → deterministic or consistently rejected."""
    try:
        a = tmp_path / f"big_a_{seed}"
        _gen(a, seed=seed)
    except (ValueError, OverflowError, TypeError) as e:
        with pytest.raises(type(e)):
            b = tmp_path / f"big_b_{seed}"
            _gen(b, seed=seed)
        return
    b = tmp_path / f"big_b_{seed}"
    _gen(b, seed=seed)
    for csv in CSV_FILES:
        assert _sha(a / csv) == _sha(b / csv), f"seed={seed} non-deterministic for {csv}"
