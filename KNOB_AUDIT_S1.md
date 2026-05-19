# Knob Audit Stage 1: Existence + Isolation
Generated: 2026-05-19T11:26:57
Git SHA: `fd1ff7c`
Total elapsed: 255.6s

## Summary
| Verdict | Count |
|---|---|
| ✅ HONORED | 59 |
| ⚠️ OVER-COUPLED | 4 |
| ❌ UNDER-COUPLED | 8 |
| 🟡 NO-DECLARATION | 24 |
| ⏭️ UNTESTABLE | 3 |
| 💥 OVERRIDE-REJECTED | 0 |
| 🚧 SCENARIO-INCOMPAT | 3 |
| **TOTAL** | **101** |

### ✅ HONORED (59 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `ev_fleet.ev_count` | int | cars.csv, sessions.csv, users.csv | cars.csv, sessions.csv, users.csv |  |
| `charging_infra.charger_count` | int | chargers.csv | chargers.csv |  |
| `charging_infra.directionality_frac` | float | chargers.csv | chargers.csv |  |
| `user_behavior.axes_distribution` | list[region] | users.csv, sessions.csv | sessions.csv, users.csv |  |
| `user_behavior.negotiation_mix` | simplex | users.csv | users.csv |  |
| `user_behavior.w_multiplier` | vec2 | users.csv | users.csv |  |
| `user_behavior.min_depart_soc` | float | sessions.csv | sessions.csv |  |
| `building_load.tmyx_station` | path | building_load.csv | building_load.csv |  |
| `building_load.archetype` | categorical | building_load.csv | building_load.csv |  |
| `building_load.size` | categorical | building_load.csv | building_load.csv |  |
| `building_load.peak_kw` | float | building_load.csv | building_load.csv |  |
| `utility_rate.energy_price_offpeak` | float | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.energy_price_peak` | float | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.peak_window` | vec2 | grid_prices.csv | grid_prices.csv |  |
| `utility_rate.dr_program` | categorical | dr_events.csv | dr_events.csv |  |
| `utility_rate.dr_magnitude_kw_range` | vec2 | dr_events.csv | dr_events.csv |  |
| `utility_rate.dr_lambda_base` | float | dr_events.csv | dr_events.csv |  |
| `sim_window.weekdays_only` | bool | sessions.csv | sessions.csv |  |
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

### ⚠️ OVER-COUPLED (4 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `ev_fleet.battery_mix` | simplex | cars.csv | cars.csv, sessions.csv | also changed: ['sessions.csv'] |
| `ev_fleet.battery_heterogeneity` | categorical | cars.csv | cars.csv, sessions.csv | also changed: ['sessions.csv'] |
| `charging_infra.uni_rate_kw` | float | chargers.csv | chargers.csv, sessions.csv | also changed: ['sessions.csv'] |
| `charging_infra.bi_rate_kw` | float | chargers.csv | chargers.csv, sessions.csv | also changed: ['sessions.csv'] |

### ❌ UNDER-COUPLED (8 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `building_load.climate` | categorical | building_load.csv | — | declared ['building_load.csv'] but ['building_load.csv'] unchanged |
| `building_load.weather_lat` | float | building_load.csv, dr_events.csv | — | declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged |
| `building_load.weather_lon` | float | building_load.csv, dr_events.csv | — | declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged |
| `building_load.weather_year` | int | building_load.csv, dr_events.csv | — | declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged |
| `building_load.occupancy_source` | categorical | building_load.csv, sessions.csv | building_load.csv | declared ['building_load.csv', 'sessions.csv'] but ['sessions.csv'] unchanged |
| `utility_rate.tariff_type` | categorical | grid_prices.csv, dr_events.csv | grid_prices.csv | declared ['dr_events.csv', 'grid_prices.csv'] but ['dr_events.csv'] unchanged |
| `sim_window.mode` | categorical | building_load.csv, grid_prices.csv, sessions.csv, dr_events.csv | building_load.csv, grid_prices.csv, sessions.csv | declared ['building_load.csv', 'dr_events.csv', 'grid_prices.csv', 'sessions.csv'] but ['dr_events.csv'] unchanged |
| `noise.profile` | categorical | building_load.csv, sessions.csv, grid_prices.csv, dr_events.csv | building_load.csv, grid_prices.csv, sessions.csv | declared ['building_load.csv', 'dr_events.csv', 'grid_prices.csv', 'sessions.csv'] but ['dr_events.csv'] unchanged |

