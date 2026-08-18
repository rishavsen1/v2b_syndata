# Campaign config variants (untracked splits, documented here)

Variant split directories are **deliberately untracked** — this file is the
tracked record of what they contain and how to regenerate them.

## `campus_base_phi15` — configs/_campus_base_phi15_split/

- **Source**: exact copies of the tracked `configs/_campus_base_split/b*.yaml`
  (10 buildings, generated from `campus_base.yaml` by
  `tools/campus/split_campus_config.py`).
- **Modifications** (the ONLY diffs, added to every building's `overrides:`):
  1. `user_behavior.phi_scale: 1.5` — densifies weekday appearance beyond the
     source-faithful ceiling. ACN JPL "regular" chargers plug in ~53% of
     weekdays, so an unscaled 30-EV veryhigh building tops out at ~14 distinct
     users/day; 1.5 gives ~20. The scale is recorded in every unit's manifest.
  2. `user_behavior.soc_chain_enforce: true` + `soc_chain_mode: proportional`
     + `soc_chain_draw_min/max: 0.75/1.35` — next arrival = prev departure −
     g × (SoC charged last visit), g ~ U(0.75, 1.35). Design decision
     2026-08-18 (superseding the earlier i.i.d. variant): usage scales with
     the energy the user requested, so continuity arrival < prev departure
     always holds, small refills are not over-drained onto the min-SoC floor
     (the legacy absolute U(10,50) margin piles ~33% of arrivals there), and
     E[g] slightly above 1 cancels the ceiling-truncation drift. First
     sessions draw the truncated Beta(2,3) prior
     (`user_behavior.arrival_soc_alpha/beta`). This makes the synthetic fleet
     building-dependent BY CONSTRUCTION (energy in ≈ energy out at this
     site) — a scenario choice, not a fidelity claim: the real JPL cohort
     demonstrably charges elsewhere (98% of users receive less building
     energy than their own stated driving consumes).
- **Regenerate**:
  ```bash
  mkdir -p configs/_campus_base_phi15_split
  uv run python - <<'PY'
  import yaml, glob
  from pathlib import Path
  for f in glob.glob("configs/_campus_base_split/b*.yaml"):
      c = yaml.safe_load(open(f))
      for b in c["buildings"]:
          o = b.setdefault("overrides", {})
          o["user_behavior.phi_scale"] = 1.5
          o["user_behavior.soc_chain_enforce"] = True
          o["user_behavior.soc_chain_mode"] = "proportional"
          o["user_behavior.soc_chain_draw_min"] = 0.75
          o["user_behavior.soc_chain_draw_max"] = 1.35
      yaml.safe_dump(c, open(Path("configs/_campus_base_phi15_split") / Path(f).name, "w"),
                     sort_keys=False)
  PY
  ```
- **Campaign command** (10 buildings × 12 months × 200 samples):
  ```bash
  SPLIT=configs/_campus_base_phi15_split OUT=data/output/campus_base \
  START=2024-01 END=2024-12 SAMPLES=200 NOISE=clean tools/campus/run_campus.sh 28
  ```
- **Smoke evidence**: `docs/experiments/campus_base_smoke_overview.{png,csv}`
  (energy KS 0.081, dwell 0.071, required-SoC 0.264, 0% of repeat arrivals
  above the prior departure, 20/20 units validated).
