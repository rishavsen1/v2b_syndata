# Related Work and Positioning

This document positions `v2b_syndata` against the existing landscape of
Vehicle-to-Building (V2B), electric-vehicle (EV) charging, and building-load
datasets and simulators. The goal is honest comparison, not promotion: we
list where `v2b_syndata` calibrates *from*, where it *integrates with*,
where it *uniquely covers* the V2B factor space, and where it *does not*.

The framing throughout: a V2B study spans six entangled factors —
**building load**, **users**, **vehicles**, **charging equipment**,
**electricity prices**, and **demand-response events**. No existing public
artifact spans all six with calibrated marginals, a knob-audited control
surface, and bitwise reproducibility. `v2b_syndata` fills that combinatorial
gap; it does not claim to replace any individual real dataset on its own axis.

---

## 1. Summary Comparison Table

Legend for **V2B coverage** column (six factors):
B = building load · U = users · V = vehicles · C = chargers ·
P = prices/tariffs · D = DR events.

Legend for **Type**: REAL = empirical measurements;
SYN = synthetic generator; HYB = hybrid (real data feeding a synthesizer);
SIM = control-loop / dynamic simulator (not primarily a dataset).

| Name (cite) | Type | V2B coverage | Calibration to real data | Configurability | License | Year, geography | Status |
|---|---|---|---|---|---|---|---|
| **`v2b_syndata` (this work)** | SYN (HYB at the marginal level) | B U V C P D (all 6) | ACN-Data, EV WATTS, INL EVP-1, ElaadNL for sessions; EnergyPlus + ASHRAE 90.1 prototypes + TMYx for building load; CAISO CBP/BIP rules for DR | 98 audited knobs; 4 user-facing descriptors; per-scenario YAML + seed | Apache-2.0 / MIT [verify] | 2026, US + EU calibration | Active |
| ACN-Data (Lee et al. 2019) | REAL | U V C (sessions only) | n/a (primary measurement) | None (fixed traces) | CC BY 4.0 | 2018–2021, Caltech / JPL / Office001 (US workplace) | Active, public |
| ACN-Sim (Lee et al. 2018, 2021) | SIM | C (algorithm sandbox) over ACN-Data sessions | Replays ACN-Data | Replaces optimizer/policy; events fixed by trace | BSD-3 | 2018–, Caltech | Active |
| EV WATTS (DOE / EPRI, livewire.energy.gov) | REAL | U V C (sessions; port-level, no driver ID) | n/a (primary measurement) | None | Public, US-Gov | 2020–, US multi-site | Active, periodic releases |
| INL EV Project Phase 1 (Idaho National Lab, avt.inl.gov) | REAL | U V C (sessions; vehicle-keyed) | n/a (primary measurement) | None | Public, US-Gov | 2011–2013, US residential (Leaf, Volt) | Archive, no new data |
| EV Project Phase 2 (INL aggregate) | REAL (aggregate) | aggregate U V C | n/a | None | Public, US-Gov | 2013–2018, US multi-site | Archive |
| ElaadNL Open Charging Transactions (open-data.elaad.io) | REAL | U V C (per-card sessions, public + DCFC) | n/a (primary measurement) | None | CC BY 4.0 | 2020 release, NL/EU | Active, periodic releases |
| ChargeCar (CMU, chargecar.org) | REAL (trip + sometimes session) | V (driving) U (commute) | n/a | None | Open, academic | 2008–2013 [verify], Pittsburgh | Archive, mostly inactive |
| Pecan Street Dataport | REAL | B (residential) U (limited) V (residential EV charging panel, some homes) | n/a | None | Paid academic license | 2011–, Austin / California | Active, paywalled |
| OpenEI EV datasets (NREL OpenEI portal) | REAL (collection of dumps) | varies per dataset | n/a | None | Mostly public-domain | varies | Active catalog |
| NREL EV Detailed Data (Fleet DNA / Live Charging) | REAL | V C (fleet duty cycles + charging) | n/a | None | Public, US-Gov | 2010s–, US fleets | Active |
| Caltech Adaptive Charging Network (deployment) | REAL (deployment) | C V U (sessions feed ACN-Data) | n/a | Live system; not a dataset per se | n/a | 2016–, Caltech | Active deployment |
| ACN-Portal / ACN-Sim suite (Lee et al. 2021) | SIM | C (charging optimization simulator) | Replays ACN-Data; can synthesize sessions | Algorithm + minimal event params; not full V2B factor sweep | BSD-3 | 2018–, US | Active |
| CityLearn (Vazquez-Canteli et al. 2020; Nweye et al. 2023) | SIM | B P D (limited) — district-level energy + storage RL benchmark | Building data from real prototypes; EV not core | RL environment, scenario YAMLs | MIT | 2020–, US (prototypes) | Active |
| OCHRE (NREL, Maguire & Roberts 2022) | SIM | B (residential) + EV charging coupling | Calibrated against AMI traces internally [verify] | Per-dwelling configurator | BSD-3 | 2022–, US residential | Active |
| EVI-Pro Lite (NREL, Wood et al. 2017) | SYN (web tool) | U V C (load profiles) | NHTS + NREL ChargePoint anonymized data | Web-form sliders: city, fleet size, charger mix | Public, US-Gov | 2017–, US | Active web tool |
| EVI-Pro (full, NREL) | SYN (offline) | U V C | NHTS travel + various session datasets | Internal config; not openly distributed | Restricted | 2017–, US | Restricted access |
| gym-electric-motor (Balakrishna et al. 2019/2021) | SIM | V (motor / drivetrain) | Physics models, not session data | RL gym API | MIT | 2019–, generic | Active |
| pymgrid (Henri et al. 2020) | SIM | B P D (microgrid; EV optional) | Synthetic + Pecan Street feeds | YAML microgrid configurator | LGPL-3 | 2020–, generic | Active (sparsely) |
| SimBench (Meinecke et al. 2020) | SYN | grid topology + P D (distribution grids) | German DSO data | Scenario library, no fine EV control | ODbL 1.0 | 2019–, DE | Active |
| EVeREST (EVerest, LF Energy) | SIM | C (OCPP-compliant charger sim) | Protocol-level, not session-level | Protocol stacks, hardware-in-loop | Apache-2.0 | 2021–, generic | Active |
| DOE Commercial Reference Buildings | REAL/SYN (canonical archetypes) | B only | Anchored to ASHRAE / DOE survey data | EnergyPlus IDF parameters | Public-domain | 2011–, US | Active |
| ASHRAE 90.1 Prototype Building Models | SYN (canonical archetypes) | B only | Code-compliance archetypes | Climate zone × archetype | Public, ANSI | updated periodically, US | Active (we use these directly via EnergyPlus 23.2) |
| TMYx weather files (climate.onebuilding.org) | REAL | B only (climate driver) | Synthesized "typical year" from real station data | Per-location station selection | Public-domain | continuous, global | Active |

