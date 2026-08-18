"""Map users to regions along the φ axis. First-match by axes_distribution order.

κ was removed from assignment (2026-08): it was independent of every session
quantity (|spearman| ≤ 0.15), unused at generation, and the κ×φ rectangles
manufactured empty/degenerate cells (erratic: 0 users at every ACN site;
rare_inconsistent: 3). Regions are now φ bins; `consist` bounds in
axes_distribution are retained in YAML for schema stability but not read.
"""
from __future__ import annotations

from typing import Any

from .feature_extractor import UserFeatures


def assign_user_to_region(
    user: UserFeatures,
    axes_distribution: list[dict[str, Any]],
) -> str | None:
    """Return region name whose φ bin contains the user, or None if unassigned.

    Deterministic first-match per axes_distribution order. δ bounds are NOT
    used as a filter (commute-distance is a noisy proxy and may be unobserved);
    κ is not used at all (see module docstring).
    """
    for region in axes_distribution:
        phi_lo, phi_hi = region["freq"]
        if phi_lo <= user.phi <= phi_hi:
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
