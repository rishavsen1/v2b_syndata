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
