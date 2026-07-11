# KDD 2027 D&B — Paper Structure (end-to-end)

> The complete skeleton of the submission: every section, claim, figure, table,
> and the evidence each rests on. Companion docs: `KDD_READINESS.md` (task
> tracker), `KDD_SUBMISSION_PLAN.md` (sprint plan). Created 2026-07-07;
> **rev 2 (2026-07-08)** after adversarial verification — all numbers below
> re-checked against repo ground truth; ⚠ marks items with open caveats.

## Venue facts (verified against the posted CFP, 2026-07-08)

- **KDD 2027 Datasets & Benchmarks, Cycle 1**: abstract **Jul 19, 2026**;
  full paper **Jul 26, 2026** (AoE); rebuttal Sep 29–Oct 13; notify Nov 14.
- **Format:** ACM `acmart` sigconf, **8 content pages at submission** +
  references + **appendix with no page limit**; camera-ready 9 content pages
  (12 total). → The first draft is written unconstrained (per author
  decision); overflow migrates to the appendix, and the per-section weights
  below are the final 8-page trim guidance.
- **Single-blind** (author names listed — no anonymization work needed).
- **OpenReview**; GitHub link recommended; **hyperlinks cannot be added after
  submission** — all artifact links must be in the submitted PDF.
- Category: **Data Generators and Environments** — synthetic data "must be
  accompanied with a quantification and discussion of its representativeness,
  in addition to proving its utility."

## Title candidates

1. **v2b-syndata: A Calibrated, Reproducible Generator for Vehicle-to-Building
   Energy Datasets** *(preferred; "v2b-syndata" in prose, `v2b_syndata` only
   for code identifiers — keep consistent)*
2. Synthetic Vehicle-to-Building Data with Physical Simulation and Behavioral
   Calibration
3. From One Seed to a Campus: Generating Calibrated V2B Datasets for Learning
   and Optimization

## Abstract skeleton (≈180–200 words, one sentence per line)

1. **Problem:** V2B research requires coupled building-load / EV-charging /
   tariff / DER data that is unavailable: real logs are privacy-restricted,
   confined to a few sites, and no charging equipment records battery state of
   charge.
2. **Artifact:** v2b-syndata, a configurable generator emitting coupled
   15-minute datasets (building load, charging sessions, driver attributes,
   tariffs, DR events, PV, storage specs) for parameterized scenarios.
3. **Physical:** building load from EnergyPlus simulation of DOE prototype
   buildings under perturbed typical-year weather; the same weather frame
   drives the PV model and is exported with the data.
4. **Calibrated:** driver behavior fitted per behavioral region from **three
   real charging corpora — ACN-Data, EV WATTS, ElaadNL —** with documented fit
   quality and provenance (plus a fixture-calibrated 2011-era INL cohort as an
   explicitly labeled distribution-shift benchmark).
5. **Reproducible:** a scenario file and one integer seed regenerate any
   dataset bitwise; every run ships a provenance manifest.
6. **Representativeness:** load fidelity vs ComStock/BDG2 (ASHRAE G14);
   per-region marginal + copula fidelity with held-out protocol and bootstrap
   CIs.
7. **Utility:** train-on-synthetic/test-on-real (TSTR) short-horizon
   forecasting transfers at parity with train-on-real **on ACN**; cross-cohort
   transfer (ElaadNL) reported as a shift study. ⚠ scope pending WS-C outcome.
8. **Release:** generator (MIT), datasets (CC BY 4.0), Croissant metadata,
   datasheet, benchmark scenarios; an 18,000-sample multi-building corpus.

## Contribution list (Introduction, verbatim candidates)

- C1. A forward-sampling generative model for coupled V2B data whose behavioral
  layer is calibrated per region from three real charging corpora (ACN,
  EV WATTS, ElaadNL), and whose building layer is a real EnergyPlus simulation
  — with a single perturbed weather realization shared by load, PV, and the
  exported weather channel.
