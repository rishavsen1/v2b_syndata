"""Campus-tree overview: pooled generated session distributions vs ACN source.

Streams every ``sessions_soc.csv`` under a building-major campus tree
(``<root>/b*/<MONTH>/<sample>/``) and renders a 2x3 panel figure in the style
of ``data/calibration/acn_csv/<site>_*_overview.png``, overlaying the ACN
source site the campus populations were calibrated from (anonymous userIDs
excluded, same-local-day sessions only — the calibration cohort).

Panels:
  1 energy per session (kWh, from SoC delta x capacity)   vs source kWhDelivered
  2 arrival hour                                          vs source
  3 departure hour                                        vs source
  4 dwell (h)                                             vs source
  5 sessions per car-month (generated only; source is not per-month comparable)
  6 per-building session count + energy table (generated only)

Run:
  uv run python tools/campus/campus_overview.py data/output/campus_base \
      --site jpl --out docs/experiments/campus_base_overview.png \
      [--max-units-per-building 100]
"""
from __future__ import annotations

import argparse
import glob
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import scipy.stats as st

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC_C, GEN_C = "#555555", "#d8853b"


def _source_arrays(site: str):
    from v2b_syndata.calibration.sources import CALIBRATION_SOURCES
    src = CALIBRATION_SOURCES["acn_data"]()
    sess = src.fetch_sessions({
        "sites": (site,), "year_start": 2019, "year_end": 2021,
        "cache_dir": REPO / "data/calibration/acn_cache",
    })
    arr = np.array([s.arrival_hour for s in sess])
    dw = np.array([s.dwell_hours for s in sess])
    kwh = np.array([s.kwh_delivered for s in sess])
    dep = (arr + dw) % 24.0
    return arr, dep, dw, kwh


def _load_generated(root: Path, max_units: int | None):
    rows = []
    per_building = {}
    for bdir in sorted(root.glob("b*"), key=lambda p: int(p.name[1:])):
        cars_cache: dict[str, pd.Series] = {}
        files = sorted(glob.glob(str(bdir / "*" / "*" / "sessions_soc.csv")))
        if max_units:
            files = files[:max_units]
        n_sess = 0
        energy = 0.0
        for f in files:
            unit = Path(f).parent
            g = pd.read_csv(f, usecols=["car_id", "arrival", "departure",
                                        "arrival_soc", "departure_soc"])
            ckey = str(unit)
            if ckey not in cars_cache:
                cars_cache[ckey] = pd.read_csv(unit / "cars.csv").set_index("car_id")["capacity_kwh"]
            cap = g["car_id"].map(cars_cache[ckey])
            a = pd.to_datetime(g["arrival"]); d = pd.to_datetime(g["departure"])
            kwh = (g["departure_soc"] - g["arrival_soc"]) / 100.0 * cap
            rows.append(pd.DataFrame({
                "b": bdir.name,
                "arr_h": a.dt.hour + a.dt.minute / 60.0,
                "dep_h": d.dt.hour + d.dt.minute / 60.0,
                "dwell": (d - a).dt.total_seconds() / 3600.0,
                "kwh": kwh,
                "car": g["car_id"],
                "month": a.dt.to_period("M").astype(str),
                "unit": ckey,
            }))
            n_sess += len(g)
            energy += float(kwh.sum())
        per_building[bdir.name] = {"units": len(files), "sessions": n_sess,
                                   "mwh": energy / 1000.0}
    return pd.concat(rows, ignore_index=True), per_building


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--site", default="jpl", choices=["caltech", "jpl", "office001"])
    p.add_argument("--out", type=Path, default=REPO / "docs/experiments/campus_base_overview.png")
    p.add_argument("--max-units-per-building", type=int, default=None)
    args = p.parse_args(argv)

    sa, sdep, sdw, skwh = _source_arrays(args.site)
    g, per_b = _load_generated(args.root, args.max_units_per_building)
    n_units = sum(v["units"] for v in per_b.values())

    fig, ax = plt.subplots(2, 3, figsize=(16.5, 8.6))

    def overlay(a, sx, gx, bins, rng_, title, xlabel):
        ks = st.ks_2samp(sx, gx).statistic
        a.hist(sx, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
               label=f"ACN {args.site} source (n={len(sx):,})")
        a.hist(gx, bins=bins, range=rng_, density=True, histtype="step",
               color=GEN_C, lw=2.2, label=f"campus generated (n={len(gx):,})")
        a.set_title(f"{title}   KS={ks:.3f}", fontsize=10, loc="left")
        a.set_xlabel(xlabel); a.set_ylabel("density"); a.legend(fontsize=8)

    overlay(ax[0, 0], skwh, g["kwh"].to_numpy(), 40, (0, 60),
            "1  Energy per session (kWh)", "kWh")
    overlay(ax[0, 1], sa, g["arr_h"].to_numpy(), 48, (0, 24),
            "2  Arrival hour", "hour of day")
    overlay(ax[0, 2], sdep, g["dep_h"].to_numpy(), 48, (0, 24),
            "3  Departure hour", "hour of day")
    overlay(ax[1, 0], sdw, g["dwell"].to_numpy(), 48, (0, 24),
            "4  Dwell (hours)", "hours")

    per_cm = g.groupby(["unit", "car"]).size()
    ax[1, 1].hist(per_cm, bins=np.arange(0, 32) - 0.5, color=GEN_C, alpha=0.8)
    ax[1, 1].set_title(f"5  Sessions per car-month  (mean {per_cm.mean():.1f})",
                       fontsize=10, loc="left")
    ax[1, 1].set_xlabel("sessions in month"); ax[1, 1].set_ylabel("car-months")

    a6 = ax[1, 2]; a6.axis("off")
    lines = [f"{b}: {v['units']} units  {v['sessions']:,} sessions  {v['mwh']:.1f} MWh EV"
             for b, v in per_b.items()]
    tot = (f"TOTAL: {n_units:,} units  {len(g):,} sessions  "
           f"{sum(v['mwh'] for v in per_b.values()):.1f} MWh EV")
    a6.text(0.02, 0.98, "\n".join(lines + ["", tot]), va="top", family="monospace",
            fontsize=9, transform=a6.transAxes)
    a6.set_title("6  Per-building totals", fontsize=10, loc="left")

    fig.suptitle(
        f"campus_base generated tree vs ACN {args.site} calibration cohort "
        f"(anonymous excluded, same-day sessions) — {n_units:,} units",
        fontsize=13)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=120, bbox_inches="tight")
    print(f"saved {args.out}")
    stats = args.out.with_suffix(".csv")
    rows = []
    for name, sx, gx in (("kwh", skwh, g["kwh"]), ("arrival_hour", sa, g["arr_h"]),
                         ("departure_hour", sdep, g["dep_h"]), ("dwell_hours", sdw, g["dwell"])):
        gx = np.asarray(gx)
        rows.append({"quantity": name, "n_source": len(sx), "n_generated": len(gx),
                     "source_mean": float(np.mean(sx)), "generated_mean": float(np.mean(gx)),
                     "source_median": float(np.median(sx)), "generated_median": float(np.median(gx)),
                     "ks": float(st.ks_2samp(sx, gx).statistic)})
    pd.DataFrame(rows).to_csv(stats, index=False)
    print(f"saved {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
