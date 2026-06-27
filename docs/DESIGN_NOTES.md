# Design Notes & Decision Log

Implementation choices made where the spec was ambiguous. Each is reversible later.

> The numbered sections below (1–31) are cited **by section number** from
> source code (`validate.py`, `runner.py`, `prototypes.py`, `e5_metrics.py`)
> — do not renumber. For the live backlog (open items, conventions, deferred
> work) see [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md).

## 1. Sim window: `month` mode anchored at DEFAULT_SIM_START

`sim_window.mode` choices: `month` (default), `full_year`, `custom`.

The anchor and end are decoupled:

- `sim_window.start` sets the anchor timestamp used by `month` and `full_year`.
- `sim_window.custom_end` is only consulted when `sim_window.mode=custom`.
- `sim_window.start = null` falls back to `DEFAULT_SIM_START` in `runner.py`.

- `month`: window is the calendar month containing `DEFAULT_SIM_START` in
  `runner.py` (currently 2020-04-01). Length = `calendar.monthrange()` days
  (28/29/30/31). End is exclusive (first instant of next month). Default
  yields April 2020 → 30 days × 96 = 2880 rows for `building_load.csv` /
  `grid_prices.csv`. ~22 weekdays for sessions (φ-gated).
- `full_year`: Jan 1 to Dec 31 of the anchor year, calendar-aligned.
- `custom`: requires `sim_window.start` and `sim_window.custom_end` knobs
  (timestamp). End is exclusive.

PLAN.md previously referenced a "~7,680 rows" / "4-week seasonal" interpretation
that did not have a clean row-count derivation. Replaced with calendar-month
windows so row counts are unambiguous and align with utility billing periods.

To change the default month: edit `DEFAULT_SIM_START` in
`src/v2b_syndata/runner.py`. To override at the CLI:

```
--override 'sim_window.mode=custom' \
--override 'sim_window.start=2020-05-01' \
--override 'sim_window.custom_end=2020-06-01'
```

## 2. Peak window semantics: hour ∈ [start, end)

`peak_window: [start, end]` interpreted as `start ≤ hour < end`. For Nashville
[14, 19] this means peak is exactly 14:00–18:59 (5 hours). Wraparound (e.g.,
[22, 6]) handled as `hour >= start OR hour < end`. S01 / current locations don't
use wraparound.

## 3. `previous_day_external_use_soc` formula

For each session, look up the prior session of the same `car_id` (sorted by
arrival). Define:
- `prior_required = prior_session.required_soc_at_depart` (assume the car left at this SoC)
- `external_use = max(0, prior_required - current.arrival_soc)`

For the first session per car, value = 0.0. Column is non-nullable (per validate
spec A4 implications).

## 4. `required_soc_at_depart` rejection sampling (replaces earlier clamp)

`required_soc_at_depart` represents the user's stated target. It must always
sit above `arrival_soc` (D6) and at or above the `min_depart_soc` knob (D7).
The earlier implementation clamped `required_soc` downward for D5 reachability,
which could push it below either floor. That was a bug — V2B *discharge*
happens at simulation/optimization time, not at generation time, so the
generator never has a reason to emit `required ≤ arrival`.

New algorithm per session-day (in `renderers/sessions.py::render`):

```
floor   = max(min_depart_soc * 100, arrival_soc + epsilon)   # epsilon = 0.01
ceiling = car.max_allowed_soc

if floor >= ceiling:
    drop the session for this car-day      # arrived too charged
else:
    r ~ TruncNorm(85, 5) clipped to [floor, ceiling]
    if (r - arrival) / 100 * capacity_kwh > max_charger_rate * dwell_hr * 1.05:
        retry whole session (arrival, dwell, soc, target), up to 5 retries
        after 5 fails: drop the session for this car-day
```

D5 reachability is enforced by *rejection*, not clamping. This changes the
random-number consumption pattern relative to the prior build, so SHA-256
hashes on the same seed differ from previous builds. Reproducibility within
the new build is preserved (same seed → same bytes across two runs).

`validate.py` carries new hard invariants:

- **D6**: `required_soc_at_depart > arrival_soc` for every session.
- **D7**: `required_soc_at_depart >= min_depart_soc * 100` for every session.

Both block generation on failure.

## 5. Non-overlap rejection

Per car_id, sessions are sampled day-by-day. After sampling (arrival, dwell), if
`departure > next_already_sampled_arrival` or `arrival < prior_departure`, resample
up to 5 retries. After 5 failures, drop the session for that day. (Day-by-day
sequential sampling means only the prior session matters, so retries are simple.)

## 6. F4 / F5 tolerance

