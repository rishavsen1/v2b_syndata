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
    from v2b_syndata.calibration.battery_inference import (
        infer_capacity,
        reconstruct_arrival_soc,
    )
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
    # depart-SoC target: the same prior-based reconstruction calibration used
    rng = np.random.default_rng(20260613)
    dep_soc = []
    for s in sess:
        cap, _ = infer_capacity(s)
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        if soc is None or cap <= 0 or not s.kwh_delivered:
            continue
        d_ = min(1 - 1e-6, soc + float(s.kwh_delivered) / float(cap))
        if d_ > soc:
            dep_soc.append(d_ * 100)
    # per-weekday-date: mean dwell per active user
    df = pd.DataFrame({
        "date": pd.to_datetime([s.arrival_time for s in sess]).date,
        "uid": [s.user_id for s in sess],
        "dw": dw,
    })
    byd = df.groupby("date").agg(n=("uid", "nunique"), dwsum=("dw", "sum"))
    dwell_per_active = (byd["dwsum"] / byd["n"]).to_numpy()
    return arr, dep, dw, kwh, np.array(dep_soc), dwell_per_active


def _load_generated(root: Path, max_units: int | None):
    rows = []
    per_building = {}
    per_day = []
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
            gg = pd.read_csv(f, usecols=["previous_day_external_use_soc"])
            rows.append(pd.DataFrame({
                "b": bdir.name,
                "arr_h": a.dt.hour + a.dt.minute / 60.0,
                "dep_h": d.dt.hour + d.dt.minute / 60.0,
                "dwell": (d - a).dt.total_seconds() / 3600.0,
                "kwh": kwh,
                "req_soc": g["departure_soc"],
                "prev_ext": gg["previous_day_external_use_soc"],
                "car": g["car_id"],
                "month": a.dt.to_period("M").astype(str),
                "unit": ckey,
            }))
            fleet = int(cars_cache[ckey].shape[0])
            daily = g.assign(date=a.dt.date).groupby("date")["car_id"].nunique()
            dw_day = (pd.DataFrame({"date": a.dt.date,
                                    "dw": (d - a).dt.total_seconds() / 3600.0})
                      .groupby("date")["dw"].sum())
            for date, cnt in daily.items():
                per_day.append({"unit": ckey, "date": date, "n_evs": cnt,
                                "fleet": fleet, "share": cnt / fleet,
                                "dwell_per_active": float(dw_day.loc[date]) / cnt})
            n_sess += len(g)
            energy += float(kwh.sum())
        per_building[bdir.name] = {"units": len(files), "sessions": n_sess,
                                   "mwh": energy / 1000.0}
    return pd.concat(rows, ignore_index=True), per_building, pd.DataFrame(per_day)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--site", default="jpl", choices=["caltech", "jpl", "office001"])
    p.add_argument("--out", type=Path, default=REPO / "docs/experiments/campus_base_overview.png")
    p.add_argument("--max-units-per-building", type=int, default=None)
    args = p.parse_args(argv)

    sa, sdep, sdw, skwh, sdep_soc, sdw_day = _source_arrays(args.site)
    g, per_b, per_day = _load_generated(args.root, args.max_units_per_building)
    n_units = sum(v["units"] for v in per_b.values())

    fig, ax = plt.subplots(3, 3, figsize=(16.5, 12.9))

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

    # 6: distinct EVs active per day, as a share of the building fleet.
    # No direct source analogue at building scale (the ACN site pools hundreds
    # of drivers over 50+ chargers), so the reference lines are the model's own
    # source-anchored expectation E[phi] and the realized mean.
    a6 = ax[1, 2]
    a6.hist(per_day["share"], bins=np.linspace(0, 1, 31), color=GEN_C, alpha=0.8)
    mu = per_day["share"].mean()
    a6.axvline(mu, color="k", lw=1.2, ls="--", label=f"realized mean {mu:.2f}")
    a6.set_title(f"6  Active EVs per day / fleet size  "
                 f"(mean {per_day['n_evs'].mean():.1f} EVs)", fontsize=10, loc="left")
    a6.set_xlabel("share of fleet active"); a6.set_ylabel("building-days")
    a6.legend(fontsize=8)

    # 7: dwell hours per active EV per day — source comparable.
    overlay(ax[2, 0], sdw_day, per_day["dwell_per_active"].to_numpy(), 40, (0, 14),
            "7  Dwell hours per active EV per day", "h / active EV / day")

    # 8: departure-SoC requirement. Source side is the calibration's
    # prior-based reconstruction (SoC is never metered), so this compares two
    # MODELED quantities; generated is now DERIVED from the energy draw.
    overlay(ax[2, 1], sdep_soc, g["req_soc"].to_numpy(), 40, (0, 100),
            "8  Required SoC at departure (%)", "% SoC")

    # 9: previous-day external use (chain draw) — generated only; no dataset
    # observes between-visit consumption.
    a9 = ax[2, 2]
    pe = g["prev_ext"].to_numpy()
    a9.hist(pe[pe > 0], bins=40, color=GEN_C, alpha=0.8)
    a9.set_title(f"9  previous_day_external_use_soc  "
                 f"(zero share {np.mean(pe <= 0):.2f}; no source analogue)",
                 fontsize=10, loc="left")
    a9.set_xlabel("SoC points consumed between visits"); a9.set_ylabel("sessions")

    lines = [f"{b}: {v['units']} units  {v['sessions']:,} sessions  {v['mwh']:.1f} MWh EV"
             for b, v in per_b.items()]
    tot = (f"TOTAL: {n_units:,} units  {len(g):,} sessions  "
           f"{sum(v['mwh'] for v in per_b.values()):.1f} MWh EV")
    print("\n".join(lines + [tot]))

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
                         ("departure_hour", sdep, g["dep_h"]), ("dwell_hours", sdw, g["dwell"]),
                         ("required_soc_at_depart", sdep_soc, g["req_soc"]),
                         ("dwell_per_active_day", sdw_day, per_day["dwell_per_active"])):
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
