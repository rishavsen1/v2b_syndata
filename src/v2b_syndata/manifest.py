"""Build manifest.json for reproducibility records."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from . import __version__
from .types import ResolvedKnobs

CSV_NAMES = [
    "building_load",
    "cars",
    "users",
    "chargers",
    "grid_prices",
    "dr_events",
    "sessions",
]


def _git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, cwd=str(Path(__file__).parent),
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return "unknown"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    output_dir: Path,
    scenario_id: str,
    seed: int,
    resolved: ResolvedKnobs,
    cli_overrides: dict[str, Any],
    noise_profile: str,
) -> dict[str, Any]:
    csv_paths = {name: output_dir / f"{name}.csv" for name in CSV_NAMES}
    csv_row_counts: dict[str, int] = {}
    csv_sha256: dict[str, str] = {}
    for name, p in csv_paths.items():
        if not p.exists():
            raise FileNotFoundError(f"missing CSV {p}")
        # Row count = lines − 1 (subtract header)
        with p.open() as f:
            csv_row_counts[name] = max(0, sum(1 for _ in f) - 1)
        csv_sha256[name] = _file_sha256(p)

    manifest = {
        "scenario_id": scenario_id,
        "seed": seed,
        "knob_overrides": cli_overrides,
        "knob_resolution": resolved.as_dict(),
        "noise_profile": noise_profile,
        "generator_git_sha": _git_sha(),
        "generator_version": __version__,
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "csv_row_counts": csv_row_counts,
        "csv_sha256": csv_sha256,
    }
    out = output_dir / "manifest.json"
    with out.open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest
