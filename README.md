# v2b-syndata

Configurable synthetic V2B (Vehicle-to-Building) dataset generator.

Forward-sampling generative model: scenario YAML + seed → bitwise-identical CSVs.

## Quickstart with Claude Code (no manual setup)

If you have [Claude Code](https://claude.com/claude-code) installed, the
entire toolchain — `uv`, Python deps, and EnergyPlus — installs in one shot
with zero manual downloads.

```bash
git clone <this-repo> v2b_syndata
cd v2b_syndata
claude   # opens Claude Code in this directory
```

Then inside Claude Code, run:

```
/setup
```

That slash command is defined in `.claude/commands/setup.md`. Claude Code
will:

1. install `uv` if missing,
2. `uv sync` the Python environment,
3. download and extract a user-local EnergyPlus 23.2.0 into `~/opt/` (no
   sudo, no manual click-through),
4. verify `discover_energyplus()` resolves the binary,
5. run a deterministic smoke generation (`S01` seed=42) and assert all 7
   CSVs + `manifest.json` land on disk,
6. print a status table — every row must read `OK`.

If `/setup` exits with all-OK, skip the rest of this README and jump to
[Generate](#generate). If a step fails, the command prints the next manual
action for that specific failure — follow it and re-run `/setup`; it is
idempotent.

> No Claude Code? Follow the manual install path below.

## Manual install

### Prerequisites

Building load is simulated through EnergyPlus (23.x or newer). Install once
per machine; the package's `load_pipeline.ep_runner.discover_energyplus`
searches the standard locations.

### Linux

1. Download from <https://energyplus.net/downloads> (use the build matching
   your distro — e.g. EnergyPlus 23.2 for Ubuntu 22.04, glibc 2.35).
2. Install or extract to `/usr/local/EnergyPlus-<ver>/` (system) or
   `~/opt/EnergyPlus-<ver>/` (user-space).
3. Either ensure `energyplus` is on `$PATH`, or set
   `ENERGYPLUS_PATH=/path/to/EnergyPlus-<ver>/`.

### macOS / Windows

Same downloader. Default install paths (`/Applications/EnergyPlus-*`,
`C:\EnergyPlusV*`) are auto-discovered.

### Verify

```bash
uv run python -c "from v2b_syndata.load_pipeline.ep_runner import discover_energyplus; print(discover_energyplus())"
```

A missing binary raises `EnergyPlusBinaryNotFound` — generation halts hard;
no silent fallback to a stub.

### Install

```bash
uv sync
```

## Generate

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

## Web frontend

Browser-based scenario configurator. Pick descriptors via dropdowns, tune
individual knobs in the Advanced panel, generate, and preview CSVs +
manifest inline.

```bash
pip install -r tools/web/requirements.txt
python tools/web/app.py
# → Running on http://127.0.0.1:5000
```

Local-only by default. See `tools/web/README.md` for LAN exposure and
architecture details. Output runs land in `tools/web/runs/` (last 20
kept, gitignored).

## Outputs

Per scenario seed:
- `building_load.csv` — flex + inflex building load (15-min)
- `cars.csv` — vehicle physics
- `users.csv` — behavioral axes + CONSENT weights
- `chargers.csv` — charger fleet
- `grid_prices.csv` — energy price tape
- `dr_events.csv` — DR events (header-only if program=none)
- `sessions.csv` — multi-day session log
- `manifest.json` — reproducibility record

## Architecture

See `handoff/spec/` for full spec (PLAN.md, BAYES_NET.md, validate_spec.md, knobs.yaml).

Tier 0 descriptors → Tier 1 roots → Tier 1.5 per-entity → Tier 2 latents → Tier 3 renderers.

## Step 3 status

This implementation uses **stubs** for EnergyPlus (sinusoid building load) and DR events
(deterministic mock events). Real integrations land in Steps 4 and 6. See `docs/DESIGN_NOTES.md`
for non-trivial implementation choices.

## Tests

```bash
uv run pytest
```
