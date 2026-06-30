// Client logic for the multi-building configurator.
// Each .building-card owns its own state in `card._ctx = {overrides, resolved}`
// (per-card knob panel). Generate POSTs the assembled per-building config to
// /api/generate-unified.

let DESCRIPTORS = null;   // {location: [...], building: [...], ...}
let KNOBS = null;         // {bucket: {knob: spec}}
let SCENARIOS = null;     // [{id, description, descriptors, overrides}, ...]
let DER_CATALOG = null;   // {pv:{type:{dc_capacity_kw,label}}, battery:{type:{capacity_kwh,power_kw,round_trip_efficiency,label}}}

// Feature picker for distribution plots, per-CSV — OPTIMUS schema (building_id
// aware). Column names match export_optimus.py output.
const PLOT_FEATURES = {
    "building_load.csv": [
        { value: "power_kw",            label: "power_kw (total)" },
        { value: "power_kw_flexible",   label: "power_kw_flexible (HVAC)" },
        { value: "power_kw_inflexible", label: "power_kw_inflexible (lights + plug)" },
    ],
    "pv_generation.csv": [
        { value: "power_pv_kw",   label: "PV power (kW)" },
        { value: "energy_kwh_pv", label: "PV energy (kWh / 15-min)" },
    ],
    "sessions.csv": [
        { value: "arrival_hour",                  label: "arrival hour" },
        { value: "duration",                      label: "dwell (hours)" },
        { value: "required_soc_at_depart",        label: "required SoC at depart" },
        { value: "previous_day_external_use_soc", label: "previous-day external use SoC" },
    ],
    "cars.csv": [
        { value: "capacity_kwh",     label: "capacity (kWh)" },
        { value: "soc",              label: "soc (first arrival)" },
        { value: "frequency",        label: "frequency φ" },
        { value: "user_type",        label: "user_type (region)" },
        { value: "min_allowed_soc",  label: "min allowed SoC" },
        { value: "max_allowed_soc",  label: "max allowed SoC" },
    ],
    "grid_prices.csv": [
        { value: "price_per_kwh",    label: "price ($/kWh)" },
    ],
    "weather_data.csv": [
        { value: "dry_bulb_temp_c",          label: "dry-bulb temperature (°C)" },
        { value: "dew_point_temp_c",         label: "dew-point temperature (°C)" },
        { value: "relative_humidity_pct",    label: "relative humidity (%)" },
        { value: "global_horizontal_w_m2",   label: "solar GHI (W/m²)" },
        { value: "direct_normal_w_m2",       label: "solar DNI (W/m²)" },
        { value: "diffuse_horizontal_w_m2",  label: "solar DHI (W/m²)" },
        { value: "wind_speed_m_s",           label: "wind speed (m/s)" },
        { value: "wind_direction_deg",       label: "wind direction (°)" },
        { value: "atmospheric_pressure_pa",  label: "atmospheric pressure (Pa)" },
        { value: "horizontal_ir_w_m2",       label: "horizontal IR / sky longwave (W/m²)" },
        { value: "total_sky_cover",          label: "total sky cover (tenths)" },
        { value: "opaque_sky_cover",         label: "opaque sky cover (tenths)" },
    ],
};
// CSVs that carry per-building distributions worth plotting.
const PLOTTABLE_CSVS = ["building_load.csv", "pv_generation.csv", "weather_data.csv", "sessions.csv", "cars.csv", "grid_prices.csv"];
// Time-series CSVs (datetime axis) — support the daily-profile / monthly toggle.
const TIMESERIES_CSVS = new Set(["building_load.csv", "pv_generation.csv", "weather_data.csv", "grid_prices.csv"]);

// Knobs promoted into the per-card Scenario Descriptors / quick-fields. They are
// still regular knobs (override path + manifest source unchanged) — just
// surfaced as dedicated inputs and hidden from the Advanced panel so users
// don't see the same control twice.
const SHORTCUT_KNOBS = new Set([
    "building_load.tmyx_station",
    "building_load.peak_kw",
    "building_load.peak_kw_scaling",
]);

// PV/battery "major" knobs promoted to dedicated main-grid selectors (string
// values, so handled separately from the numeric QUICK_KEYS). Hidden from the
// DER panel so they aren't shown twice. `none` = off.
const DER_GRID_KNOBS = new Map([
    ["pv.pv_type", ".mb-pv-type"],
    ["battery.battery_type", ".mb-battery-type"],
]);

// Perturbation knobs are surfaced together in the per-card "Perturbations"
// panel (with the noise-profile dropdown), NOT in the generic Advanced panel —
// so every dial that adds randomness/realism lives in one place. The whole
// `noise` bucket plus the two fixed weather-offset knobs move there.
//   - noise.profile is represented by the .mb-noise dropdown (not a duplicate widget)
//   - the per-sample stochastic weather σ is a run-level control (#u-weather-sigma)
const PERTURB_WEATHER_KNOBS = new Set([
    "building_load.weather_temp_offset_c",
    "building_load.weather_solar_scale",
    "building_load.weather_dewpoint_offset_c",
    "building_load.weather_wind_scale",
]);
function isPerturbKnob(path) {
    return path.startsWith("noise.") || PERTURB_WEATHER_KNOBS.has(path);
}

// `resolved` is a per-card {path: {value, source}} map from /api/resolve.
function getEffectiveDefault(path, spec, resolved) {
    if (resolved && resolved[path] && resolved[path].value !== undefined) {
        return resolved[path].value;
    }
    return spec.default;
}

function getEffectiveSource(path, resolved) {
    if (resolved && resolved[path]) return resolved[path].source;
    return "default";
}

// Parse a fetch Response as JSON, but fail with a legible message when the
// server returns HTML (a 404/500 page) instead of JSON — otherwise resp.json()
// throws the cryptic "Unexpected token '<', "<!doctype "...". A 404 here almost
// always means the Flask dev server is stale (it does NOT auto-reload): the
// browser loaded new static files but the running process lacks the new route.
async function safeJson(resp) {
    const text = await resp.text();
    try {
        return JSON.parse(text);
    } catch (e) {
        const hint = resp.status === 404
            ? " — endpoint not found; the web server is likely running old code. Restart it: python tools/web/app.py"
            : " — restart the web server (python tools/web/app.py) if it is running old code";
        throw new Error(`Server returned a non-JSON ${resp.status} response${hint}`);
    }
}

async function init() {
    try {
        [DESCRIPTORS, KNOBS, SCENARIOS, DER_CATALOG] = await Promise.all([
            fetch("/api/descriptors").then(r => r.json()),
            fetch("/api/knobs").then(r => r.json()),
            fetch("/api/scenarios").then(r => r.json()),
            fetch("/api/der-catalog").then(r => r.json()).catch(() => null),
        ]);
    } catch (e) {
        document.getElementById("status").textContent = "Failed to load config from backend: " + e;
        return;
    }

    document.getElementById("add-building").addEventListener("click", addBuilding);
    document.getElementById("generate-btn").addEventListener("click", startUnified);
    const loadFile = document.getElementById("load-config-file");
    document.getElementById("load-config").addEventListener("click", () => loadFile.click());
    loadFile.addEventListener("change", async () => {
        if (!loadFile.files.length) return;
        try {
            applyConfig(JSON.parse(await loadFile.files[0].text()));
            document.getElementById("status").textContent =
                "Config loaded — click Generate to reproduce.";
        } catch (e) {
            document.getElementById("status").textContent = "Bad config file: " + e;
        }
        loadFile.value = "";
    });
    const estInputs = ["u-start-month", "u-end-month", "u-samples"];
    estInputs.forEach(id => document.getElementById(id).addEventListener("input", updateRunEstimate));
    addBuilding();                      // start with one building card
    updateRunEstimate();
}

function updateSourceLabel(widget, path, ctx) {
    const src = (path in ctx.overrides) ? "explicit (you)" : getEffectiveSource(path, ctx.resolved);
    const label = widget.querySelector(".source-label");
    if (!label) return;
    label.textContent = `from: ${src}`;
    const head = src.split(":")[0];
    const cls = (path in ctx.overrides) ? "source-explicit"
              : head === "descriptor" ? "source-descriptor"
              : head === "calibration" ? "source-calibration"
              : head === "explicit" ? "source-explicit"
              : "source-default";
    label.className = `source-label ${cls}`;
}

// ────────────────────────────────────────────────────────────────────
// Knob bucket rendering (per-card)
// ────────────────────────────────────────────────────────────────────

// Render the full knob panel INTO a per-card container, bound to that card's
// ctx ({overrides, resolved}). Each widget reads/writes ctx, so cards are fully
// independent.
function populateCardKnobs(card) {
    const container = card.querySelector(".card-knob-buckets");
    const ctx = card._ctx;
    container.innerHTML = "";
    for (const [bucket, knobs] of Object.entries(KNOBS)) {
        if (bucket === "noise") continue;                      // → Perturbations panel
        if (bucket === "pv" || bucket === "battery") continue; // → DER panel (main card)
        const section = document.createElement("section");
        section.className = "knob-bucket";
        const h3 = document.createElement("h3");
        h3.textContent = bucket;
        section.appendChild(h3);
        let n = 0;
        for (const [knobName, spec] of Object.entries(knobs)) {
            const path = `${bucket}.${knobName}`;
            if (SHORTCUT_KNOBS.has(path)) continue;  // promoted to per-card quick-fields
            if (isPerturbKnob(path)) continue;       // → Perturbations panel
            section.appendChild(createKnobWidget(path, spec, ctx));
            n++;
        }
        if (n > 0) container.appendChild(section);
    }
}

// Render the consolidated Perturbations panel: every noise.* jitter knob plus
// the fixed weather-offset knobs, bound to the card's ctx (the .mb-noise
// dropdown above them is the high-level profile control). Changing the profile
// re-resolves and snaps these widgets (see refreshCardKnobs) — high→low sync.
function populateCardPerturbations(card) {
    const container = card.querySelector(".card-perturb-knobs");
    const ctx = card._ctx;
    container.innerHTML = "";

    const wx = document.createElement("section");
    wx.className = "knob-bucket";
    const wxh = document.createElement("h3");
    wxh.textContent = "weather (fixed offset — per-sample σ is in Run settings)";
    wx.appendChild(wxh);
    for (const path of PERTURB_WEATHER_KNOBS) {
        const [bucket, knobName] = path.split(/\.(.+)/);
        const spec = (KNOBS[bucket] || {})[knobName];
        if (spec) wx.appendChild(createKnobWidget(path, spec, ctx));
    }
    container.appendChild(wx);

    const ns = document.createElement("section");
    ns.className = "knob-bucket";
    const nsh = document.createElement("h3");
    nsh.textContent = "noise jitter (set by the profile above; override any below)";
    ns.appendChild(nsh);
    for (const [knobName, spec] of Object.entries(KNOBS.noise || {})) {
        if (knobName === "profile") continue;  // the .mb-noise dropdown is the profile control
        ns.appendChild(createKnobWidget(`noise.${knobName}`, spec, ctx));
    }
    container.appendChild(ns);
}

