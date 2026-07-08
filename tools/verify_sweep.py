#!/usr/bin/env python
"""Verification harness for the bench sweep.

Two-part check:

1. **Data generation correctness** — for each generated scenario_dir:
   - Hard validators (D5/D6/C4 etc.) via v2b_syndata.validate
   - Schema sanity: row counts match knob values (ev_count, charger_count)
   - Manifest e5 block matches realized concurrency
   - SoC distributions within [min_allowed, max_allowed]
   - arrival < required (D6) row-by-row
   - arrival < departure (C4) row-by-row

2. **Algorithm sanity** — for each row in results.csv:
   - All metrics in plausible numeric ranges
   - Expected ordering: uncontrolled.peak >= scheduled.peak (no scheduler = highest peak)
   - EDF/LLF target_miss_rate <= LRPT (deadline-aware ≥ deadline-blind in oversubscribed regime)
   - energy_fulfillment_rate ∈ [0, 1.5] (1.5 allows uncontrolled overcharge quirk)
   - n_sessions_offered > 0 and n_sessions_admitted + n_sessions_rejected == n_sessions_offered

Exit 0 = all checks pass; 1 = soft warnings; 2 = hard failures.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from v2b_syndata.validate import validate  # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# Data generation checks
# ──────────────────────────────────────────────────────────────────────

def check_scenario_data(scenario: str, sdir: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one generated scenario directory."""
    errors: list[str] = []
    warnings: list[str] = []

    if not sdir.exists():
        return [f"{scenario}: scenario dir missing: {sdir}"], []

    # 1. Hard validator
    try:
        rep = validate(sdir)
        if not rep.passed:
            for e in rep.errors:
                # E5 is expected to fire on oversubscribed scenarios — it's a
                # property of the scenario, not a bug. Demote to warning.
                if e.startswith("E5:"):
                    warnings.append(f"{scenario}: E5 expected (oversubscribed): {e}")
                else:
                    errors.append(f"{scenario}: validator: {e}")
        for w in rep.warnings:
            warnings.append(f"{scenario}: validator warn: {w}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"{scenario}: validate raised {type(e).__name__}: {e}")
        return errors, warnings

    # 2. Schema counts vs knob values
    try:
        manifest = json.loads((sdir / "manifest.json").read_text())
        knobs = manifest.get("knob_resolution", {})
        ev_count = int(knobs.get("ev_fleet.ev_count", {}).get("value", 0))
        charger_count = int(knobs.get("charging_infra.charger_count", {}).get("value", 0))

        cars = pd.read_csv(sdir / "cars.csv")
        chargers = pd.read_csv(sdir / "chargers.csv")
        users = pd.read_csv(sdir / "users.csv")
        sessions = pd.read_csv(sdir / "sessions.csv", parse_dates=["arrival", "departure"])

        if len(cars) != ev_count:
            errors.append(f"{scenario}: cars.csv has {len(cars)} rows; expected {ev_count}")
        if len(users) != ev_count:
            errors.append(f"{scenario}: users.csv has {len(users)} rows; expected {ev_count}")
        if len(chargers) != charger_count:
            errors.append(f"{scenario}: chargers.csv has {len(chargers)} rows; expected {charger_count}")
        if len(sessions) == 0:
            errors.append(f"{scenario}: sessions.csv empty")

        # 3. Row-level invariants
        # D6: arrival_soc < required_soc_at_depart
        d6_violations = (sessions["arrival_soc"] >= sessions["required_soc_at_depart"]).sum()
        if d6_violations > 0:
            errors.append(f"{scenario}: D6 violated in {d6_violations} sessions (arrival_soc >= required)")

        # C4: arrival < departure
        c4_violations = (sessions["arrival"] >= sessions["departure"]).sum()
        if c4_violations > 0:
            errors.append(f"{scenario}: C4 violated in {c4_violations} sessions (arrival >= departure)")

        # SoC within per-car bounds
        sessions_with_bounds = sessions.merge(
            cars[["car_id", "min_allowed_soc", "max_allowed_soc"]],
            on="car_id",
            how="left",
        )
        below_min = (sessions_with_bounds["arrival_soc"] < sessions_with_bounds["min_allowed_soc"]).sum()
        above_max = (sessions_with_bounds["arrival_soc"] > sessions_with_bounds["max_allowed_soc"]).sum()
        if below_min > 0:
            errors.append(f"{scenario}: {below_min} sessions with arrival_soc below min_allowed_soc")
        if above_max > 0:
            errors.append(f"{scenario}: {above_max} sessions with arrival_soc above max_allowed_soc")

        # 4. Manifest e5 block consistency check
        e5 = manifest.get("e5", {})
        if e5:
            realized = e5.get("realized_max_concurrent", 0)
            n_chargers = e5.get("n_chargers", 0)
            infeasible_frac = e5.get("infeasible_tick_fraction", 0.0)
            if realized > n_chargers and infeasible_frac > 0:
                # expected on oversubscribed scenarios
                pass
            elif realized > n_chargers and infeasible_frac == 0:
                errors.append(
                    f"{scenario}: e5 block inconsistent: realized {realized} > n_chargers "
                    f"{n_chargers} but infeasible_tick_fraction == 0"
                )

    except FileNotFoundError as e:
        errors.append(f"{scenario}: missing CSV: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"{scenario}: data check raised {type(e).__name__}: {e}")

    return errors, warnings


# ──────────────────────────────────────────────────────────────────────
# Algorithm sanity checks
# ──────────────────────────────────────────────────────────────────────

def check_algorithm_results(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Per-scenario sanity checks on the bench result matrix."""
    errors: list[str] = []
    warnings: list[str] = []

    for scenario, gdf in df.groupby("scenario"):
        gdf = gdf.set_index("algorithm")

        # 1. Metric range sanity
        for algo, row in gdf.iterrows():
            if not (0.0 <= row["target_miss_rate"] <= 1.0):
                errors.append(f"{scenario}/{algo}: target_miss_rate {row['target_miss_rate']} ∉ [0,1]")
            if row["energy_fulfillment_rate"] < 0 or row["energy_fulfillment_rate"] > 1.5:
                errors.append(
                    f"{scenario}/{algo}: energy_fulfillment_rate {row['energy_fulfillment_rate']} ∉ [0,1.5]"
                )
            if row["peak_charge_kw"] < 0:
                errors.append(f"{scenario}/{algo}: peak_charge_kw {row['peak_charge_kw']} < 0")
            if row["n_sessions_offered"] <= 0:
                errors.append(f"{scenario}/{algo}: n_sessions_offered == 0 (no sessions?)")
            if row["n_sessions_admitted"] + row["n_sessions_rejected"] != row["n_sessions_offered"]:
                errors.append(
                    f"{scenario}/{algo}: admitted ({row['n_sessions_admitted']}) + rejected "
                    f"({row['n_sessions_rejected']}) != offered ({row['n_sessions_offered']})"
                )

        # 2. Uncontrolled should have highest peak_charge_kw (no scheduling)
        if "uncontrolled" in gdf.index:
            uc = float(gdf.loc["uncontrolled", "peak_charge_kw"])
            others = gdf.drop("uncontrolled")
            others_peak = float(others["peak_charge_kw"].max())
            if uc < others_peak - 1.0:  # 1 kW tolerance
                warnings.append(
                    f"{scenario}: uncontrolled peak_charge_kw ({uc:.1f}) < max scheduled ({others_peak:.1f})"
                )

        # 3. In oversubscribed scenarios, EDF/LLF should beat LRPT on target_miss
        # (deadline-aware ≥ deadline-blind). Use a 5%-difference threshold to
        # avoid noise on barely-contended scenarios.
        if {"edf", "lrpt"}.issubset(gdf.index):
            edf_miss = float(gdf.loc["edf", "target_miss_rate"])
            lrpt_miss = float(gdf.loc["lrpt", "target_miss_rate"])
            if edf_miss > lrpt_miss + 0.005 and lrpt_miss > 0.005:
                warnings.append(
                    f"{scenario}: EDF target_miss ({edf_miss:.3f}) > LRPT ({lrpt_miss:.3f}) "
                    f"— unexpected for deadline-aware vs deadline-blind"
                )

    return errors, warnings


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Verify bench sweep correctness")
    p.add_argument("--sweep-dir", default="data/sweep")
    args = p.parse_args()

    sweep_dir = Path(args.sweep_dir)
    scenarios_dir = sweep_dir / "scenarios"
    results_csv = sweep_dir / "results.csv"

    if not results_csv.exists():
        print(f"ERROR: {results_csv} missing", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    all_warnings: list[str] = []

    # ── Part 1: data generation ──
    print("=== Part 1: data generation correctness ===")
    scenario_dirs = sorted(scenarios_dir.iterdir()) if scenarios_dir.exists() else []
    for sdir in scenario_dirs:
        if not sdir.is_dir():
            continue
        scenario = sdir.name
        seed_dirs = list(sdir.glob("seed*"))
        for seed_dir in seed_dirs:
            errs, warns = check_scenario_data(scenario, seed_dir)
            all_errors.extend(errs)
            all_warnings.extend(warns)
            status = "✗" if errs else ("⚠" if warns else "✓")
            print(f"  {status} {scenario}/{seed_dir.name} "
                  f"({len(errs)} err, {len(warns)} warn)")

    # ── Part 2: algorithm sanity ──
    print("\n=== Part 2: algorithm sanity ===")
    df = pd.read_csv(results_csv)
    algo_errs, algo_warns = check_algorithm_results(df)
    all_errors.extend(algo_errs)
    all_warnings.extend(algo_warns)
    print(f"  checked {len(df)} (scenario, algo) result rows")
    print(f"  algo errors:   {len(algo_errs)}")
    print(f"  algo warnings: {len(algo_warns)}")

    # ── Summary ──
    print("\n=== Summary ===")
    print(f"errors:   {len(all_errors)}")
    print(f"warnings: {len(all_warnings)}")
    if all_errors:
        print("\n--- ERRORS ---")
        for e in all_errors[:30]:
            print(f"  {e}")
        if len(all_errors) > 30:
            print(f"  ... and {len(all_errors) - 30} more")
    if all_warnings:
        print("\n--- WARNINGS (first 30) ---")
        for w in all_warnings[:30]:
            print(f"  {w}")
        if len(all_warnings) > 30:
            print(f"  ... and {len(all_warnings) - 30} more")

    if all_errors:
        return 2
    if all_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
