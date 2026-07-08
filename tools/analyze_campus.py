#!/usr/bin/env python3
"""Fundamental + uncertainty analysis of the 10-building San Jose campus dataset
(building-major layout: data/output/campus10/b1 .. b10, each 12 months x 150
samples = 1,800 monthly samples, output noise = clean, per-building weather
perturbation). Streams every sample per building, extracts per-sample summary
metrics across all streams (building load, PV, net load, EV sessions, grid
prices, DR, weather), quantifies cross-sample UNCERTAINTY per building and rolls
up to a campus view, then renders a single self-contained HTML report.

Adapted from tools/analyze_overnight.py. Unlike that (single building, fixed
N_CHARGERS/PV), charger count and PV rating are read PER BUILDING from each
sample's chargers.csv / pv.csv.

Run:  uv run python tools/analyze_campus.py
Out:  data/output/campus10/analysis.html  (+ analysis_summary.csv)
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "output" / "campus10"
OUT_HTML = BASE / "analysis.html"
OUT_CSV = BASE / "analysis_summary.csv"
TICK_H = 0.25  # 15-min
NAVY, AMBER, GREEN, GREY = "#1f4e79", "#d8853b", "#2ca02c", "#888888"
MONTH_ORDER = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
# 10 distinct colors for per-building traces
BLDG_COLORS = plt.get_cmap("tab10").colors


def _read(p):
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def _building_specs(bdir: Path) -> dict:
    """Read this building's static spec (charger count, PV kW, battery kWh,
    building type) from the first available sample. Returns a dict; missing
    pieces default sensibly."""
    spec = {"n_chargers": 0, "pv_dc_kw": 0.0, "batt_kwh": 0.0, "batt_type": "none",
            "building": "", "population": "", "weather": "", "ev_count": 0}
    import json
    for cfgp in sorted(bdir.glob("*/*/multi_building_config.json")):
        try:
            c = json.load(open(cfgp))["buildings"][0]
        except Exception:
            continue
        d = c.get("descriptors", {}); o = c.get("overrides", {})
        spec["building"] = d.get("building", "")
        spec["population"] = d.get("population", "")
        spec["weather"] = c.get("weather_profile") or ""
        spec["ev_count"] = int(o.get("ev_fleet.ev_count", 0) or 0)
        spec["batt_type"] = str(o.get("battery.battery_type", "none"))
        break
    for chp in sorted(bdir.glob("*/*/chargers.csv")):
        ch = _read(chp)
        if ch is not None:
            spec["n_chargers"] = int(len(ch))
            break
    for pvp in sorted(bdir.glob("*/*/pv.csv")):
        pv = _read(pvp)
        if pv is not None and len(pv):
            for col in ("dc_capacity_kw", "nameplate_dc_kw", "capacity_kw"):
                if col in pv.columns:
                    spec["pv_dc_kw"] = float(pv[col].iloc[0]); break
            break
    for btp in sorted(bdir.glob("*/*/battery.csv")):
        bt = _read(btp)
        if bt is not None and len(bt):
            for col in ("capacity_kwh", "usable_kwh", "energy_kwh"):
                if col in bt.columns:
                    spec["batt_kwh"] = float(bt[col].iloc[0]); break
            break
    return spec


def sample_metrics(d: Path, n_chargers: int, pv_dc_kw: float) -> dict | None:
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
        if pv_dc_kw > 0:
            m["pv_capacity_factor"] = float(np.mean(pvp) / pv_dc_kw)
    n = min(len(load), len(pvp))
    net = load[:n] - pvp[:n]
    m["net_peak_kw"] = float(np.max(net))
    m["net_min_kw"] = float(np.min(net))  # <0 ⇒ export
    pv_sum = float(np.sum(pvp[:n]))
    m["pv_self_consumption"] = float(np.sum(np.minimum(load[:n], pvp[:n])) / pv_sum) if pv_sum else np.nan

    # grid prices → building energy cost ($)
    gp = _read(d / "grid_prices.csv")
    if gp is not None and "price_per_kwh" in gp.columns:
        price = gp["price_per_kwh"].to_numpy(float)
        k = min(len(price), len(load))
        m["energy_cost_usd"] = float(np.sum(load[:k] * TICK_H * price[:k]))
        m["net_cost_usd"] = float(np.sum(np.maximum(net[:k], 0.0) * TICK_H * price[:k]))

    # weather
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
            dur_h = dur / 3600.0 if dur.median() > 100 else dur
            m["dwell_h_mean"] = float(dur_h.mean())
            grid = pd.date_range(dt.min(), dt.max(), freq="15min")
            occ = np.zeros(len(grid)); base0 = grid[0]
            for a, dh in zip(arr, dur_h):
                if pd.isna(a) or pd.isna(dh):
                    continue
                i0 = int((a - base0).total_seconds() // 900)
                i1 = int((a + pd.Timedelta(hours=float(dh)) - base0).total_seconds() // 900)
                i0 = max(i0, 0); i1 = min(i1, len(occ) - 1)
                if i1 >= i0:
                    occ[i0:i1 + 1] += 1
            m["peak_concurrency"] = int(occ.max()) if len(occ) else 0
            if n_chargers > 0:
                m["concurrency_infeasible_frac"] = float(np.mean(occ > n_chargers))
        if "required_soc_at_depart" in ss.columns:
            m["req_soc_mean"] = float(pd.to_numeric(ss["required_soc_at_depart"], errors="coerce").mean())
        if cars is not None and "capacity_kwh" in cars.columns and "required_soc_at_depart" in ss.columns:
            cap = dict(zip(cars["car_id"], cars["capacity_kwh"]))
            soc0 = dict(zip(cars["car_id"], cars.get("soc", pd.Series(dtype=float))))
            e = 0.0
            for _, r in ss.iterrows():
                c = r["car_id"]
                swing = (float(r["required_soc_at_depart"]) - float(soc0.get(c, 40.0))) / 100.0
                e += max(0.0, swing) * float(cap.get(c, 60.0))
            m["ev_energy_mwh"] = e / 1000.0

    dso = _read(d / "dso_commands.csv")
    if dso is not None:
        m["n_dr_events"] = int(len(dso))
    return m


# ── chart helpers ───────────────────────────────────────────────────────────
def _png(fig) -> str:
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def box_by_building(df, col, title, ylabel):
    """Box-and-whisker of a metric across samples, one box per building."""
    fig, ax = plt.subplots(figsize=(8.4, 3.4))
    blds = [b for b in BUILDING_ORDER if b in set(df.building)]
    data = [df[df.building == b][col].dropna().values if col in df.columns else []
            for b in blds]
    bp = ax.boxplot(data, showfliers=False, patch_artist=True, widths=0.6)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(BLDG_COLORS[i % len(BLDG_COLORS)]); patch.set_alpha(0.65)
    for med in bp["medians"]:
        med.set_color("#222")
    ax.set_xticklabels(blds, fontsize=7, rotation=0)
    ax.set_title(title, fontsize=10); ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=7); ax.grid(axis="y", alpha=0.25)
    return _png(fig)


def cv_by_building(df, col, title, xlabel):
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    blds = [b for b in BUILDING_ORDER if b in set(df.building)]
    cvs = []
    for b in blds:
        v = df[df.building == b][col].dropna() if col in df.columns else pd.Series(dtype=float)
        cvs.append(100 * v.std() / v.mean() if len(v) and v.mean() else 0.0)
    ax.barh(range(len(blds)), cvs, color=[BLDG_COLORS[i % 10] for i in range(len(blds))])
    ax.set_yticks(range(len(blds))); ax.set_yticklabels(blds, fontsize=7)
    ax.invert_yaxis(); ax.set_xlabel(xlabel, fontsize=8)
    ax.set_title(title, fontsize=10); ax.tick_params(labelsize=7); ax.grid(axis="x", alpha=0.25)
    return _png(fig)


def campus_monthly_band(df, col, title, ylabel, color=NAVY):
    """Campus-summed monthly band: sum per-building medians per month."""
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    g = df.groupby("month_i")[col]
    med = g.median(); p5 = g.quantile(.05); p95 = g.quantile(.95)
    x = med.index
    ax.fill_between(x, p5, p95, alpha=0.2, color=color, label="P5–P95 (per sample)")
    ax.plot(x, med, "-o", color=color, ms=3, label="median")
    ax.set_xticks(range(12)); ax.set_xticklabels(MONTH_ORDER, fontsize=7, rotation=45)
    ax.set_title(title, fontsize=10); ax.set_ylabel(ylabel, fontsize=8)
    ax.legend(fontsize=7); ax.tick_params(labelsize=7)
    return _png(fig)


# ── stats ───────────────────────────────────────────────────────────────────
def describe(s: pd.Series) -> dict:
    s = s.dropna()
    if not len(s):
        return {k: np.nan for k in ("mean", "std", "cv", "p5", "p50", "p95", "min", "max")} | {"n": 0}
    mean = float(s.mean())
    return {"mean": mean, "std": float(s.std()),
            "cv": float(s.std() / mean) if mean else np.nan,
            "p5": float(s.quantile(.05)), "p50": float(s.quantile(.50)),
            "p95": float(s.quantile(.95)), "min": float(s.min()), "max": float(s.max()),
            "n": int(len(s))}


LABELS = {
    "bl_peak_kw": "Building peak load (kW)", "bl_mean_kw": "Building average load (kW)",
    "bl_min_kw": "Building base/overnight load (kW)",
    "bl_energy_mwh": "Building monthly energy (MWh)", "bl_load_factor": "Load factor (avg ÷ peak)",
    "bl_peak_hour": "Hour of daily peak", "bl_flex_frac": "Flexible (HVAC) load share",
    "pv_energy_mwh": "PV monthly generation (MWh)", "pv_peak_kw": "PV peak output (kW)",
    "pv_capacity_factor": "PV capacity factor (avg ÷ rated)", "net_peak_kw": "Net peak load after PV (kW)",
    "net_min_kw": "Net minimum load (kW; <0 = PV export)", "pv_self_consumption": "PV used on-site (self-consumption)",
    "energy_cost_usd": "Monthly energy cost ($)", "net_cost_usd": "Monthly energy cost after PV ($)",
    "wx_mean_temp_c": "Mean outdoor temperature (°C)", "wx_max_temp_c": "Max outdoor temperature (°C)",
    "wx_mean_ghi": "Mean solar irradiance (W/m²)", "n_sessions": "EV charging sessions / month",
    "sessions_per_day": "EV sessions / day", "arr_hour_mean": "Mean EV arrival hour",
    "dwell_h_mean": "Mean EV dwell time (hours)", "peak_concurrency": "Peak simultaneous EVs charging",
    "concurrency_infeasible_frac": "Time over charger capacity", "req_soc_mean": "Mean required departure SoC (%)",
    "ev_energy_mwh": "EV charging energy / month (MWh)", "n_dr_events": "Demand-response events / month",
}

BUILDING_ORDER: list[str] = []  # filled in main()


def main():
    global BUILDING_ORDER
    bdirs = sorted([p for p in BASE.glob("b*") if p.is_dir()],
                   key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else 999)
    if not bdirs:
        raise SystemExit(f"no building folders b* under {BASE}")
    BUILDING_ORDER = [p.name for p in bdirs]

    specs = {p.name: _building_specs(p) for p in bdirs}
    rows = []
    for p in bdirs:
        sp = specs[p.name]
        for bl in sorted(p.glob("*/*/building_load.csv")):
            d = bl.parent
            mon = d.parent.name  # e.g. JAN2024
            m = sample_metrics(d, sp["n_chargers"], sp["pv_dc_kw"])
            if m is None:
                continue
            m["building"] = p.name
            m["weather"] = sp["weather"]
            m["month"] = mon[:3]
            m["month_i"] = MONTH_ORDER.index(mon[:3]) if mon[:3] in MONTH_ORDER else -1
            m["sample"] = d.name
            rows.append(m)
    df = pd.DataFrame(rows)
    if not len(df):
        raise SystemExit(f"no samples found under {BASE}/b*/<MONTH>/<sample>/")
    df.to_csv(OUT_CSV, index=False)

    metric_cols = [c for c in df.columns
                   if c not in ("building", "weather", "month", "month_i", "sample")]
    # per-building stats
    per_bldg = {b: {c: describe(df[df.building == b][c]) for c in metric_cols}
                for b in BUILDING_ORDER}
    stats_all = {c: describe(df[c]) for c in metric_cols}

    charts = {
        "peak_box": box_by_building(df, "bl_peak_kw", "Building peak load by building", "kW"),
        "energy_box": box_by_building(df, "bl_energy_mwh", "Monthly energy by building", "MWh"),
        "netpeak_box": box_by_building(df, "net_peak_kw", "Net peak (load − PV) by building", "kW"),
        "conc_box": box_by_building(df, "peak_concurrency", "Peak EV concurrency by building", "sessions"),
        "cost_box": box_by_building(df, "energy_cost_usd", "Monthly energy cost by building", "$"),
        "peak_cv": cv_by_building(df, "bl_peak_kw", "Peak-load uncertainty (CV) by building", "CV across samples (%)"),
        "campus_month_energy": campus_monthly_band(df, "bl_energy_mwh", "Per-sample monthly energy (all buildings)", "MWh", NAVY),
        "campus_month_netpeak": campus_monthly_band(df, "net_peak_kw", "Per-sample net peak by month", "kW", GREEN),
    }
    render_html(df, specs, per_bldg, stats_all, charts)
    print(f"wrote {OUT_HTML}  ({len(df)} samples across {len(BUILDING_ORDER)} buildings)")
    print(f"wrote {OUT_CSV}")


def per_building_table(specs, per_bldg):
    """One row per building: static spec + key metric mean (CV)."""
    def mc(b, c):
        s = per_bldg[b].get(c, {})
        mean, cv = s.get("mean", float("nan")), s.get("cv", float("nan"))
        if mean != mean:
            return ""
        cvs = "" if cv != cv else f" <span class='cvs'>±{cv*100:.0f}%</span>"
        return (f"{mean:,.1f}" if abs(mean) >= 10 else f"{mean:.2f}") + cvs
    rows = ""
    for b in BUILDING_ORDER:
        sp = specs[b]
        rows += (
            f"<tr><td class='l'><b>{b}</b></td>"
            f"<td class='l'>{sp['building']}</td>"
            f"<td class='l'>{sp['population']}</td>"
            f"<td class='l'>{sp['weather']}</td>"
            f"<td>{sp['ev_count']}</td><td>{sp['n_chargers']}</td>"
            f"<td>{sp['pv_dc_kw']:.0f}</td><td class='l'>{sp['batt_type']}</td>"
            f"<td>{mc(b,'bl_peak_kw')}</td><td>{mc(b,'bl_energy_mwh')}</td>"
            f"<td>{mc(b,'net_peak_kw')}</td><td>{mc(b,'pv_energy_mwh')}</td>"
            f"<td>{mc(b,'peak_concurrency')}</td><td>{mc(b,'energy_cost_usd')}</td></tr>")
    return (
        "<table><thead><tr>"
        "<th>bldg</th><th class='l'>type</th><th class='l'>population</th><th class='l'>weather</th>"
        "<th>EVs</th><th>chg</th><th>PV kW</th><th class='l'>battery</th>"
        "<th>peak kW</th><th>energy MWh</th><th>net-peak kW</th><th>PV MWh</th>"
        "<th>EV conc.</th><th>cost $</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
        "<p class='muted'>Metric cells show <b>mean</b> across that building's 1,800 samples with <b>±CV</b> "
        "(coefficient of variation = std ÷ mean) — the weather-driven relative uncertainty.</p>")


def render_html(df, specs, per_bldg, stats_all, charts):
    n = len(df); nb = len(BUILDING_ORDER)
    img = lambda k: f"<img src='{charts[k]}' alt='{k}'>"
    # campus headline: sum of per-building P95 peaks (coincident-ish upper bound),
    # and total mean energy.
    sum_peak_p95 = sum(per_bldg[b].get("bl_peak_kw", {}).get("p95", 0) or 0 for b in BUILDING_ORDER)
    sum_netpeak_p95 = sum(per_bldg[b].get("net_peak_kw", {}).get("p95", 0) or 0 for b in BUILDING_ORDER)
    sum_energy_mean = sum(per_bldg[b].get("bl_energy_mwh", {}).get("mean", 0) or 0 for b in BUILDING_ORDER)
    sum_pv_mean = sum(per_bldg[b].get("pv_energy_mwh", {}).get("mean", 0) or 0 for b in BUILDING_ORDER)
    total_pv_kw = sum(specs[b]["pv_dc_kw"] for b in BUILDING_ORDER)
    total_ev = sum(specs[b]["ev_count"] for b in BUILDING_ORDER)
    total_chg = sum(specs[b]["n_chargers"] for b in BUILDING_ORDER)
    n_slight = sum(1 for b in BUILDING_ORDER if specs[b]["weather"] == "slight")
    n_mod = sum(1 for b in BUILDING_ORDER if specs[b]["weather"] == "moderate")

    html = f"""<title>Campus dataset — 10-building uncertainty analysis</title>