// POST the card's base + descriptors to /api/resolve; refresh that card's knob
// widgets (non-overridden ones snap to the resolved value) + numeric placeholders.
// Render the per-card DER panel: the `pv` + `battery` buckets surfaced
// prominently in the main card (not the generic Advanced panel), bound to the
// card's ctx. Uses the same createKnobWidget factory, so refresh/sync/serialize
// all work via the shared `.knob` selectors + ctx.overrides.
function populateCardDer(card) {
    const container = card.querySelector(".card-der-knobs");
    if (!container) return;
    const ctx = card._ctx;
    container.innerHTML = "";
    for (const bucket of ["pv", "battery"]) {
        const knobs = KNOBS[bucket];
        if (!knobs) continue;
        const section = document.createElement("section");
        section.className = "knob-bucket";
        const h3 = document.createElement("h3");
        h3.textContent = bucket === "pv" ? "PV (rooftop / carport)" : "Battery (stationary)";
        section.appendChild(h3);
        let n = 0;
        for (const [knobName, spec] of Object.entries(knobs)) {
            const path = `${bucket}.${knobName}`;
            if (DER_GRID_KNOBS.has(path)) continue;  // promoted to the main-grid selectors
            section.appendChild(createKnobWidget(path, spec, ctx));
            n++;
        }
        if (n > 0) container.appendChild(section);
    }
}


// Set/clear a DER advanced-panel override and reflect it in its widget. Used to
// fill the advanced dials when a main-grid preset is chosen.
function _derWidget(card, path) {
    return card.querySelector(`.card-der-knobs .knob[data-path='${path}']`);
}
function derSetOverride(card, path, value) {
    const ctx = card._ctx;
    ctx.overrides[path] = value;
    const w = _derWidget(card, path);
    if (!w) return;
    const [bucket, knobName] = path.split(/\.(.+)/);
    const spec = (KNOBS[bucket] || {})[knobName];
    const input = w.querySelector(".knob-input-row > :first-child");
    if (input && spec) resetWidgetValue(input, spec, value);
    w.classList.add("modified");
    updateSourceLabel(w, path, ctx);
}
function derClearOverride(card, path) {
    const ctx = card._ctx;
    delete ctx.overrides[path];
    const w = _derWidget(card, path);
    if (!w) return;
    const [bucket, knobName] = path.split(/\.(.+)/);
    const spec = (KNOBS[bucket] || {})[knobName];
    const input = w.querySelector(".knob-input-row > :first-child");
    if (input && spec) resetWidgetValue(input, spec, getEffectiveDefault(path, spec, ctx.resolved));
    w.classList.remove("modified");
    updateSourceLabel(w, path, ctx);
}

// Picking a main-grid PV/battery preset fills the advanced dials with its
// catalog values (so they're visible + editable); 'none' clears them.
function applyPvPreset(card) {
    if (!DER_CATALOG || !DER_CATALOG.pv) return;
    const t = card.querySelector(".mb-pv-type").value;
    const info = DER_CATALOG.pv[t];
    if (t && t !== "none" && info) derSetOverride(card, "pv.dc_capacity_kw", info.dc_capacity_kw);
    else derClearOverride(card, "pv.dc_capacity_kw");
}
function applyBatteryPreset(card) {
    if (!DER_CATALOG || !DER_CATALOG.battery) return;
    const t = card.querySelector(".mb-battery-type").value;
    const info = DER_CATALOG.battery[t];
    const fields = ["capacity_kwh", "power_kw", "round_trip_efficiency"];
    if (t && t !== "none" && info) {
        fields.forEach(f => derSetOverride(card, `battery.${f}`, info[f]));
    } else {
        fields.forEach(f => derClearOverride(card, `battery.${f}`));
    }
}

// Toggle a small popover listing what each preset in a dropdown means.
function toggleDerPopover(btn, kind) {
    const existing = document.querySelector(".der-popover");
    const wasForThis = existing && existing._forBtn === btn;
    if (existing) existing.remove();
    if (wasForThis || !DER_CATALOG || !DER_CATALOG[kind]) return;
    const pop = document.createElement("div");
    pop.className = "der-popover";
    pop._forBtn = btn;
    pop.style.cssText = "position:absolute;z-index:1000;background:#fff;border:1px solid #c9d3dc;"
        + "border-radius:6px;padding:8px 11px;box-shadow:0 3px 10px rgba(0,0,0,.16);"
        + "font-size:.78rem;max-width:360px;line-height:1.5;color:#1f2933";
    // Sort by size ascending (PV by kW rating, battery by kWh capacity), then by
    // power as a tiebreak; 'none' (size 0) stays first.
    const sizeOf = (info) => kind === "pv"
        ? (info.dc_capacity_kw || 0)
        : (info.capacity_kwh || 0) * 1e6 + (info.power_kw || 0);
    const entries = Object.entries(DER_CATALOG[kind])
        .sort((a, b) => sizeOf(a[1]) - sizeOf(b[1]));
    pop.innerHTML = entries.map(([t, info]) => {
        let detail;
        if (t === "none") detail = "off";
        else if (kind === "pv") detail = `${info.dc_capacity_kw} kW DC — ${info.label}`;
        else detail = `${info.capacity_kwh} kWh / ${info.power_kw} kW · `
            + `${Math.round(info.round_trip_efficiency * 100)}% round-trip — ${info.label}`;
        return `<div><strong>${t}</strong> — ${detail}</div>`;
    }).join("");
    document.body.appendChild(pop);
    const r = btn.getBoundingClientRect();
    pop.style.left = `${window.scrollX + r.left}px`;
    pop.style.top = `${window.scrollY + r.bottom + 4}px`;
    setTimeout(() => {
        const close = (e) => {
            if (!pop.contains(e.target) && e.target !== btn) {
                pop.remove();
                document.removeEventListener("click", close);
            }
        };
        document.addEventListener("click", close);
    }, 0);
}


async function refreshCardKnobs(card) {
    const ctx = card._ctx;
    const descriptors = {};
    ["location", "building", "population", "equipment"].forEach(k => {
        const v = card.querySelector(".mb-" + k).value;
        if (v) descriptors[k] = v;
    });
    // Include the noise profile so the resolved noise.* values reflect the
    // chosen profile → the Perturbations widgets snap to it (high→low sync).
    const noiseVal = card.querySelector(".mb-noise").value;
    if (noiseVal) descriptors.noise = noiseVal;
    try {
        const r = await fetch("/api/resolve", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ base_scenario: card.querySelector(".mb-base").value, descriptors }),
        });
        const data = await safeJson(r);
        if (!data.error) ctx.resolved = data;
    } catch (e) { /* keep prior resolved */ }
    // refresh every widget (both the Advanced and Perturbations panels) that the
    // user hasn't overridden
    card.querySelectorAll(".card-knob-buckets .knob, .card-perturb-knobs .knob, .card-der-knobs .knob").forEach(widget => {
        const path = widget.dataset.path;
        const [bucket, knobName] = path.split(/\.(.+)/);
        const spec = (KNOBS[bucket] || {})[knobName];
        if (!spec) return;
        if (!(path in ctx.overrides)) {
            const input = widget.querySelector(".knob-input-row > :first-child");
            if (input) resetWidgetValue(input, spec, getEffectiveDefault(path, spec, ctx.resolved));
            widget.classList.remove("modified");
        }
        updateSourceLabel(widget, path, ctx);
    });
}

// Set the card's knob widgets to reflect ctx.overrides (used by config load).
function syncCardKnobWidgets(card) {
    const ctx = card._ctx;
    card.querySelectorAll(".card-knob-buckets .knob, .card-perturb-knobs .knob, .card-der-knobs .knob").forEach(widget => {
        const path = widget.dataset.path;
        const [bucket, knobName] = path.split(/\.(.+)/);
        const spec = (KNOBS[bucket] || {})[knobName];
        if (!spec) return;
        const overridden = path in ctx.overrides;
        const val = overridden ? ctx.overrides[path] : getEffectiveDefault(path, spec, ctx.resolved);
        const input = widget.querySelector(".knob-input-row > :first-child");
        if (input) resetWidgetValue(input, spec, val);
        widget.classList.toggle("modified", overridden);
        updateSourceLabel(widget, path, ctx);
    });
}

function createKnobWidget(path, spec, ctx) {
    const wrapper = document.createElement("div");
    wrapper.className = "knob";
    wrapper.dataset.path = path;

    const label = document.createElement("div");
    label.className = "knob-label";

    const pathEl = document.createElement("div");
    pathEl.className = "knob-path";
    pathEl.innerHTML = `<code>${path}</code>`;
    label.appendChild(pathEl);

    if (spec.description) {
        const desc = document.createElement("div");
        desc.className = "knob-desc";
        desc.textContent = spec.description;
        label.appendChild(desc);
    }

    const meta = document.createElement("div");
    meta.className = "knob-meta";
    let metaText = `type=${spec.type} · default=${formatValue(spec.default)}`;
    if (spec.range) metaText += ` · range=${JSON.stringify(spec.range)}`;
    if (spec.choices) metaText += ` · choices=${JSON.stringify(spec.choices)}`;
    meta.textContent = metaText;
    label.appendChild(meta);

    const inputRow = document.createElement("div");
    inputRow.className = "knob-input-row";
    const input = createInputForType(path, spec, wrapper, ctx);
    inputRow.appendChild(input);

    const resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.textContent = "reset";
    resetBtn.style.padding = "0.2rem 0.5rem";
    resetBtn.style.fontSize = "0.7rem";
    resetBtn.addEventListener("click", () => {
        delete ctx.overrides[path];
        wrapper.classList.remove("modified");
        resetWidgetValue(input, spec, getEffectiveDefault(path, spec, ctx.resolved));
        updateSourceLabel(wrapper, path, ctx);
    });
    inputRow.appendChild(resetBtn);

    label.appendChild(inputRow);

    const sourceLabel = document.createElement("div");
    sourceLabel.className = "source-label source-default";
    sourceLabel.textContent = "from: default";
    label.appendChild(sourceLabel);

    wrapper.appendChild(label);
    return wrapper;
}

