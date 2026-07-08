# DR magnitude grounding — WS-D (KDD_READINESS #10)

**Date:** 2026-07-08 · **Workstream:** WS-D of `docs/KDD_SUBMISSION_PLAN.md`
**Question:** are the per-event `magnitude_kw ~ Uniform(dr_magnitude_kw_range)`
defaults in `src/v2b_syndata/samplers/dr_sampler.py` (`PROGRAM_SPECS`:
CBP (50, 200), BIP (100, 500), ELRP (50, 300) kW) defensible against published
per-participant commitment/curtailment data for the three California programs,
given our commercial buildings' 100–600 kW design peaks?

**Semantics being grounded:** `dr_events.csv:magnitude_kw` is the per-event
requested/committed curtailment for a *single site* (one building = one service
account). The right comparators are therefore per-service-account nominations
and per-customer load impacts, **not** program-level MW.

**No configs were changed by this workstream** — recommendations only.

## Verdict summary

| Program | Verdict | Current default | Recommended default | Basis |
|---|---|---|---|---|
| CBP | **GROUNDED** (at the level of per-account means and %-of-load; Uniform shape remains a modeling choice) | (50, 200) | **(15, 235)** — or, better, `Uniform(0.13, 0.39) × building peak kW` | PY2022 statewide evaluation: per-customer impacts 12.8–58.9 kW = 13–39 % of reference load; per-account nominations 11–70 kW |
| BIP | **GROUNDED** (tariff bounds; typical real participants are larger than our buildings — scope caveat required) | (100, 500) | **keep (100, 500)**, now citable; add constraint `magnitude ≤ 0.85 × building peak` and note buildings < ~118 kW peak are ineligible | E-BIP tariff: minimum load reduction 100 kW, FSL ≤ 85 % of max demand; observed per-account drops ~0.9–1.6 MW |
| ELRP | **STYLIZED** (participation thresholds grounded; per-site magnitude distribution is not public and delivered A.1 impacts are ~0–1 kW/site, statistically insignificant) | (50, 300) | keep a stylized range but re-bound to **(5, 150)** = [above the 1 kW eligibility floor, ≤ ~25 % of mid-band peak]; carry the §5.4/§8 caveat verbatim | ELRP T&C: A.1 minimum 1 kW nomination; PY2023 evaluations: A.1 per-site reductions 0.6–1.1 kW (PG&E) / −1.2 kW (SCE), none significant |

---

## 1. CBP — Capacity Bidding Program (PG&E / SCE / SDG&E)

### Evidence

| # | Number | Meaning | Source |
|---|---|---|---|
| C1 | **100 kW minimum per aggregation**, not per account: "An Aggregator must submit aggregations of customers that include 100 kW or more of load curtailment for each unique combination of: Product / Sub-LAP … Due to the CAISO requirement that a PDR resource consist of 100 kW or greater, if a nomination is less than 100 kW, the nomination(s) will not be eligible for bidding." | The oft-quoted 100 kW floor applies to the *aggregated* PDR resource. There is **no per-account kW minimum** in E-CBP; single accounts of any size participate through aggregators. | PG&E Schedule E-CBP, Sheet (Cal. P.U.C. 58059-E rev.), Advice 7262-E / D.23-06-029, effective 2024-06-08 [1] |
| C2 | Capacity Nomination "cannot be greater than the sum of max demand of the nominated SAs"; Elect product 1–4 h duration; season May–Oct (PG&E, SDG&E). | Upper bound on any account's implied nomination is its own max demand. | PG&E Schedule E-CBP [1] |
| C3 | PY2022 average summer nominations: PG&E Non-Res DA **698 accounts / 48.7 MW** (≈ 70 kW/acct); SCE DA 143 / 1.6 MW (≈ 11 kW/acct); SCE DO 146 / 2.7 MW (≈ 18 kW/acct); SDG&E DO 79 / 2.1 MW (≈ 27 kW/acct). | Mean per-account nominated capacity across all four active non-residential IOU×product cells: **≈ 11–70 kW**. | AEG 2023, Table ES-1 [2] |
| C4 | PY2022 average summer event day, per-customer (reporting hour): PG&E DA reference load **150.9 kW**, impact **58.9 kW (39 %)**; SCE DA 78.8 kW ref, 12.8 kW (16 %); SCE DO 142.2 kW ref, 19.1 kW (13 %); SDG&E DO 167.1 kW ref, 22.0 kW (13 %). | Delivered per-customer curtailment: **≈ 13–59 kW**, i.e. **13–39 % of reference load**, for accounts whose average event-hour loads (79–167 kW) sit at the bottom of our 100–600 kW design-peak band. | AEG 2023, Table ES-2 [2] |
| C5 | PY2019 average PG&E DA event: 241 accounts, 9.2 MW nominated / 9.8 MW delivered (≈ 38–41 kW/acct). | Same order of magnitude two program-years earlier; the per-account scale is stable. | AEG 2020 DRMEC workshop deck [3] |

