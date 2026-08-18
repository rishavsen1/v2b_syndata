# ACN anonymous-session exclusion — verification + sensitivity

_Regenerate with `uv run python tools/acn_anon_sensitivity.py --csv docs/experiments/acn_anonymous_exclusion.csv`.
Deterministic: no RNG beyond the fixed-seed arrival-SoC prior (`20260613`), which is
held identical across variants. Reads only the cached ACN JSON — no network / API token._

Two questions this answers:

1. Do the committed ACN fits actually exclude anonymous sessions?
2. If they were re-admitted, how far would the generative parameters move?

## What "anonymous" means here

An ACN session is anonymous iff its `userID` is `null`. There is no string
sentinel — every non-null `userID` in the three caches is a numeric string, so
null is the only marker. Anonymous sessions also carry no `userInputs` block,
which is why they can never support capacity inference.

`AcnSource.fetch_sessions` calls `filter_with_userid` before `extract_session`,
so anonymous rows never reach the fitter. This is load-bearing rather than
cosmetic: `extract_session` does `str(raw["userID"])`, so an un-filtered null
would collapse every anonymous row into a single pseudo-driver named `"None"`.

## 1. Verification — the committed fits already exclude them

Session counts reconcile exactly against the committed `calibration_metadata`:

| site | raw sessions | anonymous | after `filter_with_userid` | after dwell filter | committed `n_sessions_total` |
|---|--:|--:|--:|--:|--:|
| caltech | 16,127 | 2,233 | 13,894 | 13,395 | 13,395 |
| jpl | 28,863 | 890 | 27,973 | 27,799 | 27,799 |
| office001 | 1,683 | 1,098 | 585 | 580 | 580 |
| **pooled** | 46,673 | 4,221 | 42,452 | 41,774 | 41,774 |

Re-running calibration for each site on anonymous-filtered data and diffing every
fitted leaf against `configs/populations.yaml` yields **0 parameter differences**
at all three sites, with identical user counts (266 / 379 / 14). The committed
numbers are exactly reproducible from the anonymous-excluded cohort.

## 2. Sensitivity — what re-admitting them would cost

Two variants, both compared against the shipped baseline. Real identified users
are untouched in each, so every delta is attributable to the anonymous rows.
Identified sessions are iterated first and in shipped order so their arrival-SoC
prior draws stay bit-identical — no reported shift is an RNG-stream artifact.

**`literal`** — anonymous sessions get a synthetic `userID` and pass through
`aggregate_user_features` unmodified.

**`forced`** — the pseudo-users bypass `MIN_SESSIONS_PER_USER` and
`MIN_WEEKDAYS_IN_USER_WINDOW`, using the same φ/κ formulas the aggregator would
apply to a one-session user.

### Why a one-session user is degenerate

For n = 1 both behavioral axes are pinned by construction, not estimated:

- **φ** = observed weekdays / weekdays in the active window = 1/1 = **1.0** on a
  weekday (0.0 on a weekend, since the window contains no weekday).
- **κ** = 1 − CV of arrival hour, but a single arrival has zero variance, so the
  `std() == 0` branch fires and κ = **1.0**.
- **δ_km** unobserved (no `userInputs`), and δ is not used for region assignment.

So every weekday anonymous plug-in is classified as a *maximally frequent,
maximally consistent* driver and routed to `regular_charger`; weekend ones land in
`rare_consistent`. None reach `occasional_consistent`. This is an artifact of the
estimator at n = 1, not recovered behavior.

### Cohort damage (`forced`)

| site | region | real users | pseudo-users | synthetic share of users | sessions | synthetic share of sessions |
|---|---|--:|--:|--:|--:|--:|
| caltech | regular_charger | 41 | +1,889 | 97.9% | 5,361 → 7,250 | 26.1% |
| caltech | rare_consistent | 140 | +224 | 61.5% | 2,757 → 2,981 | 7.5% |
| jpl | regular_charger | 102 | +812 | 88.8% | 13,168 → 13,980 | 5.8% |
| jpl | rare_consistent | 108 | +63 | 36.8% | 2,454 → 2,517 | 2.5% |
| office001 | regular_charger | 5 | +1,087 | 99.5% | 346 → 1,433 | 75.9% |

