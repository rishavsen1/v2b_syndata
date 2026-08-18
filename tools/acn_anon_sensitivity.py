"""Quantify how ACN's anonymous (null-``userID``) sessions would shift the fits.

The shipped calibrator drops anonymous sessions in
``AcnSource.fetch_sessions`` via ``filter_with_userid``. This script measures
what the per-region parameters *would* have been had those rows been retained
as one-session-each pseudo-users, so the exclusion can be reported as a
quantified choice rather than an assumption.

Two variants are compared against the shipped baseline:

``literal``
    Anonymous sessions get a synthetic ``userID`` and go through
    ``aggregate_user_features`` unmodified. ``MIN_SESSIONS_PER_USER`` (5) and
    ``MIN_WEEKDAYS_IN_USER_WINDOW`` (5) both reject a one-session user, so this
    variant is expected to reproduce the baseline exactly. It is run rather
    than assumed.

``forced``
    The pseudo-users bypass those two filters: each anonymous session becomes a
    ``UserFeatures`` built with the same phi/kappa formulas
    ``aggregate_user_features`` would apply to a single-session user
    (phi = 1.0 on a weekday, 0.0 on a weekend; kappa = 1.0 because a lone
    arrival hour has zero variance; delta_km unobserved). Real identified users
    are untouched, so every delta is attributable to the anonymous rows.

Arrival SoC is a seeded prior draw shared across sessions, so both variants
iterate identified sessions first and in the shipped order. That keeps the
identified sessions' SoC draws bit-identical and prevents an RNG reshuffle from
masquerading as a parameter shift.

Usage
-----
  uv run python tools/acn_anon_sensitivity.py
  uv run python tools/acn_anon_sensitivity.py --site caltech --site jpl
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from v2b_syndata.calibration import api
from v2b_syndata.calibration.acn_fetcher import fetch_all_sessions, filter_with_userid
from v2b_syndata.calibration.battery_inference import (
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.feature_extractor import (
    SessionFeatures,
    UserFeatures,
    aggregate_user_features,
    extract_session,
)

SITE_TO_POPULATION = {
    "caltech": "acn_caltech_baseline",
    "jpl": "acn_jpl_baseline",
    "office001": "acn_office001_baseline",
}
CACHE_DIR = Path("data/calibration/acn_cache")
POPS_YAML = Path("configs/populations.yaml")
YEAR_START, YEAR_END = 2019, 2021
ARR_SOC_SEED = 20260613  # must match api.calibrate_populations


def split_raw(site: str) -> tuple[list[dict], list[dict]]:
    """Return (identified_raw, anonymous_raw) for one site."""
    raw = fetch_all_sessions(site, YEAR_START, YEAR_END, cache_dir=CACHE_DIR)
    identified = filter_with_userid(raw)
    anonymous = [r for r in raw if r.get("userID") is None]
    return identified, anonymous


def extract(raws: list[dict], site: str) -> list[SessionFeatures]:
    out = []
    for r in raws:
        sf = extract_session(r, site)
        if sf is not None:
            out.append(sf)
    return out


def tag_anonymous(anon_raw: list[dict], site: str) -> list[SessionFeatures]:
    """One synthetic userID per anonymous session → one pseudo-user per session."""
    tagged = []
    for i, r in enumerate(anon_raw):
        r2 = dict(r)
        r2["userID"] = f"anon_{site}_{i:06d}"
        tagged.append(r2)
    return extract(tagged, site)


def pseudo_user(s: SessionFeatures) -> UserFeatures:
    """UserFeatures for a single-session user, mirroring aggregate_user_features."""
    ts = pd.Timestamp(s.arrival_time)
    is_weekday = ts.dayofweek < 5
    n_weekdays = 1 if is_weekday else 0
    n_obs = 1 if is_weekday else 0
    phi = float(n_obs / n_weekdays) if n_weekdays > 0 else 0.0
    return UserFeatures(
        user_id=s.user_id,
        n_sessions=1,
        n_weekdays_observed=n_obs,
        n_weekdays_total=n_weekdays,
        phi=phi,
        kappa=1.0,  # zero-variance arrival hour → the std==0 branch
        delta_km=None,
    )


def soc_tables(
    sessions: list[SessionFeatures],
) -> tuple[dict[str, list[float]], dict[str, list[float]], float]:
    """Replicate the arrival/departure SoC reconstruction in calibrate_populations."""
    arr_soc: dict[str, list[float]] = {}
    dep_soc: dict[str, list[float]] = {}
    fallback = total = 0
    rng = np.random.default_rng(ARR_SOC_SEED)
    for s in sessions:
        cap, src = infer_capacity(s)
        total += 1
        if src == "fallback":
            fallback += 1
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        if soc is None:
            continue
        arr_soc.setdefault(s.user_id, []).append(soc)
        if s.kwh_delivered is not None and cap and cap > 0:
            depart = min(1.0 - 1e-6, soc + float(s.kwh_delivered) / float(cap))
            if depart > soc:
                dep_soc.setdefault(s.user_id, []).append(depart)
    return arr_soc, dep_soc, (fallback / total if total else 0.0)


def run_variant(
    site: str,
    pops_yaml: dict[str, Any],
    mode: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Fit one site under `mode` ∈ {baseline, literal, forced}.

    Returns (region_fits, metadata, region_user_counts).
    """
    pop_name = SITE_TO_POPULATION[site]
    identified_raw, anon_raw = split_raw(site)
    sess_ident = extract(identified_raw, site)
    sess_anon = tag_anonymous(anon_raw, site) if mode != "baseline" else []

    # Identified first, shipped order → identical RNG draws across variants.
    sessions = sess_ident + sess_anon

    if mode == "literal":
        # Straight through the shipped aggregator; the min-session and
        # min-weekday filters decide whether pseudo-users survive.
        window_start = min(s.arrival_time for s in sessions)
        window_end = max(s.arrival_time for s in sessions)
        users = aggregate_user_features(sessions, window_start, window_end)
    else:
        window_start = min(s.arrival_time for s in sess_ident)
        window_end = max(s.arrival_time for s in sess_ident)
        users = aggregate_user_features(sess_ident, window_start, window_end)
        if mode == "forced":
            users = users + [pseudo_user(s) for s in sess_anon]

    arr_soc, dep_soc, fallback_rate = soc_tables(sessions)
    sessions_by_uid: dict[str, list[SessionFeatures]] = {}
    for s in sessions:
        sessions_by_uid.setdefault(s.user_id, []).append(s)

    captured: dict[str, Any] = {}

    def capture(path, name, region_fits, metadata, axes_weights=None):
        captured["fits"] = region_fits
        captured["weights"] = axes_weights

    original = api.write_region_distributions
    api.write_region_distributions = capture
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            api._calibrate_one_population(
                pop_name=pop_name,
                pops_yaml=pops_yaml,
                users=users,
                sessions_by_uid=sessions_by_uid,
                arr_soc_by_uid=arr_soc,
                depart_soc_by_uid=dep_soc,
                populations_yaml_path=POPS_YAML,
                provenance=f"sensitivity:{mode}",
                dataset_name="ACN-Data",
                extra_meta={"sites": [site], "mode": mode},
                today_iso="sensitivity",
                fallback_rate=fallback_rate,
                n_users_total=len(users),
                n_sessions_total=len(sessions),
                write_yaml=True,
            )
    finally:
        api.write_region_distributions = original

    axes = pops_yaml[pop_name]["axes_distribution"]
    from v2b_syndata.calibration.region_assignment import assign_users

    r2u = assign_users(users, axes)
    counts = {r["name"]: len(r2u.get(r["name"], [])) for r in axes}
    counts["__unassigned__"] = len(r2u.get("__unassigned__", []))

    meta = {
        "n_users": len(users),
        "n_sessions": len(sessions),
        "n_pseudo_users": len(sess_anon) if mode == "forced" else 0,
        "capacity_fallback_rate": fallback_rate,
    }
    return captured["fits"], meta, counts


