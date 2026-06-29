#!/usr/bin/env python3
"""TSTR (train-on-synthetic, test-on-real) utility proof via load forecasting.

KDD readiness item #3 (utility). The track *requires* a proof of utility, not
just an assertion. This harness demonstrates that a short-horizon aggregate
charging-load forecaster TRAINED ON SYNTHETIC data transfers to REAL data, and
quantifies the gap against the real-trained topline.

Three settings are reported on the SAME held-out REAL test split:

  - TRTR  train real      -> test real   (the topline / upper bound)
  - TSTR  train synthetic -> test real   (THE UTILITY PROOF)
  - TRTS  train real      -> test synth  (context: how "learnable" synth is)

Headline = the TSTR-vs-TRTR gap on real held-out data.

Pipeline
--------
1. Build an aggregate charging-load series (kW per hour, or 15-min) from:
   (a) a GENERATED synthetic cohort (`v2b_syndata.runner.generate` on a
       calibrated scenario, default S_acn_caltech), and
   (b) the REAL ACN / ElaadNL sessions (production source loaders).
2. Sessions -> load by spreading each session's delivered energy uniformly
   across its connect->disconnect window (see SESSION->LOAD ASSUMPTION below).
3. Features = lagged load (t-1,t-2,t-3,t-24), hour-of-day, day-of-week.
4. Fixed-seed HistGradientBoostingRegressor (deterministic). 1-step-ahead.
5. Metrics: MAE, RMSE, MAPE. Writes data/tstr/results.json + prints a table.

Reproducible with one command; every result is stamped with the generator
version + git sha (from the synthetic cohort's manifest) so a baseline run on
the current generator and a final run on the improved generator (workstream B)
are distinguishable in the JSON.

SESSION->LOAD AGGREGATION ASSUMPTION
------------------------------------
Neither the real datasets nor the synthetic CSV carry a per-minute power
trace. We reconstruct an aggregate load curve by spreading each session's
*total delivered energy* uniformly (constant power) over its connect->disconnect
dwell window: power_kw = energy_kwh / dwell_hours, accrued to every time bin the
window overlaps, pro-rated by overlap fraction. Summing over concurrent
sessions yields aggregate kW per bin. This is the standard "energy-rectangle"
proxy; it deliberately ignores real charging ramp/taper and idle-after-full
behavior (ACN's doneChargingTime is not used) so that REAL and SYNTHETIC are
reconstructed by the *identical* rule and the TSTR comparison is apples-to-apples.

Usage
-----
  uv run python tools/tstr_forecasting.py                  # full baseline run
  uv run python tools/tstr_forecasting.py --freq 15min
  uv run python tools/tstr_forecasting.py --real elaadnl
  uv run python tools/tstr_forecasting.py --quick          # tiny month, fast
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CAL = REPO / "data" / "calibration"
OUT_DIR = REPO / "data" / "tstr"

SEED = 1234
LAGS = (1, 2, 3, 24)  # hourly lags; auto-scaled for sub-hourly freq
TRAIN_FRAC = 0.6  # of the REAL series: first 60% train, last 40% test (held-out)


# --------------------------------------------------------------------------- #
# 1. Sessions -> aggregate load series (the shared reconstruction rule)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Session:
    """Minimal session: connect time, dwell (h), delivered energy (kWh)."""
    connect: pd.Timestamp
    dwell_hours: float
    kwh: float


def sessions_to_load_series(
    sessions: Sequence[Session],
    freq: str = "1h",
) -> pd.Series:
    """Aggregate sessions into a load curve (mean kW per bin).

    Each session contributes constant power energy/dwell across its
    connect->disconnect window, pro-rated by per-bin overlap. The returned
    Series is indexed by a complete, gap-free DatetimeIndex at `freq` (missing
    bins are 0 kW), value = average power (kW) drawn during that bin.

    See module docstring "SESSION->LOAD AGGREGATION ASSUMPTION".
    """
    valid = [
        s for s in sessions
        if s.dwell_hours and s.dwell_hours > 0 and np.isfinite(s.kwh) and s.kwh >= 0
    ]
    if not valid:
        raise ValueError("no valid sessions to aggregate")

    bin_delta = pd.Timedelta(freq)
    bin_hours = bin_delta.total_seconds() / 3600.0

    starts = pd.to_datetime([s.connect for s in valid])
    # Drop tz so synthetic (naive) and real (UTC-aware) align on wall clock.
    if starts.tz is not None:
        starts = starts.tz_localize(None)
    dwell = np.array([s.dwell_hours for s in valid], dtype=float)
    kwh = np.array([s.kwh for s in valid], dtype=float)
    ends = starts + pd.to_timedelta(dwell, unit="h")
    power_kw = kwh / dwell  # constant power over the window

    grid_start = starts.min().floor(freq)
    grid_end = ends.max().ceil(freq)
    index = pd.date_range(grid_start, grid_end, freq=freq, inclusive="left")
    if len(index) == 0:
        index = pd.date_range(grid_start, periods=1, freq=freq)
    # energy accrued per bin (kWh); convert to mean kW at the end.
    energy = np.zeros(len(index), dtype=float)
    edges = index.values.astype("datetime64[ns]").astype("int64")
    bin_ns = int(bin_delta.value)

    s_ns = starts.values.astype("datetime64[ns]").astype("int64")
    e_ns = ends.values.astype("datetime64[ns]").astype("int64")
    grid0 = int(edges[0])
    n_bins = len(index)

    for i in range(len(valid)):
        a = s_ns[i]
        b = e_ns[i]
        p = power_kw[i]
        first = (a - grid0) // bin_ns
        last = (b - grid0) // bin_ns
        first = max(first, 0)
        last = min(last, n_bins - 1)
        for j in range(first, last + 1):
            bin_lo = grid0 + j * bin_ns
            bin_hi = bin_lo + bin_ns
            overlap_ns = min(b, bin_hi) - max(a, bin_lo)
            if overlap_ns <= 0:
                continue
            overlap_h = overlap_ns / 3.6e12  # ns -> hours
            energy[j] += p * overlap_h

    load_kw = energy / bin_hours  # mean kW over the bin
    return pd.Series(load_kw, index=index, name="load_kw")


# --------------------------------------------------------------------------- #
# 2. Real / synthetic session loaders
# --------------------------------------------------------------------------- #
def load_real_sessions(source: str, sites: tuple[str, ...] | None = None) -> list[Session]:
    """Load REAL sessions from cached ACN / ElaadNL via production loaders."""
    if source == "acn":
        from v2b_syndata.calibration.sources.acn import AcnSource
        feats = AcnSource().fetch_sessions({
            "sites": sites or ("caltech",),
            "year_start": 2019, "year_end": 2021,
            "cache_dir": CAL / "acn_cache",
        })
    elif source == "elaadnl":
        from v2b_syndata.calibration.sources.elaadnl import ElaadNLSource
        feats = ElaadNLSource().fetch_sessions({
            "archive_tag": "utrecht_4tu_2024",
            "cache_dir": CAL / "elaadnl_cache",
            "venue_filter": "workplace",
        })
    else:
        raise ValueError(f"unknown real source {source!r} (acn|elaadnl)")
    return [
        Session(connect=pd.Timestamp(f.arrival_time), dwell_hours=float(f.dwell_hours),
                kwh=float(f.kwh_delivered))
        for f in feats
    ]


def generate_synthetic_cohort(
    scenario_id: str, seed: int, sim_months: int, work_dir: Path,
) -> tuple[list[Session], dict[str, Any]]:
    """Generate a synthetic cohort and convert its sessions to Session records.

    Synthetic delivered energy is reconstructed from the SoC swing:
        kwh = capacity_kwh * (required_soc_at_depart - arrival_soc) / 100
    (SoC columns are in percent). Returns (sessions, generator_stamp).
    """
    from v2b_syndata.runner import generate

    work_dir.mkdir(parents=True, exist_ok=True)
    overrides: dict[str, Any] = {}
    manifest = generate(
        scenario_id=scenario_id, seed=seed, output_dir=work_dir,
        config_dir=REPO / "configs", cli_overrides=overrides or None,
    )
    sess = pd.read_csv(work_dir / "sessions.csv")
    cars = pd.read_csv(work_dir / "cars.csv")[["car_id", "capacity_kwh"]]
    df = sess.merge(cars, on="car_id", how="left")
    df["connect"] = pd.to_datetime(df["arrival"])
    df["depart"] = pd.to_datetime(df["departure"])
    df["dwell_hours"] = (df["depart"] - df["connect"]).dt.total_seconds() / 3600.0
    soc_swing = (df["required_soc_at_depart"] - df["arrival_soc"]).clip(lower=0.0)
    df["kwh"] = df["capacity_kwh"] * soc_swing / 100.0

    sessions = [
        Session(connect=r.connect, dwell_hours=float(r.dwell_hours), kwh=float(r.kwh))
        for r in df.itertuples()
        if r.dwell_hours > 0 and np.isfinite(r.kwh)
    ]
    stamp = {
        "scenario_id": scenario_id,
        "seed": seed,
        "generator_version": manifest.get("generator_version"),
        "generator_git_sha": manifest.get("generator_git_sha"),
        "sim_window": [str(df["connect"].min()), str(df["depart"].max())],
        "n_sessions": len(sessions),
    }
    return sessions, stamp


# --------------------------------------------------------------------------- #
# 3. Feature engineering
# --------------------------------------------------------------------------- #
def build_features(load: pd.Series, lags: Sequence[int] = LAGS) -> tuple[pd.DataFrame, pd.Series]:
    """1-step-ahead supervised matrix: lagged load + hour-of-day + day-of-week.

    Returns (X, y) aligned and NaN-free (rows with incomplete lags dropped).
    """
    df = pd.DataFrame({"load_kw": load.astype(float)})
    idx = df.index
    df["hour"] = idx.hour + idx.minute / 60.0
    df["dow"] = idx.dayofweek
    for lag in lags:
        df[f"lag_{lag}"] = df["load_kw"].shift(lag)
    feat_cols = ["hour", "dow"] + [f"lag_{lag}" for lag in lags]
    df = df.dropna(subset=feat_cols)
    return df[feat_cols], df["load_kw"]


# --------------------------------------------------------------------------- #
# 4. Model + metrics
# --------------------------------------------------------------------------- #
def make_model(seed: int = SEED):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(
        max_iter=300, learning_rate=0.05, max_depth=6,
        min_samples_leaf=20, l2_regularization=1.0,
        random_state=seed,
    )


def metrics(y_true: np.ndarray, y_pred: np.ndarray, eps_frac: float = 0.05) -> dict[str, float]:
    """MAE, RMSE, MAPE. MAPE uses a denominator floor (eps_frac * mean|y|) so
    near-zero bins (charging gaps) don't blow the percentage up."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    floor = eps_frac * float(np.mean(np.abs(y_true))) or 1e-9
    denom = np.maximum(np.abs(y_true), floor)
    mape = float(np.mean(np.abs(err) / denom) * 100.0)
    return {"mae": mae, "rmse": rmse, "mape": mape}