- C2. A reproducibility contract: hash-keyed randomness (order-independent
  sub-streams), bitwise (scenario, seed) → dataset determinism, and per-value
  provenance manifests; plus datasheet, Croissant metadata, and dual licensing.
- C3. A two-sided evaluation meeting the D&B "generators" bar:
  representativeness (G14 building-load fidelity vs ComStock/BDG2; held-out,
  CI-quantified distributional fidelity vs the calibration corpora) and utility
  (TSTR forecasting at parity with TRTR on ACN; cross-cohort shift study).
- C4. A released benchmark suite: 60 scenario configurations spanning sites,
  building types, cohorts, and equipment; distribution-shift cohort pairs
  (US workplace → EU public → fixture-calibrated 2011-era residential,
  labeled as such); and an 18,000-sample 10-building reference corpus.

## Section-by-section plan (weights = 8-page trim guidance; draft fully)

### 1. Introduction (1.0 pp)
- The three data barriers (privacy, site-lock, unmeasured SoC); why generation
  (control, counterfactuals, label completeness, privacy by construction).
- Contributions C1–C4; Figure 1 referenced early.
- **State the SoC honesty position here** (SoC channels are calibrated model
  priors, not measurements) — pre-empt, don't bury.

### 2. Related Work (0.75 pp)
- EV charging datasets (ACN-Data, ElaadNL, EV WATTS, INL EV Project) and their
  access/coverage limits.
- Building-energy corpora & simulation (ComStock/EULP, BDG2, DOE prototypes,
  EnergyPlus) — consumed as ground truth/physics, not competitors.
- Synthetic generators: EV session models (ACN-Sim's generative layer, ElaadNL
  simulators), deep generative timeseries (TimeGAN lineage) — positioning:
  deep models imitate one site's joint law, are neither controllable nor
  auditable; we trade nonparametric expressiveness for parametric families +
  copula with provenance and knobs.
- TSTR protocol lineage; datasheets (Gebru et al.); Croissant.

### 3. The Generator (1.5 pp)
- 3.1 Design: descriptors → knob resolution (69 typed knobs, priority chain,
  per-value provenance); sampling DAG tiers T0–T3; **Figure 1**.
- 3.2 Building physics: DOE/PNNL ASHRAE-90.1-2019 prototypes; TMYx EPW;
  input-side perturbation (ΔT; solar ×; dew-point Δ with Magnus-consistent RH;
  wind ×); 15-min meters; flexible/inflexible split; peak-normalization
  switch; one-weather-truth property.
- 3.3 Behavioral layer: axes (φ, κ, δ); region boxes; per-driver sampling;
  session synthesis = copula-coupled arrival/dwell + SoC draws under **six**
  feasibility gates enforced **by rejection** (same-day C12; window;
  non-overlap; SoC monotonicity D6; behavioral departure floor D7 — active for
  hand-specified populations, 0 for calibrated cohorts; energy reachability
  D5). Gate equations + copula inversion (bisection PPF on shared uniforms).
- 3.4 Tariffs, DR (thinned inhomogeneous Poisson, program constants), PV
  (PVWatts-v5 chain), storage (specs only — dispatch is a downstream
  decision, argued).
- 3.5 Reproducibility: SHA-256 spawn-keyed `SeedSequence` sub-streams;
  order-independence; manifest schema.
- 3.6 Noise model: output-side measurement noise as a separate optional
  channel; D5 post-jitter repair contract.

### 4. Calibration from Real Charging Data (1.25 pp)
- **Sources table (Tab 1), with policy labels:**
  - ACN-Data 2019–21: 632 assigned users / 41,774 sessions; region shares
    36.1 / 0.6 / 39.8 / 23.0% (fitted).
  - EV WATTS public: **1,265,017 real sessions** ingested (workplace cohort;
    fitted 2026-06-28). ⚠ `CALIBRATION_RESULTS.md` predates this — regenerate
    before Tab 1/2 are final (sprint WS-F).
  - ElaadNL / 4TU Utrecht 2020–24: 55,379 raw sessions → 55,201 fitted;
    1,231 driver identifiers; own re-anchored 4-region grid (fitted).
  - INL EV Project 2011–13: **fixture-calibrated** (65-session fixture, so
    labeled) — released as a legacy-fleet shift *benchmark*, not claimed as a
    calibration corpus.
