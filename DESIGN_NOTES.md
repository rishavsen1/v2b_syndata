# Design Notes — Step 3 (renderer stubs)

Implementation choices made where the spec was ambiguous. Each is reversible later.

## 1. Sim window: `four_weeks_seasonal` = 28 contiguous days from 2020-04-06

PLAN.md mentions "~7,680 rows" for building_load under this mode but no row-count
interpretation cleanly recovers 7680 = 80 × 96 from "4 weeks" and 15-min sampling.
We treat the figure as approximate and use 28 contiguous days starting Monday
2020-04-06. This yields:
- `building_load.csv` / `grid_prices.csv`: 28 × 96 = 2688 rows
- ~20 weekdays for sessions (subject to φ gating)

Anchor date 2020-04-06 chosen as a Monday in the spring shoulder. To use a different
window, override `sim_window.mode = custom` with `custom_start` / `custom_end`.

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

## 4. `required_soc_at_depart` clamp for D5 reachability

Spec sample step 3 produces `r ~ TruncNorm(0.85, 0.05) clipped to [min_depart_soc, max]`.
Spec invariant D5 requires `(r - arr) * cap / 100 ≤ max_charger_rate * dwell_hr * 1.05`.
For very short dwells with high-capacity batteries this is infeasible at any
`r ≥ min_depart_soc`. We clamp:

```
reachable_max_soc = arrival_soc + max_charger_rate_kw * dwell_hr / capacity_kwh * 100 * 1.05
required_soc      = min(sampled_required_soc, reachable_max_soc)
```

This may produce `required_soc < min_depart_soc` knob value in degenerate cases.
That is acceptable: D4 only requires `required ∈ [car.min_allowed_soc, car.max_allowed_soc]`,
and the knob `min_depart_soc` is not a hard invariant. When `required < arrival`
we have a discharge case and D5 is skipped.

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

## 9. CLI auto-validate runs only on `clean` noise

`v2b_syndata.cli generate` automatically runs the validator on its output, but
only when the resolved noise profile is `clean`. Noise profiles by design
perturb values past hard invariants (e.g. `light_noise` shifts arrival_soc by
~8 percentage points, which can push it below `min_allowed_soc` or break D5
reachability). Skipping auto-validate keeps the post-noise CSVs faithful to
the noise spec; an explicit `cli validate <dir>` still flags the
out-of-bound rows when you want to inspect them.

## 10. `noise.profile` knob is informational only

The active noise profile is selected at CLI / scenario level, not per individual
noise field. The bucketed knobs (`noise.building_load_jitter_pct` etc.) record
the resolved values from the chosen profile. Setting `noise.profile = clean` and
overriding e.g. `noise.building_load_jitter_pct = 0.05` is supported via
`--override`; profile values otherwise win.

## 11. F_SHARE_TOL = 0.20 (4× spec value)

Spec validate_spec.md F4/F5 calls for 0.05 absolute deviation between sample
shares and configured weights. At ev_count=20 this is statistically infeasible
across mid-weight categories — type_ii has weight 0.536, binomial std at n=20
is ~0.11, so within ±0.05 happens <40% of the time. Cross-category multinomial
makes the joint probability of all four categories landing within ±0.05
vanishingly small. Reaching 0.05 reliably needs n ≈ 400. We widen to 0.20 for
v1 (n=20 fleets) and document; the soft check S4 already exists for ψ-tier
distribution sanity. Tighten as scenarios with larger fleets land.
