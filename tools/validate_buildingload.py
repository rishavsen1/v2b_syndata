#!/usr/bin/env python3
"""Real-data fidelity validation for the synthetic building load.

Replaces the old self-referential S5 check (which compared EnergyPlus output to
bands derived from the generator's OWN occupancy schedules) with genuine
real-data validation against NREL ComStock / EULP commercial end-use load
profiles and BDG2 real metered buildings.

Pipeline
--------
1. Generate the generator's CZ-5B (Denver) building load for each shipped
   prototype with ``peak_kw_scaling`` OFF, so absolute kW / EUI compare.
2. Align it to the matched ComStock (and, where applicable, BDG2) reference
   profile from ``data/buildingload_reference/`` produced by
   ``fetch_buildingload_reference.py``.
3. Compute ASHRAE Guideline-14 metrics — CV(RMSE) (≤30% hourly), NMBE
   (≤±10%) — plus normalized-shape correlation, peak-hour error (Δh), and
   load factor.
4. Emit a per-(archetype,size) metrics table to stdout and a JSON.

The heavy EnergyPlus generation is isolated in :func:`generate_generator_load`
so the metric maths can be unit-tested with synthetic fixtures. Run with
``--help`` for options.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("validate_buildingload")

REPO = Path(__file__).resolve().parent.parent
REFERENCE_DIR = REPO / "data" / "buildingload_reference"

# ASHRAE Guideline-14 hourly thresholds.
CVRMSE_THRESHOLD = 30.0   # percent
NMBE_THRESHOLD = 10.0     # percent (absolute)

# Denver TMYx station (CZ-5B) — the climate zone the generator ships.
DENVER_TMYX = "USA_CO_Denver.Intl.AP.725650_TMYx"

# The 5 shipped DOE prototypes, as (archetype, size) generator keys mapped to
# the ComStock building_type / reference-band size token.
#   generator size keys:  office -> small/med/large ; retail -> med/large
#   reference_bands key:  "<archetype>|<size>|<CZ>" with size in
#                         small/med/large (med == mediumoffice / stripmall)
SHIPPED_PROTOTYPES: list[tuple[str, str, str]] = [
    # (archetype, generator_size, reference_size)
    ("office", "small", "small"),
    ("office", "med", "med"),
    ("office", "large", "large"),
    ("retail", "med", "med"),     # RetailStripmall
    ("retail", "large", "large"),  # RetailStandalone
]


# ──────────────────────────────────────────────────────────────────────
# Pure metric functions (unit-testable, no EnergyPlus, no I/O)
# ──────────────────────────────────────────────────────────────────────

def cv_rmse(measured: np.ndarray, predicted: np.ndarray) -> float:
    """ASHRAE G14 coefficient of variation of the RMSE, in PERCENT.

    ``measured`` is the reference (real / ComStock) series, ``predicted`` is
    the generator series. CV(RMSE) = 100 * RMSE / mean(measured).
    """
    measured = np.asarray(measured, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if measured.shape != predicted.shape:
        raise ValueError(f"shape mismatch {measured.shape} vs {predicted.shape}")
    n = measured.size
    if n == 0:
        return float("nan")
    rmse = np.sqrt(np.sum((measured - predicted) ** 2) / n)
    mbar = float(np.mean(measured))
    if abs(mbar) < 1e-12:
        return float("nan")
    return 100.0 * rmse / mbar


def nmbe(measured: np.ndarray, predicted: np.ndarray) -> float:
    """ASHRAE G14 normalized mean bias error, in PERCENT (signed).

    NMBE = 100 * sum(measured - predicted) / ((n) * mean(measured)).
    Positive => the generator under-predicts vs the reference.
    """
    measured = np.asarray(measured, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if measured.shape != predicted.shape:
        raise ValueError(f"shape mismatch {measured.shape} vs {predicted.shape}")
    n = measured.size
    if n == 0:
        return float("nan")
    mbar = float(np.mean(measured))
    if abs(mbar) < 1e-12:
        return float("nan")
    return 100.0 * float(np.sum(measured - predicted)) / (n * mbar)


def shape_correlation(shape_a: np.ndarray, shape_b: np.ndarray) -> float:
    """Pearson correlation between two (normalized) 24h shapes."""
    a = np.asarray(shape_a, dtype=float)
    b = np.asarray(shape_b, dtype=float)
    if a.shape != b.shape or a.size < 2:
        return float("nan")
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def peak_hour_error(shape_a: np.ndarray, shape_b: np.ndarray) -> int:
    """Absolute difference (in hours, wrap-around) of the argmax of two shapes."""
    a = int(np.argmax(np.asarray(shape_a, dtype=float)))
    b = int(np.argmax(np.asarray(shape_b, dtype=float)))
    diff = abs(a - b)
    return min(diff, 24 - diff)


def load_factor(series: np.ndarray) -> float:
    """mean / peak over the series (dimensionless, 0..1)."""
    s = np.asarray(series, dtype=float)
    pk = float(np.max(s)) if s.size else 0.0
    if pk < 1e-12:
        return float("nan")
    return float(np.mean(s)) / pk


def normalized_weekday_shape(series: pd.Series) -> np.ndarray:
    """Average WEEKDAY 24h profile, normalized so max == 1.0.

    ``series`` is a datetime-indexed kW series at any sub-daily resolution.
    """
    df = pd.DataFrame({"kw": series.to_numpy()}, index=pd.DatetimeIndex(series.index))
    weekday = df[df.index.dayofweek < 5]
    if weekday.empty:
        weekday = df
    prof = weekday.groupby(weekday.index.hour)["kw"].mean()
    prof = prof.reindex(range(24)).interpolate().bfill().ffill()
    arr = prof.to_numpy()
    mx = float(np.max(arr))
    return arr / mx if mx > 1e-12 else arr


def normalized_weekend_shape(series: pd.Series) -> np.ndarray:
    """Average WEEKEND 24h profile, normalized so max == 1.0."""
    df = pd.DataFrame({"kw": series.to_numpy()}, index=pd.DatetimeIndex(series.index))
    weekend = df[df.index.dayofweek >= 5]
    if weekend.empty:
        weekend = df
    prof = weekend.groupby(weekend.index.hour)["kw"].mean()
    prof = prof.reindex(range(24)).interpolate().bfill().ffill()
    arr = prof.to_numpy()
    mx = float(np.max(arr))
    return arr / mx if mx > 1e-12 else arr


def to_hourly(series: pd.Series) -> pd.Series:
    """Resample a sub-hourly kW series to hourly means (G14 hourly metrics)."""
    idx = pd.DatetimeIndex(series.index)
    s = pd.Series(series.to_numpy(), index=idx)
    return s.resample("1h").mean().dropna()


@dataclass
class BuildingLoadMetrics:
    archetype: str
    size: str
    climate_zone: str
    n_hours: int
    gen_mean_kw: float
    gen_peak_kw: float
    ref_mean_kw: float
    ref_peak_kw: float
    cv_rmse_pct: float
    nmbe_pct: float
    shape_corr_weekday: float
    shape_corr_weekend: float
    peak_hour_err_h: int
    gen_load_factor: float
    ref_load_factor: float
    cvrmse_pass: bool
    nmbe_pass: bool

    def passes(self) -> bool:
        return bool(self.cvrmse_pass and self.nmbe_pass)


def compute_metrics(
    gen_hourly: pd.Series,
    ref_hourly: pd.Series,
    *,
    archetype: str,
    size: str,
    climate_zone: str,
) -> BuildingLoadMetrics:
    """Compute the full G14 + shape metric set for one (archetype,size,CZ).

    Both inputs are hourly-mean kW Series; they are aligned on the intersecting
    hour-of-year (or any shared DatetimeIndex). When the indices differ (e.g.
    ComStock 2018 vs generator 2020) they are aligned by (month, day, hour) so
    the diurnal+seasonal shapes overlay — magnitudes are compared as-is.
    """
    g = pd.Series(gen_hourly.to_numpy(), index=pd.DatetimeIndex(gen_hourly.index))
    r = pd.Series(ref_hourly.to_numpy(), index=pd.DatetimeIndex(ref_hourly.index))

    # Align by calendar position (month, day, hour) so differing reference years
    # still overlay on the diurnal+seasonal cycle.
    def _key(idx: pd.DatetimeIndex) -> pd.MultiIndex:
        return pd.MultiIndex.from_arrays([idx.month, idx.day, idx.hour])

    g2 = g.copy()
    r2 = r.copy()
    g2.index = _key(g.index)
    r2.index = _key(r.index)
    g2 = g2[~g2.index.duplicated(keep="first")]
    r2 = r2[~r2.index.duplicated(keep="first")]
    common = g2.index.intersection(r2.index)
    if len(common) == 0:
        raise ValueError("no overlapping (month,day,hour) between gen and ref")
    gv = g2.loc[common].to_numpy()
    rv = r2.loc[common].to_numpy()

    wd_g = normalized_weekday_shape(g)
    wd_r = normalized_weekday_shape(r)
    we_g = normalized_weekend_shape(g)
    we_r = normalized_weekend_shape(r)

    cvr = cv_rmse(rv, gv)
    nm = nmbe(rv, gv)
    return BuildingLoadMetrics(
        archetype=archetype,
        size=size,
        climate_zone=climate_zone,
        n_hours=int(len(common)),
        gen_mean_kw=float(np.mean(gv)),
        gen_peak_kw=float(np.max(gv)),
        ref_mean_kw=float(np.mean(rv)),
        ref_peak_kw=float(np.max(rv)),
        cv_rmse_pct=cvr,
        nmbe_pct=nm,
        shape_corr_weekday=shape_correlation(wd_g, wd_r),
        shape_corr_weekend=shape_correlation(we_g, we_r),
        peak_hour_err_h=peak_hour_error(wd_g, wd_r),
        gen_load_factor=load_factor(gv),
        ref_load_factor=load_factor(rv),
        cvrmse_pass=bool(cvr <= CVRMSE_THRESHOLD) if np.isfinite(cvr) else False,
        nmbe_pass=bool(abs(nm) <= NMBE_THRESHOLD) if np.isfinite(nm) else False,
    )


# ──────────────────────────────────────────────────────────────────────
# Reference loading (ComStock parquet) — pure I/O, no EnergyPlus
# ──────────────────────────────────────────────────────────────────────

def load_reference_hourly(
    archetype: str,
    size: str,
    climate_zone: str,
    *,
    reference_dir: Path = REFERENCE_DIR,
    metric: str = "total_kw",
) -> pd.Series:
    """Load the ComStock per-building hourly-mean kW series for a prototype.

    Reads ``comstock_timeseries.parquet`` (tidy long format with columns
    source/archetype/size/climate_zone/timestamp/flex_kw/inflex_kw/total_kw).
    Returns an hourly-mean kW Series. Raises FileNotFoundError if the
    reference parquet is missing, KeyError if the cell is absent.
    """
    pq = reference_dir / "comstock_timeseries.parquet"
    if not pq.exists():
        raise FileNotFoundError(
            f"reference parquet missing: {pq}. Run "
            "tools/fetch_buildingload_reference.py first."
        )
    df = pd.read_parquet(pq)
    sel = df[
        (df["source"] == "comstock")
        & (df["archetype"] == archetype)
        & (df["size"] == size)
        & (df["climate_zone"] == climate_zone)
    ]
    if sel.empty:
        raise KeyError(
            f"no comstock reference for ({archetype},{size},{climate_zone})"
        )
    s = pd.Series(
        sel[metric].to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(sel["timestamp"])),
    ).sort_index()
    return to_hourly(s)


# ──────────────────────────────────────────────────────────────────────
# Generator load (EnergyPlus) — heavy; isolated for test gating
# ──────────────────────────────────────────────────────────────────────

def _occupancy_for(idx: pd.DatetimeIndex, archetype: str) -> pd.Series:
    """Build the generator's ASHRAE occupancy series for a given archetype."""
    from v2b_syndata.samplers.load import _build_occupancy_series

    source = "ashrae_90_1_retail" if archetype == "retail" else "ashrae_90_1_office"
    return _build_occupancy_series(source, idx)


