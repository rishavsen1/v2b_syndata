"""v2b_syndata scenario CSVs → ACN-Sim ChargingNetwork + EventQueue.

Schema mapping:
- sessions.csv (arrival/departure/arrival_soc/required_soc_at_depart) → PluginEvent w/ requested_energy
- cars.csv (capacity_kwh) → Battery
- chargers.csv (max_rate_kw, min_rate_kw clipped to 0) → EVSE max_rate
- building_load.csv → not fed to scheduler; aggregated post-hoc in metrics

Charger pool with FCFS admission control (v2):
- The ChargingNetwork has exactly `n_chargers` EVSE objects (not n_cars).
- On arrival, sessions are admitted FCFS into the earliest-free charger.
  If no charger is free at the arrival tick, the session is REJECTED and
  does not become a PluginEvent. Rejected sessions are reported as
  `admission_rejection_rate` in the metrics; they never reach the
  scheduler. Matches the standard "no queueing room" workplace policy.
- Per-charger occupancy is non-overlapping by construction; ACN-Sim
  natively handles sequential plug-ins at the same station_id.
- The previous v1 adapter used a 1:1 car→EVSE mapping with only an
  aggregate-kW cap, which let all sessions plug in to virtual slots and
  under-counted target_miss in oversubscribed scenarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from acnportal import acnsim
from acnportal.acnsim.models.battery import Battery
from acnportal.acnsim.network.charging_network import ChargingNetwork

DEFAULT_VOLTAGE = 208
DEFAULT_PERIOD_MIN = 5  # acnsim simulation tick length


@dataclass
class ScenarioInputs:
    sessions: pd.DataFrame
    cars: pd.DataFrame  # indexed by car_id
    chargers: pd.DataFrame
    building_load: pd.DataFrame
    sim_start: pd.Timestamp
    sim_end: pd.Timestamp


@dataclass
class AdmissionStats:
    n_offered: int
    n_admitted: int
    n_rejected: int

    @property
    def rejection_rate(self) -> float:
        return self.n_rejected / self.n_offered if self.n_offered else 0.0


@dataclass
class AcnsimInputs:
    network: ChargingNetwork
    events: acnsim.EventQueue
    sim_start: pd.Timestamp
    period_min: int
    n_periods: int
    voltage: float
    sessions: pd.DataFrame   # passed-through for metrics
    cars: pd.DataFrame
    building_load: pd.DataFrame
    admission: AdmissionStats
    admitted_session_ids: set[str]


def load_scenario(scenario_dir: Path) -> ScenarioInputs:
    """Read the 7 CSVs we care about. Building+grid_prices+dr_events
    are loaded but only building is used at the metric layer."""
    scenario_dir = Path(scenario_dir)
    sessions = pd.read_csv(
        scenario_dir / "sessions.csv",
        parse_dates=["arrival", "departure"],
    )
    cars = pd.read_csv(scenario_dir / "cars.csv").set_index("car_id")
    chargers = pd.read_csv(scenario_dir / "chargers.csv")
    building_load = pd.read_csv(
        scenario_dir / "building_load.csv",
        parse_dates=["datetime"],
    )

    sim_start = building_load["datetime"].min()
    sim_end = building_load["datetime"].max()
    return ScenarioInputs(sessions, cars, chargers, building_load, sim_start, sim_end)


def _fcfs_admit(
    sessions: pd.DataFrame, n_chargers: int
) -> tuple[pd.DataFrame, int]:
    """Greedy FCFS admission into a finite charger pool.

    For each session sorted by arrival, find the earliest-free charger
    (the one whose last-admitted session departed earliest, provided
    that departure is ≤ this session's arrival). If found, the session
    is admitted onto that charger and the charger's last-departure
    bookkeeping advances. If none is free at the session's arrival,
    the session is REJECTED.

    Returns: (admitted_df with `assigned_charger_idx` column, n_rejected)
    """
    if n_chargers <= 0:
        return sessions.iloc[0:0].copy(), len(sessions)

    sorted_s = sessions.sort_values("arrival").reset_index(drop=True)
    # Each charger's currently-scheduled last departure timestamp.
    charger_last_dep = [pd.Timestamp.min] * n_chargers
    admitted_rows = []
    n_rejected = 0

    for _, row in sorted_s.iterrows():
        # Find the charger with the earliest last_departure that's
        # ≤ this session's arrival. Greedy "leave-newest-free-charger
        # available for later sessions" not necessary — any-free works
        # for FCFS correctness; we pick the earliest-free deterministically
        # for stable assignment across reruns.
        free_idx = -1
        free_last_dep = pd.Timestamp.max
        arr = row["arrival"]
        for i, last_dep in enumerate(charger_last_dep):
            if last_dep <= arr and last_dep < free_last_dep:
                free_idx = i
                free_last_dep = last_dep
        if free_idx >= 0:
            charger_last_dep[free_idx] = row["departure"]
            r = row.copy()
            r["assigned_charger_idx"] = free_idx
            admitted_rows.append(r)
        else:
            n_rejected += 1

    if admitted_rows:
        admitted_df = pd.DataFrame(admitted_rows).reset_index(drop=True)
    else:
        admitted_df = sessions.iloc[0:0].copy()
        admitted_df["assigned_charger_idx"] = pd.Series(dtype="int64")
    return admitted_df, n_rejected


def build_acnsim_inputs(
    inputs: ScenarioInputs,
    period_min: int = DEFAULT_PERIOD_MIN,
    voltage: float = DEFAULT_VOLTAGE,
) -> AcnsimInputs:
    """Materialize ChargingNetwork + EventQueue from v2b scenario.

    FCFS admission gates sessions onto the finite charger pool before
    they reach the scheduler.
    """
    network = ChargingNetwork()
    # V1G: clip negative min_rate to 0. Charger.max_rate_kw is in kW;
    # ACN-Sim EVSE max_rate is in amps. Convert via P = V·I → I = P/V.
    max_kw_per_evse = float(inputs.chargers["max_rate_kw"].max())
    max_amp = max_kw_per_evse * 1000.0 / voltage
    n_chargers = len(inputs.chargers)

    station_ids: list[str] = []
    for charger_idx in range(n_chargers):
        station_id = f"EVSE_{charger_idx:04d}"
        evse = acnsim.EVSE(station_id, max_rate=max_amp, min_rate=0.0)
        network.register_evse(evse, voltage=voltage, phase_angle=0)
        station_ids.append(station_id)

    # Aggregate-current cap = n_chargers × max_amp. With one EVSE per
    # physical charger this matches the per-station cap and only binds
    # when something tries to violate it (e.g. UncontrolledCharging).
    agg = acnsim.Current({sid: 1.0 for sid in station_ids})
    network.add_constraint(agg, limit=max_amp * n_chargers, name="agg_current")

    # FCFS admission of sessions into the charger pool
    n_offered = len(inputs.sessions)
    admitted_df, n_rejected = _fcfs_admit(inputs.sessions, n_chargers)
    admission = AdmissionStats(
        n_offered=n_offered,
        n_admitted=len(admitted_df),
        n_rejected=n_rejected,
    )

    # Sessions → PluginEvents (only admitted sessions reach the scheduler)
    sim_start = inputs.sim_start
    period_sec = period_min * 60.0
    events = acnsim.EventQueue()
    admitted_session_ids: set[str] = set()

    for _, row in admitted_df.iterrows():
        car_id = row["car_id"]
        if car_id not in inputs.cars.index:
            continue
        car = inputs.cars.loc[car_id]

        arr_sec = (row["arrival"] - sim_start).total_seconds()
        dep_sec = (row["departure"] - sim_start).total_seconds()
        if dep_sec <= arr_sec:
            continue
        arr_tick = int(arr_sec / period_sec)
        dep_tick = int(dep_sec / period_sec)
        if dep_tick <= arr_tick:
            dep_tick = arr_tick + 1

        capacity = float(car["capacity_kwh"])
        arrival_soc = float(row["arrival_soc"])
        required_soc = float(row["required_soc_at_depart"])
        kwh_needed = max(0.0, (required_soc - arrival_soc) / 100.0 * capacity)
        init_charge_kwh = arrival_soc / 100.0 * capacity

        battery = Battery(
            capacity=capacity,
            init_charge=init_charge_kwh,
            max_power=max_kw_per_evse,
        )
        charger_idx = int(row["assigned_charger_idx"])
        station_id = station_ids[charger_idx]
        session_id = str(row["session_id"])
        ev = acnsim.EV(
            arrival=arr_tick,
            departure=dep_tick,
            requested_energy=kwh_needed,
            station_id=station_id,
            session_id=session_id,
            battery=battery,
            estimated_departure=dep_tick,
        )
        events.add_event(acnsim.PluginEvent(arr_tick, ev))
        admitted_session_ids.add(session_id)

    sim_end_sec = (inputs.sim_end - sim_start).total_seconds()
    n_periods = int(sim_end_sec / period_sec) + 1

    return AcnsimInputs(
        network=network,
        events=events,
        sim_start=sim_start,
        period_min=period_min,
        n_periods=n_periods,
        voltage=voltage,
        sessions=inputs.sessions,
        cars=inputs.cars,
        building_load=inputs.building_load,
        admission=admission,
        admitted_session_ids=admitted_session_ids,
    )
