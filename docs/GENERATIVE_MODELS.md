# Generative models

How every random quantity in a generated dataset is modeled: **which
distribution family** is used (and why that family over the alternatives), and
**which ground-truth features** fit its parameters. This is the reference for
"why is arrival time a truncated normal and not a beta?" type questions.

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
| arrival hour | TruncNorm(μ, σ) on [6, 20] | unimodal commute peak with a hard physical support (no arrivals at 3 AM); a plain normal leaks mass past midnight | `arrival_hour` (local clock hour of connect) | μ, σ · **calibrated**; trunc [6,20] **fixed** |
| dwell | Weibull(k, λ) | non-negative, right-skewed duration with a tunable tail; the standard parametric survival/duration family | `dwell_hours` (disconnect − connect) | k, λ · **calibrated** |
| arrival × dwell coupling | Gaussian copula ρ | couples the two marginals (early arrivers stay longer) *without* distorting either marginal — applied on the shared uniform draw | Spearman ρ of (`arrival_hour`, `dwell_hours`) | ρ · **calibrated** |
| arrival SoC | Beta(α, β) on [0, 1] | natural law for a bounded fraction; α/β set mean and skew independently | *none — SoC is unobserved* (see below) | α, β · **fixed prior** (default Beta(4,6) ≈ 0.40) |
| departure-SoC requirement | Beta(α, β), else TruncNorm(μ, σ) | same bounded-fraction argument as arrival SoC; the TruncNorm fallback is a simple high-SoC prior when no source data exists | `arrival_prior + kWhDelivered/capacity` | α, β · **calibrated**; fallback μ/σ · **knobs** (`depart_soc_mu`/`sigma`, default 85/5) |
| region frequency | categorical weights | a car belongs to exactly one behavioral region; weights are just the empirical population mix | per-region **user share** | `axes_distribution[*].weight` · **calibrated** |
| weekend appearance | Bernoulli rate scaling | weekend turnout is a fraction of the weekday rate; one scalar captures the weekday:weekend ratio | weekend vs weekday sessions-per-day ratio | `weekend_activity_factor` · **calibrated** (else knob) |
| DR events | inhomogeneous Poisson(λ(t)) + Uniform magnitude | event arrivals are rare, memoryless, and rate-modulated by season/heat/hour — the textbook point-process model | *not data-fit* — program specs from PG&E/CAISO tariff docs | λ_base, magnitude range · **knobs**; modulation factors **fixed** |
| battery capacity | deterministic inference | physics (range × efficiency), not a distribution | `milesRequested × WhPerMile × 1.5` (ACN only) | per-session inferred, else 60 kWh **fixed** |
| battery mix | Dirichlet(p·α) | the conjugate distribution over a simplex (class shares sum to 1); α tunes per-sample dispersion | *not data-fit* — declared mix | `battery_mix`, `battery_mix_dirichlet_alpha` · **knobs** |
| building load | EnergyPlus simulation | a calibrated building-physics engine, not a statistical model | TMYx weather + ASHRAE occupancy schedule | physical; `peak_kw` scaling · **knob** |
| grid prices | rule-based TOU tape | tariffs are deterministic schedules, not random | *not fit* | peak/off-peak prices, window · **knobs** |
| negotiation mix | categorical | survey-derived behavioral type shares | CONSENT survey (n=28) | `negotiation_mix` · **fixed prior / knob** |

The rest of this document expands each row.

---

## Arrival hour — `TruncNorm(μ, σ)` on [6, 20]

**Models** the clock hour a car connects.

**Why TruncNorm.** Workplace/commute arrivals cluster around a single morning
peak — a unimodal, roughly symmetric bump — which a normal captures with two
parameters. But arrival hour has a *hard physical support*: a Gaussian centered
at 08:00 with realistic spread puts non-negligible mass before dawn and after
midnight, which is both unphysical and breaks the no-overnight constraint (C12).
Truncating to `[6, 20]` cuts that leakage while keeping the closed-form inverse
CDF the copula needs. A wrapped/von-Mises circular law would model 24h
periodicity but workplace charging is not periodic (no 1 AM lobe), and it lacks
the clean truncated-quantile the copula path relies on.

**Fit features.** `arrival_hour` = local connect hour + min/60 + sec/3600,
read in the site's wall-clock timezone (`feature_extractor.extract_session`;
ACN is converted UTC→`America/Los_Angeles` before reading the hour).

**Parameters.** μ, σ fit by MLE under the truncation
(`fit_truncnorm_arrival`); the `[6, 20]` bounds are fixed in three places
(`distribution_fitter.ARRIVAL_LO/HI`, `DIST_PARAM_RANGES`, and
`samplers/sessions_dist.py`). Generation samples via the truncated-normal
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
the data, there is no `soc_depart` block. The fallback is a high-SoC prior:
`TruncNorm(μ, σ)` with mean/std from the knobs `user_behavior.depart_soc_mu`
(default 85) and `user_behavior.depart_soc_sigma` (default 5) — a narrow bump
near "nearly full," which is a reasonable default target and is now tunable
(previously hardcoded 85/5). Truncation keeps it inside the valid band.

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
  `peak_kw_scaling` is on. This is building physics, not a sampled distribution;
  the only randomness is a small post-sim ±5%/±3% realism noise on flex/inflex.
- **Grid prices** (`renderers/grid_prices.py`) — a deterministic
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
