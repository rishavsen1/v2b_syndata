"""Batch generation: months × samples_per_month → structured output tree.

Used by the `v2b-syndata batch` CLI subcommand and the `/api/batch` web
endpoint. Wraps `runner.generate()` with a multiprocessing pool and a
top-level `batch_manifest.json` that tracks per-sample status.

Opinionated batch defaults differ from single-shot CLI:

    --noise-profile tmyx_stochastic
    --axes-alpha 30      (user_behavior.axes_distribution_dirichlet_alpha)
    --battery-alpha 30   (ev_fleet.battery_mix_dirichlet_alpha)

so a no-arg batch run produces seed-varying building load + population +
battery composition. All three are overridable via flag.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .e5_metrics import InfeasibilityError
from .knob_loader import _normalize


@dataclass
class BatchJobSpec:
    scenario_id: str
    month_label: str          # e.g., "APR2024"
    month_start: str          # ISO date, e.g., "2024-04-01"
    sample_idx: int
    seed: int
    sample_dir: Path          # <output_dir>/<scenario_id>/<MONTH>/<idx>/
    config_dir: Path
    noise_profile: str | None
    extra_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    month: str
    sample_idx: int
    seed: int
    path: str
    status: str               # "succeeded" | "failed"
    duration_sec: float
    error: str | None = None
    # Post-generation validation rollup for this unit. For a plain-batch sample
    # it is the single native manifest's `validation` block reshaped to
    # {passed, n_errors, errors}; for a multi-building unit it is the unit's
    # `validation_summary` ({n_units, n_passed, n_failed, total_errors, ...}).
    # None when the unit failed before writing a manifest.
    validation: dict[str, Any] | None = None


def _months_between(start_ym: str, end_ym: str) -> list[tuple[str, datetime]]:
    """Inclusive months from 'YYYY-MM' to 'YYYY-MM'. Returns [(LABEL, datetime)].

    Label is 3-letter month + year, uppercase: 'APR2024'.
    """
    start = datetime.strptime(start_ym + "-01", "%Y-%m-%d")
    end = datetime.strptime(end_ym + "-01", "%Y-%m-%d")
    if end < start:
        raise ValueError(f"end_month {end_ym} before start_month {start_ym}")
    out: list[tuple[str, datetime]] = []
    cur = start
    while cur <= end:
        label = cur.strftime("%b%Y").upper()
        out.append((label, cur))
        # Roll to first of next month
        y, m = cur.year, cur.month
        m += 1
        if m == 13:
            m = 1
            y += 1
        cur = datetime(y, m, 1)
    return out


def _run_one_sample(spec: BatchJobSpec) -> BatchResult:
    """Worker entry: invoke the CLI as a subprocess so EnergyPlus has its own
    process and tempdir lifecycle. Subprocess invocation also isolates any
    crash from the orchestrator."""
    t0 = time.monotonic()
    spec.sample_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "v2b_syndata.cli",
        "--config-dir", str(spec.config_dir),
        "generate",
        "--scenario", spec.scenario_id,
        "--seed", str(spec.seed),
        "--output-dir", str(spec.sample_dir),
    ]
    if spec.noise_profile:
        cmd += ["--noise-profile", spec.noise_profile]

    # Inject sim_window override for this month.
    extras = dict(spec.extra_overrides)
    extras.setdefault("sim_window.mode", "month")
    extras["sim_window.start"] = spec.month_start
    for path, value in extras.items():
        cmd += ["--override", f"{path}={_format_value(value)}"]

    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
        status = "succeeded" if res.returncode == 0 else "failed"
        err = None if status == "succeeded" else (res.stderr or "non-zero rc")[-2000:]
    except subprocess.TimeoutExpired:
        status, err = "failed", "timeout (>30 min)"
    except Exception as e:  # noqa: BLE001
        status, err = "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    # Read the auto-validation block runner.generate wrote into the manifest.
    validation = _read_sample_validation(spec.sample_dir)

    return BatchResult(
        month=spec.month_label,
        sample_idx=spec.sample_idx,
        seed=spec.seed,
        path=str(spec.sample_dir.relative_to(spec.sample_dir.parent.parent.parent)),
        status=status,
        duration_sec=time.monotonic() - t0,
        error=err,
        validation=validation,
    )


def _read_sample_validation(sample_dir: Path) -> dict[str, Any] | None:
    """Return {passed, n_errors, errors} from a native sample's manifest, or None."""
    mpath = sample_dir / "manifest.json"
    if not mpath.exists():
        return None
    try:
        v = json.loads(mpath.read_text()).get("validation")
    except (json.JSONDecodeError, OSError):
        return None
    if not v:
        return None
    return {
        "passed": bool(v.get("passed", not v.get("n_errors", 0))),
        "n_errors": int(v.get("n_errors", 0)),
        "errors": list(v.get("errors", []))[:5],
    }


def _format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return json.dumps(list(v))
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v)


