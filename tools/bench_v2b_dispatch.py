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
monthly-peak-of-net metric. Because ACN-Sim's stock sorted V1G heuristics
(LLF/EDF) are building-load-unaware and the charger pool is uncontended here
(60 chargers, non-overlapping per-car sessions), they charge each EV at max
rate until its requested energy is met — i.e. they are the semantic twin of
the *uncontrolled* arm, and a near-zero delta against it independently
validates the demand model (windows, arrival-SoC chain, energy needs) through
an established simulator. The delta against LP-V1G then measures the value of
building-load-aware scheduling, not an inconsistency.

Outputs: docs/experiments/v2b_dispatch.md (memo) and v2b_dispatch.csv
(machine-readable; consumed by tools/repro_paper.py step ``collect``).
Everything except the solve/wall-time columns is deterministic: no RNG, and
the LP has a unique optimum under the tie-break.

Usage:
    uv run python tools/bench_v2b_dispatch.py
    uv run python tools/bench_v2b_dispatch.py --data-dir <unit> --out-dir <dir>
    uv run python tools/bench_v2b_dispatch.py --skip-acnsim
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
DEFAULT_OUT = REPO / "docs" / "experiments"

TICK_S = 900
DT_H = TICK_S / 3600.0  # 0.25 h
TIE_BREAK = 1e-4


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


def solve_lp(unit: Unit, *, allow_discharge: bool, use_battery: bool) -> dict:
    """Peak-shaving LP. Returns dict with ev_kw, batt_kw (net), status, etc."""
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
        if d_off >= 0:
            ub[d_off:d_off + L] = s.p_discharge
            add(UB, t, d_off + k, -np.ones(L))
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
        shape=(T, n_var)).tocsc()
    b_ub = pv - load
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
            "n_constraints": T + n_eq, "lp_peak_kw": float(x[0])}


ACNSIM_ALGOS = ("llf", "uncontrolled")


def run_acnsim_crosscheck(unit: Unit) -> dict[str, dict]:
    """Cross-check via the repo's established ACN-Sim bench machinery.

    Adapts the reconstructed unit into the native-schema ``ScenarioInputs``
    the bench adapter consumes (same arrival-SoC chain and relaxed
    required_soc as the LP arms, for a like-for-like comparison), runs stock
    V1G schedulers at 15-min ticks with the unbinding feeder default, and
    computes the identical peak-of-net metric from the resulting charging
    schedule. Deterministic (no RNG in these schedulers).
    """
    import pytz
    from acnportal import acnsim

    from v2b_syndata.bench.adapter import ScenarioInputs, build_acnsim_inputs
    from v2b_syndata.bench.algorithms import ALGORITHMS

    times = unit.times
    T = len(times)
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
    scenario = ScenarioInputs(
        sessions=sess_df, cars=cars_df, chargers=unit.chargers_native,
        building_load=bl_df, sim_start=times[0], sim_end=times[-1])

    out: dict[str, dict] = {}
    for algo_name in ACNSIM_ALGOS:
        t0 = time.perf_counter()
        acn = build_acnsim_inputs(scenario, period_min=int(TICK_S // 60))
        tz = pytz.timezone("America/Los_Angeles")
        start = tz.localize(acn.sim_start.to_pydatetime().replace(tzinfo=None))
        sim = acnsim.Simulator(acn.network, ALGORITHMS[algo_name](),
                               acn.events, start,
                               period=int(TICK_S // 60), verbose=False)
        sim.run()
        agg = np.asarray(acnsim.aggregate_power(sim), dtype=float)
        ev_kw = np.zeros(T)
        n = min(T, len(agg))
        ev_kw[:n] = agg[:n]
        requested = sum(float(ev.requested_energy)
                        for ev in sim.ev_history.values())
        delivered = sum(float(ev.energy_delivered)
                        for ev in sim.ev_history.values())
        out[f"acnsim_{algo_name}_crosscheck"] = {
            **metrics(unit, ev_kw, np.zeros(T)),
            "status": (f"simulated (acnsim; {acn.admission.n_admitted}"
                       f"/{acn.admission.n_offered} admitted; "
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
        "the same unit: the optimus CSVs are adapted in-memory into the "
        "native-schema `ScenarioInputs` the adapter expects (same arrival-SoC "
        "reconstruction and relaxed `required_soc` as the LP arms), simulated "
        "at 15-min ticks with the unbinding feeder default, and the resulting "
        "charging schedule is added to `building_load - PV` to compute the "
        "identical peak-of-net metric. ACN-Sim's stock sorted V1G heuristics "
        "are building-load-unaware, and the charger pool is uncontended here "
        "(60 chargers, per-car sessions never overlap), so LLF charges each "
        "EV at max rate until its requested energy is met — the semantic twin "
        "of the **uncontrolled** arm. A near-zero LLF-vs-uncontrolled delta "
        "therefore independently validates the demand model (session windows, "
        "arrival-SoC chain, energy needs) through an established simulator; "
        "the gap to LP-V1G measures the value of building-load-aware "
        "scheduling (no stock ACN-Sim algorithm observes building load). "
        "ACN-Sim's `UncontrolledCharging` keeps charging past the requested "
        "energy (to battery capacity) by its own semantics, so it upper-"
        "bounds the uncontrolled arm.",
        "",
    ]
    llf = arms.get("acnsim_llf_crosscheck")
    if llf is not None:
        d_unc = llf["peak_net_kw"] - arms["uncontrolled"]["peak_net_kw"]
        d_v1g = llf["peak_net_kw"] - arms["v1g"]["peak_net_kw"]
        L += [
            f"Deltas: ACN-Sim LLF peak vs uncontrolled arm: "
            f"{d_unc:+.1f} kW ({100 * d_unc / arms['uncontrolled']['peak_net_kw']:+.2f}%); "
            f"vs LP-V1G: {d_v1g:+.1f} kW.",
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--skip-acnsim", action="store_true",
                    help="skip the ACN-Sim cross-check rows")
    args = ap.parse_args()

    t0 = time.perf_counter()
    result = run_benchmark(args.data_dir, with_acnsim=not args.skip_acnsim)
    write_outputs(args.data_dir, args.out_dir, result)
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
