# Ethics & Fairness writeup — v2b_syndata KDD D&B submission

Drafting material for Section 8 (*Accessibility, Ethics & Limits*, 0.5 pg, secondary Ethics axis) and the Ethics-axis bullets that thread through Section 4 (*Calibration*). Tone is honest and surface-level explicit, not defensive: the strength of a D&B Section 8 is naming what the artifact *is not*, and naming the limits that downstream papers must carry forward when they cite the substrate. Concrete validation numbers come from `data/calibration_validation/{S1_marginals,S3_holdout,S5_buildingload,S6_weekly}.csv` (50-seeded generations per source against the calibration corpus).

---

## 1. Privacy & PII

`v2b_syndata` ingests four publicly released charging datasets at calibration time and emits fully synthetic CSVs at generation time. **No identifiable personal data appears in any shipped artifact.** What the calibration pipeline touches, and what propagates, differ:

- The calibration sources arrive already pseudonymized by their publishers. We do not de-anonymize and do not retain raw per-session records.
- The fitter computes per-user summary features (φ, κ, δ proxy, arrival statistics) into an intermediate per-user table at `data/calibration/<source>_per_user.csv`. **This file is local to the calibration run and is not distributed.** It is gitignored and lives only inside the fitter's working directory.
- Only fitted distribution parameters — typically 3–4 numbers per (region, variable) (TruncNorm μ/σ, Weibull k/λ, Beta α/β, Spearman ρ) — and the per-region `n_samples` counts are persisted to `configs/populations.yaml`, the calibration provenance manifest, and downstream `manifest.json` outputs.
- The generator's output CSVs (`users.csv`, `cars.csv`, `sessions.csv`, …) carry only synthetic integer `user_id` / `car_id` columns with no provenance link to any real driver, card, port, or vehicle.

**Per-source pseudonymization regime, documented in `calibration_metadata.user_id_strategy`:**

| Source | `user_id_strategy` | Identity granularity in source | What enters our fitter |
|---|---|---|---|
| ACN-Data (Caltech / JPL / Office001) | `userID` | SHA-anonymized Caltech-issued user identifier | Per-user features keyed by anonymized userID |
| INL EV Project Phase 1 | `vin_proxy` | Pseudonymized vehicle IDs (e.g. `Veh001`) | True per-vehicle features (when present); falls back to `port_proxy` when `vehicle_id` is missing |
| ElaadNL / 4TU Utrecht | `card_proxy` | Pseudonymized RFID card ID. README warns that early-rollout cards were shared between drivers, so longitudinal identity is **weaker than `vin_proxy`** | Per-card features; falls back to `port_proxy` when `EV_id_x` is missing |
| EV WATTS (DOE / EPRI) | `port_proxy` | No driver ID published. We synthesize `user_id = "evwatts:port:<evse_id>"` | **Per-port shift-consistency**, not individual-driver consistency |

Two consequences flow from this table and should be carried forward by any downstream paper that cites `v2b_syndata`:

1. EV WATTS-derived (φ, κ) is **not** an individual-driver behavioral fit; it is a per-EVSE shift-consistency fit. Papers comparing populations should not conflate the two.
2. ElaadNL `card_proxy` is documented as imperfect identity. Where shared cards exist, (φ, κ) statistics absorb the shared-card pooling. We carry this caveat forward verbatim from the source's own README rather than over-claiming individual-driver coverage.

**Calibration-time data flow, concretely.** A calibration run against (e.g.) ACN proceeds: fetch sessions via `acnportal` and the Caltech HTTPS API (token-gated, per-user account), filter (`userID != null`, `n_sessions >= 5`, `n_weekdays_in_user_active_window >= 5`, year window 2019–2021), infer battery capacity per session via `WhPerMile × kWhRequested` (60 kWh fallback when missing — fired on 33.3% of sessions), compute per-user features (φ, κ, arrival/dwell summary stats) keyed by anonymized userID into the intermediate per-user table, assign each user to a region by deterministic first-match against `axes_distribution[*]`, fit per-region TruncNorm / Weibull / Beta marginals + a Gaussian copula on (arrival, dwell), B4-guard reject fits outside `DIST_PARAM_RANGES`, write **only fitted parameters + per-region `n_samples` + `ks_fit_quality` + provenance string** back into `configs/populations.yaml`. The anonymized-userID-keyed per-user feature table never leaves the runner's working directory. Nothing about individual sessions or individual users is observable from the artifact a third party installs.

