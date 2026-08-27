"""Out-of-sample predictability of EV-behaviour features from exogenous context.

Replicates the "Training Data Analysis (EV Behavior)" table: gradient boosting,
trained on low sample indices and tested on held-out high ones, reporting
out-of-sample R² = 1 − SSE/SS(mean of TRAIN).

Two feature sets:
  EXOGENOUS     — building, month, hour (+ day-of-week): known before any car
                  arrives at that hour.
  GIVEN ARRIVAL — plus capacity_kwh and arrival_soc, i.e. the car is plugged in
                  and its state is observed.

Reads a CEILING column alongside each R². The data-generating process is known,
so for several rows the achievable R² is analytically ~0 (capacity and arrival
SoC carry no building/month/hour term by construction) — those rows are
NEGATIVE CONTROLS, and a non-zero R² there would indicate leakage, not signal.
The ceiling for hour-driven rows is estimated from the copula rank correlation
(R² ≈ ρ² for a monotone dependence).

Run:
  uv run python tools/campus/predictability.py data/output/campus_base_moderate_2 \
      --train-samples 0-29 --test-samples 100-129
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[2]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _rng_span(spec: str) -> range:
    lo, hi = spec.split("-")
    return range(int(lo), int(hi) + 1)


def load(root: Path, samples: range) -> pd.DataFrame:
    frames = []
    for b in sorted(root.glob("b*"), key=lambda p: int(p.name[1:])):
        bid = int(b.name[1:])
        for mdir in sorted(b.glob("*")):
            if not mdir.is_dir():
                continue
            mon = MONTHS.get(mdir.name[:3])
            if mon is None:
                continue
            for s in samples:
                d = mdir / str(s)
                f = d / "sessions_soc.csv"
                if not f.exists():
                    continue
                try:
                    g = pd.read_csv(f, usecols=["car_id", "arrival", "departure",
                                                "arrival_soc", "departure_soc"])
                    cars = pd.read_csv(d / "cars.csv").set_index("car_id")
                except Exception:
                    continue
                a = pd.to_datetime(g["arrival"]); dep = pd.to_datetime(g["departure"])
                cap = g["car_id"].map(cars["capacity_kwh"]).astype(float)
                frames.append(pd.DataFrame({
                    "building": bid, "month": mon, "sample": s,
                    "hour": a.dt.hour, "dow": a.dt.dayofweek,
                    "date": a.dt.normalize(),
                    "duration_h": (dep - a).dt.total_seconds() / 3600.0,
                    "capacity_kwh": cap,
                    "arrival_soc": g["arrival_soc"].astype(float),
                    "charge_needed": (g["departure_soc"] - g["arrival_soc"]) / 100.0 * cap,
                }))
    return pd.concat(frames, ignore_index=True)


def arrivals_per_hour(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (unit, date, hour) over the full 0-23 grid on active days."""
    key = ["building", "month", "sample", "date"]
    cnt = (df.groupby(key + ["hour"]).size().rename("arrivals").reset_index())
    days = cnt[key].drop_duplicates()
    grid = days.merge(pd.DataFrame({"hour": range(24)}), how="cross")
    out = grid.merge(cnt, on=key + ["hour"], how="left").fillna({"arrivals": 0})
    out["dow"] = pd.to_datetime(out["date"]).dt.dayofweek
    return out


def oos_r2(model, Xtr, ytr, Xte, yte):
    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    sse = float(np.sum((yte - pred) ** 2))
    sst = float(np.sum((yte - ytr.mean()) ** 2))
    return 1.0 - sse / sst, float(np.sqrt(sse / len(yte))), pred


def main(argv=None) -> int:
    from sklearn.ensemble import HistGradientBoostingRegressor as HGB

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--train-samples", default="0-29")
    ap.add_argument("--test-samples", default="100-129")
    ap.add_argument("--out", type=Path,
                    default=REPO / "docs/experiments/predictability_moderate2.csv")
    a = ap.parse_args(argv)

    tr = load(a.root, _rng_span(a.train_samples))
    te = load(a.root, _rng_span(a.test_samples))
    print(f"train sessions {len(tr):,}   test sessions {len(te):,}")
    atr, ate = arrivals_per_hour(tr), arrivals_per_hour(te)
    print(f"train arrival-hour rows {len(atr):,}   test {len(ate):,}")

    EXO = ["building", "month", "hour", "dow"]
    GIVEN = EXO + ["capacity_kwh", "arrival_soc"]
    rows = []

    def add(name, unit, ytr, yte, Xtr, Xte, Xtr2=None, Xte2=None, ceiling="", note=""):
        r2, rmse, pred = oos_r2(HGB(random_state=0, max_iter=200), Xtr, ytr, Xte, yte)
        rec = {"row_field": name, "unit": unit, "sd": float(np.std(yte)),
               "exo_R2": r2, "exo_RMSE": rmse,
               "pred_lo": float(np.percentile(pred, 1)), "pred_hi": float(np.percentile(pred, 99)),
               "true_lo": float(np.min(yte)), "true_hi": float(np.max(yte)),
               "ceiling": ceiling, "note": note}
        if Xtr2 is not None:
            r2b, rmseb, _ = oos_r2(HGB(random_state=0, max_iter=200), Xtr2, ytr, Xte2, yte)
            rec["given_R2"], rec["given_RMSE"] = r2b, rmseb
        rows.append(rec)

    add("arrivals / hour", "cars", atr["arrivals"].to_numpy(), ate["arrivals"].to_numpy(),
        atr[EXO], ate[EXO], ceiling="high (phi x arrival mixture is a function of building,hour)")
    for col, unit, ceil, note in (
        ("duration_h", "h", "~rho(arr,dwell)^2 = 0.34", "copula edge"),
        ("capacity_kwh", "kWh", "0 (NEGATIVE CONTROL)", "drawn per car from battery_mix; no building/month/hour term"),
        ("arrival_soc", "%", "~0 (NEGATIVE CONTROL)", "placed on the feasible band; depends on capacity+energy, not clock"),
        ("charge_needed", "kWh", "~rho(arr,kwh)^2 = 0.02", "copula edge (was ~0 before the 2026-08 fix)"),
    ):
        Xtr2 = tr[GIVEN] if col != "capacity_kwh" and col != "arrival_soc" else None
        Xte2 = te[GIVEN] if Xtr2 is not None else None
        add(col, unit, tr[col].to_numpy(), te[col].to_numpy(),
            tr[EXO], te[EXO], Xtr2, Xte2, ceiling=ceil, note=note)

    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    show = df.copy()
    show["pred range"] = show.apply(lambda r: f"{r.pred_lo:.1f} – {r.pred_hi:.1f}", axis=1)
    show["true range"] = show.apply(lambda r: f"{r.true_lo:.1f} – {r.true_hi:.1f}", axis=1)
    cols = ["row_field", "unit", "sd", "exo_R2", "exo_RMSE", "pred range", "true range",
            "given_R2", "given_RMSE", "ceiling"]
    print(show[[c for c in cols if c in show.columns]].to_string(index=False,
          float_format=lambda x: f"{x:.4f}"))
    print(f"\nsaved {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
