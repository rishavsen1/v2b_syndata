"""Knob audit harness — Stage 1 (existence + isolation) and Stage 2 (direction + magnitude).

Stage 1 verifies each knob/deep-param actually affects the declared output CSVs.
Stage 2 sweeps and tests directional response.

Run:
    python tools/knob_audit.py --stage 1
    python tools/knob_audit.py --stage 2          # only after S1 triage
    python tools/knob_audit.py --stage 1 --jobs 4 # parallel probes

Outputs:
    /tmp/knob_audit/audit_metadata.json
    docs/KNOB_AUDIT_S1.md  (or docs/KNOB_AUDIT_S2.md)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

CSV_FILES = [
    "building_load.csv", "cars.csv", "users.csv", "chargers.csv",
    "sessions.csv", "grid_prices.csv", "dr_events.csv",
]
DEFAULT_SCENARIO = "S01"
DEFAULT_SEED = 42

# Knobs that have no observable effect under S01 (dr_program=none).
# Re-probe these under S_dr_cbp instead.
DR_DEPENDENT_KNOBS = {
    "utility_rate.dr_magnitude_kw_range",
    "utility_rate.dr_lambda_base",
    "utility_rate.dr_program",
    "noise.dr_notification_dropout_prob",
    "noise.profile",  # dr-jitter / price-jitter only present in adversarial
    "sim_window.mode",  # needs DR-enabled baseline to exercise dr_events.csv leg
}

# Multi-seed probe paths — DR-event dropout is probabilistic; single-seed probe
# can miss legitimate effect. Union changed-CSVs across this many seeds.
MULTI_SEED_PATHS = {
    "noise.profile": 10,
}

# Baseline scenario for descriptor swap probes — high-capacity scenario so
# stable_commuter_heavy / consent_calibration_site / high_power_dcfc don't
# trip E5 against S01's default 20-charger headroom.
DESCRIPTOR_BASELINE = "S_audit_baseline"

# Population-sparse regions whose deep-channel leaves need a bigger fleet to
# accumulate enough sessions for std/correlation metrics. S01's consent_default
# weights occasional_visitor at 0.10 → 2 EVs at 20-EV default → 1 user typical.
# S_audit_baseline overrides ev_count=50 → ~5 users in that region.
SPARSE_REGION_BASELINE = {
    "occasional_visitor": "S_audit_baseline",
}

# Categorical knobs whose alternates are environmentally heavy (e.g. building
# rerun); we test only one alternate to keep S1 budget low.
SLOW_CATEGORICAL_SINGLE_PROBE = {
    "building_load.archetype",
    "building_load.size",
    "building_load.occupancy_source",
    "building_load.tmyx_station",
    "sim_window.mode",
}


# ──────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class KnobSpec:
    path: str
    knob_type: str
    range_or_choices: Any
    default: Any
    affects_csv: list[str]
    is_deep_channel: bool = False
    is_descriptor: bool = False
    descriptor_kind: str | None = None   # "location" | "building" | ...
    untestable_reason: str | None = None
    baseline_scenario: str = DEFAULT_SCENARIO


@dataclass
class ProbeResult:
    knob_path: str
    probe_label: str          # "low" or "high" or "alt"
    probe_value: Any
    scenario: str
    success: bool
    error: str | None
    changed_csvs: list[str]
    elapsed_s: float


@dataclass
class KnobVerdict:
    knob_path: str
    knob_type: str
    is_deep_channel: bool
    is_descriptor: bool
    descriptor_kind: str | None
    declared_affects: list[str]
    observed_changes: list[str]   # union across probes
    probes: list[ProbeResult]
    verdict: str
    note: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Enumeration
# ──────────────────────────────────────────────────────────────────────────


def parse_knobs_yaml(yaml_path: Path) -> list[KnobSpec]:
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    out: list[KnobSpec] = []
    for bucket, knobs in raw.items():
        for name, spec in knobs.items():
            path = f"{bucket}.{name}"
            affects = spec.get("affects_csv") or []
            base = DEFAULT_SCENARIO
            if path in DR_DEPENDENT_KNOBS:
                base = "S_dr_cbp"
            out.append(KnobSpec(
                path=path,
                knob_type=spec.get("type", "?"),
                range_or_choices=spec.get("range") or spec.get("choices") or spec.get("components"),
                default=spec.get("default"),
                affects_csv=list(affects),
                baseline_scenario=base,
            ))
    return out


def parse_deep_channel(populations_yaml: Path, region_source: str = "consent_default") -> list[KnobSpec]:
    """Enumerate deep-channel params from one calibrated population.

    Stage 1 tests these against S01 (which uses `consent_default`). Cross-population
    leaves are out of S1 scope — they'd require swapping the population descriptor.

    Deep params overlay session-distribution leaves per region; they affect
    sessions.csv only (NOT users.csv — user-level region label is fixed per car).
    """
    from v2b_syndata.knob_loader import DIST_PARAM_RANGES

    with populations_yaml.open() as f:
        pops = yaml.safe_load(f)
    pop = pops.get(region_source, {})
    rd = pop.get("region_distributions", {})
    out: list[KnobSpec] = []
    for region, dists in rd.items():
        for leaf, (lo, hi) in DIST_PARAM_RANGES.items():
            path = f"user_behavior.region_distributions.{region}.{leaf}"
            out.append(KnobSpec(
                path=path,
                knob_type="float",
                range_or_choices=[lo, hi],
                default=None,
                affects_csv=["sessions.csv"],
                is_deep_channel=True,
            ))
    return out


def parse_descriptors(config_dir: Path, base_scenario: str = DESCRIPTOR_BASELINE) -> list[KnobSpec]:
    """Each non-default descriptor library entry becomes a descriptor-swap probe.

    Skip the descriptor that matches the base scenario's current value (would be
    a no-op swap). Descriptors have no precise per-CSV declaration — treat as
    NO-DECLARATION at verdict time (record what changed).
    """
    sc_path = config_dir / "scenarios" / f"{base_scenario}.yaml"
    with sc_path.open() as f:
        sc = yaml.safe_load(f)
    current_descriptors = sc.get("descriptors", {})

    out: list[KnobSpec] = []
    for kind, fname in [
        ("location", "locations.yaml"),
        ("building", "buildings.yaml"),
        ("population", "populations.yaml"),
        ("equipment", "equipment.yaml"),
        ("noise", "noise_profiles.yaml"),
    ]:
        with (config_dir / fname).open() as f:
            entries = yaml.safe_load(f) or {}
        for name in entries:
            if current_descriptors.get(kind) == name:
                continue  # would be a no-op swap
            out.append(KnobSpec(
                path=f"descriptor.{kind}={name}",
                knob_type="descriptor",
                range_or_choices=list(entries.keys()),
                default=None,
                affects_csv=[],  # no formal declaration; verdict via NO-DECLARATION path
                is_descriptor=True,
                descriptor_kind=kind,
                baseline_scenario=base_scenario,
            ))
    return out


# ──────────────────────────────────────────────────────────────────────────
# Probe selection
# ──────────────────────────────────────────────────────────────────────────


def select_probes(spec: KnobSpec) -> list[tuple[str, Any]] | None:
    """Return list of (label, value) probes. None ⇒ untestable."""
    t = spec.knob_type
    path = spec.path

    if t == "int":
        rng = spec.range_or_choices
        if not rng:
            return None
        lo, hi = rng
        if hi - lo < 2:
            return [("alt", hi if spec.default == lo else lo)]
        low = int(lo + 0.1 * (hi - lo))
        high = int(hi - 0.1 * (hi - lo))
        if low == spec.default:
            low = max(lo, low + 1)
        if high == spec.default:
            high = min(hi, high - 1)
        if low == high:
            return [("alt", low)]
        return [("low", low), ("high", high)]

    if t == "float":
        rng = spec.range_or_choices
        if not rng:
            return None
        lo, hi = rng
        low = lo + 0.1 * (hi - lo)
        high = hi - 0.1 * (hi - lo)
        return [("low", round(low, 4)), ("high", round(high, 4))]

    if t == "bool":
        return [("alt", not bool(spec.default))]

    if t == "categorical":
        choices = [c for c in (spec.range_or_choices or []) if c != spec.default]
        if not choices:
            return None
        # noise.profile: only `adversarial` has all six jitters non-zero, so it is
        # the only probe that can exercise every declared affects_csv.
        if path == "noise.profile":
            return [("alt", "adversarial")]
        if path in SLOW_CATEGORICAL_SINGLE_PROBE or len(choices) == 1:
            return [("alt", choices[0])]
        return [("low", choices[0]), ("high", choices[-1])]

    if t == "vec2":
        if path == "utility_rate.peak_window":
            return [("low", [5, 21]), ("high", [7, 23])]
        if path == "utility_rate.dr_magnitude_kw_range":
            return [("low", [40, 100]), ("high", [200, 500])]
        if path == "user_behavior.w_multiplier":
            return [("low", [0.5, 0.5]), ("high", [2.0, 2.0])]
        return None

    if t == "simplex":
        if path == "ev_fleet.battery_mix":
            return [("low", [0.10, 0.20, 0.50, 0.20]),
                    ("high", [0.40, 0.30, 0.20, 0.10])]
        if path == "user_behavior.negotiation_mix":
            return [("alt", [0.25, 0.25, 0.25, 0.25])]
        return None

    if t == "list[vec2]":
        return None

    if t == "list[region]":
        if path == "user_behavior.axes_distribution":
            # Probe: reshuffle weights but keep region structure.
            default = spec.default or []
            if not default:
                return None
            alt = [dict(r) for r in default]
            n = len(alt)
            # Inversely-weighted alt: heaviest region gets least weight
            w_orig = sorted([r["weight"] for r in alt], reverse=True)
            for i, r in enumerate(alt):
                r["weight"] = w_orig[(i + n // 2) % n]
            total = sum(r["weight"] for r in alt)
            for r in alt:
                r["weight"] /= total
            return [("alt", alt)]
        return None

    if t == "timestamp":
        if spec.default is None:
            return None
        return None

    if t == "path":
        if path == "building_load.tmyx_station":
            return [("alt", "USA_CA_San.Jose-Mineta.Intl.AP.724945_TMYx")]
        return None

    if t == "descriptor":
        return [("alt", path.split("=", 1)[1])]

    return None


# ──────────────────────────────────────────────────────────────────────────
# Probe execution
# ──────────────────────────────────────────────────────────────────────────


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def hash_outputs(out_dir: Path) -> dict[str, str]:
    return {f: sha16(out_dir / f) for f in CSV_FILES if (out_dir / f).exists()}


def diff_hashes(base: dict[str, str], probe: dict[str, str]) -> list[str]:
    changed = []
    for f in CSV_FILES:
        if base.get(f) != probe.get(f):
            changed.append(f)
    return changed


def _audit_config_dir(temp_base: Path) -> Path:
    """Create / reuse a temp configs/ copy where we can inject scenario YAMLs."""
    audit_cfg = temp_base / "configs"
    if not audit_cfg.exists():
        shutil.copytree(REPO / "configs", audit_cfg)
    return audit_cfg


def run_scenario(
    scenario: str,
    overrides: dict[str, Any],
    out_dir: Path,
    config_dir: Path,
    seed: int = DEFAULT_SEED,
) -> tuple[bool, str | None]:
    """Invoke runner.generate via subprocess so failures isolate cleanly."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "v2b_syndata.cli",
        "--config-dir", str(config_dir),
        "generate",
        "--scenario", scenario,
        "--seed", str(seed),
        "--output-dir", str(out_dir),
    ]
    for k, v in overrides.items():
        s = yaml.safe_dump(v, default_flow_style=True, width=10**9).strip()
        if s.endswith("..."):
            s = s.rsplit("\n", 1)[0].strip()
        # Sanity: no newlines should remain
        s = s.replace("\n", " ")
        cmd.extend(["--override", f"{k}={s}"])
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if proc.returncode != 0:
        # Truncate stderr to last few lines
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        return False, tail
    return True, None


