# Reproducibility & Accessibility — v2b_syndata

Companion prose for KDD D&B paper Sections 6 (Reproducibility & Verification, 1.0 pg, primary axis *Quality & Docs*) and 8 (Accessibility, Ethics & Limits, ~0.25 pg of the shared 0.5 pg budget, primary axis *Accessibility*). Exact numeric claims trace to `data/calibration_validation/*.csv`, `docs/KNOB_AUDIT_S1.md`, `docs/KNOB_AUDIT_S2.md`, and `docs/AUDIT_REPORT.md`.

---

# Part A — Reproducibility

The reproducibility contract is the centerpiece of the artifact: *the same `(scenario, seed)` produces byte-identical CSVs across runs on the same platform, and every value in those CSVs is traceable to a documented source.* This section makes that contract concrete in six layers — a bitwise determinism primitive, a manifest provenance ledger, a two-stage knob audit, a 450-test pytest harness, a hard-invariant validator, and an empirical calibration-faithfulness battery — and is explicit about the one thing the contract does not cover.

The motivation for this layering is that no single mechanism is sufficient. Bitwise determinism without manifest provenance gives reproducibility without interpretability — you can re-run the bytes but cannot say why they came out that way. Manifest provenance without a knob audit gives interpretability with no guarantee that the documented `affects_csv` declarations describe what actually happens at runtime. A knob audit without a calibration-faithfulness check gives a self-consistent generator with no anchor to real data. A calibration-faithfulness check without hard invariants gives statistical plausibility without per-row physical legality. The six layers below are designed to be independently auditable and jointly necessary.

## A.1 Bitwise reproducibility (the D53 contract)

The generator commits to the following identity. For any scenario YAML *S* and integer seed *s*, two independent runs of `v2b-syndata generate --scenario S --seed s` on the same platform produce, for each of the seven output CSVs, byte-identical files — verified by SHA-256 over file contents and recorded in `manifest.csv_sha256`. This is enforced by four discipline primitives in `src/v2b_syndata/seeding.py` and the renderer base class:

1. **Per-node SHA-256 seeding.** Every sampler-node draws from an independent `numpy.random.SeedSequence` keyed by `entropy = global_seed` and `spawn_key = (stable_int(name), [car_id])`, where `stable_int(name) = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")`. SHA-256 — not Python's built-in `hash()` — is mandatory: CPython 3 hash randomization re-salts each process, so `hash()` cannot be used for cross-process determinism. This guarantees the *additive property* needed for an evolving generator: adding a new node never perturbs the seed sub-stream of any existing node, because spawn keys are derived from node *names*, not spawn order.
2. **Deterministic pandas serialization.** Every renderer calls `df.to_csv(..., lineterminator='\n', index=False)` with no `float_format` override. Default pandas float repr is deterministic given identical inputs; explicit `lineterminator='\n'` blocks platform-specific CRLF substitution; `index=False` blocks an unwanted leading column. Column order is pinned by an explicit list in each renderer (not by `df.columns`-at-construction-time, which can drift under refactors).
3. **ISO-8601 datetime stamping.** All timestamps are written as `df['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')` strings, not via the default Timestamp repr. Locale, timezone, and pandas-internal format toggles cannot change the byte sequence.
4. **`noise.profile = clean` by default.** The single-shot CLI default profile has all six post-render jitters set to 0; the entire pipeline is fully deterministic at the byte level. Non-`clean` profiles (`light_noise`, `realistic_noise`, `adversarial`, `tmyx_stochastic`, `custom`) sample additional random variates, but each is seeded from the same node-and-seed primitive, so they remain bitwise reproducible at fixed `(scenario, seed, noise.profile)`.

`tests/test_reproducibility.py` pins the contract: it hashes the seven CSVs from two independent `generate("S01", seed=42)` calls and asserts byte-equality across all seven files. `tests/test_determinism_stress.py` extends this to multiple seeds and parametrized scenarios — its core invariant is "10 different seeds × 10 runs each: each seed produces a single hash that recurs across all 10 runs; across the 10 seeds, hash diversity ≥ 9." `tests/test_end_to_end.py` carries golden `csv_sha256` values for representative scenarios and would fail under any silent serialization drift. The full design rationale is documented in `docs/DESIGN_NOTES.md` items 7 (per-node seeding) and 8 (CSV serialization discipline).

A subtle point is that this discipline gives more than determinism — it gives **seed-stable refactoring.** A maintainer can rename `node_name="arrival_sampler"` to `node_name="arrival_sampler_v2"` and confidently expect that the old name's bytes are unrecoverable, *and* expect that the new name's seed sub-stream is independent of any other node's. The cost of seed-stable refactoring is bounded by the willingness to rename consistently. This is what the audit pipeline (A.3) verifies as a side-effect when it perturbs one knob at a time and confirms it does not perturb unrelated nodes.

Concretely, the implementation in `src/v2b_syndata/seeding.py` is 43 lines total:

```python
def stable_int(name: str) -> int:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")

def seed_for_car(global_seed: int, node_name: str, car_id: int) -> np.random.SeedSequence:
    return np.random.SeedSequence(
        entropy=global_seed,
        spawn_key=(stable_int(node_name), int(car_id)),
    )
```

Every sampler that takes a stochastic action calls `rng_for_node(seed, "<node_name>")` or `rng_for_car(seed, "<node_name>", car_id)`, never `np.random` global state and never `random` from the stdlib. This is enforced by code review and by the fact that any sampler bypassing the discipline would fail `test_reproducibility.py` immediately.

## A.2 Manifest provenance — every value traceable to its source

Every realization emits a sibling `manifest.json` next to the seven CSVs. The manifest is the artifact's provenance ledger; without it, a CSV bundle is a black box. Its required keys are pinned by validator invariant I1 (`handoff/spec/validate_spec.md`):

