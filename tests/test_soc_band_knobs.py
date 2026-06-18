"""ev_fleet.min_allowed_soc / max_allowed_soc apply a fleet-wide SoC band.

Defaults (10/100) match the per-battery-class spec, so output is bit-identical;
overriding them rewrites every row of cars.csv.
"""
from __future__ import annotations

import filecmp

import pandas as pd


def test_default_band_unchanged(fast_generate):
    out, _ = fast_generate(seed=5, overrides={"ev_fleet.ev_count": 8})
    cars = pd.read_csv(out / "cars.csv")
    assert sorted(cars["min_allowed_soc"].unique()) == [10.0]
    assert sorted(cars["max_allowed_soc"].unique()) == [100.0]


def test_override_band_applies_to_all_cars(fast_generate):
    out, _ = fast_generate(seed=5, overrides={
        "ev_fleet.ev_count": 8,
        "ev_fleet.min_allowed_soc": 25.0,
        "ev_fleet.max_allowed_soc": 85.0,
    })
    cars = pd.read_csv(out / "cars.csv")
    assert sorted(cars["min_allowed_soc"].unique()) == [25.0]
    assert sorted(cars["max_allowed_soc"].unique()) == [85.0]


def test_explicit_default_is_bit_identical(fast_generate):
    a, _ = fast_generate(seed=5, overrides={"ev_fleet.ev_count": 8})
    b, _ = fast_generate(seed=5, overrides={
        "ev_fleet.ev_count": 8,
        "ev_fleet.min_allowed_soc": 10.0,
        "ev_fleet.max_allowed_soc": 100.0,
    })
    for name in ("cars.csv", "sessions.csv"):
        assert filecmp.cmp(a / name, b / name, shallow=False), name
