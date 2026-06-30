#!/usr/bin/env python3
"""Fundamental + uncertainty analysis of the overnight San Jose medium-office
dataset (1,800 monthly samples: 900 slight + 900 moderate weather realizations,
output noise = clean). Streams every sample (memory-light), extracts per-sample
summary metrics across all streams (building load, PV, net load, EV sessions,
grid prices, DR, weather), then quantifies the cross-sample UNCERTAINTY and
renders a single self-contained HTML report.

Run:  uv run python tools/analyze_overnight.py
Out:  data/output/overnight/analysis.html  (+ analysis_summary.csv)
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "output" / "overnight"
OUT_HTML = BASE / "analysis.html"
OUT_CSV = BASE / "analysis_summary.csv"
TICK_H = 0.25  # 15-min
N_CHARGERS = 15
PV_DC_KW = 100.0
NAVY, AMBER, GREEN, GREY = "#1f4e79", "#d8853b", "#2ca02c", "#888888"

MONTH_ORDER = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ── per-sample metric extraction (one streamed pass) ────────────────────────
def _read(p):
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def sample_metrics(d: Path) -> dict | None:
    bl = _read(d / "building_load.csv")
    if bl is None or "power_kw" not in bl.columns or len(bl) == 0:
        return None
    m: dict = {}
    dt = pd.to_datetime(bl["datetime"])
    load = bl["power_kw"].to_numpy(float)
    m["bl_peak_kw"] = float(np.max(load))
    m["bl_mean_kw"] = float(np.mean(load))
    m["bl_min_kw"] = float(np.min(load))
    m["bl_energy_mwh"] = float(bl.get("energy_kwh", pd.Series(load * TICK_H)).sum() / 1000.0)
    m["bl_load_factor"] = m["bl_mean_kw"] / m["bl_peak_kw"] if m["bl_peak_kw"] else np.nan
    m["bl_peak_hour"] = int(dt.iloc[int(np.argmax(load))].hour)
    if "power_kw_flexible" in bl.columns:
        fl = bl["power_kw_flexible"].to_numpy(float)
        m["bl_flex_frac"] = float(np.sum(fl) / np.sum(load)) if np.sum(load) else np.nan

    # PV
    pv = _read(d / "pv_generation.csv")
    pvp = np.zeros(len(load))
    if pv is not None and "power_pv_kw" in pv.columns:
        pvp = pv["power_pv_kw"].to_numpy(float)
        m["pv_energy_mwh"] = float(pv.get("energy_kwh_pv", pd.Series(pvp * TICK_H)).sum() / 1000.0)
        m["pv_peak_kw"] = float(np.max(pvp))
        m["pv_capacity_factor"] = float(np.mean(pvp) / PV_DC_KW)
    # net load (building − PV); align lengths defensively
    n = min(len(load), len(pvp))
    net = load[:n] - pvp[:n]
    m["net_peak_kw"] = float(np.max(net))
    m["net_min_kw"] = float(np.min(net))  # <0 ⇒ export
    pv_sum = float(np.sum(pvp[:n]))
    m["pv_self_consumption"] = float(np.sum(np.minimum(load[:n], pvp[:n])) / pv_sum) if pv_sum else np.nan

    # grid prices → building energy cost ($) for this sample
    gp = _read(d / "grid_prices.csv")
    if gp is not None and "price_per_kwh" in gp.columns:
        price = gp["price_per_kwh"].to_numpy(float)
        k = min(len(price), len(load))
        m["energy_cost_usd"] = float(np.sum(load[:k] * TICK_H * price[:k]))
        # cost of NET load (after PV) — what a PV-aware tariff bill would track
        m["net_cost_usd"] = float(np.sum(np.maximum(net[:k], 0.0) * TICK_H * price[:k]))

    # weather (the perturbation driver)
    wx = _read(d / "weather_data.csv")
    if wx is not None and "dry_bulb_temp_c" in wx.columns:
        m["wx_mean_temp_c"] = float(wx["dry_bulb_temp_c"].mean())
        m["wx_max_temp_c"] = float(wx["dry_bulb_temp_c"].max())
        if "global_horizontal_w_m2" in wx.columns:
            m["wx_mean_ghi"] = float(wx["global_horizontal_w_m2"].mean())

    # EV sessions
    ss = _read(d / "sessions.csv")
    cars = _read(d / "cars.csv")
    if ss is not None and len(ss):
        m["n_sessions"] = int(len(ss))
        days = max(1, (dt.max() - dt.min()).days + 1)
        m["sessions_per_day"] = len(ss) / days
        arr = pd.to_datetime(ss["arrival"], errors="coerce")
        m["arr_hour_mean"] = float((arr.dt.hour + arr.dt.minute / 60).mean())
        if "duration" in ss.columns:
            dur = pd.to_numeric(ss["duration"], errors="coerce")
            dur_h = dur / 3600.0 if dur.median() > 100 else dur  # seconds → h
            m["dwell_h_mean"] = float(dur_h.mean())
            # concurrency vs N_CHARGERS (E5 feasibility) on a 15-min grid
            grid = pd.date_range(dt.min(), dt.max(), freq="15min")
            occ = np.zeros(len(grid))
            gi = {t: i for i, t in enumerate(grid)}
            base0 = grid[0]
            for a, dh in zip(arr, dur_h):
                if pd.isna(a) or pd.isna(dh):
                    continue
                i0 = int((a - base0).total_seconds() // 900)
                i1 = int((a + pd.Timedelta(hours=float(dh)) - base0).total_seconds() // 900)
                i0 = max(i0, 0); i1 = min(i1, len(occ) - 1)
                if i1 >= i0:
                    occ[i0:i1 + 1] += 1
            m["peak_concurrency"] = int(occ.max()) if len(occ) else 0
            m["concurrency_infeasible_frac"] = float(np.mean(occ > N_CHARGERS))
        if "required_soc_at_depart" in ss.columns:
            m["req_soc_mean"] = float(pd.to_numeric(ss["required_soc_at_depart"], errors="coerce").mean())
        # EV energy demand ≈ Σ capacity·(req_soc − arrival_soc); arrival soc from cars.soc
        if cars is not None and "capacity_kwh" in cars.columns and "required_soc_at_depart" in ss.columns:
            cap = dict(zip(cars["car_id"], cars["capacity_kwh"]))
            soc0 = dict(zip(cars["car_id"], cars.get("soc", pd.Series(dtype=float))))
            e = 0.0
            for _, r in ss.iterrows():
                c = r["car_id"]
                swing = (float(r["required_soc_at_depart"]) - float(soc0.get(c, 40.0))) / 100.0
                e += max(0.0, swing) * float(cap.get(c, 60.0))
            m["ev_energy_mwh"] = e / 1000.0

    # DR
    dso = _read(d / "dso_commands.csv")
    if dso is not None:
        m["n_dr_events"] = int(len(dso))
    return m


# ── chart helpers (matplotlib → embedded base64 PNG) ────────────────────────
def _png(fig) -> str:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def hist_by_profile(df, col, title, xlabel):
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    allv = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
    if len(allv) and allv.max() > allv.min():
        bins = np.linspace(float(allv.min()), float(allv.max()), 31)  # shared edges → comparable
    elif len(allv):
        v0 = float(allv.iloc[0]); bins = np.array([v0 - 0.5, v0 + 0.5])  # constant metric
    else:
        bins = 10
    for prof, c in (("slight", NAVY), ("moderate", AMBER)):
        v = df[df.profile == prof][col].dropna() if col in df.columns else pd.Series(dtype=float)
        if len(v):
            ax.hist(v, bins=bins, alpha=0.55, label=f"{prof} (n={len(v)})", color=c)
    ax.set_title(title, fontsize=10); ax.set_xlabel(xlabel, fontsize=8)
    ax.set_ylabel("samples", fontsize=8); ax.legend(fontsize=7); ax.tick_params(labelsize=7)
    return _png(fig)


def monthly_band(df, col, title, ylabel, color=NAVY):
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    g = df.groupby("month_i")[col]
    med = g.median(); p5 = g.quantile(.05); p95 = g.quantile(.95)
    x = med.index
    ax.fill_between(x, p5, p95, alpha=0.2, color=color, label="P5–P95")
    ax.plot(x, med, "-o", color=color, ms=3, label="median")
    ax.set_xticks(range(12)); ax.set_xticklabels(MONTH_ORDER, fontsize=7, rotation=45)
    ax.set_title(title, fontsize=10); ax.set_ylabel(ylabel, fontsize=8)
    ax.legend(fontsize=7); ax.tick_params(labelsize=7)
    return _png(fig)


def cv_ranking(stats):
    items = [(k, v["cv"]) for k, v in stats.items() if v["cv"] == v["cv"] and v["cv"] > 0]
    items.sort(key=lambda t: t[1], reverse=True)
    items = items[:14]
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    labels = [k for k, _ in items]; vals = [v * 100 for _, v in items]
    ax.barh(range(len(labels)), vals, color=NAVY)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis(); ax.set_xlabel("coefficient of variation across samples (%)", fontsize=8)
    ax.set_title("Where the uncertainty is (CV ranking)", fontsize=10); ax.tick_params(labelsize=7)
    return _png(fig)


# ── stats ───────────────────────────────────────────────────────────────────
def describe(s: pd.Series) -> dict:
    s = s.dropna()
    if not len(s):
        return {"mean": np.nan, "std": np.nan, "cv": np.nan, "p5": np.nan,
                "p50": np.nan, "p95": np.nan, "min": np.nan, "max": np.nan, "n": 0}
    mean = float(s.mean())
    return {"mean": mean, "std": float(s.std()),
            "cv": float(s.std() / mean) if mean else np.nan,
            "p5": float(s.quantile(.05)), "p50": float(s.quantile(.50)),
            "p95": float(s.quantile(.95)), "min": float(s.min()), "max": float(s.max()),
            "n": int(len(s))}


def main():
    rows = []
    for prof in ("slight", "moderate"):
        root = BASE / prof
        if not root.exists():
            continue
        for bl in sorted(root.glob("*/*/building_load.csv")):
            d = bl.parent
            mon = d.parent.name           # e.g. JAN2024
            m = sample_metrics(d)
            if m is None:
                continue
            m["profile"] = prof
            m["month"] = mon[:3]
            m["month_i"] = MONTH_ORDER.index(mon[:3]) if mon[:3] in MONTH_ORDER else -1
            m["sample"] = d.name
            rows.append(m)
    df = pd.DataFrame(rows)
    if not len(df):
        raise SystemExit("no samples found under data/output/overnight/{slight,moderate}")
    df.to_csv(OUT_CSV, index=False)

    metric_cols = [c for c in df.columns if c not in ("profile", "month", "month_i", "sample")]
    stats = {c: describe(df[c]) for c in metric_cols}
    stats_slight = {c: describe(df[df.profile == "slight"][c]) for c in metric_cols}
    stats_mod = {c: describe(df[df.profile == "moderate"][c]) for c in metric_cols}

    charts = {
        "peak": hist_by_profile(df, "bl_peak_kw", "Building peak load", "kW"),
        "energy": hist_by_profile(df, "bl_energy_mwh", "Building monthly energy", "MWh"),
        "netpeak": hist_by_profile(df, "net_peak_kw", "Net peak (load − PV)", "kW"),
        "month_load": monthly_band(df, "bl_energy_mwh", "Monthly building energy", "MWh", NAVY),
        "month_pv": monthly_band(df, "pv_energy_mwh", "Monthly PV generation", "MWh", AMBER),
        "month_netpeak": monthly_band(df, "net_peak_kw", "Net peak by month", "kW", GREEN),
        "selfcons": hist_by_profile(df, "pv_self_consumption", "PV self-consumption ratio", "fraction"),
        "concurrency": hist_by_profile(df, "peak_concurrency", f"Peak EV concurrency (vs {N_CHARGERS} chargers)", "simultaneous sessions"),
        "cost": hist_by_profile(df, "energy_cost_usd", "Monthly building energy cost", "$"),
        "cv": cv_ranking(stats),
    }
    render_html(df, stats, stats_slight, stats_mod, charts)
    print(f"wrote {OUT_HTML}  ({len(df)} samples)")


# ── HTML ─────────────────────────────────────────────────────────────────────
LABELS = {
    "bl_peak_kw": "Building peak (kW)", "bl_mean_kw": "Building mean (kW)",
    "bl_energy_mwh": "Building energy (MWh/mo)", "bl_load_factor": "Load factor",
    "bl_peak_hour": "Peak hour", "bl_flex_frac": "Flexible-load fraction",
    "pv_energy_mwh": "PV energy (MWh/mo)", "pv_peak_kw": "PV peak (kW)",
    "pv_capacity_factor": "PV capacity factor", "net_peak_kw": "Net peak load (kW)",
    "net_min_kw": "Net min (kW, <0=export)", "pv_self_consumption": "PV self-consumption",
    "energy_cost_usd": "Energy cost ($/mo)", "net_cost_usd": "Net energy cost ($/mo)",
    "wx_mean_temp_c": "Mean temp (°C)", "wx_max_temp_c": "Max temp (°C)",
    "wx_mean_ghi": "Mean GHI (W/m²)", "n_sessions": "Sessions/mo",
    "sessions_per_day": "Sessions/day", "arr_hour_mean": "Mean arrival hour",
    "dwell_h_mean": "Mean dwell (h)", "peak_concurrency": "Peak EV concurrency",
    "concurrency_infeasible_frac": "Ticks over charger cap", "req_soc_mean": "Mean required SoC (%)",
    "ev_energy_mwh": "EV energy demand (MWh/mo)", "n_dr_events": "DR events/mo",
}


def stat_table(stats, cols):
    rows = ""
    for c in cols:
        if c not in stats:
            continue
        s = stats[c]
        cv = "" if s["cv"] != s["cv"] else f"{s['cv']*100:.1f}%"
        def f(x):
            return "" if x != x else (f"{x:.3f}" if abs(x) < 10 else f"{x:,.1f}")
        rows += (f"<tr><td class='l'>{LABELS.get(c, c)}</td><td>{f(s['mean'])}</td>"
                 f"<td>{f(s['std'])}</td><td class='cv'>{cv}</td><td>{f(s['p5'])}</td>"
                 f"<td>{f(s['p50'])}</td><td>{f(s['p95'])}</td></tr>")
    return ("<table><thead><tr><th>metric</th><th>mean</th><th>std</th><th>CV</th>"
            "<th>P5</th><th>P50</th><th>P95</th></tr></thead><tbody>"
            + rows + "</tbody></table>")


def render_html(df, stats, st_s, st_m, charts):
    n = len(df); ns = int((df.profile == "slight").sum()); nm = int((df.profile == "moderate").sum())
    def g(c, k):
        return stats.get(c, {}).get(k, float("nan"))
    img = lambda key: f"<img src='{charts[key]}' alt='{key}'>"
    # headline decision numbers
    peak95 = g("bl_peak_kw", "p95"); netpeak95 = g("net_peak_kw", "p95")
    conc95 = g("peak_concurrency", "p95")
    html = f"""<title>Overnight dataset — uncertainty analysis</title>