---

## 2. Real EV-session datasets — what `v2b_syndata` calibrates *from*

The four real-empirical session datasets `v2b_syndata` calibrates against —
ACN-Data, EV WATTS, INL EVP-1, and ElaadNL — each cover a distinct slice
of the global charging-session space, and none of them on their own spans
the buildings × users × vehicles × chargers × prices × DR factor product
that V2B research requires. `v2b_syndata` does not aggregate their raw
records; instead, the package's `calibration/` module fits parametric
families (TruncNorm / Weibull / Beta arrival-time, dwell, and arrival-SoC,
plus a Gaussian copula on the arrival/dwell joint) per behavioral region
and stamps the provenance into the run manifest under
`knob_resolution[*].source = "calibration:<dataset>_<window>_<date>"`. This
preserves the empirical marginals while permitting controlled variation along
the population descriptor.

**ACN-Data (Lee et al. 2019)** is the gold-standard public workplace-charging
session dataset, drawn from the Caltech Adaptive Charging Network and the
Caltech JPL/Office001 sites. The 2019–2021 window contains roughly 50k
sessions [verify] with persistent userIDs, energy delivered, miles
requested, and an EVSE-level identifier. Its limitation for V2B work is
that it is exclusively workplace L2 charging at one organization: the
behavioral region distribution is overwhelmingly low-frequency
("occasional visitor" / "erratic"), and high-φ residential commuter
populations are essentially absent. `v2b_syndata`'s ACN calibration
re-anchors the region grid on the empirical (φ, κ) joint observed in ACN
itself (see `docs/CALIBRATION_NOTES.md` Section 9–Section 11); region match against the
original hand-authored `consent_default` grid was only ~2%.

