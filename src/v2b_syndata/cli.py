"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .knob_loader import all_knob_paths, load_knob_registry, parse_overrides
from .runner import generate
from .validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "configs"


def cmd_generate(args: argparse.Namespace) -> int:
    cli_overrides = parse_overrides(args.override or [])
    manifest = generate(
        scenario_id=args.scenario,
        seed=args.seed,
        output_dir=Path(args.output_dir),
        config_dir=Path(args.config_dir),
        cli_overrides=cli_overrides,
        noise_profile_override=args.noise_profile,
    )
    print(f"generated {manifest['scenario_id']} seed={manifest['seed']} -> {args.output_dir}")
    # Auto-validate only on a clean noise profile — perturbed outputs may
    # legitimately violate hard invariants (this is the point of the
    # adversarial profile). Use `validate <dir>` for explicit checks.
    if manifest.get("noise_profile") == "clean":
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

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
