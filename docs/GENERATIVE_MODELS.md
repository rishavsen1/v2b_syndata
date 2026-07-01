# Generative models

How every random quantity in a generated dataset is modeled: **which
distribution family** is used, **why that family** was chosen, and **which
ground-truth features** fit its parameters. This is the reference for "why is
arrival time a truncated normal and not a beta?" type questions.

> **On "why this family".** The family choices below were made on *principled*
> grounds — correct support, composability with the copula, interpretable
> parameters — **not** by an empirical contest between candidate families. The
> calibration code records only a single self-KS per quantity, never an AIC/BIC
> comparison. A retrospective model-selection study (see
> [Empirical model selection](#empirical-model-selection-2026-06) and
> `docs/experiments/`) shows where the principled choice matches the data
> (dwell→Weibull) and where the study *motivated a model the generator now
> ships* (arrival→a per-region truncated-Gaussian **mixture**). Read the "why"
> columns as design rationale, and that section for the empirical verdict.

## Two layers

The pipeline separates **calibration** from **generation**:

1. **Calibration** (`v2b-syndata calibrate`, `src/v2b_syndata/calibration/`) —
   fits per-region distribution *parameters* from real charging-session
   datasets (ACN-Data, ElaadNL/4TU, EV WATTS, INL) and writes them into
   `configs/populations.yaml` under `region_distributions.<region>.<dist>`.
   This is an offline, occasional step.
2. **Generation** (`v2b-syndata generate`, `src/v2b_syndata/`) — forward-samples
   CSVs from those parameters (or hand-authored defaults) under a SHA-keyed RNG,
   so a `(scenario, overrides, seed)` triple is bitwise-reproducible.

Every fitted parameter has one of three provenances, recorded per-knob in
`manifest.json`:

- **calibrated** — fit from source data (only where ≥ `MIN_SAMPLES = 30`
  sessions exist for a region; `distribution_fitter.fit_region`).
- **knob** — a tunable in `configs/knobs.yaml` (CLI/scenario-overridable).
- **fixed** — a hardcoded prior/constant in code.

A calibrated fit is **post-clamped** to the validity window in
`knob_loader.DIST_PARAM_RANGES`; if any required parameter lands out of range
(or the MLE fails to converge), the whole distribution is *dropped* and
generation falls back to the hand-authored default — a degenerate fit can never
break generation (`distribution_fitter._drop_if_oor`).

## Summary

| quantity | family | why this family | fit features (source) | parameters · provenance |
|---|---|---|---|---|
| arrival hour | per-region 2-component truncated-normal (Gaussian) mixture on [4, 22]; single TruncNorm(μ, σ) fallback | arrivals are **bimodal** (morning commute peak + midday shoulder), which a 2-component truncated-Gaussian captures, with a hard daytime support (no 3 AM arrivals) | `arrival_hour` (local clock hour of connect) | per-component w/μ/σ · **calibrated** (single μ,σ for synthetic pops); trunc [4,22] **fixed** |
| dwell | Weibull(k, λ), optional 2-component Weibull mixture | non-negative, right-skewed duration; a 2-component mixture is used where it beats single-Weibull by a KS margin | `dwell_hours` (disconnect − connect) | k, λ (per component) · **calibrated** |
| arrival × dwell coupling | Gaussian copula ρ | couples the two marginals (early arrivers stay longer) *without* distorting either marginal — applied on the shared uniform draw | Spearman ρ of (`arrival_hour`, `dwell_hours`) | ρ · **calibrated** |
| arrival SoC | Beta(α, β) on [0, 1] | natural law for a bounded fraction; α/β set mean and skew independently | *none — SoC is unobserved* (see below) | α, β · **fixed prior** (default Beta(4,6) ≈ 0.40) |
| departure-SoC requirement | Beta(α, β), else TruncNorm(μ, σ) | same bounded-fraction argument as arrival SoC; the TruncNorm fallback is a simple high-SoC prior when no source data exists | `arrival_prior + kWhDelivered/capacity` | α, β · **calibrated**; fallback μ/σ · **knobs** (`depart_soc_mu`/`sigma`, default 50/5) |
| region frequency | categorical weights | a car belongs to exactly one behavioral region; weights are just the empirical population mix | per-region **user share** | `axes_distribution[*].weight` · **calibrated** |
| weekend appearance | Bernoulli rate scaling | weekend turnout is a fraction of the weekday rate; one scalar captures the weekday:weekend ratio | weekend vs weekday sessions-per-day ratio | `weekend_activity_factor` · **calibrated** (else knob) |
| DR events | inhomogeneous Poisson(λ(t)) + Uniform magnitude | event arrivals are rare, memoryless, and rate-modulated by season/heat/hour — the textbook point-process model | *not data-fit* — program specs from PG&E/CAISO tariff docs | λ_base, magnitude range · **knobs**; modulation factors **fixed** |
| battery capacity | deterministic inference | physics (range × efficiency), not a distribution | `milesRequested × WhPerMile × 1.5` (ACN only) | per-session inferred, else 60 kWh **fixed** |
| battery mix | Dirichlet(p·α) | the conjugate distribution over a simplex (class shares sum to 1); α tunes per-sample dispersion | *not data-fit* — declared mix | `battery_mix`, `battery_mix_dirichlet_alpha` · **knobs** |
| building load | EnergyPlus simulation | a calibrated building-physics engine, not a statistical model | TMYx weather + ASHRAE occupancy schedule | physical; `peak_kw` scaling · **knob** |
| rooftop PV | PVWatts physics (not fit) | deterministic engineering model from the SAME (perturbed) EPW irradiance/temp EnergyPlus used → weather-consistent with the load | EPW GHI/DNI/DHI + dry-bulb | `pv.*` knobs / `der_catalog` presets · **knobs** |
| stationary battery | specs (knobs) + deterministic dispatch heuristic | capacity/power/efficiency are equipment attributes; dispatch is a rule (peak-shave + TOU arbitrage), not a sampled process | *not fit* | `battery.*` knobs / `der_catalog` presets · **knobs** |
| grid prices | rule-based TOU tape | tariffs are deterministic schedules, not random | *not fit* | peak/off-peak prices, window · **knobs** |
| negotiation mix | categorical | survey-derived behavioral type shares | CONSENT survey (n=28) | `negotiation_mix` · **fixed prior / knob** |

The rest of this document expands each row.

---

## Arrival hour — per-region truncated-Gaussian mixture on [4, 22]

**Models** the clock hour a car connects.

**Why a truncated-Gaussian mixture.** Real arrivals are **bimodal** — a sharp
morning-commute peak plus a midday/afternoon shoulder — which a single normal
underfits (the empirical study cut KS 0.11→0.03 by moving to a 2-component
mixture). Each component is a normal; their sum captures both modes. Arrival hour
also has a *hard physical support*: a Gaussian with realistic spread leaks mass
before dawn / after midnight, which is unphysical and breaks the no-overnight
constraint (C12). The window is `[4, 22]` — wide enough to capture nearly all
real arrivals (the old `[6, 20]` structurally discarded ~8% of ACN arrivals)
while preserving the closed-form truncated quantile the copula needs. A
wrapped/von-Mises circular law would model 24h periodicity, but workplace
charging is not periodic (no 1 AM lobe) and lacks the clean truncated quantile.

**Fit features.** `arrival_hour` = local connect hour + min/60 + sec/3600,
read in the site's wall-clock timezone (`feature_extractor.extract_session`;
ACN is converted UTC→`America/Los_Angeles` before reading the hour).

