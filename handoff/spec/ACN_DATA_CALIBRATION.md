# ACN-Data Calibration Plan (v3)

Standalone workstream for fitting per-region distribution parameters used by Tier 1.5 (`A_user`) and Tier 2 (`f_arr`, `f_dwell`, `f_soc`). Runs after Step 3 (renderer stubs) and before Step 5 (full S01 generation).

## Objective

Replace hand-specified parameters in `populations.yaml` with values fit to ACN-Data. Three calibration targets:

1. **A_user marginal distribution** — empirical distribution of (φ, κ) across users in ACN-Data; calibrates region-grid weights and bounds in `axes_distribution`
2. **Per-region (f_arr, f_dwell, f_soc) marginals** — TruncNorm / Weibull / Beta parameters per region
3. **(arrival, dwell) copula correlation** — Gaussian copula ρ per region

## Data

**ACN-Data** — Caltech / JPL / Office001 sites, public release.
- ~50k+ workplace charging sessions
- Per-session: connectionTime, disconnectTime, kWhDelivered, doneChargingTime, userID, stationID, sessionID
- Multi-day persistence observable via userID
- No SoC reported directly — reconstruct arrival_soc from kWhDelivered + assumed battery capacity

## Pipeline

### Step 1: Per-user feature extraction (A_user empirical)

For each unique `userID`:

| Feature | Formula |
|---|---|
| `phi_observed` | (# weekdays with ≥ 1 session) / (# weekdays in observation window) |
| `kappa_observed` | 1 − CV(arrival_hour) across user's sessions; CV = std/mean |
| `delta_km_observed` | Not directly observable in ACN-Data. v1: drop and rely on hand-specified region ranges. Future: NHTS-anchored. |

Filter users with < 5 sessions (statistical noise).

Output: `data/calibration/acn_per_user.csv` with one row per userID.

### Step 2: Region calibration

**Approach B (manual bounds, weight calibration)** for v1:
- Keep hand-specified region bounds from `populations.yaml`
- Fit only the weights: count fraction of ACN-Data users falling into each region's (φ, κ) box
- Normalize to sum to 1

(Approach A — k-means cluster discovery in (φ, κ) space — is upgrade path if reviewers demand data-driven taxonomy.)

### Step 3: Per-region (f_arr, f_dwell, f_soc) marginal fits

For each region (defined by its (φ, κ) box):
- Subset ACN-Data users falling into this box
- Subset their sessions

Fit:
| Distribution | To | Method |
|---|---|---|
| TruncNorm(μ_arr, σ_arr) | arrival_hour samples | MLE; truncate at [0, 24] |
| Weibull(k, λ) | dwell_hours samples | MLE via `scipy.stats.weibull_min.fit` |
| Beta(α, β) | arrival_soc (reconstructed from kWhDelivered / capacity_assumed) | MLE; clip to (0, 1) |

Per-region parameters write to extension of `populations.yaml`:

```yaml
consent_default:
  ...
  region_distributions:    # NEW, populated by calibration
    stable_commuter:
      arrival: {dist: truncnorm, mu: 8.7, sigma: 0.6}
      dwell:   {dist: weibull,   k: 2.1, lambda: 9.2}
      soc_arrival: {dist: beta,  alpha: 4.5, beta: 6.1}
      copula_rho: -0.18
    ...
```

### Step 4: Copula correlation per region

For each region:
- Compute Spearman ρ between arrival_hour and dwell_hours within region
- Translate to Gaussian copula correlation: ρ_gaussian = 2 sin(π ρ_spearman / 6)
- Store as `copula_rho` per region

If |ρ| < 0.15 across all regions, document and skip copula (independent sampling acceptable).

### Step 5: Validation

- KS test: generated arrival distribution vs ACN-Data per region (target < 0.10)
- KS test: generated dwell vs ACN-Data per region
- Compare A_user empirical (φ, κ) of generated `users.csv` against ACN-Data — should be statistically indistinguishable

## Outputs

| File | Content |
|---|---|
| `configs/populations.yaml` | Updated with `region_distributions` block per population entry |
| `notebooks/acn_calibration.ipynb` | Reproducible fitting notebook |
| `data/calibration/acn_per_user.csv` | Per-user empirical features |
| `data/calibration/acn_per_region_stats.csv` | Per-region empirical stats (sample sizes, fit quality, ρ values) |
| `tests/test_distributions.py` | KS tests against fitted ACN-Data marginals (soft check S2) |

## Caveats

- ACN-Data is **workplace charging dominant** — visitor / retail behavior under-represented. The `visitor_heavy` and `occasional_visitor` regions calibrate poorly. Acceptable for v1; flag in paper limitations.
- δ (commute distance) cannot be observed in ACN-Data — stays hand-specified. Future: NHTS commute survey calibration.
- Multi-site differences (Caltech vs JPL vs Office001) not modeled — data pooled. Could stratify if needed.
- Battery capacity assumption for SoC reconstruction introduces bias. Sensitivity check: compare SoC fits under capacity ∈ {40, 60, 80} kWh.

## Dependency status

This plan **does not block Step 3.** Stubs use hand-specified defaults from current `populations.yaml`. Calibration replaces those defaults later. Regenerating S01 with calibrated values is one command.
