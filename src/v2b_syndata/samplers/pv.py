"""PV generation latent (node ``PV_gen``).

Computes a 15-min AC PV power series from the SAME (perturbed) EPW weather the
building-load EnergyPlus run consumed — pure deterministic physics, no RNG.
When PV is inactive (disabled or zero capacity) it stores an all-zeros series
WITHOUT touching the EPW, so default runs stay byte-identical and need no cached
weather file.
"""
from __future__ import annotations

import pandas as pd

from ..der_catalog import resolve_pv
from ..load_pipeline import weather as weather_mod
from ..load_pipeline.pv_model import pv_ac_series
from ..types import ScenarioContext


def pv_spec_from_ctx(ctx: ScenarioContext) -> dict:
    """Resolve the per-building PV spec from the resolved knobs."""
    return resolve_pv(
        enabled=bool(ctx.knobs.get("pv.enabled")) if ctx.knobs.has("pv.enabled") else False,
        pv_type=str(ctx.knobs.get("pv.pv_type")),
        dc_capacity_kw=float(ctx.knobs.get("pv.dc_capacity_kw")),
        module_type=str(ctx.knobs.get("pv.module_type")),
        dc_ac_ratio=float(ctx.knobs.get("pv.dc_ac_ratio")),
        tilt_deg=float(ctx.knobs.get("pv.tilt_deg")),
        azimuth_deg=float(ctx.knobs.get("pv.azimuth_deg")),
        system_derate=float(ctx.knobs.get("pv.system_derate")),
        albedo=float(ctx.knobs.get("pv.albedo")),
    )


def sample_pv_gen(ctx: ScenarioContext) -> None:
    idx = ctx.datetime_index()
    spec = pv_spec_from_ctx(ctx)
    ctx.latents["_pv_spec"] = spec  # consumed by the pv.csv renderer

    if float(spec["dc_capacity_kw"]) <= 0.0:
        ctx.latents["PV_gen"] = pd.Series(0.0, index=idx, name="power_pv_kw")
        return

    tmyx_station = str(ctx.knobs.get("building_load.tmyx_station"))
    wx = weather_mod.parsed_perturbed_weather(
        tmyx_station,
        ctx.sim_start.year,
        float(ctx.knobs.get("building_load.weather_temp_offset_c")),
        float(ctx.knobs.get("building_load.weather_solar_scale")),
        float(ctx.knobs.get("building_load.weather_dewpoint_offset_c")),
        float(ctx.knobs.get("building_load.weather_wind_scale")),
    )
    wx = wx[(wx.index >= pd.Timestamp(ctx.sim_start)) & (wx.index < pd.Timestamp(ctx.sim_end))]
    lat, lon, tz = weather_mod.parse_epw_location(
        weather_mod.get_weather_epw(tmyx_station, "tmyx", None)
    )
    ctx.latents["PV_gen"] = pv_ac_series(
        wx, idx,
        lat_deg=lat, lon_deg=lon, tz_hours=tz,
        dc_capacity_kw=float(spec["dc_capacity_kw"]),
        ac_capacity_kw=float(spec["ac_capacity_kw"]),
        tilt_deg=float(spec["tilt_deg"]),
        azimuth_deg=float(spec["azimuth_deg"]),
        system_derate=float(spec["system_derate"]),
        temp_coeff_per_c=float(spec["temp_coeff_per_c"]),
        noct_c=float(spec["noct_c"]),
        albedo=float(spec["albedo"]),
    )
