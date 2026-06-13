# v2b-syndata

Configurable synthetic V2B (Vehicle-to-Building) dataset generator.

Forward-sampling generative model: scenario YAML + seed → bitwise-identical CSVs.

## Quickstart — one command, any agent (or none)

`tools/setup.sh` installs the entire toolchain end-to-end: `uv`, Python deps, a user-local EnergyPlus 23.2.0 under `~/opt/`, and runs a smoke generation. Idempotent; safe to re-run.

```bash
cd v2b_syndata
./tools/setup.sh
```

It prints a final status table; every row must read `OK`. If any phase fails, the script aborts with the next manual step inline.

### Using an agentic CLI?

Any agent can run the script — it's just a shell command. If you'd rather have the agent drive the install interactively (so it can adapt to platform edge cases the script doesn't cover):

| Agent | How to invoke |
|---|---|
| **Claude Code** | open the repo with `claude`, then type `/setup` (defined at `.claude/commands/setup.md`) |
| **Copilot CLI / Codex / Gemini CLI / Cursor / Aider / …** | tell the agent: *"run `tools/setup.sh`; if it errors, fall back to the steps in `.claude/commands/setup.md`"* |

The two paths are equivalent: the shell script is the deterministic fast path; the markdown command file gives an agent the same intent with room to improvise when something unusual happens (unknown distro, asset 404, missing curl, etc.).

> No agent and no script — follow the manual install path below.

## Manual install

### Prerequisites

Building load is simulated through EnergyPlus (23.x or newer). Install once per machine; the package's `load_pipeline.ep_runner.discover_energyplus` searches the standard locations.

### Linux

1. Download from <https://energyplus.net/downloads> (use the build matching
   your distro — e.g. EnergyPlus 23.2 for Ubuntu 22.04, glibc 2.35).
2. Install or extract to `/usr/local/EnergyPlus-<ver>/` (system) or
   `~/opt/EnergyPlus-<ver>/` (user-space).
3. Either ensure `energyplus` is on `$PATH`, or set
   `ENERGYPLUS_PATH=/path/to/EnergyPlus-<ver>/`.

### macOS / Windows

Same downloader. Default install paths (`/Applications/EnergyPlus-*`, `C:\EnergyPlusV*`) are auto-discovered.

### Verify

```bash
uv run python -c "from v2b_syndata.load_pipeline.ep_runner import discover_energyplus; print(discover_energyplus())"
```

A missing binary raises `EnergyPlusBinaryNotFound` — generation halts hard; no silent fallback to a stub.

### Install

```bash
uv sync
```

## Web frontend (recommended for first run)

Browser-based scenario configurator. Pick descriptors via dropdowns, tune individual knobs in the Advanced panel, generate, and preview CSVs + manifest inline. Easiest way to drive the generator end-to-end without learning the CLI flags.

Flask is bundled in the main `uv sync` install — no extra `pip install` step needed.

```bash
uv run python tools/web/app.py
# → Running on http://127.0.0.1:5000
```

Local-only by default. See `tools/web/README.md` for LAN exposure and architecture details. Output runs land in `tools/web/runs/` (last 20 kept, gitignored).

## Generate (CLI)

```bash
uv run python -m v2b_syndata.cli generate \
    --scenario S01 \
    --seed 42 \
    --output-dir data/output/dev/S01/seed42/

uv run python -m v2b_syndata.cli validate data/output/dev/S01/seed42/
```

## Other commands

```bash
uv run python -m v2b_syndata.cli list-knobs
uv run python -m v2b_syndata.cli list-scenarios
```

## Interactive walkthrough — no install needed

`showcase/short_overview/walkthrough.html` is a self-contained, install-free page that explains how `users.csv → cars.csv → sessions.csv` are generated. Open it in any browser. Two tabs:

- **Playground** — slide φ, κ, δ, ρ, region preset, battery_mix simplex,
  Dirichlet α, CONSENT cluster; 10 live Plotly panels + a worked-day text
  trace update on every drag.
- **Concepts & 2-car example** — prose explainer of how the behavioral
  axes relate to the region marginals, plus an interactive 2-car
  week-long session simulator (per-car region + φ / κ / δ / ρ sliders;
  deterministic luck so slider drags show the *causal* effect of each
  axis).

```bash
# Linux
xdg-open showcase/short_overview/walkthrough.html
# macOS
open    showcase/short_overview/walkthrough.html
# WSL → Windows browser
explorer.exe "$(wslpath -w showcase/short_overview/walkthrough.html)"
# Headless / remote
cd showcase/short_overview && python -m http.server 8080
#   → http://localhost:8080/walkthrough.html
```

