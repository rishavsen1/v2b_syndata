# Calibration Notes

What was filtered, what fallbacks fired, what caveats apply to the fitted
parameters in `configs/populations.yaml`.

## 1. Filter chain

| Stage | Filter | Notes |
|---|---|---|
| ACN-Data fetch | All sites: caltech, jpl, office001 | per D40 |
| Year window | 2019–2021 inclusive | per D41; 2018 caltech has 0% userID coverage |
| Session validity | `userID != null` | per D40 |
| Per-user filter | `n_sessions >= 5` | drops statistical noise |
| Battery inference | per-session via `WhPerMile` + `kWhRequested` | per D42 |
| Region assignment | first-match in `axes_distribution[*]` order | deterministic |

## 2. Fallback rates

The capacity-inference fallback fires when `WhPerMile` is missing, equals the
ACN-default sentinel value 299, or when miles/kWh requested are absent. The
overall rate is reported at runtime under
`calibration_metadata.capacity_inference_fallback_rate` and printed by
`v2b-syndata calibrate`. A high fallback rate indicates many sessions are
using the 60 kWh default, which biases the arrival-SoC fit toward the
fleet-median assumption.

## 3. δ proxy noise

δ (commute distance) is calibrated against `userInputs.milesRequested`, a
**user-stated charge target, not measured commute**. The miles requested is
a noisy proxy for actual round-trip commute distance because:
- It reflects how much the driver chose to charge for, not how far they drove.
- Direction-of-travel and round-trip ambiguity is unresolved.
- Some users habitually request more than they need (range buffer).

For Step 5, δ stays a hand-specified `dist_km` range per region with the
empirical mean from `milesRequested` reported as a diagnostic only (not
written into `region_distributions`). NHTS-anchored δ calibration is future
work.

## 4. Copula transform bias

The conversion `ρ_gaussian = 2·sin(π·ρ_spearman / 6)` is **exact only for
bivariate-normal copulas**. For the `(arrival_hour, dwell_hours)` joint with
truncnorm × weibull marginals, the transform is biased by < 0.05 in
simulation. Documented but not corrected; correcting would require a
likelihood-based copula fit per region.

## 5. Region overlap and assignment

Region bounds in `axes_distribution` may overlap. Assignment is **deterministic
first-match by axes_distribution order**: the user is assigned to the first
region whose `freq` and `consist` ranges contain `(φ, κ)`. This is enforced
by `tests/test_calibration/test_region_assignment.py::test_assign_first_match_deterministic`.

Users falling outside all regions are tracked under the `__unassigned__`
key. The unassigned rate is reported on `calibration_metadata.unassigned_user_rate`;
investigate if > 20%.

## 6. `ks_fit_quality` semantics

Each fitted distribution carries `ks_fit_quality`, computed as the
Kolmogorov-Smirnov statistic of the fit against the **same data the
distribution was fitted to** (training set). It is a goodness-of-fit
measure on the fit itself, NOT generalization to held-out data. Use it
only as a sanity check that the parametric family is reasonable.

Held-out KS validation (e.g. via train/test split or bootstrap resamples)
is deferred to **Step 5.5**. The placeholder soft check S2 in `validate.py`
emits a warning explaining this when calibration metadata is present.

## 7. Battery capacity sensitivity sweep

The notebook `notebooks/acn_calibration.ipynb` (cell 6) re-fits Beta(soc)
under fixed-capacity assumptions {40, 60, 75, 100} kWh. The reported alpha
and beta range across this sweep characterizes how sensitive the arrival-SoC
distribution is to the capacity heuristic. A wide range indicates the
arrival-SoC distribution should not be used for any analysis where battery
capacity matters quantitatively.

## 8. Required SoC at depart NOT calibrated

The renderer's required-SoC distribution remains the hardcoded
`TruncNorm(85, 5)` in `renderers/sessions.py`. Step 5 calibrates
arrival-SoC only. See DESIGN_NOTES.md item #22.

## 9. First real ACN-Data calibration (2026-05-06)

Run: `acn_data_2019_2021_20260506`. 42,451 sessions / 646 users post-filter.

