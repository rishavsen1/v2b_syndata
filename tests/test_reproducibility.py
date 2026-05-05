"""Same scenario_id + seed → identical CSV bytes (manifest.csv_sha256 dict)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from v2b_syndata.runner import generate


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_same_seed_yields_identical_csvs(tmp_path, config_dir):
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate("S01", seed=42, output_dir=a, config_dir=config_dir)
    generate("S01", seed=42, output_dir=b, config_dir=config_dir)
    csv_names = ["building_load", "cars", "users", "chargers",
                 "grid_prices", "dr_events", "sessions"]
    for n in csv_names:
        sa = _sha(a / f"{n}.csv")
        sb = _sha(b / f"{n}.csv")
        assert sa == sb, f"{n}.csv bytes differ across runs"


def test_different_seed_diverges(tmp_path, config_dir):
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate("S01", seed=42, output_dir=a, config_dir=config_dir)
    generate("S01", seed=43, output_dir=b, config_dir=config_dir)
    # Sessions and users will differ with different seed
    assert _sha(a / "users.csv") != _sha(b / "users.csv")