- `scenario_id`, `seed`, `generator_git_sha`, `noise_profile` — identifies the exact code, scenario, seed, and noise mode that produced the run.
- `knob_resolution` — a dict mapping every knob path in `configs/knobs.yaml` to `{value, source}`, with `source ∈ {explicit, descriptor:<name>, calibration:<provenance>, hand_specified:<population>, default}`. Validator invariant I4 enforces that every registry knob appears in this block: there is no such thing as an unaccounted-for parameter. The four-source-tag taxonomy makes it possible to attribute a downstream result back to a single design choice — was a delta a CLI override, a descriptor preset, a real-data fit, or a hand-curated value?
- `csv_row_counts` and `csv_sha256` — invariants I2 and I3 cross-check row counts and content hashes against the on-disk CSVs; mismatches abort.
- `calibration_metadata` — when a calibrated population is used, this block records provenance string (e.g. `acn_data_2019_2021_20260506`), `n_users` and `n_sessions` post-filter, capacity-inference fallback rate, unassigned-user rate, and per-region `n_samples` and `ks_fit_quality`.
- `e5` — the post-render concurrency report: realized max concurrent active sessions versus charger capacity, with an `infeasible_tick_fraction` field. The validator's `--strict-e5` flag promotes E5 warnings to a hard `InfeasibilityError`.

Fig 03 in `showcase/figures/` shows a manifest excerpt; we reproduce it as a small inset in the published section. The audit `docs/AUDIT_REPORT.md` Section A4 reports a real-run resolution distribution (32 descriptor / 11 calibration / 9 default leaves) and confirms zero metadata leakage into `knob_resolution` (calibration provenance lives in its own block, not interleaved with knob values).

The source-tag taxonomy is precise about the kind of evidence behind each value:

- `explicit` — set by a `--set knob.path=value` CLI flag for this run.
- `descriptor:<name>` — set by Tier-0 descriptor expansion (Location / Building / Population / Equipment library entry). E.g. `descriptor:office_medium_v2` for `building_load.peak_kw` when the building descriptor is `office_medium_v2`.
- `calibration:<provenance>` — fitted from real data; the provenance string identifies the source, version window, and run date (e.g. `calibration:acn_data_2019_2021_20260506`).
- `hand_specified:<population>` — set by the population library author (e.g. CONSENT cluster means, δ commute distance) and not by data fit. Visible at audit time so readers can distinguish design choices from empirical anchors.
- `default` — the value from `configs/knobs.yaml`'s `default:` field, fired only when no upstream layer claims the knob.

A scenario-result paper that wants to attribute an outcome to a specific cause inspects `manifest.knob_resolution` and immediately sees which rung of the four-tier resolution chain owned each value.

This is one of the genuinely strongest accessibility-of-evidence features of the artifact: most downstream analyses of V2B results require the analyst to track down what the "default" actually was. With a v2b_syndata manifest, the default is named: `default` means `configs/knobs.yaml`'s value, not "whatever the codebase happened to produce on that run." The git SHA recorded in `manifest.generator_git_sha` lets a reader pin the exact registry state.

## A.3 Knob audit Stage 1 + Stage 2

`v2b_syndata` ships a two-stage monotonicity audit of every registry knob against every CSV it claims to touch — the audit verifies that the knob *exists*, that its declared `affects_csv` list is honored at runtime, and that perturbing it moves the affected CSV in the expected direction. The two stages are runnable as `tools/knob_audit.py` (Stage 1) and `tools/sensitivity_sweep.py` (Stage 2); they regenerate `docs/KNOB_AUDIT_S1.md` and `docs/KNOB_AUDIT_S2.md`.

**Stage 1 — Existence + Isolation (`docs/KNOB_AUDIT_S1.md`).** The 101 knobs declared in `configs/knobs.yaml` were trimmed to 98 after existence checks. Of these 98: 67 `HONORED` (declared `affects_csv` matches runtime-observed effect), 28 `NO-DECLARATION` (categorical / simplex / list[region] knobs that have no ordinal probe direction and are therefore tracked but not direction-audited), 3 `UNTESTABLE` (knobs gated behind a mode that the scenario library does not exercise in the default S01 baseline), 0 `OVER-COUPLED`, 0 `UNDER-COUPLED`, 0 `OVERRIDE-REJECTED`. The clean count of 0 across the failure verdicts is the headline finding: the declared `affects_csv` schema is the actual runtime effect schema.