**Region match against `consent_default`:** 12/646 users assigned (98.1% unassigned).
ACN-Data is overwhelmingly **low-frequency workplace charging** matching the
`occasional_visitor` (878 sessions) and `erratic` (421 sessions) regions. The
high-frequency `stable_commuter`/`flexible_local`/`irregular_distant` regions
get effectively zero ACN coverage.

**Implication:** the hand-specified `axes_distribution` for `consent_default`
does not reflect ACN-Data reality. Two paths forward:
- Re-anchor regions on the empirical (φ, κ) joint observed in ACN.
- Treat ACN as one population (workplace) and source other populations
  (residential, transit fleet) from different datasets.

Deferred to **Step 5.5** with NHTS-anchored δ work.

**B4 guard activations on this run** — fitter dropped 2 distributions whose
MLE estimates fell outside `DIST_PARAM_RANGES`:
- `occasional_visitor.arrival.sigma=6.45` (above `[0.01, 6.0]`)
- `occasional_visitor.soc_arrival.{alpha=267, beta=53}` (above `[0.01, 50.0]`)

The drops are warnings, not errors — generation continues using placeholder
formulas for the dropped distributions. The capacity-fallback rate (33.3%)
contributes to the soc_arrival pathology because many sessions cluster
arrival_soc near 1.0 when `kWhRequested` is small relative to the 60 kWh
default capacity assumption.

**KS fit quality on retained distributions:**
- `occasional_visitor.dwell.ks_fit_quality = 0.119` (Weibull marginal a stretch)
- `erratic.arrival.ks_fit_quality = 0.557` (TruncNorm wrong family for this region)
- Most others < 0.10.

The parametric families chosen (TruncNorm/Weibull/Beta) don't always fit the
empirical marginals; revisit family choice in Step 5.5.

## 10. φ definition fix: per-user active window (Step 5.5 prep)

The original `aggregate_user_features` (commit `cb82e85`) computed
`φ = n_active_weekdays / n_weekdays_in_global_window`. Denominator was the
entire 3-year calibration span, so a user with 22 sessions concentrated in
a 6-month employment window got `φ ≈ 0.07` instead of `~0.7`. Result: 98%
of ACN users fell outside every region in `consent_default` and only 2/5
regions got any users.

Fixed in distribution_fitter / feature_extractor (commit TBD): denominator
is now the **per-user active window** `[first_session, last_session]`. Added
a second filter: `n_weekdays_in_user_window >= 5` to drop users whose active
span is too short for a stable estimate.

Re-run results:
- φ mean 0.074 → **0.201**
- φ max 0.588 → **1.000** (full range reachable)
- Users with φ >= 0.7: 0 → **18**
- Per-region session counts now: stable_commuter=87, irregular_distant=344,
  occasional_visitor=874, erratic=421. flexible_local still 0 (no users in
  that φ × κ box).
- Regions calibrated: 2/5 → **4/5**
- Manifest deep-channel calibrated leaves: 11 → **26**
- `unassigned_user_rate`: 0.981 → **0.952** (still high — see below).

The remaining 95% unassigned rate is a separate issue: most ACN users have
**high κ but low φ** (consistent arrival time, but only a few days per week).
That combination does not match any existing region in `consent_default`,
which pairs high κ only with high φ (stable_commuter) or pairs low φ only
with low κ (occasional_visitor, erratic). Re-anchoring regions on the
empirical (φ, κ) joint observed in ACN is the natural next step.
Deferred to Step 5.5 region re-anchor work.

## 11. Step 5.5: per-population calibration policy

ACN-Data calibration is no longer universal. Each population in
`configs/populations.yaml` declares `calibration_policy`:

- `acn_data` — ACN-Data fitted via `v2b-syndata calibrate`; region grid is
  ACN-anchored. Manifest source: `calibration:<provenance>`.
- `synthetic` — hand-authored `region_distributions`; no real-data fit.
  Manifest source: `hand_specified:<population_name>`. `v2b-syndata calibrate`
  skips with an informative log line.

Future calibration sources (NHTS for δ, EVI-Pro/EVWatts for high-φ commuters)
extend the policy enum without breaking the generator.

