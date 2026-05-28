"""EV WATTS bulk-release loader. Expected source: livewire.energy.gov."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests


def fetch_all_sessions(
    release_tag: str,
    cache_dir: Path,
    bulk_url: str | None = None,
    timeout_sec: int = 300,
) -> list[dict[str, Any]]:
    """Load EV WATTS rows for `release_tag`.

    Cache lookup order: parquet → CSV (fixture path). Cache hit bypasses
    URL/token resolution. Cache miss requires `bulk_url` arg or
    `EVWATTS_BULK_URL` env var; nothing is hard-coded.
    """
    cache_dir = Path(cache_dir)
    parquet_path = cache_dir / f"evwatts_{release_tag}.parquet"
    csv_path = cache_dir / f"evwatts_{release_tag}.csv"

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        return df.to_dict(orient="records")
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        return df.to_dict(orient="records")

    if bulk_url is None:
        bulk_url = os.environ.get("EVWATTS_BULK_URL")
    if not bulk_url:
        raise RuntimeError(
            "EVWATTS_BULK_URL not set and no cache file found at "
            f"{parquet_path}. Provide EVWATTS_BULK_URL env var (set in .env "
            "or shell), or pre-populate the cache directory."
        )

    headers: dict[str, str] = {}
    token = os.environ.get("EVWATTS_API_TOKEN")
    if token:
        # TODO: confirm auth scheme — livewire.energy.gov may require
        # account-based login instead of bearer token.
        headers["Authorization"] = f"Bearer {token}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    # Prefer parquet from upstream when content-type permits; fall back to
    # writing whatever we get to parquet_path (best-effort, fixture path is CSV).
    with requests.get(bulk_url, stream=True, timeout=timeout_sec, headers=headers) as r:
        r.raise_for_status()
        with parquet_path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)

    df = pd.read_parquet(parquet_path)
    return df.to_dict(orient="records")
