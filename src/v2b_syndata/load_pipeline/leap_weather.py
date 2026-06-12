"""Leap-year-aware EPW weather transform.

TMYx weather files are 365-day (8760 hourly rows, no Feb 29). When EnergyPlus
runs an annual RunPeriod pinned to a leap year (e.g. 2020) against a 365-day
file, its schedule day-type sequencer does not advance across the absent
Feb 29, so every date from Mar 1 onward is simulated with the *wrong* calendar
day's schedule block (calendar Saturday gets the weekday block, etc.). The
weekday/weekend load shape is then wrong at the source — re-labelling the
output timestamps cannot fix it because the load values were baked under the
shifted schedule.

The fix is to keep the weather and the leap calendar in lockstep: for a leap
simulation year, synthesize a Feb 29 (a copy of Feb 28's 24 hourly rows) so the
file has 366 days, matching the leap RunPeriod. EnergyPlus then advances the
day-of-week correctly and applies weekend schedules on real Sat/Sun.

Non-leap years are byte-for-byte unchanged (TMYx is inherently a non-leap year
and already aligns), so this transform is a no-op there.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import shutil
from pathlib import Path

_DOW_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday")

_N_HEADER = 8            # EPW: 8 header lines, then hourly data rows.
_HOLIDAYS_LINE = 4       # "HOLIDAYS/DAYLIGHT SAVINGS,<LeapYearObserved>,..."
_DATA_PERIODS_LINE = 7   # 0-indexed header line carrying the start day-of-week.
_HOURS_PER_DAY = 24


def is_leap(year: int) -> bool:
    return calendar.isleap(year)


def make_leap_epw(src_epw: Path, dst_epw: Path, year: int) -> Path:
    """Write a copy of ``src_epw`` to ``dst_epw`` suitable for simulating ``year``.

    For a leap ``year``: inserts a Feb 29 block (24 rows duplicating Feb 28,
    with the day field rewritten to 29) and rewrites the DATA PERIODS start
    day-of-week to the leap year's Jan-1 weekday. For a non-leap ``year``: an
    exact byte copy (no-op).

    Pure function of the input bytes → deterministic.
    """
    src_epw = Path(src_epw)
    dst_epw = Path(dst_epw)
    dst_epw.parent.mkdir(parents=True, exist_ok=True)

    if not is_leap(year):
        shutil.copyfile(src_epw, dst_epw)
        return dst_epw

    # Detect the terminator from raw bytes — read_text() uses universal-newline
    # mode and would translate CRLF→LF before we could see it.
    raw_bytes = src_epw.read_bytes()
    newline = "\r\n" if b"\r\n" in raw_bytes else "\n"
    lines = raw_bytes.decode().splitlines()
    header = lines[:_N_HEADER]
    data = lines[_N_HEADER:]

    # 0. Set the EPW "LeapYear Observed" flag to Yes. This is the FIRST field of
    # the HOLIDAYS/DAYLIGHT SAVINGS header; without it EnergyPlus rejects the
    # 366-day data ("WeatherFile does not allow Leap Years") and silently runs
    # 365 days — re-introducing the day-of-week drift the Feb 29 row is meant to
    # cure. This edit is load-bearing, so fail loudly on an unexpected header
    # rather than silently no-op (the row-count guard below cannot catch it).
    hol = header[_HOLIDAYS_LINE].split(",")
    if not header[_HOLIDAYS_LINE].startswith("HOLIDAYS") or len(hol) < 2:
        raise ValueError(
            f"{src_epw.name}: unexpected HOLIDAYS/DAYLIGHT SAVINGS header: "
            f"{header[_HOLIDAYS_LINE]!r}"
        )
    hol[1] = "Yes"
    header[_HOLIDAYS_LINE] = ",".join(hol)

    # 1. Build the Feb 29 block from Feb 28's rows (day field = column index 2).
    feb29_rows: list[str] = []
    last_feb28_idx: int | None = None
    for i, row in enumerate(data):
        parts = row.split(",")
        if len(parts) > 3 and parts[1] == "2" and parts[2] == "28":
            parts[2] = "29"
            feb29_rows.append(",".join(parts))
            last_feb28_idx = i

    if last_feb28_idx is None or len(feb29_rows) != _HOURS_PER_DAY:
        raise ValueError(
            f"{src_epw.name}: expected 24 Feb-28 rows to clone for Feb 29, "
            f"found {len(feb29_rows)}"
        )

    out_data = data[: last_feb28_idx + 1] + feb29_rows + data[last_feb28_idx + 1 :]

    # 2. Align the DATA PERIODS start day-of-week to the leap year's Jan 1.
    dp = header[_DATA_PERIODS_LINE].split(",")
    if not header[_DATA_PERIODS_LINE].startswith("DATA PERIODS") or len(dp) < 5:
        raise ValueError(
            f"{src_epw.name}: unexpected DATA PERIODS header: "
            f"{header[_DATA_PERIODS_LINE]!r}"
        )
    dp[4] = _DOW_NAMES[_dt.date(year, 1, 1).weekday()]
    header[_DATA_PERIODS_LINE] = ",".join(dp)

    # 3. Guard: a leap year must yield exactly 366 days of hourly data, so the
    # silent-drift failure mode cannot reappear unnoticed.
    expected = 366 * _HOURS_PER_DAY
    if len(out_data) != expected:
        raise ValueError(
            f"{src_epw.name}: leap EPW has {len(out_data)} data rows, "
            f"expected {expected}"
        )

    dst_epw.write_text(newline.join(header + out_data) + newline)
    return dst_epw
