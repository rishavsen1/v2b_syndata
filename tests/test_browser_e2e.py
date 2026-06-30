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
def test_ui_der_panel(page, server):
    """PV + battery: the major knob (type/sizing preset) is a selector in the
    MAIN grid; advanced dials live in the collapsible DER panel; neither appears
    in the generic Advanced panel."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    card = page.locator(".building-card").first

    # major knobs are selectors in the main grid
    pv_sel = card.locator(".descriptor-grid .mb-pv-type")
    bt_sel = card.locator(".descriptor-grid .mb-battery-type")
    assert pv_sel.count() == 1 and bt_sel.count() == 1
    assert pv_sel.locator("option[value='rooftop_medium']").count() == 1
    assert pv_sel.input_value() == "none"  # off by default
    assert bt_sel.locator("option[value='lfp_4h']").count() == 1

    # advanced dials are in the DER panel; the major knobs are NOT duplicated there
    card.locator(".mb-der > summary").click()
    der = card.locator(".card-der-knobs")
    assert der.locator(".knob[data-path='pv.dc_capacity_kw']").count() == 1
    assert der.locator(".knob[data-path='battery.capacity_kwh']").count() == 1
    assert der.locator(".knob[data-path='pv.pv_type']").count() == 0
    assert der.locator(".knob[data-path='battery.battery_type']").count() == 0

    # …and nothing PV/battery in the generic Advanced panel
    card.locator(".mb-adv > summary").click()
    adv = card.locator(".card-knob-buckets")
    assert adv.locator(".knob[data-path^='pv.']").count() == 0
    assert adv.locator(".knob[data-path^='battery.']").count() == 0

    # picking a PV preset is the on switch (selectable, value sticks)
    pv_sel.select_option("rooftop_large")
    assert pv_sel.input_value() == "rooftop_large"


@pytest.mark.browser
def test_ui_der_info_and_preset_sync(page, server):
    """The ⓘ buttons explain each preset, and picking a preset fills the
    advanced dials with its catalog values."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    card = page.locator(".building-card").first

    # info popover lists what each PV preset means
    card.locator(".der-info[data-der='pv']").click()
    pop = page.locator(".der-popover")
    assert pop.count() == 1
    txt = pop.inner_text()
    assert "rooftop_small" in txt and "30 kW" in txt
    # entries sorted by size ascending (small 30 < medium 100 < carport 200 < large 250 < xl 600)
    order = [txt.index(k) for k in
             ("rooftop_small", "rooftop_medium", "carport", "rooftop_large", "rooftop_xl")]
    assert order == sorted(order)

    # battery popover also sorted by capacity (2h=200 kWh before 4h=400 kWh)
    card.locator(".der-info[data-der='battery']").click()
    btxt = page.locator(".der-popover").inner_text()
    assert btxt.index("lfp_2h") < btxt.index("lfp_4h")
    assert btxt.index("nmc_2h") < btxt.index("nmc_4h")
    card.locator(".der-info[data-der='battery']").click()  # toggle popover closed
    assert page.locator(".der-popover").count() == 0

    # picking a PV preset fills the advanced dc_capacity_kw dial
    card.locator(".mb-pv-type").select_option("rooftop_large")
    card.locator(".mb-der > summary").click()
    dc = card.locator(".card-der-knobs .knob[data-path='pv.dc_capacity_kw'] input")
    page.wait_for_function(
        "document.querySelector(\".card-der-knobs .knob[data-path='pv.dc_capacity_kw'] input\").value === '250'",
        timeout=5000)
    assert dc.input_value() == "250"

    # picking a battery preset fills capacity + power
    card.locator(".mb-battery-type").select_option("lfp_4h")
    cap = card.locator(".card-der-knobs .knob[data-path='battery.capacity_kwh'] input")
    pwr = card.locator(".card-der-knobs .knob[data-path='battery.power_kw'] input")
    assert cap.input_value() == "400" and pwr.input_value() == "100"

    # back to 'none' clears the PV dial
    card.locator(".mb-pv-type").select_option("none")
    assert dc.input_value() == "0"


