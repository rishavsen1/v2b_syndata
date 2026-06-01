"""C12 regression: sessions must not cross midnight (no overnight stays).

The renderer rejects any sampled (arrival, dwell) whose departure lands on a
later calendar day than arrival, and validate() flags such a row as C12. S01
over a 30-day April window historically produced a handful of overnight stays
(see data/output3/S01/APR2024) — making this a non-vacuous regression guard.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from v2b_syndata.runner import generate
from v2b_syndata.validate import validate

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

_LONG_WINDOW = {
    "sim_window.mode": "custom",
    "sim_window.start": "2024-04-01",
    "sim_window.custom_end": "2024-05-01",
}


def _gen(out: Path, seed: int) -> None:
    generate(
        scenario_id="S01", seed=seed, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides=dict(_LONG_WINDOW),
        noise_profile_override=None,
    )


def _overnight_rows(sessions: pd.DataFrame) -> pd.DataFrame:
    arr = pd.to_datetime(sessions["arrival"]).dt.normalize()
    dep = pd.to_datetime(sessions["departure"]).dt.normalize()
    return sessions[arr != dep]


def test_generator_emits_no_overnight_sessions(tmp_path):
    """Across several seeds known to historically produce overnight stays,
    the renderer must now emit zero sessions that cross midnight."""
    for seed in (0, 1, 8):
        out = tmp_path / f"s{seed}"
        _gen(out, seed)
        sessions = pd.read_csv(out / "sessions.csv")
        overnight = _overnight_rows(sessions)
        assert overnight.empty, (
            f"seed={seed}: {len(overnight)} overnight session(s) emitted; "
            f"e.g. {overnight.iloc[0]['arrival']} -> {overnight.iloc[0]['departure']}"
        )


def test_validator_flags_injected_overnight(tmp_path):
    """An injected midnight-crossing row trips C12 (and nothing else spurious)."""
    out = tmp_path / "out"
    _gen(out, seed=0)
    sess_path = out / "sessions.csv"
    sessions = pd.read_csv(sess_path)
    assert len(sessions) > 0

    # Push the first session's departure into the next calendar day, keeping
    # duration_sec self-consistent so only C12 (not C6) fires.
    arr = pd.to_datetime(sessions.loc[0, "arrival"])
    new_dep = arr + pd.Timedelta(days=1) - pd.Timedelta(minutes=15)
    sessions.loc[0, "departure"] = new_dep.strftime("%Y-%m-%d %H:%M:%S")
    sessions.loc[0, "duration_sec"] = int((new_dep - arr).total_seconds())
    sessions.to_csv(sess_path, index=False, lineterminator="\n")

    rep = validate(out, strict=False)
    c12 = [e for e in rep.errors if e.startswith("C12")]
    assert c12, f"C12 not raised for an overnight row; errors={rep.errors}"


def test_validator_passes_clean_sessions(tmp_path):
    """A normally-generated (post-fix) scenario raises no C12 error."""
    out = tmp_path / "out"
    _gen(out, seed=0)
    rep = validate(out, strict=False)
    c12 = [e for e in rep.errors if e.startswith("C12")]
    assert not c12, f"unexpected C12 on clean data: {c12}"


def test_arrival_jitter_cannot_reintroduce_overnight():
    """Noise shifts arrival backward (departure is fixed); large backward jitter
    on a just-after-midnight arrival must NOT land it on the previous calendar
    day. The day-start floor in apply_noise keeps every jittered session
    same-day, so C12 holds post-noise.

    Focused unit test (not generation): S01's arrivals cluster in the morning,
    so a near-midnight arrival rarely occurs naturally — we construct one and
    drive apply_noise directly. Many cars make a backward crossing near-certain
    without the fix.
    """
    from datetime import datetime

    from v2b_syndata.noise import apply_noise
    from v2b_syndata.types import ScenarioContext

    class _Knobs:
        def get(self, _key):
            return 0.5  # user_behavior.min_depart_soc

    n_cars = 40
    sessions = pd.DataFrame([{
        "session_id": i + 1, "car_id": i + 1, "building_id": "B001",
        "arrival": "2024-04-15 00:15:00", "departure": "2024-04-15 06:00:00",
        "duration_sec": 20700, "arrival_soc": 30.0,
        "required_soc_at_depart": 80.0, "previous_day_external_use_soc": 0.0,
    } for i in range(n_cars)])
    cars = pd.DataFrame([{
        "car_id": i + 1, "capacity_kwh": 75.0, "min_allowed_soc": 5.0,
        "max_allowed_soc": 95.0, "battery_class": "m3_75",
    } for i in range(n_cars)])
    chargers = pd.DataFrame([{
        "charger_id": 1, "directionality": "unidirectional",
        "min_rate_kw": 0.0, "max_rate_kw": 50.0,
    }])
    ctx = ScenarioContext(
        scenario_id="UNIT", seed=7, knobs=_Knobs(),
        sim_start=datetime(2024, 4, 1), sim_end=datetime(2024, 5, 1),
        rendered={"sessions.csv": sessions, "cars.csv": cars,
                  "chargers.csv": chargers},
        noise={"arrival_time_jitter_min": 60.0, "soc_arrival_jitter_pct": 0.0},
        noise_profile_name="unit",
    )
    apply_noise(ctx)
    out = ctx.rendered["sessions.csv"]
    assert len(out) > 0
    arr = pd.to_datetime(out["arrival"]).dt.normalize()
    dep = pd.to_datetime(out["departure"]).dt.normalize()
    bad = out[arr != dep]
    assert bad.empty, (
        f"{len(bad)} session(s) pushed overnight by jitter; "
        f"e.g. {bad.iloc[0]['arrival']} -> {bad.iloc[0]['departure']}"
    )
