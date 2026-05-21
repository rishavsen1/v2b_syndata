"""Generate the 3 figures for the short overview (Word doc + Marp deck)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

BLUE = "#1f4e79"
ORANGE = "#d8853b"
LIGHT = "#f5f5f5"
GREY = "#666666"
INK = "#222222"

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["font.size"] = 11

FIG_DIR = Path(__file__).parent / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def _box(ax, x, y, w, h, text, *, face=LIGHT, edge=BLUE, lw=2.0,
         fontsize=11, fontweight="normal", color=INK, ha="center", va="center",
         rounding=0.04):
    """Rounded rectangle with centered text."""
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={rounding}",
        linewidth=lw, edgecolor=edge, facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text,
            ha=ha, va=va, fontsize=fontsize,
            fontweight=fontweight, color=color, wrap=True)


def _arrow(ax, x0, y0, x1, y1, *, color=BLUE, lw=2.0, style="->", curved=False):
    if curved:
        cs = "arc3,rad=0.25"
    else:
        cs = "arc3,rad=0.0"
    a = FancyArrowPatch(
        (x0, y0), (x1, y1),
        arrowstyle=style, mutation_scale=18,
        color=color, linewidth=lw, connectionstyle=cs,
    )
    ax.add_patch(a)


def _clean(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


# ---------------------------------------------------------------------------
# Figure 1: three CSV DAG
# ---------------------------------------------------------------------------

def fig_three_csvs_dag():
    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=160)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.625)
    _clean(ax)

    # title
    ax.text(5, 5.25, "The three CSVs — generated in order",
            ha="center", va="center", fontsize=17,
            color=BLUE, fontweight="bold")

    # boxes
    box_w, box_h = 3.0, 1.4
    cx = 5.0
    y_users = 3.55
    y_cars = 1.95
    y_sess = 0.35

    _box(ax, cx - box_w / 2, y_users, box_w, box_h,
         "users.csv\n— per-car behavior —\nφ  κ  δ\nnegotiation_type, w1, w2",
         face="#eaf2fb", edge=BLUE, fontsize=11, fontweight="bold")

    _box(ax, cx - box_w / 2, y_cars, box_w, box_h,
         "cars.csv\n— per-car physics —\nbattery_class, capacity_kwh\nmin/max_allowed_soc",
         face="#eaf2fb", edge=BLUE, fontsize=11, fontweight="bold")

    _box(ax, cx - box_w / 2, y_sess, box_w, box_h,
         "sessions.csv\n— per-day arrivals —\narrival, dwell, SoC\nrequired_soc",
         face="#eaf2fb", edge=BLUE, fontsize=11, fontweight="bold")

    # arrows
    _arrow(ax, cx, y_users, cx, y_cars + box_h, lw=2.3)
    _arrow(ax, cx, y_cars, cx, y_sess + box_h, lw=2.3)

    # side captions
    ax.text(cx + box_w / 2 + 0.3, y_users + box_h / 2 - 0.55, "1 row per car_id",
            fontsize=10, color=GREY, va="center")
    ax.text(cx + box_w / 2 + 0.3, y_cars + box_h / 2 - 0.55, "1 row per car_id",
            fontsize=10, color=GREY, va="center")
    ax.text(cx + box_w / 2 + 0.3, y_sess + box_h / 2 - 0.55, "0..N rows per car_id\nover sim window",
            fontsize=10, color=GREY, va="center")

    # legend / accent note
    ax.text(0.4, 0.2,
            "users first → cars next → sessions last",
            color=ORANGE, fontsize=12, fontweight="bold")

    plt.tight_layout()
    out = FIG_DIR / "01_three_csvs_dag.png"
    plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# Figure 2: sessions.csv 10-step pipeline
# ---------------------------------------------------------------------------

def fig_sessions_pipeline():
    fig, ax = plt.subplots(figsize=(15.0, 9.0), dpi=170)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9.8)
    _clean(ax)

    ax.text(8, 9.45, "sessions.csv — 10-step generation pipeline",
            ha="center", va="center", fontsize=22, color=BLUE, fontweight="bold")
    ax.text(8, 9.00, "for each car_id × each weekday in sim_window  (rejection sampling, max 8 retries)",
            ha="center", va="center", fontsize=13, color=GREY, style="italic")

    # 10 steps - 2 columns x 5 rows; column-major flow (down col 1, then down col 2)
    steps = [
        ("1. Resolve region",         "from users.csv",                              False),
        ("2. Attendance gate",        "Bernoulli(φ) → skip if fail",                 True),
        ("3. Copula sample",          "(arrival, dwell) ~ Gauss copula\nTruncNorm × Weibull marginals",  True),
        ("4. Snap arrival",           "to 15-min grid",                              False),
        ("5. Arrival SoC",            "Beta(α, β) + shift_eff\nshift_eff = shift − 0.003·δ", True),
        ("6. Required SoC",           "TruncNorm(85, 5)\nclamped to bounds",         False),
        ("7. D5 reachability",        "energy_needed ≤ max_charge ?\nretry step 3 if no",  False),
        ("8. Floor duration",         "to 15-min multiples",                         False),
        ("9. Non-overlap (C7)",       "drop if overlaps prior\nsession for car_id",  False),
        ("10. Track external SoC",    "SoC delta since last\nbuilding session",      False),
    ]

    box_w, box_h = 6.0, 1.30
    x_left, x_right = 0.30, 9.70
    y_top = 7.55
    dy = 1.55  # vertical step

    positions = []
    for i, (title, body, has_axis) in enumerate(steps):
        col = i // 5            # 0 = left, 1 = right
        row = i %  5            # 0..4 down
        x = x_left if col == 0 else x_right
        y = y_top - row * dy
        positions.append((x, y, x + box_w / 2, y + box_h / 2))
        face = "#fff3e0" if has_axis else "#eaf2fb"
        edge = ORANGE if has_axis else BLUE

        _box(ax, x, y, box_w, box_h, "", face=face, edge=edge, lw=2.0)
        ax.text(x + 0.25, y + box_h - 0.32, title,
                fontsize=15, fontweight="bold",
                color="#a85a14" if has_axis else BLUE,
                ha="left", va="top")
        ax.text(x + 0.25, y + box_h - 0.66, body,
                fontsize=12.5, color=INK, ha="left", va="top",
                family="monospace")

    # arrows: 1→2→3→4→5 (down left col), 5→6 (cross to top of right col), 6→7→8→9→10 (down right col)
    for i in range(9):
        sx, sy, scx, scy = positions[i]
        tx, ty, tcx, tcy = positions[i + 1]
        if i == 4:  # 5 → 6  cross columns
            _arrow(ax, sx + box_w, scy, tx, tcy, lw=2.0, color=GREY)
        else:       # straight down within column
            _arrow(ax, scx, sy + 0.02, tcx, ty + box_h - 0.02,
                   lw=1.8, color=GREY)

    # retry arrow: 7 -> 3 (dashed orange)
    s7 = positions[6]
    s3 = positions[2]
    arrow = FancyArrowPatch(
        (s7[0], s7[3]),  # left edge midpoint of step 7
        (s3[0] + box_w, s3[3]),  # right edge midpoint of step 3
        arrowstyle="->", mutation_scale=20, color=ORANGE,
        linewidth=2.3, linestyle="dashed",
        connectionstyle="arc3,rad=-0.55",
    )
    ax.add_patch(arrow)
    ax.text(8.0, 5.85, "retry (≤ 8×)\nif D5 fails",
            color=ORANGE, fontsize=13, fontweight="bold", ha="center")

    # legend
    leg_orange = mpatches.Patch(facecolor="#fff3e0", edgecolor=ORANGE,
                                label="φ / κ / δ enters here")
    leg_blue = mpatches.Patch(facecolor="#eaf2fb", edgecolor=BLUE,
                              label="deterministic step")
    ax.legend(handles=[leg_orange, leg_blue], loc="lower center",
              frameon=False, fontsize=13, ncol=2,
              bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    out = FIG_DIR / "02_sessions_pipeline.png"
    plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# Figure 3: worked example
# ---------------------------------------------------------------------------

def fig_worked_example():
    fig, ax = plt.subplots(figsize=(15.0, 8.25), dpi=170)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    _clean(ax)

    ax.text(8, 8.65, "Worked example — car_id = 42, day = 2024-04-08 (Mon)",
            ha="center", va="center", fontsize=20, color=BLUE, fontweight="bold")

    # 3 columns
    col_w = 4.85
    col_gap = 0.45
    x0 = 0.30
    x1 = x0 + col_w + col_gap
    x2 = x1 + col_w + col_gap

    # header strip
    headers = [(x0, "users.csv  +  cars.csv", BLUE),
               (x1, "step-by-step computation", ORANGE),
               (x2, "sessions.csv row emitted", BLUE)]
    for x, txt, c in headers:
        _box(ax, x, 7.65, col_w, 0.55, txt, face=c, edge=c,
             color="white", fontsize=15, fontweight="bold")

    # column 1: users + cars
    users_lines = [
        ("region", "flexible_local"),
        ("φ (phi)", "0.84"),
        ("κ (kappa)", "0.62"),
        ("δ (delta_km)", "12.4 km"),
        ("negotiation_type", "II (balanced)"),
        ("w1, w2", "0.71, 0.48"),
    ]
    cars_lines = [
        ("battery_class", "bolt_40"),
        ("capacity_kwh", "40"),
        ("min/max_soc", "10 / 100"),
    ]

    # users sub-block
    _box(ax, x0, 4.40, col_w, 3.05, "", face="#eaf2fb", edge=BLUE, lw=1.8)
    ax.text(x0 + 0.22, 7.25, "users.csv (row)", fontsize=14,
            fontweight="bold", color=BLUE, va="top")
    for i, (k, v) in enumerate(users_lines):
        y = 6.85 - i * 0.40
        ax.text(x0 + 0.30, y, k, fontsize=12.5, color=INK, va="top",
                family="monospace")
        ax.text(x0 + col_w - 0.25, y, v, fontsize=12.5, color=INK,
                va="top", ha="right", fontweight="bold", family="monospace")

    # cars sub-block
    _box(ax, x0, 2.55, col_w, 1.70, "", face="#eaf2fb", edge=BLUE, lw=1.8)
    ax.text(x0 + 0.22, 4.05, "cars.csv (row)", fontsize=14,
            fontweight="bold", color=BLUE, va="top")
    for i, (k, v) in enumerate(cars_lines):
        y = 3.66 - i * 0.40
        ax.text(x0 + 0.30, y, k, fontsize=12.5, color=INK, va="top",
                family="monospace")
        ax.text(x0 + col_w - 0.25, y, v, fontsize=12.5, color=INK,
                va="top", ha="right", fontweight="bold", family="monospace")

    # region distributions hint
    ax.text(x0 + 0.22, 2.30,
            "region → f_arr = TruncNorm(9.5, σ=1.5)\n"
            "          f_dwell = Weibull(1.8, 6.5)\n"
            "          f_soc = Beta(5, 5), shift=0\n"
            "          ρ = −0.2  (Gauss copula)",
            fontsize=11, family="monospace", color=GREY, va="top")

    # column 2: computation
    _box(ax, x1, 0.55, col_w, 6.90, "", face="#fff3e0", edge=ORANGE, lw=1.8)
    comp_lines = [
        ("1. Attendance gate", "draw=0.31 < φ=0.84 → go"),
        ("2. Copula sample",   "σ_eff = 1.5·(1−0.62·0.5) = 1.035"),
        ("",                   "u = (−0.42, 0.18)"),
        ("",                   "arrival = 9.18 h   dwell = 7.6 h"),
        ("3. Snap to grid",    "arrival = 09:15"),
        ("4. Arrival SoC",     "shift_eff = −0.003·12.4 = −0.037"),
        ("",                   "Beta(5,5)=0.512 + shift = 47.5%"),
        ("5. Required SoC",    "floor = max(0.80, 0.475+ε) = 0.80"),
        ("",                   "TruncNorm(85,5) → 84.3%"),
        ("6. D5 reachability", "need = 14.7 kWh"),
        ("",                   "max = 20·7.6·0.96 = 146 kWh  ✓"),
        ("7. Floor duration",  "7.6 h → 7.5 h = 27000 sec"),
        ("8. Non-overlap",     "no prior session → emit"),
    ]
    ax.text(x1 + 0.22, 7.25, "computation (key steps)", fontsize=14,
            fontweight="bold", color="#a85a14", va="top")
    y = 6.90
    for k, v in comp_lines:
        if k:
            ax.text(x1 + 0.30, y, k, fontsize=12,
                    fontweight="bold", color=BLUE, va="top")
            y -= 0.32
        ax.text(x1 + 0.50, y, v, fontsize=11,
                family="monospace", color=INK, va="top")
        y -= 0.30

    # column 3: sessions output
    out_lines = [
        ("session_id", "412"),
        ("car_id", "42"),
        ("building_id", "1"),
        ("arrival", "2024-04-08 09:15"),
        ("departure", "2024-04-08 16:45"),
        ("duration_sec", "27000"),
        ("arrival_soc", "47.5"),
        ("required_soc", "84.3"),
        ("prev_ext_use_soc", "0.0"),
    ]
    _box(ax, x2, 3.40, col_w, 4.05, "", face="#eaf2fb", edge=BLUE, lw=1.8)
    ax.text(x2 + 0.22, 7.25, "sessions.csv (row)", fontsize=14,
            fontweight="bold", color=BLUE, va="top")
    for i, (k, v) in enumerate(out_lines):
        y = 6.85 - i * 0.40
        ax.text(x2 + 0.30, y, k, fontsize=12.5, color=INK, va="top",
                family="monospace")
        ax.text(x2 + col_w - 0.25, y, v, fontsize=12.5, color=INK,
                va="top", ha="right", fontweight="bold", family="monospace")

    # callout below column 3
    _box(ax, x2, 0.55, col_w, 2.65,
         "",
         face="#fff3e0", edge=ORANGE, lw=1.8)
    ax.text(x2 + 0.22, 3.00, "How users.csv feeds in:",
            fontsize=13, fontweight="bold", color="#a85a14", va="top")
    ax.text(x2 + 0.30, 2.62,
            "φ  → step 1  (attendance)\n"
            "κ  → step 2  (σ_eff narrower)\n"
            "δ  → step 4  (shift SoC lower)\n"
            "battery → step 6 (capacity)\n"
            "max_allowed_soc → step 5",
            fontsize=11.5, family="monospace", color=INK, va="top")

    # arrows from col1 to col2 (light)
    _arrow(ax, x0 + col_w, 6.0, x1, 5.3, color=GREY, lw=1.4)
    _arrow(ax, x0 + col_w, 3.4, x1, 4.0, color=GREY, lw=1.4)

    # arrow col2 to col3
    _arrow(ax, x1 + col_w, 4.0, x2, 5.3, color=GREY, lw=1.4)

    plt.tight_layout()
    out = FIG_DIR / "03_worked_example.png"
    plt.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    fig_three_csvs_dag()
    fig_sessions_pipeline()
    fig_worked_example()
