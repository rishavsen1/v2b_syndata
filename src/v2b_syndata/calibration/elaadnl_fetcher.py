"""ElaadNL-anchored EU workplace charging dataset loader.

Real-data source (v2): the SmoothEMS met GridShield dataset published via
4TU.ResearchData at https://data.4tu.nl/datasets/80ef3824-3f5d-4e45-8794-3b8791efbd13
("Electric Vehicle Charging Session Data of Large Office Parking Lot",
CC BY-NC-SA 4.0). The dataset is a consortium output of ElaadNL +
University of Twente + a.s.r. + MENNEKES + Kropman + Amperapark; ElaadNL
operates the data API. Covers an a.s.r. office parking lot in Utrecht,
NL, Aug 2020 – Oct 2024, ~300 charging points, 55,379 sessions across
3,409 pseudonymized EV identifiers.

Why this slot is called "elaadnl_*" rather than "utrecht_4tu_*": the
direct ElaadNL Open Charging Transactions historical download was
discontinued (platform.elaad.io retired; current dashboard at
data.elaad.nl exposes data only via interactive UI). The 4TU.nl Utrecht
dataset is ElaadNL-collected charging data published with a citable DOI,
making it the closest available real-data substitute. The loader name +
class name preserve back-compat with prior PRs (b9d630f / d49134e
pattern) and downstream populations / scenarios; semantic substitution
is documented in docs/CALIBRATION_NOTES.md.

Fixture-driven tests still use the original card-id schema (card_id,
evse_id, venue, evse_power_kw, start_time, end_time, energy_kwh). Real
4TU data uses a different schema (EV_id_x, evse_uid, rail, channel,
total_energy, start_datetime, end_datetime, capacity_kwh, ...); the
fetcher applies a column-rename + venue/power synthesis layer so the
downstream extractor (sources/elaadnl.py) consumes the same shape in
both cases.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# Column rename: 4TU schema → our internal extractor schema.
_RENAME_4TU_TO_INTERNAL = {
    "EV_id_x":         "card_id",
    "evse_uid":        "evse_id",
    "start_datetime":  "start_time",
    "end_datetime":    "end_time",
    "total_energy":    "energy_kwh",
}

# Per README, default plug power 11 kW (22 kW max, halved if both
# channels active). We use 11 kW as a conservative default for
# distribution-fitting purposes; exact per-session power is not
# recorded in the dataset.
_DEFAULT_EVSE_POWER_KW = 11.0


def _is_4tu_schema(columns: list[str]) -> bool:
    """4TU header has BOM + semicolon-separated; ours uses commas + simple
    snake_case. Detect by the presence of EV_id_x or start_datetime."""
    return "EV_id_x" in columns or "start_datetime" in columns


def _normalize_4tu_to_internal(df: pd.DataFrame) -> pd.DataFrame:
    """Convert 4TU.nl Utrecht schema into the internal session-row format."""
    df = df.rename(columns=_RENAME_4TU_TO_INTERNAL)
    # 4TU is workplace-only by construction (a.s.r. office parking lot)
    df["venue"] = "workplace"
    # Per-session power not in dataset; use default
    df["evse_power_kw"] = _DEFAULT_EVSE_POWER_KW
    return df


def fetch_all_sessions(
    archive_tag: str,
    cache_dir: Path,
    bulk_url: str | None = None,
    timeout_sec: int = 300,
) -> list[dict[str, Any]]:
    """Load ElaadNL-anchored charging-session rows for ``archive_tag``.

    Cache lookup order: parquet → CSV (fixture or real-data path). Cache
    hit bypasses URL/token resolution. Cache miss requires ``bulk_url``
    arg or ``ELAADNL_BULK_URL`` env var; nothing is hard-coded.

    Two CSV schemas are supported:
      * Internal (fixture): card_id, evse_id, venue, evse_power_kw,
        start_time, end_time, energy_kwh — comma-separated.
      * 4TU.nl Utrecht real-data: EV_id_x, evse_uid, rail, channel,
        start_datetime, end_datetime, total_energy, ... —
        semicolon-separated; detected automatically and renamed.
    """
    cache_dir = Path(cache_dir)
    parquet_path = cache_dir / f"elaadnl_{archive_tag}.parquet"
    csv_path = cache_dir / f"elaadnl_{archive_tag}.csv"

    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        if _is_4tu_schema(list(df.columns)):
            df = _normalize_4tu_to_internal(df)
        return df.to_dict(orient="records")

    if csv_path.exists():
        # 4TU.nl ships CSVs with BOM + ; separator. Try ; first; if
        # only one column lands, fall back to comma.
        df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
        if len(df.columns) <= 1:
            df = pd.read_csv(csv_path)
        if _is_4tu_schema(list(df.columns)):
            df = _normalize_4tu_to_internal(df)
        return df.to_dict(orient="records")

    if bulk_url is None:
        bulk_url = os.environ.get("ELAADNL_BULK_URL")
    if not bulk_url:
        raise RuntimeError(
            "ELAADNL_BULK_URL not set and no cache file found at "
            f"{parquet_path}. Provide ELAADNL_BULK_URL env var (set in .env "
            "or shell), or pre-populate the cache directory. Real-data "
            "default: 4TU.nl dataset 80ef3824-3f5d-4e45-8794-3b8791efbd13 "
            "(Electric Vehicle Charging Session Data of Large Office "
            "Parking Lot, Utrecht NL, CC BY-NC-SA 4.0)."
        )

    headers: dict[str, str] = {}
    token = os.environ.get("ELAADNL_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    # If URL ends in .csv, save as CSV; if .parquet, save as parquet.
    is_csv = bulk_url.lower().endswith(".csv")
    out_path = csv_path if is_csv else parquet_path
    with requests.get(bulk_url, stream=True, timeout=timeout_sec, headers=headers) as r:
        r.raise_for_status()
        with out_path.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)

    if is_csv:
        df = pd.read_csv(out_path, sep=";", encoding="utf-8-sig")
        if len(df.columns) <= 1:
            df = pd.read_csv(out_path)
    else:
        df = pd.read_parquet(out_path)
    if _is_4tu_schema(list(df.columns)):
        df = _normalize_4tu_to_internal(df)
    return df.to_dict(orient="records")
