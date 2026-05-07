"""Tests for sessions_dist per-leaf fallback chain (C3) +
override-on-calibrated-leaf manifest stamp.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2b_syndata.samplers.sessions_dist import sample_f_arr, sample_f_dwell, sample_f_soc
from v2b_syndata.types import (
    FleetAttrs,
    KnobValue,
    ResolvedKnobs,
    RootBundle,
    ScenarioContext,
    UserAttrs,
)


def _build_ctx(region_distributions: dict) -> ScenarioContext:
    """Construct a ScenarioContext just rich enough for f_arr/f_dwell/f_soc samplers."""
    knobs = ResolvedKnobs()
    knobs.values["user_behavior.min_depart_soc"] = KnobValue(value=0.8, source="default")

    roots = RootBundle(
        C="temperate",
        W={"lat": 36.0, "lon": -86.0, "year": 2020},
        A="office", S="med", O="ashrae_90_1_office",
        T={"tariff_type": "TOU", "energy_price_offpeak": 0.137,
           "energy_price_peak": 0.178, "peak_window": [14, 19],
           "demand_charge_per_kw": 11.67, "dr_program": "none",
           "dr_magnitude_kw_range": [50.0, 200.0], "dr_lambda_base": 0.05},
        U={
            "axes_distribution": [],
            "negotiation_mix": [0.107, 0.536, 0.321, 0.036],
            "w_multiplier": [1.0, 1.0],
            "min_depart_soc": 0.8,
            "external_charge_cost": 0.3,
            "menu_levels": [[0.0, 0]],
            "region_distributions": region_distributions,
        },
        F={"ev_count": 1, "battery_mix": [0.2, 0.3, 0.4, 0.1],
           "battery_heterogeneity": "het"},
        X={"charger_count": 1, "directionality_frac": 0.5,
           "uni_rate_kw": 20.0, "bi_rate_kw": 20.0},
    )
    ctx = ScenarioContext(scenario_id="S01", seed=42, knobs=knobs, roots=roots)
    ctx.a_user = {1: UserAttrs(
        car_id=1, region="stable_commuter", phi=0.9, kappa=0.85,
        delta_km=50.0, negotiation_type="type_ii", w1=0.01, w2=0.05,
    )}
    ctx.a_fleet = {1: FleetAttrs(
        car_id=1, battery_class="m3_75", capacity_kwh=75.0,
        min_allowed_soc=10.0, max_allowed_soc=100.0,
    )}
    return ctx


def test_partial_fallback_calibrated_k_placeholder_lambda():
    """region_distributions has dwell.k but NOT dwell.lambda → use calibrated k,
    placeholder λ = 8 * (0.5 + φ)."""
    rd = {"stable_commuter": {"dwell": {"k": 2.5}}}
    ctx = _build_ctx(rd)
    sample_f_dwell(ctx)
    p = ctx.latents["f_dwell"][1]
    assert p["k"] == 2.5  # calibrated
    expected_lam = 8.0 * (0.5 + 0.9)  # placeholder formula with phi=0.9
    assert abs(p["lam"] - expected_lam) < 1e-9
    assert p["rho"] == 0.0  # placeholder default


def test_partial_fallback_calibrated_lambda_placeholder_k():
    rd = {"stable_commuter": {"dwell": {"lambda": 12.0}}}
    ctx = _build_ctx(rd)
    sample_f_dwell(ctx)
    p = ctx.latents["f_dwell"][1]
    assert p["k"] == 2.0  # placeholder
    assert p["lam"] == 12.0  # calibrated


def test_full_calibration_no_fallback():
    rd = {"stable_commuter": {
        "arrival": {"mu": 8.7, "sigma": 0.6},
        "dwell": {"k": 2.1, "lambda": 9.2},
        "soc_arrival": {"alpha": 4.5, "beta": 6.1},
        "copula": {"rho_gaussian": -0.187},
    }}
    ctx = _build_ctx(rd)
    sample_f_arr(ctx)
    sample_f_dwell(ctx)
    sample_f_soc(ctx)
    arr = ctx.latents["f_arr"][1]
    dw = ctx.latents["f_dwell"][1]
    so = ctx.latents["f_soc"][1]
    assert arr["mu"] == 8.7
    assert arr["sigma"] == 0.6
    assert dw["k"] == 2.1
    assert dw["lam"] == 9.2  # YAML lambda → runtime lam
    assert dw["rho"] == -0.187  # YAML rho_gaussian → runtime rho
    assert so["alpha"] == 4.5
    assert so["beta"] == 6.1


def test_no_calibration_all_placeholders():
    """Empty region_distributions → all placeholder formulas."""
    ctx = _build_ctx({})
    sample_f_arr(ctx)
    sample_f_dwell(ctx)
    sample_f_soc(ctx)
    arr = ctx.latents["f_arr"][1]
    dw = ctx.latents["f_dwell"][1]
    so = ctx.latents["f_soc"][1]
    assert arr["mu"] == 8.5
    assert abs(arr["sigma"] - 2.0 * (1.0 - 0.85)) < 1e-9  # 2*(1-κ)
    assert dw["k"] == 2.0
    assert abs(dw["lam"] - 8.0 * (0.5 + 0.9)) < 1e-9
    assert dw["rho"] == 0.0
    assert so["alpha"] == 4.0
    assert so["beta"] == 6.0


def test_user_in_uncalibrated_region_falls_back():
    """User assigned to a region with no calibrated entry → placeholders apply."""
    rd = {"stable_commuter": {"dwell": {"k": 2.5, "lambda": 12.0}}}
    ctx = _build_ctx(rd)
    # Reassign user to uncalibrated region
    ctx.a_user[1] = UserAttrs(
        car_id=1, region="flexible_local", phi=0.7, kappa=0.6,
        delta_km=10.0, negotiation_type="type_ii", w1=0.01, w2=0.05,
    )
    sample_f_dwell(ctx)
    p = ctx.latents["f_dwell"][1]
    assert p["k"] == 2.0  # placeholder
    assert abs(p["lam"] - 8.0 * (0.5 + 0.7)) < 1e-9


def test_override_on_calibrated_leaf_manifest_stamp(tmp_path: Path):
    """End-to-end: calibrated populations.yaml entry + CLI override on one leaf
    must produce manifest source='explicit' for the override path while OTHER
    calibrated leaves keep source=calibration:..."""
    # Inject a synthetic calibration block, then override one leaf.
    pops_path = Path(__file__).resolve().parent.parent / "configs" / "populations.yaml"
    backup = pops_path.read_text()

    from v2b_syndata.calibration.writer import write_region_distributions
    fits = {
        "stable_commuter": {
            "arrival": {"mu": 8.7, "sigma": 0.6, "n_samples": 100, "ks_fit_quality": 0.05},
            "dwell": {"k": 2.1, "lambda": 9.2, "n_samples": 100, "ks_fit_quality": 0.06},
        },
    }
    metadata = {"source": "calibration:acn_data_2019_2021_test"}

    # Step 5.5 policy split: consent_default is now synthetic. To exercise the
    # acn_data path we inject onto acn_workplace_baseline.
    fits_acn = {
        "regular_charger": {
            "arrival": {"mu": 8.7, "sigma": 0.6, "n_samples": 100, "ks_fit_quality": 0.05},
            "dwell": {"k": 2.1, "lambda": 9.2, "n_samples": 100, "ks_fit_quality": 0.06},
        },
    }
    try:
        write_region_distributions(pops_path, "acn_workplace_baseline", fits_acn, metadata)

        # Build an audit scenario that uses acn_workplace_baseline (S01 uses consent_default).
        scen_path = pops_path.parent / "scenarios" / "audit_acn.yaml"
        scen_path.write_text(
            "scenario_id: audit_acn\n"
            "description: audit\n"
            "descriptors:\n"
            "  location: nashville_tn\n"
            "  building: medium_office_v1\n"
            "  population: acn_workplace_baseline\n"
            "  equipment: balanced_50pct\n"
            "  noise: clean\n"
        )
        try:
            from v2b_syndata.runner import generate
            out_dir = tmp_path / "out"
            manifest = generate(
                scenario_id="audit_acn", seed=42,
                output_dir=out_dir,
                config_dir=Path(__file__).resolve().parent.parent / "configs",
                cli_overrides={
                    "user_behavior.region_distributions.regular_charger.dwell.lambda": 15.0,
                },
                noise_profile_override=None,
            )
            res = manifest["knob_resolution"]
            ov_key = "user_behavior.region_distributions.regular_charger.dwell.lambda"
            assert res[ov_key]["value"] == 15.0
            assert res[ov_key]["source"] == "explicit"
            cal_key = "user_behavior.region_distributions.regular_charger.arrival.mu"
            assert res[cal_key]["value"] == 8.7
            assert res[cal_key]["source"] == "calibration:acn_data_2019_2021_test"
        finally:
            scen_path.unlink(missing_ok=True)
    finally:
        pops_path.write_text(backup)
