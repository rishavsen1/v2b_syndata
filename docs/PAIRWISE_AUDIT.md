# Pairwise Interaction Audit (V3)
Generated: 2026-05-19T17:20:31
Pairs sampled: 50 (seeded random.seed=42)
Total elapsed: 218.6s

## Summary
| Verdict | Count |
|---|---|
| ✅ LINEAR | 44 |
| ⚠️ MILDLY_NONLINEAR | 1 |
| ⚠️ MODERATELY_NONLINEAR | 2 |
| ❌ STRONGLY_NONLINEAR | 0 |
| 🔄 SIGN_FLIP | 0 |
| 🟡 UNINFORMATIVE | 3 |
| 💥 ERROR | 0 |
| **TOTAL** | **50** |

## ⚠️ MODERATELY_NONLINEAR (2 pairs)

### `building_load.peak_kw` × `noise.building_load_jitter_pct`
- Scenario: `S01` · val_a=`5000.0` val_b=`0.5`
- **building_load.csv** (flex_var) MODERATELY_NONLINEAR: d_a=245397.025401, d_b=760.593691, d_both=321456.394542, expected_linear=246157.619093, nonlinearity=0.3059

### `utility_rate.dr_program` × `noise.dr_notification_dropout_prob`
- Scenario: `S_dr_cbp` · val_a=`ELRP` val_b=`1.0`
- **dr_events.csv** (lead_hr) MODERATELY_NONLINEAR: d_a=-22.0, d_b=-24.0, d_both=-24.0, expected_linear=-46.0, nonlinearity=0.4783

## ⚠️ MILDLY_NONLINEAR (1 pairs)

| pair | scenario | worst nonlinearity (csv) |
|---|---|---|
| `ev_fleet.ev_count` × `noise.arrival_time_jitter_min` | S_audit_baseline | 0.181 (sessions.csv) |

## ✅ LINEAR (44 pairs)

