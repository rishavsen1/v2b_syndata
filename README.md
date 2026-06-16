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

Output runs land in `tools/web/runs/` (last 20 kept, gitignored). See `tools/web/README.md` for architecture details.

**Remote / SSH fallback.** `127.0.0.1` is loopback on the *server*, so if you run this over SSH the URL won't load in your laptop browser. The app honors `HOST`/`PORT` env vars — bind all interfaces and browse to the host's IP:

```bash
HOST=0.0.0.0 uv run python tools/web/app.py
# → also Running on http://<host-ip>:5000   (e.g. http://10.2.218.193:5000)
```

Then open `http://<host-ip>:5000` from your laptop. Notes:
- Find `<host-ip>` with `hostname -I`.
- If it still won't load, a firewall is blocking the port: `sudo ufw allow 5000/tcp` (when ufw is active).
- "Address already in use" → a stale server holds the port: `fuser -k 5000/tcp`.
- `0.0.0.0` exposes the dev server to your whole LAN; default (`HOST=127.0.0.1`) keeps it loopback-only.

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

**Remote / SSH fallback.** `python -m http.server` already binds all interfaces, so over SSH just swap `localhost` for the host's IP — browse to `http://<host-ip>:8080/walkthrough.html` from your laptop (find `<host-ip>` with `hostname -I`; if it won't load, allow the port: `sudo ufw allow 8080/tcp`).

Full launch options + a recommended new-user usage path live in [`showcase/README.md`](showcase/README.md#how-to-launch-the-interactive-cars--sessions-generation-walkthrough-walkthroughhtml).

## Input datasets (calibration sources)

`v2b-syndata calibrate` fits per-region behavioral distributions from real
charging-session datasets. **Charger logs record *energy* (kWh) and timestamps —
never state-of-charge**, so SoC is modeled, uniformly across every source:

- `arrival_soc   = ` draw from a normal prior (`battery_inference.ARRIVAL_SOC_PRIOR_*`, mean ≈ 0.40) — arrival SoC is *unobserved* in all datasets
- `departure_soc = arrival_soc + kWhDelivered / capacity`   (the SoC the car left at — the calibrated `soc_depart`, `required_soc_at_depart`)

> **Only ACN-Data provides the requested-energy / trip inputs** (`kWhRequested`,
> `milesRequested`, `WhPerMile`), which give it the best **capacity inference**.
> We deliberately do **not** derive arrival SoC from `kWhRequested` (`1 − req/cap`):
> that assumes the request tops the car to full, which the data contradicts
> (ACN delivered/requested ≈ 0.58). Arrival SoC is therefore drawn from a shared
> prior for every source, and the real per-session signal — **delivered energy,
> which all sources record** — drives the departure-SoC requirement.

| source | requested / trip inputs | delivered energy | capacity | SoC model |
|---|---|---|---|---|
| **ACN-Data** (Caltech/JPL/Office001) | ✅ `kWhRequested`, miles, Wh/mi | ✅ | inferred per-session | prior arrival → delivered departure |
| **ElaadNL / 4TU** | ❌ | ✅ | default 60 kWh | prior arrival → delivered departure |
| **EV WATTS** | ❌ | ✅ | default 60 kWh | prior arrival → delivered departure |
| **INL** (EV Project Phase 1) | ❌ | ✅ | default 60 kWh | prior arrival → delivered departure |

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
(`region_distributions.soc_depart`) where available, else a `TruncNorm`
fallback whose mean/std are the knobs `user_behavior.depart_soc_mu` (default 85)
and `user_behavior.depart_soc_sigma` (default 5) — applied only to uncalibrated/
synthetic populations. The only hard SoC constraint is
`required_soc_at_depart > arrival_soc` (D6); the 80% `min_depart_soc` floor (D7)
is a discretionary prior, set to 0 for the data-calibrated cohorts so the
empirical departure SoC is not clamped.

## Multi-building generation (optimus export)

Generate **N distinct buildings in one run** — each with its own base scenario,
descriptor picks, knob overrides, and seed — and export them in the
`optimus-persist-multi` input CSV schema (loader-compatible, with `building_id`).

```bash
uv run python -m v2b_syndata.cli generate-multi \
    --config configs/multi_example.yaml \
    --output-dir data/output/multi/ \
    --output-mode shared          # or per-building

# regenerate a prior run byte-identically from its exported config
uv run python -m v2b_syndata.cli generate-multi \
    --from-config data/output/multi/multi_building_config.json \
    --output-dir data/output/multi_repro/
```

Config (YAML or JSON) — globals at the top, one entry per building:

```yaml
output_mode: shared            # shared (building_id column) | per-building (subfolders)
dr_program: CBP                # global DR; one unified dso_commands.csv
dr_incentive_per_kw: 5.0       # $/kW on committed reduction → dso_commands.incentive
dr_penalty_per_kwh: 12.0       # $/kWh on excess            → dso_commands.penalty
default_policy: ILP-MPCFIXEDFSL
buildings:
  - base_scenario: S01
    descriptors: {location: nashville_tn}
    overrides: {ev_fleet.ev_count: 30}
    seed: 42
  - base_scenario: S01
    descriptors: {building: large_office_v1, location: san_jose_ca}
    overrides: {ev_fleet.ev_count: 25}
    seed: 7
```

- **shared** (default): one concatenated CSV per file with a `building_id`
  column. **per-building**: numbered subfolders `<output-dir>/<building_id>/`,
  each a complete single-building set.
- Output files: `building_load, cars, chargers, sessions, grid_prices,
  weather_data, occupancy, dso_commands` (unified, global), `policies`, plus
  `multi_building_config.json` (the reproducibility record).
- The webapp exposes the same feature: open the **Multi-building** panel, add
  building cards with `+ Add building`, pick the output layout, and generate.

## Architecture

See `handoff/spec/` for full spec (PLAN.md, BAYES_NET.md, validate_spec.md, knobs.yaml).

Tier 0 descriptors → Tier 1 roots → Tier 1.5 per-entity → Tier 2 latents → Tier 3 renderers.

## Step 3 status

This implementation uses **stubs** for EnergyPlus (sinusoid building load) and DR events (deterministic mock events). Real integrations land in Steps 4 and 6. See `docs/DESIGN_NOTES.md` for non-trivial implementation choices.

## Tests

```bash
uv run pytest
```
