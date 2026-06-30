// Guided product tour for the configurator, using the vendored driver.js
// (window["driver"]["js"].driver). The "▶ Take a tour" button in the header
// starts it. Steps are anchored to stable selectors on the first building card
// and the run/output sections, so the tour stays valid as the UI evolves.

function startTour() {
    const ns = window.driver && window.driver.js;
    if (!ns || !ns.driver) {
        alert("Tour library failed to load (driver.js). Reload the page and try again.");
        return;
    }
    const card = ".building-card";  // there is always at least one card
    const steps = [
        { popover: {
            title: "Welcome 👋",
            description: "This tool generates <b>reproducible, optimus-format</b> synthetic datasets. "
                + "You configure one or more buildings, then Generate. Everything is reproducible from "
                + "<code>seed + config</code>. Let's walk through a single building card.",
        } },
        { element: card, popover: {
            title: "One building = one card",
            description: "Each card fully defines a single building — its scenario, EV fleet, building load, "
                + "and DER. Output is multi-building with a <code>building_id</code> column.",
            side: "top", align: "start",
        } },
        { element: card + " .mb-base", popover: {
            title: "Base scenario",
            description: "Start from a named scenario (e.g. <code>S01</code>). The Location / Building / "
                + "Population / Equipment selectors override its descriptors per building.",
            side: "bottom", align: "start",
        } },
        { element: card + " .preview-info[data-preview='population']", popover: {
            title: "Preview your choices 🔎",
            description: "Not sure what a Location / Building / Population produces? Click the <b>ⓘ</b> "
                + "next to each for a quick chart — utility prices & weather for Location, the load curve "
                + "(peak = the building's kW) for Building, and arrival / dwell / SoC / region mix for "
                + "Population. Or open the <b>▶ Preview — what these inputs produce</b> panel below to see "
                + "all three at once. It works even at the scenario defaults.",
            side: "bottom", align: "start",
        } },
        { element: card + " .mb-peak-kw", popover: {
            title: "Quick fields",
            description: "Common knobs surfaced as inputs — EV & charger count, peak kW, SoC bounds, seed. "
                + "Leave blank to use the scenario default (shown as the placeholder).",
            side: "bottom", align: "start",
        } },
        { element: card + " .mb-pv-type", popover: {
            title: "PV system",
            description: "Add rooftop/carport solar by preset (<code>none</code> = off). The ⓘ explains each "
                + "option; picking one sizes the array and fills the advanced PV dials. Its generation curve "
                + "uses the <b>same weather</b> as this building's load.",
            side: "bottom", align: "start",
        } },
        { element: card + " .mb-battery-type", popover: {
            title: "Battery storage",
            description: "Add stationary storage by preset (LFP / NMC, 2 h or 4 h). The ⓘ lists each one. "
                + "Specs only — downstream tools decide dispatch.",
            side: "bottom", align: "start",
        } },
        { element: card + " .mb-der", popover: {
            title: "PV & battery — advanced",
            description: "Fine-tune the selected system: explicit kW, tilt / azimuth, module type, system "
                + "derate; battery capacity / power / efficiency / SoC window.",
            side: "top", align: "start",
        } },
        { element: card + " .mb-perturb", popover: {
            title: "Perturbations",
            description: "Per-building weather noise (pre-generation, shifts the simulated weather) and "
                + "building-load noise (post-generation jitter on the produced CSVs).",
            side: "top", align: "start",
        } },
        { element: card + " .mb-adv", popover: {
            title: "Advanced knobs",
            description: "Every remaining <code>knobs.yaml</code> knob, scoped to this building.",
            side: "top", align: "start",
        } },
        { element: "#add-building", popover: {
            title: "More buildings",
            description: "Add independent building cards; <b>Duplicate</b> copies a card with a fresh seed. "
                + "<b>Load config</b> regenerates a previous run byte-for-byte.",
            side: "top", align: "start",
        } },
        { element: "#run-settings", popover: {
            title: "Run settings",
            description: "How much to generate: month range × samples/month × workers, the output layout "
                + "(shared vs per-building), and a global DR program.",
            side: "top", align: "start",
        } },
        { element: "#generate-btn", popover: {
            title: "Generate",
            description: "Runs generation — EnergyPlus building load + sampled charging sessions + DER — "
                + "and writes the optimus CSVs. Reproducible from seed + config.",
            side: "bottom", align: "start",
        } },
        { popover: {
            title: "Results & plots 📊",
            description: "After generating, the <b>Output</b> section appears with <b>Distributions & "
                + "profiles</b>: plot <code>building_load</code>, <code>weather_data</code>, and "
                + "<code>pv_generation</code> as a daily profile (mean ±1σ) or the full monthly series. "
                + "That's the tour — happy generating!",
        } },
    ];

    // Skip steps whose element isn't present (defensive — e.g. a future layout
    // change), so the tour never dead-ends on a missing anchor.
    const present = steps.filter(s => !s.element || document.querySelector(s.element));
    ns.driver({
        showProgress: true,
        smoothScroll: true,
        allowClose: true,
        nextBtnText: "Next →",
        prevBtnText: "← Back",
        doneBtnText: "Done",
        steps: present,
    }).drive();
}

document.getElementById("start-tour")?.addEventListener("click", startTour);
