# V2B Generator — Complete Bayes Net Specification (v3)

Reflects all decisions D1–D28 plus Tier 1.5 (per-entity instantiation layer). Supersedes v2.

## Tier 0: User-facing descriptors

Four named bundles; each resolves into a subset of Tier 1 roots via library files.

| Descriptor | Library file | Resolves into Tier 1 roots |
|---|---|---|
| Location | `configs/locations.yaml` | C, W, T |
| Building | `configs/buildings.yaml` | A, S, O |
| Population | `configs/populations.yaml` | U, F |
| Equipment | `configs/equipment.yaml` | X |

**Resolution chain:** CLI override > scenario YAML overrides > descriptor expansion > `knobs.yaml` default.

**Building–Population coupling (D21, loose):** Building library entries carry `default_population` recommendation. Validation warns on incongruent combinations; does not block.

## Tier 1: Exogenous roots (set deterministically)

Nine root nodes. Distribution P(node) is a delta at the configured value.

| Node | Bundles knob group | Holds |
|---|---|---|
| C | building_load.climate | Climate label (categorical) |
| W | building_load.weather | NASAPower weather pull |
| A | building_load.archetype | Archetype label |
| S | building_load.size | Size label |
| O | building_load.occupancy | Occupancy schedule (EnergyPlus + ASHRAE) |
| T | utility_rate.* | Tariff config (type, prices, peak window, DR program) |
| U | user_behavior.* | Population spec (axes_distribution, negotiation_mix, w_multiplier, menu) |
| F | ev_fleet.* | Fleet spec (count, battery_mix, heterogeneity) |
| X | charging_infra.* | Charger config |

## Tier 1.5: Per-entity instantiation (sampled per car)

**Two nodes that produce per-car_id assignments BEFORE distribution-level latents fire.** Makes per-user/per-vehicle sampling an explicit step rather than implicit in downstream samplers.

### Node `A_user` — per-user assignments
- **Parents:** U
- **Output:** `dict[car_id → {region_name, phi, kappa, delta_km, negotiation_type, w1, w2}]`
- **Sampler:**
  1. For each `car_id` in 1..ev_count:
     - Sample `region ~ Categorical(axes_distribution.weights)`
     - Sample `(phi, kappa, delta_km) ~ Uniform(region.bounds)`
     - Sample `negotiation_type ~ Categorical(negotiation_mix)` independently
     - Sample `(w1, w2) ~ Normal(cluster_mean[neg_type], cluster_std[neg_type])` clipped ≥ 0
     - Apply `w_multiplier`: `w1 *= α_w1; w2 *= α_w2`
- **Why explicit:** dedicated seed sub-stream per car (`SeedSequence.spawn` keyed by car_id); natural debug surface; renders users.csv as trivial dump; ACN-Data calibration target = A_user's empirical distribution

### Node `A_fleet` — per-vehicle assignments
- **Parents:** F
- **Output:** `dict[car_id → {battery_class, capacity_kwh, min_allowed_soc, max_allowed_soc}]`
- **Sampler:**
  1. For each `car_id`:
     - If `battery_heterogeneity == homog`: pick mode of `battery_mix`
     - Else: sample `battery_class ~ Categorical(battery_mix)`
  2. Lookup `capacity_kwh` from class spec
  3. Set SoC bounds (typically `min=10%, max=100%`)
- **Why explicit:** parallels A_user; cars.csv becomes trivial dump; battery class assignment is reproducibly seeded per car_id

## Tier 2: Latent intermediates (sampled distributions)

Five latents. f_arr/f_dwell/f_soc are now **parameterized by A_user**, not directly by U.

### Node `L_flex` — flexible building load
- **Parents:** A, S, W, O
- **Output:** float series (kW), 15-min over sim window
- **Sampler:** EnergyPlus run with DOE prototype = (A, S), weather file = W, occupancy schedule = O. Extract end-use: cooling, heating, fans, water systems. Sum to L_flex(t). Apply ±5% Gaussian per-timestep realism noise (separate from D25 noise layer).

### Node `L_inflex` — inflexible building load
- **Parents:** A, S, O
- **Output:** float series (kW), 15-min over sim window
- **Sampler:** Same EnergyPlus run. Extract: interior_lighting, exterior_lighting, interior_equipment. Sum. Apply ±3% Gaussian noise.

### Node `f_arr` — per-user arrival distribution (parameterized)
- **Parents:** A_user
- **Output:** for each car_id, a per-day arrival distribution with parameters (μ_arr_v, σ_arr_v) where σ_arr_v decreases with κ_v
- **Sampler:** Define TruncNorm(μ_arr_v, σ_arr_v) per user. Per-day appearance gated by Bernoulli(φ_v). Joint with f_dwell via Gaussian copula (correlation ρ_v from region).

### Node `f_dwell` — per-user dwell distribution (parameterized)
- **Parents:** A_user
- **Output:** per-user Weibull(k_v, λ_v) where shape/scale depend on (φ_v, κ_v)
- **Joint with f_arr:** Gaussian copula correlation ρ from region (calibrated against ACN-Data per ACN_DATA_CALIBRATION.md)

### Node `f_soc` — per-user arrival SoC distribution (parameterized)
- **Parents:** A_user
- **Output:** per-user Beta(α_v, β_v) shifted by `δ_v · k_kWh_per_mi` heuristic; clipped to [min_allowed_soc, max_allowed_soc]

## Tier 3: Output renderers