### Population assignments

| population | policy | provenance |
|---|---|---|
| `consent_default` | synthetic | hand-authored, domain-informed |
| `acn_workplace_baseline` | acn_data | calibration:acn_data_2019_2021_<date> |
| `stable_commuter_heavy` | synthetic | (region_distributions still TODO) |
| `visitor_heavy` | synthetic | (region_distributions still TODO) |

### Real-ACN run on `acn_workplace_baseline`

`acn_data_2019_2021_20260506`. 42,451 sessions / 646 users post-filter.

| metric | acn_workplace_baseline | (vs old consent_default attempt) |
|---|---|---|
| regions calibrated | **5/5** | 4/5 |
| n_users assigned | **634** | 31 |
| unassigned_user_rate | **0.019** | 0.952 |
| capacity fallback | 0.333 | 0.333 |

Per-region n_samples: rare_consistent 3,848; rare_inconsistent 1,424;
occasional_consistent 15,607; regular_charger 17,857; erratic 1,805.

KS fit quality varies (0.07–0.52); arrival fits are weakest. Family choice
(TruncNorm/Weibull/Beta) revisit deferred. soc_arrival fits are uniformly
high (~0.4); related to capacity-inference fallback rate.

### Manifest stamps after Step 5.5

S01 (consent_default) generation produces 35 deep-channel leaves all
stamped `hand_specified:consent_default`. Generation against
`acn_workplace_baseline` stamps the calibration provenance instead.



## Inflex (lights + equipment) is seasonally variable, not occupancy-static

Initial assumption: power_inflex_kw should be invariant across seasons
since occupancy schedules don't change. Empirical finding: 30-60% seasonal
variation observed across all locations.

Two ASHRAE 90.1 prototype mechanisms explain this:
- Interior daylight-responsive lighting (ASHRAE 90.1 §9.4.1.1): interior 
  lights dim when daylight sensors detect sufficient illumination. 
  Winter = less daylight → higher midday interior lighting load.
- Exterior lighting daylight controls (§9.4.1.4): exterior lights tied 
  to astronomical dark hours. Winter = longer evening dark hours → 
  higher dusk inflex.

E8 analysis should expect:
- flex (HVAC) varies primarily with outdoor temperature
- inflex varies with daylight hours (both interior dimming + exterior on-time)
- Total load = climate × season × daylight, not just climate × season.

## Step 7 finding: ExteriorLights drives apparent inflex seasonal variation

ASHRAE 90.1 MediumOffice prototype includes daylight-controlled exterior
lighting (lights on when sun below horizon). This produces seasonal
inflex variation even with identical occupancy schedules:

Example (San Francisco, 18:00 hour):
  Winter:  181 kW  (sun set by 17:30, lights on)
  Spring:   85 kW  (longer daylight)
  Summer:   73 kW  (sun until 20:00)
  Fall:     93 kW

Implication: power_inflex_kw is NOT occupancy-invariant under varying
sim_window months. For E8 analysis, separate ExteriorLights from
InteriorLights+Equipment if isolating occupancy effect. Otherwise
treat inflex as climate-coupled via daylight hours.


## #12 (Step 7 audit) — D5 rejection couples battery/charger-rate → sessions

`sessions.py:168-173` enforces D5 reachability (`required_kwh ≤ available_kwh`)
via rejection sampling. Threshold uses `max(charger_rate)` and `car.capacity_kwh`,
so changing either shifts the rejection rate, which shifts RNG consumption
within the per-car sessions stream, which produces different session realizations.

Per-node seeding (`seeding.seed_for_car`) prevents cross-renderer RNG bleed.
Within-stream consumption shifts under different feasibility thresholds are
inherent to the rejection scheme.

Architectural by design. `affects_csv` declarations updated to include
`sessions.csv` for:
- `ev_fleet.battery_mix`
- `ev_fleet.battery_heterogeneity`
- `charging_infra.uni_rate_kw`
- `charging_infra.bi_rate_kw`

Implication for E4 experiments: when varying charger rates, sessions will
differ. Aggregate over multiple seeds and treat session variation as
within-condition noise.
