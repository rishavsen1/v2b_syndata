"""user_behavior.dwell_clip_lo / dwell_clip_hi (2026-08).

The dwell clip was hardcoded 0.5 / 14.0 in sessions_dist.py. It is a hard
truncation that shows up in the generated data as a density spike at the clip
point, so it is now a registered knob and lands in the manifest. Defaults
reproduce the old constants exactly (bitwise-identical existing scenarios).
"""
from __future__ import annotations

import pandas as pd

from v2b_syndata.knob_loader import load_knob_registry


def test_clip_knobs_registered_with_legacy_defaults(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    assert reg["user_behavior.dwell_clip_lo"]["default"] == 0.5
    assert reg["user_behavior.dwell_clip_hi"]["default"] == 14.0


def _dwell_hours(out_dir):
    return pd.read_csv(out_dir / "sessions.csv")["duration_sec"] / 3600.0


def test_default_clip_matches_legacy_constant(fast_generate):
    out, _ = fast_generate(scenario="S_acn_caltech", seed=5)
    assert _dwell_hours(out).max() <= 14.0 + 1e-9


def test_clip_hi_override_truncates_dwell(fast_generate):
    """Lowering the knob must bind: the same seed's long tail is cut off.

    Asserted downward rather than upward because a 7-day window rarely draws a
    dwell past 14 h, so raising the clip is not observable in a fast fixture.
    """
    base, _ = fast_generate(scenario="S_acn_caltech", seed=5)
    tight, _ = fast_generate(scenario="S_acn_caltech", seed=5,
                             overrides={"user_behavior.dwell_clip_hi": 6.0})
    assert _dwell_hours(base).max() > 6.0  # tail exists at the default clip
    assert _dwell_hours(tight).max() <= 6.0 + 1e-9


def test_clip_knob_recorded_in_manifest(fast_generate):
    _, manifest = fast_generate(scenario="S_acn_caltech", seed=5)
    assert "user_behavior.dwell_clip_hi" in manifest["knob_resolution"]
    assert "user_behavior.dwell_clip_lo" in manifest["knob_resolution"]
