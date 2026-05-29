"""Smoke tests for the ACN-Sim-backed bench harness.

Uses the `fast_generate` fixture (7-day window) for speed. Verifies:
- adapter constructs ChargingNetwork + EventQueue from generated CSVs
- run_scenario returns a valid MetricsResult for every registered algorithm
- bench CLI subcommand returns rc=0 and emits parsable JSON
"""
from __future__ import annotations

import json

import pytest

from v2b_syndata.bench import (
    ALGORITHMS,
    MetricsResult,
    available_algorithms,
    run_scenario,
)
from v2b_syndata.bench.adapter import build_acnsim_inputs, load_scenario
from v2b_syndata.cli import main


def test_registry_lists_seven_algorithms():
    assert set(available_algorithms()) == {
        "edf", "llf", "fcfs", "lcfs", "lrpt", "round_robin", "uncontrolled",
    }
    # Each entry is a zero-arg callable returning an algorithm instance
    for name, factory in ALGORITHMS.items():
        inst = factory()
        assert hasattr(inst, "schedule") or hasattr(inst, "run"), \
            f"{name} not an ACN-Sim algorithm"


def test_adapter_loads_scenario(fast_generate):
    scenario_dir, _ = fast_generate()
    inputs = load_scenario(scenario_dir)
    assert len(inputs.cars) > 0
    assert len(inputs.chargers) > 0
    assert len(inputs.sessions) > 0
    assert inputs.sim_start < inputs.sim_end


def test_adapter_builds_acnsim_inputs(fast_generate):
    scenario_dir, _ = fast_generate()
    inputs = load_scenario(scenario_dir)
    acn = build_acnsim_inputs(inputs)
    # n_chargers EVSEs (not n_cars). FCFS admission pre-stages PluginEvents.
    assert len(acn.network.station_ids) == len(inputs.chargers)
    # At least one PluginEvent enqueued
    assert acn.events._queue, "no events enqueued"
    # Aggregate-current constraint registered
    assert acn.network.constraint_matrix is not None
    # Admission stats are accounted for
    assert acn.admission.n_offered == len(inputs.sessions)
    assert acn.admission.n_admitted + acn.admission.n_rejected == acn.admission.n_offered


def test_adapter_admission_no_overlap_at_same_charger(fast_generate):
    """Two sessions admitted to the same charger must not overlap in time."""
    from v2b_syndata.bench.adapter import _fcfs_admit
    scenario_dir, _ = fast_generate()
    inputs = load_scenario(scenario_dir)
    admitted, _ = _fcfs_admit(inputs.sessions, n_chargers=len(inputs.chargers))
    # For each assigned charger, verify the per-charger schedule is
    # strictly non-overlapping when sorted by arrival.
    for cidx, group in admitted.groupby("assigned_charger_idx"):
        sg = group.sort_values("arrival").reset_index(drop=True)
        prior_dep = sg["departure"].shift(1)
        # arrival[i] must be >= departure[i-1]
        violations = (sg["arrival"] < prior_dep).sum()
        assert violations == 0, f"charger {cidx} has overlapping sessions"


def test_run_scenario_edf_smoke(fast_generate):
    scenario_dir, _ = fast_generate()
    result = run_scenario(scenario_dir=scenario_dir, algorithm="edf")
    assert isinstance(result, MetricsResult)
    assert result.algorithm == "edf"
    assert result.n_sessions_offered > 0
    assert result.n_sessions_admitted + result.n_sessions_rejected == result.n_sessions_offered
    assert 0.0 <= result.admission_rejection_rate <= 1.0
    assert 0.0 <= result.energy_fulfillment_rate <= 1.5  # uncontrolled can exceed 1
    assert 0.0 <= result.target_miss_rate <= 1.0
    assert 0.0 <= result.e2e_miss_rate <= 1.0
    assert result.peak_charge_kw >= 0
    assert result.peak_net_kw >= 0
    assert result.runtime_sec > 0


@pytest.mark.parametrize("algo", sorted(ALGORITHMS.keys()))
def test_all_algorithms_run(fast_generate, algo):
    scenario_dir, _ = fast_generate()
    result = run_scenario(scenario_dir=scenario_dir, algorithm=algo)
    assert result.algorithm == algo
    assert result.n_sessions_offered > 0
    # Shape sanity — every algo must emit positive runtime + non-negative power.
    assert result.runtime_sec > 0
    assert result.peak_charge_kw >= 0


def test_unknown_algorithm_raises(fast_generate):
    scenario_dir, _ = fast_generate()
    with pytest.raises(ValueError, match="unknown algorithm"):
        run_scenario(scenario_dir=scenario_dir, algorithm="nope")


def test_bench_cli_returns_json(fast_generate, tmp_path, capsys):
    scenario_dir, _ = fast_generate()
    out_path = tmp_path / "result.json"
    rc = main([
        "bench",
        "--scenario-dir", str(scenario_dir),
        "--algo", "edf",
        "--out", str(out_path),
    ])
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["algorithm"] == "edf"
    assert payload["n_sessions_offered"] > 0
    assert "peak_charge_kw" in payload
    assert "admission_rejection_rate" in payload
    assert "e2e_miss_rate" in payload


def test_bench_cli_unknown_algo_rc2(fast_generate, capsys):
    scenario_dir, _ = fast_generate()
    rc = main([
        "bench",
        "--scenario-dir", str(scenario_dir),
        "--algo", "definitely_not_an_algorithm",
    ])
    assert rc == 2
