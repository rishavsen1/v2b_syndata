# Behavioral Model Card — EV arrival, dwell, and SoC

_A model card for the behavioral generative models in `v2b-syndata`: what family each
random quantity uses, what it was fitted on, what its measured error is, where the
fitted parameters live, and how to sample from them without running the generator._

Companion docs: `docs/GENERATIVE_MODELS.md` (why each family), `docs/CALIBRATION_RESULTS.md`
(full validation tables), `docs/experiments/PAPER_NUMBERS.md` (consolidated evidence).

---

## 1. TL;DR for a reader in a hurry

- The behavioral model is a **per-region parametric mixture model**, not a neural
  network. Four marginals (arrival hour, dwell hours, arrival SoC, departure SoC)
  plus a **Gaussian copula** coupling arrival to dwell.
- Fits are **per (population × region)** — never per building. Each building
  *selects* a population; ten buildings sharing a population share one fitted model.
- The **only input feature is a discrete region label**, derived from two per-driver
  statistics (φ = visit frequency; κ was removed 2026-08 — unused at generation and near-independent of behavior). There is no
  conditioning on weather, price, building, or calendar day inside the marginals.
- Training-set KS is **0.019–0.15** for arrival/dwell/arrival-SoC and **0.24–0.31**
  for departure SoC. Held-out KS exists for **arrival and dwell only**: median
  degradation **+0.064**, worst cell **+0.425**.
- **Arrival SoC is not a fit to data.** No charging dataset records SoC; it is a
  fixed prior, and its reported KS is circular. Do not present it as calibrated.

---

## 2. Model specification

Sampled per car per day, after a Bernoulli(φ) appearance draw decides the day has
a session at all.

| # | Quantity | Family | Parameters | Support |
|---|---|---|---|---|
| 1 | arrival hour | 2-component truncated-Gaussian mixture (fallback: single TruncNorm) | `w1, mu1, sigma1, mu2, sigma2, trunc_lo, trunc_hi` | `[4, 22] h` calibrated, `[6, 20] h` hand-authored |
| 2 | dwell hours | Weibull (fallback/alternative: 2-component Weibull mixture) | `k, lambda` or `w1, k1, lambda1, k2, lambda2` | `(0, ∞)`, clipped to `[0.5, 14] h` |
| 3 | arrival SoC | Beta | `alpha, beta` | `[0, 1]`, shifted by `-δ_km · 0.003`, clipped to car band |
| 4 | departure SoC (= required SoC) | Beta (fallback: TruncNorm(85, 5) floored at 80%) | `alpha, beta` | `[0, 1]`, clamped into `(arrival, max_allowed]` |
| 5 | arrival × dwell dependence | Gaussian copula | `rho_gaussian` (from `rho_spearman` via `ρ_g = 2·sin(π·ρ_s/6)`) | `[-0.99, 0.99]` |

**Family selection is gated on fidelity, not likelihood.** A mixture ships only if
its KS beats the single family by `MIXTURE_KS_MARGIN = 0.02` *and* every component
passes the runtime validity ranges (`MIXTURE_MIN_SAMPLES = 60`, `MIN_SAMPLES = 30`).
That is why some regions ship `weibull` and others `weibull_mixture`.

**Sampling procedure** (`renderers/sessions.py`): draw a correlated uniform pair
`(u_arr, u_dwell)` from the bivariate normal copula, then push each through its
marginal inverse-CDF — closed form for single families, 60-step bisection for
mixtures. Exactly one uniform per quantity, which is what preserves the generator's
bitwise-determinism guarantee. The two SoC marginals are drawn independently.

**Why arrival is bimodal:** every calibrated region selects the mixture. Morning
commute plus a midday shoulder, e.g. ACN `rare_consistent` =
`0.42·N(8.21, 1.25) + 0.58·N(14.54, 3.52)` truncated to `[4, 22]`.

---

## 3. Input features

### 3.1 What the model conditions on

Only one thing: a **discrete region label**. Within a region, the marginals are
unconditional. So the model is a piecewise-constant conditional density
`p(arrival, dwell, soc | region)`, with typically 3–5 regions per population.

The region label comes from two per-driver summary statistics computed over that
driver's whole history (`calibration/feature_extractor.py`):

| Feature | Symbol | Definition | Range |
|---|---|---|---|
| visit frequency | φ | unique weekdays with a session ÷ weekdays in that driver's own active window `[first, last]` | `[0, 1]` |
| commute distance | δ_km | `mean(milesRequested) × 1.609` | km or unobserved |

