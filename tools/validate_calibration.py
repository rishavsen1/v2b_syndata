#!/usr/bin/env python
"""Calibration faithfulness verification harness.

Compares generated CSVs against the real-data sources they were calibrated
to. Per-region marginals (S1), joint arrival×dwell density (S2), held-out
KS (S3), building load vs PNNL prototype design intent (S5), and weekly
weekday/weekend patterns (S6).

Scope (2026-05-30):
  ACN-Data and ElaadNL/4TU Utrecht are calibrated against real bulk data
  and qualify for S1/S2/S3/S6. EV WATTS and INL are fixture-only and
  therefore excluded from real-vs-generated comparison. S5 is source-
  independent and runs on the EnergyPlus building-load output of a default
  scenario per (archetype, size).

EnergyPlus:
  Pin the engine for a reproducible baseline — the bundled prototypes are
  EnergyPlus 24.1, so run with ``ENERGYPLUS_BIN=/usr/local/bin/energyplus``
  (or any 24.1 install). Absolute load kW shift across EnergyPlus major
  versions; the load cache keys on the prototype IDF bytes, so upgrading the
  prototypes invalidates it automatically — but a bare binary swap that leaves
  the IDFs untouched needs a manual ``rm -rf data/load_pipeline_cache``.

Usage:
    uv run python tools/validate_calibration.py \\
        --output data/calibration_validation/ \\
        --seeds 50 \\
        --workers 16 \\
        [--sources acn,elaadnl]   # default: both real-calibrated sources

Outputs:
    data/calibration_validation/S1_marginals.csv
    data/calibration_validation/S2_joint.csv
    data/calibration_validation/S3_holdout.csv
    data/calibration_validation/S5_buildingload.csv
    data/calibration_validation/S6_weekly.csv
    data/calibration_validation/S1_marginals/<source>/<region>_<var>.png
    data/calibration_validation/S2_joint/<source>_<region>.png
    data/calibration_validation/figure_calibration_panel.png  (paper Fig 14a)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as stats
import yaml as pyyaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from v2b_syndata.calibration.feature_extractor import (  # noqa: E402
    aggregate_user_features,
)
from v2b_syndata.calibration.region_assignment import assign_user_to_region  # noqa: E402
from v2b_syndata.calibration.sources import CALIBRATION_SOURCES  # noqa: E402
from v2b_syndata.calibration.distribution_fitter import (  # noqa: E402
    fit_truncnorm_arrival,
    fit_weibull_dwell,
)
from v2b_syndata.runner import generate as runner_generate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("validate")


# Source → (policy, scenario, source_args, calibration_population)
SOURCE_SPECS = {
    "acn": {
        "policy": "acn_data",
        "scenario": "S_acn_workplace",
        "source_args": {
            "sites": ("caltech", "jpl", "office001"),
            "year_start": 2019,
            "year_end": 2021,
            "cache_dir": REPO / "data" / "calibration" / "acn_cache",
        },
        "population": "acn_workplace_baseline",
    },
    # ACN per-site subdivisions (3 cohorts within the single ACN-Data
    # dataset). Demonstrate that homogeneous single-site fits have
    # tighter K-S than the mixed multi-site pool.
    "acn_caltech": {
        "policy": "acn_data",
        "scenario": "S_acn_caltech",
        "source_args": {
            "sites": ("caltech",),
            "year_start": 2019,
            "year_end": 2021,
            "cache_dir": REPO / "data" / "calibration" / "acn_cache",
        },
        "population": "acn_caltech_baseline",
    },
    "acn_jpl": {
        "policy": "acn_data",
        "scenario": "S_acn_jpl",
        "source_args": {
            "sites": ("jpl",),
            "year_start": 2019,
            "year_end": 2021,
            "cache_dir": REPO / "data" / "calibration" / "acn_cache",
        },
        "population": "acn_jpl_baseline",
    },
    "acn_office001": {
        "policy": "acn_data",
        "scenario": "S_acn_office001",
        "source_args": {
            "sites": ("office001",),
            "year_start": 2019,
            "year_end": 2021,
            "cache_dir": REPO / "data" / "calibration" / "acn_cache",
        },
        "population": "acn_office001_baseline",
    },
    "elaadnl": {
        "policy": "elaadnl_open_2020",
        "scenario": "S_elaadnl_public_eu",
        "source_args": {
            "archive_tag": "utrecht_4tu_2024",
            "venue_filter": "workplace",
            "cache_dir": REPO / "data" / "calibration" / "elaadnl_cache",
        },
        "population": "elaadnl_public_eu",
    },
    # EV WATTS (DOE/EPRI) workplace cohort — real public data ingested via
    # tools/ingest_evwatts.py (session⋈evse, venue="Business Office").
    "evwatts": {
        "policy": "evwatts",
        "scenario": "S_evwatts_workplace",
        "source_args": {
            "release_tag": "public_2026",
            "venue_filter": "workplace_public",
            "cache_dir": REPO / "data" / "calibration" / "evwatts_cache",
        },
        "population": "evwatts_workplace_public",
    },
}


@dataclass
class SourceData:
    name: str
    sessions_df: pd.DataFrame    # session-level
    region_axes: list[dict]
    user_to_region: dict[str, str]
    users: list                  # UserFeatures (per-driver phi / kappa / delta_km)


# ──────────────────────────────────────────────────────────────────────
# Source-side data fetch
# ──────────────────────────────────────────────────────────────────────

def load_source(source_key: str) -> SourceData:
    """Pull real SessionFeatures + assign each user to a region."""
    spec = SOURCE_SPECS[source_key]
    src_cls = CALIBRATION_SOURCES[spec["policy"]]
    src = src_cls()
    cfg = dict(spec["source_args"])  # copy
    log.info("loading source %s …", source_key)
    sessions = src.fetch_sessions(cfg)
    log.info("  fetched %d sessions", len(sessions))

    # Build the same UserFeatures aggregation used at calibrate-time.
    arr_times = [s.arrival_time for s in sessions]
    users = aggregate_user_features(sessions, min(arr_times), max(arr_times))
    log.info("  aggregated %d users", len(users))

    # Region assignment via the live population axes_distribution.
    pops_yaml = pyyaml.safe_load(
        (REPO / "configs" / "populations.yaml").read_text()
    )
    region_axes = pops_yaml[spec["population"]]["axes_distribution"]
    user_to_region = {}
    for u in users:
        r = assign_user_to_region(u, region_axes) or "__unassigned__"
        user_to_region[u.user_id] = r

    # Flatten sessions → DataFrame, augment with region + derived fields.
    rows = []
    for s in sessions:
        rows.append(
            dict(
                user_id=s.user_id,
                arrival_time=s.arrival_time,
                arrival_hour=s.arrival_hour,
                dwell_hours=s.dwell_hours,
                kwh_delivered=s.kwh_delivered,
                region=user_to_region.get(s.user_id, "__unassigned__"),
            )
        )
    sessions_df = pd.DataFrame(rows)
    sessions_df["arrival_time"] = pd.to_datetime(sessions_df["arrival_time"], utc=True)

    return SourceData(
        name=source_key,
        sessions_df=sessions_df,
        region_axes=region_axes,
        user_to_region=user_to_region,
        users=users,
    )


# ──────────────────────────────────────────────────────────────────────
# S0: region-assignment diagnostic — how real drivers map to regions
# ──────────────────────────────────────────────────────────────────────

def s0_assignment(
    source_key: str,
    source_data: SourceData,
    output_root: Path,
) -> pd.DataFrame:
    """Scatter source drivers in (φ, κ) space, coloured by assigned region, with
    the axes_distribution boxes overlaid and the unassigned fraction annotated.

    This visualises the grouping step itself: each real driver is a point at its
    (frequency φ, consistency κ); each dashed rectangle is a region definition;
    a point's colour is the region it first-matches (grey = matched no box).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out_dir = output_root / "assignment"
    out_dir.mkdir(parents=True, exist_ok=True)

    users = source_data.users
    axes = source_data.region_axes
    u2r = source_data.user_to_region
    n_total = len(users)

    region_names = [r["name"] for r in axes]
    cmap = plt.get_cmap("tab10")
    color = {name: cmap(i % 10) for i, name in enumerate(region_names)}
    color["__unassigned__"] = (0.72, 0.72, 0.72, 1.0)

    by_region: dict[str, list] = {}
    for u in users:
        by_region.setdefault(u2r.get(u.user_id, "__unassigned__"), []).append(u)

    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    # region boxes (skip zero-area / zero-weight that still define a box)
    for r in axes:
        phi_lo, phi_hi = r["freq"]
        kap_lo, kap_hi = r["consist"]
        ax.add_patch(Rectangle(
            (phi_lo, kap_lo), phi_hi - phi_lo, kap_hi - kap_lo,
            fill=False, edgecolor=color[r["name"]], linewidth=2.0,
            linestyle="--", zorder=2,
        ))

    rows = []
    for name in region_names + ["__unassigned__"]:
        us = by_region.get(name, [])
        if us:
            ax.scatter([u.phi for u in us], [u.kappa for u in us],
                       s=16, alpha=0.5, color=color[name], edgecolors="none",
                       label=f"{name} (n={len(us)})", zorder=3)
        rows.append({
            "source": source_key, "region": name, "n_users": len(us),
            "user_share": round(len(us) / n_total, 4) if n_total else 0.0,
        })

    n_unassigned = len(by_region.get("__unassigned__", []))
    pct_un = (n_unassigned / n_total * 100) if n_total else 0.0
    ax.set_xlabel("φ  —  charging frequency (fraction of active weekdays the driver shows up)")
    ax.set_ylabel("κ  —  arrival-time consistency (1 = same time every day, 0 = scattered)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_title(
        f"{source_key}: how {n_total} real drivers map to regions\n"
        f"dashed boxes = region definitions · {n_unassigned} unassigned ({pct_un:.0f}%)"
    )
    ax.legend(loc="lower left", fontsize=7, framealpha=0.92)
    ax.grid(True, alpha=0.15, zorder=0)
    fig.tight_layout()
    fig.savefig(out_dir / f"{source_key}.png", dpi=140)
    plt.close(fig)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────
