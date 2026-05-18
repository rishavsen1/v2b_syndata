"""End-to-end tests for the DR events renderer (Step 6)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from v2b_syndata.runner import generate

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"


def _gen(out_dir: Path, scenario: str = "S_dr_cbp", overrides: dict | None = None):
    return generate(
        scenario_id=scenario,
        seed=42,
        output_dir=out_dir,
        config_dir=CONFIG_DIR,
        cli_overrides=overrides or {},
        noise_profile_override=None,
    )


@pytest.mark.real_energyplus
def test_dr_renderer_s01_no_program_header_only(tmp_path: Path):
    out = tmp_path / "s01"
    generate(
        scenario_id="S01", seed=42, output_dir=out,
        config_dir=CONFIG_DIR, cli_overrides={}, noise_profile_override=None,
    )
    df = pd.read_csv(out / "dr_events.csv")
    assert len(df) == 0
    assert list(df.columns) == ["event_id", "start", "end", "magnitude_kw", "notified_at"]


@pytest.mark.real_energyplus
def test_dr_renderer_cbp_events_in_season(tmp_path: Path):
    out = tmp_path / "cbp"
    _gen(out, scenario="S_dr_cbp")
    df = pd.read_csv(out / "dr_events.csv")
    assert len(df) > 0, "expected some CBP events in summer SF window"
    starts = pd.to_datetime(df["start"])
    assert starts.dt.month.isin(range(5, 11)).all()


@pytest.mark.real_energyplus
def test_dr_renderer_cbp_notification_lead_24h(tmp_path: Path):
    out = tmp_path / "cbp"
    _gen(out, scenario="S_dr_cbp")
    df = pd.read_csv(out / "dr_events.csv")
    starts = pd.to_datetime(df["start"])
    notifs = pd.to_datetime(df["notified_at"])
    leads = (starts - notifs).dt.total_seconds() / 3600
    for lead in leads:
        assert abs(lead - 24.0) < 1 / 60


@pytest.mark.real_energyplus
def test_dr_renderer_bip_lead_2h(tmp_path: Path):
    out = tmp_path / "bip"
    _gen(out, scenario="S_dr_bip", overrides={"utility_rate.dr_lambda_base": 0.5})
    df = pd.read_csv(out / "dr_events.csv")
    if len(df) > 0:
        leads = (pd.to_datetime(df["start"]) - pd.to_datetime(df["notified_at"])).dt.total_seconds() / 3600
        for lead in leads:
            assert abs(lead - 2.0) < 1 / 60


@pytest.mark.real_energyplus
def test_dr_renderer_elrp_lead_2h(tmp_path: Path):
    out = tmp_path / "elrp"
    _gen(out, scenario="S_dr_elrp")
    df = pd.read_csv(out / "dr_events.csv")
    if len(df) > 0:
        leads = (pd.to_datetime(df["start"]) - pd.to_datetime(df["notified_at"])).dt.total_seconds() / 3600
        for lead in leads:
            assert abs(lead - 2.0) < 1 / 60


@pytest.mark.real_energyplus
def test_dr_renderer_reproducibility(tmp_path: Path):
    out1 = tmp_path / "r1"
    out2 = tmp_path / "r2"
    _gen(out1, scenario="S_dr_cbp")
    _gen(out2, scenario="S_dr_cbp")
    h1 = hashlib.sha256((out1 / "dr_events.csv").read_bytes()).hexdigest()
    h2 = hashlib.sha256((out2 / "dr_events.csv").read_bytes()).hexdigest()
    assert h1 == h2


@pytest.mark.real_energyplus
def test_dr_renderer_lambda_base_override_sensitivity(tmp_path: Path):
    out_low = tmp_path / "low"
    out_high = tmp_path / "high"
    _gen(out_low, scenario="S_dr_cbp", overrides={"utility_rate.dr_lambda_base": 0.01})
    _gen(out_high, scenario="S_dr_cbp", overrides={"utility_rate.dr_lambda_base": 0.5})
    n_low = len(pd.read_csv(out_low / "dr_events.csv"))
    n_high = len(pd.read_csv(out_high / "dr_events.csv"))
    assert n_high > n_low, f"high λ ({n_high}) must exceed low λ ({n_low})"


@pytest.mark.real_energyplus
def test_dr_renderer_invalid_program_rejected(tmp_path: Path):
    """Unsupported dr_program string must be rejected."""
    from v2b_syndata.knob_loader import KnobValidationError
    out = tmp_path / "bad"
    # dr_program is a categorical knob — knob_loader rejects unknown values before
    # reaching the renderer. Use the registry validation path.
    with pytest.raises(KnobValidationError):
        _gen(out, scenario="S_dr_cbp",
             overrides={"utility_rate.dr_program": "DRAM"})


@pytest.mark.real_energyplus
def test_dr_renderer_monthly_cap_enforced(tmp_path: Path):
    """Crank λ_base; verify per-month cap holds."""
    from v2b_syndata.samplers.dr_sampler import PROGRAM_SPECS
    out = tmp_path / "cap"
    _gen(out, scenario="S_dr_cbp", overrides={"utility_rate.dr_lambda_base": 5.0})
    df = pd.read_csv(out / "dr_events.csv")
    assert len(df) > 0
    spec = PROGRAM_SPECS["CBP"]
    per_month = pd.to_datetime(df["start"]).dt.to_period("M").value_counts()
    assert (per_month <= spec.max_events_per_month).all(), per_month.to_dict()


@pytest.mark.real_energyplus
def test_dr_renderer_event_duration_4h(tmp_path: Path):
    out = tmp_path / "dur"
    _gen(out, scenario="S_dr_cbp")
    df = pd.read_csv(out / "dr_events.csv")
    starts = pd.to_datetime(df["start"])
    ends = pd.to_datetime(df["end"])
    for s, e in zip(starts, ends):
        assert (e - s).total_seconds() == 4 * 3600


@pytest.mark.real_energyplus
def test_dr_renderer_temperature_correlation(tmp_path: Path):
    """Event-day avg max temp ≥ non-event-day avg max temp (heat-conditional sampler)."""
    from v2b_syndata.load_pipeline.weather import (
        get_weather_epw,
        parse_epw_temperatures,
    )
    out = tmp_path / "temp"
    _gen(out, scenario="S_dr_cbp", overrides={"utility_rate.dr_lambda_base": 0.2})
    df = pd.read_csv(out / "dr_events.csv")
    if len(df) < 5:
        pytest.skip("not enough events for temperature correlation check")
    df["date"] = pd.to_datetime(df["start"]).dt.date
    event_dates = set(df["date"])
    epw = get_weather_epw("USA_CA_San.Francisco.Intl.AP.724940_TMYx", "tmyx")
    hourly_f = parse_epw_temperatures(epw, year=2020) * 9 / 5 + 32
    daily_max = hourly_f.resample("D").max()
    # Restrict to summer window
    summer = daily_max[(daily_max.index >= "2020-06-01") & (daily_max.index < "2020-09-01")]
    by_date = {ts.date(): val for ts, val in summer.items()}
    event_temps = [by_date[d] for d in event_dates if d in by_date]
    non_event_temps = [val for d, val in by_date.items() if d not in event_dates]
    if event_temps and non_event_temps:
        assert sum(event_temps) / len(event_temps) >= sum(non_event_temps) / len(non_event_temps) - 1.0
