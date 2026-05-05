# Build the V2B Synthetic Dataset Generator

You are building a complete Python package for a configurable synthetic V2B (Vehicle-to-Building) dataset generator. The architecture, schema, distributions, and knob registry have all been designed and locked in advance. Your job is to **implement** the system to spec. Do not redesign — implement what is specified.

## Read these spec files first (in this order)

1. `spec/PLAN.md` — high-level project plan and architecture
2. `spec/BAYES_NET.md` — complete generator DAG: every node, parent, sampler, output
3. `spec/DATASET_AUDIT.md` — which datasets feed which nodes
4. `spec/validate_spec.md` — all 40+ invariant checks the validator must enforce
5. `spec/knobs.yaml` — full tunable knob registry (every parameter, type, range, default)
6. `spec/configs/locations.yaml` — Tier 0 Location library
7. `spec/configs/buildings.yaml` — Tier 0 Building library
8. `spec/configs/populations.yaml` — Tier 0 Population library (with axis-region grids)
9. `spec/configs/equipment.yaml` — Tier 0 Equipment library
10. `spec/configs/noise_profiles.yaml` — post-render noise profiles
11. `spec/configs/scenarios/S01.yaml` — example scenario file
12. `spec/ACN_DATA_CALIBRATION.md` — calibration plan (do not implement now; understand the interface)
13. `spec/bayes_net_v7.png` — visual DAG reference

## Architectural overview (read BAYES_NET.md for full detail)

The generator is a **forward sampler** with 4 tiers below user-facing descriptors:

- **Tier 0 (Descriptors):** 4 named bundles (Location, Building, Population, Equipment) in scenario YAML, resolved via library files
- **Tier 1 (Roots):** 9 exogenous nodes (C, W, T, A, S, O, U, F, X), set deterministically from descriptor expansion
- **Tier 1.5 (Per-entity):** 2 nodes — A_user (per-car attributes), A_fleet (per-car battery) — sampled once per car_id
- **Tier 2 (Latents):** 5 sampled distributions (L_flex, L_inflex, f_arr, f_dwell, f_soc); f_* parameterized by A_user
- **Tier 3 (Renderers):** 7 output CSVs + 1 manifest JSON

**Reproducibility contract:** `generate(scenario_id, knob_overrides, seed) → bitwise-identical CSVs`. Same seed → same bytes.

## What to build (Step 3: renderer stubs)

Build a complete end-to-end pipeline using **stubs for EnergyPlus and ACN-Data integration**. The pipeline must:

1. Load scenarios via Tier 0 descriptors (resolve from library files)
2. Resolve all knob values via the chain: CLI override > scenario overrides > descriptor expansion > knobs.yaml default
3. Sample all DAG nodes in topological order
4. Render all 7 CSVs + manifest.json
5. Pass all 40+ hard invariants in `validate_spec.md`
6. Re-run with same seed produces bitwise-identical CSVs

For nodes that depend on external data (L_flex, L_inflex use EnergyPlus), implement **stubs** as specified in the "Stub behaviors" section below. The real samplers will replace stubs in later steps.

## Repository layout to create

```
v2b-syndata/
├── pyproject.toml
├── README.md
├── .gitignore
├── configs/                     # COPY from spec/configs/ verbatim
│   ├── knobs.yaml
│   ├── locations.yaml
│   ├── buildings.yaml
│   ├── populations.yaml
│   ├── equipment.yaml
│   ├── noise_profiles.yaml
│   └── scenarios/
│       └── S01.yaml
├── src/v2b_syndata/
│   ├── __init__.py
│   ├── types.py                 # dataclasses: Knobs, Roots, ScenarioContext, KnobSource
│   ├── seeding.py               # SeedSequence helpers; per-node and per-car seeds
│   ├── knob_loader.py           # YAML → resolved knobs; resolution chain logic
│   ├── descriptor_loader.py     # Tier 0 → Tier 1 expansion via library lookup
│   ├── dag.py                   # networkx.DiGraph, topological sort, sampler registry
│   ├── samplers/
│   │   ├── __init__.py
│   │   ├── exogenous.py         # C, A, S, T, U, F, X, W, O packing
│   │   ├── per_entity.py        # A_user, A_fleet (real implementations, not stubs)
│   │   ├── load.py              # L_flex, L_inflex (STUB — sinusoid)
│   │   └── sessions_dist.py     # f_arr, f_dwell, f_soc (parameterized from A_user)
│   ├── renderers/
│   │   ├── __init__.py
│   │   ├── building_load.py
│   │   ├── cars.py              # dump A_fleet
│   │   ├── users.py             # dump A_user
│   │   ├── chargers.py
│   │   ├── grid_prices.py
│   │   ├── dr_events.py         # STUB — see below
│   │   └── sessions.py          # multi-day, copula joint, non-overlap rejection
│   ├── noise.py                 # post-render perturbation per noise_profiles.yaml
│   ├── validate.py              # all invariants A1–H6 + I1–I4
│   ├── manifest.py              # build manifest.json
│   └── cli.py                   # `python -m v2b_syndata.cli generate ...`
├── tests/
│   ├── __init__.py
│   ├── test_knob_loader.py
│   ├── test_descriptor_resolution.py
│   ├── test_dag.py              # topology valid, no cycles, all samplers registered
│   ├── test_consistency.py      # invariants A1–H6 + I1–I4
│   ├── test_reproducibility.py  # same seed → same SHA-256 hashes
│   └── test_end_to_end.py       # full S01 generation
└── data/output/                 # gitignored; outputs land here
```