Region assignment is a **deterministic first-match** of φ against the
rectangular boxes in `populations.yaml::axes_distribution` (`region_assignment.py`).
**δ_km is not used as an assignment filter** — it is a noisy, often-missing proxy —
but it does enter generation as the arrival-SoC shift `-δ_km · 0.003`.

### 3.2 Raw per-session fields consumed by the fitter

`arrival_hour` (converted to site-local wall clock — ACN logs are true UTC),
`dwell_hours`, `kWhDelivered`, and where present `milesRequested`, `WhPerMile`,
`kWhRequested`, `minutesAvailable`.

### 3.3 What is deliberately NOT an input

No weather, no building load, no electricity price, no charger type, no calendar
date, no day-of-week inside the marginals. Day-of-week enters only as two scalars
outside the distributions: the per-driver appearance rate φ and a population-level
`weekend_activity_factor` (e.g. 0.168 for ACN) that scales φ on Saturday/Sunday.

### 3.4 Inclusion filters (these shape the fitted support)

Sessions shorter than 0.5 h or longer than 168 h are dropped; drivers with fewer
than 5 sessions or fewer than 5 weekdays of active window are dropped; arrivals
outside `[4, 22]` h are **filtered, not clipped**, for the mixture fit (clipping
piles boundary mass that EM overfits into a spurious spike).

---

## 4. Training procedure and measured error

### 4.1 Estimator

| Quantity | Estimator |
|---|---|
| arrival single | MLE, Nelder–Mead on the truncated-normal negative log-likelihood |
| arrival mixture | deterministic EM (no RNG; quantile-chunk init, 300 iterations) |
| dwell | `scipy.stats.weibull_min.fit(floc=0)`; mixture = EM soft partition, then per-component Weibull MLE with hard assignment |
| SoC | `scipy.stats.beta.fit(floc=0, fscale=1)` |
| copula | Spearman ρ, converted to Gaussian ρ analytically |

Every fitted parameter is post-clamped to a declared validity window; a fit that
falls outside is **dropped**, and the region falls back to the pooled fit or a
placeholder formula. Fitting is fully deterministic — no random seed.

### 4.2 Training error (in-sample KS)

Recorded as `ks_fit_quality` next to every parameter block. This is a one-sample
KS statistic of the fitted CDF against **the same data it was fitted to**. It is a
descriptive fit statistic, *not* generalization error.

Per-region training KS, all data-calibrated populations:

| Population | Region | user share | arrival (family, n, KS) | dwell (family, n, KS) | soc_arr KS | soc_dep KS | ρ_g |
|---|---|--:|---|---|--:|--:|--:|
| `acn_workplace_baseline` | rare_consistent | 0.362 | mixture, 4,676, **0.040** | weibull, 4,723, **0.063** | 0.035 | 0.255 | −0.562 |
| | rare_inconsistent | 0.006 | mixture, 41,355 †, 0.036 | wb-mixture, 80, 0.061 | 0.063 | 0.253 | +0.055 |
| | occasional_consistent | 0.400 | mixture, 17,245, **0.045** | weibull, 17,313, **0.100** | 0.033 | 0.248 | −0.645 |
| | regular_charger | 0.231 | mixture, 18,504, **0.042** | weibull, 18,724, **0.115** | 0.033 | 0.237 | −0.590 |
| `acn_caltech_baseline` | rare_consistent | 0.528 | mixture, 2,713, 0.054 | wb-mixture, 2,757, 0.083 | 0.037 | 0.251 | −0.398 |
| | occasional_consistent | 0.306 | mixture, 4,609, 0.044 | weibull, 4,658, 0.093 | 0.032 | 0.245 | −0.457 |
| | regular_charger | 0.155 | mixture, 5,348, 0.028 | weibull, 5,361, 0.089 | 0.036 | 0.246 | −0.395 |
| `acn_jpl_baseline` | rare_consistent | 0.286 | mixture, 2,449, 0.021 | weibull, 2,454, 0.064 | 0.028 | 0.245 | −0.627 |
| | occasional_consistent | 0.440 | mixture, 11,687, 0.024 | wb-mixture, 11,702, 0.100 | 0.032 | 0.247 | −0.684 |
| | regular_charger | 0.271 | mixture, 12,961, 0.019 | weibull, 13,168, **0.148** | 0.034 | 0.239 | −0.586 |
| `acn_office001_baseline` | rare_consistent | 0.286 | mixture, 579, 0.030 | weibull, **41**, **0.174** | 0.130 | 0.305 | −0.675 |
| | occasional_consistent | 0.357 | mixture, 186, 0.072 | weibull, **187**, **0.210** | 0.051 | 0.279 | −0.298 |
| | regular_charger | 0.357 | mixture, 346, 0.035 | weibull, 346, **0.165** | 0.066 | 0.271 | −0.675 |
| `elaadnl_public_eu` | occasional_consistent | 0.336 | mixture, 5,660, 0.016 | weibull, 5,660, 0.076 | 0.033 | 0.257 | −0.601 |
| | weekly_consistent | 0.332 | mixture, 13,623, 0.022 | weibull, 13,623, 0.097 | 0.031 | 0.262 | −0.571 |
| | regular_commuter | 0.332 | mixture, 32,549, 0.036 | weibull, 32,549, 0.104 | 0.033 | 0.262 | −0.537 |
| `evwatts_workplace_public` | regular_charger | 0.511 | mixture, 1,143,838 †, 0.031 | weibull, 1,084,348, 0.058 | 0.030 | 0.270 | −0.263 |
| | occasional_consistent | 0.305 | mixture, 1,143,838 †, 0.031 | weibull, 152,380, 0.122 | 0.031 | 0.275 | −0.263 |
| | rare_consistent | 0.175 | mixture, 1,143,838 †, 0.031 | weibull, 20,482, 0.116 | 0.032 | 0.286 | −0.174 |
| `inl_residential_legacy` | daily_commuter | 0.500 | single truncnorm, **64**, 0.126 | — none — | — | — | +0.012 |

