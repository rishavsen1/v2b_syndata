#!/usr/bin/env python
"""V2B dispatch baseline: LP peak-shaving benchmark on one released corpus unit.

Runs three dispatch arms over a single optimus-schema building-month
(default: the released campus10 unit ``data/output/campus10/b1/JUL2024/0``):

  uncontrolled  charge every session at its charger's max rate from arrival
                until required_soc_at_depart is met (no optimization);
  v1g           smart charging LP — charging only, no vehicle discharge, no
                stationary battery;
  v2b           smart charging LP + vehicle discharge on bidirectional-
                assigned sessions + the stationary battery.

Formulation (single LP per optimized arm, scipy linprog / HiGHS):

  min  P  +  1e-4 * dt * sum_t price_t * (sum_s c_{s,t} + bc_t)

  s.t. for all t:   load_t + sum_s c_{s,t} - sum_s d_{s,t}
                       + bc_t - bd_t - pv_t  <=  P                (peak)
       per session s (window [t0, t1), per-step SoC state e_{s,k} in kWh):
         e_{s,0} = arrival_kwh + dt*(c_{s,0} - d_{s,0})
         e_{s,k} = e_{s,k-1}   + dt*(c_{s,k} - d_{s,k})
         floor_kwh <= e_{s,k} <= max_allowed_kwh
         e_{s,L-1} >= required_kwh                              (departure)
         0 <= c_{s,k} <= p_charge_s ;  0 <= d_{s,k} <= p_discharge_s
       stationary battery (v2b arm only):
         E_0 = E_init + dt*(sqrt(eta)*bc_0 - bd_0/sqrt(eta))
         E_t = E_{t-1} + dt*(sqrt(eta)*bc_t - bd_t/sqrt(eta))
         E_min <= E_t <= E_max ;  E_{T-1} >= E_init  (no free energy)
         0 <= bc_t, bd_t <= power_kw

The vehicle side is modeled lossless (charger rates are taken at the vehicle
battery); the stationary battery's round-trip efficiency eta is split as
sqrt(eta) on each direction. The 1e-4 price term is a tie-break only: it makes
the solution unique/deterministic and breaks simultaneous charge+discharge
degeneracy without materially changing the peak objective.

Data-reconstruction rules (documented because the optimus schema does not
carry them explicitly):

* Per-session arrival SoC. optimus sessions.csv has no arrival_soc column;
  cars.csv ``soc`` is each car's FIRST-session arrival SoC (export_optimus.
  build_cars). The generator defines previous_day_external_use_soc =
  max(0, prior_required_soc - arrival_soc) (docs/DESIGN_NOTES.md section 3),
  so we reconstruct, per car in arrival order:
      arrival_soc(1st session) = cars.soc
      arrival_soc(k)           = required_soc(k-1) - previous_day_external_use_soc(k)
  This is exact whenever previous_day_external_use_soc > 0 and otherwise a
  lower bound (the car cannot have gained charge off-site), i.e. the
  conservative reconstruction a downstream simulator would use.

* Charger assignment / discharge eligibility. optimus sessions are not bound
  to chargers. Sessions are sorted by (arrival, session_id) and session i is
  assigned to charger ``i mod n_chargers`` in chargers.csv file order; the
  session charges at that charger's max rate and may discharge (v2b arm) up
  to |min rate| iff the charger is bidirectional. With the released unit's
  48/60 bidirectional chargers this deterministically grants discharge to
  ~80% of sessions, matching the fleet's bidirectional share. This is a
  dispatch bound, not a plug-level allocation simulation (concurrent sessions
  may map to the same charger id).

* Feasibility guard. required_soc is clamped to min(max_allowed_soc,
  reachable SoC at the assigned charger's max rate within the in-horizon
  window); every clamp is counted and reported as a relaxation. Session
  windows are clipped to the month horizon (clips are counted too).

ACN-Sim cross-check (labeled ``*_crosscheck``; the LP remains the primary for
the three main arms): the repo's established ACN-Sim bench machinery
(src/v2b_syndata/bench/, V1G-only by design, building-load-unaware) is run on
the SAME unit — the optimus CSVs are adapted in-memory into the native-schema
``ScenarioInputs`` the adapter expects, using the same arrival-SoC
reconstruction — at 15-min ticks with the unbinding feeder default, and its
charging schedule is added to building_load - PV to compute the identical
monthly-peak-of-net metric. ALL SEVEN stock V1G schedulers are run
(EDF/LLF/FCFS/LCFS/LRPT/RoundRobin/Uncontrolled). Because the stock
algorithms are building-load-unaware and the charger pool is uncontended here
(60 chargers, non-overlapping per-car sessions, unbinding feeder), every
queue-ordering algorithm charges each EV at max rate until its requested
energy is met — i.e. they all coincide with the *uncontrolled* arm, and a
near-zero delta against it independently validates the demand model (windows,
arrival-SoC chain, energy needs) through an established simulator. The point
of the table is exactly that queue algorithms cannot help without a queue;
the delta against LP-V1G measures the value of building-load-aware
scheduling, not an inconsistency.

Contended benchmark (``--contended``; separate outputs
docs/experiments/contended_bench.{md,csv}): the same machinery on a unit
whose charger pool is deliberately scarce (charging_infra.charger_count
reduced below the fleet's realized peak concurrency) plus a binding feeder
cap (``--feeder-ratio``, default 0.125 = the ACN-Caltech-like service ratio
documented in bench/adapter.py). Plug scarcity is resolved by the adapter's
FCFS admission (a pool policy — identical for every algorithm; rejected
sessions never plug in, so there is no queueing delay to report); the feeder
cap is what the scheduling algorithms actually contend over. LP arms on the
contended unit are labeled RELAXATIONS: the LP's static session→charger
assignment cannot express plug contention (a faithful model needs big-M /
integer machinery, deliberately not attempted), so the LP instead serves ALL
sessions under an aggregate EV-power cap — ``plugcap`` = charger_count × rate
(the honest fractional-plug-sharing proxy) and ``feedercap`` = the same
feeder cap the ACN-Sim arms see.

Outputs: docs/experiments/v2b_dispatch.md (memo) and v2b_dispatch.csv
(machine-readable; consumed by tools/repro_paper.py step ``collect``), or
contended_bench.{md,csv} with --contended. The CSVs and the contended memo
are byte-deterministic (no RNG, no wall-time columns; the LP optimum is
unique under the tie-break); only v2b_dispatch.md carries wall times.

Usage:
    uv run python tools/bench_v2b_dispatch.py
    uv run python tools/bench_v2b_dispatch.py --data-dir <unit> --out-dir <dir>
    uv run python tools/bench_v2b_dispatch.py --skip-acnsim
    uv run python tools/bench_v2b_dispatch.py --contended [--feeder-ratio 0.125]
"""
from __future__ import annotations

import argparse
import ast
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.optimize import linprog

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
DEFAULT_DATA = REPO / "data" / "output" / "campus10" / "b1" / "JUL2024" / "0"
DEFAULT_CONTENDED_DATA = (REPO / "data" / "output" / "contended" / "b1ch35"
                          / "JUL2024" / "0")
