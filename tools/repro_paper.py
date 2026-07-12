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
  5. tstr_scale    — TSTR scale/duration study (ElaadNL): 12-month same-fleet,
                     scale-matched 1-month (ev_count 1000 / charger_count 500,
                     the knob caps), and the headline 12-month scale-matched
                     arm → data/tstr/results_elaadnl_scale.json (combined,
                     keyed; baseline embedded) + per-arm JSONs.
  6. ablation      — mixture / per-region arrival+dwell fit ablation (below)
                     → docs/experiments/mixture_ablation.csv (+ .md) and
                     docs/experiments/sources_summary.csv. Regenerates the
                     "GMM-k mixture" and "pooled-broadcast vs per-region"
                     claims from committed primary sources (the planning-doc
                     0.148→0.073 number had no committed source; whatever this
                     step produces supersedes it).
  7. family_selection — across-family model selection on the SOURCE region
                     cells (arrival hour / dwell hours / arrival SoC):
                     candidate families per variable scored by one-sample KS
                     on the training data plus AIC/BIC where a parametric
                     likelihood is defined → docs/experiments/
                     family_selection.csv (+ .md). Regenerates the paper's
                     "why these families" appendix numbers. Deterministic
                     (median-split EM; Scott-factor KDE on a fixed grid;
                     SoC prior seed 20260613 = calibration/api.py's own;
                     no free RNG).
  8. v2b_dispatch  — tools/bench_v2b_dispatch.py: LP peak-shave dispatch
                     baseline (uncontrolled / V1G / V2B) on the released
                     campus10 unit b1/JUL2024/0, plus ACN-Sim V1G
                     cross-check rows via the repo bench machinery →
                     docs/experiments/v2b_dispatch.csv (+ .md memo).
                     Deterministic (no RNG; unique LP optimum under the
                     price tie-break) except the solve_s wall-time column,
                     which collect does not cite.
  9. collect       — consolidates every headline number the paper cites into
                     docs/experiments/PAPER_NUMBERS.md with value, source
                     artifact, generating command, git SHA, and the compute
                     statement.

Determinism contract (the WS-F gate):
  Two consecutive full runs must produce a bit-identical PAPER_NUMBERS.md.
  Everything numeric is seeded (generation: hash-keyed per-node streams;
  bootstrap: seed 20260708 with per-cell hashed sub-streams; TSTR: seed 1234,
  including its paired-bootstrap ratio CIs (B=1000, per-regime hashed
  sub-streams); ablation: deterministic EM, no RNG). Wall-clock runtimes are
  the one intrinsically non-deterministic output, so they are RECORDED ONCE into
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
V2B_DISPATCH_CSV = DOCS_EXP / "v2b_dispatch.csv"
V2B_DISPATCH_UNIT = CAMPUS_DIR / "b1" / "JUL2024" / "0"
CONTENDED_CSV = DOCS_EXP / "contended_bench.csv"
CONTENDED_CONFIG = DOCS_EXP / "contended_bench_config.json"
CONTENDED_UNIT = (REPO / "data" / "output" / "contended" / "b1ch35"
                  / "JUL2024" / "0")

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
# Family-selection scope: the driver-identity-grounded cohorts (same list as
# the ablation) plus EV WATTS — the "why these families" claim is about the
# whole calibrated corpus, and this step fits each cell once (no 50-seed
# generation), so the 1.26M-session cohort is affordable here.
FAMILY_SOURCES = [*ABLATION_SOURCES, "evwatts"]
FAMILY_CSV = DOCS_EXP / "family_selection.csv"
FAMILY_MD = DOCS_EXP / "family_selection.md"

STEPS = ["calibration", "buildingload", "tstr_acn", "tstr_elaadnl",
         "tstr_scale", "ablation", "family_selection", "v2b_dispatch",
         "contended_bench", "collect"]

# TSTR scale study (review attack: "one synthetic month, 20-vehicle building
# vs the 1,231-driver multi-year real aggregate"). Three arms on top of the
# committed baseline, all seed 1234, scenario S_elaadnl_public_eu:
#   A  12 consecutive synthetic months, same 20-EV fleet   (--months 12)
#   B  1 month, scale-matched fleet ev_count=1000 (knob cap; real cohort is
#      1,231 drivers), charger_count=500 (knob cap)
#   C  both (headline arm)
_SCALE_OVR = ["--override", "ev_fleet.ev_count=1000",
              "--override", "charging_infra.charger_count=500"]
TSTR_SCALE_ARMS = {
    "arm_a_12mo_ev20": (["--months", "12"],
                        TSTR_DIR / "results_elaadnl_12mo.json"),
    "arm_b_1mo_ev1000": (_SCALE_OVR,
                         TSTR_DIR / "results_elaadnl_ev1000.json"),
    "arm_c_12mo_ev1000": (["--months", "12", *_SCALE_OVR],
                          TSTR_DIR / "results_elaadnl_ev1000_12mo.json"),
}
TSTR_SCALE_JSON = TSTR_DIR / "results_elaadnl_scale.json"


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


