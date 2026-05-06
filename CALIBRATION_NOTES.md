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