† = the region's own arrival fit was rejected, so the **pooled** cross-region fit was
broadcast in. For EV WATTS this happened for *every* region, so arrival does not vary
by region in that population.

Abbreviated: near-zero-weight regions are omitted for Caltech (`rare_inconsistent`,
n = 74) and EV WATTS (`rare_inconsistent` n = 467, `erratic` n = 2,031). Bold marks
the cells worth watching — small n or KS above ~0.10.

Regenerate this table: `uv run python -m v2b_syndata.cli calibrate --population <name>`.

### 4.3 Test error (held-out KS)

`tools/validation/validate_calibration.py::s3_holdout` implements the only held-out protocol:
**80/20 split by sorted `user_id`** (deterministic, not random), refit on train with
the same family-selection gate production uses, one-sample KS on the test fold.
Cells need n ≥ 200, test fold ≥ 30, train fold ≥ 50.

**Scope limit: arrival and dwell only. There is no held-out evaluation of arrival
SoC, departure SoC, or the copula anywhere in the repo.**

| Metric | Value |
|---|---|
| median Δ (holdout − train KS), 36 cells | **+0.064** |
| median Δ excluding EV WATTS, 26 cells | +0.069 |
| worst cell | **+0.425** — acn_office001 / regular_charger / arrival (n_test = 62) |
| worst arrival cells | +0.425, +0.372 (acn_jpl/regular_charger, n_test 1,386), +0.241 |
| worst dwell cells | +0.290, +0.281 (both acn_caltech), +0.194 |
| best-generalizing cells | ElaadNL regular_commuter: arrival +0.001, dwell −0.000 |

Selected per-cell rows (full table: `docs/CALIBRATION_RESULTS.md` §S3):

| source | region | variable | n train | n test | KS train | KS holdout | Δ |
|---|---|---|--:|--:|--:|--:|--:|
| acn | occasional_consistent | arrival | 16,052 | 1,261 | 0.042 | 0.093 | +0.051 |
| acn | regular_charger | arrival | 16,864 | 1,860 | 0.052 | 0.286 | +0.234 |
| acn | rare_consistent | dwell | 4,134 | 589 | 0.068 | 0.262 | +0.194 |
| acn_jpl | regular_charger | arrival | 11,782 | 1,386 | 0.023 | 0.395 | +0.372 |
| elaadnl | regular_commuter | arrival | 24,360 | 8,189 | 0.040 | 0.042 | +0.001 |
| evwatts | regular_charger | arrival | 828,517 | 255,831 | 0.024 | 0.071 | +0.046 |

