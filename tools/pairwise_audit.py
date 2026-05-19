"""V3 pairwise interaction audit.

Sample 50 random pairs from Stage 2 admitted MONOTONIC knobs. For each pair:
generate baseline, only-A, only-B, both. Per affected CSV, measure metric
deltas and classify the joint effect as LINEAR vs NONLINEAR vs SIGN_FLIP.

Reuses Stage 2's probe selectors + metric registry from tools/knob_audit.py.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import knob_audit  # noqa: E402  (sibling tool)

DEFAULT_SEED = 42
N_PAIRS = 50

# Knobs whose presence in a pair forces a non-S01 baseline.
_DR_KNOBS = {
    "utility_rate.dr_program", "utility_rate.dr_magnitude_kw_range",
    "utility_rate.dr_lambda_base", "noise.dr_notification_dropout_prob",
    "sim_window.mode", "noise.profile",
}
_HIGH_CAPACITY_KNOBS = {"ev_fleet.ev_count", "charging_infra.charger_count"}


# ──────────────────────────────────────────────────────────────────────────


def _load_admitted_paths() -> list[str]:
    """Read Stage 2 metadata, return paths with MONOTONIC verdict."""
    meta_path = Path("/tmp/knob_audit/audit_s2_metadata.json")
    if not meta_path.exists():
        raise SystemExit(f"missing {meta_path} — run tools/knob_audit.py --stage 2 first")
    with meta_path.open() as f:
        meta = json.load(f)
    return [v["knob_path"] for v in meta["verdicts"] if v["overall_verdict"] == "MONOTONIC"]


def _build_spec_index() -> dict[str, knob_audit.KnobSpec]:
    cfg = REPO / "configs"
    regs = knob_audit.parse_knobs_yaml(cfg / "knobs.yaml")
    deep = knob_audit.parse_deep_channel(cfg / "populations.yaml")
    return {s.path: s for s in regs + deep}


def _high_probe(spec: knob_audit.KnobSpec) -> Any:
    """Return Stage 2's last probe value (the 'high' end)."""
    probes = knob_audit.select_5_probes(spec)
    if not probes:
        return None
    # Last probe = high end for numerics; last choice for categoricals.
    return probes[-1][1]


def _select_scenario(path_a: str, path_b: str,
                     spec_a: knob_audit.KnobSpec,
                     spec_b: knob_audit.KnobSpec) -> tuple[str, dict[str, Any]]:
    """Pick a baseline scenario + any extra overrides to keep it feasible."""
    extras: dict[str, Any] = {}
    if path_a in _DR_KNOBS or path_b in _DR_KNOBS:
        return "S_dr_cbp", extras
    if path_a in _HIGH_CAPACITY_KNOBS or path_b in _HIGH_CAPACITY_KNOBS:
        # S_audit_baseline already has ev=50, chargers=60; bump chargers when
        # both knobs push concurrency.
        return "S_audit_baseline", extras
    return knob_audit.DEFAULT_SCENARIO, extras


def _metrics_for_pair(spec_a: knob_audit.KnobSpec,
                      spec_b: knob_audit.KnobSpec) -> list[tuple[str, Any, str | None, str]]:
    """Return list of (csv, metric_fn, region_for_deep, label) tuples that
    cover both knobs' affected CSVs. Deep-channel metrics receive (dfs, region)."""
    out: list[tuple[str, Any, str | None, str]] = []
    seen: set[tuple[str, str]] = set()

    def _push(csv: str, fn, region: str | None, label: str):
        key = (csv, label)
        if key in seen:
            return
        seen.add(key)
        out.append((csv, fn, region, label))

    for spec in (spec_a, spec_b):
        if spec.is_deep_channel:
            region = spec.path.split(".")[-3]
            dist, param = spec.path.rsplit(".", 2)[-2:]
            fn = knob_audit._deep_metric(dist, param)
            _push("sessions.csv", fn, region, f"{region}/{dist}.{param}")
            continue
        override = knob_audit.KNOB_METRIC_OVERRIDES.get(spec.path)
        if override:
            for csv, fn, _, label in override:
                _push(csv, fn, None, label)
            continue
        fallback = {
            "cars.csv": (knob_audit._m_cars_capacity, "capacity_mean"),
            "users.csv": (knob_audit._m_users_phi, "phi_mean"),
            "chargers.csv": (knob_audit._m_chargers_rate, "rate_mean"),
            "sessions.csv": (knob_audit._m_sessions_count, "row_count"),
            "building_load.csv": (knob_audit._m_building_flex, "flex_mean"),
            "grid_prices.csv": (knob_audit._m_grid_mean, "price_mean"),
            "dr_events.csv": (knob_audit._m_dr_count, "row_count"),
        }
        for csv in spec.affects_csv:
            if csv in fallback:
                fn, label = fallback[csv]
                _push(csv, fn, None, label)
    return out


