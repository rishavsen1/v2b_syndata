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


# ── generate-multi (single / batch / from-config) ────────────────────────────

@pytest.fixture
def _stub_weather(tmp_path, monkeypatch):
    """Synthetic EPW so generate-multi's weather export needs no real station."""
    import pandas as pd
    from v2b_syndata import export_optimus as exp
    epw = tmp_path / "fixture.epw"
    idx = pd.date_range("2021-01-01", "2022-01-01", freq="h", inclusive="left")
    lines = ["LOCATION,Test"] + ["HEADER"] * 7
    for ts in idx:
        cols = ["0"] * 22
        cols[1], cols[2], cols[3] = str(ts.month), str(ts.day), str(ts.hour + 1)
        cols[6], cols[7], cols[8], cols[21] = "15.0", "5.0", "50.0", "2.5"
        if 6 <= ts.hour <= 20:
            cols[13] = cols[14] = cols[15] = "300"
        lines.append(",".join(cols))
    epw.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(exp.weather, "get_weather_epw", lambda *a, **k: epw)
    return epw


def _write_multi_cfg(path: Path) -> Path:
    path.write_text(json.dumps({
        "output_mode": "shared",
        "buildings": [
            {"base_scenario": "S01", "descriptors": {"location": "nashville_tn"},
             "overrides": {"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4,
                           "sim_window.mode": "custom", "sim_window.start": "2021-09-01",
                           "sim_window.custom_end": "2021-09-04"}, "seed": 1},
            {"base_scenario": "S01", "descriptors": {"location": "nashville_tn"},
             "overrides": {"ev_fleet.ev_count": 7, "charging_infra.charger_count": 7,
                           "sim_window.mode": "custom", "sim_window.start": "2021-09-01",
                           "sim_window.custom_end": "2021-09-04"}, "seed": 2},
        ],
    }))
    return path


def test_cli_generate_multi_config(tmp_path: Path, _stub_weather):
    import pandas as pd
    cfg = _write_multi_cfg(tmp_path / "mb.json")
    out = tmp_path / "mb_out"
    rc = _run("--config-dir", str(CONFIG_DIR), "generate-multi",
              "--config", str(cfg), "--output-dir", str(out))
    assert rc == 0
    cars = pd.read_csv(out / "cars.csv", index_col=0)
    assert sorted(cars["building_id"].unique()) == [0, 1]
    assert cars.groupby("building_id").size().to_dict() == {0: 4, 1: 7}
    wx = pd.read_csv(out / "weather_data.csv")
    assert "global_horizontal_w_m2" in wx.columns
    assert (out / "multi_building_config.json").exists()


def test_cli_generate_multi_batch(tmp_path: Path, _stub_weather):
    cfg = _write_multi_cfg(tmp_path / "mb.json")
    out = tmp_path / "mb_batch"
    rc = _run("--config-dir", str(CONFIG_DIR), "generate-multi", "--config", str(cfg),
              "--output-dir", str(out), "--start-month", "2021-09", "--end-month", "2021-09",
              "--samples-per-month", "2", "--workers", "1", "--noise-profile", "clean",
              "--weather-sigma-c", "2.0")
    assert rc == 0
    import json
    manifest = json.loads((out / "batch_manifest.json").read_text())
    assert manifest["weather_sigma_c"] == 2.0
    for s in (0, 1):
        assert (out / "SEP2021" / str(s) / "cars.csv").exists()


def test_cli_generate_multi_weather_profile(tmp_path: Path, _stub_weather):
    """--weather-profile is the batch default; it resolves per-building to a
    per-sample weather realization (logged as overrides in each unit config)."""
    import json
    cfg = _write_multi_cfg(tmp_path / "mb.json")
    out = tmp_path / "wxprof"
    rc = _run("--config-dir", str(CONFIG_DIR), "generate-multi", "--config", str(cfg),
              "--output-dir", str(out), "--start-month", "2021-09", "--end-month", "2021-09",
              "--samples-per-month", "2", "--workers", "1", "--noise-profile", "clean",
              "--weather-profile", "moderate")
    assert rc == 0
    manifest = json.loads((out / "batch_manifest.json").read_text())
    assert manifest["weather_profile"] == "moderate"
    # the resolved per-sample realization is pinned per building in the unit config
    unit = json.loads((out / "SEP2021" / "0" / "multi_building_config.json").read_text())
    ov = unit["buildings"][0]["overrides"]
    assert "building_load.weather_temp_offset_c" in ov
    assert "building_load.weather_solar_scale" in ov


def test_cli_generate_multi_from_config(tmp_path: Path, _stub_weather):
    import filecmp
    cfg = _write_multi_cfg(tmp_path / "mb.json")
    a = tmp_path / "a"
    _run("--config-dir", str(CONFIG_DIR), "generate-multi", "--config", str(cfg), "--output-dir", str(a))
    b = tmp_path / "b"
    _run("--config-dir", str(CONFIG_DIR), "generate-multi",
         "--from-config", str(a / "multi_building_config.json"), "--output-dir", str(b))
    assert filecmp.cmp(a / "cars.csv", b / "cars.csv", shallow=False)