### Assessment vs current default (50, 200)

Our default's mass sits **above** observed per-account behavior: the observed
per-account nominated/delivered range across IOUs and years is ~11–70 kW
(means), and per-customer percentage impacts are 13–39 % of load. For a 100 kW-peak
building, `Uniform(50, 200)` routinely requests more than the building's
entire event-hour load; for a 600 kW building the ceiling of 200 kW ≈ 33 % of
peak is plausible but the 50 kW floor (8 %) is low-ish. The empirically
defensible parameterization is *fractional*.

### Recommendation

- **Preferred (model change, post-freeze):** sample `magnitude_kw =
  Uniform(0.13, 0.39) × building_design_peak_kw` — the PY2022 per-customer
  %-impact band [2] — and clip to ≥ 5 kW. This scales correctly across our
  100–600 kW building range and is what the citation actually supports.
- **Minimal change (knob default only):** `CBP: (15.0, 235.0)` =
  [0.13 × 100 kW, 0.39 × 600 kW]. Justification: end-to-end image of the
  observed percentage band over our design-peak band.
- **Honesty bounds for the paper:** the public evaluations report *means* per
  IOU×product, not per-account distributions (account-level data are
  confidential). The claim we can make is "per-event magnitudes are bounded by
  the observed range of per-account means and per-customer percentage impacts
  from the statewide CBP evaluations"; the Uniform shape itself stays a
  modeling choice.

**Verdict: GROUNDED** (adopt re-bounded range with citations [1, 2, 3]).

---

## 2. BIP — Base Interruptible Program (PG&E E-BIP)

### Evidence

| # | Number | Meaning | Source |
|---|---|---|---|
| B1 | "the FSL must be no more than 85 percent of each customer's highest monthly maximum demand … over the past 12 months **with a minimum load reduction of 100 kW**." (stated for both legacy and new C&I/Ag TOU rates) | Per-account committed curtailment is **≥ 100 kW** and **≥ 15 % of max demand** — the documented minimum the task asked to verify. **Confirmed.** | PG&E Schedule E-BIP (Cal. P.U.C. 45773-E rev.) [4] |
| B2 | Eligibility: "must have at least 100 kilowatt (kW) or higher maximum demand during the summer on-peak or winter partial-peak for at least one month over the previous 12 months." | Only buildings with ≥ 100 kW max demand can enroll at all; combined with B1, a feasible participant needs peak ≥ 100/0.85 ≈ **118 kW**. | PG&E Schedule E-BIP [4] |
| B3 | PG&E event 2008-08-28: aggregate drop ≈ **210 MW**, an **83 % drop** vs 252 MW reference, across a program of ~149 service accounts (Jan 2009 enrollment) → ≈ **1.4 MW/account**. SCE event 2006: 555 accounts, ≈ **518 MW** average drop → ≈ **0.93 MW/account**. | Real BIP participants are predominantly manufacturing/industrial at the ~1 MW scale — *larger than any building in our 100–600 kW population*. | Freeman, Sullivan & Co. 2009, statewide BIP evaluation [5] |
| B4 | ELRP sub-group A.1-BIP (BIP customers), PY2023: SCE 22 sites, significant event 2023-07-20 delivered **984 kW/site** (25.9 % reduction); PG&E 13 sites with 20.9 MW aggregate enrolled load → ≈ 1.6 MW/site. | Independent, recent confirmation of the ~1 MW per-site scale of BIP participants. | DSA 2024 (SCE) Table 3-5 [7]; DSA 2024 (PG&E) Table 1-1 [8] |