## Implementation specifications

### `pyproject.toml`

- Use **uv** for dependency management (modern, fast)
- Python 3.11+
- Dependencies: `numpy`, `pandas`, `networkx`, `pyyaml`, `scipy`, `pydantic` (for type validation)
- Dev dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy`

### `types.py`

Define dataclasses (or Pydantic models) for:
- `KnobValue` — value + source ∈ {explicit, descriptor:<name>, default}
- `ResolvedKnobs` — full resolved knob set after chain
- `RootBundle` — packed Tier 1 root values
- `UserAttrs` — per-user (region, phi, kappa, delta_km, neg_type, w1, w2)
- `FleetAttrs` — per-car (battery_class, capacity_kwh, min/max SoC)
- `ScenarioContext` — everything a sampler needs (knobs, RNG, sim window)

### `seeding.py`

- Single global seed → `numpy.random.SeedSequence`
- `spawn()` per node by name (deterministic mapping name → sub-stream)
- `spawn()` per car_id within A_user / A_fleet
- Document: adding a new node should NOT shift seeds of unrelated nodes

### `knob_loader.py` + `descriptor_loader.py`

Implement resolution chain:
```
resolved_value = CLI override                    (highest priority)
              or scenario_yaml.overrides[knob]
              or descriptor → library file
              or knobs.yaml default              (lowest)