**EV WATTS (DOE / EPRI)** publishes multi-site session aggregates via the
DOE Livewire portal. Coverage is broader than ACN (workplace, public,
some DCFC) but per-driver identity is not generally exposed in the bulk
releases; `v2b_syndata`'s `calibration/sources/evwatts.py` synthesizes
`user_id = "evwatts:port:<evse_id>"` and stamps
`calibration_metadata.user_id_strategy = "port_proxy"`, so downstream
consumers know the resulting (φ, κ) is per-port shift-consistency, not
individual-driver consistency. This caveat propagates into the
descriptor `evwatts_workplace_public` and `evwatts_dcfc_public`.

**INL EV Project Phase 1 (Idaho National Lab, 2011–2013)** is the only
public source with true per-vehicle identity at session granularity —
pseudonymized Vehicle IDs like `Veh001` for the original Nissan Leaf
and Chevy Volt fleet on ChargePoint and Blink hardware. `v2b_syndata`'s
INL source synthesizes `user_id = "inl:vin:<vehicle_id>"`. The catch is
that this is a **legacy** fleet — ~24 kWh battery class, ~3.3 kW onboard
charger — so mixing INL-calibrated marginals with modern-fleet scenarios
(60–100 kWh batteries) requires care and is flagged in the descriptor's
metadata. Phase 2 of the EV Project (2013–2018) is published only as
aggregate statistics, which is why we do not calibrate against Phase 2
directly.

**ElaadNL Open Charging Transactions** is the most recent and the only
non-US source on our calibration list — anonymized RFID-card session
records from the Netherlands across public, semi-public, and DCFC venues,
CC BY 4.0. ElaadNL contributes EU coverage (geographic axis) and DCFC
coverage (charging-mode axis). Two notable limitations are documented in
the manifest: (i) longitudinal identity is weaker than INL's `vin_proxy`
because drivers may hold multiple cards and cards transfer between drivers,
so the strategy is stamped `card_proxy`; and (ii) source CSVs ship naive
Europe/Amsterdam timestamps which we localize to UTC without shifting, so
ElaadNL-derived `arrival_hour` distributions are offset by 1–2 h vs.
wall-clock local time. The offset is uniform across the source's marginals,
not a bug, but it is something downstream studies must account for if they
care about local solar-time alignment.

The bottom line for Section 2: real session datasets give us *marginals* for the
session-renderer subgraph (`f_arr`, `f_dwell`, `f_soc`); they do not give
us a B × U × V × C × P × D joint. The job of `v2b_syndata` is to combine
the empirical marginals with controllable joints and the rest of the V2B
factor stack.

---

## 3. Synthetic data generators — what we control vs. what they control

The closest synthetic-data analog in the published landscape is **EVI-Pro
Lite** (Wood et al. 2017, NREL). EVI-Pro takes a city, fleet size, charger
mix, and a few behavioral sliders and produces aggregate load profiles
calibrated against NHTS (National Household Travel Survey) and
NREL-internal ChargePoint data. It is excellent for *aggregate load
forecasting*. It is not a session-level generator: outputs are 15-minute
power curves, not individual session records with arrival, dwell, SoC, and
EVSE assignment, so it cannot feed a charging-controller benchmark.
The full EVI-Pro tool (offline) is not openly distributed; EVI-Pro Lite is
a web form, not a Python package — there is no manifest, no seed, no
reproducibility contract, and no V2B factors beyond U V C.

**ACN-Sim** (Lee et al. 2018, 2021) ships a `acnportal.algorithms` algorithm
sandbox that can synthesize Poisson sessions on demand, but the synthesizer
is a small fragment of the codebase intended for algorithm prototyping,
not for systematic scenario generation: there is no descriptor layer, no
calibrated copula on (arrival, dwell), no building load, no DR program,
and no audit of which knobs monotonically move which outputs.

**SimBench** (Meinecke et al. 2020) is the closest spiritual cousin in the
*power-systems* community: a curated, versioned scenario library for
distribution-grid studies, with documented data provenance and a defined
scenario taxonomy. SimBench covers grid topology + load + (limited)
DER scenarios; EV charging is present but coarse, and the building / user
layer is essentially absent. The right analogy: SimBench is to distribution
networks what `v2b_syndata` aspires to be for the V2B factor product.

