// Client logic. Single-page configurator.
// All state lives in `state`. Widget changes mutate state.overrides /
// state.descriptors / state.seed. Generate POSTs `state` to /api/generate.

const state = {
    base_scenario: "S01",
    descriptors: {},     // {location:..., building:..., population:..., equipment:...}
    overrides: {},       // {"bucket.knob": value}
    seed: 42,
    noise_profile: null,
    strict_e5: false,
};

let DESCRIPTORS = null;   // {location: [...], building: [...], ...}
let KNOBS = null;         // {bucket: {knob: spec}}
let SCENARIOS = null;     // [{id, description, descriptors, overrides}, ...]

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

    populateScenarioSelect();
    populateDescriptorSelects();
    populateNoiseSelect();
    populateKnobBuckets();
    attachListeners();
    syncFromScenario(state.base_scenario);
}

// ────────────────────────────────────────────────────────────────────
// Populate selects
// ────────────────────────────────────────────────────────────────────

function populateScenarioSelect() {
    const sel = document.getElementById("base-scenario-select");
    SCENARIOS.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `${s.id} — ${s.description}`.slice(0, 140);
        sel.appendChild(opt);
    });
    sel.value = state.base_scenario;
    sel.addEventListener("change", e => {
        state.base_scenario = e.target.value;
        syncFromScenario(e.target.value);
    });
}

function populateDescriptorSelects() {
    for (const cat of ["location", "building", "population", "equipment"]) {
        const sel = document.getElementById(`${cat}-select`);
        if (!sel) continue;
        sel.innerHTML = "";
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "(use base scenario)";
        sel.appendChild(blank);
        (DESCRIPTORS[cat] || []).forEach(opt => {
            const o = document.createElement("option");
            o.value = opt.id;
            o.textContent = `${opt.id}${opt.description ? " — " + opt.description.slice(0, 70) : ""}`;
            sel.appendChild(o);
        });
        sel.addEventListener("change", e => {
            if (e.target.value) state.descriptors[cat] = e.target.value;
            else delete state.descriptors[cat];
            renderOverrideSummary();
        });
    }
}

function populateNoiseSelect() {
    const sel = document.getElementById("noise-select");
    sel.innerHTML = "";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "(use scenario default)";
    sel.appendChild(blank);
    (DESCRIPTORS.noise || []).forEach(opt => {
        const o = document.createElement("option");
        o.value = opt.id;
        o.textContent = `${opt.id} — ${opt.description.slice(0, 70)}`;
        sel.appendChild(o);
    });
    sel.addEventListener("change", e => {
        state.noise_profile = e.target.value || null;
        renderOverrideSummary();
    });
}

function syncFromScenario(scenarioId) {
    const sc = SCENARIOS.find(s => s.id === scenarioId);
    if (!sc) return;
    // Reflect base descriptors in the selectors visually but DON'T pin them
    // into state.descriptors (keep them empty so the backend uses the
    // unmodified base scenario when the user hasn't touched anything).
    for (const cat of ["location", "building", "population", "equipment"]) {
        const sel = document.getElementById(`${cat}-select`);
        const baseVal = (sc.descriptors || {})[cat];
        if (sel && baseVal) {
            // Highlight what the base provides by adjusting placeholder text only.
            sel.querySelector("option[value='']").textContent = `(base: ${baseVal})`;
        }
        delete state.descriptors[cat];
        if (sel) sel.value = "";
    }
    state.noise_profile = null;
    document.getElementById("noise-select").value = "";
    renderOverrideSummary();
}

// ────────────────────────────────────────────────────────────────────
// Knob bucket rendering
// ────────────────────────────────────────────────────────────────────

function populateKnobBuckets() {
    const container = document.getElementById("knob-buckets");
    container.innerHTML = "";
    for (const [bucket, knobs] of Object.entries(KNOBS)) {
        const section = document.createElement("section");
        section.className = "knob-bucket";
        const h3 = document.createElement("h3");
        h3.textContent = bucket;
        section.appendChild(h3);

        for (const [knobName, spec] of Object.entries(knobs)) {
            const path = `${bucket}.${knobName}`;
            const widget = createKnobWidget(path, spec);
            section.appendChild(widget);
        }
        container.appendChild(section);
    }
}