```

For each resolved knob, record source for manifest.

Validate each value against `knobs.yaml` declared type and range.

### `dag.py`

- `networkx.DiGraph` with nodes registered with their parents
- Sampler registry: `samplers: dict[str, Callable[[ScenarioContext], Any]]`
- Topological sort yields execution order
- Validate: no cycles, every node has a registered sampler, every parent exists

### Samplers

**Exogenous (`samplers/exogenous.py`):** Read from resolved knobs, pack into RootBundle. No randomness.

**Per-entity (`samplers/per_entity.py`):** REAL implementations:
- `A_user(U)`: For each car_id, sample region by weights, then (φ, κ, δ) uniformly within region, then negotiation_type, then (w1, w2) from CONSENT cluster Normal, apply w_multiplier.
- `A_fleet(F)`: Per car_id, sample battery_class.

CONSENT cluster parameters (hard-coded constants in `samplers/per_entity.py`):
```python
CONSENT_CLUSTERS = {
    "type_i":   {"w1_mean": 0.0489, "w1_std": 0.02, "w2_mean": 0.1250, "w2_std": 0.01},
    "type_ii":  {"w1_mean": 0.0133, "w1_std": 0.01, "w2_mean": 0.0346, "w2_std": 0.02},
    "type_iii": {"w1_mean": 0.0362, "w1_std": 0.01, "w2_mean": 0.0673, "w2_std": 0.01},
    "type_iv":  {"w1_mean": 0.0,    "w1_std": 0.0,  "w2_mean": 0.1083, "w2_std": 0.0},
}
```

Battery class capacities:
```python
BATTERY_SPECS = {
    "leaf_24":     {"capacity_kwh": 24.0,  "min_soc": 10.0, "max_soc": 100.0},
    "bolt_40":     {"capacity_kwh": 40.0,  "min_soc": 10.0, "max_soc": 100.0},
    "m3_75":       {"capacity_kwh": 75.0,  "min_soc": 10.0, "max_soc": 100.0},
    "rivian_100":  {"capacity_kwh": 100.0, "min_soc": 10.0, "max_soc": 100.0},
}
```

**Load (`samplers/load.py`) — STUB:**
- `L_flex(t)`: `120 + 60 * sin(2π * (hour - 6) / 24)` kW; clamp ≥ 0
- `L_inflex(t)`: `40 + 15 * sin(2π * (hour - 6) / 24)` kW; clamp ≥ 0
- Returns 15-min interval pandas Series over sim window
- Add ±5% / ±3% Gaussian noise (use spawned seed)

**Distribution samplers (`samplers/sessions_dist.py`):**
For each user (parameterized from A_user):
- `f_arr_v`: Bernoulli(φ_v) gates per-day appearance; `arrival_hour ~ TruncNorm(μ_arr=8.5, σ_arr=2.0*(1-κ_v))`. Truncate to [6, 20].
- `f_dwell_v`: `Weibull(k=2.0, λ=8.0*(0.5+φ_v))` hours; clip to [0.5, 14].
- `f_soc_v`: `Beta(α=4, β=6)` shifted by `-δ_v * 0.003` (heuristic kWh/mi inverse); clip to [min_allowed_soc, max_allowed_soc].
- Joint (arrival, dwell): Gaussian copula with ρ = 0 (independent) for stub. Real ρ comes from ACN-Data calibration later.

### Renderers

**`building_load.csv`:** Sum L_flex + L_inflex; rescale s.t. peak == `peak_kw` knob; emit columns `datetime, power_flex_kw, power_inflex_kw`.

**`cars.csv`:** Dump A_fleet to CSV. Columns: `car_id, capacity_kwh, min_allowed_soc, max_allowed_soc, battery_class`.

**`users.csv`:** Dump A_user to CSV. Columns: `car_id, region, phi, kappa, delta_km, negotiation_type, w1, w2`.

**`chargers.csv`:** Compute n_bi = round(charger_count * directionality_frac), n_uni = remainder. Emit rows: bi rows have `min_rate_kw=-bi_rate_kw, max_rate_kw=+bi_rate_kw`; uni rows have `min_rate_kw=0, max_rate_kw=uni_rate_kw`. Columns: `charger_id, directionality, min_rate_kw, max_rate_kw`.

**`grid_prices.csv`:** 15-min grid; price = peak_price if hour in peak_window else off_peak_price; type tagged. Flat tariff: const off_peak. Columns: `datetime, price_per_kwh, type`.

**`dr_events.csv` — STUB:**
- If `dr_program == none`: emit header-only file
- Else: emit 4 mock events at 14:00 on first 4 weekdays of each summer month in sim window. Magnitude = midpoint of `dr_magnitude_kw_range`. notified_at = start − notification_lead per program (CBP=24h, BIP=2h, ELRP=24h).
- Real inhomogeneous Poisson sampler comes in Step 6.
- Columns: `event_id, start, end, magnitude_kw, notified_at`.

**`sessions.csv`:** For each car_id, for each weekday in sim window:
1. Bernoulli(φ_v) gates appearance
2. If appearing: sample arrival_hour, sample dwell, departure = arrival + dwell
3. Sample arrival_soc, sample required_soc_at_depart (TruncNorm(0.85, 0.05) clipped to [min_depart_soc, max_allowed_soc])
4. Compute previous_day_external_use_soc from prior session's departure SoC vs this session's arrival SoC
5. Reject and resample if non-overlap violated (max 5 retries per session)

Columns: `session_id, car_id, building_id, arrival, departure, duration_sec, arrival_soc, required_soc_at_depart, previous_day_external_use_soc`.

### `noise.py`

Post-render perturbation per `noise_profiles.yaml`:
- `building_load_jitter_pct`: multiplicative Gaussian on `power_flex_kw`, `power_inflex_kw`
- `arrival_time_jitter_min`: additive Gaussian on `arrival`
- `soc_arrival_jitter_pct`: additive on `arrival_soc`
- `dr_notification_dropout_prob`: Bernoulli drop entire DR event rows
- `price_jitter_pct`: multiplicative on `price_per_kwh`
- `occupancy_jitter_pct`: multiplicative on `power_inflex_kw` (occupancy proxy)

Default `clean` profile: all zeros, no perturbation.

### `validate.py`

Implement every invariant in `spec/validate_spec.md`:
- Hard invariants A1–H6 + I1–I4 → raise `ValidationError` and exit non-zero
- Soft checks S1–S5 → log warnings only, exit zero

CLI: `python -m v2b_syndata.cli validate <output_dir>` runs both; `--strict` flag treats soft as hard.

### `manifest.py`

`manifest.json` schema (all fields required):
```json
{
  "scenario_id": "S01",
  "seed": 42,
  "knob_overrides": {},
  "knob_resolution": {
    "ev_fleet.ev_count": {"value": 20, "source": "default"},
    "building_load.climate": {"value": "subtropical", "source": "descriptor:nashville_tn"},
    ...
  },
  "noise_profile": "clean",
  "generator_git_sha": "<git rev-parse HEAD>",
  "generator_version": "0.1.0",
  "generated_at": "<ISO timestamp>",
  "csv_row_counts": {"building_load": 7680, ...},
  "csv_sha256": {"building_load": "abc123...", ...}
}
```

### `cli.py`

```bash
python -m v2b_syndata.cli generate \
    --scenario S01 \
    --seed 42 \
    --output-dir data/output/dev/S01/seed42/ \
    --override utility_rate.peak_window='[16,21]' \
    --noise-profile clean

