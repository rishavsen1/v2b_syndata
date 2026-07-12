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
    # ALL seven stock schedulers are cross-checked; on an uncontended pool
    # with an unbinding feeder every queue-ordering algorithm ==
    # charge-at-max-until-required, i.e. the uncontrolled arm's semantics.
    for algo in ("edf", "llf", "fcfs", "lcfs", "lrpt"):
        key = f"acnsim_{algo}_crosscheck"
        assert key in arms
        assert arms[key]["peak_net_kw"] == pytest.approx(
            arms["uncontrolled"]["peak_net_kw"], abs=1e-6)
        assert arms[key]["ev_charge_kwh"] == pytest.approx(
            arms["uncontrolled"]["ev_charge_kwh"], abs=1e-3)
    assert "acnsim_round_robin_crosscheck" in arms
    assert "acnsim_uncontrolled_crosscheck" in arms


# ── PART 4b: aggregate EV-power cap in the LP ─────────────────────────

def test_solve_lp_agg_cap_binds_and_serves(fixture_dir):
    # 20 kWh over 8 x 15-min steps under a 10 kW aggregate cap:
    # exactly feasible (10 kW x 2 h), so the cap binds everywhere.
    unit = bvd.load_unit(fixture_dir)
    sol = bvd.solve_lp(unit, allow_discharge=False, use_battery=False,
                       ev_agg_cap_kw=10.0)
    assert sol["status"] == "optimal"
    assert sol["ev_kw"].max() <= 10.0 + 1e-6
    assert sol["ev_kw"].sum() * 0.25 == pytest.approx(20.0, abs=1e-6)


def test_solve_lp_agg_cap_infeasible_raises(fixture_dir):
    # 5 kW x 2 h = 10 kWh < the 20 kWh requirement -> infeasible LP.
    unit = bvd.load_unit(fixture_dir)
    with pytest.raises(RuntimeError):
        bvd.solve_lp(unit, allow_discharge=False, use_battery=False,
                     ev_agg_cap_kw=5.0)


def test_solve_lp_agg_cap_none_matches_uncapped(fixture_dir):
    unit = bvd.load_unit(fixture_dir)
    a = bvd.solve_lp(unit, allow_discharge=False, use_battery=False)
    b = bvd.solve_lp(unit, allow_discharge=False, use_battery=False,
                     ev_agg_cap_kw=1e9)
    assert a["lp_peak_kw"] == pytest.approx(b["lp_peak_kw"], abs=1e-6)


# ── PART 4b: pure helpers ─────────────────────────────────────────────

def test_satisfaction_stats():
    requested = {"a": 10.0, "b": 5.0, "c": 0.0}
    delivered = {"a": 9.96, "b": 4.0}  # a within the 0.05 kWh tolerance
    n_sat, req, dlv = bvd.satisfaction_stats(requested, delivered)
    assert n_sat == 2  # a (within tol) and c (0-need, delivered 0 >= -tol)
    assert req == pytest.approx(15.0)
    assert dlv == pytest.approx(13.96)


def test_build_scenario_frames(fixture_dir):
    unit = bvd.load_unit(fixture_dir)
    sess, cars, bl = bvd.build_scenario_frames(unit)
    assert list(sess["session_id"]) == [1]
    assert sess.loc[0, "arrival"] == unit.times[0]
    assert sess.loc[0, "departure"] == unit.times[0] + pd.Timedelta(hours=2)
    assert sess.loc[0, "arrival_soc"] == pytest.approx(20.0)
    assert sess.loc[0, "required_soc_at_depart"] == pytest.approx(60.0)
    assert cars.loc[1, "capacity_kwh"] == pytest.approx(50.0)
    assert len(bl) == T


# ── PART 4b: contended benchmark ──────────────────────────────────────