The broader synthetic-data literature increasingly emphasizes datasheets
(Gebru et al. 2018, *Datasheets for Datasets*) and machine-readable
metadata (Croissant, MLCommons 2024). `v2b_syndata` ships a per-run
`manifest.json` with seed lineage, knob resolution sources, and SHA-256
hashes per CSV; a Datasheet-for-Datasets style document is on the
roadmap for the KDD D&B submission and is not yet included in the
repository. We do not yet ship Croissant metadata.

Honest comparison: EVI-Pro Lite reaches a broader audience and is
backed by an institution (NREL) with operational longevity that an
academic artifact cannot match. `v2b_syndata`'s niche is *session-level
controllability with calibrated marginals and audited knobs* — a
different point on the trade-off curve, not strictly better.

---

## 4. Charging-network simulators — we integrate, we do not compete

This category is where the language of "competition" is most misleading.
**ACN-Sim** (Lee et al. 2021) and **CityLearn** (Vazquez-Canteli et al.
2020; Nweye et al. 2023) are *control-loop simulators* — they take a
scenario, apply a policy or optimizer at every tick, and report a
performance metric. They are downstream consumers of the kind of scenario
data `v2b_syndata` emits, not substitutes for the generator.

**ACN-Sim** consumes session events (arrivals, energy demand, deadlines)
and a network topology, then runs a charging optimizer (Quick-Charge,
LLF, MPC, RL) under a budget. A natural integration is to feed
`v2b_syndata`-generated `sessions.csv` rows into ACN-Sim as the event
stream, with `chargers.csv` as the network topology and
`building_load.csv` (subtracted from a feeder cap) as the budget. The
`paper_bench/` directory in `v2b_syndata` includes a peak-shaving
demonstration along these lines using a greedy heuristic and a CVXPY MPC
baseline; we do not re-implement ACN-Sim's optimizers and we do not claim
to subsume ACN-Sim.

**CityLearn** is an RL benchmark for district-level energy management,
typically with batteries, HVAC setbacks, and (in recent versions) EV
charging schedules. CityLearn's scenarios are statically packaged in the
distribution, which limits factor sweeps. `v2b_syndata` can supply the
scenario inputs (building load, EV sessions, prices, DR) that a
CityLearn-style RL benchmark needs to expand its scenario coverage along
the V2B axes.

**OCHRE** (Maguire & Roberts 2022, NREL) is a residential dwelling
simulator with EV charging coupling. It is detailed at the dwelling
level and well-suited as a downstream consumer of `v2b_syndata`
sessions.csv when the building is a residence.

**EVerest / EVeREST** (LF Energy) is an OCPP-compliant charger-protocol
simulator, useful for hardware-in-loop and protocol conformance work; it
is orthogonal to `v2b_syndata`, which operates at a higher level of
abstraction (session-level requests, not OCPP messages).

The intended posture: `v2b_syndata` produces the inputs; ACN-Sim,
CityLearn, OCHRE, and EVerest consume them. Our paper_bench is the
proof-of-integration, not the eval suite for the simulators themselves.

---

## 5. Building-load datasets and simulators — we *use* the canonical sims internally

For the building-load factor, the canonical artifacts are
**EnergyPlus** (DOE, NREL, ORNL), the **DOE Commercial Reference
Buildings**, the **ASHRAE 90.1 Prototype Building Models**, and the
**TMYx** typical-meteorological-year weather files. These are not
competitors — they are the substrate of our `load_pipeline/` module.
A `v2b_syndata` run invokes EnergyPlus 23.2 against the appropriate
ASHRAE 90.1 prototype IDF for the chosen building descriptor, driven by
the TMYx file for the chosen location descriptor. The IDF and weather
choices are recorded in the manifest's `building_load_provenance` block.

**Pecan Street Dataport** (UT Austin / Pecan Street Inc.) is the
gold-standard residential AMI dataset, with per-circuit submetering and
in some homes EV-charger circuits. It is paid academic access; the
license terms prevent us from redistributing slices, so we cannot
calibrate against it without involving a per-user license check. For
that reason we do not currently use Pecan Street, even though it would
be an excellent source for the residential side of the building × EV
joint. This is a real limitation, not a stylistic choice; if the KDD D&B
submission demands a residential V2B calibration we will need to either
purchase a Dataport license or restrict the residential scope to publicly
documented archetypes.

