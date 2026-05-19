"""Runner sim_window edge cases + defensive raises."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_custom_sim_window_requires_start_and_end(tmp_path: Path, config_dir: Path):
    """mode=custom without sim_window.start + custom_end raises ValueError."""
    from v2b_syndata.runner import generate
    with pytest.raises(ValueError, match="custom"):
        generate(
            scenario_id="S01", seed=42,
            output_dir=tmp_path / "out",
            config_dir=config_dir,
            cli_overrides={"sim_window.mode": "custom"},
            noise_profile_override=None,
        )


def test_unknown_sim_window_mode_raises(tmp_path: Path, config_dir: Path):
    """Unknown mode value raises KnobValidationError from registry check
    (before runner's mode dispatch)."""
    from v2b_syndata.knob_loader import KnobValidationError
    from v2b_syndata.runner import generate
    with pytest.raises(KnobValidationError, match="not in"):
        generate(
            scenario_id="S01", seed=42,
            output_dir=tmp_path / "out",
            config_dir=config_dir,
            cli_overrides={"sim_window.mode": "fortnightly"},
            noise_profile_override=None,
        )


def test_full_year_sim_window_succeeds(tmp_path: Path, config_dir: Path):
    """mode=full_year produces a full-year output without explicit dates."""
    from v2b_syndata.runner import generate
    m = generate(
        scenario_id="S01", seed=42,
        output_dir=tmp_path / "out",
        config_dir=config_dir,
        cli_overrides={"sim_window.mode": "full_year"},
        noise_profile_override=None,
    )
    assert m["scenario_id"] == "S01"
    import pandas as pd
    bl = pd.read_csv(tmp_path / "out" / "building_load.csv")
    # 2020 is a leap year — 366 days × 96 quarter-hours = 35136 rows.
    assert len(bl) == 35136
