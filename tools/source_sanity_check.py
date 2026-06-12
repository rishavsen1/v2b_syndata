#!/usr/bin/env python
"""Source-data sanity check (deliverable 1c).

For each real calibration source cohort, summarize and plot the arrival-hour
and departure-hour (= arrival + dwell, wrapped to 24h) distributions, plus
dwell. Flags cohorts whose central arrival/departure clock-hours fall outside
the normal workplace-charging window — a quick "does the ground-truth data
look sane?" gate before we trust it as a comparison target.

Reuses the harness's load_source() so timezone handling is identical to
calibration (ACN → Pacific; ElaadNL → native UTC-labelled local, by design).

Usage:
    uv run python tools/source_sanity_check.py \
        --output data/calibration_validation/source_sanity \
        --sources acn,acn_caltech,acn_jpl,acn_office001,elaadnl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env", override=False)

# Reuse the harness loader so tz handling matches calibration exactly.
from tools.validate_calibration import load_source  # noqa: E402

# Normal workplace-charging windows (local clock hour).
ARRIVAL_OK = (5.0, 12.0)     # arrivals should center in the morning commute
DEPARTURE_OK = (13.0, 22.0)  # departures should center in afternoon/evening


def summarize(df: pd.DataFrame, source_key: str) -> dict:
    arr = df["arrival_hour"].to_numpy()
    dep = (df["arrival_hour"] + df["dwell_hours"]).to_numpy() % 24.0
    dwell = df["dwell_hours"].to_numpy()

    def pct(a, q):
        return float(np.percentile(a, q))

    arr_med = pct(arr, 50)
    dep_med = pct(dep, 50)
    arr_ok = ARRIVAL_OK[0] <= arr_med <= ARRIVAL_OK[1]
    dep_ok = DEPARTURE_OK[0] <= dep_med <= DEPARTURE_OK[1]
    frac_overnight = float(np.mean(dwell > 16.0))

    return {
        "source": source_key,
        "n_sessions": int(len(df)),
        "n_users": int(df["user_id"].nunique()),
        "arrival_p10": round(pct(arr, 10), 2),
        "arrival_median": round(arr_med, 2),
        "arrival_p90": round(pct(arr, 90), 2),
        "departure_p10": round(pct(dep, 10), 2),
        "departure_median": round(dep_med, 2),
        "departure_p90": round(pct(dep, 90), 2),
        "dwell_median_h": round(pct(dwell, 50), 2),
        "dwell_p90_h": round(pct(dwell, 90), 2),
        "frac_dwell_gt_16h": round(frac_overnight, 4),
        "arrival_window_ok": arr_ok,
        "departure_window_ok": dep_ok,
        "VERDICT": "OK" if (arr_ok and dep_ok) else "CHECK",
    }


def plot_cohort(df: pd.DataFrame, source_key: str, out_dir: Path) -> Path:
    arr = df["arrival_hour"].to_numpy()
    dep = (df["arrival_hour"] + df["dwell_hours"]).to_numpy() % 24.0
    dwell = np.clip(df["dwell_hours"].to_numpy(), 0, 24)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    bins = np.arange(0, 25, 1)
    axes[0].hist(arr, bins=bins, color="#2c7fb8", edgecolor="white")
    axes[0].axvspan(*ARRIVAL_OK, color="green", alpha=0.08)
    axes[0].set_title(f"{source_key} — arrival hour")
    axes[0].set_xlabel("clock hour (local)")
    axes[0].set_xticks(range(0, 25, 2))

    axes[1].hist(dep, bins=bins, color="#d95f0e", edgecolor="white")
    axes[1].axvspan(*DEPARTURE_OK, color="green", alpha=0.08)
    axes[1].set_title(f"{source_key} — departure hour")
    axes[1].set_xlabel("clock hour (local)")
    axes[1].set_xticks(range(0, 25, 2))

    axes[2].hist(dwell, bins=np.arange(0, 25, 0.5), color="#756bb1", edgecolor="white")
    axes[2].set_title(f"{source_key} — dwell (h)")
    axes[2].set_xlabel("hours")

    fig.tight_layout()
    out = out_dir / f"{source_key}_arr_dep_dwell.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Source-data arrival/departure sanity check")
    p.add_argument("--output", default="data/calibration_validation/source_sanity")
    p.add_argument("--sources", default="acn,acn_caltech,acn_jpl,acn_office001,elaadnl")
    args = p.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = [s.strip() for s in args.sources.split(",") if s.strip()]

    rows = []
    for key in keys:
        print(f"[sanity] loading {key} …", flush=True)
        sd = load_source(key)
        df = sd.sessions_df
        rows.append(summarize(df, key))
        png = plot_cohort(df, key, out_dir)
        print(f"[sanity]   {key}: {len(df)} sessions → {png}", flush=True)

    summary = pd.DataFrame(rows)
    csv = out_dir / "source_sanity_summary.csv"
    summary.to_csv(csv, index=False)
    print("\n=== SOURCE SANITY SUMMARY ===")
    print(summary.to_string(index=False))
    print(f"\nwritten: {csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