function createInputForType(path, spec, wrapper, ctx) {
    const effDefault = getEffectiveDefault(path, spec, ctx.resolved);
    const onChange = (v, valid = true) => {
        if (!valid) return;
        const baseline = getEffectiveDefault(path, spec, ctx.resolved);
        if (deepEqual(v, baseline)) {
            delete ctx.overrides[path];
            wrapper.classList.remove("modified");
        } else {
            ctx.overrides[path] = v;
            wrapper.classList.add("modified");
        }
        updateSourceLabel(wrapper, path, ctx);
    };

    switch (spec.type) {
        case "int":
        case "float": {
            const inp = document.createElement("input");
            inp.type = "number";
            if (spec.range) {
                inp.min = spec.range[0];
                inp.max = spec.range[1];
            }
            inp.step = spec.type === "int" ? "1" : "any";
            inp.value = effDefault;
            inp.addEventListener("change", e => {
                const raw = e.target.value;
                let v = spec.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
                if (Number.isNaN(v)) {
                    showInlineError(inp, "not a number");
                    return;
                }
                if (spec.range && (v < spec.range[0] || v > spec.range[1])) {
                    showInlineError(inp, `must be in [${spec.range[0]}, ${spec.range[1]}]`);
                    return;
                }
                onChange(v);
            });
            return inp;
        }

        case "bool": {
            const wrap = document.createElement("span");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = !!effDefault;
            cb.addEventListener("change", e => onChange(e.target.checked));
            wrap.appendChild(cb);
            wrap.appendChild(document.createTextNode(" enabled"));
            return wrap;
        }

        case "categorical": {
            const sel = document.createElement("select");
            (spec.choices || []).forEach(choice => {
                const opt = document.createElement("option");
                opt.value = choice;
                opt.textContent = choice;
                if (choice === effDefault) opt.selected = true;
                sel.appendChild(opt);
            });
            sel.addEventListener("change", e => onChange(e.target.value));
            return sel;
        }

        case "simplex":
            return createSimplexWidget(path, spec, wrapper, onChange, ctx);

        case "vec2":
            return createVec2Widget(path, spec, onChange, ctx);

        case "list[vec2]":
        case "list[region]":
        case "path":
        case "timestamp":
        default: {
            const ta = document.createElement("textarea");
            ta.rows = 2;
            ta.value = JSON.stringify(effDefault);
            ta.addEventListener("change", e => {
                try {
                    const v = JSON.parse(e.target.value);
                    onChange(v);
                } catch (err) {
                    showInlineError(ta, "invalid JSON");
                }
            });
            return ta;
        }
    }
}

function createSimplexWidget(path, spec, wrapper, onChange, ctx) {
    const container = document.createElement("div");
    container.className = "simplex-widget";

    const effDefault = getEffectiveDefault(path, spec, ctx.resolved);
    const components = spec.components || effDefault.map((_, i) => `c${i}`);
    const inputs = components.map((name, i) => {
        const wrap = document.createElement("div");
        wrap.className = "component";
        const lbl = document.createElement("span");
        lbl.className = "component-name";
        lbl.textContent = name;
        const inp = document.createElement("input");
        inp.type = "number";
        inp.min = 0;
        inp.max = 1;
        inp.step = 0.01;
        inp.value = effDefault[i];
        wrap.appendChild(lbl);
        wrap.appendChild(inp);
        container.appendChild(wrap);
        return inp;
    });

    const sumEl = document.createElement("div");
    sumEl.className = "sum-indicator";
    container.appendChild(sumEl);

    const update = () => {
        const vals = inputs.map(i => parseFloat(i.value) || 0);
        const sum = vals.reduce((a, b) => a + b, 0);
        sumEl.textContent = `Σ = ${sum.toFixed(4)}`;
        const valid = Math.abs(sum - 1.0) < 0.001;
        sumEl.className = "sum-indicator " + (valid ? "valid" : "invalid");
        onChange(vals, valid);
    };
    inputs.forEach(i => i.addEventListener("input", update));
    update();
    return container;
}

function createVec2Widget(path, spec, onChange, ctx) {
    const container = document.createElement("div");
    container.className = "vec2-widget";
    const [a, b] = getEffectiveDefault(path, spec, ctx.resolved);
    const ia = document.createElement("input");
    const ib = document.createElement("input");
    [ia, ib].forEach(i => {
        i.type = "number";
        i.step = "any";
    });
    ia.value = a;
    ib.value = b;
    if (spec.range) {
        const rA = Array.isArray(spec.range[0]) ? spec.range[0] : spec.range;
        const rB = Array.isArray(spec.range[1]) ? spec.range[1] : spec.range;
        ia.min = rA[0]; ia.max = rA[1];
        ib.min = rB[0]; ib.max = rB[1];
    }
    const update = () => onChange([parseFloat(ia.value), parseFloat(ib.value)]);
    ia.addEventListener("change", update);
    ib.addEventListener("change", update);
    container.appendChild(ia);
    container.appendChild(ib);
    return container;
}

function resetWidgetValue(input, spec, value) {
    // `value` is the target restore value (may be the descriptor-resolved
    // value, not spec.default). Falls back to spec.default if undefined.
    if (value === undefined) value = spec.default;
    if (spec.type === "bool" && input.tagName === "SPAN") {
        input.querySelector("input").checked = !!value;
    } else if (spec.type === "simplex") {
        const inputs = input.querySelectorAll("input");
        (value || []).forEach((v, i) => { if (inputs[i]) inputs[i].value = v; });
        if (inputs[0]) inputs[0].dispatchEvent(new Event("input"));
    } else if (spec.type === "vec2") {
        const inputs = input.querySelectorAll("input");
        if (inputs[0]) inputs[0].value = value[0];
        if (inputs[1]) inputs[1].value = value[1];
    } else if (spec.type === "categorical") {
        input.value = value;
    } else if (input.tagName === "TEXTAREA") {
        input.value = JSON.stringify(value);
    } else if (input.tagName === "INPUT") {
        input.value = value;
    }
}

// ────────────────────────────────────────────────────────────────────
// Run progress
// ────────────────────────────────────────────────────────────────────

function renderBatchStatus(data) {
    const txt = document.getElementById("batch-status-text");
    const m = data.manifest;
    if (!m) {
        txt.textContent = `elapsed ${data.elapsed_sec}s — manifest not yet written`;
        return;
    }
    const nDone = (m.n_succeeded || 0) + (m.n_failed || 0);
    txt.innerHTML = `batch_id=${m.batch_id} · status=<strong>${m.status}</strong> · ${nDone}/${m.n_total || 0} done (${m.n_succeeded || 0} ok, ${m.n_failed || 0} failed) · elapsed ${data.elapsed_sec}s · profile=${m.noise_profile}`;

    // Only render rows for failures; succeeded samples just bump the counter.
    const tbl = document.getElementById("batch-month-table");
    tbl.innerHTML = "";
    const failures = (m.samples || []).filter(s => s.status === "failed");
    if (failures.length === 0) return;
    const header = document.createElement("div");
    header.className = "row";
    header.style.fontWeight = "600";
    header.innerHTML = `<span colspan="5">Failures (${failures.length}):</span>`;
    tbl.appendChild(header);
    failures.forEach(s => {
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = `
            <span>${s.month}</span>
            <span>#${s.sample_idx}</span>
            <span>seed=${s.seed}</span>
            <span class="batch-status-failed">${s.status}</span>
            <span>${s.duration_sec || ""}s ${s.error ? "— " + escapeHtml(s.error.slice(0,120)) : ""}</span>
        `;
        tbl.appendChild(row);
    });
}

async function fetchAndParseCsv(url) {
    const txt = await fetch(url).then(r => r.text());
    const lines = txt.trim().split("\n");
    if (lines.length < 2) return [];
    const headers = lines[0].split(",");
    return lines.slice(1).map(line => {
        const vals = line.split(",");
        const row = {};
        headers.forEach((h, i) => {
            const raw = vals[i];
            const num = parseFloat(raw);
            row[h] = (!isNaN(num) && raw !== "" && /^-?[\d.]+(e[+-]?\d+)?$/i.test(raw)) ? num : raw;
        });
        return row;
    });
}

// ────────────────────────────────────────────────────────────────────
// Utilities
// ────────────────────────────────────────────────────────────────────

function formatValue(v) {
    if (v === null || v === undefined) return "null";
    if (Array.isArray(v)) return `[${v.map(formatValue).join(", ")}]`;
    if (typeof v === "object") return JSON.stringify(v);
    if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(4);
    return String(v);
}

function deepEqual(a, b) {
    if (a === b) return true;
    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) if (!deepEqual(a[i], b[i])) return false;
        return true;
    }
    if (typeof a === "object" && typeof b === "object" && a && b) {
        const ka = Object.keys(a), kb = Object.keys(b);
        if (ka.length !== kb.length) return false;
        for (const k of ka) if (!deepEqual(a[k], b[k])) return false;
        return true;
    }
    if (typeof a === "number" && typeof b === "number")
        return Math.abs(a - b) < 1e-9;
    return false;
}

