# Experiments — empirical model selection

Did we pick the right distribution family for each EV-user generative model?
The generator's calibration code records only a single `ks_fit_quality` per
quantity (the chosen family vs its own training data) — it never *competed*
families. These scripts run that competition against real ground-truth data.

## Run

```bash
uv run python docs/experiments/model_selection.py    # AIC/BIC/KS tables
uv run python docs/experiments/model_fit_plots.py    # → model_fit_comparison.png
```

Both load the cached calibration sources (no network / API token needed):
`data/calibration/acn_cache/*.json` (ACN-Data, 41,774 sessions) and
`data/calibration/elaadnl_cache/elaadnl_utrecht_4tu_2024.csv` (ElaadNL, 55,201).
Features are extracted through the **same** `calibration.feature_extractor`
pipeline the generator uses.

## Method

For each quantity, candidate families are fit by MLE and ranked by **AIC**,
**BIC**, and the **Kolmogorov–Smirnov** statistic. For arrival we additionally
report **coverage** (fraction of real arrivals inside the [6,20] truncation
window). For the copula we fit Gaussian + three Archimedean families on the
rank pseudo-observations and report Kendall τ / Spearman ρ / empirical tail
dependence.

## Headline results (ACN-Data pooled, n=41,774; ElaadNL n=55,201 for robustness)

| quantity | chosen family | best by AIC | best by KS | verdict |
|---|---|---|---|---|
| **arrival hour** | TruncNorm(μ,σ)[6,20] | GaussMix-2 | GaussMix-2 (KS 0.029 vs 0.108) | **simplification** — arrival is bimodal; 8.3% of ACN arrivals fall outside [6,20]. Kept for closed-form copula composability + interpretable μ. |
| **dwell** | Weibull(k,λ) | **Weibull** | **Weibull** (KS 0.102) | **vindicated** — best of the standard duration families; Gamma a close 2nd. |
| **arrival × dwell** | Gaussian copula | Frank | n/a | strong **negative** dependence (Kendall τ=−0.44); Gaussian ≫ independence but **Frank fits better**. Gaussian kept for closed-form coupling. |
| **arrival SoC** | Beta prior | n/a | n/a | **unobservable** — no charger records SoC, so no model comparison is possible. Honest prior, not a fit. |
| **departure SoC** | Beta(α,β) | Kumaraswamy (≈Beta) | TruncNorm | Beta ≈ Kumaraswamy, defensible. Fit partly synthetic (real signal is delivered/capacity, mean 0.30). |

**Robustness** (dwell AIC-winner / arrival [6,20] coverage):
Caltech `Gamma / 0.95`, JPL `Weibull / 0.90`, Office001 `Lognormal(n=580) / 1.00`,
ElaadNL `Weibull / 1.00`. Weibull wins on the two largest cohorts; Gamma is the
consistent runner-up. Arrival is bimodal (GaussMix-2 best) on every dataset.

See [`../GENERATIVE_MODELS.md`](../GENERATIVE_MODELS.md#empirical-model-selection-2026-06)
for the full discussion.

## Per-region across-family comparison (2026-07, committed primary)

The tables above are POOLED per-source fits from the 2026-06 study. The
committed, regenerable primary for the paper's "why these families" claim is
now the **per-region** across-family comparison:

```bash
uv run python tools/repro_paper.py --steps family_selection
# → family_selection.csv (per-cell scores) + family_selection.md (aggregates)
```

It scores candidate families per variable (arrival hour, dwell hours,
arrival SoC) on every fitted (source, region) cell — including the shipped
2-component mixtures, which the pooled study predates — with one-sample KS +
AIC/BIC, and records the deployment constraints (KDE: no closed-form PPF on
the copula uniform; free GMM: mass outside the [4,22] h arrival window).
See `family_selection.md`.