DEFAULT_OUT = REPO / "docs" / "experiments"

TICK_S = 900
DT_H = TICK_S / 3600.0  # 0.25 h
TIE_BREAK = 1e-4
ENERGY_TOL_KWH = 0.05   # session satisfied iff delivered >= requested - tol
                        # (same tolerance as bench.runner._ENERGY_TOL_KWH)
# Feeder-to-theoretical-max ratio for the contended benchmark. 0.125 is the
# ACN-Caltech-like service ratio documented in bench/adapter.py — tight
# enough that the schedulers must ration power (they separate), loose enough
# that deadline-aware orderings (EDF/LLF) still satisfy every admitted
# session (the problem stays feasible).
CONTENDED_FEEDER_RATIO = 0.125


# ──────────────────────────────────────────────────────────────────────
# Data loading / reconstruction
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    session_id: int
    car_id: int
    t0: int              # first 15-min step index (inclusive)
    t1: int              # last step index (exclusive), clipped to horizon
    p_charge: float      # kW (assigned charger max rate)
    p_discharge: float   # kW (>=0; 0 unless bidirectional-assigned, v2b arm)
    cap_kwh: float
    arrival_kwh: float
    required_kwh: float  # after feasibility clamp
    floor_kwh: float     # min(arrival, min_allowed) * cap
    max_kwh: float       # max_allowed * cap
    relaxed: bool        # required_soc was clamped down
    clipped: bool        # window clipped to horizon

    @property
    def length(self) -> int:
        return self.t1 - self.t0


@dataclass
class Unit:
    times: pd.DatetimeIndex
    load_kw: np.ndarray
    pv_kw: np.ndarray
    price: np.ndarray
    battery: dict
    sessions: list[Session]
    chargers_native: pd.DataFrame  # charger_id, max_rate_kw, min_rate_kw
    n_relaxed: int
    n_clipped: int
    n_skipped: int
    n_bidirectional_sessions: int


def _parse_rate(s: str) -> tuple[float, float]:
    lo, hi = ast.literal_eval(s)
    return float(lo), float(hi)


def load_unit(data_dir: Path) -> Unit:
    bl = pd.read_csv(data_dir / "building_load.csv")
    pv = pd.read_csv(data_dir / "pv_generation.csv")
    gp = pd.read_csv(data_dir / "grid_prices.csv", index_col=0)
    cars = pd.read_csv(data_dir / "cars.csv", index_col=0).set_index("car_id")
    chargers = pd.read_csv(data_dir / "chargers.csv", index_col=0)
    sessions = pd.read_csv(data_dir / "sessions.csv", index_col=0)
    batt = pd.read_csv(data_dir / "battery.csv").iloc[0]

    times = pd.DatetimeIndex(pd.to_datetime(bl["datetime"]))
    if not ((times.values == pd.to_datetime(pv["datetime"]).values).all()
            and (times.values == pd.to_datetime(gp["datetime"]).values).all()):
        raise ValueError("building_load / pv_generation / grid_prices time grids differ")
    T = len(times)
    t_start = times[0]

    rates = [_parse_rate(r) for r in chargers["charge_rates_kw"]]
    bidir = [lo < 0 for lo, _ in rates]

    s = sessions.copy()
    s["_arr"] = pd.to_datetime(s["arrival"])
    s = s.sort_values(["_arr", "session_id"], kind="mergesort").reset_index(drop=True)

    # Reconstruct per-session arrival SoC (percent) per car, arrival order.
    arrival_pct = np.empty(len(s))
    prev_required: dict[int, float] = {}
    for i, row in s.iterrows():
        cid = row["car_id"]
        if cid not in prev_required:
            arrival_pct[i] = float(cars.loc[cid, "soc"])
        else:
            arrival_pct[i] = prev_required[cid] - float(row["previous_day_external_use_soc"])
        prev_required[cid] = float(row["required_soc_at_depart"])

    out: list[Session] = []
    n_relaxed = n_clipped = n_skipped = n_bidir = 0
    for i, row in s.iterrows():
        cid = row["car_id"]
        cap = float(cars.loc[cid, "capacity_kwh"])
        min_pct = float(cars.loc[cid, "min_allowed_soc"])
        max_pct = float(cars.loc[cid, "max_allowed_soc"])
        t0 = int(round((row["_arr"] - t_start).total_seconds() / TICK_S))
        t1 = t0 + int(round(float(row["duration"]) / TICK_S))
        clipped = t0 < 0 or t1 > T
        t0c, t1c = max(t0, 0), min(t1, T)
        if t1c <= t0c:
            n_skipped += 1
            continue
        n_clipped += int(clipped)

        lo, hi = rates[i % len(rates)]
        p_charge = float(hi)
        p_discharge = float(-lo) if bidir[i % len(rates)] else 0.0
        n_bidir += int(p_discharge > 0)

        a_pct = float(arrival_pct[i])
        r_pct = min(float(row["required_soc_at_depart"]), max_pct)
        reachable_pct = a_pct + 100.0 * p_charge * (t1c - t0c) * DT_H / cap
        relaxed = False
        if r_pct > reachable_pct + 1e-9:
            r_pct = reachable_pct
            relaxed = True
            n_relaxed += 1

        out.append(Session(
            session_id=int(row["session_id"]), car_id=int(cid),
            t0=t0c, t1=t1c, p_charge=p_charge, p_discharge=p_discharge,
            cap_kwh=cap,
            arrival_kwh=a_pct / 100.0 * cap,
            required_kwh=r_pct / 100.0 * cap,
            floor_kwh=min(a_pct, min_pct) / 100.0 * cap,
            max_kwh=max_pct / 100.0 * cap,
            relaxed=relaxed, clipped=clipped,
        ))

    battery = {
        "cap_kwh": float(batt["capacity_kwh"]),
        "power_kw": float(batt["power_kw"]),
        "eta_rt": float(batt["round_trip_efficiency"]),
        "e_min": float(batt["min_soc_pct"]) / 100.0 * float(batt["capacity_kwh"]),
        "e_max": float(batt["max_soc_pct"]) / 100.0 * float(batt["capacity_kwh"]),
        "e_init": float(batt["initial_soc_pct"]) / 100.0 * float(batt["capacity_kwh"]),
    }
    chargers_native = pd.DataFrame({
        "charger_id": chargers["charger_id"].values,
        "min_rate_kw": [lo for lo, _ in rates],
        "max_rate_kw": [hi for _, hi in rates],
    })
    return Unit(
        times=times, load_kw=bl["power_kw"].to_numpy(float),
        pv_kw=pv["power_pv_kw"].to_numpy(float),
        price=gp["price_per_kwh"].to_numpy(float), battery=battery,
        sessions=out, chargers_native=chargers_native,
        n_relaxed=n_relaxed, n_clipped=n_clipped,
        n_skipped=n_skipped, n_bidirectional_sessions=n_bidir,
    )


# ──────────────────────────────────────────────────────────────────────
# Arms
# ──────────────────────────────────────────────────────────────────────

