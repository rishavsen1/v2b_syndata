"""Map users to regions in (φ, κ) space. First-match by axes_distribution order."""
from __future__ import annotations

from typing import Any

from .feature_extractor import UserFeatures


def assign_user_to_region(
    user: UserFeatures,
    axes_distribution: list[dict[str, Any]],
) -> str | None:
    """Return region name where user's (phi, kappa) falls, or None if unassigned.

    Deterministic first-match per axes_distribution order. δ bounds are NOT
    used as a filter (commute-distance is a noisy proxy and may be unobserved).
    """
    for region in axes_distribution:
        phi_lo, phi_hi = region["freq"]
        kap_lo, kap_hi = region["consist"]
        if phi_lo <= user.phi <= phi_hi and kap_lo <= user.kappa <= kap_hi:
            return str(region["name"])
    return None


def assign_users(
    users: list[UserFeatures],
    axes_distribution: list[dict[str, Any]],
) -> dict[str, list[UserFeatures]]:
    """Group users by assigned region. Unassigned users go under key '__unassigned__'."""
    out: dict[str, list[UserFeatures]] = {}
    for u in users:
        rname = assign_user_to_region(u, axes_distribution) or "__unassigned__"
        out.setdefault(rname, []).append(u)
    return out
