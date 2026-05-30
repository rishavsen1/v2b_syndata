# Paper Plan — KDD 2026/2027 D&B Submission

Living document. Updated as plan changes.

## Target
- **Venue:** KDD 2027 Datasets & Benchmarks track, July cycle
- **Deadline:** ~July 31 2026 (confirm when CFP drops on `kdd2027.kdd.org`)
- **Format:** ACM `sigconf` template, double-blind, 8 content pages + unlimited refs/appendix
- **Submission system:** OpenReview
- **Fallbacks:** NeurIPS D&B (Dec 2026), ICDM 2027

## Title (working)
"v2b_syndata: A Configurable, Reproducibly-Seeded Synthetic Dataset Generator for Vehicle-to-Building Research"

## Headline claim
> v2b_syndata provides a controlled, reproducible substrate for V2B research, calibrated to 4 real-world data sources spanning US and EU geographies. Generated CSVs integrate with standard charging-network simulators (e.g., ACN-Sim) and produce meaningfully different aggregate outcomes across scenarios.

## Honest scope claim
> We model physical-slot scarcity via FCFS admission; electrical-service constraints are configurable but the published bench uses feeder=1.0. Algorithm-comparison benchmarking is downstream work.

## Headline contributions (§1)
1. Configurable, parametric V2B dataset generator covering 6 factors (building, users, cars, chargers, prices, DR) at the marginal level
2. Unified 4-source `CalibrationSource` protocol (ACN-Data, EV WATTS, INL EVP-1, ElaadNL) — US + EU geography
3. Bitwise reproducibility (D53), audited knob surface (98 knobs, Stage 1+2), manifest-level provenance
4. Demonstrated integration with ACN-Sim's standard scheduling pipeline (7 stock algorithms run unmodified)

## Section structure (locked in `OUTLINE.md`)

| § | Section | Pages | Eval axis |
|---|---|---|---|
| 1 | Introduction & Contributions | 1.00 | Impact |
| 2 | Related Work & Positioning | 0.50 | Impact |
| 3 | Generator Design & Architecture | 1.50 | Quality & Docs |
| 4 | Calibration: Unified 4-Source Protocol | 1.25 | Impact + Ethics |
| 5 | Scenario Library | 0.75 | Impact |
| 6 | Reproducibility & Verification | 1.00 | Quality & Docs |
| 7 | Demonstration: Bench Through Standard Pipeline | 1.00 | Impact |
| 8 | Accessibility, Ethics & Limits | 0.50 | Accessibility + Ethics |
| 9 | Conclusion & Roadmap | 0.50 | — |
| **Total** | | **8.00** | |

## Figures (6 main, rest appendix)
1. **Fig 01** — positioning diagram (synthetic-vs-real, controllability axis)
2. **Fig 07** — Bayes-net DAG (tier 0/1/1.5/2/3)
3. **Fig 11** — 4-source calibration provenance flow
4. **Fig 12** — scenario library treemap (41 scenarios × axes)
5. **Fig 14** — paper_bench results (peak_kw + target_miss × scenario × algo)
6. **Fig 15** — verification pipeline diagram (validators, audit, manifest)

## Tables
- §2: 23-row comparison table vs related artifacts (from `RELATED_WORK.md`)
- §3: Knob surface summary (count by bucket, source priority chain)
- §4: 4 calibration sources × {user_id_strategy, geography, vintage, n_sessions, license}
- §7: paper_bench results (7 scenarios × 7 algos × 3 metrics)

## Appendices (unlimited)
- A. Full Datasheet (`DATASHEET.md` rendered)
- B. Reproducibility statement + how-to-rerun-paper-bench
- C. Knob reference (auto-generated from `docs/KNOB_REFERENCE.md`)
- D. Validate spec (D-class invariants enumerated)
- E. Sensitivity sweep results (the feeder × slot × algo data we do NOT claim in the main paper)
- F. Per-source calibration stats (n_users / n_sessions / capacity_fallback rate / region coverage)
- G. CONSENT model details (negotiation clusters, weights)
- H. EnergyPlus integration notes (PNNL prototype quirks, occupancy injection)

## Timeline (~7 weeks remaining)

| Phase | Task | Effort |
|---|---|---|
| W5 polish | #11 Ethics writeup | half day |
| W5 polish | #12 Repro/accessibility polish | half day |
| W5 verification | **Calibration faithfulness verification** (see §below) | 1–2 days |
| W6 draft v1 | §1 Intro | 0.5 day |
| W6 draft v1 | §2 Related | 0.25 day |
| W6 draft v1 | §3 Design | 1 day |
| W6 draft v1 | §4 Calibration | 0.5 day |
| W6 draft v1 | §5 Scenario library | 0.25 day |
| W7 draft v1 | §6 Reproducibility | 0.5 day |
| W7 draft v1 | §7 Bench demo | 0.5 day |
| W7 draft v1 | §8 Ethics & limits | 0.25 day |
| W7 draft v1 | §9 Conclusion | 0.25 day |
| W7 review | #14 Internal review + revise | 1–2 days |
| W8 submit | #15 Anonymize repo + OpenReview submit | 0.5 day |

**Total: ~10–14 working days. Calendar: ~7 weeks. Comfortable margin.**

## Submission-blocking author decisions (TODO)
- License (Apache-2.0 / MIT / BSD-3?)
- IRB / ethics-board statement
- Funding acknowledgment
- Anonymized GitHub URL placeholder
- Author list + affiliations
- Archive deposit (Zenodo? GitHub Release? both?)

All flagged in `DATASHEET.md` with 13 `[TODO at submission time]` markers.

## Risks

| Risk | Mitigation |
|---|---|
| KDD 2027 CFP timing | Watch site; fallback to NeurIPS D&B (Dec) or ICDM 2027 |
| Page overrun on §3 (Design) | Per-tier detail to appendix; main keeps diagram + paragraph each |
| Reviewer asks for adacharge MPC | Cite as future work; show repo hook (`feeder_kw_ratio`) exists |
| Companion paper IP overlap | Bench section independent; companion not cited as motivation |
| **Calibration faithfulness challenged** | See verification plan below; ship empirical KS + Wasserstein numbers in §4 |

## Calibration verification plan

Open task — to be done in W5 before paper drafting starts. See `paper/CALIBRATION_VERIFICATION.md` (to be created).