**OpenEI EV datasets** (NREL OpenEI portal) is a catalog of various EV
data dumps; some are subsumed by EV WATTS or the NREL Fleet DNA program,
others are point-in-time releases of limited duration. We treat it as a
discovery mechanism rather than a calibration source. **NREL EV Detailed
Data / Fleet DNA** covers fleet duty cycles and is more relevant for
medium- and heavy-duty fleet studies, which are outside the V2B
(light-duty plus building) scope of `v2b_syndata`.

---

## 6. What `v2b_syndata` uniquely offers

The artifact's claim is not novelty on any individual factor — every
factor is better-served on its own axis by a specialized real dataset or
simulator — but rather **six-factor co-controllability with calibrated
marginals, manifest-stamped provenance, and bitwise reproducibility**.
Concretely:

1. **All six V2B factors emitted from one resolution pass**: building load,
   users, vehicles, chargers, prices, and DR events are all materialized
   from one descriptor + seed, and the joint is internally consistent
   (e.g., the sessions sampler enforces D5 reachability against the
   `cars` capacity and the `chargers` rate, so each emitted session is
   physically achievable given the emitted fleet).

2. **Calibrated marginals with provenance stamping**: the session marginals
   (arrival, dwell, arrival-SoC, and the (arrival, dwell) copula) are
   fitted against ACN-Data / EV WATTS / INL / ElaadNL, with the
   provenance written into `manifest["knob_resolution"]` at the leaf
   level — so a downstream consumer can answer, for any column in any
   CSV, "where did this distribution come from?"

3. **Audited knob surface**: 98 knobs, all subjected to a two-stage
   monotonicity audit (existence + sign of effect), 67/67 admitted
   knobs MONOTONIC in the intended direction; 12 declaration corrections
   in `knobs.yaml` came out of the audit (see `showcase/OVERVIEW.md` Section 7,
   Table 4).

4. **Bitwise reproducibility under the `clean` noise profile**: 11/11
   determinism tests pass across processes; the per-node
   `SeedSequence.spawn()` policy isolates per-car streams so a knob
   change affecting one factor does not silently shift the RNG path of
   another.

5. **Configurable noise contracts**: a separate `tmyx_stochastic` profile
   layers bounded jitter (±5% on building load, ±5 min on arrivals, ±3%
   on arrival SoC) while preserving the physical-feasibility invariants
   (C4: arrival < departure; D5: required-SoC ≤ max-feasible-SoC; D6:
   arrival-SoC < required-SoC). Stochasticity is opt-in for Monte Carlo
   sweeps, off by default for ad-hoc generation.

6. **Both descriptor- and knob-level controllability**: a four-descriptor
   YAML (location, building, population, equipment) is the user-facing
   surface; underneath, every individual knob is overridable in the
   scenario YAML or on the CLI, and the resolution chain is recorded in
   the manifest.

No existing public artifact we are aware of offers this combination. The
closest single-piece analog on the synthetic-data axis is EVI-Pro Lite
(aggregate, not session-level; not configurable from Python); on the
audited-scenario-library axis is SimBench (distribution grids, not V2B);
on the calibrated-session axis is ACN-Data itself (one site, no
buildings, no DR, no prices).

---

## 7. What `v2b_syndata` does *not* offer (honest limitations)

The reverse listing matters as much as the claim list. The following are
real limitations of the artifact at the version targeting the KDD D&B
2027 submission:

1. **No real-driver identity.** All `user_id` fields are synthesized.
   ACN-Data and INL EVP-1 are calibrated against pseudonymized real
   identities, but `v2b_syndata` does not preserve any individual real
   identity into its output — only the empirical marginals and the
   region-level joint of (φ, κ). Studies that need to evaluate
   personalization against individual real drivers must go to the
   underlying datasets, not to our generator.

2. **No V2B discharge in `paper_bench` today (V1G only).** The
   bench currently exercises unidirectional charging with curtailment.
   Bidirectional discharge can be configured via the `equipment`
   descriptor (`charging_infra.bi_rate_kw` / `directionality_frac`
   knobs are audited as MONOTONIC), but the in-paper utility demo
   restricts to V1G + peak-shaving for reproducibility-by-default.

