"""INL EV Project Phase 1 calibration source.

Legacy 24 kWh Leaf/Volt fleet (2011–2013). Do not mix with modern-fleet
scenarios — battery capacity assumptions diverge.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd

from ..feature_extractor import MIN_DWELL_HOURS, SessionFeatures
from ..inl_fetcher import fetch_all_sessions

SCHEMA_VERSION = "v1"

# TODO confirm column names against real avt.inl.gov Phase 1 release.
COL_VEHICLE_ID = "vehicle_id"
COL_START = "start_time"
COL_END = "end_time"
COL_ENERGY_KWH = "energy_kwh"
COL_EVSE_ID = "evse_id"
COL_VENUE = "venue"
COL_POWER_KW = "evse_power_kw"

_RESIDENTIAL_VENUES = {"residential", "home"}
_WORKPLACE_VENUES = {"workplace", "office", "work"}


class InlSource:
    per_user_csv_filename = "inl_per_user.csv"

    def __init__(self) -> None:
        # Counts per-session user_id strategies observed during fetch. Phase 1
        # release exposed pseudonymized Vehicle IDs, so the primary strategy
        # is vin_proxy; the port_proxy branch is a row-level fallback for
        # rows missing vehicle_id. Source-level metadata flips to port_proxy
        # only when port-proxy dominates the cohort.
        self._n_vin = 0
        self._n_port = 0

    def fetch_sessions(self, config: dict[str, Any]) -> list[SessionFeatures]:
        archive_tag = str(config["archive_tag"])
        cache_dir = Path(config["cache_dir"])
        bulk_url = config.get("bulk_url")
        venue_filter = config.get("venue_filter", "residential")
        min_kw = config.get("min_power_kw")
        max_kw = config.get("max_power_kw")

        rows = fetch_all_sessions(archive_tag, cache_dir, bulk_url=bulk_url)
        out: list[SessionFeatures] = []
        for r in rows:
            sf = _extract_session_inl(r, venue_filter, min_kw, max_kw)
            if sf is not None:
                if sf.user_id.startswith("inl:port:"):
                    self._n_port += 1
                else:
                    self._n_vin += 1
                out.append(sf)
        return out

    def dataset_name(self) -> str:
        return "INL EV Project Phase 1"

    def provenance_prefix(self, config: dict[str, Any]) -> str:
        archive_tag = str(config["archive_tag"])
        today_compact = dt.date.today().isoformat().replace("-", "")
        return f"calibration:inl_ev_project_{archive_tag}_{today_compact}"

    def extra_metadata(self, config: dict[str, Any]) -> dict[str, Any]:
        # vin_proxy unless port-proxy fallback dominated the cohort.
        strategy = "port_proxy" if self._n_port > self._n_vin else "vin_proxy"
        return {
            "user_id_strategy": strategy,
            "archive_tag": str(config["archive_tag"]),
            "venue_filter": config.get("venue_filter", "residential"),
            "fleet_era": "phase1_2011_2013",
            "schema_version": SCHEMA_VERSION,
        }

    def token_help_message(self) -> str:
        return (
            "verify INL_BULK_URL points to an avt.inl.gov Phase 1 archive "
            "or pre-populate the cache directory"
        )

    def parse_args(self, raw: list[str]) -> dict[str, Any]:
        """Parse --source-arg key=value pairs scoped to inl_ev_project."""
        out: dict[str, Any] = {}
        for kv in raw:
            if "=" not in kv:
                raise ValueError(f"--source-arg must be key=value: {kv!r}")
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "archive_tag":
                out["archive_tag"] = v
            elif k == "venue_filter":
                out["venue_filter"] = v
            elif k == "min_power_kw":
                out["min_power_kw"] = float(v)
            elif k == "max_power_kw":
                out["max_power_kw"] = float(v)
            elif k == "bulk_url":
                out["bulk_url"] = v
            else:
                raise ValueError(f"InlSource: unknown source-arg key {k!r}")
        return out


def _venue_allowed(venue: Any, venue_filter: str | None) -> bool:
    if venue_filter is None or venue_filter == "all":
        return True
    v = str(venue).strip().lower() if venue is not None else ""
    if venue_filter == "residential":
        return v in _RESIDENTIAL_VENUES
    if venue_filter == "workplace":
        return v in _WORKPLACE_VENUES
    return True


def _extract_session_inl(
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

    # TODO timezone handling — Phase 1 covered Pacific NW + Arizona deployments;
    # naive timestamps treated as UTC for now, matching EV WATTS extractor.
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
    if dwell < MIN_DWELL_HOURS or dwell > 168.0:  # < 30 min noise; > 1 week bogus
        return None

    arr_hour = start.hour + start.minute / 60.0 + start.second / 3600.0
    kwh_del = _safe_float(row.get(COL_ENERGY_KWH)) or 0.0

    vehicle_id = row.get(COL_VEHICLE_ID)
    has_vehicle = vehicle_id is not None and not (
        isinstance(vehicle_id, float) and pd.isna(vehicle_id)
    ) and str(vehicle_id).strip() != ""
    if has_vehicle:
        user_id = f"inl:vin:{vehicle_id}"
    else:
        evse_id = row.get(COL_EVSE_ID)
        if evse_id is None or (isinstance(evse_id, float) and pd.isna(evse_id)):
            return None
        user_id = f"inl:port:{evse_id}"

    site = str(venue) if venue not in (None, "") and not (isinstance(venue, float) and pd.isna(venue)) else "inl"

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
