# Coverage Report (V1)

Generated: 2026-05-19
Command: `coverage run -m pytest -k "not real_energyplus and not e2e_calibration" && coverage report`
HTML report: `htmlcov/index.html` (run `coverage html` after a `coverage run`)

## 1. Overall

| | Before V1 | After V1 |
|---|---:|---:|
| Line coverage | 89% | **91%** |
| Statements | 2550 | 2552 |
| Missed lines | 280 | 232 |
| Tests | 237 | **278** (+41) |

Improvements driven by §6 low-hanging-gap fill (tests/test_cli.py +
parametrized test_knob_loader.py extensions + test_dag.py extensions +
tests/test_validate_io.py + tests/test_runner_modes.py). Critical-module
deltas:

| Module | Before | After |
|---|---:|---:|
| `cli.py` | 68% | **90%** |
| `dag.py` | 83% | **93%** |
| `knob_loader.py` | 86% | **92%** |
| `runner.py` | 97% | 98% |

## 2. Per-module coverage (sorted lowest → highest)

| Module | Cov | Stmts | Miss | Category |
|---|---:|---:|---:|---|
| `load_pipeline/api.py` | **50%** | 66 | 33 | infra (real EnergyPlus paths) |
| `load_pipeline/ep_runner.py` | **56%** | 72 | 32 | infra (EnergyPlus discovery + subprocess) |
| `cli.py` | **68%** | 146 | 46 | testable via subprocess — easy fill |
| `load_pipeline/occupancy_inject.py` | **81%** | 63 | 12 | infra (IDF mutation paths) |
| `dag.py` | **83%** | 42 | 7 | defensive raises |
| `load_pipeline/exceptions.py` | **83%** | 12 | 2 | defensive (exception __init__) |
| `knob_loader.py` | 86% | 183 | 25 | defensive raises (type/range) |
| `validate.py` | 88% | 467 | 58 | mix — some real branches, some defensive |
| `load_pipeline/weather.py` | 88% | 81 | 10 | infra (AMY stub + EPW fetch error paths) |
| `manifest.py` | 90% | 40 | 4 | defensive |
| `calibration/acn_fetcher.py` | 90% | 42 | 4 | infra (ACN token error path) |
| `descriptor_loader.py` | 91% | 96 | 9 | defensive raises |
| `renderers/dr_events.py` | 91% | 47 | 4 | defensive |
| `calibration/distribution_fitter.py` | 92% | 103 | 8 | rare-fit warning branches |
| `noise.py` | 93% | 61 | 4 | defensive (legacy compat) |
| `calibration/feature_extractor.py` | 93% | 101 | 7 | defensive |
| `renderers/building_load.py` | 93% | 14 | 1 | defensive |
| `renderers/sessions.py` | 96% | 111 | 4 | defensive + 1 rare branch |
| `load_pipeline/output_parser.py` | 96% | 50 | 2 | defensive |
| `runner.py` | 97% | 94 | 3 | defensive (custom sim_window error path) |
| `sessions_dist.py` | 98% | 40 | 1 | defensive |
| `types.py` | 98% | 63 | 1 | defensive |
| `calibration/api.py` | 98% | 117 | 2 | defensive |
| (100% modules) | 100% | — | 0 | dr_sampler, exogenous, load, per_entity, seeding, cars, chargers, grid_prices, users, prototypes, cache, battery_inference, region_assignment, writer, knob_loader/exceptions |

## 3. Critical modules (<85%) — uncovered line ranges

### `load_pipeline/api.py` (50%) — INFRA

```
36-38: _annual_runperiod_for_year(year) — RunPeriod IDF text generator
74:    _strip_runperiods — regex substitution
78-80: _force_timestep_4 — regex sub or prepend
84:    _strip_existing_meter_outputs — regex sub
88-91: _append_meter_outputs — string concat
95-102: _prepare_idf_for_run — file IO mutation
128-142: _simulate_single body — tempdir + EnergyPlus invocation
170-177: simulate_building_load mixed-archetype branch
185-186: _retail_keys() helper
```