### `building_load.csv`
- **Parents:** L_flex, L_inflex, knob `peak_kw`
- **Renderer:** Joint rescale to peak_kw. Write columns: `datetime, power_flex_kw, power_inflex_kw`.

### `cars.csv`
- **Parents:** A_fleet
- **Renderer:** Trivial dump of A_fleet to CSV.

### `users.csv` (sidecar)
- **Parents:** A_user
- **Renderer:** Trivial dump of A_user to CSV. Columns: `car_id, region, phi, kappa, delta_km, negotiation_type, w1, w2`.

### `chargers.csv`
- **Parents:** X
- **Renderer:** Compute n_bi, n_uni; emit rows.

### `grid_prices.csv`
- **Parents:** T
- **Renderer:** 15-min grid; assign peak/off_peak per `peak_window`.

### `dr_events.csv`
- **Parents:** T, W, C
- **Renderer (D20):** Inhomogeneous Poisson process.
  1. Determine program type from T (CBP, BIP, ELRP, none)
  2. If none: emit header-only file
  3. Else: λ(t) = λ_base × seasonal(t) × dow(t) × temp_factor(W.max_temp_today) × tod_factor(t)
  4. Sample event arrivals via thinning
  5. Per event: magnitude ~ Uniform(program_typical_range); notified_at = start − notification_lead (CBP=24h, BIP=2h, ELRP variable)
  6. Cap events per month at program limit

### `sessions.csv`
- **Parents:** f_arr, f_dwell, f_soc, A_user, A_fleet
- **Renderer:**
  1. For each car_id, for each weekday in sim window:
     a. Bernoulli(φ_v) gates appearance
     b. If appearing: joint sample (arrival, dwell) via copula → arrival timestamp, departure
     c. Sample arrival_soc from f_soc_v
     d. Sample required_soc_at_depart from per-region TruncNorm; floor at min_depart_soc
     e. Compute previous_day_external_use_soc
  2. Non-overlap rejection per car_id

## Sampling order (topological, updated for Tier 1.5)

```
1. Read scenario YAML + CLI overrides
2. Resolve descriptors → Tier 1 roots (Location→C,W,T; Building→A,S,O; Population→U,F; Equipment→X)
3. Tier 1.5 — per-entity instantiation:
   3a. A_user from U (per car_id: region, φ, κ, δ, neg_type, w1, w2)
   3b. A_fleet from F (per car_id: battery_class, capacity, SoC bounds)
4. Tier 2 — latent distributions:
   4a. L_flex, L_inflex via EnergyPlus pipeline (A, S, W, O)
   4b. f_arr, f_dwell, f_soc — parameterize per-user from A_user
5. Render trivial outputs:
   5a. chargers.csv from X
   5b. grid_prices.csv from T
   5c. dr_events.csv from (T, W, C) via inhomogeneous Poisson
   5d. users.csv ← dump A_user
   5e. cars.csv ← dump A_fleet
   5f. building_load.csv ← rescale (L_flex + L_inflex)
6. Render sessions.csv per car_id × weekday with copula-joint draws + non-overlap rejection
7. Apply optional noise layer (D25; default = clean)
8. Validate (validate_spec.md invariants A1–H4)
9. Write manifest.json with knob_resolution sources + per-node seed sub-streams
```

## Coupling

Previous coupling priors (A×S→F,X, F↔X, U×A) handled by **library curation** in Tier 0.

Remaining live coupling:
- **W × T → dr_events.csv:** weather feeds Poisson rate; tariff selects program
- **A_user → (f_arr, f_dwell):** per-user (φ, κ) parameterizes joint copula

## Implementation

- Python 3.11+
- `networkx.DiGraph` for topology + topological sort
- Per-node sampler functions in `samplers: dict[str, Callable]`
- No pgmpy
- **Reproducibility:** root `numpy.random.SeedSequence` → `spawn()` per node; A_user further `spawn()`s per car_id for stable per-entity seeds across topology changes
- EnergyPlus integration: adapter wrapping existing pipeline
- Validation: `validate.py` runs ~40 hard invariant checks post-render

## Summary table

| Tier | Node | Parents | Sampler form | Output |
|---|---|---|---|---|
| 0 | Location, Building, Population, Equipment | knobs | resolution | Tier 1 root values |
| 1 | C–X (9 roots) | descriptors / explicit / default | delta | bundled root values |
| 1.5 | A_user | U | per-car Cat + Uniform + Normal | dict[car_id → user attrs] |
| 1.5 | A_fleet | F | per-car Categorical | dict[car_id → battery attrs] |
| 2 | L_flex | A, S, W, O | EnergyPlus + noise | flex load series |
| 2 | L_inflex | A, S, O | EnergyPlus + noise | inflex load series |
| 2 | f_arr | A_user | per-user TruncNorm × Bernoulli(φ) | parameterized arrival dist |
| 2 | f_dwell | A_user | per-user Weibull (joint with f_arr) | parameterized dwell dist |
| 2 | f_soc | A_user | per-user Beta + δ shift | parameterized SoC dist |
| 3 | building_load.csv | L_flex, L_inflex | rescale + write | CSV |
| 3 | cars.csv | A_fleet | dump | CSV |
| 3 | users.csv | A_user | dump | CSV |
| 3 | chargers.csv | X | deterministic | CSV |
| 3 | grid_prices.csv | T | deterministic | CSV |
| 3 | dr_events.csv | T, W, C | inhomogeneous Poisson | CSV |
| 3 | sessions.csv | f_*, A_user, A_fleet | per-user-day copula sample + reject | CSV |
