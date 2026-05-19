# Knob Audit Stage 2: Direction + Magnitude
Generated: 2026-05-19T13:53:20
Git SHA: `860dd19`
Total elapsed: 650.6s
Knobs probed: 67

## Summary
| Verdict | Count |
|---|---|
| ✅ MONOTONIC | 62 |
| ⚠️ NON-MONOTONIC | 2 |
| ⚠️ WEAK-EFFECT | 0 |
| ❌ WRONG-DIRECTION | 0 |
| 🟡 NO-EFFECT | 3 |
| **TOTAL** | **67** |

## Interpretation
- **NON-MONOTONIC at low Weibull k:** dwell.k probes start at k≈0.01 (range floor). Weibull at k≪1 collapses to a degenerate distribution (most mass near 0), so realized duration std is artificially low at the floor before rising at moderate k and decreasing again at high k. Not a pipeline bug — Weibull math.
- **NO-EFFECT for low-frequency regions:** S01 uses consent_default with small `occasional_visitor` weight (1 user out of 20 EVs). Single-user regions yield insufficient samples for std/corr metrics (returns NaN). Re-probe under S_audit_baseline (50 EVs) for proper coverage.
- **`any` direction verdicts:** categorical / simplex / bool / list[region] knobs have no ordinal probe order, so monotonicity isn't claimed. Verdict is RESPONSIVE-vs-NO-EFFECT only.

## ✅ MONOTONIC (62 knobs)

### `ev_fleet.ev_count`
- **cars.csv** (row_count, expect ↑)
  - probes: `['1', '51', '100', '150', '200']`
  - metric: `['1', '51', '100', '150', '200']`
  - **MONOTONIC** — ↑ range=199 (19900.0%)
- **users.csv** (row_count, expect ↑)
  - probes: `['1', '51', '100', '150', '200']`
  - metric: `['1', '51', '100', '150', '200']`
  - **MONOTONIC** — ↑ range=199 (19900.0%)
- **sessions.csv** (row_count, expect ↑)
  - probes: `['1', '51', '100', '150', '200']`
  - metric: `['8', '788', '1601', '2379', '3132']`
  - **MONOTONIC** — ↑ range=3124 (39050.0%)

### `ev_fleet.battery_mix`
- **cars.csv** (capacity_mean, expect any)
  - probes: `['[1.0, 0.0, 0.0, 0.0]', '[0.5, 0.5, 0.0, 0.0]', '[0.25, 0.25, 0.25, 0.25]', '[0.0, 0.0, 0.5, 0.5]', '[0.0, 0.0, 0.0, 1.0]']`
  - metric: `['24', '32', '58.95', '87.5', '100']`
  - **MONOTONIC** — responsive (range=76)

### `ev_fleet.battery_heterogeneity`
- **cars.csv** (capacity_mean, expect any)
  - probes: `['homog', 'mixed']`
  - metric: `['75', '55.2']`
  - **MONOTONIC** — responsive (range=19.8)

### `charging_infra.charger_count`
- **chargers.csv** (row_count, expect ↑)
  - probes: `['1', '26', '50', '75', '100']`
  - metric: `['1', '26', '50', '75', '100']`
  - **MONOTONIC** — ↑ range=99 (9900.0%)

### `charging_infra.directionality_frac`
- **chargers.csv** (frac_bidir, expect ↑)
  - probes: `['0.0', '0.25', '0.5', '0.75', '1.0']`
  - metric: `['0', '0.25', '0.5', '0.75', '1']`
  - **MONOTONIC** — ↑ range=1 (100000000000000.0%)

### `charging_infra.uni_rate_kw`
- **chargers.csv** (rate_mean, expect ↑)
  - probes: `['3.3', '89.975', '176.65', '263.325', '350.0']`
  - metric: `['11.65', '54.99', '98.33', '141.7', '185']`
  - **MONOTONIC** — ↑ range=173.3 (1488.0%)

### `charging_infra.bi_rate_kw`
- **chargers.csv** (rate_mean, expect ↑)
  - probes: `['3.3', '89.975', '176.65', '263.325', '350.0']`
  - metric: `['11.65', '54.99', '98.33', '141.7', '185']`
  - **MONOTONIC** — ↑ range=173.3 (1488.0%)

