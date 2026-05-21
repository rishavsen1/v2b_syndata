# Knob Audit Stage 1: Existence + Isolation
Generated: 2026-05-19T13:12:55
Git SHA: `63d04bd`
Total elapsed: 395.7s

## Summary
| Verdict | Count |
|---|---|
| ✅ HONORED | 67 |
| ⚠️ OVER-COUPLED | 0 |
| ❌ UNDER-COUPLED | 0 |
| 🟡 NO-DECLARATION | 28 |
| ⏭️ UNTESTABLE | 3 |
| 💥 OVERRIDE-REJECTED | 0 |
| 🚧 SCENARIO-INCOMPAT | 0 |
| **TOTAL** | **98** |

### ✅ HONORED (67 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `ev_fleet.ev_count` | int | cars.csv, sessions.csv, users.csv | cars.csv, sessions.csv, users.csv |  |
| `ev_fleet.battery_mix` | simplex | cars.csv, sessions.csv | cars.csv, sessions.csv |  |
| `ev_fleet.battery_heterogeneity` | categorical | cars.csv, sessions.csv | cars.csv, sessions.csv |  |
| `charging_infra.charger_count` | int | chargers.csv | chargers.csv |  |
| `charging_infra.directionality_frac` | float | chargers.csv | chargers.csv |  |
| `charging_infra.uni_rate_kw` | float | chargers.csv, sessions.csv | chargers.csv, sessions.csv |  |
| `charging_infra.bi_rate_kw` | float | chargers.csv, sessions.csv | chargers.csv, sessions.csv |  |
| `user_behavior.axes_distribution` | list[region] | users.csv, sessions.csv | sessions.csv, users.csv |  |
| `user_behavior.negotiation_mix` | simplex | users.csv | users.csv |  |
| `user_behavior.w_multiplier` | vec2 | users.csv | users.csv |  |
| `user_behavior.min_depart_soc` | float | sessions.csv | sessions.csv |  |
| `building_load.tmyx_station` | path | building_load.csv | building_load.csv |  |
| `building_load.archetype` | categorical | building_load.csv | building_load.csv |  |
| `building_load.size` | categorical | building_load.csv | building_load.csv |  |
| `building_load.occupancy_source` | categorical | building_load.csv | building_load.csv |  |
| `building_load.peak_kw` | float | building_load.csv | building_load.csv |  |
| `utility_rate.tariff_type` | categorical | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.energy_price_offpeak` | float | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.energy_price_peak` | float | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.peak_window` | vec2 | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.dr_program` | categorical | dr_events.csv | dr_events.csv |  |
| `utility_rate.dr_magnitude_kw_range` | vec2 | dr_events.csv | dr_events.csv |  |
| `utility_rate.dr_lambda_base` | float | dr_events.csv | dr_events.csv |  |
| `sim_window.mode` | categorical | building_load.csv, grid_prices.csv, sessions.csv, dr_events.csv | building_load.csv, dr_events.csv, grid_prices.csv, sessions.csv |  |
| `sim_window.weekdays_only` | bool | sessions.csv | sessions.csv |  |
| `noise.profile` | categorical | building_load.csv, sessions.csv, grid_prices.csv, dr_events.csv | building_load.csv, dr_events.csv, grid_prices.csv, sessions.csv |  |
| `noise.building_load_jitter_pct` | float | building_load.csv | building_load.csv |  |
| `noise.arrival_time_jitter_min` | float | sessions.csv | sessions.csv |  |
| `noise.soc_arrival_jitter_pct` | float | sessions.csv | sessions.csv |  |
| `noise.dr_notification_dropout_prob` | float | dr_events.csv | dr_events.csv |  |
| `noise.price_jitter_pct` | float | grid_prices.csv | grid_prices.csv |  |
| `noise.occupancy_jitter_pct` | float | building_load.csv | building_load.csv |  |
| `user_behavior.region_distributions.stable_commuter.arrival.mu` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.arrival.sigma` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.dwell.k` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.dwell.lambda` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.soc_arrival.alpha` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.soc_arrival.beta` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.stable_commuter.copula.rho_gaussian` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.arrival.mu` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.arrival.sigma` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.dwell.k` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.dwell.lambda` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.soc_arrival.alpha` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.soc_arrival.beta` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.flexible_local.copula.rho_gaussian` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.arrival.mu` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.arrival.sigma` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.dwell.k` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.dwell.lambda` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.soc_arrival.alpha` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.soc_arrival.beta` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.irregular_distant.copula.rho_gaussian` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.arrival.mu` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.arrival.sigma` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.dwell.k` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.dwell.lambda` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.soc_arrival.alpha` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.soc_arrival.beta` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.occasional_visitor.copula.rho_gaussian` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.arrival.mu` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.arrival.sigma` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.dwell.k` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.dwell.lambda` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.soc_arrival.alpha` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.soc_arrival.beta` | deep | sessions.csv | sessions.csv |  |
| `user_behavior.region_distributions.erratic.copula.rho_gaussian` | deep | sessions.csv | sessions.csv |  |

### 🟡 NO-DECLARATION (28 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `user_behavior.external_charge_cost` | float | — | — | override accepted; observed change: [] |
| `building_load.climate` | categorical | — | — | override accepted; observed change: [] |
| `utility_rate.demand_charge_per_kw` | float | — | — | override accepted; observed change: [] |
| `descriptor.location=nashville_tn` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=san_francisco_ca` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=minneapolis_mn` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=miami_fl` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=houston_tx` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=atlanta_ga` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=sacramento_ca` | descriptor | — | building_load.csv, dr_events.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'dr_events.csv', 'grid_prices.csv'] |
| `descriptor.location=new_york_ny` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.building=medium_office_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=small_office_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=retail_strip_mall` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=retail_standalone` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=mixed_use_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.population=acn_workplace_baseline` | descriptor | — | sessions.csv, users.csv | override accepted; observed change: ['sessions.csv', 'users.csv'] |
| `descriptor.population=stable_commuter_heavy` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.population=visitor_heavy` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.population=occasional_commuter` | descriptor | — | sessions.csv, users.csv | override accepted; observed change: ['sessions.csv', 'users.csv'] |
| `descriptor.population=flexible_workforce` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.equipment=uni_only` | descriptor | — | chargers.csv | override accepted; observed change: ['chargers.csv'] |
| `descriptor.equipment=bi_heavy` | descriptor | — | chargers.csv | override accepted; observed change: ['chargers.csv'] |
| `descriptor.equipment=consent_calibration_site` | descriptor | — | chargers.csv | override accepted; observed change: ['chargers.csv'] |
| `descriptor.equipment=high_power_dcfc` | descriptor | — | chargers.csv, sessions.csv | override accepted; observed change: ['chargers.csv', 'sessions.csv'] |
| `descriptor.noise=light_noise` | descriptor | — | building_load.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'sessions.csv'] |
| `descriptor.noise=realistic_noise` | descriptor | — | building_load.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'sessions.csv'] |
| `descriptor.noise=adversarial` | descriptor | — | building_load.csv, grid_prices.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv', 'sessions.csv'] |

### ⏭️ UNTESTABLE (3 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `user_behavior.menu_levels` | list[vec2] | — | — | no probe selector for type=list[vec2] |
| `sim_window.start` | timestamp | — | — | no probe selector for type=timestamp |
| `sim_window.custom_end` | timestamp | — | — | no probe selector for type=timestamp |

## Recommendations

## Stage 2 admission list (67 knobs)

- `ev_fleet.ev_count`
- `ev_fleet.battery_mix`
- `ev_fleet.battery_heterogeneity`
- `charging_infra.charger_count`
- `charging_infra.directionality_frac`
- `charging_infra.uni_rate_kw`
- `charging_infra.bi_rate_kw`
- `user_behavior.axes_distribution`
- `user_behavior.negotiation_mix`
- `user_behavior.w_multiplier`
- `user_behavior.min_depart_soc`
- `building_load.tmyx_station`
- `building_load.archetype`
- `building_load.size`
- `building_load.occupancy_source`
- `building_load.peak_kw`
- `utility_rate.tariff_type`
- `utility_rate.energy_price_offpeak`
- `utility_rate.energy_price_peak`
- `utility_rate.peak_window`
- `utility_rate.dr_program`
- `utility_rate.dr_magnitude_kw_range`
- `utility_rate.dr_lambda_base`
- `sim_window.mode`
- `sim_window.weekdays_only`
- `noise.profile`
- `noise.building_load_jitter_pct`
- `noise.arrival_time_jitter_min`
- `noise.soc_arrival_jitter_pct`
- `noise.dr_notification_dropout_prob`
- `noise.price_jitter_pct`
- `noise.occupancy_jitter_pct`
- `user_behavior.region_distributions.stable_commuter.arrival.mu`
- `user_behavior.region_distributions.stable_commuter.arrival.sigma`
- `user_behavior.region_distributions.stable_commuter.dwell.k`
- `user_behavior.region_distributions.stable_commuter.dwell.lambda`
- `user_behavior.region_distributions.stable_commuter.soc_arrival.alpha`
- `user_behavior.region_distributions.stable_commuter.soc_arrival.beta`
- `user_behavior.region_distributions.stable_commuter.copula.rho_gaussian`
- `user_behavior.region_distributions.flexible_local.arrival.mu`
- `user_behavior.region_distributions.flexible_local.arrival.sigma`
- `user_behavior.region_distributions.flexible_local.dwell.k`
- `user_behavior.region_distributions.flexible_local.dwell.lambda`
- `user_behavior.region_distributions.flexible_local.soc_arrival.alpha`
- `user_behavior.region_distributions.flexible_local.soc_arrival.beta`
- `user_behavior.region_distributions.flexible_local.copula.rho_gaussian`
- `user_behavior.region_distributions.irregular_distant.arrival.mu`
- `user_behavior.region_distributions.irregular_distant.arrival.sigma`
- `user_behavior.region_distributions.irregular_distant.dwell.k`
- `user_behavior.region_distributions.irregular_distant.dwell.lambda`
- `user_behavior.region_distributions.irregular_distant.soc_arrival.alpha`
- `user_behavior.region_distributions.irregular_distant.soc_arrival.beta`
- `user_behavior.region_distributions.irregular_distant.copula.rho_gaussian`
- `user_behavior.region_distributions.occasional_visitor.arrival.mu`
- `user_behavior.region_distributions.occasional_visitor.arrival.sigma`
- `user_behavior.region_distributions.occasional_visitor.dwell.k`
- `user_behavior.region_distributions.occasional_visitor.dwell.lambda`
- `user_behavior.region_distributions.occasional_visitor.soc_arrival.alpha`
- `user_behavior.region_distributions.occasional_visitor.soc_arrival.beta`
- `user_behavior.region_distributions.occasional_visitor.copula.rho_gaussian`
- `user_behavior.region_distributions.erratic.arrival.mu`
- `user_behavior.region_distributions.erratic.arrival.sigma`
- `user_behavior.region_distributions.erratic.dwell.k`
- `user_behavior.region_distributions.erratic.dwell.lambda`
- `user_behavior.region_distributions.erratic.soc_arrival.alpha`
- `user_behavior.region_distributions.erratic.soc_arrival.beta`
- `user_behavior.region_distributions.erratic.copula.rho_gaussian`
