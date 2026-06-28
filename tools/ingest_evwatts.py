#!/usr/bin/env python
"""Ingest the real EV WATTS public dataset into the internal calibration schema.

The EV WATTS public release (livewire.energy.gov) is OCPI-relational — a large
``session`` table joined to an ``evse`` table on ``evse_id``. This tool joins
them, filters to a venue cohort + drops error-flagged sessions, and writes the
flat internal schema that ``calibration.sources.evwatts`` expects:

    start_time_utc, end_time_utc, energy_kwh, evse_id, venue_type, rated_power_kw

Then calibrate against it, e.g. for the workplace cohort:

    uv run python tools/ingest_evwatts.py \\
        --raw-dir <dir with evwatts.public.session.csv + evwatts.public.evse.csv> \\
        --release-tag public_<YYYY> --venue "Business Office" \\
        --cache-dir data/calibration/evwatts_cache
    uv run v2b-syndata calibrate --population evwatts_workplace_public \\
        --cache-dir data/calibration/evwatts_cache \\
        --source-arg evwatts:release_tag=public_<YYYY> \\
        --source-arg evwatts:venue_filter=workplace_public

EV WATTS timestamps are naive LOCAL clock time (the dataset flags EVSEs that
don't observe DST), so they are passed through unchanged — arrival_hour is the
local charging hour. There is no driver ID upstream, so the source uses a
port-proxy user (``evwatts:port:<evse_id>``).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

# Error-flag bits (see the dataset dictionary) that corrupt arrival/dwell/energy.
# Kept benign: telematics home-estimate (4096), DST (16384), trip overlaps, etc.
BAD_FLAG_BITS = (
    1        # unrealistic kW
    | 16     # duplicate row
    | 128    # 0 kWh transferred
    | 256    # < 0.3 kWh
    | 8192   # energy kWh is null
    | 32768  # end_datetime missing
    | 65536  # negative charge duration
)


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest EV WATTS public → internal calibration CSV")
    p.add_argument("--raw-dir", required=True,
                   help="dir containing evwatts.public.session.csv + evwatts.public.evse.csv")
    p.add_argument("--release-tag", required=True, help="tag → cache file evwatts_<tag>.csv")
    p.add_argument("--venue", action="append", default=None,
                   help="evse venue(s) to keep (repeatable). Default: 'Business Office' (workplace).")
    p.add_argument("--cache-dir", default="data/calibration/evwatts_cache")
    args = p.parse_args()

    raw = Path(args.raw_dir)
    venues = args.venue or ["Business Office"]
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    evse = pd.read_csv(raw / "evwatts.public.evse.csv")
    evse.columns = [c.strip().lstrip("﻿") for c in evse.columns]
    venue_by_evse = dict(zip(evse["evse_id"], evse["venue"], strict=False))

    s = pd.read_csv(
        raw / "evwatts.public.session.csv",
        usecols=["evse_id", "start_datetime", "end_datetime", "energy_kwh", "flag_id"],
    )
    n_total = len(s)
    s["venue"] = s["evse_id"].map(venue_by_evse)
    s = s[s["venue"].isin(venues)]
    n_venue = len(s)
    flags = s["flag_id"].fillna(0).astype("int64")
    s = s[(flags & BAD_FLAG_BITS) == 0]
    n_clean = len(s)

    out = pd.DataFrame({
        "start_time_utc": s["start_datetime"].to_numpy(),
        "end_time_utc": s["end_datetime"].to_numpy(),
        "energy_kwh": s["energy_kwh"].to_numpy(),
        "evse_id": s["evse_id"].to_numpy(),
        "venue_type": s["venue"].to_numpy(),
        "rated_power_kw": "",  # connector power not joined; unused for the venue cohort
    })
    dest = cache_dir / f"evwatts_{args.release_tag}.csv"
    out.to_csv(dest, index=False, lineterminator="\n")

    print(f"venues kept: {venues}")
    print(f"sessions: {n_total:,} total → {n_venue:,} in venue → {n_clean:,} after flag filter")
    print(f"unique EVSEs (port-proxy users): {out['evse_id'].nunique():,}")
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
