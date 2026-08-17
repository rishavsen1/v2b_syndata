#!/usr/bin/env python3
"""Flatten a cached ACN-Data sessions JSON into one CSV row per session.

The cache files under ``data/calibration/acn_cache/`` are the raw ACN-Data REST
payload (a JSON list of session objects). Every session has 12 scalar fields
plus a nested ``userInputs`` list, so a faithful CSV needs two decisions:

  * ``userInputs`` is a **list of revisions** — a driver can update their
    requested energy / departure while plugged in. Lengths observed in the
    Caltech cache: 0 (2,233 sessions), 1 (12,169), and 2–25 for the rest.
    ``--user-input first`` (default) flattens ``userInputs[0]``, matching what
    ``calibration/feature_extractor.extract_session`` reads, so the CSV lines up
    with what the generator was calibrated on. ``last`` takes the final revision.
    For 1,018 Caltech sessions the two disagree on at least one numeric field;
    those rows carry ``userInputs.revisionsDiffer = True``.
  * Sessions with **no** ``userInputs`` are exactly the sessions with a null
    ``userID`` (anonymous plug-ins). They are kept, with empty ``userInputs.*``
    columns, unless ``--require-userid`` is passed.

Field names are preserved verbatim from the API (camelCase, ``userInputs.``
prefix for the nested block) so columns cross-reference the ACN-Data docs and
the repo's own accessors without a translation table. Timestamps stay as the
original RFC-1123 GMT strings; pass ``--derived`` to additionally emit the
site-local arrival hour and dwell hours the fitter actually consumes.

Examples
--------
  uv run python tools/acn_json_to_csv.py \
      data/calibration/acn_cache/caltech_2019_2021.json

  # all three sites, with the derived modeling columns
  uv run python tools/acn_json_to_csv.py \
      data/calibration/acn_cache/*.json --derived --out-dir data/calibration/acn_csv/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

TOP_FIELDS = [
    "sessionID", "_id", "siteID", "stationID", "spaceID", "clusterID", "userID",
    "connectionTime", "disconnectTime", "doneChargingTime",
    "kWhDelivered", "timezone",
]
UI_FIELDS = [
    "userID", "kWhRequested", "milesRequested", "WhPerMile",
    "minutesAvailable", "requestedDeparture", "paymentRequired", "modifiedAt",
]
NUMERIC_UI = ("kWhRequested", "milesRequested", "WhPerMile", "minutesAvailable")
# Integral in the source payload; without a nullable-int cast the NaNs from
# anonymous sessions would promote these to float and write "489.0" for user 489.
INTEGRAL_UI = ("userID", "milesRequested", "WhPerMile", "minutesAvailable")
# Zero-padded identifier strings ("000000489", "0002") — faithful in the file,
# but a naive read_csv infers them as numbers and drops the padding.
ID_COLUMNS = ("sessionID", "_id", "siteID", "stationID", "spaceID", "clusterID",
              "userID")

# Matches calibration/feature_extractor.py: ACN timestamps are true UTC despite
# the "GMT" suffix, and all three sites are in California.
ACN_TZ = "America/Los_Angeles"
TS_FORMAT = "%a, %d %b %Y %H:%M:%S GMT"


def _as_list(ui: Any) -> list[dict[str, Any]]:
    if isinstance(ui, list):
        return [e for e in ui if isinstance(e, dict)]
    if isinstance(ui, dict):
        return [ui]
    return []


def flatten(sessions: list[dict[str, Any]], which: str = "first") -> pd.DataFrame:
    rows = []
    for s in sessions:
        row = {k: s.get(k) for k in TOP_FIELDS}
        revs = _as_list(s.get("userInputs"))
        row["userInputs.count"] = len(revs)
        if not revs:
            pick: dict[str, Any] = {}
        else:
            pick = revs[0] if which == "first" else revs[-1]
        for k in UI_FIELDS:
            row[f"userInputs.{k}"] = pick.get(k)
        row["userInputs.revisionsDiffer"] = bool(
            len(revs) > 1
            and any(revs[0].get(k) != revs[-1].get(k) for k in NUMERIC_UI)
        )
        rows.append(row)
    df = pd.DataFrame(rows)
    for k in INTEGRAL_UI:
        df[f"userInputs.{k}"] = df[f"userInputs.{k}"].astype("Int64")
    return df


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Append the site-local timing columns the distribution fitter consumes."""
    conn = pd.to_datetime(df["connectionTime"], format=TS_FORMAT, utc=True)
    disc = pd.to_datetime(df["disconnectTime"], format=TS_FORMAT, utc=True)
    conn_local = conn.dt.tz_convert(ACN_TZ).dt.tz_localize(None)
    disc_local = disc.dt.tz_convert(ACN_TZ).dt.tz_localize(None)
    df["derived.arrivalLocal"] = conn_local
    df["derived.departureLocal"] = disc_local
    df["derived.arrivalHour"] = (
        conn_local.dt.hour + conn_local.dt.minute / 60.0 + conn_local.dt.second / 3600.0
    )
    # Local clock hour of unplug. Wraps past midnight for overnight stays, so it
    # is NOT arrivalHour + dwellHours; use derived.departureLocal for ordering.
    df["derived.departureHour"] = (
        disc_local.dt.hour + disc_local.dt.minute / 60.0 + disc_local.dt.second / 3600.0
    )
    # True elapsed time, measured in UTC.
    df["derived.dwellHours"] = (disc - conn).dt.total_seconds() / 3600.0
    df["derived.isWeekday"] = conn_local.dt.dayofweek < 5
    # Sessions straddling a DST transition, where wall-clock elapsed time differs
    # from true elapsed time. `feature_extractor.extract_session` subtracts
    # tz-naive LOCAL timestamps, so for these rows its dwell_hours is off by the
    # DST offset (+1 h across spring-forward) relative to the physical duration
    # in `derived.dwellHours`. 3 of 15,508 extractable Caltech sessions.
    naive_elapsed = (disc_local - conn_local).dt.total_seconds() / 3600.0
    df["derived.crossesDstChange"] = (
        (naive_elapsed - df["derived.dwellHours"]).abs() > 1e-9
    )
    # The fitter's session-level inclusion window (0.5 h .. 168 h).
    df["derived.passesDwellFilter"] = (
        (df["derived.dwellHours"] >= 0.5) & (df["derived.dwellHours"] <= 168.0)
    )
    return df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_paths", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: alongside each input JSON")
    ap.add_argument("--user-input", choices=("first", "last"), default="first",
                    help="which userInputs revision to flatten (default: first, "
                         "matching the calibration pipeline)")
    ap.add_argument("--require-userid", action="store_true",
                    help="drop anonymous sessions (userID is null)")
    ap.add_argument("--derived", action="store_true",
                    help="also emit site-local arrival hour / dwell hours")
    args = ap.parse_args(argv)

    for jp in args.json_paths:
        sessions = json.loads(jp.read_text())
        df = flatten(sessions, which=args.user_input)
        n_raw = len(df)
        if args.require_userid:
            df = df[df["userID"].notna()].reset_index(drop=True)
        if args.derived:
            df = add_derived(df)

        out_dir = args.out_dir or jp.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{jp.stem}.csv"
        df.to_csv(out, index=False)

        anon = int(df["userID"].isna().sum())
        multi = int(df["userInputs.count"].gt(1).sum())
        differ = int(df["userInputs.revisionsDiffer"].sum())
        print(f"{out}")
        print(f"  {len(df):,} rows ({n_raw:,} in JSON), {len(df.columns)} columns")
        print(f"  anonymous (null userID): {anon:,} | "
              f"multi-revision userInputs: {multi:,} (differing: {differ:,})")
        if args.derived:
            keep = int(df["derived.passesDwellFilter"].sum())
            dst = int(df["derived.crossesDstChange"].sum())
            print(f"  pass the 0.5-168 h dwell filter: {keep:,} | "
                  f"cross a DST change: {dst:,}")
        print("  read with (keeps zero-padded IDs like '0002'/'000000489' intact):")
        print(f"    pd.read_csv({out.name!r}, dtype={{{', '.join(repr(c) + ': str' for c in ID_COLUMNS)}}})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
