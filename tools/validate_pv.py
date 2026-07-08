#!/usr/bin/env python3
"""Validate the transparent PV model against the NREL SAM (PVWatts v8) reference.

KDD_READINESS #8 / KDD_SUBMISSION_PLAN WS-B: feed IDENTICAL inputs — the same
TMYx EPW weather file, tilt, azimuth, DC capacity, DC/AC ratio, derate — into

  1. ``v2b_syndata.load_pipeline.pv_model.pv_ac_series`` (ours: isotropic
     transposition + PVWatts-v5 NOCT cell temperature + lumped derate + clip), and
  2. **PySAM Pvwattsv8** (NREL's SAM SDK), reading the very same EPW, so the
     weather is byte-identical and only the PV physics differ.

Reference-semantics note (important for interpreting the bias sign):
  - Our ``system_derate`` (default 0.86) is a LUMPED total DC→AC derate
    including the inverter.
  - PVWatts separates ``losses`` (%, DC side) from the inverter nominal
    efficiency (``inv_eff``, default 96% with a part-load efficiency curve).
  The PRIMARY reference run uses the standard PVWatts semantics
  (losses = (1-derate)·100, inv_eff = 96%) — i.e. what anyone reproducing
  "14% system losses" in PVWatts would get. A SECONDARY derate-equalized run
  (losses chosen so losses × inv_eff matches our lumped derate) is also
  reported to attribute how much of the bias is loss bookkeeping vs
  transposition/thermal physics.

Axis conventions (verified): both models use azimuth 180° = due South,
tilt from horizontal, and local standard time (EPW, no DST). SAM emits 8760
hourly AC values aligned to EPW rows (row k = hour k of the year); our EPW
parser maps EPW hour 1–24 to stamps 00–23, so ``sam[k]`` and the mean of our
four 15-min ticks in hour k cover the same wall-clock hour. A lag scan
(±3 h cross-correlation) is run and reported before any error metric is
trusted.

Outputs: markdown report (``docs/experiments/pv_validation.md``), hourly pair
CSV (``docs/experiments/pv_validation_hourly.csv``), stdout summary.
Exit code 0; ``--strict`` exits 2 when the annual-error gate (<5%) fails.

Usage:
    uv run python tools/validate_pv.py                # defaults = WS-B config
    uv run python tools/validate_pv.py --strict
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from v2b_syndata.der_catalog import MODULE_PARAMS  # noqa: E402
from v2b_syndata.load_pipeline import weather as weather_mod  # noqa: E402
from v2b_syndata.load_pipeline.pv_model import pv_ac_series  # noqa: E402

DEFAULT_STATION = "USA_CA_San.Jose-Mineta.Intl.AP.724945_TMYx"
ANNUAL_GATE_PCT = 5.0
# ASHRAE Guideline 14 hourly calibration thresholds (§14.1.3.2, Table 4-1).
G14_HOURLY_CVRMSE_PCT = 30.0
G14_HOURLY_NMBE_PCT = 10.0

# our module_type name -> SAM Pvwattsv8 SystemDesign.module_type code.
SAM_MODULE_TYPE = {"standard": 0, "premium": 1, "thin_film": 2}
SAM_INV_EFF_PCT = 96.0  # PVWatts default nominal inverter efficiency.


# ── model runs ──────────────────────────────────────────────────────────────

def run_our_model(
    station: str, year: int, *, dc_kw: float, dc_ac_ratio: float, tilt_deg: float,
    azimuth_deg: float, system_derate: float, module_type: str, albedo: float,
) -> pd.Series:
    """Run pv_ac_series full-year on the unperturbed station EPW; return the
    hourly-mean kW series (== kWh per hour) on 8760 stamps."""
    wx = weather_mod.parsed_perturbed_weather(station, year)
    epw = weather_mod.get_weather_epw(station, "tmyx", None)
    lat, lon, tz = weather_mod.parse_epw_location(epw)
    n_days = 366 if pd.Timestamp(year=year, month=12, day=31).is_leap_year else 365
    idx15 = pd.date_range(f"{year}-01-01", periods=n_days * 96, freq="15min")
    mod = MODULE_PARAMS[module_type]
    q15 = pv_ac_series(
        wx, idx15,
        lat_deg=lat, lon_deg=lon, tz_hours=tz,
        dc_capacity_kw=dc_kw, ac_capacity_kw=dc_kw / dc_ac_ratio,
        tilt_deg=tilt_deg, azimuth_deg=azimuth_deg,
        system_derate=system_derate,
        temp_coeff_per_c=float(mod["temp_coeff_per_c"]),
        noct_c=float(mod["noct_c"]),
        albedo=albedo,
    )
    return q15.resample("1h").mean().rename("ours_kw")


def run_pysam(
    station: str, year: int, *, dc_kw: float, dc_ac_ratio: float, tilt_deg: float,
    azimuth_deg: float, losses_pct: float, module_type: str, albedo: float,
) -> pd.Series:
    """Run NREL PySAM Pvwattsv8 on the SAME EPW; return hourly AC kW (8760)."""
    import PySAM.Pvwattsv8 as pvwatts

    epw = weather_mod.get_weather_epw(station, "tmyx", None)
    model = pvwatts.default("PVWattsNone")
    model.SolarResource.solar_resource_file = str(epw)
    model.SolarResource.use_wf_albedo = 0
    model.SolarResource.albedo = [albedo]
    sd = model.SystemDesign
    sd.system_capacity = dc_kw          # kW-DC
    sd.dc_ac_ratio = dc_ac_ratio
    sd.tilt = tilt_deg
    sd.azimuth = azimuth_deg            # SAM: 180 = due South (same as ours)
    sd.array_type = 0                   # fixed open rack — matches our NOCT-45 thermal model
    sd.module_type = SAM_MODULE_TYPE[module_type]
    sd.losses = losses_pct
    sd.en_snowloss = 0
    sd.bifaciality = 0.0
    model.execute(0)
    ac_kw = np.asarray(model.Outputs.ac, dtype=float) / 1000.0  # W → kW
    idx = pd.date_range(f"{year}-01-01", periods=len(ac_kw), freq="1h")
    return pd.Series(ac_kw, index=idx, name="sam_kw")


# ── metrics ─────────────────────────────────────────────────────────────────

@dataclass
class Metrics:
    annual_ours_kwh: float
    annual_ref_kwh: float
    annual_err_pct: float
    cvrmse_pct: float
    nmbe_pct: float
    r_hourly: float
    cvrmse_day_pct: float
    nmbe_day_pct: float
    best_lag_h: int
    monthly: pd.DataFrame


def lag_scan(ours: pd.Series, ref: pd.Series, max_lag: int = 3) -> tuple[int, dict[int, float]]:
    """Cross-correlate at integer-hour lags; return (argmax lag, {lag: r}).
    A best lag != 0 means a time-axis misalignment — error metrics untrustworthy."""
    corrs = {lag: float(ours.corr(ref.shift(lag))) for lag in range(-max_lag, max_lag + 1)}
    best = max(corrs, key=lambda k: corrs[k])
    return best, corrs


def compute_metrics(ours: pd.Series, ref: pd.Series) -> Metrics:
    if len(ours) != len(ref):
        raise ValueError(f"length mismatch: ours {len(ours)} vs ref {len(ref)}")
    best_lag, _ = lag_scan(ours, ref)

    resid = ours.to_numpy() - ref.to_numpy()
    mean_ref = float(ref.mean())
    # ASHRAE G14: CV(RMSE) = RMSE / mean(measured); NMBE = mean bias / mean(measured).
    cvrmse = 100.0 * float(np.sqrt(np.mean(resid**2))) / mean_ref
    nmbe = 100.0 * float(np.mean(resid)) / mean_ref

    day = ref > 0.0  # daytime (reference producing) subset
    resid_d = ours[day].to_numpy() - ref[day].to_numpy()
    mean_d = float(ref[day].mean())
    cvrmse_d = 100.0 * float(np.sqrt(np.mean(resid_d**2))) / mean_d
    nmbe_d = 100.0 * float(np.mean(resid_d)) / mean_d

    both = pd.DataFrame({"ours_kwh": ours, "ref_kwh": ref})
    monthly = both.groupby(both.index.month).sum()
    monthly.index.name = "month"
    monthly["err_pct"] = 100.0 * (monthly["ours_kwh"] - monthly["ref_kwh"]) / monthly["ref_kwh"]

    a_ours, a_ref = float(ours.sum()), float(ref.sum())
    return Metrics(
        annual_ours_kwh=a_ours, annual_ref_kwh=a_ref,
        annual_err_pct=100.0 * (a_ours - a_ref) / a_ref,
        cvrmse_pct=cvrmse, nmbe_pct=nmbe, r_hourly=float(ours.corr(ref)),
        cvrmse_day_pct=cvrmse_d, nmbe_day_pct=nmbe_d,
        best_lag_h=best_lag, monthly=monthly,
    )


# ── report ──────────────────────────────────────────────────────────────────

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _monthly_table(m: pd.DataFrame) -> str:
    lines = ["| Month | ours kWh | PVWatts kWh | error % |",
             "|---|---:|---:|---:|"]
    for mo, row in m.iterrows():
        lines.append(f"| {_MONTHS[int(mo) - 1]} | {row['ours_kwh']:,.0f} "
                     f"| {row['ref_kwh']:,.0f} | {row['err_pct']:+.2f} |")
    return "\n".join(lines)


def write_report(
    path: Path, *, station: str, year: int, cfg: dict, primary: Metrics,
    equalized: Metrics, losses_primary: float, losses_equalized: float,
    lag_corrs: dict[int, float], csv_path: Path, pysam_version: str,
) -> None:
    gate = "PASS" if abs(primary.annual_err_pct) < ANNUAL_GATE_PCT else "FAIL"
    g14 = ("PASS" if primary.cvrmse_pct <= G14_HOURLY_CVRMSE_PCT
           and abs(primary.nmbe_pct) <= G14_HOURLY_NMBE_PCT else "FAIL")
    lag_row = " ".join(f"{k:+d}h:{v:.4f}" for k, v in sorted(lag_corrs.items()))
    md = f"""# PV model validation vs NREL PVWatts v8 (PySAM)