### Assessment vs current default (100, 500)

The (100, 500) range turns out to be *defensible after the fact*: the 100 kW
floor is exactly the tariff minimum load reduction [4], and 500 kW ≈ 0.85 × 600 kW
is the FSL-implied ceiling for the largest building in our population. What the
data adds is a **scope caveat**: typical real BIP accounts curtail ~1 MW [5, 7, 8],
so our buildings sit at the *small tail* of the actual BIP population, and the
Uniform over [100, 500] should be understood as "tariff-feasible commitments
for a 100–600 kW-peak building," not as the empirical BIP fleet distribution.

### Recommendation

- **Keep `BIP: (100.0, 500.0)`**, now citable to [4] (floor) and the FSL rule
  (ceiling).
- Add (post-freeze) a per-scenario consistency rule: `magnitude_kw ≤ 0.85 ×
  building_design_peak_kw`, and treat `dr_program: BIP` as invalid for
  buildings with design peak < 118 kW (B1+B2). Today nothing stops a 100 kW-peak
  scenario from sampling a 500 kW BIP event.
- Paper text: state that BIP magnitudes are **tariff-derived bounds** (minimum
  reduction and FSL cap) rather than fitted to the observed BIP fleet, whose
  members are typically ~1 MW industrial accounts [5].

**Verdict: GROUNDED** (tariff-derived bounds with citations [4, 5, 7, 8]; keep
range, add feasibility constraint + scope sentence).

---

## 3. ELRP — Emergency Load Reduction Program

### Evidence

| # | Number | Meaning | Source |
|---|---|---|---|
| E1 | A.1 (non-residential direct enrollment): "Customer's service account must be able to reduce load by a **minimum of one kilowatt** during an ELRP event"; customers "must nominate … an estimated target load reduction quantity." | The direct-participation threshold is only **1 kW** — there is no 50 kW (or any material) floor. Our (50, 300) floor has no basis in the program rules. | PG&E ELRP Group A Terms & Conditions (2026-02-15), §1.1.1 [6]; program adopted by CPUC D.21-03-056 [9] |
| E2 | A.2 (non-residential aggregators): "The aggregated resource capacity meets or exceeds **500 kW** for non-BIP aggregators." | 500 kW is a *portfolio* threshold, not per-site. | PG&E ELRP Group A T&C §1.1.2 [6] |
| E3 | Program parameters: May–Oct, 4–9 p.m., 1 h min / 5 h max per event (A.1–A.3), **60 h annual dispatch limit**, compensation **$2/kWh** delivered, no penalties. | Pay-for-performance with no penalty → broad, shallow enrollment; nominations are non-binding. | PG&E ELRP Group A T&C §2 & §3 [6] |
| E4 | PY2023 PG&E A.1: **10,474 sites**, 614 MW enrolled load (≈ 59 kW average site load); per-site event reductions **0.60 / −0.38 / 1.08 kW** — none statistically significant. | The *delivered* per-site curtailment for non-BIP ELRP sites is ~1 kW, ~1 % of load; the typical enrolled site is *smaller* than our smallest building. | DSA 2024 (PG&E), Tables 1-1 & 3-4 [8] |
| E5 | PY2023 SCE A.1: 2,861 sites; average site −0.90 to −1.18 kW (negative = load *increase*), not significant. | Same picture at the second IOU. | DSA 2024 (SCE), Table 3-4 [7] |
| E6 | Per-site *nominated* quantities: redacted/confidential in all public evaluation versions; no public distribution exists. | We cannot fit or bound a per-site nomination distribution from public data. | [7, 8] (public redacted versions) |

### Assessment vs current default (50, 300)

Not supportable. The only hard public numbers are a **1 kW** eligibility floor
[6] and delivered per-site averages of **~0–1 kW** that are statistically
indistinguishable from zero [7, 8]. Nominated (as opposed to delivered)
per-site targets are exactly what `magnitude_kw` models, and those are not
public. Between "delivered ≈ 1 kW" and "nominations unknown," any specific
range we pick for a 100–600 kW building is a stylization. We should not launder
E4/E5 into a fitted range — they measure *response*, under events that were
mostly called with little or no advance notice, not *commitment*.

### Recommendation

