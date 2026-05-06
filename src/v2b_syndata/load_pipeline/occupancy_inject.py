"""Replace people-fraction Schedule:Compact in an IDF with one derived from a 15-min Series.

Strategy: average the input series down to a per-(daytype, hour) hourly fraction,
then emit a fresh ``Schedule:Compact`` block. Done as text replacement on the
IDF source — eppy parses the result back to verify validity.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .prototypes import get_occupancy_schedule_names


def _hourly_profile(occupancy: pd.Series) -> tuple[list[float], list[float]]:
    """Return (weekday_hourly[24], weekend_hourly[24]) ∈ [0, 1]."""
    if not isinstance(occupancy.index, pd.DatetimeIndex):
        raise ValueError("occupancy must be DatetimeIndex'd")
    df = pd.DataFrame({"v": occupancy.clip(0.0, 1.0).astype(float).to_numpy()},
                      index=occupancy.index)
    df["hour"] = df.index.hour
    df["wkend"] = df.index.dayofweek >= 5

    weekday = df[~df["wkend"]].groupby("hour")["v"].mean()
    weekend = df[df["wkend"]].groupby("hour")["v"].mean()

    def _fill(s: pd.Series) -> list[float]:
        out = [0.0] * 24
        for h, v in s.items():
            out[int(h)] = round(float(v), 4)
        return out

    return _fill(weekday), _fill(weekend)


def _emit_schedule_block(name: str, weekday: list[float], weekend: list[float]) -> str:
    """Emit a Schedule:Compact block matching PNNL prototype formatting."""
    lines = [
        "  Schedule:Compact,",
        f"    {name},            !- Name",
        "    Fraction,                !- Schedule Type Limits Name",
        "    Through: 12/31,          !- Field 1",
        "    For: Weekdays,           !- Field 2",
    ]
    for h, v in enumerate(weekday, start=1):
        lines.append(f"    Until: {h:02d}:00,{v:.4f},     !- weekday h{h:02d}")
    lines.append("    For: Weekends,           !- weekend block")
    for h, v in enumerate(weekend, start=1):
        lines.append(f"    Until: {h:02d}:00,{v:.4f},     !- weekend h{h:02d}")
    lines.append("    For: Holiday SummerDesignDay WinterDesignDay CustomDay1 CustomDay2,")
    lines.append("    Until: 24:00,0.0;        !- holiday/design days zero")
    return "\n".join(lines) + "\n"


def _replace_schedule(idf_text: str, schedule_name: str, new_block: str) -> tuple[str, bool]:
    """Replace the first Schedule:Compact whose Name field matches ``schedule_name``.

    Returns (new_text, replaced_flag).
    """
    pattern = re.compile(
        r"^\s*Schedule:Compact,\s*\n"        # opening line
        r"\s*" + re.escape(schedule_name) + r"\s*,[^\n]*\n"  # Name line
        r"(?:[^;]*;)\s*",                    # rest of block up to terminating ;
        flags=re.MULTILINE,
    )
    match = pattern.search(idf_text)
    if not match:
        return idf_text, False
    return idf_text[:match.start()] + new_block + idf_text[match.end():], True


def _replace_first_occ(idf_text: str, new_block: str) -> tuple[str, str]:
    """Fallback: replace the first Schedule:Compact whose name contains 'OCC'."""
    pattern = re.compile(
        r"^\s*Schedule:Compact,\s*\n"
        r"\s*([A-Za-z0-9_\.]+)\s*,[^\n]*\n"
        r"(?:[^;]*;)\s*",
        flags=re.MULTILINE,
    )
    for m in pattern.finditer(idf_text):
        name = m.group(1)
        if "occ" in name.lower():
            return idf_text[:m.start()] + new_block + idf_text[m.end():], name
    return idf_text, ""


def inject_occupancy(
    idf_path: Path,
    occupancy: pd.Series,
    output_idf_path: Path,
) -> Path:
    """Write a copy of ``idf_path`` with its occupancy Schedule:Compact(s) replaced.

    Replaces all known people-fraction schedules (base + setback variants).
    """
    idf_path = Path(idf_path)
    output_idf_path = Path(output_idf_path)
    idf_text = idf_path.read_text()

    weekday, weekend = _hourly_profile(occupancy)
    targets = get_occupancy_schedule_names(idf_path.name)

    new_text = idf_text
    replaced_count = 0
    for target in targets:
        block = _emit_schedule_block(target, weekday, weekend)
        new_text, ok = _replace_schedule(new_text, target, block)
        if ok:
            replaced_count += 1

    if replaced_count == 0:
        # Fallback — replace the first Schedule:Compact whose name contains OCC.
        new_text, fallback_name = _replace_first_occ(
            new_text, _emit_schedule_block("PLACEHOLDER", weekday, weekend)
        )
        if fallback_name:
            new_text = new_text.replace(
                _emit_schedule_block("PLACEHOLDER", weekday, weekend),
                _emit_schedule_block(fallback_name, weekday, weekend),
                1,
            )
        else:
            raise RuntimeError(
                f"no Schedule:Compact named {targets!r} (or *OCC*) found in {idf_path}"
            )

    output_idf_path.parent.mkdir(parents=True, exist_ok=True)
    output_idf_path.write_text(new_text)
    return output_idf_path
