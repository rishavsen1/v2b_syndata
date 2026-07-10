# Related-Work Citation Research — deep-research report

> Generated 2026-07-08 by the `deep-research` workflow (5 search angles, 26
> sources fetched, 101 claims extracted, 25 verified under 3-vote adversarial
> checking, 10 findings after synthesis). Purpose: find + verify citations for
> the KDD paper's Related Work (`paper/sections/02_related.tex`). This file is
> the verbatim research record; the paper's `references.bib` and §2 are updated
> from the VERIFIED entries below. **Integrity rule: only VERIFIED entries were
> added to the paper; UNCERTAIN/NOT-COVERED items stay as visible `\owed{}`
> markers, never fabricated.**

## Question

Find and verify authoritative citations for a Related Work section on synthetic
Vehicle-to-Building (V2B) / EV-charging + building-energy dataset generation:
(gap 1) V2G/smart-charging optimization surveys; (gap 2) statistical
EV-charging/EV-load models; (gap 3) deep generative models for synthetic
energy/EV data; plus verification of ~16 existing candidate citations.

## Executive summary

Verified authoritative citations for all three gap categories and the two
charging references surfaced (ACN-Data, ACN-Sim). **Gap 1 (V2G optimization
survey) is effectively UNRESOLVED** — the only candidate examined was refuted
as a too-new preprint; a peer-reviewed highly-cited survey must still be
sourced. **Gap 2** delivered two solid peer-reviewed primaries (Xydas 2016;
Quirós-Tortós 2015) plus a 2025 survey preprint. **Gap 3** delivered several
domain-specific options, best anchored by the peer-reviewed DiffCharge (IEEE
TSG 2024) and Wang & Hong GAN (Energy & Buildings 2020), with an especially
on-topic PV+EV cGAN (Li/Dong/Qiu 2025). ~14 of the "existing citations to
verify" (ElaadNL, EV WATTS, INL, EnergyPlus, PNNL prototypes, PVWatts,
ComStock, BDG2, TimeGAN, CSDI, RCGAN, ASHRAE G14, Datasheets, Croissant) were
NOT covered by the returned verification claims and need a follow-up pass.

Run stats: 5 angles · 26 sources fetched · 101 claims extracted · 25 verified ·
24 confirmed / 1 killed · 10 findings after synthesis · 108 agent calls.

---

## Verified findings

### Gap 1 — V2G/smart-charging optimization survey → UNRESOLVED
- **REFUTED candidate (vote 1–2):** Wang et al., *Resource-Oriented
  Optimization of Electric Vehicle Systems…*, arXiv:2509.04533 (2025-09-04,
  eess.SY). Rejected as a Related-Work anchor: un-peer-reviewed Sept-2025
  preprint, no journal-ref, cannot be "canonical/highly-cited."
  Sources: https://arxiv.org/abs/2509.04533
- **Action:** source a peer-reviewed, highly-cited V2G/smart-charging survey
  (e.g., in *Renewable & Sustainable Energy Reviews*, *Applied Energy*, or an
  IEEE transactions/magazine). Not delivered by this pass → remains `\owed`.

### Gap 2 — Statistical EV-charging/EV-load modeling → VERIFIED
1. **[VERIFIED, high, 3–0]** Xydas, Marmaras, Cipcigan, Jenkins, Carroll,
   Barker (2016). *A data-driven approach for characterising the charging
   demand of electric vehicles: A UK case study.* Applied Energy 162:763–771.
   DOI 10.1016/j.apenergy.2015.10.151. Key: `xydas2016datadriven`.
   *Provides:* two-step data-driven framework on 21,918 real charging events
   from 255 UK stations to characterise EV charging demand.
   Sources: https://www.sciencedirect.com/science/article/pii/S0306261915013938
   · https://ideas.repec.org/a/eee/appene/v162y2016icp763-771.html