def step_tstr_scale(args) -> None:
    """TSTR scale/duration study (ElaadNL): three arms over the committed
    1-month/20-EV baseline, then a combined keyed JSON. Deterministic given
    the fixed seeds (generation: SHA-keyed node streams; TSTR: seed 1234)."""
    for arm, (extra, out) in TSTR_SCALE_ARMS.items():
        _run([sys.executable, str(REPO / "tools" / "tstr_forecasting.py"),
              "--real", "elaadnl", "--normalize", *extra, "--out", str(out)],
             f"tstr_scale/{arm}")
    combined = {
        "description": (
            "TSTR scale/duration study on ElaadNL (workplace venue filter): "
            "closes the 'one synthetic month, 20-vehicle building vs a "
            "1,231-driver multi-year real aggregate' scale mismatch. "
            "ev_count=1000 / charger_count=500 are the knob-registry caps "
            "(configs/knobs.yaml); the real cohort is 1,231 drivers, so the "
            "matched fleet is capped ~19% below the real driver count. All "
            "arms: scenario S_elaadnl_public_eu, seed 1234, --normalize."),
        "baseline_1mo_ev20": json.loads(
            (TSTR_DIR / "results_elaadnl_matched.json").read_text()),
    }
    for arm, (_extra, out) in TSTR_SCALE_ARMS.items():
        combined[arm] = json.loads(out.read_text())
    TSTR_SCALE_JSON.write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n")
    print(f"wrote {TSTR_SCALE_JSON}", flush=True)


def step_v2b_dispatch(args) -> None:
    """LP peak-shave dispatch baseline (uncontrolled / V1G / V2B) on one
    released corpus unit, plus ALL SEVEN stock ACN-Sim V1G cross-check rows.
    Deterministic except the solve_s wall-time column
    (collect only cites the deterministic columns)."""
    _run([sys.executable, str(REPO / "tools" / "bench_v2b_dispatch.py"),
          "--data-dir", str(V2B_DISPATCH_UNIT), "--out-dir", str(DOCS_EXP)],
         "v2b_dispatch")


def step_contended_bench(args) -> None:
    """Contended dispatch benchmark: same building/fleet/month/seed as the
    v2b_dispatch unit but charging_infra.charger_count 60 -> 35 (~60% of the
    realized peak concurrency of 59), so plug contention binds, plus the
    0.125 ACN-Caltech-like feeder cap under which the seven stock schedulers
    genuinely separate. The unit is generated deterministically from the
    committed config if absent (byte-identical regeneration; requires
    EnergyPlus); the bench itself is fully deterministic (no RNG, no
    wall-time columns — contended_bench.{csv,md} are byte-stable)."""
    if not (CONTENDED_UNIT / "sessions.csv").exists():
        _run([sys.executable, "-m", "v2b_syndata.cli", "generate-multi",
              "--config", str(CONTENDED_CONFIG),
              "--output-dir", str(CONTENDED_UNIT)],
             "contended_bench/generate")
    _run([sys.executable, str(REPO / "tools" / "bench_v2b_dispatch.py"),
          "--contended", "--data-dir", str(CONTENDED_UNIT),
          "--out-dir", str(DOCS_EXP)],
         "contended_bench")


# ──────────────────────────────────────────────────────────────────────
# Step 6 — mixture / per-region fit ablation (deterministic; no RNG)
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
# Step 7 — across-family model selection (deterministic; no free RNG)
# ──────────────────────────────────────────────────────────────────────

FAMILY_MIN_CELL = 60        # same per-cell floor as the ablation step
_KDE_GRID_N = 4001          # fixed KDE evaluation grid (deterministic)
_SOC_PRIOR_SEED = 20260613  # MUST equal calibration/api.py's arr_soc_rng seed

FAMILY_VARIABLES = (("arrival_hour", "arrival"),
                    ("dwell_hours", "dwell"),
                    ("soc_arrival", "soc_arrival"))


