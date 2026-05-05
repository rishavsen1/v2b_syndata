# Handoff Bundle for Claude Code

This bundle contains everything Claude Code needs to build the V2B synthetic dataset generator.

## Contents

```
handoff/
├── CLAUDE_CODE_PROMPT.md       # Paste this as the initial prompt
└── spec/                        # Reference files Claude Code will read
    ├── PLAN.md                  # Project plan and architecture
    ├── BAYES_NET.md             # Generator DAG specification
    ├── DATASET_AUDIT.md         # Dataset usage map
    ├── ACN_DATA_CALIBRATION.md  # Future calibration plan (not implemented now)
    ├── validate_spec.md         # 40+ invariant checks
    ├── knobs.yaml               # Full tunable knob registry
    ├── bayes_net_v7.png         # Visual DAG (PNG)
    ├── bayes_net_v7.svg         # Visual DAG (SVG)
    └── configs/
        ├── locations.yaml
        ├── buildings.yaml
        ├── populations.yaml
        ├── equipment.yaml
        ├── noise_profiles.yaml
        └── scenarios/
            └── S01.yaml
```

## How to use

### Option A: Claude Code in a fresh project directory

```bash
# 1. Make a fresh directory for the v2b-syndata project
mkdir ~/projects/v2b-syndata && cd ~/projects/v2b-syndata

# 2. Copy the entire handoff bundle into it (Claude Code reads from here)
cp -r /path/to/handoff ./handoff

# 3. Start Claude Code in this directory
claude

# 4. Inside Claude Code, paste the prompt:
#    Open handoff/CLAUDE_CODE_PROMPT.md, copy the entire contents,
#    and paste it as your first message
```

### Option B: Use Claude Code's --file flag

```bash
cd ~/projects/v2b-syndata
cp -r /path/to/handoff ./handoff
claude --file handoff/CLAUDE_CODE_PROMPT.md
```

### Option C: Reference the prompt directly

```bash
cd ~/projects/v2b-syndata
cp -r /path/to/handoff ./handoff
claude
# Then in Claude Code: "Read handoff/CLAUDE_CODE_PROMPT.md and execute the build instructions."
```

## What Claude Code will produce

A complete `v2b-syndata/` repository with:
- `pyproject.toml` (uv-managed)
- `src/v2b_syndata/` Python package
- `configs/` (copied from handoff/spec/configs/)
- `tests/` with pytest suite
- Working CLI: `python -m v2b_syndata.cli generate --scenario S01 --seed 42`
- All hard invariants passing
- Bitwise reproducibility verified

## After Claude Code finishes

You will have a working synthetic dataset generator that:
- Generates dummy data via stubs (sinusoid building load, mock DR events)
- Has the full DAG architecture in place
- Passes validation
- Reproducibility-confirmed

**Next steps (separate Claude Code sessions):**

1. **Step 4: EnergyPlus integration** — wrap your existing EnergyPlus + DOE + NASAPower pipeline as the `samplers/load.py` adapter. You'll provide the pipeline interface details to Claude Code in a new prompt.

2. **Step 5: ACN-Data calibration** — implement the workstream in `ACN_DATA_CALIBRATION.md`. Outputs fitted distributions to `populations.yaml`.

3. **Step 6: DR Poisson sampler** — replace `dr_events.py` stub with the inhomogeneous Poisson process per CBP/BIP rules.

4. **Step 7+: Scenario library expansion + experiments E1–E8.**

## Notes

- The `CLAUDE_CODE_PROMPT.md` is self-contained. It tells Claude Code to read the spec files in order, not to re-design anything, and exactly what to build.
- All 28 design decisions (D1–D28) are baked into the spec. Claude Code should not need to make new architectural choices.
- If Claude Code asks clarifying questions during the build, it will document them in `DESIGN_NOTES.md` at the repo root.
- The build is one continuous session — expect Claude Code to use multiple turns to implement, test, and iterate. Don't interrupt unless it goes off-track.

## Troubleshooting

**If Claude Code starts redesigning instead of implementing:**
> "Stop. Re-read CLAUDE_CODE_PROMPT.md and the spec/ files. Implement to spec; do not redesign."

**If invariants fail:**
> "Run pytest -x and fix the first failing test. Do not skip or modify invariants — fix the implementation."

**If you want to add features mid-build:**
> Don't. Let Claude Code finish Step 3 first, then start a new session for additional work.
