#!/usr/bin/env python
"""One-shot reproducibility driver for the KDD paper numbers (WS-F).

Runs, in order, with fixed seeds:

  1. calibration   — tools/validate_calibration.py over the FULL source list
                     (acn, acn_caltech, acn_jpl, acn_office001, elaadnl, evwatts)
                     with --seeds 50 --workers 16 --bootstrap 1000.
                     Regenerates docs/CALIBRATION_RESULTS.md +
                     docs/experiments/s1_fidelity_cis.csv + the S0–S6 CSVs.
  2. buildingload  — tools/validate_buildingload.py (ASHRAE G14 vs NREL
                     ComStock, CZ-5B, peak_kw_scaling off). Regenerates
                     data/buildingload_reference/validation_metrics.json.
  3. tstr_acn      — tools/tstr_forecasting.py --real acn (matched scenario
                     S_acn_caltech, seed 1234) → data/tstr/results.json.
  4. tstr_elaadnl  — tools/tstr_forecasting.py --real elaadnl --normalize
                     (matched scenario S_elaadnl_public_eu, seed 1234)
                     → data/tstr/results_elaadnl_matched.json. One run emits
                     BOTH raw and unit-mean-normalized regimes.
  5. ablation      — mixture / per-region arrival+dwell fit ablation (below)
                     → docs/experiments/mixture_ablation.csv (+ .md) and
                     docs/experiments/sources_summary.csv. Regenerates the
                     "GMM-k mixture" and "pooled-broadcast vs per-region"
                     claims from committed primary sources (the planning-doc
                     0.148→0.073 number had no committed source; whatever this
                     step produces supersedes it).
  6. collect       — consolidates every headline number the paper cites into
                     docs/experiments/PAPER_NUMBERS.md with value, source
                     artifact, generating command, git SHA, and the compute
                     statement.

Determinism contract (the WS-F gate):
  Two consecutive full runs must produce a bit-identical PAPER_NUMBERS.md.
  Everything numeric is seeded (generation: hash-keyed per-node streams;
  bootstrap: seed 20260708 with per-cell hashed sub-streams; TSTR: seed 1234;
  ablation: deterministic EM, no RNG). Wall-clock runtimes are the one
  intrinsically non-deterministic output, so they are RECORDED ONCE into
  docs/experiments/repro_runtimes.json (only written when absent, or when
  --record-runtimes is passed) and PAPER_NUMBERS.md embeds that recorded
  measurement — re-runs then reproduce the file bit-for-bit while the compute
  statement stays a real, measured quantity. PAPER_NUMBERS.md carries no
  timestamps for the same reason (the git SHA pins the revision).

Usage:
    uv run python tools/repro_paper.py                 # full run
    uv run python tools/repro_paper.py --steps collect # rebuild the MD only
    uv run python tools/repro_paper.py --record-runtimes  # re-measure compute

After the WS-F changes are committed, re-run `--steps collect` once so the
embedded git SHA is the final one (artifacts are unchanged; only the SHA line
moves).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

DOCS_EXP = REPO / "docs" / "experiments"
VAL_DIR = REPO / "data" / "calibration_validation"
TSTR_DIR = REPO / "data" / "tstr"
G14_JSON = REPO / "data" / "buildingload_reference" / "validation_metrics.json"
RUNTIMES_JSON = DOCS_EXP / "repro_runtimes.json"
PAPER_NUMBERS = DOCS_EXP / "PAPER_NUMBERS.md"
ABLATION_CSV = DOCS_EXP / "mixture_ablation.csv"
ABLATION_MD = DOCS_EXP / "mixture_ablation.md"
SOURCES_SUMMARY = DOCS_EXP / "sources_summary.csv"
CAMPUS_DIR = REPO / "data" / "output" / "campus10"

# Full calibrated-source list (WS-A caveat): the acn per-site cohorts must be
# included or the regenerated CALIBRATION_RESULTS.md drops them. evwatts is
# supported by the harness (real public 2026 release, port-as-proxy identity)
# and is included since WS-F.
CAL_SOURCES = "acn,acn_caltech,acn_jpl,acn_office001,elaadnl,evwatts"
# Ablation scope: the mixture / per-region claims in the paper are about the
# driver-identity-grounded cohorts (ACN + ElaadNL). evwatts is excluded here
# (port-as-proxy identity; 1.3M-session EM fits add ~20 min for a claim the
# paper does not make about that cohort).
ABLATION_SOURCES = ["acn", "acn_caltech", "acn_jpl", "acn_office001", "elaadnl"]

STEPS = ["calibration", "buildingload", "tstr_acn", "tstr_elaadnl",
         "ablation", "collect"]


def _run(cmd: list[str], name: str) -> None:
    print(f"\n=== [{name}] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=str(REPO))
    if r.returncode != 0:
        raise SystemExit(f"step {name!r} failed (exit {r.returncode})")


def step_calibration(args) -> None:
    _run([sys.executable, str(REPO / "tools" / "validate_calibration.py"),
          "--seeds", str(args.seeds), "--workers", str(args.workers),
          "--sources", CAL_SOURCES, "--bootstrap", str(args.bootstrap)],
         "calibration")


def step_buildingload(args) -> None:
    _run([sys.executable, str(REPO / "tools" / "validate_buildingload.py"),
          "-v"], "buildingload")


def step_tstr_acn(args) -> None:
    _run([sys.executable, str(REPO / "tools" / "tstr_forecasting.py"),
          "--real", "acn", "--out", str(TSTR_DIR / "results.json")],
         "tstr_acn")


def step_tstr_elaadnl(args) -> None:
    _run([sys.executable, str(REPO / "tools" / "tstr_forecasting.py"),
          "--real", "elaadnl", "--normalize",
          "--out", str(TSTR_DIR / "results_elaadnl_matched.json")],
         "tstr_elaadnl")


# ──────────────────────────────────────────────────────────────────────
# Step 5 — mixture / per-region fit ablation (deterministic; no RNG)
# ──────────────────────────────────────────────────────────────────────

def _cdf_from_fit(fit: dict):
    """CDF callable from a distribution_fitter canonical fit dict."""
    import scipy.stats as st

    d = fit["dist"]
    if d == "truncnorm":
        lo, hi = float(fit["trunc_lo"]), float(fit["trunc_hi"])
        mu, sg = fit["mu"], fit["sigma"]
        fz = st.truncnorm((lo - mu) / sg, (hi - mu) / sg, loc=mu, scale=sg)
        return fz.cdf
    if d == "truncnorm_mixture":
        lo, hi = float(fit["trunc_lo"]), float(fit["trunc_hi"])
        comps = [(fit["w1"], fit["mu1"], fit["sigma1"]),
                 (1.0 - fit["w1"], fit["mu2"], fit["sigma2"])]

        def cdf(x):
            return sum(w * st.truncnorm.cdf(x, (lo - m) / s, (hi - m) / s,
                                            loc=m, scale=s)
                       for (w, m, s) in comps)
        return cdf
    if d == "weibull":
        return st.weibull_min(fit["k"], scale=fit["lambda"]).cdf
    if d == "weibull_mixture":
        comps = [(fit["w1"], fit["k1"], fit["lambda1"]),
                 (1.0 - fit["w1"], fit["k2"], fit["lambda2"])]

        def cdf(x):
            return sum(w * st.weibull_min.cdf(x, k, scale=lam)
                       for (w, k, lam) in comps)
        return cdf
    raise ValueError(f"unknown fit dist {d!r}")


def step_ablation(args) -> None:
    """Fit-quality ablation on the SOURCE data (the distribution generation
    samples from), regenerating two paper claims with committed primaries:

      (i)  mixture families: single TruncNorm/Weibull vs the shipped
           mixture-selection rule (2-component iff it beats single by the
           MIXTURE_KS_MARGIN=0.02 gate), per region;
      (ii) per-region fits: a pooled per-source fit broadcast to every region
           (the pre-2026-06 calibration behavior) vs the per-region fit.

    Metric: one-sample KS of the fitted model CDF against the region's source
    sessions (identical to the fitter's own ks_fit_quality definition).
    Deterministic (median-split EM init; no RNG).
    """
    import numpy as np
    import pandas as pd
    import scipy.stats as stats
    from validate_calibration import load_source  # tools/ on sys.path

    from v2b_syndata.calibration.distribution_fitter import (
        ARRIVAL_HI,
        ARRIVAL_LO,
        fit_truncnorm_arrival,
        fit_truncnorm_mixture_arrival,
        fit_weibull_dwell,
        fit_weibull_mixture_dwell,
    )

    t0 = time.perf_counter()
    rows: list[dict] = []
    src_rows: list[dict] = []

    def _fit_shipped(vals, variable):
        if variable == "arrival_hour":
            mix = fit_truncnorm_mixture_arrival(vals)
            single = fit_truncnorm_arrival(vals)
        else:
            mix = fit_weibull_mixture_dwell(vals)
            single = fit_weibull_dwell(vals)
        return single, (mix if mix is not None else single), mix is not None

    for source in ABLATION_SOURCES:
        sd = load_source(source)
        df = sd.sessions_df
        regions = sorted(set(df["region"]) - {"__unassigned__"})

        # sources-summary row (Tab 1 counts + the phi<=0.3 share claim)
        phis = np.array([u.phi for u in sd.users], dtype=float)
        src_rows.append({
            "source": source,
            "n_sessions": int(len(df)),
            "n_users": int(len(sd.users)),
            "n_users_unassigned": int(
                sum(1 for r in sd.user_to_region.values()
                    if r == "__unassigned__")
            ),
            "share_users_phi_le_0.3": float((phis <= 0.3).mean()),
        })

        for variable in ("arrival_hour", "dwell_hours"):
            if variable == "arrival_hour":
                pooled = df[variable].dropna().to_numpy()
                pooled = pooled[(pooled >= ARRIVAL_LO) & (pooled <= ARRIVAL_HI)]
            else:
                pooled = df[variable].dropna().to_numpy()
                pooled = pooled[pooled > 0]
            _, pooled_fit, _pooled_mix = _fit_shipped(pooled, variable)

            for region in regions:
                vals = df.loc[df["region"] == region, variable].dropna().to_numpy()
                if variable == "arrival_hour":
                    vals = vals[(vals >= ARRIVAL_LO) & (vals <= ARRIVAL_HI)]
                else:
                    vals = vals[vals > 0]
                if len(vals) < 60:  # below the mixture gate; skip tiny cells
                    continue
                single, shipped, mix_selected = _fit_shipped(vals, variable)
                if single is None or shipped is None:
                    continue
                ks_single = float(stats.kstest(vals, _cdf_from_fit(single)).statistic)
                ks_shipped = float(stats.kstest(vals, _cdf_from_fit(shipped)).statistic)
                ks_pooled = (
                    float(stats.kstest(vals, _cdf_from_fit(pooled_fit)).statistic)
                    if pooled_fit is not None else float("nan")
                )
                rows.append({
                    "source": source, "region": region, "variable": variable,
                    "n": int(len(vals)),
                    "ks_single": ks_single,
                    "ks_shipped": ks_shipped,
                    "mixture_selected": bool(mix_selected),
                    "ks_pooled_broadcast": ks_pooled,
                    "pooled_fit_family": pooled_fit["dist"] if pooled_fit else "",
                    "shipped_fit_family": shipped["dist"],
                })
                print(f"  {source}/{region}/{variable}: n={len(vals)} "
                      f"single={ks_single:.3f} shipped={ks_shipped:.3f} "
                      f"pooled={ks_pooled:.3f} mix={mix_selected}", flush=True)

    abl = pd.DataFrame(rows)
    DOCS_EXP.mkdir(parents=True, exist_ok=True)
    abl.to_csv(ABLATION_CSV, index=False)
    pd.DataFrame(src_rows).to_csv(SOURCES_SUMMARY, index=False)

    # Companion MD with method + aggregates.
    def agg(sub: pd.DataFrame) -> tuple[float, float, float]:
        return (float(sub["ks_single"].mean()),
                float(sub["ks_shipped"].mean()),
                float(sub["ks_pooled_broadcast"].mean()))

    lines = [
        "# Mixture / per-region fit ablation",
        "",
        "_Auto-generated by `tools/repro_paper.py` (step `ablation`). Do not "
        "edit by hand. Deterministic: median-split EM init, no RNG._",
        "",
        "Metric: one-sample KS of the fitted model CDF vs the region's real "
        "source sessions (arrival filtered to the [4,22] h window; dwell > 0) "
        "— the same `ks_fit_quality` definition the calibration fitter "
        "records, i.e. the fidelity of the distribution generation actually "
        "samples from. Three fits per (source, region, variable) cell:",
        "",
        "- **single**: single-family fit (TruncNorm arrival / Weibull dwell) "
        "on the region's sessions;",
        "- **shipped**: the shipped selection rule — 2-component mixture iff "
        "it beats single by KS ≥ 0.02 (`MIXTURE_KS_MARGIN`), else single;",
        "- **pooled broadcast**: the shipped selection rule fitted on the "
        "source's pooled sessions and broadcast to the region (the "
        "pre-2026-06 calibration behavior).",
        "",
        "This supersedes the uncommitted planning-doc figure "
        "'arrival mean KS 0.148→0.073'.",
        "",
        "| source | variable | cells | mean KS single | mean KS shipped | "
        "mean KS pooled-broadcast | mixture selected |",
        "|---|---|--:|--:|--:|--:|--:|",
    ]
    for source in ABLATION_SOURCES:
        for variable in ("arrival_hour", "dwell_hours"):
            sub = abl[(abl["source"] == source) & (abl["variable"] == variable)]
            if sub.empty:
                continue
            m_single, m_shipped, m_pooled = agg(sub)
            lines.append(
                f"| {source} | {variable} | {len(sub)} | {m_single:.3f} | "
                f"{m_shipped:.3f} | {m_pooled:.3f} | "
                f"{int(sub['mixture_selected'].sum())}/{len(sub)} |"
            )
    lines += ["", "Per-cell values: `mixture_ablation.csv`.", ""]
    ABLATION_MD.write_text("\n".join(lines))
    print(f"ablation done in {time.perf_counter() - t0:.1f}s -> "
          f"{ABLATION_CSV}, {ABLATION_MD}, {SOURCES_SUMMARY}", flush=True)


# ──────────────────────────────────────────────────────────────────────
# Step 6 — collect: PAPER_NUMBERS.md
# ──────────────────────────────────────────────────────────────────────

def _git_sha() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _fmt(x, nd: int = 3) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def _pv_numbers() -> dict[str, str]:
    """Parse the committed PV validation memo (tools/validate_pv.py output)."""
    txt = (DOCS_EXP / "pv_validation.md").read_text()

    def grab(pattern: str) -> str:
        m = re.search(pattern, txt)
        if not m:
            raise SystemExit(f"pv_validation.md: pattern not found: {pattern}")
        return m.group(1)

    monthly = [abs(float(x)) for x in re.findall(
        r"^\| (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \| [\d,]+ \| "
        r"[\d,]+ \| ([+-]\d+\.\d+) \|$", txt, re.M)]
    if len(monthly) != 12:
        raise SystemExit("pv_validation.md: expected 12 monthly rows")
    return {
        "annual_err_pct": grab(r"\*\*Annual energy error\*\* \| \*\*([+-][\d.]+)%\*\*"),
        "annual_ours_kwh": grab(r"Annual energy \(ours\) \| ([\d,]+) kWh"),
        "annual_ref_kwh": grab(r"Annual energy \(PVWatts v8\) \| ([\d,]+) kWh"),
        "cvrmse_pct": grab(r"Hourly CV\(RMSE\) \(all hours\) \| ([\d.]+)%"),
        "nmbe_pct": grab(r"Hourly NMBE \(all hours\) \| ([+-][\d.]+)%"),
        "pearson_r": grab(r"Hourly Pearson r \| ([\d.]+)"),
        "derate_equalized_pct": grab(r"→ \*\*([+-][\d.]+)%\*\*"),
        "monthly_max_abs_err_pct": f"{max(monthly):.2f}",
    }


def _campus_stats() -> dict:
    """Aggregate the reference-corpus batch manifests (b1..b10)."""
    n_total = n_succ = n_fail = 0
    total_errors = total_warnings = units_with_warnings = 0
    dur_sum = 0.0
    dur_n = 0
    buildings = sorted(p for p in CAMPUS_DIR.iterdir()
                       if p.is_dir() and (p / "batch_manifest.json").exists())
    months: set[str] = set()
    samples_per_month = None
    for b in buildings:
        man = json.loads((b / "batch_manifest.json").read_text())
        n_total += int(man["n_total"])
        n_succ += int(man["n_succeeded"])
        n_fail += int(man["n_failed"])
        samples_per_month = int(man["samples_per_month"])
        for s in man.get("samples", []):
            months.add(s["month"])
            if s.get("duration_sec") is not None:
                dur_sum += float(s["duration_sec"])
                dur_n += 1
            v = s.get("validation") or {}
            total_errors += int(v.get("total_errors", 0))
            total_warnings += int(v.get("total_warnings", 0) or 0)
            units_with_warnings += int(v.get("n_units_with_warnings", 0))
    du = subprocess.run(["du", "-sb", str(CAMPUS_DIR)], capture_output=True,
                        text=True, check=True)
    size_bytes = int(du.stdout.split()[0])
    mean_dur = dur_sum / dur_n if dur_n else float("nan")
    return {
        "n_buildings": len(buildings),
        "n_months": len(months),
        "samples_per_month": samples_per_month,
        "n_total": n_total, "n_succeeded": n_succ, "n_failed": n_fail,
        "total_errors": total_errors,
        "units_with_warnings": units_with_warnings,
        "mean_duration_sec": mean_dur,
        "cpu_hours": dur_sum / 3600.0,
        "size_gib": size_bytes / 2**30,
    }


def _inventory() -> dict:
    import yaml as pyyaml
    n_scenarios = len(list((REPO / "configs" / "scenarios").glob("*.yaml")))
    knobs = pyyaml.safe_load((REPO / "configs" / "knobs.yaml").read_text())
    n_knobs = sum(
        1 for bucket in knobs.values() if isinstance(bucket, dict)
        for spec in bucket.values() if isinstance(spec, dict) and "type" in spec
    )
    codes = set(re.findall(r"\b([A-I]\d+[a-z]?):",
                           (REPO / "src" / "v2b_syndata" / "validate.py").read_text()))
    families = {c[0] for c in codes}
    return {"n_scenarios": n_scenarios, "n_knobs": n_knobs,
            "n_invariants": len(codes), "n_invariant_families": len(families)}


def step_collect(args) -> None:
    import pandas as pd
    import yaml as pyyaml

    sha = _git_sha()
    runtimes = (json.loads(RUNTIMES_JSON.read_text())
                if RUNTIMES_JSON.exists() else {})

    s1 = pd.read_csv(VAL_DIR / "S1_marginals.csv")
    s2 = pd.read_csv(VAL_DIR / "S2_joint.csv")
    s3 = pd.read_csv(VAL_DIR / "S3_holdout.csv")
    s0 = pd.read_csv(VAL_DIR / "S0_assignment.csv")
    g14 = json.loads(G14_JSON.read_text())
    tstr_acn = json.loads((TSTR_DIR / "results.json").read_text())
    tstr_ela = json.loads((TSTR_DIR / "results_elaadnl_matched.json").read_text())
    abl = pd.read_csv(ABLATION_CSV)
    srcsum = pd.read_csv(SOURCES_SUMMARY).set_index("source")
    pops = pyyaml.safe_load((REPO / "configs" / "populations.yaml").read_text())
    pv = _pv_numbers()
    campus = _campus_stats()
    inv = _inventory()

    L: list[str] = []
    w = L.append
    w("# PAPER_NUMBERS — consolidated evidence for the KDD paper")
    w("")
    w("> **Auto-generated by `tools/repro_paper.py`. Do not edit by hand.**")
    w("> Every number the paper cites must appear here; the paper cites only")
    w("> numbers present here. Regenerate: `uv run python tools/repro_paper.py`")
    w("> (full, ~overnight-safe) or `--steps collect` (rebuild this file from")
    w("> existing artifacts).")
    w("")
    w(f"- **Git revision:** `{sha}`"
      + (" (WS-F working tree; re-run `--steps collect` after the WS-F commit"
         " to stamp the final SHA)" if _worktree_dirty() else ""))
    w("- **Determinism:** all steps seeded (generation: SHA-keyed node streams;"
      " S1 bootstrap: base seed 20260708, per-cell hashed sub-streams, B=1000;"
      " TSTR: seed 1234; ablation: deterministic EM). Two consecutive driver"
      " runs must reproduce this file bit-for-bit; wall-times below are the"
      " recorded measurement from `docs/experiments/repro_runtimes.json`"
      " (written once; see driver docstring).")
    w("- **No timestamps in this file by design** — the git SHA pins the"
      " revision; `docs/CALIBRATION_RESULTS.md` carries its own generation"
      " date.")
    w("")

    # ── 1. Calibration corpora (paper Tab 1, §4.1) ─────────────────────
    w("## 1. Calibration corpora (Tab 1, §4.1)")
    w("")
    w("| corpus | sessions | drivers/identifiers | provenance of count |")
    w("|---|--:|--:|---|")
    acn = srcsum.loc["acn"]
    ela = srcsum.loc["elaadnl"]
    evw = pops["evwatts_workplace_public"]["calibration_metadata"]
    inl = pops["inl_residential_legacy"]["calibration_metadata"]
    w(f"| ACN-Data (caltech+jpl+office001, 2019–21) | {int(acn['n_sessions']):,} "
      f"| {int(acn['n_users']):,} ({int(acn['n_users']) - int(acn['n_users_unassigned']):,} assigned) "
      f"| regenerated: `sources_summary.csv` (ablation step) |")
    w(f"| ElaadNL 4TU/Utrecht (workplace venue filter) | {int(ela['n_sessions']):,} "
      f"| {int(ela['n_users']):,} "
      f"| regenerated: `sources_summary.csv` |")
    w("| ElaadNL raw archive (pre venue filter) | 55,379 | 3,409 "
      "| `docs/CALIBRATION_NOTES.md` (historical ingest count; not re-run here) |")
    w(f"| EV WATTS public 2026 (workplace+public L2; port-as-proxy identity) "
      f"| {int(evw['n_sessions_total']):,} | {int(evw['n_users_total']):,} ports "
      f"| `configs/populations.yaml` calibration_metadata |")
    w(f"| INL EV Project (labeled FIXTURE, not a corpus) "
      f"| {int(inl['n_sessions_total'])} | {int(inl['n_users_total'])} "
      f"| `configs/populations.yaml` calibration_metadata |")
    w("")
    w("Generating command: `uv run python tools/repro_paper.py --steps ablation`"
      " (sources_summary) — EV WATTS/INL rows from committed calibration"
      " metadata.")
    w("")

    # ── 2. Region geometry / assignment (§4.2, Fig 2) ─────────────────
    w("## 2. Region assignment & weights (§4.2, Fig 2)")
    w("")
    acn_s0 = s0[s0["source"] == "acn"]
    w("| quantity | value | source |")
    w("|---|--:|---|")
    for _, r in acn_s0.iterrows():
        w(f"| ACN user share: {r['region']} | {float(r['user_share']) * 100:.1f}% "
          f"({int(r['n_users'])}) | `S0_assignment.csv` |")
    for src in sorted(set(s0["source"])):
        un = s0[(s0["source"] == src) & (s0["region"] == "__unassigned__")]
        if not un.empty:
            w(f"| unassigned drivers: {src} | "
              f"{float(un.iloc[0]['user_share']) * 100:.1f}% | `S0_assignment.csv` |")
    w(f"| ACN drivers with φ ≤ 0.3 | "
      f"{float(acn['share_users_phi_le_0.3']) * 100:.1f}% | `sources_summary.csv` |")
    w("| ElaadNL unassigned before re-anchoring (historical, 2026-06-27) | "
      "76% | `docs/PROJECT_TRACKER.md` W8/✔4 (the 0% 'after' is the "
      "regenerated S0 row above) |")
    w("")
    w("Generating command: `uv run python tools/validate_calibration.py "
      f"--seeds {args.seeds} --workers {args.workers} --sources {CAL_SOURCES} "
      f"--bootstrap {args.bootstrap}`.")
    w("")

    # ── 3. Shipped mixture example (Fig 3, §4.3) ───────────────────────
    w("## 3. Shipped arrival mixture, largest ACN region (Fig 3, §4.3)")
    w("")
    rc = pops["acn_workplace_baseline"]["region_distributions"]["rare_consistent"]["arrival"]
    w(f"- `rare_consistent` arrival = {rc['w1']:.2f}·N({rc['mu1']:.2f}, "
      f"{rc['sigma1']:.2f}) + {1 - rc['w1']:.2f}·N({rc['mu2']:.2f}, "
      f"{rc['sigma2']:.2f}), truncated to [{rc['trunc_lo']:.0f}, "
      f"{rc['trunc_hi']:.0f}] h; fit KS {rc['ks_fit_quality']:.3f} "
      f"(n = {rc['n_samples']:,}).")
    w("- Source: `configs/populations.yaml` "
      "(`acn_workplace_baseline.region_distributions.rare_consistent.arrival`).")
    w("")

    # ── 4. Behavioral fidelity S1/S2/S3 (Tab 2, §5.2, §8) ─────────────
    w("## 4. Behavioral fidelity (Tab 2, §5.2, §8)")
    w("")
    dmu = (s1["source_mean"] - s1["generated_mean"]).abs()
    legacy = s1[s1["source"] != "evwatts"]
    dmu_legacy = (legacy["source_mean"] - legacy["generated_mean"]).abs()
    worst = s1.loc[s1["ks_statistic"].idxmax()]
    rc_row = s1[(s1["source"] == "acn") & (s1["region"] == "rare_consistent")
                & (s1["variable"] == "arrival_hour")].iloc[0]
    w("| quantity | value | source |")
    w("|---|---|---|")
    w(f"| S1 mean \\|Δμ\\| (all {len(s1)} region×variable cells, all "
      f"{s1['source'].nunique()} sources) | {_fmt(dmu.mean(), 2)} h | "
      "`S1_marginals.csv` |")
    w(f"| S1 mean \\|Δμ\\| excl. evwatts ({len(legacy)} cells; pre-WS-F "
      f"aggregate for continuity) | {_fmt(dmu_legacy.mean(), 2)} h | "
      "`S1_marginals.csv` |")
    w(f"| S1 max KS (worst cell) | {_fmt(worst['ks_statistic'])} "
      f"[{_fmt(worst['ks_ci_lo'])}, {_fmt(worst['ks_ci_hi'])}] "
      f"({worst['source']} / {worst['region']} / {worst['variable']}, "
      f"n={int(worst['n_source']):,}) | `S1_marginals.csv` |")
    w(f"| S1 arrival KS, largest ACN region (acn/rare_consistent) | "
      f"{_fmt(rc_row['ks_statistic'])} [{_fmt(rc_row['ks_ci_lo'])}, "
      f"{_fmt(rc_row['ks_ci_hi'])}] | `S1_marginals.csv` |")
    w(f"| S2 max copula ρ-gap | {_fmt(s2['rho_gap'].max())} "
      f"({s2.loc[s2['rho_gap'].idxmax(), 'source']} / "
      f"{s2.loc[s2['rho_gap'].idxmax(), 'region']}) | `S2_joint.csv` |")
    w(f"| S3 median Δ(holdout − train KS) | {_fmt(s3['delta'].median())} "
      f"({len(s3)} cells) | `S3_holdout.csv` |")
    s3_ne = s3[s3["source"] != "evwatts"]
    w(f"| S3 median Δ excl. evwatts ({len(s3_ne)} cells; pre-WS-F scope for "
      f"continuity) | {_fmt(s3_ne['delta'].median())} | `S3_holdout.csv` |")
    s3w = s3.loc[s3["delta"].idxmax()]
    w(f"| S3 worst cell Δ | +{_fmt(s3w['delta'])} ({s3w['source']} / "
      f"{s3w['region']} / {s3w['variable']}, n_test={int(s3w['n_test'])}) | "
      "`S3_holdout.csv` |")
    dw = s3[s3["variable"] == "dwell_hours"].nlargest(3, "delta")
    dw_str = ", ".join(f"+{_fmt(r['delta'])} ({r['source']}/{r['region']}, "
                       f"n_test={int(r['n_test'])})" for _, r in dw.iterrows())
    w(f"| S3 worst dwell cells (top 3 Δ) | {dw_str} | `S3_holdout.csv` |")
    arr3 = s3[s3["variable"] == "arrival_hour"].nlargest(3, "delta")
    arr_str = ", ".join(f"+{_fmt(r['delta'])} ({r['source']}/{r['region']}, "
                        f"n_test={int(r['n_test'])})" for _, r in arr3.iterrows())
    w(f"| S3 worst arrival cells (top 3 Δ) | {arr_str} | `S3_holdout.csv` |")
    w("")
    w("Full per-cell table with CIs: `docs/experiments/s1_fidelity_cis.csv` "
      "and `docs/CALIBRATION_RESULTS.md`. Generating command as §2.")
    w("")

    # ── 5. Ablation (§4.3 / §5.2) ──────────────────────────────────────
    w("## 5. Mixture & per-region ablation (§4.3, §5.2)")
    w("")
    w("_Metric: one-sample KS of the fitted CDF vs the region's source "
      "sessions (= the fitter's `ks_fit_quality`). Supersedes the "
      "planning-doc '0.148→0.073', which had no committed primary source._")
    w("")
    w("| quantity | value | source |")
    w("|---|---|---|")
    acn_arr = abl[(abl["source"] == "acn") & (abl["variable"] == "arrival_hour")]
    w(f"| ACN mean arrival KS: single family → shipped (mixture where "
      f"selected) | {_fmt(acn_arr['ks_single'].mean())} → "
      f"{_fmt(acn_arr['ks_shipped'].mean())} "
      f"({len(acn_arr)} regions; mixture selected in "
      f"{int(acn_arr['mixture_selected'].sum())}) | `mixture_ablation.csv` |")
    mix_cells = abl[abl["mixture_selected"]]
    arr_mix = mix_cells[mix_cells["variable"] == "arrival_hour"]
    w(f"| arrival cells where the mixture gate fired (all ablation sources) | "
      f"{len(arr_mix)}/{len(abl[abl['variable'] == 'arrival_hour'])}; mean KS "
      f"{_fmt(arr_mix['ks_single'].mean())} → {_fmt(arr_mix['ks_shipped'].mean())} "
      f"| `mixture_ablation.csv` |")
    rc_abl = abl[(abl["source"] == "acn") & (abl["region"] == "rare_consistent")
                 & (abl["variable"] == "arrival_hour")].iloc[0]
    w(f"| pooled-broadcast → per-region fit, acn/rare_consistent arrival | "
      f"{_fmt(rc_abl['ks_pooled_broadcast'])} → {_fmt(rc_abl['ks_shipped'])} | "
      f"`mixture_ablation.csv` |")
    dwl = abl[abl["variable"] == "dwell_hours"]
    w(f"| dwell: mean KS single → shipped (all ablation sources) | "
      f"{_fmt(dwl['ks_single'].mean())} → {_fmt(dwl['ks_shipped'].mean())} "
      f"(mixture selected in {int(dwl['mixture_selected'].sum())}/{len(dwl)}) | "
      f"`mixture_ablation.csv` |")
    w("")
    w("Generating command: `uv run python tools/repro_paper.py --steps "
      "ablation`. Per-source aggregates: `docs/experiments/mixture_ablation.md`.")
    w("")

    # ── 6. Building load (Tab 3, §5.1, §8) ─────────────────────────────
    w("## 6. Building-load fidelity vs ComStock (Tab 3, §5.1, §8)")
    w("")
    w("| archetype/size | gen kW | ComStock kW | CV(RMSE) % | NMBE % | "
      "shape corr (wd) | shape corr (we) | peak-hr Δ | gen LF | ref LF |")
    w("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for e in g14:
        w(f"| {e['archetype']}/{e['size']} | {_fmt(e['gen_mean_kw'], 1)} | "
          f"{_fmt(e['ref_mean_kw'], 1)} | {_fmt(e['cv_rmse_pct'], 1)} | "
          f"{_fmt(e['nmbe_pct'], 1)} | {_fmt(e['shape_corr_weekday'])} | "
          f"{_fmt(e['shape_corr_weekend'])} | {int(e['peak_hour_err_h'])} | "
          f"{_fmt(e['gen_load_factor'])} | {_fmt(e['ref_load_factor'])} |")
    corr = [e["shape_corr_weekday"] for e in g14]
    nmbes = sorted(e["nmbe_pct"] for e in g14)
    peak_max = max(int(e["peak_hour_err_h"]) for e in g14)
    w("")
    w(f"- Weekday shape correlation range: {_fmt(min(corr), 2)}–"
      f"{_fmt(max(corr), 2)}; max peak-hour error {peak_max} h.")
    below = [x for x in nmbes if x > 0]
    above = [x for x in nmbes if x < 0]
    w(f"- NMBE: {len(below)} archetypes below stock average by "
      f"{_fmt(min(below), 1)}–{_fmt(max(below), 1)}% "
      f"(positive NMBE = generator under-predicts); "
      f"{len(above)} archetype(s) above by "
      f"{', '.join(_fmt(abs(x), 1) for x in above)}%.")
    w("- BDG2 context: 19 real meters (14 office + 5 retail) in "
      "`data/buildingload_reference/bdg2_timeseries.parquet` "
      "(fetched by `tools/fetch_buildingload_reference.py`).")
    w("")
    w("Source: `data/buildingload_reference/validation_metrics.json`. "
      "Generating command: `uv run python tools/validate_buildingload.py -v`.")
    w("")

    # ── 7. PV validation (§5.3) ────────────────────────────────────────
    w("## 7. PV validation vs NREL PVWatts v8 / PySAM (§5.3)")
    w("")
    w("| quantity | value | source |")
    w("|---|---|---|")
    w(f"| annual energy error (primary, standard loss semantics) | "
      f"{pv['annual_err_pct']}% (ours {pv['annual_ours_kwh']} kWh vs "
      f"{pv['annual_ref_kwh']} kWh) | `pv_validation.md` |")
    w(f"| max abs monthly error | {pv['monthly_max_abs_err_pct']}% | "
      "`pv_validation.md` |")
    w(f"| hourly CV(RMSE) / NMBE / Pearson r | {pv['cvrmse_pct']}% / "
      f"{pv['nmbe_pct']}% / {pv['pearson_r']} | `pv_validation.md` |")
    w(f"| derate-equalized (pure physics) annual error | "
      f"{pv['derate_equalized_pct']}% | `pv_validation.md` |")
    w("")
    w("Generating command: `uv run python tools/validate_pv.py` (requires "
      "PySAM; not re-run by this driver — the committed memo is the primary).")
    w("")

    # ── 8. TSTR (Tab 4, §6, abstract) ──────────────────────────────────
    w("## 8. TSTR / TRTR utility (Tab 4, §6, abstract)")
    w("")
    w("| corpus | regime | MAE ratio | RMSE ratio | source |")
    w("|---|---|--:|--:|---|")

    def ratio_row(res: dict, corpus: str, regime: str, key: str, src: str):
        r = res[key]["TSTR_over_TRTR_ratio"]
        w(f"| {corpus} | {regime} | {_fmt(r['mae'], 2)} | {_fmt(r['rmse'], 2)} "
          f"| `{src}` |")

    ratio_row(tstr_acn, "ACN-Data", "lagged, raw", "results_lagged",
              "data/tstr/results.json")
    ratio_row(tstr_acn, "ACN-Data", "calendar-only, raw",
              "results_calendar_only", "data/tstr/results.json")
    ratio_row(tstr_ela, "ElaadNL", "lagged, raw", "results_lagged",
              "data/tstr/results_elaadnl_matched.json")
    ratio_row(tstr_ela, "ElaadNL", "lagged, normalized",
              "results_lagged_normalized",
              "data/tstr/results_elaadnl_matched.json")
    ratio_row(tstr_ela, "ElaadNL", "calendar-only, raw",
              "results_calendar_only", "data/tstr/results_elaadnl_matched.json")
    ratio_row(tstr_ela, "ElaadNL", "calendar-only, normalized",
              "results_calendar_only_normalized",
              "data/tstr/results_elaadnl_matched.json")
    w("")
    w("| context quantity | value | source |")
    w("|---|---|---|")
    w(f"| ACN synthetic cohort | scenario {tstr_acn['config']['scenario']}, "
      f"seed {tstr_acn['config']['seed']}, "
      f"{tstr_acn['generator']['n_sessions']} sessions | "
      "`data/tstr/results.json` |")
    w(f"| ElaadNL synthetic cohort | scenario {tstr_ela['config']['scenario']}, "
      f"seed {tstr_ela['config']['seed']}, "
      f"{tstr_ela['generator']['n_sessions']} sessions, mean "
      f"{_fmt(tstr_ela['synth_series']['mean_kw'], 2)} kW, peak "
      f"{_fmt(tstr_ela['synth_series']['peak_kw'], 1)} kW | "
      "`data/tstr/results_elaadnl_matched.json` |")
    w(f"| ElaadNL real series | mean "
      f"{_fmt(tstr_ela['real_series']['mean_kw'], 2)} kW, peak "
      f"{_fmt(tstr_ela['real_series']['peak_kw'], 1)} kW, "
      f"{int(tstr_ela['real_series']['n_bins']):,} hourly bins | "
      "`data/tstr/results_elaadnl_matched.json` |")
    w(f"| ElaadNL real cohort identifiers (workplace venue filter) | "
      f"{int(srcsum.loc['elaadnl', 'n_users']):,} drivers "
      f"(raw archive: 3,409 identifiers, `docs/CALIBRATION_NOTES.md`) | "
      "`sources_summary.csv` |")
    w("| superseded artifact (mismatched-scenario ElaadNL run, kept as "
      "evidence per §6 footnote) | `data/tstr/results_elaadnl.json` "
      "(scenario S_acn_caltech) | repo |")
    w("")
    w("Generating commands: `uv run python tools/tstr_forecasting.py --real "
      "acn --out data/tstr/results.json` and `uv run python "
      "tools/tstr_forecasting.py --real elaadnl --normalize --out "
      "data/tstr/results_elaadnl_matched.json`.")
    w("")

    # ── 9. Release inventory & compute (§3, §7, §10, abstract) ─────────
    w("## 9. Release inventory, corpus, compute (§3, §7, §10, abstract)")
    w("")
    w("| quantity | value | source / command |")
    w("|---|---|---|")
    w(f"| benchmark scenario configurations | {inv['n_scenarios']} | "
      "`ls configs/scenarios/*.yaml \\| wc -l` |")
    w(f"| typed knobs in the registry | {inv['n_knobs']} | "
      "`configs/knobs.yaml` (leaf specs with a `type`) |")
    w(f"| validation invariants | {inv['n_invariants']} in "
      f"{inv['n_invariant_families']} families (A–I) | distinct "
      "`<letter><n>:` codes in `src/v2b_syndata/validate.py` |")
    w(f"| reference corpus | {campus['n_buildings']} buildings × "
      f"{campus['n_months']} months × {campus['samples_per_month']} samples = "
      f"{campus['n_total']:,} units | `data/output/campus10/*/batch_manifest.json` |")
    w(f"| corpus generation outcome | {campus['n_succeeded']:,} succeeded / "
      f"{campus['n_failed']} failed; {campus['total_errors']} hard validation "
      f"errors; {campus['units_with_warnings']:,} units carry soft advisories | "
      "batch manifests (validation summaries) |")
    w(f"| corpus size on disk | {campus['size_gib']:.1f} GiB | "
      "`du -sb data/output/campus10` |")
    w(f"| per-unit generation cost | {campus['mean_duration_sec']:.1f} s "
      f"(mean over {campus['n_total']:,} units, 1 core each) | batch manifests "
      "(`duration_sec`) |")
    w(f"| corpus compute | {campus['cpu_hours']:.0f} CPU-hours "
      f"(30 workers ≈ {campus['cpu_hours'] / 30:.1f} h wall) | batch manifests |")
    w("")

    # ── 10. Compute statement for this driver ──────────────────────────
    w("## 10. Reproduction compute (this driver, recorded measurement)")
    w("")
    if runtimes:
        w("| step | wall time |")
        w("|---|--:|")
        for k in STEPS:
            if k in runtimes:
                w(f"| {k} | {runtimes[k] / 60:.1f} min |")
        tot = sum(v for k, v in runtimes.items() if k in STEPS)
        w(f"| **total** | **{tot / 60:.1f} min** |")
        w("")
        w("_Measured once on a 32-core workstation (EnergyPlus 24.1, load "
          "caches warm) and recorded in `docs/experiments/repro_runtimes.json`;"
          " re-runs embed the recorded values so this file stays "
          "bit-reproducible. Delete that JSON or pass `--record-runtimes` to "
          "re-measure._")
    else:
        w("_No recorded runtimes yet — run the full driver once._")
    w("")

    PAPER_NUMBERS.write_text("\n".join(L) + "\n")
    print(f"wrote {PAPER_NUMBERS}", flush=True)


def _worktree_dirty() -> bool:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                       capture_output=True, text=True, check=True)
    return bool(r.stdout.strip())


STEP_FNS = {
    "calibration": step_calibration,
    "buildingload": step_buildingload,
    "tstr_acn": step_tstr_acn,
    "tstr_elaadnl": step_tstr_elaadnl,
    "ablation": step_ablation,
    "collect": step_collect,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--steps", default=",".join(STEPS),
                    help=f"comma list from {STEPS}")
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--record-runtimes", action="store_true",
                    help="overwrite docs/experiments/repro_runtimes.json with "
                         "this run's measured wall times")
    args = ap.parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown steps: {sorted(unknown)}")

    measured: dict[str, float] = {}
    t_all = time.perf_counter()
    for s in STEPS:
        if s not in steps:
            continue
        t0 = time.perf_counter()
        STEP_FNS[s](args)
        measured[s] = time.perf_counter() - t0
        print(f"--- step {s}: {measured[s]:.1f}s", flush=True)

    ran_all = all(s in measured for s in STEPS if s != "collect")
    if measured and (args.record_runtimes or
                     (not RUNTIMES_JSON.exists() and ran_all)):
        RUNTIMES_JSON.parent.mkdir(parents=True, exist_ok=True)
        RUNTIMES_JSON.write_text(json.dumps(
            {k: round(v, 1) for k, v in measured.items()}, indent=2,
            sort_keys=True) + "\n")
        print(f"recorded runtimes -> {RUNTIMES_JSON}", flush=True)
        if "collect" in steps:  # re-embed the just-recorded times
            step_collect(args)

    print(f"\nALL DONE in {(time.perf_counter() - t_all) / 60:.1f} min; "
          f"measured: { {k: round(v, 1) for k, v in measured.items()} }",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
