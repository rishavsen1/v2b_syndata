# validate.py — Invariant Specification

40+ invariant checks fired post-render against an output directory:

```
data/output/<exp>/<scenario>/<seed>/{building_load,cars,users,chargers,
                                     grid_prices,dr_events,sessions}.csv
                                   + manifest.json
```

Hard invariants (A–H): failure aborts generation, partial outputs deleted, exit code != 0.
Soft checks (S): warnings logged; do not block.

Each check has an ID for test mapping (`tests/test_consistency.py::<id>`).

## A. Schema-level (per-CSV)

- **A1.** Each expected CSV file exists in output dir
- **A2.** Each CSV has exactly the columns specified in `BAYES_NET.md` (no extras, no missing; column order not enforced)
- **A3.** Column dtypes match schema (str / float / int / timestamp)
- **A4.** No NaN in non-nullable columns
- **A5.** Categorical columns contain only declared choices:
  - `cars.battery_class ∈ {leaf_24, bolt_40, m3_75, rivian_100}`
  - `chargers.directionality ∈ {unidirectional, bidirectional}`
  - `grid_prices.type ∈ {off_peak, peak}`
  - `users.region` ∈ region names declared in scenario's population library entry
  - `users.negotiation_type ∈ {type_i, type_ii, type_iii, type_iv}`

## B. Referential integrity

- **B1.** `set(users.car_id) == set(cars.car_id)` (bijection)
- **B2.** `set(sessions.car_id) ⊆ set(cars.car_id)`
- **B3.** `cars.car_id` unique
- **B4.** `users.car_id` unique
- **B5.** `sessions.session_id` unique
- **B6.** `chargers.charger_id` unique
- **B7.** `dr_events.event_id` unique

## C. Temporal consistency

- **C1.** `building_load.datetime` monotone increasing, exactly 15-min spaced
- **C2.** `grid_prices.datetime` monotone increasing, exactly 15-min spaced
- **C3.** `set(building_load.datetime) == set(grid_prices.datetime)`
- **C4.** ∀ session: `arrival < departure`
- **C5.** ∀ session: `arrival ∈ [building_load.datetime.min(), building_load.datetime.max()]`
- **C6.** ∀ session: `duration_sec == int((departure − arrival).total_seconds())`
- **C7.** ∀ car_id: sort sessions by arrival → `sessions[i].departure ≤ sessions[i+1].arrival` (non-overlap)
- **C8.** ∀ dr_event: `start < end`
- **C9.** ∀ dr_event: `notified_at ≤ start`
- **C10.** ∀ dr_event: `start, end ∈ building_load.datetime range`
- **C11.** ∀ dr_event: `(start − notified_at)` matches notification lead per `dr_program` (CBP=24h, BIP=2h, ELRP variable; tolerance 1 min)

## D. Physical / SoC feasibility

- **D1.** ∀ car: `0 ≤ min_allowed_soc < max_allowed_soc ≤ 100`
- **D2.** ∀ car: `capacity_kwh > 0`
- **D3.** ∀ session: `arrival_soc ∈ [car.min_allowed_soc, car.max_allowed_soc]`
- **D4.** ∀ session: `required_soc_at_depart ∈ [car.min_allowed_soc, car.max_allowed_soc]`
- **D5.** SoC reachability check (only if `required > arrival`):
  ```
  energy_needed_kwh = (required_soc - arrival_soc) / 100 * capacity_kwh
  energy_available_kwh = max(charger.max_rate_kw) * duration_hr
  assert energy_needed_kwh <= energy_available_kwh * 1.05  # 5% slack
  ```
  Discharge case (required < arrival) skips this check.

## E. Charger / capacity

- **E1.** ∀ charger: `min_rate_kw ≤ 0 ≤ max_rate_kw`
- **E2.** ∀ unidirectional charger: `min_rate_kw == 0`
- **E3.** ∀ bidirectional charger: `min_rate_kw < 0`
- **E4.** ∀ bidirectional charger: `|min_rate_kw| ≈ max_rate_kw` (symmetric, ±1% tolerance)
- **E5.** Concurrent active sessions check:
  ```
  For each timestamp in building_load.datetime:
    active = count(sessions where arrival ≤ t < departure)
    assert active <= len(chargers)
  ```
  Warn at ≥ 90% utilization, fail at > capacity.

## F. CONSENT / negotiation

- **F1.** ∀ user: `w1 ≥ 0` and `w2 ≥ 0`
- **F2.** ∀ user: `w1, w2` finite (no inf, no NaN)
- **F3.** Per-cluster `mean(w1)`, `mean(w2)` within 2σ of `user_types.yaml` cluster mean (loose statistical sanity)
- **F4.** Population shares of `negotiation_type` within 0.05 of scenario's `negotiation_mix` knob (sampling noise; tighten as N grows)
- **F5.** Population shares of `region` within 0.05 of scenario's `axes_distribution` weights

## G. Behavioral axes

- **G1.** ∀ user: `phi ∈ [0, 1]`
- **G2.** ∀ user: `kappa ∈ [0, 1]`
- **G3.** ∀ user: `delta_km ≥ 0`
- **G4.** ∀ user: `(phi, kappa, delta_km)` falls within bounds of declared `region`

## H. Tariff / DR

- **H1.** if `tariff_type == flat`: `grid_prices.type == "off_peak"` everywhere AND `price_per_kwh` constant
- **H2.** if `tariff_type ∈ {TOU, demand_charge, DR}`:
  - `price_per_kwh` on peak hours (per `peak_window`) == `energy_price_peak`
  - `price_per_kwh` on off-peak == `energy_price_offpeak`
- **H3.** if `dr_program != none`: `len(dr_events) ≥ 1` (unless sim window is too short for any to land)
- **H4.** if `dr_program == none`: `len(dr_events) == 0` (header-only file)
- **H5.** DR event count consistent with program type:
  - CBP: 1–6 events / month, May–Oct only
  - BIP: 1–4 events / month, year-round
  - ELRP: 1–10 events / season, May–Oct preferred
- **H6.** ∀ dr_event: `magnitude_kw ∈ dr_magnitude_kw_range` knob

## I. Manifest

- **I1.** `manifest.json` exists, parses, has required keys: `{scenario_id, seed, knob_overrides, knob_resolution, generator_git_sha, csv_row_counts, csv_sha256, noise_profile}`
- **I2.** `manifest.csv_row_counts` matches actual row counts
- **I3.** `manifest.csv_sha256` matches actual file hashes (SHA-256 of file bytes)
- **I4.** Every knob in `knobs.yaml` appears in `manifest.knob_resolution` with source ∈ `{explicit, descriptor:<name>, default}`

## Soft distribution checks (warnings only)

Live in `tests/test_distributions.py`. Run as `validate.py --soft`.

- **S1.** KS-distance: building_load duration curve vs EnergyPlus prior < 0.10 (when EnergyPlus integrated; stub mode skips)
- **S2.** KS-distance: arrival distribution vs ACN-Data per region < 0.15 (stub mode skips)
- **S3.** Energy balance: Σ session energy delivered ≤ Σ available charger throughput × duration × efficiency_factor (1.0 in v1)
- **S4.** ψ_freq, ψ_consist, ψ_accept computed from users.csv fall in scenario's expected ψ tier (LOW / MED / HIGH per population library entry)
- **S5.** Building-Population coupling check (D21): if scenario's `population` differs from `building.default_population`, emit warning naming both
