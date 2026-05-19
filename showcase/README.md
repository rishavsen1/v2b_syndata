# v2b_syndata showcase

A self-contained presentation of what `v2b_syndata` produces, how it is
structured, how it is audited, and what comes out of three working example
scenarios.

## Purpose

This directory is the canonical entry point for anyone wanting to understand
`v2b_syndata` without running it. It collects the narrative, slides, figures,
example outputs, and a static exploration notebook in one place.

## Structure

```
showcase/
  OVERVIEW.md                       — main narrative, sections 1-9
  README.md                         — this file
  build_figures.py                  — build script for conceptual figures
  figures/
    01_*.png … 19_*.png            — 19 figures referenced from OVERVIEW
    _build_figures.py              — build script for data-driven figures
  slides/
    overview.md                    — Marp source
    overview.pdf                   — rendered deck (npx marp-cli)
  notebooks/
    exploration.ipynb              — static walkthrough of the 3 examples
  data/
    example_scenarios/
      S01_baseline/                — Nashville, mid-season, default population
      S_clim_miami_summer/         — same population, Miami / July
      S_eq_bi/                     — baseline + bidirectional chargers
```

## How to view

- **OVERVIEW.md** — open on GitHub or any markdown renderer. Embedded figures
  resolve via relative paths to `figures/`.
- **slides/overview.pdf** — any PDF viewer.
- **notebooks/exploration.ipynb** — JupyterLab / VS Code / nbviewer.

## How to re-render slides

```bash
cd showcase
npx @marp-team/marp-cli@latest slides/overview.md --pdf --allow-local-files
```

The `--allow-local-files` flag is required because slides reference figures
under `../figures/`.

## How to re-generate the three example scenarios

From the repo root:

```bash
python -m v2b_syndata.runner --scenario configs/scenarios/S01_baseline.yaml --out showcase/data/example_scenarios/S01_baseline
python -m v2b_syndata.runner --scenario configs/scenarios/S_clim_miami_summer.yaml --out showcase/data/example_scenarios/S_clim_miami_summer
python -m v2b_syndata.runner --scenario configs/scenarios/S_eq_bi.yaml --out showcase/data/example_scenarios/S_eq_bi
```

Each command emits the seven CSVs plus `manifest.json` into the target
directory. Identical seeds reproduce identical outputs (verified by V4).

## How to re-generate the figures

Two build scripts live under `showcase/`:

- `showcase/figures/_build_figures.py` — data-driven figures (those that read
  from `data/example_scenarios/`).
- `showcase/build_figures.py` — conceptual / schematic figures (architecture,
  DAG, position diagram, etc.).

To rebuild all 19 figures:

```bash
python showcase/build_figures.py
python showcase/figures/_build_figures.py
```

Both scripts write into `showcase/figures/` with the canonical
`NN_short_name.png` filename pattern.