**Read Δ carefully.** The split is by sorted user id, not random, so the test fifth
can be a systematically different cohort (later registrations, a different site mix
in the pooled ACN cut). Large per-cell Δ therefore mixes genuine overfit, cohort
shift, and small-sample noise. The cells with large n and a random-like cohort
(ElaadNL, EV WATTS) generalize well; the small single-site cells do not.

### 4.4 Other committed evidence

| Study | Result | Where |
|---|---|---|
| mixture vs single family (ablation) | ACN mean arrival KS **0.100 → 0.042**; gate fired 14/14 arrival cells, 0.134 → 0.035; dwell 0.127 → 0.102 | `docs/experiments/mixture_ablation.md` |
| pooled-broadcast vs per-region fit | acn/rare_consistent arrival **0.196 → 0.040** | same |
| across-family comparison | arrival: KDE 0.034 / free GMM-2 0.035 / **truncnorm_mix2 0.040** / single truncnorm 0.127. dwell: weibull_mix2 0.072 / weibull 0.118 / lognorm 0.123 / gamma 0.127 / expon 0.187 | `docs/experiments/family_selection.md` |
| forward fidelity, synthetic vs real (S1) | mean \|Δμ\| **0.44 h** over 36 cells; max KS 0.239 [0.146, 0.385] | `docs/experiments/PAPER_NUMBERS.md` §4 |
| copula preservation end-to-end (S2) | max ρ-gap **0.226** (acn_office001) | same |
| weekday/weekend rhythm (S6) | ACN 5.95× real vs 5.73× generated | `docs/CALIBRATION_RESULTS.md` |

KDE and free GMM score better than what ships but **cannot ship**: KDE has no
closed-form inverse-CDF to consume the copula uniform, and a free GMM puts mass
outside the `[4, 22]` arrival window.

---

## 5. Per-building granularity — read this before quoting anything per building

**No distribution is ever fitted per building.** A building descriptor names a
*population*; the population carries the fitted region blocks. Buildings that name
the same population are statistically identical in behavior, differing only through
building load, equipment, weather realization, and seed.

There are two 10-building campus configs, and they differ in a way that matters:

| Config | Populations used | Fitted? |
|---|---|---|
| `configs/campus_base.yaml` (current) | `acn_jpl_office_{high,veryhigh,mid}` | **Yes — ACN-Data** |

> **Historical note.** The 18,000-unit reference corpus in `data/output/campus10/`
> was generated from the former `campus_10.yaml` (now removed), i.e. from
> hand-authored round-number parameters (`arrival: {mu: 8.5, sigma: 0.6}`,
> `dwell: {k: 2.5, lambda: 9.5}`, …) with `calibration_policy: synthetic`, no
> `calibration_metadata`, and no `ks_fit_quality`. There is **no training or test
> error for those buildings, because nothing was trained.** The current
> `campus_base.yaml` replaces it and uses the ACN-Data-calibrated
> `acn_jpl_office_*` populations.
>
> Verify for any released unit — the population is recorded per unit:
> `jq '.buildings[0].descriptors.population' data/output/campus10/b1/JUL2024/0/multi_building_config.json`
> → `"stable_commuter_heavy"`.

Building → model map for the calibrated variant:

| building | archetype | population | underlying fit | distinct fitted model |
|---|---|---|---|---|
| b1 | large_office_v1 | `acn_jpl_office_high` | ACN-Data JPL, 27,799 sessions | JPL |
| b2 | large_office_v1 | `acn_caltech_office_high` | ACN-Data Caltech, 13,395 sessions | Caltech |
| b3 | medium_office_v1 | `acn_jpl_office_mid` | JPL | JPL |
| b4 | medium_office_v1 | `acn_caltech_office_mid` | Caltech | Caltech |
| b5 | medium_office_v1 | `acn_jpl_office_mid` | JPL | JPL |
| b6 | mixed_use_v1 | `acn_caltech_office_low` | Caltech | Caltech |
| b7 | mixed_use_v1 | `acn_jpl_office_low` | JPL | JPL |
| b8 | small_office_v1 | `acn_caltech_office_low` | Caltech | Caltech |
| b9 | small_office_v1 | `acn_jpl_office_low` | JPL | JPL |
| b10 | small_office_v1 | `acn_caltech_office_low` | Caltech | Caltech |

So ten buildings resolve to **two** fitted parameter sets. The `high/mid/low` suffix
changes only the `axes_distribution` region *weights* (how much of the fleet lands in
each archetype: e.g. `regular_charger` 0.70 / 0.55 / 0.40) — the region distributions
are literal YAML aliases (`*acn_jpl_region_dists`) of the same fit. Per-building error
is therefore the JPL or Caltech column of §4.2/§4.3, reweighted.