### `user_behavior.axes_distribution`
- **users.csv** (phi_mean, expect any)
  - probes: `["[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '"]`
  - metric: `['0.6198', '0.783', '0.7168', '0.5513', '0.2974']`
  - **MONOTONIC** — responsive (range=0.4856)
- **users.csv** (kappa_mean, expect any)
  - probes: `["[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '", "[{'name': 'stable_commuter', '"]`
  - metric: `['0.4506', '0.6666', '0.518', '0.338', '0.278']`
  - **MONOTONIC** — responsive (range=0.3886)

### `user_behavior.negotiation_mix`
- **users.csv** (w1_mean, expect any)
  - probes: `['[1.0, 0.0, 0.0, 0.0]', '[0.0, 1.0, 0.0, 0.0]', '[0.0, 0.0, 1.0, 0.0]', '[0.0, 0.0, 0.0, 1.0]', '[0.25, 0.25, 0.25, 0.25]']`
  - metric: `['0.05493', '0.01678', '0.03922', '0', '0.03544']`
  - **MONOTONIC** — responsive (range=0.05493)
- **users.csv** (w2_mean, expect any)
  - probes: `['[1.0, 0.0, 0.0, 0.0]', '[0.0, 1.0, 0.0, 0.0]', '[0.0, 0.0, 1.0, 0.0]', '[0.0, 0.0, 0.0, 1.0]', '[0.25, 0.25, 0.25, 0.25]']`
  - metric: `['0.1225', '0.03092', '0.06479', '0.1083', '0.09118']`
  - **MONOTONIC** — responsive (range=0.09158)

### `user_behavior.w_multiplier`
- **users.csv** (w1_mean, expect ↑)
  - probes: `['[0.2, 0.2]', '[0.5, 0.5]', '[1.0, 1.0]', '[2.0, 2.0]', '[4.0, 4.0]']`
  - metric: `['0.006346', '0.01586', '0.03173', '0.06346', '0.1269']`
  - **MONOTONIC** — ↑ range=0.1206 (1900.0%)
- **users.csv** (w2_mean, expect ↑)
  - probes: `['[0.2, 0.2]', '[0.5, 0.5]', '[1.0, 1.0]', '[2.0, 2.0]', '[4.0, 4.0]']`
  - metric: `['0.0129', '0.03226', '0.06452', '0.129', '0.2581']`
  - **MONOTONIC** — ↑ range=0.2452 (1900.0%)

### `user_behavior.min_depart_soc`
- **sessions.csv** (req_soc_min, expect ↑)
  - probes: `['0.5', '0.625', '0.75', '0.875', '1.0']`
  - metric: `['67.92', '67.94', '75.03', '87.5', 'nan']`
  - **MONOTONIC** — ↑ range=19.58 (28.8%)

### `building_load.tmyx_station`
- **building_load.csv** (flex_mean, expect any)
  - probes: `['USA_TN_Nashville.Intl.AP.72327', 'USA_CA_San.Jose-Mineta.Intl.AP', 'USA_FL_Miami.Natl.Hurricane.Ce', 'USA_MN_Minneapolis-St.Paul.Int', 'USA_TX_Houston-Bush.Interconti']`
  - metric: `['35.49', '24.82', '79.5', '19.67', '61.83']`
  - **MONOTONIC** — responsive (range=59.82)
- **building_load.csv** (inflex_mean, expect any)
  - probes: `['USA_TN_Nashville.Intl.AP.72327', 'USA_CA_San.Jose-Mineta.Intl.AP', 'USA_FL_Miami.Natl.Hurricane.Ce', 'USA_MN_Minneapolis-St.Paul.Int', 'USA_TX_Houston-Bush.Interconti']`
  - metric: `['126.1', '117', '108.2', '150.3', '108.8']`
  - **MONOTONIC** — responsive (range=42.15)