def fit_eval(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_test: pd.DataFrame, y_test: pd.Series, seed: int = SEED,
) -> dict[str, float]:
    model = make_model(seed)
    model.fit(X_train.values, y_train.values)
    pred = model.predict(X_test.values)
    return metrics(y_test.values, pred)


# --------------------------------------------------------------------------- #
# 5. TSTR experiment
# --------------------------------------------------------------------------- #
def split_real(load_real: pd.Series, train_frac: float = TRAIN_FRAC):
    """Chronological split of the real series into (train, test). The test
    tail is the SAME held-out real data used by all three settings."""
    n = len(load_real)
    cut = int(n * train_frac)
    return load_real.iloc[:cut], load_real.iloc[cut:]


def run_tstr(
    load_real: pd.Series, load_synth: pd.Series, seed: int = SEED,
) -> dict[str, Any]:
    """Compute TRTR / TSTR / TRTS on a common held-out REAL test split."""
    real_train, real_test = split_real(load_real)

    Xr_tr, yr_tr = build_features(real_train)
    Xr_te, yr_te = build_features(real_test)
    Xs, ys = build_features(load_synth)

    if min(len(Xr_tr), len(Xr_te), len(Xs)) < 10:
        raise ValueError(
            f"insufficient samples after feature-building: "
            f"real_train={len(Xr_tr)} real_test={len(Xr_te)} synth={len(Xs)}"
        )

    trtr = fit_eval(Xr_tr, yr_tr, Xr_te, yr_te, seed)          # real -> real
    tstr = fit_eval(Xs, ys, Xr_te, yr_te, seed)                # synth -> real
    trts = fit_eval(Xr_tr, yr_tr, Xs, ys, seed)                # real -> synth

    def gap(a: dict, b: dict) -> dict:
        return {m: a[m] - b[m] for m in ("mae", "rmse", "mape")}

    return {
        "TRTR": trtr, "TSTR": tstr, "TRTS": trts,
        "TSTR_minus_TRTR": gap(tstr, trtr),
        "TSTR_over_TRTR_ratio": {m: (tstr[m] / trtr[m] if trtr[m] else float("inf"))
                                 for m in ("mae", "rmse", "mape")},
        "sample_counts": {
            "real_train": int(len(Xr_tr)), "real_test": int(len(Xr_te)),
            "synth": int(len(Xs)),
        },
    }


