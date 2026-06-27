"""TMYx weather fetcher with local cache. AMY code path stub (D37)."""
from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .exceptions import WeatherStationNotFound

CACHE_ROOT_ENV = "V2B_WEATHER_CACHE"

# https://climate.onebuilding.org/ — TMYx files are organized by region/country/state.
# US station IDs follow ``USA_<state2>_<station_name>_TMYx`` (e.g. USA_TN_Nashville.Intl.AP.723270_TMYx).
_BASE_URL = (
    "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/"
    "USA_United_States_of_America"
)

# Two-letter state code → folder slug used by climate.onebuilding.org.
_US_STATE_FOLDERS: dict[str, str] = {
    "AL": "AL_Alabama",       "AK": "AK_Alaska",        "AZ": "AZ_Arizona",
    "AR": "AR_Arkansas",      "CA": "CA_California",    "CO": "CO_Colorado",
    "CT": "CT_Connecticut",   "DE": "DE_Delaware",      "DC": "DC_District_of_Columbia",
    "FL": "FL_Florida",       "GA": "GA_Georgia",       "HI": "HI_Hawaii",
    "ID": "ID_Idaho",         "IL": "IL_Illinois",      "IN": "IN_Indiana",
    "IA": "IA_Iowa",          "KS": "KS_Kansas",        "KY": "KY_Kentucky",
    "LA": "LA_Louisiana",     "ME": "ME_Maine",         "MD": "MD_Maryland",
    "MA": "MA_Massachusetts", "MI": "MI_Michigan",      "MN": "MN_Minnesota",
    "MS": "MS_Mississippi",   "MO": "MO_Missouri",      "MT": "MT_Montana",
    "NE": "NE_Nebraska",      "NV": "NV_Nevada",        "NH": "NH_New_Hampshire",
    "NJ": "NJ_New_Jersey",    "NM": "NM_New_Mexico",    "NY": "NY_New_York",
    "NC": "NC_North_Carolina","ND": "ND_North_Dakota",  "OH": "OH_Ohio",
    "OK": "OK_Oklahoma",      "OR": "OR_Oregon",        "PA": "PA_Pennsylvania",
    "RI": "RI_Rhode_Island",  "SC": "SC_South_Carolina","SD": "SD_South_Dakota",
    "TN": "TN_Tennessee",     "TX": "TX_Texas",         "UT": "UT_Utah",
    "VT": "VT_Vermont",       "VA": "VA_Virginia",      "WA": "WA_Washington",
    "WV": "WV_West_Virginia", "WI": "WI_Wisconsin",     "WY": "WY_Wyoming",
}


def _cache_dir() -> Path:
    """Return the local TMYx cache directory. Override via $V2B_WEATHER_CACHE."""
    import os
    override = os.environ.get(CACHE_ROOT_ENV)
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "stations"


def _parse_station(station: str) -> tuple[str, str]:
    """Parse ``USA_<state>_<rest>_TMYx`` → (state2, station_id)."""
    m = re.match(r"^USA_([A-Z]{2})_(.+)_TMYx$", station)
    if not m:
        raise ValueError(
            f"TMYx station {station!r} does not match expected pattern "
            "USA_<state2>_<...>_TMYx"
        )
    return m.group(1), station


def _build_url(station: str) -> str:
    state2, station_id = _parse_station(station)
    if state2 not in _US_STATE_FOLDERS:
        raise ValueError(f"unknown US state code {state2!r} in station {station!r}")
    return f"{_BASE_URL}/{_US_STATE_FOLDERS[state2]}/{station_id}.zip"


def _fetch_tmyx(
    station: str,
    cached_path: Path,
    fetcher: Callable[[str], bytes] | None = None,
) -> Path:
    """Download a TMYx zip, extract the .epw to ``cached_path``."""
    url = _build_url(station)
    cached_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if fetcher is not None:
            payload = fetcher(url)
        else:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            payload = resp.content
    except Exception as exc:
        raise WeatherStationNotFound(station, url) from exc

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            epw_member = next((n for n in zf.namelist() if n.endswith(".epw")), None)
            if epw_member is None:
                raise WeatherStationNotFound(station, url)
            with zf.open(epw_member) as src, cached_path.open("wb") as dst:
                dst.write(src.read())
    except zipfile.BadZipFile as exc:
        raise WeatherStationNotFound(station, url) from exc

    return cached_path


