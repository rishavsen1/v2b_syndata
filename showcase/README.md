# v2b_syndata showcase

A self-contained presentation of what `v2b_syndata` produces, how it is structured, how it is audited, and what comes out of three working example scenarios.

## Purpose

This directory is the canonical entry point for anyone wanting to understand `v2b_syndata` without running it. It collects the narrative, slides, figures, example outputs, and a static exploration notebook in one place.

## How to view

- **OVERVIEW.md** — open on GitHub or any markdown renderer. Embedded figures
  resolve via relative paths to `figures/`.
- **../notebooks/exploration.ipynb** — JupyterLab / VS Code / nbviewer.
- **short_overview/users_cars_sessions.docx** — Word / Pages / LibreOffice.
- **short_overview/deck.pdf** — any PDF viewer. PPTX export at `deck.pptx`.
- **short_overview/walkthrough.html** — see next section.

## How to launch the interactive cars & sessions generation walkthrough (`walkthrough.html`)

Single self-contained HTML page. Two tabs:

- **Playground** — drag sliders for φ, κ, δ, ρ, region preset,
  battery_mix simplex, Dirichlet α, CONSENT cluster. 10 Plotly panels
  (attendance, D5 outcomes, arrival/dwell/SoC marginals, joint copula
  scatter, required_soc, previous-day external use SoC, battery pie,
  CONSENT cluster) + a worked-day text trace update live.
- **Concepts & 2-car example** — short prose explainer of how the
  behavioral axes relate to region marginals, plus an interactive 2-car
  simulator: pick a region for each car, then drag their per-car
  φ / κ / δ / ρ sliders and watch a 5/7/10-day session table re-derive
  from the same "luck" snapshot.

Loads Plotly 2.27.0 from CDN; everything else is in the file (no server needed).

**Option A — open directly in browser (simplest)**

```bash
# Linux
xdg-open showcase/short_overview/walkthrough.html

# macOS
open showcase/short_overview/walkthrough.html

# WSL → Windows-side browser
explorer.exe "$(wslpath -w showcase/short_overview/walkthrough.html)"
```

Or paste the absolute path into the browser's address bar: `file:///home/.../v2b_syndata/showcase/short_overview/walkthrough.html`.

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

### How to use it — recommended path for a new user

If you've never seen the v2b_syndata generative model before, work through the tabs in this order:

**1. Start in the *Concepts & 2-car example* tab.** Read the opening collapsible — it explains the two-layer hierarchy (a car belongs to a *region* that sets the typical shape, and has a *personality* (φ, κ, δ) that bends those shapes). Then scroll to the 2-car simulator below it. Try this sequence to build intuition:

| Try | What to look for |
|---|---|
| Drag **Car A's φ** from 0.95 down to 0.20 | Car A's column loses rows (skips appear). κ, δ, ρ don't matter for skipped days. |
| Drag **Car A's κ** from 0.90 down to 0.05 | The arrival times in Car A's column spread out across the day (σ_eff widens). |
| Drag **Car A's δ** from 60 km up to 100 km | Car A's `arr_soc` column drops by roughly 10–30 points. Other columns unchanged. |
| Drag **Car A's ρ** from 0 to −0.9 | The link between arrival time and dwell length tightens (look across many days — earliest arrivals get the longest dwells). |
| Change **Car A's region** to `occasional_visitor` | All sliders jump to that region's midpoint, marginals update; trace re-derives. |
| Click **Re-roll week** | New "luck" snapshot — same sliders, different uniform draws. Compare to see what was structural vs random. |

The trick is that slider drags re-interpret the *same* random uniforms, so the change you see is the **causal** effect of that axis, not noise.

**2. Switch to the *Playground* tab.** Use this to inspect the marginal shapes themselves under any (φ, κ, δ, ρ) and any direct override of the region marginals (μ, σ, k, λ, α, β, shift). Key things to do:

- Pick a region preset (left panel) → all sliders + plot shapes snap to
  defaults for that region.
- Drag ρ around → the joint scatter tilts, but the arrival and dwell
  histograms stay statistically identical (that's the copula
  property; verifies the model is right).
- Drag δ around → the arrival-SoC histogram shifts horizontally; its
  shape doesn't change.
- Edit the `battery_mix` simplex (4 sliders) and drop Dirichlet α to 1
  → the pie chart varies wildly between re-samples; raise α to 1e6 →
  it locks to declared.
- Click **Re-sample** (bottom of the controls) → re-rolls 5000 draws
  per plot. The worked-day trace at the bottom also re-rolls.

**3. Cross-check with the source.** Each interactive piece mirrors a specific spot in the codebase — verify by reading these together:

- Copula step → `src/v2b_syndata/renderers/sessions.py:44–50` (the
  `_gaussian_copula_pair` function) and `:124–137` (sampling
  dispatch).
- Region marginal parameters → `configs/populations.yaml:54–88`
  (consent_default region grid).
- battery_mix override path → CLI: `python -m v2b_syndata.cli generate
  --override 'ev_fleet.battery_mix=[0.2,0.3,0.4,0.1]'`. Web UI:
  open `tools/web` and edit the simplex widget at the
  `ev_fleet.battery_mix` knob.

**4. To run the actual generator**, see [Generate](../README.md#generate) in the root README, or use the Flask web UI under `tools/web/`.

> **No installation required to use this walkthrough.** It's just an
> HTML file — internet access is needed only to load Plotly from the
> CDN once. Everything else (samplers, region presets, copula math)
> runs locally in the browser.

## How to re-render slides

```bash
cd showcase
npx @marp-team/marp-cli@latest slides/overview.md --pdf --allow-local-files
```

The `--allow-local-files` flag is required because slides reference figures under `../figures/`.

## How to re-generate the three example scenarios

From the repo root:

```bash
python -m v2b_syndata.runner --scenario configs/scenarios/S01_baseline.yaml --out showcase/data/example_scenarios/S01_baseline
python -m v2b_syndata.runner --scenario configs/scenarios/S_clim_miami_summer.yaml --out showcase/data/example_scenarios/S_clim_miami_summer
python -m v2b_syndata.runner --scenario configs/scenarios/S_eq_bi.yaml --out showcase/data/example_scenarios/S_eq_bi
```

Each command emits the seven CSVs plus `manifest.json` into the target directory. Identical seeds reproduce identical outputs (verified by V4).

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

Both scripts write into `showcase/figures/` with the canonical `NN_short_name.png` filename pattern.

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