**How it's fit (per region).** Calibration fits arrival **per region**
(`api._fit_region_arrivals`): each data-rich region gets a 2-component truncated
mixture (`fit_truncnorm_mixture_arrival`), kept **only if** it beats the single
TruncNorm by a KS margin; thin regions fall back to the pooled mixture, and
populations without data to a single TruncNorm. *(This replaced an earlier
pooled-and-broadcast approach that assumed arrival ⟂ the φ/κ/δ axes and
mis-served regions whose arrivals genuinely differ — e.g. `rare_consistent`,
which arrives ~2 h later than the pool.)* Mixture parameters are stored as
numeric leaves `arrival.w1/mu1/sigma1/mu2/sigma2`; generation inverts the mixture
CDF on the copula's shared uniform by bisection (`_mixture_ppf_u`), preserving
determinism + the copula. All calibrated ACN + ElaadNL regions ship a mixture
(22 `truncnorm_mixture` blocks in `populations.yaml`, validated arrival KS ≈
0.07–0.08 vs source); hand-authored/synthetic populations stay on the single
TruncNorm (bit-identical).

**Parameters.** Per-component w/μ/σ (or a single μ, σ) fit by MLE under the
truncation (`fit_truncnorm_mixture_arrival` / `fit_truncnorm_arrival`); the
`[4, 22]` bounds are fixed in three places (`distribution_fitter.ARRIVAL_LO/HI`,
`DIST_PARAM_RANGES`, and `samplers/sessions_dist.py`, the last read per-region
from the calibrated block). Generation samples via the (mixture-)truncated
quantile of the copula's shared uniform (`renderers/sessions.py`).