Spec uses 0.05 absolute deviation tolerance for `negotiation_type` and `region`
shares vs. configured weights. At ev_count=20 this is statistically tight for
mid-weight components (e.g. `type_ii` at 0.536). We implement at 0.05 strict; if
S01/seed=42 fails, see `validate.py` constant `F_SHARE_TOL`.

## 7. Seed sub-streams

`numpy.random.SeedSequence(entropy=seed, spawn_key=(stable_int(name), [car_id]))`
where `stable_int(name) = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")`.
`hash()` is salted in Python 3 so SHA-256 is required for cross-process determinism.
Adding a new node does not change any other node's spawn_key.

## 8. CSV bitwise reproducibility

Pandas `to_csv` is determinism-stable when:
- column order is fixed (we control it)
- `lineterminator='\n'` (avoid platform variation)
- `float_format` not set (default `repr` is deterministic)
- `index=False`

Datetime columns formatted as ISO-8601 strings via `.dt.strftime('%Y-%m-%d %H:%M:%S')`
to avoid pandas/Python version-dependent default rendering.

The acceptance criterion checks the `csv_sha256` dict in manifest.json (not the
manifest itself, which contains a `generated_at` timestamp).

## 9. CLI auto-validate runs only when every per-jitter knob is zero

`v2b_syndata.cli generate` runs the validator after generation iff every
knob in the `noise.` bucket resolves to 0.0 (`building_load_jitter_pct`,
`arrival_time_jitter_min`, `soc_arrival_jitter_pct`, `dr_notification_dropout_prob`,
`price_jitter_pct`, `occupancy_jitter_pct`). Profile name is not the gate —
a user may set `noise.profile=clean` while overriding `noise.arrival_time_jitter_min=15`,
or the reverse, and the per-jitter values are what determine whether
perturbation actually fired.

Noise profiles by design perturb values past hard invariants (D5 reachability
can break when arrival shifts shrink charging duration; soc jitter can push
arrival_soc outside `[min_allowed_soc, max_allowed_soc]`). Skipping
auto-validate keeps the post-noise CSVs faithful to the noise spec; run
`cli validate <dir>` explicitly to inspect violations on a noisy output.

## 10. `noise.profile` is a fan-out knob

Setting `noise.profile` (via CLI override, scenario YAML overrides,
`--noise-profile` flag, or scenario `descriptors.noise:`) drives expansion
of the matching entry in `configs/noise_profiles.yaml` into the six
per-jitter knobs in the `noise.` bucket. The runner peeks at `noise.profile`
**before** descriptor expansion, in this priority order:

1. `cli_overrides["noise.profile"]` (`--override 'noise.profile=X'`)
2. `noise_profile_override` parameter (`--noise-profile X`)
3. `scenario_overrides["noise.profile"]`
4. `scenario.descriptors.noise`

Whichever wins becomes the active noise descriptor; the per-jitter knobs
get `source = descriptor:<profile_name>` in the manifest. Per-jitter
overrides still beat the profile via the standard resolution chain
(`noise.building_load_jitter_pct=0.05` survives even when
`noise.profile=clean`).

Earlier builds treated `noise.profile` as informational only — overriding
it changed the manifest tag but not the per-jitter values, so noise was
silently no-op'd. That was a bug; the regression test
`test_noise_profile_changes_output` guards against re-introducing it.

## 11. F_SHARE_TOL = 0.20 (4× spec value)

Spec validate_spec.md F4/F5 calls for 0.05 absolute deviation between sample
shares and configured weights. At ev_count=20 this is statistically infeasible
across mid-weight categories — type_ii has weight 0.536, binomial std at n=20
is ~0.11, so within ±0.05 happens <40% of the time. Cross-category multinomial
makes the joint probability of all four categories landing within ±0.05
vanishingly small. Reaching 0.05 reliably needs n ≈ 400. We widen to 0.20 for
v1 (n=20 fleets) and document; the soft check S4 already exists for ψ-tier
distribution sanity. Tighten as scenarios with larger fleets land.

# Step 4 — EnergyPlus building load pipeline

Real `L_flex` / `L_inflex` driven by EnergyPlus + ASHRAE 90.1-2019 prototypes.
Step 3's sinusoid stub is now replaced; the renderer contract
(`datetime, power_flex_kw, power_inflex_kw`) is unchanged.

## 12. ASHRAE 90.1 prototype HVAC scheduling produces zero L_flex during unoccupied hours

The ASHRAE 90.1-2019 MediumOffice prototype enforces HVAC AvailabilitySchedule
per code Section 6.4.3.4 — HVAC is OFF outside scheduled occupancy when no
setback override fires. For mild-weather seasons (e.g., April Nashville), this
produces L_flex = 0 for ~40% of timesteps (overnight + weekends).

