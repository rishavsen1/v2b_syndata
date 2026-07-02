"""Batch generation: tree layout, manifest, parallelism, --force."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "v2b_syndata.cli", *args],
        capture_output=True, text=True, timeout=600,
        cwd=str(REPO),
    )


def test_months_between():
    from v2b_syndata.batch import _months_between
    out = _months_between("2024-04", "2024-06")
    assert [lbl for lbl, _ in out] == ["APR2024", "MAY2024", "JUN2024"]


def test_batch_cli_produces_tree(tmp_path: Path):
    out = tmp_path / "batch"
    r = _run([
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-05",
        "--samples-per-month", "2", "--workers", "2",
    ])
    assert r.returncode == 0, r.stderr[-500:]

    # tree
    assert (out / "batch_manifest.json").exists()
    for month in ("APR2024", "MAY2024"):
        for idx in (0, 1):
            sd = out / "S01" / month / str(idx)
            assert sd.exists(), f"missing {sd}"
            for csv in ("building_load.csv", "cars.csv", "sessions.csv",
                        "manifest.json"):
                assert (sd / csv).exists(), f"missing {sd / csv}"

    # manifest content
    m = json.loads((out / "batch_manifest.json").read_text())
    assert m["status"] == "succeeded"
    assert m["n_total"] == 4
    assert m["n_succeeded"] == 4
    assert m["n_failed"] == 0
    samples = m["samples"]
    assert {s["month"] for s in samples} == {"APR2024", "MAY2024"}


def test_batch_manifest_has_validation_summary(tmp_path: Path):
    """The batch manifest aggregates each sample's auto-validation into a
    validation_summary, and each sample record carries its own validation."""
    out = tmp_path / "batch_vs"
    r = _run([
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-04",
        "--samples-per-month", "2", "--workers", "1",
    ])
    assert r.returncode == 0, r.stderr[-500:]
    m = json.loads((out / "batch_manifest.json").read_text())
    vs = m["validation_summary"]
    assert vs["n_units"] == 2
    assert vs["n_passed"] + vs["n_failed"] == 2
    assert "total_errors" in vs and "failed_units" in vs
    for s in m["samples"]:
        if s["status"] == "succeeded":
            assert s["validation"] is not None
            assert "passed" in s["validation"] and "n_errors" in s["validation"]
    # CLI prints the summary line to stderr.
    assert "validation:" in r.stderr


def test_batch_force_flag_required(tmp_path: Path):
    out = tmp_path / "b"
    args = [
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-04",
        "--samples-per-month", "1", "--workers", "1",
    ]
    r1 = _run(args)
    assert r1.returncode == 0

    r2 = _run(args)
    assert r2.returncode != 0
    assert "exists" in (r2.stderr + r2.stdout).lower()

    r3 = _run(args + ["--force"])
    assert r3.returncode == 0


def test_batch_seed_strategy_linear(tmp_path: Path):
    out = tmp_path / "seeds"
    r = _run([
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-04",
        "--samples-per-month", "3", "--workers", "1",
        "--seed-base", "10",
    ])
    assert r.returncode == 0
    m = json.loads((out / "batch_manifest.json").read_text())
    seeds_for_apr = sorted(s["seed"] for s in m["samples"] if s["month"] == "APR2024")
    assert seeds_for_apr == [10, 11, 12]


def test_batch_uses_tmyx_stochastic_by_default(tmp_path: Path):
    out = tmp_path / "default"
    _run([
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-04",
        "--samples-per-month", "1", "--workers", "1",
    ])
    m = json.loads((out / "batch_manifest.json").read_text())
    assert m["noise_profile"] == "tmyx_stochastic"


def test_batch_samples_vary_under_default(tmp_path: Path):
    import hashlib
    out = tmp_path / "var"
    r = _run([
        "batch", "--scenario", "S01",
        "--output-dir", str(out),
        "--start-month", "2024-04", "--end-month", "2024-04",
        "--samples-per-month", "2", "--workers", "2",
    ])
    assert r.returncode == 0
    h0 = hashlib.sha256((out / "S01" / "APR2024" / "0" / "building_load.csv").read_bytes()).hexdigest()
    h1 = hashlib.sha256((out / "S01" / "APR2024" / "1" / "building_load.csv").read_bytes()).hexdigest()
    assert h0 != h1, "building_load must vary across seeds under tmyx_stochastic"
