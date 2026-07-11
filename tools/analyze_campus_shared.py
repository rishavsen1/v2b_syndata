#!/usr/bin/env python3
"""Fundamental + uncertainty analysis for a SHARED-mode campus batch
(generate-multi with output_mode: shared → month-major tree
 <BASE>/<MONTH>2024/<sample>/*.csv, every CSV carrying a building_id column;
 dso_commands.csv is campus-wide). This is the sibling of tools/analyze_campus.py
 (which handles the building-major b1..bN tree); the metric formulas are shared,
 only the I/O layer differs — here each sample dir holds ALL buildings stacked,
 split by building_id.

Streams every sample, splits by building_id, extracts per-(building, sample)
summary metrics, quantifies cross-sample uncertainty per building, rolls up to a
campus view, and renders a single self-contained HTML report.

Run:  uv run python tools/analyze_campus_shared.py --base data/output/campus20
Out:  <BASE>/analysis.html  (+ analysis_summary.csv)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")

# reuse the layout-agnostic helpers (charts, stats, labels, colors) from the
# building-major analyzer; only BUILDING_ORDER is injected per run.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_campus as ac  # noqa: E402

TICK_H = ac.TICK_H
MONTH_ORDER = ac.MONTH_ORDER
NAVY, GREEN = ac.NAVY, ac.GREEN


def _grp(df: pd.DataFrame, bid: int) -> pd.DataFrame:
    """Rows of a shared CSV for one building_id (empty frame if absent)."""
    if df is None or "building_id" not in df.columns:
        return df if df is not None else pd.DataFrame()
    return df[df["building_id"] == bid]


def metrics_from_frames(bl, pv, gp, wx, ss, cars, n_dr, n_chargers, pv_dc_kw) -> dict | None:
    """Per-(building, sample) metrics — mirrors analyze_campus.sample_metrics but
    operates on already-filtered DataFrames instead of reading a per-building dir."""
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
    pvp = np.zeros(len(load))
    if pv is not None and "power_pv_kw" in pv.columns and len(pv):
        pvp = pv["power_pv_kw"].to_numpy(float)
        m["pv_energy_mwh"] = float(pv.get("energy_kwh_pv", pd.Series(pvp * TICK_H)).sum() / 1000.0)
        m["pv_peak_kw"] = float(np.max(pvp)) if len(pvp) else 0.0
        if pv_dc_kw > 0:
            m["pv_capacity_factor"] = float(np.mean(pvp) / pv_dc_kw)
    n = min(len(load), len(pvp))
    net = load[:n] - pvp[:n]
    m["net_peak_kw"] = float(np.max(net)) if n else m["bl_peak_kw"]
    m["net_min_kw"] = float(np.min(net)) if n else m["bl_min_kw"]
    pv_sum = float(np.sum(pvp[:n]))
    m["pv_self_consumption"] = float(np.sum(np.minimum(load[:n], pvp[:n])) / pv_sum) if pv_sum else np.nan

    # grid prices → building energy cost ($)
    if gp is not None and "price_per_kwh" in gp.columns and len(gp):
        price = gp["price_per_kwh"].to_numpy(float)
        k = min(len(price), len(load))
        m["energy_cost_usd"] = float(np.sum(load[:k] * TICK_H * price[:k]))
        m["net_cost_usd"] = float(np.sum(np.maximum(net[:k], 0.0) * TICK_H * price[:k]))

    # weather
    if wx is not None and "dry_bulb_temp_c" in wx.columns and len(wx):
        m["wx_mean_temp_c"] = float(wx["dry_bulb_temp_c"].mean())
        m["wx_max_temp_c"] = float(wx["dry_bulb_temp_c"].max())
        if "global_horizontal_w_m2" in wx.columns:
            m["wx_mean_ghi"] = float(wx["global_horizontal_w_m2"].mean())

    # EV sessions
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

    m["n_dr_events"] = int(n_dr)  # campus-wide DR program (same events for all buildings)
    return m


def _read(p):
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def discover_specs(sample_dirs: list[Path]) -> dict[int, dict]:
    """building_id -> static spec (type/population/weather/ev_count from the
    config; n_chargers/pv_dc_kw/batt from the first sample's shared CSVs)."""
    specs: dict[int, dict] = {}
    cfg = None
    for d in sample_dirs:
        p = d / "multi_building_config.json"
        if p.exists():
            cfg = json.load(open(p)); break
    if cfg:
        for b in cfg.get("buildings", []):
            bid = int(b.get("building_id"))
            dd = b.get("descriptors", {}); ov = b.get("overrides", {})
            specs[bid] = {
                "building": dd.get("building", ""),
                "population": dd.get("population", ""),
                "weather": b.get("weather_profile") or "",
                "ev_count": int(ov.get("ev_fleet.ev_count", 0) or 0),
                "batt_type": str(ov.get("battery.battery_type", "none")),
                "pv_type": str(ov.get("pv.pv_type", "none")),
                "n_chargers": 0, "pv_dc_kw": 0.0,
            }
    # n_chargers & pv_dc_kw per building from the first sample that has them
    first = sample_dirs[0]
    ch = _read(first / "chargers.csv")
    if ch is not None and "building_id" in ch.columns:
        for bid, g in ch.groupby("building_id"):
            specs.setdefault(int(bid), {}).update({"n_chargers": int(len(g))})
    pv = _read(first / "pv.csv")
    if pv is not None and "building_id" in pv.columns:
        col = next((c for c in ("dc_capacity_kw", "nameplate_dc_kw", "capacity_kw") if c in pv.columns), None)
        if col:
            for bid, g in pv.groupby("building_id"):
                specs.setdefault(int(bid), {}).update({"pv_dc_kw": float(g[col].sum())})
    # ensure all keys present
    for bid, sp in specs.items():
        sp.setdefault("n_chargers", 0); sp.setdefault("pv_dc_kw", 0.0)
        sp.setdefault("building", ""); sp.setdefault("population", "")
        sp.setdefault("weather", ""); sp.setdefault("ev_count", 0)
        sp.setdefault("batt_type", "none"); sp.setdefault("pv_type", "none")
    return specs


def build_df(base: Path, limit: int | None) -> tuple[pd.DataFrame, dict]:
    sample_dirs = sorted(
        [p for p in base.glob("*2024/*") if p.is_dir() and (p / "building_load.csv").exists()],
        key=lambda p: (p.parent.name, int(p.name) if p.name.isdigit() else 0),
    )
    if not sample_dirs:
        raise SystemExit(f"no <MONTH>2024/<sample>/building_load.csv under {base}")
    if limit:
        sample_dirs = sample_dirs[:limit]
    specs = discover_specs(sample_dirs)

    rows = []
    for d in sample_dirs:
        mon = d.parent.name  # JAN2024
        bl_all = _read(d / "building_load.csv")
        if bl_all is None or "building_id" not in bl_all.columns:
            continue
        pv_all = _read(d / "pv_generation.csv")
        gp_all = _read(d / "grid_prices.csv")
        wx_all = _read(d / "weather_data.csv")
        ss_all = _read(d / "sessions.csv")
        cars_all = _read(d / "cars.csv")
        dso = _read(d / "dso_commands.csv")
        n_dr = int(len(dso)) if dso is not None else 0
        for bid in sorted(bl_all["building_id"].unique()):
            bid = int(bid)
            sp = specs.get(bid, {})
            m = metrics_from_frames(
                _grp(bl_all, bid), _grp(pv_all, bid), _grp(gp_all, bid),
                _grp(wx_all, bid), _grp(ss_all, bid), _grp(cars_all, bid),
                n_dr, sp.get("n_chargers", 0), sp.get("pv_dc_kw", 0.0),
            )
            if m is None:
                continue
            m["building"] = f"b{bid:02d}"
            m["building_id"] = bid
            m["weather"] = sp.get("weather", "")
            m["month"] = mon[:3]
            m["month_i"] = MONTH_ORDER.index(mon[:3]) if mon[:3] in MONTH_ORDER else -1
            m["sample"] = d.name
            rows.append(m)
    df = pd.DataFrame(rows)
    if not len(df):
        raise SystemExit("no per-building samples extracted")
    return df, specs


def per_building_table(specs, per_bldg, order):
    def mc(b, c):
        s = per_bldg[b].get(c, {})
        mean, cv = s.get("mean", float("nan")), s.get("cv", float("nan"))
        if mean != mean:
            return ""
        cvs = "" if cv != cv else f" <span class='cvs'>±{cv*100:.0f}%</span>"
        return (f"{mean:,.1f}" if abs(mean) >= 10 else f"{mean:.2f}") + cvs
    rows = ""
    for b in order:
        bid = int(b[1:])
        sp = specs[bid]
        storage = "both" if sp["pv_type"] != "none" else "none"
        rows += (
            f"<tr><td class='l'><b>{b}</b></td>"
            f"<td class='l'>{sp['building']}</td>"
            f"<td class='l'>{sp['population']}</td>"
            f"<td class='l'>{sp['weather']}</td>"
            f"<td>{sp['ev_count']}</td><td>{sp['n_chargers']}</td>"
            f"<td>{sp['pv_dc_kw']:.0f}</td><td class='l'>{sp['batt_type']}</td>"
            f"<td class='l'>{storage}</td>"
            f"<td>{mc(b,'bl_peak_kw')}</td><td>{mc(b,'bl_energy_mwh')}</td>"
            f"<td>{mc(b,'net_peak_kw')}</td><td>{mc(b,'pv_energy_mwh')}</td>"
            f"<td>{mc(b,'peak_concurrency')}</td><td>{mc(b,'energy_cost_usd')}</td></tr>")
    return (
        "<table><thead><tr>"
        "<th>bldg</th><th class='l'>type</th><th class='l'>population</th><th class='l'>weather</th>"
        "<th>EVs</th><th>chg</th><th>PV kW</th><th class='l'>battery</th><th class='l'>storage</th>"
        "<th>peak kW</th><th>energy MWh</th><th>net-peak kW</th><th>PV MWh</th>"
        "<th>EV conc.</th><th>cost $</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
        "<p class='muted'>Metric cells show <b>mean</b> across that building's samples with <b>±CV</b> "
        "(std ÷ mean) — the weather/EV-driven relative uncertainty. <b>storage</b>=both means PV+battery, "
        "none means neither (the PV⟺battery invariant this campus enforces).</p>")


def render_html(base: Path, df, specs, per_bldg, charts, order, nb):
    n = len(df)
    n_samples = df[["month", "sample"]].drop_duplicates().shape[0]
    img = lambda k: f"<img src='{charts[k]}' alt='{k}'>"
    g = lambda b, c, k: (per_bldg[b].get(c, {}).get(k, 0) or 0)
    sum_peak_p95 = sum(g(b, "bl_peak_kw", "p95") for b in order)
    sum_netpeak_p95 = sum(g(b, "net_peak_kw", "p95") for b in order)
    sum_energy_mean = sum(g(b, "bl_energy_mwh", "mean") for b in order)
    sum_pv_mean = sum(g(b, "pv_energy_mwh", "mean") for b in order)
    total_pv_kw = sum(specs[int(b[1:])]["pv_dc_kw"] for b in order)
    total_ev = sum(specs[int(b[1:])]["ev_count"] for b in order)
    total_chg = sum(specs[int(b[1:])]["n_chargers"] for b in order)
    n_slight = sum(1 for b in order if specs[int(b[1:])]["weather"] == "slight")
    n_mod = sum(1 for b in order if specs[int(b[1:])]["weather"] == "moderate")
    n_der = sum(1 for b in order if specs[int(b[1:])]["pv_type"] != "none")
    n_bare = nb - n_der

    html = f"""<title>Campus dataset — {nb}-building uncertainty analysis</title>
<meta name="description" content="Fundamental + uncertainty analysis of the {nb}-building San Jose synthetic V2B campus ({n_samples:,} shared-mode monthly samples).">
<style>
  :root{{--navy:#1f4e79;--amber:#d8853b;--bg:#fafafa;--surface:#fff;--border:#e0e0e0;--muted:#666;--ink:#222;}}
  *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
  header{{background:var(--navy);color:#fff;padding:1.2rem 2rem}} header h1{{margin:0;font-size:1.5rem}} header p{{margin:.3rem 0 0;opacity:.9;font-size:.9rem}}
  main{{max-width:1120px;margin:0 auto;padding:1.5rem}}
  section{{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:1rem 1.4rem;margin-bottom:1.1rem}}
  h2{{color:var(--navy);font-size:1.15rem;margin:.2rem 0 .6rem;border-bottom:2px solid #eef2f6;padding-bottom:.3rem}}
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
  <h1>Synthetic V2B campus — {nb}-building fundamental &amp; uncertainty analysis</h1>
  <p>San Jose commercial campus · {nb} buildings ({n_der} PV+battery / {n_bare} storage-free) · {total_ev} EVs / {total_chg} chargers · {total_pv_kw:,.0f} kW PV · output noise <b>clean</b> · per-building weather ({n_slight} slight + {n_mod} moderate) · {n_samples:,} monthly samples (Jan–Dec, 150/mo)</p>
</header>
<main>
  <section>
    <h2>What this dataset is</h2>
    <p class="muted">A commercial campus of <b>{nb} buildings</b> (offices, retail, mixed-use) on one San Jose site, generated in <b>shared mode</b> under <code>{base}/&lt;MONTH&gt;2024/&lt;sample&gt;/</code> — every sample holds all {nb} buildings stacked in one set of CSVs tagged by <code>building_id</code>, plus one campus-wide <code>dso_commands.csv</code>. Each (month, sample) is a <b>physically faithful</b> per-building weather realization (EPW perturbed, EnergyPlus re-run) with <b>no output-side noise</b>, so cross-sample spread is genuine weather-driven (and EV-stochastic) uncertainty. Peak load is <b>not</b> normalized (<code>peak_kw_scaling: false</code>). This campus enforces the <b>PV⟺battery</b> invariant: every building has both or neither.</p>
    <div class="kpis">
      <div class="kpi"><div class="v">{sum_peak_p95:,.0f} kW</div><div class="k">Σ building peak (P95, non-coincident upper bound)</div></div>
      <div class="kpi"><div class="v">{sum_netpeak_p95:,.0f} kW</div><div class="k">Σ net peak after PV (P95)</div></div>
      <div class="kpi"><div class="v">{sum_energy_mean:,.0f} MWh</div><div class="k">Campus energy / month (Σ building means)</div></div>
      <div class="kpi"><div class="v">{sum_pv_mean:,.0f} MWh</div><div class="k">Campus PV / month (Σ building means)</div></div>
    </div>
    <div class="take"><b>Σ vs coincident:</b> the campus peaks above sum the <i>per-building</i> P95s — a conservative <b>non-coincident</b> upper bound; real coincident campus peak is lower because buildings don't all peak in the same 15-min interval. Size the shared feeder to the coincident peak; size each building's service to its own P95 (table below).</div>
  </section>

  <section>
    <h2>Per-building summary</h2>
    <div class="tablewrap">{per_building_table(specs, per_bldg, order)}</div>
  </section>

  <section>
    <h2>Building load — variation across buildings &amp; samples</h2>
    <div class="imgrow">{img('peak_box')}{img('energy_box')}</div>
    <div class="imgrow">{img('peak_cv')}{img('campus_month_energy')}</div>
    <div class="take"><b>Decision read:</b> box widths show the weather-driven spread of each building's peak/energy across its samples; the CV chart ranks weather sensitivity (moderate-weather + HVAC-heavy buildings highest). The monthly band shows the seasonal (summer-cooling) envelope.</div>
  </section>

  <section>
    <h2>Net load after PV &amp; EV concurrency</h2>
    <div class="imgrow">{img('netpeak_box')}{img('conc_box')}</div>
    <div class="imgrow">{img('cost_box')}{img('campus_month_netpeak')}</div>
    <div class="take"><b>Storage-equipped vs storage-free:</b> buildings with PV pull net-peak down and can push net-min below zero (export); storage-free buildings track raw load. EV concurrency vs charger count flags where simultaneous demand approaches installed capacity.</div>
  </section>

  <p class="muted">Generated by <code>tools/analyze_campus_shared.py</code>. Per-sample metrics in <code>analysis_summary.csv</code>.</p>
</main>"""
    (base / "analysis.html").write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="campus output dir (e.g. data/output/campus20)")
    ap.add_argument("--limit", type=int, default=None, help="limit sample dirs (smoke test)")
    args = ap.parse_args()
    base = Path(args.base).resolve()

    df, specs = build_df(base, args.limit)
    order = sorted(df["building"].unique())
    ac.BUILDING_ORDER = order  # inject for the reused chart helpers
    nb = len(order)

    df.to_csv(base / "analysis_summary.csv", index=False)
    metric_cols = [c for c in df.columns
                   if c not in ("building", "building_id", "weather", "month", "month_i", "sample")]
    per_bldg = {b: {c: ac.describe(df[df.building == b][c]) for c in metric_cols} for b in order}

    charts = {
        "peak_box": ac.box_by_building(df, "bl_peak_kw", "Building peak load by building", "kW"),
        "energy_box": ac.box_by_building(df, "bl_energy_mwh", "Monthly energy by building", "MWh"),
        "netpeak_box": ac.box_by_building(df, "net_peak_kw", "Net peak (load − PV) by building", "kW"),
        "conc_box": ac.box_by_building(df, "peak_concurrency", "Peak EV concurrency by building", "sessions"),
        "cost_box": ac.box_by_building(df, "energy_cost_usd", "Monthly energy cost by building", "$"),
        "peak_cv": ac.cv_by_building(df, "bl_peak_kw", "Peak-load uncertainty (CV) by building", "CV across samples (%)"),
        "campus_month_energy": ac.campus_monthly_band(df, "bl_energy_mwh", "Per-sample monthly energy (all buildings)", "MWh", NAVY),
        "campus_month_netpeak": ac.campus_monthly_band(df, "net_peak_kw", "Per-sample net peak by month", "kW", GREEN),
    }
    render_html(base, df, specs, per_bldg, charts, order, nb)
    print(f"wrote {base/'analysis.html'}  ({len(df)} rows, {nb} buildings, "
          f"{df[['month','sample']].drop_duplicates().shape[0]} samples)")
    print(f"wrote {base/'analysis_summary.csv'}")


if __name__ == "__main__":
    main()