def simulate_uncontrolled(unit: Unit) -> np.ndarray:
    """Charge at max rate from arrival until required SoC met (partial final
    step so the requirement is hit exactly). Returns EV load in kW per step."""
    T = len(unit.times)
    ev = np.zeros(T)
    for s in unit.sessions:
        need = s.required_kwh - s.arrival_kwh  # > 0 by D6 + reconstruction
        for t in range(s.t0, s.t1):
            if need <= 1e-12:
                break
            e = min(s.p_charge * DT_H, need)
            ev[t] += e / DT_H
            need -= e
    return ev


def solve_lp(unit: Unit, *, allow_discharge: bool, use_battery: bool,
             ev_agg_cap_kw: float | None = None) -> dict:
    """Peak-shaving LP. Returns dict with ev_kw, batt_kw (net), status, etc.

    ``ev_agg_cap_kw`` adds, per step t, ``sum_s (c_{s,t} + d_{s,t}) <= cap``:
    an aggregate cap on power flowing through the EV plugs (discharge counts —
    a plug carries |power| regardless of direction; the stationary battery is
    behind the meter and exempt). This is the honest LP proxy for charger
    contention: it cannot say WHO plugs in (that needs integer machinery),
    only how much total plug power exists. Raises RuntimeError if infeasible.
    """
    T = len(unit.times)
    sess = unit.sessions
    load, pv, price = unit.load_kw, unit.pv_kw, unit.price

    # Variable layout: [P | per-session (c_k, d_k?, e_k) | bc_t, bd_t, E_t?]
    n_var = 1
    offs = []  # (c_off, d_off_or_-1, e_off) per session
    for s in sess:
        L = s.length
        c_off = n_var
        d_off = -1
        n_var += L
        if allow_discharge and s.p_discharge > 0:
            d_off = n_var
            n_var += L
        e_off = n_var
        n_var += L
        offs.append((c_off, d_off, e_off))
    if use_battery:
        bc_off, bd_off, E_off = n_var, n_var + T, n_var + 2 * T
        n_var += 3 * T

    lb = np.zeros(n_var)
    ub = np.full(n_var, np.inf)
    cost = np.zeros(n_var)
    cost[0] = 1.0  # P
    lb[0] = -np.inf

    ub_rows: list[np.ndarray] = []
    ub_cols: list[np.ndarray] = []
    ub_vals: list[np.ndarray] = []
    eq_rows: list[np.ndarray] = []
    eq_cols: list[np.ndarray] = []
    eq_vals: list[np.ndarray] = []
    b_eq: list[np.ndarray] = []
    n_eq = 0

    def add(triplets, r, c, v):
        triplets[0].append(np.asarray(r, dtype=np.int64))
        triplets[1].append(np.asarray(c, dtype=np.int64))
        triplets[2].append(np.asarray(v, dtype=float))

    UB = (ub_rows, ub_cols, ub_vals)
    EQ = (eq_rows, eq_cols, eq_vals)

    # Peak rows 0..T-1:  sum c - sum d + bc - bd - P <= pv - load
    # Aggregate-cap rows T..2T-1 (only when ev_agg_cap_kw is set):
    #   sum_s c_{s,t} + d_{s,t} <= ev_agg_cap_kw
    n_ub_rows = T + (T if ev_agg_cap_kw is not None else 0)
    add(UB, np.arange(T), np.zeros(T, dtype=np.int64), -np.ones(T))

    for s, (c_off, d_off, e_off) in zip(sess, offs, strict=True):
        L = s.length
        k = np.arange(L)
        t = s.t0 + k
        # bounds
        ub[c_off:c_off + L] = s.p_charge
        cost[c_off:c_off + L] = TIE_BREAK * DT_H * price[t]
        lb[e_off:e_off + L] = s.floor_kwh
        ub[e_off:e_off + L] = s.max_kwh
        lb[e_off + L - 1] = s.required_kwh  # departure requirement
        # peak rows
        add(UB, t, c_off + k, np.ones(L))
        if ev_agg_cap_kw is not None:
            add(UB, T + t, c_off + k, np.ones(L))
        if d_off >= 0:
            ub[d_off:d_off + L] = s.p_discharge
            add(UB, t, d_off + k, -np.ones(L))
            if ev_agg_cap_kw is not None:
                add(UB, T + t, d_off + k, np.ones(L))
        # SoC dynamics: e_k - e_{k-1} - dt*c_k + dt*d_k = (k==0)*arrival_kwh
        r = n_eq + k
        add(EQ, r, e_off + k, np.ones(L))
        if L > 1:
            add(EQ, r[1:], e_off + k[:-1], -np.ones(L - 1))
        add(EQ, r, c_off + k, np.full(L, -DT_H))
        if d_off >= 0:
            add(EQ, r, d_off + k, np.full(L, DT_H))
        rhs = np.zeros(L)
        rhs[0] = s.arrival_kwh
        b_eq.append(rhs)
        n_eq += L

    if use_battery:
        bat = unit.battery
        se = np.sqrt(bat["eta_rt"])
        t = np.arange(T)
        ub[bc_off:bc_off + T] = bat["power_kw"]
        ub[bd_off:bd_off + T] = bat["power_kw"]
        cost[bc_off:bc_off + T] = TIE_BREAK * DT_H * price
        lb[E_off:E_off + T] = bat["e_min"]
        ub[E_off:E_off + T] = bat["e_max"]
        # terminal E >= E_init (no free energy)
        lb[E_off + T - 1] = max(bat["e_min"], bat["e_init"])
        # peak rows
        add(UB, t, bc_off + t, np.ones(T))
        add(UB, t, bd_off + t, -np.ones(T))
        # dynamics: E_t - E_{t-1} - dt*sqrt(eta)*bc_t + dt/sqrt(eta)*bd_t = 0
        r = n_eq + t
        add(EQ, r, E_off + t, np.ones(T))
        add(EQ, r[1:], E_off + t[:-1], -np.ones(T - 1))
        add(EQ, r, bc_off + t, np.full(T, -DT_H * se))
        add(EQ, r, bd_off + t, np.full(T, DT_H / se))
        rhs = np.zeros(T)
        rhs[0] = bat["e_init"]
        b_eq.append(rhs)
        n_eq += T

    A_ub = sp.coo_matrix(
        (np.concatenate(ub_vals),
         (np.concatenate(ub_rows), np.concatenate(ub_cols))),
        shape=(n_ub_rows, n_var)).tocsc()
    b_ub = pv - load
    if ev_agg_cap_kw is not None:
        b_ub = np.concatenate([b_ub, np.full(T, float(ev_agg_cap_kw))])
    A_eq = sp.coo_matrix(
        (np.concatenate(eq_vals),
         (np.concatenate(eq_rows), np.concatenate(eq_cols))),
        shape=(n_eq, n_var)).tocsc()

    t_solve = time.perf_counter()
    res = linprog(cost, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq,
                  b_eq=np.concatenate(b_eq), bounds=np.column_stack([lb, ub]),
                  method="highs")
    solve_s = time.perf_counter() - t_solve
    if res.status != 0:
        raise RuntimeError(f"LP failed: status={res.status} ({res.message})")

    x = res.x
    ev = np.zeros(T)
    for s, (c_off, d_off, _) in zip(sess, offs, strict=True):
        L = s.length
        ev[s.t0:s.t1] += x[c_off:c_off + L]
        if d_off >= 0:
            ev[s.t0:s.t1] -= x[d_off:d_off + L]
    batt_net = np.zeros(T)
    if use_battery:
        batt_net = x[bc_off:bc_off + T] - x[bd_off:bd_off + T]
    return {"ev_kw": ev, "batt_kw": batt_net, "status": "optimal",
            "solve_s": solve_s, "n_var": n_var,
            "n_constraints": n_ub_rows + n_eq, "lp_peak_kw": float(x[0])}


