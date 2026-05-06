"""TMYx weather fetcher with local cache. AMY code path stub (D37)."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Callable

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
