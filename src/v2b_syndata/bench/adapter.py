"""v2b_syndata scenario CSVs → ACN-Sim ChargingNetwork + EventQueue.

Schema mapping:
- sessions.csv (arrival/departure/arrival_soc/required_soc_at_depart) → PluginEvent w/ requested_energy
- cars.csv (capacity_kwh) → Battery
- chargers.csv (max_rate_kw, min_rate_kw clipped to 0) → EVSE max_rate
- building_load.csv → not fed to scheduler; aggregated post-hoc in metrics

Assignment policy (v1): 1:1 car→station. station_id = "EVSE_<car_id>".
Loses charger-pool assignment problem; honest simplification for v1
benchmark demo. Documented in module docstring.
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


def build_acnsim_inputs(
    inputs: ScenarioInputs,
    period_min: int = DEFAULT_PERIOD_MIN,
    voltage: float = DEFAULT_VOLTAGE,
) -> AcnsimInputs:
    """Materialize ChargingNetwork + EventQueue from v2b scenario."""
    # 1:1 car → EVSE
    network = ChargingNetwork()
    # V1G: clip negative min_rate to 0. Charger.max_rate_kw is in kW;
    # ACN-Sim EVSE max_rate is in amps. Convert via P = V·I → I = P/V.
    max_kw_per_evse = float(inputs.chargers["max_rate_kw"].max())
    max_amp = max_kw_per_evse * 1000.0 / voltage

    station_ids: list[str] = []
    for car_id in inputs.cars.index:
        station_id = f"EVSE_{car_id}"
        evse = acnsim.EVSE(station_id, max_rate=max_amp, min_rate=0.0)
        network.register_evse(evse, voltage=voltage, phase_angle=0)
        station_ids.append(station_id)

    # Network-wide aggregate-current cap models the realistic
    # infrastructure limit (transformer / feeder capacity). Keeping the
    # 1:1 car→EVSE mapping but capping aggregate at
    # `n_chargers × max_kw_per_charger` means the network supports at
    # most n_chargers EVs at full rate simultaneously — exactly the
    # contention point that surfaces scheduling-algorithm differentiation
    # on oversubscribed scenarios (e.g. 100 cars × 30 chargers, see
    # configs/scenarios/S_scale_100.yaml). For 1:1 non-oversubscribed
    # scenarios (S01: 20 cars × 20 chargers) the constraint matches
    # n_stations × max_amp and never binds.
    n_chargers = len(inputs.chargers)
    agg = acnsim.Current({sid: 1.0 for sid in station_ids})
    network.add_constraint(agg, limit=max_amp * n_chargers, name="agg_current")

    # Sessions → PluginEvents
    sim_start = inputs.sim_start
    period_sec = period_min * 60.0
    events = acnsim.EventQueue()

    for _, row in inputs.sessions.iterrows():
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
        ev = acnsim.EV(
            arrival=arr_tick,
            departure=dep_tick,
            requested_energy=kwh_needed,
            station_id=f"EVSE_{car_id}",
            session_id=str(row["session_id"]),
            battery=battery,
            estimated_departure=dep_tick,
        )
        events.add_event(acnsim.PluginEvent(arr_tick, ev))

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
    )
