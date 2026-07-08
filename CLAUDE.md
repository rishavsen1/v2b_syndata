# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> A separate `.claude/CLAUDE.md` carries vexp tooling instructions (use
> `run_pipeline` instead of grep/glob). This file covers the project itself.

## What this is

`v2b-syndata` is a configurable synthetic **V2B (Vehicle-to-Building)** dataset
generator. It is a **forward-sampling generative model**: a scenario YAML + an
integer seed produce **bitwise-identical** CSVs (`users`, `cars`, `chargers`,
`sessions`, `building_load`, `grid_prices`, `dr_events`, `pv*`, `battery`) plus a
`manifest.json` provenance record. Building load comes from a real **EnergyPlus**
simulation; behavioral distributions are **calibrated from real charging
datasets** (ACN-Data, ElaadNL, EV WATTS, INL).

## Commands

```bash
# One-shot setup (uv + deps + user-local EnergyPlus 23.2 + smoke gen). Idempotent.
./tools/setup.sh

# Install/sync deps only
uv sync

# Tests (EnergyPlus is STUBBED by default — no binary needed)
uv run pytest
uv run pytest tests/test_reproducibility.py::test_name      # single test
uv run pytest -m real_energyplus                            # opt INTO real EnergyPlus subprocess
uv run pytest -m webapp                                     # Flask test-client endpoint tests
uv run pytest -m browser                                    # Playwright headless E2E (needs browsers installed)

# Lint / format / types
uv run ruff check .
uv run ruff format .
uv run mypy src/v2b_syndata

# Generate one scenario seed, then validate it
uv run python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir data/output/dev/S01/seed42/
uv run python -m v2b_syndata.cli validate data/output/dev/S01/seed42/

# Multi-building batch (months × samples, optimus CSVs). ALWAYS smoke-test a
# 1-month × 2-sample slice first; see "Multi-building / batch generation gotchas".
uv run python -m v2b_syndata.cli generate-multi --config configs/campus_10.yaml \
    --start-month 2024-01 --end-month 2024-12 --samples-per-month 150 \
    --noise-profile clean --workers 30 --output-dir data/output/campus10/ --force

# Discoverability
uv run python -m v2b_syndata.cli list-scenarios
uv run python -m v2b_syndata.cli list-knobs

# Web frontend (recommended for driving the generator interactively)
uv run python tools/web/app.py            # http://127.0.0.1:5000
HOST=0.0.0.0 uv run python tools/web/app.py  # bind all interfaces (SSH/LAN)
```

Other CLI subcommands (`v2b_syndata.cli`): `calibrate` (fit per-region
distributions from a real dataset), `batch` (months × samples_per_month → a
tree), `generate-multi` (N distinct buildings → optimus-compatible CSVs), `bench`
(ACN-Sim scheduling baseline on a generated output dir), `docs-gen` (regenerate
the auto block of `docs/KNOB_REFERENCE.md`).

Knob overrides are repeatable `--override 'bucket.knob=value'` (value is
YAML-parsed). Descriptors can be swapped per scenario via the web tool or
multi-building config.

## Architecture

The generator is a **DAG of samplers and renderers** executed in topological
order. The tier structure (Tier 0 descriptors → Tier 1 roots → Tier 1.5
per-entity → Tier 2 latents → Tier 3 renderers) maps directly onto modules:

- **`dag.py`** — `NODE_TOPOLOGY` declares every node and its parents. `SamplerRegistry`
  maps node name → function. The graph is validated acyclic; nodes run in
  `lexicographical_topological_sort` order (stable across networkx versions).
- **`runner.py`** — `generate()` is the entry point. It resolves knobs, builds a
  `ScenarioContext`, wires the registry (`build_registry()`), runs the DAG,
  applies noise, runs the E5 concurrency check, writes CSVs in deterministic
  order, and writes the manifest. Each sampler mutates the shared `ScenarioContext`
  in place (`ctx.roots`, `ctx.latents`, `ctx.rendered`, …).
