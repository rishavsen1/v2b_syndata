"""Integration tests for multi-building generation + optimus export.

Uses the autouse `stub_load_pipeline` fixture (no EnergyPlus) and a synthetic
EPW fixture for the weather export, with a non-leap window so the leap-EPW
transform is a no-op.
"""
from __future__ import annotations

import filecmp
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata import export_optimus as exp
from v2b_syndata.multi_building import (
    BuildingSpec,
    MultiConfig,
    generate_multi,
    regenerate_from_config,
)

_FAST = {
    "sim_window.mode": "custom",
    "sim_window.start": "2021-09-01",
    "sim_window.custom_end": "2021-09-08",
    "ev_fleet.ev_count": 4,
    "charging_infra.charger_count": 4,
}
_WINDOW_HOURS = 7 * 24
_YEAR_HOURS = 8760  # 2021, non-leap


def _write_epw(path: Path, year: int = 2021) -> Path:
    idx = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="h", inclusive="left")
    lines = ["LOCATION,Test"] + ["HEADER"] * 7
    for ts in idx:
        cols = ["0"] * 22
        cols[1], cols[2], cols[3] = str(ts.month), str(ts.day), str(ts.hour + 1)
        cols[6], cols[7], cols[8], cols[21] = "15.0", "5.0", "50.0", "2.5"
        lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def stub_weather(tmp_path, monkeypatch):
    epw = _write_epw(tmp_path / "fixture.epw", year=2021)
    monkeypatch.setattr(exp.weather, "get_weather_epw", lambda *a, **k: epw)
    return epw


def _three_specs(overrides_extra=None) -> list[BuildingSpec]:
    base = dict(_FAST)
    if overrides_extra:
        base.update(overrides_extra)
    return [
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides=dict(base), seed=42),
        BuildingSpec("S01", descriptors={"building": "large_office_v1",
                                         "location": "san_jose_ca"},
                     overrides=dict(base), seed=7),
        BuildingSpec("S01", descriptors={"population": "stable_commuter_heavy"},
                     overrides=dict(base), seed=99),
    ]


def test_shared_mode(tmp_path, config_dir, stub_weather):
    cfg = MultiConfig(_three_specs(), output_mode="shared",
                      dr_program="CBP", dr_incentive_per_kw=5.0,
                      dr_penalty_per_kwh=12.0)
    out = tmp_path / "shared"
    generate_multi(cfg, out, config_dir)

    expected = {
        "building_load.csv", "cars.csv", "chargers.csv", "sessions.csv",
        "grid_prices.csv", "weather_data.csv", "occupancy.csv",
        "dso_commands.csv", "policies.csv",
    }
    assert expected <= {p.name for p in out.glob("*.csv")}
    assert (out / "multi_building_config.json").exists()

    cars = pd.read_csv(out / "cars.csv", index_col=0)
    assert sorted(cars["building_id"].unique()) == [0, 1, 2]

    weather = pd.read_csv(out / "weather_data.csv")
    assert len(weather) == 3 * _WINDOW_HOURS
    assert "building_id" in weather.columns  # shared → carries building_id
    occ = pd.read_csv(out / "occupancy.csv")
    assert len(occ) == 3 * _YEAR_HOURS

    policies = pd.read_csv(out / "policies.csv")
    assert sorted(policies["building_id"]) == [0, 1, 2]


def test_per_building_mode(tmp_path, config_dir, stub_weather):
    cfg = MultiConfig(_three_specs(), output_mode="per-building")
    out = tmp_path / "perb"
    generate_multi(cfg, out, config_dir)

    for bid in (0, 1, 2):
        sub = out / str(bid)
        assert sub.is_dir()
        for name in ("building_load.csv", "cars.csv", "chargers.csv",
                     "sessions.csv", "grid_prices.csv", "weather_data.csv",
                     "occupancy.csv", "dso_commands.csv", "policies.csv"):
            assert (sub / name).exists(), f"{bid}/{name} missing"
        # weather/occupancy match the reference exactly (no building_id)
        assert "building_id" not in pd.read_csv(sub / "weather_data.csv").columns
        assert "building_id" not in pd.read_csv(sub / "occupancy.csv").columns
        # cars keep building_id (constant per subfolder)
        cars = pd.read_csv(sub / "cars.csv", index_col=0)
        assert (cars["building_id"] == bid).all()


def test_reproducibility_byte_identical(tmp_path, config_dir, stub_weather):
    specs = _three_specs()
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    generate_multi(MultiConfig(list(specs), output_mode="shared"), out_a, config_dir)
    generate_multi(MultiConfig(list(specs), output_mode="shared"), out_b, config_dir)

    for name in ("building_load.csv", "cars.csv", "chargers.csv", "sessions.csv",
                 "grid_prices.csv", "weather_data.csv", "occupancy.csv",
                 "dso_commands.csv", "policies.csv"):
        assert filecmp.cmp(out_a / name, out_b / name, shallow=False), \
            f"{name} not byte-identical across runs"


def test_regenerate_from_config(tmp_path, config_dir, stub_weather):
    cfg = MultiConfig(_three_specs(), output_mode="shared", dr_program="CBP")
    out1 = tmp_path / "run1"
    generate_multi(cfg, out1, config_dir)

    out2 = tmp_path / "run2"
    regenerate_from_config(out1 / "multi_building_config.json", out2, config_dir)

    for name in ("building_load.csv", "cars.csv", "sessions.csv",
                 "weather_data.csv", "occupancy.csv", "dso_commands.csv"):
        assert filecmp.cmp(out1 / name, out2 / name, shallow=False), \
            f"{name} not reproduced byte-identically from config"
