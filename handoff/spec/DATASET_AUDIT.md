# Dataset Audit — what data goes where

Authoritative reference for every external dataset used by the V2B generator.

## Active datasets (5)

| # | Dataset | Owner / Access | Used for | DAG location |
|---|---|---|---|---|
| 1 | **NASAPower** | NASA / public API | Weather time series: temperature, humidity, irradiance, wind | Tier 1 root `W` → feeds `L_flex` (HVAC load) and `dr_events.csv` (Poisson rate λ depends on max temperature) |
| 2 | **DOE Commercial Reference Buildings** | DOE / public | EnergyPlus thermal models per archetype × climate zone | Tier 1 root `A, S` → selects `.idf` for EnergyPlus simulation |
| 3 | **ASHRAE 90.1 occupancy schedules** | ASHRAE / standard | Median per-archetype occupancy (people/m², hourly fraction) | Tier 1 root `O` → base schedule, modulated by EV-user pipeline |
| 4 | **CONSENT survey** | Yours, n=28 | k-means clusters → 4 negotiation types, mean/std for $(w_1, w_2)$ | Tier 1 root `U` → populates `negotiation_mix` and per-user CONSENT weight sampling |
| 5 | **CBP/BIP program rules + CAISO aggregate DR stats** | PG&E tariffs + CAISO public CSV exports | Inhomogeneous Poisson rate calibration for DR event sampling | Tier 3 renderer `dr_events.csv` |

## Calibration datasets (1)

| # | Dataset | Owner / Access | Used for | DAG location |
|---|---|---|---|---|
| 6 | **ACN-Data** | Caltech / public | Per-region fits for ZINB (count), Weibull (dwell), Beta (arrival SoC); Gaussian copula for (arrival, dwell) joint | Calibration only — fits Tier 2 latent samplers offline. Output written to `configs/populations.yaml`. |

## Rejected / parked

| # | Dataset | Why |
|---|---|---|
| 7 | NREL EULP / ComStock | Superseded by EnergyPlus + DOE pipeline (Asset 1 in conversation) |
| 8 | Nissan EV user model | Proprietary. Distribution families (ZINB/Weibull/Beta) kept; parameters re-fit to ACN-Data publicly. |
| 9 | RF model on per-event DR records | Per-customer event archives not openly available at sufficient granularity. Replaced by D20 rule-based Poisson sampler. |
| 10 | EVAdoption / Argonne ANL fleet stock | Future calibration of `battery_mix` defaults; v1 uses hand-specified per-archetype defaults |
| 11 | NHTS commute distance distribution | Future calibration of `δ` (commute distance axis); v1 uses hand-specified region ranges |

## Per-CSV traceability

Every output column traced to its data source.

### `building_load.csv`
- `power_flex_kw` — EnergyPlus simulation: DOE prototype (#2) + NASAPower weather (#1) + ASHRAE occupancy (#3, modulated by `O`)
- `power_inflex_kw` — same simulation, different EnergyPlus end-use columns

### `cars.csv`
- All columns — scenario knobs (`battery_mix`). Currently no external dataset.

### `users.csv`
- `behavioral_axes (φ, κ, δ)` — Sampled per `populations.yaml` region grid; calibrated against ACN-Data (#6)
- `negotiation_type` — Sampled from CONSENT cluster mix (#4)
- `w1, w2` — CONSENT cluster mean/std (#4), scaled by `w_multiplier` knob

### `chargers.csv`
- All columns — scenario knobs only

### `grid_prices.csv`
- All columns — scenario knobs. Defaults sourced from public utility filings (TVA, SVP, PG&E) as references, not loaded data.

### `dr_events.csv`
- All columns — D20 inhomogeneous Poisson sampler. Rate λ(t) function of (month, day-of-week, max forecast temperature, time-of-day). Calibrated to:
  - PG&E CBP/BIP/ELRP program rules (#5): season bounds (CBP May–Oct), notification lead (CBP=24h, BIP=2h, ELRP variable), magnitude ranges, cap on events/month
  - CAISO aggregate DR dispatch CSV (#5): event timing distribution
- Magnitude `magnitude_kw` — sampled from program-typical range per program
- `notified_at = start − notification_lead` deterministic given program type

### `sessions.csv`
- `arrival, departure` — joint sample via Gaussian copula on `(f_arr, f_dwell)` per population region. Marginals fit to ACN-Data per region (#6); copula correlation ρ also fit per region.
- `arrival_soc` — Beta(α, β) fit per region (#6), shifted by `commute_proxy_mi · k_kWh_per_mi` heuristic
- `required_soc_at_depart` — TruncNorm(μ, σ), per-region defaults; floored at `min_depart_soc` knob
- `previous_day_external_use_soc` — derived from prior session SoC, deterministic

## Honest gaps (paper's "limitations" section)

| Gap | Current state | Better source |
|---|---|---|
| Behavioral axis grid bounds | Hand-specified in `populations.yaml` regions | ACN-Data per-user (φ, κ, δ) empirical distribution → kernel density / mixture fit |
| Commute distance ranges | Hand-specified per region | NHTS commute survey |
| Battery class distribution | Hand-specified per Population library entry | EVAdoption / Argonne ANL fleet stock |
| Charger fleet realism | Knob-only; library entries reflect generic deployments | EVI-Pro Lite / AFDC station data |
| Within-region heterogeneity | Uniform sample within region bounds | Per-region kernel density or Gaussian fit |

None block Step 3. Each maps to one library entry or parameter file → upgradeable in Phase 2.

## Paper dataset story (preview)

> We construct synthetic V2B scenarios using a generative Bayes Net with five external data inputs: (1) NASAPower weather time series and DOE commercial reference building models simulated through EnergyPlus produce flex/inflex building load traces; (2) ASHRAE 90.1 occupancy schedules serve as base occupancy, modulated by an EV-user-data signal; (3) ACN-Data workplace charging records calibrate per-region arrival, dwell, and arrival-SoC distributions (ZINB, Weibull, Beta) along with a Gaussian copula on the (arrival, dwell) joint; (4) the CONSENT survey (n=28) defines four negotiation user clusters with empirical inconvenience weights; (5) PG&E CBP/BIP program rules and CAISO aggregate dispatch statistics calibrate an inhomogeneous Poisson sampler for demand response events. All knobs not derived from data — fleet composition, charger deployment, tariff schedules — are exposed as user-configurable parameters with realistic defaults sourced from public utility filings.