def flatten(d: dict | None, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


SKIP_SUFFIXES = ("n_samples", "ks_fit_quality", "dist", "trunc_lo", "trunc_hi")


def diff_fits(base: dict, variant: dict) -> list[tuple[str, Any, Any, float | None]]:
    a, b = flatten(base), flatten(variant)
    rows = []
    for key in sorted(set(a) | set(b)):
        if key.rsplit(".", 1)[-1] in SKIP_SUFFIXES:
            continue
        va, vb = a.get(key), b.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            va, vb = float(va), float(vb)
            if np.isclose(va, vb, rtol=1e-9, atol=1e-12):
                continue
            pct = (vb - va) / abs(va) * 100.0 if va != 0 else None
            rows.append((key, va, vb, pct))
        elif va != vb:
            rows.append((key, va, vb, None))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", action="append", choices=sorted(SITE_TO_POPULATION),
                    default=None, help="repeatable; default: all three")
    ap.add_argument("--top", type=int, default=40,
                    help="max parameter rows to print per site")
    ap.add_argument("--csv", type=Path, default=None,
                    help="also write every per-parameter delta to this CSV")
    args = ap.parse_args(argv)

    sites = args.site or ["caltech", "jpl", "office001"]
    pops_yaml = yaml.safe_load(POPS_YAML.read_text())
    committed = pops_yaml
    csv_rows: list[dict[str, Any]] = []

    for site in sites:
        pop = SITE_TO_POPULATION[site]
        print("=" * 78)
        print(f"{site}  ({pop})")
        print("=" * 78)

        base_fits, base_meta, base_counts = run_variant(site, pops_yaml, "baseline")

        # Sanity: the baseline must reproduce what is committed in the YAML.
        drift = diff_fits(committed[pop]["region_distributions"], base_fits)
        print(f"  baseline vs committed populations.yaml: {len(drift)} param diffs "
              f"({'OK' if not drift else 'DRIFT!'})")

        for mode in ("literal", "forced"):
            fits, meta, counts = run_variant(site, pops_yaml, mode)
            rows = diff_fits(base_fits, fits)
            print(f"\n  --- {mode} ---")
            print(f"  users {base_meta['n_users']} → {meta['n_users']}"
                  f"   sessions {base_meta['n_sessions']} → {meta['n_sessions']}"
                  f"   cap_fallback {base_meta['capacity_fallback_rate']:.3f}"
                  f" → {meta['capacity_fallback_rate']:.3f}")
            moved = {k: (base_counts.get(k, 0), v) for k, v in counts.items()
                     if base_counts.get(k, 0) != v}
            if moved:
                print("  region user counts: " + ", ".join(
                    f"{k} {o}→{n}" for k, (o, n) in moved.items()))
            for key, old, new, pctv in rows:
                region, _, leaf = key.partition(".")
                csv_rows.append({
                    "site": site,
                    "population": pop,
                    "variant": mode,
                    "region": region,
                    "parameter": leaf,
                    "committed": old,
                    "with_anonymous": new,
                    "pct_change": pctv,
                    "n_users_baseline": base_meta["n_users"],
                    "n_users_variant": meta["n_users"],
                    "n_sessions_baseline": base_meta["n_sessions"],
                    "n_sessions_variant": meta["n_sessions"],
                })

            print(f"  changed parameters: {len(rows)}")
            for key, old, new, pct in rows[:args.top]:
                pct_s = f"{pct:+8.1f}%" if pct is not None else "     n/a"
                if isinstance(old, float):
                    print(f"    {key:52s} {old:10.4f} → {new:10.4f}  {pct_s}")
                else:
                    print(f"    {key:52s} {old} → {new}")
            if len(rows) > args.top:
                print(f"    ... {len(rows) - args.top} more")
        print()

    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(csv_rows).to_csv(args.csv, index=False)
        print(f"wrote {args.csv} ({len(csv_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
