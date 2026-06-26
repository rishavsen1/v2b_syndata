# Edge-Case Stress Test Report (V2)

Generated: 2026-05-19
Test file: `tests/test_edge_cases.py`
Total: 45 boundary tests + 3 stress tests = **48 tests, 48 pass**

## Per-test outcomes

Every test asserts:
1. `runner.generate()` raises no exception.
2. All schema CSVs exist + are NaN/Inf-free (numeric columns).
3. `validate()` passes (modulo documented `_VALIDATION_MAY_FAIL` cases).

| Knob | Boundary | Scenario | Outcome | Notes |
|---|---|---|---|---|
| ev_fleet.ev_count | 1 | S01 | ✅ | F4/F5 share invariants skipped (single sample) |
| ev_fleet.ev_count | 100 | S_audit_baseline (chargers=100) | ✅ | 200 cap × 100 charger cap can't satisfy E5; clamp to 100 EVs |
| ev_fleet.battery_mix | [1,0,0,0] | S01 | ✅ | F3 capacity-share skipped (degenerate mix) |
| ev_fleet.battery_mix | [0,0,0,1] | S01 | ✅ | F3 skipped |
| ev_fleet.battery_heterogeneity | homog | S01 | ✅ | F3 skipped |
| charging_infra.charger_count | 100 | S_audit_baseline | ✅ | max |
| charging_infra.directionality_frac | 0.0 | S01 | ✅ | all uni |
| charging_infra.directionality_frac | 1.0 | S01 | ✅ | all bi |
| charging_infra.uni_rate_kw | 3.3 | S01 | ✅ | slowest L1 |
| charging_infra.uni_rate_kw | 350.0 | S01 | ✅ | fastest DCFC |
| charging_infra.bi_rate_kw | 3.3 / 350.0 | S01 | ✅ | both boundaries |
| user_behavior.min_depart_soc | 0.5 / 1.0 | S01 | ✅ | min + must-depart-full |
| user_behavior.w_multiplier | [0.1, 0.1] | S01 | ✅ | very flexible |
| user_behavior.w_multiplier | [5.0, 5.0] | S01 | ✅ | very inflexible |
| user_behavior.external_charge_cost | 0.10 / 1.00 | S01 | ✅ | min + max |
| user_behavior.negotiation_mix | [1,0,0,0] | S01 | ✅ | F1/F2 share skipped |
| user_behavior.negotiation_mix | [0,0,0,1] | S01 | ✅ | F1/F2 share skipped |
| building_load.peak_kw | 50.0 / 5000.0 | S01 | ✅ | tiny + massive |
| utility_rate.energy_price_offpeak | 0.05 / 0.50 | S01 | ✅ | |
| utility_rate.energy_price_peak | 0.05 / 0.80 | S01 | ✅ | inverted (0.05) accepted |
| utility_rate.peak_window | [0, 23] | S01 | ✅ | full-day peak |
| utility_rate.peak_window | [12, 13] | S01 | ✅ | 1-hour peak |
| utility_rate.demand_charge_per_kw | 0.0 / 50.0 | S01 | ✅ | |
| utility_rate.dr_lambda_base | 0.0 | S_dr_cbp | ✅ | empty dr_events.csv accepted |
| utility_rate.dr_lambda_base | 10.0 | S_dr_cbp | ✅ | per-month cap still enforced |
| utility_rate.dr_magnitude_kw_range | [0.0, 0.0] | S_dr_cbp | ✅ | zero-magnitude events |
| utility_rate.dr_magnitude_kw_range | [900.0, 1000.0] | S_dr_cbp | ✅ | massive |
| sim_window.weekdays_only | True / False | S01 | ✅ | weekend inclusion |
| noise.building_load_jitter_pct | 0.50 | S01 | ✅ | validate skipped (50% jitter) |
| noise.arrival_time_jitter_min | 60.0 | S01 | ✅ | validate skipped |
| noise.soc_arrival_jitter_pct | 0.30 | S01 | ✅ | validate skipped |
| noise.dr_notification_dropout_prob | 1.0 | S_dr_cbp | ✅ | dr_events.csv empty by design |
| noise.price_jitter_pct | 0.30 | S01 | ✅ | validate skipped |
| noise.occupancy_jitter_pct | 0.30 | S01 | ✅ | validate skipped |

### Stress tests

