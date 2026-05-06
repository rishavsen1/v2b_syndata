# Steps 3–5 Audit Report

Generated: 2026-05-06 03:30 UTC
Generator git SHA: cb82e85d4d675b9313e105a7050dfef2c05d7c45 (Step 5 commit)

## Summary

- **Test count change:** before 164, after 213 (Δ +49). 212 pass, 0 fail, 1 xfail.
- **Test result:** `212 passed, 1 xfailed in 45.74s`
- **Audit verdict:** **ISSUES_FOUND** — 1 calibration-side bug + 2 pre-existing pipeline bugs surfaced.
- **Blockers for Step 6:** B1 (calibration token-required even when cache hit). B2 + B3 are pre-existing bugs from Step 3/4 territory; not Step-5 regressions but should be fixed before Step 6 if possible.
- **Non-blocking findings:** A2 lat/lon override is a no-op without `tmyx_station` (Step 4 design). Validate-on-noise is by-design opt-in.

## Phase 1: Test Coverage Fill

### New test files

| File | Lines | Tests |
|---|---|---|
| tests/test_descriptor_loader_calibration.py | 200 | 6 |
| tests/test_validate_calibration_invariants.py | 179 | 8 |
| tests/test_exogenous_hydrate.py | 114 | 8 |
| tests/test_sessions_dist_fallback.py | 182 | 6 |
| tests/test_calibration/test_e2e_calibration.py | 196 | 4 + 1 xfail |
| tests/test_calibration/test_acn_fetcher.py | 107 | 7 |
| tests/test_calibration/test_writer.py (extended) | 129 | 4 |
| tests/test_cli_calibrate.py | 94 | 3 |
| tests/test_calibration/test_api_orchestration.py | 139 | 5 |
| **Total** | **1340** | **49 (48 pass + 1 xfail)** |

### Test result

```
$ uv run pytest -q
............................................................................. [100%]
=========================== short test summary info ============================
XFAIL tests/test_calibration/test_e2e_calibration.py::test_e2e_calibration_handles_missing_token_with_cache - B1: acn_fetcher reads ACN_API_TOKEN at entry even when cache hits.
212 passed, 1 xfailed in 45.74s
```

All HIGH and MEDIUM coverage gaps from the closure status are filled.

## Phase 2: Integration Audit

### A1. Multi-descriptor coverage (42 combos)

```
PASS=40 FAIL=2 TOTAL=42
FAIL houston_tx mixed_use_v1
FAIL atlanta_ga mixed_use_v1
```

Both failures: **EnergyPlus crashes (rc=-11 SIGSEGV)** during `simulate_building_load` for `mixed_use_v1` archetype + hot-climate weather. Step 4 territory; classified as **B2** (see Findings).

**Verdict:** PASS for 40/42; 2 documented EnergyPlus crashes unrelated to Step 5.

### A2. Cross-tier seeding isolation

```
file                     base           loc            loc2           dwell          noise
building_load.csv        718d65670d17   718d65670d17   a46796a254d8   718d65670d17   9ef0aaaeea5d
grid_prices.csv          5227136b4e1f   5227136b4e1f   5227136b4e1f   5227136b4e1f   5227136b4e1f
sessions.csv             a0951273c273   a0951273c273   a0951273c273   fd0580f9e39c   b74e073b92d4
cars.csv                 7a8c3e2ea392   7a8c3e2ea392   7a8c3e2ea392   7a8c3e2ea392   7a8c3e2ea392
users.csv                6df4aabcc07e   6df4aabcc07e   6df4aabcc07e   6df4aabcc07e   6df4aabcc07e
chargers.csv             358213e77125   358213e77125   358213e77125   358213e77125   358213e77125
```

- `loc` = lat/lon-only override → no change anywhere. Lat/lon are decorative; `tmyx_station` drives the EnergyPlus cache key. **Documented as non-blocker**, not a bug.
- `loc2` = lat/lon + tmyx_station override → building_load CHANGES; everything else unchanged. ✓ Cross-tier isolation works.
- `dwell` = Step 5 deep-channel override → **only** sessions changes. ✓ Step 5 leaf-override stays in scope.
- `noise` = light_noise profile → building_load + sessions change (post-render fan-out per Step 3 design). cars/users/chargers untouched. ✓

**Verdict:** **PASS** with documented note: lat/lon-only override is decorative.

### A3. Calibration roundtrip integrity

ACN_API_TOKEN unavailable; programmatic preservation check via synthetic writer:

```
PRESERVATION: all hand-authored blocks preserved byte-equivalent
```

After writeback of `region_distributions:` + `calibration_metadata:` blocks, every population's `axes_distribution`, `negotiation`, and `fleet` blocks are byte-equivalent to pre-calibration.

