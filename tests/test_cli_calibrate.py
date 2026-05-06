"""Smoke tests for `calibrate` and `docs-gen` CLI subcommands."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml as pyyaml

from v2b_syndata.cli import main


def _build_synthetic_cache(cache_dir: Path):
    """Mirror of test_e2e_calibration._build_synthetic_fixture (small)."""
    import pandas as pd
    cache_dir.mkdir(parents=True, exist_ok=True)
    rng_uid = 0
    for site in ("caltech", "jpl", "office001"):
        sessions = []
        for _ in range(8):
            rng_uid += 1
            for d in range(12):
                base = pd.Timestamp("2020-01-06", tz="UTC") + pd.Timedelta(days=d * 7)
                arr = base + pd.Timedelta(hours=8.5 + (rng_uid % 3) * 0.3)
                dep = arr + pd.Timedelta(hours=8.0 + (rng_uid % 5) * 0.3)
                fmt = "%a, %d %b %Y %H:%M:%S GMT"
                miles = 30 + (rng_uid % 10) * 5
                wpm = 250 + (rng_uid % 4) * 10
                sessions.append({
                    "userID": rng_uid,
                    "connectionTime": arr.strftime(fmt),
                    "disconnectTime": dep.strftime(fmt),
                    "kWhDelivered": miles * wpm / 1000.0 * 0.95,
                    "userInputs": [{
                        "milesRequested": miles, "WhPerMile": wpm,
                        "kWhRequested": miles * wpm / 1000.0,
                        "minutesAvailable": 480,
                    }],
                })
        (cache_dir / f"{site}_2019_2021.json").write_text(json.dumps(sessions))


def test_calibrate_subcommand_writes_populations_yaml(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ACN_API_TOKEN", "dummy")
    cache = tmp_path / "cache"
    _build_synthetic_cache(cache)
    artifacts = tmp_path / "artifacts"
    cfg = tmp_path / "configs"
    cfg.mkdir()
    src_pops = Path(__file__).resolve().parent.parent / "configs" / "populations.yaml"
    shutil.copy(src_pops, cfg / "populations.yaml")

    rc = main([
        "--config-dir", str(cfg),
        "calibrate",
        "--population", "consent_default",
        "--year-start", "2019", "--year-end", "2021",
        "--cache-dir", str(cache),
        "--artifact-dir", str(artifacts),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "calibration complete" in out
    assert "consent_default" in out

    data = pyyaml.safe_load((cfg / "populations.yaml").read_text())
    assert "region_distributions" in data["consent_default"]
    assert "calibration_metadata" in data["consent_default"]


def test_docs_gen_subcommand_emits_full_reference(tmp_path, capsys):
    src_cfg = Path(__file__).resolve().parent.parent / "configs"
    rc = main(["--config-dir", str(src_cfg), "docs-gen"])
    assert rc == 0
    out = capsys.readouterr().out
    # Must contain every DIST_PARAM_RANGES leaf
    from v2b_syndata.knob_loader import DIST_PARAM_RANGES
    for leaf in DIST_PARAM_RANGES:
        assert leaf in out, f"missing leaf {leaf}"
    # Source-category section
    assert "calibration:" in out
    # Hand-written section excluded from docs-gen (auto-only output here)
    assert "Registry knobs" in out


def test_docs_gen_includes_all_registry_knobs(tmp_path, capsys):
    src_cfg = Path(__file__).resolve().parent.parent / "configs"
    rc = main(["--config-dir", str(src_cfg), "docs-gen"])
    out = capsys.readouterr().out
    from v2b_syndata.knob_loader import all_knob_paths, load_knob_registry
    reg = load_knob_registry(src_cfg / "knobs.yaml")
    for path in all_knob_paths(reg):
        assert path in out, f"missing knob {path}"