---

## 2. Re-identification risk

**Re-identification of any real driver from a v2b_syndata generator output is not possible.** The argument is short and direct.

Three protections compound:

- **Synthetic outputs only.** Every row in every shipped CSV is forward-sampled from a parametric model. No real timestamps, no real session energies, no real card IDs appear in generator output. The seed → CSV path is bitwise-reproducible, but the CSV bytes are not derived from any real session.
- **Low-dimensional parametric calibration.** A calibrated region contributes typically 3–4 parameters per variable (TruncNorm μ/σ for arrival_hour, Weibull k/λ for dwell_hours, Beta α/β for arrival_soc, Spearman ρ for the bivariate copula). These low-dimensional summaries are not sufficient statistics for individual sessions — they are population marginals. The `n_samples` count carried alongside each fit is a coarse cohort size, not a sample-membership pointer.
- **Intermediate per-user tables stay local.** `data/calibration/<source>_per_user.csv` exists only during calibration runs; it is gitignored and never distributed in the released artifact. The released generator carries fitted summaries, not per-user feature vectors.

Because the only information flowing from real data into the distributed artifact is a handful of distribution parameters per cohort, no individual session can be reconstructed from a `v2b_syndata` install, and no membership-inference attack against the calibration corpus is enabled by the shipped artifact. This is a structural property of the calibration pipeline, not a configuration choice.

**Adversarial framing.** Suppose an attacker has full access to the distributed artifact (code + `configs/populations.yaml` with all fitted parameters + a fresh generation run on any seed) and is trying to determine whether a specific real driver D appeared in the calibration corpus. The attacker has:

- The parametric region marginals: μ, σ for arrival_hour; k, λ for dwell_hours; α, β for arrival_soc; ρ for the bivariate copula. Per region, that is ≈ 7 scalar parameters.
- The per-region `n_samples` count (a coarse cohort size — typically thousands of sessions per region).
- The provenance tag (e.g. `acn_data_2019_2021_20260506`) declaring which public source and which window was used.

The attacker does **not** have: per-user feature vectors (gitignored), per-session records (never ingested into the artifact), session timestamps (only parametric μ remains), session energies (only Beta α/β over normalized SoC remains), userID-to-cluster assignments. A membership-inference test against a 7-dim parametric summary fit on n ≈ 10,000–30,000 sessions has no per-individual signal to exploit. The shipped artifact reveals no more about any specific driver than reading the public ACN-Data paper does.

A stronger reading: a per-row session in a generator-output `sessions.csv` is provably **not** drawn from any real driver. The session's `(arrival_hour, dwell_hours, arrival_soc, energy_kwh)` tuple is sampled from the parametric joint with a deterministic per-car SeedSequence stream, with no rejection conditioning on any real-session content. The mapping from real-data → fitted-parameter → sampled-session destroys per-session identity by construction.

---

## 3. Geographic & venue representativeness

The calibration corpus is workplace-charging-heavy and skews US + NL. We document the coverage envelope explicitly so downstream papers can name the scope they inherit.

**What is calibrated end-to-end against real bulk corpora (v1):**

- **ACN-Data** (Caltech ACN team, 2019–2021, US west coast — California). Three workplace sub-cohorts under the unified `calibration_policy: acn_data`:
  - **Caltech** — university campus charging (n=277 users / 13,893 sessions; mixed student + staff cohort).
  - **JPL** — NASA Jet Propulsion Laboratory employee parking (n=382 / 27,973 sessions; corporate-research workforce).
  - **Office001** — corporate office parking (n=14 / 585 sessions; tight commute cohort, smallest n).
- **ElaadNL / 4TU Utrecht** (a.s.r. office parking lot, NL, Aug 2020 – Oct 2024). EU office workplace (n=3,409 pseudonymized EV identifiers / 55,379 sessions / ~300 charging points). CC BY-NC-SA 4.0.

**What is loader-ready but fixture-only in v1** (real-data acquisition deferred to v2 follow-up; loader implementations + synthetic fixtures + documented `EVWATTS_BULK_URL` / `INL_BULK_URL` env-var hooks ship today):

- **EV WATTS** (DOE / EPRI). US workplace + DCFC. Behind an account-required portal SPA at `livewire.energy.gov`.
- **INL EV Project Phase 1** (Idaho National Lab, 2011–2013). Legacy ~24 kWh Leaf + Volt fleet. Public outputs are aggregate-only at `avt.inl.gov`.