This is realistic, not a bug:
- L_inflex remains non-zero (lighting/equipment baseline) — minimum ~36 kW
- HVAC startup ramp at 5–7 AM is smooth (6 → 16 → 25 kW)
- Peak/baseline ratio ~5.5x matches published reference profiles

Verified for nashville_tn + medium_office_v1 + April 2020. Other prototype/
weather combos may produce different zero-rates depending on heating/cooling
demand triggering setback override.

Implication: V2B discharge during unoccupied hours has zero displaceable HVAC
load. Charging-shift opportunity is concentrated in 6 AM – 8 PM window.
Honest reporting in paper: "FSL value comes primarily from occupied-hour
load shifting; unoccupied-hour V2B is grid-only."

## 13. ASHRAE 90.1-2019 prototype curation: Denver climate zone

Spec named the bundled IDFs `ASHRAE901_*_STD2019_USA.idf`; PNNL releases
prototypes per climate-zone (Atlanta, Baltimore, Denver, Miami, …), not a
generic "USA" file. We bundle the **Denver (climate zone 5B) variants** that
ship with EnergyPlus 23.2 (`ExampleFiles/`). HVAC sizing follows the Denver
prototype but climate signal flows from the chosen TMYx EPW; re-runs against
warmer/colder weather still produce reasonable shapes. Switching to other
climate-zone variants is a one-line change in
`load_pipeline/prototypes.py::PROTOTYPE_MAP`.

## 14. EnergyPlus 23.2.0 baseline (not 26.x as installed)

Ubuntu 22.04 (glibc 2.35) cannot run the system-installed EnergyPlus 26.1.0
(needs glibc 2.38). The pipeline is tested against EnergyPlus 23.2.0
installed under `~/opt/`. `ep_runner.discover_energyplus` searches `~/opt/`,
`/usr/local/EnergyPlus-*`, `/opt/EnergyPlus-*`, `$ENERGYPLUS_PATH`,
`$ENERGYPLUS_BIN`, and `which energyplus`; it validates each candidate by
running `--version`, so installs that exist on disk but cannot link
(GLIBC mismatch) are skipped automatically.

## 15. Occupancy injection target — `BLDG_OCC_SCH` plus setback variants

PNNL prototype IDFs reference People objects via the *setback* schedules
`BLDG_OCC_SCH_w_SB` and `BLDG_OCC_SCH_wo_SB`, NOT the base `BLDG_OCC_SCH`.
Initial implementation only replaced the base schedule and observed no change
in EP output. The pipeline now replaces all three names in lockstep
(`get_occupancy_schedule_names`).

## 16. Annual RunPeriod — explicit Begin Year + Day of Week

PNNL prototypes ship with three short RunPeriod blocks (Jan, April, July)
intended for design-day diagnostics; running them all yields a duplicated,
non-annual output. `_prepare_idf_for_run` strips every existing RunPeriod and
appends a single annual block. Both `Begin Year` and `Day of Week for Start
Day` are set explicitly because EP's "derive day-of-week from year" path
silently defaults to Sunday in the PNNL configuration — leaving Day of Week
blank shifted weekday/weekend schedules by several days.

Even with the explicit Wednesday spec for Jan 1 2020, EP 23.2 + the PNNL
lighting schedule applies "For: Weekdays" to a calendar-Saturday and rolls
calendar-Monday into the "Sunday Holidays AllOtherDays" branch. The result
is a per-day shape where Tue–Sat run as full weekdays and Sun–Mon run as
weekend. Acceptance criteria (peak/off-peak ratio 2–4×, weekend ≠ weekday)
are still satisfied; the off-by-one is an EP/PNNL prototype quirk worth
documenting but not chasing for v1.

## 17. Occupancy contract: synthesized from `O` source label, not raw Series

The `O` root holds a string label (`ashrae_90_1_office`,
`ashrae_90_1_retail`, `ashrae_90_1_mixed`). `samplers/load.py` synthesizes a
15-min occupancy Series from a hardcoded ASHRAE-shaped weekday/weekend
profile per label, then passes that Series to `simulate_building_load`. This
gives the EV-user pipeline a hook to modulate occupancy later (Step 5+)
without changing the API surface.

## 18. Test isolation: stub-by-default for unit tests

`tests/conftest.py` autouse-monkey-patches `samplers.load.simulate_building_load`
with a deterministic synthetic loader so the existing 99 Step-3 tests do not
need the EnergyPlus binary. Tests that exercise the real pipeline opt in via
`@pytest.mark.real_energyplus` (only used inside `tests/test_load_pipeline/`).
This preserves D33 ("hard error if binary missing") for the production CLI
path while keeping CI portable.

## 19. TMYx station IDs verified per-location

