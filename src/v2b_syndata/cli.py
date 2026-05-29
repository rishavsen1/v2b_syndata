"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .e5_metrics import InfeasibilityError
from .knob_loader import all_knob_paths, load_knob_registry, parse_overrides
from .runner import generate
from .validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "configs"

# Auto-load .env at repo root if present. Existing env vars take precedence
# (override=False) so shell-set ACN_API_TOKEN beats .env file.
load_dotenv(REPO_ROOT / ".env", override=False)


def cmd_generate(args: argparse.Namespace) -> int:
    cli_overrides = parse_overrides(args.override or [])
    try:
        manifest = generate(
            scenario_id=args.scenario,
            seed=args.seed,
            output_dir=Path(args.output_dir),
            config_dir=Path(args.config_dir),
            cli_overrides=cli_overrides,
            noise_profile_override=args.noise_profile,
            strict_e5=args.strict_e5,
        )
    except InfeasibilityError as e:
        print(f"E5 STRICT ERROR: {e}", file=sys.stderr)
        return 2
    print(f"generated {manifest['scenario_id']} seed={manifest['seed']} -> {args.output_dir}")
    # Auto-validate only when no perturbation was actually applied. Per-jitter
    # knobs are authoritative — checking profile name alone misses cases where
    # the user overrode individual jitters under a clean profile (or vice
    # versa). Run `cli validate <dir>` explicitly for noisy outputs.
    if _all_jitters_zero(manifest):
        rep = validate(Path(args.output_dir), strict=False)
        if not rep.passed:
            print("VALIDATION FAILED:", file=sys.stderr)
            for e in rep.errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        if rep.warnings:
            for w in rep.warnings:
                print(f"  warning: {w}", file=sys.stderr)
    return 0


_JITTER_KNOBS = (
    "noise.building_load_jitter_pct",
    "noise.arrival_time_jitter_min",
    "noise.soc_arrival_jitter_pct",
    "noise.dr_notification_dropout_prob",
    "noise.price_jitter_pct",
    "noise.occupancy_jitter_pct",
)


def _all_jitters_zero(manifest: dict) -> bool:
    res = manifest.get("knob_resolution", {})
    for k in _JITTER_KNOBS:
        entry = res.get(k)
        if entry is None:
            continue
        if float(entry["value"]) != 0.0:
            return False
    return True


def cmd_validate(args: argparse.Namespace) -> int:
    rep = validate(Path(args.output_dir), strict=args.strict)
    if rep.errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in rep.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    if rep.warnings:
        for w in rep.warnings:
            print(f"  warning: {w}", file=sys.stderr)
    print("OK")
    return 0


def cmd_list_knobs(args: argparse.Namespace) -> int:
    reg = load_knob_registry(Path(args.config_dir) / "knobs.yaml")
    for path in all_knob_paths(reg):
        spec = reg[path]
        typ = spec.get("type", "?")
        default = spec.get("default")
        print(f"{path:55s}  type={typ:18s}  default={default!r}")
    return 0


