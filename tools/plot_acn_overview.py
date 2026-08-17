#!/usr/bin/env python3
"""Per-site overview figure for an ACN-Data session CSV (tools/acn_json_to_csv.py).

Six panels on one sheet, identical across sites so figures can be compared:

  1. kWh delivered (metered)          4. arrival hour, site-local
  2. kWh requested (driver-entered)   5. departure hour, site-local
  3. dwell hours                      6. delivered vs requested

Distribution panels are split by whether the session carries a ``userID``;
anonymous plug-ins behave very differently from identified drivers and at
Office001 they are the majority of sessions. ``--identified-only`` drops the
anonymous rows entirely, which is the population the calibrator actually fits
(per-driver phi/kappa need a stable userID). Axis ranges are recomputed from the
retained rows, so read values off the annotations rather than comparing axes.

Usage
-----
  uv run python tools/plot_acn_overview.py data/calibration/acn_csv/jpl_2019_2021.csv
  uv run python tools/plot_acn_overview.py data/calibration/acn_csv/*.csv
  uv run python tools/plot_acn_overview.py --identified-only data/calibration/acn_csv/*.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ID_COLUMNS = ["sessionID", "_id", "siteID", "stationID", "spaceID", "clusterID",
              "userID"]

C_ID = "#2a6f97"       # identified drivers
C_ANON = "#e8a33d"     # anonymous plug-ins
C_ACCENT = "#b23a48"

DWELL_CLIP_H = 24.0    # dwell has a long thin tail (max 214 h at Caltech)


def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={c: str for c in ID_COLUMNS})
    df["anonymous"] = df["userID"].isna()
    return df


def _hist(ax, df: pd.DataFrame, col: str, bins, xlabel: str, title: str,
          clip: float | None = None, clip_note: str = "beyond axis",
          extra: str = "", legend: bool = False) -> None:
    d = df[df[col].notna()]
    v = d[col]
    n_over = int((v >= clip).sum()) if clip is not None else 0
    ident = d.loc[~d["anonymous"], col]
    anon = d.loc[d["anonymous"], col]

    if len(anon) and len(ident):
        ax.hist([ident, anon], bins=bins, stacked=True, color=[C_ID, C_ANON],
                label=[f"identified (n={len(ident):,})",
                       f"anonymous (n={len(anon):,})"], edgecolor="none")
    else:
        ax.hist(v, bins=bins, color=C_ID, edgecolor="none",
                label=f"n={len(v):,}")
    ax.axvline(v.median(), color=C_ACCENT, ls="--", lw=1.5)
    ax.axvline(v.mean(), color="black", ls=":", lw=1.5)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel("sessions", fontsize=9)
    sub = f"median {v.median():.2f}  ·  mean {v.mean():.2f}"
    if n_over:
        sub += f"  ·  {n_over:,} {clip_note}"
    if extra:
        sub += f"\n{extra}"
    ax.set_title(f"{title}\n{sub}", fontsize=10, loc="left")
    if legend:
        ax.legend(fontsize=8, frameon=False)
    ax.set_xlim(bins[0], bins[-1])


def plot_site(df: pd.DataFrame, site: str, out: Path,
              dropped_anon: int | None = None) -> dict:
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 8.6))
    n_anon = int(df["anonymous"].sum())
    span = (f"{df['derived.arrivalLocal'].min()[:10]} → "
            f"{df['derived.arrivalLocal'].max()[:10]} local")
    if dropped_anon is None:
        who = f"{len(df):,} sessions; {len(df) - n_anon:,} identified, {n_anon:,} anonymous"
    else:
        who = (f"identified drivers only — {len(df):,} sessions from "
               f"{df['userID'].nunique():,} drivers, "
               f"{dropped_anon:,} anonymous dropped")
    fig.suptitle(f"ACN-Data {site} 2019–2021 — session overview",
                 fontsize=13.5, fontweight="bold", y=0.988)
    fig.text(0.5, 0.951, f"{who}; {span}", ha="center", fontsize=10.5,
             color="#333333")

    # 1. delivered
    _hist(axes[0, 0], df, "kWhDelivered",
          np.arange(0, np.ceil(df["kWhDelivered"].quantile(0.995)) + 1, 1.0),
          "kWh delivered (metered)", "1  Energy delivered", legend=True)

    # 2. requested. kWhRequested = milesRequested x WhPerMile, so a mistyped
    # efficiency inflates it without bound; flag the share outside any real EV.
    req = df["userInputs.kWhRequested"]
    wpm = df.loc[req.notna(), "userInputs.WhPerMile"]
    bad = int(((wpm < 200) | (wpm > 600)).sum())
    note = ""
    if bad:
        note = (f"{bad:,} of {int(req.notna().sum()):,} derive from Wh/mi outside "
                f"200–600 (implausible)")
    _hist(axes[0, 1], df, "userInputs.kWhRequested",
          np.arange(0, np.ceil(req.quantile(0.995)) + 2, 2.0),
          "kWh requested (driver-entered)",
          f"2  Energy requested  ({req.isna().sum():,} missing)", extra=note)

    # 3. dwell
    dw = df.copy()
    dw["derived.dwellHours"] = dw["derived.dwellHours"].clip(upper=DWELL_CLIP_H)
    _hist(axes[0, 2], dw, "derived.dwellHours", np.arange(0, DWELL_CLIP_H + 0.5, 0.5),
          f"dwell hours (clipped at {DWELL_CLIP_H:.0f} h)", "3  Dwell time",
          clip=DWELL_CLIP_H, clip_note=f"over {DWELL_CLIP_H:.0f} h")

    # 4/5. arrival + departure clock hour
    hb = np.arange(0, 24.5, 0.5)
    _hist(axes[1, 0], df, "derived.arrivalHour", hb,
          "arrival hour, site-local", "4  Arrival time (local)")
    _hist(axes[1, 1], df, "derived.departureHour", hb,
          "departure hour, site-local", "5  Departure time (local)")
    for a in (axes[1, 0], axes[1, 1]):
        a.set_xticks(np.arange(0, 25, 3))

    # 6. delivered vs requested
    ax = axes[1, 2]
    r = df.dropna(subset=["userInputs.kWhRequested"])
    r = r[r["userInputs.kWhRequested"] > 0]
    ratio = float("nan")
    if len(r):
        ax.scatter(r["userInputs.kWhRequested"], r["kWhDelivered"], s=5,
                   alpha=0.15, color=C_ID, edgecolors="none")
        lim = float(max(r["userInputs.kWhRequested"].quantile(0.995),
                        r["kWhDelivered"].quantile(0.995))) * 1.05
        ratio = r["kWhDelivered"].sum() / r["userInputs.kWhRequested"].sum()
        ax.plot([0, lim], [0, lim], color="black", lw=1.1, ls="--",
                label="delivered = requested")
        ax.plot([0, lim], [0, lim * ratio], color=C_ACCENT, lw=1.8,
                label=f"Σdelivered/Σrequested = {ratio:.2f}")
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax.set_xlabel("kWh requested", fontsize=9)
    ax.set_ylabel("kWh delivered", fontsize=9)
    ax.set_title(f"6  Delivered vs requested  (n = {len(r):,})", fontsize=10,
                 loc="left")

    for a in axes.flat:
        a.spines[["top", "right"]].set_visible(False)
        a.grid(axis="y", alpha=0.25, lw=0.6)
    fig.tight_layout(rect=(0, 0, 1, 0.935))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)

    return {
        "n": len(df), "anon": n_anon,
        "kwh_delivered_mean": df["kWhDelivered"].mean(),
        "kwh_requested_mean": req.mean(),
        "dwell_median": df["derived.dwellHours"].median(),
        "arrival_median": df["derived.arrivalHour"].median(),
        "departure_median": df["derived.departureHour"].median(),
        "ratio": ratio,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_paths", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--identified-only", action="store_true",
                    help="drop sessions with no userID (anonymous plug-ins)")
    args = ap.parse_args(argv)

    for cp in args.csv_paths:
        df = load(cp)
        site = cp.stem.split("_")[0]
        dropped = None
        suffix = "_overview"
        if args.identified_only:
            dropped = int(df["anonymous"].sum())
            df = df[~df["anonymous"]].reset_index(drop=True)
            suffix = "_overview_identified"
        out = (args.out_dir or cp.parent) / f"{cp.stem}{suffix}.png"
        s = plot_site(df, site, out, dropped_anon=dropped)
        print(f"wrote {out}")
        print(f"  n={s['n']:,} (anonymous {s['anon']:,})  "
              f"delivered mean={s['kwh_delivered_mean']:.2f}  "
              f"requested mean={s['kwh_requested_mean']:.2f}  "
              f"dwell median={s['dwell_median']:.2f} h  "
              f"arrival median={s['arrival_median']:.2f} h  "
              f"departure median={s['departure_median']:.2f} h  "
              f"ratio={s['ratio']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
