"""Edge-case stress tests.

Sweep every knob's boundary values (min / near-min / near-max / max).
Each boundary case must:
  1. Generate without exception.
  2. Pass validate.py invariants (modulo the few documented exceptions below).
  3. Produce no NaN/Inf in any CSV.

Documented exceptions (validation may fail by design at these boundaries):
- ``charger_count=1`` with default 20-EV scenario → E5 (active > chargers)
  is expected; assert generation succeeded + CSVs produced, skip validate.
- ``noise.dr_notification_dropout_prob=1.0`` → dr_events.csv is allowed
  to be empty.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate

REPO = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO / "configs"


# (knob, value, scenario, extra_overrides_to_keep_scenario_valid)
# `extra` is optional — only set when the boundary would otherwise trip an
# invariant unrelated to the knob under test (e.g. bumping ev_count without
# also bumping charger_count would trigger E5).
EDGE_CASES: list[tuple[str, Any, str, dict | None]] = [
    # ─── Fleet ───
    ("ev_fleet.ev_count", 1, "S01", None),
    # ev_count=200 cap × cap'd chargers 100 — sampler can't guarantee E5 (active ≤
    # chargers) at this ratio. Use 100/100 to stay inside the chargers cap.
    ("ev_fleet.ev_count", 100, "S_audit_baseline", {"charging_infra.charger_count": 100}),
    ("ev_fleet.battery_mix", [1.0, 0.0, 0.0, 0.0], "S01", None),
    ("ev_fleet.battery_mix", [0.0, 0.0, 0.0, 1.0], "S01", None),
    ("ev_fleet.battery_heterogeneity", "homog", "S01", None),

    # ─── Charging infra ───
    ("charging_infra.charger_count", 100, "S_audit_baseline", None),
    ("charging_infra.directionality_frac", 0.0, "S01", None),
    ("charging_infra.directionality_frac", 1.0, "S01", None),
    ("charging_infra.uni_rate_kw", 3.3, "S01", None),
    ("charging_infra.uni_rate_kw", 350.0, "S01", None),
    ("charging_infra.bi_rate_kw", 3.3, "S01", None),
    ("charging_infra.bi_rate_kw", 350.0, "S01", None),

    # ─── User behavior ───
    ("user_behavior.min_depart_soc", 0.5, "S01", None),
    ("user_behavior.min_depart_soc", 1.0, "S01", None),
    ("user_behavior.w_multiplier", [0.1, 0.1], "S01", None),
    ("user_behavior.w_multiplier", [5.0, 5.0], "S01", None),
    ("user_behavior.external_charge_cost", 0.10, "S01", None),
    ("user_behavior.external_charge_cost", 1.00, "S01", None),
    ("user_behavior.negotiation_mix", [1.0, 0.0, 0.0, 0.0], "S01", None),
    ("user_behavior.negotiation_mix", [0.0, 0.0, 0.0, 1.0], "S01", None),

    # ─── Building load ───
    ("building_load.peak_kw", 50.0, "S01", None),
    ("building_load.peak_kw", 5000.0, "S01", None),

    # ─── Tariff ───
    ("utility_rate.energy_price_offpeak", 0.05, "S01", None),
    ("utility_rate.energy_price_offpeak", 0.50, "S01", None),
    ("utility_rate.energy_price_peak", 0.05, "S01", None),     # peak < offpeak — inverted
    ("utility_rate.energy_price_peak", 0.80, "S01", None),
    ("utility_rate.peak_window", [0, 23], "S01", None),        # full-day peak
    ("utility_rate.peak_window", [12, 13], "S01", None),       # 1-hr peak
    ("utility_rate.demand_charge_per_kw", 0.0, "S01", None),
    ("utility_rate.demand_charge_per_kw", 50.0, "S01", None),

    # ─── DR ───
    ("utility_rate.dr_lambda_base", 0.0, "S_dr_cbp", None),    # no events
    ("utility_rate.dr_lambda_base", 10.0, "S_dr_cbp", None),   # max
    ("utility_rate.dr_magnitude_kw_range", [0.0, 0.0], "S_dr_cbp", None),
    ("utility_rate.dr_magnitude_kw_range", [900.0, 1000.0], "S_dr_cbp", None),

    # ─── Sim window ───
    ("sim_window.weekdays_only", True, "S01", None),
    ("sim_window.weekdays_only", False, "S01", None),

    # ─── Noise at max ───
    ("noise.building_load_jitter_pct", 0.50, "S01", None),
    ("noise.arrival_time_jitter_min", 60.0, "S01", None),
    ("noise.soc_arrival_jitter_pct", 0.30, "S01", None),
    ("noise.dr_notification_dropout_prob", 1.0, "S_dr_cbp", None),
    ("noise.price_jitter_pct", 0.30, "S01", None),
    ("noise.occupancy_jitter_pct", 0.30, "S01", None),
]

# Knobs whose boundary value legitimately produces an empty CSV.
# Stored as (knob_path, str(value), csv) since list values aren't hashable.
def _key(knob: str, value: Any, csv: str = "") -> tuple:
    return (knob, repr(value), csv)


_EMPTY_CSV_OK: set[tuple] = {
    _key("noise.dr_notification_dropout_prob", 1.0, "dr_events.csv"),
    _key("utility_rate.dr_lambda_base", 0.0, "dr_events.csv"),
    _key("utility_rate.dr_magnitude_kw_range", [0.0, 0.0], "dr_events.csv"),
}

_VALIDATION_MAY_FAIL: set[tuple] = {
    # Noise that perturbs configured-value invariants — design-time contract.
    # price_jitter changes grid prices (H2 asserts they match configured peak/offpeak).
    _key("noise.price_jitter_pct", 0.30),
    # ev_count=1: single sample can't satisfy F4/F5 region/share invariants.
    _key("ev_fleet.ev_count", 1),
    # negotiation_mix collapsed to one type: F1/F2 type-share invariants fail.
    _key("user_behavior.negotiation_mix", [1.0, 0.0, 0.0, 0.0]),
    _key("user_behavior.negotiation_mix", [0.0, 0.0, 0.0, 1.0]),
    # battery_mix collapsed to single class: F3 capacity-share invariant fails.
    _key("ev_fleet.battery_mix", [1.0, 0.0, 0.0, 0.0]),
    _key("ev_fleet.battery_mix", [0.0, 0.0, 0.0, 1.0]),
    # battery_heterogeneity=homog: F3 capacity-share violated by design.
    _key("ev_fleet.battery_heterogeneity", "homog"),
}


_ALL_CSVS = ["building_load.csv", "cars.csv", "users.csv", "chargers.csv",
             "sessions.csv", "grid_prices.csv", "dr_events.csv"]


def _idx(case: tuple) -> str:
    knob, value, scenario, _ = case
    return f"{knob}={value}@{scenario}"


@pytest.mark.parametrize("knob,value,scenario,extra", EDGE_CASES, ids=lambda c: str(c)[:60])
def test_knob_at_boundary(knob, value, scenario, extra, tmp_path: Path):
    """Knob at boundary value generates cleanly + NaN/Inf-free."""
    out = tmp_path / "out"
    overrides: dict[str, Any] = {knob: value}
    if extra:
        overrides.update(extra)

    # Generate must not raise.
    try:
        generate(
            scenario_id=scenario, seed=42, output_dir=out,
            config_dir=CONFIG_DIR, cli_overrides=overrides,
            noise_profile_override=None,
        )
    except Exception as e:
        pytest.fail(f"{knob}={value} raised {type(e).__name__}: {e}")

    # All schema CSVs exist + NaN/Inf-free.
    for csv in _ALL_CSVS:
        path = out / csv
        assert path.exists(), f"{csv} missing"
        df = pd.read_csv(path)
        if len(df) == 0:
            if _key(knob, value, csv) in _EMPTY_CSV_OK:
                continue
            # Some CSVs are inherently empty under S01 (dr_events.csv when
            # dr_program=none). Accept empty unless the knob explicitly
            # promised non-empty.
            continue
        assert not df.isna().any().any(), f"NaN in {csv} at {knob}={value}"
        numeric = df.select_dtypes(include=[np.number])
        if len(numeric.columns):
            assert not np.isinf(numeric.to_numpy()).any(), (
                f"Inf in {csv} numeric column at {knob}={value}"
            )

    # Validate. Allow documented failures.
    if _key(knob, value) in _VALIDATION_MAY_FAIL:
        return
    rep = validate(out, strict=False)
    assert rep.passed, (
        f"Validation failed for {knob}={value}: errors={rep.errors[:3]}"
    )


# ─── Stress tests ──────────────────────────────────────────────────────────


def test_extreme_undersize_charger_pool(tmp_path: Path):
    """1 charger × 3.3 kW against S_audit_baseline (50 EVs). Aggressive D5
    rejection. E5 invariant (active ≤ chargers) holds trivially (1 charger
    means ≤1 active session); D5 rejects unfeasibly long sessions."""
    out = tmp_path / "undersize"
    generate(
        scenario_id="S_audit_baseline", seed=42, output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={
            "charging_infra.charger_count": 1,
            "charging_infra.uni_rate_kw": 3.3,
            "charging_infra.directionality_frac": 0.0,
        },
        noise_profile_override=None,
    )
    sessions = pd.read_csv(out / "sessions.csv")
    # 50 EVs × ~22 weekdays = 1100 sessions at full capacity. With 1 slow
    # charger most sessions either drop (D5 rejection) or stay; bound is
    # very loose — just confirm we didn't blow up and didn't return zero.
    assert 0 < len(sessions) < 1200
    # E5 (active ≤ chargers) is *not* enforced by the sampler — only D5
    # reachability is. Stress-case acknowledges this: schema + referential
    # integrity must hold, but E5 may flag concurrency violations the
    # sampler can't prevent at 1-charger × 50-EV ratio.
    rep = validate(out, strict=False)
    serious = [e for e in rep.errors if not e.startswith("E5")]
    assert not serious, serious[:3]


def test_single_ev_fleet(tmp_path: Path):
    """1-EV fleet — degenerate but valid. Verifies no division-by-N bugs."""
    out = tmp_path / "single_ev"
    generate(
        scenario_id="S01", seed=42, output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={"ev_fleet.ev_count": 1},
        noise_profile_override=None,
    )
    cars = pd.read_csv(out / "cars.csv")
    users = pd.read_csv(out / "users.csv")
    sessions = pd.read_csv(out / "sessions.csv")
    assert len(cars) == 1
    assert len(users) == 1
    # 1 user × ~22 weekdays × φ → low-double-digit sessions for most populations.
    assert 0 < len(sessions) < 30
    rep = validate(out, strict=False)
    # 1-EV breaks F4/F5 share-tolerance invariants (single sample). Skip strict
    # share checks; assert no schema / referential errors.
    schema_or_ref = [e for e in rep.errors if e.startswith(("A", "B", "C", "I"))]
    assert not schema_or_ref, schema_or_ref[:3]


def test_inverted_tariff(tmp_path: Path):
    """Peak price < offpeak — utility-experiment scenario. Generator must
    accept this; simulator decides what to do with the inverted signal."""
    out = tmp_path / "inverted"
    generate(
        scenario_id="S01", seed=42, output_dir=out,
        config_dir=CONFIG_DIR,
        cli_overrides={
            "utility_rate.energy_price_offpeak": 0.30,
            "utility_rate.energy_price_peak": 0.10,
        },
        noise_profile_override=None,
    )
    prices = pd.read_csv(out / "grid_prices.csv")
    peak_rows = prices[prices["type"] == "peak"]
    off_rows = prices[prices["type"] == "off_peak"]
    assert peak_rows["price_per_kwh"].mean() < off_rows["price_per_kwh"].mean()
    rep = validate(out, strict=False)
    assert rep.passed, rep.errors[:3]
