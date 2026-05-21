---
description: One-shot repo setup. Installs uv, syncs dependencies, downloads EnergyPlus, verifies, runs a smoke generation.
---

You are setting up the **v2b-syndata** repo on this machine end-to-end with no
manual steps for the user. Treat this like `claude doctor`: detect what is
missing, install or fix it, verify, and report status. Print one short status
line before each phase so the user can follow along. Do not pause for
clarifying questions — make the reasonable call and proceed. Stop and surface
the failure only if a step errors in a way you cannot auto-recover.

The repo is already cloned and you are running inside its root.

### Fast path

A deterministic shell-script equivalent of this command lives at
`tools/setup.sh`. **Try it first**:

```bash
./tools/setup.sh
```

If it exits 0 with every row of the final status table reading `OK`, you are
done — report the status table to the user and stop. The script and the
phases below cover the same intent, so there is no value in re-running them
both.

If the script aborts (unknown platform, GitHub asset rename, missing `curl`,
or anything else the deterministic path can't recover from), capture its
error output and fall through to the manual phases below. You have more
latitude than the script: you can list GitHub release assets, pick a
different tarball, install missing tools, etc.

### Phase 0 — Sanity

1. Confirm CWD contains `pyproject.toml` and `src/v2b_syndata/`. If not, abort
   with a clear message.
2. Detect platform: Linux, macOS (arm64 vs x86_64), or Windows. Save to a
   shell variable; you'll branch on it later.

### Phase 1 — `uv`

1. Check `command -v uv`. If present and `uv --version` runs, skip to Phase 2.
2. Install:
   - **Linux / macOS:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - **Windows:** `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
3. Source the shell rc file or export `PATH` to include `~/.local/bin` so the
   freshly installed `uv` resolves in this same session.
4. Re-verify `uv --version`. If it still fails, abort with the installer
   output verbatim.

### Phase 2 — Python deps

1. Run `uv sync` from the repo root. Stream output.
2. On failure, surface the error and stop — do not retry blindly.

### Phase 3 — EnergyPlus

Goal: a working `energyplus` binary that `discover_energyplus()` finds.

1. Probe first:
   ```bash
   uv run python -c "from v2b_syndata.load_pipeline.ep_runner import discover_energyplus; print(discover_energyplus())"
   ```
   If it prints a path and exits 0, skip the rest of Phase 3.
2. Otherwise install to `~/opt/EnergyPlus-23-2-0/` (user-space, no sudo).
   Default version: **23.2.0**. NREL release assets are on GitHub; pick the
   tarball/zip matching the detected platform:

   | Platform | Asset name (under `v23.2.0`) |
   |---|---|
   | Linux x86_64 (Ubuntu 22.04 / glibc ≥ 2.35) | `EnergyPlus-23.2.0-7636e6b3e9-Linux-Ubuntu22.04-x86_64.tar.gz` |
   | Linux x86_64 (Ubuntu 20.04) | `EnergyPlus-23.2.0-7636e6b3e9-Linux-Ubuntu20.04-x86_64.tar.gz` |
   | macOS arm64 | `EnergyPlus-23.2.0-7636e6b3e9-Darwin-macOS12.1-arm64.tar.gz` |
   | macOS x86_64 | `EnergyPlus-23.2.0-7636e6b3e9-Darwin-macOS12.1-x86_64.tar.gz` |
   | Windows x86_64 | `EnergyPlus-23.2.0-7636e6b3e9-Windows-x86_64.zip` |

   Download from
   `https://github.com/NREL/EnergyPlus/releases/download/v23.2.0/<asset>`
   into `~/.cache/v2b-syndata/` (create if missing), then extract:
   - **Linux/macOS:** `tar -xzf <asset> -C ~/opt/ && mv ~/opt/EnergyPlus-23.2.0-* ~/opt/EnergyPlus-23-2-0`
   - **Windows:** unzip to `C:\EnergyPlusV23-2-0\`

   On Linux, if the GitHub release URL 404s or the asset name has drifted,
   list assets via
   `curl -fsSL https://api.github.com/repos/NREL/EnergyPlus/releases/tags/v23.2.0`
   and pick the Linux x86_64 `.tar.gz` whose name best matches the detected
   glibc/distro (`ldd --version`, `/etc/os-release`). Do **not** silently
   substitute a different EnergyPlus major version.
3. Re-run the `discover_energyplus()` probe. If still missing, print the
   install path you used and instruct the user to set
   `ENERGYPLUS_PATH=<that path>` in their shell rc — but only after you've
   exhausted the automatic options.

### Phase 4 — Smoke test

1. Run a single deterministic generation:
   ```bash
   uv run python -m v2b_syndata.cli generate --scenario S01 --seed 42 \
       --output-dir /tmp/v2b_setup_smoke/
   ```
2. Confirm all 7 CSVs + `manifest.json` exist under that path.
3. Clean up: `rm -rf /tmp/v2b_setup_smoke/`.

### Phase 5 — Report

Print a final summary table:

```
component       status   detail
uv              OK       0.x.y
python deps     OK       uv sync clean
EnergyPlus      OK       ~/opt/EnergyPlus-23-2-0/energyplus  (23.2.0)
smoke gen       OK       S01 seed=42 → 7 CSVs + manifest
```

If anything is `FAIL`, list the next manual step for the user (one line each).
Do not declare success unless every row is `OK`.