**Reason:** all paths gated by real EnergyPlus runtime, excluded via
`@pytest.mark.real_energyplus`. The stub in `conftest._stub_simulate_building_load`
bypasses them.

**Categorization:** INFRASTRUCTURE. Cannot be unit-tested cheaply; covered
only when the marker runs on a machine with EnergyPlus installed.

### `load_pipeline/ep_runner.py` (56%) — INFRA

```
26-27: _check_callable OSError catch
54-58, 62-65: env-var binary discovery
73:    PATH-search candidate
82:    EnergyPlusBinaryNotFound raise (no binary anywhere)
94-129: run_energyplus body — subprocess + return-code handling
```

**Reason:** same — EnergyPlus binary discovery + subprocess invocation.

**Categorization:** INFRASTRUCTURE.

### `cli.py` (68%) — EASY FILL

```
24-48: cmd_generate body (full subprocess-callable entrypoint)
62-69: _all_jitters_zero helper
73-83: cmd_validate body
87-93: cmd_list_knobs body
97-102: cmd_list_scenarios body
```

**Reason:** no direct CLI tests — pipeline is tested via `runner.generate()`
Python API. CLI subcommand wrappers are uncovered.

**Categorization:** REAL BRANCHES — these are user-facing paths. The
`docs-gen`, `calibrate`, `validate` subcommands already have integration
tests; `generate`, `list-knobs`, `list-scenarios` do not. Filling these
adds ~3 small subprocess tests.

### `load_pipeline/occupancy_inject.py` (81%) — INFRA

```
20:    fixture branch
70:    IDF parse fallback
76-86: occupancy block mutation
115-125: write injected IDF
```

**Reason:** IDF injection happens in `simulate_building_load`, gated by
EnergyPlus runtime.

**Categorization:** INFRASTRUCTURE.

### `dag.py` (83%) — DEFENSIVE

```
55-56: nx.is_directed_acyclic_graph check + RuntimeError raise (cycle in DAG)
78:    register() ValueError when name already registered
82-84: get() KeyError when sampler missing
89:    validate() RuntimeError when nodes have no sampler
```

**Reason:** every raise is defensive — DAG topology is hand-authored static
and validated once at import. Each branch is "impossible by construction" in
normal use.

**Categorization:** DEFENSIVE. Could test each raise with a fixture that
mutates `NODE_TOPOLOGY`. Low value.

### `load_pipeline/exceptions.py` (83%) — DEFENSIVE

```
13-18: EnergyPlusBinaryNotFound.__init__ body (formats checked paths list)
```

**Reason:** raised only when EnergyPlus discovery fails entirely.

**Categorization:** DEFENSIVE.

## 4. Higher-coverage modules (85-95%) — selected hot spots

### `knob_loader.py` (86%, 25 missed lines)

