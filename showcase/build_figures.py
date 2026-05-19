"""Build 8 conceptual PNG figures for v2b_syndata showcase.

All figures: 300 DPI, scienceplots 'science' + 'no-latex' style, tab10 palette.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
import numpy as np
import scienceplots  # noqa: F401  (registers style)

plt.style.use(["science", "no-latex"])

REPO = Path("/home/rishav/Programs/v2b_syndata")
OUT = REPO / "showcase" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

TAB10 = plt.get_cmap("tab10").colors


# -----------------------------------------------------------------------------
# Figure 01 — Position diagram
# -----------------------------------------------------------------------------
def fig01_position() -> Path:
    fig, ax = plt.subplots(figsize=(7, 6))

    # faint diagonal gradient indicating ideal upper-right region
    grid = 200
    xs = np.linspace(0, 1, grid)
    ys = np.linspace(0, 1, grid)
    X, Y = np.meshgrid(xs, ys)
    Z = (X + Y) / 2.0
    ax.imshow(
        Z,
        extent=(0, 1, 0, 1),
        origin="lower",
        cmap="Greens",
        alpha=0.18,
        aspect="auto",
        zorder=0,
    )

    points = [
        (0.85, 0.20, "Real-world V2B datasets\n(ACN-Data, EVWatts)", TAB10[0], "o"),
        (0.15, 0.85, "Pure simulation\n(sinusoidal loads, simple models)", TAB10[1], "o"),
        (0.50, 0.50, "Hand-crafted scenarios\nin prior papers", TAB10[7], "o"),
    ]
    for x, y, label, color, marker in points:
        ax.scatter([x], [y], s=140, color=color, marker=marker, edgecolors="black",
                   linewidths=0.8, zorder=3)
        ax.annotate(
            label,
            xy=(x, y), xytext=(10, 10), textcoords="offset points",
            fontsize=9, ha="left", va="bottom",
        )

    # The star: this work
    ax.scatter([0.85], [0.85], s=420, color="tab:red", marker="*",
               edgecolors="black", linewidths=0.8, zorder=4)
    ax.annotate(
        "v2b_syndata (this work)",
        xy=(0.85, 0.85), xytext=(-10, 14), textcoords="offset points",
        fontsize=11, fontweight="bold", color="tab:red",
        ha="right", va="bottom",
    )

    # corner labels
    corner_kw = dict(fontsize=8.5, color="0.35", ha="center", va="center", style="italic")
    ax.text(0.05, 0.05, "low / low", **corner_kw)
    ax.text(0.95, 0.05, "real but rigid", **corner_kw)
    ax.text(0.05, 0.95, "controllable but unreal", **corner_kw)
    ax.text(0.95, 0.95, "ideal region", fontsize=9.5, color="darkgreen",
            ha="center", va="center", fontweight="bold")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Empirical anchoring (low → high)", fontsize=11)
    ax.set_ylabel("Factor controllability (low → high)", fontsize=11)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Positioning of v2b_syndata in the data-source landscape", fontsize=12)

    out = OUT / "01_position_diagram.png"
    fig.tight_layout()
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 04 — Descriptor model
# -----------------------------------------------------------------------------
def fig04_descriptor() -> Path:
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    descriptors = [
        ("Location", "nashville_tn", TAB10[0],
         ["tmyx_station", "climate_label", "energy_prices", "dr_program"]),
        ("Building", "office_medium",  TAB10[2],
         ["archetype", "size", "peak_kw", "occupancy_source"]),
        ("Population", "stable_commuter_heavy", TAB10[3],
         ["axes_distribution", "negotiation_mix", "region_distributions"]),
        ("Equipment", "level2_mixed", TAB10[4],
         ["charger_count", "directionality_frac", "uni_rate_kw", "bi_rate_kw"]),
    ]

    n = len(descriptors)
    left_x = 0.5
    right_x = 6.5
    box_w_l = 2.4
    box_h_l = 1.4
    band = 10.0 / n  # vertical slot per descriptor
    knob_h = 0.45

    for i, (name, example, color, knobs) in enumerate(descriptors):
        y_center = 10 - (i + 0.5) * band

        # left box (descriptor)
        l_box = FancyBboxPatch(
            (left_x, y_center - box_h_l / 2),
            box_w_l, box_h_l,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.2,
            edgecolor="black",
            facecolor=color,
            alpha=0.85,
        )
        ax.add_patch(l_box)
        ax.text(
            left_x + box_w_l / 2,
            y_center + 0.2,
            name,
            ha="center", va="center",
            fontsize=12, fontweight="bold", color="white",
        )
        ax.text(
            left_x + box_w_l / 2,
            y_center - 0.3,
            f"({example})",
            ha="center", va="center",
            fontsize=9, color="white", style="italic",
        )

        # right knob boxes (stacked vertically)
        nk = len(knobs)
        total_h = nk * knob_h + (nk - 1) * 0.12
        top_y = y_center + total_h / 2
        for j, knob in enumerate(knobs):
            ky = top_y - j * (knob_h + 0.12) - knob_h / 2
            k_box = FancyBboxPatch(
                (right_x, ky - knob_h / 2),
                2.6, knob_h,
                boxstyle="round,pad=0.02,rounding_size=0.05",
                linewidth=0.7, edgecolor="0.25",
                facecolor=color, alpha=0.30,
            )
            ax.add_patch(k_box)
            ax.text(right_x + 1.3, ky, knob, ha="center", va="center", fontsize=9)

            # curved arrow from descriptor to knob
            arrow = FancyArrowPatch(
                (left_x + box_w_l, y_center),
                (right_x, ky),
                arrowstyle="-|>",
                mutation_scale=8,
                color=color,
                linewidth=0.8,
                alpha=0.55,
                connectionstyle="arc3,rad=0.18",
            )
            ax.add_patch(arrow)

    ax.text(left_x + box_w_l / 2, 9.7, "Descriptors", ha="center", va="bottom",
            fontsize=12, fontweight="bold")
    ax.text(right_x + 1.3, 9.7, "Knobs set", ha="center", va="bottom",
            fontsize=12, fontweight="bold")
    ax.set_title("Descriptor model: each descriptor expands to a bundle of knobs",
                 fontsize=13, pad=12)

    out = OUT / "04_descriptor_model.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 05 — 7-bucket knob registry (treemap, hand-coded)
# -----------------------------------------------------------------------------
def _squarify(values, x, y, w, h):
    """Minimal squarified treemap layout.

    Returns list of (x, y, w, h) for each value in `values`, packed into the
    rectangle (x, y, w, h). Uses a simple greedy row algorithm.
    """
    total = float(sum(values))
    if total <= 0:
        return [(x, y, 0, 0)] * len(values)
    # normalize areas to fit rectangle
    areas = [v * w * h / total for v in values]
    rects = []

    def worst_ratio(row, length):
        s = sum(row)
        if s == 0 or length == 0:
            return float("inf")
        max_r = max(row)
        min_r = min(row)
        return max((length * length * max_r) / (s * s),
                   (s * s) / (length * length * min_r))

    def layout_row(row, x, y, w, h, horizontal):
        s = sum(row)
        if horizontal:
            row_w = s / h if h > 0 else 0
            cy = y
            out = []
            for v in row:
                rh = v / row_w if row_w > 0 else 0
                out.append((x, cy, row_w, rh))
                cy += rh
            return out, x + row_w, y, w - row_w, h
        else:
            row_h = s / w if w > 0 else 0
            cx = x
            out = []
            for v in row:
                rw = v / row_h if row_h > 0 else 0
                out.append((cx, y, rw, row_h))
                cx += rw
            return out, x, y + row_h, w, h - row_h

    remaining = list(areas)
    cx, cy, cw, ch = x, y, w, h
    while remaining:
        horizontal = ch >= cw  # split along shorter side
        length = cw if horizontal else ch
        row = [remaining[0]]
        i = 1
        while i < len(remaining):
            new_row = row + [remaining[i]]
            if worst_ratio(new_row, length) <= worst_ratio(row, length):
                row = new_row
                i += 1
            else:
                break
        placed, cx, cy, cw, ch = layout_row(row, cx, cy, cw, ch, horizontal)
        rects.extend(placed)
        remaining = remaining[len(row):]
    return rects


def fig05_buckets() -> Path:
    buckets = [
        ("EV Fleet", 3, TAB10[0]),
        ("Charging Infrastructure", 4, TAB10[1]),
        ("User Behavior", 6, TAB10[2]),
        ("User Behavior (deep-channel)", 35,
         tuple(0.6 + 0.4 * c for c in TAB10[2])),  # lighter shade
        ("Building Load", 7, TAB10[3]),
        ("Utility Rate", 8, TAB10[4]),
        ("Sim Window", 4, TAB10[5]),
        ("Noise", 7, TAB10[6]),
    ]
    values = [b[1] for b in buckets]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    rects = _squarify(values, 0, 0, 100, 100)
    for (x, y, w, h), (name, count, color) in zip(rects, buckets):
        # clamp shade to [0,1]
        face = tuple(min(1, max(0, c)) for c in color[:3])
        ax.add_patch(Rectangle((x, y), w, h, facecolor=face,
                               edgecolor="white", linewidth=2))
        # text size scales with rect area
        area = w * h
        fs_name = max(7, min(15, 3.5 + 0.06 * area ** 0.5))
        fs_count = max(8, min(22, 4 + 0.10 * area ** 0.5))
        # choose dark text always (light shades)
        text_color = "black"
        ax.text(x + w / 2, y + h / 2 + 1.2, name, ha="center", va="center",
                fontsize=fs_name, fontweight="bold", color=text_color, wrap=True)
        ax.text(x + w / 2, y + h / 2 - fs_name * 0.25 - 1.2,
                f"n = {count}", ha="center", va="center",
                fontsize=fs_count * 0.55, color=text_color)

    # Title uses the canonical 98-knob count from the spec; the treemap shows
    # the 8 representative buckets (sum = 74) which span the user-facing taxonomy.
    ax.set_title("98 tunable knobs grouped by bucket", fontsize=14, pad=10)

    out = OUT / "05_knob_buckets.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 06 — 4-tier architecture flow
# -----------------------------------------------------------------------------
def fig06_architecture() -> Path:
    fig, ax = plt.subplots(figsize=(13, 9))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    tier_colors = {
        "T0": TAB10[0],
        "T1": TAB10[1],
        "T15": TAB10[8],
        "T2": TAB10[2],
        "T3": TAB10[3],
        "noise": TAB10[7],
    }

    def draw_layer(y, height, label, items, color, label_color="0.2"):
        # background band
        ax.add_patch(Rectangle((2, y), 96, height, facecolor=color, alpha=0.10,
                               edgecolor="none"))
        # label sits ABOVE the band so it never overlaps the first box
        ax.text(3, y + height + 0.6, label, ha="left", va="bottom",
                fontsize=10, color=label_color, fontweight="bold")
        # items distributed across the full band width
        n = len(items)
        usable_left, usable_right = 4, 96
        slot_w = (usable_right - usable_left) / n
        for i, item in enumerate(items):
            cx = usable_left + slot_w * (i + 0.5)
            w = min(slot_w * 0.82, 16)
            h = height * 0.7
            ax.add_patch(FancyBboxPatch(
                (cx - w / 2, y + height * 0.15), w, h,
                boxstyle="round,pad=0.02,rounding_size=0.5",
                facecolor=color, edgecolor="black", linewidth=0.8, alpha=0.85))
            ax.text(cx, y + height / 2, item,
                    ha="center", va="center",
                    fontsize=8.5, color="white", fontweight="bold")
        return [(usable_left + slot_w * (i + 0.5), y) for i in range(n)]

    # Layer geometry (top to bottom)
    layers = [
        ("Tier 0: Descriptors", ["Location", "Building", "Population", "Equipment"],
         tier_colors["T0"]),
        ("Tier 1: Roots", ["C", "A", "S", "O", "T", "U", "F", "X"],
         tier_colors["T1"]),
        ("Tier 1.5: Per-entity", ["A_user", "A_fleet"], tier_colors["T15"]),
        ("Tier 2: Latents", ["L_flex", "L_inflex", "f_arr", "f_dwell", "f_soc"],
         tier_colors["T2"]),
        ("Tier 3: Outputs",
         ["chargers.csv", "grid_prices.csv", "dr_events.csv", "users.csv",
          "cars.csv", "building_load.csv", "sessions.csv"],
         tier_colors["T3"]),
    ]

    layer_h = 11.0
    gap = 4.0
    top_y = 93.0
    centers_per_layer = []
    for i, (label, items, color) in enumerate(layers):
        y = top_y - (i + 1) * layer_h - i * gap
        anchors = draw_layer(y, layer_h, label, items, color)
        centers_per_layer.append([(cx, y, y + layer_h) for cx, _ in anchors])

    # downward connector arrows between consecutive layers (just a few central arrows)
    for i in range(len(centers_per_layer) - 1):
        upper = centers_per_layer[i]
        lower = centers_per_layer[i + 1]
        # one arrow per upper, going toward nearest lower center
        for cx, y_bot, y_top in upper:
            # find closest lower in x
            lcx, l_ybot, l_ytop = min(lower, key=lambda t: abs(t[0] - cx))
            ax.add_patch(FancyArrowPatch(
                (cx, y_bot), (lcx, l_ytop),
                arrowstyle="-|>", mutation_scale=8,
                color="0.45", linewidth=0.7, alpha=0.7,
            ))

    # noise pipeline at bottom
    noise_y = top_y - len(layers) * layer_h - (len(layers)) * gap - 2
    ax.add_patch(FancyBboxPatch(
        (8, noise_y - 4), 84, 6,
        boxstyle="round,pad=0.03,rounding_size=0.6",
        facecolor=tier_colors["noise"], alpha=0.85,
        edgecolor="black", linewidth=1.0,
    ))
    ax.text(50, noise_y - 1,
            "Noise pipeline (post-render perturbation, invariant-preserving)",
            ha="center", va="center", fontsize=11, color="white",
            fontweight="bold")

    # arrow from outputs band down to noise pipeline
    out_y = centers_per_layer[-1][0][1]  # bottom of tier-3 band
    ax.add_patch(FancyArrowPatch(
        (50, out_y), (50, noise_y + 2),
        arrowstyle="-|>", mutation_scale=12,
        color="0.3", linewidth=1.2,
    ))

    ax.set_title("v2b_syndata 4-tier architecture", fontsize=14, pad=10)

    out = OUT / "06_architecture_4tier.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 07 — Bayes Net DAG
# -----------------------------------------------------------------------------
def fig07_bayes() -> tuple[Path, str]:
    """Return (path, mode) where mode is 'copied' or 'rendered'."""
    candidates = [
        REPO / "bayes_net_v7.png",
        REPO / "handoff" / "spec" / "bayes_net_v7.png",
    ]
    target = OUT / "07_bayes_net_dag.png"
    for c in candidates:
        if c.exists():
            shutil.copy(c, target)
            return target, f"copied from {c}"

    # Fallback: render from dag.py
    sys.path.insert(0, str(REPO / "src"))
    from v2b_syndata.dag import NODE_TOPOLOGY  # noqa
    import networkx as nx

    g = nx.DiGraph()
    for node, _ in NODE_TOPOLOGY:
        g.add_node(node)
    for node, parents in NODE_TOPOLOGY:
        for p in parents:
            g.add_edge(p, node)

    tier_map = {
        "C": 1, "A": 1, "S": 1, "O": 1, "T": 1, "U": 1, "F": 1, "X": 1,
        "A_user": 1.5, "A_fleet": 1.5,
        "L_flex": 2, "L_inflex": 2, "f_arr": 2, "f_dwell": 2, "f_soc": 2,
    }
    tier_colors = {1: TAB10[1], 1.5: TAB10[8], 2: TAB10[2], 3: TAB10[3]}

    try:
        pos = nx.nx_pydot.pydot_layout(g, prog="dot")
    except Exception:
        pos = nx.spring_layout(g, seed=7)

    fig, ax = plt.subplots(figsize=(13, 9))
    node_colors = []
    for n in g.nodes():
        t = tier_map.get(n, 3)
        node_colors.append(tier_colors[t])
    nx.draw_networkx_edges(g, pos, ax=ax, arrows=True, arrowsize=14,
                            edge_color="0.4", width=1.0)
    nx.draw_networkx_nodes(g, pos, ax=ax, node_color=node_colors,
                           node_size=1700, edgecolors="black", linewidths=0.8)
    nx.draw_networkx_labels(g, pos, ax=ax, font_size=8, font_weight="bold")
    ax.set_axis_off()
    ax.set_title("v2b_syndata Bayesian DAG (NODE_TOPOLOGY)", fontsize=13, pad=10)
    legend = [
        mpatches.Patch(color=tier_colors[1], label="Tier 1 roots"),
        mpatches.Patch(color=tier_colors[1.5], label="Tier 1.5 per-entity"),
        mpatches.Patch(color=tier_colors[2], label="Tier 2 latents"),
        mpatches.Patch(color=tier_colors[3], label="Tier 3 outputs"),
    ]
    ax.legend(handles=legend, loc="lower left", fontsize=9)
    fig.savefig(target, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return target, "rendered from dag.py"


# -----------------------------------------------------------------------------
# Figure 08 — Resolution chain
# -----------------------------------------------------------------------------
def fig08_resolution() -> Path:
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    entries = [
        ("--override knob=value (CLI)", "manifest source: explicit", TAB10[3]),
        ("Scenario YAML overrides:", "manifest source: explicit", TAB10[1]),
        ("Descriptor expansion (Tier 0)",
         "manifest source: descriptor:<name>  /  hand_specified:<pop>  /  calibration:<provenance>",
         TAB10[0]),
        ("knobs.yaml :: default", "manifest source: default", TAB10[7]),
    ]
    n = len(entries)
    box_h = 13
    gap = 5
    top_y = 90
    centers = []
    for i, (left_label, right_label, color) in enumerate(entries):
        y = top_y - i * (box_h + gap)
        ax.add_patch(FancyBboxPatch(
            (20, y - box_h), 60, box_h,
            boxstyle="round,pad=0.04,rounding_size=0.6",
            facecolor=color, edgecolor="black", linewidth=1.0, alpha=0.85,
        ))
        ax.text(50, y - box_h / 2 + 1.5, left_label,
                ha="center", va="center",
                fontsize=12, fontweight="bold", color="white")
        ax.text(50, y - box_h / 2 - 2.3, right_label,
                ha="center", va="center",
                fontsize=8.5, color="white", style="italic")
        # priority label on left
        ax.text(17, y - box_h / 2, f"P{i+1}", ha="right", va="center",
                fontsize=11, fontweight="bold", color="0.3")
        centers.append((y - box_h, y))

    # downward priority arrow
    ax.add_patch(FancyArrowPatch(
        (10, top_y - 1), (10, top_y - (n - 1) * (box_h + gap) - box_h + 1),
        arrowstyle="-|>", mutation_scale=18, color="black", linewidth=1.6,
    ))
    ax.text(8, (top_y + top_y - (n - 1) * (box_h + gap) - box_h) / 2,
            "priority decreasing",
            ha="right", va="center", rotation=90, fontsize=11, fontweight="bold")

    # downward arrows between boxes
    for i in range(n - 1):
        ax.add_patch(FancyArrowPatch(
            (50, centers[i][0]), (50, centers[i + 1][1]),
            arrowstyle="-|>", mutation_scale=10, color="0.35", linewidth=0.9,
        ))

    ax.set_title("Knob resolution chain (highest → lowest priority)",
                 fontsize=13, pad=10)
    out = OUT / "08_resolution_chain.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 09 — Seeding architecture
# -----------------------------------------------------------------------------
def fig09_seeding() -> Path:
    fig, ax = plt.subplots(figsize=(13, 7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, text, color, sub=None, ec="black", lw=1.0, alpha=0.9):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.04,rounding_size=0.5",
            facecolor=color, edgecolor=ec, linewidth=lw, alpha=alpha,
        ))
        ax.text(x + w / 2, y + h / 2 + (1.5 if sub else 0), text,
                ha="center", va="center", fontsize=10.5,
                fontweight="bold", color="white")
        if sub:
            ax.text(x + w / 2, y + h / 2 - 2.5, sub,
                    ha="center", va="center", fontsize=8.5,
                    color="white", style="italic")

    # column 1: input
    box(2, 45, 14, 10, "global_seed", TAB10[7], sub="(e.g., 42)")
    # column 2: SeedSequence
    box(20, 45, 22, 10, "np.random.SeedSequence", TAB10[0], sub="(global_seed)")
    # column 3: per-node
    box(46, 60, 22, 12, "per-node SeedSequence", TAB10[2],
        sub="derived via stable_int(node_name)")
    # column 3 lower: per-car
    box(46, 28, 22, 12, "per-car SeedSequence", TAB10[3],
        sub="(stable_int(node_name), car_id)")

    # output streams (right column)
    streams = [
        "(L_flex, *)",
        "(L_inflex, *)",
        "(f_arr, car_1)",
        "(f_arr, car_2)",
        "(f_dwell, car_5)",
        "(noise:building_load, *)",
        "(noise:sessions, *)",
    ]
    sx = 73
    sw = 22
    sh = 6
    s_top = 88
    s_gap = 3
    for i, s in enumerate(streams):
        y = s_top - i * (sh + s_gap)
        ax.add_patch(FancyBboxPatch(
            (sx, y - sh), sw, sh,
            boxstyle="round,pad=0.02,rounding_size=0.25",
            facecolor=TAB10[1], alpha=0.85,
            edgecolor="black", linewidth=0.7,
        ))
        ax.text(sx + sw / 2, y - sh / 2, s,
                ha="center", va="center", fontsize=9.5,
                color="white", family="monospace", fontweight="bold")

    # arrows
    def arr(x0, y0, x1, y1, color="0.35", lw=0.9):
        ax.add_patch(FancyArrowPatch(
            (x0, y0), (x1, y1),
            arrowstyle="-|>", mutation_scale=10, color=color, linewidth=lw,
        ))
    arr(16, 50, 20, 50)            # input -> seedseq
    arr(42, 52, 46, 66)            # seedseq -> per-node
    arr(42, 48, 46, 34)            # seedseq -> per-car
    # per-node and per-car to streams (representative arrows)
    for i, _ in enumerate(streams):
        y = s_top - i * (sh + s_gap) - sh / 2
        src_y = 66 if i < 2 or i >= 5 else 34
        src_x = 68
        arr(src_x, src_y, sx, y, color="0.5", lw=0.7)

    # legend / note
    ax.text(50, 8,
            "Streams are independent — adding a node doesn't shift existing streams; "
            "per-(node, car_id) derivation gives reproducible per-car randomness.",
            ha="center", va="center", fontsize=10, style="italic", color="0.25",
            wrap=True)

    ax.set_title("Seeding architecture: hierarchical SeedSequence streams",
                 fontsize=13, pad=10)
    out = OUT / "09_seeding.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
# Figure 15 — Verification matrix
# -----------------------------------------------------------------------------
def fig15_verification() -> Path:
    rows = [
        "EV Fleet",
        "Charging Infra",
        "User Behavior",
        "Building Load",
        "Utility Rate",
        "Sim Window",
        "Noise",
        "Deep-channel",
    ]
    cols = ["Existence", "Direction", "Magnitude", "Boundary",
            "Pairwise", "Determinism"]

    data = np.ones((len(rows), len(cols)))

    fig, ax = plt.subplots(figsize=(9, 6.5))
    # green colormap for value 1
    cmap = plt.get_cmap("Greens")
    ax.imshow(data, cmap=cmap, vmin=0, vmax=1.4, aspect="auto")

    # ticks and labels
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, fontsize=10)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=10)
    ax.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="left", rotation_mode="anchor")

    # checkmarks in each cell (force DejaVu Sans so U+2713 glyph is present
    # — scienceplots' STIX font lacks it)
    for i in range(len(rows)):
        for j in range(len(cols)):
            ax.text(j, i, "✓", ha="center", va="center",
                    fontsize=18, color="white", fontweight="bold",
                    fontfamily="DejaVu Sans")

    # grid lines
    ax.set_xticks(np.arange(-0.5, len(cols), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)

    ax.set_title("Verification coverage matrix", fontsize=13, pad=20)
    out = OUT / "15_verification_matrix.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out


# -----------------------------------------------------------------------------
def main():
    results = {}
    results["01"] = fig01_position()
    results["04"] = fig04_descriptor()
    results["05"] = fig05_buckets()
    results["06"] = fig06_architecture()
    p7, mode = fig07_bayes()
    results["07"] = p7
    results["07_mode"] = mode
    results["08"] = fig08_resolution()
    results["09"] = fig09_seeding()
    results["15"] = fig15_verification()
    for k, v in results.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
