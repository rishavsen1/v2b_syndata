#!/usr/bin/env python3
"""Render the five KDD-paper figures into paper/figures/*.pdf.

Figures (see docs/KDD_PAPER_STRUCTURE.md "Figures & tables inventory"):

  fig1_pipeline.pdf  pipeline overview, double-column (~7 in)
  fig2_axes.pdf      behavioral (phi, kappa) region geometries, 2 stacked panels
  fig3_arrival.pdf   arrival-hour prior vs fitted mixture (ACN rare_consistent)
  fig4_load.pdf      building-load weekly shape, synthetic vs ComStock
  fig5_tstr.pdf      TSTR/TRTR ratio bars (ACN + ElaadNL matched)

All content is read from the repo (configs/populations.yaml, data/tstr/*.json,
data/buildingload_reference/, the load-pipeline cache) — nothing is hardcoded
from memory. Deterministic: no random draws; matplotlib only.

Run:  uv run python tools/paper_figures.py [--skip-fig4]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from scipy import stats

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "paper" / "figures"
POPULATIONS = REPO / "configs" / "populations.yaml"
TSTR_ACN = REPO / "data" / "tstr" / "results.json"
TSTR_ELAADNL = REPO / "data" / "tstr" / "results_elaadnl_matched.json"

# House palette (matches the repo's report styling).
NAVY = "#1f4e79"
AMBER = "#d8853b"
NAVY_TINT = "#e9eef4"
AMBER_TINT = "#faeedd"
GREY = "#555555"

BASE_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "pdf.fonttype": 42,          # embed TrueType — required by ACM
    "ps.fonttype": 42,
    "axes.edgecolor": GREY,
    "axes.linewidth": 0.7,
    "axes.labelcolor": "#222222",
    "xtick.color": "#222222",
    "ytick.color": "#222222",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8.5,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "figure.dpi": 200,
}


def _save(fig: plt.Figure, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, format="pdf", bbox_inches="tight", pad_inches=0.02,
                metadata={"CreationDate": None})   # strip date => reproducible
    plt.close(fig)
    print(f"  wrote {path} ({path.stat().st_size:,} B)")
    return path


# ────────────────────────────────────────────────────────────────────
# Fig 1 — pipeline overview (double column)
# ────────────────────────────────────────────────────────────────────

def _box(ax, x, y, w, h, *, fc="white", ec=NAVY, lw=1.0, ls="-", r=0.045):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0,rounding_size={r}",
                       facecolor=fc, edgecolor=ec, linewidth=lw,
                       linestyle=ls, zorder=2)
    ax.add_patch(p)
    return p


def _arrow(ax, p0, p1, *, color=NAVY, lw=1.1, style="-|>", ms=8,
           connectionstyle="arc3,rad=0.0", ls="-", zorder=3):
    a = FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=ms,
                        color=color, lw=lw, linestyle=ls,
                        connectionstyle=connectionstyle,
                        shrinkA=1.5, shrinkB=1.5, zorder=zorder)
    ax.add_patch(a)
    return a


def fig1_pipeline() -> None:
    W, H = 7.0, 3.12
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    TS = 6.1      # lane title size
    CS = 5.5      # content size

    def lane(x, w, y, h, title, lines, *, fc=NAVY_TINT, content_size=CS):
        _box(ax, x, y, w, h, fc=fc)
        ax.text(x + w / 2, y + h - 0.12, title, ha="center", va="center",
                fontsize=TS, fontweight="bold", color=NAVY)
        ax.text(x + w / 2, y + (h - 0.24) / 2, "\n".join(lines),
                ha="center", va="center", fontsize=content_size,
                color="#222222", linespacing=1.4)

    top_y, top_h = 1.60, 1.36
    mid = top_y + top_h / 2

    # L0 … L2 (left of the DAG)
    lane(0.03, 0.95, top_y, top_h, "L0 · inputs",
         ["5 descriptors:", "location · building", "population · equip.",
          "noise   +  seed $s$"])
    lane(1.12, 1.00, top_y, top_h, "L1 · resolution",
         ["69 typed knobs;", "CLI $\\succ$ scenario",
          "$\\succ$ descriptor", "$\\succ$ default;",
          "provenance per knob"])
    lane(2.26, 1.00, top_y, top_h, "L2 · seeding",
         ["SeedSequence($s$,", "SHA-256(node));", "hash-keyed streams,",
          "order-independent"])

    # L3 — sampling DAG (tall)
    dag_x, dag_w = 3.40, 1.62
    dag_y, dag_h = 0.60, 2.42
    _box(ax, dag_x, dag_y, dag_w, dag_h, fc="white", lw=1.2)
    ax.text(dag_x + dag_w / 2, dag_y + dag_h - 0.12, "L3 · sampling DAG",
            ha="center", va="center", fontsize=TS, fontweight="bold",
            color=NAVY)
    tiers = [
        ("Tier 1 · roots", "C A S O T U F X"),
        ("Tier 1.5 · per-entity", "A$_{user}$($\\phi,\\kappa,\\delta$) · A$_{fleet}$"),
        ("Tier 2 · latents", "EnergyPlus load · PV\n$f_{arr}$ $f_{dwell}$ $f_{soc}$ + copula"),
        ("Tier 3 · renderers", "10 output tables"),
    ]
    ty = dag_y + dag_h - 0.30
    tier_boxes = []
    for name, body in tiers:
        nlines = body.count("\n") + 1
        th = 0.30 + 0.115 * nlines
        ty -= th + 0.065
        fc = AMBER_TINT if "Tier 2" in name else NAVY_TINT
        _box(ax, dag_x + 0.09, ty, dag_w - 0.18, th, fc=fc, lw=0.7, r=0.03)
        ax.text(dag_x + dag_w / 2, ty + th - 0.105, name, ha="center",
                va="center", fontsize=5.8, fontweight="bold", color=NAVY)
        ax.text(dag_x + dag_w / 2, ty + (th - 0.17) / 2, body, ha="center",
                va="center", fontsize=5.6, color="#222222", linespacing=1.25)
        tier_boxes.append((ty, th))
    # tier-to-tier arrows
    for (y_hi, _), (y_lo, h_lo) in zip(tier_boxes, tier_boxes[1:]):
        _arrow(ax, (dag_x + dag_w / 2, y_hi), (dag_x + dag_w / 2, y_lo + h_lo),
               lw=0.8, ms=6)

    # L4 … L6 (right of the DAG)
    lane(5.16, 0.80, top_y, top_h, "L4 · noise",
         ["optional,", "output-side;", "clean = 0 jitter;", "repairs logged"])
    lane(6.10, 0.84, top_y, top_h, "L5 · validation",
         ["59 invariants", "in 9 families;", "hard errors", "reject the run"])
    out_x, out_w = 6.10, 0.84
    out_y, out_h = 0.10, 1.14
    lane(out_x, out_w, out_y, out_h, "L6 · outputs",
         ["10 CSV tables", "+ manifest.json", "(checksums,", "knob sources,",
          "verdict)"],
         fc="white")

    # main-flow arrows L0→…→L5, then down to L6
    _arrow(ax, (0.98, mid), (1.12, mid))
    _arrow(ax, (2.12, mid), (2.26, mid))
    _arrow(ax, (3.26, mid), (dag_x, mid))
    _arrow(ax, (dag_x + dag_w, mid), (5.16, mid))
    _arrow(ax, (5.96, mid), (6.10, mid))
    _arrow(ax, (6.10 + 0.84 / 2, top_y), (out_x + out_w / 2, out_y + out_h),
           lw=1.1)

    # ── weather side channel (one perturbed realization) ──
    wx, wy, ww, wh = 0.06, 0.10, 2.64, 0.92
    _box(ax, wx, wy, ww, wh, fc=AMBER_TINT, ec=AMBER, lw=1.2)
    ax.text(wx + ww / 2, wy + wh - 0.12, "weather channel (one realization)",
            ha="center", va="center", fontsize=TS, fontweight="bold",
            color="#9a5716")
    ax.text(wx + ww / 2, wy + (wh - 0.24) / 2,
            "TMYx EPW $\\rightarrow$ perturb: $+\\Delta T$ · ×solar ·\n"
            "$+\\Delta$dew (RH recomputed) · ×wind\n"
            "$\\rightarrow$ one weather frame per sample",
            ha="center", va="center", fontsize=CS, color="#222222",
            linespacing=1.4)

    # weather → Tier-2 latents (EnergyPlus + PV)
    t2_y, t2_h = tier_boxes[2]
    _arrow(ax, (wx + ww, wy + wh * 0.66), (dag_x + 0.09, t2_y + t2_h * 0.5),
           color=AMBER, lw=1.3, connectionstyle="arc3,rad=-0.15")
    ax.text(3.02, 1.24, "EnergyPlus\n+ PV model", fontsize=5.2, color="#9a5716",
            ha="center", va="center", style="italic")
    # weather → exported weather_data.csv (outputs)
    _arrow(ax, (wx + ww, wy + wh * 0.22), (out_x, out_y + 0.26),
           color=AMBER, lw=1.3, connectionstyle="arc3,rad=0.14")
    ax.text(4.50, 0.44, "exported as weather_data.csv (same frame)",
            fontsize=5.2, color="#9a5716", ha="center", va="center",
            style="italic")

    _save(fig, "fig1_pipeline.pdf")


# ────────────────────────────────────────────────────────────────────
# Fig 2 — (phi, kappa) region geometries
# ────────────────────────────────────────────────────────────────────

def fig2_axes() -> None:
    pops = yaml.safe_load(POPULATIONS.read_text())
    panels = [
        ("consent_default", "A — consent\\_default (hand-specified)", NAVY),
        ("acn_workplace_baseline",
         "B — acn\\_workplace\\_baseline (empirical ACN weights)", AMBER),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(3.3, 4.7), sharex=True)
    fig.subplots_adjust(hspace=0.24)

    for ax, (pop, title, color) in zip(axes, panels):
        regions = pops[pop]["axes_distribution"]
        for reg in regions:
            f0, f1 = reg["freq"]
            k0, k1 = reg["consist"]
            w = float(reg["weight"])
            zero = w <= 0.0
            ax.add_patch(plt.Rectangle(
                (f0, k0), f1 - f0, k1 - k0,
                facecolor="none" if zero else color,
                alpha=1.0 if zero else 0.22,
                edgecolor=color, linewidth=1.1,
                linestyle="--" if zero else "-", zorder=2))
            label = f"{reg['name'].replace('_', chr(10))}\n{100 * w:.1f}%"
            cx, cy = (f0 + f1) / 2, (k0 + k1) / 2
            rot = 90 if (f1 - f0) < 0.22 else 0
            ax.text(cx, cy, label, ha="center", va="center", fontsize=6.2,
                    rotation=rot, color="#1a1a1a", linespacing=1.15,
                    zorder=3)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_ylabel("timing consistency $\\kappa$")
        ax.set_title(title.replace("\\_", "_"), fontsize=7.5, color="#222222",
                     loc="left", pad=3)
        ax.set_xticks(np.arange(0, 1.01, 0.2))
        ax.set_yticks(np.arange(0, 1.01, 0.2))
        ax.grid(True, linewidth=0.3, color="#cccccc", alpha=0.6, zorder=0)
        ax.tick_params(length=2)
    axes[1].set_xlabel("plug-in frequency $\\phi$")
    _save(fig, "fig2_axes.pdf")


# ────────────────────────────────────────────────────────────────────
# Fig 3 — arrival prior vs fitted mixture (ACN rare_consistent)
# ────────────────────────────────────────────────────────────────────

def _truncnorm_pdf(x, mu, sigma, lo, hi):
    a, b = (lo - mu) / sigma, (hi - mu) / sigma
    return stats.truncnorm.pdf(x, a, b, loc=mu, scale=sigma)


def fig3_arrival() -> None:
    pops = yaml.safe_load(POPULATIONS.read_text())
    cal = pops["acn_workplace_baseline"]["region_distributions"]["rare_consistent"]["arrival"]
    assert cal["dist"] == "truncnorm_mixture", cal["dist"]
    w1 = float(cal["w1"])
    mu1, s1 = float(cal["mu1"]), float(cal["sigma1"])
    mu2, s2 = float(cal["mu2"]), float(cal["sigma2"])
    lo, hi = float(cal["trunc_lo"]), float(cal["trunc_hi"])

    # Hand-specified prior: TruncNorm(8.5, 2(1-kappa)) on [6,20]  (samplers/
    # sessions_dist.py fallback), evaluated at kappa = 0.85 -> sigma = 0.3.
    KAPPA = 0.85
    p_mu, p_sigma, p_lo, p_hi = 8.5, max(2.0 * (1.0 - KAPPA), 1e-3), 6.0, 20.0

    x = np.linspace(4.0, 22.0, 1200)
    mix1 = w1 * _truncnorm_pdf(x, mu1, s1, lo, hi)
    mix2 = (1.0 - w1) * _truncnorm_pdf(x, mu2, s2, lo, hi)
    mix = mix1 + mix2
    prior = np.where((x >= p_lo) & (x <= p_hi),
                     _truncnorm_pdf(x, p_mu, p_sigma, p_lo, p_hi), 0.0)
    prior_peak = float(prior.max())

    fig, ax = plt.subplots(figsize=(3.3, 2.1))
    ax.fill_between(x, mix, color=AMBER, alpha=0.30, zorder=1)
    ax.plot(x, mix, color=AMBER, lw=1.6, zorder=3,
            label="fitted 2-component mixture (ACN)")
    ax.plot(x, mix1, color=AMBER, lw=0.8, ls=":", zorder=2)
    ax.plot(x, mix2, color=AMBER, lw=0.8, ls=":", zorder=2)
    ax.plot(x, prior, color=NAVY, lw=1.6, zorder=4,
            label=f"hand-specified prior ($\\kappa$ = {KAPPA})")

    ymax = 0.42
    ax.set_ylim(0, ymax)
    ax.set_xlim(4, 22)
    ax.annotate(f"prior peak $\\approx$ {prior_peak:.2f} h$^{{-1}}$ (clipped)",
                xy=(p_mu + 0.35, ymax * 0.97), xytext=(11.6, 0.30),
                fontsize=6.3, color=NAVY,
                arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=0.8,
                                shrinkA=2, shrinkB=1))
    ax.set_xlabel("arrival hour")
    ax.set_ylabel("density (h$^{-1}$)")
    ax.set_xticks(range(4, 23, 2))
    ax.legend(loc="upper right", frameon=False, fontsize=5.9,
              handlelength=1.6, borderaxespad=0.1)
    ax.grid(True, linewidth=0.3, color="#cccccc", alpha=0.6, zorder=0)
    ax.tick_params(length=2)
    _save(fig, "fig3_arrival.pdf")


# ────────────────────────────────────────────────────────────────────
# Fig 4 — building-load weekly shape: synthetic vs ComStock
# ────────────────────────────────────────────────────────────────────

def _weekly_shape(series) -> np.ndarray:
    """168-point average-week profile (Mon 00h … Sun 23h), peak-normalized."""
    import pandas as pd
    idx = pd.DatetimeIndex(series.index)
    s = pd.Series(np.asarray(series, dtype=float), index=idx)
    key = idx.dayofweek * 24 + idx.hour
    prof = s.groupby(key).mean().reindex(range(168)).interpolate()
    arr = prof.to_numpy()
    return arr / float(np.max(arr))


def fig4_load(skip: bool = False) -> None:
    ARCH, SIZE, CZ = "office", "large", "5B"
    try:
        if skip:
            raise RuntimeError("--skip-fig4 requested")
        sys.path.insert(0, str(REPO / "tools"))
        from validate_buildingload import (  # noqa: E402
            generate_generator_load, load_reference_hourly, to_hourly,
        )
        ref = load_reference_hourly(ARCH, SIZE, CZ)          # ComStock, hourly
        gen = to_hourly(generate_generator_load(ARCH, SIZE))  # cached E+ run
    except Exception as e:  # noqa: BLE001 — placeholder path
        print(f"  fig4: real data unavailable ({e}); emitting placeholder")
        fig, ax = plt.subplots(figsize=(3.3, 2.1))
        ax.axis("off")
        ax.text(0.5, 0.5, "Fig. 4 placeholder\nbuilding-load weekly shape\n"
                          "(requires load-pipeline cache +\ncomstock_timeseries.parquet)",
                ha="center", va="center", fontsize=8, color=GREY)
        _save(fig, "fig4_PLACEHOLDER.pdf")
        return

    w_gen = _weekly_shape(gen)
    w_ref = _weekly_shape(ref)
    corr = float(np.corrcoef(w_gen, w_ref)[0, 1])

    fig, ax = plt.subplots(figsize=(3.3, 2.1))
    hours = np.arange(168)
    ax.plot(hours, w_ref, color=NAVY, lw=1.4, label="ComStock (real stock)")
    ax.plot(hours, w_gen, color=AMBER, lw=1.4, label="v2b-syndata (EnergyPlus)")
    for d in range(1, 7):
        ax.axvline(24 * d, color="#cccccc", lw=0.4, zorder=0)
    ax.set_xticks(np.arange(0, 168, 24) + 12)
    ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(0, 167)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("normalized load (peak = 1)")
    ax.text(0.985, 0.06, f"{ARCH} / {SIZE}, CZ {CZ} · weekly-shape $r$ = {corr:.2f}",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=6.3,
            color="#222222")
    ax.legend(loc="upper right", frameon=False, fontsize=6.3,
              handlelength=1.6, borderaxespad=0.1)
    ax.tick_params(length=2)
    _save(fig, "fig4_load.pdf")


# ────────────────────────────────────────────────────────────────────
# Fig 5 — TSTR/TRTR ratio bars
# ────────────────────────────────────────────────────────────────────

def fig5_tstr() -> None:
    acn = json.loads(TSTR_ACN.read_text())
    ela = json.loads(TSTR_ELAADNL.read_text())

    def ratio(d, block):
        r = d[block]["TSTR_over_TRTR_ratio"]
        return float(r["mae"]), float(r["rmse"])

    rows = [
        ("ACN\nlagged\nraw", *ratio(acn, "results_lagged")),
        ("ACN\ncalendar\nraw", *ratio(acn, "results_calendar_only")),
        ("ElaadNL\nlagged\nraw", *ratio(ela, "results_lagged")),
        ("ElaadNL\nlagged\nnorm.", *ratio(ela, "results_lagged_normalized")),
        ("ElaadNL\ncalendar\nraw", *ratio(ela, "results_calendar_only")),
        ("ElaadNL\ncalendar\nnorm.", *ratio(ela, "results_calendar_only_normalized")),
    ]

    labels = [r[0] for r in rows]
    mae = np.array([r[1] for r in rows])
    rmse = np.array([r[2] for r in rows])
    x = np.arange(len(rows))
    bw = 0.38

    fig, ax = plt.subplots(figsize=(3.3, 2.3))
    b1 = ax.bar(x - bw / 2, mae, bw, color=NAVY, label="MAE ratio", zorder=2)
    b2 = ax.bar(x + bw / 2, rmse, bw, color=AMBER, label="RMSE ratio", zorder=2)
    ax.axhline(1.0, color="#333333", lw=0.9, ls="--", zorder=3)
    ax.text(1.5, 1.04, "parity", fontsize=6.0, color="#333333",
            va="bottom", ha="center", zorder=4)

    ax.set_yscale("log")
    ax.set_ylim(0.4, 12)
    ax.set_yticks([0.5, 1, 2, 4, 8])
    ax.set_yticklabels(["0.5", "1", "2", "4", "8"])
    ax.set_ylabel("TSTR / TRTR error ratio")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.0, linespacing=1.15)
    for bars in (b1, b2):
        for rect in bars:
            v = rect.get_height()
            ax.text(rect.get_x() + rect.get_width() / 2, v * 1.07,
                    f"{v:.2f}", ha="center", va="bottom", fontsize=5.2,
                    color="#222222")
    ax.legend(loc="upper left", frameon=False, fontsize=6.3,
              handlelength=1.2, borderaxespad=0.1)
    ax.grid(True, axis="y", which="major", linewidth=0.3, color="#cccccc",
            alpha=0.6, zorder=0)
    ax.tick_params(length=2)
    _save(fig, "fig5_tstr.pdf")


# ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-fig4", action="store_true",
                    help="skip the EnergyPlus-cache-backed fig 4 (emit placeholder)")
    args = ap.parse_args(argv)

    plt.rcParams.update(BASE_RC)
    print("rendering paper figures ->", OUT)
    fig1_pipeline()
    fig2_axes()
    fig3_arrival()
    fig4_load(skip=args.skip_fig4)
    fig5_tstr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
