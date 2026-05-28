"""Calibration source registry. Selection key is `calibration_policy` in populations.yaml."""
from __future__ import annotations

from .acn import AcnSource
from .base import CalibrationSource
from .evwatts import EvWattsSource
from .inl import InlSource

CALIBRATION_SOURCES: dict[str, type[CalibrationSource]] = {
    "acn_data": AcnSource,
    "evwatts": EvWattsSource,
    "inl_ev_project": InlSource,
}

__all__ = [
    "CALIBRATION_SOURCES",
    "CalibrationSource",
    "AcnSource",
    "EvWattsSource",
    "InlSource",
]
