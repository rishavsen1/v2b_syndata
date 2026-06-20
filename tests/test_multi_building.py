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
    generate_multi_batch,
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
        if 6 <= ts.hour <= 20:  # daytime solar so GHI/DNI/DHI are non-zero
            cols[13] = cols[14] = cols[15] = "300"
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


def test_generate_multi_batch(tmp_path, config_dir, stub_weather):
    """Unified engine: 2 buildings × 2 samples × 1 month → <MONTH>/<sample>/ tree."""
    # No sim_window in overrides — the batch engine sets month/start itself.
    specs = [
        BuildingSpec("S01", descriptors={"location": "nashville_tn", "building": "medium_office_v1"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4}, seed=1000),
        BuildingSpec("S01", descriptors={"location": "nashville_tn", "building": "large_office_v1"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4}, seed=2000),
    ]
    out = tmp_path / "batch"
    manifest = generate_multi_batch(
        MultiConfig(specs, output_mode="shared"), out, config_dir,
        start_month="2021-09", end_month="2021-09", samples_per_month=2,
        workers=1, noise_profile="clean",   # serial so the autouse stubs apply
    )
    assert manifest["status"] == "succeeded"
    assert manifest["n_total"] == 2 and manifest["n_buildings"] == 2
    assert (out / "batch_manifest.json").exists()
    for s in (0, 1):
        unit = out / "SEP2021" / str(s)
        assert (unit / "multi_building_config.json").exists()
        cars = pd.read_csv(unit / "cars.csv", index_col=0)
        assert sorted(cars["building_id"].unique()) == [0, 1]
        bl = pd.read_csv(unit / "building_load.csv")
        assert sorted(bl["building_id"].unique()) == [0, 1]


def test_per_building_overrides_isolated(tmp_path, config_dir, stub_weather):
    """Each building's knob overrides apply only to itself (no cross-contamination)."""
    specs = [
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4}, seed=1),
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 9, "charging_infra.charger_count": 9}, seed=2),
    ]
    out = tmp_path / "iso"
    generate_multi_batch(MultiConfig(specs, output_mode="shared"), out, config_dir,
                         start_month="2021-09", end_month="2021-09", samples_per_month=1,
                         workers=1, noise_profile="clean")
    cars = pd.read_csv(out / "SEP2021" / "0" / "cars.csv", index_col=0)
    counts = cars.groupby("building_id").size().to_dict()
    assert counts[0] == 4 and counts[1] == 9


def test_per_building_noise_honored(tmp_path, config_dir, stub_weather):
    """generate_multi_batch uses each spec's own noise_profile, not one global."""
    specs = [
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
                     seed=1, noise_profile="clean"),
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
                     seed=2, noise_profile="tmyx_stochastic"),
    ]
    out = tmp_path / "noise"
    generate_multi_batch(MultiConfig(specs, output_mode="shared"), out, config_dir,
                         start_month="2021-09", end_month="2021-09", samples_per_month=1,
                         workers=1, noise_profile="clean")  # batch default only a fallback
    import json
    cfg = json.loads((out / "SEP2021" / "0" / "multi_building_config.json").read_text())
    noises = {b["building_id"]: b["noise_profile"] for b in cfg["buildings"]}
    assert noises[0] == "clean" and noises[1] == "tmyx_stochastic"