def make_descriptor_scenario(
    config_dir: Path, base_scenario: str, kind: str, name: str
) -> str:
    """Write a sibling scenario file in `config_dir/scenarios/` with one descriptor swapped."""
    src = config_dir / "scenarios" / f"{base_scenario}.yaml"
    with src.open() as f:
        sc = yaml.safe_load(f)
    new_id = f"_audit_{kind}_{name}"
    sc["scenario_id"] = new_id
    sc["descriptors"] = dict(sc["descriptors"])
    sc["descriptors"][kind] = name
    sc.pop("description", None)
    sc["description"] = f"AUDIT descriptor swap {kind}={name}"
    out = config_dir / "scenarios" / f"{new_id}.yaml"
    with out.open("w") as f:
        yaml.safe_dump(sc, f, sort_keys=False)
    return new_id


# ──────────────────────────────────────────────────────────────────────────
# Verdict logic
# ──────────────────────────────────────────────────────────────────────────


def classify(spec: KnobSpec, probes: list[ProbeResult]) -> tuple[str, str]:
    """Return (verdict, note)."""
    if not probes:
        return "UNTESTABLE", spec.untestable_reason or "no probes selected"

    all_rejected = all(not p.success for p in probes)
    if all_rejected:
        msg = (probes[0].error or "?")[:300]
        # Distinguish post-generation E* validation failures (output produced
        # but failed sanity check) from override rejection at parse time.
        if "VALIDATION FAILED" in msg or "E5" in msg or "D" in msg[:10]:
            return "SCENARIO-INCOMPAT", msg
        return "OVERRIDE-REJECTED", msg

    # Union of CSV changes across successful probes
    union = set()
    for p in probes:
        if p.success:
            union.update(p.changed_csvs)

    declared = set(spec.affects_csv)

    if not declared:
        # NO-DECLARATION: success means override accepted
        any_success = any(p.success for p in probes)
        if any_success:
            return "NO-DECLARATION", f"override accepted; observed change: {sorted(union)}"
        return "OVERRIDE-REJECTED", probes[0].error or "?"

    missing = declared - union
    extra = union - declared

    if not missing and not extra:
        return "HONORED", ""
    if missing and not extra:
        return "UNDER-COUPLED", f"declared {sorted(declared)} but {sorted(missing)} unchanged"
    if not missing and extra:
        return "OVER-COUPLED", f"also changed: {sorted(extra)}"
    return "OVER-COUPLED", f"missing {sorted(missing)}, extra {sorted(extra)}"


# ──────────────────────────────────────────────────────────────────────────
# Stage 1 driver
# ──────────────────────────────────────────────────────────────────────────


