# KDD 2027 D&B — Submission Plan (Cycle-1 sprint)

> Concrete steps from today's repo state to a good Cycle-1 submission.
> Companion docs: `KDD_PAPER_STRUCTURE.md` (what the paper says),
> `KDD_READINESS.md` (long-lived tracker; statuses there are authoritative).
> Created 2026-07-07; **rev 2 (2026-07-08)** after adversarial verification
> and CFP confirmation.


## Status 2026-07-11 (D4)

All experimental workstreams COMPLETE, ahead of the D10 freeze:
- WS-A ✅ (CIs + family-matched S3; honest medians 0.064/0.069) · WS-B ✅
  (PV +1.27%) · WS-C ✅ (matched ElaadNL + split-claim framing) · WS-D ✅
  (grounding memo) · WS-E ✅ (all 5) · WS-F ✅ (repro driver; PAPER_NUMBERS
  deterministic) · citations ✅ (4 passes, zero unverified) · adversarial
  review ✅ (all 20 fixes applied).
- NEW post-review experiments (2026-07-11): V2B dispatch LP (29.4% peak
  shave; 0 relaxations; ACN-Sim cross-check) and TSTR scale/duration study
  (shape parity at every scale; raw gap mostly fleet scale; residual =
  activity rate). Both wired into repro_paper.py + PAPER_NUMBERS.
- Paper: full draft, mathematized (§3/§4/§5/§6), review-corrected, compiles;
  repo URL inserted. Remaining \owed: Zenodo DOI, final SHA.
- OPEN (user): OpenReview profiles + abstract ≤ Jul 18; Zenodo DOI ≤ Jul 24;
  author block; PDF read-through. OPEN (assistant): full-run determinism
  re-verification; final consistency sweep; page-boundary decision deferred
  by user ("don't worry about page limits right now").

## The real calendar (CFP verified 2026-07-08)

