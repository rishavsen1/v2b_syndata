"""IO-path tests for validate.py (missing files, malformed manifest).

validate() aggregates errors into the returned ValidationReport rather than
raising — so these tests assert reports flag the missing inputs."""
from __future__ import annotations

import json
from pathlib import Path

from v2b_syndata.validate import validate


def test_validate_empty_dir_reports_missing_csvs(tmp_path: Path):
    rep = validate(tmp_path)
    assert not rep.passed
    # Every schema CSV missing → at least 4 A1 errors.
    a1 = [e for e in rep.errors if "A1:" in e and "missing" in e]
    assert len(a1) >= 4


def test_validate_missing_manifest_flagged(fast_generate):
    out_dir, _ = fast_generate()
    (out_dir / "manifest.json").unlink()
    rep = validate(out_dir)
    assert not rep.passed
    assert any("manifest" in e.lower() or "I1" in e for e in rep.errors)


def test_validate_missing_one_csv_flagged(fast_generate):
    out_dir, _ = fast_generate()
    (out_dir / "cars.csv").unlink()
    rep = validate(out_dir)
    assert not rep.passed
    assert any("cars" in e for e in rep.errors)