### Parameter movement tracks session dilution, not user count

Each pseudo-user contributes exactly one session, so the fits move with the
*session* share, which is far smaller than the user share:

| site | anon share of `regular_charger` sessions | params changed | largest \|shift\| | params ≥ 10% |
|---|--:|--:|--:|--:|
| jpl | 5.8% | 26 | 3.9% (`soc_depart.alpha`) | 0 |
| caltech | 26.1% | 34 | 23.3% (`soc_depart.beta`) | 3 |
| office001 | 75.9% | 18 | 80.0% (`arrival.sigma1`) | 6 |

Direction of the bias, consistent with anonymous plug-ins being shorter and more
scattered than identified workday sessions:

- **Dwell collapses** — Weibull `k` −13.9% (caltech) / −16.2% (office001);
  `lambda` −8.7% / −14.0%.
- **Arrival widens** — office001 `regular_charger.arrival.sigma1` +80.0%,
  `sigma2` +33.3%, second mode `mu2` +11.5% later.
- **Copula destabilizes** — arrival↔dwell ρ *strengthens* 15.1% at caltech but
  *weakens* 30.7% at office001. Moving in opposite directions by site is the
  signature of noise, not a recovered effect.
- **Capacity inference degrades** — fallback rate 43.7%→51.4% (caltech),
  28.2%→30.4% (jpl), 43.6%→**80.4%** (office001), since anonymous sessions have
  no `userInputs` and always default to 60 kWh.

Per-parameter values for both variants: `acn_anonymous_exclusion.csv` (88 rows).

## Incidental finding — the pooled arrival fallback is broader than the fitted cohort

The `literal` variant leaves the user cohort unchanged at every site (266 / 379 /
14), because a one-session user is rejected by both `MIN_SESSIONS_PER_USER` (5)
and `MIN_WEEKDAYS_IN_USER_WINDOW` (5). It is nevertheless **not** a no-op:
caltech and office001 each shift 5 parameters, jpl none.

The cause is that `pooled_arrivals` in `api._calibrate_one_population` is built
from `sessions_by_uid`, which holds *every extracted session* — not only those of
users who survived the aggregator's filters:

```python
pooled_arrivals = np.asarray(
    [s.arrival_hour for sess in sessions_by_uid.values() for s in sess], dtype=float,
)
```

Regions served by the pooled fallback therefore absorb arrivals from users that
were never assigned to any region. In the shipped pipeline this is harmless —
those sessions belong to real identified drivers who were merely too thin to
model individually — but the fallback pool is genuinely wider than the fitted
cohort, which matters if the pooling is described in the paper.

Two regions currently take that fallback, and they are exactly the two that move
under `literal`:

- **caltech `rare_inconsistent`** — 3 users, 74 sessions. Both the mixture and
  the single TruncNorm arrival fit fail the `DIST_PARAM_RANGES` guard, so the
  region falls back to the pooled caltech mixture. This is why its committed
  `arrival.n_samples` reads 13,234 while its dwell/SoC blocks read 74.
- **office001 `rare_consistent`** — same mechanism (`arrival.n_samples` 579 vs 41).

jpl is untouched because all three of its regions carry their own arrival fits.

## Verdict

Excluding anonymous sessions is correct and already implemented. Re-admitting
them would not add information — it would inject ~4,200 synthetic
`regular_charger` drivers whose φ and κ are pinned to 1.0 by definition, shorten
and widen the dwell/arrival fits in proportion to the dilution, and (at
office001) leave four in five sessions running on an assumed 60 kWh battery.

Separately worth noting for any office001 claim: at 65.2% anonymous it retains
only 14 users and 580 sessions even *with* the exclusion, and its dwell KS
(0.17–0.21) is already the worst of the three sites.