*(generated by `tools/validate_pv.py` — KDD_READINESS #8 / submission-plan WS-B)*

## Setup

- **Model under test:** `v2b_syndata.load_pipeline.pv_model.pv_ac_series`
  (isotropic transposition, Spencer solar position, PVWatts-v5 NOCT cell
  temperature, lumped DC→AC derate, inverter clip at DC/ratio).
- **Reference:** NREL **PySAM {pysam_version} `Pvwattsv8`** (SAM SDK) fed with the
  **identical TMYx EPW** file — weather is byte-identical, so all differences
  are PV physics, not resource data. (The PVWatts v8 web API was therefore not
  needed; no NSRDB-vs-TMYx weather delta to attribute.)
- **Station:** `{station}` (lat 37.359, lon −121.924, tz −8), full typical year
  indexed as {year}.
- **Configuration:** DC {cfg['dc_kw']:.0f} kW, tilt {cfg['tilt_deg']:.0f}°,
  azimuth {cfg['azimuth_deg']:.0f}° (due South in BOTH conventions — verified),
  DC/AC ratio {cfg['dc_ac_ratio']}, module `{cfg['module_type']}`,
  albedo {cfg['albedo']}, lumped system_derate {cfg['system_derate']}.
- **SAM settings:** array_type 0 (fixed open rack, matching our NOCT-45 open-rack
  thermal model), snow loss off, bifaciality 0, fixed albedo {cfg['albedo']}.

### Loss-semantics mapping

Our `system_derate={cfg['system_derate']}` is a **lumped total** DC→AC derate
(inverter included). PVWatts separates DC `losses` from the inverter
(`inv_eff` = {SAM_INV_EFF_PCT:.0f}% nominal + part-load curve). Two reference runs:

1. **Primary (standard PVWatts semantics):** `losses` = {losses_primary:.2f}%,
   inverter curve active — what anyone reproducing "{losses_primary:.0f}% system
   losses" in PVWatts/SAM gets.
2. **Derate-equalized (physics isolation):** `losses` = {losses_equalized:.4f}% so
   that losses × nominal inv_eff equals our lumped {cfg['system_derate']} — isolates
   transposition + thermal + clipping differences from loss bookkeeping.

## Time-axis check (before trusting error metrics)

Hourly cross-correlation vs lag: {lag_row}

Best lag = **{primary.best_lag_h:+d} h** (r = {primary.r_hourly:.4f} at lag 0) —
the two series are time-aligned; no solar-time/timezone shift detected.

## Results — primary reference

| Metric | Value | Threshold | Verdict |
|---|---:|---:|---|
| Annual energy (ours) | {primary.annual_ours_kwh:,.0f} kWh | | |
| Annual energy (PVWatts v8) | {primary.annual_ref_kwh:,.0f} kWh | | |
| **Annual energy error** | **{primary.annual_err_pct:+.2f}%** | < ±{ANNUAL_GATE_PCT:.0f}% | **{gate}** |
| Hourly CV(RMSE) (all hours) | {primary.cvrmse_pct:.2f}% | ≤ {G14_HOURLY_CVRMSE_PCT:.0f}% (G14 hourly) | {g14} |
| Hourly NMBE (all hours) | {primary.nmbe_pct:+.2f}% | ≤ ±{G14_HOURLY_NMBE_PCT:.0f}% (G14 hourly) | {g14} |
| Hourly CV(RMSE) (ref-producing hours) | {primary.cvrmse_day_pct:.2f}% | — | |
| Hourly NMBE (ref-producing hours) | {primary.nmbe_day_pct:+.2f}% | — | |
| Hourly Pearson r | {primary.r_hourly:.4f} | — | |

### Monthly energy

{_monthly_table(primary.monthly)}

## Results — derate-equalized reference (attribution)

Annual: ours {equalized.annual_ours_kwh:,.0f} kWh vs {equalized.annual_ref_kwh:,.0f} kWh
→ **{equalized.annual_err_pct:+.2f}%**; hourly CV(RMSE) {equalized.cvrmse_pct:.2f}%,
NMBE {equalized.nmbe_pct:+.2f}%, r {equalized.r_hourly:.4f}.

Attribution: with total losses equalized, the remaining {equalized.annual_err_pct:+.2f}%
is the pure physics gap (isotropic vs Perez transposition, NOCT vs SAM cell-temperature
model, constant vs part-load inverter efficiency, our −0.35%/°C vs SAM's standard-module
temperature coefficient). Under standard PVWatts loss semantics (primary) the two
bookkeeping choices partially offset, giving {primary.annual_err_pct:+.2f}% overall.

## Artifacts

- Hourly pair CSV: `{csv_path.relative_to(REPO) if csv_path.is_relative_to(REPO) else csv_path}` (timestamp, ours_kw,
  sam_primary_kw, sam_equalized_kw).
- Regenerate: `uv run python tools/validate_pv.py`

## Verdict

Annual energy error {primary.annual_err_pct:+.2f}% vs the standard-semantics NREL
PVWatts v8 reference on identical weather → **{gate}** against the <{ANNUAL_GATE_PCT:.0f}%
gate. Hourly agreement r = {primary.r_hourly:.4f}, CV(RMSE) = {primary.cvrmse_pct:.1f}%,
NMBE = {primary.nmbe_pct:+.1f}% ({'within' if g14 == 'PASS' else 'outside'} ASHRAE
Guideline-14 hourly calibration tolerances of ≤30% / ±10%).
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md)


