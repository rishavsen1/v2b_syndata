"""ACN-Data calibration: fit per-region distribution parameters.

Offline pipeline. Not invoked at generation time. See `api.calibrate_populations`.
"""
from __future__ import annotations

from .api import calibrate_populations
from .exceptions import CalibrationError

__all__ = ["calibrate_populations", "CalibrationError"]
