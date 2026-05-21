# v2b_syndata showcase

A self-contained presentation of what `v2b_syndata` produces, how it is
structured, how it is audited, and what comes out of three working example
scenarios.

## Purpose

This directory is the canonical entry point for anyone wanting to understand
`v2b_syndata` without running it. It collects the narrative, slides, figures,
example outputs, and a static exploration notebook in one place.

## How to view

- **OVERVIEW.md** — open on GitHub or any markdown renderer. Embedded figures
  resolve via relative paths to `figures/`.
- **../notebooks/exploration.ipynb** — JupyterLab / VS Code / nbviewer.
- **short_overview/users_cars_sessions.docx** — Word / Pages / LibreOffice.
- **short_overview/deck.pdf** — any PDF viewer. PPTX export at `deck.pptx`.
- **short_overview/walkthrough.html** — see next section.

## How to launch the interactive walkthrough (`walkthrough.html`)

Single self-contained HTML page. Drag sliders for φ, κ, δ, ρ, region preset,
battery_mix simplex, Dirichlet α, CONSENT cluster — 8 Plotly panels and a
worked-day text trace update live. Loads Plotly 2.27.0 from CDN; everything
else is in the file (no server needed).

**Option A — open directly in browser (simplest)**

```bash
# Linux
xdg-open showcase/short_overview/walkthrough.html

# macOS
open showcase/short_overview/walkthrough.html

# WSL → Windows-side browser
explorer.exe "$(wslpath -w showcase/short_overview/walkthrough.html)"
```

Or paste the absolute path into the browser's address bar:
`file:///home/.../v2b_syndata/showcase/short_overview/walkthrough.html`.

**Option B — serve over HTTP (works headless, port-forwardable)**

```bash
cd showcase/short_overview
python -m http.server 8080
# then open http://localhost:8080/walkthrough.html
```

For a remote / SSH session, port-forward:

```bash
ssh -L 8080:localhost:8080 <user>@<host>
# open http://localhost:8080/walkthrough.html on your laptop
```

**Option C — headless screenshot (no display)**

```bash
google-chrome --headless --disable-gpu --no-sandbox \
  --window-size=1600,2300 --virtual-time-budget=4000 \
  --screenshot=showcase/short_overview/walkthrough_preview.png \
  "file://$(pwd)/showcase/short_overview/walkthrough.html"
```

Requires only Plotly's CDN to be reachable. CDN line: `<script src="https://cdn.plot.ly/plotly-2.27.0.min.js">`.

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

## How to re-render the short overview (doc + deck + figures)

```bash
# figures (3 PNGs)
python showcase/short_overview/_build_figures.py

# Word doc
python showcase/short_overview/_build_docx.py

# Marp deck (PDF + PPTX)
cd showcase/short_overview
npx @marp-team/marp-cli@latest deck.md --pdf  --allow-local-files
npx @marp-team/marp-cli@latest deck.md --pptx --allow-local-files
```

`walkthrough.html` is hand-edited — no build step.