@pytest.mark.browser
def test_ui_input_previews(page, server):
    """Input previews: the collapsible Preview panel renders the three blocks
    for the card's current selections, and the per-field ⓘ opens a popover.

    We assert on the panel/popover STRUCTURE and the block text (headings,
    captions) which are written before the Plotly draw, so the test holds
    regardless of whether the Plotly bundle renders."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    card = page.locator(".building-card").first

    # ⓘ buttons sit next to Location / Building / Population in the grid
    assert card.locator(".descriptor-grid .preview-info[data-preview='location']").count() == 1
    assert card.locator(".descriptor-grid .preview-info[data-preview='building']").count() == 1
    assert card.locator(".descriptor-grid .preview-info[data-preview='population']").count() == 1

    # pick concrete descriptors so the previews have something to render. The
    # blank "scenario default" option has its *label* rewritten to the inherited
    # descriptor id, which can collide with select_option(value=…) matching — so
    # select by the unique full "<id> — <description>" label instead.
    card.locator(".mb-location").select_option(
        label="nashville_tn — Nashville, TN — TVA territory, subtropical, low-cost commercial")
    card.locator(".mb-building").select_option(
        label="medium_office_v1 — Medium office, ~5000 m², standard work hours")
    card.locator(".mb-population").select_option(
        label="consent_default — Mixed-flex CONSENT-empirical baseline — covers all 5 region archetypes")

    # Integration B: open the Preview panel → all three blocks appear, and each
    # carries its OWN per-input "affects:" tag row (replacing the old single
    # combined line). The affects rows + headings are written before the Plotly
    # draw, so they're present regardless of chart rendering.
    card.locator(".mb-preview > summary").click()
    host = card.locator(".card-preview")
    for block in ("location", "building", "population"):
        page.wait_for_selector(
            f".building-card .card-preview .pv-block[data-block='{block}'] .preview-affects",
            timeout=8000)
        assert host.locator(f".pv-block[data-block='{block}']").count() == 1
        # exactly one per-input affects row inside each block
        assert host.locator(f".pv-block[data-block='{block}'] .preview-affects").count() == 1
    # per-input affects tags: location drives prices + weather→load; population
    # drives arrival/dwell/SoC/region.
    loc_aff = host.locator(".pv-block[data-block='location'] .preview-affects").inner_text()
    assert "utility prices" in loc_aff and "weather" in loc_aff.lower()
    pop_aff = host.locator(".pv-block[data-block='population'] .preview-affects").inner_text()
    for t in ("arrival", "dwell", "region frequency"):
        assert t in pop_aff
    bld_aff = host.locator(".pv-block[data-block='building'] .preview-affects").inner_text()
    assert "building load shape" in bld_aff.lower()
    # the building block uses a REAL ComStock shape normalized to peak_kw (150)
    page.wait_for_function(
        "document.querySelector(\".building-card .card-preview .pv-block[data-block='building']\")"
        ".textContent.toLowerCase().includes('comstock')",
        timeout=8000)
    assert "150 kW" in host.locator(".pv-block[data-block='building']").inner_text()

    # Integration A: clicking the population ⓘ opens a floating popover with a
    # head naming the selection (set before the Plotly draw → robust either way).
    card.locator(".preview-info[data-preview='population']").click()
    page.wait_for_selector(".preview-popover", timeout=8000)
    assert page.locator(".preview-popover").count() == 1
    page.wait_for_function(
        "document.querySelector('.preview-popover .pp-head')"
        " && document.querySelector('.preview-popover .pp-head').textContent.includes('consent_default')",
        timeout=8000)
    # clicking the same ⓘ again toggles it closed
    card.locator(".preview-info[data-preview='population']").click()
    assert page.locator(".preview-popover").count() == 0


@pytest.mark.browser
def test_ui_input_previews_render_for_defaults(page, server):
    """A freshly-added card with NOTHING explicitly chosen still renders all
    three previews from the base scenario's inherited descriptors (S01 →
    nashville_tn / medium_office_v1 / consent_default), each flagged as a
    scenario default. Both the panel and the ⓘ popover resolve the default."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    card = page.locator(".building-card").first

    # nothing explicitly chosen: the three descriptor selects sit on the blank
    # "scenario default" option (value === "")
    assert card.locator(".mb-location").input_value() == ""
    assert card.locator(".mb-building").input_value() == ""
    assert card.locator(".mb-population").input_value() == ""

    # Integration B: opening the panel still renders all three blocks, resolved
    # to the S01 inherited defaults and tagged "scenario default".
    card.locator(".mb-preview > summary").click()
    page.wait_for_selector(".building-card .card-preview .preview-affects", timeout=8000)
    host = card.locator(".card-preview")
    page.wait_for_function(
        "document.querySelector(\".building-card .card-preview .pv-block[data-block='location'] h4\")"
        " && document.querySelector(\".building-card .card-preview .pv-block[data-block='location'] h4\")"
        ".textContent.includes('nashville_tn')",
        timeout=8000)
    loc_txt = host.locator(".pv-block[data-block='location'] h4").inner_text()
    assert "nashville_tn" in loc_txt and "scenario default" in loc_txt
    assert "medium_office_v1" in host.locator(".pv-block[data-block='building'] h4").inner_text()
    assert "consent_default" in host.locator(".pv-block[data-block='population'] h4").inner_text()

    # Integration A: the ⓘ on a blank Building select previews the inherited
    # default (medium_office_v1), tagged "(scenario default)".
    card.locator(".preview-info[data-preview='building']").click()
    page.wait_for_selector(".preview-popover", timeout=8000)
    # wait for the RESOLVED head (the transient "loading…" head also contains the
    # id, so key the wait on the "scenario default" tag the resolved head adds).
    page.wait_for_function(
        "document.querySelector('.preview-popover .pp-head')"
        " && document.querySelector('.preview-popover .pp-head').textContent.includes('scenario default')",
        timeout=8000)
    assert "medium_office_v1" in page.locator(".preview-popover .pp-head").inner_text()


