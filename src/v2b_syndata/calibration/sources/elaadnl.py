"""ElaadNL Open Charging Transactions calibration source.

Dutch public-charging dataset (CC BY 4.0, open-data.elaad.io). EU geography,
public/semi-public/workplace L2 + DCFC sessions. Anonymized per-session RFID
card IDs provide proxy longitudinal identity (one driver may hold multiple
cards; cards can transfer — weaker than vin_proxy, stronger than port_proxy).

Timezone: ElaadNL CSVs ship naive *local* (Europe/Amsterdam) timestamps. We
attach UTC as a label without shifting (`utc=True` on a naive value relabels,
it does not convert), so the extracted clock hour equals the Amsterdam
wall-clock hour — i.e. arrival_hour is already correct local time, NOT offset.
This differs from ACN, whose feed is *true* UTC and must be converted to
Pacific. Do not "fix" this source by converting the UTC-labelled value to
Amsterdam — that would add +1–2h and break a currently-correct hour.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd

from ..elaadnl_fetcher import fetch_all_sessions
from ..feature_extractor import MIN_DWELL_HOURS, SessionFeatures

SCHEMA_VERSION = "v1"

# TODO confirm column names against real open-data.elaad.io Open Charging
# Transactions release. Fixture uses normalized snake_case; production schema
# may need a column-rename layer in fetch_all_sessions.
COL_CARD_ID = "card_id"
COL_START = "start_time"
COL_END = "end_time"
COL_ENERGY_KWH = "energy_kwh"
COL_EVSE_ID = "evse_id"
COL_VENUE = "venue"
COL_POWER_KW = "evse_power_kw"

_PUBLIC_VENUES = {"public", "semi_public", "street"}
_DCFC_VENUES = {"fastcharge", "dcfc"}
_WORKPLACE_VENUES = {"workplace", "office", "work"}
_RESIDENTIAL_VENUES = {"residential", "home"}


class ElaadNLSource:
    per_user_csv_filename = "elaadnl_per_user.csv"

    def __init__(self) -> None:
        # Counts per-session user_id strategies observed during fetch. ElaadNL
        # Open Datasets expose anonymized RFID card IDs, so the primary
        # strategy is card_proxy; the port_proxy branch is a row-level
        # fallback for rows missing card_id. Source-level metadata flips to
        # port_proxy only when port-proxy dominates the cohort.
        self._n_card = 0
        self._n_port = 0

    def fetch_sessions(self, config: dict[str, Any]) -> list[SessionFeatures]:
        archive_tag = str(config["archive_tag"])
        cache_dir = Path(config["cache_dir"])
        bulk_url = config.get("bulk_url")
        venue_filter = config.get("venue_filter", "public")
        min_kw = config.get("min_power_kw")
        max_kw = config.get("max_power_kw")

        rows = fetch_all_sessions(archive_tag, cache_dir, bulk_url=bulk_url)
        out: list[SessionFeatures] = []
        for r in rows:
            sf = _extract_session_elaadnl(r, venue_filter, min_kw, max_kw)
            if sf is not None:
                if sf.user_id.startswith("elaadnl:port:"):
                    self._n_port += 1
                else:
                    self._n_card += 1
                out.append(sf)
        return out

    def dataset_name(self) -> str:
        # Real-data v2: SmoothEMS met GridShield, Utrecht NL office parking
        # lot (a.s.r. living lab, ElaadNL consortium). Published via
        # 4TU.ResearchData under CC BY-NC-SA 4.0, DOI 80ef3824-...
        # Fixture path also accepted via this same source class.
        return "ElaadNL / 4TU Utrecht office parking (SmoothEMS met GridShield)"

    def provenance_prefix(self, config: dict[str, Any]) -> str:
        archive_tag = str(config["archive_tag"])
        today_compact = dt.date.today().isoformat().replace("-", "")
        return f"calibration:elaadnl_open_2020_{archive_tag}_{today_compact}"

    def extra_metadata(self, config: dict[str, Any]) -> dict[str, Any]:
        # card_proxy unless port-proxy fallback dominated the cohort.
        strategy = "port_proxy" if self._n_port > self._n_card else "card_proxy"
        return {
            "user_id_strategy": strategy,
            "archive_tag": str(config["archive_tag"]),
            "venue_filter": config.get("venue_filter", "public"),
            "dataset_release": "open_2020",
            "geography": "NL_EU",
            "schema_version": SCHEMA_VERSION,
        }

    def token_help_message(self) -> str:
        return (
            "verify ELAADNL_BULK_URL points to a real EU workplace charging "
            "archive (e.g. 4TU.ResearchData dataset "
            "80ef3824-3f5d-4e45-8794-3b8791efbd13, 'Electric Vehicle Charging "
            "Session Data of Large Office Parking Lot', CC BY-NC-SA 4.0) or "
            "pre-populate the cache directory"
        )

    def parse_args(self, raw: list[str]) -> dict[str, Any]:
        """Parse --source-arg key=value pairs scoped to elaadnl_open_2020."""
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
                raise ValueError(f"ElaadNLSource: unknown source-arg key {k!r}")
        return out


def _venue_allowed(venue: Any, venue_filter: str | None) -> bool:
    if venue_filter is None or venue_filter == "all":
        return True
    v = str(venue).strip().lower() if venue is not None else ""
    if venue_filter == "public":
        return v in _PUBLIC_VENUES
    if venue_filter == "dcfc":
        return v in _DCFC_VENUES
    if venue_filter == "workplace":
        return v in _WORKPLACE_VENUES
    if venue_filter == "residential":
        return v in _RESIDENTIAL_VENUES
    return True


def _extract_session_elaadnl(
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

    # TZ (see module docstring): ElaadNL ships naive Europe/Amsterdam timestamps;
    # relabelling naive→UTC does not shift, so the extracted hour is already the
    # correct Amsterdam wall-clock hour. Do NOT convert to Amsterdam here.
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

    card_id = row.get(COL_CARD_ID)
    has_card = card_id is not None and not (
        isinstance(card_id, float) and pd.isna(card_id)
    ) and str(card_id).strip() != ""
    if has_card:
        user_id = f"elaadnl:card:{card_id}"
    else:
        evse_id = row.get(COL_EVSE_ID)
        if evse_id is None or (isinstance(evse_id, float) and pd.isna(evse_id)):
            return None
        user_id = f"elaadnl:port:{evse_id}"

    site = str(venue) if venue not in (None, "") and not (isinstance(venue, float) and pd.isna(venue)) else "elaadnl"

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
