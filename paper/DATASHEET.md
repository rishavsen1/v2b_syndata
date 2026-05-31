# Datasheet for v2b_syndata

This datasheet follows the template proposed by Gebru et al., *"Datasheets for Datasets"* (Communications of the ACM, 2021).

`v2b_syndata` is not a fixed dataset; it is a **generative artifact**: a configurable synthetic V2B (Vehicle-to-Building) dataset generator. A scenario YAML file and a random seed are the inputs; the outputs are 7 bitwise-identical CSVs plus a `manifest.json` reproducibility record. The "dataset", for the purposes of this datasheet, is the union of (the generator code, the 41+ pre-built scenario configurations shipped with it, and the four real-data calibration sources whose statistics are baked into the parametric distributions). Wherever the Gebru template asks about "instances", we answer in two voices: the **generative artifact** (the program) and a **realization** (one scenario × seed run producing 7 CSVs + manifest).

---

## 1. Motivation

### For what purpose was the dataset created?

To provide a controllable, reproducible substrate for V2B (Vehicle-to-Building) research. Empirical V2B datasets do not span the factor space that algorithmic and policy work needs (climate × building archetype × fleet × tariff × demand-response × user-behavior). `v2b_syndata` lets a researcher describe a scenario via four high-level descriptors (Location, Building, Population, Equipment) and a random seed, and then produces consistent CSV inputs for downstream simulators (e.g. ACN-Sim, CVXPY-based MPC harnesses, RL training loops). The generator was built specifically to support experiments E1–E8 described in `handoff/spec/PLAN.md` — toggle-ablation of a FSL/CONSENT/Persistence stack — but the artifact is general-purpose.

A secondary purpose is **methodological**: by exposing every parameter as an audited "knob" with provenance (`explicit | descriptor | calibration:<provenance> | default`), the generator makes it possible to attribute downstream simulation results back to specific design choices. See `docs/KNOB_REFERENCE.md` and `docs/PAIRWISE_AUDIT.md`.

### Who created the dataset?

The generator was implemented by the authors of the accompanying paper (Rishav Sen and collaborators at Vanderbilt). It is open-source; external contributions are welcomed via the knob-registry and calibration-source protocols documented in `docs/KNOB_REFERENCE.md` and `src/v2b_syndata/calibration/sources/`.

### Who funded the creation?

`[TODO at submission time]` — funding acknowledgements will be added at deanonymization. The development used publicly available datasets (ACN-Data, EV WATTS, INL EV Project Phase 1, ElaadNL Open Charging Transactions) and standards/tooling (EnergyPlus 23.2, ASHRAE 90.1-2019 prototypes, PG&E/CAISO public DR program rules) — no proprietary data sources.

### Any other comments?

`v2b_syndata` is intentionally **not** a leaderboard-style fixed benchmark. The artifact is a generator; the 41+ committed scenarios under `configs/scenarios/` constitute a *suggested coverage atlas*, not the only legal inputs. Users are expected to write new scenario YAMLs targeting their own research questions. The reproducibility contract is at the (scenario, seed) level, not at the level of any single CSV corpus.

---

## 2. Composition

### What do the instances that comprise the dataset represent?

Two distinct senses of "instance":

1. **Scenario configurations** — `configs/scenarios/<scenario>.yaml` files. Each is a small YAML declaring four descriptors (Location, Building, Population, Equipment) plus optional knob-level overrides. 41+ ship in the repo today (e.g. `S01.yaml`, `S_clim_miami_summer.yaml`, `S_dr_cbp.yaml`, `S_psi_010.yaml`, `S_scale_500.yaml`, `S_acn_workplace.yaml`, `S_evwatts_workplace.yaml`, `S_inl_residential_legacy.yaml`, `S_elaadnl_public_eu.yaml`).
2. **Realizations** — a tuple `(scenario, seed)` produces a directory of 7 CSVs + `manifest.json`:
   - `building_load.csv` — flex (HVAC, water systems) and inflex (lighting + equipment) electrical load at 15-min resolution
   - `cars.csv` — per-vehicle physics (battery class, capacity_kwh, min/max allowed SoC)
   - `users.csv` — per-driver behavioral axes (φ frequency, κ consistency, δ commute distance) plus CONSENT negotiation type and weights (w1, w2)
   - `chargers.csv` — charger fleet (count, directionality, rated rates)
   - `grid_prices.csv` — 15-min energy price tape with peak / off-peak labels
   - `dr_events.csv` — demand-response events (header-only when `dr_program=none`)
   - `sessions.csv` — multi-day charging session log
   - `manifest.json` — reproducibility record (per-knob resolution + source, SHA-256 of every CSV, EnergyPlus version, calibration provenance, E5 concurrency report)

CSV column schemas are specified normatively in `handoff/spec/BAYES_NET.md` and enforced by ~40 hard invariants in `handoff/spec/validate_spec.md`, grouped as:

