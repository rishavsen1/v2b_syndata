"""Render dr_events.csv via inhomogeneous Poisson sampler (Step 6).

Replaces the Step 3 deterministic stub with a calibrated stochastic sampler
backed by EPW weather data and PG&E/CAISO program rules. See
`samplers/dr_sampler.py` for the rate function and Lewis's-thinning core.

Behavior by `utility_rate.dr_program`:
- `none`  → header-only CSV (no events).
- `CBP`/`BIP`/`ELRP` → inhomogeneous Poisson sample, deterministic per seed.
- anything else → KnobValidationError.

Notification lead in the existing Step 3 stub was 24h for all programs. Step 6
fixes this per D67: CBP=24h, BIP=2h, ELRP=2h. `_NOTIF_LEAD_HOURS` constant
preserved for backwards compatibility with `validate.py` imports.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..knob_loader import KnobValidationError
from ..load_pipeline.weather import get_weather_epw, parse_epw_temperatures
from ..samplers.dr_sampler import PROGRAM_SPECS, sample_dr_events
from ..seeding import rng_for_node
from ..types import ScenarioContext

# Per-program notification lead (hours). Read by validate.py for H-checks.
# Step 3 originally exposed this; Step 6 corrects ELRP from 24h → 2h per D67.
_NOTIF_LEAD_HOURS = {"CBP": 24, "BIP": 2, "ELRP": 2}

_COLUMNS = ["event_id", "start", "end", "magnitude_kw", "notified_at"]


def render(ctx: ScenarioContext) -> None:
    assert ctx.roots is not None
    T = ctx.roots.T
    program = T["dr_program"]

    if program == "none":
        ctx.rendered["dr_events.csv"] = pd.DataFrame(columns=_COLUMNS)
        return

    if program not in PROGRAM_SPECS:
        raise KnobValidationError(
            f"utility_rate.dr_program: {program!r} is not a supported program. "
            f"Valid choices: 'none', 'CBP', 'BIP', 'ELRP'."
        )

    # Sim window bounds from ScenarioContext.
    sim_start = pd.Timestamp(ctx.sim_start)
    sim_end = pd.Timestamp(ctx.sim_end)

    # Weather: pull max daily temp from the same EPW the EnergyPlus pipeline used.
    tmyx_station = str(ctx.knobs.get("building_load.tmyx_station"))
    daily_max_temp_f = _daily_max_temp_f(tmyx_station, sim_start, sim_end)

    rng = rng_for_node(ctx.seed, "dr_events")

    mag_lo, mag_hi = T["dr_magnitude_kw_range"]
    lambda_base = float(ctx.knobs.get("utility_rate.dr_lambda_base"))

    events = sample_dr_events(
        sim_window_start=sim_start,
        sim_window_end=sim_end,
        daily_max_temp_f=daily_max_temp_f,
        program=program,
        lambda_base=lambda_base,
        magnitude_kw_range=(float(mag_lo), float(mag_hi)),
        rng=rng,
    )

    if not events:
        ctx.rendered["dr_events.csv"] = pd.DataFrame(columns=_COLUMNS)
        return

    df = pd.DataFrame(events, columns=_COLUMNS)
    # Deterministic CSV time formatting matches Step 3 conventions.
    for col in ("start", "end", "notified_at"):
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M:%S")
    ctx.rendered["dr_events.csv"] = df


def _daily_max_temp_f(
    tmyx_station: str, sim_start: pd.Timestamp, sim_end: pd.Timestamp,
) -> pd.Series:
    """Daily max dry-bulb temp in °F across the sim window. EPW is a typical
    year; if sim window crosses years, repeat the same pattern shifted by year.
    """
    epw_path: Path = get_weather_epw(tmyx_station, "tmyx")
    base_temp_c = parse_epw_temperatures(epw_path, year=int(sim_start.year))

    # If sim_end extends past the parsed year, replicate the pattern for the
    # next year(s). Multi-year DR windows are rare; loop is bounded.
    parts = [base_temp_c]
    last_year = int(sim_start.year)
    while pd.Timestamp(parts[-1].index[-1]) < sim_end:
        last_year += 1
        next_year = parse_epw_temperatures(epw_path, year=last_year)
        parts.append(next_year)
    hourly_c = pd.concat(parts)
    # Restrict to a tiny pad around the sim window for performance.
    hourly_c = hourly_c[(hourly_c.index >= sim_start - pd.Timedelta(days=1)) &
                        (hourly_c.index < sim_end + pd.Timedelta(days=1))]
    hourly_f = hourly_c * 9.0 / 5.0 + 32.0
    return hourly_f.resample("D").max()