def stage1(args: argparse.Namespace) -> int:
    audit_root = Path(args.audit_dir)
    audit_root.mkdir(parents=True, exist_ok=True)

    print(f"[audit] using audit_root={audit_root}")
    audit_cfg = _audit_config_dir(audit_root)
    print(f"[audit] audit configs at {audit_cfg}")

    # Cleanup any stale _audit_* scenarios from previous runs
    for f in (audit_cfg / "scenarios").glob("_audit_*.yaml"):
        f.unlink()

    # Enumerate
    knobs_specs = parse_knobs_yaml(audit_cfg / "knobs.yaml")
    deep_specs = parse_deep_channel(audit_cfg / "populations.yaml")
    desc_specs = parse_descriptors(audit_cfg)
    all_specs = knobs_specs + deep_specs + desc_specs
    print(f"[audit] {len(knobs_specs)} registry + {len(deep_specs)} deep + {len(desc_specs)} descriptor = {len(all_specs)} total")

    # Baselines per scenario
    baselines: dict[str, dict[str, str]] = {}
    needed_baselines = (
        {s.baseline_scenario for s in knobs_specs}
        | {s.baseline_scenario for s in desc_specs}
        | {DEFAULT_SCENARIO}
    )
    for scen in needed_baselines:
        out = audit_root / f"baseline_{scen}"
        if out.exists():
            shutil.rmtree(out)
        ok, err = run_scenario(scen, {}, out, audit_cfg)
        if not ok:
            print(f"[audit] FATAL: baseline {scen} failed: {err}")
            return 1
        baselines[scen] = hash_outputs(out)
        print(f"[audit] baseline {scen} done: {len(baselines[scen])} CSVs")

    # Probe each
    verdicts: list[KnobVerdict] = []
    t_start = time.time()
    for i, spec in enumerate(all_specs):
        t0 = time.time()
        probe_values = select_probes(spec)
        if probe_values is None:
            verdicts.append(KnobVerdict(
                knob_path=spec.path,
                knob_type=spec.knob_type,
                is_deep_channel=spec.is_deep_channel,
                is_descriptor=spec.is_descriptor,
                descriptor_kind=spec.descriptor_kind,
                declared_affects=spec.affects_csv,
                observed_changes=[],
                probes=[],
                verdict="UNTESTABLE",
                note=f"no probe selector for type={spec.knob_type}",
            ))
            print(f"[{i+1}/{len(all_specs)}] {spec.path}: UNTESTABLE")
            continue

        probes: list[ProbeResult] = []
        for label, value in probe_values:
            t_probe = time.time()
            probe_dir = audit_root / f"probe_{i}_{label}"
            if probe_dir.exists():
                shutil.rmtree(probe_dir)
            if spec.is_descriptor:
                scen_id = make_descriptor_scenario(
                    audit_cfg, spec.baseline_scenario, spec.descriptor_kind, value
                )
                ok, err = run_scenario(scen_id, {}, probe_dir, audit_cfg, seed=DEFAULT_SEED)
                scen_used = scen_id
                base_key = spec.baseline_scenario
            else:
                ok, err = run_scenario(
                    spec.baseline_scenario, {spec.path: value}, probe_dir, audit_cfg, seed=DEFAULT_SEED
                )
                scen_used = spec.baseline_scenario
                base_key = spec.baseline_scenario
            elapsed = time.time() - t_probe
            if ok:
                probe_hash = hash_outputs(probe_dir)
                base_for_scen = baselines[base_key]
                changed = set(diff_hashes(base_for_scen, probe_hash))
            else:
                changed = set()
            # Free disk before next probe
            if probe_dir.exists():
                shutil.rmtree(probe_dir)
            # Multi-seed union for probabilistic-effect knobs.
            extra_seeds = MULTI_SEED_PATHS.get(spec.path, 1) - 1
            for s_idx in range(extra_seeds):
                seed_alt = DEFAULT_SEED + 1 + s_idx
                probe_dir2 = audit_root / f"probe_{i}_{label}_s{seed_alt}"
                if probe_dir2.exists():
                    shutil.rmtree(probe_dir2)
                # Multi-seed baseline (different seed → different baseline hash too)
                # Use a per-seed baseline; reuse if cached.
                base_seed_dir = audit_root / f"baseline_{base_key}_s{seed_alt}"
                if not base_seed_dir.exists():
                    run_scenario(base_key, {}, base_seed_dir, audit_cfg, seed=seed_alt)
                base_seed_hash = hash_outputs(base_seed_dir)
                if spec.is_descriptor:
                    ok2, _ = run_scenario(scen_id, {}, probe_dir2, audit_cfg, seed=seed_alt)
                else:
                    ok2, _ = run_scenario(spec.baseline_scenario, {spec.path: value},
                                          probe_dir2, audit_cfg, seed=seed_alt)
                if ok2:
                    changed |= set(diff_hashes(base_seed_hash, hash_outputs(probe_dir2)))
                if probe_dir2.exists():
                    shutil.rmtree(probe_dir2)
            probes.append(ProbeResult(
                knob_path=spec.path, probe_label=label, probe_value=value,
                scenario=scen_used, success=ok, error=err,
                changed_csvs=sorted(changed), elapsed_s=elapsed,
            ))

        verdict, note = classify(spec, probes)
        union_changes = sorted({c for p in probes for c in p.changed_csvs})
        verdicts.append(KnobVerdict(
            knob_path=spec.path,
            knob_type=spec.knob_type,
            is_deep_channel=spec.is_deep_channel,
            is_descriptor=spec.is_descriptor,
            descriptor_kind=spec.descriptor_kind,
            declared_affects=spec.affects_csv,
            observed_changes=union_changes,
            probes=probes,
            verdict=verdict,
            note=note,
        ))
        dt = time.time() - t0
        print(f"[{i+1}/{len(all_specs)}] {spec.path}: {verdict} ({dt:.1f}s) {note[:80]}")

    # Cleanup audit scenarios
    for f in (audit_cfg / "scenarios").glob("_audit_*.yaml"):
        f.unlink()
    # Cleanup baselines
    for d in audit_root.glob("baseline_*"):
        if d.is_dir():
            shutil.rmtree(d)

    total_elapsed = time.time() - t_start
    print(f"\n[audit] total elapsed: {total_elapsed:.1f}s")

    # Persist metadata
    meta = {
        "stage": 1,
        "git_sha": _git_sha(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": total_elapsed,
        "verdicts": [_verdict_to_dict(v) for v in verdicts],
    }
    meta_path = audit_root / "audit_metadata.json"
    with meta_path.open("w") as f:
        json.dump(meta, f, indent=2)
    print(f"[audit] metadata → {meta_path}")

    # Emit report
    report_path = REPO / "docs" / "KNOB_AUDIT_S1.md"
    emit_stage1_report(verdicts, report_path, total_elapsed)
    print(f"[audit] report → {report_path}")
    return 0


def _verdict_to_dict(v: KnobVerdict) -> dict:
    d = asdict(v)
    return d


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True
        ).strip()
        return out
    except Exception:
        return "unknown"