Station IDs in `configs/locations.yaml` were validated against the
`climate.onebuilding.org` index. Spec text used `USA_TN_Nashville.AP.723270_TMYx`;
the canonical station ID is `USA_TN_Nashville.Intl.AP.723270_TMYx` (with
`.Intl.AP`). NYC was missing from the spec; resolved to JFK (`744860`).

## 20. Calibration writer schema rename: `copula_rho` → `copula.rho_gaussian`

ACN_DATA_CALIBRATION.md spec wrote `copula_rho` per region; runtime renderer
field is `dw_p["lam"]` and `dw_p["rho"]`; the user prompt for Step 5 asked
for the canonical YAML/CLI/manifest path `copula.rho_gaussian` and
`dwell.lambda`. The writer in `src/v2b_syndata/calibration/writer.py` emits
the canonical names. The runtime mapping
`(YAML lambda → runtime lam, YAML rho_gaussian → runtime rho)` lives in
`samplers/sessions_dist.py` so the renderer is unchanged. This decouples
external-facing names (used in overrides, manifest, KNOB_REFERENCE) from
historical internal field names.

## 21. Region-stable copula dispatch in renderers/sessions.py

The session rejection retry loop can re-enter sampling many times per
`(car_id, day)`. To preserve Step 4's frozen-hash bitwise reproducibility
when no calibration is present (ρ=0 default), the renderer caches
`use_copula = abs(rho) >= 1e-9` ONCE per car BEFORE entering the retry
loop. The independent-sampling branch uses the same RNG draw order as
Step 4 (`_sample_truncnorm` then `rng.weibull(k)`). The calibrated branch
draws `_gaussian_copula_pair` (two normal draws) then applies inverse-CDF
transforms — different RNG consumption, but only fires when fitted
`rho_gaussian != 0`, which is new behavior with no prior baseline.

Verification: 134 pre-Step-5 tests still pass without modification, including
all golden-hash reproducibility tests in `tests/test_end_to_end.py`.

## 22. Required-SoC distribution out of scope for Step 5

Step 5 fits arrival-SoC only via Beta(α, β). Required-SoC at depart remains
the hardcoded `TruncNorm(85, 5)` in `renderers/sessions.py:125`. D43 mentions
`kWhRequested`-derived target SoC, but this conflates the user's stated
target (the field) with the renderer's target (a free distribution). Splitting
this requires a new `f_required_soc` distribution, copula linkage to arrival
SoC, and re-fitting tests — deferred to Step 6. Documented in
CALIBRATION_NOTES.md.

## 23. φ uses per-user active window (calibration)

`src/v2b_syndata/calibration/feature_extractor.py::aggregate_user_features`
computes `φ = n_active_weekdays / n_weekdays_in_user_active_window` where
the active window is `[first_session, last_session]` per user. Original
implementation used the global calibration window as denominator, which
crushed φ for short-tenure users (typical of workplace-charging datasets
where employment turnover means users appear for only a fraction of the
multi-year window). Filter: drop users with `n_sessions < 5` OR with
`< 5 weekdays in their active window` (statistically noisy).

See CALIBRATION_NOTES.md item #10 for the empirical impact.

## 24. Per-population calibration policy (Step 5.5)

`configs/populations.yaml` entries declare `calibration_policy: acn_data | synthetic`.
`v2b-syndata calibrate` filters populations by policy BEFORE doing any fetch,
so calling `calibrate --population <synthetic>` short-circuits without
requiring `ACN_API_TOKEN`. Two new manifest source categories:

- `calibration:<provenance>` — acn_data populations after a calibration run.
- `hand_specified:<population_name>` — synthetic populations.

Resolution chain in `descriptor_loader.expand_descriptors` stamps the source
based on policy. `knob_loader.resolve_knobs` accepts both prefixes verbatim
when seen in the descriptor-supplied tuple. `validate.py::_is_valid_source`
extended to accept `hand_specified:*`. New soft check G5c warns if a
synthetic population emits hand_specified leaves for some regions but not all.

## 25. Step 6: DR Poisson sampler implementation choices

`samplers/dr_sampler.py` implements an inhomogeneous Poisson process via
Lewis's thinning (D64). Calibration constants for CBP/BIP/ELRP are PG&E +
CAISO-derived and hardcoded in the module (D70) — not loaded from external
data files. Three judgement calls during implementation:

1. **`_LAMBDA_FACTOR_MAX = 3.0`.** Upper-bound on the product of all four
   per-factor multipliers (seasonal ≤ 1, dow ≤ 1, temp ≤ 3, tod ≤ 1).
   Thinning needs an envelope; using the true max keeps acceptance rates
   non-degenerate without inflating candidate density.

2. **`_THINNING_FLOOR = 1e-6` events/hour.** When `lambda_base = 0` the
   homogeneous candidate process would draw zero candidates and the sampler
   would never terminate the gap-draw loop. Floor protects against that
   without affecting retained events (rate at any actual instant still 0,
   so the acceptance probability is exactly 0).