- **`samplers/`** — produce latents: `exogenous.py` (Tier-1 roots C/A/S/O/T/U/F/X),
  `per_entity.py` (per-user / per-fleet attrs), `load.py` (EnergyPlus building
  load), `sessions_dist.py` (arrival/dwell/SoC distributions), `pv.py`.
- **`renderers/`** — turn latents into the output CSVs (one module per CSV).
- **`load_pipeline/`** — the EnergyPlus integration. `ep_runner.discover_energyplus`
  searches standard install paths and raises `EnergyPlusBinaryNotFound` —
  **there is no silent stub fallback in production** (tests stub it via conftest).
- **`calibration/`** — fits per-region behavioral distributions from real
  charging logs. One normalizer per dataset under `sources/`; SoC is **never
  recorded by any charger** and is always a modeled prior, not a fit.

### Two invariants that constrain almost every change

1. **Bitwise determinism.** A given (scenario, seed) must always produce
   byte-identical CSVs. Seeding (`seeding.py`) keys each RNG sub-stream off a
   **SHA-256 hash of the node name** (and car_id), *not* spawn order — so adding
   a new node MUST NOT shift the seeds of existing nodes. Never use Python's
   salted `hash()`. Tests: `test_reproducibility.py`, `test_determinism_stress.py`.

2. **Knob resolution chain & provenance.** `knob_loader.resolve_knobs` resolves
   every knob by priority: **CLI override > scenario YAML `overrides` >
   descriptor expansion > `knobs.yaml` default**. Each resolved value is a
   `KnobValue(value, source)` so the manifest records where it came from
   (`explicit` / `descriptor:<name>` / `calibration:<provenance>` / `default`).
   Two channels exist: the **registry channel** (paths declared in
   `configs/knobs.yaml`) and the **deep channel** (calibrated
   `user_behavior.region_distributions.<region>.<dist>.<param>` leaves, validated
   against `DIST_PARAM_RANGES`).

### Config / descriptor system (`configs/`)

A scenario YAML names five Tier-0 descriptors (`location`, `building`,
`population`, `equipment`, `noise`). `descriptor_loader.expand_descriptors`
looks each up in its library file (`locations.yaml`, `buildings.yaml`,
`populations.yaml`, `equipment.yaml`, `noise_profiles.yaml`) and produces the
Tier-1 knob values. `knobs.yaml` is the typed knob **registry** (type, range,
default, choices). Add a new knob by declaring it there; add a new descriptor
value by editing the relevant library file.

### Noise vs weather (kept deliberately distinct)

- **Noise layer** (`noise.py`, `configs/noise_profiles.yaml`) — **output-side**:
  perturbs the produced CSVs after generation. `clean` profile → 0 jitter →
  `building_load` is a deterministic `f(weather)`.
- **Weather layer** (`configs/weather_profiles.yaml`) — **input-side**: perturbs
  the EPW that EnergyPlus simulates *and* the exported `weather_data.csv`
  together, so load stays physically faithful to the weather.

### Multi-building / batch generation gotchas (learned the expensive way)

- **Multi-sample batches want `noise_profile: clean` + a weather profile, NOT
  `tmyx_stochastic`.** Output-side jitter perturbs session SoC/duration *after*
  the sampler's D5 rejection, so ~half the samples fail D5 validation
  ("unreachable (need=X, avail=Y)" with need barely over avail). With `clean` +
  per-sample weather realization you still get genuinely distinct samples
  (EnergyPlus re-runs each perturbed EPW; the per-sample seed varies sessions)
  and 100% pass validation. This is the proven overnight/campus recipe.
- **Per-building `weather_profile:` / `noise_profile:` in the multi-building
  config win over the batch-level CLI flags** (`multi_building.py::generate_multi_batch`).
  To mix slight/moderate across buildings in one run, set them per building and
  do NOT pass `--weather-profile` / `--weather-sigma-c` / `--weather-solar-sigma`.