def get_weather_epw(
    tmyx_station: str,
    weather_type: str = "tmyx",
    weather_year: int | None = None,
    *,
    fetcher: Callable[[str], bytes] | None = None,
) -> Path:
    """Resolve a TMYx station ID to a local .epw file path. AMY raises NotImplementedError.

    ``fetcher`` is an optional override (url → zip bytes) used for testing.
    """
    if weather_type == "amy":
        raise NotImplementedError("AMY weather support deferred to v2 (D37)")
    if weather_type != "tmyx":
        raise ValueError(f"unknown weather_type {weather_type!r}")
    if weather_year is not None:
        # Year is only meaningful for AMY; TMYx is a typical-year file.
        raise ValueError("weather_year is only valid when weather_type='amy'")

    cached = _cache_dir() / f"{tmyx_station}.epw"
    if cached.exists():
        return cached
    return _fetch_tmyx(tmyx_station, cached, fetcher=fetcher)


def parse_epw_location(epw_path: Path) -> tuple[float, float, float]:
    """Parse the EPW header LOCATION record (line 1) → (latitude, longitude,
    timezone_hours). Needed by the PV solar-position model.

    EPW LOCATION line (0-indexed, comma-separated):
      0:'LOCATION' 1:City 2:State 3:Country 4:Source 5:WMO
      6:Latitude[°, +N] 7:Longitude[°, +E] 8:TimeZone[hours from GMT, +E] 9:Elevation

    Raises ValueError on a malformed header or out-of-range latitude/timezone —
    a silent default would yield a physically plausible but WRONG PV curve.
    """
    with Path(epw_path).open() as f:
        header = f.readline()
    parts = header.strip().split(",")
    if len(parts) < 9 or parts[0].strip().upper() != "LOCATION":
        raise ValueError(f"EPW first line is not a LOCATION record: {header[:80]!r}")
    try:
        lat = float(parts[6])
        lon = float(parts[7])
        tz = float(parts[8])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"EPW LOCATION lat/lon/tz unparseable: {header[:80]!r}") from exc
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"EPW latitude out of range: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"EPW longitude out of range: {lon}")
    if not (-12.0 <= tz <= 14.0):
        raise ValueError(f"EPW timezone out of range: {tz}")
    return lat, lon, tz


def parse_epw_temperatures(
    epw_path: Path, *, year: int = 2020,
) -> pd.Series:
    """Parse EPW dry-bulb temperature. Returns hourly °C series indexed by
    datetime built from (month, day, hour) of each EPW row anchored to
    `year` (TMY data has synthetic per-row years; we override for a stable index).

    EPW format: 8 header lines, then 8760 hourly rows. Columns (0-indexed):
      0:Year 1:Month 2:Day 3:Hour 4:Minute 5:Flags 6:DryBulb[°C] ...
    Hour is 1-24 in EPW; remapped to 0-23 for pandas.
    """
    with Path(epw_path).open() as f:
        for _ in range(8):
            f.readline()  # skip headers
        rows = []
        for line in f:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                month = int(parts[1])
                day = int(parts[2])
                hour = int(parts[3]) - 1  # EPW 1-24 → 0-23
                dry_bulb_c = float(parts[6])
            except (ValueError, IndexError):
                continue
            rows.append((month, day, hour, dry_bulb_c))

    df = pd.DataFrame(rows, columns=["month", "day", "hour", "temp_c"])
    timestamps = pd.to_datetime(dict(
        year=year, month=df["month"], day=df["day"], hour=df["hour"],
    ))
    return pd.Series(df["temp_c"].values, index=timestamps, name="dry_bulb_c")


_SOLAR_COLS = ("global_horizontal_w_m2", "direct_normal_w_m2", "diffuse_horizontal_w_m2")


def _sat_vapor_pressure(t_c):
    """Saturation vapour pressure (hPa) via the Magnus formula. Accepts scalar
    or numpy/pandas; uses np.exp so it vectorizes."""
    return 6.112 * np.exp(17.62 * t_c / (243.12 + t_c))


def _rh_from_t_td(t_c, td_c):
    """Relative humidity (%) from dry-bulb and dew-point (Magnus), clipped to
    [0, 100]. Keeps the exported RH consistent after a dew-point/temp shift."""
    rh = 100.0 * _sat_vapor_pressure(td_c) / _sat_vapor_pressure(t_c)
    return min(100.0, max(0.0, rh)) if np.isscalar(rh) else np.clip(rh, 0.0, 100.0)


