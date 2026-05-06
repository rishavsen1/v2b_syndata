"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pytest
import yaml

from v2b_syndata.runner import generate


def _stub_simulate_building_load(
    archetype: str,
    size: str,
    tmyx_station: str,
    occupancy: pd.Series,
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
    weather_type: str = "tmyx",
    weather_year: int | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Deterministic synthetic load. Replaces the EnergyPlus pipeline in unit tests
    so test runs do not need the EnergyPlus binary."""
    idx = pd.date_range(sim_window_start, sim_window_end, freq="15min", inclusive="left")
    hour = idx.hour + idx.minute / 60.0
    flex = np.clip(120.0 + 60.0 * np.sin(2 * np.pi * (hour - 6) / 24), 0.0, None)
    inflex = np.clip(40.0 + 15.0 * np.sin(2 * np.pi * (hour - 6) / 24), 0.0, None)
    return (
        pd.Series(flex, index=idx, name="L_flex"),
        pd.Series(inflex, index=idx, name="L_inflex"),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_energyplus: opt this test out of the EnergyPlus pipeline stub "
        "(test will invoke EnergyPlus subprocess for real).",
    )


@pytest.fixture(autouse=True)
def stub_load_pipeline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the EnergyPlus pipeline with a deterministic synthetic loader
    for every test that does not opt in via ``@pytest.mark.real_energyplus``."""
    if request.node.get_closest_marker("real_energyplus"):
        return
    monkeypatch.setattr(
        "v2b_syndata.samplers.load.simulate_building_load",
        _stub_simulate_building_load,
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"

DEFAULT_FAST_START = datetime(2020, 4, 1)
DEFAULT_FAST_END = datetime(2020, 4, 8)


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def tmp_scenario_dir(tmp_path: Path, config_dir: Path):
    """Build a temp config directory backed by symlinks, with writable scenarios/.

    Returns ``(cfg_dir, write_scenario)``. ``write_scenario(descriptors,
    scenario_id="STEST", overrides=None)`` writes
    ``cfg_dir/scenarios/<id>.yaml`` and returns ``(cfg_dir, scenario_id)``.
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for f in config_dir.iterdir():
        if f.name == "scenarios":
            continue
        (cfg / f.name).symlink_to(f)
    (cfg / "scenarios").mkdir()

    def write_scenario(
        descriptors: dict[str, str],
        scenario_id: str = "STEST",
        overrides: dict[str, Any] | None = None,
    ) -> tuple[Path, str]:
        sc = {
            "scenario_id": scenario_id,
            "description": "test scenario",
            "descriptors": dict(descriptors),
            "overrides": overrides or {},
        }
        (cfg / "scenarios" / f"{scenario_id}.yaml").write_text(yaml.safe_dump(sc))
        return cfg, scenario_id

    return cfg, write_scenario


@pytest.fixture
def fast_generate(tmp_path: Path, config_dir: Path) -> Callable[..., tuple[Path, dict[str, Any]]]:
    """Run ``runner.generate`` with a fast 7-day custom window by default.

    Caller may override ``scenario``, ``seed``, ``config_dir``, ``overrides``,
    or ``noise_profile``. ``ev_count`` is left at the descriptor's default
    so F4/F5 share invariants stay above the validator's tolerance.
    """
    counter = {"i": 0}

    def _go(
        *,
        scenario: str = "S01",
        seed: int = 42,
        config_dir: Path = config_dir,
        overrides: dict[str, Any] | None = None,
        noise_profile: str | None = None,
        out_dir: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        merged: dict[str, Any] = {
            "sim_window.mode": "custom",
            "sim_window.start": "2020-04-01",
            "sim_window.custom_end": "2020-04-08",
        }
        merged.update(overrides or {})
        if out_dir is None:
            counter["i"] += 1
            out_dir = tmp_path / f"out_{counter['i']}"
        manifest = generate(
            scenario_id=scenario,
            seed=seed,
            output_dir=out_dir,
            config_dir=config_dir,
            cli_overrides=merged,
            noise_profile_override=noise_profile,
        )
        return out_dir, manifest

    return _go


@pytest.fixture
def assert_sanity():
    """Fixture wrapper around :func:`_assert_sanity` for ergonomic test use."""
    return _assert_sanity


def _assert_sanity(
    out_dir: Path,
    manifest: dict[str, Any],
    *,
    expected_start: datetime | None = None,
    expected_end: datetime | None = None,
) -> None:
    """Cheap post-generate sanity checks.

    1. building_load and grid_prices first/last datetimes match the input window.
    2. cars and users row counts equal ev_count, with matching car_id sets.
    3. chargers row count equals charger_count.
    4. building_load and grid_prices row counts equal the 15-min window length.
    """
    if expected_start is None:
        expected_start = DEFAULT_FAST_START
    if expected_end is None:
        expected_end = DEFAULT_FAST_END

    bl = pd.read_csv(out_dir / "building_load.csv")
    gp = pd.read_csv(out_dir / "grid_prices.csv")
    cars = pd.read_csv(out_dir / "cars.csv")
    users = pd.read_csv(out_dir / "users.csv")
    chargers = pd.read_csv(out_dir / "chargers.csv")

    expected_rows = int((expected_end - expected_start).total_seconds() // (15 * 60))
    assert len(bl) == expected_rows, (
        f"building_load rows {len(bl)} != expected {expected_rows} " f"for window {expected_start} → {expected_end}"
    )
    assert len(gp) == expected_rows, f"grid_prices rows {len(gp)} != {expected_rows}"

    bl_first = pd.to_datetime(bl["datetime"].iloc[0])
    bl_last = pd.to_datetime(bl["datetime"].iloc[-1])
    expected_last = expected_end - timedelta(minutes=15)
    assert bl_first == expected_start, f"building_load first {bl_first} != {expected_start}"
    assert bl_last == expected_last, f"building_load last {bl_last} != {expected_last}"
    gp_first = pd.to_datetime(gp["datetime"].iloc[0])
    gp_last = pd.to_datetime(gp["datetime"].iloc[-1])
    assert gp_first == expected_start
    assert gp_last == expected_last

    res = manifest["knob_resolution"]
    ev_count = int(res["ev_fleet.ev_count"]["value"])
    charger_count = int(res["charging_infra.charger_count"]["value"])
    assert len(cars) == ev_count, f"cars rows {len(cars)} != ev_count {ev_count}"
    assert len(users) == ev_count, f"users rows {len(users)} != ev_count {ev_count}"
    assert set(cars["car_id"]) == set(users["car_id"]), "cars/users car_id sets differ"
    assert len(chargers) == charger_count, f"chargers rows {len(chargers)} != charger_count {charger_count}"