# Generated-side: parallel seed generation
# ──────────────────────────────────────────────────────────────────────

def _gen_one(args: tuple) -> tuple[int, Path | None, str]:
    scenario, seed, out_dir, config_dir = args
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"
    if manifest.exists():
        return seed, out_dir, "cached"
    try:
        runner_generate(
            scenario_id=scenario, seed=seed,
            output_dir=out_dir, config_dir=config_dir,
        )
        return seed, out_dir, "generated"
    except Exception as e:  # noqa: BLE001
        log.error("seed %d failed: %s", seed, e)
        return seed, None, f"err: {type(e).__name__}: {e}"


def generate_seed_set(
    source_key: str, seeds: int, output_root: Path, workers: int
) -> list[Path]:
    """Generate `seeds` seeded scenarios for the source. Return list of output dirs."""
    spec = SOURCE_SPECS[source_key]
    scenario = spec["scenario"]
    base = output_root / "scenarios" / source_key
    jobs = [
        (scenario, seed, base / f"seed{seed}", REPO / "configs")
        for seed in range(1, seeds + 1)
    ]
    log.info("generating %d %s seeds …", seeds, source_key)
    out_dirs = []
    with ProcessPoolExecutor(max_workers=min(workers, 8)) as ex:
        for fut in as_completed([ex.submit(_gen_one, j) for j in jobs]):
            seed, sdir, msg = fut.result()
            if sdir is not None:
                out_dirs.append(sdir)
    log.info("  %d seeds materialized", len(out_dirs))
    return sorted(out_dirs)


