"""Pipeline-specific fixtures and helpers.

The repo-wide ``stub_load_pipeline`` autouse fixture is harmless here — these
tests exercise the load_pipeline modules directly without invoking the
high-level ``simulate_building_load`` they patch.
"""
from __future__ import annotations

import pytest

from v2b_syndata.load_pipeline.exceptions import EnergyPlusBinaryNotFound


def _has_energyplus() -> bool:
    try:
        from v2b_syndata.load_pipeline.ep_runner import discover_energyplus

        discover_energyplus()
        return True
    except EnergyPlusBinaryNotFound:
        return False


HAS_ENERGYPLUS = _has_energyplus()
skip_if_no_energyplus = pytest.mark.skipif(
    not HAS_ENERGYPLUS, reason="EnergyPlus binary not installed/runnable"
)
