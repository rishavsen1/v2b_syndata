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
    """Estimate arrival SoC from the normal prior — uniformly, for every source.

    No charging dataset records SoC. Deriving it from ``kWhRequested`` as
    ``1 - kWhRequested/capacity`` assumes the request tops the car to a full
    charge, which the data contradicts (ACN delivered/requested ≈ 0.58, and the
    1-req/cap arrival clusters implausibly near 1.0 for small requests). So
    arrival SoC is treated as *unobserved* and drawn from a shared prior for all
    sources; ``kWhRequested`` is used only for capacity inference, and the real
    per-session signal (delivered energy) drives the departure SoC. Returns
    ``None`` if capacity is invalid or no seeded ``rng`` is supplied.
    """
    if capacity_kwh <= 0 or rng is None:
        return None
    soc = float(rng.normal(ARRIVAL_SOC_PRIOR_MEAN, ARRIVAL_SOC_PRIOR_STD))
    return max(ARRIVAL_SOC_PRIOR_LO, min(ARRIVAL_SOC_PRIOR_HI, soc))
