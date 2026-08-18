# `tools/`

Operational scripts around the generator. None of these are part of the
installed `v2b_syndata` package — they are run as files
(`uv run python tools/<group>/<script>.py`), and the handful that import each
other do so via an explicit `sys.path` insert of their own directory.

Anything importing a sibling assumes the **flat module layout inside each
subfolder** (no `__init__.py`, no package semantics). Keep it that way, or the
`spec_from_file_location` imports in `tests/` and the `sys.path` inserts in
`tools/paper/repro_paper.py` break.

| Group | What lives there |
|---|---|
| `setup.sh` | One-shot repo setup (uv + deps + user-local EnergyPlus 24.1 + smoke gen). Idempotent. Stays at top level — `README.md` and `.claude/commands/setup.md` point at it. |
| [`web/`](web/README.md) | Flask + vanilla-JS frontend for driving the generator interactively. No build step. |
| `paper/` | KDD evidence pipeline: the reproducibility driver, benchmarks, figures, appendix. |
| `validation/` | Fidelity / audit harnesses that check generated output against real references. |
| `campus/` | Multi-building batch generation and post-run analysis. |
| `data_prep/` | Ingesting and inspecting the real upstream datasets. |

## `paper/` — KDD evidence pipeline

`repro_paper.py` is the **authority**: after the evidence freeze, paper numbers
change only by re-running it, never by hand. It shells out to
`validation/validate_calibration.py`, `validation/validate_buildingload.py`,
`tstr_forecasting.py`, and `bench_v2b_dispatch.py`, then collects everything
into `docs/experiments/PAPER_NUMBERS.md`.

| Script | Purpose |
|---|---|
| `repro_paper.py` | One-shot reproducibility driver for every paper number (WS-F). |
| `paper_figures.py` | Render the five KDD figures into `paper/figures/*.pdf`. |
| `gen_paper_appendix.py` | Generate the data-driven appendix sections. |
| `tstr_forecasting.py` | TSTR (train-on-synthetic, test-on-real) utility proof via load forecasting. |
| `bench_v2b_dispatch.py` | LP peak-shaving dispatch baseline on one released corpus unit. |
| `paper_bench.py` | Paper-grade benchmark: 7 scenarios × 7 ACN-Sim algorithms. |
| `run_bench_sweep.py` | Multi-scenario × multi-algorithm benchmark sweep. |
| `sensitivity_sweep.py` | 2-axis sweep: slot ratio × feeder ratio × algorithm. |
| `verify_sweep.py` | Verification harness for the bench sweep (data + algorithm sanity). |

## `validation/` — fidelity and audit harnesses

| Script | Purpose |
|---|---|
| `validate_calibration.py` | Calibration faithfulness: fitted distributions vs the real source cohorts. |
| `validate_buildingload.py` | Building load vs ASHRAE G14 / NREL ComStock references. |
| `validate_pv.py` | Transparent PV model vs the NREL SAM (PVWatts v8) reference. |
| `model_eval.py` | Held-out model selection for the per-feature generative marginals. |
| `source_sanity_check.py` | "Does the ground truth look sane?" gate over each source cohort. |
| `knob_audit.py` | Knob audit — Stage 1 (existence + isolation), Stage 2 (direction + magnitude). |
| `pairwise_audit.py` | Pairwise knob-interaction audit; reuses `knob_audit.py`'s probes and metrics. |

## `campus/` — multi-building generation and analysis

The proven recipe is `noise_profile: clean` + a per-building weather profile;
see the "Multi-building / batch generation gotchas" section of `CLAUDE.md`.

| Script | Purpose |
|---|---|
| `split_campus_config.py` | Split `configs/campus_<TAG>.yaml` into per-building `b*.yaml` configs. |
| `run_campus.sh` | Generic building-major campus runner over those split configs. Resumable. |
| `analyze_campus.py` | Uncertainty analysis of a building-major (`b1..bN`) campus tree → HTML. |
| `analyze_campus_shared.py` | Same analysis for a shared-mode (month-major) tree. |
| `analyze_overnight.py` | Same analysis for a single-building slight-vs-moderate tree. |
| `convert_shared_to_perbuilding.py` | Convert a shared batch tree into a per-building tree. |

## `data_prep/` — real upstream datasets

| Script | Purpose |
|---|---|
| `ingest_evwatts.py` | Ingest the real EV WATTS public dataset into the calibration schema. |
| `fetch_buildingload_reference.py` | Download + characterize real building-load references. |
| `acn_json_to_csv.py` | Flatten a cached ACN-Data sessions JSON into one CSV row per session. |
| `plot_acn_overview.py` | Per-site overview figure for an ACN-Data session CSV. |
| `plot_acn_kwh.py` | Plot a per-session energy column from an ACN-Data CSV. |
| `sample_behavior_standalone.py` | Standalone sampler for the fitted behavioral distributions (usable as a library). |