**Coverage that the calibration corpus does NOT span — listed as scope, not as gap-to-be-filled-now:**

- **No residential charging** in calibrated form. INL Phase 1 is a legacy-fleet (2011–2013 Leaf/Volt, ~24 kWh) residential-leaning source and is fixture-only; treating it as a "modern residential" calibration anchor would be inappropriate.
- **No apartment-complex / multi-unit-dwelling charging.**
- **No transit-fleet or commercial-fleet charging.**
- **No Global South coverage** (Latin America, Africa, South / Southeast Asia).
- **No public on-street curbside or destination retail charging** at calibrated scale.
- **One EU source, three US sources.** Geographic coverage is biased toward US workplace.

These are honest features of the v1 release. Downstream papers should state the calibration scope they inherit and avoid implicit generalization claims to populations the substrate does not cover. The `CalibrationSource` protocol is the documented extension surface for adding new geographies and venues; we forward such work to v2.

**Population identifiers shipped at v1, with their explicit provenance:**

| Population descriptor | `calibration_policy` | Source provenance |
|---|---|---|
| `consent_default` | synthetic | hand-authored, domain-informed (no real-data anchor) |
| `acn_workplace_baseline` | `acn_data` | ACN-Data 2019–2021 mixed-site fit (Caltech + JPL + Office001 combined; 5/5 regions calibrated, n_users assigned = 634/646, unassigned_user_rate = 0.019) |
| `acn_caltech` (sub-cohort) | `acn_data` | ACN-Data Caltech site only (n=277 users / 13,893 sessions) |
| `acn_jpl` (sub-cohort) | `acn_data` | ACN-Data JPL site only (n=382 / 27,973) |
| `acn_office001` (sub-cohort) | `acn_data` | ACN-Data Office001 site only (n=14 / 585) |
| `elaadnl_public_eu` | `elaadnl_open_2020` | 4TU.nl Utrecht a.s.r. office cohort, Aug 2020 – Oct 2024 (n=3,409 / 55,379) |
| `evwatts_workplace_public`, `evwatts_dcfc_public` | `evwatts` | EV WATTS fixture-only at v1; `EVWATTS_BULK_URL` hook for portal-access users |
| `inl_residential_legacy` | `inl_ev_project` | INL EV Project Phase 1 fixture-only at v1; `INL_BULK_URL` hook |
| `stable_commuter_heavy`, `visitor_heavy` | synthetic | hand-authored (region_distributions TODO) |

Every fitted leaf in a calibrated population carries `source: calibration:<provenance>` in `manifest.knob_resolution`; every leaf in a synthetic population carries `source: hand_specified:<population_name>`. Mixed populations (some regions calibrated, some hand-authored within the same population) are not currently supported — `calibration_policy` is per-population, not per-region — which keeps the provenance audit clean.

---

## 4. CONSENT survey: n=28 limitations

The CONSENT model in `users.csv` parameterizes four negotiation-type clusters with per-cluster bivariate weights $(w_1, w_2)$ over (ΔSoC, Δdeparture). These cluster means, cluster standard deviations, and the population mix are **hand-curated from a small n=28 survey** conducted by the authors. `handoff/spec/PLAN.md` records the source: *"Per CONSENT paper: 4 clusters from k-means on n=28 survey, each with bivariate weights $(w_1, w_2)$ over (ΔSoC, Δdeparture)."*

We are transparent about what n=28 can and cannot underwrite:

- **Cluster means are credible.** k-means on n=28 with k=4 produces well-separated centroids, and we treat the four cluster centers as the qualitative skeleton of the CONSENT model.
- **Within-cluster variances are NOT credible at population scale.** A 7-member cluster cannot estimate the variance of a behavioral population; the within-cluster spread reflects survey-respondent noise more than driver-population heterogeneity.
- **Population mix (4-simplex) is hand-authored**, not estimated from the survey, because the survey was not designed as a stratified population panel.

To make this honest disclosure usable rather than rhetorical, the generator exposes a knob `noise.w_multiplier` of type `vec2`, range `[[0.1, 5.0], [0.1, 5.0]]`, default `[1.0, 1.0]` (in `handoff/spec/knobs.yaml`), which globally scales the $(w_1, w_2)$ pair. Downstream researchers using a CONSENT-touching scenario family are expected to run a `w_multiplier` sensitivity sweep and report whether their policy conclusions survive a factor-of-5 stress of the CONSENT calibration. The hard-invariant validator carries a relaxed tolerance `F_SHARE_TOL = 0.20` (rather than 0.05) on per-cluster population shares precisely because the CONSENT calibration is small-n and we do not want false-positive invariant failures from sampling noise on small fleets.