### `building_load.archetype`
- **building_load.csv** (flex_mean, expect any)
  - probes: `['office', 'retail', 'mixed']`
  - metric: `['35.49', '61.71', '45.61']`
  - **MONOTONIC** — responsive (range=26.22)

### `building_load.size`
- **building_load.csv** (flex_mean, expect any)
  - probes: `['small', 'med', 'large']`
  - metric: `['61.81', '35.49', '50.31']`
  - **MONOTONIC** — responsive (range=26.32)

### `building_load.occupancy_source`
- **building_load.csv** (flex_mean, expect any)
  - probes: `['ashrae_90_1_office', 'ashrae_90_1_retail', 'ashrae_90_1_mixed', 'custom_path']`
  - metric: `['35.49', '36.62', '36.21', '35.49']`
  - **MONOTONIC** — responsive (range=1.126)

### `building_load.peak_kw`
- **building_load.csv** (flex_mean, expect ↑)
  - probes: `['50.0', '1287.5', '2525.0', '3762.5', '5000.0']`
  - metric: `['3.549', '91.39', '179.2', '267.1', '354.9']`
  - **MONOTONIC** — ↑ range=351.4 (9900.0%)

### `utility_rate.tariff_type`
- **grid_prices.csv** (price_mean, expect any)
  - probes: `['flat', 'TOU', 'demand_charge', 'DR']`
  - metric: `['0.085', '0.09542', '0.09542', '0.09542']`
  - **MONOTONIC** — responsive (range=0.01042)

### `utility_rate.energy_price_offpeak`
- **grid_prices.csv** (price_mean, expect ↑)
  - probes: `['0.05', '0.1625', '0.275', '0.3875', '0.5']`
  - metric: `['0.06771', '0.1568', '0.2458', '0.3349', '0.424']`
  - **MONOTONIC** — ↑ range=0.3562 (526.2%)

### `utility_rate.energy_price_peak`
- **grid_prices.csv** (price_mean, expect ↑)
  - probes: `['0.05', '0.2375', '0.425', '0.6125', '0.8']`
  - metric: `['0.07771', '0.1168', '0.1558', '0.1949', '0.234']`
  - **MONOTONIC** — ↑ range=0.1563 (201.1%)

### `utility_rate.peak_window`
- **grid_prices.csv** (price_mean, expect any)
  - probes: `['[6, 18]', '[7, 20]', '[8, 22]', '[9, 23]', '[5, 15]']`
  - metric: `['0.11', '0.1121', '0.1142', '0.1142', 'nan']`
  - **MONOTONIC** — responsive (range=0.004167)

### `utility_rate.dr_program`
- **dr_events.csv** (lead_hr, expect any)
  - probes: `['none', 'CBP', 'BIP', 'ELRP']`
  - metric: `['0', '24', '2', '2']`
  - **MONOTONIC** — responsive (range=24)

### `utility_rate.dr_magnitude_kw_range`
- **dr_events.csv** (magnitude_mean, expect ↑)
  - probes: `['[40, 60]', '[80, 120]', '[150, 200]', '[200, 400]', '[300, 600]']`
  - metric: `['48.39', '96.78', '171', '283.9', '425.8']`
  - **MONOTONIC** — ↑ range=377.4 (780.0%)

### `utility_rate.dr_lambda_base`
- **dr_events.csv** (row_count, expect ↑)
  - probes: `['0.0', '2.5', '5.0', '7.5', '10.0']`
  - metric: `['0', '18', '18', '18', '18']`
  - **MONOTONIC** — ↑ range=18 (1800000000000000.0%)

### `sim_window.mode`
- **sessions.csv** (row_count, expect any)
  - probes: `['month', 'full_year', 'custom']`
  - metric: `['312', '3756', '948']`
  - **MONOTONIC** — responsive (range=3444)

### `sim_window.weekdays_only`
- **sessions.csv** (row_count, expect ↓)
  - probes: `['False', 'True']`
  - metric: `['443', '319']`
  - **MONOTONIC** — ↓ range=124 (28.0%)

### `noise.profile`
- **building_load.csv** (flex_var, expect any)
  - probes: `['clean', 'light_noise', 'realistic_noise', 'adversarial', 'custom']`
  - metric: `['1817', '1818', '1824', '1880', 'nan']`
  - **MONOTONIC** — responsive (range=62.26)
