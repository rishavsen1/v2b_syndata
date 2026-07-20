"""`emit_sessions_soc` writes sessions_soc.csv (explicit SoC columns) next to
the unchanged sessions.csv; default False emits no extra file.

Reuses the stub_weather / _three_specs pattern from test_multi_building.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

from v2b_syndata import export_optimus as exp
from v2b_syndata.multi_building import (
    BuildingSpec,
    MultiConfig,
    config_from_dict,
    generate_multi,
)

from .test_multi_building import _FAST, _write_epw


@pytest.fixture
def stub_weather(tmp_path, monkeypatch):
    epw = _write_epw(tmp_path / "fixture.epw", year=2021)
    monkeypatch.setattr(exp.weather, "get_weather_epw", lambda *a, **k: epw)
    return epw


def _one_spec() -> list[BuildingSpec]:
    return [BuildingSpec("S01", descriptors={"location": "san_jose_ca"},
                         overrides=dict(_FAST), seed=42)]


def test_default_no_extra_file(tmp_path, config_dir, stub_weather):
    out = tmp_path / "off"
    generate_multi(MultiConfig(_one_spec()), out, config_dir)
    assert not (out / "sessions_soc.csv").exists()


def test_emit_sessions_soc_shared(tmp_path, config_dir, stub_weather):
    out = tmp_path / "on"
    generate_multi(MultiConfig(_one_spec(), emit_sessions_soc=True), out, config_dir)

    soc = pd.read_csv(out / "sessions_soc.csv", index_col=0)
    plain = pd.read_csv(out / "sessions.csv", index_col=0)
    assert list(soc.columns) == [
        "car_id", "arrival", "departure", "arrival_soc", "departure_soc",
        "previous_day_external_use_soc", "duration", "session_id",
        "building_id",
    ]
    # Same sessions, same order; SoC endpoints consistent with the plain file.
    assert len(soc) == len(plain)
    assert (soc["session_id"].values == plain["session_id"].values).all()
    assert (soc["departure_soc"].values
            == plain["required_soc_at_depart"].values).all()
    assert (soc["arrival_soc"] < soc["departure_soc"]).all()  # D6
    # departure = arrival + duration on the native grid.
    arr = pd.to_datetime(soc["arrival"])
    dep = pd.to_datetime(soc["departure"])
    assert ((dep - arr).dt.total_seconds() == soc["duration"]).all()


def test_config_roundtrip_flag(tmp_path, config_dir, stub_weather):
    cfg = config_from_dict({
        "emit_sessions_soc": True,
        "buildings": [{"base_scenario": "S01",
                       "descriptors": {"location": "san_jose_ca"},
                       "overrides": dict(_FAST), "seed": 42}],
    })
    assert cfg.emit_sessions_soc is True
    out = tmp_path / "rt"
    config = generate_multi(cfg, out, config_dir)
    assert config["emit_sessions_soc"] is True
    assert (out / "sessions_soc.csv").exists()