function createKnobWidget(path, spec) {
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
    const input = createInputForType(path, spec, wrapper);
    inputRow.appendChild(input);

    const resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.textContent = "reset";
    resetBtn.style.padding = "0.2rem 0.5rem";
    resetBtn.style.fontSize = "0.7rem";
    resetBtn.addEventListener("click", () => {
        delete state.overrides[path];
        wrapper.classList.remove("modified");
        resetWidgetValue(input, spec);
        renderOverrideSummary();
    });
    inputRow.appendChild(resetBtn);

    label.appendChild(inputRow);
    wrapper.appendChild(label);
    return wrapper;
}

function createInputForType(path, spec, wrapper) {
    const onChange = (v, valid = true) => {
        if (!valid) return;
        if (deepEqual(v, spec.default)) {
            delete state.overrides[path];
            wrapper.classList.remove("modified");
        } else {
            state.overrides[path] = v;
            wrapper.classList.add("modified");
        }
        renderOverrideSummary();
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
            inp.value = spec.default;
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
            cb.checked = !!spec.default;
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
                if (choice === spec.default) opt.selected = true;
                sel.appendChild(opt);
            });
            sel.addEventListener("change", e => onChange(e.target.value));
            return sel;
        }

        case "simplex":
            return createSimplexWidget(path, spec, wrapper, onChange);

        case "vec2":
            return createVec2Widget(path, spec, onChange);

        case "list[vec2]":
        case "list[region]":
        case "path":
        case "timestamp":
        default: {
            const ta = document.createElement("textarea");
            ta.rows = 2;
            ta.value = JSON.stringify(spec.default);
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

function createSimplexWidget(path, spec, wrapper, onChange) {
    const container = document.createElement("div");
    container.className = "simplex-widget";

    const components = spec.components || spec.default.map((_, i) => `c${i}`);
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
        inp.value = spec.default[i];
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

function createVec2Widget(path, spec, onChange) {
    const container = document.createElement("div");
    container.className = "vec2-widget";
    const [a, b] = spec.default;
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

function resetWidgetValue(input, spec) {
    if (spec.type === "bool" && input.tagName === "SPAN") {
        input.querySelector("input").checked = !!spec.default;
    } else if (spec.type === "simplex") {
        const inputs = input.querySelectorAll("input");
        spec.default.forEach((v, i) => { if (inputs[i]) inputs[i].value = v; });
        // re-trigger sum recompute
        if (inputs[0]) inputs[0].dispatchEvent(new Event("input"));
    } else if (spec.type === "vec2") {
        const inputs = input.querySelectorAll("input");
        if (inputs[0]) inputs[0].value = spec.default[0];
        if (inputs[1]) inputs[1].value = spec.default[1];
    } else if (spec.type === "categorical") {
        input.value = spec.default;
    } else if (input.tagName === "TEXTAREA") {
        input.value = JSON.stringify(spec.default);
    } else if (input.tagName === "INPUT") {
        input.value = spec.default;
    }
}

// ────────────────────────────────────────────────────────────────────
// Misc UI
// ────────────────────────────────────────────────────────────────────

function attachListeners() {
    document.getElementById("seed").addEventListener("change", e => {
        const v = parseInt(e.target.value, 10);
        if (!Number.isNaN(v)) state.seed = v;
    });
    document.getElementById("strict-e5").addEventListener("change", e => {
        state.strict_e5 = e.target.checked;
    });
    document.getElementById("generate-btn").addEventListener("click", generate);
}

function renderOverrideSummary() {
    const section = document.getElementById("override-summary");
    const pre = document.getElementById("override-pre");
    const payload = buildPayload();
    const hasContent =
        Object.keys(payload.overrides).length > 0 ||
        Object.keys(payload.descriptors).length > 0 ||
        payload.noise_profile;
    section.style.display = hasContent ? "" : "none";
    pre.textContent = JSON.stringify(payload, null, 2);
}

function buildPayload() {
    return {
        base_scenario: state.base_scenario,
        seed: state.seed,
        descriptors: { ...state.descriptors },
        overrides: { ...state.overrides },
        noise_profile: state.noise_profile,
        strict_e5: state.strict_e5,
    };
}

// ────────────────────────────────────────────────────────────────────
// Generate + render output
// ────────────────────────────────────────────────────────────────────

async function generate() {
    const btn = document.getElementById("generate-btn");
    const status = document.getElementById("status");
    btn.disabled = true;
    status.className = "";
    status.innerHTML = '<span class="spinner"></span> Generating…';
    document.getElementById("output").style.display = "none";

    const t0 = performance.now();
    const payload = buildPayload();

    try {
        const resp = await fetch("/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
            status.className = "error";
            status.textContent = `Error: ${data.error || resp.statusText}`;
            console.error(data);
            const out = document.getElementById("output");
            out.style.display = "block";
            document.getElementById("output-tabs").innerHTML = "";
            document.getElementById("output-panel").innerHTML =
                `<pre>${escapeHtml(data.stderr || data.stdout || data.error || "")}</pre>`;
            document.getElementById("downloads").innerHTML = "";
            document.getElementById("run-log").textContent = JSON.stringify(data, null, 2);
            return;
        }
        const dt = ((performance.now() - t0) / 1000).toFixed(2);
        status.className = "success";
        status.textContent = `Done in ${dt}s — run ${data.run_id}`;
        renderOutput(data, dt);
    } catch (e) {
        status.className = "error";
        status.textContent = "Request failed: " + e.message;
    } finally {
        btn.disabled = false;
    }
}

function renderOutput(result, dt) {
    const output = document.getElementById("output");
    output.style.display = "block";

    const meta = document.getElementById("output-meta");
    const m = result.manifest;
    meta.innerHTML = `
        scenario_id=${m.scenario_id} · seed=${m.seed} · run_id=${result.run_id} · elapsed=${dt}s
    `;

    const tabs = document.getElementById("output-tabs");
    tabs.innerHTML = "";
    const csvNames = Object.keys(result.csv_summaries);
    csvNames.forEach((name, i) => {
        const btn = document.createElement("button");
        btn.textContent = name;
        btn.className = "tab" + (i === 0 ? " active" : "");
        btn.addEventListener("click", () => activateTab(name, result));
        tabs.appendChild(btn);
    });
    const manifestTab = document.createElement("button");
    manifestTab.textContent = "manifest.json";
    manifestTab.className = "tab";
    manifestTab.addEventListener("click", () => activateTab("__manifest", result));
    tabs.appendChild(manifestTab);

    const resTab = document.createElement("button");
    resTab.textContent = "knob_resolution";
    resTab.className = "tab";
    resTab.addEventListener("click", () => activateTab("__resolution", result));
    tabs.appendChild(resTab);

    if (csvNames.length > 0) activateTab(csvNames[0], result);

    const downloads = document.getElementById("downloads");
    downloads.innerHTML = "<h3>Downloads</h3>";
    csvNames.forEach(name => {
        const a = document.createElement("a");
        a.href = `/api/output/${result.run_id}/${name}`;
        a.textContent = name;
        a.download = name;
        downloads.appendChild(a);
    });
    const ml = document.createElement("a");
    ml.href = `/api/output/${result.run_id}/manifest`;
    ml.textContent = "manifest.json";
    ml.download = "manifest.json";
    downloads.appendChild(ml);

    document.getElementById("run-log").textContent =
        `$ ${result.command}\n\n--- stdout ---\n${result.stdout}\n--- stderr ---\n${result.stderr || ""}`;
}

function activateTab(name, result) {
    document.querySelectorAll(".tab").forEach(t => {
        const isActive =
            t.textContent === name ||
            (name === "__manifest" && t.textContent === "manifest.json") ||
            (name === "__resolution" && t.textContent === "knob_resolution");
        t.classList.toggle("active", isActive);
    });
    const panel = document.getElementById("output-panel");
    panel.innerHTML = "";

    if (name === "__manifest") {
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(result.manifest, null, 2);
        panel.appendChild(pre);
        return;
    }
    if (name === "__resolution") {
        renderKnobResolution(panel, result.manifest);
        return;
    }

    const summary = result.csv_summaries[name];
    if (!summary) return;

    const info = document.createElement("div");
    info.innerHTML = `<p style="margin:0.5rem 0;font-size:0.9rem;">Rows: <b>${summary.row_count}</b> · Columns: ${summary.columns.length} (${summary.columns.slice(0, 6).join(", ")}${summary.columns.length > 6 ? "…" : ""})</p>`;
    panel.appendChild(info);

    if (summary.head.length > 0) {
        const plotDiv = document.createElement("div");
        plotDiv.id = `plot-${name.replace(/\W/g, "_")}`;
        plotDiv.style.height = "360px";
        panel.appendChild(plotDiv);
        renderCsvPlot(plotDiv.id, name, summary);
    }

    panel.appendChild(buildTable(summary.head, summary.columns));
}

function renderKnobResolution(panel, manifest) {
    const res = manifest.knob_resolution || {};
    const table = document.createElement("table");
    table.className = "csv-preview";
    table.innerHTML = "<thead><tr><th>knob</th><th>value</th><th>source</th></tr></thead>";
    const tbody = document.createElement("tbody");

    const sortedKeys = Object.keys(res).sort();
    for (const k of sortedKeys) {
        const entry = res[k];
        const src = entry.source || "";
        const cls = src.startsWith("explicit") ? "source-explicit"
            : src.startsWith("descriptor") ? "source-descriptor"
            : src.startsWith("calibration") ? "source-calibration"
            : "source-default";
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><code>${k}</code></td><td>${formatValue(entry.value)}</td><td class="${cls}">${src}</td>`;
        tbody.appendChild(tr);
    }
    table.appendChild(tbody);

    const wrap = document.createElement("div");
    wrap.className = "csv-preview-wrap";
    wrap.appendChild(table);
    panel.appendChild(wrap);
}

function renderCsvPlot(divId, csvName, summary) {
    const head = summary.head;
    if (!head.length) return;
    const cols = new Set(summary.columns);

    try {
        if (csvName === "building_load.csv" && cols.has("timestamp") && cols.has("power_flex_kw")) {
            Plotly.newPlot(divId, [
                { x: head.map(r => r.timestamp), y: head.map(r => r.power_flex_kw), name: "flex", type: "scatter", mode: "lines" },
                { x: head.map(r => r.timestamp), y: head.map(r => r.power_inflex_kw), name: "inflex", type: "scatter", mode: "lines" },
            ], { title: "Building load (first 50 rows)", margin: { t: 30, l: 50, r: 10, b: 40 }, xaxis: { title: "" }, yaxis: { title: "kW" } });
            return;
        }
        if (csvName === "grid_prices.csv" && cols.has("timestamp")) {
            const priceCol = ["price_per_kwh", "price", "energy_price"].find(c => cols.has(c));
            if (priceCol) {
                Plotly.newPlot(divId, [
                    { x: head.map(r => r.timestamp), y: head.map(r => r[priceCol]), type: "scatter", mode: "lines+markers" },
                ], { title: `Grid prices (first 50 rows): ${priceCol}`, margin: { t: 30, l: 50, r: 10, b: 40 }, yaxis: { title: "$/kWh" } });
                return;
            }
        }
        if (csvName === "sessions.csv" && cols.has("arrival")) {
            const arrHours = head.map(r => {
                const d = new Date(r.arrival);
                return isNaN(d) ? null : d.getHours() + d.getMinutes() / 60;
            }).filter(v => v !== null);
            Plotly.newPlot(divId, [
                { x: arrHours, type: "histogram", nbinsx: 24 },
            ], { title: "Session arrival hour (first 50 rows)", margin: { t: 30, l: 50, r: 10, b: 40 }, xaxis: { title: "hour of day" }, yaxis: { title: "count" } });
            return;
        }
        if (csvName === "dr_events.csv" && cols.has("event_start")) {
            Plotly.newPlot(divId, [
                { x: head.map(r => r.event_start), y: head.map((_, i) => i + 1), type: "scatter", mode: "markers" },
            ], { title: "DR events", margin: { t: 30, l: 50, r: 10, b: 40 } });
            return;
        }

        const numericCols = summary.columns.filter(c =>
            (summary.dtypes[c] || "").includes("int") || (summary.dtypes[c] || "").includes("float")
        );
        if (numericCols.length > 0) {
            const col = numericCols[0];
            Plotly.newPlot(divId, [
                { x: head.map(r => r[col]), type: "histogram" },
            ], { title: `${csvName} — ${col} distribution`, margin: { t: 30, l: 50, r: 10, b: 40 } });
        }
    } catch (e) {
        console.warn("plot failed", e);
    }
}

function buildTable(rows, cols) {
    const wrap = document.createElement("div");
    wrap.className = "csv-preview-wrap";
    const table = document.createElement("table");
    table.className = "csv-preview";

    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    cols.forEach(c => {
        const th = document.createElement("th");
        th.textContent = c;
        trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.forEach(row => {
        const tr = document.createElement("tr");
        cols.forEach(c => {
            const td = document.createElement("td");
            const v = row[c];
            td.textContent =
                (typeof v === "number" && !Number.isInteger(v))
                    ? v.toFixed(4)
                    : String(v);
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    wrap.appendChild(table);
    return wrap;
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

init();
