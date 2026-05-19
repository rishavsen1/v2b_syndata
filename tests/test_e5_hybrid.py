"""E5 hybrid enforcement: warning, manifest fields, --strict-e5 error."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from v2b_syndata.e5_metrics import InfeasibilityError, compute_concurrency
from v2b_syndata.runner import generate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _gen(out: Path, scenario: str = "S01", overrides: dict | None = None,
         strict_e5: bool = False):
    return generate(
        scenario_id=scenario, seed=42, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=overrides or {},
        noise_profile_override=None,
        strict_e5=strict_e5,
    )


def test_e5_manifest_field_populated_on_clean_scenario(tmp_path: Path):
    out = tmp_path / "ok"
    _gen(out)
    m = json.loads((out / "manifest.json").read_text())
    assert "e5" in m
    for k in ("realized_max_concurrent", "n_chargers", "infeasible",
              "infeasible_tick_count", "total_tick_count", "infeasible_tick_fraction"):
        assert k in m["e5"], f"missing {k}"
    assert m["e5"]["infeasible"] is False  # S01 is feasible


def test_e5_manifest_infeasible_on_undersize(tmp_path: Path):
    out = tmp_path / "bad"
    _gen(out, scenario="S_audit_baseline",
         overrides={"charging_infra.charger_count": 1})
    m = json.loads((out / "manifest.json").read_text())
    assert m["e5"]["infeasible"] is True
    assert m["e5"]["realized_max_concurrent"] > 1
    assert m["e5"]["infeasible_tick_count"] > 0


def test_e5_warning_on_undersize(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    out = tmp_path / "warn"
    with caplog.at_level(logging.WARNING, logger="v2b_syndata.runner"):
        _gen(out, scenario="S_audit_baseline",
             overrides={"charging_infra.charger_count": 1})
    assert any("E5 infeasibility" in r.message for r in caplog.records)


def test_e5_strict_mode_errors(tmp_path: Path):
    out = tmp_path / "strict"
    with pytest.raises(InfeasibilityError):
        _gen(out, scenario="S_audit_baseline",
             overrides={"charging_infra.charger_count": 1},
             strict_e5=True)
    # Even on strict error, manifest + CSVs must be written first.
    assert (out / "manifest.json").exists()
    assert (out / "sessions.csv").exists()


def test_e5_strict_mode_passes_on_clean(tmp_path: Path):
    """--strict-e5 on a feasible scenario must NOT raise."""
    out = tmp_path / "strict_ok"
    m = _gen(out, strict_e5=True)
    assert m["e5"]["infeasible"] is False


def test_compute_concurrency_empty_sessions():
    """Edge case: no sessions → max_concurrent=0, not infeasible."""
    import pandas as pd
    from datetime import datetime
    rep = compute_concurrency(
        pd.DataFrame(columns=["arrival", "departure"]),
        sim_start=datetime(2020, 4, 1), sim_end=datetime(2020, 4, 8),
        n_chargers=20,
    )
    assert rep.realized_max_concurrent == 0
    assert not rep.infeasible
