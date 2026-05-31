# OUTLINE.md — v2b_syndata KDD D&B Track Submission

**Target venue:** KDD 2027 Datasets & Benchmarks Track (July 2026 deadline; KDD 2026 D&B cycle has passed). Accepted contribution category: *Data Generators and Environments*.
**Format:** ACM `sigconf` template, 8 content pages + unlimited references and appendix, double-blind.
**Structure choice:** Traditional Intro → Related Work → Design → Calibration → Scenario Library → Verification & Reproducibility → Demonstration → Accessibility/Ethics/Limits → Conclusion. Each section header carries an `[Axis: X]` tag mapping it to one of the four D&B evaluation criteria (Accessibility, Quality & Docs, Impact, Ethics & Fairness). One-section-per-axis was rejected because calibration legitimately straddles Impact + Ethics and reproducibility straddles Quality + Accessibility; splitting them would fragment coherent topics.

**Page budget (sums to 8.0):**

| # | Section | Pages | Primary axis | Secondary axis |
|---|---|---|---|---|
| 1 | Introduction & contributions | 1.00 | Impact | — |
| 2 | Related work & positioning | 0.50 | Impact | — |
| 3 | Generator design & architecture | 1.50 | Quality & Docs | — |
| 4 | Calibration: unified 4-source protocol | 1.25 | Impact | Ethics |
| 5 | Scenario library | 0.75 | Impact | — |
| 6 | Reproducibility & verification | 1.00 | Quality & Docs | — |
| 7 | Demonstration: bench through standard pipeline | 1.00 | Impact | — |
| 8 | Accessibility, ethics, limits | 0.50 | Accessibility | Ethics |
| 9 | Conclusion & future work | 0.50 | — | — |

**Figure budget (load-bearing, ~6–7 in main text; rest go to appendix):**
- Fig 01 `01_position_diagram.png` — Intro
- Fig 07 `07_bayes_net_dag.png` — Design (preferred over Fig 06 because the DAG carries more information per cm²; Fig 06 may move to appendix)
- Fig 11 `11_acn_calibration.png` — Calibration
- Fig 12 `12_scenario_library.png` — Scenario Library
- Fig 15 `15_verification_matrix.png` — Verification (Fig 13 `13_psi_monotonicity.png` as inset or appendix)
- Fig 14 `14_climate_divergence.png` — Demonstration (Fig 16 `16_load_profiles_compared.png` to appendix)
- Fig 03 `03_manifest_excerpt.png` — small inset in Reproducibility
- Appendix references: Figs 02, 04, 05, 06, 08, 09, 10, 13, 16, 17, 18, 19.

**Double-blind & artifact TBDs (resolve before submission):**
- Anonymize repo URL; replace with anonymous-archive zip OR anonymous-Github mirror.
- Mint a Zenodo/Figshare archival DOI for the tagged release + a pre-generated reference dataset (S01 seed=42 and the 7-scenario bench output).
- Choose dataset license (CC BY 4.0 candidate) and code license (already in repo; verify).
- Datasheet for Datasets (Gebru et al. 2021) appendix and Reproducibility Checklist (Pineau et al. 2021) appendix are required artifacts, not optional.

---

## Section 1 — Introduction & Contributions  [Axis: Impact] (1.00 pg)

**Working title (placeholder):** *v2b_syndata: A Configurable, Calibrated, Bitwise-Reproducible Generator for Vehicle-to-Building Datasets.*

### Key points

- V2B research must co-vary six factor families (building physics, EV fleet, user behavior, charging infrastructure, tariff/DR, climate) but no public empirical trace spans all six. Existing public datasets cover slices: ACN-Data has workplace sessions but no building load; EV Project has residential sessions but only 2011–2013 legacy fleet; ElaadNL is EU-only; no public corpus pairs sessions with co-located 15-min building load and tariff metadata.
- Synthetic generation is the right substrate when the controlled variable is the scenario itself. **Hypothesis-controlled experiments require knob-level provenance, not trace selection.**
- We contribute (a) a forward-sampling 4-tier generative model with explicit Bayes-net topology over the joint, (b) a unified `CalibrationSource` protocol spanning four real-data sources (ACN-Data US workplace, EV WATTS US workplace/DCFC, INL EV Project US residential legacy, ElaadNL EU public), (c) 53 pre-built scenarios covering the V2B factor space, (d) bitwise-identical seed→CSV reproducibility validated end-to-end, (e) a 422-test verification harness with knob-level audit reports.
- Distinction from prior synthetic-data work (CTGAN, SDV): we are **not** trying to learn an empirical joint and resample it. We forward-sample a structured causal model whose parameters are knobs the researcher controls, with marginal fits drawn from real data only where stable evidence is available.
- Explicit non-goals: this is not a benchmark for V2B optimization algorithms; the included bench is plumbing evidence, not an algorithm contest.

### Figure / table

- Fig 01 (positioning diagram).
- Tab 1: one-row contribution summary keyed to the four D&B axes.

### Cites

