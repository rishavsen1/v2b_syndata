"""Calibration source registry. Selection key is `calibration_policy` in populations.yaml."""
from __future__ import annotations

from .acn import AcnSource
from .base import CalibrationSource
from .evwatts import EvWattsSource

CALIBRATION_SOURCES: dict[str, type[CalibrationSource]] = {
    "acn_data": AcnSource,
    "evwatts": EvWattsSource,
}

__all__ = ["CALIBRATION_SOURCES", "CalibrationSource", "AcnSource", "EvWattsSource"]