- **sessions.csv** (arr_var, expect any)
  - probes: `['clean', 'light_noise', 'realistic_noise', 'adversarial', 'custom']`
  - metric: `['4.946', '4.962', '5.035', '5.599', 'nan']`
  - **MONOTONIC** — responsive (range=0.6524)

### `noise.building_load_jitter_pct`
- **building_load.csv** (flex_var, expect ↑)
  - probes: `['0.0', '0.125', '0.25', '0.375', '0.5']`
  - metric: `['2479', '2511', '2651', '2899', '3239']`
  - **MONOTONIC** — ↑ range=760.6 (30.7%)

### `noise.arrival_time_jitter_min`
- **sessions.csv** (arr_var, expect ↑)
  - probes: `['0.0', '15.0', '30.0', '45.0', '60.0']`
  - metric: `['4.43', '4.58', '4.851', '5.251', '5.773']`
  - **MONOTONIC** — ↑ range=1.343 (30.3%)

### `noise.soc_arrival_jitter_pct`
- **sessions.csv** (soc_var, expect ↑)
  - probes: `['0.0', '0.075', '0.15', '0.225', '0.3']`
  - metric: `['303.6', '334.5', '436.5', '574.3', '730.2']`
  - **MONOTONIC** — ↑ range=426.6 (140.5%)

### `noise.dr_notification_dropout_prob`
- **dr_events.csv** (row_count, expect ↓)
  - probes: `['0.0', '0.25', '0.5', '0.75', '1.0']`
  - metric: `['2', '2', '2', '0', '0']`
  - **MONOTONIC** — ↓ range=2 (100.0%)

### `noise.price_jitter_pct`
- **grid_prices.csv** (price_var, expect ↑)
  - probes: `['0.0', '0.075', '0.15', '0.225', '0.3']`
  - metric: `['0.000412', '0.000459', '0.000612', '0.000871', '0.001236']`
  - **MONOTONIC** — ↑ range=0.0008233 (199.6%)

### `noise.occupancy_jitter_pct`
- **building_load.csv** (inflex_var, expect ↑)
  - probes: `['0.0', '0.075', '0.15', '0.225', '0.3']`
  - metric: `['7845', '7972', '8350', '8980', 'nan']`
  - **MONOTONIC** — ↑ range=1135 (14.5%)

### `user_behavior.region_distributions.stable_commuter.arrival.mu`
- **sessions.csv** (stable_commuter/arrival.mu, expect ↑)
  - probes: `['6.0', '9.5', '13.0', '16.5', '20.0']`
  - metric: `['6.566', '9.369', '12.86', '16.36', '19.23']`
  - **MONOTONIC** — ↑ range=12.66 (192.9%)

### `user_behavior.region_distributions.stable_commuter.arrival.sigma`
- **sessions.csv** (stable_commuter/arrival.sigma, expect ↑)
  - probes: `['0.01', '1.5075', '3.005', '4.5025', '6.0']`
  - metric: `['0', '1.412', '2.322', '3.121', '3.588']`
  - **MONOTONIC** — ↑ range=3.588 (358845406937969.5%)

### `user_behavior.region_distributions.stable_commuter.dwell.lambda`
- **sessions.csv** (stable_commuter/dwell.lambda, expect ↑)
  - probes: `['0.01', '6.0075', '12.005', '18.0025', '24.0']`
  - metric: `['0.5', '6.078', '10.38', '11.98', '12.71']`
  - **MONOTONIC** — ↑ range=12.21 (2442.5%)

### `user_behavior.region_distributions.stable_commuter.soc_arrival.alpha`
- **sessions.csv** (stable_commuter/soc_arrival.alpha, expect ↑)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['10', '52.2', '64.24', '69.61', '72.58']`
  - **MONOTONIC** — ↑ range=62.58 (625.8%)

### `user_behavior.region_distributions.stable_commuter.soc_arrival.beta`
- **sessions.csv** (stable_commuter/soc_arrival.beta, expect ↓)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['82.68', '13.87', '10.22', '10', '10']`
  - **MONOTONIC** — ↓ range=72.68 (87.9%)

