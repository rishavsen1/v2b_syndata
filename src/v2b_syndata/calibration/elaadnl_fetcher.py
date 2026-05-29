"""ElaadNL Open Charging Transactions (Dutch public-charging open dataset).

Expected source: open-data.elaad.io bulk archive (CC BY 4.0).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests


def fetch_all_sessions(
    archive_tag: str,
    cache_dir: Path,
    bulk_url: str | None = None,
    timeout_sec: int = 300,
) -> list[dict[str, Any]]:
    """Load ElaadNL Open Charging Transactions rows for `archive_tag`.

    Cache lookup order: parquet → CSV (fixture path). Cache hit bypasses
    URL/token resolution. Cache miss requires `bulk_url` arg or
    `ELAADNL_BULK_URL` env var; nothing is hard-coded.
    """
    cache_dir = Path(cache_dir)
    parquet_path = cache_dir / f"elaadnl_{archive_tag}.parquet"
    csv_path = cache_dir / f"elaadnl_{archive_tag}.csv"

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        return df.to_dict(orient="records")
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        return df.to_dict(orient="records")

    if bulk_url is None:
        bulk_url = os.environ.get("ELAADNL_BULK_URL")
    if not bulk_url:
        raise RuntimeError(
            "ELAADNL_BULK_URL not set and no cache file found at "
            f"{parquet_path}. Provide ELAADNL_BULK_URL env var (set in .env "
            "or shell), or pre-populate the cache directory."
        )

    headers: dict[str, str] = {}
    token = os.environ.get("ELAADNL_API_TOKEN")
    if token:
        # TODO: confirm whether ElaadNL bulk archive requires auth — Open
        # Datasets are historically public CC BY 4.0 downloads.
        headers["Authorization"] = f"Bearer {token}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    with requests.get(bulk_url, stream=True, timeout=timeout_sec, headers=headers) as r:
        r.raise_for_status()
        with parquet_path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)

    df = pd.read_parquet(parquet_path)
    return df.to_dict(orient="records")