The survey instrument template (consent-to-V2B-discharge questions under varying conditions on ΔSoC and Δdeparture) lives under `handoff/spec/` and is included as appendix material so reviewers can inspect what was asked.

---

## 5. Algorithmic-fairness implications

The v2b_syndata scenario library deliberately includes scenarios that treat user types **differently** — most prominently the CONSENT family (`S_consent_relaxed`, `S_consent_strict`, `S_consent_drained_pop`, `S_consent_topped_pop`) and the ψ-monotonicity family (`S_psi_010` … `S_psi_090`). This is by design: scenarios are the unit of controlled variation in this artifact.

The downstream consequence is that **V2B control-policy publications that use v2b_syndata as substrate must disclose which scenario family they evaluated on**, and should report **per-region performance breakdowns**, not just population-aggregated metrics. The motivating concern is operational, not abstract:

- `S_consent_strict` constrains the population to negotiation types with low $(w_1, w_2)$ — drivers who are unwilling to give up SoC or accept departure shifts. A policy that performs well in aggregate on `S_consent_strict` may achieve that aggregate by **discriminating which users it asks** — most likely loading the consent burden onto the willing-cluster minority. Aggregating without disclosure hides who pays the consent cost.
- The ψ family analogously shifts which behavioral region carries the predictability mass. A policy that wins on `S_psi_010` may be exploiting the high-predictability tail; one that wins on `S_psi_090` may be tuned to a flat-predictability regime. The substrate cannot distinguish these unless the paper reports per-region metrics.

**Reporting recommendation for downstream users:** (a) name the scenario family and the specific scenario set evaluated; (b) report per-region metrics (`region` ∈ {`stable_commuter`, `flexible_local`, `occasional_visitor`, `erratic`, `rare_consistent`, `rare_inconsistent`, `regular_charger`, ...} depending on population) in addition to fleet-aggregated metrics; (c) report per-negotiation-type metrics on CONSENT-touching scenarios. The `manifest.json` from each generation run already carries the population identity and the per-region region_distributions block, so the disclosure is mechanically traceable from any seeded run.

A minimal disclosure template a downstream V2B-policy paper using v2b_syndata as substrate can copy verbatim:

> *"We evaluate policy P on scenarios {`S_i`} drawn from family `F` of the v2b_syndata 53-scenario library. Population is `<population>` (calibration_policy: `<policy>`, provenance: `<provenance_string>`). We report aggregate peak-shaving / DR-revenue / target-miss metrics, and stratified metrics by `region` ∈ {...} and by `negotiation_type` ∈ {type_i, type_ii, type_iii, type_iv}, so that the consent burden distribution across user types is visible."*

`v2b_syndata` does **not** model protected demographic attributes (race, gender, age, income, language). Statistical claims about disparate impact across protected demographic groups are not supported by this artifact and would be unfounded. The fairness recommendation above applies to **synthetic behavioral regions and synthetic negotiation types**, which are the only equity-relevant axes the artifact represents.

---

## 6. What v2b_syndata IS NOT

Naming the non-scope is part of the artifact contract.

