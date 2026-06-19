"""Top-level orchestrator: simulate_building_load."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pandas as pd

from . import cache as cache_mod
from . import ep_runner, leap_weather, output_parser, weather
from .occupancy_inject import inject_occupancy
from .prototypes import get_prototype_idf

# 8 end-use meters from BAYES_NET.md L_flex / L_inflex.
_REQUIRED_METERS = (
    "Cooling:Electricity",
    "Heating:Electricity",
    "Fans:Electricity",
    "WaterSystems:Electricity",
    "InteriorLights:Electricity",
    "ExteriorLights:Electricity",
    "InteriorEquipment:Electricity",
    "ExteriorEquipment:Electricity",
)

_DOW_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday")


def _annual_runperiod_for_year(year: int) -> str:
    """Annual RunPeriod for ``year``. We set both Begin Year *and* Day of Week
    explicitly because EnergyPlus's "derive DOW from year" path silently
    defaults to Sunday in some configurations (PNNL prototypes).
    """
    import datetime as _dt
    dow = _DOW_NAMES[_dt.date(year, 1, 1).weekday()]
    return f"""\
  RunPeriod,
    Annual,                  !- Name
    1,                       !- Begin Month
    1,                       !- Begin Day of Month
    {year},                    !- Begin Year
    12,                      !- End Month
    31,                      !- End Day of Month
    {year},                    !- End Year
    {dow},               !- Day of Week for Start Day
    No,                      !- Use Weather File Holidays and Special Days
    No,                      !- Use Weather File Daylight Saving Period
    No,                      !- Apply Weekend Holiday Rule
    Yes,                     !- Use Weather File Rain Indicators
    Yes;                     !- Use Weather File Snow Indicators
