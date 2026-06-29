#!/usr/bin/env python3
"""Download + characterize real/simulated building-load references for KDD validation.

Two sources:

  1. ComStock (NREL EULP) climate-zone aggregates (baseline upgrade=0), AMY2018,
     15-min interval. Five shipped prototypes (small/med/large office, retail
     standalone, retail strip mall) across several ASHRAE/IECC climate zones.
     End-use meters let us split flex (cooling+heating+fans+water_systems) from
     inflex (interior/exterior lighting + interior equipment) exactly as the
     generator's output_parser.py does.

  2. BDG2 (Building Data Genome Project 2) — real metered whole-building
     electricity (kWh/hour). No end-use split (total only).

Outputs (under data/buildingload_reference/):
  comstock_timeseries.parquet, bdg2_timeseries.parquet
  reference_bands.json   (characterization keyed by source/archetype/size/zone)
  MANIFEST.json + download_log.txt  (provenance: every URL, bytes, counts)

Idempotent: raw downloads are cached in _raw/; re-runs skip existing nonzero
files and just re-characterize. Use --force to re-download.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
OUT_DIR = REPO_ROOT / "data" / "buildingload_reference"
RAW_DIR = OUT_DIR / "_raw"

COMSTOCK_BASE = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2024/comstock_amy2018_release_2/"
    "timeseries_aggregates/by_ashrae_iecc_climate_zone_2006/upgrade=0/"
    "ashrae_iecc_climate_zone_2006={cz}/up00-{czl}-{btype}.csv"
)

SQFT_PER_SQM = 10.7639  # floor_area_represented is reported in ft^2

# (filename buildingtype) -> (archetype, size, representative DOE prototype floor area m2)
# Prototype areas (DOE commercial reference buildings) used to scale the
# represented-stock aggregate down to one representative building so that
# mean_kw / peak_kw are physically meaningful single-building magnitudes.
COMSTOCK_TYPES = {
    "smalloffice": ("office", "small", 511.0),
    "mediumoffice": ("office", "med", 4982.0),
    "largeoffice": ("office", "large", 46320.0),
    # Retail size labels follow the generator's prototypes.py convention:
    #   ("retail","med")   -> ASHRAE901_RetailStripmall  (2090 m2)
    #   ("retail","large") -> ASHRAE901_RetailStandalone (2294 m2)
    # There is no "small" retail prototype.
    "retailstripmall": ("retail", "med", 2090.0),
    "retailstandalone": ("retail", "large", 2294.0),
}

DEFAULT_ZONES = ["5B", "3B", "4A", "6A"]

# End-use kWh columns -> bucket. Mirrors output_parser.py FLEX/INFLEX_METERS.
FLEX_COLS = [
    "out.electricity.cooling.energy_consumption.kwh",
    "out.electricity.heating.energy_consumption.kwh",
    "out.electricity.fans.energy_consumption.kwh",
    "out.electricity.water_systems.energy_consumption.kwh",
]
INFLEX_COLS = [
    "out.electricity.interior_lighting.energy_consumption.kwh",
    "out.electricity.exterior_lighting.energy_consumption.kwh",
    "out.electricity.interior_equipment.energy_consumption.kwh",
    "out.electricity.exterior_equipment.energy_consumption.kwh",  # absent in ComStock; kept for safety
]
TOTAL_COL = "out.electricity.total.energy_consumption.kwh"

BDG2_META_URL = (
    "https://github.com/buds-lab/building-data-genome-project-2/raw/master/"
    "data/metadata/metadata.csv"
)
BDG2_ELEC_URLS = [
    "https://github.com/buds-lab/building-data-genome-project-2/raw/master/"
    "data/meters/cleaned/electricity_cleaned.csv",
    "https://github.com/buds-lab/building-data-genome-project-2/raw/master/"
    "data/meters/raw/electricity.csv",
]

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)


# ---------------------------------------------------------------------------
# Download helpers (idempotent)
# ---------------------------------------------------------------------------

def download(url: str, dest: Path, force: bool, manifest: list[dict]) -> Path | None:
    """Stream `url` to `dest`. Skip if cached & nonzero (unless force).

    Returns dest on success, None on failure (logged, non-fatal).
    """
    if dest.exists() and dest.stat().st_size > 0 and not force:
        nbytes = dest.stat().st_size
        log(f"CACHED  {dest.name} ({nbytes:,} bytes) <- {url}")
        manifest.append({"url": url, "dest": dest.name, "status": "cached", "bytes": nbytes})
        return dest
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            if r.status_code == 404:
                log(f"WARNING 404 {url}")
                manifest.append({"url": url, "dest": dest.name, "status": "404", "bytes": 0})
                return None
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            nbytes = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
                        nbytes += len(chunk)
            tmp.replace(dest)
        log(f"OK      {dest.name} ({nbytes:,} bytes) <- {url}")
        manifest.append({"url": url, "dest": dest.name, "status": "ok", "bytes": nbytes})
        return dest
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR   {url} -> {exc}")
        manifest.append({"url": url, "dest": dest.name, "status": f"error:{exc}", "bytes": 0})
        return None


# ---------------------------------------------------------------------------
# Characterization
# ---------------------------------------------------------------------------

def _weekday_weekend_shapes(s: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Return (weekday_24, weekend_24) mean-by-hour, NOT normalized."""
    df = pd.DataFrame({"kw": s.to_numpy()}, index=pd.DatetimeIndex(s.index))
    df["hour"] = df.index.hour
    df["wknd"] = df.index.dayofweek >= 5
    wd = df[~df["wknd"]].groupby("hour")["kw"].mean().reindex(range(24)).to_numpy()
    we = df[df["wknd"]].groupby("hour")["kw"].mean().reindex(range(24)).to_numpy()
    return wd, we


