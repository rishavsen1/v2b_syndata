"""ACN-Data raw HTTP access. Not acnportal — direct REST."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

ACN_BASE = "https://ev.caltech.edu/api/v1/sessions"


def fetch_all_sessions(
    site: str,
    year_start: int,
    year_end: int,
    cache_dir: Path | None = None,
    page_size: int = 500,
    timeout_sec: int = 120,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Page through all sessions in [year_start, year_end] for a site.

    Caches to cache_dir/<site>_<start>_<end>.json. Re-uses cache if present.
    Token only required when an actual HTTP fetch is needed; cache hits
    bypass token resolution entirely (B1 fix from docs/archive/AUDIT_REPORT.md).
    """
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = cache_dir / f"{site}_{year_start}_{year_end}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())

    if token is None:
        try:
            token = os.environ["ACN_API_TOKEN"]
        except KeyError as e:
            raise RuntimeError(
                "ACN_API_TOKEN not set and no cache file found at "
                f"{cache_path}. Provide ACN_API_TOKEN env var (set in .env "
                "or shell), or pre-populate the cache directory."
            ) from e

    where = '{"connectionTime":{"$gte":"%s","$lt":"%s"}}' % (
        f"Mon, 01 Jan {year_start} 00:00:00 GMT",
        f"Mon, 01 Jan {year_end + 1} 00:00:00 GMT",
    )

    all_sessions: list[dict[str, Any]] = []
    page = 1
    auth = HTTPBasicAuth(token, "")
    url = f"{ACN_BASE}/{site}"
    while True:
        r = requests.get(
            url,
            auth=auth,
            params={"max_results": page_size, "where": where, "page": page},
            timeout=timeout_sec,
        )
        r.raise_for_status()
        j = r.json()
        items = j.get("_items", [])
        if not items:
            break
        all_sessions.extend(items)
        links = j.get("_links", {})
        if "next" not in links:
            break
        page += 1

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(all_sessions))

    return all_sessions


def filter_with_userid(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sessions if s.get("userID") is not None]