### `user_behavior.region_distributions.stable_commuter.copula.rho_gaussian`
- **sessions.csv** (stable_commuter/copula.rho_gaussian, expect ↑)
  - probes: `['-0.99', '-0.495', '0.0', '0.495', '0.99']`
  - metric: `['-0.9647', '-0.4456', '-0.05011', '0.4233', '0.9757']`
  - **MONOTONIC** — ↑ range=1.94 (201.1%)

### `user_behavior.region_distributions.flexible_local.arrival.mu`
- **sessions.csv** (flexible_local/arrival.mu, expect ↑)
  - probes: `['6.0', '9.5', '13.0', '16.5', '20.0']`
  - metric: `['7.201', '9.549', '13.01', '16.44', '18.78']`
  - **MONOTONIC** — ↑ range=11.58 (160.8%)

### `user_behavior.region_distributions.flexible_local.arrival.sigma`
- **sessions.csv** (flexible_local/arrival.sigma, expect ↑)
  - probes: `['0.01', '1.5075', '3.005', '4.5025', '6.0']`
  - metric: `['0', '1.451', '2.412', '3.183', '3.644']`
  - **MONOTONIC** — ↑ range=3.644 (364392348086329.3%)

### `user_behavior.region_distributions.flexible_local.dwell.k`
- **sessions.csv** (flexible_local/dwell.k, expect ↓)
  - probes: `['0.01', '1.2575', '2.505', '3.7525', '5.0']`
  - metric: `['6.147', '3.617', '2.206', '1.563', '1.212']`
  - **MONOTONIC** — ↓ range=4.935 (80.3%)

### `user_behavior.region_distributions.flexible_local.dwell.lambda`
- **sessions.csv** (flexible_local/dwell.lambda, expect ↑)
  - probes: `['0.01', '6.0075', '12.005', '18.0025', '24.0']`
  - metric: `['0.5', '5.25', '9.415', '11.59', '12.68']`
  - **MONOTONIC** — ↑ range=12.18 (2437.0%)

### `user_behavior.region_distributions.flexible_local.soc_arrival.alpha`
- **sessions.csv** (flexible_local/soc_arrival.alpha, expect ↑)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['10.33', '68.31', '80.28', '85.22', '87.9']`
  - **MONOTONIC** — ↑ range=77.57 (750.8%)

### `user_behavior.region_distributions.flexible_local.soc_arrival.beta`
- **sessions.csv** (flexible_local/soc_arrival.beta, expect ↓)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['96.94', 'nan', '14.69', '11.39', '10.36']`
  - **MONOTONIC** — ↓ range=86.58 (89.3%)

### `user_behavior.region_distributions.flexible_local.copula.rho_gaussian`
- **sessions.csv** (flexible_local/copula.rho_gaussian, expect ↑)
  - probes: `['-0.99', '-0.495', '0.0', '0.495', '0.99']`
  - metric: `['-0.9817', '-0.6301', '0.1668', '0.3986', '0.9859']`
  - **MONOTONIC** — ↑ range=1.968 (200.4%)

### `user_behavior.region_distributions.irregular_distant.arrival.mu`
- **sessions.csv** (irregular_distant/arrival.mu, expect ↑)
  - probes: `['6.0', '9.5', '13.0', '16.5', '20.0']`
  - metric: `['8.333', '10.51', '13.72', '16.79', '18.5']`
  - **MONOTONIC** — ↑ range=10.17 (122.0%)

### `user_behavior.region_distributions.irregular_distant.arrival.sigma`
- **sessions.csv** (irregular_distant/arrival.sigma, expect ↑)
  - probes: `['0.01', '1.5075', '3.005', '4.5025', '6.0']`
  - metric: `['0', '1.252', '2.234', '2.938', '3.225']`
  - **MONOTONIC** — ↑ range=3.225 (322453313831847.0%)