def _contended_fixture(tmp_path):
    """Two overlapping sessions of the same car on a 1-charger pool:
    FCFS admission must reject the second. Session 1 spans the horizon
    (needs 20 kWh, laxity 1 h); session 2 arrives 15 min later (needs
    10 kWh: arrival 60% - 15% external use = 45%, required 65%)."""
    two = pd.DataFrame({
        "car_id": [1, 1],
        "arrival": [START.strftime("%Y-%m-%d %H:%M:%S"),
                    (START + pd.Timedelta(minutes=15)).strftime(
                        "%Y-%m-%d %H:%M:%S")],
        "required_soc_at_depart": [60.0, 65.0],
        "previous_day_external_use_soc": [0.0, 15.0],
        "duration": [7200, 3600], "session_id": [1, 2], "building_id": [0, 0],
    })
    return _write_fixture(tmp_path, two)


def test_contended_benchmark_smoke(tmp_path):
    pytest.importorskip("acnportal")
    d = _contended_fixture(tmp_path)
    res = bvd.run_contended_benchmark(d, feeder_kw_ratio=0.5)
    arms = res["arms"]
    # 1 charger x 20 kW -> plug cap 20 kW, feeder cap 10 kW
    assert res["params"]["plug_cap_kw"] == pytest.approx(20.0)
    assert res["params"]["feeder_kw"] == pytest.approx(10.0)
    # admission: second (overlapping) session rejected, for EVERY algorithm
    for algo in bvd.ACNSIM_ALGOS:
        r = arms[f"acnsim_{algo}"]
        assert (r["n_admitted"], r["n_rejected"]) == (1, 1)
    # LLF under the 10 kW feeder cap still serves the admitted 20 kWh
    llf = arms["acnsim_llf"]
    assert llf["kwh_delivered"] == pytest.approx(20.0, abs=0.1)
    assert llf["n_satisfied"] == 1
    assert llf["satisfied_pct_offered"] == pytest.approx(50.0)
    # LP plug-cap relaxation serves ALL sessions (30 kWh, no admission)
    lp = arms["v1g_lp_plugcap"]
    assert (lp["n_admitted"], lp["n_rejected"]) == (2, 0)
    assert lp["kwh_delivered"] == pytest.approx(30.0, abs=1e-6)
    # feeder-cap LP (10 kW x 2 h = 20 kWh < 30 kWh) is honestly infeasible
    assert arms["v1g_lp_feedercap"]["status"].startswith("infeasible")
    # reference arm reproduces the unconstrained uncontrolled semantics
    assert arms["uncontrolled_nolimit"]["kwh_requested"] == pytest.approx(30.0)


def test_repro_paper_wires_contended_step():
    import repro_paper as rp
    assert "contended_bench" in rp.STEPS
    assert rp.STEPS.index("contended_bench") < rp.STEPS.index("collect")
    assert "contended_bench" in rp.STEP_FNS
    # the committed generation config the step regenerates the unit from
    assert rp.CONTENDED_CONFIG.exists()


def test_contended_outputs_deterministic(tmp_path):
    pytest.importorskip("acnportal")
    d = _contended_fixture(tmp_path)
    r1 = bvd.run_contended_benchmark(d, feeder_kw_ratio=0.5)
    r2 = bvd.run_contended_benchmark(d, feeder_kw_ratio=0.5)
    rows1, rows2 = bvd.contended_rows(r1), bvd.contended_rows(r2)

    def _nan_safe(rows):
        return [{k: (None if v != v else v) if isinstance(v, float) else v
                 for k, v in r.items()} for r in rows]

    assert _nan_safe(rows1) == _nan_safe(rows2)

    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    bvd.write_contended_outputs(d, out1, r1)
    bvd.write_contended_outputs(d, out2, r2)
    for name in ("contended_bench.csv", "contended_bench.md"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
    csv = pd.read_csv(out1 / "contended_bench.csv")
    # determinism gate: no wall-time columns anywhere
    assert not any("solve" in c or "time" in c for c in csv.columns)
    assert list(csv.columns) == bvd.CONTENDED_COLS


def test_outputs_written(fixture_dir, tmp_path):
    out = tmp_path / "out"
    res = bvd.run_benchmark(fixture_dir, with_acnsim=False)
    bvd.write_outputs(fixture_dir, out, res)
    csv = pd.read_csv(out / "v2b_dispatch.csv")
    assert set(csv["arm"]) == {"uncontrolled", "v1g", "v2b"}
    assert (out / "v2b_dispatch.md").read_text().startswith(
        "# V2B dispatch baseline")
