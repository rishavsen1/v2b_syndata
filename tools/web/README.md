# V2B Synthetic Generator — Web Frontend

Browser-based scenario configurator. Pick descriptors via dropdown, tweak
individual knobs, generate, and preview CSVs + manifest inline.

## Run

```bash
cd tools/web/
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

Default port is 5000. Default bind is `127.0.0.1` (local only).

## Expose for LAN demo

Edit the last line of `app.py`:

```python
app.run(host="0.0.0.0", port=5000, debug=False)
```

Then any device on your LAN can reach `http://<your-ip>:5000`. **No auth** —
do not expose to the internet.

## Architecture

- `app.py` — Flask backend. Six endpoints, ~200 lines.
- `static/index.html` — single-page shell.
- `static/style.css` — styling.
- `static/app.js` — all client logic.

No frameworks, no build step. Plotly is loaded from CDN.

### Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/` | index.html |
| GET | `/api/descriptors` | descriptor library (location/building/population/equipment/noise) |
| GET | `/api/knobs` | full `knobs.yaml` |
| GET | `/api/scenarios` | all pre-built scenarios (id, description, descriptors, overrides) |
| POST | `/api/generate` | run the CLI; return manifest + CSV previews |
| GET | `/api/output/<run_id>/<csv_name>` | download a CSV |
| GET | `/api/output/<run_id>/manifest` | download manifest.json |

### Storage

Generated outputs land in `tools/web/runs/<timestamp>_<uuid>/`. Last 20
runs kept; older ones pruned on app startup and on each successful
generate. The `runs/` dir is gitignored.

### Descriptor composition

When the user picks descriptors that differ from the base scenario, the
backend writes a temporary scenario YAML to `configs/scenarios/_web_<run_id>.yaml`,
runs the CLI against that, and deletes it after the subprocess exits.
Any orphan `_web_*.yaml` from a previous crash is cleaned up on app
startup.

## Reproducibility check

Same base + seed + (no overrides) → bitwise-identical CSVs to a direct CLI
invocation. To verify:

```bash
# UI: select S01, seed=42, no overrides, generate
# Then in shell:
python -m v2b_syndata.cli generate --scenario S01 --seed 42 --output-dir /tmp/v2b_cli_ref
sha256sum tools/web/runs/<latest_run_id>/*.csv /tmp/v2b_cli_ref/*.csv | sort
# Pair-up by filename; hashes should match.
```
