"""Tests for region_assignment (φ-only since 2026-08; κ removed)."""
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


def _user(phi):
    return UserFeatures(
        user_id="u", n_sessions=10, n_weekdays_observed=10,
        n_weekdays_total=20, phi=phi, delta_km=None,
    )


def test_assign_in_region():
    assert assign_user_to_region(_user(0.9), AXES) == "stable_commuter"


def test_assign_outside_all_regions():
    # 0.5 phi: not in stable_commuter [0.85,1] nor flexible_local [0.70,0.95]
    # nor occasional [0.05,0.20]
    assert assign_user_to_region(_user(0.5), AXES) is None


def test_assign_first_match_deterministic():
    # phi=0.85 matches stable_commuter [0.85,1] AND flexible_local [0.70,0.95];
    # first-match per AXES order = stable_commuter.
    assert assign_user_to_region(_user(0.85), AXES) == "stable_commuter"


def test_consist_bounds_are_ignored():
    # κ removed from assignment: a user lands in a region on φ alone even
    # though the region still declares consist bounds in YAML (schema kept).
    axes = [{"name": "only", "freq": [0.0, 1.0], "consist": [0.99, 1.0],
             "dist_km": [1, 2], "weight": 1.0}]
    assert assign_user_to_region(_user(0.1), axes) == "only"


def test_assign_users_groups():
    users = [_user(0.9), _user(0.8), _user(0.5)]
    grouped = assign_users(users, AXES)
    assert len(grouped["stable_commuter"]) == 1
    assert len(grouped["flexible_local"]) == 1
    assert len(grouped["__unassigned__"]) == 1