@pytest.mark.browser
def test_ui_tour(page, server):
    """The '▶ Take a tour' button starts the driver.js guided tour and steps
    through it."""
    page.goto(server + "/", wait_until="networkidle")
    page.wait_for_selector(".building-card")
    assert page.locator("#start-tour").count() == 1

    page.click("#start-tour")
    page.wait_for_selector(".driver-popover", timeout=5000)
    assert "Welcome" in page.locator(".driver-popover-title").inner_text()

    # advancing reaches the per-card step
    page.click(".driver-popover-next-btn")
    assert "building" in page.locator(".driver-popover-title").inner_text().lower()

    # close it
    page.click(".driver-popover-close-btn")
    assert page.locator(".driver-popover").count() == 0


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
    cards.nth(0).locator(".mb-pv-type").select_option("rooftop_medium")  # PV on building 0
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
    # PV generation is plottable just like building load (daily profile + monthly)
    assert page.locator("#ua-csv option[value='pv_generation.csv']").count() == 1
    page.select_option("#ua-csv", "pv_generation.csv")
    assert page.locator("#ua-feature option[value='power_pv_kw']").count() == 1
    page.select_option("#ua-feature", "power_pv_kw")
    page.select_option("#ua-agg", "daily")
    assert page.locator("#ua-agg").is_visible()        # time-series → Aggregation toggle
    page.click("#ua-run")
    page.wait_for_function(
        "document.getElementById('ua-status').textContent.includes('building')",
        timeout=20000,
    )