2. **[VERIFIED core, high, 3–0; pages/month UNCERTAIN]** Quirós-Tortós, Ochoa,
   Lees (2015). *A Statistical Analysis of EV Charging Behavior in the UK.*
   IEEE PES ISGT Latin America 2015. DOI 10.1109/ISGT-LA.2015.7381196.
   Key: `quirostortos2015statistical`. (Page range pp. 445–449 and month
   unconfirmed — IEEE Xplore fetch bot-blocked.)
   *Provides:* fits empirical PDFs (connections/day, start time, initial/final
   SOC), weekday/weekend split, from 221 real UK Nissan LEAF users over a year.
   Sources: https://ieeexplore.ieee.org/document/7381196/ ·
   https://www.semanticscholar.org/paper/72ca3b0843820d47983568c201d8b2d4141a15be
3. **[VERIFIED metadata, high; suitability 2–1 — PREPRINT]** Lin, Prabowo,
   Razzak, Xue, Amos, Behrens, Salim (2025). *Electric Vehicle Charging Load
   Modeling: A Survey, Trends, Challenges and Opportunities.* arXiv:2511.03741.
   Key: `lin2025evloadsurvey`. Optional supplementary survey; cite as arXiv.
   Source: https://arxiv.org/abs/2511.03741

### Gap 3 — Deep generative models for synthetic energy/EV data → VERIFIED
4. **[VERIFIED, high, 3–0 — PRIMARY pick]** Li, Xiong, Chen (2024).
   *DiffCharge: Generating EV Charging Scenarios via a Denoising Diffusion
   Model.* IEEE Transactions on Smart Grid; arXiv:2308.09857; IEEE Xplore doc
   10418170. Key: `li2024diffcharge`.
   *Provides:* DDPM generating realistic battery- and station-level EV charging
   time series; code at github.com/LSY-Cython/DiffCharge. Best domain-specific,
   peer-reviewed answer to gap 3.
   Sources: https://arxiv.org/abs/2308.09857 ·
   https://ieeexplore.ieee.org/abstract/document/10418170
5. **[VERIFIED, high, 3–0 — foundational GAN]** Wang & Hong (2020).
   *Generating realistic building electrical load profiles through the
   Generative Adversarial Network (GAN).* Energy and Buildings 224:110299.
   DOI 10.1016/j.enbuild.2020.110299 (LBNL). Key: `wang2020generating`.
   *Provides:* normalize→k-means→per-cluster GAN pipeline, validated on the
   Building Data Genome Project (KL divergence < 0.3 for most parameters).
   Sources: https://doi.org/10.1016/j.enbuild.2020.110299 ·
   https://www.osti.gov/pages/biblio/1784288
6. **[VERIFIED, high, 3–0 — most on-topic for V2B]** Li, Dong, Qiu (2025).
   *Conditional generative adversarial network (cGAN) for generating building
   load profiles with photovoltaics and electric vehicles.* Energy and
   Buildings 335:115584. DOI 10.1016/j.enbuild.2025.115584. Key: `li2025cgan`.
   *Provides:* cGAN conditioned on PV/EV/weather generating building load
   profiles preserving statistics across seasons and DER statuses; validated on
   110 southwest-US households (mean/std, KL, FID).
   Source: https://www.sciencedirect.com/science/article/abs/pii/S0378778825003147
7. **[VERIFIED alternatives, high, 3–0 each]** — mostly preprints:
   - ERGAN — Liang, Wang, Wang (2024). *Synthetic Data Generation for
     Residential Load Patterns via Recurrent GAN and Ensemble Method.*
     arXiv:2410.15379. Key: `liang2024ergan`. (Later appeared in IEEE TIM;
     that version unverified here.)
   - CENTS — Fuest, Cuesta-Infante, Veeramachaneni (2025). *CENTS: Generating
     synthetic electricity consumption time series for rare and unseen
     scenarios.* arXiv:2501.14426. Key: `fuest2025cents`.
   - Li, Ma, Menendez, Chen, Zhong (2026). *Synthetic data generation for joint
     electric vehicle driving and charging events via deep generative
     networks.* Transportation Research Part C, art. 105481.
     DOI 10.1016/j.trc.2025.105481. Key: `li2026syntheticEVjoint`.
     (Peer-reviewed; Transformer+GMM+Gibbs on 3,777 Shanghai BEVs.)
   Sources: https://arxiv.org/abs/2410.15379 · https://arxiv.org/abs/2501.14426
   · https://www.sciencedirect.com/science/article/abs/pii/S0968090X25004851