- Axes extraction → S0 region assignment: unassigned 0–0.5% on the current
  grids; **re-anchoring on the empirical (φ, κ) cloud done for ElaadNL
  (76% → 0% unassigned); ACN re-anchor pending (W8)** — state as is.
- Per-region MLE fits: arrival TruncNorm/GMM-k (window [4,22]); dwell Weibull ±
  mixture; **mixtures gated on KS improvement ≥ 0.02 with n ≥ 60; any fit
  requires n ≥ 30**; Gaussian copula via Spearman→Gaussian ρ; per-region fits
  replace pooled broadcast (worst-cell fix: rare_consistent arrival KS
  0.179 → 0.079, committed in `CALIBRATION_RESULTS.md`).
- SoC reconstruction (the honest model): no source records SoC; arrival SoC =
  shared seeded prior; departure SoC = prior + delivered/capacity; capacity
  inference fallback ≈ 33% (ACN). Provenance stamps carry this into every
  manifest.

### 5. Representativeness Evaluation (1.25 pp)
- 5.1 Building load vs real: G14 CV(RMSE)/NMBE + shape correlation vs ComStock
  (CZ 5B/3B/4A/6A) and 19 BDG2 meters; shape corr 0.71–0.94; peak-hour ≤ 3 h;
  **EUI: 4/5 archetypes 37–54% below stock-average ComStock; office/large 27%
  above (NMBE −27.1%)** — reported per-archetype, framed as single-prototype
  scope. `peak_kw_scaling` off for comparison.
- 5.2 Behavioral marginals & joint: per-region |Δμ| / KS / W₁ (mean |Δμ|
  0.31 h; worst cell KS 0.233); copula ρ-gap ≤ 0.226; **held-out protocol**
  (**family-matched protocol, landed 2026-07-08**: median Δ(holdout−train
  KS) = 0.069, worst cells +0.234 and +0.425 at n_test=62 — the earlier
  single-family 0.012 was flattering and is superseded) + **bootstrap CIs
  (landed)**: B=1000 seeded percentile, e.g. worst cell KS 0.222
  [0.209, 0.235].
- 5.3 Calibration-fix ablation: pooled→per-region (0.179→0.079, committed) and
  GMM-k arrival (⚠ 0.148→0.073 currently has **no committed primary source**
  — regenerate via WS-F before citing).
- 5.4 DER: PV vs NREL PVWatts v8/SAM (sprint WS-B; <5% annual target); DR
  magnitudes grounded in program documents or explicitly stylized (WS-D).

### 6. Utility Evaluation — TSTR (1.0 pp)
- Protocol: short-horizon forecasting; train synthetic vs train real; held-out
  real test; TSTR/TRTR ratio.
- ACN (committed, `data/tstr/results.json`): lagged 0.99×/0.92× (MAE/RMSE);
  calendar-only probe 0.57×/0.79×.
- **ElaadNL ⚠: an adverse committed artifact exists**
  (`results_elaadnl.json`: lagged 7.61×/6.31× — but run against the mismatched
  scenario `S_acn_caltech`, 91 synthetic sessions vs a 481 kW site). Sprint
  WS-C re-runs with the matched `S_elaadnl_public_eu`; the paper reports the
  corrected number whatever it is — parity claim stays scoped to ACN unless
  ElaadNL clears it, else framed as a cross-cohort shift study.
- Magnitude caveat: shape-normalized transfer metric + stated scope.

### 7. Release: Datasets, Benchmark, Access & Maintenance (0.75 pp)
- Licenses (MIT code / CC BY 4.0 data); datasheet; Croissant; manifests
  (⚠ refresh datasheet + croissant.json to cover the campus corpus and
  restored caches — sprint; fix stale `battery_dispatch` mention in
  `DATA_LICENSE.md`).