**Stage 2 — Direction + Magnitude (`docs/KNOB_AUDIT_S2.md`).** The 67 ordinal knobs from Stage 1 are each probed across 5 values × the CSVs they touch (1–4 CSV metrics each, depending on declared coverage). Verdict distribution: **67/67 MONOTONIC, 0 NON-MONOTONIC, 0 WEAK-EFFECT, 0 WRONG-DIRECTION, 0 NO-EFFECT.** Two probe-range adjustments are documented inline in the report: a Weibull-k floor of 0.5 for `dwell.k` probes (below 0.5 the density collapses to a degenerate spike near zero, and the std/var metric becomes statistically unreliable while not reflecting real-pipeline behavior), and a sparse-region baseline override for `occasional_visitor.*` deep-channel leaves (probed against `S_audit_baseline` 50-EV scenario instead of S01's 1-user-typical, so that std/correlation metrics have enough samples to converge). Stage 2 caught and forced fixes for three silent measurement bugs that the unit-test suite had missed (chargers bidirectional column-mismatch, occupancy_jitter wrong-CSV variance attribution, negotiation_mix row-count metric off-by-one) — these are Tab 6 in the published Section 6.

**Pairwise (Stage 3) audit (`docs/PAIRWISE_AUDIT.md`).** A 50-pair sample (`random.seed=42`) of knob × knob interactions: 44 LINEAR, 1 MILDLY_NONLINEAR, 2 MODERATELY_NONLINEAR, 3 UNINFORMATIVE, 0 STRONGLY_NONLINEAR, 0 SIGN_FLIP. The two moderately-nonlinear pairs — `building_load.peak_kw × noise.building_load_jitter_pct` (flex variance is multiplicative in both factors by construction) and `utility_rate.dr_program × noise.dr_notification_dropout_prob` (notification lead is bounded below by the program-specific minimum) — are expected and documented.

The audit pipeline is itself reproducible: `tools/knob_audit.py` and `tools/sensitivity_sweep.py` both consume the same `configs/knobs.yaml` registry and emit timestamped + git-SHA-stamped markdown reports. The Stage 1 and Stage 2 numbers above were generated against the `40afef9` git SHA on 2026-05-19.

What this audit gives a downstream user is a stronger claim than the more typical "the parameters do something." It gives: *for every knob in the registry, perturbing it in the documented direction moves the documented CSV's documented metric in the documented direction, across the registry's declared range.* In a 98-knob system that is the difference between a black-box generator and one where a reader can reason about the effect of a parameter change without re-running it. The Stage 2 report is the single most useful diagnostic when a downstream contributor proposes a new knob — adding the knob means adding a row to the report.

## A.4 The 450-test pytest harness

`uv run pytest --collect-only` reports **450 tests** at the submission tag, broken down by area:

| Area | Files | Test count | What they enforce |
|---|---|---|---|
| Edge / boundary cases | `test_edge_cases.py`, `test_noise_d3_clamp.py`, `test_noise_fixes.py`, `test_sessions_dist_fallback.py` | 71 | D5/D6 rejection, D3 clamp, noise-profile bound preservation |
| Knob registry + loader | `test_knob_loader.py`, `test_descriptor_loader_calibration.py`, `test_descriptor_resolution.py`, `test_calibration_policy.py` | 60 | Resolution chain CLI > scenario > descriptor > default; manifest source tagging |
| Sampler / renderer | `test_samplers/`, `test_renderer_copula.py`, `test_dr_renderer.py`, `test_dirichlet.py`, `test_dag.py` | ~60 | Per-sampler invariants, copula transform, DR-event thinning, DAG ordering |
| Variation modes | `test_variation_descriptors.py`, `test_variation_modes.py`, `test_variation_overrides.py` | 54 | Tier-0 descriptor → Tier-1 root expansion |
| Calibration + sources | `test_calibration/` (10 files: ACN fetcher, EVWATTS, INL, ElaadNL extractors; feature_extractor, region_assignment, distribution_fitter, writer, api orchestration, multi-source integration, battery_inference, e2e) | ~75 | Per-source loader, MLE fits, B4-guard, write-back byte-equivalence |
| Validator invariants | `test_consistency.py`, `test_validate_calibration_invariants.py`, `test_e5_hybrid.py`, `test_exogenous_hydrate.py` | 43 | A–I hard invariants exercised end-to-end |
| Determinism / reproducibility | `test_reproducibility.py`, `test_determinism_stress.py`, `test_end_to_end.py`, `test_custom_noise_profile.py`, `test_tmyx_stochastic.py` | 25 | Same-seed → same bytes; cross-seed divergence; golden hashes |
| Bench | `test_bench/test_bench_smoke.py` | 15 | ACN-Sim pipeline plumbing |
| Load pipeline | `test_load_pipeline/` (weather, prototypes, e2e_load, cache) | 21 | EnergyPlus runner cache, weather hydration, prototype IDF parsing |
| CLI / batch | `test_cli.py`, `test_cli_calibrate.py`, `test_batch.py`, `test_runner_modes.py` | 26 | Top-level CLI surface, batch mode, calibrate subcommand |

Status at submission tag: **0 failing, 0 xfail, 0 skip** when EnergyPlus 23.2 is installed. (The historical `xfail` for ACN_API_TOKEN cache-hit semantics, recorded in `docs/AUDIT_REPORT.md`, is resolved.) Line coverage 91% (`docs/COVERAGE_REPORT.md`). The 450 count moved past the OUTLINE.md "422" placeholder during the Step-5.5 calibration-validation work; the suite continues to grow as new invariants are surfaced. CI integration is planned as a GitHub Actions matrix over (Linux Ubuntu 22.04, macOS 13) × Python {3.10, 3.11, 3.12} on the public-release branch.

Two test-suite design choices are worth surfacing:

- **`conftest.py` provides a `config_dir` fixture** that points the runner at a hermetic copy of `configs/`. Tests never mutate the on-disk repo state; runner-side caches (EnergyPlus IDF artifacts, TMYx weather files) write to `tmp_path`. This is what makes the determinism tests parallelizable and what keeps `pytest -n auto` from racing.
- **Calibration tests run against synthetic fixtures by default.** `tests/test_calibration/test_e2e_calibration.py` and the per-source extractor tests consume small in-repo fixtures (80 sessions / 6 ports for EVWATTS; 78 sessions / 4 vehicles for INL). The full-corpus calibration is exercised only when `ACN_API_TOKEN` is set; absent the token the test is skipped, not failed. This keeps CI green on forks without external secrets.

## A.5 Hard validators — the D-class invariant battery

`v2b-syndata validate <output_dir>` runs ~40 hard invariants against a freshly generated realization. Hard invariants abort generation with exit code ≠ 0 and delete partial outputs; soft checks (the `S*` series, run with `--soft`) emit warnings only. The full catalog lives in `handoff/spec/validate_spec.md`; the structure is:

| Series | Count | Class | Examples |
|---|---|---|---|
| A. Schema-level | 5 | per-CSV | A1 file exists, A2 column set exact, A3 dtypes, A4 no NaN in non-nullable columns, A5 categoricals from declared choice sets |
| B. Referential integrity | 7 | cross-CSV | B1 `set(users.car_id) == set(cars.car_id)`, B2 `sessions.car_id ⊆ cars.car_id`, B3–B7 ID uniqueness |
| C. Temporal consistency | 11 | timeline | C1 15-min monotone grid, C3 building_load grid == grid_prices grid, C4 arrival < departure, C7 per-car non-overlap, C11 DR notification lead matches program rule |
| D. Physical / SoC feasibility | 7 | physics | D1 SoC bounds well-formed, D5 reachability `(required − arrival) / 100 × capacity ≤ max_rate × duration × 1.05`, D6 `required > arrival`, D7 `required ≥ min_depart_soc × 100` |
| E. Charger / capacity | 5 | infra | E1–E4 rate-sign discipline + bidir symmetry, E5 concurrent-active ≤ charger count (post-render report; `--strict-e5` promotes to error) |
| F. CONSENT / negotiation | 5 | population | F1–F2 (w1, w2) ≥ 0 and finite, F3 cluster means within 2σ of `user_types.yaml`, F4–F5 population shares within F_SHARE_TOL=0.20 of configured weights (loose due to ev_count=20 sample size) |
| G. Behavioral axes | 4 | per-user | G1–G3 φ ∈ [0,1], κ ∈ [0,1], δ_km ≥ 0; G4 (φ, κ, δ_km) inside declared region |
| H. Tariff / DR | 6 | pricing | H1 flat tariff constant, H2 TOU prices match peak window (legitimately breakable under `price_jitter`), H3–H5 DR event counts respect program rules, H6 magnitudes in range |
| I. Manifest | 4 | provenance | I1 required keys present, I2 row counts match, I3 SHA-256 match, I4 every registry knob resolved |

D5 reachability and D6 strict-inequality are enforced by **rejection sampling, not clamping** — early clamping was an identified bug, fixed in Step 5 (see `docs/DESIGN_NOTES.md` item 4). The distinction matters: clamping moves a tail sample to the boundary, biasing the marginal toward the boundary; rejection redraws until a feasible sample lands inside the joint feasible region, preserving the marginal's interior shape. D7 binds `required_soc_at_depart` against the per-user `min_depart_soc` floor; the rejection budget retries a sample up to N times before dropping the session and warning. The `--strict` flag promotes soft warnings (S1–S5) to hard errors for stress-testing; `--strict-e5` specifically promotes the E5 concurrency report.

Soft distribution checks (S1–S5, in `tests/test_distributions.py`) cover the cross-source semantic invariants that are bounds, not equalities: KS-distance of `building_load` duration curve vs EnergyPlus prior < 0.10; KS of arrival distribution vs ACN per-region < 0.15 (the S2 validator below tightens this empirically); energy balance σ session-energy-delivered ≤ σ available-charger-throughput × duration × efficiency; ψ-tier alignment between sampled users and the population library entry's declared ψ band; Building↔Population coupling warning when scenario's `population` differs from `building.default_population`.

## A.6 Calibration-faithfulness validation — empirical generated-vs-real

`tools/validate_calibration.py` is the v2 answer to the natural question *"does the generator's output actually look like the data its parameters were fit to?"*. It generates 50 seeded realizations per real-calibrated source (ACN, ElaadNL/4TU Utrecht), pools the generated and source sessions per region, and runs five orthogonal checks. Output CSVs land in `data/calibration_validation/{S1_marginals, S2_joint, S3_holdout, S5_buildingload, S6_weekly}.csv`. Headline numbers (all from those CSVs; full table in App F):

**S1 — Per-region marginal KS + Wasserstein-1.** Quality tracks behavioral homogeneity, not source granularity. Best fit: ACN/Office001 regular_charger (corporate, n=347), **K-S = 0.097**, σ_source = 1.87 ≈ σ_generated = 1.68 on arrival_hour. ElaadNL/Utrecht daily_commuter (n=8,227): K-S = 0.179, W₁ = 0.49. ElaadNL/Utrecht weekday_only (n=19,174): K-S = 0.159, W₁ = 0.49. ACN mixed regular_charger (3 sites pooled, n=17,857): K-S = 0.147. ACN/JPL regular_charger (NASA, n=12,484): K-S = 0.166 (σ underfit 22%). ACN/Caltech regular_charger (university, n=5,306): K-S = 0.198 (σ underfit 33%). Interpretation: TruncNorm captures arrival cleanly when the underlying cohort is genuinely unimodal (corporate workplace, tight 8–9 AM peak); multi-modal cohorts (university students, mixed-site averages) yield 20–30% σ underfit at K-S 0.15–0.22. Edge cohorts (`erratic`, `rare_inconsistent`) show K-S 0.38–0.55 — these are the by-definition "noisy" regions and are flagged as such.

**S2 — Joint Spearman ρ on (arrival_hour, dwell_hours).** All region ρ-gaps ≤ 0.10 across both sources. ElaadNL daily_commuter: ρ_source = −0.501 vs ρ_generated = −0.489, **gap = 0.012**. ElaadNL weekday_only: gap = 0.009. ACN regular_charger: gap = 0.044. The Gaussian copula faithfully reproduces the strong negative arrival-dwell correlation across single-site and mixed-pool fits. The 0.10 ceiling on the copula transform bias documented in `docs/CALIBRATION_NOTES.md` item 4 is empirically validated.

**S3 — Held-out KS with deterministic 80/20 user split.** Main-region delta within ±0.06 of training-set KS. ElaadNL weekday_only arrival_hour: ks_train = 0.144, ks_holdout = 0.142 (Δ = −0.002). ElaadNL daily_commuter dwell_hours: Δ = −0.059. ACN regular_charger arrival_hour: Δ = +0.051. ACN/JPL occasional_consistent arrival_hour: Δ = −0.058. Confirms parametric fits generalize for n ≥ 200 regions. Edge regions (erratic, rare_inconsistent) show larger deltas — low-sample noise, separately documented.

**S5 — Building load vs PNNL prototype intent.** `S_size_small` office peak/off-peak ratio 4.21× (in expected 4–8× range, ✓). `S01` office_medium 8.54× (above range — high-intensity flex profile). `S_size_large` 2.38× (below — flat-utilization large-office profile). Weekday/weekend ratios 1.04–1.37× across all four scenarios versus PNNL expected 2.5–8× — surfaced as a known v1 limit in Section 8.

**S6 — Weekly weekday/weekend ratio.** Source: ACN 5.32×, ACN/JPL 11.6×, ACN/Caltech 2.61×, ElaadNL 45.7×. Generated: 0 weekend sessions across all sources (the renderer samples each calendar day i.i.d. and ship-default scenarios use `sim_window.weekdays_only=true`). Documented as a v1 limit; future work adds an explicit weekly-schedule term on φ. The cohort spread in source ratios (2.6× → 45.7×) underlines that "weekend behavior" is itself a deployment-context variable, not a single universal constant — the workplace lot in Utrecht is empty on weekends in a way the Caltech campus is not.

Reading the CSVs directly is the recommended path for downstream readers: `S1_marginals.csv` columns include `(source, region, variable, n_source, n_generated, ks_statistic, ks_pvalue, wasserstein_1, source_mean, source_std, generated_mean, generated_std)`; `S2_joint.csv` exposes per-region `rho_source`, `rho_generated`, `rho_gap`; `S3_holdout.csv` columns are `(source, region, variable, n_train, n_test, ks_train, ks_holdout, delta)`. None of these numbers are placeholders — they were produced by the same `validate_calibration.py` invocation against the same `populations.yaml` fitted parameters that ship with the repo.

Two design choices in the validation harness are worth flagging because they materially affect how the headline numbers should be read:

- **50 seeded scenario generations per source.** The generated-side sample size is bounded by the cost of 50 scenario runs, not by the cost of pooling sessions; pooling across 50 seeds gives n_generated in the 200–7,000 range per region, which is comfortably above the n ≥ 200 threshold used for the held-out S3 cut.
- **Deterministic 80/20 user split for S3.** Sort users by `user_id`, take the first 80% for train and last 20% for test. Determinism here matters: the same train/test split fires every time the validator is invoked, so the S3 number is reproducible at the byte level and a downstream user can verify the split independently.

The S5 weekday/weekend gap (1.04–1.37× generated vs 2.5–8× PNNL expected) is currently the single most informative validation finding. It says: the PNNL prototype IDFs *do* encode weekend differentiation in their occupancy schedules, but the post-EnergyPlus aggregation step appears to smooth the differentiation more than expected. We document this in Section 8 as a known v1 limit and as a directly-actionable v2 task. The fact that S5 has a numerically explicit gap (rather than a hand-waved "could be better") is the kind of artifact-quality signal a D&B reviewer can act on.

## A.7 What is *not* bitwise-stable — the honest limit

We claim bitwise identity *within* a fixed platform configuration, not *across* configurations. Specifically:

- **Cross-platform identity is not claimed.** Tested platform is Linux x86_64 + glibc 2.35 (Ubuntu 22.04) + EnergyPlus 23.2.0 (`7636e6b3e9` build) + Python 3.10–3.12 + the pinned `uv.lock`. macOS 13 has been verified to install and produce structurally-valid outputs, but the EnergyPlus float discipline differs by sub-ULP between EnergyPlus builds, so byte-equality across OS is not asserted. Windows is untested.
- **Transitive pip-resolved dependencies can shift the bytes.** numpy minor-version updates can change reduction order; pandas float-repr is stable across the versions in `pyproject.toml` but is not part of pandas's public contract. Use the committed `uv.lock` as the pin; if you `pip install` outside `uv`, record the resolved versions in your manifest.
- **EnergyPlus version drift breaks `building_load.csv` byte-equality.** The 23.2.x line is pinned for two reasons: (a) Ubuntu 22.04's glibc 2.35 cannot run the EnergyPlus 26.x glibc-2.38 build, and (b) HVAC zone-sizing convergence subtly shifts between major versions. `tools/setup.sh` will force-install 23.2.0 if a different system EnergyPlus is detected.
- **Realizations from before `acn_data_2019_2021_20260506` use older calibration parameters.** Provenance strings record the date of the calibration run; reproducing a pre-20260506 realization requires checking out the corresponding generator git SHA from the manifest. The reproducibility contract is point-in-time over the git history, not retroactive.

The reproducibility appendix (App B in the paper) lists explicit `csv_sha256` values for `S01 seed=42` and the 7 bench scenarios against the submission-tag generator SHA, so a reviewer can verify byte-identity end-to-end.

The framing we adopt is *contractual reproducibility with documented scope*. Within the platform we test against, the contract is bitwise — the strongest possible reproducibility claim. Across platforms, the contract relaxes to structural reproducibility (same schemas, same invariants, same distributional properties) and we say so explicitly. This is preferable to either over-claiming (advertising cross-platform identity without testing it) or under-claiming (refusing to assert byte-identity even where it holds).

---

# Part B — Accessibility

The accessibility surface is built on two assumptions: (a) the prospective user does not know what `uv sync` does, and (b) the prospective reviewer does not want to install EnergyPlus. We address (a) with a one-command setup script that is idempotent and agent-driveable, and (b) with two no-install browser paths.

The accessibility design is intentionally redundant. Three doors lead in: shell script, agentic command, browser frontend. Each is sufficient on its own; the user picks whichever matches the tool already in front of them. The cost of redundancy is one markdown file + one shell script + one Flask app — small relative to the value of not blocking a reviewer on an install issue.

## B.1 One-command install (`tools/setup.sh`)

`./tools/setup.sh` is the deterministic install path. It is idempotent (safe to re-run; phases whose post-conditions hold are skipped) and fails fast with the next-manual-step printed inline. Phases:

1. **Sanity.** Confirm CWD contains `pyproject.toml` and `src/v2b_syndata/`; detect OS + arch.
2. **`uv`.** If `uv --version` runs, skip. Otherwise install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (Linux/macOS) and amend `PATH` for the current shell.
3. **Python deps.** `uv sync` streams output.
4. **EnergyPlus 23.2.0.** Probe `discover_energyplus()` first. If absent or major.minor ≠ 23.2, download the NREL `7636e6b3e9` build matching the platform from `https://github.com/NREL/EnergyPlus/releases/download/v23.2.0/`, extract to `~/opt/EnergyPlus-23-2-0/`, and re-probe. Auto-discovery walks `~/opt/`, `/usr/local/EnergyPlus-*`, `/opt/EnergyPlus-*`, `$ENERGYPLUS_PATH`, `$ENERGYPLUS_BIN`, and `which energyplus`. Missing binary raises `EnergyPlusBinaryNotFound` with the install URL embedded in the error message — no silent fallback to a stub.
5. **Smoke generation.** `uv run python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir /tmp/v2b_setup_smoke/`. Confirm 7 CSVs + `manifest.json` exist. Clean up.
6. **Report.** Print a status table; every row must read `OK`:

```
component       status   detail
uv              OK       0.x.y
python deps     OK       uv sync clean
EnergyPlus      OK       ~/opt/EnergyPlus-23-2-0/energyplus  (23.2.0)
smoke gen       OK       S01 seed=42 → 7 CSVs + manifest
```

Verified on fresh Ubuntu 22.04 and macOS 13 (arm64 + x86_64). The script source is `tools/setup.sh`; the equivalent agentic markdown lives at `.claude/commands/setup.md` (see B.3). Setup time on a warm pip cache: ~90 seconds (uv sync) + ~200 MB EnergyPlus download.

Three discipline points keep this script accessible:

- **No `sudo`.** EnergyPlus extracts into the user's home directory (`~/opt/`). The script never asks for elevated privileges; on a shared workstation or container this matters.
- **Re-entry is idempotent.** Re-running the script after a partial failure picks up where it left off. Each phase has a post-condition probe — `uv --version`, `discover_energyplus()`, `dist-info` for the package, the smoke output dir — and re-runs only the failed phase.
- **Failure is loud.** `set -euo pipefail` is set at the top; any unexpected exit prints `FAIL: <message>` and the next manual step. The README and the agentic command file both reiterate this contract so a reader can predict the script's failure mode without reading it line-by-line.

## B.2 No-install paths — browser-only review surface

Two browser-driveable paths let a reviewer kick the tires without installing anything.

**(a) Web frontend (`tools/web/app.py`).** A Flask app bundled in the main `uv sync` install (no `pip install` step). Launch via `uv run python tools/web/app.py`; the app binds 127.0.0.1:5000 by default. The page is a descriptor-aware scenario configurator — Location, Building, Population, Equipment dropdowns wire through to the descriptor expansion pipeline, and an Advanced panel exposes individual knobs with their declared range, default, and source label (`descriptor:<name>`, `calibration:<provenance>`, `default`). Generation runs the same CLI codepath; output lands in `tools/web/runs/` (last 20 retained, gitignored) and is previewed inline as CSV head + `manifest.json` excerpt. Batch generation (multiple seeds per scenario) is one toggle. See `tools/web/README.md` for LAN exposure and architecture details. This is the **recommended first-run path** because it surfaces the descriptor → knob → CSV chain without forcing the user to learn the CLI flag set.

**(b) Install-free interactive walkthrough (`showcase/short_overview/walkthrough.html`).** A self-contained static HTML page; no Python, no server, no network — the Plotly library is bundled. Open in any browser. Two tabs:

- *Playground* — live Plotly sliders on φ, κ, δ, ρ (Gaussian copula correlation), region preset, battery_mix simplex, Dirichlet α, CONSENT cluster selector; **10 live panels + a worked-day text trace update on every drag.** Drives home the link between behavioral-axis values, region marginals, and per-session realizations.
- *Concepts & 2-car example* — prose explainer of the (φ, κ, δ) → region → session pipeline plus an interactive 2-car week-long session simulator (per-car region + φ/κ/δ/ρ sliders, deterministic luck so slider drags isolate the *causal* effect of each axis).

Launch invocations are listed in `README.md` for Linux (`xdg-open`), macOS (`open`), WSL (`explorer.exe "$(wslpath -w …)"`), and headless (`python -m http.server 8080` from `showcase/short_overview/`).

The walkthrough is meant to do one specific thing: let a reviewer who has never read a `users.csv` or `sessions.csv` see, in 30 seconds, that the (φ, κ, δ, ρ) axes are not abstract — they are slider-driveable and they have visible effect on per-session realizations. The 2-car simulator's *deterministic luck* discipline (fixed PRNG state per slider configuration) means a reviewer can confirm, by isolated slider drags, that φ shifts session count and κ shifts arrival-time variance. This is the same signal the audited monotonicity report (A.3) carries, but rendered visually.

## B.3 Agentic-CLI integration

`v2b_syndata` ships with an agent-agnostic install contract. The deterministic fast path is `tools/setup.sh`; the agentic equivalent at `.claude/commands/setup.md` is a markdown spec covering the same five phases (sanity → uv → uv sync → EnergyPlus → smoke → report) but with explicit license to improvise when the deterministic path fails — list GitHub release assets via the API, pick a glibc-matched tarball, install missing `curl`, etc. The two paths are intentionally redundant; the script is the fast common-case answer, the markdown command file is the fallback for the long tail.

| Agent | Invocation |
|---|---|
| Claude Code | open repo with `claude`, type `/setup` (resolves to `.claude/commands/setup.md`) |
| Copilot CLI / Codex / Gemini CLI / Cursor / Aider | prompt: *"run `tools/setup.sh`; if it errors, fall back to the steps in `.claude/commands/setup.md`"* |
| No agent | `./tools/setup.sh` |

The shell script and the markdown command share intent but not implementation. Either is sufficient.

The motivating observation behind shipping both is that an agentic CLI is increasingly the *first* tool a new user invokes on an unfamiliar repo — `claude` or `gemini` or `cursor` is more likely to be opened than `bash` is, in 2026. A repo whose setup story degrades into "ask the user to debug a curl 404" is a repo whose practical accessibility is much lower than its actual install complexity warrants. The two-path design is meant to make the install experience the same regardless of which tool the user reaches for first.

## B.4 Documentation surface

The repo's first-class documentation comprises:

- `README.md` (148 lines, quickstart-focused) — install, web frontend, CLI generate, walkthrough launch.
- `docs/` (9 markdown files):
  - `DESIGN_NOTES.md` — 31 items documenting non-trivial implementation choices (seeding, CSV discipline, EnergyPlus quirks, noise bounds).
  - `CALIBRATION_NOTES.md` — 19 items documenting the calibration filter chain, fit-quality caveats, copula transform bias, source-specific idiosyncrasies.
  - `AUDIT_REPORT.md` — bug-discovery and resolution log; the ground truth for what has been found and fixed.
  - `EDGE_CASE_REPORT.md` — 48 boundary tests documented.
  - `KNOB_REFERENCE.md` (auto-generated by `v2b-syndata docs-gen`).
  - `KNOB_AUDIT_S1.md` + `KNOB_AUDIT_S2.md` — the audit reports referenced in A.3.
  - `PAIRWISE_AUDIT.md` — the 50-pair Stage 3 audit referenced in A.3.
  - `COVERAGE_REPORT.md` — pytest line coverage.
- `handoff/spec/` (6 specification files):
  - `PLAN.md` — the original generator-design specification.
  - `BAYES_NET.md` — Tier 0 → Tier 3 topology, per-CSV schema definitions.
  - `validate_spec.md` — the A–I invariant catalog referenced in A.5.
  - `knobs.yaml` — the registry referenced everywhere.
  - `ACN_DATA_CALIBRATION.md` — the canonical recipe for the ACN fit.
  - `DATASET_AUDIT.md` — cross-source coverage matrix.
- `showcase/` — `OVERVIEW.md` (the showcase narrative), `README.md` (figure index and launch-instructions for the walkthrough), 19 publication-ready figures under `showcase/figures/`.
- `paper/` — this paper's working files: `OUTLINE.md`, `DATASHEET.md` (Gebru et al. 2021 template, 412 lines), `RELATED_WORK.md`, `PLAN.md`, `REPRODUCIBILITY_ACCESSIBILITY.md` (this file).

What the documentation is explicitly *not*: a tutorial corpus. We do not ship Jupyter notebooks walking new users through "build your first scenario" because the web frontend already does that interactively, and because every duplicated tutorial path is another path that can drift out of sync with the code. The walkthrough, the README quickstart, the web frontend, and the showcase deck cover the user-facing surface; everything below that is reference documentation pointing at the code as the source of truth.

## B.5 EnergyPlus availability

`v2b_syndata` requires EnergyPlus 23.2.x. The pin has two motivations:

- **glibc compatibility.** The current Ubuntu LTS (22.04) ships glibc 2.35; the EnergyPlus 26.x line requires glibc 2.38 (Ubuntu 24.04+ / Debian 13+ / RHEL 10+). The 23.2.x line builds against glibc 2.35 and runs on 22.04 unmodified. Forcing users onto a not-yet-LTS distro to run the artifact is a non-starter for accessibility.
- **HVAC sizing stability.** EnergyPlus zone-sizing convergence subtly differs between major versions; pinning 23.2 holds `building_load.csv` byte-stable.

Discovery walks five locations in order: `~/opt/EnergyPlus-*`, `/usr/local/EnergyPlus-*`, `/opt/EnergyPlus-*`, then the `$ENERGYPLUS_PATH` and `$ENERGYPLUS_BIN` environment overrides, then `which energyplus`. Missing binary raises `EnergyPlusBinaryNotFound` with the install URL embedded in the error message — no silent fallback to a stub. The error message itself is the install instructions, so a user who has never read the README still gets actionable guidance from the first failed `generate` invocation.

`tools/setup.sh` will *force-install* 23.2.0 if a system EnergyPlus of a different major.minor version is detected. This deliberately overrides a system install: we would rather a user run two EnergyPlus side-by-side than have building-load bytes drift between users on the same scenario seed. The forced-install is to `~/opt/`, never to a system path, so no `sudo` is required and the system EnergyPlus (if any) remains intact.

## B.6 Open distribution plan

| Artifact | Plan |
|---|---|
| Code | Anonymized GitHub mirror for double-blind review; full repo (untagged commits + Git tags) post-acceptance. |
| Tagged release | Git tag `v2b-syndata-v1` at submission, mapping to a specific generator git SHA recorded in every `manifest.json`. |
| Archival DOI | Zenodo deposit post-acceptance, mirroring the tagged release + a pre-generated reference bundle (`S01 seed=42` and the 7 bench scenarios at one seed each, ~few hundred MB compressed). Lets users not running EnergyPlus locally still reproduce the paper's numeric claims. |
| Dataset license | **CC BY 4.0** for the generated dataset bundle — matches ElaadNL's source terms and is compatible with the ACN-Data redistribution-by-fit permission and the EV WATTS / INL U.S. Government work-product status. |
| Code license | `[TODO at submission time]` — MIT or Apache-2.0 (working plan); no `LICENSE` file is committed yet, this is one of the resolved-before-submission TBDs. |
| Calibration sources | Not redistributed. `configs/populations.yaml` carries the fitted distributional parameters and `provenance` strings (e.g. `acn_data_2019_2021_20260506`); raw per-session data is re-fetched from the originating sources via the `CalibrationSource` loader if a user needs to re-run calibration. |
| Contributions | Issue tracker + PR review through GitHub post-acceptance. The four extension surfaces — new knobs, new scenarios, new descriptors, new calibration sources — are documented in `docs/KNOB_REFERENCE.md` and `src/v2b_syndata/calibration/sources/`. |
| ElaadNL/4TU substitution | The original ElaadNL Open Charging Transactions endpoint was retired in favor of a dashboard-only interface during this project's development; we substituted the ElaadNL/4TU Utrecht dataset (DOI 80ef3824, CC BY-NC-SA 4.0) into the ElaadNL slot. The provenance string in shipped configurations identifies the actual dataset used; downstream redistribution of fitted parameters derived from the 4TU corpus must preserve the CC BY-NC-SA attribution. |
| Pre-rendered bundle | `[TODO at submission time]` likely a Zenodo deposit of `S01 seed=42` plus the seven bench scenarios at one seed each (~few hundred MB compressed). Lets users who cannot install EnergyPlus reproduce the bench numbers. |

The reproducibility contract holds across both distribution channels: a user who installs from the GitHub mirror and generates locally and a user who downloads the Zenodo bundle and validates SHA-256 against `manifest.csv_sha256` should see byte-identical files for any `(scenario, seed)` pair we publish.

Extension paths for future contributors are documented in the datasheet maintenance section: new knobs land via `configs/knobs.yaml` + an entry in the next audit run; new scenarios drop into `configs/scenarios/` with the four descriptor fields; new calibration sources implement the `CalibrationSource` protocol in `src/v2b_syndata/calibration/sources/` (existing examples: `acn_fetcher.py`, `evwatts.py`, `inl.py`, `elaadnl.py`); new descriptors extend the library YAMLs (`configs/locations.yaml`, `configs/buildings.yaml`, `configs/populations.yaml`, `configs/equipment.yaml`). The test suite at `tests/` is the contract — new contributions add or extend tests.

---

## Appendix-bound reproducibility checklist (Pineau et al. 2021)

The full Pineau et al. 2021 reproducibility checklist lives in Appendix B of the paper. The headline answers, all answered "yes" with specific repo locations, are:

- *Code released with the paper?* Yes — full repository under anonymized GitHub mirror for review, deanonymized at acceptance.
- *Random seeds documented?* Yes — `manifest.seed` per realization; `tests/test_reproducibility.py` for the bitwise contract.
- *Hardware specification?* CPU-only; no GPU required. EnergyPlus 23.2.0 + Python 3.10–3.12. Smoke-tested platform is Linux x86_64 + glibc 2.35 (Ubuntu 22.04).
- *Software versions pinned?* `uv.lock` committed; EnergyPlus pinned to 23.2.0 (`7636e6b3e9` NREL build) in `tools/setup.sh`.
- *Dependencies enumerated?* Yes — `pyproject.toml` + `uv.lock`. No private/proprietary dependencies.
- *Dataset license documented?* CC BY 4.0 for the generated bundle; per-calibration-source attribution preserved in `manifest.calibration_metadata.provenance` (ACN-Data terms, EV WATTS U.S. Gov, INL U.S. Gov, ElaadNL/4TU CC BY-NC-SA 4.0).
- *Code license documented?* `[TODO at submission time]` — MIT or Apache-2.0 (working plan); resolved before submission.
- *Code documentation?* `README.md` + `docs/` (9 files) + `handoff/spec/` (6 files); auto-generated `KNOB_REFERENCE.md` ensures the knob registry doc stays in sync.
- *Statistical tests reported?* Yes for the calibration validation harness — S1 KS + W₁, S2 Spearman ρ gap, S3 held-out KS Δ, all reported per-region with sample sizes.
- *Negative results / limits documented?* Yes — S5 weekday/weekend gap, S6 weekend-session-zero, INL legacy-fleet caveat, capacity-inference fallback rate, copula-transform bias upper bound, are all surfaced in Section 8.
- *Reproducibility appendix?* Yes — App B carries explicit `csv_sha256` values for `S01 seed=42` and the 7 bench scenarios; App C lists the full knob registry; App D lists the validator invariant catalog A1–H6 + S*; App E carries the Stage 1 + Stage 2 audit tables; App F carries calibration provenance per fitted leaf.
- *External resources required to reproduce?* EnergyPlus 23.2.0 (force-installed by `tools/setup.sh`); TMYx weather files from `climate.onebuilding.org` (cached locally on first use). Calibration sources (ACN, ElaadNL/4TU) needed only to *re-run* calibration; fitted parameters ship in `configs/populations.yaml`, so generation does not require network access to the calibration endpoints.
- *Datasheet?* Yes — full Gebru et al. 2021 datasheet shipped as `paper/DATASHEET.md` (412 lines, all seven sections: Motivation, Composition, Collection, Preprocessing, Uses, Distribution, Maintenance).
- *Data statement (Bender & Friedman 2018)?* Partial — the calibration sources' geographic and venue coverage is documented in Section 4 + DATASHEET §3; the synthetic nature of the generator means several data-statement axes (speaker demographics, recording conditions) do not apply.

*End of Reproducibility & Accessibility writeup. Hard facts back-referenced: `data/calibration_validation/{S1_marginals,S2_joint,S3_holdout,S5_buildingload,S6_weekly}.csv`; `docs/KNOB_AUDIT_S1.md`; `docs/KNOB_AUDIT_S2.md`; `docs/PAIRWISE_AUDIT.md`; `handoff/spec/validate_spec.md`; `src/v2b_syndata/seeding.py`; `tools/setup.sh`; `tests/test_reproducibility.py`.*