def _wx_is_noop(temp_offset_c, solar_scale, dewpoint_offset_c, wind_scale) -> bool:
    return (float(temp_offset_c) == 0.0 and float(solar_scale) == 1.0
            and float(dewpoint_offset_c) == 0.0 and float(wind_scale) == 1.0)


def perturb_weather_frame(
    df: pd.DataFrame, temp_offset_c: float = 0.0, solar_scale: float = 1.0,
    dewpoint_offset_c: float = 0.0, wind_scale: float = 1.0,
) -> pd.DataFrame:
    """Apply the weather *realization* transform to a parsed weather frame:
    additive °C offset on dry-bulb, additive °C offset on dew-point (the
    moisture driver), multiplicative scale on the three solar channels and on
    wind speed (both clipped at 0). When dry-bulb or dew-point shift,
    relative_humidity_pct is recomputed (Magnus) from the perturbed pair so the
    export stays internally consistent. This is the SAME transform applied to the
    EPW the EnergyPlus load sim consumes (`perturb_epw_file`).

    Returns the frame unchanged (same object) when every knob is a no-op.
    """
    if _wx_is_noop(temp_offset_c, solar_scale, dewpoint_offset_c, wind_scale):
        return df
    out = df.copy()
    if float(temp_offset_c) != 0.0:
        out["dry_bulb_temp_c"] = out["dry_bulb_temp_c"] + float(temp_offset_c)
    if float(dewpoint_offset_c) != 0.0:
        out["dew_point_temp_c"] = out["dew_point_temp_c"] + float(dewpoint_offset_c)
    if float(solar_scale) != 1.0:
        for c in _SOLAR_COLS:
            if c in out.columns:
                out[c] = (out[c] * float(solar_scale)).clip(lower=0.0)
    if float(wind_scale) != 1.0 and "wind_speed_m_s" in out.columns:
        out["wind_speed_m_s"] = (out["wind_speed_m_s"] * float(wind_scale)).clip(lower=0.0)
    # Recompute RH from the (perturbed) dry-bulb + dew-point so it stays consistent.
    if (float(temp_offset_c) != 0.0 or float(dewpoint_offset_c) != 0.0) \
       and "relative_humidity_pct" in out.columns:
        out["relative_humidity_pct"] = _rh_from_t_td(
            out["dry_bulb_temp_c"].to_numpy(), out["dew_point_temp_c"].to_numpy())
    return out


def perturb_epw_file(
    epw_path: Path, out_path: Path,
    temp_offset_c: float = 0.0, solar_scale: float = 1.0,
    dewpoint_offset_c: float = 0.0, wind_scale: float = 1.0,
) -> Path:
    """Rewrite an EPW with the weather realization transform so EnergyPlus
    *simulates* the perturbed weather. Mirrors `perturb_weather_frame`: dry-bulb
    (col 6) += temp offset, dew-point (col 7) += dew-point offset, RH (col 8)
    recomputed from the pair when either shifts, solar (cols 13/14/15) ×scale,
    wind (col 21) ×scale (all clipped ≥0). Header (first 8 lines) and other
    columns are copied verbatim; data rows detected as in `parse_epw_weather`.

    No-op transform → returns `epw_path` unchanged (no rewrite).
    """
    if _wx_is_noop(temp_offset_c, solar_scale, dewpoint_offset_c, wind_scale):
        return Path(epw_path)
    src = Path(epw_path).read_text().splitlines(keepends=True)
    out_lines = src[:8]  # headers verbatim
    for line in src[8:]:
        nl = "\n" if line.endswith("\n") else ""
        parts = line.rstrip("\n").split(",")
        if len(parts) < 22:
            out_lines.append(line)
            continue
        try:
            int(parts[1]); int(parts[2]); int(parts[3])
            t = float(parts[6]) + float(temp_offset_c)
            td = float(parts[7]) + float(dewpoint_offset_c)
            parts[6] = repr(t)
            parts[7] = repr(td)
            if float(temp_offset_c) != 0.0 or float(dewpoint_offset_c) != 0.0:
                parts[8] = repr(float(_rh_from_t_td(t, td)))
            for ci in (13, 14, 15):
                parts[ci] = repr(max(0.0, float(parts[ci]) * float(solar_scale)))
            parts[21] = repr(max(0.0, float(parts[21]) * float(wind_scale)))
        except (ValueError, IndexError):
            out_lines.append(line)
            continue
        out_lines.append(",".join(parts) + nl)
    Path(out_path).write_text("".join(out_lines))
    return Path(out_path)