| pair | scenario | worst nonlinearity (csv) |
|---|---|---|
| `user_behavior.axes_distribution` × `sim_window.mode` | S_dr_cbp | 0.000 (users.csv) |
| `ev_fleet.battery_mix` × `user_behavior.region_distributions.stable_commuter.copula.rho_gaussian` | S01 | 0.025 (sessions.csv) |
| `utility_rate.peak_window` × `user_behavior.region_distributions.erratic.dwell.lambda` | S01 | 0.000 (grid_prices.csv) |
| `utility_rate.energy_price_offpeak` × `user_behavior.region_distributions.stable_commuter.dwell.lambda` | S01 | 0.000 (grid_prices.csv) |
| `building_load.peak_kw` × `user_behavior.region_distributions.flexible_local.copula.rho_gaussian` | S01 | 0.000 (building_load.csv) |
| `user_behavior.w_multiplier` × `sim_window.mode` | S_dr_cbp | 0.000 (users.csv) |
| `charging_infra.bi_rate_kw` × `user_behavior.region_distributions.flexible_local.copula.rho_gaussian` | S01 | 0.003 (sessions.csv) |
| `charging_infra.uni_rate_kw` × `user_behavior.region_distributions.flexible_local.dwell.lambda` | S01 | 0.005 (sessions.csv) |
| `user_behavior.region_distributions.stable_commuter.dwell.lambda` × `user_behavior.region_distributions.irregular_distant.dwell.lambda` | S01 | 0.000 (sessions.csv) |
| `ev_fleet.battery_mix` × `user_behavior.region_distributions.erratic.copula.rho_gaussian` | S01 | 0.088 (sessions.csv) |
| `ev_fleet.battery_mix` × `user_behavior.region_distributions.occasional_visitor.soc_arrival.beta` | S01 | 0.000 (cars.csv) |
| `charging_infra.bi_rate_kw` × `user_behavior.w_multiplier` | S01 | 0.000 (chargers.csv) |
| `utility_rate.tariff_type` × `user_behavior.region_distributions.stable_commuter.arrival.sigma` | S01 | 0.000 (grid_prices.csv) |
| `user_behavior.region_distributions.irregular_distant.dwell.lambda` × `user_behavior.region_distributions.erratic.arrival.sigma` | S01 | 0.000 (sessions.csv) |
| `ev_fleet.battery_mix` × `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | S01 | 0.034 (sessions.csv) |
| `building_load.size` × `user_behavior.region_distributions.irregular_distant.dwell.k` | S01 | 0.000 (building_load.csv) |
| `user_behavior.region_distributions.stable_commuter.dwell.lambda` × `user_behavior.region_distributions.flexible_local.arrival.mu` | S01 | 0.000 (sessions.csv) |
| `building_load.peak_kw` × `user_behavior.region_distributions.stable_commuter.arrival.sigma` | S01 | 0.000 (building_load.csv) |
| `user_behavior.region_distributions.flexible_local.arrival.mu` × `user_behavior.region_distributions.irregular_distant.arrival.mu` | S01 | 0.000 (sessions.csv) |
| `utility_rate.dr_program` × `noise.price_jitter_pct` | S_dr_cbp | 0.000 (dr_events.csv) |
| `user_behavior.region_distributions.stable_commuter.dwell.lambda` × `user_behavior.region_distributions.irregular_distant.copula.rho_gaussian` | S01 | 0.000 (sessions.csv) |
| `noise.building_load_jitter_pct` × `noise.dr_notification_dropout_prob` | S_dr_cbp | 0.000 (building_load.csv) |
| `building_load.occupancy_source` × `user_behavior.region_distributions.erratic.dwell.lambda` | S01 | 0.000 (building_load.csv) |
| `noise.profile` × `user_behavior.region_distributions.occasional_visitor.arrival.sigma` | S_dr_cbp | 0.000 (building_load.csv) |
| `charging_infra.bi_rate_kw` × `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | S01 | 0.015 (sessions.csv) |
| `charging_infra.uni_rate_kw` × `user_behavior.region_distributions.erratic.soc_arrival.beta` | S01 | 0.057 (sessions.csv) |
| `noise.price_jitter_pct` × `user_behavior.region_distributions.flexible_local.dwell.lambda` | S01 | 0.000 (grid_prices.csv) |
| `charging_infra.bi_rate_kw` × `utility_rate.dr_lambda_base` | S_dr_cbp | 0.000 (chargers.csv) |
| `noise.soc_arrival_jitter_pct` × `noise.dr_notification_dropout_prob` | S_dr_cbp | 0.000 (sessions.csv) |
| `noise.building_load_jitter_pct` × `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | S01 | 0.000 (building_load.csv) |
| `utility_rate.peak_window` × `utility_rate.dr_program` | S_dr_cbp | 0.000 (grid_prices.csv) |
| `ev_fleet.battery_heterogeneity` × `user_behavior.region_distributions.irregular_distant.dwell.lambda` | S01 | 0.000 (cars.csv) |
| `user_behavior.region_distributions.flexible_local.arrival.sigma` × `user_behavior.region_distributions.erratic.dwell.k` | S01 | 0.000 (sessions.csv) |
| `user_behavior.region_distributions.erratic.arrival.sigma` × `user_behavior.region_distributions.erratic.dwell.k` | S01 | 0.002 (sessions.csv) |
| `user_behavior.negotiation_mix` × `utility_rate.dr_program` | S_dr_cbp | 0.000 (users.csv) |
| `noise.price_jitter_pct` × `user_behavior.region_distributions.stable_commuter.soc_arrival.alpha` | S01 | 0.000 (grid_prices.csv) |
| `charging_infra.uni_rate_kw` × `user_behavior.negotiation_mix` | S01 | 0.000 (chargers.csv) |
| `utility_rate.dr_magnitude_kw_range` × `user_behavior.region_distributions.irregular_distant.arrival.mu` | S_dr_cbp | 0.000 (dr_events.csv) |
| `noise.soc_arrival_jitter_pct` × `user_behavior.region_distributions.flexible_local.arrival.sigma` | S01 | 0.000 (sessions.csv) |
| `building_load.size` × `utility_rate.dr_magnitude_kw_range` | S_dr_cbp | 0.000 (building_load.csv) |
| `charging_infra.directionality_frac` × `noise.occupancy_jitter_pct` | S01 | 0.000 (chargers.csv) |
| `building_load.peak_kw` × `user_behavior.region_distributions.erratic.soc_arrival.alpha` | S01 | 0.000 (building_load.csv) |
| `utility_rate.dr_magnitude_kw_range` × `noise.occupancy_jitter_pct` | S_dr_cbp | 0.000 (dr_events.csv) |
| `charging_infra.uni_rate_kw` × `building_load.archetype` | S01 | 0.000 (chargers.csv) |

## 🟡 UNINFORMATIVE (3 pairs)

| pair | scenario | worst nonlinearity (csv) |
|---|---|---|
| `user_behavior.min_depart_soc` × `user_behavior.region_distributions.irregular_distant.dwell.lambda` | S01 | 0.000 (sessions.csv) |
| `user_behavior.min_depart_soc` × `user_behavior.region_distributions.stable_commuter.arrival.mu` | S01 | 0.000 (sessions.csv) |
| `ev_fleet.battery_heterogeneity` × `user_behavior.region_distributions.occasional_visitor.copula.rho_gaussian` | S01 | 0.000 (cars.csv) |

## Top 10 nonlinear interactions (any CSV)
| nonlinearity | knob_a | knob_b | csv | metric | verdict |
|---|---|---|---|---|---|
| 0.478 | `utility_rate.dr_program` | `noise.dr_notification_dropout_prob` | dr_events.csv | lead_hr | MODERATELY_NONLINEAR |
| 0.306 | `building_load.peak_kw` | `noise.building_load_jitter_pct` | building_load.csv | flex_var | MODERATELY_NONLINEAR |
| 0.181 | `ev_fleet.ev_count` | `noise.arrival_time_jitter_min` | sessions.csv | arr_var | MILDLY_NONLINEAR |
| 0.088 | `ev_fleet.battery_mix` | `user_behavior.region_distributions.erratic.copula.rho_gaussian` | sessions.csv | erratic/copula.rho_gaussian | LINEAR |
| 0.057 | `charging_infra.uni_rate_kw` | `user_behavior.region_distributions.erratic.soc_arrival.beta` | sessions.csv | erratic/soc_arrival.beta | LINEAR |
| 0.034 | `ev_fleet.battery_mix` | `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | sessions.csv | flexible_local/soc_arrival.beta | LINEAR |
| 0.025 | `ev_fleet.battery_mix` | `user_behavior.region_distributions.stable_commuter.copula.rho_gaussian` | sessions.csv | stable_commuter/copula.rho_gaussian | LINEAR |
| 0.015 | `charging_infra.bi_rate_kw` | `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | sessions.csv | flexible_local/soc_arrival.beta | LINEAR |
| 0.005 | `charging_infra.uni_rate_kw` | `user_behavior.region_distributions.flexible_local.dwell.lambda` | sessions.csv | flexible_local/dwell.lambda | LINEAR |
| 0.003 | `building_load.peak_kw` | `noise.building_load_jitter_pct` | building_load.csv | flex_mean | LINEAR |

## Verdict
- ✅ No STRONGLY_NONLINEAR or SIGN_FLIP findings. Proceed to V4.