# All seven stock ACN-Sim V1G schedulers shipped by the repo bench registry
# (src/v2b_syndata/bench/algorithms.py). Order is the fixed report order.
ACNSIM_ALGOS = ("edf", "llf", "fcfs", "lcfs", "lrpt", "round_robin",
                "uncontrolled")


def build_scenario_frames(
    unit: Unit,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(sessions, cars, building_load) DataFrames in the native schema the
    bench adapter consumes — same arrival-SoC chain and relaxed required_soc
    as the LP arms, for a like-for-like comparison. Pure pandas."""
    times = unit.times
    step = pd.Timedelta(seconds=TICK_S)
    sess_df = pd.DataFrame({
        "session_id": [s.session_id for s in unit.sessions],
        "car_id": [s.car_id for s in unit.sessions],
        "arrival": [times[s.t0] for s in unit.sessions],
        "departure": [times[0] + s.t1 * step for s in unit.sessions],
        "arrival_soc": [100.0 * s.arrival_kwh / s.cap_kwh
                        for s in unit.sessions],
        "required_soc_at_depart": [100.0 * s.required_kwh / s.cap_kwh
                                   for s in unit.sessions],
    })
    cars_df = (pd.DataFrame({
        "car_id": [s.car_id for s in unit.sessions],
        "capacity_kwh": [s.cap_kwh for s in unit.sessions],
    }).drop_duplicates("car_id").set_index("car_id"))
    bl_df = pd.DataFrame({"datetime": times, "power_kw": unit.load_kw})
    return sess_df, cars_df, bl_df


def satisfaction_stats(
    requested: dict[str, float], delivered: dict[str, float],
    tol: float = ENERGY_TOL_KWH,
) -> tuple[int, float, float]:
    """(n_satisfied, kwh_requested, kwh_delivered) over admitted sessions.

    A session is satisfied iff delivered >= requested - tol — the same
    definition as bench.runner's target-miss accounting.
    """
    n_sat = sum(1 for sid, req in requested.items()
                if delivered.get(sid, 0.0) >= req - tol)
    return n_sat, float(sum(requested.values())), float(sum(delivered.values()))


def _simulate_acnsim(unit: Unit, algo_name: str, *,
                     feeder_kw_ratio: float = 1.0) -> dict:
    """One ACN-Sim run of a stock scheduler over the adapted unit at 15-min
    ticks. Returns ev_kw (on the unit grid), per-session requested/delivered
    kWh dicts, and the adapter's AdmissionStats. Deterministic (no RNG)."""
    import warnings

    import pytz
    from acnportal import acnsim

    from v2b_syndata.bench.adapter import ScenarioInputs, build_acnsim_inputs
    from v2b_syndata.bench.algorithms import ALGORITHMS

    times = unit.times
    T = len(times)
    sess_df, cars_df, bl_df = build_scenario_frames(unit)
    scenario = ScenarioInputs(
        sessions=sess_df, cars=cars_df, chargers=unit.chargers_native,
        building_load=bl_df, sim_start=times[0], sim_end=times[-1])
    acn = build_acnsim_inputs(scenario, period_min=int(TICK_S // 60),
                              feeder_kw_ratio=feeder_kw_ratio)
    tz = pytz.timezone("America/Los_Angeles")
    start = tz.localize(acn.sim_start.to_pydatetime().replace(tzinfo=None))
    sim = acnsim.Simulator(acn.network, ALGORITHMS[algo_name](),
                           acn.events, start,
                           period=int(TICK_S // 60), verbose=False)
    with warnings.catch_warnings():
        # UncontrolledCharging ignores network constraints by design; under a
        # binding feeder cap ACN-Sim warns "Invalid schedule provided" every
        # recompute. Expected and documented — silence just that message.
        warnings.filterwarnings("ignore", message="Invalid schedule provided")
        sim.run()
    agg = np.asarray(acnsim.aggregate_power(sim), dtype=float)
    ev_kw = np.zeros(T)
    n = min(T, len(agg))
    ev_kw[:n] = agg[:n]
    requested = {str(ev.session_id): float(ev.requested_energy)
                 for ev in sim.ev_history.values()}
    delivered = {str(ev.session_id): float(ev.energy_delivered)
                 for ev in sim.ev_history.values()}
    return {"ev_kw": ev_kw, "requested": requested, "delivered": delivered,
            "admission": acn.admission, "feeder_kw": acn.feeder_kw}


def run_acnsim_crosscheck(unit: Unit) -> dict[str, dict]:
    """Cross-check via the repo's established ACN-Sim bench machinery.

    Adapts the reconstructed unit into the native-schema ``ScenarioInputs``
    the bench adapter consumes (same arrival-SoC chain and relaxed
    required_soc as the LP arms, for a like-for-like comparison), runs ALL
    SEVEN stock V1G schedulers at 15-min ticks with the unbinding feeder
    default, and computes the identical peak-of-net metric from the resulting
    charging schedule. Deterministic (no RNG in these schedulers).
    """
    out: dict[str, dict] = {}
    for algo_name in ACNSIM_ALGOS:
        t0 = time.perf_counter()
        sim = _simulate_acnsim(unit, algo_name)
        _, requested, delivered = satisfaction_stats(
            sim["requested"], sim["delivered"])
        adm = sim["admission"]
        out[f"acnsim_{algo_name}_crosscheck"] = {
            **metrics(unit, sim["ev_kw"], np.zeros(len(unit.times))),
            "status": (f"simulated (acnsim; {adm.n_admitted}"
                       f"/{adm.n_offered} admitted; "
                       f"{delivered:,.0f}/{requested:,.0f} kWh delivered)"),
            "solve_s": time.perf_counter() - t0,
            "n_var": 0, "n_constraints": 0,
        }
    return out


def metrics(unit: Unit, ev_kw: np.ndarray, batt_kw: np.ndarray) -> dict:
    net = unit.load_kw + ev_kw + batt_kw - unit.pv_kw
    return {
        "peak_net_kw": float(net.max()),
        "energy_cost_usd": float((unit.price * np.clip(net, 0.0, None) * DT_H).sum()),
        "ev_charge_kwh": float(np.clip(ev_kw, 0.0, None).sum() * DT_H),
        "ev_discharge_kwh": float(np.clip(-ev_kw, 0.0, None).sum() * DT_H),
        "batt_throughput_kwh": float(np.abs(batt_kw).sum() * DT_H),
    }


def run_benchmark(data_dir: Path, *, with_acnsim: bool = True) -> dict:
    """Run the three main arms (+ optional ACN-Sim cross-check rows);
    returns {'unit': Unit, 'arms': {name: row_dict}}."""
    unit = load_unit(data_dir)
    arms: dict[str, dict] = {}

    t0 = time.perf_counter()
    ev_unc = simulate_uncontrolled(unit)
    arms["uncontrolled"] = {
        **metrics(unit, ev_unc, np.zeros_like(ev_unc)),
        "status": "simulated", "solve_s": time.perf_counter() - t0,
        "n_var": 0, "n_constraints": 0,
    }
    for name, kw in (("v1g", {"allow_discharge": False, "use_battery": False}),
                     ("v2b", {"allow_discharge": True, "use_battery": True})):
        sol = solve_lp(unit, **kw)
        arms[name] = {
            **metrics(unit, sol["ev_kw"], sol["batt_kw"]),
            "status": sol["status"], "solve_s": sol["solve_s"],
            "n_var": sol["n_var"], "n_constraints": sol["n_constraints"],
        }
    if with_acnsim:
        try:
            arms.update(run_acnsim_crosscheck(unit))
        except Exception as e:  # cross-check must not sink the main arms
            arms["acnsim_crosscheck"] = {
                **{k: float("nan") for k in
                   ("peak_net_kw", "energy_cost_usd", "ev_charge_kwh",
                    "ev_discharge_kwh", "batt_throughput_kwh")},
                "status": f"unavailable ({type(e).__name__}: {e})",
                "solve_s": 0.0, "n_var": 0, "n_constraints": 0,
            }
    p0 = arms["uncontrolled"]["peak_net_kw"]
    c0 = arms["uncontrolled"]["energy_cost_usd"]
    for row in arms.values():
        row["peak_reduction_pct"] = 100.0 * (1.0 - row["peak_net_kw"] / p0)
        row["cost_reduction_pct"] = 100.0 * (1.0 - row["energy_cost_usd"] / c0)
    return {"unit": unit, "arms": arms}


# ──────────────────────────────────────────────────────────────────────
# Contended benchmark (plug-scarce unit + binding feeder cap)
# ──────────────────────────────────────────────────────────────────────

def run_contended_benchmark(
    data_dir: Path, *, feeder_kw_ratio: float = CONTENDED_FEEDER_RATIO,
) -> dict:
    """All seven ACN-Sim V1G schedulers + labeled LP relaxations on a
    contended unit (charger pool smaller than the fleet's realized peak
    concurrency), scored on the same monthly-peak-of-net metric plus
    energy-service accounting. Fully deterministic (no RNG, no wall times).

    Contention channels (see module docstring):
    - plugs: the adapter's FCFS admission rejects sessions that arrive with
      no charger free — a pool POLICY, identical for every algorithm;
    - power: the feeder cap (feeder_kw_ratio × chargers × rate) is the shared
      resource the schedulers ration — this is where they separate.
    Mean queueing delay is NOT reported: the machinery models
    plug-on-arrival-or-reject admission, so no session waits.
    """
    unit = load_unit(data_dir)
    T = len(unit.times)
    n_offered = len(unit.sessions)
    n_chargers = len(unit.chargers_native)
    rate_kw = float(unit.chargers_native["max_rate_kw"].max())
    plug_cap_kw = n_chargers * rate_kw
    feeder_kw = feeder_kw_ratio * plug_cap_kw
    req_all_kwh = float(sum(s.required_kwh - s.arrival_kwh
                            for s in unit.sessions))

    def full_service_row(m: dict, status: str) -> dict:
        return {**m, "kwh_requested": req_all_kwh, "kwh_delivered": req_all_kwh,
                "n_admitted": n_offered, "n_rejected": 0,
                "n_satisfied": n_offered, "status": status}

    arms: dict[str, dict] = {}
    # Reference arm: charge-at-max with NO plug or feeder limit — the same
    # semantics (and number) as the uncontended table's `uncontrolled` arm.
    ev_unc = simulate_uncontrolled(unit)
    arms["uncontrolled_nolimit"] = full_service_row(
        metrics(unit, ev_unc, np.zeros(T)),
        "simulated (no plug/feeder limit; serves all sessions)")

    for algo_name in ACNSIM_ALGOS:
        sim = _simulate_acnsim(unit, algo_name,
                               feeder_kw_ratio=feeder_kw_ratio)
        n_sat, kwh_req, kwh_del = satisfaction_stats(
            sim["requested"], sim["delivered"])
        adm = sim["admission"]
        note = ("ignores the feeder cap by design — cap-violating upper bound"
                if algo_name == "uncontrolled"
                else f"feeder-capped at {feeder_kw:.1f} kW")
        arms[f"acnsim_{algo_name}"] = {
            **metrics(unit, sim["ev_kw"], np.zeros(T)),
            "kwh_requested": kwh_req, "kwh_delivered": kwh_del,
            "n_admitted": adm.n_admitted, "n_rejected": adm.n_rejected,
            "n_satisfied": n_sat,
            "status": f"simulated (acnsim; {note})",
        }

    # LP relaxations (labeled): static session→charger assignment cannot
    # express plug contention, so the LP serves ALL sessions under an
    # aggregate EV-power cap instead (fractional plug sharing; no admission).
    lp_specs = [
        ("v1g_lp_plugcap", {"allow_discharge": False, "use_battery": False},
         plug_cap_kw,
         f"LP relaxation (agg EV power <= plugs x rate = {plug_cap_kw:.0f} kW;"
         " fractional plug sharing; serves all sessions)"),
        ("v2b_lp_plugcap", {"allow_discharge": True, "use_battery": True},
         plug_cap_kw,
         f"LP relaxation (agg EV power <= {plug_cap_kw:.0f} kW; + discharge"
         " + battery; serves all sessions)"),
        ("v1g_lp_feedercap", {"allow_discharge": False, "use_battery": False},
         feeder_kw,
         f"LP relaxation (agg EV power <= feeder cap = {feeder_kw:.1f} kW;"
         " same power envelope as the acnsim arms; serves all sessions)"),
    ]
    nan_metrics = {k: float("nan") for k in
                   ("peak_net_kw", "energy_cost_usd", "ev_charge_kwh",
                    "ev_discharge_kwh", "batt_throughput_kwh")}
    for name, kw, cap, label in lp_specs:
        try:
            sol = solve_lp(unit, **kw, ev_agg_cap_kw=cap)
            arms[name] = full_service_row(
                metrics(unit, sol["ev_kw"], sol["batt_kw"]), label)
        except RuntimeError:
            arms[name] = {
                **nan_metrics, "kwh_requested": req_all_kwh,
                "kwh_delivered": float("nan"), "n_admitted": n_offered,
                "n_rejected": 0, "n_satisfied": 0,
                "status": (f"infeasible under the {cap:.1f} kW aggregate cap"
                           " when serving ALL sessions — row omitted from"
                           " comparisons (honest relaxation limit)"),
            }

    p0 = arms["uncontrolled_nolimit"]["peak_net_kw"]
    for row in arms.values():
        row["peak_reduction_pct"] = 100.0 * (1.0 - row["peak_net_kw"] / p0)
        row["fulfillment_pct"] = (100.0 * row["kwh_delivered"]
                                  / row["kwh_requested"]
                                  if row["kwh_requested"] else 100.0)
        row["satisfied_pct_admitted"] = (100.0 * row["n_satisfied"]
                                         / row["n_admitted"]
                                         if row["n_admitted"] else 100.0)
        row["satisfied_pct_offered"] = 100.0 * row["n_satisfied"] / n_offered

    return {"unit": unit, "arms": arms,
            "params": {"n_offered": n_offered, "n_chargers": n_chargers,
                       "rate_kw": rate_kw, "plug_cap_kw": plug_cap_kw,
                       "feeder_kw_ratio": feeder_kw_ratio,
                       "feeder_kw": feeder_kw,
                       "req_all_kwh": req_all_kwh}}


# ──────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────

def write_outputs(data_dir: Path, out_dir: Path, result: dict) -> None:
    unit: Unit = result["unit"]
    arms: dict[str, dict] = result["arms"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # solve_s deliberately excluded: wall-time is the one nondeterministic
    # quantity and lives in the memo / repro_runtimes.json, keeping this CSV
    # byte-stable across runs (determinism gate).
    cols = ["arm", "peak_net_kw", "peak_reduction_pct", "energy_cost_usd",
            "cost_reduction_pct", "ev_charge_kwh", "ev_discharge_kwh",
            "batt_throughput_kwh", "status", "n_var", "n_constraints",
            "n_sessions", "n_relaxed", "n_clipped", "n_skipped",
            "n_bidirectional_sessions"]
    rows = []
    for name, r in arms.items():
        rows.append({
            "arm": name,
            "peak_net_kw": round(r["peak_net_kw"], 3),
            "peak_reduction_pct": round(r["peak_reduction_pct"], 3),
            "energy_cost_usd": round(r["energy_cost_usd"], 2),
            "cost_reduction_pct": round(r["cost_reduction_pct"], 3),
            "ev_charge_kwh": round(r["ev_charge_kwh"], 1),
            "ev_discharge_kwh": round(r["ev_discharge_kwh"], 1),
            "batt_throughput_kwh": round(r["batt_throughput_kwh"], 1),
            "status": r["status"],
            "n_var": r["n_var"], "n_constraints": r["n_constraints"],
            "solve_s": round(r["solve_s"], 2),
            "n_sessions": len(unit.sessions),
            "n_relaxed": unit.n_relaxed, "n_clipped": unit.n_clipped,
            "n_skipped": unit.n_skipped,
            "n_bidirectional_sessions": unit.n_bidirectional_sessions,
        })
    pd.DataFrame(rows, columns=cols).to_csv(out_dir / "v2b_dispatch.csv",
                                            index=False)

    def f(x, nd=1):
        return f"{x:,.{nd}f}"

    rel_data = data_dir.relative_to(REPO) if data_dir.is_relative_to(REPO) else data_dir
    L = [
        "# V2B dispatch baseline (LP peak shave) — one released corpus unit",
        "",
        "_Auto-generated by `tools/bench_v2b_dispatch.py`. Do not edit by "
        "hand. Deterministic (no RNG; unique LP optimum under the price "
        "tie-break) except the `solve_s` wall-time column._",
        "",
        f"**Unit:** `{rel_data}` — {len(unit.times)} x 15-min steps "
        f"({unit.times[0]} .. {unit.times[-1]}), {len(unit.sessions)} charging "
        f"sessions / 60 cars, 60 chargers (48 bidirectional +-20 kW, 12 "
        f"unidirectional 20 kW), stationary battery "
        f"{f(unit.battery['cap_kwh'], 0)} kWh / "
        f"{f(unit.battery['power_kw'], 0)} kW (eta_rt = "
        f"{unit.battery['eta_rt']}), PV, TOU prices.",
        "",
        "## Arms",
        "",
        "- **uncontrolled** — every session charges at its charger's max rate "
        "from arrival until `required_soc_at_depart` is met (partial final "
        "step). No optimization.",
        "- **v1g** — smart-charging LP: session charging only; no vehicle "
        "discharge, no stationary battery.",
        "- **v2b** — v1g + vehicle discharge on bidirectional-assigned "
        "sessions + the stationary battery.",
        "",
        "## Formulation",
        "",
        "Single LP per optimized arm (`scipy.optimize.linprog`, HiGHS, sparse):",
        "minimize `P + 1e-4 * dt * sum price*(c + bc)` subject to, per step t, "
        "`load + sum(c) - sum(d) + bc - bd - pv <= P`; per session, per-step "
        "SoC state variables with dynamics `e_k = e_{k-1} + dt*(c_k - d_k)`, "
        "bounds `min(arrival, min_allowed) <= SoC <= max_allowed`, terminal "
        "`SoC(depart) >= required_soc_at_depart`, rates within the assigned "
        "charger's limits, charging only inside the session window; battery "
        "SoC dynamics with the round-trip efficiency split as `sqrt(eta)` per "
        "direction, SoC in `[min, max]`, start at `initial_soc_pct`, terminal "
        "SoC >= initial (no free energy). Vehicles are modeled lossless. The "
        "`1e-4` price term is a tie-break: it makes the optimum unique and "
        "kills charge/discharge degeneracy without materially changing the "
        "peak objective. Energy cost is reported as "
        "`sum price * max(net, 0) * 0.25` USD.",
        "",
        "## Data-reconstruction rules",
        "",
        "- **Arrival SoC per session** (not an optimus column): per car in "
        "arrival order, `arrival_soc(first) = cars.soc` (which the exporter "
        "sets to the first session's true arrival SoC) and `arrival_soc(k) = "
        "required_soc(k-1) - previous_day_external_use_soc(k)`. Exact whenever "
        "`previous_day_external_use_soc > 0` (generator definition, "
        "`docs/DESIGN_NOTES.md` section 3: `max(0, prior_required - arrival)`), "
        "otherwise a conservative lower bound.",
        "- **Charger assignment / discharge eligibility**: sessions sorted by "
        "`(arrival, session_id)`; session *i* is assigned to charger "
        "`i mod 60` in `chargers.csv` file order and may discharge iff that "
        "charger is bidirectional (48/60 => 80% of sessions, deterministic, "
        "matching the fleet's bidirectional share). This is a dispatch bound, "
        "not a plug-level allocation simulation.",
        "- **Feasibility guard**: `required_soc` is clamped to what the "
        "assigned charger can reach within the in-horizon window "
        "(relaxations counted below); windows are clipped to the month.",
        "",
        "## Results",
        "",
        "| arm | peak net (kW) | peak reduction | energy cost (USD) | "
        "cost reduction | EV charged (kWh) | EV discharged (kWh) | "
        "battery throughput (kWh) | status | LP size (var / constr) | "
        "solve (s) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|---|---|--:|",
    ]
    for name, r in arms.items():
        size = (f"{r['n_var']:,} / {r['n_constraints']:,}"
                if r["n_var"] else "—")
        L.append(
            f"| {name} | {f(r['peak_net_kw'])} | "
            f"{f(r['peak_reduction_pct'])}% | {f(r['energy_cost_usd'], 2)} | "
            f"{f(r['cost_reduction_pct'])}% | {f(r['ev_charge_kwh'])} | "
            f"{f(r['ev_discharge_kwh'])} | {f(r['batt_throughput_kwh'])} | "
            f"{r['status']} | {size} | {r['solve_s']:.2f} |")
    L += [
        "",
        "## ACN-Sim cross-check",
        "",
        "The `acnsim_*_crosscheck` rows run the repo's established ACN-Sim "
        "bench machinery (`src/v2b_syndata/bench/`, V1G-only by design) on "
        "the same unit — ALL SEVEN stock schedulers in the registry "
        "(EDF, LLF, FCFS, LCFS, LRPT, RoundRobin, Uncontrolled): the optimus "
        "CSVs are adapted in-memory into the native-schema `ScenarioInputs` "
        "the adapter expects (same arrival-SoC "
        "reconstruction and relaxed `required_soc` as the LP arms), simulated "
        "at 15-min ticks with the unbinding feeder default, and the resulting "
        "charging schedule is added to `building_load - PV` to compute the "
        "identical peak-of-net metric. ACN-Sim's stock V1G schedulers "
        "are building-load-unaware, and the charger pool is uncontended here "
        "(60 chargers, per-car sessions never overlap, unbinding feeder), so "
        "every queue-ordering algorithm charges each EV at max rate until its "
        "requested energy is met — the semantic twin "
        "of the **uncontrolled** arm. The table's point is exactly that "
        "queue algorithms cannot help without a queue: their near-zero "
        "deltas vs the uncontrolled arm independently validate the demand "
        "model (session windows, "
        "arrival-SoC chain, energy needs) through an established simulator; "
        "the gap to LP-V1G measures the value of building-load-aware "
        "scheduling (no stock ACN-Sim algorithm observes building load). "
        "For the contended companion (where the algorithms DO separate) see "
        "`contended_bench.md`. "
        "ACN-Sim's `UncontrolledCharging` keeps charging past the requested "
        "energy (to battery capacity) by its own semantics, so it upper-"
        "bounds the uncontrolled arm.",
        "",
    ]
    ctrl = [a for a in ACNSIM_ALGOS if a != "uncontrolled"]
    deltas = [arms[f"acnsim_{a}_crosscheck"]["peak_net_kw"]
              - arms["uncontrolled"]["peak_net_kw"]
              for a in ctrl if f"acnsim_{a}_crosscheck" in arms]
    if deltas and "acnsim_llf_crosscheck" in arms:
        d_max = max(deltas, key=abs)
        d_v1g = (arms["acnsim_llf_crosscheck"]["peak_net_kw"]
                 - arms["v1g"]["peak_net_kw"])
        L += [
            f"Deltas: max |peak delta| of the {len(deltas)} controlled "
            f"ACN-Sim schedulers vs the uncontrolled arm: {d_max:+.1f} kW "
            f"({100 * d_max / arms['uncontrolled']['peak_net_kw']:+.2f}%); "
            f"LLF vs LP-V1G: {d_v1g:+.1f} kW.",
            "",
        ]
    L += [
        f"Feasibility: {unit.n_relaxed} required-SoC relaxations, "
        f"{unit.n_clipped} horizon-clipped windows, {unit.n_skipped} sessions "
        f"skipped (fully out of horizon); {unit.n_bidirectional_sessions}"
        f"/{len(unit.sessions)} sessions bidirectional-assigned.",
        "",
        "Machine-readable: `v2b_dispatch.csv`. Repro: `uv run python "
        "tools/repro_paper.py --steps v2b_dispatch` (or run this script "
        "directly).",
        "",
    ]
    (out_dir / "v2b_dispatch.md").write_text("\n".join(L))


CONTENDED_COLS = [
    "arm", "peak_net_kw", "peak_reduction_pct", "kwh_requested",
    "kwh_delivered", "fulfillment_pct", "n_admitted", "n_rejected",
    "n_satisfied", "satisfied_pct_admitted", "satisfied_pct_offered",
    "ev_discharge_kwh", "batt_throughput_kwh", "status",
]


def contended_rows(result: dict) -> list[dict]:
    """CSV rows for the contended benchmark. Pure; deterministic rounding;
    deliberately NO wall-time column (byte-identical across runs)."""
    rows = []
    for name, r in result["arms"].items():
        rows.append({
            "arm": name,
            "peak_net_kw": round(r["peak_net_kw"], 3),
            "peak_reduction_pct": round(r["peak_reduction_pct"], 3),
            "kwh_requested": round(r["kwh_requested"], 1),
            "kwh_delivered": round(r["kwh_delivered"], 1),
            "fulfillment_pct": round(r["fulfillment_pct"], 2),
            "n_admitted": r["n_admitted"],
            "n_rejected": r["n_rejected"],
            "n_satisfied": r["n_satisfied"],
            "satisfied_pct_admitted": round(r["satisfied_pct_admitted"], 2),
            "satisfied_pct_offered": round(r["satisfied_pct_offered"], 2),
            "ev_discharge_kwh": round(r["ev_discharge_kwh"], 1),
            "batt_throughput_kwh": round(r["batt_throughput_kwh"], 1),
            "status": r["status"],
        })
    return rows


def write_contended_outputs(data_dir: Path, out_dir: Path,
                            result: dict) -> None:
    """contended_bench.csv + contended_bench.md — both byte-deterministic
    (no RNG anywhere in the pipeline; no wall-time fields)."""
    unit: Unit = result["unit"]
    p = result["params"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = contended_rows(result)
    pd.DataFrame(rows, columns=CONTENDED_COLS).to_csv(
        out_dir / "contended_bench.csv", index=False)

    rel_data = (data_dir.relative_to(REPO)
                if data_dir.is_relative_to(REPO) else data_dir)
    n_bidir = int((unit.chargers_native["min_rate_kw"] < 0).sum())
    L = [
        "# Contended dispatch benchmark — plug-scarce unit + binding feeder "
        "cap",
        "",
        "_Auto-generated by `tools/bench_v2b_dispatch.py --contended`. Do not "
        "edit by hand. Fully deterministic: no RNG, no wall-time columns — "
        "two runs are byte-identical._",
        "",
        f"**Unit:** `{rel_data}` — same building, fleet, month, weather, "
        f"noise (clean) and seed as the released uncontended unit "
        f"`data/output/campus10/b1/JUL2024/0` (all demand-side CSVs are "
        f"byte-identical; SHA-keyed node seeding makes `charger_count` "
        f"changes invisible to every other node), but with "
        f"**{p['n_chargers']} chargers** ({n_bidir} bidirectional) for 60 "
        f"cars / {p['n_offered']} sessions.",
        "",
        "Generation command (deterministic; documented config committed at "
        "`docs/experiments/contended_bench_config.json`):",
        "",
        "```",
        "uv run python -m v2b_syndata.cli generate-multi \\",
        "  --config docs/experiments/contended_bench_config.json \\",
        "  --output-dir data/output/contended/b1ch35/JUL2024/0",
        "```",
        "",
        "## Contention design",
        "",
        f"- The uncontended unit's realized peak concurrency is **59** "
        f"(its manifest E5 block; mean work-hour concurrency ~42). "
        f"`charging_infra.charger_count = {p['n_chargers']}` ≈ 60% of that "
        f"observed peak, so plug contention binds hard on every workday "
        f"while most sessions remain servable.",
        "- The unit deliberately violates the generator's E5 physical-"
        "realism invariant (18.1% of ticks have more active sessions than "
        "chargers; the manifest records the validation error). That is the "
        "point: offered demand exceeds the plugs, and the DISPATCH layer — "
        "not the generator — must resolve it. The unit is a benchmark "
        "stress input, not part of the released corpus.",
        "- Plug scarcity is resolved by the bench adapter's FCFS admission "
        "(`bench/adapter.py`): a session that arrives with no free charger "
        "is rejected and never plugs in. Admission is a pool POLICY, "
        "identical for every algorithm — every arm below sees the same "
        "admitted set. **Mean queueing delay is not reported because the "
        "machinery models plug-on-arrival-or-reject; no session waits.**",
        f"- The scheduling algorithms contend over the FEEDER cap: "
        f"{p['feeder_kw']:.1f} kW = {p['feeder_kw_ratio']} x "
        f"{p['n_chargers']} chargers x {p['rate_kw']:.0f} kW. The 0.125 "
        f"service ratio is the ACN-Caltech-like operating point documented "
        f"in `bench/adapter.py`. At an unbinding feeder (ratio 1.0) all six "
        f"controlled schedulers coincide exactly even on this plug-scarce "
        f"unit — admitted sessions never share a constraint — so the feeder "
        f"cap is what makes queue ORDER matter.",
        "",
        "## LP arms (labeled relaxations)",
        "",
        "The LP's static session→charger assignment cannot express plug "
        "contention — a faithful assignment model needs big-M / integer "
        "machinery, deliberately NOT attempted here. Instead the LP serves "
        "ALL sessions (no admission) under an aggregate EV-power cap "
        "`sum_s (c + d) <= cap` (discharge counts: a plug carries |power|; "
        "the stationary battery is behind the meter and exempt):",
        "",
        f"- `*_lp_plugcap` — cap = chargers x rate = {p['plug_cap_kw']:.0f} "
        "kW: the honest fractional-plug-sharing proxy for the plug pool.",
        f"- `v1g_lp_feedercap` — cap = the acnsim arms' feeder cap "
        f"({p['feeder_kw']:.1f} kW): same power envelope as the schedulers, "
        "but load-aware and admission-free.",
        "",
        "These rows answer \"what could a building-load-aware optimizer do "
        "with the same total plug power if plug-swapping were frictionless\" "
        "— an upper bound on scheduling value, not a plug-level simulation.",
        "",
        "## Results",
        "",
        "| arm | peak net (kW) | peak red. | kWh delivered / requested | "
        "fulfill. | admitted | rejected | satisfied (of admitted) | "
        "satisfied (of offered) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]

    def f(x, nd=1):
        return "—" if x != x else f"{x:,.{nd}f}"  # NaN-safe

    for r in rows:
        L.append(
            f"| {r['arm']} | {f(r['peak_net_kw'])} | "
            f"{f(r['peak_reduction_pct'])}% | "
            f"{f(r['kwh_delivered'], 0)} / {f(r['kwh_requested'], 0)} | "
            f"{f(r['fulfillment_pct'])}% | {r['n_admitted']} | "
            f"{r['n_rejected']} | {r['n_satisfied']} "
            f"({f(r['satisfied_pct_admitted'])}%) | "
            f"{f(r['satisfied_pct_offered'])}% |")
    L += [
        "",
        "Full rows (incl. discharge / battery throughput and per-arm status "
        "labels): `contended_bench.csv`.",
        "",
        "## Reading the table",
        "",
        "- `uncontrolled_nolimit` reproduces the uncontended table's "
        "uncontrolled arm (same demand; infrastructure limits ignored) — "
        "the common baseline for peak reduction.",
        "- `acnsim_uncontrolled` ignores the feeder cap by design "
        "(cap-violating upper bound) and over-delivers past the requested "
        "energy by ACN-Sim's own semantics.",
        "- The six controlled schedulers all draw exactly the feeder cap "
        "during the rush, so their PEAKS nearly coincide; they separate on "
        "ENERGY SERVICE — deadline-aware orderings (EDF/LLF) satisfy every "
        "admitted session, while deadline-blind orderings (FCFS/LCFS/LRPT/"
        "RR) strand energy in sessions that depart unserved.",
        "- The LP rows serve every session (no admission) AND shave the "
        "building peak — locating the two distinct sources of dispatch "
        "value: queue/admission management under contention (scheduler-"
        "side) vs building-load-aware timing (optimizer-side).",
        "",
        "Repro: `uv run python tools/repro_paper.py --steps contended_bench` "
        "(or run this script with `--contended`).",
        "",
    ]
    (out_dir / "contended_bench.md").write_text("\n".join(L))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=None,
                    help=f"unit dir (default: {DEFAULT_DATA} or, with "
                         f"--contended, {DEFAULT_CONTENDED_DATA})")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--skip-acnsim", action="store_true",
                    help="skip the ACN-Sim cross-check rows")
    ap.add_argument("--contended", action="store_true",
                    help="run the contended-pool benchmark (writes "
                         "contended_bench.{csv,md})")
    ap.add_argument("--feeder-ratio", type=float,
                    default=CONTENDED_FEEDER_RATIO,
                    help="contended-mode feeder cap as a fraction of "
                         "chargers x rate (default %(default)s)")
    args = ap.parse_args()
    data_dir = args.data_dir or (DEFAULT_CONTENDED_DATA if args.contended
                                 else DEFAULT_DATA)

    t0 = time.perf_counter()
    if args.contended:
        result = run_contended_benchmark(
            data_dir, feeder_kw_ratio=args.feeder_ratio)
        write_contended_outputs(data_dir, args.out_dir, result)
        for name, r in result["arms"].items():
            print(f"{name:>22}: peak {r['peak_net_kw']:8.1f} kW "
                  f"({r['peak_reduction_pct']:+6.2f}%)  "
                  f"{r['kwh_delivered']:8.0f}/{r['kwh_requested']:8.0f} kWh  "
                  f"sat {r['n_satisfied']}/{r['n_admitted']} adm, "
                  f"{r['n_rejected']} rej", flush=True)
        print(f"total {time.perf_counter() - t0:.1f}s -> "
              f"{args.out_dir / 'contended_bench.md'}", flush=True)
        return 0

    result = run_benchmark(data_dir, with_acnsim=not args.skip_acnsim)
    write_outputs(data_dir, args.out_dir, result)
    for name, r in result["arms"].items():
        print(f"{name:>13}: peak {r['peak_net_kw']:8.1f} kW "
              f"({r['peak_reduction_pct']:+6.2f}%)  cost "
              f"${r['energy_cost_usd']:,.2f} ({r['cost_reduction_pct']:+6.2f}%)"
              f"  [{r['status']}, {r['solve_s']:.2f}s]", flush=True)
    u = result["unit"]
    print(f"relaxations: {u.n_relaxed}; clipped: {u.n_clipped}; "
          f"skipped: {u.n_skipped}; total {time.perf_counter() - t0:.1f}s "
          f"-> {args.out_dir / 'v2b_dispatch.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
