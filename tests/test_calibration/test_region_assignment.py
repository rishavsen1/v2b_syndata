"""Tests for region_assignment."""
from __future__ import annotations

from v2b_syndata.calibration.feature_extractor import UserFeatures
from v2b_syndata.calibration.region_assignment import (
    assign_user_to_region,
    assign_users,
)


AXES = [
    {"name": "stable_commuter", "freq": [0.85, 1.00], "consist": [0.75, 1.00],
     "dist_km": [40, 80], "weight": 0.4},
    {"name": "flexible_local", "freq": [0.70, 0.95], "consist": [0.50, 0.80],
     "dist_km": [5, 15], "weight": 0.3},
    {"name": "occasional", "freq": [0.05, 0.20], "consist": [0.10, 0.40],
     "dist_km": [3, 50], "weight": 0.3},
]


def _user(phi, kappa):
    return UserFeatures(
        user_id="u", n_sessions=10, n_weekdays_observed=10,
        n_weekdays_total=20, phi=phi, kappa=kappa, delta_km=None,
    )


def test_assign_in_region():
    u = _user(0.9, 0.85)
    assert assign_user_to_region(u, AXES) == "stable_commuter"


def test_assign_outside_all_regions():
    u = _user(0.5, 0.5)
    # 0.5 phi: not in stable_commuter [0.85,1] nor flexible_local [0.70,0.95]
    # nor occasional [0.05,0.20]
    assert assign_user_to_region(u, AXES) is None


def test_assign_first_match_deterministic():
    # phi=0.85, kappa=0.78 → matches stable_commuter [0.85,1]×[0.75,1]
    # Also matches flexible_local [0.70,0.95]×[0.50,0.80] at the boundary.
    # First-match per AXES order = stable_commuter.
    u = _user(0.85, 0.78)
    assert assign_user_to_region(u, AXES) == "stable_commuter"


def test_assign_users_groups():
    users = [_user(0.9, 0.9), _user(0.8, 0.6), _user(0.5, 0.5)]
    grouped = assign_users(users, AXES)
    assert len(grouped["stable_commuter"]) == 1
    assert len(grouped["flexible_local"]) == 1
    assert len(grouped["__unassigned__"]) == 1
