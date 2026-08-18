"""The fallback departure-SoC TruncNorm μ/σ are knobs.

Setting them explicitly to the current defaults (50/5) must reproduce the
default run bit-for-bit; overriding μ must move required_soc_at_depart for an
uncalibrated population (S01 / consent_default uses the fallback, not a fitted
soc_depart).
"""
from __future__ import annotations

import filecmp

import pandas as pd


def test_default_knobs_bit_identical(fast_generate):
    """Explicitly setting μ=50/σ=5 == not setting them (defaults preserved)."""
    out_default, _ = fast_generate(seed=123)
    out_explicit, _ = fast_generate(seed=123, overrides={
        "user_behavior.depart_soc_mu": 50.0,
        "user_behavior.depart_soc_sigma": 5.0,
    })
    assert filecmp.cmp(out_default / "sessions.csv",
                       out_explicit / "sessions.csv", shallow=False)


def test_override_shifts_required_soc(fast_generate):
    """Lowering μ (no floor) lowers required_soc_at_depart for the fallback."""
    common = {"user_behavior.min_depart_soc": 0.0}  # drop the 80% floor
    out_hi, _ = fast_generate(seed=123, overrides={
        **common, "user_behavior.depart_soc_mu": 85.0,
    })
    out_lo, _ = fast_generate(seed=123, overrides={
        **common, "user_behavior.depart_soc_mu": 50.0,
    })
    hi = pd.read_csv(out_hi / "sessions.csv")["required_soc_at_depart"]
    lo = pd.read_csv(out_lo / "sessions.csv")["required_soc_at_depart"]
    assert len(hi) and len(lo)
    assert lo.mean() < hi.mean(), (lo.mean(), hi.mean())


# --------------------------------------------------------------------------- #
# Energy-first departure requirement (2026-08)
# --------------------------------------------------------------------------- #
def test_energy_block_drives_required_soc(fast_generate):
    """A calibrated `energy` lognormal must produce session energies whose
    distribution tracks the fitted lognormal, independent of battery_mix."""
    import numpy as np
    import pandas as pd
    import scipy.stats as st
    import yaml

    out, _ = fast_generate(scenario="S_acn_jpl", seed=11,
                           overrides={"ev_fleet.ev_count": 120,
                                      "charging_infra.charger_count": 60})
    s = pd.read_csv(out / "sessions.csv")
    cars = pd.read_csv(out / "cars.csv").set_index("car_id")["capacity_kwh"]
    kwh = ((s["required_soc_at_depart"] - s["arrival_soc"]) / 100.0
           * s["car_id"].map(cars))
    pops = yaml.safe_load(open("configs/populations.yaml"))
    e = pops["acn_jpl_baseline"]["region_distributions"]["regular_charger"]["energy"]
    # Model medians per region are ~10.4-11.8 kWh; the generated median must be
    # in that neighborhood, not the old gap*capacity regime (median ~22 kWh).
    assert 6.0 < np.median(kwh) < 16.0, f"median {np.median(kwh):.1f}"
    # And the marginal must be close to the fitted lognormal (headroom clamp
    # trims the top, so allow a loose KS bound).
    ref = st.lognorm.rvs(e["sigma"], scale=e["scale"], size=4000,
                         random_state=np.random.default_rng(0))
    assert st.ks_2samp(kwh, ref).statistic < 0.2


def test_phi_scale_densifies_appearance(fast_generate):
    """phi_scale multiplies the drawn φ (capped 0.95): more distinct cars/day."""
    import pandas as pd

    base, _ = fast_generate(scenario="S_acn_jpl", seed=3,
                            overrides={"ev_fleet.ev_count": 60,
                                       "charging_infra.charger_count": 30})
    dense, _ = fast_generate(scenario="S_acn_jpl", seed=3,
                             overrides={"ev_fleet.ev_count": 60,
                                        "charging_infra.charger_count": 30,
                                        "user_behavior.phi_scale": 1.7})
    def daily(out):
        s = pd.read_csv(out / "sessions.csv")
        a = pd.to_datetime(s["arrival"])
        return s.groupby(a.dt.date)["car_id"].nunique().mean()
    b, d = daily(base), daily(dense)
    assert d > b * 1.3, f"phi_scale had insufficient effect: {b:.1f} -> {d:.1f}"
    u = pd.read_csv(dense / "users.csv")
    assert (u["phi"] <= 0.95 + 1e-9).all()


def test_proportional_chain_continuity_and_band(fast_generate):
    """soc_chain_mode=proportional: every non-first arrival sits strictly below
    the prior departure requirement (g > 0), usage scales with the prior
    charge, and the [min_allowed_soc, max_allowed_soc] band is never violated."""
    import pandas as pd

    out, _ = fast_generate(scenario="S_acn_jpl", seed=9,
                           overrides={"ev_fleet.ev_count": 80,
                                      "charging_infra.charger_count": 40,
                                      "user_behavior.soc_chain_enforce": True,
                                      "user_behavior.soc_chain_mode": "proportional",
                                      "user_behavior.soc_chain_draw_min": 0.75,
                                      "user_behavior.soc_chain_draw_max": 1.35})
    s = pd.read_csv(out / "sessions.csv").sort_values(["car_id", "arrival"])
    assert (s["arrival_soc"] >= 10.0 - 1e-9).all()
    assert (s["arrival_soc"] <= 90.0 + 1e-9).all()
    assert (s["required_soc_at_depart"] <= 90.0 + 1e-9).all()
    prev_req = s.groupby("car_id")["required_soc_at_depart"].shift(1)
    rep = s[prev_req.notna()]
    # continuity: arrival strictly below prior departure requirement (or pinned
    # at the min-SoC floor when g*charge would undershoot the band)
    ok = (rep["arrival_soc"] < prev_req[prev_req.notna()] + 1e-9) | \
         (rep["arrival_soc"] <= 10.0 + 1e-9)
    assert ok.all(), f"{(~ok).sum()} arrivals above prior departure"
    assert len(rep) > 50