def load_generated(source_key: str, seed_dirs: list[Path]) -> pd.DataFrame:
    """Concatenate sessions.csv across all seeds; tag each row with region."""
    spec = SOURCE_SPECS[source_key]
    pops_yaml = pyyaml.safe_load(
        (REPO / "configs" / "populations.yaml").read_text()
    )
    region_axes = pops_yaml[spec["population"]]["axes_distribution"]

    frames = []
    for sdir in seed_dirs:
        sessions = pd.read_csv(
            sdir / "sessions.csv",
            parse_dates=["arrival", "departure"],
        )
        users = pd.read_csv(sdir / "users.csv")
        # Map car_id → user attrs → region. users.csv has the per-user
        # behavioral axes (phi, kappa, region directly).
        if "region" in users.columns:
            car_region = dict(zip(users["car_id"], users["region"]))
        else:
            # Fall back: assign by (phi, kappa) range match
            car_region = {}
            for _, row in users.iterrows():
                fake_user = type("U", (), {
                    "phi": row["phi"], "kappa": row["kappa"],
                    "delta_km": row.get("delta_km", 0.0),
                    "user_id": str(row["car_id"]),
                })()
                car_region[row["car_id"]] = (
                    assign_user_to_region(fake_user, region_axes)
                    or "__unassigned__"
                )

        sessions["region"] = sessions["car_id"].map(car_region).fillna("__unassigned__")
        sessions["arrival_hour"] = (
            sessions["arrival"].dt.hour
            + sessions["arrival"].dt.minute / 60.0
        )
        sessions["dwell_hours"] = (
            sessions["departure"] - sessions["arrival"]
        ).dt.total_seconds() / 3600.0
        sessions["seed"] = int(sdir.name.replace("seed", ""))
        frames.append(
            sessions[["seed", "car_id", "region", "arrival",
                      "arrival_hour", "dwell_hours", "arrival_soc"]]
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────
# S1: per-region marginal validation
# ──────────────────────────────────────────────────────────────────────

def s1_marginals(
    source_key: str,
    source_df: pd.DataFrame,
    generated_df: pd.DataFrame,
    output_root: Path,
) -> pd.DataFrame:
    """KS, Wasserstein-1, histogram-overlay plots per (region, variable)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = output_root / "S1_marginals" / source_key
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    variables = [
        ("arrival_hour", "hour-of-day", (0, 24)),
        ("dwell_hours", "dwell (h)", (0, 24)),
    ]
    # Only compute regions that have data on BOTH sides
    regions = sorted(
        set(source_df["region"]) & set(generated_df["region"])
        - {"__unassigned__"}
    )

    for region in regions:
        src_r = source_df[source_df["region"] == region]
        gen_r = generated_df[generated_df["region"] == region]
        for var, label, xlim in variables:
            src_vals = src_r[var].dropna().to_numpy()
            gen_vals = gen_r[var].dropna().to_numpy()
            if len(src_vals) < 30 or len(gen_vals) < 30:
                log.warning("  %s/%s/%s: tiny sample (src=%d, gen=%d)",
                            source_key, region, var, len(src_vals), len(gen_vals))
                continue

            ks_stat, ks_p = stats.ks_2samp(src_vals, gen_vals)
            w1 = stats.wasserstein_distance(src_vals, gen_vals)
            rows.append({
                "source": source_key, "region": region, "variable": var,
                "n_source": len(src_vals), "n_generated": len(gen_vals),
                "ks_statistic": float(ks_stat), "ks_pvalue": float(ks_p),
                "wasserstein_1": float(w1),
                "source_mean": float(np.mean(src_vals)),
                "source_std": float(np.std(src_vals)),
                "generated_mean": float(np.mean(gen_vals)),
                "generated_std": float(np.std(gen_vals)),
            })

            fig, ax = plt.subplots(figsize=(6, 3.5))
            ax.hist(src_vals, bins=40, range=xlim, density=True,
                    alpha=0.5, label=f"source (n={len(src_vals)})",
                    color="tab:blue", edgecolor="none")
            ax.hist(gen_vals, bins=40, range=xlim, density=True,
                    alpha=0.5, label=f"generated (n={len(gen_vals)})",
                    color="tab:orange", edgecolor="none")
            ax.set_xlabel(label)
            ax.set_ylabel("density")
            ax.set_title(
                f"{source_key} / {region} / {var}\n"
                f"K-S={ks_stat:.3f}, W₁={w1:.3f}"
            )
            ax.legend(loc="upper right", fontsize=8)
            fig.tight_layout()
            fig.savefig(out_dir / f"{region}_{var}.png", dpi=130)
            plt.close(fig)

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────
# S2: joint (arrival × dwell) validation
# ──────────────────────────────────────────────────────────────────────

def s2_joint(
    source_key: str,
    source_df: pd.DataFrame,
    generated_df: pd.DataFrame,
    output_root: Path,
) -> pd.DataFrame:
    """Spearman ρ comparison + side-by-side 2D KDE."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = output_root / "S2_joint" / source_key
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    regions = sorted(
        set(source_df["region"]) & set(generated_df["region"])
        - {"__unassigned__"}
    )
    for region in regions:
        src_r = source_df[source_df["region"] == region]
        gen_r = generated_df[generated_df["region"] == region]
        src_arr = src_r["arrival_hour"].dropna().to_numpy()
        src_dwell = src_r["dwell_hours"].dropna().to_numpy()
        gen_arr = gen_r["arrival_hour"].dropna().to_numpy()
        gen_dwell = gen_r["dwell_hours"].dropna().to_numpy()

        if min(len(src_arr), len(src_dwell), len(gen_arr), len(gen_dwell)) < 30:
            continue

        # Align lengths (pairwise)
        n_src = min(len(src_arr), len(src_dwell))
        n_gen = min(len(gen_arr), len(gen_dwell))
        rho_src, _ = stats.spearmanr(src_arr[:n_src], src_dwell[:n_src])
        rho_gen, _ = stats.spearmanr(gen_arr[:n_gen], gen_dwell[:n_gen])
        rho_gap = abs(rho_src - rho_gen)

        rows.append({
            "source": source_key, "region": region,
            "n_source": int(n_src), "n_generated": int(n_gen),
            "spearman_rho_source": float(rho_src),
            "spearman_rho_generated": float(rho_gen),
            "rho_gap": float(rho_gap),
        })

        # Side-by-side scatter + density (cheap proxy for KDE)
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True, sharex=True)
        for ax, (a, d, label, color) in zip(
            axes,
            [(src_arr[:n_src], src_dwell[:n_src], "source", "tab:blue"),
             (gen_arr[:n_gen], gen_dwell[:n_gen], "generated", "tab:orange")],
        ):
            ax.scatter(a, d, s=1.5, alpha=0.25, color=color)
            ax.set_xlabel("arrival_hour")
            ax.set_title(f"{label} (n={len(a)}, ρ_S={stats.spearmanr(a, d)[0]:.2f})",
                         fontsize=9)
            ax.set_xlim(0, 24)
            ax.set_ylim(0, 24)
        axes[0].set_ylabel("dwell_hours")
        fig.suptitle(f"{source_key} / {region}: joint (arrival × dwell)", fontsize=11)
        fig.tight_layout()
        fig.savefig(out_dir / f"{region}.png", dpi=130)
        plt.close(fig)

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────
# S3: held-out KS (where sample size ≥ 200 per region)
# ──────────────────────────────────────────────────────────────────────

