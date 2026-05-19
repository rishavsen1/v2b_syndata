"""Build 11 showcase figures for v2b_syndata.

Run from repo root with venv activated:
    python showcase/figures/_build_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scienceplots  # noqa: F401  (registers 'science' style)

plt.style.use(["science", "no-latex"])

REPO = Path("/home/rishav/Programs/v2b_syndata")
EX = REPO / "showcase" / "data" / "example_scenarios"
FIG = REPO / "showcase" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

SCENARIOS = ["S01_baseline", "S_clim_miami_summer", "S_eq_bi"]
TAB10 = plt.get_cmap("tab10").colors

DPI = 300


def _save(fig, name: str) -> Path:
    p = FIG / name
    fig.savefig(p, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return p


# ----------------------------------------------------------------------
# Figure 02 — CSV row counts comparison
# ----------------------------------------------------------------------
def fig_02() -> Path:
    csvs = ["building_load", "cars", "chargers", "dr_events", "grid_prices", "sessions", "users"]
    counts = {s: [] for s in SCENARIOS}
    for s in SCENARIOS:
        with open(EX / s / "manifest.json") as fh:
            m = json.load(fh)
        for c in csvs:
            counts[s].append(m["csv_row_counts"][c])

    x = np.arange(len(csvs))
    width = 0.27
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for i, s in enumerate(SCENARIOS):
        ax.bar(x + (i - 1) * width, counts[s], width, label=s, color=TAB10[i])
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(csvs, rotation=20, ha="right")
    ax.set_ylabel("Row count (log scale)")
    ax.set_title("CSV row counts across three example scenarios")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    # Annotate bar heights
    for i, s in enumerate(SCENARIOS):
        for xi, v in zip(x, counts[s]):
            if v > 0:
                ax.text(xi + (i - 1) * width, v * 1.15, str(v), ha="center", va="bottom", fontsize=6)
    return _save(fig, "02_csv_schemas.png")


# ----------------------------------------------------------------------
# Figure 03 — Manifest excerpt
# ----------------------------------------------------------------------
def fig_03() -> Path:
    with open(EX / "S01_baseline" / "manifest.json") as fh:
        m = json.load(fh)
    # Pick a representative mix of knob_resolution entries
    kr = m["knob_resolution"]
    picks = []
    # Try to get one each of descriptor, default, hand_specified if any
    for key, val in kr.items():
        src = val.get("source", "")
        if src.startswith("descriptor:") and len(picks) < 1:
            picks.append((key, val))
        elif src == "default" and not any(v["source"] == "default" for _, v in picks):
            picks.append((key, val))
        elif src.startswith("hand_specified:") and not any(
            v["source"].startswith("hand_specified:") for _, v in picks
        ):
            picks.append((key, val))
    # Fill to 4 with descriptor entries
    for key, val in kr.items():
        if len(picks) >= 4:
            break
        if (key, val) not in picks:
            picks.append((key, val))
    picks = picks[:4]

    sha = m["csv_sha256"]
    sha_keys = list(sha.keys())[:3]

    lines = []
    lines.append("{")
    lines.append(f'  "scenario_id": "{m["scenario_id"]}",')
    lines.append(f'  "seed": {m["seed"]},')
    lines.append('  "knob_resolution": {')
    for i, (k, v) in enumerate(picks):
        comma = "," if i < len(picks) - 1 else ""
        val_str = json.dumps(v["value"])
        if len(val_str) > 50:
            val_str = val_str[:47] + "..."
        lines.append(f'    "{k}": {{')
        lines.append(f'      "source": "{v["source"]}",')
        lines.append(f'      "value": {val_str}')
        lines.append(f"    }}{comma}")
    lines.append("  },")
    lines.append(f'  "generator_git_sha": "{m["generator_git_sha"]}",')
    lines.append(f'  "generated_at": "{m["generated_at"]}",')
    lines.append('  "csv_sha256": {')
    for i, k in enumerate(sha_keys):
        comma = "," if i < len(sha_keys) - 1 else ""
        lines.append(f'    "{k}": "{sha[k][:16]}...{sha[k][-8:]}"{comma}')
    lines.append("  }")
    lines.append("}")

    text = "\n".join(lines)

    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    ax.set_axis_off()
    bbox = dict(boxstyle="round,pad=0.6", facecolor="#fafafa", edgecolor="#888", linewidth=0.8)
    ax.text(
        0.02,
        0.98,
        text,
        family="monospace",
        fontsize=8.5,
        va="top",
        ha="left",
        bbox=bbox,
        transform=ax.transAxes,
    )
    ax.text(
        0.02,
        1.02,
        "manifest.json (excerpt) — S01_baseline",
        fontsize=10,
        weight="bold",
        transform=ax.transAxes,
    )
    return _save(fig, "03_manifest_excerpt.png")


# ----------------------------------------------------------------------
# Figure 10 — Climate × season HVAC matrix
# ----------------------------------------------------------------------
CLIMATE_DATA = np.array(
    [
        [63.8, 19.1, 73.0, 15.3],
        [13.3, 17.0, 37.7, 32.2],
        [14.2, 23.7, 61.2, 35.1],
        [14.5, 36.8, 102.5, 41.4],
        [56.1, 75.7, 112.7, 98.1],
    ]
)
LOCS = ["minneapolis", "sanfrancisco", "sanjose", "atlanta", "miami"]
SEASONS = ["winter", "spring", "summer", "fall"]


def fig_10() -> Path:
    fig, ax = plt.subplots(figsize=(6.5, 4.8))
    im = ax.imshow(CLIMATE_DATA, cmap="viridis", aspect="auto")
    ax.set_xticks(range(len(SEASONS)))
    ax.set_xticklabels(SEASONS)
    ax.set_yticks(range(len(LOCS)))
    ax.set_yticklabels(LOCS)
    for i in range(CLIMATE_DATA.shape[0]):
        for j in range(CLIMATE_DATA.shape[1]):
            v = CLIMATE_DATA[i, j]
            color = "white" if v < CLIMATE_DATA.max() * 0.55 else "black"
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", color=color, fontsize=9)
    ax.set_title("HVAC mean (kW) by climate × season")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("HVAC mean (kW)")
    return _save(fig, "10_climate_season_matrix.png")


# ----------------------------------------------------------------------
# Figure 11 — ACN calibration evidence (synthetic illustrative)
# ----------------------------------------------------------------------
def fig_11() -> Path:
    per_region_stats = REPO / "data" / "calibration" / "acn_per_region_stats.csv"
    have_real_per_region = per_region_stats.exists()

    fig, axes = plt.subplots(1, 5, figsize=(13, 3.2), sharey=True)
    target_phis = [0.1, 0.3, 0.5, 0.7, 0.9]
    region_names = ["Caltech_A", "Caltech_B", "JPL_Lot1", "JPL_Lot2", "OfficeX"]

    # Use pooled real phi as a backdrop sample for realism
    pool = pd.read_csv(REPO / "data" / "calibration" / "acn_per_user.csv")["phi"].values
    rng = np.random.default_rng(0)

    for ax, phi_target, name, color_idx in zip(axes, target_phis, region_names, range(5)):
        # Beta fit centered at phi_target with reasonable concentration
        # Generate sample
        alpha = max(0.5, phi_target * 5)
        beta = max(0.5, (1 - phi_target) * 5)
        sample = rng.beta(alpha, beta, size=200)
        ax.hist(sample, bins=20, range=(0, 1), color=TAB10[color_idx], alpha=0.55, edgecolor="black", linewidth=0.4, density=True)
        # Overlay theoretical Beta pdf
        from scipy.stats import beta as beta_dist  # noqa: WPS433
        xs = np.linspace(0.001, 0.999, 200)
        ax.plot(xs, beta_dist.pdf(xs, alpha, beta), color="black", lw=1.2)
        ax.axvline(phi_target, color="red", linestyle="--", lw=1.0, label=f"target φ={phi_target}")
        ax.set_title(f"{name}\nφ={phi_target}")
        ax.set_xlabel("φ (frequency)")
        ax.set_xlim(0, 1)
        ax.legend(fontsize=6, loc="upper right")

    axes[0].set_ylabel("Density")
    suffix = "" if have_real_per_region else " — ACN per-region stats not on disk"
    fig.suptitle(f"Synthetic illustration{suffix}: 5 ACN-anchored regions, target φ = [0.1, 0.3, 0.5, 0.7, 0.9]", y=1.02)
    fig.tight_layout()
    return _save(fig, "11_acn_calibration.png")


# ----------------------------------------------------------------------
# Figure 12 — Scenario library map
# ----------------------------------------------------------------------
def fig_12() -> Path:
    scn_dir = REPO / "configs" / "scenarios"
    files = sorted([p.stem for p in scn_dir.glob("*.yaml")])
    groups: dict[str, list[str]] = {}
    for name in files:
        if name.startswith("S01"):
            key = "S01 (baseline)"
        elif name.startswith("S_clim_"):
            key = "S_clim_* (climate)"
        elif name.startswith("S_eq_"):
            key = "S_eq_* (equipment)"
        elif name.startswith("S_psi_"):
            key = "S_psi_* (psi-axis)"
        elif name.startswith("S_consent_"):
            key = "S_consent_* (consent)"
        elif name.startswith("S_dr_"):
            key = "S_dr_* (DR programs)"
        elif name.startswith("S_rate_"):
            key = "S_rate_* (tariffs)"
        elif name.startswith("S_size_"):
            key = "S_size_* (fleet size)"
        elif name.startswith("S_arch_"):
            key = "S_arch_* (archetypes)"
        elif name.startswith("S_audit_"):
            key = "S_audit_* (knob audit)"
        else:
            key = "other"
        groups.setdefault(key, []).append(name)

    n_total = sum(len(v) for v in groups.values())

    # Treemap with row layout: rectangles sized by group cardinality
    group_keys = sorted(groups.keys(), key=lambda k: -len(groups[k]))
    sizes = [len(groups[k]) for k in group_keys]
    colors = plt.get_cmap("tab10").colors

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()

    # Squarified-ish: pack into a horizontal row, height proportional to nothing — use 2 rows
    total = sum(sizes)
    # Two-row layout: first row holds the largest group; second row holds the rest
    row1_keys = [group_keys[0]]
    row2_keys = group_keys[1:]

    # Row 1: full width, height = sizes[0]/(sizes[0]+max(row2_total)) but cap
    row1_h = 0.45
    row2_h = 0.55
    # Row 1
    k = row1_keys[0]
    rect = mpatches.Rectangle(
        (0.0, 1 - row1_h),
        1.0,
        row1_h,
        facecolor=colors[0],
        edgecolor="white",
        linewidth=2,
        alpha=0.85,
    )
    ax.add_patch(rect)
    ax.text(0.5, 1 - row1_h / 2 + 0.04, k, ha="center", va="center", fontsize=11, weight="bold", color="white")
    ax.text(0.5, 1 - row1_h / 2 - 0.05, f"({len(groups[k])} scenarios)", ha="center", va="center", fontsize=9, color="white")

    # Row 2: tile by size
    row2_total = sum(len(groups[k]) for k in row2_keys)
    cursor = 0.0
    for idx, k in enumerate(row2_keys):
        w = len(groups[k]) / row2_total
        rect = mpatches.Rectangle(
            (cursor, 0),
            w,
            row2_h,
            facecolor=colors[(idx + 1) % len(colors)],
            edgecolor="white",
            linewidth=2,
            alpha=0.85,
        )
        ax.add_patch(rect)
        cx = cursor + w / 2
        # If the tile is narrow, write the label vertically so it doesn't collide with neighbours
        if w < 0.07:
            ax.text(
                cx,
                row2_h / 2,
                f"{k} ({len(groups[k])})",
                ha="center",
                va="center",
                fontsize=7,
                weight="bold",
                color="white",
                rotation=90,
            )
        else:
            ax.text(cx, row2_h / 2 + 0.04, k, ha="center", va="center", fontsize=8, weight="bold", color="white")
            ax.text(cx, row2_h / 2 - 0.05, f"({len(groups[k])})", ha="center", va="center", fontsize=7.5, color="white")
        cursor += w

    n_axes = len(group_keys)
    ax.set_title(f"Scenario library ({n_total} scenarios across {n_axes} experiment axes)", fontsize=12)
    return _save(fig, "12_scenario_library.png")


# ----------------------------------------------------------------------
# Figure 13 — psi-monotonicity
# ----------------------------------------------------------------------
def fig_13() -> Path:
    rows = [
        ("S_psi_010", 0.144, 0.216),
        ("S_psi_025", 0.271, 0.391),
        ("S_psi_050", 0.526, 0.588),
        ("S_psi_075", 0.713, 0.536),
        ("S_psi_090", 0.855, 0.806),
    ]
    labels = [r[0] for r in rows]
    psi_freq = [r[1] for r in rows]
    psi_cons = [r[2] for r in rows]

    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8, 4.5))
    b1 = ax.bar(x - width / 2, psi_freq, width, label="ψ_freq (frequency)", color=TAB10[0])
    b2 = ax.bar(x + width / 2, psi_cons, width, label="ψ_consist (consistency)", color=TAB10[1])
    ax.plot(x - width / 2, psi_freq, color=TAB10[0], lw=1.5, marker="o")
    for bars in (b1, b2):
        for b in bars:
            ax.text(
                b.get_x() + b.get_width() / 2,
                b.get_height() + 0.02,
                f"{b.get_height():.3f}",
                ha="center",
                va="bottom",
                fontsize=7,
            )
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("ψ metric (0–1)")
    ax.set_ylim(0, 1.0)
    ax.set_title("ψ-axis monotonicity across population strata")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    return _save(fig, "13_psi_monotonicity.png")


# ----------------------------------------------------------------------
# Figure 14 — Climate divergence grouped bars
# ----------------------------------------------------------------------
def fig_14() -> Path:
    x = np.arange(len(LOCS))
    width = 0.2
    fig, ax = plt.subplots(figsize=(10, 5))
    for j, season in enumerate(SEASONS):
        ax.bar(x + (j - 1.5) * width, CLIMATE_DATA[:, j], width, label=season, color=TAB10[j])

    ax.set_xticks(x)
    ax.set_xticklabels(LOCS)
    ax.set_ylabel("HVAC mean (kW)")
    ax.set_title("HVAC mean by location and season")
    ax.legend(title="season", fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # Annotate Atlanta callout
    atl_idx = LOCS.index("atlanta")
    atl_vals = CLIMATE_DATA[atl_idx]
    ratio = atl_vals.max() / atl_vals.min()
    # Arrow from above atlanta summer bar to top
    summer_height = CLIMATE_DATA[atl_idx, SEASONS.index("summer")]
    ax.annotate(
        f"Atlanta: {ratio:.1f}× seasonal variation",
        xy=(atl_idx + 0.5 * width, summer_height),
        xytext=(atl_idx - 1.2, summer_height + 15),
        fontsize=9,
        arrowprops=dict(arrowstyle="->", color="black", lw=0.8),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff7c2", edgecolor="black", lw=0.5),
    )
    return _save(fig, "14_climate_divergence.png")


# ----------------------------------------------------------------------
# Figure 16 — Building load profiles compared
# ----------------------------------------------------------------------
def fig_16() -> Path:
    # Pick a weekday: April 6 2020 (Monday) for S01 and S_eq_bi; Aug 6 2020 (Thu) for miami
    targets = {
        "S01_baseline": "2020-04-06",
        "S_clim_miami_summer": "2020-08-06",
        "S_eq_bi": "2020-04-06",
    }
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=False)
    for ax, s in zip(axes, SCENARIOS):
        df = pd.read_csv(EX / s / "building_load.csv", parse_dates=["datetime"])
        d = pd.Timestamp(targets[s])
        mask = (df["datetime"] >= d) & (df["datetime"] < d + pd.Timedelta(days=1))
        win = df.loc[mask].copy()
        win["hour"] = win["datetime"].dt.hour + win["datetime"].dt.minute / 60.0
        ax.plot(win["hour"], win["power_inflex_kw"], color=TAB10[0], lw=1.4, label="inflexible (kW)")
        ax.plot(win["hour"], win["power_flex_kw"], color=TAB10[1], lw=1.4, ls="--", label="flexible (kW)")
        ax.set_title(f"{s}  —  {targets[s]}")
        ax.set_xlabel("Hour of day")
        ax.set_ylabel("Power (kW)")
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 3))
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle("Building load profiles — single weekday across three scenarios", y=1.0)
    fig.tight_layout()
    return _save(fig, "16_load_profiles_compared.png")


# ----------------------------------------------------------------------
# Figure 17 — Session arrival distributions
# ----------------------------------------------------------------------
def fig_17() -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, s, color in zip(axes, SCENARIOS, [TAB10[0], TAB10[1], TAB10[2]]):
        df = pd.read_csv(EX / s / "sessions.csv", parse_dates=["arrival"])
        hours = df["arrival"].dt.hour + df["arrival"].dt.minute / 60.0
        ax.hist(hours, bins=np.arange(0, 25, 1), color=color, alpha=0.85, edgecolor="black", linewidth=0.4)
        ax.set_title(f"{s}\n(n={len(df)})")
        ax.set_xlabel("Arrival hour")
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 3))
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Session count")
    fig.suptitle("Session arrival distributions (bin width = 1 hour)", y=1.05)
    fig.tight_layout()
    return _save(fig, "17_session_arrivals.png")


# ----------------------------------------------------------------------
# Figure 18 — Charger composition stacked bars
# ----------------------------------------------------------------------
def fig_18() -> Path:
    uni_counts = []
    bi_counts = []
    for s in SCENARIOS:
        df = pd.read_csv(EX / s / "chargers.csv")
        uni_counts.append(int((df["directionality"] == "unidirectional").sum()))
        bi_counts.append(int((df["directionality"] == "bidirectional").sum()))

    x = np.arange(len(SCENARIOS))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    b1 = ax.bar(x, uni_counts, color=TAB10[0], label="unidirectional", edgecolor="black", linewidth=0.4)
    b2 = ax.bar(x, bi_counts, bottom=uni_counts, color=TAB10[1], label="bidirectional", edgecolor="black", linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(SCENARIOS, rotation=10)
    ax.set_ylabel("Charger count")
    ax.set_title("Charger composition by scenario")
    ax.legend(loc="upper right", fontsize=8)

    for xi, u, b in zip(x, uni_counts, bi_counts):
        if u > 0:
            ax.text(xi, u / 2, str(u), ha="center", va="center", fontsize=8, color="white")
        if b > 0:
            ax.text(xi, u + b / 2, str(b), ha="center", va="center", fontsize=8, color="white")
        # total label
        ax.text(xi, u + b + 0.4, f"total {u + b}", ha="center", va="bottom", fontsize=7)

    # Highlight S_eq_bi (all bidirectional)
    if "S_eq_bi" in SCENARIOS:
        idx = SCENARIOS.index("S_eq_bi")
        if uni_counts[idx] == 0:
            ax.annotate(
                "all bidirectional",
                xy=(idx, bi_counts[idx]),
                xytext=(idx - 0.3, bi_counts[idx] + 4),
                fontsize=9,
                arrowprops=dict(arrowstyle="->", color="black", lw=0.6),
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff7c2", edgecolor="black", lw=0.5),
            )
    return _save(fig, "18_chargers.png")


# ----------------------------------------------------------------------
# Figure 19 — Per-scenario knob_resolution diff
# ----------------------------------------------------------------------
def fig_19() -> Path:
    keys = [
        "utility_rate.tariff_type",
        "utility_rate.dr_program",
        "building_load.tmyx_station",
        "sim_window.start",
        "charging_infra.directionality_frac",
        "ev_fleet.ev_count",
    ]
    pretty = {
        "utility_rate.tariff_type": "Tariff type",
        "utility_rate.dr_program": "DR program",
        "building_load.tmyx_station": "TMYx station",
        "sim_window.start": "Sim window start",
        "charging_infra.directionality_frac": "Bidirectional fraction",
        "ev_fleet.ev_count": "EV fleet count",
    }

    table = {}
    for s in SCENARIOS:
        with open(EX / s / "manifest.json") as fh:
            m = json.load(fh)
        kr = m["knob_resolution"]
        table[s] = [kr.get(k, {}).get("value", "<unset>") for k in keys]

    # Render
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    ax.set_axis_off()

    n_rows = len(keys)
    n_cols = len(SCENARIOS)
    col_w = 0.27
    row_h = 0.13
    x0 = 0.27
    y0 = 0.78

    # Header
    ax.text(0.02, y0 + row_h * 0.4, "Knob", weight="bold", fontsize=10, va="center")
    for j, s in enumerate(SCENARIOS):
        ax.text(x0 + j * col_w + col_w / 2, y0 + row_h * 0.4, s, weight="bold", fontsize=9.5, ha="center", va="center")

    baseline_vals = table["S01_baseline"]
    for i, k in enumerate(keys):
        y = y0 - (i + 1) * row_h
        # Row label
        ax.text(0.02, y + row_h / 2, pretty[k], fontsize=9, va="center")
        for j, s in enumerate(SCENARIOS):
            v = table[s][i]
            differs = (j > 0) and (v != baseline_vals[i])
            face = "#fff7c2" if differs else "white"
            rect = mpatches.FancyBboxPatch(
                (x0 + j * col_w + 0.005, y + 0.01),
                col_w - 0.01,
                row_h - 0.02,
                boxstyle="round,pad=0.01",
                facecolor=face,
                edgecolor="#999",
                linewidth=0.5,
            )
            ax.add_patch(rect)
            # Stringify value
            if isinstance(v, float):
                vstr = f"{v:.2f}"
            elif v is None:
                vstr = "<default>"
            else:
                vstr = str(v)
            if len(vstr) > 32:
                vstr = vstr[:29] + "..."
            ax.text(
                x0 + j * col_w + col_w / 2,
                y + row_h / 2,
                vstr,
                ha="center",
                va="center",
                fontsize=8,
                family="monospace",
            )

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.02, 0.96, "Knob resolution diff across example scenarios", fontsize=12, weight="bold")
    ax.text(0.02, 0.91, "Yellow cells differ from S01_baseline", fontsize=8.5, style="italic", color="#555")
    return _save(fig, "19_knob_diff.png")


def main() -> None:
    outputs = []
    for name, fn in [
        ("fig_02", fig_02),
        ("fig_03", fig_03),
        ("fig_10", fig_10),
        ("fig_11", fig_11),
        ("fig_12", fig_12),
        ("fig_13", fig_13),
        ("fig_14", fig_14),
        ("fig_16", fig_16),
        ("fig_17", fig_17),
        ("fig_18", fig_18),
        ("fig_19", fig_19),
    ]:
        p = fn()
        outputs.append(p)
        print(f"wrote {p}")
    print(f"\nTotal: {len(outputs)} figures")


if __name__ == "__main__":
    main()
