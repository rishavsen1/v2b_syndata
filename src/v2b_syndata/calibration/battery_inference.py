"""Per-session battery capacity inference + arrival SoC reconstruction.

D42 + D43: capacity inferred from userInputs.WhPerMile + kWhRequested when
available; falls back to 60 kWh otherwise. Arrival SoC = 1 - kWhRequested/capacity.

Only ACN-Data records requested energy. For sources that log delivered energy
but no request (ElaadNL, EV WATTS, INL), arrival SoC cannot be reconstructed
directly, so it is estimated from a normal prior (see ARRIVAL_SOC_PRIOR_*); the
departure-SoC requirement is then arrival + delivered/capacity, the same as for
ACN. Pass a seeded ``rng`` to enable the estimate (keeps calibration reproducible).
"""
from __future__ import annotations

import numpy as np

from .feature_extractor import SessionFeatures

DEFAULT_CAPACITY_KWH = 60.0
WH_PER_MILE_SENTINEL = 299  # ACN-Data default placeholder; treat as missing.
INFERRED_MIN_KWH = 20.0
INFERRED_MAX_KWH = 130.0
RANGE_BUFFER_FACTOR = 1.5  # users typically don't request full battery

# Arrival-SoC prior for sources lacking requested energy. Mean matches the
# model's default arrival distribution (Beta(4, 6) ⇒ E≈0.40).
ARRIVAL_SOC_PRIOR_MEAN = 0.40
ARRIVAL_SOC_PRIOR_STD = 0.15
ARRIVAL_SOC_PRIOR_LO = 0.05
ARRIVAL_SOC_PRIOR_HI = 0.95


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


def reconstruct_arrival_soc(
    s: SessionFeatures,
    capacity_kwh: float,
    rng: np.random.Generator | None = None,
) -> float | None:
    """Returns arrival SoC fraction in [0, 1], or None if it cannot be obtained.

    With ``kwh_requested`` (ACN): exact, ``1 - kWhRequested/capacity``.
    Without it but with a seeded ``rng``: estimated from the normal arrival-SoC
    prior (sources that log delivered energy only). ``None`` if capacity is
    invalid, or if requested is missing and no ``rng`` was supplied.
    """
    if capacity_kwh <= 0:
        return None
    if s.kwh_requested is not None:
        soc = 1.0 - s.kwh_requested / capacity_kwh
        return float(max(0.0, min(1.0, soc)))
    if rng is None:
        return None
    soc = float(rng.normal(ARRIVAL_SOC_PRIOR_MEAN, ARRIVAL_SOC_PRIOR_STD))
    return max(ARRIVAL_SOC_PRIOR_LO, min(ARRIVAL_SOC_PRIOR_HI, soc))