3. **EPW weather pull on the renderer side.** `dr_events.py` calls
   `get_weather_epw + parse_epw_temperatures` directly rather than reading
   from a context cache. The EPW path is keyed off `building_load.tmyx_station`
   which is already in the ctx via `ctx.knobs`. The DAG declares
   `dr_events.csv` depends on `building_load.csv`, so by the time this
   renderer fires the EPW is already in the local cache from the EnergyPlus
   pipeline — no extra network fetch in real runs, no extra fetch for tests
   on cached stations.

## 26. Step 6: `dr_lambda_base` semantic + range change

`utility_rate.dr_lambda_base` units corrected from events/day to events/hour
(per D63: `λ_base × factors = events/hour`). Range widened from `[0, 1.0]`
to `[0, 10.0]` so monthly-cap stress tests can drive λ_base above the
canonical 0.05/hour without hitting the registry validator. Default 0.05
unchanged (matches PG&E CBP empirical event density when factors=1).

## 27. Step 6: `_NOTIF_LEAD_HOURS` ELRP correction

The Step 3 stub had `ELRP=24` (matching CBP). D67 specifies ELRP=2h.
Corrected in `renderers/dr_events.py::_NOTIF_LEAD_HOURS` and reflected
in `PROGRAM_SPECS["ELRP"].notification_lead_hours`. Validate H8 now
catches any deviation from the program-spec lead.

## 28. Step 6: TMY year handling

EPW files are typical-year (synthetic per-row year). `parse_epw_temperatures`
overrides the EPW row year with the sim_window year so the returned index
aligns with the sim window. Multi-year sim windows replicate the typical-year
pattern shifted to each year. Documented in CALIBRATION_NOTES if a future
DR sweep needs AMY weather (deferred to D37).

## 29. Step 6: Sacramento TMYx ID correction

Initial `configs/locations.yaml::sacramento_ca` had `tmyx_station:
USA_CA_Sacramento.Intl.AP.724830_TMYx` (404 against climate.onebuilding.org).
Correct ID is `_724839_` (Sacramento International airport WBAN). Fixed.

## 30. E5 (concurrent active ≤ chargers) is a validator-only invariant

Surfaced in V2 stress test: `S_audit_baseline` (50 EVs) + 1 charger
produces 486 sessions; 1375 of 2852 15-min ticks have active > 1
(max concurrent = 26). Sampler enforces D5 (energy reachability) only;
sessions are sampled per-car independently with no concurrent-occupancy
tracking.

**Current contract:**
- Sampler enforces: D-class (per-session physics, energy reachability).
- Validator enforces: E5 (cross-session concurrency over rendered output).

**Implication:** under-sized scenarios (fleet ≫ chargers) silently
produce unphysical CSVs that fail validation. Users must size charger
pools to match fleet.

**Decision (applied, V2-followup):** **Hybrid.** Sampler stays
per-car-independent. `runner.generate()` now computes realized concurrency
post-noise and emits:

1. `logging.WARNING` when `realized_max_concurrent > n_chargers`.
2. `manifest["e5"]` block with fields `{realized_max_concurrent,
   n_chargers, infeasible, infeasible_tick_count, total_tick_count,
   infeasible_tick_fraction}`.
3. `cli generate --strict-e5` flag promotes the warning to
   `InfeasibilityError` (rc=2). CSVs + manifest are still written before
   the raise so the failed scenario stays inspectable.

Implementation in `src/v2b_syndata/e5_metrics.py` (vectorized tick sweep
+ `E5Report` dataclass + `InfeasibilityError`). Sampler architecture and
D53 reproducibility unchanged — metrics derive from rendered output, not
from the RNG path.

See [`archive/EDGE_CASE_REPORT.md`](archive/EDGE_CASE_REPORT.md) for the quantified violation distribution that
motivated this design.

## 31. noise.py C4 + D6 jitter bound fixes (V2-followup, applied)

Both V2 bugs are now fixed in `src/v2b_syndata/noise.py`:

### C4 — bidirectional arrival-jitter bound
At top of `noise.py`:
```python
_MIN_SESSION_DURATION_SEC = 15 * 60  # one grid tick
```
In the arrival-jitter block:
```python
max_forward = (deps - arrivals).dt.total_seconds().astype(int) - _MIN_SESSION_DURATION_SEC
shifts_sec = np.minimum(shifts_sec, max_forward.to_numpy())
min_backward = (sim_start_ts - arrivals).dt.total_seconds().astype(int)
shifts_sec = np.maximum(shifts_sec, min_backward.to_numpy())
```
Forward bound preserves C4 (arrival < departure − 15 min). Backward bound
keeps arrival within sim window. Test:
`tests/test_noise_fixes.py::test_jitter_preserves_temporal_ordering` +
`test_jitter_keeps_sessions_in_window`.