def _family_candidates(variable: str, vals) -> list[dict]:
    """Fit every candidate family for one (source, region, variable) cell.

    Returns [{family, k_params, loglik, ks, shippable, note}]; k_params is
    None where no parametric likelihood is defined (KDE), in which case
    AIC/BIC are not reported. Deterministic: the mixture EM is the fitter's
    own median-split-initialized `_gmm_em`, the KDE uses scipy's Scott
    factor on a fixed grid, and no candidate consumes an RNG.

    Candidate sets:
      arrival_hour: truncnorm[4,22] (shipped single), truncnorm 2-component
        mixture (the shipped upgrade, fitted UNgated here), free 2-component
        GMM (untruncated — its out-of-window tail mass is recorded), and a
        Gaussian KDE (scored only; not shippable — see the MD memo).
        A (shifted) lognormal is deliberately NOT fitted: arrival hour lives
        on a bounded clock window, so the lognormal support origin would be
        an artifact of the clock zero, not a property of behavior.
      dwell_hours: weibull, weibull 2-component mixture (ungated), lognorm,
        gamma, expon (all floc=0).
      soc_arrival: beta[0,1] (shipped), truncnorm[0,1], uniform[0,1] (null).
    """
    import numpy as np
    import scipy.stats as st
    from scipy.optimize import minimize
    from scipy.special import ndtr

    from v2b_syndata.calibration.distribution_fitter import (
        ARRIVAL_HI,
        ARRIVAL_LO,
        _gmm_em,
        fit_truncnorm_arrival,
    )

    x = np.asarray(vals, dtype=float)
    n = len(x)
    rows: list[dict] = []

    def _ks(cdf) -> float:
        return float(st.kstest(x, cdf).statistic)

    def _ll(logpdf_vals) -> float:
        return float(np.clip(np.asarray(logpdf_vals, dtype=float),
                             -700.0, None).sum())

    def add(family, k, ll, ks, shippable, note=""):
        rows.append({"family": family, "k_params": k, "loglik": ll,
                     "ks": ks, "shippable": shippable, "note": note})

    if variable == "arrival_hour":
        a, b = ARRIVAL_LO, ARRIVAL_HI
        fit = fit_truncnorm_arrival(x)
        if fit is not None:
            mu, sg = fit["mu"], fit["sigma"]
            fz = st.truncnorm((a - mu) / sg, (b - mu) / sg, loc=mu, scale=sg)
            add("truncnorm", 2, _ll(fz.logpdf(x)), _ks(fz.cdf), True)
        # One deterministic EM feeds both mixture candidates (identical to
        # the params fit_truncnorm_mixture_arrival would ship, minus the
        # KS-margin acceptance gate).
        mu2, sd2, w2, _ = _gmm_em(x, 2)
        order = np.argsort(mu2)
        mu2, sd2, w2 = mu2[order], sd2[order], w2[order]

        def tmix_pdf(q):
            q = np.asarray(q, dtype=float)
            return sum(w2[j] * st.truncnorm.pdf(
                q, (a - mu2[j]) / sd2[j], (b - mu2[j]) / sd2[j],
                loc=mu2[j], scale=sd2[j]) for j in range(2))

        def tmix_cdf(q):
            q = np.asarray(q, dtype=float)
            return sum(w2[j] * st.truncnorm.cdf(
                q, (a - mu2[j]) / sd2[j], (b - mu2[j]) / sd2[j],
                loc=mu2[j], scale=sd2[j]) for j in range(2))

        add("truncnorm_mix2", 5,
            _ll(np.log(np.clip(tmix_pdf(x), 1e-300, None))),
            _ks(tmix_cdf), True,
            "shipped form (fitter gates it at KS margin 0.02)")

        def gmm_pdf(q):
            q = np.asarray(q, dtype=float)
            return sum(w2[j] * st.norm.pdf(q, mu2[j], sd2[j])
                       for j in range(2))

        def gmm_cdf(q):
            q = np.asarray(q, dtype=float)
            return sum(w2[j] * st.norm.cdf(q, mu2[j], sd2[j])
                       for j in range(2))

        tail = float(1.0 - (gmm_cdf(b) - gmm_cdf(a)))
        add("gmm2_free", 5,
            _ll(np.log(np.clip(gmm_pdf(x), 1e-300, None))),
            _ks(gmm_cdf), False,
            f"untruncated; mass outside [{a:g},{b:g}]h = {tail:.4f}")

        kde = st.gaussian_kde(x)  # Scott factor — deterministic
        bw = float(np.sqrt(kde.covariance[0, 0]))
        grid = np.linspace(a, b, _KDE_GRID_N)
        pdf_grid = kde.evaluate(grid)
        cdf_grid = np.empty(_KDE_GRID_N)
        for s0 in range(0, _KDE_GRID_N, 16):  # chunked exact Gaussian CDF
            g = grid[s0:s0 + 16]
            cdf_grid[s0:s0 + 16] = ndtr(
                (g[:, None] - x[None, :]) / bw).mean(axis=1)
        ll = _ll(np.log(np.clip(np.interp(x, grid, pdf_grid), 1e-300, None)))
        add("kde", None, ll,
            _ks(lambda q: np.interp(np.asarray(q, dtype=float),
                                    grid, cdf_grid)),
            False,
            f"scored only ({_KDE_GRID_N}-pt grid); no closed-form PPF")
        return rows

    if variable == "dwell_hours":
        for name, dist, k in (("weibull", st.weibull_min, 2),
                              ("lognorm", st.lognorm, 2),
                              ("gamma", st.gamma, 2),
                              ("expon", st.expon, 1)):
            try:
                fz = dist(*dist.fit(x, floc=0))
                ll = _ll(fz.logpdf(x))
                if not np.isfinite(ll):
                    raise ValueError("non-finite loglik")
                add(name, k, ll, _ks(fz.cdf), True)
            except Exception as e:  # noqa: BLE001
                add(name, k, float("nan"), float("nan"), True,
                    f"fit failed: {e}"[:60])
        # Ungated 2-component Weibull mixture — the fitter's own
        # construction (fit_weibull_mixture_dwell) minus the ship gate:
        # deterministic Gaussian EM soft partition → hard assignment →
        # per-cluster Weibull MLE, weights = cluster mass.
        mu, sd, wg, _ = _gmm_em(x, 2)
        resp = np.array([wg[j] * st.norm.pdf(x, mu[j], max(float(sd[j]), 1e-6))
                         for j in range(2)])
        assign = resp.argmax(0)
        comps = []
        for j in range(2):
            cj = x[assign == j]
            if len(cj) < 2:
                comps = []
                break
            kj, _, lamj = st.weibull_min.fit(cj, floc=0)
            comps.append((len(cj) / n, float(kj), float(lamj)))
        if comps:
            comps.sort(key=lambda c: c[2])
            (w1, k1, l1), (_w2, k2, l2) = comps

            def wmix_pdf(q):
                q = np.asarray(q, dtype=float)
                return (w1 * st.weibull_min.pdf(q, k1, scale=l1)
                        + (1.0 - w1) * st.weibull_min.pdf(q, k2, scale=l2))

            def wmix_cdf(q):
                q = np.asarray(q, dtype=float)
                return (w1 * st.weibull_min.cdf(q, k1, scale=l1)
                        + (1.0 - w1) * st.weibull_min.cdf(q, k2, scale=l2))

            add("weibull_mix2", 5,
                _ll(np.log(np.clip(wmix_pdf(x), 1e-300, None))),
                _ks(wmix_cdf), True,
                "shipped form (fitter gates it at KS margin 0.02)")
        else:
            add("weibull_mix2", 5, float("nan"), float("nan"), True,
                "degenerate EM partition")
        return rows

    if variable == "soc_arrival":
        d = np.clip(x, 1e-6, 1 - 1e-6)

        def _ks_d(cdf) -> float:
            return float(st.kstest(d, cdf).statistic)

        try:
            al, be, _, _ = st.beta.fit(d, floc=0, fscale=1)
            fz = st.beta(al, be)
            add("beta", 2, _ll(fz.logpdf(d)), _ks_d(fz.cdf), True)
        except Exception as e:  # noqa: BLE001
            add("beta", 2, float("nan"), float("nan"), True,
                f"fit failed: {e}"[:60])

        def negll(p):
            mu, sg = p
            if sg <= 0.01:
                return 1e12
            lp = st.truncnorm.logpdf(d, (0.0 - mu) / sg, (1.0 - mu) / sg,
                                     loc=mu, scale=sg)
            return -float(lp.sum()) if np.all(np.isfinite(lp)) else 1e12

        r = minimize(negll, [float(d.mean()), max(float(d.std()), 0.05)],
                     method="Nelder-Mead")
        mu, sg = float(r.x[0]), max(0.01, float(r.x[1]))
        fz = st.truncnorm((0.0 - mu) / sg, (1.0 - mu) / sg, loc=mu, scale=sg)
        add("truncnorm01", 2, _ll(fz.logpdf(d)), _ks_d(fz.cdf), True)

        add("uniform01", 0, 0.0,
            _ks_d(lambda q: np.clip(np.asarray(q, dtype=float), 0.0, 1.0)),
            True, "null model")
        return rows

    raise ValueError(f"unknown variable {variable!r}")


