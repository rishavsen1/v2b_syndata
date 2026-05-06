"""Top-level calibration orchestration. Public entry point: calibrate_populations."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .acn_fetcher import fetch_all_sessions, filter_with_userid
from .battery_inference import infer_capacity, reconstruct_arrival_soc
from .distribution_fitter import fit_region
from .feature_extractor import (
    SessionFeatures,
    aggregate_user_features,
    extract_session,
)
from .region_assignment import assign_users
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
) -> dict[str, Any]:
    """Run full calibration pipeline.

    Returns summary dict with per-population stats: {pop_name: {n_users, n_sessions, ...}}.
    """
    populations_yaml_path = Path(populations_yaml_path)
    cache_dir = Path(cache_dir)
    artifact_dir = Path(artifact_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch all sessions across sites and years.
    raw_sessions: list[tuple[dict[str, Any], str]] = []
    for site in sites:
        site_sessions = fetch_all_sessions(site, year_start, year_end, cache_dir=cache_dir)
        site_sessions = filter_with_userid(site_sessions)
        for s in site_sessions:
            raw_sessions.append((s, site))

    # 2. Extract per-session features.
    sessions: list[SessionFeatures] = []
    for raw, site in raw_sessions:
        sf = extract_session(raw, site)
        if sf is not None:
            sessions.append(sf)

    if not sessions:
        raise RuntimeError(
            "no sessions extracted — verify ACN_API_TOKEN and year range"
        )

    # 3. Aggregate per-user features.
    window_start = pd.Timestamp(f"{year_start}-01-01", tz="UTC")
    window_end = pd.Timestamp(f"{year_end}-12-31", tz="UTC")
    users = aggregate_user_features(sessions, window_start, window_end)

    # 4. Battery inference + arrival SoC per session.
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

    fallback_rate = capacity_fallback_count / capacity_total if capacity_total else 0.0

    # 5. Index sessions by user for fast region-aggregation.
    sessions_by_uid: dict[str, list[SessionFeatures]] = {}
    for s in sessions:
        sessions_by_uid.setdefault(s.user_id, []).append(s)

    # 6. Per-population processing.
    with populations_yaml_path.open() as f:
        pops_yaml = yaml.safe_load(f)

    if population_names is None:
        population_names = [
            n for n, v in pops_yaml.items()
            if isinstance(v, dict) and "axes_distribution" in v
        ]

    today_iso = dt.date.today().isoformat()
    today_compact = today_iso.replace("-", "")
    provenance = f"calibration:acn_data_{year_start}_{year_end}_{today_compact}"

    summary: dict[str, Any] = {
        "n_sessions_total": len(sessions),
        "n_users_total": len(users),
        "capacity_inference_fallback_rate": fallback_rate,
        "provenance": provenance,
        "populations": {},
    }

    for pop_name in population_names:
        pop_summary = _calibrate_one_population(
            pop_name=pop_name,
            pops_yaml=pops_yaml,
            users=users,
            sessions_by_uid=sessions_by_uid,
            arr_soc_by_uid=arr_soc_by_uid,
            populations_yaml_path=populations_yaml_path,
            provenance=provenance,
            sites=sites,
            year_start=year_start,
            year_end=year_end,
            today_iso=today_iso,
            fallback_rate=fallback_rate,
            n_users_total=len(users),
            n_sessions_total=len(sessions),
            write_yaml=write_yaml,
        )
        summary["populations"][pop_name] = pop_summary

    # 7. Write per-user and per-region artifact CSVs.
    user_df = pd.DataFrame([
        {"user_id": u.user_id, "n_sessions": u.n_sessions, "phi": u.phi,
         "kappa": u.kappa, "delta_km": u.delta_km}
        for u in users
    ])
    user_df.to_csv(artifact_dir / "acn_per_user.csv", index=False)

    return summary


def _calibrate_one_population(
    pop_name: str,
    pops_yaml: dict[str, Any],
    users: list,
    sessions_by_uid: dict[str, list[SessionFeatures]],
    arr_soc_by_uid: dict[str, list[float]],
    populations_yaml_path: Path,
    provenance: str,
    sites: tuple[str, ...],
    year_start: int,
    year_end: int,
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

    metadata = {
        "source": provenance,
        "dataset": "ACN-Data",
        "sites": list(sites),
        "year_range": [int(year_start), int(year_end)],
        "calibration_date": today_iso,
        "n_users_total": int(n_users_total),
        "n_sessions_total": int(n_sessions_total),
        "n_users_assigned_in_population": int(sum(
            len(v) for k, v in region_to_users.items() if k != "__unassigned__"
        )),
        "n_users_with_userinputs": int(n_users_with_inputs),
        "capacity_inference_fallback_rate": float(fallback_rate),
        "unassigned_user_rate": float(unassigned_rate),
    }

    if write_yaml:
        write_region_distributions(
            populations_yaml_path,
            pop_name,
            region_fits,
            metadata,
        )

    return {
        "n_regions_fit": len(region_fits),
        "regions": list(region_fits.keys()),
        "unassigned_user_rate": unassigned_rate,
        "metadata": metadata,
    }