Full launch options + a recommended new-user usage path live in [`showcase/README.md`](showcase/README.md#how-to-launch-the-interactive-cars--sessions-generation-walkthrough-walkthroughhtml).

## Input datasets (calibration sources)

`v2b-syndata calibrate` fits per-region behavioral distributions from real
charging-session datasets. **Charger logs record *energy* (kWh) and timestamps —
never state-of-charge.** SoC is *reconstructed*:

- `arrival_soc   = 1 − kWhRequested / capacity`   (needs requested energy)
- `departure_soc = arrival_soc + kWhDelivered / capacity`   (the SoC the car left at)

> **Only ACN-Data provides the full picture** — it logs the user's *requested*
> energy as a kiosk input, so arrival (and hence departure) SoC are exact. Every
> other source records **delivered energy only**; for those, arrival SoC is
> estimated from a normal prior (`battery_inference.ARRIVAL_SOC_PRIOR_*`,
> mean ≈ 0.40) and the departure-SoC requirement is taken from
> `arrival + delivered/capacity`.

| source | requested energy | delivered energy | arrival / departure SoC |
|---|---|---|---|
| **ACN-Data** (Caltech/JPL/Office001) | ✅ `kWhRequested` | ✅ | exact (full picture) |
| **ElaadNL / 4TU** | ❌ | ✅ | arrival estimated (prior) → departure |
| **EV WATTS** | ❌ | ✅ | arrival estimated (prior) → departure |
| **INL** (EV Project Phase 1) | ❌ | ✅ | arrival estimated (prior) → departure |

Raw per-session fields, by source:

- **ACN-Data:** `sessionID, userID, siteID, stationID, connectionTime, disconnectTime, kWhDelivered, userInputs{milesRequested, WhPerMile, kWhRequested, minutesAvailable}`
- **ElaadNL / 4TU:** `EV_id_x, start_datetime, end_datetime, total_energy, capacity_kwh, commute_km_range_min/max, EV_brand/model_selfreported, ownership`
- **EV WATTS:** `evse_id, venue_type, rated_power_kw, start_time_utc, end_time_utc, energy_kwh`
- **INL:** `vehicle_id, evse_id, venue, evse_power_kw, start_time, end_time, energy_kwh`

All sources normalize into one internal record before calibration —
`SessionFeatures{user_id, site, arrival_time, arrival_hour, dwell_hours, kwh_delivered, miles_requested?, wh_per_mile?, kwh_requested?, minutes_available?}`
(the `?` fields are populated for ACN only).

## Outputs

Per scenario seed — deterministic CSVs (bitwise-identical for a given seed) + a manifest:

| file | columns |
|---|---|
| `users.csv` | `car_id, region, phi, kappa, delta_km, negotiation_type, w1, w2` |
| `cars.csv` | `car_id, capacity_kwh, min_allowed_soc, max_allowed_soc, battery_class` |
| `chargers.csv` | `charger_id, directionality, min_rate_kw, max_rate_kw` |
| `sessions.csv` | `session_id, car_id, building_id, arrival, departure, duration_sec, arrival_soc, required_soc_at_depart, previous_day_external_use_soc` |
| `building_load.csv` | `datetime, power_flex_kw, power_inflex_kw, power_kw` (15-min, EnergyPlus) |
| `grid_prices.csv` | `datetime, price_per_kwh, type` |
| `dr_events.csv` | `event_id, start, end, magnitude_kw, notified_at` (header-only if program=none) |
| `manifest.json` | knob resolution + provenance (reproducibility record) |

`sessions.csv` SoC columns are *synthesized*: `arrival_soc` from the per-region
calibrated Beta, and `required_soc_at_depart` from the calibrated departure-SoC
(`region_distributions.soc_depart`) where available, else the `N(85, 5)` prior.
The only hard SoC constraint is `required_soc_at_depart > arrival_soc` (D6); the
80% `min_depart_soc` floor (D7) is a discretionary prior, set to 0 for the
data-calibrated cohorts so the empirical departure SoC is not clamped.

## Architecture

See `handoff/spec/` for full spec (PLAN.md, BAYES_NET.md, validate_spec.md, knobs.yaml).

Tier 0 descriptors → Tier 1 roots → Tier 1.5 per-entity → Tier 2 latents → Tier 3 renderers.

## Step 3 status

This implementation uses **stubs** for EnergyPlus (sinusoid building load) and DR events (deterministic mock events). Real integrations land in Steps 4 and 6. See `docs/DESIGN_NOTES.md` for non-trivial implementation choices.

## Tests

```bash
uv run pytest
```
