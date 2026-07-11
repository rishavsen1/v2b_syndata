"""Smoke tests for tools/bench_v2b_dispatch.py (LP peak-shave baseline).

Tiny synthetic optimus-schema fixture: 8 x 15-min steps, one 50-kWh car
(arrival SoC 20%, required 60% -> 20 kWh), one bidirectional +-20 kW charger,
a 20 kWh / 10 kW stationary battery, flat prices, zero PV, and a building
load with a 2-step peak in the middle. Hand-checkable optima:

  uncontrolled: charges 20 kW for the first 4 steps -> peak net 70 kW;
  v1g:          avoids the 50 kW load peak entirely  -> peak net 50 kW;
  v2b:          vehicle + battery discharge shave below the building peak.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import bench_v2b_dispatch as bvd  # noqa: E402

T = 8
START = pd.Timestamp("2024-07-01 00:00:00")


def _write_fixture(d: Path, sessions: pd.DataFrame) -> Path:
    times = [START + i * pd.Timedelta(minutes=15) for i in range(T)]
    dt = [t.strftime("%Y-%m-%d %H:%M:%S") for t in times]
    pd.DataFrame({
        "datetime": dt,
        "power_kw": [10.0, 10.0, 50.0, 50.0, 10.0, 10.0, 10.0, 10.0],
        "building_id": 0,
    }).to_csv(d / "building_load.csv", index=False)
    pd.DataFrame({
        "datetime": dt, "power_pv_kw": 0.0, "building_id": 0,
    }).to_csv(d / "pv_generation.csv", index=False)
    pd.DataFrame({
        "datetime": dt, "price_per_kwh": 0.1, "type": "off-peak",
        "building_id": 0,
    }).to_csv(d / "grid_prices.csv")
    pd.DataFrame({
        "car_id": [1], "capacity_kwh": [50.0], "soc": [20.0],
        "min_allowed_soc": [10.0], "max_allowed_soc": [90.0],
        "building_id": [0], "frequency": [1.0], "user_type": [0],
    }).to_csv(d / "cars.csv")
    pd.DataFrame({
        "charger_id": [1], "directionality": ["bidirectional"],
        "charge_rates_kw": ["(-20.0, 20.0)"], "building_id": [0],
    }).to_csv(d / "chargers.csv")
    sessions.to_csv(d / "sessions.csv")
    pd.DataFrame({
        "battery_id": ["batt_0"], "battery_type": ["nmc"],
        "capacity_kwh": [20.0], "power_kw": [10.0],
        "round_trip_efficiency": [0.9], "min_soc_pct": [10.0],
        "max_soc_pct": [95.0], "initial_soc_pct": [50.0],
        "building_id": [0],
    }).to_csv(d / "battery.csv", index=False)
    return d


def _one_session(duration_sec: int = 7200,
                 required: float = 60.0) -> pd.DataFrame:
    return pd.DataFrame({
        "car_id": [1], "arrival": [START.strftime("%Y-%m-%d %H:%M:%S")],
        "required_soc_at_depart": [required],
        "previous_day_external_use_soc": [0.0],
        "duration": [duration_sec], "session_id": [1], "building_id": [0],
    })


@pytest.fixture()
def fixture_dir(tmp_path):
    return _write_fixture(tmp_path, _one_session())


def test_three_arms_ordered_and_exact(fixture_dir):
    res = bvd.run_benchmark(fixture_dir, with_acnsim=False)
    arms = res["arms"]
    # hand-computed optima (see module docstring)
    assert arms["uncontrolled"]["peak_net_kw"] == pytest.approx(70.0)
    assert arms["v1g"]["peak_net_kw"] == pytest.approx(50.0, abs=1e-6)
    assert arms["v2b"]["peak_net_kw"] < 50.0 - 1.0
    assert arms["v1g"]["status"] == arms["v2b"]["status"] == "optimal"
    # v2b uses vehicle discharge and/or the battery
    assert (arms["v2b"]["ev_discharge_kwh"]
            + arms["v2b"]["batt_throughput_kwh"]) > 0.0
    # energy served: uncontrolled and v1g charge exactly the 20 kWh need
    assert arms["uncontrolled"]["ev_charge_kwh"] == pytest.approx(20.0)
    assert arms["v1g"]["ev_charge_kwh"] == pytest.approx(20.0, abs=1e-6)
    assert res["unit"].n_relaxed == 0


def test_deterministic_resolve(fixture_dir):
    a = bvd.run_benchmark(fixture_dir, with_acnsim=False)["arms"]
    b = bvd.run_benchmark(fixture_dir, with_acnsim=False)["arms"]
    for arm in ("uncontrolled", "v1g", "v2b"):
        assert a[arm]["peak_net_kw"] == b[arm]["peak_net_kw"]
        assert a[arm]["energy_cost_usd"] == b[arm]["energy_cost_usd"]


def test_infeasible_requirement_is_relaxed(tmp_path):
    # 1 x 15-min step window: reachable SoC = 20 + 100*20*0.25/50 = 30% < 60%
    d = _write_fixture(tmp_path, _one_session(duration_sec=900))
    res = bvd.run_benchmark(d, with_acnsim=False)
    unit = res["unit"]
    assert unit.n_relaxed == 1
    s = unit.sessions[0]
    assert s.required_kwh == pytest.approx(0.30 * 50.0)
    assert res["arms"]["v1g"]["status"] == "optimal"  # feasible after relax


def test_arrival_soc_chain(tmp_path):
    # second session: arrival = required(1st) - previous_day_external_use
    two = pd.DataFrame({
        "car_id": [1, 1],
        "arrival": [START.strftime("%Y-%m-%d %H:%M:%S"),
                    (START + pd.Timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")],
        "required_soc_at_depart": [60.0, 65.0],
        "previous_day_external_use_soc": [0.0, 15.0],
        "duration": [3600, 3600], "session_id": [1, 2], "building_id": [0, 0],
    })
    d = _write_fixture(tmp_path, two)
    unit = bvd.load_unit(d)
    assert unit.sessions[0].arrival_kwh == pytest.approx(0.20 * 50.0)
    assert unit.sessions[1].arrival_kwh == pytest.approx(0.45 * 50.0)


def test_acnsim_crosscheck_matches_uncontrolled(fixture_dir):
    pytest.importorskip("acnportal")
    res = bvd.run_benchmark(fixture_dir, with_acnsim=True)
    arms = res["arms"]
    assert "acnsim_llf_crosscheck" in arms
    # LLF (uncontended, unbinding feeder) == charge-at-max-until-required,
    # i.e. the uncontrolled arm's semantics.
    assert arms["acnsim_llf_crosscheck"]["peak_net_kw"] == pytest.approx(
        arms["uncontrolled"]["peak_net_kw"], abs=1e-6)
    assert arms["acnsim_llf_crosscheck"]["ev_charge_kwh"] == pytest.approx(
        arms["uncontrolled"]["ev_charge_kwh"], abs=1e-3)


def test_outputs_written(fixture_dir, tmp_path):
    out = tmp_path / "out"
    res = bvd.run_benchmark(fixture_dir, with_acnsim=False)
    bvd.write_outputs(fixture_dir, out, res)
    csv = pd.read_csv(out / "v2b_dispatch.csv")
    assert set(csv["arm"]) == {"uncontrolled", "v1g", "v2b"}
    assert (out / "v2b_dispatch.md").read_text().startswith(
        "# V2B dispatch baseline")