- The 18,000-sample campus corpus: 10 buildings × 12 months × 150
  **weather-realized** samples (per-unit configs pin per-sample ΔT/solar/dew/
  wind draws; note: the *batch-level* manifest field reads `none` because
  weather profiles are per-building — recording fix in sprint); 0 hard errors;
  **soft-warning profile disclosed** (E5 near-saturation and seasonal
  H3/H7 warnings — counts reported, framed).
- **Hosting & maintenance plan:** Zenodo (or equiv.) deposit + DOI for the
  corpus; GitHub for the generator; versioning = (git SHA, config, seed)
  triplet; maintenance commitment statement. Links in the PDF at submission
  (CFP rule).
- Benchmark scenarios (60 configs); scheduling baseline (`bench`, ACN-Sim) —
  **scope: V1G evaluation; V2B dispatch intentionally downstream** (parallel
  to specs-not-decisions design); `verify_sweep` repaired to run end-to-end.
- **Compute statement:** ≈117 s/sample ⇒ ≈580 CPU-hours for the 18k corpus
  (30-worker wall-clock ≈ 8 h); single-run generation ≈ 2 min.

### 8. Limitations & Ethics (0.5 pp)
- Single-climate-zone prototype physics (Denver CZ-5B) vs multi-site tariffs;
  EUI deviations incl. the office/large overshoot; load *shape* validated
  across CZs.
- SoC channels are model priors (one line, again).
- ACN region grid not yet re-anchored (W8); κ origin-dependence (W4).
- Gaussian copula chosen for closed-form inversion though Frank fits better
  (W5) — stated with the transform-bias note.
- F4/F5 share tolerance relaxed vs original spec (W10) — validation-rigor
  scope.
