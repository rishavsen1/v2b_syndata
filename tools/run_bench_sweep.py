#!/usr/bin/env python
"""Multi-scenario × multi-algorithm benchmark sweep.

Usage:
    uv run python tools/run_bench_sweep.py \
        --output data/sweep \
        --seed 42 \
        [--gen-workers 8] [--bench-workers 20]

Selects a representative scenario set (climate × population × scale axes),
generates each (scenario, seed) if missing in parallel, runs each
(scenario × 7 algorithms) bench in parallel, writes:
    data/sweep/scenarios/<scenario>/seed<NNN>/   (generated outputs)
    data/sweep/results.csv                       (one row per scenario × algo)
    data/sweep/peak_kw_by_scenario.png           (smoke figure)

The scenario set spans climate (Miami summer / Minneapolis winter),
population (consent_strict, evwatts_workplace_public, inl_residential_legacy,
elaadnl_public_eu — 4 calibration sources), equipment (S_eq_bi), ψ
(low/high), DR (CBP), audit baseline (50 EV / 1 charger upper bound), and
the three new scale scenarios (100 / 250 / 500 EV).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# Make src/ importable when run as a script.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from v2b_syndata.bench import available_algorithms, run_scenario  # noqa: E402
from v2b_syndata.runner import generate as runner_generate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sweep")


# 13 scenarios spanning climate × population × ψ × equipment × DR × scale.
# Calibration-source coverage: ACN (consent_default in S01), EV WATTS,
# INL, ElaadNL = 4 sources represented.
REPRESENTATIVE_SCENARIOS = [
    "S01",
    "S_clim_miami_summer",
    "S_clim_minneapolis_winter",
    "S_consent_strict",
    "S_evwatts_workplace",
    "S_inl_residential_legacy",
    "S_elaadnl_public_eu",
    "S_eq_bi",
    "S_psi_010",
    "S_psi_090",
    "S_dr_cbp",
    "S_scale_100",
    "S_scale_250",
    "S_scale_500",
]


def _generate_one(args: tuple[str, int, Path, Path]) -> tuple[str, Path, bool, str]:
    """Generate one (scenario, seed) into scenario_dir. Skip if manifest exists."""
    scenario, seed, scenario_dir, config_dir = args
    manifest = scenario_dir / "manifest.json"
    if manifest.exists():
        return scenario, scenario_dir, True, "skipped (manifest present)"
    try:
        runner_generate(
            scenario_id=scenario,
            seed=seed,
            output_dir=scenario_dir,
            config_dir=config_dir,
        )
        return scenario, scenario_dir, True, "generated"
    except Exception as e:  # noqa: BLE001
        return scenario, scenario_dir, False, f"{type(e).__name__}: {e}"


def _bench_one(args: tuple[str, str, Path]) -> dict | None:
    """Run one (scenario, algorithm) bench combination."""
    scenario, algorithm, scenario_dir = args
    try:
        result = run_scenario(scenario_dir=scenario_dir, algorithm=algorithm)
        d = result.to_dict()
        d["scenario"] = scenario
        return d
    except Exception as e:  # noqa: BLE001
        log.error("bench failed: scenario=%s algo=%s err=%s", scenario, algorithm, e)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description="V2B bench sweep")
    p.add_argument("--output", default="data/sweep",
                   help="output directory root (default: data/sweep)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--config-dir", default=str(REPO / "configs"))
    p.add_argument("--gen-workers", type=int, default=8,
                   help="parallel workers for scenario generation (default: 8)")
    p.add_argument("--bench-workers", type=int, default=20,
                   help="parallel workers for bench runs (default: 20)")
    p.add_argument("--scenarios", nargs="+", default=None,
                   help="override scenario list (space-separated)")
    p.add_argument("--algos", nargs="+", default=None,
                   help="override algorithm list (default: all registered)")
    p.add_argument("--skip-figures", action="store_true",
                   help="don't render smoke figure")
    args = p.parse_args()

    output_root = Path(args.output)
    scenarios_dir = output_root / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    scenarios = args.scenarios or REPRESENTATIVE_SCENARIOS
    algos = args.algos or available_algorithms()
    config_dir = Path(args.config_dir)

    log.info("sweep config: %d scenarios × %d algos = %d bench runs",
             len(scenarios), len(algos), len(scenarios) * len(algos))
    log.info("gen workers=%d, bench workers=%d", args.gen_workers, args.bench_workers)

    # ── Stage 1: generate scenarios in parallel ────────────────────────
    gen_jobs = []
    for s in scenarios:
        scenario_dir = scenarios_dir / s / f"seed{args.seed}"
        gen_jobs.append((s, args.seed, scenario_dir, config_dir))

    t_gen = time.perf_counter()
    log.info("stage 1: generating %d scenarios (workers=%d)...",
             len(gen_jobs), args.gen_workers)
    scenario_dirs: dict[str, Path] = {}
    failures: list[str] = []
    with ProcessPoolExecutor(max_workers=args.gen_workers) as ex:
        for fut in as_completed([ex.submit(_generate_one, j) for j in gen_jobs]):
            scenario, sdir, ok, msg = fut.result()
            log.info("  %s %s: %s", "✓" if ok else "✗", scenario, msg)
            if ok:
                scenario_dirs[scenario] = sdir
            else:
                failures.append(f"{scenario}: {msg}")
    log.info("stage 1 done in %.1fs (%d ok / %d fail)",
             time.perf_counter() - t_gen, len(scenario_dirs), len(failures))
    if failures and not scenario_dirs:
        log.error("all generations failed; abort")
        return 2

    # ── Stage 2: bench × algorithm matrix in parallel ──────────────────
    bench_jobs = []
    for scenario, sdir in scenario_dirs.items():
        for algo in algos:
            bench_jobs.append((scenario, algo, sdir))

    t_bench = time.perf_counter()
    log.info("stage 2: benching %d (scenario, algo) combos (workers=%d)...",
             len(bench_jobs), args.bench_workers)
    rows = []
    with ProcessPoolExecutor(max_workers=args.bench_workers) as ex:
        for fut in as_completed([ex.submit(_bench_one, j) for j in bench_jobs]):
            r = fut.result()
            if r:
                rows.append(r)
    log.info("stage 2 done in %.1fs (%d/%d succeeded)",
             time.perf_counter() - t_bench, len(rows), len(bench_jobs))

    if not rows:
        log.error("no bench runs succeeded; abort")
        return 2

    df = pd.DataFrame(rows).sort_values(["scenario", "algorithm"]).reset_index(drop=True)
    # Drop the noisy per_session_fulfillment list field from the CSV view.
    if "per_session_fulfillment" in df.columns:
        df = df.drop(columns=["per_session_fulfillment"])
    csv_path = output_root / "results.csv"
    df.to_csv(csv_path, index=False)
    log.info("wrote %s (%d rows)", csv_path, len(df))

    # ── Stage 3: smoke figure (peak_kw_by_scenario) ────────────────────
    if not args.skip_figures:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            scenarios_sorted = sorted(df["scenario"].unique())
            algos_sorted = sorted(df["algorithm"].unique())
            x = np.arange(len(scenarios_sorted))
            w = 0.8 / max(1, len(algos_sorted))

            fig, ax = plt.subplots(figsize=(max(10, len(scenarios_sorted) * 0.8), 5))
            for i, a in enumerate(algos_sorted):
                vals = []
                for s in scenarios_sorted:
                    row = df[(df["scenario"] == s) & (df["algorithm"] == a)]
                    vals.append(float(row["peak_net_kw"].iloc[0]) if not row.empty else np.nan)
                ax.bar(x + i * w - 0.4 + w / 2, vals, w, label=a)
            ax.set_xticks(x)
            ax.set_xticklabels(scenarios_sorted, rotation=45, ha="right")
            ax.set_ylabel("peak_net_kw")
            ax.set_title("Peak net load (kW) by scenario × scheduling algorithm")
            ax.legend(loc="upper left", ncol=2, fontsize=8)
            fig.tight_layout()
            fig_path = output_root / "peak_kw_by_scenario.png"
            fig.savefig(fig_path, dpi=120)
            log.info("wrote %s", fig_path)
        except ImportError as e:
            log.warning("matplotlib unavailable, skipping figure: %s", e)

    # Print summary table
    print("\n=== bench sweep summary ===")
    pivot = df.pivot(index="scenario", columns="algorithm", values="target_miss_rate")
    print(pivot.round(4).to_string())
    print(f"\nresults.csv: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
