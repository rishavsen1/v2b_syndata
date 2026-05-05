# V2B Synthetic Dataset Generator — Plan (v3)

## What we are building

A configurable program that produces synthetic V2B simulation input data. You describe a scenario via 4 high-level descriptors (Location, Building, Population, Equipment), and the program generates a consistent set of CSV files that downstream simulators consume.

The program is a **generative model**: each scenario sets the parameters of a sampling process, and a random seed produces one realization. Different seeds produce different realizations with the same statistics. The same seed always produces the same files (bitwise identical).

## Why we are building it

Methods paper on FSL + CONSENT + Persistence stack needs experimental scenarios that vary along controlled axes. Real datasets don't span the factor space we care about. Synthetic data gives us controlled, reproducible scenarios for experiments E1–E8.

## What gets produced per scenario

Six CSVs, one sidecar, one DR file (always emitted, possibly empty), one manifest:

1. `building_load.csv` — building electrical load split into `power_flex_kw` (HVAC + water systems) and `power_inflex_kw` (lighting + equipment)
2. `cars.csv` — vehicle physics (battery class, capacity, SoC bounds)
3. `users.csv` — sidecar with behavioral axes (φ, κ, δ), negotiation type, CONSENT weights
4. `chargers.csv` — charger fleet (count, directionality, rates)
5. `grid_prices.csv` — energy price tape over simulation window
6. `dr_events.csv` — demand response events (always emitted; empty if no DR program)
7. `sessions.csv` — multi-day session log
8. `manifest.json` — reproducibility record

## How users specify scenarios

**Two layers of abstraction:**

**Tier 0: Descriptors (user-facing).** Four named bundles in scenario YAML:

| Descriptor | Bundles | Library file |
|---|---|---|
| Location | climate, weather source, tariff regime | `configs/locations.yaml` |
| Building | archetype, size, occupancy schedule | `configs/buildings.yaml` |
| Population | user types (axes + negotiation), fleet composition | `configs/populations.yaml` |
| Equipment | charger count, directionality, rates | `configs/equipment.yaml` |

**Tier 1: Knobs (canonical DOF inventory).** Every individual parameter, listed in `configs/knobs.yaml`. Power users (experiments) operate here.

**Resolution chain:**

```
resolved_value = CLI override
              or scenario_yaml.overrides[knob]
              or descriptor → library file
              or knobs.yaml default
```

Manifest records source per knob: `explicit | descriptor | default`.

**Example scenario:**

```yaml
scenario_id: S01
descriptors:
  location: nashville_tn
  building: medium_office_v1
  population: consent_default
  equipment: balanced_50pct
overrides:
  utility_rate.peak_window: [16, 21]
```

## Behavioral user model: 3-axis taxonomy

Replaces named classes (office_regular, etc.) with continuous axes:

| Axis | Symbol | Range | Definition |
|---|---|---|---|
| Frequency | φ | [0, 1] | P(user appears on a given weekday) |
| Consistency | κ | [0, 1] | 1 − coefficient of variation of arrival_hour for this user |
| Commute distance | δ | km | One-way commute distance |

Population descriptor specifies a region-grid distribution over (φ, κ, δ): named regions with axis ranges and weights. Per-user values sampled uniformly within assigned region.

## Negotiation model (orthogonal to behavioral)

Per CONSENT paper: 4 clusters from k-means on n=28 survey, each with bivariate weights $(w_1, w_2)$ over (ΔSoC, Δdeparture). Logit acceptance over menu of L flexibility options vs outside option $\bar{E}$. Population mix = 4-simplex over clusters, w_multiplier scales weights.

## Generator architecture: 4 tiers

- **Tier 0 (descriptors):** 4 user-facing named bundles
- **Tier 1 (roots):** 9 nodes — C, W, A, S, O, T, U, F, X. Set deterministically from descriptor expansion.
- **Tier 1.5 (per-entity instantiation):** 2 nodes — A_user (per-car attributes) and A_fleet (per-car battery). Sampled once per car_id; downstream samplers parameterized from these.
- **Tier 2 (latents):** 5 sampled distributions — L_flex, L_inflex, f_arr, f_dwell, f_soc. Joint sampling on (f_arr, f_dwell) within population region via Gaussian copula.
- **Tier 3 (renderers):** 7 output CSVs.

