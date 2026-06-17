"""Empirical model-selection study for the EV-user generative models.

Loads real calibration data through the SAME feature pipeline the generator
uses (`calibration.feature_extractor`), then fits competing distribution
families and ranks them by AIC / BIC / KS so we can say *empirically* whether
each chosen family is justified — not just principled.

Run:  uv run python docs/experiments/model_selection.py

Data: expects the cached calibration sources under
  data/calibration/acn_cache/{caltech,jpl,office001}_2019_2021.json
  data/calibration/elaadnl_cache/elaadnl_utrecht_4tu_2024.csv
(no network / API token needed when the cache is present).

Results summary lives in docs/experiments/README.md and the "Empirical model
selection" section of docs/GENERATIVE_MODELS.md.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import scipy.stats as st
from scipy.optimize import minimize

warnings.filterwarnings("ignore")
np.seterr(all="ignore")

from v2b_syndata.calibration.battery_inference import (
    infer_capacity,
    reconstruct_arrival_soc,
)
from v2b_syndata.calibration.sources import CALIBRATION_SOURCES

REPO = Path(__file__).resolve().parents[2]
ACN_CACHE = REPO / "data/calibration/acn_cache"
ELAADNL_CSV = REPO / "data/calibration/elaadnl_cache/elaadnl_utrecht_4tu_2024.csv"


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def aic_bic(loglik: float, k: int, n: int) -> tuple[float, float]:
    return (2 * k - 2 * loglik, k * np.log(n) - 2 * loglik)


def ks_of(data: np.ndarray, frozen) -> float:
    return float(st.kstest(data, frozen.cdf).statistic)


def report(title: str, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r["AIC"])
    best_aic = rows[0]["AIC"]
    best_ks = min(r["KS"] for r in rows if not np.isnan(r["KS"]))
    print(f"\n### {title}")
    print(f"{'family':<22}{'k':>3}{'logLik':>14}{'AIC':>14}{'BIC':>14}{'KS':>9}{'ΔAIC':>10}")
    for r in rows:
        star = " *" if r["KS"] == best_ks else "  "
        print(f"{r['name']:<22}{r['k']:>3}{r['ll']:>14.1f}{r['AIC']:>14.1f}"
              f"{r['BIC']:>14.1f}{r['KS']:>9.4f}{r['AIC']-best_aic:>10.1f}{star}")
    print(f"  best AIC: {rows[0]['name']}   best KS: "
          f"{min((r for r in rows if not np.isnan(r['KS'])), key=lambda r: r['KS'])['name']}")


def gmm2_fit(x: np.ndarray, iters: int = 300):
    """2-component Gaussian mixture via EM. Returns (params, loglik, k=5, cdf)."""
    x = np.asarray(x, float)
    n = len(x)
    m = np.median(x)
    mu = np.array([x[x <= m].mean(), x[x > m].mean()])
    sd = np.array([max(x[x <= m].std(), 0.5), max(x[x > m].std(), 0.5)])
    w = np.array([0.5, 0.5])
    for _ in range(iters):
        p = np.array([w[j] * st.norm.pdf(x, mu[j], sd[j]) for j in range(2)])
        r = p / (p.sum(0) + 1e-300)
        nk = r.sum(1)
        w = nk / n
        mu = (r * x).sum(1) / nk
        sd = np.maximum(np.sqrt((r * (x - mu[:, None]) ** 2).sum(1) / nk), 0.25)
    ll = float(np.log(np.array([w[j] * st.norm.pdf(x, mu[j], sd[j])
                                for j in range(2)]).sum(0) + 1e-300).sum())

    def cdf(q):
        return w[0] * st.norm.cdf(q, mu[0], sd[0]) + w[1] * st.norm.cdf(q, mu[1], sd[1])
    return (mu, sd, w), ll, 5, cdf


def kumaraswamy_fit(x):
    def negll(p):
        a, b = p
        if a <= 0 or b <= 0:
            return 1e12
        ll = np.log(a) + np.log(b) + (a - 1) * np.log(x) + (b - 1) * np.log1p(-x ** a)
        return -ll.sum() if np.all(np.isfinite(ll)) else 1e12
    r = minimize(negll, [2.0, 2.0], method="Nelder-Mead")
    a, b = r.x

    def cdf(q):
        return 1 - (1 - np.asarray(q) ** a) ** b
    return (a, b), -r.fun, 2, cdf


# ─────────────────────────────────────────────────────────────────────────────
# arrival hour
# ─────────────────────────────────────────────────────────────────────────────

def analyze_arrival(arr: np.ndarray, label: str) -> None:
    n = len(arr)
    inrange = arr[(arr >= 6) & (arr <= 20)]
    cov = len(inrange) / n
    print(f"\n========== ARRIVAL HOUR — {label} (n={n}) ==========")
    print(f"empirical: mean={arr.mean():.2f} std={arr.std():.2f} median={np.median(arr):.2f}")
    print(f"COVERAGE: P(6<=arrival<=20) = {cov:.4f}  "
          f"→ TruncNorm[6,20] structurally discards {(1-cov)*100:.1f}% of arrivals")

    # ---- full-support families on ALL arrivals (TruncNorm cannot — see coverage) ----
    rows = []
    mu, sd = st.norm.fit(arr); fz = st.norm(mu, sd)
    ll = float(fz.logpdf(arr).sum()); a, b = aic_bic(ll, 2, n)
    rows.append(dict(name="Normal", k=2, ll=ll, AIC=a, BIC=b, KS=ks_of(arr, fz)))
    p = st.skewnorm.fit(arr); fz = st.skewnorm(*p)
    ll = float(fz.logpdf(arr).sum()); a, b = aic_bic(ll, 3, n)
    rows.append(dict(name="SkewNormal", k=3, ll=ll, AIC=a, BIC=b, KS=ks_of(arr, fz)))
    theta = arr / 24.0 * 2 * np.pi
    kappa, loc, _ = st.vonmises.fit(theta, fscale=1)
    fzv = st.vonmises(kappa, loc=loc)
    llv = float(fzv.logpdf(theta).sum()) + n * np.log(2 * np.pi / 24)
    a, b = aic_bic(llv, 2, n)
    rows.append(dict(name="vonMises(circ)", k=2, ll=llv, AIC=a, BIC=b,
                     KS=float(st.kstest(arr, lambda q: fzv.cdf(np.asarray(q) / 24 * 2 * np.pi)).statistic)))
    _, llg, kg, gcdf = gmm2_fit(arr); a, b = aic_bic(llg, kg, n)
    rows.append(dict(name="GaussMix-2", k=kg, ll=llg, AIC=a, BIC=b,
                     KS=float(st.kstest(arr, gcdf).statistic)))
    report(f"{label}: full-support fit on ALL arrivals (TruncNorm cannot — see coverage)", rows)

    # ---- bulk fit restricted to [6,20] (calibration's effective domain) ----
    d = inrange; nb = len(d); rows = []

    def tn_negll(params):
        mu, sg = params
        if sg <= 0.05 or sg > 12 or mu < 6 or mu > 20:
            return 1e12
        lp = st.truncnorm.logpdf(d, (6 - mu) / sg, (20 - mu) / sg, loc=mu, scale=sg)
        return -lp.sum() if np.all(np.isfinite(lp)) else 1e12
    r = minimize(tn_negll, [d.mean(), d.std()], method="Nelder-Mead")
    mu, sg = r.x; fz = st.truncnorm((6 - mu) / sg, (20 - mu) / sg, loc=mu, scale=sg)
    ll = float(fz.logpdf(d).sum()); a, b = aic_bic(ll, 2, nb)
    rows.append(dict(name="TruncNorm[6,20]*", k=2, ll=ll, AIC=a, BIC=b, KS=ks_of(d, fz)))
    db = np.clip(d, 6 + 1e-6, 20 - 1e-6)
    al, be, _, _ = st.beta.fit(db, floc=6, fscale=14); fz = st.beta(al, be, loc=6, scale=14)
    ll = float(fz.logpdf(db).sum()); a, b = aic_bic(ll, 2, nb)
    rows.append(dict(name="Beta[6,20]", k=2, ll=ll, AIC=a, BIC=b, KS=ks_of(db, fz)))
    p = st.skewnorm.fit(d); fz = st.skewnorm(*p)
    ll = float(fz.logpdf(d).sum()); a, b = aic_bic(ll, 3, nb)
    rows.append(dict(name="SkewNormal", k=3, ll=ll, AIC=a, BIC=b, KS=ks_of(d, fz)))
    _, llg, kg, gcdf = gmm2_fit(d); a, b = aic_bic(llg, kg, nb)
    rows.append(dict(name="GaussMix-2", k=kg, ll=llg, AIC=a, BIC=b,
                     KS=float(st.kstest(d, gcdf).statistic)))
    report(f"{label}: bulk fit restricted to [6,20] (n={nb}) — * = chosen model", rows)


# ─────────────────────────────────────────────────────────────────────────────
# dwell hours
# ─────────────────────────────────────────────────────────────────────────────

def analyze_dwell(dw: np.ndarray, label: str) -> None:
    d = dw[(dw >= 0.5) & (dw <= 168.0)]; n = len(d)
    print(f"\n========== DWELL HOURS — {label} (n={n}) ==========")
    print(f"empirical: mean={d.mean():.2f} std={d.std():.2f} median={np.median(d):.2f} "
          f"skew={st.skew(d):.2f}")
    rows = []
    fams = {"Weibull*": (st.weibull_min, 2), "Lognormal": (st.lognorm, 2),
            "Gamma": (st.gamma, 2), "Exponential": (st.expon, 1),
            "InverseGaussian": (st.invgauss, 2)}
    for name, (dist, k) in fams.items():
        try:
            fz = dist(*dist.fit(d, floc=0)); ll = float(fz.logpdf(d).sum())
            if not np.isfinite(ll):
                continue
            a, b = aic_bic(ll, k, n)
            rows.append(dict(name=name, k=k, ll=ll, AIC=a, BIC=b, KS=ks_of(d, fz)))
        except Exception as e:
            print(f"  {name}: fit failed ({e})")
    report(f"{label}: dwell duration — * = chosen model (Weibull)", rows)


# ─────────────────────────────────────────────────────────────────────────────
# departure SoC  (arrival prior + delivered/capacity)
# ─────────────────────────────────────────────────────────────────────────────

def analyze_depart_soc(sessions, label: str) -> None:
    rng = np.random.default_rng(20260613)
    depart = []
    efrac = []
    for s in sessions:
        cap, _ = infer_capacity(s)
        soc = reconstruct_arrival_soc(s, cap, rng=rng)
        if soc is None or s.kwh_delivered is None or cap <= 0:
            continue
        ef = float(s.kwh_delivered) / float(cap)
        dep = min(1 - 1e-6, soc + ef)
        if dep > soc:
            depart.append(dep)
            efrac.append(min(ef, 1.5))
    d = np.clip(np.array(depart), 1e-6, 1 - 1e-6); ef = np.array(efrac); n = len(d)
    print(f"\n========== DEPARTURE SoC — {label} (n={n}) ==========")
    print(f"  REAL energy fraction delivered/capacity: mean={ef.mean():.3f} "
          f"median={np.median(ef):.3f} std={ef.std():.3f}  (this is the real signal)")
    print(f"  departure SoC (= prior arrival + efrac): mean={d.mean():.3f} std={d.std():.3f} "
          f" [NOTE: contaminated by the synthetic arrival prior]")
    rows = []
    al, be, _, _ = st.beta.fit(d, floc=0, fscale=1); fz = st.beta(al, be)
    ll = float(fz.logpdf(d).sum()); a, b = aic_bic(ll, 2, n)
    rows.append(dict(name="Beta*", k=2, ll=ll, AIC=a, BIC=b, KS=ks_of(d, fz)))
    _, llk, _, kcdf = kumaraswamy_fit(d); a, b = aic_bic(llk, 2, n)
    rows.append(dict(name="Kumaraswamy", k=2, ll=llk, AIC=a, BIC=b,
                     KS=float(st.kstest(d, kcdf).statistic)))
    z = np.log(d / (1 - d)); mu, sd = st.norm.fit(z)
    ll = float((st.norm.logpdf(z, mu, sd) - np.log(d) - np.log1p(-d)).sum())
    a, b = aic_bic(ll, 2, n)
    rows.append(dict(name="Logit-Normal", k=2, ll=ll, AIC=a, BIC=b,
                     KS=float(st.kstest(d, lambda q: st.norm.cdf(
                         np.log(np.clip(q, 1e-9, 1 - 1e-9) / (1 - np.clip(q, 1e-9, 1 - 1e-9))),
                         mu, sd)).statistic)))

    def tnn(params):
        mu, sg = params
        if sg <= 0.01:
            return 1e12
        lp = st.truncnorm.logpdf(d, (0 - mu) / sg, (1 - mu) / sg, loc=mu, scale=sg)
        return -lp.sum() if np.all(np.isfinite(lp)) else 1e12
    r = minimize(tnn, [d.mean(), d.std()], method="Nelder-Mead")
    mu, sg = r.x; fz = st.truncnorm((0 - mu) / sg, (1 - mu) / sg, loc=mu, scale=sg)
    ll = float(fz.logpdf(d).sum()); a, b = aic_bic(ll, 2, n)
    rows.append(dict(name="TruncNorm[0,1]", k=2, ll=ll, AIC=a, BIC=b, KS=ks_of(d, fz)))
    report(f"{label}: departure-SoC requirement — * = chosen model (Beta)", rows)


# ─────────────────────────────────────────────────────────────────────────────
# arrival × dwell copula
# ─────────────────────────────────────────────────────────────────────────────

def copula_compare(arr: np.ndarray, dw: np.ndarray, label: str) -> None:
    m = (dw >= 0.5) & (dw <= 168.0)
    a, w = arr[m], dw[m]; n = len(a)
    u = st.rankdata(a) / (n + 1); v = st.rankdata(w) / (n + 1)
    tau = st.kendalltau(a, w).statistic; rho_s = st.spearmanr(a, w).statistic
    lL = np.mean((u < 0.05) & (v < 0.05)) / 0.05
    lU = np.mean((u > 0.95) & (v > 0.95)) / 0.05
    print(f"\n========== ARRIVAL × DWELL COPULA — {label} (n={n}) ==========")
    print(f"  Kendall τ={tau:.3f}  Spearman ρ={rho_s:.3f}  "
          f"emp. tail dep λL(5%)={lL:.3f} λU(5%)={lU:.3f}")
    rows = [dict(name="Independence", k=0, ll=0.0, AIC=0.0, BIC=0.0)]
    z1, z2 = st.norm.ppf(u), st.norm.ppf(v); rho = float(np.corrcoef(z1, z2)[0, 1])
    ll = float((-0.5 * np.log(1 - rho**2)
                - (rho**2 * (z1**2 + z2**2) - 2 * rho * z1 * z2) / (2 * (1 - rho**2))).sum())
    a_, b_ = aic_bic(ll, 1, n)
    rows.append(dict(name=f"Gaussian(ρ={rho:.2f})*", k=1, ll=ll, AIC=a_, BIC=b_))

    def clayton_negll(th):
        th = th[0]
        if th <= 1e-6:
            return 1e12
        c = np.log1p(th) + (-1 - th) * (np.log(u) + np.log(v)) \
            + (-2 - 1 / th) * np.log(u ** -th + v ** -th - 1)
        return -c.sum() if np.all(np.isfinite(c)) else 1e12
    r = minimize(clayton_negll, [0.5], method="Nelder-Mead"); a_, b_ = aic_bic(-r.fun, 1, n)
    rows.append(dict(name=f"Clayton(θ={r.x[0]:.2f})", k=1, ll=-r.fun, AIC=a_, BIC=b_))

    def frank_negll(th):
        th = th[0]
        if abs(th) < 1e-6:
            return 1e12
        num = th * (1 - np.exp(-th)) * np.exp(-th * (u + v))
        den = ((1 - np.exp(-th)) - (1 - np.exp(-th * u)) * (1 - np.exp(-th * v))) ** 2
        c = np.log(num) - np.log(den)
        return -c.sum() if np.all(np.isfinite(c)) else 1e12
    r = minimize(frank_negll, [1.0], method="Nelder-Mead"); a_, b_ = aic_bic(-r.fun, 1, n)
    rows.append(dict(name=f"Frank(θ={r.x[0]:.2f})", k=1, ll=-r.fun, AIC=a_, BIC=b_))
    rows = sorted(rows, key=lambda r: r["AIC"])
    print(f"{'copula':<22}{'k':>3}{'logLik':>12}{'AIC':>12}{'BIC':>12}")
    for r in rows:
        print(f"{r['name']:<22}{r['k']:>3}{r['ll']:>12.1f}{r['AIC']:>12.1f}{r['BIC']:>12.1f}")
    print(f"  best AIC: {rows[0]['name']}")


# ─────────────────────────────────────────────────────────────────────────────
# loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_acn(sites=("caltech", "jpl", "office001")):
    src = CALIBRATION_SOURCES["acn_data"]()
    return src.fetch_sessions({"sites": sites, "year_start": 2019, "year_end": 2021,
                               "cache_dir": ACN_CACHE})


class _Sess:
    __slots__ = ("arrival_hour", "dwell_hours", "kwh_delivered")

    def __init__(self, ah, dh, kd):
        self.arrival_hour, self.dwell_hours, self.kwh_delivered = ah, dh, kd


def load_elaadnl():
    import pandas as pd
    if not ELAADNL_CSV.exists():
        return []
    df = pd.read_csv(ELAADNL_CSV, sep=";", engine="python", on_bad_lines="skip")
    s = pd.to_datetime(df["start_datetime"]); e = pd.to_datetime(df["end_datetime"])
    dwell = (e - s).dt.total_seconds() / 3600.0
    ah = s.dt.hour + s.dt.minute / 60.0
    return [_Sess(float(a), float(d), float(kd))
            for a, d, kd in zip(ah, dwell, df["total_energy"])
            if 0.5 <= d <= 168.0]


def dwell_winner(dw):
    d = dw[(dw >= 0.5) & (dw <= 168.0)]; best = None; wk = None
    for name, (dist, k) in {"Weibull": (st.weibull_min, 2), "Lognormal": (st.lognorm, 2),
                            "Gamma": (st.gamma, 2), "Exponential": (st.expon, 1),
                            "InverseGaussian": (st.invgauss, 2)}.items():
        try:
            fz = dist(*dist.fit(d, floc=0)); ll = float(fz.logpdf(d).sum())
            if not np.isfinite(ll):
                continue
            aic = 2 * k - 2 * ll; ks = ks_of(d, fz)
            if name == "Weibull":
                wk = ks
            if best is None or aic < best[1]:
                best = (name, aic, ks)
        except Exception:
            pass
    return best[0], wk


def main():
    acn = load_acn()
    arr = np.array([s.arrival_hour for s in acn]); dw = np.array([s.dwell_hours for s in acn])
    print("#" * 70)
    print(f"# ACN-Data pooled (Caltech+JPL+Office001), n={len(acn)}")
    print("#" * 70)
    analyze_arrival(arr, "ACN pooled")
    analyze_dwell(dw, "ACN pooled")
    analyze_depart_soc(acn, "ACN pooled")
    copula_compare(arr, dw, "ACN pooled")

    ela = load_elaadnl()
    if ela:
        ea = np.array([s.arrival_hour for s in ela]); ed = np.array([s.dwell_hours for s in ela])
        print("\n" + "#" * 70)
        print(f"# ElaadNL Utrecht (robustness check), n={len(ela)}")
        print("#" * 70)
        analyze_arrival(ea, "ElaadNL")
        analyze_dwell(ed, "ElaadNL")
        copula_compare(ea, ed, "ElaadNL")

    print("\n" + "#" * 70)
    print("# ROBUSTNESS — winners across datasets")
    print("#" * 70)
    datasets = [("ACN-caltech", load_acn(("caltech",))),
                ("ACN-jpl", load_acn(("jpl",))),
                ("ACN-office001", load_acn(("office001",)))]
    if ela:
        datasets.append(("ElaadNL", ela))
    print(f"{'dataset':<16}{'n':>7}  {'dwell bestAIC':<16}{'Weibull KS':>11}{'arr cov[6,20]':>15}")
    for lbl, sess in datasets:
        a = np.array([s.arrival_hour for s in sess]); w = np.array([s.dwell_hours for s in sess])
        dwin, wks = dwell_winner(w); cov = np.mean((a >= 6) & (a <= 20))
        print(f"{lbl:<16}{len(sess):>7}  {dwin:<16}{wks:>11.4f}{cov:>15.3f}")


if __name__ == "__main__":
    main()