- Tariffs are descriptor constants, not yet URDB-validated (#9).
- Parametric families; near-uniform arrival tail approximated (#12).
- Ethics: synthetic-by-construction privacy; source licenses honored;
  `docs/ETHICS.md` summarized.

### 9. Conclusion (0.25 pp) — one paragraph.

### Reproducibility statement (unnumbered, required)
- Every paper number regenerable: calibrate → validate_calibration (with CIs)
  → validate_buildingload → tstr_forecasting → model_eval from committed
  configs (sprint WS-F closes the loop; paper cites only
  `docs/experiments/PAPER_NUMBERS.md` values). Commands + seeds + git SHA +
  compute statement.

### Appendix plan (no page limit at submission)
- A: full knob registry table; B: full per-region fit tables with CIs;
  C: invariant catalog (A1–I4, 59 checks); D: campus corpus datasheet extract +
  warning profile; E: additional TSTR ablations; F: figure-scale versions of
  the axes grids.

## Figures & tables inventory

| ID | Content | Source asset | Status |
|---|---|---|---|
| Fig 1 | Pipeline overview (L0–L7, one-weather-truth) | redraw from GENERATION_VISUAL/deck (vector) | to produce |
| Fig 2 | Axes grids: hand-authored vs ACN-anchored (φ×κ boxes + weights) | deck slide-7 canvas → matplotlib | to produce |
| Fig 3 | Arrival: synthetic prior vs fitted bimodal mixture + per-region KS before/after | deck slide 8 + CALIBRATION_RESULTS S1 | to produce |
| Fig 4 | Load fidelity: synthetic vs ComStock/BDG2 weekly shapes + G14 inset | validate_buildingload outputs | re-render |
| Fig 5 | TSTR bars: TSTR vs TRTR (ACN, ElaadNL-corrected) × feature sets | data/tstr + WS-C | partial |
| Tab 1 | Calibration sources (n, span, venue, **policy label**) | populations.yaml metadata | ready after WS-F regen |
| Tab 2 | Per-region fidelity: |Δμ| / KS / W₁, in-sample + held-out, **bootstrap CIs** | CALIBRATION_RESULTS + WS-A | partial |
| Tab 3 | G14 per (archetype, CZ) vs ComStock/BDG2 | validate_buildingload | ready |
| Tab 4 | TSTR/TRTR ratios | data/tstr + WS-C | partial |
| Tab 5 | Release inventory (files, licenses, sizes, DOI, Croissant) | repo + WS hosting | after refresh |

## Claims → evidence map (audit before submission)

| Claim | Evidence | Where |
|---|---|---|
| Physically simulated load | EnergyPlus + prototypes + G14 vs real meters | §3.2, §5.1, Tab 3 |
| Behaviorally calibrated (3 corpora) | per-region fits, held-out KS, CIs | §4, §5.2, Tab 2 |
| Bitwise reproducible | determinism tests, hash-keyed seeding, manifests | §3.5, repro stmt |
| Useful for learning | TSTR parity (ACN) + corrected ElaadNL result | §6, Tab 4 |
| Honest SoC | reconstruction model + provenance stamps | §4, §8 |
| Scalable | 18k corpus, 0 hard errors, compute stmt | §7 |
| Coupled channels | one-weather-truth property | §3.2 |
| Weather-realized corpus | per-unit config offsets (not batch field) | §7 |

## Anticipated reviewer attacks → planned defenses

| Attack | Defense |
|---|---|
| "Benchmark doesn't exercise V2B discharge" | **CLOSED 2026-07-11**: LP dispatch baseline (V2B 29.4% vs V1G 18.7% peak shave, 0 relaxations, ACN-Sim cross-check) — §6 + app:dispatch |
| "Fidelity numbers are in-sample" | **CLOSED**: family-matched held-out (median 0.064, outliers disclosed) + B=1000 CIs on every cell |
| "PV/DR unvalidated" | **CLOSED**: PV +1.27% vs PVWatts v8 (§5.3); DR grounded (BIP/CBP) or stylized-declared (ELRP) |
| "One climate zone" | §8 + multi-CZ shape validation |
| "SoC is fabricated" | intro-level honesty + §4 contract |
| "Only 2–3 real corpora; INL is fake" | INL labeled fixture everywhere; claim scoped to 3 |
| "ElaadNL TSTR fails" | **CLOSED 2026-07-11**: scale/duration study — shape parity in every arm; raw gap mostly scale (7.38→3.05); residual = activity rate, quantified — §6 + app:tstr |
| "Copula misspecified (Frank > Gaussian)" | §8 W5 statement + inversion-tractability rationale |
| "Region grid stale for ACN" | §4/§8 W8 statement |
| "F4/F5 tolerance loosened" | §8 validation-scope statement |
| "Tariffs not real" | §8 #9 statement (descriptor constants, URDB mapping future) |
| "Parametric families too rigid" | mixture ablation + roadmap |
| "Why not a deep generative model" | §2 positioning |
| "EUI off" | per-archetype numbers incl. the +27% cell, §5.1/§8 |
| "Thousands of soft warnings in corpus" | §7 warning-profile disclosure |

## Notation table (keep consistent)

φ plug-in frequency · κ timing consistency · δ daily distance (km) ·
ρ Gaussian-copula correlation · KS two-sample Kolmogorov–Smirnov ·
W₁ Wasserstein-1 · CV(RMSE)/NMBE per ASHRAE Guideline 14 ·
TSTR/TRTR train-synthetic(real)-test-real.

## Numbers still owed by the sprint (draft placeholders marked ⟨⟩)

1. ~~Bootstrap CIs for Tab 2~~ ✅ landed (WS-A, 2026-07-08).
2. Corrected ElaadNL TSTR row (WS-C, matched scenario).
3. PV vs PVWatts v8 annual/hourly error (WS-B).
4. DR grounding outcome (WS-D).
5. Regenerated `CALIBRATION_RESULTS.md` incl. EV WATTS + the 0.148→0.073
   ablation with a committed primary source (WS-F).
6. Final git SHA + compute statement for the repro statement (WS-F).