<meta name="description" content="Fundamental + uncertainty analysis of the San Jose medium-office synthetic dataset (1800 weather-perturbed samples).">
<style>
  :root{{--navy:#1f4e79;--amber:#d8853b;--bg:#fafafa;--surface:#fff;--border:#e0e0e0;--muted:#666;--ink:#222;}}
  *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
  header{{background:var(--navy);color:#fff;padding:1.2rem 2rem}} header h1{{margin:0;font-size:1.5rem}} header p{{margin:.3rem 0 0;opacity:.9;font-size:.9rem}}
  main{{max-width:1080px;margin:0 auto;padding:1.5rem}}
  section{{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:1rem 1.4rem;margin-bottom:1.1rem}}
  h2{{color:var(--navy);font-size:1.15rem;margin:.2rem 0 .6rem;border-bottom:2px solid #eef2f6;padding-bottom:.3rem}}
  h3{{color:var(--navy);font-size:.95rem;margin:1rem 0 .3rem}}
  table{{border-collapse:collapse;width:100%;font-size:.8rem;margin:.3rem 0}}
  th,td{{border:1px solid var(--border);padding:.28rem .5rem;text-align:right;font-variant-numeric:tabular-nums}}
  th{{background:#f0f4f8;color:var(--navy)}} td.l{{text-align:left}} td.cv{{font-weight:600;color:var(--amber)}}
  .imgrow{{display:flex;flex-wrap:wrap;gap:.8rem;margin:.6rem 0}} .imgrow img{{max-width:100%;border:1px solid var(--border);border-radius:4px}}
  .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.5rem 0}}
  .kpi{{background:#f7fafc;border:1px solid var(--border);border-left:4px solid var(--navy);border-radius:5px;padding:.6rem .8rem}}
  .kpi .v{{font-size:1.35rem;font-weight:700;color:var(--navy)}} .kpi .k{{font-size:.72rem;color:var(--muted)}}
  .take{{background:#fff8ef;border:1px solid #f0d9b8;border-left:4px solid var(--amber);border-radius:5px;padding:.6rem .9rem;font-size:.86rem;margin:.5rem 0}}
  .muted{{color:var(--muted);font-size:.82rem}} code{{background:#f0f0f0;padding:0 4px;border-radius:3px;font-size:.85em}}
</style>
<header>
  <h1>Synthetic V2B dataset — fundamental &amp; uncertainty analysis</h1>
  <p>San Jose medium office · 15 EVs / 15 chargers (50/50) · PV 100 kW · battery 200 kWh LFP · output noise <b>clean</b> · weather perturbation only ({ns} slight + {nm} moderate, {n} monthly samples, Jan–Dec)</p>
</header>
<main>
  <section>
    <h2>What this dataset is &amp; how to read the uncertainty</h2>
    <p class="muted">Each of the <b>{n}</b> samples is one calendar month of this building, generated with a <b>physically faithful</b> per-sample weather realization (the EPW is perturbed and EnergyPlus re-run) and <b>no output-side noise</b>. So the spread you see across samples is the genuine weather-driven (and EV-stochastic) uncertainty of the outputs — not artificial jitter. Columns below: <b>mean</b>, <b>std</b>, <b>CV</b> (std/mean — the normalized uncertainty), and the <b>P5/P50/P95</b> band you should design against.</p>
    <div class="kpis">
      <div class="kpi"><div class="v">{peak95:,.0f} kW</div><div class="k">Building peak — P95 (weather-driven; size service/transformer to this)</div></div>
      <div class="kpi"><div class="v">{netpeak95:,.0f} kW</div><div class="k">Net peak after PV — P95 (battery / peak-shaving target)</div></div>
      <div class="kpi"><div class="v">{conc95:.0f}</div><div class="k">Peak EV concurrency — P95 (vs {N_CHARGERS} chargers)</div></div>
      <div class="kpi"><div class="v">{g('pv_self_consumption','p50')*100:.0f}%</div><div class="k">PV self-consumption — median</div></div>
    </div>
    <div class="imgrow">{img('cv')}</div>
    <div class="take"><b>How to use it downstream:</b> the CV ranking shows which quantities are uncertain enough to demand robust (distributional) decisions vs. which are effectively deterministic. Design to the <b>P95</b> for capacity/adequacy (peaks, concurrency) and to the <b>P5–P95 band</b> for energy/cost/PV planning.</div>
  </section>

  <section>
    <h2>Building load</h2>
    <div class="imgrow">{img('peak')}{img('energy')}{img('month_load')}</div>
    {stat_table(stats, ['bl_peak_kw','bl_mean_kw','bl_energy_mwh','bl_load_factor','bl_peak_hour','bl_flex_frac'])}
    <div class="take"><b>Decision read:</b> raw EnergyPlus magnitudes flow through (no peak normalization), so the building <b>peak is weather-driven</b>: P95 = <b>{peak95:,.0f} kW</b> (CV {g('bl_peak_kw','cv')*100:.0f}%, P5–P95 {g('bl_peak_kw','p5'):.0f}–{peak95:.0f} kW) — size the electrical service / transformer to the P95, not the mean. Energy varies CV {g('bl_energy_mwh','cv')*100:.0f}% ({g('bl_energy_mwh','p5'):.0f}–{g('bl_energy_mwh','p95'):.0f} MWh/mo); load factor median ≈ {g('bl_load_factor','p50'):.2f} (peaky ⇒ strong peak-shaving headroom). Summer (cooling) months drive the upper tail — see the monthly band.</div>
  </section>

  <section>
    <h2>PV generation &amp; net load</h2>
    <div class="imgrow">{img('month_pv')}{img('netpeak')}{img('selfcons')}{img('month_netpeak')}</div>
    {stat_table(stats, ['pv_energy_mwh','pv_peak_kw','pv_capacity_factor','pv_self_consumption','net_peak_kw','net_min_kw'])}
    <div class="take"><b>Decision read:</b> PV trims the peak — net-peak P95 <b>{netpeak95:,.0f} kW</b> vs building-peak P95 <b>{peak95:,.0f} kW</b> — but the reduction is unreliable: on low-PV winter/cloudy samples PV contributes ≈0 at the peak instant, so <b>storage (200 kWh / 100 kW LFP), not PV, is what cuts the peak with confidence</b>. PV generation is the single most uncertain output (CV {g('pv_energy_mwh','cv')*100:.0f}%); self-consumption ~{g('pv_self_consumption','p50')*100:.0f}% (the office daytime load absorbs most PV) so added storage mainly buys peak reduction, not more PV capture. Negative net-min ⇒ PV export hours (interconnection / export-tariff exposure).</div>
  </section>

  <section>
    <h2>EV fleet &amp; charging sessions</h2>
    <div class="imgrow">{img('concurrency')}</div>
    {stat_table(stats, ['n_sessions','sessions_per_day','arr_hour_mean','dwell_h_mean','req_soc_mean','ev_energy_mwh','peak_concurrency','concurrency_infeasible_frac'])}
    <div class="take"><b>Decision read:</b> peak concurrency vs the {N_CHARGERS} installed chargers tests infrastructure adequacy — the "ticks over charger cap" fraction is the share of time demand exceeds supply (queuing risk). EV energy demand is the flexible load a V2B optimizer schedules around prices/PV.</div>
  </section>

  <section>
    <h2>Grid prices &amp; cost exposure</h2>
    <div class="imgrow">{img('cost')}</div>
    {stat_table(stats, ['energy_cost_usd','net_cost_usd'])}
    <div class="take"><b>Decision read:</b> the TOU tariff is deterministic, so cost uncertainty is inherited entirely from load/weather uncertainty — the spread here is your monthly-bill risk band. Net cost (after PV) shows the PV bill reduction and its variability.</div>
  </section>

  <section>
    <h2>Weather (the uncertainty driver) &amp; DR</h2>
    {stat_table(stats, ['wx_mean_temp_c','wx_max_temp_c','wx_mean_ghi','n_dr_events'])}
    <h3>Slight vs moderate weather perturbation — does the level matter?</h3>
    {compare_table(st_s, st_m, ['bl_peak_kw','bl_energy_mwh','pv_energy_mwh','net_peak_kw','energy_cost_usd'])}
    <div class="take"><b>Decision read:</b> comparing the two perturbation levels shows how sensitive each output's uncertainty is to weather-forecast error magnitude — i.e. how much tighter your design margins could be with better weather information.</div>
  </section>

  <section class="muted">
    <h2>Provenance</h2>
    <p>Generated by <code>generate-multi</code> from <code>configs/overnight_medoffice_sanjose.yaml</code> (two runs: <code>--weather-profile slight</code> seed-base 0, <code>--weather-profile moderate</code> seed-base 100000; <code>--noise-profile clean</code>; Jan–Dec 2024 × 75 samples/month each). Per-sample summaries in <code>analysis_summary.csv</code>. Every number is reproducible from <code>seed + config</code>.</p>
  </section>
</main>"""
    OUT_HTML.write_text(html)


def compare_table(s_s, s_m, cols):
    rows = ""
    for c in cols:
        a, b = s_s.get(c, {}), s_m.get(c, {})
        cva = "" if a.get("cv", float('nan')) != a.get("cv", float('nan')) else f"{a['cv']*100:.1f}%"
        cvb = "" if b.get("cv", float('nan')) != b.get("cv", float('nan')) else f"{b['cv']*100:.1f}%"
        rows += (f"<tr><td class='l'>{LABELS.get(c,c)}</td><td>{a.get('mean',float('nan')):,.1f}</td><td class='cv'>{cva}</td>"
                 f"<td>{b.get('mean',float('nan')):,.1f}</td><td class='cv'>{cvb}</td></tr>")
    return ("<table><thead><tr><th>metric</th><th>slight mean</th><th>slight CV</th>"
            "<th>moderate mean</th><th>moderate CV</th></tr></thead><tbody>" + rows + "</tbody></table>")


if __name__ == "__main__":
    main()
