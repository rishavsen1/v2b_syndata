"""Round-trip fit check: ACN source distributions vs generated synthetic sessions.

For one ACN site, overlays the ground-truth session distributions (the same
feature pipeline the calibrator consumes — anonymous ``userID`` rows already
excluded by ``AcnSource.fetch_sessions``) against a generated cohort produced
from the population calibrated on that site, and reports a two-sample KS
statistic per marginal.

Panels mirror ``tools/plot_acn_overview.py`` so the figure can be read next to
``data/calibration/acn_csv/<site>_2019_2021_overview.png``:

  (a) arrival hour   (b) departure hour   (c) dwell hours
  (d) delivered energy (kWh)   (e) departure-SoC requirement (%)

Delivered energy for the generated cohort is reconstructed as
``(required_soc_at_depart - arrival_soc)/100 * battery_capacity_kwh`` joined on
``car_id``, which is the quantity the sampler actually controls.

Run:
  uv run python -m v2b_syndata.cli generate --scenario S_acn_caltech --seed 7 \
      --output-dir /tmp/gen_caltech --override ev_fleet.ev_count=400 \
      --override charging_infra.charger_count=120 --override sim_window.mode=full_year
  uv run python tools/acn_roundtrip_fit.py --site caltech --gen-dir /tmp/gen_caltech

Writes <out-dir>/acn_roundtrip_<site>.png and prints a KS table (also written
as acn_roundtrip_<site>.csv).
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import scipy.stats as st

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from v2b_syndata.calibration.battery_inference import (  # noqa: E402
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.sources import CALIBRATION_SOURCES  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SOC_SEED = 20260613  # same prior stream the calibrator uses
DWELL_LO, DWELL_HI = 0.5, 24.0
SRC_C, GEN_C = "#555555", "#d8853b"


def _source_frame(site: str) -> pd.DataFrame:
    """Ground-truth per-session features for one ACN site (anonymous excluded)."""
    src = CALIBRATION_SOURCES["acn_data"]()
    sess = src.fetch_sessions({
        "sites": (site,),
        "year_start": 2019,
        "year_end": 2021,
        "cache_dir": REPO / "data/calibration/acn_cache",
    })
    rng = np.random.default_rng(SOC_SEED)
    rows = []
    for s in sess:
        cap, _ = infer_capacity(s)
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        depart = None
        if soc is not None and s.kwh_delivered is not None and cap > 0:
            d = min(1 - 1e-6, soc + float(s.kwh_delivered) / float(cap))
            depart = d * 100 if d > soc else None
        rows.append({
            "arrival_hour": s.arrival_hour,
            "departure_hour": (s.arrival_hour + s.dwell_hours) % 24.0,
            "dwell_hours": s.dwell_hours,
            "kwh": s.kwh_delivered,
            "soc_depart": depart,
        })
    return pd.DataFrame(rows)


def _generated_frame(gen_dir: Path) -> pd.DataFrame:
    """Per-session features from a generated output dir (native schema)."""
    g = pd.read_csv(gen_dir / "sessions.csv")
    cars = pd.read_csv(gen_dir / "cars.csv")
    cap_col = next(
        (c for c in cars.columns if "capacity" in c.lower() or c == "battery_kwh"), None
    )
    if cap_col is None:
        raise SystemExit(f"no battery-capacity column in {gen_dir/'cars.csv'}")
    cap = cars.set_index("car_id")[cap_col]
    arrival = pd.to_datetime(g["arrival"])
    departure = pd.to_datetime(g["departure"])
    soc_gap = (g["required_soc_at_depart"] - g["arrival_soc"]) / 100.0
    return pd.DataFrame({
        "arrival_hour": arrival.dt.hour + arrival.dt.minute / 60.0,
        "departure_hour": departure.dt.hour + departure.dt.minute / 60.0,
        "dwell_hours": g["duration_sec"] / 3600.0,
        "kwh": soc_gap * g["car_id"].map(cap).to_numpy(),
        "soc_depart": g["required_soc_at_depart"],
    })


PANELS = [
    ("arrival_hour", "(a) Arrival hour", "hour of day", 48, (0, 24)),
    ("departure_hour", "(b) Departure hour", "hour of day", 48, (0, 24)),
    ("dwell_hours", "(c) Dwell", "hours", 48, (0, 24)),
    ("kwh", "(d) Energy delivered", "kWh", 40, (0, 60)),
    ("soc_depart", "(e) Departure-SoC requirement", "% SoC at departure", 40, (0, 100)),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--site", required=True, choices=["caltech", "jpl", "office001"])
    p.add_argument("--gen-dir", required=True, type=Path)
    p.add_argument("--out-dir", type=Path, default=REPO / "docs/experiments")
    args = p.parse_args(argv)

    src = _source_frame(args.site)
    gen = _generated_frame(args.gen_dir)
    # dwell filter applied to both sides identically
    for df in (src, gen):
        df.loc[(df["dwell_hours"] < DWELL_LO) | (df["dwell_hours"] > DWELL_HI),
               "dwell_hours"] = np.nan

    fig, axes = plt.subplots(2, 3, figsize=(16.5, 8.6))
    flat = axes.ravel()
    stats_rows = []
    for ax, (col, title, xlabel, bins, rng_) in zip(flat, PANELS):
        s = src[col].dropna().to_numpy()
        gv = gen[col].dropna().to_numpy()
        ks = st.ks_2samp(s, gv)
        stats_rows.append({
            "site": args.site, "quantity": col,
            "n_source": len(s), "n_generated": len(gv),
            "source_mean": float(np.mean(s)), "generated_mean": float(np.mean(gv)),
            "source_median": float(np.median(s)), "generated_median": float(np.median(gv)),
            "ks_statistic": float(ks.statistic), "ks_pvalue": float(ks.pvalue),
        })
        ax.hist(s, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
                label=f"source (n={len(s):,})")
        ax.hist(gv, bins=bins, range=rng_, density=True, histtype="step", color=GEN_C,
                lw=2.4, label=f"generated (n={len(gv):,})")
        ax.set_title(f"{title}\nKS = {ks.statistic:.3f}   "
                     f"mean {np.mean(s):.2f} vs {np.mean(gv):.2f}",
                     fontsize=10, loc="left")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("density")
        ax.legend(fontsize=8)
    flat[-1].axis("off")

    fig.suptitle(
        f"ACN {args.site} 2019–2021 (anonymous userID excluded) vs generated "
        f"S_acn_{args.site} — round-trip fit",
        fontsize=13,
    )
    fig.tight_layout()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    png = args.out_dir / f"acn_roundtrip_{args.site}.png"
    fig.savefig(png, dpi=120, bbox_inches="tight")

    table = pd.DataFrame(stats_rows)
    csv = args.out_dir / f"acn_roundtrip_{args.site}.csv"
    table.to_csv(csv, index=False)
    print(table.to_string(index=False))
    print(f"\nsaved {png}\nsaved {csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
