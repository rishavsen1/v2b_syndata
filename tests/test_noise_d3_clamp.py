"""B3 regression: noise on arrival_soc must clamp to [min_allowed_soc, max_allowed_soc].

Originally noise.py:73 clamped to [0, 100] (battery rails) which violated D3
when min_allowed_soc=10. Fix re-clamps per car using cars.csv bounds.
"""
from __future__ import annotations

from pathlib import Path

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate


CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


def test_noise_light_does_not_violate_d3(tmp_path):
    """Generate S01 with light_noise; validate must pass D3."""
    out = tmp_path / "out"
    generate(
        scenario_id="S01", seed=42,
        output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={},
        noise_profile_override="light_noise",
    )
    rep = validate(out, strict=False)
    d3_errors = [e for e in rep.errors if "D3:" in e]
    assert not d3_errors, f"D3 violations under light_noise: {d3_errors}"


def test_noise_realistic_does_not_violate_d3(tmp_path):
    out = tmp_path / "out"
    generate(
        scenario_id="S01", seed=42,
        output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={},
        noise_profile_override="realistic_noise",
    )
    rep = validate(out, strict=False)
    d3_errors = [e for e in rep.errors if "D3:" in e]
    assert not d3_errors, f"D3 violations under realistic_noise: {d3_errors}"


def test_noise_arrival_soc_within_per_car_bounds(tmp_path):
    """Stronger: every arrival_soc in [min_allowed_soc, max_allowed_soc] per car_id."""
    import pandas as pd
    out = tmp_path / "out"
    generate(
        scenario_id="S01", seed=42,
        output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={},
        noise_profile_override="light_noise",
    )
    sessions = pd.read_csv(out / "sessions.csv")
    cars = pd.read_csv(out / "cars.csv").set_index("car_id")
    for _, row in sessions.iterrows():
        car = cars.loc[int(row["car_id"])]
        assert car["min_allowed_soc"] <= row["arrival_soc"] <= car["max_allowed_soc"], \
            f"car {row['car_id']} arrival_soc={row['arrival_soc']} outside " \
            f"[{car['min_allowed_soc']}, {car['max_allowed_soc']}]"
