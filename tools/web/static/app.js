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
let RESOLVED = {};        // {path: {value, source}} — from /api/resolve

// Feature picker for distribution plots, per-CSV.
const PLOT_FEATURES = {
    "building_load.csv": [
        { value: "power_kw",         label: "power_kw (total)" },
        { value: "power_flex_kw",    label: "power_flex_kw (HVAC)" },
        { value: "power_inflex_kw",  label: "power_inflex_kw (lights + plug)" },
    ],
    "sessions.csv": [
        { value: "arrival_hour",                  label: "arrival hour" },
        { value: "departure_hour",                label: "departure hour" },
        { value: "duration_sec",                  label: "duration (sec)" },
        { value: "arrival_soc",                   label: "arrival SoC" },
        { value: "required_soc_at_depart",        label: "required SoC at depart" },
        { value: "previous_day_external_use_soc", label: "previous-day external use SoC" },
    ],
    "cars.csv": [
        { value: "capacity_kwh",     label: "capacity (kWh)" },
        { value: "min_allowed_soc",  label: "min allowed SoC" },
        { value: "max_allowed_soc",  label: "max allowed SoC" },
        { value: "battery_class",    label: "battery class" },
    ],
};

// Default fixed bin count for histogram overlays. Bin EDGES are computed
// from the global min/max across all samples in a batch run so bars from
// different samples align column-for-column.
const HIST_BINS = 30;
const HOUR_BINS = 24;

function getEffectiveDefault(path, spec) {
    if (RESOLVED && RESOLVED[path] && RESOLVED[path].value !== undefined) {
        return RESOLVED[path].value;
    }
    return spec.default;
}

function getEffectiveSource(path) {
    if (RESOLVED && RESOLVED[path]) return RESOLVED[path].source;
    return "default";
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

    populateScenarioSelect();
    populateDescriptorSelects();
    populateNoiseSelect();
    populateKnobBuckets();
    attachListeners();
    syncFromScenario(state.base_scenario);
    await refreshResolvedDefaults();
}

async function refreshResolvedDefaults() {
    try {
        const resp = await fetch("/api/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                base_scenario: state.base_scenario,
                descriptors: state.descriptors,
            }),
        });
        const data = await resp.json();
        if (data.error) {
            console.warn("resolve failed:", data.error);
            return;
        }
        RESOLVED = data;
    } catch (e) {
        console.warn("resolve fetch failed:", e);
        return;
    }
    // For every knob widget, refresh displayed value (if user hasn't overridden)
    // and refresh source label.
    document.querySelectorAll(".knob").forEach(widget => {
        const path = widget.dataset.path;
        if (!path) return;
        const [bucket, knobName] = path.split(/\.(.+)/);
        const spec = (KNOBS[bucket] || {})[knobName];
        if (!spec) return;
        if (!(path in state.overrides)) {
            const resolvedVal = getEffectiveDefault(path, spec);
            const input = widget.querySelector(".knob-input-row > :first-child");
            if (input) resetWidgetValue(input, spec, resolvedVal);
            widget.classList.remove("modified");
        }
        updateSourceLabel(widget, path);
    });
}

