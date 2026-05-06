"""Occupancy injection preserves IDF validity (eppy round-trip)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.load_pipeline.occupancy_inject import (
    _hourly_profile,
    inject_occupancy,
)
from v2b_syndata.load_pipeline.prototypes import get_prototype_idf


@pytest.fixture
def small_office_idf():
    return get_prototype_idf("office", "small")


def _build_series(constant: float = 0.7) -> pd.Series:
    idx = pd.date_range("2020-04-01", "2020-04-08", freq="15min", inclusive="left")
    return pd.Series(constant, index=idx, name="occupancy")


def test_hourly_profile_constant_input():
    s = _build_series(0.5)
    weekday, weekend = _hourly_profile(s)
    assert len(weekday) == 24
    assert len(weekend) == 24
    assert all(abs(v - 0.5) < 1e-6 for v in weekday)
    assert all(abs(v - 0.5) < 1e-6 for v in weekend)


def test_inject_writes_file(tmp_path, small_office_idf):
    s = _build_series(0.6)
    out = tmp_path / "out.idf"
    result = inject_occupancy(small_office_idf, s, out)
    assert result == out
    assert out.exists()
    text = out.read_text()
    assert "BLDG_OCC_SCH" in text
    # Replacement block contains weekday hourly fractions of 0.6.
    assert "0.6000" in text


def test_inject_idf_parses_with_eppy(tmp_path, small_office_idf):
    """Modified IDF must still be a valid IDF (eppy parses it)."""
    s = _build_series(0.4)
    out = tmp_path / "round.idf"
    inject_occupancy(small_office_idf, s, out)

    from eppy.modeleditor import IDF

    # Locate the bundled Energy+.idd from the EnergyPlus install via env or
    # the ep_runner's discovery; failing those, skip the eppy validation.
    import os
    idd_candidates = []
    if "ENERGYPLUS_PATH" in os.environ:
        idd_candidates.append(Path(os.environ["ENERGYPLUS_PATH"]) / "Energy+.idd")
    idd_candidates.extend(
        Path(p) / "Energy+.idd"
        for p in [
            "/usr/local/EnergyPlus-26-1-0",
            "/usr/local/EnergyPlus-23-2-0",
            str(Path.home() / "opt" / "EnergyPlus-23.2.0-7636e6b3e9-Linux-Ubuntu22.04-x86_64"),
        ]
    )
    idd = next((c for c in idd_candidates if c.exists()), None)
    if idd is None:
        pytest.skip("Energy+.idd not found locally; skip eppy validation")

    IDF.setiddname(str(idd))
    parsed = IDF(str(out))
    schedules = parsed.idfobjects["Schedule:Compact".upper()]
    names = [s.Name for s in schedules]
    assert "BLDG_OCC_SCH" in names