def emit_stage1_report(verdicts: list[KnobVerdict], path: Path, elapsed: float) -> None:
    buckets: dict[str, list[KnobVerdict]] = {
        "HONORED": [], "OVER-COUPLED": [], "UNDER-COUPLED": [],
        "NO-DECLARATION": [], "UNTESTABLE": [], "OVERRIDE-REJECTED": [],
        "SCENARIO-INCOMPAT": [],
    }
    for v in verdicts:
        buckets.setdefault(v.verdict, []).append(v)

    lines = []
    lines.append("# Knob Audit Stage 1: Existence + Isolation\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    lines.append(f"Git SHA: `{_git_sha()}`\n")
    lines.append(f"Total elapsed: {elapsed:.1f}s\n")
    EMOJI = {
        "HONORED": "✅",
        "OVER-COUPLED": "⚠️",
        "UNDER-COUPLED": "❌",
        "NO-DECLARATION": "🟡",
        "UNTESTABLE": "⏭️",
        "OVERRIDE-REJECTED": "💥",
        "SCENARIO-INCOMPAT": "🚧",
    }
    lines.append("\n## Summary\n")
    lines.append("| Verdict | Count |\n|---|---|\n")
    for name in ["HONORED", "OVER-COUPLED", "UNDER-COUPLED", "NO-DECLARATION",
                 "UNTESTABLE", "OVERRIDE-REJECTED", "SCENARIO-INCOMPAT"]:
        lines.append(f"| {EMOJI[name]} {name} | {len(buckets.get(name, []))} |\n")
    lines.append(f"| **TOTAL** | **{len(verdicts)}** |\n")

    # Per bucket
    for name in ["HONORED", "OVER-COUPLED", "UNDER-COUPLED", "NO-DECLARATION",
                 "UNTESTABLE", "OVERRIDE-REJECTED", "SCENARIO-INCOMPAT"]:
        bucket = buckets.get(name, [])
        if not bucket:
            continue
        lines.append(f"\n### {EMOJI[name]} {name} ({len(bucket)} knobs)\n")
        lines.append("| knob | type | declared | observed | note |\n")
        lines.append("|---|---|---|---|---|\n")
        for v in bucket:
            kind = "descriptor" if v.is_descriptor else ("deep" if v.is_deep_channel else v.knob_type)
            decl = ", ".join(v.declared_affects) if v.declared_affects else "—"
            obs = ", ".join(v.observed_changes) if v.observed_changes else "—"
            note = v.note.replace("|", "/").replace("\n", " ")[:160]
            lines.append(f"| `{v.knob_path}` | {kind} | {decl} | {obs} | {note} |\n")

    # Per-knob diagnosis for findings the Stage 1 fix pass did not eliminate.
    # Add entries here as new issues surface; leave empty when all findings are
    # already resolved by knobs.yaml declarations or pipeline edits.
    UNDER_COUPLED_DIAGNOSIS: dict[str, str] = {}
    OVER_COUPLED_DIAGNOSIS: dict[str, str] = {}

    # Recommendations
    lines.append("\n## Recommendations\n")
    if buckets.get("UNDER-COUPLED"):
        lines.append("### HIGH: under-coupled knobs (declared CSV but did NOT differ)\n")
        for v in buckets["UNDER-COUPLED"]:
            diag = UNDER_COUPLED_DIAGNOSIS.get(v.knob_path, "—")
            lines.append(f"- `{v.knob_path}`: {v.note}\n")
            lines.append(f"  - **Diagnosis:** {diag}\n")
    if buckets.get("OVER-COUPLED"):
        lines.append("\n### MEDIUM: over-coupled knobs (extra side-effects)\n")
        for v in buckets["OVER-COUPLED"]:
            diag = OVER_COUPLED_DIAGNOSIS.get(v.knob_path, "—")
            lines.append(f"- `{v.knob_path}`: {v.note}\n")
            lines.append(f"  - **Diagnosis:** {diag}\n")
    if buckets.get("OVERRIDE-REJECTED"):
        lines.append("\n### LOW: probe values rejected (may indicate range tightness)\n")
        for v in buckets["OVERRIDE-REJECTED"]:
            lines.append(f"- `{v.knob_path}`: {v.note}\n")
    if buckets.get("SCENARIO-INCOMPAT"):
        lines.append("\n### INFO: descriptor swaps that broke S01's count invariants\n")
        lines.append("These descriptors are reachable via their own scenarios but conflict "
                     "with S01's `charger_count=20`. Not knob bugs — descriptor/scenario "
                     "matching issue. Test with a sized-up baseline if needed.\n\n")
        for v in buckets["SCENARIO-INCOMPAT"]:
            lines.append(f"- `{v.knob_path}`: {v.note}\n")

    # Stage 2 admission list
    admitted = [v.knob_path for v in verdicts if v.verdict in ("HONORED", "OVER-COUPLED")]
    lines.append(f"\n## Stage 2 admission list ({len(admitted)} knobs)\n\n")
    for p in admitted:
        lines.append(f"- `{p}`\n")

    with path.open("w") as f:
        f.write("".join(lines))


# ──────────────────────────────────────────────────────────────────────────
# Stage 2: direction + magnitude verification
# ──────────────────────────────────────────────────────────────────────────


def _read_csv(path: Path) -> Any:
    import pandas as pd
    return pd.read_csv(path)


def _load_outputs(out_dir: Path) -> dict[str, Any]:
    dfs: dict[str, Any] = {}
    for f in CSV_FILES:
        p = out_dir / f
        if p.exists():
            dfs[f] = _read_csv(p)
    return dfs


# Per-CSV default metrics — chosen for monotonic response to most knobs.
def _m_building_flex(dfs):  return float(dfs["building_load.csv"]["power_flex_kw"].mean())
def _m_building_inflex(dfs):return float(dfs["building_load.csv"]["power_inflex_kw"].mean())
def _m_building_flex_var(dfs):return float(dfs["building_load.csv"]["power_flex_kw"].var())
def _m_building_inflex_var(dfs):return float(dfs["building_load.csv"]["power_inflex_kw"].var())
def _m_users_w1(dfs):    return float(dfs["users.csv"]["w1"].mean())
def _m_users_w2(dfs):    return float(dfs["users.csv"]["w2"].mean())
def _m_cars_count(dfs):     return float(len(dfs["cars.csv"]))
def _m_cars_capacity(dfs):  return float(dfs["cars.csv"]["capacity_kwh"].mean())
def _m_users_count(dfs):    return float(len(dfs["users.csv"]))
def _m_users_phi(dfs):      return float(dfs["users.csv"]["phi"].mean())
def _m_users_kappa(dfs):    return float(dfs["users.csv"]["kappa"].mean())
def _m_chargers_count(dfs): return float(len(dfs["chargers.csv"]))
def _m_chargers_bidir(dfs):
    df = dfs["chargers.csv"]
    return float((df["directionality"] == "bidirectional").mean()) if len(df) else 0.0
def _m_chargers_rate(dfs):  return float(dfs["chargers.csv"]["max_rate_kw"].mean())
def _m_sessions_count(dfs): return float(len(dfs["sessions.csv"]))
def _m_sessions_arr_hour(dfs):
    import pandas as pd
    s = pd.to_datetime(dfs["sessions.csv"]["arrival"]).dt
    return float((s.hour + s.minute / 60.0).mean())
def _m_sessions_duration_hr(dfs):
    return float((dfs["sessions.csv"]["duration_sec"] / 3600.0).mean())
def _m_sessions_arr_soc(dfs):  return float(dfs["sessions.csv"]["arrival_soc"].mean())
def _m_sessions_req_soc(dfs):  return float(dfs["sessions.csv"]["required_soc_at_depart"].mean())
def _m_sessions_req_soc_min(dfs):return float(dfs["sessions.csv"]["required_soc_at_depart"].min())
def _m_sessions_arr_var(dfs):
    import pandas as pd
    s = pd.to_datetime(dfs["sessions.csv"]["arrival"]).dt
    return float((s.hour + s.minute / 60.0).var())
def _m_sessions_soc_var(dfs):  return float(dfs["sessions.csv"]["arrival_soc"].var())
def _m_grid_mean(dfs):    return float(dfs["grid_prices.csv"]["price_per_kwh"].mean())
def _m_grid_var(dfs):     return float(dfs["grid_prices.csv"]["price_per_kwh"].var())
def _m_grid_peak_ratio(dfs):
    df = dfs["grid_prices.csv"]
    if "type" not in df: return float("nan")
    peak = df.loc[df["type"] == "peak", "price_per_kwh"].mean()
    off = df.loc[df["type"] == "offpeak", "price_per_kwh"].mean()
    if off == 0 or not off == off:  # nan check
        return float("nan")
    return float(peak / off) if off else float("nan")
def _m_dr_count(dfs):      return float(len(dfs.get("dr_events.csv", [])))
def _m_dr_magnitude(dfs):
    df = dfs.get("dr_events.csv")
    return float(df["magnitude_kw"].mean()) if df is not None and len(df) else 0.0
def _m_dr_lead_hr(dfs):
    import pandas as pd
    df = dfs.get("dr_events.csv")
    if df is None or len(df) == 0: return 0.0
    leads = (pd.to_datetime(df["start"]) - pd.to_datetime(df["notified_at"])).dt.total_seconds() / 3600
    return float(leads.mean())


# Deep-channel metric: filter sessions by user region first.
def _deep_metric(dist_name, param):
    """Return a metric fn (dfs, region) → float specific to the deep-channel leaf."""
    def fn(dfs, region):
        users = dfs["users.csv"]
        car_ids = set(users.loc[users["region"] == region, "car_id"].tolist())
        sess = dfs["sessions.csv"]
        sub = sess[sess["car_id"].isin(car_ids)]
        if len(sub) == 0:
            return float("nan")
        if dist_name == "arrival" and param == "mu":
            import pandas as pd
            s = pd.to_datetime(sub["arrival"]).dt
            return float((s.hour + s.minute / 60.0).mean())
        if dist_name == "arrival" and param == "sigma":
            import pandas as pd
            s = pd.to_datetime(sub["arrival"]).dt
            return float((s.hour + s.minute / 60.0).std())
        if dist_name == "dwell" and param == "lambda":
            return float((sub["duration_sec"] / 3600.0).mean())
        if dist_name == "dwell" and param == "k":
            return float((sub["duration_sec"] / 3600.0).std())
        if dist_name == "soc_arrival" and param == "alpha":
            return float(sub["arrival_soc"].mean())
        if dist_name == "soc_arrival" and param == "beta":
            return float(sub["arrival_soc"].mean())
        if dist_name == "copula" and param == "rho_gaussian":
            import pandas as pd
            s = pd.to_datetime(sub["arrival"]).dt
            arr_h = s.hour + s.minute / 60.0
            dur_h = sub["duration_sec"] / 3600.0
            if len(arr_h) < 3:
                return float("nan")
            return float(arr_h.corr(dur_h))
        return float("nan")
    return fn


# Expected direction per knob — "↑" higher knob = higher metric, "↓" inverse,
# "any" no direction claim (categorical / simplex / bool).
# Format: knob_path → list[(csv, metric_fn, expected_dir, label)]
# Metric fn signature: dfs → float
KNOB_METRIC_OVERRIDES: dict[str, list[tuple[str, Any, str, str]]] = {
    # Fleet
    "ev_fleet.ev_count": [
        ("cars.csv", _m_cars_count, "↑", "row_count"),
        ("users.csv", _m_users_count, "↑", "row_count"),
        ("sessions.csv", _m_sessions_count, "↑", "row_count"),
    ],
    "ev_fleet.battery_mix": [("cars.csv", _m_cars_capacity, "any", "capacity_mean")],
    "ev_fleet.battery_heterogeneity": [("cars.csv", _m_cars_capacity, "any", "capacity_mean")],
    # Infra
    "charging_infra.charger_count": [("chargers.csv", _m_chargers_count, "↑", "row_count")],
    "charging_infra.directionality_frac": [("chargers.csv", _m_chargers_bidir, "↑", "frac_bidir")],
    "charging_infra.uni_rate_kw": [("chargers.csv", _m_chargers_rate, "↑", "rate_mean")],
    "charging_infra.bi_rate_kw": [("chargers.csv", _m_chargers_rate, "↑", "rate_mean")],
    # User-behavior
    "user_behavior.min_depart_soc": [("sessions.csv", _m_sessions_req_soc_min, "↑", "req_soc_min")],
    "user_behavior.axes_distribution": [
        ("users.csv", _m_users_phi, "any", "phi_mean"),
        ("users.csv", _m_users_kappa, "any", "kappa_mean"),
    ],
    "user_behavior.negotiation_mix": [
        ("users.csv", _m_users_w1, "any", "w1_mean"),
        ("users.csv", _m_users_w2, "any", "w2_mean"),
    ],
    "user_behavior.w_multiplier": [
        ("users.csv", _m_users_w1, "↑", "w1_mean"),
        ("users.csv", _m_users_w2, "↑", "w2_mean"),
    ],
    # Building
    "building_load.tmyx_station": [
        ("building_load.csv", _m_building_flex, "any", "flex_mean"),
        ("building_load.csv", _m_building_inflex, "any", "inflex_mean"),
    ],
    "building_load.archetype": [("building_load.csv", _m_building_flex, "any", "flex_mean")],
    "building_load.size": [("building_load.csv", _m_building_flex, "any", "flex_mean")],
    "building_load.occupancy_source": [("building_load.csv", _m_building_flex, "any", "flex_mean")],
    "building_load.peak_kw": [("building_load.csv", _m_building_flex, "↑", "flex_mean")],
    # Tariff
    "utility_rate.tariff_type": [("grid_prices.csv", _m_grid_mean, "any", "price_mean")],
    "utility_rate.energy_price_offpeak": [("grid_prices.csv", _m_grid_mean, "↑", "price_mean")],
    "utility_rate.energy_price_peak": [("grid_prices.csv", _m_grid_mean, "↑", "price_mean")],
    "utility_rate.peak_window": [("grid_prices.csv", _m_grid_mean, "any", "price_mean")],
    "utility_rate.dr_program": [("dr_events.csv", _m_dr_lead_hr, "any", "lead_hr")],
    "utility_rate.dr_magnitude_kw_range": [("dr_events.csv", _m_dr_magnitude, "↑", "magnitude_mean")],
    "utility_rate.dr_lambda_base": [("dr_events.csv", _m_dr_count, "↑", "row_count")],
    # Sim window
    "sim_window.mode": [("sessions.csv", _m_sessions_count, "any", "row_count")],
    "sim_window.weekdays_only": [("sessions.csv", _m_sessions_count, "↓", "row_count")],
    # Noise — variance-based on jitter
    "noise.profile": [
        ("building_load.csv", _m_building_flex_var, "any", "flex_var"),
        ("sessions.csv", _m_sessions_arr_var, "any", "arr_var"),
    ],
    "noise.building_load_jitter_pct": [("building_load.csv", _m_building_flex_var, "↑", "flex_var")],
    "noise.arrival_time_jitter_min": [("sessions.csv", _m_sessions_arr_var, "↑", "arr_var")],
    "noise.soc_arrival_jitter_pct": [("sessions.csv", _m_sessions_soc_var, "↑", "soc_var")],
    "noise.dr_notification_dropout_prob": [("dr_events.csv", _m_dr_count, "↓", "row_count")],
    "noise.price_jitter_pct": [("grid_prices.csv", _m_grid_var, "↑", "price_var")],
    "noise.occupancy_jitter_pct": [("building_load.csv", _m_building_inflex_var, "↑", "inflex_var")],
}


# Probe selectors for Stage 2 (5 values).
def select_5_probes(spec: KnobSpec) -> list[tuple[str, Any]] | None:
    t = spec.knob_type
    path = spec.path

    if spec.is_deep_channel:
        from v2b_syndata.knob_loader import DIST_PARAM_RANGES
        leaf = ".".join(path.rsplit(".", 2)[-2:])
        lo, hi = DIST_PARAM_RANGES[leaf]
        # Weibull(k) collapses to a degenerate distribution near k=0 (most mass
        # at 0), so std/var metrics are unstable below k≈0.5. Floor the probe
        # range to keep monotonicity checks meaningful — k=0.01 in the registry
        # remains a valid override, but Stage 2 will not probe it.
        if leaf == "dwell.k":
            lo = max(lo, 0.5)
        vals = [lo + i * (hi - lo) / 4 for i in range(5)]
        return [(f"p{i+1}", round(v, 6)) for i, v in enumerate(vals)]

    if t == "int":
        lo, hi = spec.range_or_choices
        vals = sorted({max(lo, min(hi, round(lo + i * (hi - lo) / 4))) for i in range(5)})
        return [(f"p{i+1}", v) for i, v in enumerate(vals)]
    if t == "float":
        lo, hi = spec.range_or_choices
        vals = [lo + i * (hi - lo) / 4 for i in range(5)]
        return [(f"p{i+1}", round(v, 6)) for i, v in enumerate(vals)]
    if t == "bool":
        return [("p1", False), ("p2", True)]
    if t == "categorical":
        choices = list(spec.range_or_choices or [])
        if not choices: return None
        return [(c, c) for c in choices]
    if t == "vec2":
        if path == "utility_rate.peak_window":
            return [("p1", [6, 18]), ("p2", [7, 20]), ("p3", [8, 22]),
                    ("p4", [9, 23]), ("p5", [5, 15])]
        if path == "utility_rate.dr_magnitude_kw_range":
            return [("p1", [40, 60]), ("p2", [80, 120]), ("p3", [150, 200]),
                    ("p4", [200, 400]), ("p5", [300, 600])]
        if path == "user_behavior.w_multiplier":
            return [("p1", [0.2, 0.2]), ("p2", [0.5, 0.5]), ("p3", [1.0, 1.0]),
                    ("p4", [2.0, 2.0]), ("p5", [4.0, 4.0])]
        return None
    if t == "simplex":
        if path == "ev_fleet.battery_mix":
            return [("p1", [1.0, 0.0, 0.0, 0.0]), ("p2", [0.5, 0.5, 0.0, 0.0]),
                    ("p3", [0.25, 0.25, 0.25, 0.25]), ("p4", [0.0, 0.0, 0.5, 0.5]),
                    ("p5", [0.0, 0.0, 0.0, 1.0])]
        if path == "user_behavior.negotiation_mix":
            return [("p1", [1.0, 0.0, 0.0, 0.0]), ("p2", [0.0, 1.0, 0.0, 0.0]),
                    ("p3", [0.0, 0.0, 1.0, 0.0]), ("p4", [0.0, 0.0, 0.0, 1.0]),
                    ("p5", [0.25, 0.25, 0.25, 0.25])]
        return None
    if t == "path":
        if path == "building_load.tmyx_station":
            return [
                ("nashville", "USA_TN_Nashville.Intl.AP.723270_TMYx"),
                ("san_jose", "USA_CA_San.Jose-Mineta.Intl.AP.724945_TMYx"),
                ("miami", "USA_FL_Miami.Natl.Hurricane.Center.722020_TMYx"),
                ("minneapolis", "USA_MN_Minneapolis-St.Paul.Intl.AP.726580_TMYx"),
                ("houston", "USA_TX_Houston-Bush.Intercontinental.AP.722430_TMYx"),
            ]
        return None
    if t == "list[region]":
        if path == "user_behavior.axes_distribution":
            default = spec.default or []
            if not default: return None
            n = len(default)
            probes = []
            # 5 weight permutations: uniform, peak-at-i for each i (up to 5)
            uniform = [dict(r, weight=1.0 / n) for r in default]
            probes.append(("uniform", uniform))
            for i in range(min(4, n)):
                weights = [0.05] * n
                weights[i] = 1 - 0.05 * (n - 1)
                probes.append((f"peak_{default[i]['name']}",
                               [dict(r, weight=w) for r, w in zip(default, weights)]))
            while len(probes) < 5:
                probes.append(("uniform_dup", uniform))
            return probes[:5]
        return None

    return None


def classify_monotonic(metric_vals: list[float], expected: str) -> tuple[str, str]:
    """Return (verdict, note)."""
    import math
    if any(math.isnan(v) for v in metric_vals):
        # Drop NaNs; if too few valid points, NO-EFFECT
        valid = [v for v in metric_vals if not math.isnan(v)]
        if len(valid) < 2:
            return "NO-EFFECT", "insufficient valid metric points"
        metric_vals = valid

    rng = max(metric_vals) - min(metric_vals)
    base = max(abs(metric_vals[0]), 1e-12)

    if rng / base < 1e-6:
        return "NO-EFFECT", f"metric flat across probes (range/base={rng/base:.2e})"

    if expected == "any":
        # Categorical / simplex / bool: any variation is success
        return "MONOTONIC", f"responsive (range={rng:.4g})"

    diffs = [b - a for a, b in zip(metric_vals, metric_vals[1:])]
    all_up = all(d >= -1e-9 for d in diffs) and any(d > 1e-9 for d in diffs)
    all_down = all(d <= 1e-9 for d in diffs) and any(d < -1e-9 for d in diffs)

    if all_up:
        actual = "↑"
    elif all_down:
        actual = "↓"
    else:
        # Tolerate small sample-noise reversals: if dominant trend agrees with
        # expected direction and the largest counter-diff is <5% of the total
        # range, treat as MONOTONIC with a noise caveat. Catches population-
        # sparse-region deep-channel sweeps where 5–10 sessions cause small
        # flips on an otherwise-clean trend.
        pos = sum(d for d in diffs if d > 0)
        neg = sum(d for d in diffs if d < 0)
        dominant = "↑" if pos > -neg else "↓"
        counter = max((abs(d) for d in diffs if (d > 0 if dominant == "↓" else d < 0)),
                      default=0.0)
        if dominant == expected and rng > 0 and counter / rng < 0.05:
            return "MONOTONIC", (
                f"{dominant} dominant (counter-flip {counter/rng*100:.1f}% < 5% tolerance); "
                f"diffs={[round(d, 4) for d in diffs]}"
            )
        return "NON-MONOTONIC", f"diffs={[round(d, 4) for d in diffs]}"

    if actual != expected:
        return "WRONG-DIRECTION", f"expected {expected}, got {actual}"

    rng_pct = rng / base
    if rng_pct < 0.05:
        return "WEAK-EFFECT", f"range {rng_pct*100:.2f}% < 5% threshold"

    return "MONOTONIC", f"{actual} range={rng:.4g} ({rng_pct*100:.1f}%)"


@dataclass
class S2ProbeResult:
    knob_path: str
    csv: str
    metric_label: str
    probe_values: list[Any]
    metric_values: list[float]
    expected_dir: str
    verdict: str
    note: str


@dataclass
class S2KnobVerdict:
    knob_path: str
    csv_results: list[S2ProbeResult]
    overall_verdict: str
    note: str
    elapsed_s: float


_VERDICT_RANK = {
    "WRONG-DIRECTION": 0, "NO-EFFECT": 1, "NON-MONOTONIC": 2,
    "WEAK-EFFECT": 3, "MONOTONIC": 4,
}


def _aggregate(csv_results: list[S2ProbeResult]) -> tuple[str, str]:
    if not csv_results:
        return "NO-EFFECT", "no CSV metric"
    worst = min(csv_results, key=lambda r: _VERDICT_RANK.get(r.verdict, 99))
    if all(r.verdict == "MONOTONIC" for r in csv_results):
        return "MONOTONIC", ", ".join(f"{r.csv}/{r.metric_label}: {r.note}" for r in csv_results)
    return worst.verdict, f"{worst.csv}/{worst.metric_label}: {worst.note}"


def stage2(args: argparse.Namespace) -> int:
    audit_root = Path(args.audit_dir)
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_cfg = _audit_config_dir(audit_root)
    for f in (audit_cfg / "scenarios").glob("_audit_*.yaml"):
        f.unlink()

    # Load Stage 1 metadata for admission list.
    s1_meta_path = audit_root / "audit_metadata.json"
    if not s1_meta_path.exists():
        print(f"[s2] need {s1_meta_path} from a prior Stage 1 run")
        return 1
    with s1_meta_path.open() as f:
        s1 = json.load(f)
    admitted = [v["knob_path"] for v in s1["verdicts"]
                if v["verdict"] in ("HONORED", "OVER-COUPLED")]
    print(f"[s2] admitted: {len(admitted)} knobs")

    # Re-enumerate specs so we have type/range/baseline/affects metadata.
    knobs_specs = parse_knobs_yaml(audit_cfg / "knobs.yaml")
    deep_specs = parse_deep_channel(audit_cfg / "populations.yaml")
    spec_by_path = {s.path: s for s in knobs_specs + deep_specs}

    # Apply sparse-region baseline override (occasional_visitor.* → S_audit_baseline).
    for p in list(admitted):
        spec = spec_by_path.get(p)
        if spec is None or not spec.is_deep_channel:
            continue
        region = p.split(".")[-3]
        if region in SPARSE_REGION_BASELINE:
            spec.baseline_scenario = SPARSE_REGION_BASELINE[region]

    # Pre-compute baselines per scenario.
    baselines_dfs: dict[str, dict[str, Any]] = {}
    for scen in {spec_by_path[p].baseline_scenario for p in admitted if p in spec_by_path}:
        out = audit_root / f"s2_baseline_{scen}"
        if out.exists():
            shutil.rmtree(out)
        ok, err = run_scenario(scen, {}, out, audit_cfg)
        if not ok:
            print(f"[s2] FATAL: baseline {scen}: {err}")
            return 1
        baselines_dfs[scen] = _load_outputs(out)
        print(f"[s2] baseline {scen} loaded")

    verdicts: list[S2KnobVerdict] = []
    t_start = time.time()

    for i, path in enumerate(admitted):
        t0 = time.time()
        if path not in spec_by_path:
            verdicts.append(S2KnobVerdict(path, [], "NO-SPEC", "admitted but not in registry/deep", 0.0))
            continue
        spec = spec_by_path[path]
        probes = select_5_probes(spec)
        if probes is None:
            verdicts.append(S2KnobVerdict(path, [], "UNTESTABLE", f"no probe selector for {spec.knob_type}", 0.0))
            print(f"[{i+1}/{len(admitted)}] {path}: UNTESTABLE")
            continue

        # Determine which (csv, metric_fn, expected, label) tuples apply.
        if spec.is_deep_channel:
            region = path.split(".")[-3]
            leaf_parts = path.rsplit(".", 2)
            dist_name = leaf_parts[-2]
            param = leaf_parts[-1]
            expected = {
                ("arrival", "mu"): "↑",
                ("arrival", "sigma"): "↑",
                ("dwell", "lambda"): "↑",
                ("dwell", "k"): "↓",
                ("soc_arrival", "alpha"): "↑",
                ("soc_arrival", "beta"): "↓",
                ("copula", "rho_gaussian"): "↑",
            }.get((dist_name, param), "any")
            label = f"{region}/{dist_name}.{param}"
            csv_metrics = [("sessions.csv", _deep_metric(dist_name, param), expected, label, region)]
        else:
            csv_metrics = []
            override = KNOB_METRIC_OVERRIDES.get(path)
            if override:
                csv_metrics = [(c, fn, ex, lab, None) for (c, fn, ex, lab) in override]
            else:
                # Fall back: pick a generic metric per declared CSV.
                fallback = {
                    "cars.csv": (_m_cars_capacity, "any", "capacity_mean"),
                    "users.csv": (_m_users_phi, "any", "phi_mean"),
                    "chargers.csv": (_m_chargers_rate, "any", "rate_mean"),
                    "sessions.csv": (_m_sessions_count, "any", "row_count"),
                    "building_load.csv": (_m_building_flex, "any", "flex_mean"),
                    "grid_prices.csv": (_m_grid_mean, "any", "price_mean"),
                    "dr_events.csv": (_m_dr_count, "any", "row_count"),
                }
                for c in spec.affects_csv:
                    if c in fallback:
                        fn, ex, lab = fallback[c]
                        csv_metrics.append((c, fn, ex, lab, None))

        # Generate scenario once per (knob, probe), reuse dfs across CSV metrics.
        # Tolerate E5/E* validation failures: CSVs are still written before
        # auto-validate runs, so we can measure metrics even when invariants trip.
        per_probe_dfs: list[tuple[Any, dict[str, Any] | None]] = []
        for plabel, val in probes:
            probe_dir = audit_root / f"s2_probe_{i}_{plabel}"
            if probe_dir.exists():
                shutil.rmtree(probe_dir)
            ok, err = run_scenario(spec.baseline_scenario, {path: val}, probe_dir, audit_cfg)
            outputs_exist = (probe_dir / "sessions.csv").exists()
            if outputs_exist:
                per_probe_dfs.append((val, _load_outputs(probe_dir)))
            else:
                per_probe_dfs.append((val, None))
            if probe_dir.exists():
                shutil.rmtree(probe_dir)

        csv_results: list[S2ProbeResult] = []
        for csv, fn, expected, label, region in csv_metrics:
            metric_vals: list[float] = []
            probe_values_used: list[Any] = []
            for val, dfs in per_probe_dfs:
                if dfs is None:
                    metric_vals.append(float("nan"))
                else:
                    try:
                        m = fn(dfs, region) if region is not None else fn(dfs)
                    except Exception:
                        m = float("nan")
                    metric_vals.append(m)
                probe_values_used.append(val)
            verdict, note = classify_monotonic(metric_vals, expected)
            csv_results.append(S2ProbeResult(
                knob_path=path, csv=csv, metric_label=label,
                probe_values=probe_values_used,
                metric_values=[round(v, 6) if v == v else float("nan") for v in metric_vals],
                expected_dir=expected, verdict=verdict, note=note,
            ))
        overall, overall_note = _aggregate(csv_results)
        dt = time.time() - t0
        verdicts.append(S2KnobVerdict(
            knob_path=path, csv_results=csv_results,
            overall_verdict=overall, note=overall_note, elapsed_s=dt,
        ))
        print(f"[{i+1}/{len(admitted)}] {path}: {overall} ({dt:.1f}s) {overall_note[:80]}")

    # Cleanup
    for d in audit_root.glob("s2_baseline_*"):
        if d.is_dir():
            shutil.rmtree(d)
    for f in (audit_cfg / "scenarios").glob("_audit_*.yaml"):
        f.unlink()

    total_elapsed = time.time() - t_start
    print(f"\n[s2] total elapsed: {total_elapsed:.1f}s")

    meta = {
        "stage": 2,
        "git_sha": _git_sha(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": total_elapsed,
        "verdicts": [_s2_to_dict(v) for v in verdicts],
    }
    with (audit_root / "audit_s2_metadata.json").open("w") as f:
        json.dump(meta, f, indent=2)

    report_path = REPO / "docs" / "KNOB_AUDIT_S2.md"
    emit_stage2_report(verdicts, report_path, total_elapsed)
    print(f"[s2] report → {report_path}")
    return 0


def _s2_to_dict(v: S2KnobVerdict) -> dict:
    return {
        "knob_path": v.knob_path,
        "overall_verdict": v.overall_verdict,
        "note": v.note,
        "elapsed_s": v.elapsed_s,
        "csv_results": [asdict(r) for r in v.csv_results],
    }


def emit_stage2_report(verdicts: list[S2KnobVerdict], path: Path, elapsed: float) -> None:
    buckets: dict[str, list[S2KnobVerdict]] = {
        "MONOTONIC": [], "NON-MONOTONIC": [], "WEAK-EFFECT": [],
        "WRONG-DIRECTION": [], "NO-EFFECT": [], "UNTESTABLE": [], "NO-SPEC": [],
    }
    for v in verdicts:
        buckets.setdefault(v.overall_verdict, []).append(v)

    EMOJI = {
        "MONOTONIC": "✅", "NON-MONOTONIC": "⚠️", "WEAK-EFFECT": "⚠️",
        "WRONG-DIRECTION": "❌", "NO-EFFECT": "🟡",
        "UNTESTABLE": "⏭️", "NO-SPEC": "❓",
    }

    lines = []
    lines.append("# Knob Audit Stage 2: Direction + Magnitude\n")
    lines.append(f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    lines.append(f"Git SHA: `{_git_sha()}`\n")
    lines.append(f"Total elapsed: {elapsed:.1f}s\n")
    lines.append(f"Knobs probed: {len(verdicts)}\n")

    lines.append("\n## Summary\n")
    lines.append("| Verdict | Count |\n|---|---|\n")
    for name in ["MONOTONIC", "NON-MONOTONIC", "WEAK-EFFECT", "WRONG-DIRECTION",
                 "NO-EFFECT", "UNTESTABLE", "NO-SPEC"]:
        c = len(buckets.get(name, []))
        if c == 0 and name in ("NO-SPEC", "UNTESTABLE"):
            continue
        lines.append(f"| {EMOJI[name]} {name} | {c} |\n")
    lines.append(f"| **TOTAL** | **{len(verdicts)}** |\n")

    # Probe range constraints applied this run.
    lines.append("\n## Probe range constraints\n")
    lines.append("- **Weibull k floor=0.5** for deep-channel `dwell.k` probes. Weibull(k<0.5) "
                 "collapses to a degenerate density near 0; std/var becomes unstable at the "
                 "registry floor (k=0.01) without reflecting real pipeline behavior. The "
                 "registry range stays at [0.01, 5.0] — only the Stage 2 sweep skips below 0.5.\n")
    lines.append("- **Sparse-region baseline override:** deep-channel leaves under "
                 "`occasional_visitor.*` are probed on `S_audit_baseline` (50 EVs → ~5 users in "
                 "that region) instead of S01 (1 user typical). Single-user regions yield "
                 "insufficient samples for std/correlation metrics.\n")
    lines.append("- **`any` direction verdicts:** categorical / simplex / bool / list[region] "
                 "knobs have no ordinal probe order, so monotonicity isn't claimed. Verdict "
                 "is RESPONSIVE-vs-NO-EFFECT only.\n")

    # Per-bucket per-knob detail
    for name in ["MONOTONIC", "NON-MONOTONIC", "WEAK-EFFECT", "WRONG-DIRECTION",
                 "NO-EFFECT", "UNTESTABLE", "NO-SPEC"]:
        bucket = buckets.get(name, [])
        if not bucket:
            continue
        lines.append(f"\n## {EMOJI[name]} {name} ({len(bucket)} knobs)\n\n")
        for v in bucket:
            lines.append(f"### `{v.knob_path}`\n")
            for r in v.csv_results:
                pvs = [str(x)[:30] for x in r.probe_values]
                mvs = [f"{x:.4g}" if x == x else "nan" for x in r.metric_values]
                lines.append(f"- **{r.csv}** ({r.metric_label}, expect {r.expected_dir})\n")
                lines.append(f"  - probes: `{pvs}`\n")
                lines.append(f"  - metric: `{mvs}`\n")
                lines.append(f"  - **{r.verdict}** — {r.note}\n")
            if not v.csv_results:
                lines.append(f"  - {v.note}\n")
            lines.append("\n")

    # Cross-knob summary
    lines.append("## Cross-knob findings\n")
    deep_results = [v for v in verdicts if "region_distributions" in v.knob_path]
    deep_ok = sum(1 for v in deep_results if v.overall_verdict == "MONOTONIC")
    lines.append(f"- Deep-channel: {deep_ok}/{len(deep_results)} MONOTONIC.\n")
    noise_results = [v for v in verdicts if v.knob_path.startswith("noise.")]
    noise_ok = sum(1 for v in noise_results if v.overall_verdict == "MONOTONIC")
    lines.append(f"- noise.*: {noise_ok}/{len(noise_results)} MONOTONIC.\n")
    dr_results = [v for v in verdicts if "dr_" in v.knob_path or v.knob_path == "utility_rate.dr_program"]
    dr_ok = sum(1 for v in dr_results if v.overall_verdict == "MONOTONIC")
    lines.append(f"- DR-related: {dr_ok}/{len(dr_results)} MONOTONIC.\n")

    # Recommendations
    if buckets.get("WRONG-DIRECTION") or buckets.get("NO-EFFECT"):
        lines.append("\n## Recommendations\n")
        if buckets.get("WRONG-DIRECTION"):
            lines.append("### ❌ WRONG-DIRECTION (highest priority)\n")
            for v in buckets["WRONG-DIRECTION"]:
                lines.append(f"- `{v.knob_path}`: {v.note}\n")
        if buckets.get("NO-EFFECT"):
            lines.append("### 🟡 NO-EFFECT\n")
            for v in buckets["NO-EFFECT"]:
                lines.append(f"- `{v.knob_path}`: {v.note}\n")
        if buckets.get("WEAK-EFFECT"):
            lines.append("### ⚠️ WEAK-EFFECT (informational)\n")
            for v in buckets["WEAK-EFFECT"]:
                lines.append(f"- `{v.knob_path}`: {v.note}\n")

    with path.open("w") as f:
        f.write("".join(lines))


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["1", "2"], default="1")
    ap.add_argument("--audit-dir", default="/tmp/knob_audit")
    args = ap.parse_args()
    if args.stage == "1":
        return stage1(args)
    return stage2(args)


if __name__ == "__main__":
    sys.exit(main())
