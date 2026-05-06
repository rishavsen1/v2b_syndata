"""Per-session battery capacity inference + arrival SoC reconstruction.

D42 + D43: capacity inferred from userInputs.WhPerMile + kWhRequested when
available; falls back to 60 kWh otherwise. Arrival SoC = 1 - kWhRequested/capacity.
"""
from __future__ import annotations

from .feature_extractor import SessionFeatures

DEFAULT_CAPACITY_KWH = 60.0
WH_PER_MILE_SENTINEL = 299  # ACN-Data default placeholder; treat as missing.
INFERRED_MIN_KWH = 20.0
INFERRED_MAX_KWH = 130.0
RANGE_BUFFER_FACTOR = 1.5  # users typically don't request full battery


def infer_capacity(s: SessionFeatures) -> tuple[float, str]:
    """Returns (capacity_kwh, source) where source ∈ {'inferred', 'fallback'}."""
    if (
        s.wh_per_mile is None
        or int(s.wh_per_mile) == WH_PER_MILE_SENTINEL
        or s.miles_requested is None
        or s.kwh_requested is None
    ):
        return DEFAULT_CAPACITY_KWH, "fallback"

    inferred = RANGE_BUFFER_FACTOR * s.miles_requested * s.wh_per_mile / 1000.0
    if INFERRED_MIN_KWH < inferred < INFERRED_MAX_KWH:
        return float(inferred), "inferred"
    return DEFAULT_CAPACITY_KWH, "fallback"


def reconstruct_arrival_soc(s: SessionFeatures, capacity_kwh: float) -> float | None:
    """Returns arrival SoC fraction in [0, 1], or None if kwh_requested unavailable."""
    if s.kwh_requested is None or capacity_kwh <= 0:
        return None
    soc = 1.0 - s.kwh_requested / capacity_kwh
    return float(max(0.0, min(1.0, soc)))