def characterize(s: pd.Series, floor_area_m2: float | None, n_buildings: int,
                 eui_override: float | None = None,
                 eui_kwh_m2_yr: float | None = None) -> dict:
    """Compute the band/shape metrics for one per-building kW series.

    `s` is a per-building average kW timeseries with a DatetimeIndex.

    EUI reporting (eui_kwh_m2_yr field) holds annual energy intensity in
    **kWh/m2/yr** (the conventional "EUI" unit).
    For ComStock pass `eui_kwh_m2_yr` directly (computed from represented stock);
    for BDG2 pass `eui_override` (metadata EUI) or rely on the fallback from the
    series itself.
    """
    s = s.dropna()
    s = s[s.index.notna()]
    if len(s) == 0:
        return {}
    wd, we = _weekday_weekend_shapes(s)
    wd_safe = np.where(np.isnan(wd), 0.0, wd)
    we_safe = np.where(np.isnan(we), 0.0, we)

    peak = float(np.nanmax(s.to_numpy()))
    mean = float(np.nanmean(s.to_numpy()))

    # peak/offpeak on the typical-weekday profile: peak hour mean vs mean of hours < 6
    wd_peak = float(np.nanmax(wd)) if np.isfinite(np.nanmax(wd)) else 0.0
    offpeak_vals = wd[:6]
    offpeak = float(np.nanmean(offpeak_vals)) if np.any(np.isfinite(offpeak_vals)) else np.nan
    peak_offpeak = float(wd_peak / offpeak) if offpeak and offpeak > 0 else float("nan")

    wd_mean = float(np.nanmean(wd)) if np.any(np.isfinite(wd)) else np.nan
    we_mean = float(np.nanmean(we)) if np.any(np.isfinite(we)) else np.nan
    wd_we = float(wd_mean / we_mean) if we_mean and we_mean > 0 else float("nan")

    load_factor = float(mean / peak) if peak > 0 else float("nan")

    wd_norm = (wd_safe / wd_peak).tolist() if wd_peak > 0 else wd_safe.tolist()
    we_peak = float(np.nanmax(we_safe)) if np.any(np.isfinite(we_safe)) else 0.0
    we_norm = (we_safe / we_peak).tolist() if we_peak > 0 else we_safe.tolist()
    peak_hour_wd = int(np.nanargmax(wd_safe)) if wd_peak > 0 else 0

    eui = None
    if eui_kwh_m2_yr is not None:
        eui = float(eui_kwh_m2_yr)
    elif eui_override is not None:
        eui = float(eui_override)
    elif floor_area_m2 and floor_area_m2 > 0:
        # Fallback: annualize the series to kWh/m2/yr.
        # series is hourly kW for BDG2 -> kWh == kW numerically per step.
        hours = len(s)
        annual_kwh = mean * 8760.0
        eui = float(annual_kwh / floor_area_m2)

    return {
        "peak_offpeak_ratio": round(peak_offpeak, 4),
        "weekday_weekend_ratio": round(wd_we, 4),
        "load_factor": round(load_factor, 4),
        "shape_weekday": [round(x, 5) for x in wd_norm],
        "shape_weekend": [round(x, 5) for x in we_norm],
        "peak_hour_weekday": peak_hour_wd,
        "mean_kw": round(mean, 4),
        "peak_kw": round(peak, 4),
        "eui_kwh_m2_yr": round(eui, 2) if eui is not None else None,
        "peak_w_m2": round(peak / floor_area_m2 * 1000.0, 2)
        if floor_area_m2 and floor_area_m2 > 0 else None,
        "n_buildings": int(n_buildings),
    }


