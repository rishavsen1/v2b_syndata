# Ethics, Bias, and Intended-Use Statement — `v2b_syndata`

Companion to `docs/DATASHEET.md`. Every claim is grounded in the repository docs
(`README.md`, `docs/CALIBRATION_RESULTS.md`, `docs/KDD_READINESS.md`); we mirror,
not soften, the known limitations.

---

## 1. Privacy

**Risk: low.** The generator's *output* is **fully synthetic** — no real person,
vehicle, account, or address appears in any generated CSV. Identifiers
(`car_id`, `charger_id`, `session_id`, `building_id`) are sequential synthetic
keys, not pseudonymized real IDs.

The *calibration corpora* are already-public research releases consumed only as
**aggregate distribution parameters**:

- **ACN-Data** (Caltech/JPL/Office001) and **ElaadNL / 4TU** are public charging
  datasets; the generator stores only fitted per-region distribution *parameters*
  in `configs/populations.yaml`, not the raw sessions
  (`docs/GENERATIVE_MODELS.md`, "Two layers"). No raw source record is
  redistributed by this repository.
- Crucially, **state-of-charge is never present in any source** — charger logs
  record energy and timestamps only (`README.md`). The generator therefore
  cannot leak a behavior it never observed.

**Residual risk.** Because calibration reduces a corpus to a handful of
distribution parameters per region (with a `MIN_SAMPLES = 30` floor before a
region is marked `calibrated`), membership-inference / reconstruction risk
against the *original* corpora is very low. We make **no formal differential-
privacy guarantee**; users who fit from raw sources must honor those sources'
own licenses and terms.

---

## 2. Bias and representativeness

The generator is **honestly non-representative** along several axes — these are
documented as scope, not hidden:

- **Geographic / behavioral skew.** Real EV-behavior calibration rests on **US
  workplace charging (ACN-Data, California: Caltech/JPL/Office001)** plus **one
  Netherlands site (ElaadNL)**. EV WATTS and INL — which might have broadened
  coverage — are **tiny synthetic fixtures (~64/~65 sessions), excluded from all
  fidelity numbers** (`docs/CALIBRATION_RESULTS.md`, Caveats). Conclusions about
  residential, fast-charging-corridor, or non-US/EU behavior are **not
  supported**.
- **Single climate zone for building load.** Only **Denver CZ-5B** ships
  (`docs/KDD_READINESS.md`, Gap 3); building-load and PV reflect that one
  climate, despite the ComStock reference validator being climate-zone-aware
  (5B/3B/4A/6A). Hot-humid / heating-dominated generalization is untested in the
  shipped configuration.
- **Single building prototype, below stock average.** The generator ships one
  efficient ASHRAE 90.1-2019 prototype per archetype; its EUI is **~30–50% below
  the ComStock stock-weighted average** (e.g. ~7.8–8.0 vs ~15.7 W/m² small
  office), so it under-represents older, less-efficient building stock
  (`docs/CALIBRATION_RESULTS.md`, S5b). The diurnal *shape* matches well
  (weekday correlation 0.71–0.94), but **magnitudes are not stock-representative**.
- **Arrival-shape bias.** Real arrival is bimodal; the model leans toward a
  unimodal/clipped arrival outside the calibrated cohorts, and arrival-SoC is the
  weakest marginal (capacity-inference fallback ~33% on ACN;
  `docs/CALIBRATION_RESULTS.md`). Do not use for capacity-sensitive fairness or
  equity analysis.

**Implication.** Treat `v2b_syndata` as a *workplace-charging, single-climate,
efficient-building* generator. Claims of broad demographic or geographic
representativeness would be unsupported by the calibration evidence.

---

## 3. Consent

No consent process applies to the synthetic output (no individuals are present).
The upstream calibration corpora (ACN-Data, ElaadNL/4TU) are public research
datasets governed by their own release terms; this repository consumes them only
as aggregate parameters and redistributes no raw records. Users who re-run
`v2b-syndata calibrate` against raw downloads are responsible for complying with
each source's data-use agreement.

---

## 4. Potential misuse

- **Misrepresenting synthetic data as real.** The output must always be labeled
  synthetic; presenting `building_load.csv` magnitudes as a real building's metered
  consumption would be misleading (they track an efficient prototype, not stock).
- **Over-claiming SoC realism.** `arrival_soc` / `required_soc_at_depart` are
  **modeled priors**, not measurements. Using them as ground-truth SoC labels —
  e.g. to train an "SoC estimator" and claim real-world validity — is a misuse.
- **Capacity-sensitive grid/equity claims.** Because capacity is inferred (ACN
  only) or defaulted (60 kWh elsewhere), do not derive policy claims that hinge
  on accurate per-vehicle capacity.
- **Privacy-attack benchmarking without caveat.** The data is synthetic; using it
  to claim a method "preserves privacy on real mobility data" without noting the
  synthetic provenance would overstate the evidence.
- **Bidirectional V2B/V2G performance claims via the bundled benchmark.** The
  shipped benchmark is **V1G-only** (`docs/KDD_READINESS.md`); reporting V2B
  discharge benefits from it would misrepresent what was actually evaluated.

---

## 5. Intended-use statement

`v2b_syndata` is intended for **reproducible research and benchmarking** of
**V2B/charging scheduling, building- and charging-load forecasting, and
demand-response studies** (`README.md`; `docs/DATASHEET.md`, *Uses*). It is
designed to let researchers ship a deterministic *recipe* (scenario + seed)
instead of a frozen corpus, and to be configured (knobs, descriptors, noise/
weather perturbation layers) to stress-test methods across conditions.

It is **appropriate** for: methods development, ablations, controlled
distribution-shift studies, and TSTR-style transfer experiments to held-out real
ACN/ElaadNL (where transfer is demonstrated; `docs/KDD_READINESS.md`, action #3).

It is **not appropriate** as: a stand-in for stock-representative building energy
data, a source of real SoC labels, a multi-climate or residential-charging
corpus (as shipped), or a bidirectional-V2B benchmark (bundled scheduler is
V1G-only). Users should cite the calibration sources and reproduce fidelity
numbers from the committed harnesses rather than asserting realism.

---

## 6. Environmental and compute note

Building load is computed with **EnergyPlus** physics simulation at generation
time; large multi-building / multi-month runs incur real compute. Determinism
means results need not be re-simulated once cached for a given seed.
