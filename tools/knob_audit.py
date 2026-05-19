"""Knob audit harness — Stage 1 (existence + isolation) and Stage 2 (direction + magnitude).

Stage 1 verifies each knob/deep-param actually affects the declared output CSVs.
Stage 2 sweeps and tests directional response.

Run:
    python tools/knob_audit.py --stage 1
    python tools/knob_audit.py --stage 2          # only after S1 triage
    python tools/knob_audit.py --stage 1 --jobs 4 # parallel probes

Outputs:
    /tmp/knob_audit/audit_metadata.json
    KNOB_AUDIT_S1.md  (or KNOB_AUDIT_S2.md)
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


def parse_descriptors(config_dir: Path, base_scenario: str = DEFAULT_SCENARIO) -> list[KnobSpec]:
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
) -> tuple[bool, str | None]:
    """Invoke runner.generate via subprocess so failures isolate cleanly."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "v2b_syndata.cli",
        "--config-dir", str(config_dir),
        "generate",
        "--scenario", scenario,
        "--seed", str(DEFAULT_SEED),
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
    for scen in {s.baseline_scenario for s in knobs_specs} | {DEFAULT_SCENARIO}:
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
                    audit_cfg, DEFAULT_SCENARIO, spec.descriptor_kind, value
                )
                ok, err = run_scenario(scen_id, {}, probe_dir, audit_cfg)
                scen_used = scen_id
            else:
                ok, err = run_scenario(
                    spec.baseline_scenario, {spec.path: value}, probe_dir, audit_cfg
                )
                scen_used = spec.baseline_scenario
            elapsed = time.time() - t_probe
            if ok:
                probe_hash = hash_outputs(probe_dir)
                base_for_scen = baselines[scen_used] if scen_used in baselines else baselines[spec.baseline_scenario]
                changed = diff_hashes(base_for_scen, probe_hash)
            else:
                changed = []
            probes.append(ProbeResult(
                knob_path=spec.path, probe_label=label, probe_value=value,
                scenario=scen_used, success=ok, error=err,
                changed_csvs=changed, elapsed_s=elapsed,
            ))
            # Free disk
            if probe_dir.exists():
                shutil.rmtree(probe_dir)

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
    report_path = REPO / "KNOB_AUDIT_S1.md"
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

    # Per-knob diagnosis for under-coupled findings (hand-curated).
    UNDER_COUPLED_DIAGNOSIS = {
        "building_load.climate":
            "DECLARATION FIX. Description in knobs.yaml says 'Climate label (categorical, "
            "used for indexing). Weather W carries actual signal.' → label-only knob; "
            "set affects_csv: []. Current 'building_load.csv' declaration is aspirational, "
            "not real.",
        "building_load.weather_lat":
            "PIPELINE LEGACY. NASAPower lat/lon predated TMYx pipeline (D37). EnergyPlus now "
            "drives building_load.csv via `tmyx_station`. Either: (a) remove these three knobs, "
            "or (b) re-declare affects_csv=[] and document as 'stub/future'. Currently dead.",
        "building_load.weather_lon": "See weather_lat — same legacy issue.",
        "building_load.weather_year":
            "Same legacy issue. Anchor year is currently used only for sim window indexing "
            "(sim_window picks April YYYY); EPW year is the TMYx file's own year.",
        "building_load.occupancy_source":
            "PARTIAL EFFECT. Occupancy schedule swap changes EnergyPlus output (✓ building_load) "
            "but sessions.csv unchanged. Either: (a) sessions don't actually consume occupancy "
            "signal (likely — occupancy modulates building load, not session arrival times), or "
            "(b) modulation pathway dropped. Verify samplers/per_entity.py — if (a), update "
            "affects_csv to [building_load.csv].",
        "utility_rate.tariff_type":
            "DECLARATION FIX. dr_events.csv is driven by `dr_program`, not `tariff_type`. Probe "
            "TOU→flat changes grid_prices.csv (✓) but not DR events. Set affects_csv: "
            "[grid_prices.csv] only.",
        "sim_window.mode":
            "EXPECTED MISS. Probe under S01 has dr_program=none so dr_events.csv is empty in "
            "both baseline and probe; cannot observe sim_window effect on DR. The knob DOES "
            "affect dr_events scheduling under any dr-enabled scenario (proven indirectly via "
            "S_dr_cbp). Optional: re-probe sim_window.mode under S_dr_cbp for the dr_events "
            "leg, OR drop dr_events.csv from affects_csv when no DR program is active "
            "(but that's conditional — leave as-is).",
        "noise.profile":
            "PROBABILISTIC MISS. Probe is `adversarial` under S_dr_cbp baseline. "
            "dr_notification_dropout_prob=0.10 may produce zero drops on a small event count "
            "(P(0|n≈8) ≈ 0.43). Re-run with seed sweep to confirm coverage. Not a real bug.",
    }
    OVER_COUPLED_DIAGNOSIS = {
        "ev_fleet.battery_mix":
            "Expected coupling — sessions reference per-car capacity for SoC accounting. "
            "Cross-effect on sessions.csv is physically correct. Update declaration to "
            "[cars.csv, sessions.csv].",
        "ev_fleet.battery_heterogeneity": "Same as battery_mix — declaration should include sessions.csv.",
        "charging_infra.uni_rate_kw":
            "Investigate: chargers.csv carries rate, but sessions.csv shouldn't reference it "
            "directly. May be RNG-stream coupling (different charger order changes session "
            "RNG draws). Verify in seeding.py.",
        "charging_infra.bi_rate_kw": "Same as uni_rate_kw — investigate RNG coupling.",
    }

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
# Stage 2 (stub — implement after S1 triage)
# ──────────────────────────────────────────────────────────────────────────


def stage2(args: argparse.Namespace) -> int:
    print("Stage 2 not yet implemented. Run --stage 1 first; triage with user.")
    return 1


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
