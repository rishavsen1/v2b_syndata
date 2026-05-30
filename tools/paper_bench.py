#!/usr/bin/env python
"""Paper-grade benchmark: 7 representative scenarios × 7 ACN-Sim algorithms.

Scope: shows v2b_syndata generated CSVs flow through ACN-Sim's standard
scheduling pipeline. Feeder cap unbinding (ratio=1.0) — published scope
models physical-slot scarcity via FCFS admission only.

The 7 scenarios span:
  - S01                       — ACN-anchored baseline (Nashville)
  - S_evwatts_workplace       — EV WATTS calibration source
  - S_inl_residential_legacy  — INL Phase 1 calibration source
  - S_elaadnl_public_eu       — ElaadNL calibration source
  - S_clim_miami_summer       — climate-driven load variant
  - S_psi_090                 — behaviorally-saturated population
  - S_cont_fleet_500          — large-fleet scaled scenario

Output:
    data/paper_bench/results.csv               (49 rows: 7×7)
    data/paper_bench/scenario_axis_metrics.png (paper figure)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from v2b_syndata.bench import available_algorithms, run_scenario  # noqa: E402
from v2b_syndata.runner import generate as runner_generate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("paper_bench")


PAPER_SCENARIOS = [
    ("S01", "ACN-Data"),
    ("S_evwatts_workplace", "EV WATTS"),
    ("S_inl_residential_legacy", "INL Phase 1"),
    ("S_elaadnl_public_eu", "ElaadNL"),
    ("S_clim_miami_summer", "Climate (Miami)"),
    ("S_psi_090", "Behavioral (high ψ)"),
    ("S_cont_fleet_500", "Scale (500 EV)"),
]


def _gen_one(args):
    scenario, seed, sdir, cfg = args
    if (sdir / "manifest.json").exists():
        return scenario, sdir, True, "cached"
    try:
        runner_generate(scenario_id=scenario, seed=seed, output_dir=sdir, config_dir=cfg)
        return scenario, sdir, True, "generated"
    except Exception as e:  # noqa: BLE001
        return scenario, sdir, False, f"{type(e).__name__}: {e}"


def _bench_one(args):
    scenario, label, algo, sdir = args
    try:
        r = run_scenario(scenario_dir=sdir, algorithm=algo, feeder_kw_ratio=1.0)
        d = r.to_dict()
        d["scenario"] = scenario
        d["scenario_label"] = label
        return d
    except Exception as e:  # noqa: BLE001
        log.error("bench failed: %s %s err=%s", scenario, algo, e)
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/paper_bench")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--config-dir", default=str(REPO / "configs"))
    p.add_argument("--workers", type=int, default=14)
    args = p.parse_args()

    out_root = Path(args.output)
    scens_dir = out_root / "scenarios"
    scens_dir.mkdir(parents=True, exist_ok=True)

    algos = available_algorithms()
    log.info("paper bench: %d scenarios × %d algos = %d runs",
             len(PAPER_SCENARIOS), len(algos), len(PAPER_SCENARIOS) * len(algos))

    # Stage 1: generate
    gen_jobs = [(s, args.seed, scens_dir / s / f"seed{args.seed}", Path(args.config_dir))
                for s, _ in PAPER_SCENARIOS]
    log.info("stage 1: generating %d scenarios...", len(gen_jobs))
    sdir_map: dict[str, Path] = {}
    with ProcessPoolExecutor(max_workers=min(args.workers, 8)) as ex:
        for fut in as_completed([ex.submit(_gen_one, j) for j in gen_jobs]):
            scenario, sdir, ok, msg = fut.result()
            log.info("  %s %s: %s", "✓" if ok else "✗", scenario, msg)
            if ok:
                sdir_map[scenario] = sdir

    # Stage 2: bench
    bench_jobs = []
    for s, label in PAPER_SCENARIOS:
        if s not in sdir_map:
            continue
        for algo in algos:
            bench_jobs.append((s, label, algo, sdir_map[s]))

    t_bench = time.perf_counter()
    log.info("stage 2: %d bench combos...", len(bench_jobs))
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed([ex.submit(_bench_one, j) for j in bench_jobs]):
            r = fut.result()
            if r:
                rows.append(r)
    log.info("stage 2 done in %.1fs (%d/%d succeeded)",
             time.perf_counter() - t_bench, len(rows), len(bench_jobs))

    if not rows:
        return 2

    df = pd.DataFrame(rows)
    if "per_session_fulfillment" in df.columns:
        df = df.drop(columns=["per_session_fulfillment"])
    df = df.sort_values(["scenario", "algorithm"]).reset_index(drop=True)
    csv_path = out_root / "results.csv"
    df.to_csv(csv_path, index=False)
    log.info("wrote %s (%d rows)", csv_path, len(df))

    # Stage 3: paper figure
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        # Three subplots: target_miss, admission_rejection, peak_charge_kw
        scenarios_ordered = [s for s, _ in PAPER_SCENARIOS]
        labels_ordered = [f"{s}\n{lab}" for s, lab in PAPER_SCENARIOS]
        algos_sorted = sorted(df["algorithm"].unique())

        fig, axes = plt.subplots(3, 1, figsize=(11, 9))
        for ax_idx, (metric, ylabel) in enumerate([
            ("target_miss_rate", "target_miss_rate (admitted)"),
            ("admission_rejection_rate", "admission_rejection_rate"),
            ("peak_charge_kw", "peak_charge_kw"),
        ]):
            ax = axes[ax_idx]
            x = np.arange(len(scenarios_ordered))
            w = 0.8 / max(1, len(algos_sorted))
            for i, algo in enumerate(algos_sorted):
                vals = []
                for s in scenarios_ordered:
                    row = df[(df["scenario"] == s) & (df["algorithm"] == algo)]
                    vals.append(float(row[metric].iloc[0]) if not row.empty else np.nan)
                ax.bar(x + i * w - 0.4 + w / 2, vals, w, label=algo)
            ax.set_xticks(x)
            if ax_idx == 2:
                ax.set_xticklabels(labels_ordered, rotation=30, ha="right", fontsize=8)
            else:
                ax.set_xticklabels([])
            ax.set_ylabel(ylabel, fontsize=9)
            if ax_idx == 0:
                ax.legend(loc="upper left", ncol=4, fontsize=7, frameon=False)
        fig.suptitle(
            "v2b_syndata × ACN-Sim: 7 scenarios × 7 algorithms (feeder unbinding)",
            fontsize=11,
        )
        fig.tight_layout()
        fig_path = out_root / "scenario_axis_metrics.png"
        fig.savefig(fig_path, dpi=130)
        plt.close(fig)
        log.info("wrote %s", fig_path)
    except ImportError as e:
        log.warning("matplotlib unavailable: %s", e)

    # Summary table
    print("\n=== paper bench: target_miss_rate ===")
    pivot = df.pivot(index="scenario", columns="algorithm", values="target_miss_rate")
    print(pivot.round(4).to_string())
    print("\n=== paper bench: peak_charge_kw ===")
    pivot2 = df.pivot(index="scenario", columns="algorithm", values="peak_charge_kw")
    print(pivot2.round(0).to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