---

## 6. Known limitations — please carry these when sharing

1. **Arrival SoC is a prior, not a fit.** No charging dataset records SoC.
   `battery_inference.reconstruct_arrival_soc` draws every session's arrival SoC
   from a fixed `N(0.40, 0.15)` clipped to `[0.05, 0.95]`, for every source. The
   Beta is then fitted to those draws — which is why every calibrated region reports
   `Beta(≈3.7, ≈5.6)`, mean 0.398, sd 0.153, i.e. the prior recovered to three
   decimals. **Its `ks_fit_quality ≈ 0.03` measures "Beta ≈ clipped Normal" and
   carries zero information about real arrival SoC.** `GENERATIVE_MODELS.md` records
   the input feature for this quantity as "none — unobserved" and states that no
   model comparison is possible. Never describe arrival SoC as calibrated, and do
   not use this generator for capacity-sensitive SoC analysis.
2. **Departure SoC is the weakest genuinely-fitted marginal** (KS 0.24–0.31, an
   order of magnitude worse than arrival). It is `arrival_soc + kWhDelivered / capacity`,
   so it inherits the arrival prior *and* the ~33% capacity-inference fallback rate,
   and the Beta MLE fights a hard pile-up near 1.0.
3. **`inl_residential_legacy` is a 65-session, 4-user fixture**, not a corpus. It
   fits only `daily_commuter.arrival` (n = 64) plus a copula. Never cite it as a
   calibration dataset.
4. **EV WATTS uses port-as-proxy identity**, so its φ axis describes per-port
   shift consistency, not individual-driver consistency. Its arrival fit is pooled
   across all regions.
5. **The emitted sessions are a truncated view of these marginals.** The renderer's
   D5/D6/D7 rejection loop, the 15-minute grid snap, the same-calendar-day
   constraint and the dwell clip all reshape the sample after the marginals are
   drawn. Measured consequence: sampling the fitted blocks directly reproduces the
   fitted Spearman ρ to within 0.002, but the generator's *emitted* ρ drifts by up
   to 0.226 (S2). Validate against the emitted CSVs, not against the parameters.
6. **`ks_fit_quality` is in-sample.** The generator's S2 soft check surfaces it with
   an explicit warning that held-out validation is deferred. Quote §4.3 for
   generalization, not §4.2.

---

## 7. Where the models live

| What | Path |
|---|---|
| **Fitted parameters (the model artifact)** | `configs/populations.yaml` → `<population>.region_distributions.<region>.{arrival,dwell,soc_arrival,soc_depart,copula}` |
| Provenance per population | same file → `<population>.calibration_metadata` (dataset, sites, year range, n_sessions, capacity-fallback rate, calibration date) |
| Region boxes + weights | same file → `<population>.axes_distribution` |
| Fitting code (MLE/EM + range guards) | `src/v2b_syndata/calibration/distribution_fitter.py` |
| Orchestration, pooled fallback | `src/v2b_syndata/calibration/api.py` |
| Feature extraction (φ, δ_km) | `src/v2b_syndata/calibration/feature_extractor.py` |
| Region assignment | `src/v2b_syndata/calibration/region_assignment.py` |
| SoC prior + capacity inference | `src/v2b_syndata/calibration/battery_inference.py` |
| Dataset normalizers | `src/v2b_syndata/calibration/sources/{acn,elaadnl,evwatts,inl}.py` |
| YAML → runtime parameters | `src/v2b_syndata/samplers/sessions_dist.py` |
| Sampler (copula + inverse-CDF + rejection) | `src/v2b_syndata/renderers/sessions.py` |
| Parameter validity ranges | `src/v2b_syndata/knob_loader.py::DIST_PARAM_RANGES` |
| Validation harness | `tools/validation/validate_calibration.py` |
| Standalone sampler | `tools/data_prep/sample_behavior_standalone.py` |

There is **no pickle, checkpoint, or binary model file.** The entire fitted model is
the human-readable YAML block, which is what makes it auditable and diffable.

---

## 8. Standalone use

### 8.1 Option A — the standalone script (no generator, no EnergyPlus)

`tools/data_prep/sample_behavior_standalone.py` reads the fitted blocks and samples from them
with only numpy/scipy/pyyaml. It is self-contained and can be copied out of the repo.

