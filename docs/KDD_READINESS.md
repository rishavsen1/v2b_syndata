# KDD 2027 Datasets & Benchmarks — Readiness & Action Plan

Living tracker for getting `v2b_syndata` to a submittable state for the KDD
Datasets & Benchmarks track (category: **Data Generators and Environments**,
which requires *both* a quantification of representativeness *and* a proof of
utility). Created 2026-06-28.

> Companion to `docs/PROJECT_TRACKER.md` (the general backlog). This file is the
> submission-specific view. Status legend: ☐ not started · ◐ in progress · ✅ done.

## Execution decisions (2026-06-28)
- **Mode:** tasks 1–6 run as 3 parallel workstreams in isolated git worktrees
  (A = building-load validation; B = EV-marginal fidelity; C = TSTR utility),
  each driven by a lead agent that may spawn sub-agents. Review at each
  verification gate before merge. Merge order: A → C(baseline) → B → C(final).
- **TSTR task (#3):** short-horizon **charging/building-load forecasting** —
  train on synthetic, test on held-out real ACN/ElaadNL; report TSTR-vs-TRTR gap.
- **Ref-data scope (#1):** **broad** — multiple climate zones of ComStock + many
  BDG2 meters. Validator is built climate-zone-aware; generator changes stay
  scoped to tasks 1–6, but this de-risks item #12 (ship >1 climate zone) next.
- Plan doc: `docs/superpowers/plans/2026-06-28-kdd-tasks-1-6.md`.

## The three headline gaps (root-caused in code)

### Gap 1 — shipped marginals (TruncNorm/Weibull) are worse than KDE/GMM
Marginals are sampled by inverting a **shared Gaussian-copula uniform**
(`renderers/sessions.py:62-107`), so a marginal must expose a closed-form
`ppf(u)`; the scalar knob/provenance/override system (`knob_loader.py`
`DIST_PARAM_RANGES`, `_check_deep_range`) only binds to floats; the fitter drops
non-scalar fits; and determinism requires exactly one uniform consumed per draw.
KDE violates all of these. **But a 2-component `truncnorm_mixture` already ships
for ACN/ElaadNL arrival** (`populations.yaml:135-140`), inverted by bisection on
the shared uniform (`_mixture_ppf_u`, `sessions.py:84-107`) — proving the
architecture can carry a multi-modal, scalar-parameterized marginal. Fix =
generalize to **GMM-k** (incl. dwell, which is still single-Weibull), not KDE.

### Gap 2 — arrival bimodality / [6,20] clip / σ-compression / worst region
- [6,20] clip enforced in 3 places: `distribution_fitter.py:27-28`,
  `knob_loader.py:35-44`, `samplers/sessions_dist.py:47,53-54`.
- σ-compression is a **support artifact**: the hard window discards the ~8.3%
  tail mass that inflates real σ (copula is faithful, ρ-gap ≤0.032).
- Worst cell **`rare_consistent`** (KS 0.222, |Δμ| 1.94h) is the **largest** ACN
  region (~36% of drivers) — failure is **real and measured, not hidden**
  (distinct from the sub-1% `rare_inconsistent` tail). Cause: `api.py:284-291`
  fits **one pooled mixture and broadcasts it to every region**, assuming arrival
  ⟂ (φ,κ) axes — false for `rare_consistent` (arrives ~2h later than the pool).

### Gap 3 — building-load / DER have no real-data fidelity evidence
- Building load = real EnergyPlus on DOE/PNNL prototypes, but **only Denver
  CZ-5B** ships (`prototypes.py:5`) and magnitudes are **renormalized to a
  `peak_kw` knob** (`building_load.py:14-26`).
- S5 check (`tools/validate_calibration.py:612-661`) compares against bands
  **derived from the generator's own occupancy schedules** (`:595-599`) — it
  validates the model against itself. No building-load fidelity check exists in
  `validate.py`.
- PV (`pv_model.py`, deterministic PVWatts-v5) is **never validated**.
- Battery is **specs-only** — no dispatch/SoC timeseries (`renderers/battery.py:1`).
- DR magnitudes are a flat Uniform prior with no data behind them.

## Prioritized actions

Priority: **P0** = submission blocker · **P1** = strongly expected · **P2** = strengthens/defends.

| # | Pri | Gap | Action | Why | Status |
|---|-----|-----|--------|-----|--------|
| 1 | P0 | 3 | `tools/validate_buildingload.py`: match each (archetype,size,CZ-5B) to **NREL ComStock/EULP** + a few **BDG2** real meters; compute CV(RMSE), NMBE (ASHRAE G14), normalized load-shape correlation, peak-hour error, load factor; `peak_kw_scaling` off for the comparison. | Converts building half from "validated against itself" to real-data fidelity. | ✅ merged. ComStock (CZ 5B/3B/4A/6A) + 19 BDG2 meters. Finding: matches a single 90.1-2019 prototype (~8 W/m²); shape corr 0.71–0.94, peak ≤3h; EUI ~30–50% below stock-avg ComStock (documented as scope, not defect). |
| 2 | P0 | 3 | Replace self-derived `PNNL_EXPECTED_*` bands (`validate_calibration.py:600-609`) with per-(archetype,size) ranges derived from ComStock; keep peak/off-peak as a coarse smoke test only. | Current 3/4 "failures" are a broken yardstick, not a broken model. | ✅ merged. S5 now loads ComStock bands from `reference_bands.json`; peak/off-peak demoted to coarse smoke test; G14 fidelity in `validate_buildingload.py`. |
| 3 | P0 | utility | **TSTR**: train a load-forecasting / charging-demand / scheduler model on synthetic, test on held-out **real** ACN/ElaadNL; report transfer. | Track *requires* proving utility; currently only asserted. | ✅ merged + final run on improved generator (HEAD). ACN: lagged TSTR/TRTR 0.99×/0.92× MAE/RMSE; calendar-only probe 0.57×/0.79× (synthetic-trained beats real-trained on load shape). Robust across the B marginal changes. Caveat: synth magnitude < real; ElaadNL TSTR pending raw-cache restore. |
| 4 | P1 | 1 | Generalize 2-comp EM → **GMM-k** (`distribution_fitter.py`); add mixture path to **dwell** (`sessions_dist.sample_f_dwell` + `_weibull_mixture_ppf_u`); add scalar leaves to `DIST_PARAM_RANGES`; re-calibrate; re-run `model_eval`. | Closes held-out KS gap (~0.10→~0.03) with proven machinery; preserves copula + knobs + determinism. | ✅ merged. GMM-k arrival + Weibull dwell mixtures wired; ACN mean arrival KS 0.148→0.073. Dwell mixtures ship where they beat single-Weibull (gate conservative → aggregate dwell flat). |
| 5 | P1 | 2 | Replace pooled-broadcast fit (`api.py:284-291`) with **per-region mixture fits** (fallback to pooled when n<60). | Fixes worst cell (`rare_consistent`, 36% of ACN). | ✅ merged. Per-region fits; `rare consistent` arrival KS **0.179→0.079** (μ 11.25 vs src 11.95). Single-site `acn_office001` n=41 falls back to pooled (small-sample). |
| 6 | P1 | 2 | Widen window to ~[4,22] in all 3 locations; read `trunc_lo/hi` from calibrated block; gate behind calibrated-leaf presence to keep synthetic pops bitwise-identical; re-calibrate. | Recovers discarded tail mass causing σ under-dispersion. | ✅ merged. Window [4,22], read per-region; synthetic pops bitwise-identical (determinism tests green). |
| 7 | P1 | 3 | Add battery dispatch: `samplers/battery_dispatch.py` + `renderers/battery_dispatch.py` → `battery_dispatch.csv` (peak-shave + TOU-arbitrage heuristic/LP over existing load/prices/DR); add `validate.py` invariants. | Builds the missing operational "→Building" behavior. | ☐ |
| 8 | P1 | 3 | `tools/validate_pv.py`: compare `pv_model.pv_ac_series` to **PVWatts v8 API / SAM** (<5% annual error; G14 hourly). | Cheap, high-credibility validation of a deterministic model. | ☐ |
| 9 | P2 | 3 | Map each tariff to an OpenEI **URDB** rate ID; validate peak/off-peak `$/kWh` + `peak_window`. | Makes prices traceably real. | ☐ |
| 10 | P2 | 3 | Bound/fit DR magnitudes to published **CAISO / PG&E CBP/BIP/ELRP** commitments; else caveat explicitly. | Replaces a no-data prior with grounded ranges. | ☐ |
| 11 | P2 | 1 | Wire held-out KS into calibration (tracker F2/F3); report bootstrap CIs on KS/W₁. | Every fidelity number is in-sample today. | ☐ |
| 12 | P2 | 2/3 | Empirical inverse-CDF arrival family for near-uniform tails (quantile transform on shared uniform); ship >1 climate zone of prototypes. | Removes last unmodeled arrival shape + single-climate limit. | ☐ |
| 13 | P2 | all | Re-run `calibrate` → `validate_calibration` → `model_eval` → benchmark; commit refreshed results; reconcile `depart_soc_mu` 85-vs-50 doc contradiction (tracker O4). | Every paper number regenerable from committed scripts. | ☐ |

## Also outstanding (from the wider assessment, not in the table above)
- **No LICENSE file** — blocker for an open-science track (add MIT/Apache-2.0).
- Datasheet/dataset-card + Croissant metadata.
- Ethics/fairness/bias/misuse section.
- EV WATTS / INL are tiny synthetic fixtures, not the real releases.
- `verify_sweep.py` references metric columns absent from `MetricsResult` (benchmark pipeline not run end-to-end).
- Benchmark is V1G-only (clips V2B discharge, excludes building load + DR from the scheduler).