function showInlineError(input, msg) {
    let err = input.parentElement && input.parentElement.querySelector(".inline-error");
    if (!err) {
        err = document.createElement("span");
        err.className = "inline-error";
        (input.parentElement || document.body).appendChild(err);
    }
    err.textContent = msg;
    setTimeout(() => err.remove(), 4000);
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// ────────────────────────────────────────────────────────────────────────────
// Multi-building generation (optimus export). Self-contained: reuses the
// already-loaded DESCRIPTORS + SCENARIOS, posts to /api/generate-unified.
// ────────────────────────────────────────────────────────────────────────────

let MB_CARD_SEQ = 0;

function mbFillSelect(sel, items, blankLabel) {
    sel.innerHTML = "";
    if (blankLabel !== null) {
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = blankLabel;
        sel.appendChild(blank);
    }
    (items || []).forEach(it => {
        const opt = document.createElement("option");
        opt.value = it.id;
        opt.textContent = it.description ? `${it.id} — ${it.description}` : it.id;
        sel.appendChild(opt);
    });
}

function createBuildingCard() {
    const idx = MB_CARD_SEQ++;
    const card = document.createElement("div");
    card.className = "building-card";
    card.dataset.cardId = idx;
    card._ctx = { overrides: {}, resolved: {} };  // per-building knob state
    card.innerHTML = `
        <div class="building-card-head">
            <span class="building-card-title"></span>
            <span style="display:flex;gap:0.4rem">
                <button type="button" class="mb-dup secondary">⧉ duplicate</button>
                <button type="button" class="mb-remove secondary">− remove</button>
            </span>
        </div>
        <div class="descriptor-grid">
            <label><span class="field-name">Base scenario</span><select class="mb-base"></select></label>
            <label><span class="field-name">Location <button type="button" class="preview-info" data-preview="location" aria-label="preview this location" title="preview what this location produces">&#9432;</button></span><select class="mb-location"></select></label>
            <label><span class="field-name">Building <button type="button" class="preview-info" data-preview="building" aria-label="preview this building" title="preview what this building produces">&#9432;</button></span><select class="mb-building"></select></label>
            <label><span class="field-name">Population <button type="button" class="preview-info" data-preview="population" aria-label="preview this population" title="preview what this population produces">&#9432;</button></span><select class="mb-population"></select></label>
            <label><span class="field-name">Equipment</span><select class="mb-equipment"></select></label>
            <label><span class="field-name">Seed</span><input type="number" class="mb-seed" step="1"></label>
            <label><span class="field-name">EV count</span><input type="number" class="mb-ev-count" min="1" placeholder="scenario default"></label>
            <label><span class="field-name">Charger count</span><input type="number" class="mb-charger-count" min="1" placeholder="scenario default"></label>
            <label><span class="field-name">Peak kW</span><input type="number" class="mb-peak-kw" min="50" step="10" placeholder="enter to scale peak"></label>
            <label><span class="field-name">Min SoC %</span><input type="number" class="mb-min-soc" min="0" max="100" step="1" placeholder="(10)"></label>
            <label><span class="field-name">Max SoC %</span><input type="number" class="mb-max-soc" min="0" max="100" step="1" placeholder="(90)"></label>
            <label><span class="field-name">Policy</span><input type="text" class="mb-policy" placeholder="(default policy)"></label>
            <label><span class="field-name">PV system <button type="button" class="der-info" data-der="pv" aria-label="PV preset meanings" style="background:none;border:none;cursor:pointer;color:#0e6e87;font-size:.85rem;padding:0 .15rem">&#9432;</button></span><select class="mb-pv-type"></select></label>
            <label><span class="field-name">Battery <button type="button" class="der-info" data-der="battery" aria-label="Battery preset meanings" style="background:none;border:none;cursor:pointer;color:#0e6e87;font-size:.85rem;padding:0 .15rem">&#9432;</button></span><select class="mb-battery-type"></select></label>
            <label><span class="field-name">Weather noise (pre-generation)</span><select class="mb-weather"></select></label>
            <label><span class="field-name">Building load noise (post-generation)</span><select class="mb-noise"></select></label>
        </div>
        <div class="mb-soc-warn inline-error" style="display:none"></div>
        <details class="mb-preview panel-row">
            <summary><span class="chev">▶</span>Preview — what these inputs produce (this building)</summary>
            <p class="hint" style="margin:0.3rem 0">Computed from the selected Location / Building / Population config values, drawn with Plotly. Re-renders when any of those three change. The building daily-load shape is <strong>illustrative</strong> (production uses a precomputed EnergyPlus profile).</p>
            <div class="card-preview"></div>
        </details>
        <details class="mb-der">
            <summary>PV &amp; battery — advanced (this building)</summary>
            <p class="hint" style="margin:0.3rem 0">The <strong>PV system</strong> and <strong>Battery</strong> selectors in the inputs above are the on/off + sizing controls (a preset other than <code>none</code> enables it). These dials fine-tune the selected system: explicit <code>pv.dc_capacity_kw</code>, tilt/azimuth, module, derate; battery <code>capacity_kwh</code>/<code>power_kw</code>, efficiency, SoC window. The PV curve uses the <em>same</em> (perturbed) weather as this building's load.</p>
            <div class="card-der-knobs"></div>
        </details>
        <details class="mb-perturb">
            <summary>Perturbation details (this building)</summary>
            <p class="hint" style="margin:0.3rem 0">Fine-grained dials behind the two noise selectors above. <strong>Building load noise</strong> jitters the <em>produced</em> CSVs (load/sessions/prices) post-generation — the dials snap to the selected profile; change any to override. <strong>Weather noise</strong>'s fixed offset shifts this building's simulated &amp; exported weather (the selector above instead draws a per-sample offset).</p>
            <div class="card-perturb-knobs"></div>
        </details>
        <details class="mb-adv">
            <summary>Advanced — knobs (this building)</summary>
            <p class="hint" style="margin:0.3rem 0">Every other <code>configs/knobs.yaml</code> knob, scoped to this building (noise + weather perturbations are in the inputs + Perturbation details above). Defaults show the resolved value for this card's base scenario + descriptors; change any to override (the quick-fields above take precedence for EV/charger/peak/SoC).</p>
            <div class="card-knob-buckets"></div>
        </details>
    `;
    mbFillSelect(card.querySelector(".mb-base"), SCENARIOS, null);
    mbFillSelect(card.querySelector(".mb-location"), DESCRIPTORS.location, "");
    mbFillSelect(card.querySelector(".mb-building"), DESCRIPTORS.building, "");
    mbFillSelect(card.querySelector(".mb-population"), DESCRIPTORS.population, "");
    mbFillSelect(card.querySelector(".mb-equipment"), DESCRIPTORS.equipment, "");
    mbFillSelect(card.querySelector(".mb-noise"), DESCRIPTORS.noise, "");
    // PV + battery: major per-building knobs surfaced in the main grid. Options
    // are the knob choices (none = off); explicit kW / advanced dials live in the
    // DER panel below.
    mbFillSelect(card.querySelector(".mb-pv-type"),
                 ((KNOBS.pv || {}).pv_type || {}).choices?.map(c => ({ id: c })) || [], null);
    mbFillSelect(card.querySelector(".mb-battery-type"),
                 ((KNOBS.battery || {}).battery_type || {}).choices?.map(c => ({ id: c })) || [], null);
    // Weather profiles: options + their per-channel breakdown come from
    // weather_profiles.yaml (descriptions), so the UI never drifts from config.
    mbFillSelect(card.querySelector(".mb-weather"), DESCRIPTORS.weather, null);
    // Default seed = the card's monotonic index → 1st building is 0, each new
    // one increments (0, 1, 2, …). Distinct seeds give independent realizations;
    // the user can still edit it, and loading a config restores the saved seed.
    card.querySelector(".mb-seed").value = idx;
    populateCardKnobs(card);          // generic Advanced panel
    populateCardPerturbations(card);  // consolidated noise + weather panel
    populateCardDer(card);            // PV + battery advanced dials

    // Main-grid PV/battery selectors: picking a preset fills the advanced dials;
    // the ⓘ buttons explain what each option means.
    card.querySelector(".mb-pv-type").addEventListener("change", () => applyPvPreset(card));
    card.querySelector(".mb-battery-type").addEventListener("change", () => applyBatteryPreset(card));
    card.querySelectorAll(".der-info").forEach(btn =>
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleDerPopover(btn, btn.dataset.der);
        }));

    // INPUT PREVIEWS — integration A: ⓘ next to Location/Building/Population.
    card.querySelectorAll(".preview-info").forEach(btn =>
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            togglePreviewPopover(btn, btn.dataset.preview, card);
        }));
    // INPUT PREVIEWS — integration B: the collapsible panel renders on open and
    // re-renders whenever a descriptor select changes (if the panel is open).
    const previewDetails = card.querySelector(".mb-preview");
    if (previewDetails) {
        previewDetails.addEventListener("toggle", () => {
            if (previewDetails.open) renderCardPreview(card);
        });
        // Re-render on descriptor changes AND on base-scenario change (the base
        // determines which inherited defaults fill any blank descriptor).
        [".mb-location", ".mb-building", ".mb-population", ".mb-base"].forEach(s =>
            card.querySelector(s).addEventListener("change", () => renderCardPreview(card)));
    }

    // Footgun guard: Max SoC ≤ the departure floor (min_depart_soc) drops ALL
    // sessions for this building. Warn live. Floor = this card's min_depart_soc
    // (override → resolved → 0.80 default).
    const checkSoc = () => {
        const w = card.querySelector(".mb-soc-warn");
        const mx = parseFloat(card.querySelector(".mb-max-soc").value);
        const ov = card._ctx.overrides, res = card._ctx.resolved;
        const floor = ("user_behavior.min_depart_soc" in ov)
            ? Number(ov["user_behavior.min_depart_soc"])
            : ((res["user_behavior.min_depart_soc"] || {}).value ?? 0.40);
        const floorPct = floor * 100;
        if (!isNaN(mx) && mx <= floorPct) {
            w.style.display = "";
            w.textContent = `⚠ Max SoC ${mx}% ≤ departure floor min_depart_soc (${floorPct}%) `
                + `→ all sessions dropped. Raise Max SoC or lower min_depart_soc in this building's Advanced.`;
        } else {
            w.style.display = "none";
        }
    };
    card.querySelector(".mb-max-soc").addEventListener("input", checkSoc);

    const baseSel = card.querySelector(".mb-base");
    const updateInheritLabels = () => {
        const sc = (SCENARIOS || []).find(s => s.id === baseSel.value);
        const d = (sc && sc.descriptors) || {};
        [["location", ".mb-location"], ["building", ".mb-building"],
         ["population", ".mb-population"], ["equipment", ".mb-equipment"],
         ["noise", ".mb-noise"]].forEach(([key, cls]) => {
            const opt = card.querySelector(cls).options[0];
            opt.textContent = d[key] ? d[key] : "scenario default";
        });
    };
    const setPlaceholders = () => {
        const set = (cls, path) => {
            const v = (card._ctx.resolved[path] || {}).value;
            if (v != null) card.querySelector(cls).placeholder = String(v);
        };
        set(".mb-ev-count", "ev_fleet.ev_count");
        set(".mb-charger-count", "charging_infra.charger_count");
        set(".mb-peak-kw", "building_load.peak_kw");
        set(".mb-min-soc", "ev_fleet.min_allowed_soc");
        set(".mb-max-soc", "ev_fleet.max_allowed_soc");
    };
    // One /api/resolve per refresh → card._ctx.resolved → labels + placeholders + knob widgets.
    const refreshCard = async () => {
        updateInheritLabels();
        await refreshCardKnobs(card);
        setPlaceholders();
        checkSoc();
    };
    card._refresh = refreshCard;
    // Changing the noise profile (.mb-noise) re-resolves too → the Perturbations
    // jitter widgets snap to the selected profile's values (high→low sync).
    [baseSel, ".mb-location", ".mb-building", ".mb-population", ".mb-equipment", ".mb-noise"]
        .forEach(s => (typeof s === "string" ? card.querySelector(s) : s)
                 .addEventListener("change", refreshCard));
    refreshCard();
    card.querySelector(".mb-dup").addEventListener("click", () => {
        const clone = createBuildingCard();
        document.getElementById("building-cards").appendChild(clone);
        const spec = cardToSpec(card);
        spec.seed = parseInt(clone.dataset.cardId, 10);  // distinct seed, not the source's
        setCardValues(clone, spec);
        renumberBuildingCards();
    });
    card.querySelector(".mb-remove").addEventListener("click", () => {
        card.remove();
        renumberBuildingCards();
    });
    return card;
}