```bash
# what is available, and which populations are actually calibrated
uv run python tools/data_prep/sample_behavior_standalone.py --list

# 5000 draws from one region, with families + train KS + a sampler self-check
uv run python tools/data_prep/sample_behavior_standalone.py \
    --population acn_workplace_baseline --region regular_charger \
    -n 5000 --seed 42 --report

# draw across all regions using the calibrated user-share weights, write CSV
uv run python tools/data_prep/sample_behavior_standalone.py \
    --population elaadnl_public_eu -n 20000 --out sessions.csv
```

`--report` prints, per region, the selected families, the stored training KS, and a
round-trip KS of the script's own draws against the fitted CDF. That last number
should sit inside the Monte-Carlo band (`1.36/√n`); it validates the sampler, not
the model.

As a library (the script lives in `tools/data_prep/`, which is not an installed package):

```python
import sys; sys.path.insert(0, "tools/data_prep")
from pathlib import Path
import numpy as np
from sample_behavior_standalone import build_models

models = build_models(Path("configs/populations.yaml"), "acn_jpl_baseline")
m = models["regular_charger"]

m.families      # {'arrival': 'truncnorm_mixture', 'dwell': 'weibull', ...}
m.stored_ks()   # in-sample KS recorded at fit time
m.rho           # Gaussian-copula correlation

df = m.sample(10_000, np.random.default_rng(0))
# columns: population, region, arrival_hour, dwell_hours, departure_hour,
#          soc_arrival, soc_depart
```

Verified against the generator: the inverse-CDFs agree to `0.0` for both mixture
families and `~1e-14` for the closed-form single families, and the sampled Spearman
ρ reproduces every fitted `rho_spearman` to within 0.002 across all 12 calibrated
regions. Uniforms are drawn in batch rather than one session at a time, so draws are
**distributionally identical but not bitwise-identical** to a generator run — use the
CLI when you need the reproducibility guarantee.

The script intentionally omits the per-car layers that are not part of the
distribution model: the δ_km SoC shift, the per-car SoC clip band, the D5/D6/D7
rejection loop, the 15-minute snap, and the φ appearance Bernoulli.

### 8.2 Option B — read the parameters yourself

The model is just YAML, so any language can consume it. Arrival, for example:

```python
import yaml, numpy as np, scipy.stats as st

blk = yaml.safe_load(open("configs/populations.yaml"))[
    "acn_workplace_baseline"]["region_distributions"]["rare_consistent"]["arrival"]
lo, hi = blk["trunc_lo"], blk["trunc_hi"]
comps = [(blk["w1"], blk["mu1"], blk["sigma1"]),
         (1 - blk["w1"], blk["mu2"], blk["sigma2"])]

def cdf(x):
    return sum(w * st.truncnorm.cdf(x, (lo - m) / s, (hi - m) / s, loc=m, scale=s)
               for w, m, s in comps)
```

Dwell is `scipy.stats.weibull_min(k, scale=lambda)` (or the analogous 2-component
mixture); both SoC marginals are `scipy.stats.beta(alpha, beta)`. Mixtures have no
closed-form quantile — bisect the monotone CDF, as both the renderer and the
standalone script do.

### 8.3 Option C — fit your own from a charging log

```bash
uv run python -m v2b_syndata.cli calibrate --population <name> [--source-arg ...]
```

This writes fresh `region_distributions` + `calibration_metadata` back into
`populations.yaml`, including recomputed `ks_fit_quality` and empirical
`axes_distribution` weights. Add a normalizer under `calibration/sources/` for a new
dataset. Or call `fit_region(arrivals, dwells, soc_arrivals, soc_departs)` from
`calibration/distribution_fitter.py` directly on your own arrays.

### 8.4 Reproducing the error numbers

```bash
# S1 fidelity + S2 copula + S3 held-out KS -> docs/CALIBRATION_RESULTS.md
uv run python tools/validation/validate_calibration.py --seeds 50 --workers 16 \
    --sources acn,acn_caltech,acn_jpl,acn_office001,elaadnl,evwatts --bootstrap 1000

# everything the paper cites, into docs/experiments/PAPER_NUMBERS.md
uv run python tools/paper/repro_paper.py                      # ~18 min on 32 cores
uv run python tools/paper/repro_paper.py --steps ablation     # mixture ablation only

# held-out 70/30 family comparison (NLL + KS) -> docs/MODEL_SELECTION.md
uv run python tools/validation/model_eval.py --seed 0
```