"""


# PNNL IDFs put a ``!- comment`` on the same line as the terminating ``;``.
# Patterns consume everything between the opening keyword and ``;``, then the
# rest of the closing line (comment + newline).
_RUNPERIOD_RE = re.compile(
    r"^\s*RunPeriod\s*,\s*\n[^;]*;[^\n]*\n",
    flags=re.MULTILINE,
)
_TIMESTEP_RE = re.compile(
    r"^\s*Timestep\s*,[^;]*;[^\n]*\n",
    flags=re.MULTILINE,
)
_OUTPUT_METER_RE = re.compile(
    r"^\s*Output:Meter(?::MeterFileOnly)?\s*,[^;]*;[^\n]*\n",
    flags=re.MULTILINE,
)


def _strip_runperiods(idf_text: str) -> str:
    return _RUNPERIOD_RE.sub("", idf_text)


def _force_timestep_4(idf_text: str) -> str:
    if _TIMESTEP_RE.search(idf_text):
        return _TIMESTEP_RE.sub("  Timestep, 4;\n", idf_text, count=1)
    return "  Timestep, 4;\n" + idf_text


def _strip_existing_meter_outputs(idf_text: str) -> str:
    return _OUTPUT_METER_RE.sub("", idf_text)


def _append_meter_outputs(idf_text: str) -> str:
    block = "\n".join(
        f"  Output:Meter:MeterFileOnly,{m},Timestep;" for m in _REQUIRED_METERS
    )
    return idf_text.rstrip() + "\n\n" + block + "\n"


def _prepare_idf_for_run(idf_path: Path, output_path: Path, year: int) -> Path:
    text = Path(idf_path).read_text()
    text = _strip_runperiods(text)
    text += "\n" + _annual_runperiod_for_year(year) + "\n"
    text = _force_timestep_4(text)
    text = _strip_existing_meter_outputs(text)
    text = _append_meter_outputs(text)
    Path(output_path).write_text(text)
    return Path(output_path)


def _simulate_single(
    archetype: str,
    size: str,
    epw_path: Path,
    occupancy: pd.Series,
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
    temp_offset_c: float = 0.0,
    solar_scale: float = 1.0,
) -> tuple[pd.Series, pd.Series]:
    proto_idf = get_prototype_idf(archetype, size)
    year = pd.Timestamp(sim_window_start).year

    # Cache key uses the *prototype* hash (deterministic) plus inputs. ``leap=``
    # keys the leap-aware weather transform below. We deliberately do NOT tag
    # the key with the EnergyPlus binary version: that would force a callable
    # binary just to compute the key, making a populated parquet cache unusable
    # on a machine without EnergyPlus (CI / shipped-cache reproducibility). The
    # 23.2->24.1 prototype upgrade already invalidates the cache via the hashed
    # IDF bytes; a bare binary swap that leaves the IDFs untouched needs a
    # manual cache clear.
    key = cache_mod.cache_key(
        idf_path=proto_idf,
        epw_path=epw_path,
        occupancy=occupancy,
        sim_window_start=sim_window_start,
        sim_window_end=sim_window_end,
        extra=(
            f"meters={','.join(_REQUIRED_METERS)};rp=annual;ts=4;year={year}"
            f";leap={int(leap_weather.is_leap(year))}"
            f";dT={float(temp_offset_c)!r};ssc={float(solar_scale)!r}"
        ),
    )
    cached = cache_mod.get_cached(key)
    if cached is not None:
        return cached

    # Binary is resolved lazily here (cache miss only) — never required for a
    # cache hit.
    with tempfile.TemporaryDirectory(prefix="v2b_ep_") as tmp:
        tmp = Path(tmp)
        injected = inject_occupancy(proto_idf, occupancy, tmp / "injected.idf")
        runtime = _prepare_idf_for_run(injected, tmp / "runtime.idf", year=year)
        # A 365-day TMYx cannot faithfully simulate a leap year (EnergyPlus
        # mis-sequences the day-of-week across the missing Feb 29). Inject one.
        run_epw = epw_path
        if leap_weather.is_leap(year):
            run_epw = leap_weather.make_leap_epw(epw_path, tmp / "weather.epw", year)
        # Weather realization: perturb the EPW EnergyPlus actually consumes so
        # the simulated load is faithful to the (perturbed) weather we export.
        # No-op when temp_offset_c == 0 and solar_scale == 1.
        run_epw = weather.perturb_epw_file(
            run_epw, tmp / "perturbed.epw", temp_offset_c, solar_scale,
        )
        ep_out = tmp / "ep_run"
        meter_csv = ep_runner.run_energyplus(runtime, run_epw, ep_out)
        flex, inflex = output_parser.parse_eplusout(
            meter_csv, sim_window_start, sim_window_end
        )

    cache_mod.put_cached(key, flex, inflex)
    return flex, inflex


def simulate_building_load(
    archetype: str,
    size: str,
    tmyx_station: str,
    occupancy: pd.Series,
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
    weather_type: str = "tmyx",
    weather_year: int | None = None,
    temp_offset_c: float = 0.0,
    solar_scale: float = 1.0,
) -> tuple[pd.Series, pd.Series]:
    """Return ``(L_flex_kw, L_inflex_kw)`` for the requested building over sim window.

    Both series are 15-min indexed, ``[sim_window_start, sim_window_end)``.

    ``archetype="mixed"`` runs office + retail at the same size and averages.
    Implementation hinges on EnergyPlus + cached parquet artifacts; see
    ``handoff/spec/BAYES_NET.md`` Tier 2 nodes ``L_flex`` / ``L_inflex``.

    ``temp_offset_c`` / ``solar_scale`` apply a *weather realization* transform
    (additive °C on dry-bulb, multiplicative on solar) to the EPW EnergyPlus
    consumes — keep them in sync with ``export_optimus.build_weather`` so the
    exported weather matches the simulated load.
    """
    epw_path = weather.get_weather_epw(tmyx_station, weather_type, weather_year)
    sim_window_start = pd.Timestamp(sim_window_start)
    sim_window_end = pd.Timestamp(sim_window_end)

    if archetype == "mixed":
        # 50/50 office + retail composite (D34). Retail small not in prototype map;
        # fall back to "med" when caller asks for "small" composites.
        retail_size = size if (("retail", size) in _retail_keys()) else "med"
        flex_o, inflex_o = _simulate_single(
            "office", size, epw_path, occupancy, sim_window_start, sim_window_end,
            temp_offset_c, solar_scale,
        )
        flex_r, inflex_r = _simulate_single(
            "retail", retail_size, epw_path, occupancy, sim_window_start, sim_window_end,
            temp_offset_c, solar_scale,
        )
        return 0.5 * (flex_o + flex_r), 0.5 * (inflex_o + inflex_r)

    return _simulate_single(
        archetype, size, epw_path, occupancy, sim_window_start, sim_window_end,
        temp_offset_c, solar_scale,
    )


def _retail_keys() -> set:
    from .prototypes import PROTOTYPE_MAP
    return set(PROTOTYPE_MAP.keys())