function renumberBuildingCards() {
    document.querySelectorAll("#building-cards .building-card").forEach((card, i) => {
        card.querySelector(".building-card-title").textContent = `Building ${i} (building_id=${i})`;
    });
}

function downloadJson(obj, filename) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    a.click(); URL.revokeObjectURL(a.href);
}

// Repopulate one card from a building spec (inverse of buildUnifiedPayload).
// Knobs that have a dedicated quick-field input on the card (so they don't
// also appear in the per-card knob panel / aren't double-counted).
const QUICK_KEYS = {
    "ev_fleet.ev_count": ".mb-ev-count",
    "charging_infra.charger_count": ".mb-charger-count",
    "building_load.peak_kw": ".mb-peak-kw",
    "ev_fleet.min_allowed_soc": ".mb-min-soc",
    "ev_fleet.max_allowed_soc": ".mb-max-soc",
};

// One building card → a BuildingSpec (overrides = per-card knob panel + quick
// fields; quick fields win). Used by the payload and the Duplicate button.
function cardToSpec(card) {
    const descriptors = {};
    ["location", "building", "population", "equipment"].forEach(k => {
        const v = card.querySelector(".mb-" + k).value;
        if (v) descriptors[k] = v;
    });
    const overrides = { ...card._ctx.overrides };
    for (const [key, sel] of Object.entries(QUICK_KEYS)) {
        const raw = card.querySelector(sel).value;
        if (raw === "") continue;
        const v = parseFloat(raw);
        if (!isNaN(v)) overrides[key] = v;
    }
    // PV / battery major selectors (string-valued). Record only a non-'none'
    // pick as an override; 'none' is the default (off) and needs no override.
    for (const [key, sel] of DER_GRID_KNOBS) {
        const v = card.querySelector(sel).value;
        if (v && v !== "none") overrides[key] = v;
    }
    // Peak-kW scaling is off unless a Peak kW value is entered — then we scale
    // the load so its max hits that value (no separate toggle).
    overrides["building_load.peak_kw_scaling"] = card.querySelector(".mb-peak-kw").value !== "";
    return {
        base_scenario: card.querySelector(".mb-base").value,
        descriptors,
        overrides,
        seed: (v => Number.isNaN(v) ? 0 : v)(parseInt(card.querySelector(".mb-seed").value, 10)),
        noise_profile: card.querySelector(".mb-noise").value || null,
        weather_profile: card.querySelector(".mb-weather").value || null,
        policy: card.querySelector(".mb-policy").value || null,
    };
}

function setCardValues(card, b) {
    const set = (sel, v) => { if (v != null && v !== "") card.querySelector(sel).value = v; };
    set(".mb-base", b.base_scenario);
    const d = b.descriptors || {};
    set(".mb-location", d.location); set(".mb-building", d.building);
    set(".mb-population", d.population); set(".mb-equipment", d.equipment);
    set(".mb-noise", b.noise_profile); set(".mb-seed", b.seed);
    set(".mb-weather", b.weather_profile); set(".mb-policy", b.policy);
    const o = { ...(b.overrides || {}) };
    // quick-field keys → their inputs; remove from the knob-panel overrides
    for (const [key, sel] of Object.entries(QUICK_KEYS)) {
        if (key in o) { card.querySelector(sel).value = o[key]; delete o[key]; }
    }
    // PV/battery major selectors (string quick-fields)
    for (const [key, sel] of DER_GRID_KNOBS) {
        if (key in o) { card.querySelector(sel).value = o[key]; delete o[key]; }
    }
    // peak_kw_scaling is derived from whether Peak kW is set (no widget); drop it.
    delete o["building_load.peak_kw_scaling"];
    card._ctx.overrides = o;            // remaining → per-card knob panel
    syncCardKnobWidgets(card);
    if (card._refresh) card._refresh();  // re-resolve + placeholders + SoC check
}

// Restore the whole form from a downloaded run config → "regenerate".
function applyConfig(cfg) {
    document.getElementById("building-cards").innerHTML = "";
    (cfg.buildings || []).forEach(b => {
        const card = createBuildingCard();
        document.getElementById("building-cards").appendChild(card);
        setCardValues(card, b);
    });
    renumberBuildingCards();
    const set = (id, v) => { if (v != null) document.getElementById(id).value = v; };
    set("u-output-path", cfg.output_path); set("u-start-month", cfg.start_month);
    set("u-end-month", cfg.end_month); set("u-samples", cfg.samples);
    set("u-workers", cfg.workers);
    set("u-dr-program", cfg.dr_program); set("u-dr-incentive", cfg.dr_incentive_per_kw);
    set("u-dr-penalty", cfg.dr_penalty_per_kwh); set("u-default-policy", cfg.default_policy);
    if (cfg.output_mode) {
        const r = document.querySelector(`input[name='output-mode'][value='${cfg.output_mode}']`);
        if (r) r.checked = true;
    }
    updateRunEstimate();
}

function addBuilding() {
    document.getElementById("building-cards").appendChild(createBuildingCard());
    renumberBuildingCards();
}

function buildUnifiedPayload() {
    const buildings = Array.from(
        document.querySelectorAll("#building-cards .building-card")
    ).map(cardToSpec);   // each building fully self-contained (no global shared overrides)

    const val = id => document.getElementById(id).value;
    const num = id => { const v = parseFloat(val(id)); return isNaN(v) ? null : v; };
    const payload = {
        buildings,
        output_mode: (document.querySelector("input[name='output-mode']:checked") || {}).value || "shared",
        output_path: val("u-output-path") || "",
        start_month: val("u-start-month"),
        end_month: val("u-end-month") || val("u-start-month"),
        samples: parseInt(val("u-samples"), 10) || 1,
        workers: parseInt(val("u-workers"), 10) || 4,
        force: document.getElementById("u-force").checked,
        default_policy: val("u-default-policy") || "ILP-MPCFIXEDFSL",
        strict_e5: document.getElementById("u-strict-e5").checked,
    };
    const drp = val("u-dr-program"); if (drp) payload.dr_program = drp;
    const inc = num("u-dr-incentive"); if (inc !== null) payload.dr_incentive_per_kw = inc;
    const pen = num("u-dr-penalty"); if (pen !== null) payload.dr_penalty_per_kwh = pen;
    return payload;
}

function runEstimate() {
    const sm = document.getElementById("u-start-month").value;
    const em = document.getElementById("u-end-month").value || sm;
    const samples = parseInt(document.getElementById("u-samples").value, 10) || 1;
    let months = 1;
    if (sm && em) {
        const [sy, smm] = sm.split("-").map(Number);
        const [ey, emm] = em.split("-").map(Number);
        months = Math.max(1, (ey - sy) * 12 + (emm - smm) + 1);
    }
    const nb = document.querySelectorAll("#building-cards .building-card").length;
    return { months, samples, units: months * samples, buildings: nb, total: months * samples * nb };
}

function updateRunEstimate() {
    const e = runEstimate();
    const el = document.getElementById("run-estimate");
    if (el) el.textContent =
        `${e.buildings} building(s) × ${e.samples} sample(s) × ${e.months} month(s) `
        + `= ${e.units} unit(s), ${e.total} building-generations.`;
}

let UNIFIED_JOB = null, UNIFIED_POLL = null, LAST_PAYLOAD = null;