def test_weather_sigma_drives_per_sample_realizations(tmp_path, config_dir, stub_weather):
    """weather_sigma_c > 0 → each sample gets a distinct, reproducible dry-bulb
    offset that perturbs BOTH the exported weather and the (stub) load — so the
    cross-sample variance is weather-driven, not decoupled jitter."""
    import json
    specs = [
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4}, seed=1),
    ]
    kw = dict(start_month="2021-09", end_month="2021-09", samples_per_month=3,
              workers=1, noise_profile="clean", weather_sigma_c=3.0, weather_solar_sigma=0.05)
    out = tmp_path / "wx"
    manifest = generate_multi_batch(MultiConfig(specs, output_mode="shared"), out, config_dir, **kw)
    assert manifest["weather_sigma_c"] == 3.0
    assert manifest["weather_solar_sigma"] == 0.05

    offsets, scales, wx_means, load_sums = [], [], [], []
    for s in (0, 1, 2):
        cfg = json.loads((out / "SEP2021" / str(s) / "multi_building_config.json").read_text())
        ov = cfg["buildings"][0]["overrides"]
        off = ov["building_load.weather_temp_offset_c"]
        offsets.append(off)
        scales.append(ov["building_load.weather_solar_scale"])
        wdf = pd.read_csv(out / "SEP2021" / str(s) / "weather_data.csv")
        wx_means.append(round(wdf["dry_bulb_temp_c"].mean(), 6))
        bl = pd.read_csv(out / "SEP2021" / str(s) / "building_load.csv")
        load_sums.append(round(bl["power_kw_flexible"].sum(), 6))
    # distinct realizations across samples (both temp offset and solar scale)
    assert len(set(offsets)) == 3, f"offsets not distinct: {offsets}"
    assert len(set(scales)) == 3, f"solar scales not distinct: {scales}"
    assert len(set(wx_means)) == 3, "exported weather identical across samples"
    assert len(set(load_sums)) == 3, "load did not respond to per-sample weather"

    # reproducible: same config + sigma → identical offsets
    out2 = tmp_path / "wx2"
    generate_multi_batch(MultiConfig(specs, output_mode="shared"), out2, config_dir, **kw)
    offs2 = [json.loads((out2 / "SEP2021" / str(s) / "multi_building_config.json").read_text())
             ["buildings"][0]["overrides"]["building_load.weather_temp_offset_c"] for s in (0, 1, 2)]
    assert offs2 == offsets


def test_weather_profile_changes_weather_and_load(tmp_path, config_dir, stub_weather):
    """End-to-end guard: a non-trivial weather profile actually changes the
    EXPORTED weather_data.csv AND the simulated load vs `none` — not just the
    pinned override. (The autouse load stub carries a +3%/°C sensitivity.)"""
    def run(profile):
        out = tmp_path / profile
        specs = [BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                              overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
                              seed=1, weather_profile=profile)]
        generate_multi_batch(MultiConfig(specs, output_mode="shared"), out, config_dir,
                             start_month="2021-09", end_month="2021-09", samples_per_month=1,
                             workers=1, noise_profile="clean")
        wx = pd.read_csv(out / "SEP2021" / "0" / "weather_data.csv")
        bl = pd.read_csv(out / "SEP2021" / "0" / "building_load.csv")
        return {
            "temp": wx["dry_bulb_temp_c"].mean(),
            "rh": wx["relative_humidity_pct"].mean(),
            "wind": wx["wind_speed_m_s"].mean(),
            "ghi": wx["global_horizontal_w_m2"].mean(),
            "load": bl["power_kw_flexible"].sum(),
        }

    n, s = run("none"), run("strong")
    # all four weather channels move (temp + humidity + wind + solar) …
    for k in ("temp", "rh", "wind", "ghi"):
        assert abs(s[k] - n[k]) > 1e-6, f"{k} NOT perturbed: none={n[k]} strong={s[k]}"
    # … and the (stubbed) load responds
    assert abs(s["load"] - n["load"]) > 1.0, f"load did NOT respond: {n['load']} vs {s['load']}"


def test_per_building_weather_profile(tmp_path, config_dir, stub_weather):
    """Each building's own weather_profile wins over the batch default — building 0
    (none) gets no weather offset, building 1 (strong) does."""
    import json
    specs = [
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
                     seed=1, weather_profile="none"),
        BuildingSpec("S01", descriptors={"location": "nashville_tn"},
                     overrides={"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4},
                     seed=2, weather_profile="strong"),
    ]
    out = tmp_path / "wxpb"
    generate_multi_batch(MultiConfig(specs, output_mode="shared"), out, config_dir,
                         start_month="2021-09", end_month="2021-09", samples_per_month=1,
                         workers=1, noise_profile="clean", weather_profile="none")
    cfg = json.loads((out / "SEP2021" / "0" / "multi_building_config.json").read_text())
    ov = {b["building_id"]: b["overrides"] for b in cfg["buildings"]}
    assert "building_load.weather_temp_offset_c" not in ov[0]  # profile none → no draw
    assert "building_load.weather_temp_offset_c" in ov[1]       # profile strong → drawn
    assert cfg["buildings"][1]["weather_profile"] == "strong"   # round-trips in config


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