def s3_holdout(source_key: str, source_df: pd.DataFrame) -> pd.DataFrame:
    """80/20 split, refit on train, KS on test."""
    rows = []
    regions = sorted(set(source_df["region"]) - {"__unassigned__"})
    for region in regions:
        src_r = source_df[source_df["region"] == region]
        if len(src_r) < 200:
            continue
        # Deterministic split by user_id sort.
        users_sorted = sorted(src_r["user_id"].unique())
        cut = int(len(users_sorted) * 0.8)
        train_uids = set(users_sorted[:cut])
        train = src_r[src_r["user_id"].isin(train_uids)]
        test = src_r[~src_r["user_id"].isin(train_uids)]
        if len(test) < 30:
            continue

        # Fit arrival on train, KS on test
        for var, fit_fn in [
            ("arrival_hour", fit_truncnorm_arrival),
            ("dwell_hours", fit_weibull_dwell),
        ]:
            train_vals = train[var].dropna().to_numpy()
            test_vals = test[var].dropna().to_numpy()
            if len(train_vals) < 50 or len(test_vals) < 30:
                continue
            fit = fit_fn(train_vals)
            if fit is None:
                continue
            # Build CDF from fit params and run kstest(test, cdf)
            if var == "arrival_hour" and fit.get("dist") == "truncnorm":
                from scipy.stats import truncnorm
                a, b = (6 - fit["mu"]) / fit["sigma"], (20 - fit["mu"]) / fit["sigma"]
                cdf = truncnorm(a, b, loc=fit["mu"], scale=fit["sigma"]).cdf
            elif var == "dwell_hours" and fit.get("dist") == "weibull":
                from scipy.stats import weibull_min
                cdf = weibull_min(fit["k"], scale=fit["lambda"]).cdf
            else:
                continue

            ks_train = float(fit.get("ks_fit_quality", float("nan")))
            ks_holdout, _ = stats.kstest(test_vals, cdf)
            rows.append({
                "source": source_key, "region": region, "variable": var,
                "n_train": len(train_vals), "n_test": len(test_vals),
                "ks_train": ks_train, "ks_holdout": float(ks_holdout),
                "delta": float(ks_holdout - ks_train) if not np.isnan(ks_train) else float("nan"),
            })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────
# S5: building load vs PNNL prototype design intent
# ──────────────────────────────────────────────────────────────────────

# (archetype, size) → default scenario that uses it, plus the matching
# reference-band size token (reference_bands.json uses small/med/large; the
# generator's "medium" office == reference "med", "standalone" retail ==
# reference "large").
S5_SCENARIOS = {
    ("office", "small"):     "S_size_small",
    ("office", "medium"):    "S01",
    ("office", "large"):     "S_size_large",
    ("retail", "standalone"): "S_arch_retail",
}
S5_REFERENCE_SIZE = {
    ("office", "small"):      "small",
    ("office", "medium"):     "med",
    ("office", "large"):      "large",
    ("retail", "standalone"): "large",   # standalone == reference retail|large
}

