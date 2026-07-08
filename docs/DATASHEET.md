# Datasheet for `v2b_syndata`

A "Datasheet for Datasets" (Gebru et al., 2021, *Communications of the ACM*
64(12)) for **`v2b_syndata`**, a configurable synthetic **Vehicle-to-Building
(V2B) EV-charging dataset *generator***. Because the artifact is a generator
rather than a fixed corpus, every "dataset" answer below describes the *family*
of datasets the generator produces from a `(scenario YAML, knob overrides,
seed)` triple, and the calibration corpora the generator's distributions were
fit from.

All quantitative claims are cited inline to the source doc/file. Where the
generator is weak we say so — reviewers can cross-check every number against the
committed scripts (`tools/repro_paper.py` — the one-shot reproduction driver —
plus `tools/validate_calibration.py`, `tools/validate_buildingload.py`,
`tools/validate_pv.py`, `tools/tstr_forecasting.py`, `tools/model_eval.py`);
the consolidated, provenance-stamped number list is
`docs/experiments/PAPER_NUMBERS.md`.

> **Companion docs.** Schema and model overview: `README.md`. Distribution
> families + empirical verdicts: `docs/GENERATIVE_MODELS.md`. Fidelity numbers:
> `docs/CALIBRATION_RESULTS.md`. Submission gap analysis and honest limitations:
> `docs/KDD_READINESS.md`. Ethics/bias/misuse: `docs/ETHICS.md`. Machine-readable
> schema: `croissant.json` (repo root).

---

## Motivation

**For what purpose was the dataset created?**
To provide a *reproducible, configurable* source of EV-charging-plus-building
data for research on **Vehicle-to-Building scheduling, building/charging load
forecasting, and demand-response (DR) studies** — domains where real,
jointly-instrumented (sessions + building load + tariffs + DR + DER) traces are
scarce, privacy-encumbered, or single-site. The generator forward-samples from
calibrated behavioral distributions so that a given seed yields **bitwise-
identical** CSVs (`README.md`, "Outputs"), letting a paper ship the *recipe*
(scenario + seed) rather than gigabytes of frozen data.

**Who created it and on whose behalf?**
The `v2b_syndata` authors (Vanderbilt University), prepared for a KDD 2027
Datasets & Benchmarks submission under the *Data Generators and Environments*
category (`docs/KDD_READINESS.md`).

**Who funded the creation?**
See the paper's acknowledgements (not encoded in this repository).

---

## Composition

**What do the instances represent, and what files exist?**
A generated *dataset instance* is one scenario-seed directory of CSVs plus a
provenance manifest. There are several instance types, one per file
(`README.md`, "Outputs"; schema enforced by `src/v2b_syndata/validate.py`
`_SCHEMAS`):

| file | instance = one… | columns |
|---|---|---|
| `users.csv` | EV driver (behavioral profile) | `car_id, region, phi, kappa, delta_km, negotiation_type, w1, w2` |
| `cars.csv` | vehicle (battery spec) | `car_id, capacity_kwh, min_allowed_soc, max_allowed_soc, battery_class` |
| `chargers.csv` | charging port | `charger_id, directionality, min_rate_kw, max_rate_kw` |
| `sessions.csv` | charging session | `session_id, car_id, building_id, arrival, departure, duration_sec, arrival_soc, required_soc_at_depart, previous_day_external_use_soc` |
| `building_load.csv` | 15-min building-power timestep | `datetime, power_flex_kw, power_inflex_kw, power_kw` (EnergyPlus) |
| `pv_generation.csv` | 15-min PV-power timestep | `datetime, power_pv_kw` (all-zeros when PV off) |
| `pv.csv` | rooftop-PV system spec | `pv_id, pv_type, dc_capacity_kw, ac_capacity_kw, dc_ac_ratio, tilt_deg, azimuth_deg, module_type, system_derate, temp_coeff_per_c, noct_c, albedo` |
| `battery.csv` | stationary-battery spec | `battery_id, battery_type, capacity_kwh, power_kw, round_trip_efficiency, min_soc_pct, max_soc_pct, initial_soc_pct` (specs only — no dispatch) |
| `grid_prices.csv` | tariff timestep | `datetime, price_per_kwh, type` (`type ∈ {peak, off-peak}`) |
| `dr_events.csv` | demand-response event | `event_id, start, end, magnitude_kw, notified_at` (header-only when `program=none`) |
| `manifest.json` | run provenance | resolved knobs + per-knob provenance (`calibrated`/`knob`/`fixed`) |

