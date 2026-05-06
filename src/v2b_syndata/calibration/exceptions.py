"""Calibration-specific exceptions."""
from __future__ import annotations


class CalibrationError(RuntimeError):
    pass


class InsufficientSamplesError(CalibrationError):
    pass