def generate_generator_load(
    archetype: str,
    size: str,
    *,
    tmyx_station: str = DENVER_TMYX,
    sim_start: str = "2018-01-01",
    sim_end: str = "2019-01-01",
) -> pd.Series:
    """Run the generator's EnergyPlus pipeline (peak_kw_scaling implicitly OFF —
    we read raw kW directly from ``simulate_building_load``) and return the
    total (flex+inflex) kW Series at native 15-min resolution.

    Requires a real EnergyPlus binary; gate callers with the
    ``real_energyplus`` marker. Heavy (one annual EnergyPlus run per call,
    content-addressed-cached under ``data/load_pipeline_cache``).
    """
    from v2b_syndata.load_pipeline import simulate_building_load

    start = pd.Timestamp(sim_start)
    end = pd.Timestamp(sim_end)
    idx = pd.date_range(start, end, freq="15min", inclusive="left")
    occ = _occupancy_for(idx, archetype)
    flex, inflex = simulate_building_load(
        archetype=archetype,
        size=size,
        tmyx_station=tmyx_station,
        occupancy=occ,
        sim_window_start=start,
        sim_window_end=end,
    )
    total = (flex.fillna(0.0) + inflex.fillna(0.0)).rename("total_kw")
    return total


# ──────────────────────────────────────────────────────────────────────
# Orchestration + reporting
# ──────────────────────────────────────────────────────────────────────