def _classify(m_base: float, m_a: float, m_b: float, m_both: float) -> dict[str, Any]:
    """Decompose joint effect; classify linearity."""
    d_a = m_a - m_base
    d_b = m_b - m_base
    d_both = m_both - m_base
    expected = d_a + d_b

    if abs(expected) < 1e-9 and abs(d_both) < 1e-9:
        return {"verdict": "UNINFORMATIVE", "reason": "no individual effect"}
    if abs(expected) < 1e-9:
        # One leg moved on its own but they cancel each other linearly;
        # any joint deviation here is interaction.
        nonlinearity = float("inf") if abs(d_both) > 1e-9 else 0.0
    else:
        nonlinearity = abs(d_both - expected) / abs(expected)

    sign_flip = (
        np.sign(d_a) == np.sign(d_b) and np.sign(d_a) != 0
        and np.sign(d_both) != np.sign(d_a)
        and abs(d_both) > 0.1 * max(abs(d_a), abs(d_b))
    )

    if sign_flip:
        verdict = "SIGN_FLIP"
    elif nonlinearity < 0.10:
        verdict = "LINEAR"
    elif nonlinearity < 0.30:
        verdict = "MILDLY_NONLINEAR"
    elif nonlinearity < 0.50:
        verdict = "MODERATELY_NONLINEAR"
    else:
        verdict = "STRONGLY_NONLINEAR"

    return {
        "verdict": verdict,
        "d_a": round(d_a, 6),
        "d_b": round(d_b, 6),
        "d_both": round(d_both, 6),
        "expected_linear": round(expected, 6),
        "nonlinearity": round(nonlinearity, 4),
        "sign_flip": bool(sign_flip),
    }


@dataclass
class PairCsvResult:
    csv: str
    metric_label: str
    m_base: float
    m_a: float
    m_b: float
    m_both: float
    verdict: str
    classification: dict[str, Any]


@dataclass
class PairResult:
    knob_a: str
    knob_b: str
    val_a: Any
    val_b: Any
    scenario: str
    csv_results: list[PairCsvResult]
    error: str | None = None


# ──────────────────────────────────────────────────────────────────────────