---

## Dwell — `Weibull(k, λ)`

**Models** how long a car stays plugged in (hours).

**Why Weibull.** Dwell is a non-negative, right-skewed *duration*. Weibull is
the canonical duration/survival family: its shape `k` flexes from
exponential-like (k≈1, many short stays) to bell-like (k>2, a dominant
work-shift length), and it has a closed-form CDF/quantile for the copula. A
log-normal would also fit a right tail but over-weights very long stays; a
gamma is similar but Weibull's hazard interpretation matches "probability of
unplugging in the next minute given still plugged in."

**Fit features.** `dwell_hours` = disconnect − connect, with sub-30-min stays
dropped (metering noise / failed connects, `MIN_DWELL_HOURS = 0.5`) and
> 1-week stays dropped as bogus.

**Parameters.** k, λ via `scipy.stats.weibull_min.fit(arr, floc=0)` (location
pinned at 0 so it stays a true two-parameter Weibull, `fit_weibull_dwell`).

> **Optional 2-component Weibull mixture.** Where a region's dwell isn't
> well-captured by one Weibull (e.g. a short top-up mode plus a full-shift mode),
> calibration fits a 2-component Weibull mixture (`fit_weibull_mixture_dwell`)
> and keeps it **only if** it beats the single Weibull by a KS margin; it is
> sampled by the same bisection inverse-CDF on the copula's shared uniform. A few
> regions ship it (4 `weibull_mixture` blocks in `populations.yaml`); the rest
> stay single Weibull (bit-identical).

---

## Arrival × dwell coupling — Gaussian copula ρ

**Models** the dependence between arrival hour and dwell (early arrivers tend to
stay longer).

**Why a copula.** We want to preserve each *marginal* exactly (the TruncNorm
arrival and Weibull dwell above) while still correlating them. A copula does
precisely that: draw one correlated pair of uniforms, then push each through its
own marginal quantile. Modeling the joint directly (e.g. a bivariate normal on
raw hours) would force both marginals to be Gaussian, throwing away the Weibull
tail. The Gaussian copula is the simplest one-parameter dependence structure.

**Fit features.** Spearman ρ of (`arrival_hour`, `dwell_hours`) — rank
correlation, so it is invariant to the marginal shapes. It is converted to the
Gaussian-copula correlation via `ρ_g = 2·sin(π·ρ_s/6)` and clamped to ±0.99
(`fit_copula_rho`).

**Generation.** A single bivariate-normal draw at correlation ρ produces
(u_arr, u_dwell); each uniform is mapped through its marginal's inverse CDF.
ρ ≈ 0 collapses to independent sampling, RNG-equivalent to the uncoupled path
(`renderers/sessions.py`).

---

## Arrival SoC — `Beta(α, β)` (fixed prior)

**Models** the state-of-charge a car arrives with, as a fraction in [0, 1].

**Why Beta.** SoC is a bounded fraction; Beta is the natural law on [0, 1] and
its two shape parameters set mean (`α/(α+β)`) and skew independently.

