"""Flask backend for the V2B synthetic dataset configurator.

Five JSON endpoints + a static index. The /api/generate endpoint composes
a temporary scenario YAML (if the user has touched descriptor pickers),
then invokes `python -m v2b_syndata.cli generate` as a subprocess and
ships back manifest + CSV previews.

Local-only by default. See README for LAN exposure.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import yaml
from flask import Flask, Response, jsonify, request, send_from_directory

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIGS = REPO_ROOT / "configs"
SCENARIOS_DIR = CONFIGS / "scenarios"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)

GEN_TIMEOUT_SEC = 180
MAX_RUNS_KEPT = 20

app = Flask(__name__, static_folder="static", static_url_path="/static")


# ────────────────────────────────────────────────────────────────────────────
# Config loaders
# ────────────────────────────────────────────────────────────────────────────

def load_descriptors() -> dict:
    out: dict = {}
    for category, filename in [
        ("location", "locations.yaml"),
        ("building", "buildings.yaml"),
        ("population", "populations.yaml"),
        ("equipment", "equipment.yaml"),
    ]:
        with open(CONFIGS / filename) as f:
            data = yaml.safe_load(f) or {}
        out[category] = [
            {"id": k, "description": (v.get("description") or "") if isinstance(v, dict) else ""}
            for k, v in data.items()
        ]
    # noise descriptors are a simpler shape (noise_profiles.yaml)
    with open(CONFIGS / "noise_profiles.yaml") as f:
        nd = yaml.safe_load(f) or {}
    out["noise"] = [
        {"id": k, "description": (v.get("description") or "") if isinstance(v, dict) else ""}
        for k, v in nd.items()
    ]
    return out


def load_knobs() -> dict:
    with open(CONFIGS / "knobs.yaml") as f:
        return yaml.safe_load(f)


def load_scenarios() -> list:
    out = []
    for yml in sorted(SCENARIOS_DIR.glob("*.yaml")):
        if yml.name.startswith("_web_"):
            continue
        with open(yml) as f:
            data = yaml.safe_load(f) or {}
        desc = (data.get("description") or "").split("\n")[0]
        out.append({
            "id": data.get("scenario_id", yml.stem),
            "description": desc,
            "file": yml.name,
            "descriptors": data.get("descriptors", {}),
            "overrides": data.get("overrides", {}),
        })
    return out


def prune_old_runs(keep: int = MAX_RUNS_KEPT) -> None:
    runs = sorted(
        [p for p in RUNS_DIR.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in runs[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def prune_temp_scenarios() -> None:
    for p in SCENARIOS_DIR.glob("_web_*.yaml"):
        try:
            p.unlink()
        except OSError:
            pass


# ────────────────────────────────────────────────────────────────────────────
# Scenario composer
# ────────────────────────────────────────────────────────────────────────────

def _format_override_value(v):
    """Format a Python value as a CLI override value (YAML-parseable)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        # compact flow-style JSON is parsed as YAML
        return json.dumps(list(v))
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v)


def _compose_temp_scenario(base_id: str, descriptors: dict, run_id: str) -> Path:
    """Write a temp scenario YAML that inherits base descriptors and applies
    the user's descriptor picks. Returns its path."""
    base_path = SCENARIOS_DIR / f"{base_id}.yaml"
    if not base_path.exists():
        for yml in SCENARIOS_DIR.glob("*.yaml"):
            with open(yml) as f:
                d = yaml.safe_load(f) or {}
            if d.get("scenario_id") == base_id:
                base_path = yml
                break
    with open(base_path) as f:
        base = yaml.safe_load(f) or {}

    merged_descriptors = dict(base.get("descriptors") or {})
    for k, v in (descriptors or {}).items():
        if v:
            merged_descriptors[k] = v

    new_id = f"_web_{run_id}"
    composed = {
        "scenario_id": new_id,
        "description": f"web-composed from {base_id}",
        "descriptors": merged_descriptors,
    }
    if base.get("overrides"):
        composed["overrides"] = base["overrides"]

    out_path = SCENARIOS_DIR / f"{new_id}.yaml"
    with open(out_path, "w") as f:
        yaml.safe_dump(composed, f, sort_keys=False)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Routes
# ────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/descriptors")
def api_descriptors():
    return jsonify(load_descriptors())


@app.route("/api/knobs")
def api_knobs():
    return jsonify(load_knobs())


@app.route("/api/scenarios")
def api_scenarios():
    return jsonify(load_scenarios())