def _generate_outputs(scenario: str, overrides: dict[str, Any],
                      out_dir: Path, audit_cfg: Path,
                      retries: int = 2) -> tuple[dict[str, Any] | None, str | None]:
    """Run scenario, load CSVs, clean up. Returns (dfs_or_None, error_or_None).

    Retries once on subprocess failure — V3 hit non-deterministic flakes
    under load (subprocess returned nonzero rc + missing sessions.csv even
    though standalone reproduction succeeded 5/5 trials). Likely
    EnergyPlus-cache / disk / signal noise from concurrent test runs."""
    last_err: str | None = None
    for attempt in range(retries + 1):
        if out_dir.exists():
            shutil.rmtree(out_dir)
        ok, err = knob_audit.run_scenario(scenario, overrides, out_dir, audit_cfg)
        if (out_dir / "sessions.csv").exists():
            dfs = knob_audit._load_outputs(out_dir)
            shutil.rmtree(out_dir, ignore_errors=True)
            return dfs, None
        last_err = err or "sessions.csv missing"
    return None, f"after {retries + 1} attempts: {last_err}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-pairs", type=int, default=N_PAIRS)
    ap.add_argument("--audit-dir", default="/tmp/pairwise_audit")
    args = ap.parse_args()

    random.seed(DEFAULT_SEED)
    audit_root = Path(args.audit_dir)
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_cfg = knob_audit._audit_config_dir(audit_root)

    admitted = _load_admitted_paths()
    print(f"[pair] admitted MONOTONIC knobs: {len(admitted)}")
    spec_idx = _build_spec_index()
    admitted = [p for p in admitted if p in spec_idx]

    all_pairs = list(itertools.combinations(admitted, 2))
    sample = random.sample(all_pairs, min(args.n_pairs, len(all_pairs)))
    print(f"[pair] sampled {len(sample)} pairs from {len(all_pairs)} combinations")

    # Per-scenario baselines (cache).
    baseline_dfs: dict[str, dict[str, Any]] = {}

    results: list[PairResult] = []
    t0 = time.time()
    for i, (path_a, path_b) in enumerate(sample):
        spec_a, spec_b = spec_idx[path_a], spec_idx[path_b]
        scen, extras = _select_scenario(path_a, path_b, spec_a, spec_b)
        val_a = _high_probe(spec_a)
        val_b = _high_probe(spec_b)
        if val_a is None or val_b is None:
            results.append(PairResult(path_a, path_b, val_a, val_b, scen,
                                      csv_results=[], error="no high probe"))
            print(f"[{i+1}/{len(sample)}] {path_a} × {path_b}: skip (no probe)")
            continue

        try:
            if scen not in baseline_dfs:
                dfs_b, err_b = _generate_outputs(scen, {**extras},
                                                 audit_root / f"base_{scen}", audit_cfg)
                baseline_dfs[scen] = dfs_b
                if dfs_b is None:
                    raise RuntimeError(f"baseline {scen}: {err_b}")
            base = baseline_dfs[scen]
            only_a, err_a = _generate_outputs(
                scen, {**extras, path_a: val_a}, audit_root / f"a_{i}", audit_cfg)
            only_b, err_bb = _generate_outputs(
                scen, {**extras, path_b: val_b}, audit_root / f"b_{i}", audit_cfg)
            both, err_ab = _generate_outputs(
                scen, {**extras, path_a: val_a, path_b: val_b},
                audit_root / f"ab_{i}", audit_cfg)
            fails = []
            if only_a is None: fails.append(f"only-A: {err_a}")
            if only_b is None: fails.append(f"only-B: {err_bb}")
            if both is None: fails.append(f"both: {err_ab}")
            if fails:
                msg = "; ".join(fails)
                results.append(PairResult(path_a, path_b, val_a, val_b, scen,
                                          csv_results=[], error=msg))
                print(f"[{i+1}/{len(sample)}] {path_a} × {path_b}: GEN-FAIL {msg[:80]}")
                continue

            csv_results = []
            for csv, fn, region, label in _metrics_for_pair(spec_a, spec_b):
                def m(dfs):
                    try:
                        return float(fn(dfs, region) if region is not None else fn(dfs))
                    except Exception:
                        return float("nan")
                m_base = m(base); m_a = m(only_a); m_b = m(only_b); m_both = m(both)
                if any(np.isnan(v) for v in (m_base, m_a, m_b, m_both)):
                    classification = {"verdict": "UNINFORMATIVE", "reason": "nan metric"}
                else:
                    classification = _classify(m_base, m_a, m_b, m_both)
                csv_results.append(PairCsvResult(
                    csv=csv, metric_label=label,
                    m_base=round(m_base, 6), m_a=round(m_a, 6),
                    m_b=round(m_b, 6), m_both=round(m_both, 6),
                    verdict=classification["verdict"],
                    classification=classification,
                ))
            results.append(PairResult(path_a, path_b, val_a, val_b, scen,
                                      csv_results=csv_results))
            # Worst verdict per pair
            worst = _worst_verdict([r.verdict for r in csv_results])
            print(f"[{i+1}/{len(sample)}] {path_a} × {path_b}: {worst}")
        except Exception as e:
            results.append(PairResult(path_a, path_b, val_a, val_b, scen,
                                      csv_results=[], error=f"{type(e).__name__}: {e}"))
            print(f"[{i+1}/{len(sample)}] {path_a} × {path_b}: ERROR {e}")

    elapsed = time.time() - t0
    print(f"\n[pair] total elapsed: {elapsed:.1f}s")

    meta_out = audit_root / "pairwise_metadata.json"
    with meta_out.open("w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_s": elapsed,
            "n_pairs": len(sample),
            "results": [_pair_to_dict(r) for r in results],
        }, f, indent=2)
    print(f"[pair] metadata → {meta_out}")

    report = REPO / "PAIRWISE_AUDIT.md"
    emit_report(results, report, elapsed)
    print(f"[pair] report → {report}")


_VERDICT_RANK = {
    "SIGN_FLIP": 0, "STRONGLY_NONLINEAR": 1, "MODERATELY_NONLINEAR": 2,
    "MILDLY_NONLINEAR": 3, "LINEAR": 4, "UNINFORMATIVE": 5,
}


def _worst_verdict(vs: list[str]) -> str:
    if not vs:
        return "ERROR"
    return min(vs, key=lambda v: _VERDICT_RANK.get(v, 99))


def _pair_to_dict(r: PairResult) -> dict:
    return {
        "knob_a": r.knob_a, "knob_b": r.knob_b,
        "val_a": r.val_a, "val_b": r.val_b,
        "scenario": r.scenario,
        "error": r.error,
        "csv_results": [asdict(c) for c in r.csv_results],
    }


