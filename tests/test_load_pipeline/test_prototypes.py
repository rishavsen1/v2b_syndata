"""Prototype mapping + file existence."""
from __future__ import annotations

import pytest

from v2b_syndata.load_pipeline.prototypes import (
    PROTOTYPE_MAP,
    get_occupancy_schedule_name,
    get_prototype_idf,
)


def test_all_mapped_idfs_exist():
    for key, fname in PROTOTYPE_MAP.items():
        path = get_prototype_idf(*key)
        assert path.exists(), f"missing IDF for {key}: {path}"
        assert path.name == fname


def test_unknown_combination_raises():
    with pytest.raises(ValueError, match="unknown"):
        get_prototype_idf("office", "tiny")


def test_mixed_archetype_raises():
    with pytest.raises(ValueError, match="composite"):
        get_prototype_idf("mixed", "med")


def test_occupancy_schedule_name_default():
    # Known prototype.
    assert get_occupancy_schedule_name(
        "ASHRAE901_OfficeSmall_STD2019_Denver.idf"
    ) == "BLDG_OCC_SCH"
    # Unknown filename falls back to BLDG_OCC_SCH.
    assert get_occupancy_schedule_name("nonexistent.idf") == "BLDG_OCC_SCH"