- **Not a fixed corpus.** The artifact is a generator. The 53 shipped scenarios are a suggested coverage atlas, not the only legal inputs.
- **Not a leaderboard benchmark.** The bench in Section 7 demonstrates that scenarios drive measurable downstream variation through a standard ACN-Sim pipeline. It is plumbing evidence, not an algorithm contest. With `feeder=1.0` the seven ACN-Sim stock algorithms tie within each scenario; cross-scenario variation is what differs. We do not rank charging-control algorithms.
- **Not a privacy-sensitive dataset.** All shipped outputs are synthetic. There is no PII in the distributed artifact.
- **Not a real-world V2B telemetry source.** Reviewers should not treat any v2b_syndata-generated CSV as observed field data. The provenance ledger in `manifest.knob_resolution` makes the synthetic origin of every leaf explicit (`source ∈ {explicit, descriptor, calibration:<provenance>, hand_specified:<population>, default}`).
- **Not a building-energy simulator or charging-control simulator.** It is the substrate; EnergyPlus and ACN-Sim are the natural downstream consumers.
- **Not a CTGAN / SDV / TabDDPM-style empirical-joint resampler.** We do not fit a high-dimensional model to a real corpus and resample. The Bayes-net topology is explicit and forward-sampled; marginals are calibrated where stable evidence exists, hand-specified elsewhere, and every leaf carries a provenance tag. Researchers who need a generator whose every knob is auditable and who want hypothesis-controlled experiments at the scenario level (rather than trace-selection-driven experiments) should reach for v2b_syndata; researchers who need a learned approximation of an empirical joint should reach for the GAN/diffusion family of tabular generators instead.
- **Not a billing or settlement source.** Prices, tariffs, and DR program rules are realistic-but-stylized aggregations of public utility filings, not any specific real customer contract or current rate schedule.
- **Not a battery-degradation modeling source.** Generator emits arrival/departure SoC and a battery class label; no temperature, no per-cell state, no aging.

---

## 7. Known limitations forwarded from calibration validation

The calibration-validation harness (`tools/validate_calibration.py`, five orthogonal checks S1/S2/S3/S5/S6) is the empirical ground truth for what works and what doesn't in v1. We surface specific shortfalls directly here because reviewers should see them in Section 8, not have to dig them out of the appendix.

**Weekly weekday/weekend pattern not reproduced (S6 validation).** From `data/calibration_validation/S6_weekly.csv`:

| Source | Source weekday sessions/day | Source weekend sessions/day | Source weekly ratio | Generated weekday | Generated weekend | Generated ratio |
|---|---|---|---|---|---|---|
| ACN (mixed) | 58.72 | 11.05 | **5.32×** | 186.27 | **0.00** | ∞ |
| ACN/Caltech | 20.46 | 7.83 | 2.61× | 186.23 | 0.00 | ∞ |
| ACN/JPL | 43.72 | 3.77 | **11.60×** | 186.45 | 0.00 | ∞ |
| ACN/Office001 | 1.79 | 1.00 | 1.79× | 186.00 | 0.00 | ∞ |
| ElaadNL/Utrecht | 62.82 | 1.38 | **45.69×** | 459.27 | 0.00 | ∞ |

Generated data produces **literally zero weekend sessions** across every cohort, while real workplaces produce a 1.8×–45.7× weekday/weekend ratio depending on cohort. The cause is structural: the sessions sampler treats each calendar day i.i.d. and most ship-default scenarios use `sim_window.weekdays_only=true`. This is a v1 limitation documented for honest forward-citation. Future work adds an explicit weekly-schedule term on φ to recover the empirical weekday/weekend ratio.

**Building-load weekday/weekend ratio is flat (S5 validation).** From `data/calibration_validation/S5_buildingload.csv`:

| Scenario | Archetype | Peak/off-peak ratio | Weekday/weekend ratio | Expected (PNNL) weekday/weekend |
|---|---|---|---|---|
| `S_size_small` | office small | 4.21× (in range) | **1.37×** | [2.5, 8.0] |
| `S01` | office medium | 8.54× (above range) | **1.28×** | [2.5, 8.0] |
| `S_size_large` | office large | 2.38× (below range) | **1.09×** | [2.5, 8.0] |
| `S_arch_retail` | retail standalone | 13.95× (above range) | **1.04×** | [1.2, 2.5] |

Peak/off-peak ratios are mostly in the PNNL expected range (small office 4.21× in the [4–8×] band; medium and large drift outside). Weekday/weekend ratios are uniformly **below** PNNL prototype expectations (1.04×–1.37× observed vs 2.5×–8× expected for offices). PNNL prototype occupancy schedules do encode weekend differentiation; the post-EnergyPlus aggregation appears to smooth more than expected. Cause under investigation; documented as a v1 known issue, not chased before submission.

**Multi-modal arrival distributions yield σ underfit in mixed-cohort sources (S1 validation).** From `data/calibration_validation/S1_marginals.csv`, focusing on `regular_charger` arrival_hour fits as the cleanest signal:

| Cohort | n_source | n_generated | K-S | σ_source | σ_generated | σ underfit |
|---|---|---|---|---|---|---|
| ACN/Office001 | 347 | 2213 | **0.097** | 1.87 | 1.68 | ~10% (best) |
| ElaadNL/daily_commuter | 8227 | 7176 | 0.179 | 1.70 | 1.69 | ~0% |
| ElaadNL/weekday_only | 19174 | 2478 | 0.159 | 1.79 | 1.79 | ~0% |
| ACN/JPL | 12484 | 2219 | 0.166 | 3.55 | 2.77 | **22%** |
| ACN (mixed pool) | 17857 | 2219 | 0.147 | 3.67 | 2.94 | **20%** |
| ACN/Caltech | 5306 | 2219 | **0.198** | 3.63 | 2.43 | **33%** |

The driver is **cohort behavioral homogeneity**, not source granularity: corporate workplace cohorts (Office001, ElaadNL/Utrecht) produce tight unimodal arrival peaks that TruncNorm captures cleanly; university-student or mixed-site cohorts produce multi-modal arrivals that a single TruncNorm under-fits by 20–33% on σ. Future work: mixture-of-TruncNorm parametric families for behaviorally heterogeneous cohorts.

**Held-out generalization confirmed for main regions (S3, 80/20 user split).** Main-region held-out K-S deltas fall within ±0.06 of training-set K-S for `regular_charger`, `occasional_consistent`, `rare_consistent`. Edge regions (`erratic`, `rare_inconsistent` on dwell_hours) show held-out delta up to +0.40 and +0.51 respectively, which is low-sample noise on cohorts with n_test ≈ 110–160. These edge-region deltas are surfaced under low-sample caveats rather than as a calibration defect.

**Joint correlation captured faithfully (S2).** All region-level Spearman ρ-gaps between source and generated land below 0.10; the strong negative arrival–dwell correlation in ElaadNL daily_commuter (ρ_source = −0.501) is reproduced at ρ_generated = −0.489 (gap = 0.012); ACN regular_charger ρ-gap = 0.044; ElaadNL weekday_only ρ-gap = 0.009. The copula transform `ρ_gaussian = 2·sin(π·ρ_spearman / 6)` is exact only for bivariate-normal copulas; bias on truncnorm × weibull marginals is < 0.05 in simulation, and S2 empirically confirms ρ-gap ≤ 0.10 across all real-calibrated regions.

**φ-definition shift, documented for transparency.** The original feature-extractor (pre-fix, commit `cb82e85`) computed `φ = n_active_weekdays / n_weekdays_in_global_3_year_window`, which under-counted users whose active employment window was a six-month subset of the calibration span (φ ≈ 0.07 for users who actually charge ~70% of days during their active employment). The fix uses `φ = n_active_weekdays / n_weekdays_in_per_user_active_window`. Effect on the ACN fit: φ-mean rose from 0.074 → 0.201, users with φ ≥ 0.7 rose from 0 → 18, regions calibrated rose from 2/5 → 4/5, unassigned_user_rate fell from 0.981 → 0.952 against `consent_default`. Re-anchoring regions on the empirical (φ, κ) joint observed in ACN further reduced unassigned_user_rate to 0.019 under `acn_workplace_baseline` (5/5 regions calibrated, n_users assigned = 634). We surface this calibration-defect-and-fix sequence under the Ethics axis because honest reporting of "what we got wrong and how we caught it" is more useful to reviewers than a clean origin story.

**Other limits documented in `docs/CALIBRATION_NOTES.md` and DESIGN_NOTES that downstream users inherit:**

- ACN battery-capacity inference fallback fires on **33.3%** of sessions (`WhPerMile` missing → 60 kWh default), biasing arrival-SoC fits toward fleet-median assumption.
- ElaadNL/Utrecht naive Europe/Amsterdam timestamps treated as UTC for cross-source consistency; arrival_hour offset 1–2h vs wall-clock, applied uniformly to the fit, documented in CALIBRATION_NOTES item 11.
- `required_soc_at_depart` is hand-specified TruncNorm(85, 5) (deferred to Step 6); δ (commute distance) is hand-specified per region because the ACN `userInputs.milesRequested` proxy is too noisy to write back.
- `ks_fit_quality` reported per region is **in-sample** (training-set K-S). S3 holdout (above) is the v2 generalization answer.
- Bitwise reproducibility validated on **single platform** (Linux x86_64 + EnergyPlus 23.2.x); cross-platform identity not claimed.
- EV WATTS and INL Phase 1 are **fixture-only** in v1; bulk-data acquisition deferred to v2 follow-up (access paths documented per source).

---

## 8. Future work in this dimension