async function startUnified() {
    const status = document.getElementById("status");
    let payload;
    try { payload = buildUnifiedPayload(); }
    catch (e) { status.textContent = String(e.message || e); return; }
    if (!payload.buildings.length) { status.textContent = "Add at least one building."; return; }
    if (!payload.start_month) { status.textContent = "Set a start month."; return; }
    LAST_PAYLOAD = payload;
    const btn = document.getElementById("generate-btn");
    btn.disabled = true;
    status.textContent = "Launching…";
    try {
        const resp = await fetch("/api/generate-unified", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await safeJson(resp);
        if (!resp.ok) { status.textContent = "Error: " + (data.error || resp.status); btn.disabled = false; return; }
        UNIFIED_JOB = { id: data.job_id, output_mode: payload.output_mode };
        document.getElementById("progress").style.display = "";
        status.textContent = `Running job ${data.job_id}…`;
        pollUnified();
    } catch (e) {
        status.textContent = "Request failed: " + e;
        btn.disabled = false;
    }
}

async function pollUnified() {
    if (!UNIFIED_JOB) return;
    let data;
    try {
        const resp = await fetch(`/api/generate-unified/${UNIFIED_JOB.id}/status`);
        data = await safeJson(resp);
    } catch (e) {
        document.getElementById("status").textContent = "Status poll failed: " + e;
        return;
    }
    renderBatchStatus({ manifest: data.manifest, elapsed_sec: data.elapsed_sec });
    if (data.running) {
        UNIFIED_POLL = setTimeout(pollUnified, 2000);
        return;
    }
    document.getElementById("generate-btn").disabled = false;
    const m = data.manifest || {};
    document.getElementById("status").textContent =
        `Done — ${m.status || "?"} (${m.n_succeeded || 0}/${m.n_total || 0} units, exit ${data.exit_code}).`;
    if (m.status === "succeeded" || m.status === "partial") showUnifiedAnalysis(m);
}

function showUnifiedAnalysis(manifest) {
    document.getElementById("output").style.display = "";
    const meta = document.getElementById("output-meta");
    meta.innerHTML =
        `<p class="small">job <code>${escapeHtml(UNIFIED_JOB.id)}</code> · ${manifest.n_buildings} building(s) · `
        + `${escapeHtml(manifest.output_mode)} · ${manifest.n_succeeded}/${manifest.n_total} units</p>`;
    const bar = document.createElement("div");
    bar.className = "analysis-controls";
    const zip = document.createElement("a");
    zip.href = `/api/generate-unified/${UNIFIED_JOB.id}/download`;
    zip.className = "secondary"; zip.textContent = "⬇ Download outputs (zip)";
    zip.style.textDecoration = "none"; zip.style.padding = "0.3rem 0.7rem";
    const cfgBtn = document.createElement("button");
    cfgBtn.type = "button"; cfgBtn.className = "secondary"; cfgBtn.textContent = "⬇ Download run config";
    cfgBtn.onclick = () => downloadJson(LAST_PAYLOAD, `unified_config_${UNIFIED_JOB.id}.json`);
    bar.append(zip, cfgBtn);
    meta.appendChild(bar);
    document.getElementById("run-log").textContent = JSON.stringify(manifest, null, 2);

    const months = [...new Set((manifest.samples || [])
        .filter(s => s.status === "succeeded").map(s => s.month))];
    document.getElementById("ua-month").innerHTML =
        months.map(mo => `<option value="${mo}">${mo}</option>`).join("");
    const csvSel = document.getElementById("ua-csv");
    csvSel.innerHTML = PLOTTABLE_CSVS.map(c => `<option value="${c}">${c}</option>`).join("");
    const syncFeat = () => {
        const feats = PLOT_FEATURES[csvSel.value] || [];
        document.getElementById("ua-feature").innerHTML =
            feats.map(f => `<option value="${f.value}">${f.label}</option>`).join("");
        // Time-series CSVs use the daily/monthly Aggregation toggle; distribution
        // CSVs use the box/violin/histogram Shape toggle. Show only the relevant one.
        const isTS = TIMESERIES_CSVS.has(csvSel.value);
        const aggLbl = document.getElementById("ua-agg")?.closest("label");
        const shapeLbl = document.getElementById("ua-shape")?.closest("label");
        if (aggLbl) aggLbl.style.display = isTS ? "" : "none";
        if (shapeLbl) shapeLbl.style.display = isTS ? "none" : "";
    };
    csvSel.onchange = syncFeat; syncFeat();
    const aggEl = document.getElementById("ua-agg");
    if (aggEl) aggEl.onchange = () => runUnifiedAnalysis(manifest);
    document.getElementById("ua-shape").onchange = () => runUnifiedAnalysis(manifest);
    document.getElementById("ua-run").onclick = () => runUnifiedAnalysis(manifest);
    runUnifiedAnalysis(manifest);
}

async function runUnifiedAnalysis(manifest) {
    const month = document.getElementById("ua-month").value;
    const csv = document.getElementById("ua-csv").value;
    const feature = document.getElementById("ua-feature").value;
    const st = document.getElementById("ua-status");
    st.textContent = "loading…";
    const samples = (manifest.samples || [])
        .filter(s => s.status === "succeeded" && s.month === month)
        .map(s => s.sample_idx);
    const byBuilding = {};
    for (const s of samples) {
        let rows;
        try {
            rows = await fetchAndParseCsv(
                `/api/generate-unified/${UNIFIED_JOB.id}/csv/${month}/${s}/${csv}`);
        } catch { continue; }
        rows.forEach(r => {
            const b = (r.building_id ?? 0);
            (byBuilding[b] = byBuilding[b] || []).push(r);
        });
    }
    const nB = Object.keys(byBuilding).length;
    if (!nB) { st.textContent = "no data"; return; }
    st.textContent = `${nB} building(s) · ${samples.length} sample(s)`;
    const shape = document.getElementById("ua-shape").value;
    const aggEl = document.getElementById("ua-agg");
    plotOptimus("unified-plot", csv, byBuilding, feature, shape, aggEl ? aggEl.value : "daily");
}

const BCOLORS = ["#2c7fb8", "#d8853b", "#31a354", "#756bb1", "#c51b8a", "#636363"];

// rgba band colour from a hex (for the ±1σ variance shading).
function rgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function plotOptimus(divId, csvName, byBuilding, feature, shape = "box", agg = "daily") {
    const ids = Object.keys(byBuilding).sort((a, b) => a - b);
    const traces = [];
    const isTimeSeries = TIMESERIES_CSVS.has(csvName);
    const isMonthly = agg === "monthly";

    ids.forEach((bid, i) => {
        const rows = byBuilding[bid];
        const color = BCOLORS[i % BCOLORS.length];
        const name = `building ${bid}`;

        if (isTimeSeries) {
            // Pool rows into slots, then plot the per-slot mean + ±1σ band.
            //   daily   → key = time-of-day (folds every day × sample into a
            //             mean diurnal profile);
            //   monthly → key = full timestamp (folds samples only, preserving
            //             the month-long timeline).
            // With a single sample the band collapses onto the mean line.
            const slot = {};
            rows.forEach(r => {
                const d = new Date(r.datetime);
                if (isNaN(d)) return;
                const key = isMonthly ? r.datetime : d.getHours() + d.getMinutes() / 60;
                const y = Number(r[feature]);
                if (isNaN(y)) return;
                (slot[key] = slot[key] || []).push(y);
            });
            const keys = Object.keys(slot);
            // numeric sort for hour-of-day; lexical (= chronological) for timestamps
            keys.sort(isMonthly ? undefined : (a, b) => a - b);
            const xs = isMonthly ? keys : keys.map(Number);
            const mean = [], lo = [], hi = [];
            let anyBand = false;
            keys.forEach(k => {
                const v = slot[k];
                const m = v.reduce((a, b) => a + b, 0) / v.length;
                const sd = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / v.length);
                if (sd > 0) anyBand = true;
                mean.push(m); lo.push(m - sd); hi.push(m + sd);
            });
            // band = upper then lower with fill:'tonexty' (only when >1 sample)
            if (anyBand) {
                traces.push({ x: xs, y: hi, type: "scatter", mode: "lines",
                              line: { width: 0 }, showlegend: false, hoverinfo: "skip" });
                traces.push({ x: xs, y: lo, type: "scatter", mode: "lines",
                              line: { width: 0 }, fill: "tonexty", fillcolor: rgba(color, 0.18),
                              name: `${name} ±1σ`, hoverinfo: "skip" });
            }
            traces.push({ x: xs, y: mean, type: "scatter", mode: "lines",
                          line: { color, width: 2 }, name });
        } else {
            // distribution → box / violin / histogram per building (toggle).
            const vals = extractOptimusFeature(rows, csvName, feature);
            if (shape === "violin") {
                traces.push({ y: vals, name, type: "violin", box: { visible: true },
                              meanline: { visible: true }, points: false,
                              line: { color }, fillcolor: rgba(color, 0.4) });
            } else if (shape === "histogram") {
                traces.push({ x: vals, name, type: "histogram", opacity: 0.55,
                              marker: { color }, nbinsx: feature === "arrival_hour" ? 24 : 30 });
            } else {  // box
                traces.push({ y: vals, name, type: "box", boxmean: true,
                              marker: { color }, line: { color } });
            }
        }
    });

    const isHistShape = !isTimeSeries && shape === "histogram";
    const yTitle = csvName === "building_load.csv" ? "power_kw"
                 : csvName === "grid_prices.csv" ? "$/kWh"
                 : feature;
    const aggNote = isMonthly ? "monthly series" : "daily profile";
    const layout = {
        title: `${csvName} — ${feature} by building` + (isTimeSeries ? ` (${aggNote})` : ""),
        margin: { t: 40, l: 60, r: 10, b: 50 },
        xaxis: {
            title: isTimeSeries ? (isMonthly ? "" : "hour of day")
                 : isHistShape ? feature : "building",
        },
        yaxis: {
            title: isTimeSeries ? yTitle
                 : isHistShape ? "count" : feature,
        },
    };
    if (isHistShape) layout.barmode = "overlay";
    else if (!isTimeSeries) layout.boxmode = "group";   // box + violin group by building
    Plotly.newPlot(divId, traces, layout);
}

// ────────────────────────────────────────────────────────────────────────────
// INPUT PREVIEWS — show what a selected Location / Building / Population
// produces, BEFORE generating. Two integration points share this code:
//   A) a per-field ⓘ popover (single preview, floating);
//   B) a collapsible "▶ Preview" panel per card (all three previews together).
// Density curves are computed in JS from the params the backend returns and
// drawn with the Plotly already loaded in index.html.
// ────────────────────────────────────────────────────────────────────────────

// Region series palette: tool navy + amber + valid-green + two harmonious tones.
const PREVIEW_REGION_COLORS = ["#1f4e79", "#d8853b", "#2ca02c", "#2c7fb8", "#8e5aa8"];

const _normPdf = (x, m, s) => Math.exp(-0.5 * ((x - m) / s) ** 2) / (s * Math.sqrt(2 * Math.PI));
const _weibPdf = (x, k, l) => (x <= 0 ? 0 : (k / l) * (x / l) ** (k - 1) * Math.exp(-((x / l) ** k)));
// Lanczos approximation for ln Γ(z) — needed for the Beta normalizing constant.
function _lgamma(z) {
    const g = [676.5203681218851, -1259.1392167224028, 771.32342877765313,
        -176.61502916214059, 12.507343278686905, -0.13857109526572012,
        9.9843695780195716e-6, 1.5056327351493116e-7];
    if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - _lgamma(1 - z);
    z -= 1;
    let x = 0.99999999999980993;
    for (let i = 0; i < g.length; i++) x += g[i] / (z + i + 1);
    const t = z + g.length - 0.5;
    return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}
const _betaPdf = (x, a, b) => {
    if (x <= 0 || x >= 1) return 0;
    const lnB = _lgamma(a) + _lgamma(b) - _lgamma(a + b);
    return Math.exp((a - 1) * Math.log(x) + (b - 1) * Math.log(1 - x) - lnB);
};
const _lin = (a, b, n) => Array.from({ length: n }, (_, i) => a + (b - a) * i / (n - 1));

// Abramowitz & Stegun 7.1.26 erf approximation (|err| < 1.5e-7), → standard
// normal CDF Φ. Needed to renormalize the truncated normal over its window.
function _erf(x) {
    const s = x < 0 ? -1 : 1;
    x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
        - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
}
const _normCdf = (x, mu, sigma) => 0.5 * (1 + _erf((x - mu) / (sigma * Math.SQRT2)));

