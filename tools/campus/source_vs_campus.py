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
# Only quantities the SOURCE actually measures. `required_soc_at_depart` is
# deliberately absent: on the source side it would be
# `seeded_prior + kWhDelivered / inferred_capacity` — a constant prior (drawn
# with no relation to arrival hour) divided by a capacity that falls back to
# 60 kWh for 28% of JPL sessions. Comparing against it measures our prior and
# our capacity guess, not behaviour. Arrival SoC gets its own generated-only
# row below for the same reason.
PARAMS = [
    ("arr_h", "arrival hour", 48, (0, 24)),
    ("dwell", "dwell (h)", 48, (0, 16)),
    ("kwh", "energy delivered (kWh)", 40, (0, 60)),
]
HOUR_BINS = [0, 7, 9, 11, 14, 24]
HOUR_LABELS = ["<7", "7-9", "9-11", "11-14", "14+"]


def source_frame(site: str, pop_name: str) -> pd.DataFrame:
    from v2b_syndata.calibration.acn_fetcher import fetch_all_sessions, filter_with_userid
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
    rows = [{"region": u2r.get(s.user_id, "__unassigned__"),
             "arr_h": s.arrival_hour, "dwell": s.dwell_hours,
             "kwh": s.kwh_delivered} for s in sess]
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
                "arr_soc": g["arrival_soc"], "cap": cap,
            }))
    return pd.concat(frames, ignore_index=True)


def _render_unified(src, gen, a, cmap, gen_h):
    """One pooled distribution per feature — no region split anywhere."""
    fig, ax = plt.subplots(2, 4, figsize=(25, 11))
    rows = []
    for i, (key, label, bins, rng_) in enumerate(PARAMS):
        axx = ax[0, i]
        sv = src[key].dropna().to_numpy()
        gv = gen[key].dropna().to_numpy()
        ks = st.ks_2samp(sv, gv).statistic
        rows.append({"feature": label, "n_source": len(sv), "n_generated": len(gv),
                     "source_mean": sv.mean(), "generated_mean": gv.mean(),
                     "source_median": float(np.median(sv)),
                     "generated_median": float(np.median(gv)), "ks": ks})
        axx.hist(sv, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
                 label=f"ACN {a.site} source  (n={len(sv):,})")
        axx.hist(gv, bins=bins, range=rng_, density=True, histtype="step",
                 color=GEN_C, lw=2.4, label=f"campus generated  (n={len(gv):,})")
        axx.set_title(f"{label}\nKS = {ks:.3f}   mean {sv.mean():.2f} vs {gv.mean():.2f}",
                      fontsize=11, loc="left")
        axx.set_xlabel(label); axx.set_ylabel("density"); axx.legend(fontsize=8)

    axx = ax[1, 0]
    gv = gen["arr_soc"].dropna().to_numpy()
    axx.hist(gv, bins=40, range=(0, 100), density=True, color=GEN_C, alpha=0.8,
             label=f"campus generated (n={len(gv):,})")
    axx.set_title(f"arrival SoC (%)  —  GENERATED ONLY\n"
                  f"mean {gv.mean():.1f}%, {np.mean(gv <= 10.001):.0%} pinned at the {10}% floor\n"
                  f"(no source analogue: SoC is never metered)", fontsize=11, loc="left")
    axx.set_xlabel("% SoC at arrival"); axx.set_ylabel("density"); axx.legend(fontsize=8)

    # arrival SoC, hour by hour
    axx = ax[1, 1]
    for i2, hlab in enumerate(HOUR_LABELS):
        v = gen_h[gen_h.hb == hlab]["arr_soc"].to_numpy()
        if len(v) < 30:
            continue
        axx.hist(v, bins=40, range=(0, 100), density=True, histtype="step", lw=2.0,
                 color=cmap(i2 / max(1, len(HOUR_LABELS) - 1)),
                 label=f"{hlab}  mean {v.mean():.0f}%, floor {np.mean(v <= 10.001):.0%}")
    axx.set_title("arrival SoC BY ARRIVAL HOUR — generated only\n"
                  "(curves nearly coincide: the spread is capacity-driven, not hour-driven)",
                  fontsize=11, loc="left")
    axx.set_xlabel("% SoC at arrival"); axx.set_ylabel("density"); axx.legend(fontsize=8)

    # arrival SoC mean + spread per hour bin
    axx = ax[1, 2]
    m = gen_h.groupby("hb")["arr_soc"].mean()
    q1 = gen_h.groupby("hb")["arr_soc"].quantile(0.25)
    q3 = gen_h.groupby("hb")["arr_soc"].quantile(0.75)
    se = gen_h.groupby("hb")["arr_soc"].sem()
    x = range(len(HOUR_LABELS))
    axx.fill_between(x, q1.values, q3.values, color=GEN_C, alpha=0.22, label="IQR")
    axx.errorbar(x, m.values, yerr=1.96 * se.values, marker="o", color=GEN_C,
                 lw=2, capsize=3, label="mean ± 95% CI")
    axx.set_xticks(list(x)); axx.set_xticklabels(HOUR_LABELS)
    axx.set_xlabel("arrival-hour bin"); axx.set_ylabel("% SoC at arrival")
    rg = st.spearmanr(gen.arr_h, gen.arr_soc, nan_policy="omit").statistic
    axx.set_title(f"arrival SoC level by hour — generated only\nspearman {rg:+.3f} (flat)",
                  fontsize=11, loc="left")
    axx.legend(fontsize=8); axx.grid(alpha=.25)

    axx = ax[1, 3]
    for key, c, ls in (("dwell", "#1f4e79", "-"), ("kwh", "#d8853b", "-")):
        for df, lab, mk in ((src, "source", "o"), (gen, "campus", "s")):
            d = df.dropna(subset=[key, "arr_h"]).copy()
            d["hb"] = pd.cut(d.arr_h, HOUR_BINS, labels=HOUR_LABELS)
            m = d.groupby("hb")[key].mean()
            norm = m / m.iloc[0]
            axx.plot(range(len(HOUR_LABELS)), norm.values, marker=mk,
                     ls="-" if lab == "source" else "--", color=c,
                     label=f"{key} — {lab}")
    axx.set_xticks(range(len(HOUR_LABELS))); axx.set_xticklabels(HOUR_LABELS)
    axx.set_xlabel("arrival-hour bin"); axx.set_ylabel("mean, normalised to first bin")
    axx.set_title("CONDITIONAL shape: how dwell and energy fall\nwith later arrival "
                  "(all regions pooled)", fontsize=11, loc="left")
    axx.legend(fontsize=8); axx.grid(alpha=.25)

    axx = ax[0, 3]; axx.axis("off")
    t = f"{'feature':22s}{'source':>10s}{'campus':>10s}{'KS':>8s}\n" + "-" * 50 + "\n"
    for r in rows:
        t += f"{r['feature'][:22]:22s}{r['source_mean']:10.2f}{r['generated_mean']:10.2f}{r['ks']:8.3f}\n"
    t += ("\ndependence (Spearman)\n" + "-" * 50 + "\n")
    for aa, bb, lab in (("arr_h", "dwell", "arrival vs dwell"),
                        ("arr_h", "kwh", "arrival vs energy"),
                        ("dwell", "kwh", "dwell vs energy")):
        rs = st.spearmanr(src[aa], src[bb], nan_policy="omit").statistic
        rg = st.spearmanr(gen[aa], gen[bb], nan_policy="omit").statistic
        t += f"{lab:22s}{rs:+10.3f}{rg:+10.3f}\n"
    axx.text(0.02, 0.98, t, va="top", family="monospace", fontsize=10,
             transform=axx.transAxes)

    fig.suptitle(f"ACN {a.site} source vs generated campus — unified distributions "
                 f"(all regions, all buildings, all months pooled)", fontsize=15)
    fig.tight_layout()
    fig.savefig(a.unified_out, dpi=120, bbox_inches="tight")
    pd.DataFrame(rows).to_csv(a.unified_out.with_suffix(".csv"), index=False)
    print(f"saved {a.unified_out}")


