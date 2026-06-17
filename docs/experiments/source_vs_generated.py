"""Source vs generated distributions — round-trip validation.

Calibrate → generate → does the generated population reproduce the source?
Compares ACN-Data Caltech (ground truth, via the live feature pipeline) against
a generated `S_acn_caltech` cohort (calibrated from that same source).

Run:
  # 1. generate a calibrated cohort (full year, large fleet for a smooth sample)
  uv run python -m v2b_syndata.cli generate --scenario S_acn_caltech --seed 7 \\
      --output-dir /tmp/gen_caltech --override ev_fleet.ev_count=400 \\
      --override charging_infra.charger_count=120 --override sim_window.mode=full_year
  # 2. plot
  uv run python docs/experiments/source_vs_generated.py /tmp/gen_caltech

Writes docs/experiments/source_vs_generated.png
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import scipy.stats as st

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from v2b_syndata.calibration.battery_inference import (
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.sources import CALIBRATION_SOURCES

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "source_vs_generated.png"
GEN_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/gen_caltech")

# ── source: ACN Caltech ──────────────────────────────────────────────────────
src = CALIBRATION_SOURCES["acn_data"]()
sess = src.fetch_sessions({"sites": ("caltech",), "year_start": 2019, "year_end": 2021,
                           "cache_dir": REPO / "data/calibration/acn_cache"})
src_arr = np.array([s.arrival_hour for s in sess])
src_dw = np.array([s.dwell_hours for s in sess]); src_dw = src_dw[(src_dw >= 0.5) & (src_dw <= 24)]
# source departure-SoC TARGET = the quantity soc_depart was calibrated to
rng = np.random.default_rng(20260613); src_dep = []
for s in sess:
    cap, _ = infer_capacity(s); soc = reconstruct_arrival_soc(s, cap, rng=rng)
    if soc is None or s.kwh_delivered is None or cap <= 0:
        continue
    dep = min(1 - 1e-6, soc + float(s.kwh_delivered) / float(cap))
    if dep > soc:
        src_dep.append(dep * 100)
src_dep = np.array(src_dep)

# ── generated: S_acn_caltech sessions.csv ────────────────────────────────────
g = pd.read_csv(GEN_DIR / "sessions.csv")
gen_arr = pd.to_datetime(g["arrival"]).dt.hour + pd.to_datetime(g["arrival"]).dt.minute / 60.0
gen_arr = gen_arr.to_numpy()
gen_dw = (g["duration_sec"] / 3600.0).to_numpy()
gen_dep = g["required_soc_at_depart"].to_numpy()

# ── plot ─────────────────────────────────────────────────────────────────────
SRC_C, GEN_C = "#555555", "#d8853b"
fig, ax = plt.subplots(1, 3, figsize=(17, 5))


def overlay(a, src_x, gen_x, bins, rng_, title, xlabel):
    a.hist(src_x, bins=bins, range=rng_, density=True, color=SRC_C, alpha=0.55,
           label=f"source (ACN Caltech, n={len(src_x)})")
    a.hist(gen_x, bins=bins, range=rng_, density=True, histtype="step", color=GEN_C,
           lw=2.5, label=f"generated (n={len(gen_x)})")
    ks = st.ks_2samp(src_x, gen_x).statistic
    a.set_title(f"{title}\n2-sample KS(source, generated) = {ks:.3f}", fontsize=11)
    a.set_xlabel(xlabel); a.set_ylabel("density"); a.legend(fontsize=9)


overlay(ax[0], src_arr, gen_arr, 48, (0, 24),
        "(a) Arrival hour", "hour of day")
ax[0].axvspan(0, 6, color="red", alpha=0.05); ax[0].axvspan(20, 24, color="red", alpha=0.05)
overlay(ax[1], src_dw, gen_dw[(gen_dw >= 0.5) & (gen_dw <= 24)], 48, (0, 24),
        "(b) Dwell (hours)", "dwell hours")
overlay(ax[2], src_dep, gen_dep, 40, (0, 100),
        "(c) Departure-SoC requirement (%)", "required SoC at departure (%)")

fig.suptitle("Source (ground truth) vs generated — calibrated S_acn_caltech round-trip",
             fontsize=14, y=1.02)
fig.tight_layout()
fig.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"saved {OUT}")
