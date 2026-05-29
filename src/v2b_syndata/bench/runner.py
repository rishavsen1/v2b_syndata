"""Run one (scenario, algorithm) → MetricsResult."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytz
from acnportal import acnsim

from .adapter import build_acnsim_inputs, load_scenario
from .algorithms import ALGORITHMS, available_algorithms
from .metrics import MetricsResult

_ENERGY_TOL_KWH = 0.05  # session counts as satisfied if delivered ≥ requested - tol


def run_scenario(
    scenario_dir: str | Path,
    algorithm: str,
    *,
    period_min: int = 5,
    voltage: float = 208.0,
    tz: str = "America/Los_Angeles",
) -> MetricsResult:
    """Run one ACN-Sim simulation over a v2b scenario output directory.

    Parameters
    ----------
    scenario_dir : path to a v2b generate output directory (the 7 CSVs).
    algorithm    : key in `ALGORITHMS` (one of `available_algorithms()`).
    period_min   : ACN-Sim tick length, minutes. 5 = ACN default; v2b
                   CSVs are 15-min so 5-min ticks resample finer.
    voltage      : EVSE supply voltage; only affects kW↔A conversion.
    tz           : timezone for ACN-Sim's wall-clock start anchor;
                   does not affect simulation outcome.
    """
    scenario_dir = Path(scenario_dir)
    if algorithm not in ALGORITHMS:
        raise ValueError(
            f"unknown algorithm {algorithm!r}. "
            f"available: {available_algorithms()}"
        )

    t0 = time.perf_counter()

    inputs = load_scenario(scenario_dir)
    acn_inputs = build_acnsim_inputs(inputs, period_min=period_min, voltage=voltage)

    pytz_tz = pytz.timezone(tz)
    sim_start_tz = pytz_tz.localize(acn_inputs.sim_start.to_pydatetime().replace(tzinfo=None))

    algo = ALGORITHMS[algorithm]()
    sim = acnsim.Simulator(
        acn_inputs.network,
        algo,
        acn_inputs.events,
        sim_start_tz,
        period=period_min,
        verbose=False,
    )
    sim.run()

    metrics = _compute_metrics(
        sim=sim,
        algorithm=algorithm,
        sessions=inputs.sessions,
        cars=inputs.cars,
        building_load=inputs.building_load,
        admission=acn_inputs.admission,
        period_min=period_min,
        scenario_dir=scenario_dir,
    )
    metrics.runtime_sec = time.perf_counter() - t0
    return metrics


def _compute_metrics(
    *,
    sim,
    algorithm: str,
    sessions,
    cars,
    building_load,
    admission,
    period_min: int,
    scenario_dir: Path,
) -> MetricsResult:
    # Scenario id / seed from the manifest if present
    scenario_id = ""
    seed = -1
    manifest_path = scenario_dir / "manifest.json"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text())
            scenario_id = m.get("scenario_id", "")
            seed = int(m.get("seed", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    # Aggregate charge power over sim ticks (kW).
    agg_kw_per_tick = np.asarray(acnsim.aggregate_power(sim), dtype=float)

    # Net load = building inflex + flex + EV charge, on the BUILDING grid.
    # Building is 15-min; agg is `period_min`. Resample both to a common
    # base (the simulation tick) by forward-filling building.
    n_ticks = len(agg_kw_per_tick)
    sim_start = building_load["datetime"].min()
    tick_index = (
        sim_start + np.arange(n_ticks) * np.timedelta64(period_min, "m")
    )
    bl = (
        building_load.set_index("datetime")["power_kw"]
        .reindex(tick_index, method="ffill")
        .to_numpy()
    )
    net_kw = bl + agg_kw_per_tick

    # Per-session fulfillment from sim.ev_history (ACN-Sim's per-EV record).
    requested = {str(ev.session_id): float(ev.requested_energy)
                 for ev in sim.ev_history.values()}
    delivered = {str(ev.session_id): float(ev.energy_delivered)
                 for ev in sim.ev_history.values()}

    total_req = sum(requested.values())
    total_del = sum(delivered.values())
    fulfillment_rate = (total_del / total_req) if total_req > 0 else 1.0

    per_session_fulfillment = []
    n_satisfied = 0
    for sid, req in requested.items():
        d = delivered.get(sid, 0.0)
        ratio = (d / req) if req > 0 else 1.0
        per_session_fulfillment.append(ratio)
        if d >= req - _ENERGY_TOL_KWH:
            n_satisfied += 1
    n_admitted = len(requested)
    target_miss = 1.0 - (n_satisfied / n_admitted) if n_admitted else 0.0

    # End-to-end miss rate: admission-rejected sessions + admitted-but-missed
    # sessions, over all offered sessions.
    n_offered = admission.n_offered
    n_rejected = admission.n_rejected
    n_e2e_miss = n_rejected + (n_admitted - n_satisfied)
    e2e_miss_rate = (n_e2e_miss / n_offered) if n_offered else 0.0

    return MetricsResult(
        algorithm=algorithm,
        scenario_id=scenario_id,
        seed=seed,
        n_sessions_offered=n_offered,
        n_sessions_admitted=n_admitted,
        n_sessions_rejected=n_rejected,
        admission_rejection_rate=admission.rejection_rate,
        total_kwh_requested=total_req,
        total_kwh_delivered=total_del,
        energy_fulfillment_rate=fulfillment_rate,
        n_sessions_satisfied=n_satisfied,
        target_miss_rate=target_miss,
        e2e_miss_rate=e2e_miss_rate,
        per_session_fulfillment=per_session_fulfillment,
        peak_charge_kw=float(agg_kw_per_tick.max()) if n_ticks else 0.0,
        peak_net_kw=float(net_kw.max()) if n_ticks else 0.0,
    )
