"""Hard + soft invariant checker per validate_spec.md.

Hard invariants (A–H) and manifest checks (I) raise ValidationError.
Soft checks (S) emit warnings via the `warnings` field of ValidationReport.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .renderers.dr_events import _NOTIF_LEAD_HOURS

# Schema reference — column name → expected dtype family.
# Order is not enforced (per A2) but we validate columns are exactly these.
_SCHEMAS: dict[str, list[str]] = {
    "building_load": ["datetime", "power_flex_kw", "power_inflex_kw"],
    "cars": ["car_id", "capacity_kwh", "min_allowed_soc", "max_allowed_soc", "battery_class"],
    "users": ["car_id", "region", "phi", "kappa", "delta_km",
              "negotiation_type", "w1", "w2"],
    "chargers": ["charger_id", "directionality", "min_rate_kw", "max_rate_kw"],
    "grid_prices": ["datetime", "price_per_kwh", "type"],
    "dr_events": ["event_id", "start", "end", "magnitude_kw", "notified_at"],
    "sessions": ["session_id", "car_id", "building_id", "arrival", "departure",
                 "duration_sec", "arrival_soc", "required_soc_at_depart",
                 "previous_day_external_use_soc"],
}

_BATTERY_CLASSES = {"leaf_24", "bolt_40", "m3_75", "rivian_100"}
_DIRECTIONALITY = {"unidirectional", "bidirectional"}
_PRICE_TYPES = {"off_peak", "peak"}
_NEG_TYPES = {"type_i", "type_ii", "type_iii", "type_iv"}

# F4/F5 share tolerance — n=20 is statistically tight at 0.05 (see DESIGN_NOTES §6).
F_SHARE_TOL = 0.20


class ValidationError(Exception):
    pass


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, ok: bool, msg: str) -> None:
        if not ok:
            self.errors.append(msg)

    def add_warn(self, ok: bool, msg: str) -> None:
        if not ok:
            self.warnings.append(msg)

    @property
    def passed(self) -> bool:
        return not self.errors


def _load_csv(output_dir: Path, name: str) -> pd.DataFrame:
    path = output_dir / f"{name}.csv"
    if not path.exists():
        raise ValidationError(f"A1: missing {name}.csv")
    return pd.read_csv(path)


def _load_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "manifest.json"
    if not path.exists():
        raise ValidationError("I1: missing manifest.json")
    with path.open() as f:
        return json.load(f)


def validate(output_dir: Path, strict: bool = False) -> ValidationReport:
    """Run every invariant. Aggregates errors instead of bailing on first."""
    output_dir = Path(output_dir)
    rep = ValidationReport()

    # Section A: schema-level
    csvs: dict[str, pd.DataFrame] = {}
    for name, cols in _SCHEMAS.items():
        path = output_dir / f"{name}.csv"
        if not path.exists():
            rep.errors.append(f"A1: missing {name}.csv")
            continue
        df = pd.read_csv(path)
        csvs[name] = df
        actual = set(df.columns)
        expected = set(cols)
        if actual != expected:
            rep.errors.append(
                f"A2: {name}.csv columns mismatch. extra={actual - expected}, missing={expected - actual}"
            )
            continue  # downstream checks unsafe

    if rep.errors:
        return rep  # short-circuit further checks

    # A3 / A4 — dtype + null sanity, focusing on numeric / categorical fields.
    _check_a3_a4(rep, csvs)

    # A5 — categorical domains
    _check_a5(rep, csvs)

    # B — referential integrity
    _check_b(rep, csvs)

    # C — temporal consistency
    _check_c(rep, csvs)

    # D — physical / SoC
    _check_d(rep, csvs)

    # E — charger / capacity
    _check_e(rep, csvs)

    # G — behavioral axes (do before F because F4/F5 use users)
    _check_g(rep, csvs)

    # I — manifest
    manifest = _check_i(rep, output_dir)

    # F — CONSENT shares (depend on manifest knob_resolution)
    _check_f(rep, csvs, manifest)

    # H — tariff / DR
    _check_h(rep, csvs, manifest)

    # Soft checks
    _check_soft(rep, csvs, manifest)

    if strict and rep.warnings:
        rep.errors.extend(f"(strict) {w}" for w in rep.warnings)
        rep.warnings = []

    return rep


def _check_a3_a4(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    numeric_cols = {
        "building_load": ["power_flex_kw", "power_inflex_kw"],
        "cars": ["car_id", "capacity_kwh", "min_allowed_soc", "max_allowed_soc"],
        "users": ["car_id", "phi", "kappa", "delta_km", "w1", "w2"],
        "chargers": ["charger_id", "min_rate_kw", "max_rate_kw"],
        "grid_prices": ["price_per_kwh"],
        "dr_events": ["event_id", "magnitude_kw"],
        "sessions": ["session_id", "car_id", "duration_sec",
                     "arrival_soc", "required_soc_at_depart",
                     "previous_day_external_use_soc"],
    }
    for name, cols in numeric_cols.items():
        df = csvs[name]
        if len(df) == 0:
            continue  # Empty CSV — pandas reads object dtypes; cannot enforce numeric here.
        for c in cols:
            if df[c].isna().any():
                rep.errors.append(f"A4: {name}.{c} contains NaN")
            if not pd.api.types.is_numeric_dtype(df[c]):
                rep.errors.append(f"A3: {name}.{c} not numeric (got {df[c].dtype})")

    # Datetime columns must parse.
    for col in ("datetime",):
        for name in ("building_load", "grid_prices"):
            df = csvs[name]
            try:
                pd.to_datetime(df[col])
            except Exception as e:  # pragma: no cover
                rep.errors.append(f"A3: {name}.{col} not parseable as datetime: {e}")


def _check_a5(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    bad = set(csvs["cars"]["battery_class"]) - _BATTERY_CLASSES
    if bad:
        rep.errors.append(f"A5: cars.battery_class invalid {bad}")
    bad = set(csvs["chargers"]["directionality"]) - _DIRECTIONALITY
    if bad:
        rep.errors.append(f"A5: chargers.directionality invalid {bad}")
    bad = set(csvs["grid_prices"]["type"]) - _PRICE_TYPES
    if bad:
        rep.errors.append(f"A5: grid_prices.type invalid {bad}")
    bad = set(csvs["users"]["negotiation_type"]) - _NEG_TYPES
    if bad:
        rep.errors.append(f"A5: users.negotiation_type invalid {bad}")
    # users.region is checked against scenario library entry — covered in F5
    # via manifest's knob_resolution, kept loose here to avoid duplication.


def _check_b(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    cars = set(csvs["cars"]["car_id"])
    users = set(csvs["users"]["car_id"])
    rep.add(cars == users, "B1: users.car_id != cars.car_id")
    sess_cars = set(csvs["sessions"]["car_id"])
    rep.add(sess_cars <= cars, f"B2: sessions.car_id not subset of cars (extra={sess_cars - cars})")
    rep.add(csvs["cars"]["car_id"].is_unique, "B3: cars.car_id not unique")
    rep.add(csvs["users"]["car_id"].is_unique, "B4: users.car_id not unique")
    rep.add(csvs["sessions"]["session_id"].is_unique, "B5: sessions.session_id not unique")
    rep.add(csvs["chargers"]["charger_id"].is_unique, "B6: chargers.charger_id not unique")
    if len(csvs["dr_events"]) > 0:
        rep.add(csvs["dr_events"]["event_id"].is_unique, "B7: dr_events.event_id not unique")


def _check_c(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    bl_dt = pd.to_datetime(csvs["building_load"]["datetime"])
    gp_dt = pd.to_datetime(csvs["grid_prices"]["datetime"])
    rep.add(bl_dt.is_monotonic_increasing, "C1: building_load.datetime not monotone")
    rep.add(gp_dt.is_monotonic_increasing, "C2: grid_prices.datetime not monotone")
    if len(bl_dt) > 1:
        rep.add(
            (bl_dt.diff().dropna() == pd.Timedelta(minutes=15)).all(),
            "C1: building_load.datetime not 15-min spaced",
        )
    if len(gp_dt) > 1:
        rep.add(
            (gp_dt.diff().dropna() == pd.Timedelta(minutes=15)).all(),
            "C2: grid_prices.datetime not 15-min spaced",
        )
    rep.add(set(bl_dt) == set(gp_dt), "C3: building_load and grid_prices datetimes differ")

    sess = csvs["sessions"]
    if len(sess) > 0:
        arr = pd.to_datetime(sess["arrival"])
        dep = pd.to_datetime(sess["departure"])
        rep.add((arr < dep).all(), "C4: arrival >= departure")
        in_range = (arr >= bl_dt.min()) & (arr <= bl_dt.max())
        rep.add(in_range.all(), "C5: session arrival outside building_load range")
        secs = (dep - arr).dt.total_seconds().astype(int)
        rep.add((secs == sess["duration_sec"].astype(int)).all(),
                "C6: duration_sec mismatch")
        # C7: per-car non-overlap
        for car_id, group in sess.groupby("car_id"):
            g = group.sort_values("arrival")
            ga = pd.to_datetime(g["arrival"]).to_numpy()
            gd = pd.to_datetime(g["departure"]).to_numpy()
            for i in range(len(ga) - 1):
                if gd[i] > ga[i + 1]:
                    rep.errors.append(
                        f"C7: car {car_id} overlap session {i}->{i+1} ({gd[i]} > {ga[i+1]})"
                    )
                    break

    dr = csvs["dr_events"]
    if len(dr) > 0:
        s = pd.to_datetime(dr["start"])
        e = pd.to_datetime(dr["end"])
        n = pd.to_datetime(dr["notified_at"])
        rep.add((s < e).all(), "C8: dr start >= end")
        rep.add((n <= s).all(), "C9: dr notified_at > start")
        rep.add(((s >= bl_dt.min()) & (e <= bl_dt.max() + pd.Timedelta(minutes=15))).all(),
                "C10: dr event outside building_load range")
        # C11: notification lead matches program (need program from manifest)
        # Done in _check_h.


def _check_d(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    cars = csvs["cars"]
    rep.add((cars["min_allowed_soc"] >= 0).all() and
            (cars["max_allowed_soc"] <= 100).all() and
            (cars["min_allowed_soc"] < cars["max_allowed_soc"]).all(),
            "D1: car SoC bounds invalid")
    rep.add((cars["capacity_kwh"] > 0).all(), "D2: car capacity non-positive")

    sess = csvs["sessions"]
    if len(sess) == 0:
        return
    # Build per-car_id dicts. First occurrence wins on duplicates;
    # B3 reports the duplicate separately.
    car_min: dict[int, float] = {}
    car_max: dict[int, float] = {}
    car_cap: dict[int, float] = {}
    for _, crow in cars.iterrows():
        cid_k = int(crow["car_id"])
        if cid_k in car_min:
            continue
        car_min[cid_k] = float(crow["min_allowed_soc"])
        car_max[cid_k] = float(crow["max_allowed_soc"])
        car_cap[cid_k] = float(crow["capacity_kwh"])

    for col, label in (("arrival_soc", "D3"), ("required_soc_at_depart", "D4")):
        for _, row in sess.iterrows():
            cid = int(row["car_id"])
            if cid not in car_min:
                continue
            mn = car_min[cid]
            mx = car_max[cid]
            v = float(row[col])
            if not (mn <= v <= mx):
                rep.errors.append(f"{label}: car {cid} session {row['session_id']} {col}={v} outside [{mn}, {mx}]")
                break

    # D5: SoC reachability — only when required > arrival
    chargers = csvs["chargers"]
    max_rate = float(chargers["max_rate_kw"].max())
    for _, row in sess.iterrows():
        cid = int(row["car_id"])
        if cid not in car_cap:
            continue
        cap = car_cap[cid]
        a = float(row["arrival_soc"])
        r = float(row["required_soc_at_depart"])
        if r <= a:
            continue
        dur_hr = float(row["duration_sec"]) / 3600.0
        need = (r - a) / 100.0 * cap
        avail = max_rate * dur_hr
        if need > avail * 1.05:
            rep.errors.append(
                f"D5: car {cid} session {row['session_id']} unreachable "
                f"(need={need:.2f} kWh, avail={avail:.2f} kWh)"
            )
            break


def _check_e(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    chargers = csvs["chargers"]
    rep.add(((chargers["min_rate_kw"] <= 0) & (chargers["max_rate_kw"] >= 0)).all(),
            "E1: charger rate sign invalid")
    uni = chargers[chargers["directionality"] == "unidirectional"]
    rep.add((uni["min_rate_kw"] == 0).all(), "E2: unidirectional with min_rate != 0")
    bi = chargers[chargers["directionality"] == "bidirectional"]
    rep.add((bi["min_rate_kw"] < 0).all(), "E3: bidirectional with min_rate >= 0")
    if len(bi) > 0:
        sym = (bi["min_rate_kw"].abs() - bi["max_rate_kw"]).abs() <= bi["max_rate_kw"] * 0.01
        rep.add(sym.all(), "E4: bidirectional charger not symmetric")

    # E5: concurrent active sessions ≤ len(chargers)
    sess = csvs["sessions"]
    bl_dt = pd.to_datetime(csvs["building_load"]["datetime"])
    if len(sess) > 0 and len(bl_dt) > 0:
        arrs = pd.to_datetime(sess["arrival"]).to_numpy()
        deps = pd.to_datetime(sess["departure"]).to_numpy()
        max_active = 0
        n_chargers = len(chargers)
        # Sample subsets of timestamps for speed: full 15-min grid is fine here
        for t in bl_dt.to_numpy():
            active = int(((arrs <= t) & (deps > t)).sum())
            if active > max_active:
                max_active = active
            if active > n_chargers:
                rep.errors.append(f"E5: {active} active sessions > {n_chargers} chargers at {t}")
                return
        if max_active > 0.9 * n_chargers:
            rep.warnings.append(f"E5 (warn): peak utilization {max_active}/{n_chargers}")


def _check_g(rep: ValidationReport, csvs: dict[str, pd.DataFrame]) -> None:
    users = csvs["users"]
    rep.add(((users["phi"] >= 0) & (users["phi"] <= 1)).all(), "G1: phi outside [0,1]")
    rep.add(((users["kappa"] >= 0) & (users["kappa"] <= 1)).all(), "G2: kappa outside [0,1]")
    rep.add((users["delta_km"] >= 0).all(), "G3: delta_km negative")


def _check_i(rep: ValidationReport, output_dir: Path) -> dict[str, Any]:
    path = output_dir / "manifest.json"
    if not path.exists():
        rep.errors.append("I1: manifest.json missing")
        return {}
    try:
        with path.open() as f:
            manifest = json.load(f)
    except Exception as e:
        rep.errors.append(f"I1: manifest.json invalid JSON: {e}")
        return {}
    required = {"scenario_id", "seed", "knob_overrides", "knob_resolution",
                "generator_git_sha", "csv_row_counts", "csv_sha256", "noise_profile"}
    missing = required - set(manifest.keys())
    rep.add(not missing, f"I1: manifest missing keys {missing}")
    # I2 row counts
    for name, cnt in manifest.get("csv_row_counts", {}).items():
        p = output_dir / f"{name}.csv"
        if p.exists():
            with p.open() as f:
                actual = max(0, sum(1 for _ in f) - 1)
            rep.add(actual == int(cnt), f"I2: {name}.csv row count {actual} != manifest {cnt}")
    # I3 sha256
    for name, expected in manifest.get("csv_sha256", {}).items():
        p = output_dir / f"{name}.csv"
        if p.exists():
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
            rep.add(h.hexdigest() == expected, f"I3: {name}.csv sha256 mismatch")
    # I4 every knob present in resolution with valid source
    res = manifest.get("knob_resolution", {})
    knob_path = Path(__file__).parent.parent.parent / "configs" / "knobs.yaml"
    from .knob_loader import all_knob_paths, load_knob_registry
    if knob_path.exists():
        registry = load_knob_registry(knob_path)
        for path_ in all_knob_paths(registry):
            if path_ not in res:
                rep.errors.append(f"I4: knob {path_} missing from manifest.knob_resolution")
                continue
            src = res[path_].get("source", "")
            if src not in ("explicit", "default") and not src.startswith("descriptor:"):
                rep.errors.append(f"I4: {path_} has invalid source {src!r}")
    return manifest


def _check_f(rep: ValidationReport, csvs: dict[str, pd.DataFrame],
             manifest: dict[str, Any]) -> None:
    users = csvs["users"]
    rep.add((users["w1"] >= 0).all() and (users["w2"] >= 0).all(),
            "F1: CONSENT weights negative")
    rep.add(users[["w1", "w2"]].notna().all().all() and
            (users[["w1", "w2"]].abs() != float("inf")).all().all(),
            "F2: CONSENT weights inf/NaN")

    # F3: per-cluster mean within 2σ — loose: uses CONSENT_CLUSTERS / w_multiplier
    res = manifest.get("knob_resolution", {})
    if not res:
        return
    alpha_w1, alpha_w2 = res.get("user_behavior.w_multiplier", {"value": [1.0, 1.0]})["value"]
    from .samplers.per_entity import CONSENT_CLUSTERS
    for ntype, params in CONSENT_CLUSTERS.items():
        sub = users[users["negotiation_type"] == ntype]
        if len(sub) == 0:
            continue
        for k, mean_key, std_key in (("w1", "w1_mean", "w1_std"),
                                      ("w2", "w2_mean", "w2_std")):
            expected_mean = params[mean_key] * (alpha_w1 if k == "w1" else alpha_w2)
            expected_std = max(params[std_key] * (alpha_w1 if k == "w1" else alpha_w2), 1e-6)
            actual = float(sub[k].mean())
            # 2σ over n samples is a loose guardrail; use 3 * std/sqrt(n) + slack
            tol = 3.0 * expected_std / max(len(sub) ** 0.5, 1) + 0.05
            if abs(actual - expected_mean) > tol:
                rep.errors.append(
                    f"F3: cluster {ntype} {k} mean {actual:.4f} far from {expected_mean:.4f} (tol {tol:.4f})"
                )

    # F4: negotiation_type shares
    neg_mix = res.get("user_behavior.negotiation_mix", {}).get("value")
    if neg_mix:
        from .samplers.per_entity import NEG_TYPES
        n = len(users)
        for nt, expected in zip(NEG_TYPES, neg_mix, strict=True):
            actual = float((users["negotiation_type"] == nt).sum()) / n
            if abs(actual - expected) > F_SHARE_TOL:
                rep.errors.append(
                    f"F4: negotiation_type {nt} share {actual:.3f} vs {expected:.3f} (tol {F_SHARE_TOL})"
                )

    # F5: region shares
    axes = res.get("user_behavior.axes_distribution", {}).get("value", [])
    if axes:
        n = len(users)
        for r in axes:
            actual = float((users["region"] == r["name"]).sum()) / n
            expected = float(r["weight"])
            if abs(actual - expected) > F_SHARE_TOL:
                rep.errors.append(
                    f"F5: region {r['name']} share {actual:.3f} vs {expected:.3f} (tol {F_SHARE_TOL})"
                )

    # G4: (phi, kappa, delta) within declared region bounds
    if axes:
        region_lookup = {r["name"]: r for r in axes}
        for _, row in users.iterrows():
            region = region_lookup.get(row["region"])
            if region is None:
                continue
            f_lo, f_hi = region["freq"]
            k_lo, k_hi = region["consist"]
            d_lo, d_hi = region["dist_km"]
            ok = (f_lo <= row["phi"] <= f_hi and
                  k_lo <= row["kappa"] <= k_hi and
                  d_lo <= row["delta_km"] <= d_hi)
            if not ok:
                rep.errors.append(
                    f"G4: car {row['car_id']} (phi={row['phi']:.3f}, kappa={row['kappa']:.3f}, "
                    f"delta={row['delta_km']:.1f}) outside region {row['region']} bounds"
                )
                break


def _check_h(rep: ValidationReport, csvs: dict[str, pd.DataFrame],
             manifest: dict[str, Any]) -> None:
    res = manifest.get("knob_resolution", {})
    if not res:
        return
    tariff = res.get("utility_rate.tariff_type", {}).get("value")
    off_p = float(res.get("utility_rate.energy_price_offpeak", {}).get("value", 0.0))
    peak_p = float(res.get("utility_rate.energy_price_peak", {}).get("value", 0.0))
    pw = res.get("utility_rate.peak_window", {}).get("value", [0, 0])
    program = res.get("utility_rate.dr_program", {}).get("value", "none")

    gp = csvs["grid_prices"]
    if tariff == "flat":
        rep.add((gp["type"] == "off_peak").all(), "H1: flat tariff with peak rows")
        rep.add(gp["price_per_kwh"].nunique() == 1, "H1: flat tariff with varied prices")
    else:
        # Allow noise jitter — use approximate equality if noise profile is non-clean.
        noise_profile = manifest.get("noise_profile", "clean")
        approx = noise_profile != "clean"
        peak_rows = gp[gp["type"] == "peak"]
        off_rows = gp[gp["type"] == "off_peak"]
        if approx:
            rep.add(((peak_rows["price_per_kwh"] - peak_p).abs() <= 0.5).all() if len(peak_rows) else True,
                    "H2: peak prices off")
            rep.add(((off_rows["price_per_kwh"] - off_p).abs() <= 0.5).all() if len(off_rows) else True,
                    "H2: offpeak prices off")
        else:
            rep.add((peak_rows["price_per_kwh"] == peak_p).all() if len(peak_rows) else True,
                    "H2: peak prices != configured")
            rep.add((off_rows["price_per_kwh"] == off_p).all() if len(off_rows) else True,
                    "H2: offpeak prices != configured")
        # Peak window check — every row in peak hours has type=peak
        for _, row in gp.iterrows():
            ts = pd.to_datetime(row["datetime"])
            in_peak = (pw[0] <= ts.hour < pw[1]) if pw[0] <= pw[1] else (ts.hour >= pw[0] or ts.hour < pw[1])
            expected = "peak" if in_peak else "off_peak"
            if row["type"] != expected:
                rep.errors.append(f"H2: row {row['datetime']} type {row['type']} != expected {expected}")
                break

    dr = csvs["dr_events"]
    if program == "none":
        rep.add(len(dr) == 0, f"H4: dr_program=none but {len(dr)} events")
    else:
        # H3: best-effort — sim window may not cover season
        if len(dr) == 0:
            rep.warnings.append(f"H3 (warn): dr_program={program} but no events (sim window may exclude season)")
        # H5: counts per program type — soft, depends on stub
        # H6: magnitudes within range
        mag_range = res.get("utility_rate.dr_magnitude_kw_range", {}).get("value", [0.0, 0.0])
        if len(dr) > 0:
            rep.add(((dr["magnitude_kw"] >= mag_range[0]) & (dr["magnitude_kw"] <= mag_range[1])).all(),
                    f"H6: dr_events.magnitude_kw outside {mag_range}")

    # C11: notification lead per program
    if program in _NOTIF_LEAD_HOURS and len(dr) > 0:
        expected_lead = timedelta(hours=_NOTIF_LEAD_HOURS[program])
        starts = pd.to_datetime(dr["start"])
        notifs = pd.to_datetime(dr["notified_at"])
        leads = starts - notifs
        # tolerance 1 minute
        tol = timedelta(minutes=1)
        bad = (leads - expected_lead).abs() > tol
        if bad.any():
            rep.errors.append(f"C11: dr notification lead deviates from program {program}")


def _check_soft(rep: ValidationReport, csvs: dict[str, pd.DataFrame],
                manifest: dict[str, Any]) -> None:
    # S3: energy balance — sessions vs charger throughput * duration
    sess = csvs["sessions"]
    chargers = csvs["chargers"]
    cars_df = csvs["cars"]
    cap_lookup: dict[int, float] = {}
    for _, crow in cars_df.iterrows():
        cid = int(crow["car_id"])
        cap_lookup.setdefault(cid, float(crow["capacity_kwh"]))
    if len(sess) > 0 and len(chargers) > 0:
        max_rate = float(chargers["max_rate_kw"].max())
        total_avail_kwh = float((max_rate * (sess["duration_sec"] / 3600.0)).sum()) * len(chargers)
        delivered = 0.0
        for _, row in sess.iterrows():
            cap = cap_lookup.get(int(row["car_id"]))
            if cap is None:
                continue
            d = max(0.0, float(row["required_soc_at_depart"]) - float(row["arrival_soc"]))
            delivered += d / 100.0 * cap
        if delivered > total_avail_kwh:
            rep.warnings.append(
                f"S3: delivered {delivered:.1f} kWh > available {total_avail_kwh:.1f} kWh"
            )


def emit_warnings(rep: ValidationReport) -> None:
    for w in rep.warnings:
        warnings.warn(w, stacklevel=2)