def _render_overlay(src, gen, a, cmap, gen_h):
    """Same rows, but every region overlaid inside one panel.

    Columns: SOURCE regions | CAMPUS regions | POOLED source-vs-campus. Shows
    how much the regions actually differ from EACH OTHER (in the ground truth
    and in the generator) alongside the aggregate comparison.
    """
    rc = {r: plt.get_cmap("tab10").colors[i] for i, r in enumerate(REGIONS)}
    nrow = len(PARAMS) + 2
    fig, ax = plt.subplots(nrow, 3, figsize=(17, nrow * 4.1))

    for i, (key, label, bins, rng_) in enumerate(PARAMS):
        for j, (df, who) in enumerate(((src, "SOURCE"), (gen, "CAMPUS"))):
            axx = ax[i, j]
            if key not in df.columns:
                axx.axis("off"); continue
            for r in REGIONS:
                v = df[df.region == r][key].dropna().to_numpy()
                if len(v) < 30:
                    continue
                axx.hist(v, bins=bins, range=rng_, density=True, histtype="step",
                         lw=2.0, color=rc[r], label=f"{r} (n={len(v):,})")
            axx.set_title(f"{label} — {who}: regions overlaid", fontsize=10, loc="left")
            axx.set_xlabel(label); axx.legend(fontsize=7)
            if j == 0:
                axx.set_ylabel("density")
        axx = ax[i, 2]
        sv = src[key].dropna().to_numpy() if key in src.columns else np.array([])
        gv = gen[key].dropna().to_numpy()
        if len(sv) >= 30:
            ks = st.ks_2samp(sv, gv).statistic
            axx.hist(sv, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
                     label=f"source n={len(sv):,}")
            axx.set_title(f"{label} — POOLED over all regions   KS={ks:.3f}",
                          fontsize=10, loc="left")
        else:
            axx.set_title(f"{label} — POOLED (generated only)", fontsize=10, loc="left")
        axx.hist(gv, bins=bins, range=rng_, density=True, histtype="step",
                 color=GEN_C, lw=2.2, label=f"campus n={len(gv):,}")
        axx.set_xlabel(label); axx.legend(fontsize=7)

    # arrival-SoC row: regions overlaid (campus only), then by hour, then pooled
    r0 = len(PARAMS)
    axx = ax[r0, 0]
    for r in REGIONS:
        v = gen[gen.region == r]["arr_soc"].dropna().to_numpy()
        if len(v) < 30:
            continue
        axx.hist(v, bins=40, range=(0, 100), density=True, histtype="step", lw=2.0,
                 color=rc[r], label=f"{r} (mean {v.mean():.0f}%)")
    axx.set_title("arrival SoC — CAMPUS: regions overlaid\n(generated only: SoC is never metered)",
                  fontsize=10, loc="left")
    axx.set_xlabel("% SoC at arrival"); axx.set_ylabel("density"); axx.legend(fontsize=7)

    axx = ax[r0, 1]
    for i2, hlab in enumerate(HOUR_LABELS):
        v = gen_h[gen_h.hb == hlab]["arr_soc"].to_numpy()
        if len(v) < 30:
            continue
        axx.hist(v, bins=40, range=(0, 100), density=True, histtype="step", lw=2.0,
                 color=cmap(i2 / max(1, len(HOUR_LABELS) - 1)),
                 label=f"{hlab} (mean {v.mean():.0f}%)")
    axx.set_title("arrival SoC by arrival hour — ALL REGIONS POOLED", fontsize=10, loc="left")
    axx.set_xlabel("% SoC at arrival"); axx.legend(fontsize=7)

    axx = ax[r0, 2]
    caps = sorted(gen["cap"].dropna().unique()) if "cap" in gen.columns else []
    for i2, c in enumerate(caps):
        v = gen[gen.cap == c]["arr_soc"].dropna().to_numpy()
        if len(v) < 30:
            continue
        axx.hist(v, bins=40, range=(0, 100), density=True, histtype="step", lw=2.0,
                 color=cmap(i2 / max(1, len(caps) - 1)),
                 label=f"{c:.0f} kWh (mean {v.mean():.0f}%, floor {np.mean(v <= 10.001):.0%})")
    axx.set_title("arrival SoC by BATTERY CAPACITY — all regions\n"
                  "(the floor pile-up is capacity-driven, not hour-driven)",
                  fontsize=10, loc="left")
    axx.set_xlabel("% SoC at arrival"); axx.legend(fontsize=7)

    # conditional row, all regions pooled
    for j, key in enumerate(["dwell", "kwh", "arr_soc"]):
        axx = ax[r0 + 1, j]
        series = ((gen, GEN_C, "campus"),) if key == "arr_soc" else \
                 ((src, SRC_C, "source"), (gen, GEN_C, "campus"))
        for df, c, lab in series:
            if key not in df.columns:
                continue
            d = df.dropna(subset=[key, "arr_h"]).copy()
            d["hb"] = pd.cut(d.arr_h, HOUR_BINS, labels=HOUR_LABELS)
            m = d.groupby("hb")[key].mean(); se = d.groupby("hb")[key].sem()
            axx.errorbar(range(len(HOUR_LABELS)), m.values, yerr=1.96 * se.values,
                         marker="o", color=c, lw=2, capsize=3, label=lab)
        rg = st.spearmanr(gen.arr_h, gen[key], nan_policy="omit").statistic
        sub = (f"campus {rg:+.3f} (generated only)" if key == "arr_soc"
               else f"source {st.spearmanr(src.arr_h, src[key], nan_policy='omit').statistic:+.3f}"
                    f" vs campus {rg:+.3f}")
        axx.set_xticks(range(len(HOUR_LABELS))); axx.set_xticklabels(HOUR_LABELS)
        axx.set_xlabel("arrival-hour bin")
        axx.set_title(f"CONDITIONAL (all regions): mean {key} by arrival hour\n{sub}",
                      fontsize=10, loc="left")
        axx.legend(fontsize=7); axx.grid(alpha=.25)

    fig.suptitle(f"ACN {a.site} source vs generated campus — ALL REGIONS "
                 f"(overlaid, and pooled)", fontsize=15, y=0.998)
    fig.tight_layout()
    fig.savefig(a.overlay_out, dpi=110, bbox_inches="tight")
    print(f"saved {a.overlay_out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--site", default="jpl")
    ap.add_argument("--population", default="acn_jpl_baseline")
    ap.add_argument("--units", type=int, default=300)
    ap.add_argument("--phi-scale", type=float, default=1.5)
    ap.add_argument("--out", type=Path, default=REPO / "docs/experiments/source_vs_campus.png")
    ap.add_argument("--overlay-out", type=Path, default=None,
                    help="also render the regions-overlaid view to this path")
    ap.add_argument("--unified-out", type=Path, default=None,
                    help="also render ONE pooled distribution per feature (no region split)")
    a = ap.parse_args(argv)

    src = source_frame(a.site, a.population)
    gen = synth_frame(a.root, a.units, a.phi_scale)
    print(f"source n={len(src):,}  generated n={len(gen):,}")
    print("region mix  source:",
          {k: round(v, 3) for k, v in src.region.value_counts(normalize=True).items()})
    print("region mix  campus:",
          {k: round(v, 3) for k, v in gen.region.value_counts(normalize=True).items()})

    cols = REGIONS + ["POOLED"]
    fig, axes = plt.subplots(len(PARAMS) + 2, len(cols), figsize=(20, 22))
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

    # ── arrival-SoC distribution BY ARRIVAL HOUR (generated only) ───────────
    # No source analogue: SoC is never metered. This row is an INTERNAL
    # consistency check — after the energy-first fix, arrivals that precede a
    # large charge must sit lower, so early-hour curves should shift left.
    gen_h = gen.dropna(subset=["arr_soc", "arr_h"]).copy()
    gen_h["hb"] = pd.cut(gen_h.arr_h, HOUR_BINS, labels=HOUR_LABELS)
    cmap = plt.get_cmap("viridis")
    for j, reg in enumerate(cols):
        ax = axes[len(PARAMS), j]
        sub = gen_h if reg == "POOLED" else gen_h[gen_h.region == reg]
        if len(sub) < 50:
            ax.axis("off"); continue
        for i, hlab in enumerate(HOUR_LABELS):
            v = sub[sub.hb == hlab]["arr_soc"].to_numpy()
            if len(v) < 30:
                continue
            ax.hist(v, bins=40, range=(0, 100), density=True, histtype="step", lw=1.8,
                    color=cmap(i / max(1, len(HOUR_LABELS) - 1)),
                    label=f"{hlab}  (mean {v.mean():.0f}%, n={len(v):,})")
        ax.set_title(f"arrival SoC by arrival hour — GENERATED ONLY\n{reg}  "
                     f"(no source analogue: SoC is never metered)", fontsize=9, loc="left")
        ax.set_xlabel("% SoC at arrival"); ax.legend(fontsize=6.5)
        if j == 0:
            ax.set_ylabel("density")

    # conditional row: mean of each parameter by arrival-hour bin
    hb, hl = HOUR_BINS, HOUR_LABELS
    for j, key in enumerate(["dwell", "kwh", "arr_soc"]):
        ax = axes[-1, j]
        series = ((gen, GEN_C, "campus"),) if key == "arr_soc" else \
                 ((src, SRC_C, "source"), (gen, GEN_C, "campus"))
        for df, c, lab in series:
            if key not in df.columns:
                continue
            d = df.dropna(subset=[key, "arr_h"]).copy()
            d["hb"] = pd.cut(d.arr_h, hb, labels=hl)
            m = d.groupby("hb")[key].mean()
            sd = d.groupby("hb")[key].sem()
            ax.errorbar(range(len(hl)), m.values, yerr=1.96 * sd.values, marker="o",
                        color=c, lw=2, capsize=3, label=lab)
        rg = st.spearmanr(gen.arr_h, gen[key], nan_policy="omit").statistic
        ax.set_xticks(range(len(hl))); ax.set_xticklabels(hl)
        ax.set_xlabel("arrival-hour bin")
        if key == "arr_soc":
            sub = f"campus {rg:+.3f}  (generated only)"
        else:
            rs = st.spearmanr(src.arr_h, src[key], nan_policy="omit").statistic
            sub = f"spearman source {rs:+.3f} vs campus {rg:+.3f}"
        ax.set_title(f"CONDITIONAL: mean {key} by arrival hour\n{sub}", fontsize=9, loc="left")
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
    if a.unified_out is not None:
        _render_unified(src, gen, a, cmap, gen_h)

    if a.overlay_out is not None:
        _render_overlay(src, gen, a, cmap, gen_h)

    sdf = pd.DataFrame(stats)
    sdf.to_csv(a.out.with_suffix(".csv"), index=False)
    print(sdf.pivot_table(index="parameter", columns="region", values="ks").round(3).to_string())
    print(f"\nsaved {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