def emit_report(results: list[PairResult], path: Path, elapsed: float) -> None:
    EMOJI = {
        "LINEAR": "✅", "MILDLY_NONLINEAR": "⚠️", "MODERATELY_NONLINEAR": "⚠️",
        "STRONGLY_NONLINEAR": "❌", "SIGN_FLIP": "🔄",
        "UNINFORMATIVE": "🟡", "ERROR": "💥",
    }
    # Aggregate by worst verdict per pair.
    counts: dict[str, int] = {}
    for r in results:
        if r.error:
            counts["ERROR"] = counts.get("ERROR", 0) + 1
            continue
        worst = _worst_verdict([c.verdict for c in r.csv_results])
        counts[worst] = counts.get(worst, 0) + 1

    lines = []
    lines.append("# Pairwise Interaction Audit (V3)\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    lines.append(f"Pairs sampled: {len(results)} (seeded random.seed=42)\n")
    lines.append(f"Total elapsed: {elapsed:.1f}s\n")
    lines.append("\n## Summary\n")
    lines.append("| Verdict | Count |\n|---|---|\n")
    for v in ["LINEAR", "MILDLY_NONLINEAR", "MODERATELY_NONLINEAR",
              "STRONGLY_NONLINEAR", "SIGN_FLIP", "UNINFORMATIVE", "ERROR"]:
        lines.append(f"| {EMOJI[v]} {v} | {counts.get(v, 0)} |\n")
    lines.append(f"| **TOTAL** | **{len(results)}** |\n")

    # Per-bucket detail (worst per pair). Show STRONG / SIGN_FLIP / MODERATE
    # fully; collapse LINEAR + MILDLY + UNINFORMATIVE into a count table.
    detail_buckets = ["SIGN_FLIP", "STRONGLY_NONLINEAR", "MODERATELY_NONLINEAR",
                      "MILDLY_NONLINEAR", "LINEAR", "UNINFORMATIVE", "ERROR"]
    for name in detail_buckets:
        bucket = [r for r in results
                  if (r.error and name == "ERROR")
                  or (not r.error and _worst_verdict([c.verdict for c in r.csv_results]) == name)]
        if not bucket:
            continue
        lines.append(f"\n## {EMOJI[name]} {name} ({len(bucket)} pairs)\n")
        if name in ("LINEAR", "UNINFORMATIVE", "MILDLY_NONLINEAR"):
            lines.append("\n| pair | scenario | worst nonlinearity (csv) |\n|---|---|---|\n")
            for r in bucket:
                worst_c = max((c for c in r.csv_results),
                              key=lambda c: c.classification.get("nonlinearity", 0))
                nl = worst_c.classification.get("nonlinearity", 0)
                lines.append(f"| `{r.knob_a}` × `{r.knob_b}` | {r.scenario} | "
                             f"{nl:.3f} ({worst_c.csv}) |\n")
            continue
        if name == "ERROR":
            for r in bucket:
                lines.append(f"- `{r.knob_a}` × `{r.knob_b}` ({r.scenario}): {r.error}\n")
            continue
        # SIGN_FLIP / STRONGLY / MODERATELY: full detail
        for r in bucket:
            lines.append(f"\n### `{r.knob_a}` × `{r.knob_b}`\n")
            lines.append(f"- Scenario: `{r.scenario}` · val_a=`{r.val_a}` val_b=`{r.val_b}`\n")
            for c in r.csv_results:
                if c.verdict not in (name, "SIGN_FLIP", "STRONGLY_NONLINEAR",
                                     "MODERATELY_NONLINEAR"):
                    continue
                cl = c.classification
                lines.append(
                    f"- **{c.csv}** ({c.metric_label}) {c.verdict}: "
                    f"d_a={cl.get('d_a')}, d_b={cl.get('d_b')}, d_both={cl.get('d_both')}, "
                    f"expected_linear={cl.get('expected_linear')}, "
                    f"nonlinearity={cl.get('nonlinearity')}\n"
                )

    # Top-10 by nonlinearity (any csv, any pair)
    flat = []
    for r in results:
        for c in r.csv_results:
            nl = c.classification.get("nonlinearity", 0)
            if isinstance(nl, (int, float)) and np.isfinite(nl):
                flat.append((nl, r.knob_a, r.knob_b, c.csv, c.metric_label, c.verdict))
    flat.sort(reverse=True)
    lines.append("\n## Top 10 nonlinear interactions (any CSV)\n")
    lines.append("| nonlinearity | knob_a | knob_b | csv | metric | verdict |\n|---|---|---|---|---|---|\n")
    for nl, a, b, csv, lab, v in flat[:10]:
        lines.append(f"| {nl:.3f} | `{a}` | `{b}` | {csv} | {lab} | {v} |\n")

    # Verdict
    strong = counts.get("STRONGLY_NONLINEAR", 0) + counts.get("SIGN_FLIP", 0)
    lines.append("\n## Verdict\n")
    if counts.get("SIGN_FLIP", 0) > 0:
        lines.append("- ❌ SIGN_FLIP detected — investigate before V4.\n")
    elif strong == 0:
        lines.append("- ✅ No STRONGLY_NONLINEAR or SIGN_FLIP findings. Proceed to V4.\n")
    else:
        lines.append("- ⚠️ STRONGLY_NONLINEAR findings present. Inspect for legitimacy.\n")

    path.write_text("".join(lines))


if __name__ == "__main__":
    main()