**Fit features — none.** **No charging dataset records SoC.** The tempting
reconstruction `arrival = 1 − kWhRequested/capacity` assumes every request tops
the car to full, which the data contradicts (ACN delivered/requested ≈ 0.58,
and `1−req/cap` piles implausibly near 1.0 for small requests). So arrival SoC
is treated as **unobserved** and drawn from a shared normal prior (mean 0.40,
`battery_inference.ARRIVAL_SOC_PRIOR_*`) during calibration, and at generation
from `Beta(α, β)` (default `Beta(4, 6)` ≈ 0.40). A per-car
distance shift `−δ_km·0.003` lowers it for longer commutes before clamping to
the car's `[min_allowed_soc, max_allowed_soc]` (`samplers/sessions_dist.sample_f_soc`,
`renderers/sessions.py`).

> Because arrival SoC is a prior, its `α, β` are effectively **fixed**; the
> `soc_arrival` Beta block is only written when a region has the data, and even
> then it is fit to prior-generated values, so it reflects the prior, not a real
> observation.

---

## Departure-SoC requirement — `Beta(α, β)`, else `TruncNorm(μ, σ)`

**Models** `required_soc_at_depart` — the SoC the car needs by the time it
leaves (which, in this dataset, *is* the departure SoC).

**Why Beta (calibrated path).** Same bounded-fraction argument as arrival SoC.
Here there *is* a real per-session signal to fit.