def _load_family_cells(source_key: str, pops_yaml: dict) -> dict:
    """Per-region arrays for one source: arrival hours (within the [4,22]h
    fitting window), dwell hours (>0) and reconstructed arrival SoC.

    The SoC reconstruction replicates calibration/api.py exactly — a single
    RNG seeded 20260613 consumed once per session in fetch order — so the
    SoC cells are the very inputs the shipped Beta was fitted to (the SoC
    contract: a modeled prior, not a measurement; see paper §4.4).
    """
    import numpy as np
    from validate_calibration import SOURCE_SPECS  # tools/ on sys.path

    from v2b_syndata.calibration.battery_inference import (
        infer_capacity,
        reconstruct_arrival_soc,
    )
    from v2b_syndata.calibration.distribution_fitter import (
        ARRIVAL_HI,
        ARRIVAL_LO,
    )
    from v2b_syndata.calibration.feature_extractor import (
        aggregate_user_features,
    )
    from v2b_syndata.calibration.region_assignment import (
        assign_user_to_region,
    )
    from v2b_syndata.calibration.sources import CALIBRATION_SOURCES

    spec = SOURCE_SPECS[source_key]
    src = CALIBRATION_SOURCES[spec["policy"]]()
    sessions = src.fetch_sessions(dict(spec["source_args"]))
    arr_times = [s.arrival_time for s in sessions]
    users = aggregate_user_features(sessions, min(arr_times), max(arr_times))
    axes = pops_yaml[spec["population"]]["axes_distribution"]
    u2r = {u.user_id: (assign_user_to_region(u, axes) or "__unassigned__")
           for u in users}

    rng = np.random.default_rng(_SOC_PRIOR_SEED)
    per: dict[str, dict[str, list[float]]] = {}
    for s in sessions:
        cap, _tag = infer_capacity(s)
        # Draw for EVERY session in fetch order (api.py does), so the RNG
        # stream — and therefore each region's SoC multiset — is identical
        # to what calibration fitted.
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        region = u2r.get(s.user_id, "__unassigned__")
        if region == "__unassigned__":
            continue
        c = per.setdefault(region, {"arrival_hour": [], "dwell_hours": [],
                                    "soc_arrival": []})
        if ARRIVAL_LO <= s.arrival_hour <= ARRIVAL_HI:
            c["arrival_hour"].append(float(s.arrival_hour))
        if s.dwell_hours > 0:
            c["dwell_hours"].append(float(s.dwell_hours))
        if soc is not None:
            c["soc_arrival"].append(float(soc))
    return {r: {k: np.asarray(v, dtype=float) for k, v in d.items()}
            for r, d in sorted(per.items())}