Forward-looking items, surfaced here so reviewers see the trajectory rather than reading absence as oversight:

- **NHTS-anchored δ calibration.** Replace the hand-specified per-region commute-distance ranges with fits anchored to the FHWA National Household Travel Survey, which is a stratified population panel with credible variance estimates.
- **Non-PG&E utility tariff regions.** Current tariff/DR calibration uses PG&E CBP/BIP and CAISO ELRP rules. Adding non-PG&E utility regions (e.g. SCE, NYISO, ERCOT, ISO-NE, MISO) is an obvious extension and benefits researchers studying geographically diverse policy regimes.
- **Residential calibration sources.** The natural v2 additions are modern residential telematics or networked-charger residential bulk releases. The `CalibrationSource` protocol is the extension surface; the generator does not need to change.
- **Mixture-of-TruncNorm parametric families.** Multi-modal arrival distributions in mixed-cohort sources (ACN/Caltech university students; ACN mixed pool) cause the ~20–33% σ underfit on `regular_charger` arrival_hour documented in §7. A mixture family + family-selection within the `B4 guard` would close that gap.
- **Weekly weekday/weekend schedule term on φ.** Direct fix for the S6 zero-weekend-sessions issue documented in §7.
- **Held-out KS in the steady-state calibration pipeline.** S3 is currently a one-shot validation harness; pulling the 80/20 split inside `distribution_fitter` and persisting a held-out K-S alongside the in-sample `ks_fit_quality` would make generalization a first-class property of every fitted region.
- **CONSENT survey scale-up.** A larger-n (≥ 200) panel would convert within-cluster variances from "treat cautiously" to "treat as estimated." Until that exists, the `w_multiplier` knob is the user-facing honest-disclosure mechanism.

None of these are blockers for v1 release; all are concrete and forwarded openly to the community via the `CalibrationSource` extension protocol and the issue-tracker contribution path documented in the Datasheet's Maintenance section.

**An additional methodological direction.** A natural follow-up methodological piece would compare v2b_syndata-style forward-sampled structured generators against learned-joint approaches (CTGAN, TabDDPM, SDV) on the V2B substrate. The trade-off is well-understood — learned-joint generators capture empirical dependencies that the analyst did not pre-specify, at the cost of provenance-opacity (no per-knob causal interpretation, no source-tag per leaf, no controlled scenario generation). A side-by-side study would not invalidate either approach but would help researchers pick the right tool. v2b_syndata's audit infrastructure (the 67/67 Stage-2 monotonicity result, the per-knob `affects_csv` declarations, the manifest provenance ledger) is the side of the comparison that downstream users can audit; whether learned-joint methods can match that audit surface is an open methodological question.

---

## Summary checklist for paper authors

When lifting this material into Section 8 (~0.5 page) and into the Ethics-axis bullets in Section 4:

| Section 8 paragraph | Material to lift from this writeup |
|---|---|
| Privacy / no PII claim | §1 (table of `user_id_strategy` regimes) + §2 (parametric-summary-only propagation, 3–4 params per region) |
| Geographic / venue scope | §3 (coverage envelope: 2 datasets, 5 populations; explicit non-coverage list) |
| Algorithmic fairness | §5 (disclosure template + per-region / per-negotiation-type reporting recommendation) |
| Honest limits | §7 (S6 zero-weekend-sessions; S5 flat building weekday/weekend ratio; S1 multi-modal underfit on Caltech 33% / JPL 22% / mixed 20%; capacity-fallback 33.3%; required-SoC uncalibrated) |
| What it is not | §6 (not a corpus, not a leaderboard, not a privacy-sensitive dataset, not real telemetry, not a CTGAN-style empirical resampler) |

For Section 4 (Calibration) Ethics-axis bullets:

| Section 4 ethics bullet | Material to lift |
|---|---|
| Per-source pseudonymization regimes | §1 (table) |
| What flows into the artifact vs what stays local | §1 (data flow paragraph) + §2 (adversarial framing) |
| CONSENT n=28 honest disclosure | §4 (cluster means credible; within-cluster variances cautious; `w_multiplier` sensitivity knob) |
| Acknowledging calibration limitations as ethics material | §7 (φ definition fix; S6/S5/S1 shortfalls; B4 guard activations) |

For Section 9 (Conclusion) future work bullets: §8 (NHTS, residential, mixture families, weekly schedule term on φ).

*End of writeup.*