### `user_behavior.region_distributions.irregular_distant.dwell.lambda`
- **sessions.csv** (irregular_distant/dwell.lambda, expect ↑)
  - probes: `['0.01', '6.0075', '12.005', '18.0025', '24.0']`
  - metric: `['0.5', '5.779', '8.767', '10.61', '11.35']`
  - **MONOTONIC** — ↑ range=10.85 (2170.3%)

### `user_behavior.region_distributions.irregular_distant.soc_arrival.alpha`
- **sessions.csv** (irregular_distant/soc_arrival.alpha, expect ↑)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['10', '43.95', '58.23', '64.38', '67.8']`
  - **MONOTONIC** — ↑ range=57.8 (578.0%)

### `user_behavior.region_distributions.irregular_distant.soc_arrival.beta`
- **sessions.csv** (irregular_distant/soc_arrival.beta, expect ↓)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['78.44', '11.22', '10', '10', '10']`
  - **MONOTONIC** — ↓ range=68.44 (87.3%)

### `user_behavior.region_distributions.irregular_distant.copula.rho_gaussian`
- **sessions.csv** (irregular_distant/copula.rho_gaussian, expect ↑)
  - probes: `['-0.99', '-0.495', '0.0', '0.495', '0.99']`
  - metric: `['-0.9532', '-0.5122', '0.02864', '0.2426', '0.9741']`
  - **MONOTONIC** — ↑ range=1.927 (202.2%)

### `user_behavior.region_distributions.occasional_visitor.arrival.mu`
- **sessions.csv** (occasional_visitor/arrival.mu, expect ↑)
  - probes: `['6.0', '9.5', '13.0', '16.5', '20.0']`
  - metric: `['7.5', '9.25', '12.25', '15.5', '17.5']`
  - **MONOTONIC** — ↑ range=10 (133.3%)

### `user_behavior.region_distributions.occasional_visitor.dwell.lambda`
- **sessions.csv** (occasional_visitor/dwell.lambda, expect ↑)
  - probes: `['0.01', '6.0075', '12.005', '18.0025', '24.0']`
  - metric: `['0.5', '9.358', '14', '14', '14']`
  - **MONOTONIC** — ↑ range=13.5 (2700.0%)

### `user_behavior.region_distributions.occasional_visitor.soc_arrival.alpha`
- **sessions.csv** (occasional_visitor/soc_arrival.alpha, expect ↑)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['10', '48.44', '63.38', '70.19', '74.09']`
  - **MONOTONIC** — ↑ range=64.09 (640.9%)

### `user_behavior.region_distributions.occasional_visitor.soc_arrival.beta`
- **sessions.csv** (occasional_visitor/soc_arrival.beta, expect ↓)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['88.59', '10', '10', '10', '10']`
  - **MONOTONIC** — ↓ range=78.59 (88.7%)

### `user_behavior.region_distributions.erratic.arrival.mu`
- **sessions.csv** (erratic/arrival.mu, expect ↑)
  - probes: `['6.0', '9.5', '13.0', '16.5', '20.0']`
  - metric: `['9.022', '10.61', '12.83', '15.08', '16.73']`
  - **MONOTONIC** — ↑ range=7.705 (85.4%)

### `user_behavior.region_distributions.erratic.arrival.sigma`
- **sessions.csv** (erratic/arrival.sigma, expect ↑)
  - probes: `['0.01', '1.5075', '3.005', '4.5025', '6.0']`
  - metric: `['0', '1.456', '2.664', '3.315', '3.643']`
  - **MONOTONIC** — ↑ range=3.643 (364347620153732.2%)

### `user_behavior.region_distributions.erratic.dwell.k`
- **sessions.csv** (erratic/dwell.k, expect ↓)
  - probes: `['0.01', '1.2575', '2.505', '3.7525', '5.0']`
  - metric: `['nan', '1.737', '0.9025', '0.6535', '0.5018']`
  - **MONOTONIC** — ↓ range=1.235 (71.1%)

### `user_behavior.region_distributions.erratic.dwell.lambda`
- **sessions.csv** (erratic/dwell.lambda, expect ↑)
  - probes: `['0.01', '6.0075', '12.005', '18.0025', '24.0']`
  - metric: `['0.5', '5.882', '8.577', '10.51', '11.65']`
  - **MONOTONIC** — ↑ range=11.15 (2230.2%)

