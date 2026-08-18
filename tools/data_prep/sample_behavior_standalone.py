#!/usr/bin/env python3
"""Standalone sampler for the fitted V2B behavioral distributions.

Reads the fitted parameter blocks straight out of ``configs/populations.yaml``
(``region_distributions.<region>.{arrival,dwell,soc_arrival,soc_depart,copula}``)
and draws EV-charging behavior without importing or running the generator.

Only numpy / scipy / pyyaml are needed, so this file can be copied out of the
repo and used against a populations YAML on its own.

The marginal families and the arrival x dwell Gaussian copula reproduce
``renderers/sessions.py``. What is deliberately NOT reproduced here (it belongs
to the generator's per-car state, not to the distribution model):

  * the per-user commute-distance SoC shift (``-delta_km * 0.003``) and the
    per-car SoC clip band,
  * the D5/D6/D7 rejection loop, the 15-minute grid snap and the same-calendar-day
    constraint, which together make the *emitted* sessions a truncated view of
    these marginals,
  * the per-user appearance Bernoulli (phi) that decides whether a day has a
    session at all.

The inverse-CDFs here are numerically identical to the renderer's (verified to
0 for both mixture families, ~1e-14 for the closed-form single families), but
uniforms are drawn in batch rather than one session at a time, so draws are
distributionally identical to a generator run and NOT bitwise-identical to one.
Use the CLI (`v2b_syndata.cli generate`) when you need the reproducibility
guarantee.

Examples
--------
  # what is available, and which populations are data-calibrated
  uv run python tools/data_prep/sample_behavior_standalone.py --list

  # 5000 draws from one region, with a round-trip fit report
  uv run python tools/data_prep/sample_behavior_standalone.py \
      --population acn_workplace_baseline --region regular_charger \
      -n 5000 --seed 42 --report

  # draw across all regions using the calibrated user-share weights
  uv run python tools/data_prep/sample_behavior_standalone.py \
      --population elaadnl_public_eu -n 20000 --out sessions.csv
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy.stats as st
import yaml

# Defaults mirroring the generator where the YAML block is silent.
DEFAULT_TRUNC_LO = 6.0          # sessions_dist.sample_f_arr
DEFAULT_TRUNC_HI = 20.0
DWELL_CLIP_LO = 0.5             # renderers/sessions.py f_dwell clip band
DWELL_CLIP_HI = 14.0
BISECT_ITERS = 60               # renderers/sessions.py _mixture_ppf


# --------------------------------------------------------------------------
# inverse-CDF helpers (vectorized equivalents of the renderer's scalar forms)
# --------------------------------------------------------------------------
def _invert_cdf(
    u: np.ndarray,
    cdf: Callable[[np.ndarray], np.ndarray],
    a: float,
    b: float,
    iters: int = BISECT_ITERS,
) -> np.ndarray:
    """Bisect a monotone CDF on [a, b]. One uniform in, one quantile out."""
    if b <= a:
        return np.full_like(u, a)
    u = np.clip(u, 1e-9, 1.0 - 1e-9)
    lo = np.full_like(u, a, dtype=float)
    hi = np.full_like(u, b, dtype=float)
    for _ in range(iters):
        m = 0.5 * (lo + hi)
        below = cdf(m) < u
        lo = np.where(below, m, lo)
        hi = np.where(below, hi, m)
    return 0.5 * (lo + hi)


def _trunc_mixture_cdf(block: dict[str, Any]) -> tuple[Callable, float, float]:
    """CDF of the arrival model, plus its support. Handles both families."""
    lo = float(block.get("trunc_lo", DEFAULT_TRUNC_LO))
    hi = float(block.get("trunc_hi", DEFAULT_TRUNC_HI))
    if "w1" in block and "mu1" in block:
        w1 = float(block["w1"])
        comps = [
            (w1, float(block["mu1"]), float(block["sigma1"])),
            (1.0 - w1, float(block["mu2"]), float(block["sigma2"])),
        ]
    else:
        comps = [(1.0, float(block["mu"]), float(block["sigma"]))]

    def cdf(x):
        x = np.asarray(x, dtype=float)
        return sum(
            w * st.truncnorm.cdf(x, (lo - mu) / sg, (hi - mu) / sg, loc=mu, scale=sg)
            for (w, mu, sg) in comps
        )

    return cdf, lo, hi


def _weibull_mixture_cdf(block: dict[str, Any]) -> tuple[Callable, float, float]:
    """CDF of the dwell model, plus a finite bisection ceiling."""
    if "w1" in block and "k1" in block:
        w1 = float(block["w1"])
        comps = [
            (w1, float(block["k1"]), float(block["lambda1"])),
            (1.0 - w1, float(block["k2"]), float(block["lambda2"])),
        ]
    else:
        comps = [(1.0, float(block["k"]), float(block["lambda"]))]

    def cdf(x):
        x = np.asarray(x, dtype=float)
        return sum(w * st.weibull_min.cdf(x, k, scale=lam) for (w, k, lam) in comps)

    hi = max(float(st.weibull_min.ppf(1.0 - 1e-9, k, scale=lam)) for (_w, k, lam) in comps)
    return cdf, 0.0, hi


# --------------------------------------------------------------------------
# the model object
# --------------------------------------------------------------------------
class RegionBehaviorModel:
    """The four marginals + copula fitted for one (population, region) cell."""

    def __init__(self, population: str, region: str, block: dict[str, Any]):
        self.population = population
        self.region = region
        self.block = block
        self.arrival = block.get("arrival")
        self.dwell = block.get("dwell")
        self.soc_arrival = block.get("soc_arrival")
        self.soc_depart = block.get("soc_depart")
        self.rho = float((block.get("copula") or {}).get("rho_gaussian", 0.0))
        if self.arrival is None or self.dwell is None:
            missing = [k for k in ("arrival", "dwell") if block.get(k) is None]
            raise ValueError(
                f"{population}/{region}: no {'/'.join(missing)} block — this cell "
                "was not fitted (n below MIN_SAMPLES) and the generator falls back "
                "to a placeholder formula for it"
            )

    @property
    def families(self) -> dict[str, str]:
        out = {
            "arrival": str(self.arrival.get("dist", "truncnorm")),
            "dwell": str(self.dwell.get("dist", "weibull")),
        }
        if self.soc_arrival:
            out["soc_arrival"] = str(self.soc_arrival.get("dist", "beta"))
        if self.soc_depart:
            out["soc_depart"] = str(self.soc_depart.get("dist", "beta"))
        return out

    def stored_ks(self) -> dict[str, float]:
        """Training-set KS recorded at fit time. NOT held-out."""
        out = {}
        for name in ("arrival", "dwell", "soc_arrival", "soc_depart"):
            blk = getattr(self, name)
            if blk and "ks_fit_quality" in blk:
                out[name] = float(blk["ks_fit_quality"])
        return out

    def sample(self, n: int, rng: np.random.Generator, clip_dwell: bool = True) -> pd.DataFrame:
        """Draw n (arrival_hour, dwell_hours, soc_arrival, soc_depart) tuples.

        arrival and dwell share a bivariate-normal copula at rho_gaussian; the
        two SoC marginals are drawn independently, exactly as the generator does.
        """
        # Gaussian copula -> correlated uniforms.
        z1 = rng.standard_normal(n)
        z2 = self.rho * z1 + np.sqrt(1.0 - self.rho**2) * rng.standard_normal(n)
        u_arr = st.norm.cdf(z1)
        u_dwell = st.norm.cdf(z2)

        a_cdf, a_lo, a_hi = _trunc_mixture_cdf(self.arrival)
        d_cdf, d_lo, d_hi = _weibull_mixture_cdf(self.dwell)
        arrival_hour = _invert_cdf(u_arr, a_cdf, a_lo, a_hi)
        dwell_hours = _invert_cdf(u_dwell, d_cdf, d_lo, d_hi)
        if clip_dwell:
            dwell_hours = np.clip(dwell_hours, DWELL_CLIP_LO, DWELL_CLIP_HI)

        cols: dict[str, Any] = {
            "population": self.population,
            "region": self.region,
            "arrival_hour": arrival_hour,
            "dwell_hours": dwell_hours,
            "departure_hour": arrival_hour + dwell_hours,
        }
        if self.soc_arrival:
            cols["soc_arrival"] = rng.beta(
                float(self.soc_arrival["alpha"]), float(self.soc_arrival["beta"]), n
            )
        if self.soc_depart:
            cols["soc_depart"] = rng.beta(
                float(self.soc_depart["alpha"]), float(self.soc_depart["beta"]), n
            )
        return pd.DataFrame(cols)

    def roundtrip_ks(self, n: int, rng: np.random.Generator) -> dict[str, float]:
        """KS of our own draws against the fitted CDF.

        This validates the sampler, not the model: it should be ~0 (Monte-Carlo
        noise, ~1.36/sqrt(n) at the 95% level). It does NOT measure fit to data.
        """
        df = self.sample(n, rng, clip_dwell=False)
        a_cdf, _, _ = _trunc_mixture_cdf(self.arrival)
        d_cdf, _, _ = _weibull_mixture_cdf(self.dwell)
        out = {
            "arrival": float(st.kstest(df["arrival_hour"].to_numpy(), a_cdf).statistic),
            "dwell": float(st.kstest(df["dwell_hours"].to_numpy(), d_cdf).statistic),
        }
        for name in ("soc_arrival", "soc_depart"):
            blk = getattr(self, name)
            if blk and name in df:
                out[name] = float(
                    st.kstest(
                        df[name].to_numpy(), "beta",
                        args=(float(blk["alpha"]), float(blk["beta"]), 0, 1),
                    ).statistic
                )
        return out


def load_population(yaml_path: Path, name: str) -> dict[str, Any]:
    with Path(yaml_path).open() as fh:
        pops = yaml.safe_load(fh)
    if name not in pops:
        raise KeyError(f"population {name!r} not in {yaml_path}")
    return pops[name]


def build_models(yaml_path: Path, name: str) -> dict[str, RegionBehaviorModel]:
    pop = load_population(yaml_path, name)
    rd = pop.get("region_distributions") or {}
    if not rd:
        raise ValueError(f"population {name!r} has no region_distributions block")
    models = {}
    for region, block in rd.items():
        try:
            models[region] = RegionBehaviorModel(name, region, block)
        except ValueError as exc:
            print(f"  skip: {exc}", file=sys.stderr)
    return models


def region_weights(yaml_path: Path, name: str, regions: list[str]) -> np.ndarray:
    """Empirical per-region user share from axes_distribution, renormalized."""
    pop = load_population(yaml_path, name)
    by_name = {r["name"]: float(r.get("weight", 0.0)) for r in pop.get("axes_distribution", [])}
    w = np.array([by_name.get(r, 0.0) for r in regions], dtype=float)
    if w.sum() <= 0:
        w = np.ones(len(regions))
    return w / w.sum()


def cmd_list(yaml_path: Path) -> None:
    with Path(yaml_path).open() as fh:
        pops = yaml.safe_load(fh)
    rows = []
    for name, entry in pops.items():
        if not isinstance(entry, dict) or "axes_distribution" not in entry:
            continue
        rd = entry.get("region_distributions") or {}
        meta = entry.get("calibration_metadata") or {}
        ks = [
            float(d["ks_fit_quality"])
            for d in (v for blk in rd.values() for v in blk.values())
            if isinstance(d, dict) and "ks_fit_quality" in d
        ]
        rows.append({
            "population": name,
            "policy": entry.get("calibration_policy", "-"),
            "calibrated": "yes" if meta else "no (hand-authored)",
            "dataset": meta.get("dataset", "-"),
            "n_sessions": meta.get("n_sessions_total", "-"),
            "n_regions": len(rd),
            "median_train_ks": round(float(np.median(ks)), 4) if ks else "-",
        })
    print(pd.DataFrame(rows).to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--populations-yaml", type=Path, default=Path("configs/populations.yaml"))
    ap.add_argument("--list", action="store_true", help="list populations and fit status, then exit")
    ap.add_argument("--population", default="acn_workplace_baseline")
    ap.add_argument("--region", default=None, help="single region; default = all, mixed by weight")
    ap.add_argument("-n", "--n-samples", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--report", action="store_true", help="print families, stored KS, round-trip KS")
    ap.add_argument("--out", type=Path, default=None, help="write samples to CSV")
    args = ap.parse_args(argv)

    if args.list:
        cmd_list(args.populations_yaml)
        return 0

    models = build_models(args.populations_yaml, args.population)
    if args.region:
        if args.region not in models:
            print(f"region {args.region!r} not fitted; have: {sorted(models)}", file=sys.stderr)
            return 1
        models = {args.region: models[args.region]}

    rng = np.random.default_rng(args.seed)
    regions = sorted(models)
    weights = region_weights(args.populations_yaml, args.population, regions)
    counts = np.floor(weights * args.n_samples).astype(int)
    counts[int(np.argmax(weights))] += args.n_samples - counts.sum()

    frames = [
        models[r].sample(int(c), rng)
        for r, c in zip(regions, counts, strict=True)
        if c > 0
    ]
    df = pd.concat(frames, ignore_index=True)

    if args.report:
        for r in regions:
            m = models[r]
            print(f"\n=== {args.population} / {r}   rho_gaussian={m.rho:+.3f}")
            print(f"  families      : {m.families}")
            stored = m.stored_ks()
            print(f"  train-set KS  : {stored if stored else 'none (hand-authored block)'}")
            rt = m.roundtrip_ks(20000, np.random.default_rng(args.seed))
            print(f"  round-trip KS : { {k: round(v, 4) for k, v in rt.items()} }"
                  f"   (sampler check; 95% MC band ~{1.36 / np.sqrt(20000):.4f})")

    print(f"\ndrew {len(df)} samples from {args.population} ({len(regions)} region(s))")
    with pd.option_context("display.width", 200):
        print(df.drop(columns=["population"]).groupby("region").describe().T.to_string())
    if args.out:
        df.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