### 🟡 NO-DECLARATION (24 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `user_behavior.external_charge_cost` | float | — | — | override accepted; observed change: [] |
| `utility_rate.demand_charge_per_kw` | float | — | — | override accepted; observed change: [] |
| `descriptor.location=san_jose_ca` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=san_francisco_ca` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=minneapolis_mn` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=miami_fl` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=houston_tx` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=atlanta_ga` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.location=sacramento_ca` | descriptor | — | building_load.csv, dr_events.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'dr_events.csv', 'grid_prices.csv'] |
| `descriptor.location=new_york_ny` | descriptor | — | building_load.csv, grid_prices.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv'] |
| `descriptor.building=small_office_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=large_office_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=retail_strip_mall` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=retail_standalone` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.building=mixed_use_v1` | descriptor | — | building_load.csv | override accepted; observed change: ['building_load.csv'] |
| `descriptor.population=acn_workplace_baseline` | descriptor | — | sessions.csv, users.csv | override accepted; observed change: ['sessions.csv', 'users.csv'] |
| `descriptor.population=visitor_heavy` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.population=occasional_commuter` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.population=flexible_workforce` | descriptor | — | cars.csv, sessions.csv, users.csv | override accepted; observed change: ['cars.csv', 'sessions.csv', 'users.csv'] |
| `descriptor.equipment=uni_only` | descriptor | — | chargers.csv | override accepted; observed change: ['chargers.csv'] |
| `descriptor.equipment=bi_heavy` | descriptor | — | chargers.csv | override accepted; observed change: ['chargers.csv'] |
| `descriptor.noise=light_noise` | descriptor | — | building_load.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'sessions.csv'] |
| `descriptor.noise=realistic_noise` | descriptor | — | building_load.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'sessions.csv'] |
| `descriptor.noise=adversarial` | descriptor | — | building_load.csv, grid_prices.csv, sessions.csv | override accepted; observed change: ['building_load.csv', 'grid_prices.csv', 'sessions.csv'] |

### ⏭️ UNTESTABLE (3 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `user_behavior.menu_levels` | list[vec2] | — | — | no probe selector for type=list[vec2] |
| `sim_window.start` | timestamp | — | — | no probe selector for type=timestamp |
| `sim_window.custom_end` | timestamp | — | — | no probe selector for type=timestamp |

### 🚧 SCENARIO-INCOMPAT (3 knobs)
| knob | type | declared | observed | note |
|---|---|---|---|---|
| `descriptor.population=stable_commuter_heavy` | descriptor | — | — | VALIDATION FAILED:   - E5: 21 active sessions > 20 chargers at 2020-04-01T09:45:00.000000 |
| `descriptor.equipment=consent_calibration_site` | descriptor | — | — | VALIDATION FAILED:   - E5: 16 active sessions > 15 chargers at 2020-04-13T12:00:00.000000 |
| `descriptor.equipment=high_power_dcfc` | descriptor | — | — | VALIDATION FAILED:   - E5: 10 active sessions > 8 chargers at 2020-04-01T10:30:00.000000 |

## Recommendations
### HIGH: under-coupled knobs (declared CSV but did NOT differ)
- `building_load.climate`: declared ['building_load.csv'] but ['building_load.csv'] unchanged
  - **Diagnosis:** DECLARATION FIX. Description in knobs.yaml says 'Climate label (categorical, used for indexing). Weather W carries actual signal.' → label-only knob; set affects_csv: []. Current 'building_load.csv' declaration is aspirational, not real.
- `building_load.weather_lat`: declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged
  - **Diagnosis:** PIPELINE LEGACY. NASAPower lat/lon predated TMYx pipeline (D37). EnergyPlus now drives building_load.csv via `tmyx_station`. Either: (a) remove these three knobs, or (b) re-declare affects_csv=[] and document as 'stub/future'. Currently dead.
- `building_load.weather_lon`: declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged
  - **Diagnosis:** See weather_lat — same legacy issue.