| Date | Day | Milestone |
|---|---|---|
| Jul 8 | D1 | sprint start |
| Jul 17 | D10 | **evidence freeze** — all experimental numbers final |
| Jul 18 | D11 | OpenReview abstract + title + authors registered (buffer day) |
| **Jul 19** | D12 | **CFP abstract deadline (AoE)** |
| Jul 21–22 | D14–15 | full draft complete (user's 2-week horizon) |
| Jul 24 | D17 | frozen PDF: 8 content pages + refs + appendix; links in PDF |
| **Jul 26** | D19 | **CFP full-paper deadline (AoE)** |

Format: 8 content pages at submission + unlimited appendix; single-blind
(no anonymization work); OpenReview; hyperlinks cannot be added after
submission — artifact links must appear in the submitted PDF.

## Ground rules

- **Evidence freeze D10.** After Jul 17, numbers change only via the
  reproducibility pipeline (WS-F), never by hand.
- **Gates, not slips:** a failed workstream gate becomes a written scope
  statement/limitation — it does not move the calendar.
- Every change lands on `main` behind green `uv run pytest` (662 tests) and,
  where generator behavior could shift, the determinism suite.

## Workstreams

### WS-H — CFP compliance (NEW; hard external gates)
- D1: create OpenReview profiles for **all** authors (CFP requirement);
  confirm cycle-1 venue page.
- D11: register abstract + title + author list (one day ahead of Jul 19).
- D17: page-format check (8 content pp), links-in-PDF audit, submission
  dry-run.
- **Gate:** abstract registered ≤ Jul 18; PDF passes format check.

### WS-A ∥ — Bootstrap CIs + held-out protocol repair
*(KDD_READINESS #11; held-out KS already ships as S3, median Δ = 0.012.)*
- D1–3: add seeded bootstrap (B ≥ 1000 over source sessions) to
  `tools/validate_calibration.py` for KS and W₁ per region×variable; CI
  columns into `CALIBRATION_RESULTS.md` + machine-readable CSV for Tab 2.
- **Protocol repair (verifier G1 / tracker F3):** current S3 holdout refits a
  *single TruncNorm*, not the shipped GMM-k mixture — a protocol/model
  mismatch a reviewer will catch. Broaden S3 to refit the shipped family on
  the training split; if not landed by D8, the Tab 2 caption carries the
  caveat verbatim and §5.2 discloses the dwell holdout outliers
  (+0.19/+0.28/+0.29).
- **Gate:** CIs bit-reproduce across two runs; Tab 2 fills for ACN + ElaadNL;
  S3 either broadened or caveated.

### WS-B ∥ — PV validation vs NREL reference
*(KDD_READINESS #8.)*
- D1–4: `tools/validate_pv.py`: identical inputs (tilt 10°, azimuth 180°,
  dc 100 kW, derate 0.86) into `pv_model.pv_ac_series` and the NREL reference —
  **prefer local pysam/SAM fed with our exact TMYx EPW** (apples-to-apples);
  PVWatts v8 API (DEMO_KEY) as cross-check with the NSRDB-weather delta
  attributed. Report annual error (<5% target), monthly profile, hourly
  CV(RMSE)/NMBE.
- **Gate:** documented error table by D8; >5% unresolved → limitation text.

### WS-C ∥ — ElaadNL TSTR: correct the adverse artifact (starts D1)
*(Re-baselined: `data/tstr/results_elaadnl.json` already exists and is
adverse — lagged 7.61×/6.31× — but was run against the mismatched scenario
`S_acn_caltech` (91 synthetic sessions vs a 481 kW-peak real site). No
dependency on WS-A — `tstr_forecasting.py` already supports `--real elaadnl`.)*
- D1: reproduce the artifact; diagnose the scenario-pairing bug in the harness
  invocation; re-run with the matched `S_elaadnl_public_eu`.
- D2–5: full corrected runs (lagged + calendar probes); add shape-normalized
  transfer metric; draft the magnitude paragraph.
- Decision D5: if corrected transfer ≈ parity → Tab 4 row + abstract keeps a
  two-dataset utility claim; if still adverse → **cross-cohort shift study**
  framing (documented, honest), parity claim scoped to ACN.
- **Gate:** a committed, matched-scenario ElaadNL result (either sign) + the
  framing text; the stale mismatched artifact clearly superseded.

### WS-D ∥ — DR magnitude grounding (or explicit stylization)
*(KDD_READINESS #10.)*
- D3–7: search published CAISO/PG&E CBP/BIP/ELRP program data for
  commitment/curtailment magnitudes; if found, re-bound
  `dr_magnitude_kw_range` defaults per program with citations; else write the
  "stylized prior" caveat for §5.4/§8.
- **Gate:** grounded-with-citations or caveated — no third state. (Risk: null
  search → caveat path is pre-approved, not a failure.)

### WS-E — Hygiene fixes (batched, D4–8)
1. **O4 is already fixed in `GENERATIVE_MODELS.md`** (verified: both locations
   say 50) — close the stale tracker entry only.
2. **O1 SIGSEGV** (mixed_use_v1 × hot climates): 1-day reproduction cap; not
   fixable → remove/annotate affected shipped combos + known-issue note.
3. **`verify_sweep.py`** reads `row["n_sessions"]` absent from
   `MetricsResult` — repair; run `bench` + sweep end-to-end once (V1G scope).
4. **`DATA_LICENSE.md`**: remove stale `battery_dispatch` mention (reverted
   feature).
5. **Batch-manifest weather recording**: `batch_manifest.json` records only the
   batch-level `--weather-profile` ("none") while per-building profiles do the
   work — record per-building effective weather profiles so the corpus
   manifest is self-describing (this misled our own verifier; it will mislead
   reviewers).
6. **Commit the working set** — untracked files (campus configs, showcase
   HTMLs, analyzers, KDD docs) **and the modified `CLAUDE.md`**.
- **Gate:** clean `git status`; pytest green; sweep runs end-to-end.

### WS-F — Reproducibility pass + release-metadata refresh (D8–10)
*(KDD_READINESS #13 + verifier G4/G5. Runs after WS-E's commit-clean so SHAs
are stable.)*
- One driver (`tools/repro_paper.py`): calibrate → validate_calibration (CIs)
  → validate_buildingload → tstr_forecasting → model_eval →
  `docs/experiments/PAPER_NUMBERS.md` (with git SHA + compute statement).
- **Must regenerate with committed primary sources:** the GMM-k ablation
  (0.148→0.073 currently exists only in planning docs) and
  `CALIBRATION_RESULTS.md` including the EV WATTS cohort (current file
  predates its calibration).
- **Refresh `docs/DATASHEET.md` + `croissant.json`** to describe the released
  artifact (campus corpus, restored caches).
- **Zenodo dry-run** for the 19 GB corpus (upload mechanics, DOI reservation,
  authorship metadata) — owned here, not just in DoD.
- **Gate:** two consecutive driver runs → identical `PAPER_NUMBERS.md`; paper
  cites only numbers present there; DOI reserved.

### WS-G — The paper (D1–17, interleaved)
- D1–2: `paper/` scaffold (acmart sigconf), section stubs from
  `KDD_PAPER_STRUCTURE.md`, notation macros, bib skeleton.
- D3–8: §§2–4 prose (stable content, not blocked by freeze); appendix
  skeletons.
- D9–10: figures (Fig 1–5 per inventory; matplotlib re-renders of deck
  canvases for Figs 2–3).
- D11–14: §§5–7 from `PAPER_NUMBERS.md`; §8–9; abstract last; full draft by
  D14–15 (unconstrained length; appendix absorbs overflow).
- D15–17: 8-page trim of main text (pre-agreed cut order: §2, §3.6, §3.4
  detail → appendix); register pass (academic, plain, no colloquialisms, no
  inflation); links-in-PDF audit; internal review-agent pass.
- **Gate:** compiles; every number traces to `PAPER_NUMBERS.md`; structure
  doc's claims→evidence table fully checked.

## Day-by-day (consistent with workstream text)

| Day (date) | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| 1–2 (7/8–9) | CIs impl | PV harness | artifact diagnosis + rerun | — | — | — | scaffold | profiles |
| 3–4 (7/10–11) | CIs land | PV results | corrected runs | search | O4/O1 | — | §3–4 | — |
| 5–7 (7/12–14) | F3 broaden | buffer | framing decision (D5) | close | sweep/licenses/manifest | — | §2 + appendix | — |
| 8 (7/15) | caveat fallback | done | done | done | commit-clean | — | figures | — |
| 9–10 (7/16–17) | — | — | — | — | — | repro driver + regen + Zenodo | figures | — |
| 11 (7/18) | — | — | — | — | — | freeze check | §5–7 | **abstract reg** |
| 12–14 (7/19–21) | — | — | — | — | — | — | §5–9 + abstract | abstract due 7/19 |
| 15–17 (7/22–24) | — | — | — | — | — | — | trim + edit + PDF | format audit |
| 18–19 (7/25–26) | — | — | — | — | — | — | buffer | **submit 7/26** |

## Risks & mitigations

1. **ElaadNL corrected TSTR still adverse** → pre-approved shift-study framing
   (WS-C gate); a negative-but-explained transfer on a shifted cohort is
   publishable evidence.
2. **PVWatts weather mismatch muddies the comparison** → pysam-with-our-EPW is
   the primary; API only as cross-check.
3. **Bootstrap CIs weaken an ablation claim** → report the CI; soften the
   claim. Truth over headline.
4. **O1 rabbit-hole** → 1-day cap, then scenario removal.
5. **WS-F regeneration contradicts a planning-doc number** (e.g., 0.148→0.073)
   → the regenerated number wins everywhere; planning docs updated.
6. **DR null search** → stylized-prior caveat path (pre-approved).
7. **Page overflow** → appendix absorbs; pre-agreed §2/§3.6 cuts.
8. **19 GB Zenodo mechanics** → dry-run scheduled D9–10, not submission week.

## Definition of done

- [ ] WS gates passed or converted to written limitations.
- [ ] `PAPER_NUMBERS.md` regenerated at final SHA; paper matches it.
- [ ] Abstract registered ≤ Jul 18; paper submitted ≤ Jul 26 AoE.
- [ ] 8 content pages; links in PDF; compiles clean.
- [ ] Datasheet/Croissant/licenses refreshed and referenced.
- [ ] Zenodo DOI reserved; corpus deposit plan tested.
- [ ] `KDD_READINESS.md` + `PROJECT_TRACKER.md` statuses synced (incl. O4
  closure).