# ---------------------------------------------------------------------------
# ComStock
# ---------------------------------------------------------------------------

def process_comstock(zones: list[str], force: bool, manifest: list[dict]):
    frames = []
    bands: dict[str, dict] = {}

    for cz in zones:
        czl = cz.lower()
        for btype, (archetype, size, proto_m2) in COMSTOCK_TYPES.items():
            url = COMSTOCK_BASE.format(cz=cz, czl=czl, btype=btype)
            dest = RAW_DIR / f"comstock_{czl}_{btype}.csv"
            path = download(url, dest, force, manifest)
            if path is None:
                continue
            try:
                df = pd.read_csv(path)
            except Exception as exc:  # noqa: BLE001
                log(f"ERROR   parse {dest.name}: {exc}")
                continue

            models = float(df["models_used"].iloc[0])
            if models <= 0:
                log(f"WARNING {dest.name}: models_used={models}, skipping")
                continue
            # floor_area_represented is the represented STOCK floor area, in ft^2.
            # The out.*.kwh columns are energy summed over that represented stock.
            floor_area_repr_m2 = float(df["floor_area_represented"].iloc[0]) / SQFT_PER_SQM

            ts = pd.to_datetime(df["timestamp"])

            flex_present = [c for c in FLEX_COLS if c in df.columns]
            inflex_present = [c for c in INFLEX_COLS if c in df.columns]

            # Per-m2 instantaneous power (kW/m2) over the represented stock:
            #   kW = kwh_15min * 4 ; divide by represented area -> kW/m2.
            # Scale to ONE representative prototype building of proto_m2 so the
            # tidy kW columns are physically meaningful single-building loads.
            scale = 4.0 / floor_area_repr_m2 * proto_m2
            flex_kw = df[flex_present].sum(axis=1).to_numpy() * scale
            inflex_kw = df[inflex_present].sum(axis=1).to_numpy() * scale
            total_kw = df[TOTAL_COL].to_numpy() * scale

            # EUI (kWh/m2/yr) from represented stock = annual_kwh / represented_area.
            annual_kwh = float(df[TOTAL_COL].sum())
            eui_kwh_m2_yr = annual_kwh / floor_area_repr_m2

            tdf = pd.DataFrame({
                "source": "comstock",
                "archetype": archetype,
                "size": size,
                "climate_zone": cz,
                "building_id": "",
                "timestamp": ts.to_numpy(),
                "flex_kw": flex_kw,
                "inflex_kw": inflex_kw,
                "total_kw": total_kw,
                "floor_area_m2": proto_m2,
            })
            frames.append(tdf)

            s_total = pd.Series(total_kw, index=pd.DatetimeIndex(ts))
            metrics = characterize(s_total, proto_m2, int(round(models)),
                                   eui_kwh_m2_yr=eui_kwh_m2_yr)
            key = f"{archetype}|{size}|{cz}"
            bands[key] = metrics
            n_inflex_note = "" if "out.electricity.exterior_equipment.energy_consumption.kwh" not in df.columns else " (+extequip)"
            log(
                f"CHAR    {key}: peak/off={metrics.get('peak_offpeak_ratio')} "
                f"wd/we={metrics.get('weekday_weekend_ratio')} lf={metrics.get('load_factor')} "
                f"EUI={metrics.get('eui_kwh_m2_yr')} kWh/m2/yr peakdens={metrics.get('peak_w_m2')} W/m2 "
                f"peak={metrics.get('peak_kw')}kW proto={proto_m2:.0f}m2 n={int(round(models))}{n_inflex_note}"
            )

    ts_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # BAND entries: lo/hi across zones for each (archetype,size) with +/-10% margin.
    band_keys: dict[tuple[str, str], list[str]] = {}
    for key in bands:
        arch, size, _cz = key.split("|")
        band_keys.setdefault((arch, size), []).append(key)

    for (arch, size), keys in band_keys.items():
        def collect(metric: str) -> list[float]:
            return [bands[k][metric] for k in keys
                    if bands[k].get(metric) is not None and np.isfinite(bands[k][metric])]
        band_entry = {"_zones": [k.split("|")[2] for k in keys]}
        for metric in ("peak_offpeak_ratio", "weekday_weekend_ratio", "load_factor"):
            vals = collect(metric)
            if vals:
                lo = min(vals) * 0.9
                hi = max(vals) * 1.1
                band_entry[metric] = [round(lo, 4), round(hi, 4)]
            else:
                band_entry[metric] = [None, None]
        bands[f"{arch}|{size}|BAND"] = band_entry

    return ts_df, bands