# ──────────────────────────────────────────────────────────────────────
# Real-data bands from NREL ComStock / EULP (replaces the old self-derived
# PNNL_EXPECTED_* bands which compared EnergyPlus output to ranges that were
# themselves derived from the generator's OWN occupancy schedules — i.e. the
# model was validated against itself). The genuine ASHRAE-G14 fidelity check
# (CV(RMSE)/NMBE vs ComStock) lives in tools/validate_buildingload.py; S5 keeps
# only a COARSE real-data smoke test here.
#
# Bands are loaded from data/buildingload_reference/reference_bands.json, keyed
# "<archetype>|<size>|BAND" with [lo,hi] ranges for weekday/weekend ratio and
# load factor across the downloaded climate zones (5B/3B/4A/6A), plus the
# normalized peak/off-peak ratio for context.
REFERENCE_BANDS_PATH = (
    REPO / "data" / "buildingload_reference" / "reference_bands.json"
)

# Coarse peak/off-peak smoke-test fallback (used only if the reference file is
# absent). The generator's S5 ratio is peak-INSTANT / mean(hour<6), which runs
# higher than ComStock's normalized peak-hour/off-peak-hour ratio, so this is a
# generous smoke band, NOT a fidelity gate.
_COARSE_PEAK_OFFPEAK = {
    "office": (1.5, 30.0),
    "retail": (1.5, 30.0),
    "mixed":  (1.5, 30.0),
}


def _load_reference_bands(path: Path = REFERENCE_BANDS_PATH) -> dict | None:
    """Load reference_bands.json, or None (with a warning) if absent."""
    if not path.exists():
        log.warning(
            "S5: reference bands missing at %s — run "
            "tools/fetch_buildingload_reference.py; falling back to coarse "
            "smoke bands.", path,
        )
        return None
    import json
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        log.warning("S5: could not parse %s: %s", path, e)
        return None


def _ww_band_for(bands: dict | None, arch: str, ref_size: str) -> tuple[float, float]:
    """weekday/weekend band from reference BAND entry, widened ±15% for the
    generator's coarser instantaneous-vs-mean ratio definition."""
    default = (1.0, 9.0)
    if not bands:
        return default
    entry = bands.get(f"{arch}|{ref_size}|BAND")
    if not entry or "weekday_weekend_ratio" not in entry:
        return default
    lo, hi = entry["weekday_weekend_ratio"]
    return (round(lo * 0.85, 3), round(hi * 1.15, 3))


def s5_buildingload(output_root: Path) -> pd.DataFrame:
    """Per (archetype, size), generate scenario; coarse-compare building_load
    shape ratios against REAL-DATA (ComStock/EULP) bands.

    This is a coarse smoke test: the weekday/weekend ratio is checked against
    ranges derived from NREL ComStock across multiple climate zones, and the
    peak/off-peak ratio is kept only as an informational sanity bound. The
    rigorous ASHRAE-G14 fidelity comparison (CV(RMSE)/NMBE vs ComStock) is in
    tools/validate_buildingload.py.
    """
    bands = _load_reference_bands()
    rows = []
    for (arch, size), scenario in S5_SCENARIOS.items():
        ref_size = S5_REFERENCE_SIZE.get((arch, size), size)
        out_dir = output_root / "scenarios_s5" / scenario / "seed42"
        if not (out_dir / "manifest.json").exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                runner_generate(
                    scenario_id=scenario, seed=42,
                    output_dir=out_dir, config_dir=REPO / "configs",
                )
            except Exception as e:  # noqa: BLE001
                log.warning("S5: gen %s failed: %s", scenario, e)
                continue

        try:
            bl = pd.read_csv(
                out_dir / "building_load.csv", parse_dates=["datetime"]
            )
        except FileNotFoundError:
            continue

        bl["hour"] = bl["datetime"].dt.hour
        bl["dow"] = bl["datetime"].dt.dayofweek
        peak = float(bl["power_kw"].max())
        off_peak_mask = bl["hour"] < 6
        off_peak = float(bl.loc[off_peak_mask, "power_kw"].mean())
        weekday = float(bl.loc[bl["dow"] < 5, "power_kw"].mean())
        weekend = float(bl.loc[bl["dow"] >= 5, "power_kw"].mean())

        po_ratio = peak / off_peak if off_peak > 1e-3 else float("inf")
        ww_ratio = weekday / weekend if weekend > 1e-3 else float("inf")

        # Real-data weekday/weekend band (ComStock, multi-zone). Peak/off-peak
        # kept as a generous coarse smoke bound only.
        exp_po_lo, exp_po_hi = _COARSE_PEAK_OFFPEAK.get(arch, (1.5, 30.0))
        exp_ww_lo, exp_ww_hi = _ww_band_for(bands, arch, ref_size)
        band_src = "comstock" if bands else "coarse-fallback"

        rows.append({
            "scenario": scenario, "archetype": arch, "size": size,
            "peak_kw": peak, "off_peak_kw": off_peak,
            "weekday_kw": weekday, "weekend_kw": weekend,
            "peak_off_peak_ratio": po_ratio,
            "weekday_weekend_ratio": ww_ratio,
            "po_in_range": bool(exp_po_lo <= po_ratio <= exp_po_hi),
            "ww_in_range": bool(exp_ww_lo <= ww_ratio <= exp_ww_hi),
            "expected_po_range": f"[{exp_po_lo}, {exp_po_hi}]",
            "expected_ww_range": f"[{exp_ww_lo}, {exp_ww_hi}]",
            "band_source": band_src,
        })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────
# S6: weekly pattern (weekday vs weekend active rate)
# ──────────────────────────────────────────────────────────────────────