// Truncated-normal pdf on [lo,hi], RENORMALIZED so it integrates to 1 over the
// window: φ((x-μ)/σ)/σ ÷ (Φ(hi)-Φ(lo)). (Without the divisor the curve is just a
// clipped normal and under-integrates whenever μ sits near a window edge.)
function _truncNormPdf(x, mu, sigma, lo, hi) {
    if (x < lo || x > hi) return 0;
    const z = _normCdf(hi, mu, sigma) - _normCdf(lo, mu, sigma);
    if (z <= 1e-9) return 0;
    return _normPdf(x, mu, sigma) / z;
}
// Evaluate an arrival distribution (single TruncNorm or 2-comp mixture) at x.
function _arrivalPdf(arr, x) {
    const lo = arr.trunc_lo != null ? arr.trunc_lo : 4;
    const hi = arr.trunc_hi != null ? arr.trunc_hi : 22;
    if (arr.dist === "truncnorm_mixture" || (arr.mu1 != null && arr.mu2 != null)) {
        const w1 = arr.w1 != null ? arr.w1 : 0.5;
        return w1 * _truncNormPdf(x, arr.mu1, arr.sigma1, lo, hi)
            + (1 - w1) * _truncNormPdf(x, arr.mu2, arr.sigma2, lo, hi);
    }
    // single truncnorm: {mu, sigma}
    if (arr.mu != null) return _truncNormPdf(x, arr.mu, arr.sigma, lo, hi);
    return 0;
}
// Evaluate a dwell distribution (single Weibull or 2-comp mixture) at x.
function _dwellPdf(dw, x) {
    if (dw.dist === "weibull_mixture" || (dw.k1 != null && dw.k2 != null)) {
        const w1 = dw.w1 != null ? dw.w1 : 0.5;
        return w1 * _weibPdf(x, dw.k1, dw.lambda1) + (1 - w1) * _weibPdf(x, dw.k2, dw.lambda2);
    }
    if (dw.k != null) return _weibPdf(x, dw.k, dw.lambda);
    return 0;
}

// Compact Plotly layout shared by the small preview charts.
function _previewLayout(opts) {
    return Object.assign({
        margin: { t: 24, l: 36, r: 8, b: 30 },
        height: opts.height || 150,
        showlegend: false,
        font: { size: 10, family: "var(--font-ui)" },
        title: opts.title ? { text: opts.title, font: { size: 11, color: "#1f4e79" } } : undefined,
        xaxis: { title: opts.xtitle ? { text: opts.xtitle, font: { size: 9 } } : undefined,
                 tickfont: { size: 8 }, zeroline: false },
        yaxis: { showticklabels: false, zeroline: false, showgrid: false },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    }, opts.extra || {});
}
const _PLOT_CFG = { displayModeBar: false, responsive: true, staticPlot: false };

// ── Location price + (illustrative) weather ──────────────────────────────────
function renderLocationPreview(hostPrice, data, hostWeather) {
    const t = data.tariff || {};
    const off = t.energy_price_offpeak, pk = t.energy_price_peak;
    const win = t.peak_window || [];
    const xs = [], ys = [];
    for (let h = 0; h <= 24; h += 0.25) {
        xs.push(h);
        const peak = win.length === 2 && h >= win[0] && h < win[1];
        ys.push(peak ? pk : off);
    }
    const traces = [{
        x: xs, y: ys, type: "scatter", mode: "lines",
        line: { color: "#1f4e79", width: 2 }, fill: "tozeroy",
        fillcolor: "rgba(31,78,121,0.10)", hoverinfo: "x+y",
    }];
    const layout = _previewLayout({
        title: `${data.id} — ${t.type || "tariff"} ($/kWh)`,
        xtitle: "hour of day",
        extra: { xaxis: { range: [0, 24], tickvals: [0, 6, 12, 18, 24], tickfont: { size: 8 } },
                 yaxis: { rangemode: "tozero", tickfont: { size: 8 }, showticklabels: true },
                 shapes: win.length === 2 ? [{
                     type: "rect", xref: "x", yref: "paper", x0: win[0], x1: win[1],
                     y0: 0, y1: 1, fillcolor: "rgba(216,133,59,0.13)", line: { width: 0 },
                 }] : [] },
    });
    Plotly.newPlot(hostPrice, traces, layout, _PLOT_CFG);

    if (hostWeather) {
        // Illustrative monthly dry-bulb shape keyed off the climate band. Marked
        // illustrative — the real TMYx series is exported only at generation.
        const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
        const CLIMATE_TEMPS = {
            subtropical: [7, 9, 14, 18, 23, 27, 28, 28, 24, 18, 12, 8],
            temperate: [4, 6, 10, 14, 19, 23, 26, 25, 21, 15, 9, 5],
            cold: [-8, -5, 1, 9, 16, 21, 24, 22, 17, 9, 1, -5],
            tropical: [20, 21, 23, 25, 27, 28, 29, 29, 28, 26, 23, 21],
        };
        const temps = CLIMATE_TEMPS[data.climate] || CLIMATE_TEMPS.temperate;
        Plotly.newPlot(hostWeather, [{
            x: months, y: temps, type: "bar",
            marker: { color: "rgba(216,133,59,0.85)" }, hoverinfo: "y",
        }], _previewLayout({
            title: `weather (illustrative · ${data.climate || "?"})`,
            extra: { yaxis: { tickfont: { size: 8 }, showticklabels: true, title: { text: "°C", font: { size: 9 } } } },
        }), _PLOT_CFG);
    }
}

// ── Building illustrative daily load ──────────────────────────────────────────
function renderBuildingPreview(host, data) {
    const ls = data.load_shape || {};
    const peak = Number(data.peak_kw) || 1;
    const xs = ls.hours || [];
    const ys = (ls.normalized || []).map(f => f * peak);
    Plotly.newPlot(host, [{
        x: xs, y: ys, type: "scatter", mode: "lines",
        line: { color: "#1f4e79", width: 2 }, fill: "tozeroy",
        fillcolor: "rgba(31,78,121,0.12)", hoverinfo: "x+y",
    }], _previewLayout({
        title: `${data.id} — ${data.archetype}/${data.size} · peak ${peak} kW (illustrative)`,
        xtitle: "hour of day",
        extra: { xaxis: { range: [0, 24], tickvals: [0, 6, 12, 18, 24], tickfont: { size: 8 } },
                 yaxis: { rangemode: "tozero", tickfont: { size: 8 }, showticklabels: true,
                          title: { text: "kW", font: { size: 9 } } } },
    }), _PLOT_CFG);
}

// ── Population arrival / dwell / SoC / region-frequency ───────────────────────
// Returns the ordered region list (name, weight, color) so callers can build a
// legend. Renders into whichever of the four hosts are provided.
function renderPopulationPreview(hosts, data) {
    const axes = data.axes_distribution || [];
    const rd = data.region_distributions || {};
    // Order regions by axes_distribution (weight order); attach a color each.
    const regions = axes.map((a, i) => ({
        name: a.name, weight: a.weight,
        color: PREVIEW_REGION_COLORS[i % PREVIEW_REGION_COLORS.length],
        dist: rd[a.name] || {},
    }));

    const mkSeries = (xs, fn) => regions
        .filter(r => fn.has(r))
        .map(r => ({
            x: xs, y: xs.map(x => fn.eval(r, x)), type: "scatter", mode: "lines",
            line: { color: r.color, width: 1.6 }, name: r.name, hoverinfo: "skip",
        }));

    if (hosts.arrival) {
        const xs = _lin(4, 22, 90);
        const traces = mkSeries(xs, {
            has: r => r.dist.arrival, eval: (r, x) => _arrivalPdf(r.dist.arrival, x),
        });
        Plotly.newPlot(hosts.arrival, traces, _previewLayout({
            title: "arrival hour — TruncNorm", xtitle: "hour",
            extra: { xaxis: { range: [4, 22], tickvals: [6, 9, 12, 15, 18, 21], tickfont: { size: 8 } } },
        }), _PLOT_CFG);
    }
    if (hosts.dwell) {
        const xs = _lin(0.05, 18, 90);
        const traces = mkSeries(xs, {
            has: r => r.dist.dwell, eval: (r, x) => _dwellPdf(r.dist.dwell, x),
        });
        Plotly.newPlot(hosts.dwell, traces, _previewLayout({
            title: "dwell hours — Weibull", xtitle: "hours",
            extra: { xaxis: { range: [0, 18], tickvals: [0, 4, 8, 12, 16], tickfont: { size: 8 } } },
        }), _PLOT_CFG);
    }
    if (hosts.soc) {
        const xs = _lin(0.01, 0.99, 90);
        const traces = mkSeries(xs, {
            has: r => r.dist.soc_arrival,
            eval: (r, x) => _betaPdf(x, r.dist.soc_arrival.alpha, r.dist.soc_arrival.beta),
        });
        Plotly.newPlot(hosts.soc, traces, _previewLayout({
            title: "arrival SoC — Beta", xtitle: "state of charge",
            extra: { xaxis: { range: [0, 1], tickvals: [0, 0.5, 1], ticktext: ["0", "50%", "100%"], tickfont: { size: 8 } } },
        }), _PLOT_CFG);
    }
    if (hosts.freq) {
        Plotly.newPlot(hosts.freq, [{
            x: regions.map(r => r.name.split("_")[0]),
            y: regions.map(r => r.weight),
            type: "bar",
            marker: { color: regions.map(r => r.color) },
            text: regions.map(r => `${Math.round((r.weight || 0) * 100)}%`),
            textposition: "outside", textfont: { size: 8 }, hoverinfo: "x+y",
        }], _previewLayout({
            title: "region frequency",
            extra: { xaxis: { tickfont: { size: 7 } }, yaxis: { rangemode: "tozero" },
                     margin: { t: 24, l: 8, r: 8, b: 40 } },
        }), _PLOT_CFG);
    }
    return regions;
}

async function _fetchPreview(kind, id) {
    const r = await fetch(`/api/preview/${kind}/${encodeURIComponent(id)}`);
    return safeJson(r);
}

// Resolve the EFFECTIVE descriptor id for a card: the explicit pick if one is
// chosen, else the base scenario's inherited descriptor (so previews render for
// defaults, not just explicit picks). Returns {id, inherited} — `inherited` is
// true when the id came from the base scenario rather than an explicit pick.
function effectiveDescriptor(card, kind) {
    const explicit = card.querySelector(".mb-" + kind).value;
    if (explicit) return { id: explicit, inherited: false };
    const baseId = card.querySelector(".mb-base").value;
    const sc = (SCENARIOS || []).find(s => s.id === baseId);
    const inheritedId = sc && sc.descriptors && sc.descriptors[kind];
    return inheritedId ? { id: inheritedId, inherited: true } : { id: null, inherited: false };
}