- **A. Schema-level** (A1–A5): file existence, exact column set, dtype match, no NaN in non-nullable columns, categorical values from declared choice sets.
- **B. Referential integrity** (B1–B7): `set(users.car_id) == set(cars.car_id)`, `set(sessions.car_id) ⊆ set(cars.car_id)`, unique IDs.
- **C. Temporal consistency** (C1–C11): 15-min monotone increasing timestamps, identical datetime grids for `building_load.csv` and `grid_prices.csv`, arrival < departure, session timestamps inside the building-load window, DR event notification-lead matches program rules.
- **D. Physical / SoC feasibility** (D1–D7): SoC bounds well-formed, capacity > 0, arrival_soc and required_soc_at_depart inside `[min_allowed_soc, max_allowed_soc]`, energy-reachability via `max(charger.max_rate_kw) × duration_hr × 1.05`, `required > arrival`, `required ≥ min_depart_soc × 100`.
- **E. Charger / capacity** (E1–E5): per-charger rate sign discipline, bidirectional symmetry, concurrent-active ≤ charger count.
- **F. CONSENT / negotiation** (F1–F5): `w1, w2 ≥ 0` and finite, per-cluster mean within 2σ of `user_types.yaml`, population shares of negotiation type and region within `F_SHARE_TOL = 0.20` of configured weights (relaxed from spec's 0.05 due to ev_count=20 sample size).
- **G. Behavioral axes** (G1–G4): `phi, kappa ∈ [0, 1]`, `delta_km ≥ 0`, sampled `(phi, kappa, delta_km)` falls within the declared region's bounds.
- **H. Tariff / DR** (H1–H6): flat tariff has constant price; TOU prices match peak window exactly (broken legitimately under `price_jitter > 0`, see `docs/CALIBRATION_NOTES.md` item 13); DR event counts respect program rules (CBP May–Oct, BIP year-round, ELRP May–Oct preferred); magnitudes within configured range.
- **I. Manifest** (I1–I4): manifest exists with required keys, `csv_row_counts` and `csv_sha256` agree with on-disk files, every knob in `knobs.yaml` is resolved with a source tag.

Soft distribution checks (warnings, do not block) live in `tests/test_distributions.py`: KS-distance vs EnergyPlus prior (S1), KS-distance vs ACN per-region (S2), energy balance (S3), ψ tier match (S4), and a Building↔Population coupling check (S5).

### How many instances are there in total?

- **Scenarios shipped**: 41+ pre-built scenario YAMLs under `configs/scenarios/`, spanning climate × season (Atlanta, Miami, Minneapolis, San Francisco, San Jose × spring/summer/fall/winter), building archetype (office, retail, mixed-use; small/medium/large), fleet scale (20–500 EVs), charger count (50–200), DR program (none, CBP, BIP, ELRP), tariff regime (flat, TOU, demand-charge), behavioral population (consent_default, acn_workplace_baseline, evwatts_workplace_public, evwatts_dcfc_public, inl_residential_legacy, elaadnl_public_eu, plus consent variants), and ψ predictability targets (0.10, 0.25, 0.50, 0.75, 0.90).
- **Realizations**: unbounded. The generator can produce arbitrary new (scenario, seed) realizations on demand. The reproducibility contract guarantees that the same (scenario, seed) → bitwise-identical CSVs across runs and platforms. See `docs/DESIGN_NOTES.md` item #8.
- **Total degrees of freedom**: documented at `docs/KNOB_REFERENCE.md`. Registry knobs (~50) span `ev_fleet.*`, `charging_infra.*`, `user_behavior.*`, `building_load.*`, `utility_rate.*`, `sim_window.*`, and `noise.*`. Deep-channel per-region distribution parameters add 7 leaves per region (`arrival.{mu,sigma}`, `dwell.{k,lambda}`, `soc_arrival.{alpha,beta}`, `copula.rho_gaussian`), with typically 5 regions per population and several populations. Every knob is monotonicity-audited against every output CSV column (Stage 1 + Stage 2) — see `docs/KNOB_AUDIT_S1.md` and `docs/KNOB_AUDIT_S2.md`.

### Does the dataset contain all possible instances or is it a sample?

The artifact **is** the population of possible instances, parameterized. The 41+ shipped scenarios are an opinionated curated sample meant to cover the factor space relevant to FSL/CONSENT/Persistence experiments and to anchor reproducibility tests. Per-(scenario, seed) realizations are samples from a known generative model whose structure is documented in `handoff/spec/BAYES_NET.md`.

### What data does each instance consist of?

A scenario YAML is a few hundred bytes. A realization directory (per scenario × seed) is typically ~1–2 MB at the S01 default size (20 EVs, calendar-month sim window). The 7 CSVs follow strict schemas (column set, dtype, no NaN in non-nullable columns) — see `handoff/spec/validate_spec.md` checks A1–A5. The `manifest.json` carries:

- `knob_resolution` block: `{knob_path: {value, source}}` with source ∈ `{explicit, descriptor:<name>, calibration:<provenance>, hand_specified:<population>, default}`
- `csv_sha256` dict: per-CSV content hash
- `e5` block: realized max concurrent sessions, n_chargers, infeasible-tick fraction (see `docs/DESIGN_NOTES.md` #30)
- `calibration_metadata` (when a calibrated population is used): provenance string, capacity-inference fallback rate, unassigned-user rate, per-region n_samples and `ks_fit_quality`
- Optional `noise.d5_enforcement` block when noise jitter is active

### Is there a label or target associated with each instance?

There is no single supervised "label" — `v2b_syndata` is a generative dataset, not a labeled benchmark. However, several **derived analytic targets** are surfaced:

- **ψ (predictability index)** — triple `(ψ_freq, ψ_consist, ψ_accept)` summarizing the population, defined in `handoff/spec/PLAN.md` §"Predictability index ψ". Several scenarios target a specific ψ band (`S_psi_010.yaml`, …, `S_psi_090.yaml`).
- **`sessions.required_soc_at_depart`** — the per-session user-stated charging target, which downstream V2B schedulers treat as the constraint to satisfy.
- **`manifest['e5']`** — per-realization infeasibility report.

Downstream tasks (peak shaving, DR participation, MPC scheduling, RL training) impose their own task-specific labels on top of these data.

### Is any information missing from individual instances?

Within the schemas defined in `handoff/spec/BAYES_NET.md`, no — non-nullable columns are enforced free of NaN by invariant A4. Outside the schemas, several quantities are *deliberately not* in the CSVs:

- **No real driver identity.** Drivers in `users.csv` are synthetic `car_id` integers. (See §"Composition — sensitive data" and §"Collection process" for the calibration sources' driver identity caveats.)
- **No realized per-tick charger draws.** `sessions.csv` records arrival/departure SoC targets, not the scheduled or realized kW timeseries — those are produced by downstream simulators consuming `v2b_syndata` as input.
- **No directly observed commute distance.** δ is hand-specified per region; the ACN calibration only proxies it via `userInputs.milesRequested`, which is a noisy stated-target proxy and is **not** persisted to `region_distributions` — see `docs/CALIBRATION_NOTES.md` item 3.
- **No required-SoC distribution from data.** Step 5 calibrates arrival-SoC only; `required_soc_at_depart` remains a hardcoded `TruncNorm(85, 5)`. See `docs/DESIGN_NOTES.md` item 22.

### Are relationships between individual instances made explicit?

Within a realization, yes — referential integrity is checked by invariants B1–B7 (`set(users.car_id) == set(cars.car_id)`, `set(sessions.car_id) ⊆ set(cars.car_id)`, unique IDs). Temporal alignment between `building_load.csv`, `grid_prices.csv`, and `dr_events.csv` is enforced by C1–C11.

Across realizations, the only explicit link is the `manifest.json`, which records the scenario name, seed, knob resolutions, and calibration provenance — enough to identify lineage but not to merge realizations into a single corpus (different seeds are sampled independently).

### Are there recommended data splits?

None at the realization level — `v2b_syndata` is not a supervised benchmark and does not ship train/val/test splits. Recommended **experimental** patterns:

- Per scenario, generate ≥ 5 seeds for Monte Carlo aggregation (the `batch` CLI subcommand automates this; see `docs/CALIBRATION_NOTES.md` item #18). Batch mode opts into the `tmyx_stochastic` noise profile and Dirichlet-perturbed `axes_distribution` / `battery_mix` by default, with `α=30` controlling perturbation strength.
- Treat session-level variation across seeds as within-condition noise, per `docs/CALIBRATION_NOTES.md` item #12 — the D5 rejection sampler couples `max(charger_rate)` and `car.capacity_kwh` to session realizations, so varying either knob shifts session counts in addition to its primary effect. The `affects_csv` declarations in `configs/knobs.yaml` are accurate about this coupling.
- For climate / season generalization: hold out a climate (e.g. Miami) at training time and evaluate on the held-out climate's seasonal scenarios. The factor-cross over climate × season is intentionally orthogonal to fleet / equipment / DR, so leave-one-climate-out splits are meaningful.

For calibration validation: `tools/validate_calibration.py` runs five orthogonal checks (S1 marginal KS + Wasserstein-1, S2 joint Spearman ρ gap, S3 80/20 held-out KS, S5 building-load vs PNNL prototype intent, S6 weekly weekday/weekend ratio) against the two real-calibrated sources (ACN, ElaadNL/4TU). Headline empirical results (50 seeded scenarios per source):

- **S1**: ACN strong-cohort regions K-S 0.11–0.22, W₁ 0.76–1.44; ElaadNL K-S 0.13–0.18, W₁ 0.49–0.61.
- **S2**: All region ρ-gaps below 0.10 (ElaadNL daily_commuter 0.012; ElaadNL weekday_only 0.009; ACN regular_charger 0.044).
- **S3**: Main-region held-out KS deltas within ±0.06 of training-set KS, confirming the parametric fits generalize.
- **S5**: Office small peak/off-peak 4.21× (in PNNL expected 4–8×); office medium 8.54× (above); weekday/weekend ratios 1.04–1.37 (below expected 2.5–8×, surfaced as limitation).
- **S6**: ACN source 5.32× weekday/weekend ratio; ElaadNL 45.7×. Generated produces ≈0 weekend sessions — surfaced as v1 limitation (i.i.d.-per-day arrival sampling).

Held-out KS used a deterministic 80/20 user split (sort by user_id, take first 80% for train). Output CSVs at `data/calibration_validation/{S1_marginals,S2_joint,S3_holdout,S5_buildingload,S6_weekly}.csv`.

### Are there any errors, sources of noise, or redundancies?

Documented and bounded; the relevant catalog lives in `docs/DESIGN_NOTES.md` (31 items) and `docs/CALIBRATION_NOTES.md` (19 items). Highlights:

- **Default mode is bitwise-deterministic.** `noise.profile=clean` (the single-shot CLI default) produces byte-identical CSVs across runs on the same seed; see `docs/DESIGN_NOTES.md` item 8.
- **Optional post-render noise** via `noise.profile` (clean | light_noise | realistic_noise | adversarial | tmyx_stochastic). Jitter bounds preserve hard invariants C4 (arrival<departure) and D6 (required>arrival); D5 reachability may legitimately break under arrival-time jitter (documented in `docs/CALIBRATION_NOTES.md` items 13, 15).
- **Calibration fit weaknesses.** ACN-Data marginal fits show variable KS quality (0.07–0.52); TruncNorm/Weibull/Beta family choice does not perfectly fit all regions (`docs/CALIBRATION_NOTES.md` item 9). The copula correlation transform `ρ_gaussian = 2·sin(π·ρ_spearman/6)` is exact only for bivariate-normal copulas; bias < 0.05 in simulation (item 4).
- **EnergyPlus quirks.** ASHRAE 90.1 MediumOffice prototype produces 0 flex load during unoccupied hours (`docs/DESIGN_NOTES.md` item 12) and a Tuesday-shifted day-of-week schedule (item 16). Two (climate × mixed_use) combinations have a known EnergyPlus SIGSEGV: Houston + mixed_use_v1, Atlanta + mixed_use_v1 (`docs/AUDIT_REPORT.md` A1).
- **Capacity inference fallback.** ACN-Data lacks explicit battery capacity; the fitter infers from `WhPerMile × kWhRequested`. Fallback rate is ~33% on the v1 calibration; high fallback biases the arrival-SoC fit toward a 60 kWh fleet-median assumption (`docs/CALIBRATION_NOTES.md` item 2).
- **Region overlap.** Region (φ, κ) boxes may overlap; assignment is deterministic first-match by `axes_distribution` order (item 5).

422 hard tests and ~40 hard invariants gate generation; the bug catalog in `docs/AUDIT_REPORT.md` is the ground truth for what has been found and resolved.

### Is the dataset self-contained, or does it link to or otherwise rely on external resources?

It depends on external resources at install/generation time, but realizations once produced are self-contained CSVs.

External dependencies:

- **EnergyPlus 23.2.x** binary — must be installed locally; the generator hard-errors (`EnergyPlusBinaryNotFound`) rather than silently falling back to a stub (see `docs/DESIGN_NOTES.md` item 18 and `README.md` "Prerequisites"). Bundled ASHRAE 90.1-2019 Denver-climate-zone prototype IDFs ship with EnergyPlus.
- **TMYx weather files** from `climate.onebuilding.org`, cached locally per station (`docs/DESIGN_NOTES.md` items 19, 29).
- **Calibration source data**: ACN-Data via Caltech's HTTPS API (requires `ACN_API_TOKEN`); EV WATTS, INL EV Project Phase 1, and ElaadNL Open Charging Transactions are reached via the `CalibrationSource` protocol in `src/v2b_syndata/calibration/sources/`. These sources are needed only to *re-run calibration* — the fitted parameters are persisted into `configs/populations.yaml` and shipped with the repo, so generation does **not** require network access to the calibration sources.

Resolved manifest entries that originate from real-data fits carry a `calibration:<provenance>` source tag (e.g. `calibration:acn_data_2019_2021_20260506`); hand-authored regions are tagged `hand_specified:<population_name>` (see `docs/DESIGN_NOTES.md` item 24).

### Does the dataset contain data that might be considered confidential?

No. All shipped CSVs are synthetic. The calibration sources are themselves publicly released datasets (ACN-Data is published with anonymized userIDs; EV WATTS, INL EV Project Phase 1, and ElaadNL Open Charging Transactions are publicly released by DOE/EPRI, Idaho National Lab, and ElaadNL respectively). No proprietary or confidential data is ingested.

### Does the dataset contain data that, if viewed directly, might be offensive or distressing?

No. The data is numeric tabular metering data (timestamps, kW, SoC percentages, prices). No text, images, or audio.

### Does the dataset identify any subpopulations?

Within `users.csv`, behavioral subpopulations are identified by `region` (e.g. `stable_commuter`, `flexible_local`, `occasional_visitor`, `erratic`) and `negotiation_type` (`type_i` through `type_iv`). These are **synthetic** taxonomic labels, not protected demographic attributes. The generator does **not** model or emit race, gender, age, income, or any other protected attribute — these dimensions are not present in either the calibration sources or the output schemas. See `handoff/spec/BAYES_NET.md` "Behavioral user model".

### Is it possible to identify individuals (directly or indirectly) from the dataset?

No, in the generated CSVs — `car_id` and `user_id` columns are synthetic integers with no link to any real driver. The calibration sources retain pseudonymized identifiers (ACN userIDs, INL Vehicle IDs, ElaadNL RFID card IDs, EV WATTS EVSE IDs) only inside the fitter's intermediate `data/calibration/acn_per_user.csv`-style artifacts, which are **not** distributed; only fitted distributional parameters (means, variances, correlations) propagate to shipped configurations. The `user_id_strategy` field in `calibration_metadata` (values: `userID`, `vin_proxy`, `card_proxy`, `port_proxy`) documents the granularity of identity in each source — see `docs/CALIBRATION_NOTES.md` item 11. None of these proxy IDs are exposed in any `users.csv` or `cars.csv` output.

### Does the dataset contain data that might be considered sensitive in any way?

The generator outputs do not contain sensitive data. The upstream calibration sources are public anonymized workplace and residential charging records — their published anonymization is taken as the contract. None of the calibration sources expose health, financial, biometric, religious, political, or other categories typically considered sensitive under GDPR Art. 9 or comparable frameworks. Workplace charging behavior is in principle inferable from session timestamps (which the calibration sources publish); the generator does not republish those raw timestamps, only fitted parametric distributions.

---

## 3. Collection process

### How was the data associated with each instance acquired?

Generated, not collected. Each (scenario, seed) realization is produced by forward-sampling a 4-tier Bayesian network specified in `handoff/spec/BAYES_NET.md`:

- **Tier 0 — Descriptors** (4 user-facing bundles: Location, Building, Population, Equipment)
- **Tier 1 — Roots** (9 deterministic nodes set from descriptor expansion: C, W, A, S, O, T, U, F, X)
- **Tier 1.5 — Per-entity instantiation** (`A_user` per car_id → region, φ, κ, δ, negotiation type, w1, w2; `A_fleet` per car_id → battery class, capacity, SoC bounds)
- **Tier 2 — Latent distributions** (`L_flex`, `L_inflex` via EnergyPlus simulation; `f_arr`, `f_dwell`, `f_soc` as parameterized per-user distributions, with Gaussian copula on `(arrival, dwell)`)
- **Tier 3 — Renderers** (7 CSVs)

Seed sub-streams are derived via `numpy.random.SeedSequence(entropy=seed, spawn_key=(stable_int(name), [car_id]))` with SHA-256-based stable hashing to avoid cross-process drift (`docs/DESIGN_NOTES.md` item 7).

The **parameters** of those Tier-2 distributions, for populations declaring `calibration_policy: acn_data` (or evwatts / inl_ev_project / elaadnl_open_2020), are fit by an MLE pipeline against real per-session data drawn from one of the four calibration sources. See `handoff/spec/ACN_DATA_CALIBRATION.md` for the canonical recipe and `src/v2b_syndata/calibration/` for the implementation.

### What mechanisms or procedures were used to collect the data?

The calibration pipeline (`src/v2b_syndata/calibration/api.py` + per-source fetcher modules):

1. **Fetch.** ACN-Data via `acnportal` and the Caltech HTTPS API (sites: caltech, jpl, office001; years 2019–2021 inclusive). EV WATTS via the Livewire DOE/EPRI bulk-release CSV. INL EV Project Phase 1 via the AVT.INL.GOV Phase 1 release. ElaadNL via the `open-data.elaad.io` Open Charging Transactions release. Each source is implemented as a `CalibrationSource` protocol; new sources extend the policy enum without breaking the generator.
2. **Filter.** Per `docs/CALIBRATION_NOTES.md` §1: drop sessions with null userID, drop users with `n_sessions < 5`, drop users with `< 5 weekdays in their active window`.
3. **Battery capacity inference.** Per-session via `WhPerMile × kWhRequested`; falls back to 60 kWh default when missing (capacity_inference_fallback_rate is logged in manifest).
4. **Per-user feature extraction.** φ = active-weekdays / weekdays-in-user-active-window; κ = 1 − CV(arrival_hour); δ left hand-specified (proxy noise too high — see `docs/CALIBRATION_NOTES.md` item 3).
5. **Region assignment.** Deterministic first-match against `axes_distribution[*]` ordering.
6. **Per-region distribution fits.** TruncNorm (arrival), Weibull (dwell), Beta (arrival_soc), Spearman ρ then `ρ_gaussian = 2·sin(π·ρ_spearman/6)` for the copula. MLE estimates outside `DIST_PARAM_RANGES` are dropped (the "B4 guard" — `docs/CALIBRATION_NOTES.md` item 9).
7. **Writeback** to `configs/populations.yaml` under `region_distributions`, preserving hand-authored blocks byte-equivalent (audited in `docs/AUDIT_REPORT.md` A3).

Generation-time data flow uses **EnergyPlus** (23.2.0, bundled ASHRAE 90.1-2019 Denver prototypes) for `L_flex`/`L_inflex`, an inhomogeneous Poisson sampler (Lewis's thinning) for `dr_events.csv`, and the per-user parameterized samplers for `sessions.csv`.

### If the dataset is a sample from a larger set, what was the sampling strategy?

For the parametric calibration: **convenience sample** — each real-calibrated source is taken in its entirety after the filter chain above. As of 2026-05-30:

- **ACN-Data 2019–2021**: 42,451 sessions / 646 users post-filter (`docs/CALIBRATION_NOTES.md` item 9). 2018 dropped (0% userID coverage at Caltech).
- **ElaadNL/4TU Utrecht** (a.s.r. office parking lot, SmoothEMS met GridShield consortium output published via 4TU.ResearchData DOI 80ef3824, CC BY-NC-SA 4.0; substituted in for the deprecated ElaadNL Open Charging Transactions endpoint): 55,379 sessions / 3,409 pseudonymized EV identifiers / 4-year window (Aug 2020 – Oct 2024) / ~300 charging points.
- **EV WATTS**: fixture only (80 sessions / 6 ports). Real bulk corpus sits behind an account-required SPA at `livewire.energy.gov/ds/evwatts/evwatts.public`; the `EVWATTS_BULK_URL` env-var hook is documented in `docs/CALIBRATION_NOTES.md` for users with portal access.
- **INL EV Project Phase 1**: fixture only (78 sessions / 4 vehicles). Public outputs at `avt.inl.gov` are predominantly aggregate technical reports; session-level CSV requires direct INL contact. `INL_BULK_URL` env-var hook documented.

No power analysis or stratified sampling is performed; per-region sample sizes are reported under `calibration_metadata.region_distributions.<region>.n_samples` in the populations.yaml block (and propagate to the manifest of any generated scenario whose population is calibrated).

For the generator's per-realization sampling: forward simulation of the Bayes net with a single seed. Per-car independent streams ensure changing one car's parameters doesn't shift another's RNG path (`docs/DESIGN_NOTES.md` item 7).

### Who was involved in the data collection process?

The four calibration sources were collected by their respective originating institutions (Caltech / Adaptive Charging Network team; DOE/EPRI for EV WATTS; Idaho National Lab for the EV Project Phase 1; ElaadNL for the Open Charging Transactions release). `v2b_syndata`'s authors only re-fetched the published releases via their public APIs and ran the calibration pipeline. No human subjects were recruited or surveyed for this work — the **only** exception is the **CONSENT survey** (n=28) whose k-means cluster means/standard deviations parameterize the four negotiation-type clusters and the per-cluster bivariate weights `(w1, w2)` over (ΔSoC, Δdeparture). That survey was conducted under the authors' institutional approvals (`[TODO at submission time]` for IRB / consent acknowledgements). The survey's small-n means the cluster centers are credible as means but the within-cluster variances should be treated cautiously at scale; the generator exposes a `w_multiplier` knob `[0.1, 5.0]²` to let users explicitly stress-test sensitivity to the CONSENT calibration.

The four calibration-source institutions had no involvement in the design or implementation of `v2b_syndata`; this work uses their published data products as parametric anchors and does not represent an endorsement, partnership, or joint product with those institutions.

### Over what timeframe was the data collected?

Per calibration source:

- **ACN-Data**: sessions from 2019-01-01 through 2021-12-31 (calendar years; 3-year window). Selected because 2018 had 0% userID coverage at the Caltech site.
- **EV WATTS**: DOE/EPRI multi-year aggregate release (per-release version pinned via `SCHEMA_VERSION` in `src/v2b_syndata/calibration/sources/evwatts.py`).
- **INL EV Project Phase 1**: 2011–2013, ChargePoint + Blink stations, ~24 kWh Leaf and Volt vehicles. Marked as a **legacy fleet** caveat (`docs/CALIBRATION_NOTES.md` item 11) — battery-capacity assumptions diverge from modern EVs.
- **ElaadNL/4TU Utrecht**: Aug 2020 – Oct 2024 NL/EU office workplace cohort (a.s.r. office parking lot, 4TU.ResearchData DOI 80ef3824, CC BY-NC-SA 4.0). Substituted into the ElaadNL slot after the original Open Charging Transactions endpoint was retired in favor of dashboard-only access.
- **CONSENT survey**: small-n (28) survey by the authors. Date `[TODO at submission time]`.

Calibration runs are timestamped in the provenance string: e.g. `acn_data_2019_2021_20260506` records that the v1 fit ran on 2026-05-06.

### Were any ethical review processes conducted?

The generator's synthetic outputs do not involve human subjects, so no IRB review is required for the artifact itself. The CONSENT survey (n=28) was conducted under institutional approval `[TODO at submission time]`. The four calibration sources were collected and released by their originating institutions under their respective ethical and data-sharing terms (see Composition §"Distribution" below for IP terms). `v2b_syndata` does not re-publish raw per-session data from those sources — only fitted distribution parameters propagate into the artifact.

---

## 4. Preprocessing / cleaning / labeling

### Was any preprocessing/cleaning/labeling of the data done?

Yes, at calibration time. The filter chain is documented in `docs/CALIBRATION_NOTES.md` §1:

| Stage | Filter | Reason |
|---|---|---|
| Source filter | sites = {caltech, jpl, office001} for ACN | Per design decision D40 |
| Year window | 2019–2021 inclusive | 2018 has 0% userID coverage |
| Session validity | `userID != null` | drop unidentified sessions |
| Per-user filter | `n_sessions >= 5` AND `>= 5 weekdays in active window` | drop statistically noisy users |
| Battery inference | per-session via `WhPerMile × kWhRequested`; fallback to 60 kWh default | ACN has no explicit capacity column |
| Region assignment | deterministic first-match by `axes_distribution[*]` order | overlapping (φ, κ) boxes |
| Distribution fit guard | drop fits whose MLE estimate falls outside `DIST_PARAM_RANGES` | "B4 guard" prevents pathological tails |

For each source, the analogous filter chain is implemented in `src/v2b_syndata/calibration/sources/<source>.py`. Where a source lacks per-driver identity (EV WATTS, ElaadNL when card_id is missing), a port-proxy ID is synthesized and the `user_id_strategy` field in `calibration_metadata` is flipped to `port_proxy`. **Caveat**: this means EV WATTS-derived (φ, κ) should be read as per-port shift-consistency, not individual-driver consistency (`docs/CALIBRATION_NOTES.md` item 11).

Generation-time post-render noise (when `noise.profile != clean`) applies bounded multiplicative jitter on `power_kw`, occupancy baseline, arrival timestamps, arrival SoC, and prices; bounds are described in `docs/CALIBRATION_NOTES.md` items 13, 15, 18.

### Was the "raw" data saved in addition to the preprocessed/cleaned/labeled data?

No raw real-world data is bundled with `v2b_syndata`. The calibration sources are re-fetched from their original public APIs as needed. Fitted distribution parameters and per-region summary statistics are persisted to `configs/populations.yaml` along with the calibration provenance string. Intermediate calibration tables (`data/calibration/acn_per_user.csv` and analogues) are produced locally during a calibration run; they are gitignored and not distributed.

### Is the software used to preprocess/clean/label the instances available?

Yes. The calibration pipeline lives in `src/v2b_syndata/calibration/` and is invoked via `v2b-syndata calibrate --population <name>`. Per-source fetchers/parsers are in `src/v2b_syndata/calibration/sources/`. The fit pipeline (feature extraction → region assignment → distribution fitting → writeback) is in `src/v2b_syndata/calibration/{feature_extractor,region_assignment,distribution_fitter,writer}.py`. End-to-end tests live under `tests/test_calibration/`.

---

## 5. Uses

### Has the dataset been used for any tasks already?

Yes. The companion paper uses `v2b_syndata` to drive a `paper_bench` evaluation harness comparing open baseline V2B schedulers (greedy + CVXPY-based MPC) on a peak-shaving task across the scenario atlas. The 41+ committed scenarios were curated to support experiments E1–E8 specified in `handoff/spec/PLAN.md`: toggle-ablations of a FSL/CONSENT/Persistence stack, climate × season sweeps (Atlanta, Miami, Minneapolis, San Francisco, San Jose), DR-program comparisons (none / CBP / BIP / ELRP), ψ-spanning sweeps (0.10 → 0.90), fleet-scale studies (20 → 500 EVs), and population-anchor comparisons (consent_default vs ACN vs EV WATTS vs INL vs ElaadNL).

Internal usage is also tracked via:

- the test suite (422 tests including 48 edge-case boundary tests in `docs/EDGE_CASE_REPORT.md` and 50 pairwise-interaction audits in `docs/PAIRWISE_AUDIT.md`; line coverage at 91%, see `docs/COVERAGE_REPORT.md`),
- the knob-audit pipeline (Stage 1 + Stage 2 in `docs/KNOB_AUDIT_S1.md` / `docs/KNOB_AUDIT_S2.md` characterizes monotonicity of every registry knob against every output CSV column),
- the showcase figures (`showcase/build_figures.py` renders 19 figures exercising the generator end-to-end on representative scenarios), and
- the interactive walkthrough (`showcase/short_overview/walkthrough.html`) which lets users see the `users.csv → cars.csv → sessions.csv` pipeline respond to behavioral-axis slider drags in real time.

### Is there a repository that links to any or all papers or systems that use the dataset?

`[TODO at submission time]` — at deanonymization the README will link to the companion paper and any third-party usage we are aware of. The repo will accept user-contributed citation entries via PR.

### What (other) tasks could the dataset be used for?

The generator targets V2B research broadly. Reasonable use cases include:

- **V2B / V2G scheduling research** — using `sessions.csv`, `cars.csv`, `chargers.csv`, `building_load.csv`, `grid_prices.csv` as inputs to model-predictive control, mixed-integer programming, or reinforcement learning policies.
- **Demand-response participation research** — pairing `dr_events.csv` (CBP/BIP/ELRP) with the building+EV co-load.
- **Robustness and stress testing** — exercising algorithms against ψ-spanning scenarios or noise profiles (`adversarial`, `tmyx_stochastic`).
- **Sample-complexity / generalization studies** — generating many seeds per scenario to characterize variance.
- **Pretraining data for RL** — large fleets (`S_scale_500.yaml`) and Dirichlet-perturbed populations supply diverse training distributions.
- **Methodological work on synthetic-data benchmarks** — `v2b_syndata` is itself a case study in audited synthetic dataset construction (knob provenance, S1/S2 audits, edge-case coverage).

### Is there anything about the composition of the dataset or the way it was collected and preprocessed/cleaned/labeled that might impact future uses?

Yes — a non-exhaustive list of *limitations* that should be foregrounded in any downstream paper:

- **Calibration sources skew workplace-charging and US-centric.** ACN, EV WATTS, and INL are all US deployments; ElaadNL is the only EU source. None cover the developing world or pure-residential apartment-complex charging. Latin-American, African, and South / Southeast Asian charging patterns are not represented.
- **Legacy-fleet caveat (INL).** The INL EV Project Phase 1 covers 2011–2013 Leaf/Volt vehicles on ~24 kWh batteries. Do not mix this calibration with modern-battery scenarios without re-fitting `f_soc` against modern capacity assumptions (`docs/CALIBRATION_NOTES.md` item 11).
- **CONSENT survey is small-n.** Four negotiation clusters are derived from n=28 — the cluster centers are credible as means, but the within-cluster (w1, w2) variances should not be treated as population variances at scale. The `F_SHARE_TOL = 0.20` validator tolerance reflects this (`docs/DESIGN_NOTES.md` item 11).
- **δ (commute distance) is hand-specified per region.** The ACN-Data `milesRequested` proxy is too noisy to write back (`docs/CALIBRATION_NOTES.md` item 3). NHTS-anchored δ calibration is deferred.
- **Required-SoC distribution is hand-specified.** Step 5 calibrates arrival-SoC only; `required_soc_at_depart ~ TruncNorm(85, 5)` is hardcoded (`docs/DESIGN_NOTES.md` item 22).
- **Capacity inference fallback rate is ~33%.** When `WhPerMile` is missing, capacity defaults to 60 kWh, biasing arrival-SoC distributions toward the fleet-median assumption (`docs/CALIBRATION_NOTES.md` item 2).
- **`ks_fit_quality` is in-sample only.** It is the KS statistic of the fit against the data it was fitted to — a goodness-of-fit measure, not a generalization measure. Held-out validation is deferred to Step 5.5 (`docs/CALIBRATION_NOTES.md` item 6).
- **EnergyPlus / ASHRAE 90.1 prototype artifacts.** Day-of-week is shifted by one day in the bundled MediumOffice IDF (`docs/DESIGN_NOTES.md` item 16); ExteriorLights causes seasonal inflex variation even with constant occupancy (`docs/CALIBRATION_NOTES.md` "Inflex … seasonally variable"). Two (climate × archetype) combinations crash EnergyPlus (Houston / Atlanta + mixed_use_v1, `docs/AUDIT_REPORT.md` A1).
- **E5 (concurrent-active ≤ chargers) is post-render, not enforced at sample time.** Under-sized scenarios silently produce E5-infeasible CSVs; the runner warns and surfaces this in `manifest['e5']`, but a sloppy user could ignore the warning (`docs/DESIGN_NOTES.md` item 30).
- **Default noise off.** The single-shot CLI default is `noise.profile=clean`; batch mode opts into `tmyx_stochastic` to support Monte Carlo (`docs/CALIBRATION_NOTES.md` item 18). Realism studies should explicitly select a non-clean profile.
- **ACN regions under-cover the empirical (φ, κ) joint.** Even after the per-user active-window fix (`docs/CALIBRATION_NOTES.md` item 10), 95% of ACN users fall outside `consent_default`'s region grid because most have high-κ-but-low-φ behavior that no region in the default grid pairs together. The `acn_workplace_baseline` population re-anchors regions on the ACN empirical joint (98.1% → 1.9% unassigned) and is the recommended population for ACN-style workplace charging studies.
- **Pairwise interactions are mostly linear, with documented exceptions.** A 50-pair audit (`docs/PAIRWISE_AUDIT.md`) found 44/50 LINEAR, 1 mildly nonlinear, 2 moderately nonlinear, and 3 uninformative. The moderately-nonlinear pairs are `(building_load.peak_kw × noise.building_load_jitter_pct)` on `building_load.csv` flex variance, and `(utility_rate.dr_program × noise.dr_notification_dropout_prob)` on `dr_events.csv` notification lead — both expected by construction.

### Are there tasks for which the dataset should not be used?

Yes:

- **Forecasting individual real driver behavior.** Synthetic users are *parametric draws*, not impersonations. Do not use a synthetic `users.csv` row as a stand-in for a specific real person.
- **Equity / fairness audits over protected demographic attributes.** The generator does not model race, gender, age, income, language, geography below climate-zone granularity, or any other demographic axis. Statistical claims about disparate impact across protected groups are **not supported** by this artifact and would be unfounded.
- **Compliance-grade billing or settlement studies.** Prices, tariffs, and DR program rules are realistic-but-stylized; they reflect public utility filings and CAISO aggregate stats, not any specific real customer's contract or any utility's current rate schedule. Settlement calculations against real tariffs require pulling the actual tariff sheets, not the generator's defaults.
- **Generalization to non-US (and non-NL) deployments without recalibration.** See "Limitations" above.
- **Battery-degradation or thermal-stress modeling.** The generator emits arrival/departure SoC and a battery class label only; no temperature, no per-cell state, no aging signal.

---

## 6. Distribution

### Will the dataset be distributed to third parties outside of the entity?

Yes. Open-source release planned at submission of the companion paper. Distribution is of the **generator** (code + scenario YAMLs + bundled calibration parameters in `configs/populations.yaml`), not of a pre-rendered corpus — users generate locally per (scenario, seed). Pre-rendered fixtures may be uploaded to a sample archive `[TODO at submission time]` for users who do not want to install EnergyPlus.

### How will the dataset be distributed?

- **Generator repo**: GitHub at `[TODO at submission time]` (anonymized for double-blind review; deanonymized at acceptance). One-command setup via `tools/setup.sh` installs `uv`, syncs Python dependencies, downloads EnergyPlus 23.2.x to `~/opt/`, and runs a smoke generation. A web frontend (`tools/web/app.py`, Flask, local-only by default) lets first-time users drive the generator through dropdowns and sliders without learning the CLI flags.
- **Scenario YAMLs**: shipped in-repo under `configs/scenarios/` (41+ at v1 release).
- **Pre-built calibration parameters**: shipped in-repo under `configs/populations.yaml`. Provenance strings reference the source dataset + version + run date (e.g. `acn_data_2019_2021_20260506`).
- **Optional archived realizations**: `[TODO at submission time]` — likely a Zenodo deposit of a handful of (scenario, seed) realizations for the companion paper's experimental atlas, for users who cannot install EnergyPlus locally. The full reproducibility contract (seed → bitwise CSVs) holds whether the user generates locally or downloads from the archive.
- **Documentation**: `docs/` (10 markdown files: DESIGN_NOTES, CALIBRATION_NOTES, AUDIT_REPORT, COVERAGE_REPORT, EDGE_CASE_REPORT, KNOB_REFERENCE, KNOB_AUDIT_S1, KNOB_AUDIT_S2, PAIRWISE_AUDIT) and `handoff/spec/` (PLAN, BAYES_NET, validate_spec, knobs.yaml, ACN_DATA_CALIBRATION, DATASET_AUDIT) shipped in-repo; an auto-generated `KNOB_REFERENCE.md` is produced by `v2b-syndata docs-gen`.

### When will the dataset be distributed?

Public release is targeted to coincide with KDD 2027 D&B Track submission (~July 2026 deadline for July 2026 cycle). Internal milestones tracked in the project memory file at `kdd-paper-positioning.md`. `[TODO at submission time]` for exact public-release date.

### Will the dataset be distributed under a copyright or other intellectual property (IP) license?

The generator code: `[TODO at submission time]` — an OSI-approved permissive license (MIT or Apache-2.0) is the working plan; no `LICENSE` file is committed yet. The four real-data calibration sources retain their own licenses (see next question); only **fitted parameters** flow into the generator, not raw data, so the calibration-source licenses do not propagate to derived `configs/populations.yaml` entries — but the source attributions are preserved in the manifest's `calibration_metadata.provenance` field, and citation guidance for downstream papers will be added to the README at release.

### Have any third parties imposed IP-based or other restrictions?

The four calibration sources are subject to their respective licenses:

- **ACN-Data** (Caltech) — released under Caltech's ACN-Data terms; per the [ACN Research Portal documentation](https://ev.caltech.edu/dataset), data is free for non-commercial research with citation requirements. `v2b_syndata` accesses ACN via the official `acnportal` Python package and requires the user to obtain their own `ACN_API_TOKEN`.
- **EV WATTS** (DOE / EPRI) — released by the U.S. Department of Energy. As a U.S. Government-funded work product, no copyright applies to the underlying data; the EPRI release page imposes its own attribution requirements which `v2b_syndata` carries forward via the `calibration:evwatts:*` provenance tag.
- **INL EV Project Phase 1** (Idaho National Lab / U.S. DOE) — U.S. Government work product. Public release at avt.inl.gov; no copyright on underlying data; attribution requested.
- **ElaadNL Open Charging Transactions** — released under **CC BY 4.0** by ElaadNL via open-data.elaad.io. Attribution required; `v2b_syndata` carries the attribution in the provenance string `calibration:elaadnl_open_2020_*`. Downstream users redistributing fitted parameters derived from ElaadNL data must preserve the CC BY 4.0 attribution.

Because only fitted distributional parameters (means, variances, correlations) propagate to the shipped generator — and not raw per-session records — the redistribution restrictions on the underlying sources are not triggered by users who simply install and run `v2b_syndata`. Users who re-run the calibration pipeline against the original sources must comply with the relevant source's terms directly.

### Do any export controls or other regulatory restrictions apply?

None known. The generator handles tabular charging-session and building-load data; no cryptography, no munitions data, no dual-use technology subject to EAR / ITAR / Wassenaar.

---

## 7. Maintenance

### Who is supporting/hosting/maintaining the dataset?

`[TODO at submission time]` — the authors at Vanderbilt (and Vanderbilt institutional affiliates) maintain the repo. Hosting at GitHub (anonymized URL at submission, deanonymized at acceptance). Issue tracker and PR review through GitHub.

### How can the owner/curator/manager of the dataset be contacted?

`[TODO at submission time]` — corresponding-author email and the GitHub issues URL will be listed in the README. Until deanonymization, contact via the venue's submission system.

### Is there an erratum?

An evolving change-log is maintained inline in `docs/DESIGN_NOTES.md` and `docs/CALIBRATION_NOTES.md` — each documents implementation choices, bugs found, and bugs fixed (31 and 19 items respectively at the time of writing). Hard bugs and resolution history are tracked in `docs/AUDIT_REPORT.md`. A separate `ERRATA.md` will be added at public release if material corrections are needed after the initial public version.

### Will the dataset be updated?

Yes, on at least three axes:

- **New scenarios** under `configs/scenarios/` as research uses surface (community PRs welcomed via the knob-registry contract).
- **New calibration sources** via the `CalibrationSource` protocol (`src/v2b_syndata/calibration/sources/`). NHTS for δ calibration is the next planned source per `docs/CALIBRATION_NOTES.md` item 11.
- **Bug fixes and tightened invariants** as the test suite grows. Reproducibility is preserved by re-running and re-stamping `csv_sha256` in the manifest; users pinning to a specific generator version should record the git SHA alongside the seed.

Version pinning: each released version of `v2b_syndata` will tag a git commit; `manifest.json` records the generator git SHA so any realization can be traced back to the precise generator code that produced it.

### If the dataset relates to people, are there applicable limits on the retention of the data?

The generated CSVs are synthetic — they do not relate to identifiable people, so no retention limits apply to realizations. The underlying calibration sources have their own retention policies set by their publishing institutions; `v2b_syndata` retains only fitted distribution parameters, which do not enable re-identification.

### Will older versions of the dataset continue to be supported/hosted/maintained?

Older generator versions remain available via git history. Older calibration runs (identified by provenance string, e.g. `acn_data_2019_2021_20260506`) are not re-distributed as separate artifacts — to reproduce an older run, check out the corresponding git SHA from `manifest.generator_git_sha` and re-run. The generator's bitwise-reproducibility contract guarantees this works as long as the EnergyPlus version pinned in `tools/setup.sh` (`23.2.x`) remains installable.

### If others want to extend/augment/build on/contribute to the dataset, is there a mechanism for them to do so?

Yes, multiple:

- **New knobs**: add to `configs/knobs.yaml` with `type`, `default`, `range`, `affects_csv`; the registry plumbing is automatic. See `docs/KNOB_REFERENCE.md` and `handoff/spec/knobs.yaml`.
- **New scenarios**: drop a YAML under `configs/scenarios/`. The four descriptor fields + optional overrides are the entire schema.
- **New calibration sources**: implement the `CalibrationSource` protocol in `src/v2b_syndata/calibration/sources/`; declare a new `calibration_policy` value in `configs/populations.yaml`. Existing examples: `acn_fetcher.py`, `evwatts.py`, `inl.py`, `elaadnl.py`.
- **New descriptors / library entries**: add to `configs/locations.yaml`, `configs/buildings.yaml`, `configs/populations.yaml`, `configs/equipment.yaml` — each library file has a documented schema.
- **Tests**: the test suite at `tests/` is the contract; new contributions are expected to add or extend tests. The 422-test suite covers all hard invariants and most edge cases (`docs/EDGE_CASE_REPORT.md`, `docs/COVERAGE_REPORT.md`).

External contributions are accepted via GitHub PR after public release. Until then, contributions can be coordinated via the corresponding author `[TODO at submission time]`.

---

*End of datasheet. For implementation details, see `handoff/spec/BAYES_NET.md`, `handoff/spec/PLAN.md`, and `handoff/spec/validate_spec.md`. For calibration details, see `docs/CALIBRATION_NOTES.md` and `handoff/spec/ACN_DATA_CALIBRATION.md`. For audit history, see `docs/AUDIT_REPORT.md`, `docs/PAIRWISE_AUDIT.md`, and `docs/EDGE_CASE_REPORT.md`.*