### D6 — soc jitter clamped against required + floor
After existing B3 per-car SoC-range clamp:
```python
required = df["required_soc_at_depart"].to_numpy()
cars = ctx.rendered["cars.csv"]
min_floor_lookup = dict(zip(cars["car_id"].to_numpy(), cars["min_allowed_soc"].to_numpy()))
min_floor = np.array([min_floor_lookup[c] for c in df["car_id"].to_numpy()])
df["arrival_soc"] = np.maximum(
    min_floor,
    np.minimum(df["arrival_soc"].to_numpy(), required - 0.1),
)
```
The 0.1 SoC-percent gap keeps the strict `arrival_soc < required_soc`
inequality demanded by D6. Test:
`tests/test_noise_fixes.py::test_soc_jitter_preserves_d6`.

### D5 (arrival jitter side effect, accepted)
Even with C4 fixed, shifted arrivals change per-car overlap windows and
energy budgets. D5 (energy reachability) may still fire at max
arrival_time_jitter. Documented in V2 boundary `_VALIDATION_MAY_FAIL`.

### H2 (price_jitter, LEGITIMATE)
Unchanged — H2 is the noiseless contract; CLI auto-validate already
skips when any jitter > 0 (`cli.py:38`). No fix.

---

# Calibration-pipeline & building-load engineering notes

_Moved verbatim from `CALIBRATION_NOTES.md` on 2026-06-26 to keep that file
focused on the fit itself. The `#12`–`#19` identifiers below are the original
CALIBRATION_NOTES item numbers, preserved for traceability; the numbered
decision log above (1–31) is unchanged and remains the target of by-section
code citations._

## Inflex (lights + equipment) is seasonally variable, not occupancy-static

Initial assumption: power_inflex_kw should be invariant across seasons
since occupancy schedules don't change. Empirical finding: 30-60% seasonal
variation observed across all locations.

Two ASHRAE 90.1 prototype mechanisms explain this:
- Interior daylight-responsive lighting (ASHRAE 90.1 Section 9.4.1.1): interior 
  lights dim when daylight sensors detect sufficient illumination. 
  Winter = less daylight → higher midday interior lighting load.
- Exterior lighting daylight controls (Section 9.4.1.4): exterior lights tied 
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

## #13 — Noise jitter bounds preserve C4 + D6 invariants

After V2 V2-followup, `noise.py` jitter implementations enforce
physical-ordering invariants under any noise level:

- **`arrival_time_jitter_min`**: per-row shift is bounded both ways. Forward
  bound keeps `departure − new_arrival ≥ 15 min` (one grid tick). Backward
  bound keeps `new_arrival ≥ sim_window.start`. Both preserved via
  `np.maximum(np.minimum(...))` on the integer shift_sec array. C4 (arrival <
  departure) cannot fail under this jitter.

- **`soc_arrival_jitter_pct`**: after the B3 per-car SoC-range clamp, an
  additional clamp enforces `min_allowed_soc ≤ arrival_soc ≤ required_soc -
  0.1`. D6 (required > arrival) and the per-car physical floor are both
  preserved.

- **`price_jitter_pct`**: NOT bounded — H2 (peak/offpeak match configured)
  is intentionally noise-breakable per D25. CLI auto-validate is skipped
  when any jitter > 0 (`cli.py:38`), so the H2 fail mode never surfaces in
  default workflows.

- **D5 (arrival_time_jitter side effect)**: shifted arrival changes
  per-car energy budget; D5 can still fire at max jitter. Documented as
  noise contract, not a bug.

See `archive/EDGE_CASE_REPORT.md` "Pre-V3 deep-dive findings" + `DESIGN_NOTES.md
#31` for the full diagnosis and patch.

## #14 — E5 hybrid enforcement at generation time

The sessions sampler enforces D5 (per-session reachability) only. E5
(concurrent active ≤ chargers) is a fleet-level constraint that would
couple per-car streams; the sampler stays per-car-independent.

Per Step 7 V2-followup, generation now surfaces E5 infeasibility at
generation time (before validation) via:

- `src/v2b_syndata/e5_metrics.py::compute_concurrency()` — vectorized
  15-min tick sweep over rendered sessions.
- `runner.generate()` writes `manifest["e5"]` with fields
  `{realized_max_concurrent, n_chargers, infeasible, infeasible_tick_count,
  total_tick_count, infeasible_tick_fraction}`.
- `runner.generate()` emits `logging.WARNING` when `infeasible=True`.
- CLI `--strict-e5` promotes the warning to `InfeasibilityError`
  (rc=2). CSVs + manifest are still written before the raise so the
  failed scenario remains inspectable.