- **`building_load.peak_kw_scaling` defaults true** → every sample's peak is
  renormalized to the building descriptor's `peak_kw` exactly (peak identical
  across samples; only energy/shape vary). Set it `false` for weather-driven
  peaks (raw EnergyPlus magnitudes).
- **`--output-mode per-building` ≠ building-major layout.** It writes integer
  `0..N-1` subfolders at the *leaf* (`<out>/<MONTH>/<sample>/<bid>/`). For a
  building-major tree (`parent/b1/<MONTH>/<sample>/`), run one single-building
  batch per building (split the config; see `configs/_campus_split/`,
  `tools/run_campus10.sh`).
- **Seed spacing:** batch adds the per-sample offset (`0..samples_per_month-1`)
  to each building's base seed — space base seeds by ≥ samples_per_month (and
  ≥ `multiplier` when used) or (building, sample) seeds collide across entries.
- **Don't `cli validate` optimus output dirs.** `validate()` expects the
  *native* schema (`users.csv`, `manifest.json`); generate-multi emits
  optimus-schema CSVs and validates natively *inside* each unit's generate. The
  authoritative pass/fail is `batch_manifest.json::validation_summary` (per
  building) / `multi_building_config.json::validation_summary` (per unit).
- **Post-run analysis:** `tools/analyze_overnight.py` (single building,
  slight-vs-moderate trees) and `tools/analyze_campus.py` (building-major
  `b1..bN` trees) stream every sample → per-sample metrics CSV + self-contained
  uncertainty-analysis HTML. Reference runs: `data/output/overnight/`,
  `data/output/campus10/` (18k units, 0 hard errors).

### Validation (`validate.py`)

Hard invariants (A–H + manifest checks I) raise `ValidationError`; soft checks
(S) emit warnings. `cli generate` auto-validates only when no jitter was applied;
run `cli validate <dir>` explicitly for noisy outputs.

## KDD 2027 submission (active sprint — Cycle 1: abstract Jul 19, paper Jul 26 2026)

- **`docs/KDD_SUBMISSION_PLAN.md`** — the sprint plan (workstreams WS-A…WS-H,
  calendar, gates). **Evidence freeze Jul 17**: after that date, paper numbers
  change only via the reproducibility driver, never by hand.
- **`docs/KDD_PAPER_STRUCTURE.md`** — the paper skeleton; claims→evidence map
  and attack→defense table. Every claim in the paper must trace to a row there.
- **`docs/KDD_READINESS.md`** — long-lived task tracker (statuses authoritative).
- Paper source lives in `paper/` (acmart sigconf; 8 content pages at
  submission + unlimited appendix; single-blind). Numbers cited in the paper
  must exist in `docs/experiments/PAPER_NUMBERS.md` once WS-F lands.
- Known truth-traps when writing about the artifact: INL is a **fixture**
  (65 sessions), not a real calibration corpus; the campus corpus **is**
  weather-realized but the batch-level manifest field misleadingly reads
  `none` (per-building profiles win — check per-unit configs); the GMM-k
  0.148→0.073 ablation needs a committed primary source before citing.

## Where to look for "why"

- **`docs/DESIGN_NOTES.md`** — numbered decision log (sections 1–31). **These
  section numbers are cited by number from source code (`validate.py`,
  `runner.py`, `prototypes.py`, `e5_metrics.py`) — do not renumber them.**
- **`docs/GENERATIVE_MODELS.md`** — why each random quantity uses its
  distribution family, with the empirical AIC/BIC/KS verdicts.
- **`docs/PROJECT_TRACKER.md`** — live backlog: open items, conventions, deferred work.
- **`docs/KNOB_REFERENCE.md`** — auto block regenerated by `cli docs-gen`; do not
  hand-edit the generated section.
- **`tools/web/README.md`** — web frontend architecture (Flask + vanilla JS, no build step).

(Note: `README.md` references a `handoff/spec/` directory that no longer exists;
the spec content now lives in `docs/`.)