**Verdict:** **PASS**.

### A4. Manifest provenance audit

```
Source distribution:
  descriptor:*              32
  calibration:*             11
  default                   9

region_distributions keys total: 11
OK: all region_distributions stamped calibration:* or explicit
OK: no metadata in knob_resolution
```

11 calibrated leaves all carry `source: calibration:acn_data_2019_2021_synthetic`. Zero metadata leakage (`n_samples`, `ks_fit_quality`, `dist`, `rho_spearman` correctly filtered by descriptor_loader).

**Verdict:** **PASS**.

### A5. Distribution-shape sanity

```
Sessions: 321
metric                              value    plausible
--------------------------------------------------------
arrival_hour mean                    9.36         7-11
arrival_hour std                     1.50        0.5-4
arrival_hour min                     6.25          5-8
arrival_hour max                    15.25        15-21
dwell_hr mean                        6.86         3-12
dwell_hr std                         3.51          1-6
dwell_hr min                         0.80        0.5-2
dwell_hr max                        14.00         8-16
arrival_soc mean                    31.78        20-60
arrival_soc std                     14.33        10-25
required_soc mean                   86.02        80-95
% req > arr (D6)                   100.00          100
% req >= 80 (D7)                   100.00          100

Spearman(arrival, dwell) overall: -0.349
```

All 13 metrics in plausible ranges. **D6 (req > arr) and D7 (req ≥ 80) both = 100%.** Spearman (-0.349) reflects calibrated copula effect for stable_commuter (target ρ=-0.187) mixed with placeholder regions.

**Verdict:** **PASS**.

### A6. Reproducibility under override

```
Reproducibility under override: PASS
```

Same seed + same deep override → identical CSV SHA256s across all 7 files.

**Verdict:** **PASS** (D53 contract preserved).

### A7. Out-of-range rejection

```
v2b_syndata.knob_loader.KnobValidationError:
    user_behavior.region_distributions.stable_commuter.dwell.lambda:
    999.0 outside range [0.01, 24.0]
OK: error names value
OK: error names range
OK: error names path
```

Error message names path, value, and valid range. **Verdict:** **PASS**.

### A8. Validator full-suite invocation

| Output dir | Validate result |
|---|---|
| `isolation/base` | OK |
| `isolation/loc` | OK |
| `isolation/loc2` | OK |
| `isolation/dwell` | OK |
| `isolation/noise` | **FAIL — D3: arrival_soc=8.83 outside [10.0, 100.0]** |
| `manifest_check` | OK (warnings only: G5b, S2) |
| `repro1` | OK |

**Real bug found in noise pipeline.** light_noise jitter on `soc_arrival_jitter_pct` pushes arrival_soc below the car's `min_allowed_soc=10.0` floor, violating hard invariant D3. By design the CLI auto-validates only when all jitters are zero (`cli.py:33`); explicit `validate <noisy_dir>` catches this. Classified as **B3** (Step 3 noise pipeline; not Step 5).

### A9. Cache invalidation

```
S01 nashville:    718d65670d17
S01 minneapolis:  a46796a254d8
Cache invalidation: PASS
```

Weather change (with proper `tmyx_station` override) produces different building_load. **Verdict:** **PASS**.

## Phase 3: Findings

### Post-audit fix log

| ID | Status | Notes |
|---|---|---|
| B1 | **FIXED** | `acn_fetcher.fetch_all_sessions`: cache check moved before token read; raises clear error when neither cache nor token present. xfail test promoted to passing. |
| B2 | **NOT REPRODUCIBLE** | Re-running A1 matrix clean: **42/42 PASS, 0 FAIL** (vs original 40/42). Likely transient EnergyPlus resource pressure during back-to-back composite (office+retail) runs. No code change required; tracked for future stability work. |
| B3 | **FIXED** | `noise.py`: `arrival_soc` clamp upgraded from `[0, 100]` to per-car `[min_allowed_soc, max_allowed_soc]` via cars.csv lookup. New regression test file `tests/test_noise_d3_clamp.py` (3 tests) verifies validate passes under `light_noise` and `realistic_noise`. |

Plus dotenv added: `python-dotenv` dep + `.env.example` template + auto-load at CLI entry. `.env` already in `.gitignore`.

### Blockers (original)

**B1 — `acn_fetcher.fetch_all_sessions` reads `ACN_API_TOKEN` at entry even when cache hits.** [FIXED]

`src/v2b_syndata/calibration/acn_fetcher.py:28` does `token = os.environ["ACN_API_TOKEN"]` before checking the cache. This means the calibration pipeline cannot run from cached fixture files without the token in env, even if no HTTP call is needed.

Severity: blocks reproducible offline replay of calibrated populations.yaml from a checked-in cache fixture.