def run_batch(
    scenario_id: str,
    output_dir: Path,
    config_dir: Path,
    start_month: str,
    end_month: str,
    samples_per_month: int,
    workers: int = 4,
    seed_base: int = 0,
    noise_profile: str | None = "tmyx_stochastic",
    extra_overrides: dict[str, Any] | None = None,
    force: bool = False,
    progress_callback=None,  # called per sample completion
) -> dict[str, Any]:
    """Orchestrate the batch. Writes batch_manifest.json and returns it."""

    if output_dir.exists():
        if not force:
            raise FileExistsError(
                f"Output dir {output_dir} exists. Pass force=True to overwrite."
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    months = _months_between(start_month, end_month)
    extras = dict(extra_overrides or {})
    # Opinionated batch defaults — overridable via extra_overrides.
    extras.setdefault("user_behavior.axes_distribution_dirichlet_alpha", 30.0)
    extras.setdefault("ev_fleet.battery_mix_dirichlet_alpha", 30.0)
    extras = _normalize(extras)

    batch_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.utcnow().isoformat() + "Z"

    specs: list[BatchJobSpec] = []
    for label, dt in months:
        month_start_iso = dt.strftime("%Y-%m-%d")
        for s_idx in range(samples_per_month):
            specs.append(BatchJobSpec(
                scenario_id=scenario_id,
                month_label=label,
                month_start=month_start_iso,
                sample_idx=s_idx,
                seed=seed_base + s_idx,
                sample_dir=output_dir / scenario_id / label / str(s_idx),
                config_dir=config_dir,
                noise_profile=noise_profile,
                extra_overrides=dict(extras),
            ))

    manifest: dict[str, Any] = {
        "batch_id": batch_id,
        "scenario_id": scenario_id,
        "start_month": start_month,
        "end_month": end_month,
        "samples_per_month": samples_per_month,
        "seed_base": seed_base,
        "seed_strategy": "linear",
        "noise_profile": noise_profile,
        "extra_overrides": extras,
        "workers": workers,
        "started_at": started_at,
        "completed_at": None,
        "status": "in_progress",
        "n_total": len(specs),
        "n_succeeded": 0,
        "n_failed": 0,
        "samples": [],
        "validation_summary": {
            "n_units": 0, "n_passed": 0, "n_failed": 0,
            "total_errors": 0, "failed_units": [],
        },
    }
    manifest_path = output_dir / "batch_manifest.json"
    _write_manifest(manifest_path, manifest)

    results: list[BatchResult] = []
    use_parallel = workers > 1 and len(specs) > 1
    if use_parallel:
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_run_one_sample, s): s for s in specs}
                for fut in as_completed(futures):
                    res = fut.result()
                    results.append(res)
                    _record_result(manifest, res)
                    _write_manifest(manifest_path, manifest)
                    if progress_callback:
                        progress_callback(res, manifest)
        except Exception as e:  # noqa: BLE001
            manifest["parallel_fallback_reason"] = f"{type(e).__name__}: {e}"
            use_parallel = False  # fall through to serial for any remaining specs
            remaining = [s for s in specs if not any(
                r.month == s.month_label and r.sample_idx == s.sample_idx for r in results
            )]
            for s in remaining:
                res = _run_one_sample(s)
                results.append(res)
                _record_result(manifest, res)
                _write_manifest(manifest_path, manifest)
                if progress_callback:
                    progress_callback(res, manifest)
    else:
        for s in specs:
            res = _run_one_sample(s)
            results.append(res)
            _record_result(manifest, res)
            _write_manifest(manifest_path, manifest)
            if progress_callback:
                progress_callback(res, manifest)

    manifest["completed_at"] = datetime.utcnow().isoformat() + "Z"
    succeeded = manifest["n_succeeded"]
    failed = manifest["n_failed"]
    if failed == 0:
        manifest["status"] = "succeeded"
    elif failed > len(specs) // 2:
        manifest["status"] = "failed"
    else:
        manifest["status"] = "partial"
    # Sort sample log by (month, sample_idx) for stable output.
    manifest["samples"].sort(key=lambda r: (r["month"], r["sample_idx"]))
    _write_manifest(manifest_path, manifest)
    return manifest


def _record_result(manifest: dict[str, Any], res: BatchResult) -> None:
    manifest["samples"].append({
        "month": res.month,
        "sample_idx": res.sample_idx,
        "seed": res.seed,
        "path": res.path,
        "status": res.status,
        "duration_sec": round(res.duration_sec, 2),
        "error": res.error,
        "validation": res.validation,
    })
    if res.status == "succeeded":
        manifest["n_succeeded"] += 1
    else:
        manifest["n_failed"] += 1
    _update_validation_summary(manifest, res)


def _update_validation_summary(manifest: dict[str, Any], res: BatchResult) -> None:
    """Incrementally fold one unit's validation into manifest["validation_summary"].

    A plain-batch unit contributes one native manifest's `validation` block; a
    multi-building unit contributes its `validation_summary`. Either shape is
    normalized to (units, passed, failed, errors) here so both batch kinds emit
    the same top-level summary schema.
    """
    vs = manifest.setdefault("validation_summary", {
        "n_units": 0, "n_passed": 0, "n_failed": 0,
        "total_errors": 0, "failed_units": [],
    })
    v = res.validation
    # Nested multi-building rollup (has n_units) → aggregate its counts.
    if v and "n_units" in v:
        vs["n_units"] += int(v.get("n_units", 0))
        vs["n_passed"] += int(v.get("n_passed", 0))
        vs["n_failed"] += int(v.get("n_failed", 0))
        vs["total_errors"] += int(v.get("total_errors", 0))
        if v.get("n_failed", 0) and len(vs["failed_units"]) < 20:
            vs["failed_units"].append({
                "month": res.month, "sample": res.sample_idx,
                "n_errors": int(v.get("total_errors", 0)),
                "errors": [str(fu) for fu in v.get("failed_units", [])][:5],
            })
        return
    # Flat single-manifest validation (plain batch sample).
    vs["n_units"] += 1
    n_err = int(v.get("n_errors", 0)) if v else 0
    vs["total_errors"] += n_err
    passed = v.get("passed", not n_err) if v else (res.status == "succeeded")
    if passed:
        vs["n_passed"] += 1
    else:
        vs["n_failed"] += 1
        if len(vs["failed_units"]) < 20:
            vs["failed_units"].append({
                "month": res.month, "sample": res.sample_idx,
                "n_errors": n_err, "errors": list(v.get("errors", []))[:5] if v else [],
            })


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n")
