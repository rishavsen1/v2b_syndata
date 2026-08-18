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
  2. `user_behavior.soc_chain_enforce: false` — arrival SoC is one i.i.d.
     truncated Beta(2,3) prior per session (knobs
     `user_behavior.arrival_soc_alpha/beta`) instead of the chained
     prev-departure − U(10,50) draw. Design decision 2026-08-18: the chain
     drew from a prior on unobservable between-visit consumption; workplace
     drivers also charge at home, so day-to-day independence is defensible
     and one model is simpler.
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
          o["user_behavior.soc_chain_enforce"] = False
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
  (energy KS 0.085, dwell 0.071, required-SoC 0.243, 20/20 units validated).