def validate_all(
    *,
    climate_zone: str = "5B",
    tmyx_station: str = DENVER_TMYX,
    sim_start: str = "2018-01-01",
    sim_end: str = "2019-01-01",
    reference_dir: Path = REFERENCE_DIR,
    prototypes: list[tuple[str, str, str]] | None = None,
) -> list[BuildingLoadMetrics]:
    """Run the full validation across the shipped prototypes. Returns metrics."""
    protos = prototypes if prototypes is not None else SHIPPED_PROTOTYPES
    results: list[BuildingLoadMetrics] = []
    for archetype, gen_size, ref_size in protos:
        log.info("validating %s/%s (CZ %s)", archetype, gen_size, climate_zone)
        try:
            ref = load_reference_hourly(
                archetype, ref_size, climate_zone, reference_dir=reference_dir
            )
        except (FileNotFoundError, KeyError) as e:
            log.warning("skipping %s/%s: %s", archetype, gen_size, e)
            continue
        gen = generate_generator_load(
            archetype, gen_size, tmyx_station=tmyx_station,
            sim_start=sim_start, sim_end=sim_end,
        )
        gen_h = to_hourly(gen)
        m = compute_metrics(
            gen_h, ref,
            archetype=archetype, size=gen_size, climate_zone=climate_zone,
        )
        results.append(m)
    return results


