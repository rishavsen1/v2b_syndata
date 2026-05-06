"""Parse EnergyPlus output (eplusmtr.csv) → L_flex, L_inflex Series.

EnergyPlus emits joule totals per reporting interval. With Timestep=4 (15 min)
the conversion is ``kW = J / (15 min × 60 s/min × 1 kW/1000 W)`` = ``J / 900_000``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Meter substring → which bucket the meter contributes to.
# Matched case-insensitively against the CSV column header.
FLEX_METERS = (
    "cooling:electricity",
    "heating:electricity",
    "fans:electricity",
    "watersystems:electricity",
)
INFLEX_METERS = (
    "interiorlights:electricity",
    "exteriorlights:electricity",
    "interiorequipment:electricity",
    "exteriorequipment:electricity",
)

INTERVAL_SEC = 15 * 60  # 15-minute timestep
J_PER_KWH_15MIN = INTERVAL_SEC * 1000  # J → kW conversion factor


def _classify_columns(columns: list[str]) -> tuple[list[str], list[str]]:
    """Return (flex_cols, inflex_cols) matched against the meter substring sets."""
    flex_cols: list[str] = []
    inflex_cols: list[str] = []
    for col in columns:
        low = col.lower()
        if any(m in low for m in FLEX_METERS):
            flex_cols.append(col)
        elif any(m in low for m in INFLEX_METERS):
            inflex_cols.append(col)
    return flex_cols, inflex_cols


def _parse_ep_datetime(values: pd.Series, year: int) -> pd.DatetimeIndex:
    """EnergyPlus formats timestamps as ``MM/DD HH:MM:SS`` without a year.

    ``24:00:00`` is also valid (end-of-day) and pandas rejects it — normalize
    to next-day 00:00.
    """
    cleaned = values.astype(str).str.strip()

    def _normalize(s: str) -> tuple[str, int]:
        # Returns (mm/dd HH:MM:SS, day_offset_in_days)
        # EP uses 24:00:00 as the boundary timestamp at end of a day.
        if "24:00:00" in s:
            return s.replace("24:00:00", "00:00:00"), 1
        return s, 0

    parts = [_normalize(s) for s in cleaned]
    base = [p[0] for p in parts]
    offsets = pd.to_timedelta([p[1] for p in parts], unit="D")
    parsed = pd.to_datetime([f"{year}/{s}" for s in base], format="%Y/%m/%d  %H:%M:%S", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime([f"{year}/{s}" for s in base], errors="coerce")
    return pd.DatetimeIndex(parsed) + offsets


def parse_eplusout(
    csv_path: Path,
    sim_window_start: pd.Timestamp,
    sim_window_end: pd.Timestamp,
) -> tuple[pd.Series, pd.Series]:
    """Parse eplusmtr.csv (or eplusout.csv), slice to sim_window, return kW Series."""
    df = pd.read_csv(csv_path)
    # First column is the timestamp ("Date/Time").
    ts_col = df.columns[0]
    other_cols = list(df.columns[1:])

    flex_cols, inflex_cols = _classify_columns(other_cols)
    if not flex_cols and not inflex_cols:
        raise ValueError(
            f"no recognizable end-use meter columns in {csv_path}. cols={other_cols}"
        )

    year = pd.Timestamp(sim_window_start).year
    idx = _parse_ep_datetime(df[ts_col], year)

    flex_j = df[flex_cols].sum(axis=1).to_numpy() if flex_cols else pd.Series(0.0, index=df.index).to_numpy()
    inflex_j = df[inflex_cols].sum(axis=1).to_numpy() if inflex_cols else pd.Series(0.0, index=df.index).to_numpy()

    flex_kw = pd.Series(flex_j / J_PER_KWH_15MIN, index=idx, name="L_flex")
    inflex_kw = pd.Series(inflex_j / J_PER_KWH_15MIN, index=idx, name="L_inflex")

    # Some EP versions emit one extra row at the year boundary; drop duplicates.
    flex_kw = flex_kw[~flex_kw.index.duplicated(keep="first")]
    inflex_kw = inflex_kw[~inflex_kw.index.duplicated(keep="first")]

    start = pd.Timestamp(sim_window_start)
    end = pd.Timestamp(sim_window_end)
    flex_kw = flex_kw[(flex_kw.index >= start) & (flex_kw.index < end)]
    inflex_kw = inflex_kw[(inflex_kw.index >= start) & (inflex_kw.index < end)]
    return flex_kw, inflex_kw