def cmd_list_scenarios(args: argparse.Namespace) -> int:
    sdir = Path(args.config_dir) / "scenarios"
    for f in sorted(sdir.glob("*.yaml")):
        with f.open() as fh:
            sc = yaml.safe_load(fh)
        print(f"{sc['scenario_id']:8s}  {sc.get('description', '')}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    import warnings
    import yaml as _yaml
    from .calibration import calibrate_populations
    from .calibration.sources import CALIBRATION_SOURCES

    pops_path = Path(args.config_dir) / "populations.yaml"
    pops = args.population if args.population else None
    population_names = [pops] if pops else None

    # Translate deprecated --site/--year-start/--year-end into ACN source-args.
    legacy_used = bool(args.site) or args.year_start != 2019 or args.year_end != 2021
    if legacy_used:
        warnings.warn(
            "--site / --year-start / --year-end are deprecated; "
            "use --source-arg site=... --source-arg year_start=... --source-arg year_end=...",
            DeprecationWarning,
            stacklevel=2,
        )
    sites = tuple(args.site) if args.site else ("caltech", "jpl", "office001")

    # Partition --source-arg by optional `policy:` prefix; unprefixed args
    # route to the policy of the targeted population (or acn_data when no
    # single population resolves — preserves legacy ACN-only behavior).
    # Short aliases let users type the friendly name (e.g. `inl:`) instead
    # of the registry key (`inl_ev_project:`).
    _POLICY_ALIASES = {"inl": "inl_ev_project", "elaadnl": "elaadnl_open_2020"}
    raw_by_policy: dict[str, list[str]] = {}
    unscoped: list[str] = []
    for kv in (args.source_arg or []):
        head, sep, rest = kv.partition(":")
        resolved = _POLICY_ALIASES.get(head, head)
        if sep and "=" not in head and resolved in CALIBRATION_SOURCES:
            raw_by_policy.setdefault(resolved, []).append(rest)
        else:
            unscoped.append(kv)

    default_policy = "acn_data"
    if pops:
        try:
            with pops_path.open() as fh:
                _pops_doc = _yaml.safe_load(fh) or {}
            _entry = _pops_doc.get(pops)
            if isinstance(_entry, dict):
                _pol = _entry.get("calibration_policy")
                if _pol in CALIBRATION_SOURCES:
                    default_policy = _pol
        except OSError:
            pass
    if unscoped:
        raw_by_policy.setdefault(default_policy, []).extend(unscoped)

    source_configs: dict[str, dict] = {}
    for policy, raw_list in raw_by_policy.items():
        cfg = CALIBRATION_SOURCES[policy]().parse_args(raw_list)
        if policy == "acn_data":
            merged = {
                "sites": sites,
                "year_start": args.year_start,
                "year_end": args.year_end,
                "cache_dir": Path(args.cache_dir),
            }
            merged.update(cfg)
            source_configs["acn_data"] = merged
        else:
            cfg.setdefault("cache_dir", Path(args.cache_dir))
            source_configs[policy] = cfg

    summary = calibrate_populations(
        populations_yaml_path=pops_path,
        population_names=population_names,
        sites=sites,
        year_start=args.year_start,
        year_end=args.year_end,
        cache_dir=Path(args.cache_dir),
        artifact_dir=Path(args.artifact_dir),
        source_configs=source_configs or None,
    )
    print(f"calibration complete: {summary['provenance']}")
    print(f"  n_users={summary['n_users_total']}  n_sessions={summary['n_sessions_total']}")
    print(f"  capacity_inference_fallback_rate={summary['capacity_inference_fallback_rate']:.3f}")
    for pop_name, pop_summary in summary["populations"].items():
        regions = pop_summary.get("regions", [])
        print(f"  {pop_name}: {len(regions)} regions fit "
              f"unassigned_rate={pop_summary['unassigned_user_rate']:.3f}")
    for skipped in summary.get("skipped_populations", []):
        print(f"  skipped: {skipped}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from .batch import run_batch
    extra: dict[str, object] = {}
    for s in (args.override or []):
        if "=" not in s:
            raise SystemExit(f"invalid --override (need key=value): {s}")
        k, v = s.split("=", 1)
        extra[k.strip()] = parse_overrides([s])[k.strip()]
    if args.axes_alpha is not None:
        extra["user_behavior.axes_distribution_dirichlet_alpha"] = args.axes_alpha
    if args.battery_alpha is not None:
        extra["ev_fleet.battery_mix_dirichlet_alpha"] = args.battery_alpha

    def _print_progress(res, m):
        n_done = m["n_succeeded"] + m["n_failed"]
        print(f"  [{n_done}/{m['n_total']}] {res.month}/{res.sample_idx} seed={res.seed} "
              f"{res.status} ({res.duration_sec:.1f}s)", file=sys.stderr)

    print(f"Batch: {args.scenario} — {args.start_month} → {args.end_month}, "
          f"{args.samples_per_month}/month, {args.workers} workers", file=sys.stderr)
    try:
        manifest = run_batch(
            scenario_id=args.scenario,
            output_dir=Path(args.output_dir),
            config_dir=Path(args.config_dir),
            start_month=args.start_month,
            end_month=args.end_month,
            samples_per_month=args.samples_per_month,
            workers=args.workers,
            seed_base=args.seed_base,
            noise_profile=args.noise_profile,
            extra_overrides=extra,
            force=args.force,
            progress_callback=_print_progress,
        )
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"Batch {manifest['batch_id']} {manifest['status']}: "
          f"{manifest['n_succeeded']}/{manifest['n_total']} succeeded "
          f"({manifest['n_failed']} failed)", file=sys.stderr)
    return 0 if manifest["status"] in ("succeeded", "partial") else 2


def cmd_docs_gen(args: argparse.Namespace) -> int:
    """Emit the auto-generated section of docs/KNOB_REFERENCE.md to stdout."""
    from .knob_loader import (
        DEEP_OVERRIDE_PREFIXES,
        DIST_PARAM_RANGES,
        all_knob_paths,
        load_knob_registry,
    )

    out: list[str] = []
    out.append("# KNOB_REFERENCE — auto-generated\n")
    out.append("> Generated by `v2b-syndata docs-gen`. Do not edit by hand;\n"
               "> the hand-written usage guide section follows the auto block.\n")
    out.append("## Override path syntax\n")
    out.append("Two channels:\n")
    out.append("- **Registry channel**: `bucket.knob` paths declared in `configs/knobs.yaml`.\n")
    out.append("- **Deep channel**: paths under one of the prefixes below; values flow into\n"
               "  the population's `region_distributions` overlay block at resolve time.\n")

    out.append("## Source categories\n")
    out.append("Each resolved knob carries one of:\n")
    out.append("- `explicit` — set via `--override` or scenario YAML.\n")
    out.append("- `descriptor:<name>` — supplied by a Tier-0 descriptor expansion.\n")
    out.append("- `calibration:<provenance>` — supplied by an ACN-Data calibration run\n"
               "  (e.g. `calibration:acn_data_2019_2021_20260506`).\n")
    out.append("- `default` — fell through all chains; used `knobs.yaml::default`.\n")

    out.append("## Deep-channel parameter ranges\n")
    for prefix, ranges in DEEP_OVERRIDE_PREFIXES.items():
        out.append(f"\n### `{prefix}.<region>.<dist>.<param>`\n")
        out.append("| leaf (`<dist>.<param>`) | range |\n")
        out.append("|---|---|\n")
        for leaf, (lo, hi) in ranges.items():
            out.append(f"| `{leaf}` | `[{lo}, {hi}]` |\n")

    reg = load_knob_registry(Path(args.config_dir) / "knobs.yaml")
    out.append("\n## Registry knobs\n")
    out.append("| path | type | default | range / choices |\n")
    out.append("|---|---|---|---|\n")
    for path in all_knob_paths(reg):
        spec = reg[path]
        typ = spec.get("type", "?")
        default = spec.get("default")
        rng = spec.get("range") or spec.get("choices") or ""
        out.append(f"| `{path}` | `{typ}` | `{default!r}` | `{rng}` |\n")

    print("".join(out))
    _ = DIST_PARAM_RANGES  # silence unused-import warning when ruff strict
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="v2b_syndata", description="V2B synthetic dataset generator")
    p.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR),
                   help=f"directory containing knobs.yaml + descriptor libraries (default: {DEFAULT_CONFIG_DIR})")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate one scenario seed")
    g.add_argument("--scenario", required=True)
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--output-dir", required=True)
    g.add_argument("--override", action="append", default=[],
                   help="knob override 'bucket.knob=value' (repeatable). YAML-parsed.")
    g.add_argument("--noise-profile", default=None,
                   help="override scenario's noise descriptor")
    g.add_argument("--strict-e5", action="store_true",
                   help="Treat E5 infeasibility as an error (rc=2) rather than warning.")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("validate", help="validate an output directory")
    v.add_argument("output_dir")
    v.add_argument("--strict", action="store_true",
                   help="treat soft warnings as hard errors")
    v.set_defaults(func=cmd_validate)

    lk = sub.add_parser("list-knobs")
    lk.set_defaults(func=cmd_list_knobs)

    ls = sub.add_parser("list-scenarios")
    ls.set_defaults(func=cmd_list_scenarios)

    cal = sub.add_parser(
        "calibrate",
        help="fit per-region distributions from a calibration source "
             "(ACN-Data / EV WATTS / INL EV Project Phase 1 / ElaadNL "
             "Open Charging Transactions)",
    )
    cal.add_argument("--population", default=None,
                     help="single population name to calibrate (default: all populations)")
    cal.add_argument("--year-start", type=int, default=2019,
                     help="DEPRECATED: use --source-arg year_start=...")
    cal.add_argument("--year-end", type=int, default=2021,
                     help="DEPRECATED: use --source-arg year_end=...")
    cal.add_argument("--site", action="append", default=None,
                     help="DEPRECATED: use --source-arg site=... (repeatable)")
    cal.add_argument("--source-arg", action="append", default=None,
                     help="per-source [policy:]key=value (repeatable). Unprefixed "
                          "args route to the targeted population's policy. "
                          "Examples: site=caltech, evwatts:release_tag=fixture, "
                          "evwatts:venue_filter=workplace_public.")
    cal.add_argument("--cache-dir", default=str(REPO_ROOT / "data" / "calibration" / "acn_cache"))
    cal.add_argument("--artifact-dir", default=str(REPO_ROOT / "data" / "calibration"))
    cal.set_defaults(func=cmd_calibrate)

    b = sub.add_parser("batch", help="generate (months × samples_per_month) into a tree")
    b.add_argument("--scenario", required=True)
    b.add_argument("--output-dir", required=True)
    b.add_argument("--start-month", required=True, help="YYYY-MM (inclusive)")
    b.add_argument("--end-month", required=True, help="YYYY-MM (inclusive)")
    b.add_argument("--samples-per-month", type=int, required=True)
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--seed-base", type=int, default=0)
    b.add_argument("--noise-profile", default="tmyx_stochastic",
                   help="default tmyx_stochastic; pass clean for deterministic batch")
    b.add_argument("--axes-alpha", type=float, default=None,
                   help="user_behavior.axes_distribution_dirichlet_alpha (default 30 in batch)")
    b.add_argument("--battery-alpha", type=float, default=None,
                   help="ev_fleet.battery_mix_dirichlet_alpha (default 30 in batch)")
    b.add_argument("--override", action="append", default=[],
                   help="extra knob override 'path=value' (repeatable)")
    b.add_argument("--force", action="store_true",
                   help="overwrite output_dir if it exists")
    b.set_defaults(func=cmd_batch)

    dg = sub.add_parser("docs-gen", help="emit auto-generated section of docs/KNOB_REFERENCE.md")
    dg.set_defaults(func=cmd_docs_gen)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