def format_table(results: list[BuildingLoadMetrics]) -> str:
    """Render a fixed-width metrics table."""
    hdr = (
        f"{'archetype':<9} {'size':<6} {'CZ':<3} {'gen_kW':>7} {'ref_kW':>7} "
        f"{'CVRMSE%':>8} {'NMBE%':>7} {'corr_wd':>7} {'corr_we':>7} "
        f"{'pkΔh':>5} {'gen_LF':>6} {'ref_LF':>6} {'pass':>5}"
    )
    lines = [hdr, "-" * len(hdr)]
    for m in results:
        lines.append(
            f"{m.archetype:<9} {m.size:<6} {m.climate_zone:<3} "
            f"{m.gen_mean_kw:>7.1f} {m.ref_mean_kw:>7.1f} "
            f"{m.cv_rmse_pct:>8.1f} {m.nmbe_pct:>7.1f} "
            f"{m.shape_corr_weekday:>7.3f} {m.shape_corr_weekend:>7.3f} "
            f"{m.peak_hour_err_h:>5d} {m.gen_load_factor:>6.3f} "
            f"{m.ref_load_factor:>6.3f} {('PASS' if m.passes() else 'FAIL'):>5}"
        )
    n_pass = sum(1 for m in results if m.passes())
    lines.append("-" * len(hdr))
    lines.append(
        f"{n_pass}/{len(results)} archetypes pass G14 (CV(RMSE)≤{CVRMSE_THRESHOLD}%, "
        f"|NMBE|≤{NMBE_THRESHOLD}%)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--climate-zone", default="5B")
    ap.add_argument("--tmyx-station", default=DENVER_TMYX)
    ap.add_argument("--sim-start", default="2018-01-01")
    ap.add_argument("--sim-end", default="2019-01-01")
    ap.add_argument(
        "--reference-dir", type=Path, default=REFERENCE_DIR,
        help="dir holding comstock_timeseries.parquet + reference_bands.json",
    )
    ap.add_argument(
        "--json-out", type=Path,
        default=REFERENCE_DIR / "validation_metrics.json",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    results = validate_all(
        climate_zone=args.climate_zone,
        tmyx_station=args.tmyx_station,
        sim_start=args.sim_start,
        sim_end=args.sim_end,
        reference_dir=args.reference_dir,
    )
    if not results:
        print(
            "No results — is the reference parquet present? Run "
            "tools/fetch_buildingload_reference.py first."
        )
        return 1
    print(format_table(results))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps([asdict(m) for m in results], indent=2)
    )
    print(f"\nWrote metrics JSON → {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
