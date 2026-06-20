"""Headless-browser end-to-end tests for the web UI (Playwright + chromium).

Drives the ACTUAL page: building cards, per-card Advanced knob panel, Duplicate,
and a full Generate cycle. Marked `browser` (chromium); the generate cycle is
also `real_energyplus` (the generate-unified subprocess runs EnergyPlus).

Run:  uv run pytest tests/test_browser_e2e.py -m browser
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "web"))
import app as webapp  # noqa: E402


@pytest.fixture(scope="module")
def server():
    srv = make_server("127.0.0.1", 0, webapp.app)
    port = srv.socket.getsockname()[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


@pytest.mark.browser
def test_ui_cards_knobs_and_duplicate(page, server):
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    assert page.locator(".building-card").count() == 1

    # per-card full knob panel is present (not just a JSON box)
    first = page.locator(".building-card").first
    first.locator(".mb-adv > summary").click()
    assert first.locator(".card-knob-buckets .knob").count() > 5
    assert page.locator("#knob-buckets").count() == 0      # no global Advanced panel
    assert page.locator("#u-noise").count() == 0           # noise removed from Run settings
    assert first.locator(".mb-noise").count() == 1         # noise is per-card

    # seed defaults to 0 for the first building
    assert first.locator(".mb-seed").input_value() == "0"

    # add a 2nd building → its seed increments
    page.click("#add-building")
    assert page.locator(".building-card").count() == 2
    assert page.locator(".building-card").nth(1).locator(".mb-seed").input_value() == "1"

    # set a distinctive value on card 0, duplicate → clone carries it but gets a
    # fresh (distinct) seed, not the source's 0
    page.locator(".building-card").first.locator(".mb-ev-count").fill("17")
    page.locator(".building-card").first.locator(".mb-dup").click()
    assert page.locator(".building-card").count() == 3
    last = page.locator(".building-card").last
    assert last.locator(".mb-ev-count").input_value() == "17"
    assert last.locator(".mb-seed").input_value() != "0"


@pytest.mark.browser
def test_ui_perturbations_panel_and_high_low_sync(page, server):
    """Both noise selectors are per-card inputs (weather before building-load);
    the detail panel holds the jitter/weather dials, and picking a building-load
    noise profile snaps the individual jitter dials to its values."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    card = page.locator(".building-card").first

    # both noise selectors live in the building's input grid (not the detail panel)
    assert card.locator(".descriptor-grid .mb-noise").count() == 1     # building load noise (output)
    assert card.locator(".descriptor-grid .mb-weather option[value='moderate']").count() == 1  # weather (input)
    assert page.locator("#u-weather-profile").count() == 0            # not in Run settings anymore
    assert card.locator(".mb-peak-scaling").count() == 0              # scaling checkbox removed
    # the dials live in the detail panel
    card.locator(".mb-perturb > summary").click()
    assert card.locator(".card-perturb-knobs .knob[data-path='noise.building_load_jitter_pct']").count() == 1
    assert card.locator(".card-perturb-knobs .knob[data-path='building_load.weather_temp_offset_c']").count() == 1
    # …and those perturbation knobs are NOT duplicated in the generic Advanced panel
    assert card.locator(".card-knob-buckets .knob[data-path='noise.building_load_jitter_pct']").count() == 0
    assert card.locator(".card-knob-buckets .knob[data-path='building_load.weather_temp_offset_c']").count() == 0

    # high→low: choosing 'adversarial' resolves the profile and snaps the dials
    jitter = ".card-perturb-knobs .knob[data-path='noise.building_load_jitter_pct'] input"
    flex = ".card-perturb-knobs .knob[data-path='noise.load_flex_jitter_pct'] input"
    card.locator(".mb-noise").select_option("adversarial")
    page.wait_for_function(
        f"document.querySelector(\"{jitter}\").value === '0.15'", timeout=10000)
    assert card.locator(flex).input_value() == "0.05"
    # back to clean → dials snap to 0
    card.locator(".mb-noise").select_option("clean")
    page.wait_for_function(
        f"document.querySelector(\"{jitter}\").value === '0'", timeout=10000)


@pytest.mark.browser
@pytest.mark.real_energyplus
def test_ui_full_generate(page, server, tmp_path):
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    page.click("#add-building")  # 2 buildings
    cards = page.locator(".building-card")
    for i in (0, 1):
        cards.nth(i).locator(".mb-ev-count").fill(str(3 + i * 4))   # 3 and 7
        cards.nth(i).locator(".mb-charger-count").fill(str(3 + i * 4))
        cards.nth(i).locator(".mb-noise").select_option("clean")    # now a grid input
    page.fill("#u-output-path", str(tmp_path / "run"))
    page.fill("#u-samples", "1")
    page.click("#generate-btn")
    page.wait_for_function(
        "document.getElementById('status').textContent.includes('Done')",
        timeout=240000,
    )
    assert "succeeded" in page.locator("#status").inner_text().lower()
    # output rendered: meta + the distribution analysis selects, and the analysis
    # actually fetched the per-building CSVs (ua-status reports building/sample
    # counts). The Plotly plot itself needs the cdn.plot.ly script, which a
    # network-isolated headless browser can't load — so don't assert on it.
    assert page.locator("#output").is_visible()
    assert page.locator("#output-meta").inner_text() != ""
    assert page.locator("#ua-csv option").count() > 0
    page.wait_for_function(
        "document.getElementById('ua-status').textContent.includes('building')",
        timeout=20000,
    )
    # weather_data is plottable and the daily/monthly aggregation toggle drives it.
    assert page.locator("#ua-csv option[value='weather_data.csv']").count() == 1
    page.select_option("#ua-csv", "weather_data.csv")
    assert page.locator("#ua-agg").is_visible()        # time-series → Aggregation shown
    assert not page.locator("#ua-shape").is_visible()  # …Shape hidden
    page.select_option("#ua-feature", "dry_bulb_temp_c")
    page.select_option("#ua-agg", "monthly")
    page.click("#ua-run")
    page.wait_for_function(
        "document.getElementById('ua-status').textContent.includes('building')",
        timeout=20000,
    )
    # building_load monthly full-series view
    page.select_option("#ua-csv", "building_load.csv")
    page.select_option("#ua-agg", "monthly")
    page.click("#ua-run")
    page.wait_for_function(
        "document.getElementById('ua-status').textContent.includes('building')",
        timeout=20000,
    )
