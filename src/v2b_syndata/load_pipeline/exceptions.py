"""Custom exceptions for the load pipeline."""
from __future__ import annotations


class LoadPipelineError(Exception):
    """Base for all load pipeline errors."""


class EnergyPlusBinaryNotFound(LoadPipelineError):
    """EnergyPlus binary could not be located. Install instructions in README."""

    def __init__(self, checked: list[str]) -> None:
        super().__init__(
            "EnergyPlus binary not found. Checked locations:\n  "
            + "\n  ".join(checked)
            + "\nInstall EnergyPlus and either add to PATH or set ENERGYPLUS_PATH."
        )
        self.checked = checked


class EnergyPlusRunFailed(LoadPipelineError):
    """EnergyPlus subprocess returned non-zero or produced no output."""


class WeatherStationNotFound(LoadPipelineError):
    """TMYx station could not be fetched."""

    def __init__(self, station: str, attempted_url: str) -> None:
        super().__init__(
            f"TMYx station {station!r} not found. Attempted: {attempted_url}"
        )
        self.station = station
        self.attempted_url = attempted_url
