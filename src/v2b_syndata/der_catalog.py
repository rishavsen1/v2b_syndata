"""Catalog of distributed-energy-resource (DER) presets: rooftop/carport PV
arrays and stationary battery storage.

The generator's PV physics and battery specs are ultimately driven by the raw
numeric knobs (``pv.dc_capacity_kw``, ``battery.capacity_kwh``/``power_kw``),
but a *type* preset lets the CLI/web user pick a realistic system by name and
get a sensible rating without hand-entering kW. An explicit numeric knob (> 0)
always overrides the preset.

Sizing rationale (commercial / C&I norms — see docs/GENERATIVE_MODELS.md):
PV is roof-area / annual-energy limited, NOT a fixed fraction of building peak.
Rooftop DC ≈ usable_roof_ft² × 0.012–0.015 kW/ft². The tiers below span small
office/retail rooftops through big-box/warehouse flat roofs and parking
canopies. Battery power for behind-the-meter demand-charge management is
typically ~10–30 % of facility peak kW; energy is 2 h or 4 h of that power.
"""
from __future__ import annotations

# pv_type -> nameplate DC capacity (kW). Anchored on usable roof area, not peak.
PV_CAPACITY_KW: dict[str, float] = {
    "none": 0.0,
    "rooftop_small": 30.0,     # small office/retail (~2–3k ft² usable roof)
    "rooftop_medium": 100.0,   # medium office (congested roof, ~50k ft² floor)
    "rooftop_large": 250.0,    # large office / mid retail
    "rooftop_xl": 600.0,       # big-box / warehouse single-story flat roof
    "carport": 200.0,          # parking-canopy array (~40–60 stalls)
}

# module_type -> temperature characteristics (PVWatts NOCT model).
MODULE_PARAMS: dict[str, dict[str, float]] = {
    "standard": {"temp_coeff_per_c": -0.0035, "noct_c": 45.0},   # mainstream c-Si
    "premium": {"temp_coeff_per_c": -0.0030, "noct_c": 44.0},    # high-efficiency c-Si
    "thin_film": {"temp_coeff_per_c": -0.0025, "noct_c": 47.0},  # CdTe etc.
}

# battery_type -> {capacity_kwh, power_kw, round_trip_efficiency}.
# "_2h"/"_4h" = energy duration at rated power. LFP vs NMC differ in efficiency.
BATTERY_PARAMS: dict[str, dict[str, float]] = {
    "none": {"capacity_kwh": 0.0, "power_kw": 0.0, "round_trip_efficiency": 0.90},
    "lfp_2h": {"capacity_kwh": 200.0, "power_kw": 100.0, "round_trip_efficiency": 0.90},
    "lfp_4h": {"capacity_kwh": 400.0, "power_kw": 100.0, "round_trip_efficiency": 0.90},
    "nmc_2h": {"capacity_kwh": 200.0, "power_kw": 100.0, "round_trip_efficiency": 0.92},
    "nmc_4h": {"capacity_kwh": 400.0, "power_kw": 100.0, "round_trip_efficiency": 0.92},
}

PV_TYPES = tuple(PV_CAPACITY_KW.keys())
MODULE_TYPES = tuple(MODULE_PARAMS.keys())
BATTERY_TYPES = tuple(BATTERY_PARAMS.keys())


def resolve_pv(
    *, enabled: bool, pv_type: str, dc_capacity_kw: float, module_type: str,
    dc_ac_ratio: float, tilt_deg: float, azimuth_deg: float,
    system_derate: float, albedo: float,
) -> dict[str, object]:
    """Resolve PV knobs into a concrete spec dict. Inactive (enabled False or
    zero effective capacity) yields a zero-capacity spec. Explicit
    ``dc_capacity_kw`` > 0 overrides the ``pv_type`` preset."""
    eff_dc = float(dc_capacity_kw) if float(dc_capacity_kw) > 0.0 else PV_CAPACITY_KW.get(pv_type, 0.0)
    if not enabled:
        eff_dc = 0.0
    mod = MODULE_PARAMS.get(module_type, MODULE_PARAMS["standard"])
    ratio = float(dc_ac_ratio) if float(dc_ac_ratio) > 0.0 else 1.20
    return {
        "pv_id": "pv_0",
        "pv_type": pv_type if eff_dc > 0.0 else "none",
        "dc_capacity_kw": round(eff_dc, 3),
        "ac_capacity_kw": round(eff_dc / ratio, 3),
        "dc_ac_ratio": ratio,
        "tilt_deg": float(tilt_deg),
        "azimuth_deg": float(azimuth_deg),
        "module_type": module_type,
        "system_derate": float(system_derate),
        "temp_coeff_per_c": float(mod["temp_coeff_per_c"]),
        "noct_c": float(mod["noct_c"]),
        "albedo": float(albedo),
    }


def resolve_battery(
    *, enabled: bool, battery_type: str, capacity_kwh: float, power_kw: float,
    round_trip_efficiency: float, min_soc_pct: float, max_soc_pct: float,
    initial_soc_pct: float,
) -> dict[str, object]:
    """Resolve battery knobs into a concrete spec dict. Explicit capacity/power
    knobs (> 0) override the ``battery_type`` preset."""
    base = BATTERY_PARAMS.get(battery_type, BATTERY_PARAMS["none"])
    eff_cap = float(capacity_kwh) if float(capacity_kwh) > 0.0 else float(base["capacity_kwh"])
    eff_pow = float(power_kw) if float(power_kw) > 0.0 else float(base["power_kw"])
    if not enabled:
        eff_cap = 0.0
        eff_pow = 0.0
    return {
        "battery_id": "batt_0",
        "battery_type": battery_type if eff_cap > 0.0 else "none",
        "capacity_kwh": round(eff_cap, 3),
        "power_kw": round(eff_pow, 3),
        "round_trip_efficiency": float(round_trip_efficiency),
        "min_soc_pct": float(min_soc_pct),
        "max_soc_pct": float(max_soc_pct),
        "initial_soc_pct": float(initial_soc_pct),
    }