### Existing citations — verified this pass
8. **[VERIFIED, high, 3–0]** ACN-Data — Lee, Li, Low (2019). *ACN-Data:
   Analysis and Applications of an Open EV Charging Dataset.* Proc. Tenth ACM
   Int. Conf. on Future Energy Systems (e-Energy '19), Phoenix AZ, pp. 139–149.
   DOI 10.1145/3307772.3328313. Key: `lee2019acndata`.
   *Note:* uses GMMs → also serves as a gap-2 statistical-modeling reference.
   Sources: https://dl.acm.org/doi/10.1145/3307772.3328313 ·
   https://par.nsf.gov/biblio/10200593
9. **[VERIFIED + CORRECTION, high, 3–0]** ACN-Sim — Lee, Sharma, Johansson,
   Low (2021). *ACN-Sim: An Open-Source Simulator for Data-Driven Electric
   Vehicle Charging Research.* IEEE Trans. Smart Grid 12(6):5113–5123, Nov
   2021. DOI 10.1109/TSG.2021.3103156; arXiv:2012.02809. Key: `lee2021acnsim`.
   *Correction:* four named authors (not "Lee et al.").
   Sources: https://api.crossref.org/works/10.1109/TSG.2021.3103156 ·
   https://arxiv.org/abs/2012.02809

---

## Refuted (killed) claims
- Wang et al. arXiv:2509.04533 as a gap-1 survey anchor — vote 1–2, killed.
  Source: https://arxiv.org/html/2509.04533v1

## Caveats
- **Preprint risk:** DiffCharge (peer-reviewed, IEEE TSG 2024) is the safest
  gap-3 anchor. ERGAN, CENTS, and the Lin et al. survey are un-peer-reviewed
  preprints → cite as arXiv.
- **Coverage gap:** this pass did NOT return verification for ElaadNL/4TU,
  EV WATTS, INL "Plugged In", EnergyPlus (Crawley 2001), DOE/PNNL prototypes
  (Thornton et al.), PVWatts (NREL/TP-6A20-62641), ComStock, BDG2 (Miller
  2020), TimeGAN (Yoon 2019), CSDI (Tashiro 2021), RGAN/RCGAN (Esteban 2017),
  ASHRAE G14, Datasheets (Gebru 2021), Croissant (Akhtar). These remain to be
  verified in a follow-up round (several surfaced as sources below, so partial
  evidence exists — see Sources).
- Quirós-Tortós page range/month uncertain. Li et al. 2026 methodology rests on
  abstract (ScienceDirect paywalled).

## Open questions (follow-up needed)
1. Canonical peer-reviewed, highly-cited V2G/smart-charging optimization survey
   for gap 1 (none verified).
2. Exact metadata + DOIs for the ~14 uncovered existing citations.
3. Quirós-Tortós exact pages/month (IEEE fetch was blocked).
4. Gap-3 editorial choice: single exemplar (DiffCharge) vs a GAN+diffusion+cGAN
   cluster; whether to include preprint-only works.

## Follow-up leads surfaced as sources (not yet verified as citations)
These URLs appeared during search and likely anchor the uncovered items — a
second pass should verify each before use:
- EnergyPlus (Crawley 2001): https://doi.org/10.1016/S0378-7788(00)00114-6
- PVWatts v5 (Dobos): https://docs.nrel.gov/docs/fy14osti/62641.pdf *(fetch flagged unreliable)*
- PNNL prototype buildings: https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-20405.pdf
- BDG2 (Miller 2020, Scientific Data): https://www.nature.com/articles/s41597-020-00712-x
- TimeGAN (Yoon 2019, NeurIPS): https://papers.nips.cc/paper/2019/hash/c9efe5f26cd17ba6216bbe2a7d26d490-Abstract.html
- Datasheets (Gebru, CACM): https://cacm.acm.org/research/datasheets-for-datasets/
- EV WATTS (OSTI): https://www.osti.gov/biblio/1970735 · https://www.osti.gov/biblio/1967948

## All sources fetched (26)

| Angle | URL | Quality |
|---|---|---|
| gap1 survey | https://www.sciencedirect.com/science/article/abs/pii/S0378775305000352 | secondary |
| gap1 survey | https://ideas.repec.org/a/eee/rensus/v38y2014icp717-731.html | secondary |
| gap1 survey | https://arxiv.org/html/2509.04533v1 | primary (refuted) |
| gap1 survey | https://www.mdpi.com/2032-6653/14/1/25/htm | secondary |
| gap1 survey | https://www.sciencedirect.com/science/article/abs/pii/S004579062400329X | secondary |
| gap2 stat | https://www.sciencedirect.com/science/article/pii/S0306261915013938 | primary |
| gap2 stat | https://www.semanticscholar.org/paper/72ca3b0843820d47983568c201d8b2d4141a15be | primary |
| gap2 stat | https://arxiv.org/abs/2511.03741 | primary |
| gap3 gen | https://arxiv.org/abs/2308.09857 | primary |
| gap3 gen | https://www.sciencedirect.com/science/article/abs/pii/S0378778825003147 | primary |
| gap3 gen | https://www.sciencedirect.com/science/article/abs/pii/S0968090X25004851 | primary |
| gap3 gen | https://arxiv.org/html/2410.15379v1 | primary |
| gap3 gen | https://arxiv.org/pdf/2501.14426 | primary |
| gap3 gen | https://www.researchgate.net/publication/342751793 | primary |
| dataset verify | https://dl.acm.org/doi/10.1145/3307772.3328313 | primary |
| dataset verify | https://authors.library.caltech.edu/records/s94ac-pr864 | primary |
| dataset verify | https://www.osti.gov/biblio/1970735 | primary |
| dataset verify | https://www.osti.gov/biblio/1369632 | primary |
| dataset verify | https://www.nature.com/articles/s41597-020-00712-x | primary |
| dataset verify | https://www.osti.gov/biblio/1967948 | primary |
| sim/std/doc verify | https://doi.org/10.1016/S0378-7788(00)00114-6 | primary |
| sim/std/doc verify | https://docs.nrel.gov/docs/fy14osti/62641.pdf | unreliable |
| sim/std/doc verify | https://papers.nips.cc/paper/2019/hash/c9efe5f26cd17ba6216bbe2a7d26d490-Abstract.html | primary |
| sim/std/doc verify | https://cacm.acm.org/research/datasheets-for-datasets/ | primary |
| sim/std/doc verify | https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-20405.pdf | primary |
| sim/std/doc verify | https://www.sciencedirect.com/science/article/abs/pii/S0378775314020370 | primary |

---

## BibTeX-ready — VERIFIED additions (folded into `references.bib`)

```bibtex
@article{xydas2016datadriven,
  author  = {Xydas, Erotokritos and Marmaras, Charalampos and Cipcigan, Liana M. and Jenkins, Nick and Carroll, Steve and Barker, Myles},
  title   = {A data-driven approach for characterising the charging demand of electric vehicles: A {UK} case study},
  journal = {Applied Energy}, volume = {162}, pages = {763--771}, year = {2016},
  doi     = {10.1016/j.apenergy.2015.10.151}}

@inproceedings{quirostortos2015statistical,
  author    = {Quir{\'o}s-Tort{\'o}s, Jairo and Ochoa, Luis F. and Lees, Becky},
  title     = {A Statistical Analysis of {EV} Charging Behavior in the {UK}},
  booktitle = {2015 IEEE PES Innovative Smart Grid Technologies Latin America (ISGT LATAM)},
  year      = {2015}, doi = {10.1109/ISGT-LA.2015.7381196},
  note      = {pages/month unconfirmed}}

@misc{lin2025evloadsurvey,
  author = {Lin, Xin and Prabowo, Arian and Razzak, Imran and Xue, Hao and Amos, Matthew and Behrens, Sam and Salim, Flora D.},
  title  = {Electric Vehicle Charging Load Modeling: A Survey, Trends, Challenges and Opportunities},
  year   = {2025}, eprint = {2511.03741}, archivePrefix = {arXiv}, primaryClass = {eess.SY}}

@article{li2024diffcharge,
  author  = {Li, Siyang and Xiong, Hui and Chen, Yize},
  title   = {{DiffCharge}: Generating {EV} Charging Scenarios via a Denoising Diffusion Model},
  journal = {IEEE Transactions on Smart Grid}, year = {2024},
  doi     = {10.1109/TSG.2024.3357197}, note = {arXiv:2308.09857; verify vol/issue/pages}}

@article{wang2020generating,
  author  = {Wang, Zhe and Hong, Tianzhen},
  title   = {Generating realistic building electrical load profiles through the {Generative Adversarial Network} ({GAN})},
  journal = {Energy and Buildings}, volume = {224}, pages = {110299}, year = {2020},
  doi     = {10.1016/j.enbuild.2020.110299}}

@article{li2025cgan,
  author  = {Li, Yuewei and Dong, Bing and Qiu, Yueming (Lucy)},
  title   = {Conditional generative adversarial network ({cGAN}) for generating building load profiles with photovoltaics and electric vehicles},
  journal = {Energy and Buildings}, volume = {335}, pages = {115584}, year = {2025},
  doi     = {10.1016/j.enbuild.2025.115584}}

@article{li2026syntheticEVjoint,
  author  = {Li, ... and Ma, ... and Menendez, M{\'o}nica and Chen, ... and Zhong, ...},
  title   = {Synthetic data generation for joint electric vehicle driving and charging events via deep generative networks},
  journal = {Transportation Research Part C: Emerging Technologies}, year = {2026},
  doi     = {10.1016/j.trc.2025.105481}, note = {author list to complete; art. 105481}}

@misc{liang2024ergan,
  author = {Liang, Xinyu and Wang, Ziheng and Wang, Hao},
  title  = {Synthetic Data Generation for Residential Load Patterns via Recurrent {GAN} and Ensemble Method},
  year   = {2024}, eprint = {2410.15379}, archivePrefix = {arXiv}}

@misc{fuest2025cents,
  author = {Fuest, ... and Cuesta-Infante, Alfredo and Veeramachaneni, Kalyan},
  title  = {{CENTS}: Generating synthetic electricity consumption time series for rare and unseen scenarios},
  year   = {2025}, eprint = {2501.14426}, archivePrefix = {arXiv}, note = {author list to complete}}
```

## Status ledger

| Item | Status | Cited in §2? |
|---|---|---|
| Gap 1 V2G survey | UNRESOLVED | `\owed` (kept) |
| Gap 2 Xydas 2016 | VERIFIED | yes |
| Gap 2 Quirós-Tortós 2015 | VERIFIED (pages uncertain) | yes |
| Gap 2 Lin 2025 survey | VERIFIED (preprint) | optional |
| Gap 3 DiffCharge 2024 | VERIFIED | yes (primary) |
| Gap 3 Wang & Hong 2020 | VERIFIED | yes |
| Gap 3 Li/Dong/Qiu cGAN 2025 | VERIFIED | yes (V2B-specific) |
| Gap 3 ERGAN/CENTS/Li 2026 | VERIFIED | optional |
| ACN-Data | VERIFIED (key corrected) | yes |
| ACN-Sim | VERIFIED (authors corrected) | yes |
| ElaadNL, EV WATTS, INL, EnergyPlus, PNNL, PVWatts, ComStock, BDG2, TimeGAN, CSDI, RCGAN, ASHRAE G14, Datasheets, Croissant | NOT COVERED this pass | leads listed above; follow-up needed |

---

# Pass 2 (2026-07-09) — Gap-1 survey + existing-citation verification

> Run `wf_c26bce62-427`: 5 angles · 26 sources · 124 claims extracted · 25
> reached verification · **18 confirmed (3–0) · 7 killed** · synthesis + the
> remaining verification votes **failed on the session usage limit** (resets
> 7pm America/Chicago) — JOB 2 items below marked accordingly. Resume with
> `Workflow({scriptPath: ".../deep-research-wf_c26bce62-427.js", resumeFromRunId: "wf_c26bce62-427"})`
> — completed agents return cached.

## JOB 1 — V2G/smart-charging survey: RESOLVED (over-delivered)

Four peer-reviewed anchors verified 3–0 via Crossref/Semantic Scholar:

1. **García-Villalobos, Zamora, San Martín, Asensio, Aperribay (2014).**
   *Plug-in electric vehicles in electric distribution networks: A review of
   smart charging approaches.* RSER 38:717–731. DOI 10.1016/j.rser.2014.07.040.
   442 (Crossref) / 483 (S2) citations; publicationTypes: Review.
   → **cited in §2** as `garciavillalobos2014smartcharging`.
2. **Tan, Ramachandaramurthy, Yong (2016).** *Integration of electric vehicles
   in smart grid: A review on vehicle to grid technologies and optimization
   techniques.* RSER 53:720–732 (Jan 2016). DOI 10.1016/j.rser.2015.09.012.
   **798 citations** (Crossref). → **cited in §2** as `tan2016v2g` (covers the
   V2G-optimization half of the sentence).
3. Yilmaz & Krein (2013). *Review of the Impact of Vehicle-to-Grid
   Technologies on Distribution Systems and Utility Interfaces.* IEEE TPEL
   28(12):5673–5689. DOI 10.1109/TPEL.2012.2227500. ⚠ Do **not** conflate with
   their other 2013 review (charger topologies, 28(5):2151–2169,
   DOI 10.1109/TPEL.2012.2212917) — both verified, distinct papers.
4. Dahiwale, Rather, Mitra (2024). *A Comprehensive Review of Smart Charging
   Strategies for Electric Vehicles and Way Forward.* IEEE T-ITS
   25(9):10462–10482. DOI 10.1109/TITS.2024.3365581 (note: DOI suffix 3365581,
   not the Xplore article number). Scope caveat (vote 0–0, unresolved): its
   abstract does not explicitly cover V2G/PV co-optimization — reserve as an
   optional "recent survey" citation.
5. Sadeghian, Oshnoei, Mohammadi-ivatloo, Vahidinasab, Anvari-Moghaddam
   (2022). *A comprehensive review on electric vehicles smart charging…*
   J. Energy Storage 54:105241. DOI 10.1016/j.est.2022.105241. Metadata
   verified 3–0; its "highly-cited" claim vote **failed on limit** — usable
   as a metadata-verified alternative.

## JOB 2 — 14 existing citations: INCOMPLETE (usage limit)

Verification votes for the EV WATTS OSTI/DOI claims (incl. a candidate DOI
`10.15483/…`), the "exact bibliographic locators" batch (EnergyPlus, PNNL
prototypes, PVWatts, ComStock, BDG2, TimeGAN, CSDI, RCGAN, G14, Datasheets,
Croissant, ElaadNL/4TU, INL), and synthesis all failed with "session limit."
**Status: still TODO-verify in references.bib.** Resume the run (cached
prefix) after the limit resets to finish these.

## Refuted / unresolved votes this pass
- Dahiwale scope-match claim and its V2G-coverage caveat: vote 0–0 (verifiers
  died on limit) — recorded, not counted as confirmed.

## Bib/paper changes made from this pass
- Added `garciavillalobos2014smartcharging`, `tan2016v2g` to references.bib.
- §2's last `\owed{cite}` (V2G/smart-charging surveys) resolved with the pair.
- Remaining unverified: the 14 JOB-2 entries (still carry `TODO verify` notes).