# ---------------------------------------------------------------------------
# BDG2
# ---------------------------------------------------------------------------

def process_bdg2(max_bdg2: int, force: bool, manifest: list[dict]):
    meta_path = RAW_DIR / "bdg2_metadata.csv"
    if download(BDG2_META_URL, meta_path, force, manifest) is None:
        log("ERROR   BDG2 metadata download failed; skipping BDG2")
        return pd.DataFrame(), {}, {"kept": [], "dropped": []}

    meta = pd.read_csv(meta_path)
    meta.columns = [c.strip() for c in meta.columns]

    def has_elec(v) -> bool:
        return str(v).strip().lower() in ("yes", "y", "true", "1")

    elig = meta[meta["electricity"].apply(has_elec)].copy()
    elig = elig[elig["sqm"].notna() & (pd.to_numeric(elig["sqm"], errors="coerce") > 0)]
    elig["sqm"] = pd.to_numeric(elig["sqm"], errors="coerce")

    office = elig[elig["primaryspaceusage"].astype(str).str.strip().str.lower() == "office"]
    retail = elig[elig["primaryspaceusage"].astype(str).str.strip().str.lower() == "retail"]

    # spread of office sizes: sort by sqm, take evenly-spaced sample up to ~15
    n_office = min(15, max(0, max_bdg2 - 5))
    office_sorted = office.sort_values("sqm")
    if len(office_sorted) > n_office and n_office > 0:
        idx = np.linspace(0, len(office_sorted) - 1, n_office).round().astype(int)
        office_sel = office_sorted.iloc[np.unique(idx)]
    else:
        office_sel = office_sorted
    retail_sel = retail.head(5)

    selected = pd.concat([office_sel, retail_sel])
    sel_ids = [str(b) for b in selected["building_id"].tolist()]
    log(f"BDG2    selected {len(office_sel)} office + {len(retail_sel)} retail = {len(sel_ids)} candidates")

    # Download electricity meters (cleaned preferred)
    elec_path = None
    for url in BDG2_ELEC_URLS:
        name = "bdg2_" + url.rstrip("/").split("/")[-1]
        dest = RAW_DIR / name
        p = download(url, dest, force, manifest)
        if p is not None:
            elec_path = p
            break
    if elec_path is None:
        log("ERROR   BDG2 electricity download failed; skipping BDG2 timeseries")
        return pd.DataFrame(), {}, {"kept": [], "dropped": []}

    # Read only timestamp + selected building columns
    header = pd.read_csv(elec_path, nrows=0)
    avail = set(header.columns)
    ts_name = "timestamp" if "timestamp" in avail else header.columns[0]
    usecols = [ts_name] + [b for b in sel_ids if b in avail]
    missing = [b for b in sel_ids if b not in avail]
    if missing:
        log(f"BDG2    {len(missing)} selected ids absent from meter file: {missing[:10]}{'...' if len(missing)>10 else ''}")
    edf = pd.read_csv(elec_path, usecols=usecols, parse_dates=[ts_name])
    edf = edf.set_index(ts_name).sort_index()

    meta_by_id = selected.set_index(selected["building_id"].astype(str))

    frames = []
    per_building_metrics: list[dict] = []
    kept, dropped = [], []
    for bid in [c for c in edf.columns]:
        s = edf[bid].astype(float)
        n = len(s)
        nan_frac = float(s.isna().mean())
        nonzero = s.fillna(0.0)
        all_zero = bool((nonzero == 0).all())
        if nan_frac > 0.40 or all_zero:
            dropped.append({"building_id": bid, "nan_frac": round(nan_frac, 3), "all_zero": all_zero})
            log(f"BDG2    DROP {bid}: nan_frac={nan_frac:.2f} all_zero={all_zero}")
            continue
        row = meta_by_id.loc[bid] if bid in meta_by_id.index else None
        usage = str(row["primaryspaceusage"]).strip().lower() if row is not None else ""
        archetype = "office" if usage == "office" else ("retail" if usage == "retail" else usage)
        sqm = float(row["sqm"]) if row is not None and pd.notna(row.get("sqm")) else np.nan
        eui_meta = None
        if row is not None and "eui" in meta_by_id.columns and pd.notna(row.get("eui")):
            try:
                eui_meta = float(row["eui"])
            except (ValueError, TypeError):
                eui_meta = None

        # kWh/hour == kW numerically
        s_kw = s.copy()
        tdf = pd.DataFrame({
            "source": "bdg2",
            "archetype": archetype,
            "size": "",
            "climate_zone": "",
            "building_id": bid,
            "timestamp": s_kw.index.to_numpy(),
            "flex_kw": np.nan,
            "inflex_kw": np.nan,
            "total_kw": s_kw.to_numpy(),
            "floor_area_m2": sqm,
        })
        frames.append(tdf)

        m = characterize(s_kw, sqm, 1, eui_override=eui_meta)
        m["building_id"] = bid
        m["archetype"] = archetype
        per_building_metrics.append(m)
        kept.append({"building_id": bid, "archetype": archetype, "sqm": round(sqm, 1) if pd.notna(sqm) else None,
                     "nan_frac": round(nan_frac, 3)})
        log(f"BDG2    KEEP {bid} ({archetype}, {sqm:.0f}m2): peak/off={m.get('peak_offpeak_ratio')} "
            f"lf={m.get('load_factor')} eui={m.get('eui_kwh_m2_yr')}")

    ts_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # Pool per-archetype: BDG2 keys "<archetype>|bdg2|all"
    bands: dict[str, dict] = {}
    by_arch: dict[str, list[dict]] = {}
    for m in per_building_metrics:
        by_arch.setdefault(m["archetype"], []).append(m)

    for arch, ms in by_arch.items():
        def med_shape(key: str) -> list[float]:
            arr = np.array([m[key] for m in ms], dtype=float)  # each already max-normed
            prof = np.nanmean(arr, axis=0)
            mx = np.nanmax(prof)
            return [round(float(x / mx), 5) for x in prof] if mx > 0 else [round(float(x), 5) for x in prof]

        def stat(metric: str):
            vals = [m[metric] for m in ms if m.get(metric) is not None and np.isfinite(m[metric])]
            if not vals:
                return None, None, None
            return (round(float(np.median(vals)), 4),
                    round(float(np.percentile(vals, 10)), 4),
                    round(float(np.percentile(vals, 90)), 4))

        po_med, po_lo, po_hi = stat("peak_offpeak_ratio")
        ww_med, ww_lo, ww_hi = stat("weekday_weekend_ratio")
        lf_med, lf_lo, lf_hi = stat("load_factor")
        eui_vals = [m["eui_kwh_m2_yr"] for m in ms if m.get("eui_kwh_m2_yr") is not None]
        wd_shape = med_shape("shape_weekday")
        bands[f"{arch}|bdg2|all"] = {
            "peak_offpeak_ratio": po_med,
            "peak_offpeak_ratio_band": [po_lo, po_hi],
            "weekday_weekend_ratio": ww_med,
            "weekday_weekend_ratio_band": [ww_lo, ww_hi],
            "load_factor": lf_med,
            "load_factor_band": [lf_lo, lf_hi],
            "shape_weekday": wd_shape,
            "shape_weekend": med_shape("shape_weekend"),
            "peak_hour_weekday": int(np.argmax(wd_shape)),
            "mean_kw": None,
            "peak_kw": None,
            "eui_kwh_m2_yr": round(float(np.median(eui_vals)), 3) if eui_vals else None,
            "n_buildings": len(ms),
        }
        log(f"BDG2    POOL {arch}|bdg2|all: n={len(ms)} peak/off={po_med}[{po_lo},{po_hi}] "
            f"wd/we={ww_med} lf={lf_med}[{lf_lo},{lf_hi}] eui={bands[f'{arch}|bdg2|all']['eui_kwh_m2_yr']}")

    return ts_df, bands, {"kept": kept, "dropped": dropped, "selected_ids": sel_ids}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zones", nargs="+", default=DEFAULT_ZONES,
                    help="ASHRAE/IECC climate zones (default: 5B 3B 4A 6A)")
    ap.add_argument("--max-bdg2", type=int, default=20,
                    help="max BDG2 buildings to select (~15 office + 5 retail)")
    ap.add_argument("--force", action="store_true", help="re-download cached raw files")
    ap.add_argument("--skip-comstock", action="store_true")
    ap.add_argument("--skip-bdg2", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    manifest_dl: list[dict] = []
    all_bands: dict[str, dict] = {}
    summary_rows: list[tuple] = []

    log(f"=== fetch_buildingload_reference start; zones={args.zones} max_bdg2={args.max_bdg2} force={args.force} ===")

    if not args.skip_comstock:
        cs_ts, cs_bands = process_comstock(args.zones, args.force, manifest_dl)
        if not cs_ts.empty:
            p = OUT_DIR / "comstock_timeseries.parquet"
            cs_ts.to_parquet(p, index=False)
            log(f"WROTE   {p.name} ({p.stat().st_size:,} bytes, {len(cs_ts):,} rows)")
        all_bands.update(cs_bands)
        for k, v in cs_bands.items():
            if k.endswith("|BAND"):
                continue
            arch, size, cz = k.split("|")
            summary_rows.append((f"{arch}/{size}", cz, v.get("peak_offpeak_ratio"),
                                 v.get("weekday_weekend_ratio"), v.get("load_factor"),
                                 v.get("eui_kwh_m2_yr")))

    bdg2_info = {"kept": [], "dropped": []}
    if not args.skip_bdg2:
        b_ts, b_bands, bdg2_info = process_bdg2(args.max_bdg2, args.force, manifest_dl)
        if not b_ts.empty:
            p = OUT_DIR / "bdg2_timeseries.parquet"
            b_ts.to_parquet(p, index=False)
            log(f"WROTE   {p.name} ({p.stat().st_size:,} bytes, {len(b_ts):,} rows)")
        all_bands.update(b_bands)
        for k, v in b_bands.items():
            arch = k.split("|")[0]
            summary_rows.append((f"{arch}/bdg2", "all", v.get("peak_offpeak_ratio"),
                                 v.get("weekday_weekend_ratio"), v.get("load_factor"),
                                 v.get("eui_kwh_m2_yr")))

    # Write reference_bands.json
    bands_path = OUT_DIR / "reference_bands.json"
    bands_path.write_text(json.dumps(all_bands, indent=2))
    log(f"WROTE   {bands_path.name} ({bands_path.stat().st_size:,} bytes, {len(all_bands)} keys)")

    # Manifest + log
    total_bytes = sum(m["bytes"] for m in manifest_dl)
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "zones": args.zones,
        "max_bdg2": args.max_bdg2,
        "downloads": manifest_dl,
        "total_bytes": total_bytes,
        "n_band_keys": len(all_bands),
        "bdg2_kept": bdg2_info.get("kept", []),
        "bdg2_dropped": bdg2_info.get("dropped", []),
    }
    (OUT_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    log(f"WROTE   MANIFEST.json (total downloaded/cached {total_bytes:,} bytes)")
    (OUT_DIR / "download_log.txt").write_text("\n".join(LOG_LINES) + "\n")

    # Summary table
    print("\n" + "=" * 92)
    print(f"{'archetype/size':<18}{'zone':<6}{'peak/off':>10}{'wd/we':>9}{'load_f':>9}{'EUI kWh/m2/yr':>15}")
    print("-" * 92)
    for r in summary_rows:
        po = f"{r[2]:.2f}" if isinstance(r[2], (int, float)) and r[2] == r[2] else "n/a"
        ww = f"{r[3]:.2f}" if isinstance(r[3], (int, float)) and r[3] == r[3] else "n/a"
        lf = f"{r[4]:.3f}" if isinstance(r[4], (int, float)) and r[4] == r[4] else "n/a"
        eu = f"{r[5]:.1f}" if isinstance(r[5], (int, float)) and r[5] is not None else "n/a"
        print(f"{r[0]:<18}{r[1]:<6}{po:>10}{ww:>9}{lf:>9}{eu:>11}")
    print("=" * 92)

    # BAND ranges
    print("\nBAND ranges (across zones, +/-10% margin):")
    for k in sorted(all_bands):
        if k.endswith("|BAND"):
            v = all_bands[k]
            print(f"  {k}: peak/off={v.get('peak_offpeak_ratio')} "
                  f"wd/we={v.get('weekday_weekend_ratio')} lf={v.get('load_factor')} "
                  f"zones={v.get('_zones')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
