"""Top-level calibration orchestration. Public entry point: calibrate_populations."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .battery_inference import infer_capacity, reconstruct_arrival_soc
from .distribution_fitter import fit_region
from .feature_extractor import (
    SessionFeatures,
    aggregate_user_features,
    extract_session,  # re-exported for backwards-compat callers
    population_weekend_factor,
)
from .region_assignment import assign_users
from .sources import CALIBRATION_SOURCES
from .writer import write_region_distributions


def calibrate_populations(
    populations_yaml_path: Path,
    population_names: list[str] | None = None,
    sites: tuple[str, ...] = ("caltech", "jpl", "office001"),
    year_start: int = 2019,
    year_end: int = 2021,
    cache_dir: Path = Path("data/calibration/acn_cache"),
    artifact_dir: Path = Path("data/calibration"),
    write_yaml: bool = True,
    source_configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run full calibration pipeline.

    Returns summary dict with per-population stats: {pop_name: {n_users, n_sessions, ...}}.
    `source_configs` is an optional policy → config-dict map; for backwards
    compatibility, when omitted ACN consumes the legacy `sites`/`year_start`/
    `year_end` kwargs.
    """
    populations_yaml_path = Path(populations_yaml_path)
    cache_dir = Path(cache_dir)
    artifact_dir = Path(artifact_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with populations_yaml_path.open() as _f:
        pops_yaml = yaml.safe_load(_f)

    if population_names is None:
        population_names = [
            n for n, v in pops_yaml.items()
            if isinstance(v, dict)
            and "axes_distribution" in v
            and v.get("calibration_policy") in CALIBRATION_SOURCES
        ]

    skipped: list[str] = []
    eligible_by_policy: dict[str, list[str]] = {}
    for pname in population_names:
        entry = pops_yaml.get(pname)
        if not isinstance(entry, dict) or "axes_distribution" not in entry:
            skipped.append(f"{pname} (missing axes_distribution)")
            continue
        policy = entry.get("calibration_policy")
        if policy not in CALIBRATION_SOURCES:
            skipped.append(f"{pname} (calibration_policy={policy!r}; nothing to fit)")
            continue
        eligible_by_policy.setdefault(policy, []).append(pname)

    today_iso = dt.date.today().isoformat()

    # Legacy kwarg → ACN config dict translation (preserve existing API).
    src_cfgs: dict[str, dict[str, Any]] = dict(source_configs or {})
    src_cfgs.setdefault("acn_data", {
        "sites": tuple(sites),
        "year_start": int(year_start),
        "year_end": int(year_end),
        "cache_dir": cache_dir,
    })

    # Non-acn policies require explicit source_configs; drop populations whose
    # policy has no config (auto-discovery path, e.g. evwatts without
    # --source-arg). They appear in skipped with a clear reason.
    for policy in list(eligible_by_policy.keys()):
        if policy == "acn_data":
            continue
        if policy not in src_cfgs:
            for pname in eligible_by_policy[policy]:
                skipped.append(
                    f"{pname} (calibration_policy={policy!r} requires "
                    "--source-arg config; pass release_tag etc. to calibrate)"
                )
            del eligible_by_policy[policy]

    if not eligible_by_policy:
        # Nothing to fit. Short-circuit before fetch — no token/network required.
        # Provenance kept ACN-shaped for backwards-compat with existing callers.
        acn = CALIBRATION_SOURCES["acn_data"]()
        return {
            "skipped_populations": skipped,
            "n_sessions_total": 0,
            "n_users_total": 0,
            "capacity_inference_fallback_rate": 0.0,
            "provenance": acn.provenance_prefix(src_cfgs["acn_data"]),
            "populations": {},
        }

    summary: dict[str, Any] = {
        "skipped_populations": skipped,
        "n_sessions_total": 0,
        "n_users_total": 0,
        "capacity_inference_fallback_rate": 0.0,
        "provenance": "",
        "populations": {},
    }

    total_capacity_total = 0
    total_capacity_fallback = 0
    last_provenance = ""

    for policy, pop_names_for_policy in eligible_by_policy.items():
        source = CALIBRATION_SOURCES[policy]()
        cfg = src_cfgs.setdefault(policy, {"cache_dir": cache_dir})
        cfg.setdefault("cache_dir", cache_dir)

        sessions = source.fetch_sessions(cfg)
        if not sessions:
            raise RuntimeError(
                f"no sessions extracted — {source.token_help_message()}"
            )

        # Aggregate per-user features.
        arrival_times = [s.arrival_time for s in sessions]
        window_start = min(arrival_times)
        window_end = max(arrival_times)
        users = aggregate_user_features(sessions, window_start, window_end)

        # Battery inference + arrival SoC per session.
        arr_soc_by_uid: dict[str, list[float]] = {}
        capacity_fallback_count = 0
        capacity_total = 0
        for s in sessions:
            cap, src = infer_capacity(s)
            capacity_total += 1
            if src == "fallback":
                capacity_fallback_count += 1
            soc = reconstruct_arrival_soc(s, cap)
            if soc is not None:
                arr_soc_by_uid.setdefault(s.user_id, []).append(soc)
        total_capacity_total += capacity_total
        total_capacity_fallback += capacity_fallback_count
        fallback_rate = (
            capacity_fallback_count / capacity_total if capacity_total else 0.0
        )

        sessions_by_uid: dict[str, list[SessionFeatures]] = {}
        for s in sessions:
            sessions_by_uid.setdefault(s.user_id, []).append(s)

        provenance = source.provenance_prefix(cfg)
        last_provenance = provenance
        extra_meta = source.extra_metadata(cfg)

        for pop_name in pop_names_for_policy:
            pop_summary = _calibrate_one_population(
                pop_name=pop_name,
                pops_yaml=pops_yaml,
                users=users,
                sessions_by_uid=sessions_by_uid,
                arr_soc_by_uid=arr_soc_by_uid,
                populations_yaml_path=populations_yaml_path,
                provenance=provenance,
                dataset_name=source.dataset_name(),
                extra_meta=extra_meta,
                today_iso=today_iso,
                fallback_rate=fallback_rate,
                n_users_total=len(users),
                n_sessions_total=len(sessions),
                write_yaml=write_yaml,
            )
            summary["populations"][pop_name] = pop_summary

        # Write per-user artifact CSV (filename is per-source).
        user_df = pd.DataFrame([
            {"user_id": u.user_id, "n_sessions": u.n_sessions, "phi": u.phi,
             "kappa": u.kappa, "delta_km": u.delta_km}
            for u in users
        ])
        user_df.to_csv(artifact_dir / source.per_user_csv_filename, index=False)

        summary["n_sessions_total"] += len(sessions)
        summary["n_users_total"] += len(users)

    summary["capacity_inference_fallback_rate"] = (
        total_capacity_fallback / total_capacity_total
        if total_capacity_total else 0.0
    )
    summary["provenance"] = last_provenance

    return summary


def _calibrate_one_population(
    pop_name: str,
    pops_yaml: dict[str, Any],
    users: list,
    sessions_by_uid: dict[str, list[SessionFeatures]],
    arr_soc_by_uid: dict[str, list[float]],
    populations_yaml_path: Path,
    provenance: str,
    dataset_name: str,
    extra_meta: dict[str, Any],
    today_iso: str,
    fallback_rate: float,
    n_users_total: int,
    n_sessions_total: int,
    write_yaml: bool,
) -> dict[str, Any]:
    pop = pops_yaml[pop_name]
    axes = pop["axes_distribution"]
    region_to_users = assign_users(users, axes)
    n_unassigned = len(region_to_users.get("__unassigned__", []))
    unassigned_rate = n_unassigned / len(users) if users else 0.0

    region_fits: dict[str, dict[str, Any]] = {}
    n_users_with_inputs = 0
    for region in axes:
        rname = region["name"]
        region_users = region_to_users.get(rname, [])
        arr_list: list[float] = []
        dwell_list: list[float] = []
        soc_list: list[float] = []
        for u in region_users:
            sess = sessions_by_uid.get(u.user_id, [])
            for s in sess:
                arr_list.append(s.arrival_hour)
                dwell_list.append(s.dwell_hours)
            socs = arr_soc_by_uid.get(u.user_id, [])
            soc_list.extend(socs)
            if socs:
                n_users_with_inputs += 1

        arrivals = np.asarray(arr_list, dtype=float)
        dwells = np.asarray(dwell_list, dtype=float)
        soc_arr = np.asarray(soc_list, dtype=float) if soc_list else None
        fit = fit_region(arrivals, dwells, soc_arr)
        clean: dict[str, Any] = {}
        for key in ("arrival", "dwell", "soc_arrival", "copula"):
            if fit.get(key) is not None:
                clean[key] = fit[key]
        if clean:
            region_fits[rname] = clean

    metadata: dict[str, Any] = {
        "source": provenance,
        "dataset": dataset_name,
    }
    metadata.update(extra_meta)
    metadata.update({
        "calibration_date": today_iso,
        "n_users_total": int(n_users_total),
        "n_sessions_total": int(n_sessions_total),
        "n_users_assigned_in_population": int(sum(
            len(v) for k, v in region_to_users.items() if k != "__unassigned__"
        )),
        "n_users_with_userinputs": int(n_users_with_inputs),
        "capacity_inference_fallback_rate": float(fallback_rate),
        "unassigned_user_rate": float(unassigned_rate),
    })

    # Population weekend:weekday session-rate ratio (drives weekend appearance
    # at generation; read back via user_behavior.weekend_activity_factor).
    pop_sessions = [s for sess in sessions_by_uid.values() for s in sess]
    metadata["weekend_activity_factor"] = round(
        population_weekend_factor(pop_sessions), 4
    )

    # Empirical per-region USER share → axes_distribution weights. Generation
    # draws a car's region from this single field (per_entity.py); the prior
    # hand-authored placeholder (e.g. flat 0.20) decoupled it from reality and
    # over-produced rare regions ~100x. USER share (not session share) matches
    # the per-car assignment unit and the F5 validator. Normalized over the
    # assigned regions so the vector sums to 1.0 (knob_loader requires it);
    # genuinely-zero-user regions get weight 0.
    total_assigned = sum(
        len(v) for k, v in region_to_users.items() if k != "__unassigned__"
    )
    axes_weights: dict[str, float] | None = None
    if total_assigned > 0:
        raw = {
            region["name"]: len(region_to_users.get(region["name"], [])) / total_assigned
            for region in axes
        }
        s = sum(raw.values())
        if s > 0:
            axes_weights = {k: v / s for k, v in raw.items()}

    if write_yaml:
        write_region_distributions(
            populations_yaml_path,
            pop_name,
            region_fits,
            metadata,
            axes_weights=axes_weights,
        )

    return {
        "n_regions_fit": len(region_fits),
        "regions": list(region_fits.keys()),
        "unassigned_user_rate": unassigned_rate,
        "metadata": metadata,
    }
