#!/usr/bin/env python3
"""Plot a per-session energy column from an ACN-Data CSV (tools/data_prep/acn_json_to_csv.py).

One standalone 4-panel figure per column, with identical panel layout across
columns so two figures can be read side by side:

  (a) marginal distribution on fine bins, split by whether the session carries a
      userID, annotated with the share of values landing on a whole kWh (this is
      what separates the driver-entered request from the metered delivery);
  (b) ECDF on a log axis, where the ~2 orders of magnitude of spread is legible;
  (c) monthly total and session count, dominated by the COVID campus closure;
  (d) distribution by arrival hour, in 2-hour local-time bins.

Usage
-----
  uv run python tools/data_prep/plot_acn_kwh.py data/calibration/acn_csv/caltech_2019_2021.csv
  uv run python tools/data_prep/plot_acn_kwh.py <csv> --columns kWhDelivered
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
DEFAULT_COLUMNS = ["kWhDelivered", "userInputs.kWhRequested"]

C_ID = "#2a6f97"       # identified drivers
C_ANON = "#e8a33d"     # anonymous plug-ins
C_ACCENT = "#b23a48"

LABELS = {
    "kWhDelivered": "kWh delivered (metered)",
    "userInputs.kWhRequested": "kWh requested (driver-entered)",
}


def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        csv_path,
        dtype={c: str for c in ID_COLUMNS},
        parse_dates=["derived.arrivalLocal"],
    )
    df["anonymous"] = df["userID"].isna()
    return df


def plot_column(df: pd.DataFrame, col: str, site: str, out: Path) -> dict:
    label = LABELS.get(col, col)
    d = df[df[col].notna()].copy()
    v = d[col]
    ident = d.loc[~d["anonymous"], col]
    anon = d.loc[d["anonymous"], col]
    # Share of values on an exact whole kWh — near 0 for a meter reading, high
    # for a driver-entered request derived from a round mileage.
    round_share = float(np.isclose(v % 1.0, 0.0).mean())

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9))
    fig.suptitle(
        f"ACN-Data {site} — {label}\n"
        f"n = {len(v):,} sessions with a value "
        f"({df[col].isna().sum():,} missing)  ·  total {v.sum():,.0f} kWh  ·  "
        f"mean {v.mean():.2f}  ·  median {v.median():.2f}  ·  max {v.max():.1f}",
        fontsize=13, fontweight="bold", y=0.985,
    )

    # ---------------------------------------------------------------- (a)
    ax = axes[0, 0]
    top = float(np.ceil(v.quantile(0.995)))
    bins = np.arange(0, top + 0.5, 0.5)
    if len(anon) and len(ident):
        ax.hist([ident, anon], bins=bins, stacked=True, color=[C_ID, C_ANON],
                label=[f"identified driver (n={len(ident):,})",
                       f"anonymous, no userID (n={len(anon):,})"],
                edgecolor="none")
    else:
        ax.hist(v, bins=bins, color=C_ID, edgecolor="none",
                label=f"all sessions with a value (n={len(v):,})")
    ax.axvline(v.median(), color=C_ACCENT, ls="--", lw=1.6,
               label=f"median {v.median():.2f} kWh")
    ax.axvline(v.mean(), color="black", ls=":", lw=1.6,
               label=f"mean {v.mean():.2f} kWh")
    ax.set_xlabel(f"{label}  (0.5 kWh bins, clipped at p99.5)")
    ax.set_ylabel("sessions")
    ax.set_title("(a) Marginal distribution", fontsize=11, loc="left")
    ax.legend(fontsize=8.5, frameon=False)
    ax.set_xlim(0, top)
    ax.text(0.985, 0.62, f"{round_share:.0%} of values sit on\nan exact whole kWh",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            color=C_ACCENT if round_share > 0.2 else "grey",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="lightgrey"))

    # ---------------------------------------------------------------- (b)
    ax = axes[0, 1]
    series = [(v, "black", "all with a value")]
    if len(anon) and len(ident):
        series += [(ident, C_ID, "identified"), (anon, C_ANON, "anonymous")]
    for s_, color, lab in series:
        s = np.sort(s_[s_ > 0].to_numpy())
        ax.plot(s, np.arange(1, len(s) + 1) / len(s), color=color, lw=1.8,
                label=f"{lab} (median {np.median(s):.2f})")
    ax.set_xscale("log")
    for q in (0.5, 0.95):
        ax.axhline(q, color="grey", lw=0.7, ls=":")
        ax.text(0.985, q - 0.035, f"p{int(q * 100)} = {v.quantile(q):.1f} kWh",
                fontsize=8, color="grey", ha="right",
                transform=ax.get_yaxis_transform())
    ax.set_xlabel(f"{label}  (log scale)")
    ax.set_ylabel("cumulative fraction of sessions")
    ax.set_title("(b) ECDF", fontsize=11, loc="left")
    ax.legend(fontsize=8.5, frameon=False, loc="lower right")

    # ---------------------------------------------------------------- (c)
    ax = axes[1, 0]
    m = d.set_index("derived.arrivalLocal")[col].resample("MS").agg(["sum", "size"])
    ax.bar(m.index, m["sum"], width=24, color=C_ID, label="kWh")
    ax.set_ylabel(f"{label}, monthly total", color=C_ID, fontsize=9.5)
    ax.tick_params(axis="y", labelcolor=C_ID)
    ax.set_xlabel("month (site-local arrival time)")
    ax2 = ax.twinx()
    ax2.plot(m.index, m["size"], color=C_ACCENT, lw=1.8, marker="o", ms=3)
    ax2.set_ylabel("sessions per month", color=C_ACCENT, fontsize=9.5)
    ax2.tick_params(axis="y", labelcolor=C_ACCENT)
    zero = m.index[m["size"] == 0]
    if len(zero):
        ax.axvspan(zero.min() - pd.Timedelta(days=15),
                   zero.max() + pd.Timedelta(days=15), color="grey", alpha=0.25)
        ax.text(zero.min(), m["sum"].max() * 0.9,
                f"  no sessions\n  {zero.min():%b}–{zero.max():%b %Y}",
                fontsize=8.5, va="top")
    ax.set_title("(c) Monthly total and session count", fontsize=11, loc="left")

    # ---------------------------------------------------------------- (d)
    ax = axes[1, 1]
    edges = np.arange(0, 25, 2)
    d["hour_bin"] = pd.cut(d["derived.arrivalHour"], bins=edges, right=False)
    groups, labels_, counts = [], [], []
    for interval, g in d.groupby("hour_bin", observed=True):
        if len(g) >= 20:
            groups.append(g[col].to_numpy())
            labels_.append(f"{int(interval.left):02d}")
            counts.append(len(g))
    bp = ax.boxplot(groups, tick_labels=labels_, showfliers=False,
                    patch_artist=True, medianprops=dict(color=C_ACCENT, lw=1.6),
                    widths=0.65)
    for patch in bp["boxes"]:
        patch.set_facecolor(C_ID)
        patch.set_alpha(0.55)
        patch.set_edgecolor(C_ID)
    for x, n in enumerate(counts, start=1):
        ax.text(x, ax.get_ylim()[1] * 0.97, f"{n:,}", ha="center", va="top",
                fontsize=7, color="grey", rotation=90)
    ax.set_xlabel("arrival hour, site-local (2-hour bins, start hour shown)")
    ax.set_ylabel(label, fontsize=9.5)
    ax.set_title("(d) By arrival time  (bins with n ≥ 20; grey = n)",
                 fontsize=11, loc="left")

    for a in axes.flat:
        a.spines[["top", "right"]].set_visible(False)
        a.grid(axis="y", alpha=0.25, lw=0.6)
    axes[1, 0].spines["right"].set_visible(True)

    fig.tight_layout(rect=(0, 0, 1, 0.945))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)

    return {"n": len(v), "missing": int(df[col].isna().sum()), "total": v.sum(),
            "mean": v.mean(), "median": v.median(), "max": v.max(),
            "round_share": round_share}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--columns", nargs="+", default=DEFAULT_COLUMNS)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    df = load(args.csv_path)
    site = args.csv_path.stem.split("_")[0]
    out_dir = args.out_dir or args.csv_path.parent

    for col in args.columns:
        if col not in df.columns:
            raise SystemExit(f"column {col!r} not in {args.csv_path}")
        slug = col.replace(".", "_")
        out = out_dir / f"{args.csv_path.stem}_{slug}.png"
        s = plot_column(df, col, site, out)
        print(f"wrote {out}")
        print(f"  n={s['n']:,} (missing {s['missing']:,})  total={s['total']:,.0f} kWh  "
              f"mean={s['mean']:.2f}  median={s['median']:.2f}  max={s['max']:.1f}  "
              f"whole-kWh share={s['round_share']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