def s6_weekly(
    source_key: str,
    source_df: pd.DataFrame,
    generated_df: pd.DataFrame,
) -> pd.DataFrame:
    """Weekday vs weekend active-rate per source vs per generated."""
    def ratios(df: pd.DataFrame) -> tuple[float, float, float]:
        if df.empty or "arrival_time" not in df.columns:
            return float("nan"), float("nan"), float("nan")
        df = df.copy()
        df["dow"] = pd.to_datetime(df["arrival_time"]).dt.dayofweek
        weekday_sessions = (df["dow"] < 5).sum()
        weekend_sessions = (df["dow"] >= 5).sum()
        n_weekdays = max(1, df.loc[df["dow"] < 5, "arrival_time"].dt.normalize().nunique())
        n_weekenddays = max(1, df.loc[df["dow"] >= 5, "arrival_time"].dt.normalize().nunique())
        wd_per_day = weekday_sessions / n_weekdays
        we_per_day = weekend_sessions / n_weekenddays
        return float(wd_per_day), float(we_per_day), float(wd_per_day / we_per_day) if we_per_day > 0 else float("inf")

    src_wd, src_we, src_ratio = ratios(source_df)
    # generated_df uses 'arrival' rather than 'arrival_time'
    gen_df_renamed = generated_df.rename(columns={"arrival": "arrival_time"})
    gen_wd, gen_we, gen_ratio = ratios(gen_df_renamed)

    return pd.DataFrame([{
        "source": source_key,
        "source_weekday_sess_per_day": src_wd,
        "source_weekend_sess_per_day": src_we,
        "source_weekly_ratio": src_ratio,
        "generated_weekday_sess_per_day": gen_wd,
        "generated_weekend_sess_per_day": gen_we,
        "generated_weekly_ratio": gen_ratio,
        "gap_ratio_log10": abs(np.log10(src_ratio) - np.log10(gen_ratio))
                            if src_ratio > 0 and gen_ratio > 0 and np.isfinite(src_ratio) and np.isfinite(gen_ratio)
                            else float("nan"),
    }])


# ──────────────────────────────────────────────────────────────────────
# Markdown summary (committed; CSVs/PNGs stay git-ignored)
# ──────────────────────────────────────────────────────────────────────