python -m v2b_syndata.cli validate data/output/dev/S01/seed42/

python -m v2b_syndata.cli list-knobs       # dump all knobs with types and defaults
python -m v2b_syndata.cli list-scenarios   # dump available scenarios
```

Use `argparse` or `click`. Lean: argparse (no extra dependency).

### Tests

- `test_knob_loader.py`: resolution chain priority, type validation, range checks
- `test_descriptor_resolution.py`: Tier 0 → Tier 1 expansion correct, all 4 descriptors handled
- `test_dag.py`: topology has no cycles, every node has registered sampler, parents exist
- `test_consistency.py`: every invariant in `validate_spec.md` is exercised on at least one synthetic input
- `test_reproducibility.py`: generate S01 twice with same seed → identical SHA-256 hashes for every CSV
- `test_end_to_end.py`: `cli.generate(S01, seed=42)` produces all expected files, validate passes

Use `pytest`. Aim for ~80% line coverage on `validate.py` and resolution logic; lower OK elsewhere.

## Acceptance criteria

The build is complete when:

1. ✅ `uv sync` installs cleanly on Python 3.11+
2. ✅ `pytest` passes all tests
3. ✅ `python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir /tmp/out` produces 7 CSVs + manifest.json
4. ✅ `python -m v2b_syndata.cli validate /tmp/out` exits 0
5. ✅ Re-running step 3 with same seed produces files with identical SHA-256 hashes (verify by manifest comparison)
6. ✅ At least one knob override via `--override` works and is recorded in manifest with `source: explicit`
7. ✅ Generating with `--noise-profile light_noise` produces visibly different CSV values than `clean` for the same seed (noise applied), but the underlying generative samples are still seeded identically (verify by setting jitter knobs to zero — should match clean)

## Design constraints — do NOT change

- **No pgmpy.** Use plain Python + networkx.
- **No new datasets in this step.** Stubs for EnergyPlus and DR. Real integration is later steps.
- **No deviation from the schema in `BAYES_NET.md`.** If you find ambiguity, ASK before implementing.
- **Schema is the contract.** CSV column names, types, and order are fixed. Downstream simulators depend on this.
- **Reproducibility is non-negotiable.** Bitwise-identical output for same seed.
- **Knobs.yaml is canonical DOF.** Every parameter must have an entry. No magic constants in code (other than CONSENT clusters and battery specs noted above, which are physical constants).

## Implementation guidance

**Order of implementation (suggested):**

1. Scaffold: `pyproject.toml`, `README.md`, package skeleton, `.gitignore`
2. `types.py`, `seeding.py`
3. `knob_loader.py` + tests (verify resolution chain)
4. `descriptor_loader.py` + tests
5. `dag.py` + sampler registry skeleton
6. Exogenous samplers (trivial — packing only)
7. `samplers/per_entity.py` (A_user, A_fleet)
8. `samplers/load.py` (stubs)
9. `samplers/sessions_dist.py`
10. Simple renderers (chargers, grid_prices, users, cars, building_load)
11. `renderers/dr_events.py` (stub)
12. `renderers/sessions.py` (multi-day with non-overlap rejection — most complex renderer)
13. `noise.py`
14. `manifest.py`
15. `validate.py` (implement invariants progressively as you have outputs to test against)
16. `cli.py`
17. End-to-end test
18. Reproducibility test
19. Polish: docstrings, README, type hints, ruff/mypy

**When you encounter ambiguity:**

1. Re-read the relevant spec section
2. If still ambiguous, make the simplest choice that satisfies the invariants
3. Document the choice in a `DESIGN_NOTES.md` at repo root
4. Flag the choice clearly so it can be reviewed

**Testing approach:**

- Write tests alongside implementation, not at the end
- Use `pytest -x` during development to fail fast
- Mock the random seed for deterministic test fixtures
- Each invariant in `validate_spec.md` should have a test that constructs a violation and asserts the validator catches it

## Deliverables

A working `v2b-syndata/` repository where:
- `git status` is clean (everything committed)
- `pytest` is green
- `python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir /tmp/out` works
- All 7 CSVs + manifest.json land in `/tmp/out/`
- All hard invariants pass

After delivery, the next steps (handled separately) will be:
- Step 4: Replace `samplers/load.py` stub with real EnergyPlus pipeline adapter
- Step 5: Calibrate `populations.yaml` distributions against ACN-Data
- Step 6: Replace `dr_events.py` stub with real inhomogeneous Poisson sampler
- Step 7+: Generate scenario library, run experiments

Build cleanly so these later steps slot in without re-architecting.