**Fit features.** `arrival_prior + kWhDelivered/capacity` — the SoC the car
actually left at, using **delivered energy** (the one quantity every source
records). Delivered, not requested: arrival is already a prior, so using
requested would make departure ≈ 1.0 by construction (circular). Departures that
don't exceed arrival are dropped; the rest are fit with `fit_beta_soc(...,
leaf_prefix="soc_depart")` (`calibration/api.py`).

**Why TruncNorm fallback.** For hand-authored populations and sources without
the data, there is no `soc_depart` block. The fallback is
`TruncNorm(μ, σ)` with mean/std from the knobs `user_behavior.depart_soc_mu`
(**default 50**) and `user_behavior.depart_soc_sigma` (default 5), floored at
`user_behavior.min_depart_soc` (**default 0.40**) — i.e. synthetic EVs depart
roughly half-charged with a 40% low-tail floor. (The default was 85/0.80 before
2026-06; lowered so the synthetic prior isn't an arbitrarily high "nearly full"
target. Calibrated cohorts ignore these and use the fitted `soc_depart` Beta
with `min_depart_soc=0`.) Truncation keeps it inside the valid band.

**Constraints at generation.** The draw is clamped to `[floor, ceiling]` where
`floor = max(min_depart_soc%, arrival + ε)` (enforces D7 behavioral floor and
D6 `required > arrival`), `ceiling = max_allowed_soc`; if the target is
unreachable within the dwell at max charger rate it is rejected and resampled
(D5) (`renderers/sessions.py`).

---

## Behavioral axes (φ, κ, δ) and region frequency

A car's behavior is summarized by three axes, sampled from a region's range and
then driving the session marginals:

- **φ (frequency)** — daily appearance probability. Fit per user as
  unique-weekdays-observed ÷ weekdays-in-active-window (a *per-user* window, so
  a sparse-but-regular commuter isn't crushed by a multi-year global
  denominator) (`aggregate_user_features`).
- **κ (consistency)** — `1 − CV(arrival_hour)`, the regularity of arrival time.
- **δ (distance, km)** — `mean(milesRequested) × 1.609` (ACN only; `None`
  otherwise).

**Region frequency** — each car is assigned to one of the behavioral regions
(`stable_commuter`, `flexible_local`, …). The mix weight is the **empirical
per-region user share** (`region_to_users` counts, normalized over assigned
regions, `calibration/api.py`), written to `axes_distribution[*].weight`. User
share, not session share, because the assignment unit is the car. This replaced
a flat hand-authored placeholder that over-produced rare regions ~100×.

**Why categorical user share** (not a fitted continuous law): region membership
is genuinely discrete, and the only honest "parameter" is the observed mix.

---

## Weekend appearance — `weekend_activity_factor`

**Models** the weekend turnout as a fraction of the weekday rate. A car's
per-day appearance probability is φ on weekdays and `φ · weekend_activity_factor`
on Sat/Sun (`renderers/sessions.py`).

**Why one scalar.** Workplace charging is overwhelmingly a weekday phenomenon;
the only thing worth calibrating is the *relative* weekend turnout, so a single
multiplier on the existing φ suffices rather than a separate weekend model.

**Fit features.** `(weekend sessions / unique weekend dates) ÷ (weekday
sessions / unique weekday dates)` — the same sessions-per-day ratio the S6
validator checks, so a generated population reproduces the source's
weekday:weekend ratio (`population_weekend_factor`). 0.0 when the source has no
weekend sessions. Has no effect unless `sim_window.weekdays_only` is false.

---

## DR events — inhomogeneous Poisson(λ(t)) + Uniform magnitude

**Models** demand-response event arrivals and their magnitudes.

**Why an inhomogeneous Poisson process.** DR events are rare, effectively
memoryless, and their rate is strongly modulated by time-of-year, temperature,
and hour-of-day. That is exactly an inhomogeneous Poisson point process:
`λ(t) = λ_base · seasonal(month) · dow(weekday) · temp(maxT) · tod(hour)`. It is
sampled by Lewis's thinning (`sample_dr_events`), then trimmed to per-month /
per-season caps. Magnitudes are drawn Uniform over a program range — a
deliberately flat prior, since real per-event reduction targets are not
published per event.

**Fit features — none (program specs, not data).** The program constants
(season months, notification lead, duration, caps, magnitude range) come from
PG&E tariff docs + CAISO DR reports, hardcoded in `PROGRAM_SPECS` (CBP / BIP /
ELRP). The modulation factor shapes (e.g. heat ramp, afternoon-clustered hour
profile) are fixed model choices. Tunable knobs: `dr_program`,
`dr_lambda_base`, `dr_magnitude_kw_range`. The temperature factor *does* read
real weather — daily max temp from the EnergyPlus EPW — so dispatch correlates
with heat.

> The multi-building export adds two **economic** knobs read by the export layer
> only: `dr_incentive_per_kw` ($/kW on committed reduction) and
> `dr_penalty_per_kwh` ($/kWh on excess). They do not affect event timing.

---

## Battery capacity — deterministic inference

**Models** each car's usable battery (kWh). Not a distribution — a physics
estimate.

**Inference.** `capacity ≈ 1.5 × milesRequested × WhPerMile / 1000` — range ×
efficiency with a 1.5 buffer (users rarely request a full battery). Only
ACN-Data supplies miles + Wh/mi; everything else (and out-of-range estimates,
or ACN's `WhPerMile = 299` sentinel) falls back to **60 kWh**
(`battery_inference.infer_capacity`). Inferred values are bounded to
`[20, 130]` kWh.

**At generation**, the fleet's capacities come from the `battery_mix` simplex
(class capacities 24/40/75/100 kWh), perturbed per-sample by a Dirichlet — see
below.

---

## Battery mix — `Dirichlet(p · α)`

**Models** per-sample variation in the fleet's battery-class shares.

**Why Dirichlet.** The class shares (`leaf_24, bolt_40, m3_75, rivian_100`) live
on a simplex (sum to 1). Dirichlet is the conjugate, natural distribution over a
simplex; parameterizing it as `p · α` keeps the *mean* at the declared mix `p`
while `α` (concentration) tunes dispersion — high α ⇒ effectively deterministic
(default 1e6, preserves reproducibility), batch mode uses α ≈ 30 for ~8% jitter.

**Fit features — none.** The mix `p` is a declared knob (`battery_mix`), not fit
from data. Same Dirichlet machinery drives `axes_distribution_dirichlet_alpha`
for per-sample region-weight jitter.

---

## Non-statistical models

These are part of the generator but are not fit to data:

- **Building load** (`load_pipeline/`) — a real **EnergyPlus** simulation of a
  DOE prototype building under TMYx weather and an ASHRAE 90.1 occupancy
  schedule. The output is rescaled so `max(power_kw) == peak_kw` when
  `peak_kw_scaling` is on. This is building physics, not a sampled distribution.
  There are **two independent perturbation layers**:
  - **Noise layer** (`noise_profiles.yaml`, the `noise.*` knobs) — perturbs the
    *produced* CSVs **after** generation (load/sessions/prices/DR); it never
    touches the weather. The post-sim ±5%/±3% load realism noise is part of it
    and now profile-gated (`noise.load_flex_jitter_pct` /
    `noise.load_inflex_jitter_pct`): the `clean` profile sets them to 0, so
    `clean` output is a **deterministic `load = f(weather, building, occupancy)`**
    — the faithful target for learning `load ← weather`. Other profiles keep
    0.05/0.03 (unchanged).
  - **Weather layer** (`weather_profiles.yaml`, `building_load.weather_*` knobs) —
    the INPUT side. Four channels: `weather_temp_offset_c` (additive °C dry-bulb),
    `weather_dewpoint_offset_c` (additive °C dew-point — the moisture driver;
    relative-humidity is recomputed via Magnus to stay consistent),
    `weather_solar_scale` (×GHI/DNI/DHI) and `weather_wind_scale` (×wind speed,
    drives infiltration). These perturb the EPW EnergyPlus *simulates*
    **and** the exported `weather_data.csv` via one shared transform
    (`weather.perturb_weather_frame` / `perturb_epw_file`), so the exported
    weather always matches the load it produced. It's **per-building** like the
    noise layer: each building picks its own `weather_profile`
    (`slight|moderate|strong`, batch default via `generate-multi
    --weather-profile`, web dropdown in the card's Perturbations panel), and each
    sample draws `temp_offset ~ N(0, σ_T)` and `solar_scale ~ N(1, σ_s)` from its
    seed, logged as explicit overrides (`--weather-sigma-c` still sets σ_T
    directly). Pair with the `clean` noise layer for a pure weather→load signal —
    cross-sample variance then comes from weather, not decoupled output noise.
- **Rooftop / carport PV** (`load_pipeline/pv_model.py`, `samplers/pv.py`,
  `renderers/pv.py`) — a transparent **PVWatts-style** model: isotropic
  plane-of-array transposition of the EPW GHI/DNI/DHI via a closed-form
  NOAA/Spencer solar position, then a NOCT cell-temperature + temperature-
  coefficient + DC/AC-clip conversion. It is **weather-consistent by
  construction** — it consumes the *same* perturbed EPW (via the shared
  `weather.parsed_perturbed_weather` helper) that EnergyPlus simulated and that
  `weather_data.csv` exports, so PV and building load see identical
  irradiance/temperature (including any `weather_solar_scale` perturbation).
  Solar geometry is evaluated at each 15-min tick midpoint and solar time is
  longitude- and standard-meridian-corrected. Pure deterministic physics — no
  RNG. **Default OFF** (`pv.pv_type=none` → zero capacity) → an all-zeros
  `pv_generation.csv` with no EPW read; any preset other than `none` (or an
  explicit `pv.dc_capacity_kw`) turns it on. Ratings come from the `pv.*` knobs or the `der_catalog`
  presets (rooftop_small … rooftop_xl, carport; sized by usable roof area, not
  building peak). Emits `pv_generation.csv` (curve) + `pv.csv` (specs).
- **Stationary battery** (`renderers/battery.py`) — **specs** (capacity,
  power, round-trip efficiency, SoC window). Driven by the `battery.*` knobs /
  `der_catalog` presets (LFP/NMC, 2 h or 4 h). Default OFF → zero capacity.
  Emits `battery.csv`.- **Grid prices** (`renderers/grid_prices.py`) — a deterministic
  time-of-use tape from the `energy_price_peak/offpeak` and `peak_window` knobs.
  Tariffs are schedules, not random variables.
- **Negotiation mix** (`negotiation_mix`) — categorical type shares from the
  CONSENT survey (n=28), a fixed prior surfaced as a knob.

---

## Validation of fits

Each calibrated fit carries a `ks_fit_quality` (Kolmogorov–Smirnov statistic on
the training set — goodness-of-fit, not held-out; C11) and an `n_samples`.
Regions below `MIN_SAMPLES = 30` are not fit (the distribution is `None` →
generation uses the hand-authored default). Out-of-range or non-convergent fits
are dropped with a `RuntimeWarning` so calibration runs surface the issue rather
than silently shipping a degenerate parameter. The forward generator validates
the *output* separately (`validate.py`, the S/D/E/F invariant checks).

> Note this is **goodness-of-fit of the chosen family only** — it does not
> compare against alternative families. That comparison is the next section.

## Empirical model selection (2026-06)

The family choices above were principled, not competed. This retrospective
study (reproducible via `docs/experiments/model_selection.py` and
`model_fit_plots.py`) fits competing families to real ground-truth data —
**ACN-Data** (41,774 sessions, Caltech+JPL+Office001) and **ElaadNL** (55,201,
Utrecht), through the same feature pipeline — and ranks them by AIC / BIC / KS.

| quantity | chosen | input feature(s) | best by AIC | best by KS | verdict |
|---|---|---|---|---|---|
| **arrival hour** | per-region truncated-Gaussian mixture on [4,22] | local connect clock-hour | GaussMix-2 | GaussMix-2 (KS 0.029 vs 0.108 for a single TruncNorm) | **adopted.** The study motivated it and the generator now **ships** a 2-component truncated-Gaussian mixture per calibrated region (single TruncNorm only for synthetic pops); the window was widened [6,20]→[4,22], recovering the ~8% of arrivals the old bounds discarded. Validated arrival KS ≈ 0.07–0.08 vs source. |
| **dwell** | Weibull(k,λ) + optional 2-component Weibull mixture | disconnect − connect | **Weibull** | **Weibull** (KS 0.102) | **empirically vindicated** — best of the standard duration families on the pooled data, JPL, and ElaadNL; Gamma a close 2nd (per-site winner at Caltech). A 2-component Weibull mixture is used where it beats single by a KS margin. |
| **arrival × dwell** | Gaussian copula ρ | Spearman ρ of the two | Frank | n/a | strong **negative** dependence (Kendall τ=−0.44, ρ=−0.60; later arrival → shorter stay), reproduced on ElaadNL. Gaussian ≫ independence but **Frank fits better**; Gaussian kept because it composes with the marginal inverse-CDFs via shared normal scores. |
| **arrival SoC** | Beta(α,β) prior | **none — unobserved** | n/a | n/a | **no model comparison is possible** (no charger records SoC). Honest prior, correctly *not* derived from kWhRequested. |
| **departure SoC** | Beta(α,β) | arrival_prior + delivered/capacity | Kumaraswamy (≈Beta, ΔAIC 114) | TruncNorm | Beta ≈ Kumaraswamy → defensible. **Caveat:** partly synthetic — the real signal is delivered/capacity (mean 0.30); the fit inherits the arrival prior's shape. |

Robustness (dwell AIC-winner per site): Caltech `Gamma`, JPL `Weibull`,
Office001 `Lognormal (n=580)`, ElaadNL `Weibull`. (The earlier per-site
arrival-coverage fractions were measured for the old `[6, 20]` window and no
longer apply — the window is now `[4, 22]`.)

**Takeaway.** Dwell→Weibull and region-weights→empirical-share are well
justified. Arrival — formerly the weakest link (a single unimodal TruncNorm of a
bimodal quantity, clipping ~8% of arrivals) — is now a **per-region 2-component
truncated-Gaussian mixture on [4, 22]** that the generator ships, closing most of
that gap (validated KS ≈ 0.07–0.08 vs source). The copula captures the sign and
bulk of a real, strong negative dependence; departure-SoC Beta is fine but its
fit is partly an artifact of the arrival prior. Full tables + plot in
`docs/experiments/`.