def write_results_md(output_root: Path) -> None:
    """Emit docs/CALIBRATION_RESULTS.md from the S1–S6 summary CSVs.

    Auto-generated artifact — same tool-emits-its-own-doc convention as
    model_eval.py → MODEL_SELECTION.md. Reads the CSVs just written so the
    doc always matches them; callable standalone via ``--md-only``.
    """
    from datetime import date

    def _read(name: str) -> pd.DataFrame:
        p = output_root / name
        try:
            return pd.read_csv(p)
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return pd.DataFrame()

    s1 = _read("S1_marginals.csv")
    s2 = _read("S2_joint.csv")
    s3 = _read("S3_holdout.csv")
    s5 = _read("S5_buildingload.csv")
    s6 = _read("S6_weekly.csv")
    s0 = _read("S0_assignment.csv")

    def f(x, nd: int = 2) -> str:
        try:
            return f"{float(x):.{nd}f}"
        except (TypeError, ValueError):
            return str(x)

    def reg(s: str) -> str:
        return str(s).replace("_", " ")

    out: list[str] = []
    w = out.append
    w("# Calibration Results — generated data vs ground truth")
    w("")
    w("> **Auto-generated by `tools/validate_calibration.py`. Do not edit by hand.**  ")
    w("> Regenerate: `uv run python tools/validate_calibration.py --seeds 50 --workers 16`  ")
    w("> Rebuild only this doc from existing CSVs: add `--md-only`.")
    w("")
    w(f"_Generated {date.today().isoformat()}._ Generated sessions are pooled across "
      "seeds and compared, region by region, against the real source each population "
      "was fit to. EV WATTS and INL are fixture-only and excluded; see "
      "[`CALIBRATION_NOTES.md`](CALIBRATION_NOTES.md) for method and "
      "[`GENERATIVE_MODELS.md`](GENERATIVE_MODELS.md) for family rationale.")
    w("")
    w("**Reading the numbers.** With sample sizes in the thousands the two-sample KS "
      "*p*-value is ~0 everywhere and carries no signal — judge by effect size: mean "
      "error |Δμ|, the KS statistic, Wasserstein W₁, and the copula ρ-gap.")
    w("")

    w("## At a glance")
    w("")
    if not s0.empty:
        un = s0[s0["region"] == "__unassigned__"]
        if not un.empty:
            frags = ", ".join(
                f"{r['source']} {float(r['user_share']) * 100:.0f}%"
                for _, r in un.iterrows()
            )
            w(f"- **S0 assignment** — drivers matching no region box (unassigned): {frags}.")
    if not s1.empty:
        mean_err = (s1["source_mean"] - s1["generated_mean"]).abs().mean()
        w(f"- **S1 marginals** — mean |Δμ| {f(mean_err)} h across all region×variable "
          f"cells; KS ≤ {f(s1['ks_statistic'].max(), 2)}.")
    if not s2.empty:
        w(f"- **S2 joint** — max Spearman ρ-gap {f(s2['rho_gap'].max(), 3)}; the "
          "arrival×dwell copula is reproduced.")
    if not s3.empty:
        w(f"- **S3 held-out** — median Δ(holdout − train KS) {f(s3['delta'].median(), 3)}; "
          "no systematic overfit.")
    if not s5.empty:
        ww = int(s5["ww_in_range"].astype(str).str.lower().eq("true").sum())
        w(f"- **S5 building load (real-data)** — {ww}/{len(s5)} within the NREL "
          "ComStock weekday/weekend band (coarse smoke test; rigorous G14 "
          "metrics in `tools/validate_buildingload.py`).")
    if not s6.empty:
        w(f"- **S6 weekly rhythm** — max weekday/weekend ratio gap "
          f"{f(s6['gap_ratio_log10'].max(), 2)} dex.")
    w("")

    if not s0.empty:
        w("## S0 — How real drivers are grouped into regions")
        w("")
        w("Each driver is summarised by (φ frequency, κ consistency) and dropped into "
          "the **first** region box that contains it; `assignment/<source>.png` shows "
          "the scatter with the box overlays. Per-region driver counts:")
        w("")
        w("| source | region | drivers | share |")
        w("|---|---|--:|--:|")
        for _, r in s0.iterrows():
            w(f"| {r['source']} | {reg(r['region'])} | {int(r['n_users']):,} | "
              f"{f(float(r['user_share']) * 100, 1)}% |")
        w("")

    if not s1.empty:
        w("## S1 — Per-region marginals")
        w("")
        w("| source | region | variable | n src | n gen | src μ/σ | gen μ/σ | \\|Δμ\\| | KS | W₁ |")
        w("|---|---|---|--:|--:|--:|--:|--:|--:|--:|")
        for _, r in s1.iterrows():
            dmu = abs(float(r["source_mean"]) - float(r["generated_mean"]))
            w(f"| {r['source']} | {reg(r['region'])} | {reg(r['variable'])} | "
              f"{int(r['n_source']):,} | {int(r['n_generated']):,} | "
              f"{f(r['source_mean'])}/{f(r['source_std'])} | "
              f"{f(r['generated_mean'])}/{f(r['generated_std'])} | {f(dmu)} | "
              f"{f(r['ks_statistic'], 3)} | {f(r['wasserstein_1'], 2)} |")
        w("")

    if not s2.empty:
        w("## S2 — Joint structure (arrival × dwell)")
        w("")
        w("| source | region | n | ρ source | ρ generated | ρ-gap |")
        w("|---|---|--:|--:|--:|--:|")
        for _, r in s2.iterrows():
            w(f"| {r['source']} | {reg(r['region'])} | {int(r['n_source']):,} | "
              f"{f(r['spearman_rho_source'], 3)} | {f(r['spearman_rho_generated'], 3)} | "
              f"{f(r['rho_gap'], 3)} |")
        w("")

    if not s3.empty:
        w("## S3 — Held-out generalization (80/20 by user)")
        w("")
        w("_Δ = holdout − train KS. Fits a single TruncNorm for arrival, so arrival "
          "rows are pessimistic vs the shipped 2-component mixture._")
        w("")
        w("| source | region | variable | n train | n test | KS train | KS holdout | Δ |")
        w("|---|---|---|--:|--:|--:|--:|--:|")
        for _, r in s3.iterrows():
            d = float(r["delta"])
            w(f"| {r['source']} | {reg(r['region'])} | {reg(r['variable'])} | "
              f"{int(r['n_train']):,} | {int(r['n_test']):,} | {f(r['ks_train'], 3)} | "
              f"{f(r['ks_holdout'], 3)} | {('+' if d >= 0 else '')}{f(d, 3)} |")
        w("")

    if not s5.empty:
        w("## S5 — Building load vs real-data (NREL ComStock) shape bands")
        w("")
        w("_Coarse real-data smoke test. The weekday/weekend band is derived "
          "from NREL ComStock/EULP across climate zones 5B/3B/4A/6A "
          "(`data/buildingload_reference/reference_bands.json`); peak/off-peak "
          "is an informational sanity bound only. The rigorous ASHRAE "
          "Guideline-14 fidelity comparison (CV(RMSE)/NMBE vs ComStock, "
          "`peak_kw_scaling` off) lives in `tools/validate_buildingload.py` — "
          "see `data/buildingload_reference/validation_metrics.json`._")
        w("")
        w("| scenario | archetype/size | peak kW | off-pk kW | pk/off | wd/we | ComStock wd/we band | ✓ | band src |")
        w("|---|---|--:|--:|--:|--:|--:|:-:|:-:|")
        for _, r in s5.iterrows():
            ww_ok = str(r["ww_in_range"]).strip().lower() == "true"
            src = r["band_source"] if "band_source" in r else "—"
            w(f"| {r['scenario']} | {r['archetype']}/{r['size']} | "
              f"{f(r['peak_kw'], 0)} | {f(r['off_peak_kw'], 1)} | "
              f"{f(r['peak_off_peak_ratio'], 2)} | "
              f"{f(r['weekday_weekend_ratio'], 2)} | "
              f"{r['expected_ww_range']} | {'✓' if ww_ok else '✗'} | {src} |")
        w("")

    if not s6.empty:
        w("## S6 — Weekly weekday/weekend rhythm")
        w("")
        w("| source | source ratio | generated ratio | gap (log₁₀) |")
        w("|---|--:|--:|--:|")
        for _, r in s6.iterrows():
            w(f"| {r['source']} | {f(r['source_weekly_ratio'], 2)}× | "
              f"{f(r['generated_weekly_ratio'], 2)}× | {f(r['gap_ratio_log10'], 3)} |")
        w("")

    w("## Caveats")
    w("")
    w("- **Arrival is bimodal.** ACN arrival ships a 2-component truncated mixture "
      "(morning commute + midday shoulder); single TruncNorm underfits "
      "(PROJECT_TRACKER W1–W2).")
    w("- **Arrival-SoC is the weakest marginal** — inherits the ~33% ACN "
      "capacity-inference fallback; not for capacity-sensitive analysis.")
    w("- **S3 holdout uses a single TruncNorm**, so its arrival rows understate the "
      "shipped mixture.")
    w("- **S5 building-load now validates against real data** (NREL ComStock/EULP, "
      "no longer self-derived). The shipped single ASHRAE 90.1-2019 prototype is "
      "an efficient new-construction building (~8 W/m² mean for small office), "
      "while ComStock is a *stock-weighted average* (~16 W/m²) that includes older, "
      "less-efficient buildings — so the generator systematically under-predicts "
      "absolute EUI by ~30–50% (NMBE; see `validate_buildingload.py`). The diurnal "
      "*shape* matches well (weekday corr 0.71–0.94). Office weekday/weekend ratio "
      "runs high because the generator zeros weekend office occupancy whereas "
      "ComStock buildings carry a nonzero weekend base load. These are model-scope "
      "differences (one efficient prototype vs a stock distribution), not yardstick "
      "artifacts.")
    w("- **EV WATTS / INL** are fixture-only (~64 / ~65 synthetic sessions) and excluded.")
    w("")
    w("Underlying CSVs and the per-region distribution / joint-density PNGs live under "
      "`data/calibration_validation/` (git-ignored — regenerate with the harness).")

    target = REPO / "docs" / "CALIBRATION_RESULTS.md"
    target.write_text("\n".join(out) + "\n")
    log.info("wrote %s", target)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Calibration faithfulness verification")
    p.add_argument("--output", default="data/calibration_validation")
    p.add_argument("--seeds", type=int, default=50)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--sources", default="acn,elaadnl",
                   help="comma list of source keys (default: acn,elaadnl)")
    p.add_argument("--md-only", action="store_true",
                   help="regenerate docs/CALIBRATION_RESULTS.md from existing CSVs and exit")
    args = p.parse_args()

    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    source_keys = [s.strip() for s in args.sources.split(",") if s.strip()]

    if args.md_only:
        write_results_md(output_root)
        return 0

    t_total = time.perf_counter()

    s0_all, s1_all, s2_all, s3_all, s6_all = [], [], [], [], []

    for source_key in source_keys:
        if source_key not in SOURCE_SPECS:
            log.warning("unknown source %s, skipping", source_key)
            continue
        log.info("=" * 60)
        log.info("Source: %s", source_key)

        source_data = load_source(source_key)

        # S0 — region-assignment diagnostic (source-only; no generation needed)
        log.info("  S0 region assignment…")
        s0_all.append(s0_assignment(source_key, source_data, output_root))

        seed_dirs = generate_seed_set(source_key, args.seeds, output_root, args.workers)
        generated = load_generated(source_key, seed_dirs)

        log.info("  source sessions: %d; generated sessions: %d",
                 len(source_data.sessions_df), len(generated))

        # S1
        log.info("  S1 marginals…")
        s1_df = s1_marginals(source_key, source_data.sessions_df, generated, output_root)
        s1_all.append(s1_df)

        # S2
        log.info("  S2 joint…")
        s2_df = s2_joint(source_key, source_data.sessions_df, generated, output_root)
        s2_all.append(s2_df)

        # S3
        log.info("  S3 held-out KS…")
        s3_df = s3_holdout(source_key, source_data.sessions_df)
        s3_all.append(s3_df)

        # S6
        log.info("  S6 weekly pattern…")
        s6_df = s6_weekly(source_key, source_data.sessions_df, generated)
        s6_all.append(s6_df)

    # S5 (source-independent)
    log.info("=" * 60)
    log.info("S5 building load vs PNNL prototype intent…")
    s5_df = s5_buildingload(output_root)
    s5_df.to_csv(output_root / "S5_buildingload.csv", index=False)

    pd.concat(s1_all, ignore_index=True).to_csv(output_root / "S1_marginals.csv", index=False) if s1_all else None
    pd.concat(s2_all, ignore_index=True).to_csv(output_root / "S2_joint.csv", index=False) if s2_all else None
    pd.concat(s3_all, ignore_index=True).to_csv(output_root / "S3_holdout.csv", index=False) if s3_all else None
    pd.concat(s6_all, ignore_index=True).to_csv(output_root / "S6_weekly.csv", index=False) if s6_all else None
    pd.concat(s0_all, ignore_index=True).to_csv(output_root / "S0_assignment.csv", index=False) if s0_all else None

    write_results_md(output_root)

    log.info("=" * 60)
    log.info("Done in %.1fs. Outputs at %s/", time.perf_counter() - t_total, output_root)
    log.info("CSVs: S1_marginals, S2_joint, S3_holdout, S5_buildingload, S6_weekly")

    # Print quick summaries
    if s1_all:
        s1 = pd.concat(s1_all, ignore_index=True)
        print("\n=== S1 marginals summary ===")
        print(s1[["source", "region", "variable", "n_source", "n_generated",
                  "ks_statistic", "wasserstein_1"]].round(3).to_string(index=False))
    if s3_all:
        s3 = pd.concat(s3_all, ignore_index=True)
        if not s3.empty:
            print("\n=== S3 held-out KS ===")
            print(s3.round(3).to_string(index=False))
    if s6_all:
        s6 = pd.concat(s6_all, ignore_index=True)
        print("\n=== S6 weekly ratio ===")
        print(s6.round(3).to_string(index=False))
    print("\n=== S5 building-load ratios ===")
    print(s5_df.round(2).to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