// ── Integration A: per-field ⓘ popover ───────────────────────────────────────
// Click an ⓘ next to Location/Building/Population → fetch the preview for the
// CURRENTLY selected option → render a compact Plotly chart in a floating
// popover. Click-outside (or clicking the same ⓘ) closes. Mirrors the
// der-popover pattern (one popover at a time, body-anchored, outside-close).
async function togglePreviewPopover(btn, kind, card) {
    const existing = document.querySelector(".preview-popover");
    const wasForThis = existing && existing._forBtn === btn;
    if (existing) existing.remove();
    if (wasForThis) return;

    // Resolve the effective descriptor: explicit pick, else the base scenario's
    // inherited default — so the ⓘ always previews something.
    const eff = effectiveDescriptor(card, kind);
    const id = eff.id;
    if (!id) return;  // no explicit pick AND no scenario default → nothing to show

    const pop = document.createElement("div");
    pop.className = "preview-popover";
    pop._forBtn = btn;
    document.body.appendChild(pop);
    const r = btn.getBoundingClientRect();
    pop.style.left = `${window.scrollX + Math.max(8, r.left - 120)}px`;
    pop.style.top = `${window.scrollY + r.bottom + 4}px`;
    pop.innerHTML = `<p class="pp-head">${kind}: ${id} — loading…</p>`;

    let data;
    try {
        data = await _fetchPreview(kind, id);
    } catch (e) {
        pop.innerHTML = `<p class="pp-head">preview fetch failed: ${escapeHtml(String(e.message || e))}</p>`;
        data = null;
    }
    if (data && data.error) { pop.innerHTML = `<p class="pp-head">${escapeHtml(data.error)}</p>`; data = null; }
    if (data) {
        // Build the head + chart hosts first (so the head survives even if the
        // Plotly draw throws — e.g. CDN unavailable), then draw in a guarded step.
        pop.innerHTML = "";
        const head = document.createElement("p");
        head.className = "pp-head";
        const tag = eff.inherited ? " (scenario default)" : "";
        const draws = [];
        if (kind === "location") {
            const t = data.tariff || {};
            head.textContent = `${id}${tag} — ${t.type || "tariff"} · DR: ${t.dr_program || "none"}`;
            pop.appendChild(head);
            const c = document.createElement("div"); c.className = "pp-chart"; pop.appendChild(c);
            draws.push(() => renderLocationPreview(c, data, null));
        } else if (kind === "building") {
            head.textContent = `${id}${tag} — ${data.archetype}/${data.size} · ${data.doe_prototype}`;
            pop.appendChild(head);
            const c = document.createElement("div"); c.className = "pp-chart"; pop.appendChild(c);
            const ls = data.load_shape || {};
            const note = document.createElement("p");
            note.className = "pp-note";
            note.textContent = ls.source === "comstock_amy2018"
                ? `real ComStock weekday shape · CZ-${ls.reference_zone} · peak = ${data.peak_kw} kW`
                : "load shape is illustrative";
            draws.push(() => { renderBuildingPreview(c, data); pop.appendChild(note); });
        } else {  // population
            head.textContent = `${id}${tag} — ${(data.axes_distribution || []).length} regions`;
            pop.appendChild(head);
            const grid = document.createElement("div"); grid.className = "pp-grid"; pop.appendChild(grid);
            const a = document.createElement("div"); a.className = "pp-chart"; grid.appendChild(a);
            const dw = document.createElement("div"); dw.className = "pp-chart"; grid.appendChild(dw);
            const so = document.createElement("div"); so.className = "pp-chart"; grid.appendChild(so);
            const fr = document.createElement("div"); fr.className = "pp-chart"; grid.appendChild(fr);
            const leg = document.createElement("div"); leg.className = "pp-legend"; pop.appendChild(leg);
            draws.push(() => {
                const regions = renderPopulationPreview({ arrival: a, dwell: dw, soc: so, freq: fr }, data);
                leg.innerHTML = regions.map(rg =>
                    `<span class="pp-k"><span class="pp-sw" style="background:${rg.color}"></span>${escapeHtml(rg.name)}</span>`).join("");
            });
        }
        try { draws.forEach(d => d()); } catch (e) {
            const err = document.createElement("p");
            err.className = "pp-note"; err.textContent = `chart unavailable: ${String(e.message || e)}`;
            pop.appendChild(err);
        }
    }

    setTimeout(() => {
        const close = (e) => {
            if (!pop.contains(e.target) && e.target !== btn) {
                pop.remove();
                document.removeEventListener("click", close);
            }
        };
        document.addEventListener("click", close);
    }, 0);
}

// ── Integration B: the collapsible "Preview" panel per card ───────────────────
// Renders all three previews (for this card's current selections) into the
// .card-preview container. Re-run whenever location/building/population change
// or the panel is opened. Skipped while the <details> is closed (cheap + avoids
// laying out hidden Plotly charts at 0 width).
async function renderCardPreview(card) {
    const details = card.querySelector(".mb-preview");
    if (!details || !details.open) return;
    const host = card.querySelector(".card-preview");
    if (!host) return;

    // Resolve EFFECTIVE descriptors: explicit pick, else the base scenario's
    // inherited default — so the panel renders for defaults, not just explicit
    // picks. A freshly-added card (nothing chosen) still shows the S01 defaults.
    const loc = effectiveDescriptor(card, "location");
    const bldg = effectiveDescriptor(card, "building");
    const pop = effectiveDescriptor(card, "population");
    const dtag = (eff) => eff.inherited ? ` <span class="pp-default-tag">scenario default</span>` : "";

    host.innerHTML = `
        <div class="preview-affects"><strong>affects →</strong>
            <span class="a-tag">prices</span><span class="a-tag">load shape</span>
            <span class="a-tag">arrival</span><span class="a-tag">dwell</span>
            <span class="a-tag">SoC / energy</span><span class="a-tag">region mix</span></div>
        <div class="pv-block" data-block="location"></div>
        <div class="pv-block" data-block="building"></div>
        <div class="pv-block" data-block="population"></div>`;

    const block = (sel) => host.querySelector(`.pv-block[data-block='${sel}']`);

    // A guarded chart draw: the block scaffold (headings, caveats, chart hosts)
    // is written first so it survives even if the Plotly draw throws — e.g. the
    // Plotly CDN is unreachable. Only the fetch/parse failures show inline.
    const drawGuarded = (hostBlock, drawFn) => {
        try { drawFn(); } catch (e) {
            const err = document.createElement("p");
            err.className = "pp-note";
            err.textContent = `chart unavailable: ${String(e.message || e)}`;
            hostBlock.appendChild(err);
        }
    };

    // location
    const locBlock = block("location");
    if (!loc.id) {
        locBlock.innerHTML = `<h4>location</h4><p class="pp-note">no location (base scenario sets none)</p>`;
    } else {
        try {
            const data = await _fetchPreview("location", loc.id);
            if (data.error) throw new Error(data.error);
            locBlock.innerHTML = `<h4>location · ${escapeHtml(loc.id)}${dtag(loc)}</h4>
                <div class="chart-grid"><div class="chart-card" data-c="price"></div>
                <div class="chart-card" data-c="weather"></div></div>
                <p class="pp-note">price is the real tariff; the monthly temperature chart is illustrative (real TMYx weather is exported at generation).</p>`;
            drawGuarded(locBlock, () => renderLocationPreview(
                locBlock.querySelector("[data-c='price']"), data,
                locBlock.querySelector("[data-c='weather']")));
        } catch (e) { locBlock.innerHTML = `<h4>location</h4><p class="pp-note">${escapeHtml(String(e.message || e))}</p>`; }
    }

    // building
    const bBlock = block("building");
    if (!bldg.id) {
        bBlock.innerHTML = `<h4>building</h4><p class="pp-note">no building (base scenario sets none)</p>`;
    } else {
        try {
            const data = await _fetchPreview("building", bldg.id);
            if (data.error) throw new Error(data.error);
            const ls = data.load_shape || {};
            const caveat = ls.source === "comstock_amy2018"
                ? `Real <strong>NREL ComStock</strong> weekday profile (CZ-${ls.reference_zone}, reference climate), normalized so the peak equals <strong>peak_kw = ${data.peak_kw} kW</strong>. The deployed location's weather shifts the real curve.`
                : `daily load shape is illustrative — normalized to peak_kw = ${data.peak_kw} kW.`;
            bBlock.innerHTML = `<h4>building · ${escapeHtml(bldg.id)}${dtag(bldg)}</h4>
                <div class="chart-grid"><div class="chart-card" data-c="load"></div></div>
                <p class="pp-note">${caveat}</p>`;
            drawGuarded(bBlock, () => renderBuildingPreview(bBlock.querySelector("[data-c='load']"), data));
        } catch (e) { bBlock.innerHTML = `<h4>building</h4><p class="pp-note">${escapeHtml(String(e.message || e))}</p>`; }
    }

    // population
    const pBlock = block("population");
    if (!pop.id) {
        pBlock.innerHTML = `<h4>population</h4><p class="pp-note">no population (base scenario sets none)</p>`;
    } else {
        try {
            const data = await _fetchPreview("population", pop.id);
            if (data.error) throw new Error(data.error);
            pBlock.innerHTML = `<h4>population · ${escapeHtml(pop.id)}${dtag(pop)} — ${(data.axes_distribution || []).length} regions</h4>
                <div class="chart-grid">
                    <div class="chart-card" data-c="arr"></div><div class="chart-card" data-c="dw"></div>
                    <div class="chart-card" data-c="soc"></div><div class="chart-card" data-c="freq"></div>
                </div><div class="pp-legend" data-c="leg"></div>`;
            drawGuarded(pBlock, () => {
                const regions = renderPopulationPreview({
                    arrival: pBlock.querySelector("[data-c='arr']"),
                    dwell: pBlock.querySelector("[data-c='dw']"),
                    soc: pBlock.querySelector("[data-c='soc']"),
                    freq: pBlock.querySelector("[data-c='freq']"),
                }, data);
                pBlock.querySelector("[data-c='leg']").innerHTML = regions.map(rg =>
                    `<span class="pp-k"><span class="pp-sw" style="background:${rg.color}"></span>${escapeHtml(rg.name)}</span>`).join("");
            });
        } catch (e) { pBlock.innerHTML = `<h4>population</h4><p class="pp-note">${escapeHtml(String(e.message || e))}</p>`; }
    }
}

function extractOptimusFeature(rows, csvName, feature) {
    if (csvName === "sessions.csv" && feature === "arrival_hour") {
        return rows.map(r => {
            const d = new Date(r.arrival);
            return isNaN(d) ? null : d.getHours() + d.getMinutes() / 60;
        }).filter(v => v !== null);
    }
    if (csvName === "sessions.csv" && feature === "duration") {
        return rows.map(r => Number(r.duration) / 3600).filter(v => !isNaN(v));  // sec → hours
    }
    return rows.map(r => Number(r[feature])).filter(v => !isNaN(v));
}

init();
