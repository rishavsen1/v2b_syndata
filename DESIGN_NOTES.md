# Design Notes — Step 3 (renderer stubs)

Implementation choices made where the spec was ambiguous. Each is reversible later.

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
