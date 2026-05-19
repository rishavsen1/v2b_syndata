"""In-process CLI tests.

Calls ``cli.main(argv)`` directly so coverage instrumentation sees the
subcommand bodies. Subprocess invocation would run in a child process where
the cov tracer isn't attached, leaving cli.py at low coverage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from v2b_syndata import cli as cli_mod

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


def _run(*args: str) -> int:
    """Invoke cli.main and capture return code (None → 0)."""
    rc = cli_mod.main(list(args))
    return rc if rc is not None else 0


def test_cli_generate_produces_all_csvs(tmp_path: Path):
    out = tmp_path / "gen"
    rc = _run("--config-dir", str(CONFIG_DIR), "generate",
              "--scenario", "S01", "--seed", "42",
              "--output-dir", str(out))
    assert rc == 0
    expected = {"building_load.csv", "cars.csv", "users.csv", "chargers.csv",
                "sessions.csv", "grid_prices.csv", "dr_events.csv", "manifest.json"}
    produced = {f.name for f in out.iterdir()}
    assert expected <= produced, f"missing: {expected - produced}"


def test_cli_validate_passes_on_clean_output(tmp_path: Path, capsys: pytest.CaptureFixture):
    out = tmp_path / "gen"
    _run("--config-dir", str(CONFIG_DIR), "generate",
         "--scenario", "S01", "--seed", "42", "--output-dir", str(out))
    capsys.readouterr()  # drain stdout from generate
    rc = _run("--config-dir", str(CONFIG_DIR), "validate", str(out))
    assert rc == 0
    cap = capsys.readouterr()
    assert "OK" in cap.out


def test_cli_validate_strict_runs(tmp_path: Path, capsys: pytest.CaptureFixture):
    out = tmp_path / "gen"
    _run("--config-dir", str(CONFIG_DIR), "generate",
         "--scenario", "S01", "--seed", "42", "--output-dir", str(out))
    capsys.readouterr()
    rc = _run("--config-dir", str(CONFIG_DIR), "validate", "--strict", str(out))
    assert rc in (0, 1)


def test_cli_list_knobs_prints_registry_entries(capsys: pytest.CaptureFixture):
    rc = _run("--config-dir", str(CONFIG_DIR), "list-knobs")
    assert rc == 0
    out = capsys.readouterr().out
    for needle in (
        "ev_fleet.ev_count",
        "utility_rate.tariff_type",
        "noise.profile",
        "sim_window.mode",
    ):
        assert needle in out, f"{needle!r} missing from list-knobs output"


def test_cli_list_scenarios_prints_all_scenarios(capsys: pytest.CaptureFixture):
    rc = _run("--config-dir", str(CONFIG_DIR), "list-scenarios")
    assert rc == 0
    out = capsys.readouterr().out
    for needle in ("S01", "S_dr_cbp", "S_audit_baseline"):
        assert needle in out, f"{needle!r} missing from list-scenarios output"
    assert out.count("\n") >= 30


def test_cli_generate_override_flag_applies(tmp_path: Path):
    out = tmp_path / "gen"
    rc = _run("--config-dir", str(CONFIG_DIR), "generate",
              "--scenario", "S01", "--seed", "42",
              "--output-dir", str(out),
              "--override", "ev_fleet.ev_count=12",
              "--override", "charging_infra.charger_count=15")
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert m["knob_resolution"]["ev_fleet.ev_count"]["value"] == 12
    assert m["knob_resolution"]["ev_fleet.ev_count"]["source"] == "explicit"


def test_cli_unknown_subcommand_errors():
    with pytest.raises(SystemExit):
        _run("--config-dir", str(CONFIG_DIR), "nonsense-subcommand")


def test_cli_generate_rejects_unknown_override(tmp_path: Path):
    out = tmp_path / "gen"
    from v2b_syndata.knob_loader import KnobValidationError
    with pytest.raises(KnobValidationError):
        _run("--config-dir", str(CONFIG_DIR), "generate",
             "--scenario", "S01", "--seed", "42",
             "--output-dir", str(out),
             "--override", "nonexistent.knob=42")


def test_cli_docs_gen_emits_reference(capsys: pytest.CaptureFixture):
    """The docs-gen subcommand prints the auto-generated KNOB_REFERENCE.md section."""
    rc = _run("--config-dir", str(CONFIG_DIR), "docs-gen")
    assert rc == 0
    out = capsys.readouterr().out
    assert "KNOB_REFERENCE" in out
    assert "ev_fleet.ev_count" in out
    assert "Deep-channel" in out or "deep" in out