3. **No sub-tick building/EV electrical co-simulation.** `building_load.csv`
   and `sessions.csv` are emitted as separate streams at 15-minute
   resolution and are not co-simulated against a shared feeder model or
   transformer constraint within the generator. Downstream simulators
   (ACN-Sim, CityLearn, OCHRE, OpenDSS-coupled studies) are the right
   place to add electrical-coupling fidelity.

4. **Short horizons by default.** Scenarios are typically configured for
   monthly sim windows (4 weeks); batch generation supports
   (months × samples-per-month), but multi-year continuous runs are
   not the design target. Long-horizon climate or fleet-evolution
   studies should drive `v2b_syndata` over a longitudinal scenario
   schedule, not expect a single-run multi-year emission.

5. **Battery-capacity-inference fallback rate is non-trivial.** The
   ACN-Data calibrator falls back to a 60 kWh default capacity when
   `WhPerMile` is missing or equals the sentinel 299, at a measured
   ~33% fallback rate (`CALIBRATION_NOTES.md` Section 2 and Section 9). This biases
   the arrival-SoC fit toward the fleet-median assumption and
   contributes to high KS distance on the soc_arrival fit (~0.4) for
   ACN-anchored populations.

6. **Some KS goodness-of-fit values are poor.** The parametric families
   chosen (TruncNorm / Weibull / Beta) do not always fit empirical
   marginals well — `erratic.arrival.ks_fit_quality = 0.557` on the
   first ACN run is a real warning, not a noise floor. Family
   reselection is on the Step 5.5 roadmap.

7. **No Pecan Street residential calibration.** Pecan Street Dataport's
   license terms prevent inclusion without per-consumer licensing; we
   document the gap (Section 5) rather than work around it.

8. **NHTS-anchored commute-distance calibration is deferred.** The δ
   (commute-distance) axis is currently hand-specified per region with
   the ACN `userInputs.milesRequested` reported as a diagnostic only —
   it is a charge-target proxy, not a measured commute (see
   `CALIBRATION_NOTES.md` Section 3). The NHTS-anchored fit is in Step 5.5
   plan, not in the current release.

9. **Single-platform tested for bitwise identity.** Reproducibility is
   verified on Linux/glibc against EnergyPlus 23.2.0; cross-platform
   bitwise identity is not asserted in the test suite (`showcase/OVERVIEW.md`
   Table 6).

10. **No Datasheet-for-Datasets nor Croissant metadata in this revision.**
    The KDD D&B track's "Quality & Documentation" criterion expects at
    minimum a Datasheet; this is on the eight-week submission plan but
    not in the current repository.

If a reviewer judges `v2b_syndata` against these limitations, none of
them are dealbreakers for the V2B-factor-sweep use case the artifact
is designed for, but they are dealbreakers for use cases like (a)
personalization against individual real drivers, (b) bidirectional
ancillary-service market studies, (c) sub-cycle distribution-feeder
studies, or (d) multi-year fleet-evolution forecasting. The artifact is
correctly scoped against (i) controlled factor sweeps for V2B control,
market, and consent-modeling research, and (ii) standardizing scenario
inputs across V2B benchmarks.

---

## 8. References

The reference list is preliminary and intended to be cross-checked
against the final manuscript bibliography. Entries marked `[verify]`
need their cited number or year confirmed at copy-edit time.