# --------------------------------------------------------------------------- #
# 6. CLI / reporting
# --------------------------------------------------------------------------- #
def _series_summary(load: pd.Series) -> dict[str, Any]:
    freq = load.index.freq
    bin_h = (pd.Timedelta(freq).total_seconds() / 3600.0) if freq else 1.0
    return {
        "n_bins": int(len(load)),
        "start": str(load.index.min()), "end": str(load.index.max()),
        "mean_kw": float(load.mean()), "peak_kw": float(load.max()),
        "total_mwh": float(load.sum() * bin_h / 1000.0),
    }


def format_table(res: dict[str, Any]) -> str:
    rows = [
        ("TRTR (train real  -> test real )  [topline]", res["TRTR"]),
        ("TSTR (train synth -> test real )  [UTILITY]", res["TSTR"]),
        ("TRTS (train real  -> test synth)  [context]", res["TRTS"]),
    ]
    lines = [
        "  setting                                       MAE       RMSE      MAPE%",
        "  " + "-" * 70,
    ]
    for label, m in rows:
        lines.append(f"  {label:<44} {m['mae']:8.3f}  {m['rmse']:8.3f}  {m['mape']:7.2f}")
    lines.append("  " + "-" * 70)
    g = res["TSTR_minus_TRTR"]
    r = res["TSTR_over_TRTR_ratio"]
    lines.append(f"  TSTR - TRTR gap (lower = better transfer):   "
                 f"{g['mae']:+8.3f}  {g['rmse']:+8.3f}  {g['mape']:+7.2f}")
    lines.append(f"  TSTR / TRTR ratio (1.0 = perfect transfer):  "
                 f"{r['mae']:8.2f}x {r['rmse']:8.2f}x {r['mape']:7.2f}x")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", default="acn", choices=["acn", "elaadnl"],
                    help="real test dataset (default: acn)")
    ap.add_argument("--scenario", default="S_acn_caltech",
                    help="calibrated scenario for the synthetic cohort")
    ap.add_argument("--freq", default="1h", help="resample frequency (1h, 15min)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--sim-months", type=int, default=1,
                    help="(informational) synthetic sim window length")
    ap.add_argument("--quick", action="store_true",
                    help="cap real sessions for a fast smoke run")
    ap.add_argument("--out", default=str(OUT_DIR / "results.json"))
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] generating synthetic cohort ({args.scenario}, seed={args.seed}) ...")
    with tempfile.TemporaryDirectory() as td:
        synth_sessions, gen_stamp = generate_synthetic_cohort(
            args.scenario, args.seed, args.sim_months, Path(td) / "syn")
    print(f"      synthetic sessions: {len(synth_sessions)}  "
          f"(gen v{gen_stamp['generator_version']} @ {str(gen_stamp['generator_git_sha'])[:10]})")

    print(f"[2/4] loading real {args.real} sessions ...")
    real_sessions = load_real_sessions(args.real)
    if args.quick:
        real_sessions = real_sessions[:2000]
    print(f"      real sessions: {len(real_sessions)}")

    print(f"[3/4] building aggregate load series @ {args.freq} ...")
    load_real = sessions_to_load_series(real_sessions, freq=args.freq)
    load_synth = sessions_to_load_series(synth_sessions, freq=args.freq)

    print("[4/4] running TRTR / TSTR / TRTS ...")
    res = run_tstr(load_real, load_synth, seed=args.seed)

    out = {
        "generator": gen_stamp,
        "config": {
            "real_source": args.real, "scenario": args.scenario,
            "freq": args.freq, "seed": args.seed, "lags": list(LAGS),
            "train_frac": TRAIN_FRAC,
            "session_to_load_assumption":
                "uniform constant-power spread of delivered energy over "
                "connect->disconnect dwell window (energy-rectangle proxy); "
                "identical rule applied to real and synthetic.",
        },
        "real_series": _series_summary(load_real),
        "synth_series": _series_summary(load_synth),
        "results": res,
    }
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")

    print()
    print("=" * 74)
    print(f"  TSTR UTILITY PROOF  —  test on REAL {args.real.upper()} held-out "
          f"({res['sample_counts']['real_test']} bins @ {args.freq})")
    print(f"  synthetic from generator v{gen_stamp['generator_version']} "
          f"@ {str(gen_stamp['generator_git_sha'])[:10]}")
    print("=" * 74)
    print(format_table(res))
    print("=" * 74)
    print(f"  results written -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