Implementation: plain Python, `networkx.DiGraph` for topology, per-node sampler functions in a registry. Per-car_id seeded sub-streams via `SeedSequence.spawn()`.

## Optional noise layer

Post-render perturbation for adversarial / robustness testing. `configs/noise_profiles.yaml` defines profiles: `clean` (default), `light_noise`, `realistic_noise`, `adversarial`. Defaults to clean. Manifest records noise config separately. Doesn't touch DAG.

## Predictability index ψ

Three orthogonal scalar metrics:

```
ψ_freq    = E[φ]                        over population
ψ_consist = E[κ]                        over population
ψ_accept  = E[1 − P_reject | menu, Ē]   over population (canonical CONSENT menu)
```

ψ as a triple, or scalar via post-hoc regression weights from FSL/CONSENT/Persistence gain analysis.

## Data sources

Authoritative breakdown in `DATASET_AUDIT.md`. Quick reference:

| Component | Source |
|---|---|
| Building load (flex + inflex) | EnergyPlus + DOE prototypes + NASAPower weather + ASHRAE occupancy |
| EV sessions parametric families | ZINB / Weibull / Beta — calibrated to ACN-Data |
| EV session correlation | Gaussian copula on (arrival, dwell) within behavioral region — fit to ACN-Data |
| CONSENT weights | CONSENT survey clusters (n=28) |
| DR events | Inhomogeneous Poisson, λ(t) calibrated to PG&E CBP/BIP rules + CAISO aggregate stats |
| Grid prices | Synthetic, rule-based with utility-anchored defaults |

## Project sequence

| Step | Output | Status |
|---|---|---|
| 1 | Schema + knob registry + descriptor layer + Tier 1.5 | **Done.** |
| 2 | Data source decisions (EnergyPlus pipeline integration plan) | **Done.** |
| 3 | Renderer stubs — type-correct dummy CSVs passing all hard invariants | **Next.** |
| 4 | Integrate EnergyPlus pipeline as L_flex/L_inflex sampler | |
| 5 | ACN-Data calibration: fit ZINB/Weibull/Beta + copula per region | See `ACN_DATA_CALIBRATION.md` |
| 6 | DR sampler: implement inhomogeneous Poisson per CBP/BIP rules | |
| 7 | Generate S01 × N seeds, validate ψ-spanning | |
| 8 | Roll out remaining anchor scenarios | |
| 9 | Run E1 (toggle ablation) | Headline figure |
| 10 | Run E2–E8 | Full paper |

## Parked

- Datasheet for Datasets, Croissant metadata, baseline benchmarking suite, leaderboard infrastructure, DOI archival, maintenance plan
- PV (removed)
- Holiday/weekend handling (weekdays only for v1)
- RF model on per-event DR records (D22 — data not openly available)
- Mixture-of-Gaussians for axes distribution (region-grid for v1 — D28)

## Validation

**Hard invariants** (block generation): ~40 checks across schema, referential integrity, temporal consistency, SoC feasibility, charger capacity, CONSENT weight sanity, DR consistency, manifest completeness.

**Soft distribution checks** (warnings): KS-distance vs ACN-Data marginals, KL on copula correlation, ψ tier match, energy balance.

## Expected output volume

S01 default (20 EVs, 4-week seasonal sim window, weekdays only):
- `building_load.csv`, `grid_prices.csv`: ~7,680 rows each
- `cars.csv`, `users.csv`, `chargers.csv`: 20 rows each
- `sessions.csv`: ~400 rows (varies with φ)
- `dr_events.csv`: 0 rows for S01 (no DR)

≈1–2 MB per scenario seed. Cheap to store many seeds per scenario.
