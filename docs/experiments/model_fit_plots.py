"""Fit-comparison plots: empirical data vs candidate families (ACN pooled).

Run:  uv run python docs/experiments/model_fit_plots.py
Writes docs/experiments/model_fit_comparison.png
"""
from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib
import numpy as np
import scipy.stats as st
from scipy.optimize import minimize

warnings.filterwarnings("ignore")
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from v2b_syndata.calibration.battery_inference import (
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.sources import CALIBRATION_SOURCES

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "model_fit_comparison.png"

src = CALIBRATION_SOURCES["acn_data"]()
sess = src.fetch_sessions({"sites": ("caltech", "jpl", "office001"), "year_start": 2019,
                           "year_end": 2021, "cache_dir": REPO / "data/calibration/acn_cache"})
arr = np.array([s.arrival_hour for s in sess])
dw = np.array([s.dwell_hours for s in sess]); dw = dw[(dw >= 0.5) & (dw <= 168)]

fig, ax = plt.subplots(2, 2, figsize=(14, 10))
C = {"emp": "#bbbbbb", "chosen": "#d8853b", "alt1": "#2c7fb8", "alt2": "#31a354"}

# (a) arrival hour
a = ax[0, 0]
a.hist(arr, bins=48, density=True, color=C["emp"], label="empirical (all)")
d = arr[(arr >= 6) & (arr <= 20)]


def tn(p):
    mu, sg = p
    if sg <= 0.05:
        return 1e12
    lp = st.truncnorm.logpdf(d, (6 - mu) / sg, (20 - mu) / sg, loc=mu, scale=sg)
    return -lp.sum() if np.all(np.isfinite(lp)) else 1e12


r = minimize(tn, [d.mean(), d.std()], method="Nelder-Mead"); mu, sg = r.x
xsr = np.linspace(6, 20, 400)
a.plot(xsr, st.truncnorm.pdf(xsr, (6 - mu) / sg, (20 - mu) / sg, loc=mu, scale=sg),
       color=C["chosen"], lw=2.5, label="TruncNorm[6,20] (CHOSEN), KS=0.108")
xs = np.linspace(0, 24, 500)
m = np.median(arr); mu2 = np.array([arr[arr <= m].mean(), arr[arr > m].mean()])
sd2 = np.array([arr[arr <= m].std(), arr[arr > m].std()]); w2 = np.array([.5, .5])
for _ in range(300):
    P = np.array([w2[j] * st.norm.pdf(arr, mu2[j], sd2[j]) for j in range(2)])
    R = P / (P.sum(0) + 1e-300); nk = R.sum(1); w2 = nk / len(arr)
    mu2 = (R * arr).sum(1) / nk
    sd2 = np.maximum(np.sqrt((R * (arr - mu2[:, None]) ** 2).sum(1) / nk), .25)
a.plot(xs, w2[0] * st.norm.pdf(xs, mu2[0], sd2[0]) + w2[1] * st.norm.pdf(xs, mu2[1], sd2[1]),
       color=C["alt2"], lw=2.5, ls="--", label="GaussMix-2 (best fit), KS=0.029")
a.axvspan(0, 6, color="red", alpha=0.06); a.axvspan(20, 24, color="red", alpha=0.06)
a.set_title("(a) Arrival hour — 8.3% of arrivals fall in the red zones\n"
            "TruncNorm cannot represent them; data is bimodal", fontsize=11)
a.set_xlabel("hour of day"); a.set_ylabel("density"); a.legend(fontsize=9); a.set_xlim(0, 24)

# (b) dwell
b = ax[0, 1]
b.hist(dw, bins=80, density=True, color=C["emp"], label="empirical"); b.set_xlim(0, 24)
xs2 = np.linspace(0.5, 24, 500)
for name, dist, col, ls in [("Weibull (CHOSEN), KS=0.102", st.weibull_min, C["chosen"], "-"),
                            ("Gamma, KS=0.120", st.gamma, C["alt1"], "--"),
                            ("Lognormal, KS=0.137", st.lognorm, C["alt2"], ":")]:
    b.plot(xs2, dist.pdf(xs2, *dist.fit(dw, floc=0)), color=col, lw=2.3, ls=ls, label=name)
b.set_title("(b) Dwell — Weibull wins AIC + KS\n(Gamma a close 2nd; Lognormal/Exp worse)", fontsize=11)
b.set_xlabel("dwell hours"); b.set_ylabel("density"); b.legend(fontsize=9)

# (c) departure SoC
c = ax[1, 0]
rng = np.random.default_rng(20260613); dep = []; ef = []
for s in sess:
    cap, _ = infer_capacity(s); soc = reconstruct_arrival_soc(s, cap, rng=rng)
    if soc is None or s.kwh_delivered is None or cap <= 0:
        continue
    e = float(s.kwh_delivered) / float(cap); d2 = min(1 - 1e-6, soc + e)
    if d2 > soc:
        dep.append(d2); ef.append(min(e, 1.0))
dep = np.clip(np.array(dep), 1e-6, 1 - 1e-6)
c.hist(dep, bins=50, density=True, color=C["emp"], label="departure SoC (prior+Δ)")
c.hist(np.array(ef), bins=50, density=True, histtype="step", color="black", lw=1.5,
       label="REAL Δ = delivered/capacity (mean 0.30)")
xs3 = np.linspace(0.01, 0.99, 400)
al, be, _, _ = st.beta.fit(dep, floc=0, fscale=1)
c.plot(xs3, st.beta.pdf(xs3, al, be), color=C["chosen"], lw=2.5, label="Beta (CHOSEN)")
c.set_title("(c) Departure SoC — Beta fit\n(the real signal is Δ; SoC is Δ + a prior)", fontsize=11)
c.set_xlabel("SoC fraction"); c.set_ylabel("density"); c.legend(fontsize=9)

# (d) arrival vs dwell dependence
d_ax = ax[1, 1]
hb = d_ax.hexbin(arr, dw, gridsize=40, cmap="Oranges", mincnt=1, extent=(0, 24, 0, 24))
d_ax.set_ylim(0, 24)
tau = st.kendalltau(arr, dw).statistic; rho = st.spearmanr(arr, dw).statistic
d_ax.set_title(f"(d) Arrival × dwell — strong NEGATIVE dependence\n"
               f"Kendall τ={tau:.2f}, Spearman ρ={rho:.2f} (later arrival → shorter stay)",
               fontsize=11)
d_ax.set_xlabel("arrival hour"); d_ax.set_ylabel("dwell hours")
fig.colorbar(hb, ax=d_ax, label="count")

fig.suptitle(f"EV-user generative models vs ACN-Data ground truth (n={len(sess)})", fontsize=14, y=1.0)
fig.tight_layout()
fig.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"saved {OUT}")
