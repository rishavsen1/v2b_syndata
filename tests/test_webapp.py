"""Flask endpoint coverage for the web tool.

Two layers:
- `webapp` (fast): read-only + resolve endpoints, and the generate-unified
  *contract* (spawns the CLI subprocess, verifies the config it builds, then
  kills it — no EnergyPlus wait).
- `real_energyplus`: the full generate-unified cycle (poll → CSV → download)
  with per-building override + noise isolation.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "web"))
import app as webapp  # noqa: E402


@pytest.fixture
def client():
    return webapp.app.test_client()


# ── read-only + resolve (fast) ───────────────────────────────────────────────

@pytest.mark.webapp
def test_der_panel_wired_in_app_js():
    """PV + battery are surfaced in the main-card DER panel (not the generic
    Advanced auto-render). Fast static guard for the wiring the browser test
    exercises live."""
    app_js = (Path(__file__).resolve().parents[1]
              / "tools" / "web" / "static" / "app.js").read_text()
    assert "card-der-knobs" in app_js and "populateCardDer" in app_js
    assert 'bucket === "pv" || bucket === "battery"' in app_js  # excluded from Advanced


@pytest.mark.webapp
def test_api_knobs_serves_der_buckets(client):
    k = client.get("/api/knobs").get_json()
    assert "pv" in k and "battery" in k


@pytest.mark.webapp
def test_tour_assets_wired():
    web = Path(__file__).resolve().parents[1] / "tools" / "web"
    assert (web / "static" / "vendor" / "driver.js.iife.js").exists()
    assert (web / "static" / "vendor" / "driver.css").exists()
    idx = (web / "static" / "index.html").read_text()
    assert "start-tour" in idx and "tour.js" in idx and "driver.js.iife.js" in idx
    assert "startTour" in (web / "static" / "tour.js").read_text()


@pytest.mark.webapp
def test_static_vendor_served(client):
    assert client.get("/static/vendor/driver.js.iife.js").status_code == 200
    assert client.get("/static/vendor/driver.css").status_code == 200


@pytest.mark.webapp
def test_api_der_catalog(client):
    c = client.get("/api/der-catalog").get_json()
    assert c["pv"]["rooftop_large"]["dc_capacity_kw"] == 250.0
    assert "label" in c["pv"]["rooftop_small"]
    b = c["battery"]["lfp_4h"]
    assert b["capacity_kwh"] == 400.0 and b["power_kw"] == 100.0


@pytest.mark.webapp
def test_descriptors_knobs_scenarios(client):
    for route, key in [("/api/descriptors", "location"), ("/api/knobs", "ev_fleet")]:
        d = client.get(route).get_json()
        assert key in d
    scn = client.get("/api/scenarios").get_json()
    assert any(s["id"] == "S01" for s in scn)
    s01 = next(s for s in scn if s["id"] == "S01")
    assert {"location", "building", "population"} <= set(s01["descriptors"])


@pytest.mark.webapp
def test_resolve_returns_knob_values(client):
    d = client.post("/api/resolve", json={"base_scenario": "S01", "descriptors": {}}).get_json()
    for p in ("ev_fleet.ev_count", "charging_infra.charger_count", "building_load.peak_kw",
              "ev_fleet.min_allowed_soc", "ev_fleet.max_allowed_soc"):
        assert p in d and "value" in d[p]
    # descriptor changes the resolution
    d2 = client.post("/api/resolve", json={"base_scenario": "S01",
                                           "descriptors": {"building": "large_office_v1"}}).get_json()
    assert d2["building_load.peak_kw"]["value"] != d["building_load.peak_kw"]["value"]


@pytest.mark.webapp
def test_bad_route_returns_html_not_json(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "text/html" in r.headers.get("Content-Type", "")  # safeJson path on the client


@pytest.mark.webapp
def test_generate_unified_validation(client):
    assert client.post("/api/generate-unified", json={"buildings": []}).status_code == 400
    r = client.post("/api/generate-unified",
                    json={"buildings": [{"base_scenario": "S01"}]})  # no start_month
    assert r.status_code == 400


@pytest.mark.webapp
def test_generate_unified_builds_per_building_config(client, tmp_path):
    """The endpoint writes a config with each building self-contained (no global
    shared_overrides). Spawn then immediately kill — no EnergyPlus wait."""
    payload = {
        "buildings": [
            {"base_scenario": "S01", "descriptors": {"location": "nashville_tn"},
             "overrides": {"ev_fleet.ev_count": 4, "utility_rate.dr_lambda_base": 0.5},
             "seed": 1, "noise_profile": "clean", "weather_profile": "none"},
            {"base_scenario": "S01", "descriptors": {"location": "san_jose_ca"},
             "overrides": {"ev_fleet.ev_count": 9, "utility_rate.dr_lambda_base": 2.0},
             "seed": 2, "noise_profile": "tmyx_stochastic", "weather_profile": "moderate"},
        ],
        "output_mode": "shared", "output_path": str(tmp_path / "o"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 3, "workers": 1,
        "dr_program": "CBP",
    }
    r = client.post("/api/generate-unified", json=payload)
    assert r.status_code == 200
    job = r.get_json()["job_id"]
    try:
        cfg_files = list(webapp.RUNS_DIR.glob(f"_unified_cfg_{job}.json"))
        assert cfg_files, "temp config not written to RUNS_DIR (must not leak to repo root)"
        cfg = json.loads(cfg_files[0].read_text())
        assert len(cfg["buildings"]) == 2
        assert cfg["buildings"][0]["overrides"]["ev_fleet.ev_count"] == 4
        assert cfg["buildings"][1]["overrides"]["ev_fleet.ev_count"] == 9
        assert cfg["buildings"][0]["noise_profile"] == "clean"
        assert cfg["buildings"][1]["noise_profile"] == "tmyx_stochastic"
        # weather perturbation is per-building (written into each spec)
        assert cfg["buildings"][0]["weather_profile"] == "none"
        assert cfg["buildings"][1]["weather_profile"] == "moderate"
        assert cfg["dr_program"] == "CBP"
        assert "shared_overrides" not in cfg
    finally:
        webapp.BATCH_JOBS[job]["process"].terminate()


@pytest.mark.webapp
def test_generate_unified_run_level_sample_variation(client, tmp_path):
    """Run-level noise/weather/Dirichlet-α controls flow through the unified
    endpoint: noise + weather → CLI flags; the two α's → shared_overrides merged
    into every building. Spawn then immediately kill — no EnergyPlus wait."""
    payload = {
        "buildings": [
            {"base_scenario": "S01", "seed": 1},
            {"base_scenario": "S01", "seed": 2},
        ],
        "output_mode": "shared", "output_path": str(tmp_path / "o"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 1, "workers": 1,
        "noise_profile": "clean", "weather_profile": "moderate", "weather_sigma_c": 1.5,
        "shared_overrides": {
            "user_behavior.axes_distribution_dirichlet_alpha": 12,
            "ev_fleet.battery_mix_dirichlet_alpha": 7,
        },
    }
    r = client.post("/api/generate-unified", json=payload)
    assert r.status_code == 200
    job = r.get_json()["job_id"]
    try:
        cmd = webapp.BATCH_JOBS[job]["cmd"]
        # run-level noise + weather forwarded as CLI flags
        assert "--noise-profile" in cmd and cmd[cmd.index("--noise-profile") + 1] == "clean"
        assert "--weather-profile" in cmd and cmd[cmd.index("--weather-profile") + 1] == "moderate"
        assert "--weather-sigma-c" in cmd and cmd[cmd.index("--weather-sigma-c") + 1] == "1.5"
        # α's merged into every building via shared_overrides
        cfg = json.loads(list(webapp.RUNS_DIR.glob(f"_unified_cfg_{job}.json"))[0].read_text())
        assert "shared_overrides" not in cfg  # collapsed into each building
        for b in cfg["buildings"]:
            assert b["overrides"]["user_behavior.axes_distribution_dirichlet_alpha"] == 12
            assert b["overrides"]["ev_fleet.battery_mix_dirichlet_alpha"] == 7
    finally:
        webapp.BATCH_JOBS[job]["process"].terminate()


@pytest.mark.webapp
def test_generate_unified_defaults_unchanged(client, tmp_path):
    """A default run (no run-level controls set) still uses the historical
    default noise profile and forwards no weather/α flags → output unchanged."""
    payload = {
        "buildings": [{"base_scenario": "S01", "seed": 1}],
        "output_path": str(tmp_path / "o"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 1, "workers": 1,
    }
    r = client.post("/api/generate-unified", json=payload)
    job = r.get_json()["job_id"]
    try:
        cmd = webapp.BATCH_JOBS[job]["cmd"]
        assert cmd[cmd.index("--noise-profile") + 1] == "tmyx_stochastic"
        assert "--weather-profile" not in cmd
        assert "--weather-sigma-c" not in cmd
        cfg = json.loads(list(webapp.RUNS_DIR.glob(f"_unified_cfg_{job}.json"))[0].read_text())
        ov = cfg["buildings"][0]["overrides"]
        assert "user_behavior.axes_distribution_dirichlet_alpha" not in ov
        assert "ev_fleet.battery_mix_dirichlet_alpha" not in ov
    finally:
        webapp.BATCH_JOBS[job]["process"].terminate()


@pytest.mark.webapp
def test_batch_forwards_alpha_and_noise_flags(client, tmp_path):
    """/api/batch surfaces noise_profile and forwards --axes-alpha/--battery-alpha
    when set. Spawn then kill (no EnergyPlus wait)."""
    payload = {
        "base_scenario": "S01", "output_path": str(tmp_path / "b"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 1, "workers": 1,
        "noise_profile": "clean", "axes_alpha": 5, "battery_alpha": 9,
    }
    r = client.post("/api/batch", json=payload)
    assert r.status_code == 200
    bid = r.get_json()["batch_id"]
    try:
        cmd = webapp.BATCH_JOBS[bid]["cmd"]
        assert cmd[cmd.index("--noise-profile") + 1] == "clean"
        assert "--axes-alpha" in cmd and cmd[cmd.index("--axes-alpha") + 1] == "5.0"
        assert "--battery-alpha" in cmd and cmd[cmd.index("--battery-alpha") + 1] == "9.0"
    finally:
        webapp.BATCH_JOBS[bid]["process"].terminate()


@pytest.mark.webapp
def test_batch_defaults_no_alpha_flags(client, tmp_path):
    """Without explicit α's, /api/batch forwards no alpha flags (batch applies
    its own tmyx_stochastic default), keeping default runs unchanged."""
    payload = {
        "base_scenario": "S01", "output_path": str(tmp_path / "b2"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 1, "workers": 1,
    }
    bid = client.post("/api/batch", json=payload).get_json()["batch_id"]
    try:
        cmd = webapp.BATCH_JOBS[bid]["cmd"]
        assert "--axes-alpha" not in cmd and "--battery-alpha" not in cmd
        assert cmd[cmd.index("--noise-profile") + 1] == "tmyx_stochastic"
    finally:
        webapp.BATCH_JOBS[bid]["process"].terminate()


@pytest.mark.webapp
def test_index_html_has_run_level_controls():
    """The run-grid surfaces the four run-level sample-variation controls; app.js
    populates + wires them with the F2 effective-default pre-fill."""
    web = Path(__file__).resolve().parents[1] / "tools" / "web" / "static"
    idx = (web / "index.html").read_text()
    for el in ("u-noise-profile", "u-weather-profile", "u-weather-sigma-c",
               "u-axes-alpha", "u-battery-alpha"):
        assert el in idx, f"{el} missing from index.html"
    app_js = (web / "app.js").read_text()
    assert "initRunLevelControls" in app_js and "updateAlphaPlaceholders" in app_js
    # F2 effective α pre-fill (30 under tmyx_stochastic, 1e6 otherwise)
    assert "ALPHA_TMYX = 30" in app_js and "ALPHA_OFF = 1e6" in app_js
    # payload wiring: run-level noise/weather + α's into shared_overrides
    assert "payload.noise_profile" in app_js and "payload.weather_profile" in app_js
    assert "user_behavior.axes_distribution_dirichlet_alpha" in app_js
    assert "ev_fleet.battery_mix_dirichlet_alpha" in app_js
    # F4: the stale #u-weather-sigma comment now matches the real control id
    assert "#u-weather-sigma-c" in app_js


@pytest.mark.webapp
def test_unified_status_csv_download_fake_job(client, tmp_path):
    """Cover the status/csv/download endpoints without EnergyPlus by registering
    a finished fake job over a hand-built output tree."""
    import subprocess

    out = tmp_path / "fake"
    (out / "APR2024" / "0").mkdir(parents=True)
    (out / "batch_manifest.json").write_text(json.dumps({
        "batch_id": "x", "kind": "multi_building", "n_buildings": 2, "output_mode": "shared",
        "status": "succeeded", "n_total": 1, "n_succeeded": 1, "n_failed": 0,
        "samples": [{"month": "APR2024", "sample_idx": 0, "status": "succeeded",
                     "seed": 1, "path": "APR2024/0"}],
    }))
    (out / "APR2024" / "0" / "cars.csv").write_text(",car_id,building_id\n0,1,0\n1,2,1\n")
    proc = subprocess.Popen([sys.executable, "-c", "pass"]); proc.wait()
    job = "fakejob123"
    webapp.BATCH_JOBS[job] = {"process": proc, "output_path": str(out),
                              "started_at": 0.0, "cmd": [], "kind": "unified"}

    st = client.get(f"/api/generate-unified/{job}/status").get_json()
    assert st["running"] is False and st["manifest"]["status"] == "succeeded"
    csv = client.get(f"/api/generate-unified/{job}/csv/APR2024/0/cars.csv")
    assert csv.status_code == 200 and b"car_id" in csv.get_data()
    # path traversal guard
    assert client.get(f"/api/generate-unified/{job}/csv/..%2f..%2f/0/cars.csv").status_code in (400, 404)
    z = client.get(f"/api/generate-unified/{job}/download")
    assert z.status_code == 200 and z.headers["Content-Type"] == "application/zip"
    assert client.get("/api/generate-unified/nope/status").status_code == 404


# ── full cycle (real EnergyPlus) ─────────────────────────────────────────────

@pytest.mark.real_energyplus
def test_generate_unified_full_cycle(client, tmp_path):
    payload = {
        "buildings": [
            {"base_scenario": "S01", "descriptors": {"location": "nashville_tn"},
             "overrides": {"ev_fleet.ev_count": 4, "charging_infra.charger_count": 4}, "seed": 1},
            {"base_scenario": "S01", "descriptors": {"location": "nashville_tn"},
             "overrides": {"ev_fleet.ev_count": 9, "charging_infra.charger_count": 9}, "seed": 2},
        ],
        "output_mode": "shared", "output_path": str(tmp_path / "o"),
        "start_month": "2024-04", "end_month": "2024-04", "samples": 1, "workers": 1,
    }
    job = client.post("/api/generate-unified", json=payload).get_json()["job_id"]
    for _ in range(120):
        time.sleep(2)
        s = client.get(f"/api/generate-unified/{job}/status").get_json()
        if not s["running"]:
            break
    assert (s.get("manifest") or {}).get("status") == "succeeded"
    # per-building isolation in the served CSV
    csv = client.get(f"/api/generate-unified/{job}/csv/APR2024/0/cars.csv")
    assert csv.status_code == 200
    import io
    import pandas as pd
    cars = pd.read_csv(io.BytesIO(csv.get_data()), index_col=0)
    counts = cars.groupby("building_id").size().to_dict()
    assert counts[0] == 4 and counts[1] == 9
    # weather_data carries solar columns
    wx = client.get(f"/api/generate-unified/{job}/csv/APR2024/0/weather_data.csv")
    import pandas as pd2  # noqa
    wdf = pd.read_csv(io.BytesIO(wx.get_data()))
    assert "global_horizontal_w_m2" in wdf.columns
    # zip download
    z = client.get(f"/api/generate-unified/{job}/download")
    assert z.status_code == 200 and z.headers["Content-Type"] == "application/zip"
