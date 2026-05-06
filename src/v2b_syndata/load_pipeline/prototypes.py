"""ASHRAE 90.1-2019 prototype IDF selection.

Files committed under ``data/prototypes/``. Climate-zone-specific PNNL files —
v1 ships the Denver (CZ 5B) variants per archetype. HVAC sizing is fixed by
the prototype; weather signal comes from the EPW. See DESIGN_NOTES § 12.
"""
from __future__ import annotations

from pathlib import Path

PROTOTYPE_MAP: dict[tuple[str, str], str] = {
    ("office", "small"): "ASHRAE901_OfficeSmall_STD2019_Denver.idf",
    ("office", "med"):   "ASHRAE901_OfficeMedium_STD2019_Denver.idf",
    ("office", "large"): "ASHRAE901_OfficeLarge_STD2019_Denver.idf",
    ("retail", "med"):   "ASHRAE901_RetailStripmall_STD2019_Denver.idf",
    ("retail", "large"): "ASHRAE901_RetailStandalone_STD2019_Denver.idf",
}

# People-fraction schedule names per prototype. The base schedule
# (``BLDG_OCC_SCH``) is reference material — but EP People objects reference
# the *_w_SB and *_wo_SB setback variants directly. Injecting only the base
# leaves the load unchanged. We replace all variants with the same profile.
OCCUPANCY_SCHEDULE_NAMES: dict[str, list[str]] = {
    "ASHRAE901_OfficeSmall_STD2019_Denver.idf":
        ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"],
    "ASHRAE901_OfficeMedium_STD2019_Denver.idf":
        ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"],
    "ASHRAE901_OfficeLarge_STD2019_Denver.idf":
        ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"],
    "ASHRAE901_RetailStripmall_STD2019_Denver.idf":
        ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"],
    "ASHRAE901_RetailStandalone_STD2019_Denver.idf":
        ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"],
}

DATA_DIR = Path(__file__).parent / "data" / "prototypes"


def get_prototype_idf(archetype: str, size: str) -> Path:
    """Return path to ASHRAE 90.1-2019 prototype IDF for ``(archetype, size)``.

    ``archetype="mixed"`` is composite-only — caller must run office + retail
    separately. ``ValueError`` on unknown combinations.
    """
    if archetype == "mixed":
        raise ValueError(
            "archetype='mixed' is a composite — caller must run office + retail "
            "and average. Use api.simulate_building_load instead."
        )
    key = (archetype, size)
    if key not in PROTOTYPE_MAP:
        raise ValueError(
            f"unknown (archetype, size)={key}. Known: {sorted(PROTOTYPE_MAP)}"
        )
    path = DATA_DIR / PROTOTYPE_MAP[key]
    if not path.exists():
        raise FileNotFoundError(
            f"prototype IDF missing on disk: {path}. Re-run install or check repo state."
        )
    return path


def get_occupancy_schedule_names(idf_filename: str) -> list[str]:
    """Return the occupancy-fraction schedule names to replace in a prototype.

    Includes base + setback variants. Falls back to the standard PNNL trio.
    """
    return OCCUPANCY_SCHEDULE_NAMES.get(
        idf_filename, ["BLDG_OCC_SCH", "BLDG_OCC_SCH_w_SB", "BLDG_OCC_SCH_wo_SB"]
    )


def get_occupancy_schedule_name(idf_filename: str) -> str:
    """Backwards-compatible single-name accessor; returns first entry."""
    return get_occupancy_schedule_names(idf_filename)[0]