@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    """Dry-run knob resolution: same chain the CLI uses, no rendering.

    Returns `{knob_path: {value, source}}` reflecting what would land in
    manifest.json if Generate were clicked now with the given base
    scenario + descriptor picks (and no per-knob overrides). The frontend
    uses this to display descriptor-resolved values instead of the
    knobs.yaml defaults.
    """
    from v2b_syndata.descriptor_loader import expand_descriptors, load_scenario
    from v2b_syndata.knob_loader import load_knob_registry, resolve_knobs

    payload = request.get_json(force=True, silent=True) or {}
    base_scenario = payload.get("base_scenario", "S01")
    descriptor_overrides = payload.get("descriptors") or {}

    try:
        scenario_path = SCENARIOS_DIR / f"{base_scenario}.yaml"
        scenario = load_scenario(scenario_path)
        descriptors = dict(scenario.get("descriptors") or {})
        for k, v in descriptor_overrides.items():
            if v:
                descriptors[k] = v
        scenario_overrides = scenario.get("overrides") or {}

        registry = load_knob_registry(CONFIGS / "knobs.yaml")
        descriptor_values = expand_descriptors(descriptors, CONFIGS)
        resolved = resolve_knobs(
            registry=registry,
            descriptor_values=descriptor_values,
            scenario_overrides=scenario_overrides,
            cli_overrides={},
        )
        out = {
            path: {"value": kv.value, "source": kv.source}
            for path, kv in resolved.values.items()
        }
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(force=True, silent=True) or {}
    base_scenario = payload.get("base_scenario", "S01")
    seed = int(payload.get("seed", 42))
    overrides = payload.get("overrides") or {}
    descriptors = payload.get("descriptors") or {}
    noise_profile = payload.get("noise_profile") or None
    strict_e5 = bool(payload.get("strict_e5", False))

    run_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)

    # Compose a temp scenario only if descriptors are non-empty AND differ
    # from base. Keeping the original scenario path preserves D53 hashes
    # when the user doesn't touch the descriptor pickers.
    scenario_id_to_use = base_scenario
    temp_scenario_path: Path | None = None
    if descriptors:
        temp_scenario_path = _compose_temp_scenario(base_scenario, descriptors, run_id)
        scenario_id_to_use = f"_web_{run_id}"

    cmd = [
        sys.executable, "-m", "v2b_syndata.cli",
        "--config-dir", str(CONFIGS),
        "generate",
        "--scenario", scenario_id_to_use,
        "--seed", str(seed),
        "--output-dir", str(run_dir),
    ]
    if noise_profile:
        cmd += ["--noise-profile", noise_profile]
    if strict_e5:
        cmd += ["--strict-e5"]

    for path, value in overrides.items():
        cmd += ["--override", f"{path}={_format_override_value(value)}"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=GEN_TIMEOUT_SEC,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        if temp_scenario_path and temp_scenario_path.exists():
            temp_scenario_path.unlink()
        return jsonify({"error": f"Generation timed out after {GEN_TIMEOUT_SEC}s"}), 504
    finally:
        # Temp scenario file no longer needed once subprocess has exited;
        # the manifest captures resolved knobs from the scenario at run time.
        if temp_scenario_path and temp_scenario_path.exists():
            try:
                temp_scenario_path.unlink()
            except OSError:
                pass

    if result.returncode != 0:
        return jsonify({
            "error": result.stderr or "generation failed (no stderr)",
            "stdout": result.stdout,
            "command": " ".join(cmd),
            "returncode": result.returncode,
        }), 500

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return jsonify({
            "error": "generation completed but manifest.json missing",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }), 500
    with open(manifest_path) as f:
        manifest = json.load(f)

    csv_summaries: dict = {}
    for csv_file in sorted(run_dir.glob("*.csv")):
        df = pd.read_csv(csv_file)
        numeric_df = df.select_dtypes(include="number")
        csv_summaries[csv_file.name] = {
            "row_count": int(len(df)),
            "columns": list(df.columns),
            "head": df.head(50).fillna("").to_dict(orient="records"),
            "dtypes": {c: str(df[c].dtype) for c in df.columns},
            "numeric_stats": (
                numeric_df.describe().fillna(0).to_dict() if not numeric_df.empty else {}
            ),
        }

    prune_old_runs()

    return jsonify({
        "run_id": run_id,
        "manifest": manifest,
        "csv_summaries": csv_summaries,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": " ".join(cmd),
    })


@app.route("/api/output/<run_id>/<csv_name>")
def api_csv(run_id: str, csv_name: str):
    # Path traversal guard: only basenames allowed; nothing fancy.
    if "/" in csv_name or ".." in csv_name or "/" in run_id or ".." in run_id:
        return jsonify({"error": "invalid path"}), 400
    path = RUNS_DIR / run_id / csv_name
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return Response(
        path.read_bytes(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={csv_name}"},
    )


@app.route("/api/output/<run_id>/manifest")
def api_manifest(run_id: str):
    if "/" in run_id or ".." in run_id:
        return jsonify({"error": "invalid path"}), 400
    path = RUNS_DIR / run_id / "manifest.json"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return Response(
        path.read_text(),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=manifest.json"},
    )


if __name__ == "__main__":
    prune_old_runs()
    prune_temp_scenarios()
    app.run(host="127.0.0.1", port=5000, debug=False)
