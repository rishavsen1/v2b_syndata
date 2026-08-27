"""Source (ACN JPL) vs generated campus distributions, stratified by region.

Why stratified: the campus office tiers deliberately re-weight the population
(72% regular_charger pooled vs the source's 27%), so a pooled comparison mostly
measures that DESIGN choice, not model fidelity. Comparing region-by-region
removes the mix confound and tests the fitted marginals directly.

Region recovery:
  * source    — per-user phi from `aggregate_user_features`, binned by the
                population's `axes_distribution` freq bounds.
  * synthetic — `cars.csv::frequency` is phi AFTER `phi_scale`, so the bin
                edges scale by the same factor (capped at 0.95).

Panels: one row per parameter (arrival hour, dwell, energy, required SoC),
columns = the three regions + pooled. A final row shows the CONDITIONAL view
(parameter vs arrival-hour bin) where dependence structure lives.

Run:
  uv run python tools/campus/source_vs_campus.py data/output/campus_base \
      --site jpl --units 300
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import scipy.stats as st
import yaml

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SRC_C, GEN_C = "#555555", "#d8853b"
REGIONS = ["rare_consistent", "occasional_consistent", "regular_charger"]
PARAMS = [
    ("arr_h", "arrival hour", 48, (0, 24)),
    ("dwell", "dwell (h)", 48, (0, 16)),
    ("kwh", "energy delivered (kWh)", 40, (0, 60)),
    ("req_soc", "required SoC at departure (%)", 40, (0, 100)),
]


def source_frame(site: str, pop_name: str) -> pd.DataFrame:
    from v2b_syndata.calibration.acn_fetcher import fetch_all_sessions, filter_with_userid
    from v2b_syndata.calibration.battery_inference import (
        infer_capacity,
        reconstruct_arrival_soc,
    )
    from v2b_syndata.calibration.feature_extractor import (
        aggregate_user_features,
        extract_session,
    )
    from v2b_syndata.calibration.region_assignment import assign_user_to_region

    pops = yaml.safe_load(open(REPO / "configs/populations.yaml"))
    axes = pops[pop_name]["axes_distribution"]
    raw = filter_with_userid(fetch_all_sessions(
        site, 2019, 2021, cache_dir=REPO / "data/calibration/acn_cache"))
    sess = [s for s in (extract_session(r, site) for r in raw) if s is not None]
    users = aggregate_user_features(sess, None, None)
    u2r = {u.user_id: (assign_user_to_region(u, axes) or "__unassigned__") for u in users}
    rng = np.random.default_rng(20260613)
    rows = []
    for s in sess:
        cap, _ = infer_capacity(s)
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        req = np.nan
        if soc is not None and cap > 0 and s.kwh_delivered:
            d = min(1 - 1e-6, soc + float(s.kwh_delivered) / float(cap))
            req = d * 100 if d > soc else np.nan
        rows.append({"region": u2r.get(s.user_id, "__unassigned__"),
                     "arr_h": s.arrival_hour, "dwell": s.dwell_hours,
                     "kwh": s.kwh_delivered, "req_soc": req})
    return pd.DataFrame(rows)


def synth_frame(root: Path, units: int, phi_scale: float) -> pd.DataFrame:
    """Stratified sample of units across every building and month."""
    edges = {}
    pops = yaml.safe_load(open(REPO / "configs/populations.yaml"))
    for r in pops["acn_jpl_baseline"]["axes_distribution"]:
        lo, hi = r["freq"]
        edges[r["name"]] = (lo * phi_scale, min(0.95, hi * phi_scale))
    bdirs = sorted(root.glob("b*"), key=lambda p: int(p.name[1:]))
    per_b = max(1, units // max(1, len(bdirs)))
    frames = []
    for b in bdirs:
        cells = sorted(b.glob("*/*"))
        step = max(1, len(cells) // per_b)
        for d in cells[::step][:per_b]:
            try:
                g = pd.read_csv(d / "sessions_soc.csv")
                cars = pd.read_csv(d / "cars.csv").set_index("car_id")
            except Exception:
                continue
            a = pd.to_datetime(g["arrival"]); dep = pd.to_datetime(g["departure"])
            phi = g["car_id"].map(cars["frequency"])
            cap = g["car_id"].map(cars["capacity_kwh"])
            reg = pd.Series("__unassigned__", index=g.index)
            for name, (lo, hi) in edges.items():
                reg[(phi >= lo - 1e-9) & (phi <= hi + 1e-9)] = name
            frames.append(pd.DataFrame({
                "region": reg, "building": b.name,
                "arr_h": a.dt.hour + a.dt.minute / 60.0,
                "dwell": (dep - a).dt.total_seconds() / 3600.0,
                "kwh": (g["departure_soc"] - g["arrival_soc"]) / 100.0 * cap,
                "req_soc": g["departure_soc"],
            }))
    return pd.concat(frames, ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--site", default="jpl")
    ap.add_argument("--population", default="acn_jpl_baseline")
    ap.add_argument("--units", type=int, default=300)
    ap.add_argument("--phi-scale", type=float, default=1.5)
    ap.add_argument("--out", type=Path, default=REPO / "docs/experiments/source_vs_campus.png")
    a = ap.parse_args(argv)

    src = source_frame(a.site, a.population)
    gen = synth_frame(a.root, a.units, a.phi_scale)
    print(f"source n={len(src):,}  generated n={len(gen):,}")
    print("region mix  source:",
          {k: round(v, 3) for k, v in src.region.value_counts(normalize=True).items()})
    print("region mix  campus:",
          {k: round(v, 3) for k, v in gen.region.value_counts(normalize=True).items()})

    cols = REGIONS + ["POOLED"]
    fig, axes = plt.subplots(len(PARAMS) + 1, len(cols), figsize=(20, 19))
    stats = []
    for i, (key, label, bins, rng_) in enumerate(PARAMS):
        for j, reg in enumerate(cols):
            ax = axes[i, j]
            s = (src if reg == "POOLED" else src[src.region == reg])[key].dropna().to_numpy()
            g = (gen if reg == "POOLED" else gen[gen.region == reg])[key].dropna().to_numpy()
            if len(s) < 30 or len(g) < 30:
                ax.axis("off"); continue
            ks = st.ks_2samp(s, g).statistic
            stats.append({"parameter": label, "region": reg, "n_source": len(s),
                          "n_generated": len(g), "source_mean": s.mean(),
                          "generated_mean": g.mean(), "ks": ks})
            ax.hist(s, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
                    label=f"source n={len(s):,}")
            ax.hist(g, bins=bins, range=rng_, density=True, histtype="step",
                    color=GEN_C, lw=2.0, label=f"campus n={len(g):,}")
            ax.set_title(f"{label}\n{reg}   KS={ks:.3f}", fontsize=9, loc="left")
            ax.legend(fontsize=7)
            if j == 0:
                ax.set_ylabel("density")

    # conditional row: mean of each parameter by arrival-hour bin
    hb = [0, 7, 9, 11, 14, 24]
    hl = ["<7", "7-9", "9-11", "11-14", "14+"]
    for j, key in enumerate(["dwell", "kwh", "req_soc"]):
        ax = axes[-1, j]
        for df, c, lab in ((src, SRC_C, "source"), (gen, GEN_C, "campus")):
            d = df.dropna(subset=[key, "arr_h"]).copy()
            d["hb"] = pd.cut(d.arr_h, hb, labels=hl)
            m = d.groupby("hb")[key].mean()
            sd = d.groupby("hb")[key].sem()
            ax.errorbar(range(len(hl)), m.values, yerr=1.96 * sd.values, marker="o",
                        color=c, lw=2, capsize=3, label=lab)
        rs = st.spearmanr(src.arr_h, src[key], nan_policy="omit").statistic
        rg = st.spearmanr(gen.arr_h, gen[key], nan_policy="omit").statistic
        ax.set_xticks(range(len(hl))); ax.set_xticklabels(hl)
        ax.set_xlabel("arrival-hour bin")
        ax.set_title(f"CONDITIONAL: mean {key} by arrival hour\n"
                     f"spearman source {rs:+.3f} vs campus {rg:+.3f}", fontsize=9, loc="left")
        ax.legend(fontsize=7); ax.grid(alpha=.25)
    axes[-1, -1].axis("off")
    txt = (f"region mix (share of sessions)\n"
           f"{'region':24s}{'source':>9s}{'campus':>9s}\n" + "-" * 42 + "\n")
    sm = src.region.value_counts(normalize=True)
    gm = gen.region.value_counts(normalize=True)
    for r in REGIONS:
        txt += f"{r:24s}{sm.get(r, 0):9.3f}{gm.get(r, 0):9.3f}\n"
    txt += ("\nPooled differences are dominated by this\ndeliberate re-weighting, not by model\n"
            "fidelity. Read the per-region columns.")
    axes[-1, -1].text(0.02, 0.95, txt, va="top", family="monospace", fontsize=9,
                      transform=axes[-1, -1].transAxes)

    fig.suptitle(f"ACN {a.site} source vs generated campus — stratified by behavioral region",
                 fontsize=15, y=0.997)
    fig.tight_layout()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=110, bbox_inches="tight")
    sdf = pd.DataFrame(stats)
    sdf.to_csv(a.out.with_suffix(".csv"), index=False)
    print(sdf.pivot_table(index="parameter", columns="region", values="ks").round(3).to_string())
    print(f"\nsaved {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