- ACN-Data: Lee, Li, Low 2019 (ACM e-Energy).
- ACN-Sim: Lee, Sharma, Johansson, Chu, Low 2021 (ACM e-Energy).
- Kempton & Tomić 2005, *J. Power Sources* — V2G foundations.
- Lopes, Soares, Almeida 2011 — V2G/V2B integration framework.
- SDV / CTGAN: Patki, Wedge, Veeramachaneni 2016 IEEE DSAA; Xu et al. 2019 NeurIPS.

---

## Section 2 — Related Work & Positioning  [Axis: Impact] (0.50 pg)

### Key points

- **Three families to compare against:** (i) empirical V2B/EV traces (ACN-Data, EV Project, EV WATTS, ElaadNL, ACN-Sim's bundled traces); (ii) building-load datasets (EnergyPlus reference buildings, BDG2 benchmark); (iii) general-purpose synthetic tabular generators (CTGAN, SDV, TabDDPM).
- **Where v2b_syndata sits:** the only generator we know of that emits all seven coupled CSVs from one scenario, with documented dependencies between user behavior → sessions → building flexibility → tariff/DR response.
- **Honest comparison:** ACN-Sim *consumes* charging traces (real or recorded), it does not generate the cross-family joint. ACN-Sim and v2b_syndata are complementary — ACN-Sim is the natural downstream simulator for our `sessions.csv` + `chargers.csv`, which we demonstrate in Section 7.
- Position v2b_syndata as the **scenario substrate**, ACN-Sim as one downstream **algorithm runner**.

### Figure / table

- Tab 2: feature-matrix table (rows = related artifacts; cols = building load? sessions? users? chargers? prices? DR? real-data calibrated? scenario-knobs? reproducible? open?). v2b_syndata is the only row with checkmarks across the board.

### Cites

- ACN-Sim (Lee et al. 2021), EV Project (Smart & Schey 2012 SAE), EV WATTS (DOE/EPRI livewire.energy.gov), ElaadNL Open Charging Transactions (open-data.elaad.io, CC BY 4.0).
- BDG2: Miller et al. 2020 *Scientific Data* (building benchmark).
- TabDDPM: Kotelnikov et al. 2023 ICML.
- Datasheets for Datasets: Gebru et al. 2021 *CACM*.

---

## Section 3 — Generator Design & Architecture  [Axis: Quality & Docs] (1.50 pg)

### Key points

- **4-tier topology.** Tier 0 user-facing descriptors (Location, Building, Population, Equipment) → Tier 1 nine root nodes (C, W, A, S, O, T, U, F, X) → Tier 1.5 per-entity instantiation (`A_user` per car_id, `A_fleet` per car_id) → Tier 2 five latents (`L_flex`, `L_inflex`, `f_arr`, `f_dwell`, `f_soc`) → Tier 3 seven CSV renderers + manifest.
- **Resolution chain (mandatory invariant):** CLI override > scenario YAML overrides > descriptor expansion > `knobs.yaml` default. Every leaf in `manifest.knob_resolution` carries a `source` tag tracking which rung set the value.
- **Building load is real physics**, not a stub. EnergyPlus 23.2 + PNNL ASHRAE 90.1-2019 prototypes (Denver climate-zone 5B variant bundled) + TMYx weather files via climate.onebuilding.org. Occupancy injection rewrites `BLDG_OCC_SCH` plus its setback variants; annual RunPeriod stripped and replaced with one block with explicit Begin Year + Day-of-Week-for-Start-Day (see Design Note 16 in `docs/DESIGN_NOTES.md`).
- **Sessions sampler.** Per-user (φ, κ, δ) drawn from region-mix categorical; (arrival_hour, dwell_hours) joint draw via Gaussian copula with region-specific ρ; arrival_soc Beta-distributed and shifted by δ heuristic; required_soc TruncNorm(85, 5) gated by `min_depart_soc` floor; D5 reachability and D6 strict-inequality enforced by **rejection sampling, not clamping** (see Design Note 4; clamping was an early bug, fixed). Non-overlap rejection per car_id day-by-day.
- **DR events.** Inhomogeneous Poisson process via Lewis thinning; calibration constants for CBP/BIP/ELRP from PG&E + CAISO program docs hardcoded in `samplers/dr_sampler.py`; weather feeds `temp_factor(W.max_temp_today)` to modulate rate. Notification leads per program (CBP 24h, BIP 2h, ELRP 2h).
- **Noise layer is post-render and bound-checked.** Six per-jitter knobs (building load, occupancy, arrival time, arrival SoC, price, DR notification dropout). Arrival-time jitter is bounded both ways so C4 (`arrival < departure`) cannot fail; SoC jitter clamped against `min_allowed_soc` and `required_soc - 0.1` so D3 + D6 are preserved (see Design Notes 31 and #15 in `docs/CALIBRATION_NOTES.md`). Default profile is `clean` (all jitters = 0) so single-shot CLI runs remain bitwise reproducible.
- **Per-node RNG seeding.** `numpy.random.SeedSequence(entropy=seed, spawn_key=(stable_int(name), [car_id]))` with `stable_int(name) = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")`. SHA-256 (not Python `hash()`) chosen because Python 3 hash randomization defeats cross-process determinism. Adding a new node does not perturb existing nodes.

### Figures / tables

- Fig 07 (Bayes-net DAG) — main.
- Fig 06 (4-tier resolution) — appendix.
- Fig 08 (one-knob walkthrough) and Fig 09 (seed lineage) — appendix.
- Tab 3: per-CSV schema (cribbed from `showcase/OVERVIEW.md` Table 1).

### Cites

- EnergyPlus: Crawley et al. 2001 *Energy and Buildings*.
- PNNL prototypes: Goel et al. 2014, PNNL-23720; Goel & Wang 2014.
- TMYx: Wilcox & Marion 2008 NREL; climate.onebuilding.org dataset.
- ASHRAE 90.1-2019.
- Lewis & Shedler 1979, *Naval Research Logistics Quarterly* (thinning algorithm for non-stationary Poisson processes).
- Pineau et al. 2021, *JMLR* — reproducibility checklist.

---

## Section 4 — Calibration: Unified 4-Source Protocol  [Axis: Impact + Ethics] (1.25 pg)

### Key points

- **Unified `CalibrationSource` protocol.** One Python protocol in `src/v2b_syndata/calibration/sources/` with four concrete implementations: ACN-Data (ev.caltech.edu), EV WATTS (DOE/EPRI livewire.energy.gov), INL EV Project Phase 1 (avt.inl.gov), ElaadNL Open Charging Transactions (open-data.elaad.io). All four feed the same `feature_extractor.aggregate_user_features` and `distribution_fitter` pipelines; populations.yaml writeback is byte-equivalent across sources for unchanged blocks.
- **Geographic + venue + identity-strength coverage.** First synthetic V2B generator we know of to triangulate workplace (ACN, EV WATTS), residential legacy (INL), and EU public/semi-public/DCFC (ElaadNL). Identity strength is documented in manifest metadata: `vin_proxy` (INL, individual-driver) > `card_proxy` (ElaadNL, weak — RFID cards transfer between drivers) > `port_proxy` (EV WATTS, per-port shift-consistency, NOT individual driver).
- **What is calibrated, what is hand-specified.** Calibrated: arrival distribution, dwell distribution, arrival-SoC distribution, copula correlation per region; per-population. Hand-specified (synthetic policy): commute distance δ (no validated source — `userInputs.milesRequested` is a noisy proxy, not measurement); required-SoC at depart (uniform TruncNorm(85, 5), deferred to Step 6 in repo roadmap); CONSENT cluster means (n=28 survey, hand-curated). Per-population `calibration_policy` enum (`acn_data` | `synthetic`) gates which path fires; manifest tags leaves `calibration:<provenance>` or `hand_specified:<population>`.
- **Filter chain (transparent and reported).** ACN: 2019–2021 inclusive (2018 has 0% userID coverage); `n_sessions ≥ 5` per user; `n_weekdays_in_user_active_window ≥ 5`; per-session battery inference via `WhPerMile`+`kWhRequested` with default-60-kWh fallback. **Capacity-inference fallback rate is 33.3% on the ACN 2019-2021 run** — surfaced in `calibration_metadata`. Real ACN run: 42,451 sessions / 646 users post-filter on `acn_workplace_baseline` population, 634/646 (98.1%) region-assigned.
- **Real-data status (2026-05-30).** **Two real-data datasets** are calibrated end-to-end against real bulk corpora. ACN-Data (Lee et al. 2019; Caltech / JPL / Office001 sites, 2019–2021): 42,451 sessions, 646 users post-filter; we additionally fit **3 per-site sub-cohorts** under the same `calibration_policy: acn_data` (Caltech n=277 users / 13,893 sessions; JPL n=382 / 27,973; Office001 n=14 / 585) to surface within-source heterogeneity effects in S1 above. ElaadNL/4TU Utrecht: 55,379 sessions / 3,409 pseudonymized EV identifiers (Aug 2020 – Oct 2024, Utrecht NL office parking lot, via 4TU.ResearchData DOI 80ef3824, CC BY-NC-SA 4.0 — the SmoothEMS met GridShield consortium dataset of which ElaadNL is the data-API operator; substituted in for the original ElaadNL Open Charging Transactions endpoint, which was retired in favor of a dashboard-only interface; documented in `docs/CALIBRATION_NOTES.md`). EV WATTS and INL ship loader implementations + synthetic fixtures + documented `EVWATTS_BULK_URL` / `INL_BULK_URL` hooks; their bulk corpora sit behind an account-only SPA (livewire.energy.gov) and aggregate-only public releases (avt.inl.gov), respectively. Real-data acquisition for those two deferred to v2 follow-up. **Headline count: 2 real datasets (US + EU), with 4 calibration anchor points (ACN mixed + ACN/Caltech + ACN/JPL + ACN/Office001 + ElaadNL/Utrecht = 5 populations under 2 datasets), plus 2 protocol-extension loaders.** We do not claim 4+ distinct sources; the ACN sub-cohorts are within-dataset partitions, not separate publications.

- **Empirical generated-vs-real validation (NEW in v2).** `tools/validate_calibration.py` runs five orthogonal checks against the calibration corpus, with 50 seeded scenario generations per source. Within ACN we additionally split the dataset into 3 per-site cohorts (Caltech, JPL, Office001) under the same `calibration_policy: acn_data` — not 3 separate datasets, but 3 sub-cohorts demonstrating behavioral-homogeneity effects.
  - **S1 (marginal KS + Wasserstein-1).** Per-region per-variable (arrival_hour, dwell_hours). **Headline finding**: fit quality tracks *cohort behavioral homogeneity*, not source granularity:
    - ACN/Office001 regular_charger (corporate, n=347): **K-S 0.097, σ_src=1.87 ≈ σ_gen=1.68** — best fit across all 5 cohorts tested.
    - ElaadNL/Utrecht (corporate workplace, n=8.2k–19k): K-S 0.16–0.18; σ matched within 0.01.
    - ACN/JPL regular_charger (NASA, n=12.5k): K-S 0.166, σ underfit 22%.
    - ACN mixed pool regular_charger (3 sites combined, n=17.9k): K-S 0.147, σ underfit 20%.
    - ACN/Caltech regular_charger (university students, n=5.3k): **K-S 0.198, σ underfit 33%** — single-site doesn't guarantee unimodality.
    - **Interpretation**: TruncNorm captures arrival cleanly when the underlying cohort is genuinely unimodal (corporate workplace = tight 8–9 AM peak). Multi-modal arrival (university students, mixed-site averages) yields ~20–30% σ underfit at K-S 0.15–0.22. The driver is *behavioral schedule uniformity*, not site granularity.
  - **S2 (joint Spearman ρ).** All ρ-gaps **below 0.10**; ElaadNL daily_commuter ρ_source=−0.501 vs ρ_generated=−0.489 (gap=0.012); weekday_only gap=0.009. Copula captures the strong negative arrival–dwell correlation faithfully across both single-site and mixed-pool fits.
  - **S3 (held-out KS, 80/20 user split, n ≥ 200 regions only).** Main-region deltas within ±0.06 of training-set KS; ElaadNL weekday_only holdout matches training within 0.002. Confirms parametric fits generalize. Edge regions (erratic, rare_inconsistent) show large deltas — low-sample noise, separately documented.
  - **S5 (building load vs PNNL prototype intent).** Office small peak/off-peak 4.21× (in expected 4–8× range); office medium 8.54× (above), office large 2.38× (below). Weekday/weekend ratios consistently low (1.04–1.37 vs expected 2.5–8×) — surfaced under Section 8 Limits.
  - **S6 (weekly weekday/weekend ratio).** ACN source 5.32× weekday bias; ElaadNL source 45.7× (strong workplace pattern). Generated produces ≈0 weekend sessions across both sources — confirmed paper limitation, Section 8.
- **Honest caveats (Ethics-axis material, not weakness):**
  - **φ definition required a fix.** Original implementation used the global calibration window as denominator; correct definition uses per-user active window. This shifted 98% of ACN users from "unassigned" to assigned regions. Documented in `docs/CALIBRATION_NOTES.md` item #10.
  - **Copula transform is biased.** `ρ_gaussian = 2·sin(π·ρ_spearman / 6)` is exact only for bivariate-normal copulas; for truncnorm × weibull marginals the bias is <0.05 in simulation but not zero. S2 validation shows ρ-gap ≤ 0.10 empirically.
  - **`ks_fit_quality` is training-set.** S3 held-out validation (above) is the v2 answer; deltas confirm fits generalize within ±0.06 for main regions.
  - **ElaadNL TZ.** Naive Europe/Amsterdam timestamps treated as UTC for consistency; arrival_hour offset 1–2h vs wall-clock, uniform across fit, documented.
  - **INL is legacy fleet** (~24 kWh Nissan Leaf, Chevy Volt, 2011–2013). Do not mix with modern-battery scenarios.
- **B4 guard.** `distribution_fitter.py` post-validates every fit against `DIST_PARAM_RANGES`; out-of-range fits are dropped with a warning, generation falls back to placeholder formulas. Fired cleanly on real-data runs (e.g., ACN `occasional_visitor.arrival.sigma=6.45`, ElaadNL `daily_commuter.soc_arrival` underdetermined).

### Figures / tables

- Fig 11 (multi-source calibration faithfulness panel): 2-row figure: row 1 = arrival_hour histogram overlay (source vs 50-seed generated) for ACN/regular_charger and ElaadNL/daily_commuter; row 2 = joint (arrival × dwell) scatter density side-by-side. Build via `tools/validate_calibration.py`.
- Tab 4: 4-source comparison — rows = sources, cols = years, geo, venue, ID strength, license, real-vs-fixture status, calibrated fields, n_sessions/n_users post-filter, caveats.
- Tab 5: S1/S2/S3 numeric summary — rows = (source, region, variable), cols = n, K-S, W₁, Spearman ρ gap, held-out delta.

### Cites

- ACN-Data (Lee et al. 2019), EV WATTS (DOE/EPRI), INL EV Project Phase 1 (Smart & Schey 2012 SAE; INL/EXT-15-35268), ElaadNL Open Charging Transactions dataset (open-data.elaad.io, CC BY 4.0).
- Spearman→Pearson copula transform: Pearson 1907 / Genest & Nešlehová 2007 *Astin Bulletin*.
- NHTS 2017 (FHWA) — future δ source.

---

## Section 5 — Scenario Library  [Axis: Impact] (0.75 pg)

### Key points

- **53 scenarios shipped** (41 pre-built + 12 new scale/contention variants in `configs/scenarios/`). Each is a YAML manifest of descriptor + scenario-level knob overrides, validated at parse time.
- **Experiment families:**
  - **E1 ψ-monotonicity:** S_psi_010, _025, _050, _075, _090. Population willingness descriptor; expected monotone response in DR-revenue / FSL value.
  - **E2 rate structure:** S_rate_flat, S_rate_tou (= S01), S_rate_demand. Energy + demand-charge effect.
  - **E3 DR programs:** S_dr_cbp, _bip, _elrp.
  - **E4 equipment:** S_eq_uni, _bi. Unidirectional vs bidirectional fleet.
  - **E5 CONSENT:** S_consent_relaxed, _strict, _drained_pop, _topped_pop.
  - **E6 building archetype × size:** S_arch_retail, S_bld_large, _medium, _small, plus retail-stand / retail-strip.
  - **E8 climate × season (4×5):** 20 cells (Atlanta, Miami, Minneapolis, San Francisco, San Jose) × 4 seasons.
  - **Calibration showcase:** S_acn_workplace, S_evwatts_workplace, S_inl_residential_legacy, S_elaadnl_public_eu.
  - **Scale & contention:** S_scale_{100, 250, 500}, S_cont_fleet_{100, 250, 500}, S_infra_{50, 100, 200}.
- **Population × Building coupling is loose.** Building library entries carry `default_population` recommendation; mismatched combinations warn but do not block. Lets users explore unusual but plausible combinations (workplace charging in a retail strip, etc).
- **Scenario YAML is the smallest possible surface** — a base scenario + a list of knob overrides. Diff between scenarios is human-readable.

### Figures / tables

- Fig 12 (scenario library matrix).
- Tab 5: scenario family summary keyed to experiment families above.

### Cites

- ASHRAE 90.1-2019 climate zone definitions for the E8 geographic spread.
- CAISO E-CBP, E-BIP, ELRP utility tariff filings for the DR families.

---

## Section 6 — Reproducibility & Verification  [Axis: Quality & Docs] (1.00 pg)

### Key points

- **Bitwise reproducibility contract (D53).** Same scenario + same seed → identical CSV bytes across two runs. Verified via `csv_sha256` dict in `manifest.json` (the manifest itself contains a `generated_at` timestamp so we hash the contents, not the manifest). 11 end-to-end determinism tests in `tests/test_end_to_end.py` pin golden hashes.
  - Determinism preconditions: fixed column order; `lineterminator='\n'`; no `float_format` override; `index=False`; ISO-8601 datetime via `.dt.strftime('%Y-%m-%d %H:%M:%S')`.
- **Knob audit Stage 1 + Stage 2 (`docs/KNOB_AUDIT_*.md`).** Stage 1: 101 declared knobs trimmed to 98 after existence checks; 67 admitted to Stage 2 (the rest are descriptor-only labels, no direct numeric probe). Stage 2: each admitted knob × 5 probe values → assert monotonic-in-expected-direction on a chosen CSV metric. Result: **67/67 MONOTONIC; 0 wrong-direction.** Stage 2 caught three silent measurement bugs (Tab 6).
- **Validator (`validate.py`).** ~40 hard invariants (A through H series in `handoff/spec/validate_spec.md`): schema (A), referential integrity (B), temporal consistency (C), physical/SoC feasibility (D), charger capacity (E), CONSENT / negotiation (F), behavioral axes (G), tariff / DR (H), plus soft checks (S, G5*). E5 (concurrent active ≤ chargers) is a sampler-output check, not a generation-time check, because the sampler is per-car-independent by design; manifest carries the E5 report and `--strict-e5` promotes warnings to `InfeasibilityError`.
- **422-test suite.** ~354 unit + 45 calibration + 11 determinism + V1/V2/V2.5/V3 probe-batteries. **0 failing, 0 xfail, 0 skip** at submission tag.
- **Manifest as provenance ledger.** Every leaf carries `source ∈ {explicit, descriptor:<name>, calibration:<provenance>, hand_specified:<population>, default}`. The audit `docs/AUDIT_REPORT.md` Section A4 shows a real-run distribution: 32 descriptor, 11 calibration, 9 default; zero metadata leakage into knob_resolution.

### Figures / tables

- Fig 15 (verification matrix) — main.
- Fig 03 (manifest excerpt) — small inset.
- Fig 13 (ψ-monotonicity) — appendix.
- Tab 6: bugs caught by verification (chargers bidir column mismatch, occupancy_jitter wrong CSV variance, negotiation_mix row_count metric, C4 arrival>departure under jitter, D6 arrival_soc>required, missing `custom` profile entry).

### Cites

- Pineau et al. 2021 *JMLR* (reproducibility checklist).
- Sandve et al. 2013 *PLOS Comp Bio* (ten simple rules for reproducible research).

---

## Section 7 — Demonstration: Bench Through the Standard Pipeline  [Axis: Impact] (1.00 pg)

**Framing reminder, written into the section so it doesn't drift:** we do **NOT** claim that this bench differentiates V2B charging algorithms. The seven ACN-Sim stock algorithms produce ~identical per-session metrics within each scenario because the bench is configured with `feeder=1.0` (no electrical-service cap; only physical-slot contention). What the bench demonstrates is that **scenario-driven data flows through a standard ACN-Sim pipeline and produces monotonically varying outputs across scenarios**, which is the Impact claim a *data* paper actually owes.

### Key points

- **Setup.** `tools/paper_bench.py` runs the 7 scenarios × 7 ACN-Sim stock algorithms (EDF, LLF, FCFS, LCFS, LRPT, RoundRobin, UncontrolledCharging) at `feeder=1.0`. Inputs: `sessions.csv` + `chargers.csv` from v2b_syndata; ACN-Sim consumes them verbatim.
- **Three load-bearing numbers (from `tools/paper_bench.py` artifact, fold into Table 7):**
  - **Peak load 73 → 1772 kW** across the 7 scenarios — a 24× span purely from scenario knob differences.
  - **Target-miss rate 0.0% → 1.2%** — most scenarios saturate well; one stress scenario shows the saturation threshold.
  - **Admission rejection 0% → 36.4%** — under tight slot scarcity, the standard pipeline drops sessions, and the drop rate is scenario-monotonic.
- **What this evidence supports:** scenarios drive measurable differentiation; manifest provenance + knob audit explain *which* knob moved each metric; downstream papers can pick any two scenarios and run a controlled comparison knowing the input bytes are identical seed-over-seed.
- **What this evidence does NOT support:** an algorithm tournament. All seven algorithms tie within each scenario because slot scarcity dominates control-policy differences when feeder capacity is unbounded.
- **Sensitivity sweep tool exists** at `tools/sensitivity_sweep.py` but is **out of scope** for this paper; mentioned in the repo utilities appendix as the starting point for downstream electrical-capacity sensitivity work.

### Figures / tables

- Fig 14 (climate divergence across same-population scenarios) — main; this is the cleanest visual proof of "scenario drives output."
- Fig 16 (one-day load profiles compared) — appendix.
- Tab 7: 7-scenario bench results — rows = scenario × algorithm (49 cells), columns = peak_kw, target_miss_pct, admission_reject_pct. Highlight the within-scenario invariance and across-scenario variance.

### Cites

- ACN-Sim: Lee et al. 2021 e-Energy.
- Stock scheduler algorithms: EDF (Liu & Layland 1973 *JACM*), LLF (Mok 1983 MIT TR), FCFS (textbook), LCFS, LRPT (Pinedo *Scheduling*).

---

## Section 8 — Accessibility, Ethics & Limits  [Axis: Accessibility + Ethics] (0.50 pg)

### Key points

- **Install path.** `tools/setup.sh` (one command, idempotent) installs `uv`, Python deps, EnergyPlus 23.2 under `~/opt/`, and runs a smoke generation. EnergyPlus version pinned to 23.2.x for glibc compatibility (Ubuntu 22.04 cannot run EnergyPlus 26.x's glibc 2.38 build).
- **No-install paths.** (a) Web frontend at `tools/web/app.py` (Flask, bundled) — browser-based scenario configurator with descriptor-aware knob widgets, source labels, inline CSV + manifest preview; (b) install-free interactive walkthrough at `showcase/short_overview/walkthrough.html` (static page, opens in any browser; live sliders on φ/κ/δ/ρ, Dirichlet α, CONSENT cluster).
- **Hosting & archival (TBD before submission).** Code: anonymized for review, full repo + Git tags post-acceptance. Dataset: a pre-generated reference release (S01 seed=42 plus all 53 scenarios at one seed each, ~few hundred MB compressed) on Zenodo with archival DOI. License: code under existing repo license (verify); data under CC BY 4.0 (matches ElaadNL terms, compatible with ACN-Data permission for redistribution-by-fit, EV WATTS/INL data not redistributed).
- **Ethics.**
  - **No personally identifying information.** Calibration sources produce *distributional* fits; per-user `user_id` strings in the generator (`acn:user:<id>`, `evwatts:port:<id>`, `inl:vin:<id>`, `elaadnl:card:<id>`) are pseudonyms within the source dataset's own anonymization regime, preserved only in calibration metadata, never written to generator output CSVs.
  - **No real-driver re-identification risk.** Generator output is fully synthetic; calibration only fits low-dimensional parametric marginals (3–4 parameters per distribution), insufficient to reconstruct individual sessions.
  - **Geographic & venue representativeness.** Acknowledged limits: workplace charging is overrepresented (ACN + EV WATTS); residential coverage is only INL legacy fleet; only one EU source. Future calibration sources (NHTS for δ; non-PG&E territories for tariff) are roadmapped, not shipped.
  - **Algorithmic-fairness implications of using this data.** Researchers who use these scenarios to compare V2B control policies should report scenario coverage explicitly because policy performance on `S_consent_strict` will differ from `S_consent_relaxed`, and aggregating without disclosure can hide who pays the consent cost.
- **Limits explicitly carried into the paper, not hidden.**
  - **Weekly weekday/weekend pattern is not reproduced** (S6 validation). Real ACN data shows weekday/weekend session-per-day ratio ≈ 5.3×; ElaadNL/Utrecht ≈ 45.7× (workplace lot is empty on weekends). Generated data produces **≈0 weekend sessions** by design — the renderer samples each calendar day i.i.d. and most ship-default scenarios use `sim_window.weekdays_only=true`. Documenting this as v1 limitation; future work adds an explicit weekly-schedule term on φ.
  - **Building load weekday/weekend ratio is flat** (S5 validation, 1.04–1.37× across office sizes vs PNNL expected 2.5–8×). PNNL prototype occupancy schedules do encode weekend differentiation; the post-EnergyPlus aggregation appears to smooth more than expected. Investigating; documented as known.
  - **Building load currently uses Denver-prototype HVAC sizing** (other climate-zone variants are a one-line change in `PROTOTYPE_MAP`).
  - **Day-of-week mis-alignment on calendar Jan 1 2020 Mondays** (rolled into "Sunday Holidays AllOtherDays" branch by PNNL prototype; documented, not chased).
  - **Required-SoC distribution is uncalibrated** (deferred to Step 6). δ uncalibrated (proxy noisy). H2 tariff-tier consistency intentionally breakable under `price_jitter`.
  - **Single-platform tested for bitwise reproducibility** (Linux x86_64 + EnergyPlus 23.2); cross-platform identity not claimed.
  - **EV WATTS / INL Phase 1 are fixture-only** in current shipping repo; bulk-data acquisition deferred (access path documented for each). Generator-as-substrate claim is independent of this — the loader pattern is exercised on synthetic fixtures and validated for the two real sources.

### Figures / tables

- No figure. One small table (Tab 8) listing license / hosting / archival plan checklist with TBDs flagged.

### Cites

- Gebru et al. 2021 *CACM* — Datasheets for Datasets.
- Bender & Friedman 2018 *TACL* — Data statements.
- Mitchell et al. 2019 ACM FAT* — Model cards (precedent for artifact-level disclosure).

---

## Section 9 — Conclusion & Future Work  (0.50 pg)

### Key points

- **One-paragraph recap of contributions** keyed to the four D&B axes.
- **Three concrete next directions** (not exhaustive):
  1. Held-out KS validation of calibration fits (deferred from Step 5.5; needs train/test split harness inside `distribution_fitter`).
  2. NHTS-anchored δ calibration to replace the noisy `milesRequested` proxy.
  3. Region re-anchoring on ACN-empirical (φ, κ) joint (current `consent_default` regions inherit the hand-authored grid; ACN data suggests high-κ-low-φ users are common but uncovered).
- **Invitation to extend.** The `CalibrationSource` protocol is the natural extension surface; downstream contributors add a new source without touching the generator.
- **Datasets & Benchmarks fit, restated.** The contribution is the *generator* + the *scenario library* + the *reproducibility contract*, not any particular pre-generated CSV bundle. Tagged release at submission time provides one canonical bundle; the live generator is the long-term artifact.

### Cites

- Future-work cites only.

---

## References (collected, alphabetized — for paper bibliography)

> Section calls out specific references inline; this is the consolidated list.

- Bender, E.M., Friedman, B. 2018. Data Statements for Natural Language Processing. *TACL* 6.
- Crawley, D.B. et al. 2001. EnergyPlus: creating a new-generation building energy simulation program. *Energy and Buildings* 33(4).
- DOE/EPRI. EV WATTS. https://livewire.energy.gov/ld/eVWATTS.
- ElaadNL. 2020. Open Charging Transactions (CC BY 4.0). https://open-data.elaad.io.
- Gebru, T., Morgenstern, J., Vecchione, B., Vaughan, J.W., Wallach, H., Daumé III, H., Crawford, K. 2021. Datasheets for Datasets. *CACM* 64(12).
- Genest, C., Nešlehová, J. 2007. A primer on copulas for count data. *ASTIN Bulletin* 37(2).
- Goel, S. et al. 2014. *ASHRAE Standard 90.1-2013 Performance Rating Method Reference Manual*. PNNL-23720.
- Idaho National Laboratory. The EV Project (Phase 1). https://avt.inl.gov. Smart, J., Schey, S. 2012. *Battery Electric Vehicle Driving and Charging Behavior*. SAE 2012-01-0199.
- Kempton, W., Tomić, J. 2005. Vehicle-to-grid power fundamentals. *Journal of Power Sources* 144(1).
- Kotelnikov, A., Baranchuk, D., Rubachev, I., Babenko, A. 2023. TabDDPM. *ICML*.
- Lee, Z.J., Li, T., Low, S.H. 2019. ACN-Data: Analysis and Application of an Open EV Charging Dataset. *ACM e-Energy*.
- Lee, Z.J., Sharma, S., Johansson, D., Chu, G., Low, S.H. 2021. ACN-Sim: An Open-Source Simulator for Data-Driven EV Charging Research. *ACM e-Energy*.
- Lewis, P.A.W., Shedler, G.S. 1979. Simulation of nonhomogeneous Poisson processes by thinning. *Naval Research Logistics Quarterly* 26(3).
- Liu, C.L., Layland, J.W. 1973. Scheduling algorithms for multiprogramming in a hard-real-time environment. *JACM* 20(1).
- Lopes, J.A.P., Soares, F.J., Almeida, P.M.R. 2011. Integration of electric vehicles in the electric power system. *Proc. IEEE* 99(1).
- Miller, C. et al. 2020. The Building Data Genome Project 2. *Scientific Data* 7.
- Mitchell, M. et al. 2019. Model Cards for Model Reporting. *ACM FAT\**.
- Mok, A.K. 1983. *Fundamental Design Problems of Distributed Systems for the Hard Real-Time Environment*. MIT.
- Patki, N., Wedge, R., Veeramachaneni, K. 2016. The Synthetic Data Vault. *IEEE DSAA*.
- Pineau, J. et al. 2021. Improving Reproducibility in Machine Learning Research. *JMLR* 22.
- Sandve, G.K. et al. 2013. Ten Simple Rules for Reproducible Computational Research. *PLOS Comp Bio* 9(10).
- Wilcox, S., Marion, W. 2008. *Users Manual for TMY3 Data Sets*. NREL/TP-581-43156. TMYx: climate.onebuilding.org.
- Xu, L., Skoularidou, M., Cuesta-Infante, A., Veeramachaneni, K. 2019. Modeling Tabular Data using Conditional GAN. *NeurIPS*.

---

## Appendices (unlimited per D&B track rules)

- **App A — Datasheet for Datasets** (Gebru et al. 2021 template) for the tagged reference release. Required for D&B submission.
- **App B — Reproducibility Checklist** (Pineau et al. 2021) — explicit seed→hash table for S01 and the 7 bench scenarios; exact CLI invocations; EnergyPlus version pin; OS / glibc / Python pin.
- **App C — Full knob registry** (98 knobs from `handoff/spec/knobs.yaml`) with units, ranges, descriptors-that-touch-them, and which CSV(s) they `affects_csv`.
- **App D — Validator invariant catalog** (A1–H6 + S* soft checks) cribbed from `handoff/spec/validate_spec.md`.
- **App E — Knob audit Stage 1 + Stage 2 results** (from `docs/KNOB_AUDIT_S1.md` and `docs/KNOB_AUDIT_S2.md`) — full per-knob monotonicity table.
- **App F — Calibration provenance** — for each fitted leaf in `configs/populations.yaml`, the source, filter chain, n_samples, ks_fit_quality, capacity-fallback rate.
- **App G — Repo utility tools** — `tools/knob_audit.py`, `tools/pairwise_audit.py`, `tools/sensitivity_sweep.py`, `tools/run_bench_sweep.py`, `tools/verify_sweep.py`, `tools/web/`.
- **App H — Figures not in main text** — Figs 02, 04, 05, 06, 08, 09, 10, 13, 16, 17, 18, 19 with one-line captions.

---

## Authoring checklist (drop after first full draft)

- [ ] All 7 sections fit budgeted page counts (use `\setlength` + ACM template page count).
- [ ] Every section header carries its `[Axis: X]` tag (or a footnote in final paper).
- [ ] Section 7 bench framing line is present verbatim ("we do NOT claim algorithm differentiation…").
- [ ] Section 4 caveats are surfaced as Ethics-axis points, not weaknesses.
- [ ] Repo URL anonymized; Zenodo DOI minted and inserted.
- [ ] Datasheet appendix complete.
- [ ] Reproducibility appendix shows real `csv_sha256` values for S01 seed=42 + the 7 bench scenarios.
- [ ] License table in Section 8 filled in (no TBDs).
- [ ] Cites are concrete (no "TODO cite").
- [ ] Figure captions name the source file under `showcase/figures/`.