| Test | Scenario | Outcome |
|---|---|---|
| `test_extreme_undersize_charger_pool` | S_audit_baseline + 1 charger × 3.3 kW | ✅ E5 expected to flag (sampler doesn't enforce); schema + referential OK |
| `test_single_ev_fleet` | S01 + ev_count=1 | ✅ schema/referential pass; F4/F5 share invariants skipped |
| `test_inverted_tariff` | peak=0.10, offpeak=0.30 | ✅ accepted; H2 verified peak < offpeak |

## Findings

### Knob-pipeline contract observations

- **D5 reachability** (sessions.py:168-173) is the only feasibility check the
  sampler enforces. **E5 concurrency** (active ≤ chargers) is a *validator*
  invariant — the sampler does not pre-allocate slots; under
  pathological knob combinations (massive ev_count vs tiny chargers) E5 can
  trip. Documented in `DESIGN_NOTES.md` #12 (moved from CALIBRATION_NOTES, 2026-06).
- **Degenerate population fractions** (single negotiation type / single
  battery class / 1 EV) cleanly violate F1-F5 share invariants by
  construction. The sampler generates correctly; only the validator's
  population-matching checks fail. Boundary is reachable via legitimate
  override paths but unusual for experiments.
- **Heavy post-render jitter** (≥0.30 multiplicative or 60-minute arrival
  shift) can intermittently break C-series temporal-consistency invariants
  (e.g. arrival jitter pushing sessions past the sim_window bound). The
  pipeline doesn't clip post-jitter — accepting that real noise breaks
  invariants is consistent with D25 design.
- **Inverted tariff** (peak < offpeak) flows through cleanly. Simulator's
  job to interpret the inverted signal.

### Validation invariant categorization at the boundary

| Invariant class | Survives all 45 boundary cases? |
|---|---|
| A (schema) | ✅ Yes |
| B (referential integrity) | ✅ Yes |
| C (temporal consistency) | ⚠️ Breaks under heavy time-jitter (documented in noise.* skips) |
| D (physical/SoC) | ✅ Yes |
| E (charger/capacity) | ⚠️ Breaks at 1-charger × 50-EV stress case (sampler doesn't enforce) |
| F (CONSENT share) | ⚠️ Breaks at single-population-type knobs (degenerate by design) |
| G (behavioral axes) | ✅ Yes |
| H (tariff/DR) | ✅ Yes |
| I (manifest) | ✅ Yes |

## Pre-V3 deep-dive findings

After V2, the C-class + E-class "documented exceptions" were investigated
case-by-case (probe per knob at max; classify the exact invariant that fires).

### C-class jitter — per-knob breakdown

| Knob (at max) | Errors observed | Verdict |
|---|---|---|
| `noise.building_load_jitter_pct=0.50` | none | ✅ clean |
| `noise.arrival_time_jitter_min=60.0` | **C4** + D5 | ❌ **REAL BUG** |
| `noise.soc_arrival_jitter_pct=0.30` | **D5 + D6** | ❌ **REAL BUG** |
| `noise.price_jitter_pct=0.30` | H2 (peak/offpeak match) | ⚠️ LEGITIMATE |
| `noise.occupancy_jitter_pct=0.30` | none | ✅ clean |
| `noise.dr_notification_dropout_prob=1.0` | none (empty events) | ✅ clean |

#### C4 under arrival_time_jitter — REAL BUG

**What fires:** `C4: arrival >= departure`. At t_jit=60 min, the Gaussian
shift on arrival can land past the (unchanged) departure timestamp →
`new_arrival > departure` → negative duration_sec.

**Source code:** `src/v2b_syndata/noise.py:64-70` shifts only arrival,
keeps departure fixed, recomputes `duration_sec = departure − new_arrival`.
No bound on `shifts_sec` versus current `duration_sec`.

**Violated data:** session with original (arrival=08:00, dep=12:00, dur=4h).
Jitter sample +5h → new_arrival=13:00 > dep=12:00. duration_sec becomes
negative.

**Proposed fix (not applied):** clip per-row shift so `new_arrival` stays
strictly less than the original `departure − ε`:

```python
# In noise.py near line 64, before applying shifts_sec:
max_forward_shift = (deps - arrivals).dt.total_seconds().astype(int) - 60
shifts_sec = np.minimum(shifts_sec, max_forward_shift)
# Optional symmetric guard: also prevent shifting earlier than sim_window_start.
```

This preserves C4 by construction; the noise still spans most of the
sampled distribution because sessions with dur ≫ 1 min remain unconstrained.

#### D5/D6 under soc_arrival_jitter — REAL BUG

**What fires:** `D5: session unreachable (need > avail)` and
`D6: required_soc_at_depart <= arrival_soc`. soc jitter shifts
arrival_soc additively. When jittered up past required_soc, D6 fires
(arrival already meets requirement → no need to charge but
required > arrival violated). When jittered down hard, the resulting
energy need exceeds time × rate, D5 fires.

**Source code:** `src/v2b_syndata/noise.py:71-78`. B3 fix clamps to per-car
`[min_allowed_soc, max_allowed_soc]` but does NOT re-clip against
per-session `required_soc_at_depart`.

**Violated data:** session with (arrival_soc=85, required_soc=95). Jitter
sample +15 → new_arrival_soc=100 (clamped to max=100) but required_soc=95
stays. Now arrival_soc=100 > required_soc=95 → D6.

**Proposed fix (not applied):** after the existing per-car clamp, also clip
the jittered arrival_soc to ≤ `required_soc - ε`:

```python
# After the B3 per-car clamp:
required = df["required_soc_at_depart"].to_numpy()
df["arrival_soc"] = np.minimum(df["arrival_soc"].to_numpy(), required - 0.1)
```

This preserves D6. D5 is harder — fixing requires either reducing
jitter magnitude near the feasibility boundary or co-jittering
required_soc UP to keep need ≤ avail. Recommend addressing D6 first
and leaving D5 as a separate decision (D5 says "physically impossible
charge"; noise that creates impossible charges is arguably a contract
violation).

#### H2 under price_jitter — LEGITIMATE

**What fires:** `H2: peak prices != configured`. H2 asserts grid_prices
rows have the configured peak_price exactly. Jitter perturbs them by
design → fails.

**Verdict:** LEGITIMATE. H2 is a design-time invariant on the noiseless
output. The CLI already auto-validates only when `_all_jitters_zero`
is true (`src/v2b_syndata/cli.py:38`), so production users won't hit
this. The validator's check itself remains correct as a noise-free
contract. No fix needed.

#### D5 under arrival_time_jitter — side effect

**What fires:** D5 after arrival shift. Shifting an arrival changes its
overlap with the previous session and its available charging window,
which changes available energy.

**Verdict:** Resolves once C4 is fixed (proper shift clipping bounds
arrival within a feasible window).

### E-class undersize — quantified

Test: `S_audit_baseline` (50 EVs) + `charger_count=1` + `uni_rate_kw=3.3` + all uni.

| Metric | Value |
|---|---|
| Total sessions generated | 486 |
| 15-min ticks in sim window | 2852 |
| Ticks where `active > 1` (E5 violation) | **1375 (48%)** |
| Max concurrent active sessions | **26** |
| Days with violations | 22 of 22 weekdays |
| Peak hours (most violations) | 8:00–13:00 (88 ticks each) |

**Current architecture:** sampler enforces only D5 (energy reachability).
E5 (concurrent capacity) is a *validator* invariant on rendered output.
Sessions are sampled independently per-car. Under extreme
fleet:charger imbalance the validator surfaces the infeasibility but
the rendered data is unphysical — 26 cars simultaneously plugged into
1 charger.

**Architectural decision for Rishav** (documented in
`DESIGN_NOTES.md #30`):

- **Option B (current):** Sampler stays per-car-independent. Validator
  reports E5 as scenario infeasibility. Users must size charger pools
  to fleet. Simple; preserves reproducibility; calibration-friendly.
- **Option A:** Sampler enforces E5 via session-level rejection that
  tracks concurrent occupancy. More realistic data but breaks per-car
  independence + complicates calibration.
- **Hybrid:** Add a `feasibility-check` CLI command + manifest warning
  when realized E5 violations exceed a threshold. Keeps sampler simple
  while surfacing the issue earlier than full validation.

Recommendation: **adopt Hybrid**. Keeps sampler simple; surfaces
infeasibility at generation time rather than only at validation;
allows users to opt out for stress-testing or calibration scenarios.

## V2-followup status (applied)

Both jitter fixes and E5 hybrid enforcement landed; see DESIGN_NOTES
#30 + #31 and DESIGN_NOTES #13 + #14 (moved from CALIBRATION_NOTES, 2026-06).

| Item | Status |
|---|---|
| C4 jitter bound (`noise.py`) | ✅ applied; 15-min forward + sim_start backward |
| D6 jitter bound (`noise.py`) | ✅ applied; clamp arrival_soc to [min_floor, required−0.1] |
| D5 post-jitter truncation (`noise.py`) | ✅ applied; `_enforce_d5_post_jitter` + manifest stats |
| E5 hybrid: warning + manifest + --strict-e5 | ✅ applied; `e5_metrics.py` + runner + CLI |
| H2 under price_jitter | ⚠️ LEGITIMATE (noise contract); only remaining skip |

Test files: `tests/test_noise_fixes.py` (10 tests — 5 from C4/D6, 5 from D5)
+ `tests/test_e5_hybrid.py` (6 tests). V2 boundary skip set: down from
3 to 1 (price_jitter only).

V3 (pairwise interactions) ready.
