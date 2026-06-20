// Client logic for the multi-building configurator.
// Each .building-card owns its own state in `card._ctx = {overrides, resolved}`
// (per-card knob panel). Generate POSTs the assembled per-building config to
// /api/generate-unified.

let DESCRIPTORS = null;   // {location: [...], building: [...], ...}
let KNOBS = null;         // {bucket: {knob: spec}}
let SCENARIOS = null;     // [{id, description, descriptors, overrides}, ...]

// Feature picker for distribution plots, per-CSV — OPTIMUS schema (building_id
// aware). Column names match export_optimus.py output.
const PLOT_FEATURES = {
    "building_load.csv": [
        { value: "power_kw",            label: "power_kw (total)" },
        { value: "power_kw_flexible",   label: "power_kw_flexible (HVAC)" },
        { value: "power_kw_inflexible", label: "power_kw_inflexible (lights + plug)" },
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
        { value: "dry_bulb_temp_c",        label: "dry-bulb temperature (°C)" },
        { value: "global_horizontal_w_m2", label: "solar GHI (W/m²)" },
        { value: "relative_humidity_pct",  label: "relative humidity (%)" },
        { value: "wind_speed_m_s",         label: "wind speed (m/s)" },
    ],
};
// CSVs that carry per-building distributions worth plotting.
const PLOTTABLE_CSVS = ["building_load.csv", "weather_data.csv", "sessions.csv", "cars.csv", "grid_prices.csv"];
// Time-series CSVs (datetime axis) — support the daily-profile / monthly toggle.
const TIMESERIES_CSVS = new Set(["building_load.csv", "weather_data.csv", "grid_prices.csv"]);

// Knobs promoted into the per-card Scenario Descriptors / quick-fields. They are
// still regular knobs (override path + manifest source unchanged) — just
// surfaced as dedicated inputs and hidden from the Advanced panel so users
// don't see the same control twice.
const SHORTCUT_KNOBS = new Set([
    "building_load.tmyx_station",
    "building_load.peak_kw",
    "building_load.peak_kw_scaling",
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
        [DESCRIPTORS, KNOBS, SCENARIOS] = await Promise.all([
            fetch("/api/descriptors").then(r => r.json()),
            fetch("/api/knobs").then(r => r.json()),
            fetch("/api/scenarios").then(r => r.json()),
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
        if (bucket === "noise") continue;  // → Perturbations panel
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
    card.querySelectorAll(".card-knob-buckets .knob, .card-perturb-knobs .knob").forEach(widget => {
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
    card.querySelectorAll(".card-knob-buckets .knob, .card-perturb-knobs .knob").forEach(widget => {
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
            <label><span class="field-name">Location</span><select class="mb-location"></select></label>
            <label><span class="field-name">Building</span><select class="mb-building"></select></label>
            <label><span class="field-name">Population</span><select class="mb-population"></select></label>
            <label><span class="field-name">Equipment</span><select class="mb-equipment"></select></label>
            <label><span class="field-name">Seed</span><input type="number" class="mb-seed" step="1"></label>
            <label><span class="field-name">EV count</span><input type="number" class="mb-ev-count" min="1" placeholder="scenario default"></label>
            <label><span class="field-name">Charger count</span><input type="number" class="mb-charger-count" min="1" placeholder="scenario default"></label>
            <label><span class="field-name">Peak kW</span><input type="number" class="mb-peak-kw" min="50" step="10" placeholder="blank = no scaling; enter to scale max→this"></label>
            <label><span class="field-name">Min SoC %</span><input type="number" class="mb-min-soc" min="0" max="100" step="1" placeholder="(10)"></label>
            <label><span class="field-name">Max SoC %</span><input type="number" class="mb-max-soc" min="0" max="100" step="1" placeholder="(90)"></label>
            <label><span class="field-name">Policy</span><input type="text" class="mb-policy" placeholder="(default policy)"></label>
            <label><span class="field-name">Weather noise (pre-generation)</span><select class="mb-weather">
                <option value="none">none</option>
                <option value="slight">slight (±1°C)</option>
                <option value="moderate">moderate (±2.5°C)</option>
                <option value="strong">strong (±5°C)</option>
            </select></label>
            <label><span class="field-name">Building load noise (post-generation)</span><select class="mb-noise"></select></label>
        </div>
        <div class="mb-soc-warn inline-error" style="display:none"></div>
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
    // Default seed = the card's monotonic index → 1st building is 0, each new
    // one increments (0, 1, 2, …). Distinct seeds give independent realizations;
    // the user can still edit it, and loading a config restores the saved seed.
    card.querySelector(".mb-seed").value = idx;
    populateCardKnobs(card);          // generic Advanced panel
    populateCardPerturbations(card);  // consolidated noise + weather panel

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