def step_family_selection(args) -> None:
    """Across-family model selection on the SOURCE region cells: for every
    fitted (source, region) cell, fit the candidate families per variable
    and score one-sample KS on the training data plus AIC/BIC where a
    parametric likelihood is defined (the fitter's own model-selection
    question, asked across families rather than within one).

    Deterministic: median-split EM init, Scott-factor KDE on a fixed grid,
    SoC prior stream seeded 20260613 (identical to calibration/api.py);
    no free RNG anywhere.
    """
    import numpy as np
    import pandas as pd
    import yaml as pyyaml
    from validate_calibration import SOURCE_SPECS  # tools/ on sys.path

    t0 = time.perf_counter()
    pops_yaml = pyyaml.safe_load(
        (REPO / "configs" / "populations.yaml").read_text()
    )

    rows: list[dict] = []
    for source in FAMILY_SOURCES:
        cells = _load_family_cells(source, pops_yaml)
        shipped_dists = (
            pops_yaml[SOURCE_SPECS[source]["population"]]
            .get("region_distributions") or {}
        )
        for region, per_var in cells.items():
            for variable, dist_key in FAMILY_VARIABLES:
                vals = per_var[variable]
                if len(vals) < FAMILY_MIN_CELL:
                    continue
                shipped = str(((shipped_dists.get(region) or {})
                               .get(dist_key) or {}).get("dist", ""))
                cand = _family_candidates(variable, vals)
                finite = [c["ks"] for c in cand if np.isfinite(c["ks"])]
                ks_best = min(finite) if finite else float("nan")
                aics = {c["family"]: 2 * c["k_params"] - 2 * c["loglik"]
                        for c in cand
                        if c["k_params"] is not None
                        and np.isfinite(c["loglik"])}
                aic_order = sorted(aics, key=lambda f: aics[f])
                for c in cand:
                    k = c["k_params"]
                    ll = c["loglik"]
                    has_aic = c["family"] in aics
                    rows.append({
                        "source": source, "region": region,
                        "variable": variable, "n": int(len(vals)),
                        "family": c["family"],
                        "k_params": k if k is not None else "",
                        "loglik": ll,
                        "aic": aics.get(c["family"], float("nan")),
                        "bic": (k * np.log(len(vals)) - 2 * ll
                                if has_aic else float("nan")),
                        "ks": c["ks"],
                        "aic_rank": (aic_order.index(c["family"]) + 1
                                     if has_aic else ""),
                        "ks_win": bool(np.isfinite(c["ks"])
                                       and c["ks"] <= ks_best),
                        "shippable": bool(c["shippable"]),
                        "shipped_family": shipped,
                        "note": c["note"],
                    })
                best = min((c for c in cand if np.isfinite(c["ks"])),
                           key=lambda c: c["ks"], default=None)
                tag = (f"best-KS={best['family']} ({best['ks']:.3f})"
                       if best else "no finite fit")
                print(f"  {source}/{region}/{variable}: n={len(vals)} {tag}",
                      flush=True)

    fam = pd.DataFrame(rows)
    DOCS_EXP.mkdir(parents=True, exist_ok=True)
    fam.to_csv(FAMILY_CSV, index=False)

    # Companion MD: method + per-variable aggregates across all cells.
    lines = [
        "# Across-family model selection (behavioral marginals)",
        "",
        "_Auto-generated by `tools/repro_paper.py` (step `family_selection`). "
        "Do not edit by hand. Deterministic: median-split EM init, "
        "Scott-factor KDE on a fixed 4001-point grid, SoC prior seed "
        "20260613 (= calibration/api.py); no free RNG._",
        "",
        f"Scope: every (source, region) cell with ≥ {FAMILY_MIN_CELL} "
        f"sessions across {', '.join(FAMILY_SOURCES)} — the same normalized "
        "session data calibration fits (arrival filtered to the [4,22] h "
        "window; dwell > 0; arrival SoC = the calibration's seeded "
        "prior-based reconstruction, per the SoC contract). Metrics: "
        "one-sample KS of the fitted CDF against the cell's training data "
        "(the fitter's own `ks_fit_quality` definition) and AIC/BIC where a "
        "parametric likelihood is defined. Mixtures are fitted UNgated here "
        "so the family comparison is unconditional; the shipped fitter "
        "additionally gates the mixture at KS margin 0.02.",
        "",
        "Interpretation notes:",
        "",
        "- **KDE is scored only, and cannot ship.** Generation inverts each "
        "marginal at a copula-driven uniform (one uniform per session, a "
        "precondition for bitwise determinism); the shipped families have "
        "closed-form or bisectable CDFs on a bounded window, whereas a KDE "
        "CDF is a kernel sum with no closed-form PPF, requires shipping the "
        "full training sample instead of a compact knob-parameterized "
        "block, and its bandwidth is a data-dependent choice outside the "
        "knob registry.",
        "- **The free (untruncated) 2-component GMM cannot ship for "
        "arrival**: it places probability mass outside the generator's "
        "[4,22] h arrival window (per-cell tail mass in the `note` column), "
        "which the truncated-component mixture eliminates at identical "
        "parameter count.",
        "- **A (shifted) lognormal is not fitted for arrival**: arrival "
        "hour lives on a bounded clock window, so the lognormal support "
        "origin would be an artifact of the clock zero rather than a "
        "property of behavior.",
        "- **Arrival SoC cells are prior-reconstructed** (no charger records "
        "SoC): this table asks which family best represents the contracted "
        "reconstruction, not a measured quantity.",
        "",
    ]

    def _agg_table(variable: str) -> list[str]:
        sub = fam[fam["variable"] == variable]
        if sub.empty:
            return []
        out = [
            f"## {variable}  ({sub['source'].nunique()} sources, "
            f"{len(sub.groupby(['source', 'region']))} cells)",
            "",
            "| family | cells | mean KS | mean AIC rank | KS wins | "
            "AIC wins | shippable |",
            "|---|--:|--:|--:|--:|--:|:-:|",
        ]
        fams = sorted(sub["family"].unique(),
                      key=lambda f: float(sub[sub["family"] == f]["ks"].mean()))
        for f in fams:
            g = sub[sub["family"] == f]
            ranks = pd.to_numeric(g["aic_rank"], errors="coerce").dropna()
            mean_rank = f"{ranks.mean():.2f}" if len(ranks) else "—"
            aic_wins = int((ranks == 1).sum()) if len(ranks) else 0
            out.append(
                f"| {f} | {len(g)} | {g['ks'].mean():.4f} | {mean_rank} | "
                f"{int(g['ks_win'].sum())} | {aic_wins} | "
                f"{'yes' if bool(g['shippable'].iloc[0]) else 'no'} |"
            )
        out.append("")
        return out

    for variable, _key in FAMILY_VARIABLES:
        lines += _agg_table(variable)
    lines += [
        "Per-cell scores: `family_selection.csv`. Regenerate: "
        "`uv run python tools/repro_paper.py --steps family_selection`.",
        "",
    ]
    FAMILY_MD.write_text("\n".join(lines))
    print(f"family_selection done in {time.perf_counter() - t0:.1f}s -> "
          f"{FAMILY_CSV}, {FAMILY_MD}", flush=True)