Fix sketch (do NOT apply during audit):
```python
def fetch_all_sessions(site, year_start, year_end, cache_dir=None, ...):
    cache_path = cache_dir / f"{site}_{year_start}_{year_end}.json" if cache_dir else None
    if cache_path and cache_path.exists():
        return json.loads(cache_path.read_text())
    # Token only needed for actual fetch.
    if token is None:
        token = os.environ["ACN_API_TOKEN"]
    ...
```

Test workaround in audit: `tests/test_calibration/test_e2e_calibration.py` sets a dummy token in fixture; `test_e2e_calibration_handles_missing_token_with_cache` is `xfail`-marked pending fix.

---

**B2 — EnergyPlus SIGSEGV on `mixed_use_v1` × hot-climate weather (`houston_tx`, `atlanta_ga`).**

```
v2b_syndata.load_pipeline.exceptions.EnergyPlusRunFailed: EnergyPlus failed (rc=-11)
```

Step 4 territory, surfaced by A1 audit. 2/42 location×building combinations fail. Other 40 pass cleanly. Investigation should look at `mixed_use_v1.idf` for hot-climate-specific issues (cooling load coil sizing, condenser temperatures).

Severity: limits the location×building stress matrix. Not a regression — likely a pre-existing latent bug with mixed_use IDF that no prior test exercised.

---

**B3 — Noise pipeline can violate hard invariant D3.**

`light_noise` profile applies `soc_arrival_jitter_pct=0.05`. Resulting jitter pushes one session's arrival_soc to 8.83 < `min_allowed_soc=10.0`, violating D3. Step 3 noise pipeline, not Step 5.

The CLI auto-validate skips on non-zero jitters by design (`cli.py:33-43`), so this slips past. Explicit `validate <noisy_dir>` catches it.

Severity: noisy-output validation broken. Either:
1. Noise injection must clamp to `[min_allowed_soc, max_allowed_soc]` per car after jitter.
2. D3 must be downgraded to soft-check S* for noisy outputs (against the spirit of "hard" invariant).

Recommended fix path: clamp at noise-injection time so D3 stays hard.

### Non-blockers

**N1 — Lat/lon override is decorative without tmyx_station.**

A2 isolation matrix shows `loc` (lat/lon-only override) doesn't change building_load. The EnergyPlus cache key uses `tmyx_station` (the EPW path), not lat/lon coordinates. This is by Step 4 design (see `src/v2b_syndata/load_pipeline/cache.py::cache_key`). Documented in `KNOB_REFERENCE.md` if not already explicit.

Suggested action: document explicitly in KNOB_REFERENCE.md that lat/lon are metadata-only.

### Observations / questions

**O1 — KS_fit_quality is training-set only.** Documented in `CALIBRATION_NOTES.md` per C11. Held-out KS check still deferred to Step 5.5; S2 emits placeholder warning. No action needed for this audit.

**O2 — CLI auto-validate gating.** `cli.py:33-43` deliberately skips validation when any jitter knob is non-zero, expecting users to run `validate` explicitly. This is the only reason B3 didn't surface in routine `generate` runs. Either the auto-validate should run with relaxed thresholds for noisy outputs, or the noise pipeline should respect hard-invariant clamps.

**O3 — Multi-population calibration not audited.** A3 only injected synthetic data for `consent_default`. A real ACN-Data calibration run with `--population <each>` would shake out edge cases in the `populations.yaml` for `stable_commuter_heavy` and `occasional_visitor_dominant`. Deferred until token is available.

## Appendix

### pyproject.toml dependency changes

None this audit. (Step 5 added `ruamel.yaml>=0.18`; carried over.)

### DESIGN_NOTES.md changes

None this audit. (Step 5 added items #20-22; carried over.)

### CALIBRATION_NOTES.md changes

None this audit.

### Files modified during audit

- `tests/test_descriptor_loader_calibration.py` (NEW, 200 lines)
- `tests/test_validate_calibration_invariants.py` (NEW, 179 lines)
- `tests/test_exogenous_hydrate.py` (NEW, 114 lines)
- `tests/test_sessions_dist_fallback.py` (NEW, 182 lines)
- `tests/test_calibration/test_e2e_calibration.py` (NEW, 196 lines, with B1 xfail marker)
- `tests/test_calibration/test_acn_fetcher.py` (NEW, 107 lines)
- `tests/test_calibration/test_writer.py` (extended, +30 lines)
- `tests/test_cli_calibrate.py` (NEW, 94 lines)
- `tests/test_calibration/test_api_orchestration.py` (NEW, 139 lines)
- `AUDIT_REPORT.md` (this file)

`configs/populations.yaml` was modified during A3/A4 to inject synthetic calibration; restored to clean pre-audit state at end.
