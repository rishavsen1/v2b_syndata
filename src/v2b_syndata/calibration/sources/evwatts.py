"""EV WATTS calibration source. Port-as-proxy-user (no driver-stable ID upstream)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd

from ..evwatts_fetcher import fetch_all_sessions
from ..feature_extractor import SessionFeatures

SCHEMA_VERSION = "v1"

# TODO confirm column names against real livewire release.
COL_START = "start_time_utc"
COL_END = "end_time_utc"
COL_ENERGY_KWH = "energy_kwh"
COL_EVSE_ID = "evse_id"
COL_VENUE = "venue_type"
COL_POWER_KW = "rated_power_kw"

_RESIDENTIAL_VENUES = {"residential", "home"}


class EvWattsSource:
    per_user_csv_filename = "evwatts_per_user.csv"

    def fetch_sessions(self, config: dict[str, Any]) -> list[SessionFeatures]:
        release_tag = str(config["release_tag"])
        cache_dir = Path(config["cache_dir"])
        bulk_url = config.get("bulk_url")
        venue_filter = config.get("venue_filter")
        min_kw = config.get("min_power_kw")
        max_kw = config.get("max_power_kw")

        rows = fetch_all_sessions(release_tag, cache_dir, bulk_url=bulk_url)
        out: list[SessionFeatures] = []
        for r in rows:
            sf = _extract_session_evwatts(r, venue_filter, min_kw, max_kw)
            if sf is not None:
                out.append(sf)
        return out

    def dataset_name(self) -> str:
        return "EV WATTS (DOE/EPRI)"

    def provenance_prefix(self, config: dict[str, Any]) -> str:
        release_tag = str(config["release_tag"])
        today_compact = dt.date.today().isoformat().replace("-", "")
        return f"calibration:evwatts_{release_tag}_{today_compact}"

    def extra_metadata(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id_strategy": "port_proxy",
            "release_tag": str(config["release_tag"]),
            "venue_filter": config.get("venue_filter"),
            "schema_version": SCHEMA_VERSION,
        }

    def token_help_message(self) -> str:
        return (
            "verify EVWATTS_BULK_URL points to a livewire.energy.gov bulk "
            "release or pre-populate the cache directory"
        )

    def parse_args(self, raw: list[str]) -> dict[str, Any]:
        """Parse --source-arg key=value pairs scoped to evwatts."""
        out: dict[str, Any] = {}
        for kv in raw:
            if "=" not in kv:
                raise ValueError(f"--source-arg must be key=value: {kv!r}")
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "release_tag":
                out["release_tag"] = v
            elif k == "venue_filter":
                out["venue_filter"] = v
            elif k == "min_power_kw":
                out["min_power_kw"] = float(v)
            elif k == "max_power_kw":
                out["max_power_kw"] = float(v)
            elif k == "bulk_url":
                out["bulk_url"] = v
            else:
                raise ValueError(f"EvWattsSource: unknown source-arg key {k!r}")
        return out


def _venue_allowed(venue: Any, venue_filter: str | None) -> bool:
    if venue_filter is None:
        return True
    v = str(venue).strip().lower() if venue is not None else ""
    if venue_filter == "workplace_public":
        # Exclude residential; allow workplace + public.
        return v not in _RESIDENTIAL_VENUES
    if venue_filter == "dcfc_public":
        # Power filter does the real work; venue must not be residential.
        return v not in _RESIDENTIAL_VENUES
    return True


def _extract_session_evwatts(
    row: dict[str, Any],
    venue_filter: str | None,
    min_kw: float | None,
    max_kw: float | None,
) -> SessionFeatures | None:
    venue = row.get(COL_VENUE)
    if not _venue_allowed(venue, venue_filter):
        return None

    power = _safe_float(row.get(COL_POWER_KW))
    if min_kw is not None and (power is None or power < min_kw):
        return None
    if max_kw is not None and (power is None or power > max_kw):
        return None

    try:
        start = pd.to_datetime(row[COL_START], utc=True, errors="raise")
        end = pd.to_datetime(row[COL_END], utc=True, errors="raise")
    except (KeyError, ValueError, TypeError):
        return None
    if pd.isna(start) or pd.isna(end):
        return None
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")

    dwell = (end - start).total_seconds() / 3600.0
    if dwell <= 0 or dwell > 168.0:
        return None

    arr_hour = start.hour + start.minute / 60.0 + start.second / 3600.0
    kwh_del = _safe_float(row.get(COL_ENERGY_KWH)) or 0.0

    evse_id = row.get(COL_EVSE_ID)
    if evse_id is None or (isinstance(evse_id, float) and pd.isna(evse_id)):
        return None
    user_id = f"evwatts:port:{evse_id}"

    site = str(venue) if venue not in (None, "") and not (isinstance(venue, float) and pd.isna(venue)) else "evwatts"

    return SessionFeatures(
        user_id=user_id,
        site=site,
        arrival_time=start,
        arrival_hour=float(arr_hour),
        dwell_hours=float(dwell),
        kwh_delivered=float(kwh_del),
        miles_requested=None,
        wh_per_mile=None,
        kwh_requested=None,
        minutes_available=None,
    )


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if pd.isna(v):
            return None
        return v
    except (TypeError, ValueError):
        return None
