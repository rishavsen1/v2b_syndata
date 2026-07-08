# Project Tracker

The single live, hand-maintained backlog for `v2b_syndata`: conventions
(dos & don'ts), open items, wanted improvements, consciously-deferred work,
items blocked on external data, a forward decision log, and a done log.

**How to add a row:** append to the right section's table with the next ID in
that section's prefix. Keep `Source/Ref` pointing at the authoritative doc or
`file:line` so a reader can reconcile.

**How this relates to the other docs (the consolidated set):**

| Doc | Role |
|---|---|
| `README.md` | Entry point — install, run, schema, model overview. |
| `docs/DESIGN_NOTES.md` | Historical, numbered implementation-decision log (cited *by section number* from source — never renumber). |
| `docs/CALIBRATION_NOTES.md` | How the fit is run and what it biases (cited *by item number* from configs/scenarios/code — never renumber). |
| `docs/GENERATIVE_MODELS.md` | Why each distribution family was chosen. |
| **`docs/PROJECT_TRACKER.md`** | **This file — the live to-do / conventions list.** |

`docs/CALIBRATION_RESULTS.md`, `docs/KNOB_REFERENCE.md`, `docs/MODEL_SELECTION.md`,
`docs/PAIRWISE_AUDIT.md`, `docs/KNOB_AUDIT_S1.md`, `docs/KNOB_AUDIT_S2.md` are
**auto-generated** — do not edit by hand and do not track their internal numbers
here; rerun their generators (see DESIGN_NOTES / tool headers) and treat them as
source-of-truth for their own metrics. (`CALIBRATION_RESULTS.md` is emitted by
`tools/validate_calibration.py`; rebuild it cheaply from existing CSVs with
`--md-only`.) Items below *mirror* their open conclusions for visibility only.

_Last updated: 2026-07-08._

---

## Conventions — Dos & Don'ts

Load-bearing invariants and habits that must not be silently violated.

| ID | Rule | Area | Source/Ref |
|---|---|---|---|
| C1 | **DON'T** downgrade D3 to a soft-check for noisy outputs — keep D3 a hard invariant and clamp at noise-injection time. | noise | AUDIT_REPORT (O-series), DESIGN_NOTES D25 |
| C2 | **DON'T** generally clip post-jitter values — accepting that real noise can break invariants is the D25 design; only the specific C4/D6/D5 bounds are enforced. | noise | EDGE_CASE_REPORT |
| C3 | **DON'T** treat E5 concurrency as a sampler guarantee — the sampler enforces only D5 reachability; size charger pools to the fleet or scenarios silently emit E5-infeasible CSVs (`--strict-e5` to fail loudly). | sampler | DESIGN_NOTES #30, EDGE_CASE_REPORT |
| C4 | **DON'T** derive arrival-SoC from `kWhRequested` (`1 − req/cap`) — ACN delivered/requested ≈ 0.58 contradicts it; arrival SoC is a fixed Beta(4,6) prior. | calibration | README, GENERATIVE_MODELS |
| C5 | **DON'T** mix INL legacy-fleet data with modern-battery scenarios (battery-capacity assumptions diverge). | calibration | CALIBRATION_NOTES |
| C6 | **DON'T** `>`-redirect `docs-gen` over a `KNOB_REFERENCE.md` that has a hand-written tail — `docs-gen` prints only the auto section to stdout, so a naive redirect clobbers the tail. | docs | cli.py docs-gen |
| C7 | **DO** document that `lat`/`lon` are metadata-only/decorative without `tmyx_station`; weather signal comes from the EPW/TMYx. | calibration | AUDIT_REPORT N1, KNOB_REFERENCE |
| C8 | **DO** treat line-coverage as advisory; re-run if it segfaults under `--cov` (pandas/yaml C-ext); clear the 90% gate without chasing EnergyPlus-gated infrastructure lines. | testing | COVERAGE_REPORT |
| C9 | **DO** investigate whenever `unassigned_user_rate > 20%`. | calibration | CALIBRATION_NOTES |
| C10 | **DO** keep the web server off the public internet (no auth); LAN exposure requires an explicit `app.py` host change. Same base+seed+no-overrides must stay bitwise-identical to the CLI. | web | tools/web/README.md |

---

## Open Items

Active bugs / gaps currently in scope.

| ID | Item | Area | Source/Ref |
|---|---|---|---|
| O1 | **B2:** EnergyPlus SIGSEGV on `mixed_use_v1` × hot climate (houston_tx, atlanta_ga) — check `mixed_use_v1.idf` cooling-coil sizing / condenser temps. Transient / not always reproducible. **Not reproduced 2026-07-08** (EnergyPlus 24.1.0, `mixed_use_v1` × `houston_tx`, `mode=month`, seed 42, cold `V2B_LOAD_CACHE_DIR` — both composite-prototype E+ sims ran clean). Kept open as transient; if it recurs, capture `eplusout.err` before retrying. | energyplus | AUDIT_REPORT |
| O2 | **O3:** multi-population calibration not audited — run real ACN-Data calibration per `--population` for `stable_commuter_heavy` and `occasional_visitor_dominant`. | calibration | AUDIT_REPORT |
| O3 | **O2:** CLI auto-validate skips when any jitter knob is non-zero (`cli.py:33-43`) — either auto-validate noisy outputs with relaxed thresholds or enforce hard-invariant clamps at noise-injection time. | validation | AUDIT_REPORT |
| O5 | Coverage low-hanging tests: `cli.py` cmd_generate/cmd_validate/list-knobs/list-scenarios subprocess tests; `knob_loader._check_type_and_range` malformed-value; `validate._load_csv/_load_manifest` empty-dir; `dag.py` duplicate-register raise (L78); `runner.py` custom sim_window missing start/end; ~5 `validate.py` error-branch fault-injection. | tests | COVERAGE_REPORT |

---

## Wanted

Modeling/feature improvements not yet scheduled.

| ID | Item | Area | Source/Ref |
|---|---|---|---|
| W1 | Arrival-hour `TruncNorm[6,20]` is the weakest link: unimodal model of a bimodal quantity; clips ~8.3% of arrivals at the 6:00/20:00 bounds. GaussMix-2 fits far better (KS 0.029 vs 0.108). *(Partly addressed — ACN now ships a 2-component `truncnorm_mixture`; this tracks generalizing it.)* | arrival | GENERATIVE_MODELS, README, MODEL_SELECTION |
| W2 | KDE/GMM beat the current TruncNorm (arrival) and Weibull (dwell) marginals on the large datasets — pilot GMM-2 for arrival+dwell on ONE region behind a flag and re-run `model_eval` before any generator change. | modeling | MODEL_SELECTION |
| W3 | Arrival distributions are pooled per population, not per region — `stable_commuter_heavy` and `visitor_heavy` `region_distributions` still TODO. | calibration | CALIBRATION_NOTES |
| W4 | `kappa` metric is origin-dependent — make it origin-invariant (circular or std-based) and re-tune the `axes_distribution` grid. | metric | MODEL_SELECTION, CALIBRATION_NOTES |
| W5 | Frank copula fits arrival × dwell better than the chosen Gaussian copula (kept for closed-form marginal-inverse-CDF coupling); copula transform bias documented but not corrected (needs likelihood-based per-region fit). | copula | GENERATIVE_MODELS, CALIBRATION_NOTES |
| W6 | `required_soc_at_depart` is still hardcoded `TruncNorm(85,5)` — split into its own `f_required_soc` distribution with copula linkage to arrival SoC. | soc | CALIBRATION_NOTES, DESIGN_NOTES #22 |
| W7 | Departure-SoC Beta fit is partly synthetic (real signal is delivered/capacity, mean ~0.30) and inherits the arrival prior's shape. | soc | GENERATIVE_MODELS |
| W8 | Re-anchor `axes_distribution` boxes on each dataset's own empirical (φ,κ) cloud. **ElaadNL done (2026-06-27)** — unassigned 76%→0%. **ACN still pending** — weights stale vs the corrected cohort mix after the 2026-06 UTC→Pacific fix. | validation | MODEL_SELECTION, CALIBRATION_NOTES, S0 |
| W9 | Revisit parametric family choice (TruncNorm/Weibull/Beta) — several marginal fits are poor. | family | CALIBRATION_NOTES |
| W10 | Tighten `F_SHARE_TOL` from 0.20 back toward the spec 0.05 as larger-fleet scenarios land. | validation | DESIGN_NOTES |
| W11 | Battery **dispatch** model (charge/discharge schedule + SoC timeseries) — v1 ships specs only. Plus optional per-sample PV/battery sizing jitter (node names `pv_realization`/`battery_realization` reserved, off in v1). | der | DESIGN_NOTES #32 |

---

## Deferred

Consciously postponed, with the gating condition.

| ID | Item | Gate | Source/Ref |
|---|---|---|---|
| F1 | NHTS-anchored δ calibration (region re-anchor). | consent_default region match improving past 2/5 regions | CALIBRATION_NOTES, AUDIT_REPORT |
| F2 | Held-out KS validation (train/test split or bootstrap); `ks_fit_quality` is currently training-set only and S2 emits a placeholder warning. | — | CALIBRATION_NOTES, AUDIT_REPORT |
| F3 | S3 holdout currently evaluates a single TruncNorm (not the shipped mixture) — broaden once held-out KS lands. | F2 | MODEL_SELECTION, CALIBRATION_NOTES |
| F4 | AMY weather support for DR sweeps (D37); ASHRAE climate-zone prototype-variant switch is a one-line `PROTOTYPE_MAP` change. | — | DESIGN_NOTES |
| F5 | D5 energy-reachability may still fail at max `arrival_time_jitter`; H2 fails under `price_jitter` — both accepted as legitimate noise-contract skips, no fix. | — (documented boundary) | DESIGN_NOTES, EDGE_CASE_REPORT |
| F6 | Full Stage-2 knob-audit re-run for the Dirichlet/`region_distributions` knobs (skipped in favor of the test suite; `occasional_visitor` deep-channel leaves pass only via counter-flip tolerance). | — | CALIBRATION_NOTES, KNOB_AUDIT_S2 |

---

## Blocked — external data / access

| ID | Item | Area | Source/Ref |
|---|---|---|---|
| ~~K1~~ | **DONE (2026-06-28):** EV WATTS now calibrated on the real public release (13.9M sessions → 1.36M workplace / 3,652 ports via `tools/ingest_evwatts.py`). See ✔6. | evwatts | CALIBRATION_NOTES |
| K2 | INL is fixture-only (~65 synthetic sessions) — confirm columns vs avt.inl.gov Phase 1 & bump `SCHEMA_VERSION`; session CSV not public (`INL_BULK_URL` hook, needs direct INL contact). | inl | CALIBRATION_NOTES |
| K3 | Arrival SoC is unobservable — no charger records SoC, so no model comparison is possible (honest Beta(4,6) prior, not a fit). | soc | GENERATIVE_MODELS |
| K4 | DR per-event reduction magnitudes use a flat Uniform prior — no published per-event reduction targets available. | dr | GENERATIVE_MODELS |
| K5 | Source residential / transit-fleet populations from additional datasets to replace synthetic stand-ins. | calibration | CALIBRATION_NOTES |
| W11 | DR magnitude re-bound (post-freeze): CBP → peak-relative Uniform(0.13,0.39)×peak (or abs (15,235)); BIP add `magnitude ≤ 0.85×peak`, invalid <118 kW peak; ELRP stylized re-bound (5,150). Grounding + citations: docs/experiments/dr_magnitude_grounding.md (2026-07-08). Deferred to avoid breaking corpus regeneration before KDD freeze. | dr | dr_magnitude_grounding |
| W12 | DR timing fixes (post-freeze): BIP notification 30 min (tariff) vs our 2 h; BIP caps 10 ev/mo & 120 h/yr vs our 4/mo; `_tod_factor` zeroes ≥20:00 so the 8–9 p.m. window of all real PY2023 ELRP events is unreachable; S_dr_elrp.yaml mislabels ELRP as an FPL program. | dr | dr_magnitude_grounding |

---

## Decisions Log (forward-looking)

New, dated decisions go here; the **historical numbered decision log lives in
`docs/DESIGN_NOTES.md`** (cited by section number from source code).

| Date | Decision | Ref |
|---|---|---|
| 2026-06-26 | Consolidated docs to 5 hand-written files (README + DESIGN_NOTES + CALIBRATION_NOTES + GENERATIVE_MODELS + this tracker); auto-generated docs kept in place; point-in-time reports moved to `docs/archive/`. | this file |
| 2026-06-26 | `tools/validate_calibration.py` now emits `docs/CALIBRATION_RESULTS.md` (faithfulness S1–S6 summary) as a committed auto-generated doc; bulky CSVs/PNGs stay git-ignored. | validate_calibration.py |
| 2026-06-27 | Added the S0 region-assignment diagnostic, then re-anchored the ElaadNL grid on its own (φ,κ) cloud (judge-panel of 4 candidate grids). Confirms the datasets are modeled independently — ElaadNL's grid no longer borrows ACN's assumptions. | populations.yaml · S0 |
| 2026-06-27 | Added per-building PV + battery (DER). PV is a separate weather-consistent PVWatts curve (not netted into power_kw); battery is specs-only (no dispatch); both default-off to keep the bitwise contract. Future work: battery dispatch model; optional per-sample PV/battery sizing jitter (node names reserved). | DESIGN_NOTES #32 |
| 2026-06-29 | **Reverted** a briefly-merged `battery_dispatch.csv` generator output. Rationale: battery dispatch is a downstream control *decision* (endogenous to the V2B optimization), not exogenous data the platform should emit — PV generation belongs (weather→output, exogenous), battery dispatch does not. `battery.csv` ships specs only (cf. `cars.csv`). W11 stands but is reframed: a dispatch, if offered, belongs in `bench/` as a baseline, not a dataset CSV. | KDD_READINESS #7 |

---

## Done

Closed items kept for provenance.

| ID | Item | Source/Ref |
|---|---|---|
| ✔1 | C4 forward-shift jitter bound, D6 arrival_soc clamp to required−0.1, D5 post-jitter truncation (`_enforce_d5_post_jitter`) + manifest stats — all landed in `noise.py`. | EDGE_CASE_REPORT (V2-followup) |
| ✔2 | E5 hybrid enforcement (warning + manifest + `--strict-e5`, `e5_metrics.py`) landed. | EDGE_CASE_REPORT, DESIGN_NOTES #30 |
| ✔3 | Arrival/dwell/departure-SoC fit issues from the README known-issues list addressed (mixture-aware fits, clamp-artifact and over-pile-at-100% corrections). | README (FIXED items) |
| ✔4 | ElaadNL region grid re-anchored on its own (φ,κ) cloud (4-box tiling: occasional_consistent / weekly_consistent / regular_commuter + erratic catch-all). Unassigned 76%→0%, 293→1231 drivers fit, near-even thirds; S1 KS 0.11–0.17, S2 ρ-gap ≤0.03. | S0, validate_calibration |
| ✔6 | EV WATTS upgraded from fixture-only to **real-data calibrated**: ingested the public release (session⋈evse, venue=Business Office) via `tools/ingest_evwatts.py` → 1.36M workplace sessions / 3,356 users; `evwatts_workplace_public` fits 5/5 regions, unassigned 0.4% (no re-anchor needed). Registered in the validation harness. INL remains fixture-only. | tools/ingest_evwatts.py, populations.yaml |
| ✔5 | Per-building rooftop/carport PV + stationary battery (DER). PVWatts curve from the same perturbed EPW as building load (`pv_generation.csv`), PV + battery specs (`pv.csv`/`battery.csv`), `pv.*`/`battery.*` knobs (default off), CLI + web + multi-building, `der_catalog` presets. 15 new tests; 534 pass. | der_catalog, pv_model, DESIGN_NOTES #32, GENERATIVE_MODELS |
| ✔7 | **O4:** `GENERATIVE_MODELS.md` `depart_soc_mu` default inconsistency (summary table 85 vs prose 50) — already reconciled in the doc (both the L54 summary table and the L209 prose say **50**); tracker entry was stale, closed 2026-07-08. | GENERATIVE_MODELS L54/L209 |