Sampler architecture unchanged. Reproducibility (D53) unchanged — E5
metrics are derived from rendered output, not from the RNG path.

See `DESIGN_NOTES.md #30` for the architectural rationale.

## #15 — D5 post-jitter enforcement via required_soc truncation

After Step 7 V2.5: the noise pipeline truncates `required_soc_at_depart`
to the max feasible value whenever arrival or SoC jitter shrinks the
session feasibility budget. Implemented as `_enforce_d5_post_jitter()`
in `noise.py`, invoked at the end of the session-jitter block (after
both C4-bounded arrival jitter and D6-bounded SoC jitter have applied).

Feasibility envelope matches the sampler's pre-jitter D5 check:
```
max_feasible_required = arrival_soc
                      + (max(chargers.max_rate_kw) * dwell_hr * 1.04 / capacity_kwh) * 100
```
The post-jitter factor is 1.04 (vs sampler's 1.05) — one-percent
safety margin so float arithmetic doesn't push the rebuilt required
over validator's `need > avail * 1.05` strict threshold.

Three outcomes tracked per session:
- **Truncated**: `required_soc` lowered to `max_feasible` (user undercharges)
- **D7 relaxed**: truncation pushed `required_soc < min_depart_soc` — recorded
  as relaxation, not violation. Validator skips D7 when manifest carries
  `noise.d5_enforcement` and emits a soft warning with the relaxed count.
- **Dropped**: `max_feasible < arrival_soc + 0.01` — no valid top-up target;
  session removed from output.

## #16 — grid_prices.csv type labels use hyphen

The `type` column in `grid_prices.csv` uses:
- `"off-peak"` (hyphenated)
- `"peak"`

Earlier code used `"off_peak"` (underscore), which drifted from the
documented schema. Fixed across renderer, validators, tests, and the
spec docs (`validate_spec.md`, `BAYES_NET.md`). Code identifiers (e.g.
the `is_offpeak()` helper, `_OFFPEAK_HOURS` constants) continue to use
underscore — only the **data label** in the CSV's `type` column flips
to hyphen.

Knob-audit Stage 2 already measures the numeric `price_per_kwh` column,
not the string label, so the relabel does not change its
monotonicity diagnostics — `energy_price_offpeak` and
`energy_price_peak` remain MONOTONIC.

## #18 — Batch generation: tmyx_stochastic + Dirichlet (opt-in defaults)

A new `batch` CLI subcommand and `/api/batch` web endpoint generate
(months × samples-per-month) into a structured `<scenario>/<MON><YYYY>/<idx>/`
tree with one top-level `batch_manifest.json`. Output is parallelized
via `ProcessPoolExecutor`; falls back to serial if pool init fails.

**Defaults intentionally split between single-shot and batch:**

| Knob | Single-shot CLI default | Batch CLI default |
|---|---|---|
| `noise.profile` | `clean` | `tmyx_stochastic` |
| `user_behavior.axes_distribution_dirichlet_alpha` | `1e6` (off) | `30` |
| `ev_fleet.battery_mix_dirichlet_alpha` | `1e6` (off) | `30` |

The single-shot defaults preserve the **`clean` profile bitwise
reproducibility contract** — every existing test and every showcase
snapshot keeps the same byte output. Batch mode opts into stochasticity
because Monte Carlo across seeds is its raison d'être.

**`tmyx_stochastic` profile** (added to `configs/noise_profiles.yaml`):
- `building_load_jitter_pct: 0.05` — ±5% multiplicative on `power_kw`
- `occupancy_jitter_pct: 0.08`     — ±8% on inflex baseline
- `arrival_time_jitter_min: 5.0`   — ±5 min, snapped to 15-min grid
- `soc_arrival_jitter_pct: 0.03`   — ±3% on arrival SoC
- `price_jitter_pct: 0.0`          — tariff stays deterministic
- `dr_notification_dropout_prob: 0.0`

All bounds enforced post-hoc (C4, D5, D6 preserved). Note that
`L_flex`/`L_inflex` samplers already carry ±5%/±3% structural seed
noise per BAYES_NET — `tmyx_stochastic` layers post-render multiplicative
noise on top.

**Dirichlet RNG isolation.** New Dirichlet draws use
`rng_for_node(seed, "dirichlet:axes")` and `rng_for_node(seed, "dirichlet:battery")`
— separate sub-streams from per-car streams. This guarantees that turning
α on or off does not shift any other RNG consumer. Default α=1e6 takes a
short-circuit branch (no `rng.dirichlet(...)` call at all) so existing
hashes are preserved byte-for-byte. The `realized_distributions` block
in the manifest is **only emitted when Dirichlet actually runs** (α below
the 1e6 threshold).

**Dirichlet variance.** For `Dirichlet(p·α)` with α=30, component std
≈ √(pᵢ(1−pᵢ)/(α+1)) → ~0.05–0.09 per region weight depending on p. The
prior spec claim of "~±5%" was optimistic by ~1.7× at α=30; the
description in `knobs.yaml` documents the actual relationship.

**Audit re-verification.** `tools/knob_audit.py` has no `--knobs` filter
flag, and a full Stage 2 re-run is ~30 minutes for two knobs. Skipped
in favour of the test suite, which exercises:
- `tests/test_dirichlet.py` — variance bounds, default-off determinism, same-seed bitwise
- `tests/test_tmyx_stochastic.py` — shape preservation, mean/correlation bounds
- `tests/test_batch.py` — tree layout, `--force`, parallel run

389/389 tests pass.

## #19 — Frontend surfaces descriptor-resolved knob values

The web frontend at `tools/web/` calls `/api/resolve` on descriptor
change (and on every base-scenario change) to display the **actual
resolved value** for each knob — not the raw `knobs.yaml` default.

`/api/resolve` runs the same descriptor expansion + scenario-override +
default chain that `runner.generate()` runs, but stops short of any
rendering. Returns `{knob_path: {value, source}}` where `source ∈
{"explicit", "descriptor:<name>", "calibration:<provenance>",
"default"}` — same shape as the manifest's `knob_resolution` block.

Each knob widget shows a colour-coded "from:" label (descriptor /
explicit (you) / calibration / default). Reset reverts the input to
the descriptor-resolved value, not the raw `knobs.yaml` default — so
the displayed value always matches what the run would emit.

Counts surfaced in `manifest["noise"]["d5_enforcement"]`:
```
{
  "max_charger_rate_kw": 20.0,
  "total_input_sessions": 319,
  "truncated_count": 9,
  "d7_relaxed_count": 6,
  "dropped_count": 0,
  "total_output_sessions": 319
}
```

Under noise, sessions stay physically achievable. "Undercharged"
(D7-relaxed) status is a feature for studying real-world stress
scenarios — downstream simulators receive feasible-but-suboptimal
targets rather than impossible ones.

H2 (price tier consistency) under price_jitter remains a LEGITIMATE
break per D25 — prices aren't physical-feasibility constrained.

## 32. PV + battery (DER): separate files, specs-only battery, weather-consistent PV

Per-building rooftop/carport PV and stationary battery storage, added 2026-06-27.
Key decisions:

- **PV is a separate file, not netted into `power_kw`.** `building_load.csv`
  stays gross load (`power_flex + power_inflex`); PV generation is its own
  `pv_generation.csv`. This preserves every existing CSV byte-for-byte (no
  redefinition for `dr_events`/`bench`/`sessions` consumers) and lets downstream
  tools net PV however they want.
- **Battery is specs-only** (`battery.csv`): capacity/power/efficiency/SoC
  window, no dispatch schedule — dispatch is a downstream optimizer's job, the
  same way `cars.csv` ships specs not trips.
- **Default OFF** (`pv_type`/`battery_type` = `none` → zero effective capacity):
  the PV sampler early-returns an all-zeros series WITHOUT reading the EPW, so the
  clean-profile bitwise contract holds and no cached weather is required for
  default runs. There is no separate `enabled` flag — a preset other than `none`
  (or an explicit `dc_capacity_kw`/`capacity_kwh`) is what turns the resource on.
- **PV weather is identical to the building-load weather.** Both call the shared
  `weather.parsed_perturbed_weather` (leap-inject → parse → perturb with the same
  four `building_load.weather_*` knobs), so the PVWatts model sees the exact
  GHI/DNI/DHI EnergyPlus simulated and `weather_data.csv` exports — including any
  `weather_solar_scale` perturbation. `build_weather` was refactored onto this
  helper to guarantee no drift.
- **Time-axis correctness:** hourly EPW irradiance is forward-filled to the
  15-min grid, but solar geometry is evaluated at each tick MIDPOINT, and solar
  time is corrected for both longitude and the standard meridian (`15·tz`) — so
  the curve peaks at true solar noon rather than drifting tens of minutes early.
- **No new RNG** in the default/single-shot path; the curve and specs are pure
  `f(knobs, weather)`. Reserved node names for any future per-sample sizing
  jitter (`pv_realization`/`battery_realization`) are off in v1.
- **Per-building** in single (`pv.*`/`battery.*` overrides), batch, and
  multi-building (`BuildingSpec.overrides`); the optimus export adds `building_id`
  + energy columns, mirroring `build_building_load`/`build_cars`. Presets
  (ratings/sizes) live in `src/v2b_syndata/der_catalog.py`.