- **Lee, Z. J., Li, T., & Low, S. H. (2019).** ACN-Data: Analysis and
  Applications of an Open EV Charging Dataset. In *Proceedings of the
  Tenth ACM International Conference on Future Energy Systems
  (e-Energy '19)*. ACM. DOI: 10.1145/3307772.3328313.
- **Lee, Z. J., Sharma, S., Johansson, D., & Low, S. H. (2021).**
  ACN-Sim: An Open-Source Simulator for Data-Driven Electric Vehicle
  Charging Research. *IEEE Transactions on Smart Grid*, 12(6), 5113–5123.
- **Idaho National Laboratory (2015).** The EV Project: Q4 2013
  Quarterly Report and Phase 1 Project Final Reports. avt.inl.gov.
- **EV WATTS (DOE / EPRI).** Electric Vehicle Workplace and Travel
  Telematics Study. Data portal: livewire.energy.gov. [verify exact
  publication / project name]
- **ElaadNL (2021).** Open Charging Transactions dataset.
  open-data.elaad.io. CC BY 4.0.
- **Vazquez-Canteli, J. R., Kämpf, J., Henze, G., & Nagy, Z. (2020).**
  CityLearn v1.0: An OpenAI Gym Environment for Demand Response with
  Deep Reinforcement Learning. In *Proceedings of the 6th ACM
  International Conference on Systems for Energy-Efficient Buildings,
  Cities, and Transportation (BuildSys '19)*. ACM.
- **Nweye, K., Liu, B., Stone, P., & Nagy, Z. (2023).** Real-world
  challenges for multi-agent reinforcement learning in grid-interactive
  buildings. *Energy and AI*, 10, 100202. [verify volume/pages]
- **Maguire, J., & Roberts, D. (2022).** OCHRE: The Object-oriented,
  Controllable, High-resolution Residential Energy model. NREL Technical
  Report. [verify report number]
- **Wood, E., Rames, C., Muratori, M., Raghavan, S., & Melaina, M.
  (2017).** National Plug-In Electric Vehicle Infrastructure Analysis.
  NREL/TP-5400-69031. (EVI-Pro / EVI-Pro Lite underlying methodology.)
- **Henri, G., Lu, N., & Carrejo, C. (2020).** pymgrid: An open-source
  Python microgrid simulator. arXiv:2011.08004.
- **Meinecke, S., Sarajlić, D., Drauz, S. R., Klettke, A., Lauven,
  L.-P., Rehtanz, C., Moser, A., & Braun, M. (2020).** SimBench — A
  Benchmark Dataset of Electric Power Systems to Compare Innovative
  Solutions Based on Power Flow Analysis. *Energies*, 13(12), 3290.
- **Balakrishna, P., Book, G., Kirchgässner, W., Schenke, M., Traue, A.,
  & Wallscheid, O. (2021).** gym-electric-motor (GEM): A Python toolbox
  for the simulation of electric drive systems. *Journal of Open Source
  Software*, 6(58), 2498.
- **Pecan Street Inc.** Dataport residential AMI dataset. dataport.pecanstreet.org.
  Paid academic license.
- **NREL Fleet DNA / EV Detailed Data.** NREL Transportation Secure Data
  Center. nrel.gov/tsdc.
- **OpenEI EV Datasets Catalog.** openei.org/datasets, U.S. DOE.
- **U.S. DOE / NREL (2011, updated periodically).** Commercial Reference
  Building Models of the National Building Stock. NREL/TP-5500-46861.
- **ASHRAE / Pacific Northwest National Laboratory.** ANSI/ASHRAE/IES
  Standard 90.1 Prototype Building Models. pnnl.gov/projects/building-energy-codes-program.
- **TMYx weather files.** climate.onebuilding.org. Compiled from
  ISD/NOAA station observations.
- **Gebru, T., Morgenstern, J., Vecchione, B., Vaughan, J. W., Wallach,
  H., Daumé III, H., & Crawford, K. (2021).** Datasheets for Datasets.
  *Communications of the ACM*, 64(12), 86–92. (Originally arXiv:1803.09010,
  2018.)
- **MLCommons (2024).** Croissant: A Metadata Format for ML-Ready
  Datasets. github.com/mlcommons/croissant.
- **EVerest / LF Energy.** EVerest open-source EV charging software
  stack. github.com/EVerest. Apache-2.0.
- **California ISO.** Capacity Bidding Program (CBP) and Base Interruptible
  Program (BIP) tariff documents. caiso.com.

---

## 9. One-paragraph positioning (for the manuscript intro)

`v2b_syndata` is not a new EV-charging dataset, nor a new building-load
simulator, nor a new charging-control algorithm. It is a scenario
generator that emits the six co-varying data streams a V2B study needs
— building load, users, vehicles, chargers, prices, and demand-response
events — from one descriptor and one seed, with the session-level
marginals calibrated against the four most-cited public charging-session
datasets (ACN-Data, EV WATTS, INL EV Project Phase 1, ElaadNL) and the
building-load stream produced by EnergyPlus 23.2 against ASHRAE 90.1
prototypes and TMYx weather. It is intended to be the *input* to
downstream simulators (ACN-Sim, CityLearn, OCHRE) and benchmarks, not a
replacement for them; the artifact's contribution is the audited,
provenance-stamped, bitwise-reproducible six-factor scenario surface
itself.