<meta name="description" content="Fundamental + uncertainty analysis of the 10-building San Jose synthetic V2B campus ({n} weather-perturbed monthly samples).">
<style>
  :root{{--navy:#1f4e79;--amber:#d8853b;--bg:#fafafa;--surface:#fff;--border:#e0e0e0;--muted:#666;--ink:#222;}}
  *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
  header{{background:var(--navy);color:#fff;padding:1.2rem 2rem}} header h1{{margin:0;font-size:1.5rem}} header p{{margin:.3rem 0 0;opacity:.9;font-size:.9rem}}
  main{{max-width:1120px;margin:0 auto;padding:1.5rem}}
  section{{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:1rem 1.4rem;margin-bottom:1.1rem}}
  h2{{color:var(--navy);font-size:1.15rem;margin:.2rem 0 .6rem;border-bottom:2px solid #eef2f6;padding-bottom:.3rem}}
  h3{{color:var(--navy);font-size:.95rem;margin:1rem 0 .3rem}}
  table{{border-collapse:collapse;width:100%;font-size:.78rem;margin:.3rem 0}}
  th,td{{border:1px solid var(--border);padding:.28rem .5rem;text-align:right;font-variant-numeric:tabular-nums}}
  th{{background:#f0f4f8;color:var(--navy)}} td.l,th.l{{text-align:left}} .cvs{{color:var(--amber);font-weight:600;font-size:.9em}}
  .imgrow{{display:flex;flex-wrap:wrap;gap:.8rem;margin:.6rem 0;justify-content:center}} .imgrow img{{max-width:100%;border:1px solid var(--border);border-radius:4px}}
  .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.5rem 0}}
  .kpi{{background:#f7fafc;border:1px solid var(--border);border-left:4px solid var(--navy);border-radius:5px;padding:.6rem .8rem}}
  .kpi .v{{font-size:1.3rem;font-weight:700;color:var(--navy)}} .kpi .k{{font-size:.72rem;color:var(--muted)}}
  .take{{background:#fff8ef;border:1px solid #f0d9b8;border-left:4px solid var(--amber);border-radius:5px;padding:.6rem .9rem;font-size:.86rem;margin:.5rem 0}}
  .muted{{color:var(--muted);font-size:.82rem}} code{{background:#f0f0f0;padding:0 4px;border-radius:3px;font-size:.85em}}
  .tablewrap{{overflow-x:auto}}
</style>
<header>
  <h1>Synthetic V2B campus — 10-building fundamental &amp; uncertainty analysis</h1>
  <p>San Jose commercial campus · {nb} buildings · {total_ev} EVs / {total_chg} chargers · {total_pv_kw:,.0f} kW PV · output noise <b>clean</b> · per-building weather perturbation ({n_slight} slight + {n_mod} moderate) · {n:,} monthly samples (Jan–Dec, 150/mo/building)</p>
</header>
<main>
  <section>
    <h2>What this dataset is</h2>
    <p class="muted">A commercial campus of <b>{nb} distinct buildings</b> (offices, retail, mixed-use) on one San Jose site, laid out building-major under <code>data/output/campus10/b1 … b{nb}</code>. Each building has <b>1,800 monthly samples</b> (12 months × 150), every sample a <b>physically faithful</b> per-sample weather realization (the EPW is perturbed and EnergyPlus re-run) with <b>no output-side noise</b>. So cross-sample spread is genuine weather-driven (and EV-stochastic) uncertainty. Peak load is <b>not</b> normalized (<code>peak_kw_scaling: false</code>), so peaks move with the weather.</p>
    <div class="kpis">
      <div class="kpi"><div class="v">{sum_peak_p95:,.0f} kW</div><div class="k">Σ building peak (P95, non-coincident upper bound)</div></div>
      <div class="kpi"><div class="v">{sum_netpeak_p95:,.0f} kW</div><div class="k">Σ net peak after PV (P95)</div></div>
      <div class="kpi"><div class="v">{sum_energy_mean:,.0f} MWh</div><div class="k">Campus energy / month (Σ building means)</div></div>
      <div class="kpi"><div class="v">{sum_pv_mean:,.0f} MWh</div><div class="k">Campus PV / month (Σ building means)</div></div>
    </div>
    <div class="take"><b>Σ vs coincident:</b> the campus peaks above sum the <i>per-building</i> P95s, which is a conservative <b>non-coincident</b> upper bound — real coincident campus peak is lower because buildings don't all peak in the same 15-min interval. Size the shared feeder to the coincident peak; size each building's service to its own P95 (per-building table below).</div>
  </section>

  <section>
    <h2>Per-building summary</h2>
    <div class="tablewrap">{per_building_table(specs, per_bldg)}</div>
  </section>

  <section>
    <h2>Building load — how it varies across buildings &amp; samples</h2>
    <div class="imgrow">{img('peak_box')}{img('energy_box')}</div>
    <div class="imgrow">{img('peak_cv')}{img('campus_month_energy')}</div>
    <div class="take"><b>Decision read:</b> box widths show the weather-driven spread of each building's peak/energy across its 1,800 samples; the CV chart ranks which buildings are most weather-sensitive (moderate-weather + HVAC-heavy buildings sit highest). The monthly band shows the seasonal (summer-cooling) envelope every building shares.</div>
  </section>

  <section>
    <h2>PV generation &amp; net load</h2>
    <div class="imgrow">{img('netpeak_box')}{img('campus_month_netpeak')}</div>
    <div class="take"><b>Decision read:</b> net peak (load − PV) per building shows how much PV trims each building's peak — buildings with no PV (see table) show net-peak ≈ gross peak, and are the storage/peak-shaving priorities. On low-PV winter samples PV contributes ≈0 at the peak instant, so <b>storage, not PV, is what cuts peak with confidence</b>.</div>
  </section>

  <section>
    <h2>EV fleet &amp; charging</h2>
    <div class="imgrow">{img('conc_box')}</div>
    <div class="take"><b>Decision read:</b> peak EV concurrency per building tests charger adequacy against each building's installed count (table). Buildings where the concurrency box approaches the charger count have queuing risk; the EV energy demand is the flexible load a V2B optimizer schedules around prices/PV.</div>
  </section>

  <section>
    <h2>Cost exposure</h2>
    <div class="imgrow">{img('cost_box')}</div>
    <div class="take"><b>Decision read:</b> the TOU tariff is deterministic, so per-building monthly cost spread is inherited entirely from load/weather uncertainty — this is each tenant's monthly-bill risk band.</div>
  </section>

  <section class="muted">
    <h2>Provenance</h2>
    <p>Generated by <code>generate-multi</code> from per-building splits of <code>configs/campus_10.yaml</code> (<code>configs/_campus_split/b*.yaml</code>), one batch run per building into <code>data/output/campus10/b1 … b{nb}</code>; <code>--start-month 2024-01 --end-month 2024-12 --samples-per-month 150 --noise-profile clean</code>; per-building <code>weather_profile</code> (slight/moderate). Per-sample summaries in <code>analysis_summary.csv</code>. Every number is reproducible from <code>seed + config</code>.</p>
    <p><b>Notes:</b> EV charging requirements are guaranteed reachable within each session's dwell at the charger rate (D5, strict). <code>weather_data.csv</code> is native EPW <b>hourly</b> while other timeseries are 15-min — resample before joining. Peak scaling is <b>off</b> so magnitudes are raw EnergyPlus output.</p>
  </section>
</main>"""
    OUT_HTML.write_text(html)


if __name__ == "__main__":
    main()