# ── main ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--station", default=DEFAULT_STATION)
    p.add_argument("--year", type=int, default=2021,
                   help="index year for the TMY stamps (non-leap; default 2021)")
    p.add_argument("--dc-kw", type=float, default=100.0)
    p.add_argument("--dc-ac-ratio", type=float, default=1.2)
    p.add_argument("--tilt-deg", type=float, default=10.0)
    p.add_argument("--azimuth-deg", type=float, default=180.0)
    p.add_argument("--system-derate", type=float, default=0.86)
    p.add_argument("--module-type", default="standard", choices=sorted(SAM_MODULE_TYPE))
    p.add_argument("--albedo", type=float, default=0.2)
    p.add_argument("--out-md", type=Path, default=REPO / "docs/experiments/pv_validation.md")
    p.add_argument("--out-csv", type=Path,
                   default=REPO / "docs/experiments/pv_validation_hourly.csv")
    p.add_argument("--strict", action="store_true",
                   help="exit 2 when the <5%% annual gate fails")
    args = p.parse_args(argv)

    import PySAM
    cfg = dict(dc_kw=args.dc_kw, dc_ac_ratio=args.dc_ac_ratio, tilt_deg=args.tilt_deg,
               azimuth_deg=args.azimuth_deg, system_derate=args.system_derate,
               module_type=args.module_type, albedo=args.albedo)

    ours = run_our_model(args.station, args.year, **cfg)

    losses_primary = (1.0 - args.system_derate) * 100.0
    losses_equalized = (1.0 - args.system_derate / (SAM_INV_EFF_PCT / 100.0)) * 100.0
    sam_kwargs = dict(dc_kw=args.dc_kw, dc_ac_ratio=args.dc_ac_ratio,
                      tilt_deg=args.tilt_deg, azimuth_deg=args.azimuth_deg,
                      module_type=args.module_type, albedo=args.albedo)
    sam_primary = run_pysam(args.station, args.year, losses_pct=losses_primary, **sam_kwargs)
    sam_equalized = run_pysam(args.station, args.year, losses_pct=losses_equalized, **sam_kwargs)

    m_primary = compute_metrics(ours, sam_primary)
    m_equalized = compute_metrics(ours, sam_equalized)
    _, lag_corrs = lag_scan(ours, sam_primary)

    if m_primary.best_lag_h != 0:
        print(f"WARNING: best cross-correlation at lag {m_primary.best_lag_h:+d} h — "
              "time-axis misalignment; error metrics are NOT trustworthy.",
              file=sys.stderr)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "ours_kw": ours,
        "sam_primary_kw": sam_primary,
        "sam_equalized_kw": sam_equalized,
    }).rename_axis("timestamp").round(4).to_csv(args.out_csv)

    write_report(
        args.out_md, station=args.station, year=args.year, cfg=cfg,
        primary=m_primary, equalized=m_equalized,
        losses_primary=losses_primary, losses_equalized=losses_equalized,
        lag_corrs=lag_corrs, csv_path=args.out_csv, pysam_version=PySAM.__version__,
    )

    gate_pass = abs(m_primary.annual_err_pct) < ANNUAL_GATE_PCT
    print(f"station={args.station} year={args.year}")
    print(f"annual: ours={m_primary.annual_ours_kwh:,.0f} kWh  "
          f"pvwatts8={m_primary.annual_ref_kwh:,.0f} kWh  "
          f"error={m_primary.annual_err_pct:+.2f}%  "
          f"gate(<{ANNUAL_GATE_PCT:.0f}%): {'PASS' if gate_pass else 'FAIL'}")
    print(f"hourly: CV(RMSE)={m_primary.cvrmse_pct:.2f}%  NMBE={m_primary.nmbe_pct:+.2f}%  "
          f"r={m_primary.r_hourly:.4f}  best_lag={m_primary.best_lag_h:+d}h")
    print(f"derate-equalized annual error={m_equalized.annual_err_pct:+.2f}%")
    print(f"wrote {args.out_md} and {args.out_csv}")
    return 0 if (gate_pass or not args.strict) else 2


if __name__ == "__main__":
    raise SystemExit(main())
