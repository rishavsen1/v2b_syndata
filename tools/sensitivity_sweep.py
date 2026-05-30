#!/usr/bin/env python
"""2-axis sensitivity sweep: slot ratio × feeder ratio × algorithm.

Slot ratio = nominal `n_evs / n_chargers` for the scenarios below. The
effective ratio (peak_concurrent / n_chargers) drifts below nominal as
the scenario plays out — both are reported in the output CSV.

Feeder ratio = aggregate-current cap divided by theoretical max
(`n_chargers × per-EVSE max_kw`). Lower = tighter power constraint.

Output:
    data/sensitivity/results.csv   (one row per scenario × feeder × algo)
    data/sensitivity/heatmap_e2e_miss.png   (paper figure candidate)
    data/sensitivity/heatmap_target_miss.png

Usage:
    uv run python tools/sensitivity_sweep.py \\
        --output data/sensitivity \\
        --seed 42 \\
        [--workers 16]
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
log = logging.getLogger("sens")


# Slot-ratio axis: D2 (varying fleet at fixed 100 chargers) + D3 (varying
# chargers at fixed 200 fleet). Together they sweep both halves of the
# slot-contention space.
SCENARIOS = [
    # (scenario_id, family_for_grouping)
    ("S_cont_fleet_100", "fleet_vary_100ch"),     # 1.0× nominal
    ("S_cont_fleet_250", "fleet_vary_100ch"),     # 2.5×
    ("S_cont_fleet_500", "fleet_vary_100ch"),     # 5.0×
    ("S_infra_200",      "infra_vary_200ev"),     # 1.0× nominal (n_chargers=200)
    ("S_infra_100",      "infra_vary_200ev"),     # 2.0×
    ("S_infra_50",       "infra_vary_200ev"),     # 4.0×
]

# Feeder-ratio axis: aggregate-current cap as fraction of theoretical max
# (n_chargers × max_kw). 1.0 = unbinding; 0.1 = 10× undersized.
FEEDER_RATIOS = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0]


def _generate_one(args: tuple[str, int, Path, Path]):
    scenario, seed, scenario_dir, config_dir = args
    manifest = scenario_dir / "manifest.json"
    if manifest.exists():
        return scenario, scenario_dir, True, "cached"
    try:
        runner_generate(
            scenario_id=scenario, seed=seed,
            output_dir=scenario_dir, config_dir=config_dir,
        )
        return scenario, scenario_dir, True, "generated"
    except Exception as e:  # noqa: BLE001
        return scenario, scenario_dir, False, f"{type(e).__name__}: {e}"


def _bench_one(args):
    scenario, family, algorithm, feeder, scenario_dir = args
    try:
        r = run_scenario(
            scenario_dir=scenario_dir,
            algorithm=algorithm,
            feeder_kw_ratio=feeder,
        )
        d = r.to_dict()
        d["scenario"] = scenario
        d["family"] = family
        return d
    except Exception as e:  # noqa: BLE001
        log.error("bench failed: %s %s feeder=%.2f err=%s",
                  scenario, algorithm, feeder, e)
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/sensitivity")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--config-dir", default=str(REPO / "configs"))
    p.add_argument("--workers", type=int, default=16)
    args = p.parse_args()

    output_root = Path(args.output)
    scenarios_dir = output_root / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    algos = available_algorithms()
    n_combos = len(SCENARIOS) * len(FEEDER_RATIOS) * len(algos)
    log.info("sensitivity sweep: %d scenarios × %d feeder × %d algos = %d runs",
             len(SCENARIOS), len(FEEDER_RATIOS), len(algos), n_combos)

    # ── Stage 1: generate scenarios ──
    gen_jobs = [
        (s, args.seed, scenarios_dir / s / f"seed{args.seed}", Path(args.config_dir))
        for s, _ in SCENARIOS
    ]
    log.info("stage 1: generating %d scenarios...", len(gen_jobs))
    scenario_dirs: dict[str, Path] = {}
    with ProcessPoolExecutor(max_workers=min(args.workers, 8)) as ex:
        for fut in as_completed([ex.submit(_generate_one, j) for j in gen_jobs]):
            scenario, sdir, ok, msg = fut.result()
            log.info("  %s %s: %s", "✓" if ok else "✗", scenario, msg)
            if ok:
                scenario_dirs[scenario] = sdir

    # ── Stage 2: bench grid ──
    bench_jobs = []
    for scenario, family in SCENARIOS:
        if scenario not in scenario_dirs:
            continue
        sdir = scenario_dirs[scenario]
        for feeder in FEEDER_RATIOS:
            for algo in algos:
                bench_jobs.append((scenario, family, algo, feeder, sdir))

    t_bench = time.perf_counter()
    log.info("stage 2: %d bench combos (workers=%d)...", len(bench_jobs), args.workers)
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
    df = df.sort_values(["family", "scenario", "feeder_kw_ratio", "algorithm"])
    csv_path = output_root / "results.csv"
    df.to_csv(csv_path, index=False)
    log.info("wrote %s (%d rows)", csv_path, len(df))

    # ── Stage 3: heatmaps + summary ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        # One heatmap per (family, metric). Rows = scenarios (slot axis),
        # cols = feeder ratios, colors = max-over-algos − min-over-algos
        # for "spread" view, or pick algo == 'edf'/'lrpt' separately.
        for metric in ("e2e_miss_rate", "target_miss_rate", "admission_rejection_rate"):
            fig, axes = plt.subplots(2, len(algos), figsize=(3.0 * len(algos), 6))
            for col_idx, algo in enumerate(algos):
                for row_idx, family in enumerate(("fleet_vary_100ch", "infra_vary_200ev")):
                    sub = df[(df["family"] == family) & (df["algorithm"] == algo)]
                    if sub.empty:
                        continue
                    pivot = sub.pivot(
                        index="scenario",
                        columns="feeder_kw_ratio",
                        values=metric,
                    )
                    ax = axes[row_idx, col_idx]
                    im = ax.imshow(pivot.values, aspect="auto",
                                   vmin=0, vmax=df[metric].max() or 1, cmap="viridis")
                    ax.set_xticks(range(len(pivot.columns)))
                    ax.set_xticklabels([f"{c:.1f}" for c in pivot.columns], fontsize=7)
                    ax.set_yticks(range(len(pivot.index)))
                    ax.set_yticklabels(list(pivot.index), fontsize=7)
                    title = f"{algo}" if row_idx == 0 else ""
                    ylab = family if col_idx == 0 else ""
                    ax.set_title(title, fontsize=9)
                    ax.set_ylabel(ylab, fontsize=8)
            fig.suptitle(f"{metric} — slot × feeder × algorithm", fontsize=11)
            fig.tight_layout()
            fig_path = output_root / f"heatmap_{metric}.png"
            fig.savefig(fig_path, dpi=120)
            plt.close(fig)
            log.info("wrote %s", fig_path)
    except ImportError as e:
        log.warning("matplotlib unavailable: %s", e)

    # Print compact summary
    print("\n=== sensitivity summary: e2e_miss_rate ===")
    print("Each block: scenario rows × feeder columns. One block per algo.")
    for algo in algos:
        sub = df[df["algorithm"] == algo]
        if sub.empty:
            continue
        pivot = sub.pivot(
            index="scenario", columns="feeder_kw_ratio", values="e2e_miss_rate"
        )
        print(f"\n--- {algo} ---")
        print(pivot.round(3).to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())