# ──────────────────────────────────────────────────────────────────────
# Step 9 — collect: PAPER_NUMBERS.md
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
      " TSTR: seed 1234, incl. the paired-bootstrap ratio CIs (B=1000,"
      " per-regime hashed sub-streams); ablation: deterministic EM). Two"
      " consecutive driver"
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
    w("## 3. Shipped arrival mixture, rare-consistent ACN region (Fig 3, §4.3)")
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
    w(f"| S1 arrival KS, rare-consistent ACN region (36% of drivers) | "
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

    # ── 5b. Across-family model selection (§4.3, App. families) ───────
    w("## 5b. Across-family model selection (§4.3, App. families)")
    w("")
    w("_One-sample KS on the cell's training data + AIC/BIC where a "
      "parametric likelihood is defined, per (source, region) cell over "
      f"{', '.join(FAMILY_SOURCES)}. Mixtures fitted ungated; KDE scored "
      "only (cannot ship: no closed-form PPF on the copula uniform); free "
      "GMM not shippable for arrival (mass outside the [4,22] h window). "
      "Method + caveats: `family_selection.md`._")
    w("")
    famsel = pd.read_csv(FAMILY_CSV)
    w("| variable | family | cells | mean KS | mean AIC rank | KS wins | "
      "shippable |")
    w("|---|---|--:|--:|--:|--:|:-:|")
    for variable, _key in FAMILY_VARIABLES:
        sub = famsel[famsel["variable"] == variable]
        fams = sorted(sub["family"].unique(),
                      key=lambda f: float(sub[sub["family"] == f]["ks"].mean()))
        for f in fams:
            g = sub[sub["family"] == f]
            ranks = pd.to_numeric(g["aic_rank"], errors="coerce").dropna()
            mean_rank = f"{ranks.mean():.2f}" if len(ranks) else "—"
            w(f"| {variable} | {f} | {len(g)} | {g['ks'].mean():.4f} | "
              f"{mean_rank} | {int(g['ks_win'].sum())} | "
              f"{'yes' if bool(g['shippable'].iloc[0]) else 'no'} |")
    w("")
    w("Generating command: `uv run python tools/repro_paper.py --steps "
      "family_selection`. Per-cell scores: "
      "`docs/experiments/family_selection.csv`.")
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
    w("| corpus | regime | MAE ratio [95% CI] | RMSE ratio [95% CI] | source |")
    w("|---|---|--:|--:|---|")

    def _ci_txt(ci_block: dict | None, metric: str) -> str:
        if not ci_block:
            return ""
        lo, hi = ci_block["TSTR_over_TRTR_ratio"][metric]
        return f" [{_fmt(lo, 2)}, {_fmt(hi, 2)}]"

    def ratio_row(res: dict, corpus: str, regime: str, key: str, src: str):
        blk = res[key]
        r = blk["TSTR_over_TRTR_ratio"]
        ci = blk.get("ci")
        w(f"| {corpus} | {regime} "
          f"| {_fmt(r['mae'], 2)}{_ci_txt(ci, 'mae')} "
          f"| {_fmt(r['rmse'], 2)}{_ci_txt(ci, 'rmse')} "
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
    scale = json.loads(TSTR_SCALE_JSON.read_text())
    arm_c = scale["arm_c_12mo_ev1000"]
    for regime, key in [("lagged, raw", "results_lagged"),
                        ("lagged, normalized", "results_lagged_normalized"),
                        ("calendar-only, raw", "results_calendar_only"),
                        ("calendar-only, normalized",
                         "results_calendar_only_normalized")]:
        ratio_row(arm_c, "ElaadNL (scale-matched, 12 synth months)", regime,
                  key, "data/tstr/results_elaadnl_scale.json")
    w("")
    w("CI method: seeded PAIRED percentile bootstrap over the held-out real"
      " test bins (B=1000, base seed 1234, per-regime SHA-256 hash-keyed"
      " sub-streams) — the same resampled bin indices are applied to both"
      " models' per-bin errors before recomputing the TSTR/TRTR ratio per"
      " replicate; interval = 2.5–97.5 percentiles (`ci` blocks in the"
      " result JSONs).")
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
    w(f"| ElaadNL scale-matched cohort (headline arm C: 12 synth months, "
      f"ev_count 1000 / charger_count 500 = knob caps; real cohort 1,231 "
      f"drivers) | {arm_c['generator']['n_sessions']:,} sessions, mean "
      f"{_fmt(arm_c['synth_series']['mean_kw'], 2)} kW, peak "
      f"{_fmt(arm_c['synth_series']['peak_kw'], 1)} kW | "
      "`data/tstr/results_elaadnl_scale.json` |")
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

    # ── 10. V2B dispatch baseline (§6 / utility) ───────────────────────
    w("## 10. V2B dispatch baseline (LP peak shave, one released unit)")
    w("")
    w("_Unit `data/output/campus10/b1/JUL2024/0` (60 cars, 48/60 "
      "bidirectional chargers, 400 kWh / 100 kW battery, PV, TOU prices). "
      "LP is deterministic (no RNG; unique optimum under the 1e-4 price "
      "tie-break); the CSV's `solve_s` wall-time column is the sole "
      "non-deterministic field and is not cited here. Formulation and "
      "reconstruction rules: `docs/experiments/v2b_dispatch.md`._")
    w("")
    disp = pd.read_csv(V2B_DISPATCH_CSV).set_index("arm")
    w("| arm | monthly peak net (kW) | peak reduction | energy cost (USD) | "
      "status | source |")
    w("|---|--:|--:|--:|---|---|")
    for arm in disp.index:
        r = disp.loc[arm]
        w(f"| {arm} | {float(r['peak_net_kw']):,.1f} | "
          f"{float(r['peak_reduction_pct']):.1f}% | "
          f"{float(r['energy_cost_usd']):,.2f} | {r['status']} | "
          f"`v2b_dispatch.csv` |")
    d = disp.loc["v2b"]
    w("")
    w(f"- Feasibility: {int(d['n_relaxed'])} required-SoC relaxations, "
      f"{int(d['n_clipped'])} horizon-clipped windows, "
      f"{int(d['n_skipped'])} skipped sessions over "
      f"{int(d['n_sessions'])} sessions; "
      f"{int(d['n_bidirectional_sessions'])}/{int(d['n_sessions'])} "
      "sessions bidirectional-assigned (deterministic round-robin).")
    w(f"- V2B arm energy detail: {float(d['ev_charge_kwh']):,.0f} kWh EV "
      f"charged, {float(d['ev_discharge_kwh']):,.0f} kWh EV discharged, "
      f"{float(d['batt_throughput_kwh']):,.0f} kWh stationary-battery "
      "throughput.")
    if "acnsim_llf_crosscheck" in disp.index:
        cross = [a for a in disp.index
                 if a.startswith("acnsim_") and a.endswith("_crosscheck")
                 and a != "acnsim_uncontrolled_crosscheck"]
        dpk = max((float(disp.loc[a, "peak_net_kw"])
                   - float(disp.loc["uncontrolled", "peak_net_kw"])
                   for a in cross), key=abs)
        w(f"- ACN-Sim cross-check: all {len(cross)} controlled stock V1G "
          f"schedulers (EDF/LLF/FCFS/LCFS/LRPT/RoundRobin — building-load-"
          f"unaware; uncontended charger pool = semantic twins of the "
          f"uncontrolled arm) reproduce the uncontrolled peak to within "
          f"{dpk:+.1f} kW — queue algorithms cannot help without a queue, "
          "and the demand model is independently validated by an "
          "established simulator; see `v2b_dispatch.md` for why no stock "
          "ACN-Sim algorithm is comparable to LP-V1G.")
    w("")
    w("Generating command: `uv run python tools/repro_paper.py --steps "
      "v2b_dispatch` (wraps `tools/bench_v2b_dispatch.py`).")
    w("")

    # ── 10b. Contended dispatch benchmark ──────────────────────────────
    w("## 10b. Contended dispatch benchmark (plug-scarce unit + feeder cap)")
    w("")
    w("_Unit `data/output/contended/b1ch35/JUL2024/0`: byte-identical "
      "demand to the section-10 unit (same building/fleet/month/weather/"
      "seed; SHA-keyed node seeding) but `charging_infra.charger_count` "
      "60 → 35 ≈ 60% of the realized peak concurrency (59), plus the "
      "0.125 ACN-Caltech-like feeder service ratio (87.5 kW) from "
      "`bench/adapter.py`. FCFS pool admission rejects 412/1,242 sessions "
      "(33.2%) identically for every algorithm; the feeder cap is what the "
      "schedulers contend over. Fully deterministic (no RNG, no wall-time "
      "columns). Design and interpretation: "
      "`docs/experiments/contended_bench.md`._")
    w("")
    cont = pd.read_csv(CONTENDED_CSV).set_index("arm")
    w("| arm | peak net (kW) | kWh delivered / requested | "
      "satisfied (of admitted) | satisfied (of offered) | source |")
    w("|---|--:|--:|--:|--:|---|")
    for arm in cont.index:
        r = cont.loc[arm]
        if pd.isna(r["peak_net_kw"]):
            w(f"| {arm} | — (infeasible; see status in CSV) | — | — | — | "
              "`contended_bench.csv` |")
            continue
        w(f"| {arm} | {float(r['peak_net_kw']):,.1f} | "
          f"{float(r['kwh_delivered']):,.0f} / "
          f"{float(r['kwh_requested']):,.0f} | "
          f"{float(r['satisfied_pct_admitted']):.1f}% | "
          f"{float(r['satisfied_pct_offered']):.1f}% | "
          f"`contended_bench.csv` |")
    w("")
    sat = cont["satisfied_pct_admitted"]
    algos = [a for a in cont.index
             if a.startswith("acnsim_") and a != "acnsim_uncontrolled"]
    w(f"- Under contention the stock schedulers separate: satisfied-of-"
      f"admitted spans {min(float(sat[a]) for a in algos):.1f}%–"
      f"{max(float(sat[a]) for a in algos):.1f}% across "
      f"{len(algos)} algorithms (deadline-aware EDF/LLF at the top).")
    w("- LP rows are labeled relaxations (aggregate EV-power cap; "
      "fractional plug sharing; serve all sessions) — a faithful "
      "plug-assignment LP needs integer machinery, deliberately not "
      "attempted. The feeder-cap LP is infeasible when serving ALL "
      "sessions, showing admission rejection is necessary at that service "
      "ratio, not an artifact.")
    w("")
    w("Generating command: `uv run python tools/repro_paper.py --steps "
      "contended_bench` (generates the unit from "
      "`docs/experiments/contended_bench_config.json` if absent, then wraps "
      "`tools/bench_v2b_dispatch.py --contended`).")
    w("")

    # ── 11. Compute statement for this driver ──────────────────────────
    w("## 11. Reproduction compute (this driver, recorded measurement)")
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
    "tstr_scale": step_tstr_scale,
    "ablation": step_ablation,
    "family_selection": step_family_selection,
    "v2b_dispatch": step_v2b_dispatch,
    "contended_bench": step_contended_bench,
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
