"""Per-parameter uncertainty + correlation structure of a campus corpus.

Streams every unit of a building-major tree (``<root>/b*/<MONTH>/<sample>/``),
extracts per-sample summary metrics, then reports:

1. **Uncertainty per parameter** — mean, sd, CV, IQR and p5–p95 range, both
   campus-wide and decomposed into the three sources of spread:
     * ``within (building, month)``  — pure stochastic: weather realization +
       per-sample seed. This is the dataset's irreducible sampling uncertainty.
     * ``across months`` (building-month means) — seasonal signal.
     * ``across buildings`` (building means) — design/configuration signal.
   Reported as variance shares, so "how uncertain is this parameter, and why"
   is answerable per metric.
2. **Correlation structure** — Spearman matrix over the metrics (rank-based:
   robust to the skewed energy/peak marginals), plus the strongest pairs.

Run on either corpus:
  uv run python tools/campus/campus_uncertainty.py data/output/campus_base --tag strong
  uv run python tools/campus/campus_uncertainty.py data/output/campus_base_moderate --tag moderate

Writes <out-dir>/campus_uncertainty_<tag>.{csv,corr.csv,png}.
"""
from __future__ import annotations

import argparse
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TICK_H = 0.25

# metric -> human label (order drives the report)
METRICS = {
    "bl_peak_kw": "building peak (kW)",
    "bl_mean_kw": "building mean (kW)",
    "bl_energy_mwh": "building energy (MWh)",
    "bl_load_factor": "load factor",
    "pv_energy_mwh": "PV energy (MWh)",
    "pv_capacity_factor": "PV capacity factor",
    "net_peak_kw": "net peak (kW)",
    "net_min_kw": "net min (kW, <0 export)",
    "wx_mean_temp_c": "mean dry-bulb (degC)",
    "wx_mean_ghi": "mean GHI (W/m2)",
    "n_sessions": "EV sessions",
    "ev_energy_mwh": "EV energy (MWh)",
    "arr_hour_mean": "mean arrival hour",
    "dwell_h_mean": "mean dwell (h)",
    "req_soc_mean": "mean required SoC (%)",
    "peak_concurrency": "peak concurrent EVs",
}


def _num(df, col):
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)