def parse_epw_weather(
    epw_path: Path, *, year: int = 2020,
) -> pd.DataFrame:
    """Parse the EPW weather fields used by the optimus `weather_data.csv`
    export: dry-bulb temp, dew-point temp, relative humidity, wind speed, and
    the three solar-irradiance channels.

    Returns an hourly DataFrame indexed by datetime (built from each EPW row's
    month/day/hour anchored to `year`, mirroring `parse_epw_temperatures`), with
    columns `dry_bulb_temp_c, dew_point_temp_c, relative_humidity_pct,
    wind_speed_m_s, global_horizontal_w_m2, direct_normal_w_m2,
    diffuse_horizontal_w_m2`.

    EPW data-row columns (0-indexed):
      1:Month 2:Day 3:Hour 6:DryBulb[°C] 7:DewPoint[°C] 8:RelativeHumidity[%]
      13:GlobalHorizontalRadiation 14:DirectNormalRadiation
      15:DiffuseHorizontalRadiation (all Wh/m², hourly ≈ avg W/m²) 21:WindSpeed[m/s]
    Hour is 1-24 in EPW; remapped to 0-23 for pandas.
    """
    cols = ["month", "day", "hour", "dry_bulb_temp_c", "dew_point_temp_c",
            "relative_humidity_pct", "wind_speed_m_s",
            "global_horizontal_w_m2", "direct_normal_w_m2", "diffuse_horizontal_w_m2"]
    with Path(epw_path).open() as f:
        for _ in range(8):
            f.readline()  # skip headers
        rows = []
        for line in f:
            parts = line.split(",")
            if len(parts) < 22:  # need through wind speed (col 21) + solar (13-15)
                continue
            try:
                month = int(parts[1])
                day = int(parts[2])
                hour = int(parts[3]) - 1  # EPW 1-24 → 0-23
                dry_bulb_c = float(parts[6])
                dew_point_c = float(parts[7])
                rel_humidity = float(parts[8])
                ghi = float(parts[13])
                dni = float(parts[14])
                dhi = float(parts[15])
                wind_speed = float(parts[21])
            except (ValueError, IndexError):
                continue
            rows.append((month, day, hour, dry_bulb_c, dew_point_c,
                         rel_humidity, wind_speed, ghi, dni, dhi))

    df = pd.DataFrame(rows, columns=cols)
    timestamps = pd.to_datetime(dict(
        year=year, month=df["month"], day=df["day"], hour=df["hour"],
    ))
    out = df[[
        "dry_bulb_temp_c", "dew_point_temp_c",
        "relative_humidity_pct", "wind_speed_m_s",
        "global_horizontal_w_m2", "direct_normal_w_m2", "diffuse_horizontal_w_m2",
    ]].copy()
    out.index = timestamps
    return out


def parsed_perturbed_weather(
    tmyx_station: str, year: int,
    temp_offset_c: float = 0.0, solar_scale: float = 1.0,
    dewpoint_offset_c: float = 0.0, wind_scale: float = 1.0,
    *, fetcher: Callable[[str], bytes] | None = None,
) -> pd.DataFrame:
    """Full-year hourly weather frame matching exactly what EnergyPlus simulated:
    resolve the station EPW → leap-inject Feb 29 for leap years → parse the
    weather fields → apply the realization perturbation (same four knobs the load
    sim used). Both the optimus ``weather_data.csv`` export and the PV model build
    from this single helper, so the irradiance/temperature driving PV is
    byte-identical to the building-load weather. Caller slices to its window."""
    from . import leap_weather  # local import; leap_weather does not import weather
    epw_path = get_weather_epw(tmyx_station, "tmyx", None, fetcher=fetcher)
    if leap_weather.is_leap(year):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="v2b_wx_") as tmp:
            leap_epw = leap_weather.make_leap_epw(epw_path, Path(tmp) / "weather.epw", year)
            wx = parse_epw_weather(leap_epw, year=year)
    else:
        wx = parse_epw_weather(epw_path, year=year)
    return perturb_weather_frame(wx, temp_offset_c, solar_scale, dewpoint_offset_c, wind_scale)