function updateSourceLabel(widget, path) {
    const src = (path in state.overrides) ? "explicit (you)" : getEffectiveSource(path);
    const label = widget.querySelector(".source-label");
    if (!label) return;
    label.textContent = `from: ${src}`;
    const head = src.split(":")[0];
    const cls = (path in state.overrides) ? "source-explicit"
              : head === "descriptor" ? "source-descriptor"
              : head === "calibration" ? "source-calibration"
              : head === "explicit" ? "source-explicit"
              : "source-default";
    label.className = `source-label ${cls}`;
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
    sel.addEventListener("change", async e => {
        state.base_scenario = e.target.value;
        state.overrides = {};
        syncFromScenario(e.target.value);
        await refreshResolvedDefaults();
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
        sel.addEventListener("change", async e => {
            if (e.target.value) state.descriptors[cat] = e.target.value;
            else delete state.descriptors[cat];
            renderOverrideSummary();
            await refreshResolvedDefaults();
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
        resetWidgetValue(input, spec, getEffectiveDefault(path, spec));
        updateSourceLabel(wrapper, path);
        renderOverrideSummary();
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

function createInputForType(path, spec, wrapper) {
    const effDefault = getEffectiveDefault(path, spec);
    const onChange = (v, valid = true) => {
        if (!valid) return;
        const baseline = getEffectiveDefault(path, spec);
        if (deepEqual(v, baseline)) {
            delete state.overrides[path];
            wrapper.classList.remove("modified");
        } else {
            state.overrides[path] = v;
            wrapper.classList.add("modified");
        }
        updateSourceLabel(wrapper, path);
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

function createSimplexWidget(path, spec, wrapper, onChange) {
    const container = document.createElement("div");
    container.className = "simplex-widget";

    const effDefault = getEffectiveDefault(path, spec);
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

function createVec2Widget(path, spec, onChange) {
    const container = document.createElement("div");
    container.className = "vec2-widget";
    const [a, b] = getEffectiveDefault(path, spec);
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
    document.getElementById("generate-btn").addEventListener("click", onGenerateClick);

    // Batch listeners — recompute estimate on every change.
    ["batch-start-month", "batch-end-month", "batch-samples", "batch-workers"]
        .forEach(id => document.getElementById(id).addEventListener("input", updateBatchEstimate));
    document.getElementById("batch-cancel").addEventListener("click", cancelBatch);
    updateBatchEstimate();
}

function batchTotal() {
    const start = document.getElementById("batch-start-month").value;
    const end = document.getElementById("batch-end-month").value;
    const samples = parseInt(document.getElementById("batch-samples").value, 10) || 1;
    if (!start || !end) return { months: 1, samples, total: samples };
    const sd = new Date(start + "-01");
    const ed = new Date(end + "-01");
    const months = (ed.getFullYear() - sd.getFullYear()) * 12 + (ed.getMonth() - sd.getMonth()) + 1;
    return { months: Math.max(1, months), samples, total: Math.max(1, months) * samples };
}

function updateBatchEstimate() {
    const { months, samples, total } = batchTotal();
    const workers = parseInt(document.getElementById("batch-workers").value, 10) || 4;
    const el = document.getElementById("batch-estimate");
    const btn = document.getElementById("generate-btn");
    if (total <= 1) {
        el.textContent = "Single sample — uses /api/generate (current behavior).";
        btn.textContent = "Generate scenario";
    } else {
        const serialMin = Math.max(1, Math.round(total * 13 / 60));
        const parallelMin = Math.max(1, Math.round(serialMin / Math.max(1, workers)));
        el.innerHTML = `Batch: <strong>${total} samples</strong> (${months} month${months>1?"s":""} × ${samples}/month). Est. ~${parallelMin} min with ${workers} workers.`;
        btn.textContent = "Generate batch";
    }
}

function onGenerateClick() {
    const { total } = batchTotal();
    if (total <= 1) {
        generate();
    } else {
        startBatch();
    }
}

let BATCH_POLL_ID = null;
let CURRENT_BATCH_ID = null;

async function startBatch() {
    const outputPath = document.getElementById("batch-output-path").value.trim();
    const startMonth = document.getElementById("batch-start-month").value;
    const endMonth = document.getElementById("batch-end-month").value;
    const samples = parseInt(document.getElementById("batch-samples").value, 10) || 1;
    const workers = parseInt(document.getElementById("batch-workers").value, 10) || 4;
    const force = document.getElementById("batch-force").checked;

    if (!outputPath) {
        alert("Output path required for batch mode.");
        return;
    }

    const status = document.getElementById("status");
    status.className = "";
    status.innerHTML = '<span class="spinner"></span> Launching batch…';
    document.getElementById("generate-btn").disabled = true;
    document.getElementById("output").style.display = "none";

    const payload = {
        base_scenario: state.base_scenario,
        output_path: outputPath,
        start_month: startMonth,
        end_month: endMonth,
        samples,
        workers,
        force,
        noise_profile: state.noise_profile || "tmyx_stochastic",
        overrides: state.overrides,
    };
    let data;
    try {
        const resp = await fetch("/api/batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        data = await resp.json();
        if (!resp.ok) {
            status.className = "error";
            status.textContent = `Error: ${data.error || resp.statusText}`;
            document.getElementById("generate-btn").disabled = false;
            return;
        }
    } catch (e) {
        status.className = "error";
        status.textContent = "Batch launch failed: " + e.message;
        document.getElementById("generate-btn").disabled = false;
        return;
    }

    CURRENT_BATCH_ID = data.batch_id;
    document.getElementById("batch-progress").style.display = "";
    status.textContent = `Batch ${CURRENT_BATCH_ID} running…`;
    pollBatch();
}

async function pollBatch() {
    if (!CURRENT_BATCH_ID) return;
    let data;
    try {
        const resp = await fetch(`/api/batch/${CURRENT_BATCH_ID}/status`);
        data = await resp.json();
    } catch (e) {
        document.getElementById("batch-status-text").textContent = "poll failed: " + e.message;
        BATCH_POLL_ID = setTimeout(pollBatch, 2000);
        return;
    }
    renderBatchStatus(data);
    if (data.running) {
        BATCH_POLL_ID = setTimeout(pollBatch, 2000);
    } else {
        document.getElementById("generate-btn").disabled = false;
        const status = document.getElementById("status");
        if (data.exit_code === 0) {
            status.className = "success";
            status.textContent = `Batch ${CURRENT_BATCH_ID} complete (rc=${data.exit_code}).`;
        } else {
            status.className = "error";
            status.textContent = `Batch ${CURRENT_BATCH_ID} finished with rc=${data.exit_code}.`;
        }
        if (data.manifest && (data.manifest.status === "succeeded" || data.manifest.status === "partial")) {
            showBatchAnalysisPanel(CURRENT_BATCH_ID, data.manifest);
        }
    }
}

function showBatchAnalysisPanel(batchId, manifest) {
    let panel = document.getElementById("batch-analysis");
    if (!panel) {
        panel = document.createElement("section");
        panel.id = "batch-analysis";
        panel.innerHTML = `
            <h2>Batch analysis</h2>
            <p class="hint">Overlay all samples for a given month onto one plot. Pick CSV and feature.</p>
            <div class="batch-grid">
                <label><span class="field-name">Month</span>
                    <select id="batch-analysis-month"></select>
                </label>
                <label><span class="field-name">CSV</span>
                    <select id="batch-analysis-csv">
                        <option value="building_load.csv">building_load.csv</option>
                        <option value="grid_prices.csv">grid_prices.csv</option>
                        <option value="sessions.csv">sessions.csv</option>
                        <option value="cars.csv">cars.csv</option>
                    </select>
                </label>
                <label id="batch-analysis-feature-label"><span class="field-name">Feature</span>
                    <select id="batch-analysis-feature"></select>
                </label>
                <label id="batch-analysis-window-label"><span class="field-name">Window</span>
                    <select id="batch-analysis-window">
                        <option value="1day">1 day</option>
                        <option value="month" selected>Whole month</option>
                    </select>
                </label>
            </div>
            <button id="batch-analysis-run" type="button" style="margin-top:0.5rem">Generate Analysis</button>
            <span id="batch-analysis-status" class="small" style="margin-left:0.5rem"></span>
            <div id="batch-analysis-plot" style="height:420px;margin-top:0.5rem;display:none"></div>
        `;
        document.getElementById("batch-progress").after(panel);
    }
    const monthSel = document.getElementById("batch-analysis-month");
    const months = [...new Set((manifest.samples || []).filter(s => s.status === "succeeded").map(s => s.month))];
    monthSel.innerHTML = months.map(m => `<option value="${m}">${m}</option>`).join("");

    const csvSel = document.getElementById("batch-analysis-csv");
    const syncFeatureWindow = () => updateBatchAnalysisPickers(csvSel.value);
    csvSel.onchange = syncFeatureWindow;
    syncFeatureWindow();

    const runBtn = document.getElementById("batch-analysis-run");
    runBtn.onclick = () => runBatchAnalysis(batchId, manifest);
}

function updateBatchAnalysisPickers(csvName) {
    const features = PLOT_FEATURES[csvName] || [];
    const featLabel = document.getElementById("batch-analysis-feature-label");
    const featSel = document.getElementById("batch-analysis-feature");
    const winLabel = document.getElementById("batch-analysis-window-label");

    if (features.length > 0) {
        featSel.innerHTML = features.map(f => `<option value="${f.value}">${f.label}</option>`).join("");
        featLabel.style.display = "";
    } else {
        featLabel.style.display = "none";
    }
    // Cars has no time axis — hide window picker.
    winLabel.style.display = (csvName === "cars.csv") ? "none" : "";
}

async function runBatchAnalysis(batchId, manifest) {
    const month = document.getElementById("batch-analysis-month").value;
    const csvName = document.getElementById("batch-analysis-csv").value;
    const winEl = document.getElementById("batch-analysis-window");
    const featEl = document.getElementById("batch-analysis-feature");
    const featLabelEl = document.getElementById("batch-analysis-feature-label");
    const win = (csvName === "cars.csv") ? "month" : winEl.value;
    const feature = (featLabelEl.style.display !== "none") ? featEl.value : null;
    const status = document.getElementById("batch-analysis-status");
    const plotDiv = document.getElementById("batch-analysis-plot");

    const samples = (manifest.samples || []).filter(s => s.month === month && s.status === "succeeded");
    if (!samples.length) {
        status.textContent = "no successful samples in this month";
        return;
    }
    status.innerHTML = `<span class="spinner"></span> fetching ${samples.length} samples…`;

    // Pass 1: fetch all samples, store filtered rows keyed by sample.
    const sampleRows = [];
    let fetched = 0;
    for (const s of samples) {
        try {
            const rows = await fetchAndParseCsv(
                `/api/batch/${batchId}/csv/${month}/${s.sample_idx}/${csvName}`
            );
            const filtered = filterByWindow(rows, win);
            if (filtered.length) sampleRows.push({ sample: s, rows: filtered });
            fetched++;
            status.innerHTML = `<span class="spinner"></span> fetched ${fetched}/${samples.length}`;
        } catch (e) {
            console.warn(`fetch failed for sample ${s.sample_idx}:`, e);
        }
    }
    if (!sampleRows.length) {
        status.textContent = "no plottable data";
        return;
    }

    // Pass 2: derive shared bin spec for histogram-style plots, then build traces.
    const isHistogram = histogramFeature(csvName, feature);
    let binSpec = null;
    if (isHistogram) {
        const allValues = [];
        for (const { rows } of sampleRows) {
            allValues.push(...extractFeatureValues(rows, csvName, feature));
        }
        if (allValues.length) {
            const lo = Math.min(...allValues);
            const hi = Math.max(...allValues);
            const nBins = (feature === "arrival_hour" || feature === "departure_hour") ? HOUR_BINS : HIST_BINS;
            // Float ULP nudge so the hi-edge sample lands in the last bin, not orphaned.
            const size = (hi - lo) / nBins || 1;
            binSpec = { start: lo, end: hi + size * 1e-6, size };
        }
    }

    const traces = [];
    for (const { sample: s, rows } of sampleRows) {
        traces.push(...buildOverlayTraces(csvName, rows, feature, s.sample_idx, s.seed, binSpec));
    }

    if (!traces.length) {
        status.textContent = "no plottable data";
        return;
    }
    plotDiv.style.display = "";
    const layout = batchPlotLayout(csvName, feature, month, sampleRows.length, win);
    Plotly.newPlot("batch-analysis-plot", traces, layout);
    const winNote = (csvName === "cars.csv") ? "" : ` (${win} window)`;
    const binNote = binSpec ? ` · bins=${binSpec.size.toExponential(2)}` : "";
    status.textContent = `${sampleRows.length} overlays plotted${winNote}${feature ? " · feature=" + feature : ""}${binNote}`;
}

function histogramFeature(csvName, feature) {
    if (csvName === "sessions.csv") return true;
    if (csvName === "cars.csv" && feature !== "battery_class") return true;
    return false;
}

function batchPlotLayout(csvName, feature, month, nSamples, win) {
    const showLegend = nSamples <= 10;
    const titleBase = feature
        ? `${csvName} — ${feature} — ${month}, ${nSamples} samples`
        : `${csvName} — ${month}, ${nSamples} samples (${win})`;
    if (csvName === "building_load.csv") {
        return { title: titleBase, margin: { t: 40, l: 60, r: 10, b: 40 }, showlegend: showLegend, yaxis: { title: "kW" } };
    }
    if (csvName === "grid_prices.csv") {
        return { title: titleBase, margin: { t: 40, l: 60, r: 10, b: 40 }, showlegend: showLegend, yaxis: { title: "$/kWh" } };
    }
    if (csvName === "cars.csv" && feature === "battery_class") {
        return { title: titleBase, margin: { t: 40, l: 60, r: 10, b: 50 }, showlegend: showLegend, barmode: "group", xaxis: { title: "battery class" }, yaxis: { title: "count" } };
    }
    // Numeric histogram overlay (sessions.csv features + cars numeric features).
    return {
        title: titleBase,
        margin: { t: 40, l: 60, r: 10, b: 50 },
        showlegend: showLegend,
        barmode: "overlay",
        xaxis: { title: feature || "" },
        yaxis: { title: "count" },
    };
}

function buildOverlayTraces(csvName, rows, feature, sampleIdx, seed, binSpec) {
    const cols = new Set(Object.keys(rows[0]));
    const tag = `s${sampleIdx} (seed=${seed})`;

    if (csvName === "building_load.csv") {
        const yCol = feature || "power_kw";
        if (!cols.has(yCol)) return [];
        return [{
            x: rows.map(r => r.datetime), y: rows.map(r => r[yCol]),
            name: tag, type: "scatter", mode: "lines",
            opacity: 0.6, line: { width: 1 },
        }];
    }
    if (csvName === "grid_prices.csv" && cols.has("price_per_kwh")) {
        return [{
            x: rows.map(r => r.datetime), y: rows.map(r => r.price_per_kwh),
            name: tag, type: "scatter", mode: "lines",
            opacity: 0.5, line: { width: 1 },
        }];
    }
    if (csvName === "sessions.csv") {
        const values = extractFeatureValues(rows, csvName, feature);
        if (!values.length) return [];
        const t = { x: values, type: "histogram", name: tag, opacity: 0.4 };
        if (binSpec) t.xbins = binSpec; else t.nbinsx = HIST_BINS;
        return [t];
    }
    if (csvName === "cars.csv") {
        if (feature === "battery_class") {
            const counts = {};
            rows.forEach(r => { counts[r.battery_class] = (counts[r.battery_class] || 0) + 1; });
            const cats = Object.keys(counts).sort();
            return [{
                x: cats, y: cats.map(c => counts[c]),
                type: "bar", name: tag, opacity: 0.85,
            }];
        }
        const values = extractFeatureValues(rows, csvName, feature);
        if (!values.length) return [];
        const t = { x: values, type: "histogram", name: tag, opacity: 0.45 };
        if (binSpec) t.xbins = binSpec; else t.nbinsx = HIST_BINS;
        return [t];
    }
    return [];
}

function extractFeatureValues(rows, csvName, feature) {
    if (csvName === "sessions.csv" && (feature === "arrival_hour" || feature === "departure_hour")) {
        const tsKey = feature === "arrival_hour" ? "arrival" : "departure";
        return rows.map(r => {
            const d = new Date(r[tsKey]);
            return isNaN(d) ? null : d.getHours() + d.getMinutes() / 60;
        }).filter(v => v !== null);
    }
    return rows.map(r => r[feature]).filter(v => typeof v === "number" && !isNaN(v));
}

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

async function cancelBatch() {
    if (!CURRENT_BATCH_ID) return;
    await fetch(`/api/batch/${CURRENT_BATCH_ID}/cancel`, { method: "POST" });
    if (BATCH_POLL_ID) clearTimeout(BATCH_POLL_ID);
    document.getElementById("status").textContent = `Batch ${CURRENT_BATCH_ID} cancelled.`;
    document.getElementById("generate-btn").disabled = false;
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

    const plotable = ["building_load.csv", "grid_prices.csv", "sessions.csv", "dr_events.csv", "cars.csv"].includes(name);
    if (plotable && summary.head.length > 0) {
        const features = PLOT_FEATURES[name] || [];
        const showWindow = ["building_load.csv", "grid_prices.csv", "sessions.csv", "dr_events.csv"].includes(name);
        const featureSelect = features.length > 0
            ? `<label>Feature:
                <select class="analysis-feature">
                    ${features.map(f => `<option value="${f.value}">${f.label}</option>`).join("")}
                </select>
               </label>`
            : "";
        const windowSelect = showWindow
            ? `<label>Window:
                <select class="analysis-window">
                    <option value="1day">1 day</option>
                    <option value="month" selected>Whole month</option>
                </select>
               </label>`
            : "";
        const ctrl = document.createElement("div");
        ctrl.className = "analysis-controls";
        ctrl.innerHTML = `
            ${featureSelect}
            ${windowSelect}
            <button type="button" class="analysis-run">Generate Analysis</button>
            <span class="analysis-status"></span>
        `;
        panel.appendChild(ctrl);
        const plotId = `plot-${name.replace(/\W/g, "_")}`;
        const plotDiv = document.createElement("div");
        plotDiv.id = plotId;
        plotDiv.style.height = "360px";
        plotDiv.style.display = "none";
        panel.appendChild(plotDiv);
        ctrl.querySelector(".analysis-run").addEventListener("click", () =>
            runSingleAnalysis(result.run_id, name, plotId, ctrl)
        );
    }

    panel.appendChild(buildTable(summary.head, summary.columns));
}

async function runSingleAnalysis(runId, csvName, plotId, ctrl) {
    const winEl = ctrl.querySelector(".analysis-window");
    const featEl = ctrl.querySelector(".analysis-feature");
    const win = winEl ? winEl.value : "month";
    const feature = featEl ? featEl.value : null;
    const status = ctrl.querySelector(".analysis-status");
    status.innerHTML = '<span class="spinner"></span> fetching…';
    let rows;
    try {
        rows = await fetchAndParseCsv(`/api/output/${runId}/${csvName}`);
    } catch (e) {
        status.textContent = "fetch failed: " + e.message;
        return;
    }
    const filtered = filterByWindow(rows, win);
    const featLabel = feature ? ` · feature=${feature}` : "";
    status.textContent = `${filtered.length} rows plotted (window=${win}${featLabel})`;
    document.getElementById(plotId).style.display = "";
    plotFullCsv(plotId, csvName, filtered, feature);
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

function filterByWindow(rows, win) {
    if (win === "month" || rows.length === 0) return rows;
    // 1day: pick rows where datetime/arrival falls on first day present
    const tsKey = ["datetime", "arrival", "event_start", "start"].find(k => k in rows[0]);
    if (!tsKey) return rows.slice(0, 96);  // fallback: first 96 rows (15-min × 24h)
    const firstDay = String(rows[0][tsKey]).slice(0, 10);
    return rows.filter(r => String(r[tsKey]).slice(0, 10) === firstDay);
}

function plotFullCsv(divId, csvName, rows, feature) {
    if (!rows.length) return;
    const cols = new Set(Object.keys(rows[0]));
    try {
        if (csvName === "building_load.csv" && cols.has("datetime") && cols.has("power_flex_kw")) {
            // If feature picked, plot only that series. Otherwise show all three (back-compat).
            let traces;
            if (feature && cols.has(feature)) {
                traces = [{ x: rows.map(r => r.datetime), y: rows.map(r => r[feature]), name: feature, type: "scatter", mode: "lines" }];
            } else {
                traces = [
                    { x: rows.map(r => r.datetime), y: rows.map(r => r.power_flex_kw), name: "flex", type: "scatter", mode: "lines" },
                    { x: rows.map(r => r.datetime), y: rows.map(r => r.power_inflex_kw), name: "inflex", type: "scatter", mode: "lines" },
                ];
                if (cols.has("power_kw")) {
                    traces.push({ x: rows.map(r => r.datetime), y: rows.map(r => r.power_kw), name: "total", type: "scatter", mode: "lines", line: { width: 2, dash: "dot" } });
                }
            }
            Plotly.newPlot(divId, traces, { title: "Building load", margin: { t: 30, l: 50, r: 10, b: 40 }, xaxis: { title: "" }, yaxis: { title: "kW" } });
            return;
        }
        if (csvName === "grid_prices.csv" && cols.has("datetime")) {
            const priceCol = ["price_per_kwh", "price", "energy_price"].find(c => cols.has(c));
            if (priceCol) {
                Plotly.newPlot(divId, [
                    { x: rows.map(r => r.datetime), y: rows.map(r => r[priceCol]), type: "scatter", mode: "lines" },
                ], { title: `Grid prices: ${priceCol}`, margin: { t: 30, l: 50, r: 10, b: 40 }, yaxis: { title: "$/kWh" } });
                return;
            }
        }
        if (csvName === "sessions.csv") {
            plotSessionsFeature(divId, rows, feature || "arrival_hour");
            return;
        }
        if (csvName === "cars.csv") {
            plotCarsFeature(divId, rows, feature || "capacity_kwh");
            return;
        }
        if (csvName === "dr_events.csv" && cols.has("event_start")) {
            Plotly.newPlot(divId, [
                { x: rows.map(r => r.event_start), y: rows.map((_, i) => i + 1), type: "scatter", mode: "markers" },
            ], { title: "DR events", margin: { t: 30, l: 50, r: 10, b: 40 } });
        }
    } catch (e) {
        console.warn("plot failed", e);
    }
}

function plotSessionsFeature(divId, rows, feature) {
    let values;
    let xLabel = feature;
    let nBins = 30;
    if (feature === "arrival_hour" || feature === "departure_hour") {
        const tsKey = feature === "arrival_hour" ? "arrival" : "departure";
        values = rows.map(r => {
            const d = new Date(r[tsKey]);
            return isNaN(d) ? null : d.getHours() + d.getMinutes() / 60;
        }).filter(v => v !== null);
        xLabel = `${feature.replace("_", " ")} (0-24)`;
        nBins = 24;
    } else {
        values = rows.map(r => r[feature]).filter(v => typeof v === "number" && !isNaN(v));
        if (feature === "duration_sec") xLabel = "duration (sec)";
        else if (feature === "arrival_soc") xLabel = "arrival SoC";
        else if (feature === "required_soc_at_depart") xLabel = "required SoC at depart";
        else if (feature === "previous_day_external_use_soc") xLabel = "previous-day external use SoC";
    }
    if (!values.length) return;
    Plotly.newPlot(divId, [
        { x: values, type: "histogram", nbinsx: nBins, marker: { color: "#1f4e79" } },
    ], {
        title: `sessions.csv — ${xLabel} distribution (n=${values.length})`,
        margin: { t: 40, l: 60, r: 10, b: 50 },
        xaxis: { title: xLabel },
        yaxis: { title: "count" },
    });
}

function plotCarsFeature(divId, rows, feature) {
    if (feature === "battery_class") {
        const counts = {};
        rows.forEach(r => {
            const c = r.battery_class;
            counts[c] = (counts[c] || 0) + 1;
        });
        const cats = Object.keys(counts).sort();
        Plotly.newPlot(divId, [{
            x: cats,
            y: cats.map(c => counts[c]),
            type: "bar",
            marker: { color: "#d8853b" },
        }], {
            title: `cars.csv — battery_class distribution (n=${rows.length})`,
            margin: { t: 40, l: 60, r: 10, b: 50 },
            xaxis: { title: "battery class" },
            yaxis: { title: "count" },
        });
        return;
    }
    const values = rows.map(r => r[feature]).filter(v => typeof v === "number" && !isNaN(v));
    if (!values.length) return;
    const labels = {
        capacity_kwh: "capacity (kWh)",
        min_allowed_soc: "min allowed SoC",
        max_allowed_soc: "max allowed SoC",
    };
    Plotly.newPlot(divId, [{
        x: values,
        type: "histogram",
        nbinsx: Math.min(20, new Set(values).size),
        marker: { color: "#1f4e79" },
    }], {
        title: `cars.csv — ${labels[feature] || feature} distribution (n=${values.length})`,
        margin: { t: 40, l: 60, r: 10, b: 50 },
        xaxis: { title: labels[feature] || feature },
        yaxis: { title: "count" },
    });
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
        if (csvName === "building_load.csv" && cols.has("datetime") && cols.has("power_flex_kw")) {
            const traces = [
                { x: head.map(r => r.datetime), y: head.map(r => r.power_flex_kw), name: "flex", type: "scatter", mode: "lines" },
                { x: head.map(r => r.datetime), y: head.map(r => r.power_inflex_kw), name: "inflex", type: "scatter", mode: "lines" },
            ];
            if (cols.has("power_kw")) {
                traces.push({ x: head.map(r => r.datetime), y: head.map(r => r.power_kw), name: "total", type: "scatter", mode: "lines", line: { width: 2, dash: "dot" } });
            }
            Plotly.newPlot(divId, traces, { title: "Building load (first 50 rows)", margin: { t: 30, l: 50, r: 10, b: 40 }, xaxis: { title: "" }, yaxis: { title: "kW" } });
            return;
        }
        if (csvName === "grid_prices.csv" && cols.has("datetime")) {
            const priceCol = ["price_per_kwh", "price", "energy_price"].find(c => cols.has(c));
            if (priceCol) {
                Plotly.newPlot(divId, [
                    { x: head.map(r => r.datetime), y: head.map(r => r[priceCol]), type: "scatter", mode: "lines+markers" },
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