### `user_behavior.region_distributions.erratic.soc_arrival.alpha`
- **sessions.csv** (erratic/soc_arrival.alpha, expect ↑)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['10', '62.05', '72.87', '77.14', '79.71']`
  - **MONOTONIC** — ↑ range=69.71 (697.1%)

### `user_behavior.region_distributions.erratic.soc_arrival.beta`
- **sessions.csv** (erratic/soc_arrival.beta, expect ↓)
  - probes: `['0.01', '12.5075', '25.005', '37.5025', '50.0']`
  - metric: `['87.59', '13.62', '10.52', '10.1', '10']`
  - **MONOTONIC** — ↓ range=77.59 (88.6%)

### `user_behavior.region_distributions.erratic.copula.rho_gaussian`
- **sessions.csv** (erratic/copula.rho_gaussian, expect ↑)
  - probes: `['-0.99', '-0.495', '0.0', '0.495', '0.99']`
  - metric: `['-0.9198', '-0.3207', '-0.2731', '0.3537', '0.9676']`
  - **MONOTONIC** — ↑ range=1.887 (205.2%)


## ⚠️ NON-MONOTONIC (2 knobs)

### `user_behavior.region_distributions.stable_commuter.dwell.k`
- **sessions.csv** (stable_commuter/dwell.k, expect ↓)
  - probes: `['0.01', '1.2575', '2.505', '3.7525', '5.0']`
  - metric: `['2.426', '4.332', '3.241', '2.578', '2.04']`
  - **NON-MONOTONIC** — diffs=[1.9057, -1.0906, -0.6632, -0.5381]

### `user_behavior.region_distributions.irregular_distant.dwell.k`
- **sessions.csv** (irregular_distant/dwell.k, expect ↓)
  - probes: `['0.01', '1.2575', '2.505', '3.7525', '5.0']`
  - metric: `['0', '2.626', '1.588', '1.157', '0.9179']`
  - **NON-MONOTONIC** — diffs=[2.6263, -1.0387, -0.4302, -0.2394]


## 🟡 NO-EFFECT (3 knobs)

### `user_behavior.region_distributions.occasional_visitor.arrival.sigma`
- **sessions.csv** (occasional_visitor/arrival.sigma, expect ↑)
  - probes: `['0.01', '1.5075', '3.005', '4.5025', '6.0']`
  - metric: `['nan', 'nan', 'nan', 'nan', 'nan']`
  - **NO-EFFECT** — insufficient valid metric points

### `user_behavior.region_distributions.occasional_visitor.dwell.k`
- **sessions.csv** (occasional_visitor/dwell.k, expect ↓)
  - probes: `['0.01', '1.2575', '2.505', '3.7525', '5.0']`
  - metric: `['nan', 'nan', 'nan', 'nan', 'nan']`
  - **NO-EFFECT** — insufficient valid metric points

### `user_behavior.region_distributions.occasional_visitor.copula.rho_gaussian`
- **sessions.csv** (occasional_visitor/copula.rho_gaussian, expect ↑)
  - probes: `['-0.99', '-0.495', '0.0', '0.495', '0.99']`
  - metric: `['nan', 'nan', 'nan', 'nan', 'nan']`
  - **NO-EFFECT** — insufficient valid metric points

## Cross-knob findings
- Deep-channel: 30/35 MONOTONIC.
- noise.*: 7/7 MONOTONIC.
- DR-related: 4/4 MONOTONIC.

## Recommendations
### 🟡 NO-EFFECT
- `user_behavior.region_distributions.occasional_visitor.arrival.sigma`: sessions.csv/occasional_visitor/arrival.sigma: insufficient valid metric points
- `user_behavior.region_distributions.occasional_visitor.dwell.k`: sessions.csv/occasional_visitor/dwell.k: insufficient valid metric points
- `user_behavior.region_distributions.occasional_visitor.copula.rho_gaussian`: sessions.csv/occasional_visitor/copula.rho_gaussian: insufficient valid metric points