- `building_load.weather_year`: declared ['building_load.csv', 'dr_events.csv'] but ['building_load.csv', 'dr_events.csv'] unchanged
  - **Diagnosis:** Same legacy issue. Anchor year is currently used only for sim window indexing (sim_window picks April YYYY); EPW year is the TMYx file's own year.
- `building_load.occupancy_source`: declared ['building_load.csv', 'sessions.csv'] but ['sessions.csv'] unchanged
  - **Diagnosis:** PARTIAL EFFECT. Occupancy schedule swap changes EnergyPlus output (✓ building_load) but sessions.csv unchanged. Either: (a) sessions don't actually consume occupancy signal (likely — occupancy modulates building load, not session arrival times), or (b) modulation pathway dropped. Verify samplers/per_entity.py — if (a), update affects_csv to [building_load.csv].
- `utility_rate.tariff_type`: declared ['dr_events.csv', 'grid_prices.csv'] but ['dr_events.csv'] unchanged
  - **Diagnosis:** DECLARATION FIX. dr_events.csv is driven by `dr_program`, not `tariff_type`. Probe TOU→flat changes grid_prices.csv (✓) but not DR events. Set affects_csv: [grid_prices.csv] only.
- `sim_window.mode`: declared ['building_load.csv', 'dr_events.csv', 'grid_prices.csv', 'sessions.csv'] but ['dr_events.csv'] unchanged
  - **Diagnosis:** EXPECTED MISS. Probe under S01 has dr_program=none so dr_events.csv is empty in both baseline and probe; cannot observe sim_window effect on DR. The knob DOES affect dr_events scheduling under any dr-enabled scenario (proven indirectly via S_dr_cbp). Optional: re-probe sim_window.mode under S_dr_cbp for the dr_events leg, OR drop dr_events.csv from affects_csv when no DR program is active (but that's conditional — leave as-is).
- `noise.profile`: declared ['building_load.csv', 'dr_events.csv', 'grid_prices.csv', 'sessions.csv'] but ['dr_events.csv'] unchanged
  - **Diagnosis:** PROBABILISTIC MISS. Probe is `adversarial` under S_dr_cbp baseline. dr_notification_dropout_prob=0.10 may produce zero drops on a small event count (P(0|n≈8) ≈ 0.43). Re-run with seed sweep to confirm coverage. Not a real bug.

### MEDIUM: over-coupled knobs (extra side-effects)
- `ev_fleet.battery_mix`: also changed: ['sessions.csv']
  - **Diagnosis:** Expected coupling — sessions reference per-car capacity for SoC accounting. Cross-effect on sessions.csv is physically correct. Update declaration to [cars.csv, sessions.csv].
- `ev_fleet.battery_heterogeneity`: also changed: ['sessions.csv']
  - **Diagnosis:** Same as battery_mix — declaration should include sessions.csv.
- `charging_infra.uni_rate_kw`: also changed: ['sessions.csv']
  - **Diagnosis:** Investigate: chargers.csv carries rate, but sessions.csv shouldn't reference it directly. May be RNG-stream coupling (different charger order changes session RNG draws). Verify in seeding.py.
- `charging_infra.bi_rate_kw`: also changed: ['sessions.csv']
  - **Diagnosis:** Same as uni_rate_kw — investigate RNG coupling.

### INFO: descriptor swaps that broke S01's count invariants
These descriptors are reachable via their own scenarios but conflict with S01's `charger_count=20`. Not knob bugs — descriptor/scenario matching issue. Test with a sized-up baseline if needed.

- `descriptor.population=stable_commuter_heavy`: VALIDATION FAILED:
  - E5: 21 active sessions > 20 chargers at 2020-04-01T09:45:00.000000
- `descriptor.equipment=consent_calibration_site`: VALIDATION FAILED:
  - E5: 16 active sessions > 15 chargers at 2020-04-13T12:00:00.000000
- `descriptor.equipment=high_power_dcfc`: VALIDATION FAILED:
  - E5: 10 active sessions > 8 chargers at 2020-04-01T10:30:00.000000

## Stage 2 admission list (63 knobs)

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
- `building_load.peak_kw`
- `utility_rate.energy_price_offpeak`
- `utility_rate.energy_price_peak`
- `utility_rate.peak_window`
- `utility_rate.dr_program`
- `utility_rate.dr_magnitude_kw_range`
- `utility_rate.dr_lambda_base`
- `sim_window.weekdays_only`
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
