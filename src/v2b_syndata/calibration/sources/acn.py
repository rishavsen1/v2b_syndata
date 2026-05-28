"""ACN-Data calibration source. Wraps acn_fetcher + feature_extractor."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from ..acn_fetcher import fetch_all_sessions, filter_with_userid
from ..feature_extractor import SessionFeatures, extract_session


class AcnSource:
    per_user_csv_filename = "acn_per_user.csv"

    def fetch_sessions(self, config: dict[str, Any]) -> list[SessionFeatures]:
        sites = tuple(config.get("sites", ("caltech", "jpl", "office001")))
        year_start = int(config["year_start"])
        year_end = int(config["year_end"])
        cache_dir = Path(config["cache_dir"])
        sessions: list[SessionFeatures] = []
        for site in sites:
            raw = fetch_all_sessions(site, year_start, year_end, cache_dir=cache_dir)
            raw = filter_with_userid(raw)
            for r in raw:
                sf = extract_session(r, site)
                if sf is not None:
                    sessions.append(sf)
        return sessions

    def dataset_name(self) -> str:
        return "ACN-Data"

    def provenance_prefix(self, config: dict[str, Any]) -> str:
        year_start = int(config["year_start"])
        year_end = int(config["year_end"])
        today_compact = dt.date.today().isoformat().replace("-", "")
        return f"calibration:acn_data_{year_start}_{year_end}_{today_compact}"

    def extra_metadata(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "sites": list(config.get("sites", ("caltech", "jpl", "office001"))),
            "year_range": [int(config["year_start"]), int(config["year_end"])],
        }

    def token_help_message(self) -> str:
        return "verify ACN_API_TOKEN and year range"

    def parse_args(self, raw: list[str]) -> dict[str, Any]:
        """Parse --source-arg key=value pairs. ACN consumes: site (repeatable), year_start, year_end."""
        out: dict[str, Any] = {}
        sites: list[str] = []
        for kv in raw:
            if "=" not in kv:
                raise ValueError(f"--source-arg must be key=value: {kv!r}")
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k == "site":
                sites.append(v)
            elif k in ("year_start", "year_end"):
                out[k] = int(v)
            else:
                raise ValueError(f"AcnSource: unknown source-arg key {k!r}")
        if sites:
            out["sites"] = tuple(sites)
        return out
