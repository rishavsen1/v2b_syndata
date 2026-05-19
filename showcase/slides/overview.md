---
marp: true
theme: default
class: lead
paginate: true
backgroundColor: white
style: |
  section { font-family: 'Helvetica Neue', Arial, sans-serif; }
  h1 { color: #1f4e79; }
  h2 { color: #1f4e79; }
  table { font-size: 0.65em; }
  img { max-height: 70vh; }
  pre { font-size: 0.65em; }
---

# v2b_syndata

## Synthetic data for Vehicle-to-Building research

Parameter-driven, seed-reproducible, audited.

---

## 1. The problem

- V2B sits at the intersection of buildings, vehicles, users, equipment, tariffs, grid events.
- Empirical traces that span all six are rare or partial.
- Without a shared substrate, cross-study comparison is apples to oranges.

![bg right:50% w:90%](../figures/01_position_diagram.png)

---

## Position diagram

![w:80%](../figures/01_position_diagram.png)

---

## 2. What it produces

Seven CSVs + a `manifest.json` per scenario.

- `building_load.csv`, `cars.csv`, `users.csv`
- `chargers.csv`, `sessions.csv`
- `grid_prices.csv`, `dr_events.csv`
- Manifest pins all resolved knobs, seed lineage, per-CSV SHA-256.

---

## CSV schema

| CSV | Rows | Key columns |
|---|---|---|
| building_load.csv | ~2700/mo | datetime, power_flex_kw, power_inflex_kw |
| cars.csv | 20–50 | car_id, capacity_kwh, battery_class |
| users.csv | 20–50 | car_id, region, phi, kappa, delta_km |
| chargers.csv | 1–100 | charger_id, directionality, max_rate_kw |
| sessions.csv | ~300–800 | car_id, arrival, departure, arrival_soc |
| grid_prices.csv | ~2700/mo | datetime, price_per_kwh, type |
| dr_events.csv | 0–N | event_id, start, end, magnitude_kw |

---

## Schemas at a glance

![w:80%](../figures/02_csv_schemas.png)

---

## Manifest excerpt

![w:75%](../figures/03_manifest_excerpt.png)

---

## 3. The factor space

- Population: ψ (willingness), region mix, dispersion.
- Building, equipment, tariff, DR, climate.
- 98 knobs total, all in `configs/knobs.yaml`.

![bg right:50% w:90%](../figures/04_descriptor_model.png)

---

## Knob buckets

![w:80%](../figures/05_knob_buckets.png)

---

## Experiment matrix

| Experiment | Knobs swept | Scenarios |
|---|---|---|
| E1 ψ-monotonicity | population descriptors | 5 |
| E2 rate structure | tariff_type, prices, demand | 3 (+S01) |
| E3 DR programs | dr_program, magnitude, lead | 3 |
| E4 equipment | directionality, rates | 2 (+S01) |
| E5 CONSENT | min_depart_soc, w_mult, f_soc | 4 (+S01) |
| E6 building | archetype, size | 3 (+S01) |
| E8 climate × season | location × sim_window | 20 |

---

## 4. Architecture — four tiers

![w:78%](../figures/06_architecture_4tier.png)

---

## Generative DAG

![w:80%](../figures/07_bayes_net_dag.png)

---

## Resolution chain

![w:80%](../figures/08_resolution_chain.png)

---

## Seed lineage

![w:75%](../figures/09_seeding.png)

---

## 5. Data fidelity strategy

| Output | Source |
|---|---|
| building_load | EnergyPlus + ASHRAE 90.1 + TMYx |
| sessions | Synthetic, ACN-Data calibrated |
| cars | Synthetic via battery_mix simplex |
| chargers | Synthetic |
| grid_prices | Rule-based from real tariffs |
| dr_events | Inhomogeneous Poisson (CAISO) |
| users | Synthetic, partially ACN-calibrated |

---

## Climate × season matrix

![w:80%](../figures/10_climate_season_matrix.png)

---

## ACN-Data calibration

![w:80%](../figures/11_acn_calibration.png)

---

## 6. Scenario library

40 named scenarios cover the experiment matrix.

![bg right:55% w:95%](../figures/12_scenario_library.png)

---

## ψ-monotonicity

![w:80%](../figures/13_psi_monotonicity.png)

---

## Climate divergence

![w:80%](../figures/14_climate_divergence.png)

---

## 7. Verification matrix

![w:80%](../figures/15_verification_matrix.png)

---

## Verification summary

| Stage | Probes | Result |
|---|---|---|
| Knob audit S1 | 98 | 67 HONORED |
| Knob audit S2 | 335 | 67/67 monotonic |
| V1 Coverage | pytest --cov | 91% lines |
| V2 Boundary | 48 | bugs fixed |
| V3 Pairwise | 50 | 0 sign-flip |
| V4 Determinism | 11 | 11/11 bitwise |

**354 unit tests + 45 calibration tests — all passing.**

---

## Bugs caught

| # | Bug | Severity |
|---|---|---|
| 1 | chargers bidir column-value mismatch | silent wrong metric |
| 2 | occupancy_jitter wrong variance | silent wrong metric |
| 3 | negotiation_mix metric used row_count | meaningless metric |
| 4 | C4 jitter: arrival > departure | invalid CSV |
| 5 | D6 jitter: arrival_soc > required | impossible state |
| 6 | missing `custom` noise profile | KeyError |

+ 12 declaration corrections in knobs.yaml.

---

## 8. Working examples

Three pre-generated scenarios:

- `S01_baseline` — Nashville mid-season
- `S_clim_miami_summer` — same population, Miami / July
- `S_eq_bi` — baseline + bidirectional chargers

---

## Load profiles compared

![w:80%](../figures/16_load_profiles_compared.png)

---

## Session arrivals

![w:80%](../figures/17_session_arrivals.png)

---

## Charger mixes

![w:80%](../figures/18_chargers.png)

---

## Knob differences

![w:80%](../figures/19_knob_diff.png)

---

## 9. Scope and limits

| Verified | Not verified |
|---|---|
| Pipeline correctness | ACN-Data generalization (research) |
| Reproducibility | Cross-platform binary identity |
| Knob effects | 3+-way knob interactions |
| Invariant survival under noise | Real-V2B realism (research) |
| Determinism | Annual scale |

---

## Closing

- `OVERVIEW.md` for the narrative.
- `notebooks/exploration.ipynb` for the CSVs.
- `data/example_scenarios/` for the three working examples.
- Live frontend coming separately.