def unit_metrics(d: Path) -> dict | None:
    """Vectorized per-unit metrics. Returns None if the unit is unreadable."""
    try:
        bl = pd.read_csv(d / "building_load.csv")
    except Exception:
        return None
    lcol = next((c for c in bl.columns if "kw" in c.lower() or "power" in c.lower()), None)
    if lcol is None:
        return None
    load = _num(bl, lcol)
    m: dict = {"building": d.parents[1].name, "month": d.parent.name, "sample": d.name}
    m["bl_peak_kw"] = float(np.nanmax(load))
    m["bl_mean_kw"] = float(np.nanmean(load))
    m["bl_energy_mwh"] = float(np.nansum(load) * TICK_H / 1000.0)
    m["bl_load_factor"] = m["bl_mean_kw"] / m["bl_peak_kw"] if m["bl_peak_kw"] else np.nan

    pvp = np.zeros_like(load)
    try:
        pv = pd.read_csv(d / "pv_generation.csv")
        pcol = next((c for c in pv.columns if "kw" in c.lower() or "power" in c.lower()), None)
        if pcol is not None:
            p = _num(pv, pcol)
            pvp = p[: len(load)] if len(p) >= len(load) else np.pad(p, (0, len(load) - len(p)))
            m["pv_energy_mwh"] = float(np.nansum(p) * TICK_H / 1000.0)
            spec = pd.read_csv(d / "pv.csv")
            dc = float(spec["dc_capacity_kw"].iloc[0]) if "dc_capacity_kw" in spec else np.nan
            if dc and dc > 0:
                m["pv_capacity_factor"] = float(np.nanmean(p) / dc)
    except Exception:
        pass
    net = load - pvp
    m["net_peak_kw"] = float(np.nanmax(net))
    m["net_min_kw"] = float(np.nanmin(net))

    try:
        wx = pd.read_csv(d / "weather_data.csv")
        if "dry_bulb_temp_c" in wx:
            m["wx_mean_temp_c"] = float(_num(wx, "dry_bulb_temp_c").mean())
        if "global_horizontal_w_m2" in wx:
            m["wx_mean_ghi"] = float(_num(wx, "global_horizontal_w_m2").mean())
    except Exception:
        pass

    try:
        ss = pd.read_csv(d / "sessions_soc.csv")
        cars = pd.read_csv(d / "cars.csv").set_index("car_id")["capacity_kwh"]
        if len(ss):
            m["n_sessions"] = int(len(ss))
            arr = pd.to_datetime(ss["arrival"], errors="coerce")
            dep = pd.to_datetime(ss["departure"], errors="coerce")
            m["arr_hour_mean"] = float((arr.dt.hour + arr.dt.minute / 60).mean())
            dwell = (dep - arr).dt.total_seconds() / 3600.0
            m["dwell_h_mean"] = float(dwell.mean())
            m["req_soc_mean"] = float(_num(ss, "departure_soc").mean())
            cap = ss["car_id"].map(cars).to_numpy(dtype=float)
            gap = (_num(ss, "departure_soc") - _num(ss, "arrival_soc")) / 100.0
            m["ev_energy_mwh"] = float(np.nansum(np.clip(gap, 0, None) * cap) / 1000.0)
            # peak concurrency on the 15-min grid, vectorized via a +1/-1 sweep
            t0 = arr.min().floor("15min")
            i0 = ((arr - t0).dt.total_seconds() // 900).to_numpy(dtype=int)
            i1 = ((dep - t0).dt.total_seconds() // 900).to_numpy(dtype=int)
            n = int(max(i1.max(), i0.max())) + 2
            delta = np.zeros(n)
            np.add.at(delta, np.clip(i0, 0, n - 1), 1)
            np.add.at(delta, np.clip(i1, 0, n - 1), -1)
            m["peak_concurrency"] = int(np.cumsum(delta).max())
    except Exception:
        pass
    return m


def collect(root: Path, workers: int, max_units: int | None) -> pd.DataFrame:
    units = []
    for b in sorted(root.glob("b*"), key=lambda p: int(p.name[1:])):
        u = sorted(b.glob("*/*"))
        units.extend(u[:max_units] if max_units else u)
    print(f"streaming {len(units):,} units from {root} on {workers} workers …")
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(unit_metrics, units, chunksize=32), 1):
            if r:
                rows.append(r)
            if i % 4000 == 0:
                print(f"  {i:,}/{len(units):,}")
    return pd.DataFrame(rows)


def variance_decomposition(df: pd.DataFrame, col: str) -> dict:
    """Split total variance into building / month-within-building / residual."""
    s = df[["building", "month", col]].dropna()
    if s[col].nunique() < 2:
        return {}
    grand = s[col].mean()
    bmean = s.groupby("building")[col].mean()
    bm_mean = s.groupby(["building", "month"])[col].mean()
    n_tot = len(s)
    ss_total = float(((s[col] - grand) ** 2).sum())
    if ss_total <= 0:
        return {}
    ss_b = float(sum(len(g) * (bmean[b] - grand) ** 2 for b, g in s.groupby("building")))
    ss_m = float(sum(len(g) * (bm_mean[k] - bmean[k[0]]) ** 2
                     for k, g in s.groupby(["building", "month"])))
    ss_r = ss_total - ss_b - ss_m
    q = s[col].quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    # within-cell spread = the dataset's irreducible sampling uncertainty
    within = s.groupby(["building", "month"])[col].std().mean()
    within_cv = s.groupby(["building", "month"]).apply(
        lambda g: g[col].std() / abs(g[col].mean()) if g[col].mean() else np.nan).mean()
    return {
        "metric": col, "label": METRICS.get(col, col), "n": n_tot,
        "mean": s[col].mean(), "sd": s[col].std(),
        "cv": s[col].std() / abs(grand) if grand else np.nan,
        "p5": q[0.05], "p50": q[0.5], "p95": q[0.95],
        "iqr": q[0.75] - q[0.25], "range_p5_p95": q[0.95] - q[0.05],
        "within_cell_sd": within, "within_cell_cv": within_cv,
        "var_share_building": ss_b / ss_total,
        "var_share_month": ss_m / ss_total,
        "var_share_sampling": ss_r / ss_total,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--max-units-per-building", type=int, default=None)
    ap.add_argument("--out-dir", type=Path, default=REPO / "docs/experiments")
    a = ap.parse_args(argv)

    df = collect(a.root, a.workers, a.max_units_per_building)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    cols = [c for c in METRICS if c in df.columns]
    # Raw per-unit metrics: the reusable artifact for any downstream slice
    # (per-building, per-month, episode-to-episode). Kept out of docs/ (large).
    raw = REPO / "data" / "output" / f"campus_metrics_{a.tag}.csv"
    df.to_csv(raw, index=False)
    print(f"saved raw per-unit metrics: {raw}  ({len(df):,} rows)")

    # Per-(building, month) episode spread — how much one episode differs from
    # another with the SAME building and month (weather realization + seed only).
    ep = []
    for (b, mo), g in df.groupby(["building", "month"]):
        for c in cols:
            v = g[c].dropna()
            if len(v) < 5 or v.nunique() < 2:
                continue
            q = v.quantile([0.05, 0.5, 0.95])
            ep.append({"building": b, "month": mo, "metric": c,
                       "label": METRICS.get(c, c), "n_episodes": len(v),
                       "mean": v.mean(), "sd": v.std(),
                       "cv": v.std() / abs(v.mean()) if v.mean() else np.nan,
                       "p5": q[0.05], "p50": q[0.5], "p95": q[0.95],
                       "range_p5_p95": q[0.95] - q[0.05],
                       "rel_range": (q[0.95] - q[0.05]) / abs(v.mean()) if v.mean() else np.nan})
    ep_df = pd.DataFrame(ep)
    ep_df.to_csv(a.out_dir / f"campus_episode_spread_{a.tag}.csv", index=False)
    print(f"saved per-(building,month) episode spread: "
          f"campus_episode_spread_{a.tag}.csv ({len(ep_df):,} rows)")

    unc = pd.DataFrame([variance_decomposition(df, c) for c in cols]).dropna(subset=["metric"])
    unc.to_csv(a.out_dir / f"campus_uncertainty_{a.tag}.csv", index=False)

    corr = df[cols].corr(method="spearman")
    corr.to_csv(a.out_dir / f"campus_uncertainty_{a.tag}.corr.csv")

    fig, ax = plt.subplots(1, 2, figsize=(19, 8),
                           gridspec_kw={"width_ratios": [1.15, 1]})
    im = ax[0].imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax[0].set_xticks(range(len(cols)))
    ax[0].set_xticklabels([METRICS[c] for c in cols], rotation=90, fontsize=8)
    ax[0].set_yticks(range(len(cols)))
    ax[0].set_yticklabels([METRICS[c] for c in cols], fontsize=8)
    for i in range(len(cols)):
        for j in range(len(cols)):
            v = corr.iloc[i, j]
            if abs(v) >= 0.3 and i != j:
                ax[0].text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6,
                           color="white" if abs(v) > 0.6 else "black")
    ax[0].set_title(f"Spearman correlation — {a.tag} corpus (n={len(df):,} units)",
                    fontsize=11, loc="left")
    fig.colorbar(im, ax=ax[0], fraction=0.046)

    u = unc.sort_values("var_share_sampling")
    y = np.arange(len(u))
    ax[1].barh(y, u["var_share_building"], color="#1f4e79", label="between buildings (design)")
    ax[1].barh(y, u["var_share_month"], left=u["var_share_building"],
               color="#2ca02c", label="between months (seasonal)")
    ax[1].barh(y, u["var_share_sampling"],
               left=u["var_share_building"] + u["var_share_month"],
               color="#d8853b", label="within cell (sampling uncertainty)")
    ax[1].set_yticks(y)
    ax[1].set_yticklabels([f"{r.label}  (CV {r.cv:.2f})" for r in u.itertuples()], fontsize=8)
    ax[1].set_xlim(0, 1)
    ax[1].set_xlabel("share of total variance")
    ax[1].set_title("Where each parameter's spread comes from", fontsize=11, loc="left")
    ax[1].legend(fontsize=8, loc="lower right")

    fig.suptitle(f"campus corpus '{a.tag}' — parameter uncertainty and correlation structure",
                 fontsize=13)
    fig.tight_layout()
    png = a.out_dir / f"campus_uncertainty_{a.tag}.png"
    fig.savefig(png, dpi=120, bbox_inches="tight")
    print(unc[["label", "mean", "cv", "within_cell_cv", "range_p5_p95",
               "var_share_sampling"]].to_string(index=False))
    print(f"\nsaved {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
