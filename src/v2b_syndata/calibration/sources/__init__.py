"""Calibration source registry. Selection key is `calibration_policy` in populations.yaml."""
from __future__ import annotations

from .acn import AcnSource
from .base import CalibrationSource

CALIBRATION_SOURCES: dict[str, type[CalibrationSource]] = {
    "acn_data": AcnSource,
}

__all__ = ["CALIBRATION_SOURCES", "CalibrationSource", "AcnSource"]