- Treat `magnitude_kw` under ELRP explicitly as the **nominated target load
  reduction** (the T&C's term), which the program neither verifies nor
  penalizes.
- If a default must exist, use **(5.0, 150.0)**: above the 1 kW eligibility
  floor with margin, capped at ~25 % of the mid-band (600 kW × 0.25) so it
  never exceeds curtailment shares observed in *any* California C&I program
  (CBP's 13–39 %). Label it stylized in `PROGRAM_SPECS`' docstring and the
  manifest.
- Carry the caveat below in the paper.

**Verdict: STYLIZED** (thresholds grounded; the magnitude distribution is not).

### Caveat paragraph for §5.4 / §8 (verbatim)

> ELRP event *timing* parameters (season, event window, duration, annual
> dispatch limit) follow the published program terms, but the per-site
> curtailment magnitude is a stylized prior. ELRP's direct-enrollment
> threshold is only 1 kW and nominations are non-binding and unverified;
> per-site nominated quantities are redacted from all public load-impact
> evaluations, and the delivered per-site reductions those evaluations do
> report for non-BIP participants average roughly 0–1 kW and are statistically
> indistinguishable from zero. We therefore sample ELRP magnitudes from a
> uniform range chosen to be plausible for a committed 100–600 kW-peak
> commercial site, and flag it as a modeling assumption rather than a
> calibrated quantity; users studying ELRP-specific response should replace
> this prior with program data of their own.

---

## 4. Side findings (out of WS-D scope; log to tracker, do not change configs now)

1. **BIP notification lead**: `PROGRAM_SPECS`/D67 use 2 h; the E-BIP tariff's
   options are **30-minute** (Option A, all enrolled customers as of the 2009
   evaluation) and 4 h (Option B); the current fact sheet is 30 min [4, 5].
2. **BIP event caps**: tariff allows up to 1×4 h event/day, **10 events/month,
   120 h/year** [5]; sampler caps at 4/month.
3. **ELRP event window**: program is 4–9 p.m. [6] and PY2023 events ran
   **8–9 p.m.** [7, 8], but `_tod_factor` zeroes hours ≥ 20:00 — the sampler
   cannot produce the most common real ELRP event window.
4. **ELRP season cap**: sampler uses 10 events/season; actual limit is **60
   dispatch hours/year** [6] (≈ 12×5 h events) — close, but hours-based.
5. `S_dr_elrp.yaml` describes "FPL ELRP" (Miami); ELRP is a California (CPUC)
   program — the scenario description should say the program *rules* are
   Californian even when the weather/location descriptor is not.

## 5. BibTeX

```bibtex
@misc{pge2024ecbp,
  author       = {{Pacific Gas and Electric Company}},
  title        = {Electric Schedule {E-CBP}: Capacity Bidding Program},
  year         = {2024},
  howpublished = {California Public Utilities Commission tariff book, Advice 7262-E, Decision 23-06-029, effective June 8, 2024},
  url          = {https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-CBP.pdf}
}

@techreport{aeg2023cbp,
  author      = {{Applied Energy Group}},
  title       = {2022 Statewide Load Impact Evaluation of California Capacity Bidding Programs: Ex-Post and Ex-Ante Load Impacts},
  institution = {Prepared for PG\&E, SCE, SDG\&E and the Demand Response Measurement \& Evaluation Committee},
  year        = {2023},
  month       = apr,
  number      = {CALMAC ID PGE0481},
  url         = {https://www.calmac.org/publications/5._Statewide_2022_CBP_Rpt_PUBLICES.pdf}
}

@misc{aeg2020cbpworkshop,
  author       = {Nguyen, Abigail},
  title        = {Statewide Load Impact Evaluation of California Capacity Bidding Programs},
  year         = {2020},
  howpublished = {Applied Energy Group presentation, 2020 DRMEC Load Impact Workshop, May 1, 2020},
  url          = {https://www.cpuc.ca.gov/-/media/cpuc-website/files/legacyfiles/2/6442464897-2020-iou-lip-workshop-day-1-statewide-cbp-prez.pdf}
}

@misc{pge2023ebip,
  author       = {{Pacific Gas and Electric Company}},
  title        = {Electric Schedule {E-BIP}: Base Interruptible Program},
  year         = {2023},
  howpublished = {California Public Utilities Commission tariff book},
  url          = {https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-BIP.pdf}
}

@techreport{fsc2009bip,
  author      = {George, Stephen S. and Bode, Josh and Schellenberg, Josh},
  title       = {Load Impact Evaluation of California's Statewide Base Interruptible Program},
  institution = {Freeman, Sullivan \& Co., prepared for PG\&E, SCE, and SDG\&E},
  year        = {2009},
  month       = may,
  number      = {CALMAC ID SCE0266.01},
  url         = {http://www.calmac.org/publications/BIP_Statewide_Load_Impact_Report_-_Final_Non-Redlined_Version.pdf}
}

@misc{pge2026elrptc,
  author       = {{Pacific Gas and Electric Company}},
  title        = {Emergency Load Reduction Program ({ELRP}) Pilot: Group {A} Terms and Conditions},
  year         = {2026},
  month        = feb,
  howpublished = {Pursuant to CPUC Decisions 21-03-056, 21-06-027, 21-12-015, and 23-12-005},
  url          = {https://elrp.olivineinc.com/_files/pge/elrp/PGE-ELRP-Group-A-Terms-and-Conditions.pdf}
}

@techreport{dsa2024elrpsce,
  author      = {Lemarchand, Alana and Bode, Josh and Horner, Savannah and Walkington, John},
  title       = {2023 Load Impact Evaluation for Southern California Edison's Emergency Load Reduction Pilot},
  institution = {Demand Side Analytics, LLC, prepared for SCE},
  year        = {2024},
  month       = apr,
  number      = {CALMAC ID SCE0484},
  url         = {https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/demand-response/emergency-load-reduction-program/elrp-2023-ex-post-data/py2023_sce_elrp_load_impact_report_final_public.pdf}
}

@techreport{dsa2024elrppge,
  author      = {Lemarchand, Alana and Bode, Josh and Horner, Savannah and Walkington, John},
  title       = {2023 Load Impact Evaluation for Pacific Gas \& Electric's Emergency Load Reduction Pilot},
  institution = {Demand Side Analytics, LLC, prepared for PG\&E},
  year        = {2024},
  month       = apr,
  number      = {CALMAC ID PGE0497},
  url         = {https://www.calmac.org/publications/8._PGE_2023_ELRP_Rpt_PUBLIC.pdf}
}

@misc{cpuc2021d2103056,
  author       = {{California Public Utilities Commission}},
  title        = {Decision 21-03-056: Decision Directing {PG\&E}, {SCE}, and {SDG\&E} to Take Actions to Prepare for Potential Extreme Weather in the Summers of 2021 and 2022 (adopting the Emergency Load Reduction Program pilot)},
  year         = {2021},
  month        = mar,
  howpublished = {Rulemaking 20-11-003, issued March 25, 2021. Program page: California Public Utilities Commission, ``Emergency Load Reduction Program (ELRP)''},
  url          = {https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/electric-costs/demand-response-dr/emergency-load-reduction-program}
}
```

Reference key used in the tables above: [1] pge2024ecbp · [2] aeg2023cbp ·
[3] aeg2020cbpworkshop · [4] pge2023ebip · [5] fsc2009bip · [6] pge2026elrptc ·
[7] dsa2024elrpsce · [8] dsa2024elrppge · [9] cpuc2021d2103056.

## 6. Provenance notes (verification honesty)

- All tariff/T&C quotes were extracted from the primary PDFs (downloaded
  2026-07-08) with `pdftotext`, not from search-result summaries. One
  intermediate web-fetch summary of [6] hallucinated a "$0.50/kWh, 100 kW
  minimum" — the actual document says **$2/kWh** and **1 kW**; numbers here
  come from the raw text.
- For [9], the direct docs.cpuc.ca.gov PDF ID for D.21-03-056 could not be
  resolved programmatically (the docket UI is JavaScript-gated), so the
  citation points to the CPUC's stable ELRP program page, which names the
  decision and its issuance date (March 25, 2021, R.20-11-003). Every other
  URL in §5 was fetched and parsed during this workstream.
- Public evaluation reports redact account-level data; all per-account figures
  above are means (aggregate ÷ account count) or per-customer table values as
  published. No distributional (variance/percentile) grounding is possible
  from public sources for any of the three programs.