Categorical domains (validated): `cars.battery_class ∈ {leaf_24, bolt_40, m3_75,
rivian_100}`; `chargers.directionality ∈ {unidirectional, bidirectional}`;
`users.negotiation_type ∈ {type_i, type_ii, type_iii, type_iv}`
(`validate.py:43–46`).

**How many instances are there?**
Unbounded — instance counts are knobs (e.g. `ev_fleet.ev_count`, scenario date
range, 15-min timestep grid). The generator is the artifact; any fixed count is
a configuration choice, not a property of the dataset.

**Is there a label?**
There is no classification label. The "targets" are continuous time series
(`power_kw`, `price_per_kwh`) and per-session quantities used as forecasting/
scheduling targets in downstream tasks (see *Uses*).

**Is any information missing / modeled rather than observed?**
**Yes, and this is the single most important caveat.** Charger logs record
**energy (kWh) and timestamps, never state-of-charge** (`README.md`, "Input
datasets"). Therefore:

- `arrival_soc` is **drawn from a Beta/normal prior** (mean ≈ 0.40), *not* fit
  from data — "arrival SoC is *unobserved* in all datasets" (`README.md`;
  `docs/GENERATIVE_MODELS.md`: "**not fittable** — no charger records SoC").
- `required_soc_at_depart` is derived as `arrival_soc + kWhDelivered / capacity`,
  i.e. the only real per-session signal is **delivered energy** (mean
  delivered/capacity ≈ 0.30; `docs/GENERATIVE_MODELS.md`).
- Capacity is **inferred per-session for ACN-Data only**; all other sources
  default to 60 kWh (`README.md` source table). Arrival-SoC "inherits the ~33%
  ACN capacity-inference fallback; not for capacity-sensitive analysis"
  (`docs/CALIBRATION_RESULTS.md`, Caveats).

**Are there errors / redundancies / noise?**
An optional **output-side noise layer** (`noise_profiles.yaml`) can perturb
produced CSVs (±5%/±3% load jitter etc.); the `clean` profile sets these to 0 so
`building_load` is a deterministic `f(weather)` (`README.md`, "Multi-building").
A separate **weather-perturbation layer** alters the EPW *and* the exported
`weather_data.csv` together to keep load physically faithful.

**Does the dataset rely on external resources?**
Building load requires a local **EnergyPlus** binary at generation time (the
bundled DOE prototype models are pinned to **EnergyPlus 24.1**, which is what
the reference corpus and all paper validations used); a missing binary halts
generation hard (no silent stub; `README.md`, "Verify"). The shipped
prototypes are single-climate-zone (Denver CZ-5B; see *Limitations*), with
per-site TMYx EPWs for the nine tariff locations.

**Self-contained / confidential / offensive content?**
The generated data is **fully synthetic** — no personal data, no confidential or
offensive content. Calibration corpora are already-public aggregates (see
*Collection Process* and `docs/ETHICS.md`).

---

## Collection Process

**How was the data acquired?**
Two-stage pipeline (`docs/GENERATIVE_MODELS.md`, "Two layers"):

1. **Calibration** (`v2b-syndata calibrate`, offline/occasional) — fits
   per-region behavioral distribution *parameters* from real charging-session
   datasets and writes them into `configs/populations.yaml`. A parameter is
   marked `calibrated` only where ≥ `MIN_SAMPLES = 30` sessions exist for a
   region, else it falls back to a `knob`/`fixed` prior
   (`distribution_fitter.fit_region`).
2. **Generation** (`v2b-syndata generate`) — forward-samples CSVs under a
   SHA-keyed RNG; a `(scenario, overrides, seed)` triple is bitwise-reproducible.

**What are the calibration sources — and which are real vs. fixture?**

| source | role | real data? | what it contributes |
|---|---|---|---|
| **ACN-Data** (Caltech / JPL / Office001) | primary | ✅ real, public | the only source with trip requests (`kWhRequested`, miles, Wh/mi) → best capacity inference; arrival/dwell marginals + copula |
| **ElaadNL / 4TU** | primary | ✅ real, public | arrival/dwell marginals + copula (delivered energy; default 60 kWh) |
| **EV WATTS** (public 2026 release) | primary | ✅ real, public (1,265,017 workplace/public-L2 sessions) | arrival/dwell marginals + copula; **port-as-proxy user identity** — (φ, κ) describe per-port shift consistency, not individual drivers |
| **INL** (EV Project Phase 1) | adapter only | ⚠️ **tiny synthetic fixture** (~65 sessions) | **fixture-only — excluded from all fidelity numbers**; released as a *labeled* 2011-era distribution-shift benchmark |

> INL ships as an *adapter with a tiny synthetic fixture*, not the real
> release, and is excluded from every fidelity number
> (`docs/CALIBRATION_RESULTS.md`, Caveats). EV WATTS was upgraded from a
> fixture to the real DOE/EPRI public release (ingested via
> `tools/ingest_evwatts.py`, calibrated 2026-06-28) — real-data fidelity
> claims rest on **ACN-Data, ElaadNL, and EV WATTS** (the last under its
> port-as-proxy identity caveat).

Building-load fidelity is benchmarked against **NREL ComStock/EULP** (climate
zones 5B/3B/4A/6A) plus **19 BDG2 real meters** (`docs/KDD_READINESS.md`, action
#1; `tools/validate_buildingload.py`). PV is a deterministic PVWatts-style curve
from the same TMYx weather fed to EnergyPlus (`README.md`, "Outputs").

**Sampling strategy.**
Forward sampling: Tier-0 descriptors → Tier-1 region/root draws → per-entity
latents → renderers (`README.md`, "Architecture"). Marginals are sampled by
inverting a **shared Gaussian copula** uniform, which couples
arrival × dwell with one rank parameter (`docs/GENERATIVE_MODELS.md`;
`renderers/sessions.py`).

**Over what timeframe was the data collected?**
The calibration corpora are public historical charging logs (ACN-Data,
ElaadNL); generated timestamps follow the scenario's configured date range.

**Were individuals notified / did they consent / ethical review?**
The generator contains no individuals. The calibration corpora are
public/aggregate research releases; see *Consent* in `docs/ETHICS.md`.

---

## Preprocessing / Cleaning / Labeling

**Was any preprocessing done?**
- All four sources are normalized into one internal `SessionFeatures` record
  before calibration; trip-request fields are populated for ACN only
  (`README.md`).
- Distribution families are chosen on **principled** grounds (correct support,
  copula composability, interpretable parameters), *not* by an empirical family
  contest; a retrospective AIC/BIC/KS study
  (`docs/experiments/`, `docs/MODEL_SELECTION.md`) checks those choices
  (`docs/GENERATIVE_MODELS.md`). Families: arrival hour →
  TruncNorm (2-component truncated mixture for ACN/ElaadNL), dwell → Weibull
  (mixture where it beats single-Weibull), arrival×dwell → Gaussian copula,
  arrival/departure SoC → Beta prior.
- Calibrated fits are **post-clamped** to a validity window (arrival window
  widened to ~[4,22], read per-region; `docs/KDD_READINESS.md` action #6).

**Is SoC labeled or modeled?**
**Modeled, not observed** (see *Composition → missing information*). SoC is a
prior, never a fit. `required_soc_at_depart > arrival_soc` is the only hard SoC
invariant (D6); the 80% departure floor (D7) is set to 0 for calibrated cohorts
so empirical departure SoC is not clamped (`README.md`).

**Is the raw source data retained?**
Calibrated parameters are committed in `configs/populations.yaml`; raw source
CSVs and validation artifacts live under git-ignored `data/` dirs and are
regenerated by the committed harnesses.

---

## Uses

**What tasks has the dataset been used for?**

- **V2B / charging scheduling**, **building & charging-load forecasting**, and
  **demand-response studies** (the design intent; `README.md`).
- **TSTR utility (train-on-synthetic, test-on-real).** A short-horizon load /
  charging-demand forecaster trained on synthetic data and tested on held-out
  **real** data (`data/tstr/*.json`, regenerated by `tools/repro_paper.py`):
  - **ACN (matched cohort), lagged features:** TSTR/TRTR MAE/RMSE ratio
    **0.99× / 0.92×** (parity with training on real).
  - **ACN, calendar-only probe:** **0.57× / 0.79×** — synthetic-trained *beats*
    real-trained on load *shape*.
  - **ElaadNL (deliberate cross-scale transfer: 20-vehicle synthetic building
    vs a 481 kW-peak network aggregate):** shape transfer reaches parity in
    the calendar-only, unit-mean-normalized regime (**1.02× / 1.03×**), while
    raw-magnitude lagged transfer degrades to **7.38× / 6.16×** — a
    scale-shift result, not a shape failure
    (`data/tstr/results_elaadnl_matched.json`; the earlier mismatched-scenario
    artifact `results_elaadnl.json` is superseded and retained as evidence).

**Fidelity that supports these uses** (all from `docs/CALIBRATION_RESULTS.md`,
regenerated 2026-07-08 over ACN pooled + per-site, ElaadNL, and EV WATTS;
consolidated with provenance in `docs/experiments/PAPER_NUMBERS.md`):

- **S1 marginals:** mean `|Δμ| ≈ 0.44 h` across all 36 region×variable cells
  (0.37 h excluding EV WATTS), KS ≤ 0.24, with seeded bootstrap 95% CIs
  (B=1000) on every cell (`docs/experiments/s1_fidelity_cis.csv`).
- **S2 joint (copula):** arrival×dwell Spearman ρ reproduced; worst
  small-sample cell ρ-gap 0.226 (`acn_office001`).
- **S3 held-out (80/20 by user, family-matched refit):** median
  Δ(holdout − train KS) ≈ 0.064 under the protocol that refits the *shipped*
  family (mixture where calibration ships one); outliers are disclosed
  per-cell (worst +0.425 in a 62-session test cell).
- **Mixture + per-region fit win:** replacing a pooled-broadcast fit with the
  per-region shipped mixture drops `rare consistent` (≈36% of ACN drivers)
  arrival fit KS **0.196 → 0.040**; across all mixture-selected arrival cells
  mean KS falls **0.134 → 0.035** (`docs/experiments/mixture_ablation.csv`).
- **S6 weekly rhythm:** weekday/weekend ratio gap ≤ 0.06 dex.

**Is there anything a user should know to avoid harms / misuse?**
See `docs/ETHICS.md`. In short: do **not** treat SoC fields as observed ground
truth; do **not** use the data for **capacity-sensitive** analysis (arrival-SoC
is the weakest marginal); do **not** treat building-load magnitudes as
stock-representative (they track a single efficient prototype, not stock
average); and do **not** present the generator as a substitute for real PII-bearing
mobility/metering data in privacy-attack research without that caveat.

**Tasks the dataset should *not* be used for (as shipped):**
- Bidirectional (**V2B/V2G discharge**) benchmarking *via the bundled benchmark*
  — the shipped benchmark is **V1G-only** (clips V2B discharge, excludes
  building load + DR from the scheduler; `docs/KDD_READINESS.md`, "Also
  outstanding"). The *data schema* supports bidirectional chargers
  (`directionality=bidirectional`, negative `min_rate_kw`), but the bundled
  scheduler does not exploit it.
- Studies needing **battery dispatch / SoC time series** — `battery.csv` is
  **specs-only by design**: dispatch is a *decision of the controller under
  evaluation*, exactly as the dataset ships storage specifications rather
  than dispatch schedules (an experimental `battery_dispatch` output was
  built and deliberately reverted; publishing a reference dispatch would
  entangle the benchmark with one controller's choices).
- Multi-climate generalization — only **one climate zone (Denver CZ-5B)** ships.

---

## Distribution

**How is it distributed?**
As **open source** — the generator code, calibration scripts, scenario YAMLs,
and committed calibrated parameters. Users **regenerate** datasets locally and
deterministically (seed → bitwise-identical CSVs). In addition, a frozen
**18,000-unit reference corpus** is released (10 campus buildings × 12
months × 150 seeded samples, ~19 GiB, clean noise profile, per-sample
weather realizations; `data/output/campus10/`), with a Zenodo deposit plan
and DOI reservation procedure in `docs/experiments/DEPOSIT_PLAN.md`.
Machine-readable schema: `croissant.json` (ML Commons Croissant JSON-LD).

**Is there a DOI / license / terms?**
- **License:** generator **code** is **MIT** (`LICENSE`); the **synthetic data**
  and original repository artifacts are **CC BY 4.0** (`DATA_LICENSE.md`).
- Calibration corpora retain their **own** upstream licenses/terms (ACN-Data,
  ElaadNL/4TU, EV WATTS, INL) — not relicensed here; users fitting from raw
  sources must honor those.

**Export controls / regulatory restrictions?**
None known for the synthetic output.

---

## Maintenance

**Who maintains it / how to contact?**
The repository authors (Vanderbilt University). Issues and the live backlog are
tracked in `docs/PROJECT_TRACKER.md` and `docs/KDD_READINESS.md`.

**Will it be updated, and how are updates communicated?**
Yes — open items are tracked with a status legend (`docs/KDD_READINESS.md`).
Because the artifact is a generator, "updates" mean code/calibration changes;
every paper number is regenerable from one committed driver
(`tools/repro_paper.py` → `docs/experiments/PAPER_NUMBERS.md`). Determinism
tests guard backward compatibility (synthetic
populations stay bitwise-identical across the recent marginal-fidelity work;
`docs/KDD_READINESS.md` action #6).

**Will older versions be supported?**
Reproducibility is by `(scenario, overrides, seed)` + the committed parameters
and `manifest.json`; pinning a git commit reproduces that commit's output.

**Can others contribute?**
Yes (open source). Contributions should keep determinism tests green and refresh
the calibration/validation docs via the committed harnesses.

---

## Honest limitations (summary)

Mirroring `docs/KDD_READINESS.md` and `docs/CALIBRATION_RESULTS.md`:

1. **SoC is a prior, not a fit.** No charger records state-of-charge; `arrival_soc`
   is a Beta prior (mean ≈ 0.40) and departure SoC inherits its shape. Not for
   capacity-sensitive analysis (`docs/GENERATIVE_MODELS.md`;
   `docs/CALIBRATION_RESULTS.md`).
2. **Building load is single-prototype; four of five archetypes sit 37–54%
   below stock-average intensity (large office 27% above).** The
   generator ships one ASHRAE 90.1-2019 efficient prototype (~7.8–8.0 W/m² small
   office) vs ComStock's stock-weighted ~15.7 W/m²; **0/5 archetypes pass strict
   ASHRAE G14 magnitude thresholds**, though the diurnal *shape* matches well
   (weekday shape correlation **0.71–0.94**, peak-hour error ≤ 3 h). Documented
   as model *scope*, not a data-fit error (`docs/CALIBRATION_RESULTS.md`, S5b).
3. **Arrival fidelity is the weakest EV marginal.** Real arrival is *bimodal*
   and ~8.3% of ACN arrivals fall outside the modeling window; a single TruncNorm
   underfits (KS 0.108 vs 0.029 for a 2-component mixture). A mixture now ships
   for ACN/ElaadNL arrival, but it remains "the weakest link"
   (`docs/GENERATIVE_MODELS.md`; `docs/CALIBRATION_RESULTS.md`, Caveats).
4. **INL is a tiny synthetic fixture**, not the real release — excluded from
   every fidelity number and shipped only as a labeled distribution-shift
   benchmark. EV WATTS is the real public release but under a
   **port-as-proxy** user identity (per-port shift consistency, not
   individual-driver consistency; `docs/CALIBRATION_RESULTS.md`).
5. **Single climate zone (Denver CZ-5B)** ships; geographic skew to US workplace
   + one NL site (`docs/KDD_READINESS.md`; see `docs/ETHICS.md` for bias detail).
6. **Bundled benchmark is V1G-only**; **battery is specs-only (no dispatch)** —
   dispatch is a downstream control decision, not a generated artifact. PV is
   **validated against NREL PVWatts v8 (PySAM) on identical weather**: annual
   energy +1.27%, hourly CV(RMSE) 15.1% / NMBE +1.3% / r 0.994
   (`docs/experiments/pv_validation.md`) — validated against a reference
   implementation, not against metered arrays. DR magnitude ranges are
   tariff-derived (BIP) / evaluation-consistent (CBP), while the ELRP range
   is an explicitly stylized prior and the uniform magnitude *shape* is a
   modeling choice (`docs/experiments/dr_magnitude_grounding.md`).
