"""Opt-in SoC chain (user_behavior.soc_chain_enforce).

Default off → byte-identical sessions.csv (the knob must not disturb the RNG
stream). On → every non-first session's arrival_soc is strictly below the SoC
the car departed with, and previous_day_external_use_soc equals that gap,
landing in the [draw_min, draw_max] band except when the car's min_allowed_soc
clamp compresses it.
"""
from __future__ import annotations

import filecmp

import pandas as pd

_CHAIN_ON = {"user_behavior.soc_chain_enforce": True}


def test_default_off_bit_identical(fast_generate):
    """Explicit false + default draw bounds == not setting the knobs at all."""
    out_default, _ = fast_generate(seed=123)
    out_explicit, _ = fast_generate(seed=123, overrides={
        "user_behavior.soc_chain_enforce": False,
        "user_behavior.soc_chain_draw_min": 0.10,
        "user_behavior.soc_chain_draw_max": 0.50,
    })
    assert filecmp.cmp(out_default / "sessions.csv",
                       out_explicit / "sessions.csv", shallow=False)


def test_chain_arrival_below_prior_departure(fast_generate):
    """Chain on: arrival_soc < prior required_soc_at_depart for every
    non-first session; external use == the gap, in [10, 50] unless the
    min_allowed_soc clamp bit."""
    out, _ = fast_generate(seed=123, overrides=_CHAIN_ON)
    sessions = pd.read_csv(out / "sessions.csv")
    cars = pd.read_csv(out / "cars.csv").set_index("car_id")
    assert len(sessions), "no sessions generated"

    n_chained = 0
    for car_id, grp in sessions.groupby("car_id"):
        grp = grp.sort_values("arrival")
        min_allowed = float(cars.loc[car_id, "min_allowed_soc"])
        prior_req = None
        for _, s in grp.iterrows():
            if prior_req is None:
                assert s["previous_day_external_use_soc"] == 0.0
            else:
                n_chained += 1
                assert s["arrival_soc"] < prior_req, (car_id, s["session_id"])
                gap = prior_req - s["arrival_soc"]
                assert abs(s["previous_day_external_use_soc"] - gap) < 1e-9
                clamped = abs(s["arrival_soc"] - min_allowed) < 1e-9
                assert (10.0 - 1e-9 <= gap <= 50.0 + 1e-9) or clamped, (
                    car_id, s["session_id"], gap, clamped)
            prior_req = float(s["required_soc_at_depart"])
    assert n_chained > 0, "window produced no multi-session cars"


def test_chain_band_override(fast_generate):
    """Narrowing the draw band narrows the realized external-use spread."""
    out, _ = fast_generate(seed=123, overrides={
        **_CHAIN_ON,
        "user_behavior.soc_chain_draw_min": 0.20,
        "user_behavior.soc_chain_draw_max": 0.25,
    })
    sessions = pd.read_csv(out / "sessions.csv")
    cars = pd.read_csv(out / "cars.csv").set_index("car_id")
    ext = []
    for car_id, grp in sessions.groupby("car_id"):
        grp = grp.sort_values("arrival")
        min_allowed = float(cars.loc[car_id, "min_allowed_soc"])
        for i, (_, s) in enumerate(grp.iterrows()):
            if i == 0:
                continue
            if abs(s["arrival_soc"] - min_allowed) < 1e-9:
                continue  # clamped — outside the pure-draw band by design
            ext.append(float(s["previous_day_external_use_soc"]))
    assert ext, "no unclamped chained sessions"
    assert min(ext) >= 20.0 - 1e-9 and max(ext) <= 25.0 + 1e-9, (min(ext), max(ext))


def test_chain_bad_band_raises(fast_generate):
    import pytest
    with pytest.raises(ValueError, match="soc_chain_draw_min"):
        fast_generate(seed=123, overrides={
            **_CHAIN_ON,
            "user_behavior.soc_chain_draw_min": 0.60,
            "user_behavior.soc_chain_draw_max": 0.40,
        })