All uncovered lines are `_check_type_and_range` raise paths for type
mismatches (int-expected-got-str, simplex-doesn't-sum-to-1, etc.) and
two raises in `resolve_knobs` (line 227, 259, 270 — unknown override
rejection paths).

**Categorization:** mostly DEFENSIVE. Lines 227/259/270 are real
branches reachable via malformed CLI overrides; the rest fire only on
hand-malformed YAML.

**Easy 1-2 line additions:** parametrize `test_knob_validation.py` to
hit each raise once. ~10 lines of test code lifts to 95%+.

### `validate.py` (88%, 58 missed lines)

Mix:
- Lines 59-79: `_load_csv` + `_load_manifest` ValidationError raises on
  missing files. REAL BRANCH (tested as part of error handling).
- Lines 143-193, 275, 374-377, 445-447, 486, 495-505, 547-581: per-invariant
  early-return guard paths when CSVs are empty or fields absent. Mostly
  DEFENSIVE; a few real (e.g., 633-634 H2 mismatch, 647 H6 magnitude OOR).
- Lines 652-685: H8/H9 DR cap violation raises. REAL but tested with
  cap-stress test which uses real EnergyPlus marker.

**Categorization:** mix — ~30 defensive + ~28 real branches. Most real
branches need integration scenarios that produce the specific failure mode.

### `load_pipeline/weather.py` (88%, 10 lines)

Lines 87-89, 100-101, 149, 155-156 — EPW download / cache miss / AMY raises.

**Categorization:** INFRA + DEFENSIVE.

## 5. Categorization summary

| Category | Lines | Action |
|---|---:|---|
| INFRASTRUCTURE (EnergyPlus) | ~100 | Coverable only with `@pytest.mark.real_energyplus`. Not actionable in token-free suite. |
| DEFENSIVE (impossible-by-construction raises) | ~100 | Could parametrize to lift cov number; low value. |
| REAL BRANCHES (CLI subcommands, validate error paths) | ~80 | Worth filling — ~3 CLI subprocess tests + ~5 validate fault-injection tests. |

## 6. Low-hanging coverage gaps (easy 1-2 line wins)

Listed in order of effort/impact:

1. **`cli.py` cmd_generate via subprocess** — single `subprocess.run([..., "generate", ...])` test on S01 covers lines 24-48. Lifts cli.py from 68% → ~85%.
2. **`cli.py` cmd_validate via subprocess** — call after a generate. Lines 73-83.
3. **`cli.py` cmd_list_knobs / cmd_list_scenarios** — trivial subprocess tests. Lines 87-93, 97-102.
4. **`knob_loader._check_type_and_range`** — single parametrized test passing one malformed value per type. ~25 lines covered with one fixture.
5. **`validate._load_csv` / `_load_manifest`** — call validate() on an empty dir. Lines 59-79 (5 lines).
6. **`dag.py` register-duplicate raise** — one test instantiating SamplerRegistry, registering same name twice. Line 78.
7. **`runner.py` custom sim_window error** — test mode=custom without start/end. Lines 78, 80, 125.

Combined lift: ~50 lines of real-branch coverage with ~10 short tests. Project total would rise from 89% → ~93%.

## 7. Critical observations

- **EnergyPlus paths are uncoverable without the binary.** No action item;
  this is expected. The stub in `conftest` is the right design.
- **CLI subcommand paths are real branches but untested.** Easiest lift.
- **`runner.generate()` and the sampler/renderer core are at 96-100% coverage.** Core pipeline is well-tested.
- **Intermittent segfault under `--cov` (infrastructure, not code).** When the
  full suite runs under coverage instrumentation, ~3 of 10 runs segfault in
  pandas C extensions (most commonly
  `pandas/_libs/tslibs/parsing._guess_datetime_format_for_array`). The crashed
  test varies; sometimes the trace surfaces as an `AttributeError` in
  `yaml.composer` (yaml C ext aliased into the same trace), sometimes as a
  hard SIGSEGV with the extension-modules dump.

  Diagnosis: the pytest-cov / `coverage` tracer races against pandas' and
  yaml's C extensions on this Python 3.12.12 / pandas 2.x / coverage 7.x
  build. Repro: `for i in 1..10; do coverage run -m pytest ...; done` → ~7
  pass, ~3 segfault. No correlation with test order.

  Mitigations tried that did NOT fix it:
  - `[tool.coverage.run] core = "sysmon"` (still races on pandas)
  - Pure-Python yaml loader patch in conftest (yaml wasn't the only culprit)
  - Switching from `pytest --cov` to `coverage run -m pytest` (helped some,
    not all)
  - Vectorizing `pd.to_datetime` in `validate.py:629` (moved the crash to
    other to_datetime call sites; ~31 calls in src, not all hot)

  Pragmatic resolution: **treat coverage as advisory** — re-run if it
  crashes; the test suite itself is 100% deterministic without `--cov` (237
  pass on every run). Coverage numbers are stable when a run completes.
  Worth filing upstream with pandas + coverage if it persists on newer
  builds.

## 8. Recommendation

If V2 is started: also fill items 1-7 from §6 (small CLI + defensive tests).
Estimated +50 covered lines / ~10 short tests / ~30 min effort. Lifts overall
from 89% → ~93%, which clears the 90% gate without chasing INFRASTRUCTURE
coverage that requires EnergyPlus in CI.
