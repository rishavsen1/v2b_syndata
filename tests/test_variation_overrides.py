"""One round-trip test per knob type. Exercises every branch of `_check_type_and_range`."""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pytest

from v2b_syndata.knob_loader import (
    KnobValidationError,
    load_knob_registry,
    resolve_knobs,
)
from v2b_syndata.validate import validate


@pytest.mark.parametrize("ev_count", [1, 200])
def test_int_boundary_ev_count(ev_count, fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"ev_fleet.ev_count": ev_count})
    assert_sanity(out, manifest)
    cars = pd.read_csv(out / "cars.csv")
    assert len(cars) == ev_count


@pytest.mark.parametrize("peak_kw", [50.0, 5000.0])
def test_float_boundary_peak_kw(peak_kw, fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"building_load.peak_kw": peak_kw})
    assert_sanity(out, manifest)
    assert manifest["knob_resolution"]["building_load.peak_kw"]["value"] == peak_kw


def test_bool_weekdays_only_false(fast_generate, assert_sanity):
    out, manifest = fast_generate(overrides={"sim_window.weekdays_only": False})
    assert_sanity(out, manifest)
    assert manifest["knob_resolution"]["sim_window.weekdays_only"]["value"] is False


def test_simplex_corner_battery_mix(fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "ev_fleet.battery_mix": [1.0, 0.0, 0.0, 0.0],
        }
    )
    assert_sanity(out, manifest)
    cars = pd.read_csv(out / "cars.csv")
    assert (cars["battery_class"] == "leaf_24").all(), "battery_mix=[1,0,0,0] should yield only leaf_24"


def test_vec2_peak_window(fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "utility_rate.tariff_type": "TOU",
            "utility_rate.peak_window": [10, 14],
        }
    )
    assert_sanity(out, manifest)
    assert manifest["knob_resolution"]["utility_rate.peak_window"]["value"] == [10, 14]


def test_list_vec2_menu_levels(fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "user_behavior.menu_levels": [[0.0, 0]],
        }
    )
    assert_sanity(out, manifest)
    assert manifest["knob_resolution"]["user_behavior.menu_levels"]["value"] == [[0.0, 0]]


def test_list_region_single_region(fast_generate, assert_sanity):
    region = {
        "name": "test_region",
        "freq": [0.0, 1.0],
        "consist": [0.0, 1.0],
        "dist_km": [0.0, 100.0],
        "weight": 1.0,
    }
    out, manifest = fast_generate(
        overrides={
            "user_behavior.axes_distribution": [region],
        }
    )
    assert_sanity(out, manifest)
    users = pd.read_csv(out / "users.csv")
    assert (users["region"] == "test_region").all()


def test_timestamp_string(fast_generate, assert_sanity):
    out, manifest = fast_generate(
        overrides={
            "sim_window.start": "2020-04-01",
            "sim_window.custom_end": "2020-04-08",
        }
    )
    assert_sanity(out, manifest, expected_start=datetime(2020, 4, 1), expected_end=datetime(2020, 4, 8))


def test_timestamp_date_via_direct_api(fast_generate, assert_sanity):
    """Regression test: ``date`` objects passed via the direct API must
    round-trip into the manifest (which is JSON-serialized).

    Previously crashed because ``cli_overrides`` wasn't normalized before
    ``write_manifest`` ran ``json.dump``.
    """
    out, manifest = fast_generate(
        overrides={
            "sim_window.start": date(2020, 4, 1),
            "sim_window.custom_end": date(2020, 4, 8),
        }
    )
    assert_sanity(out, manifest, expected_start=datetime(2020, 4, 1), expected_end=datetime(2020, 4, 8))
    with (out / "manifest.json").open() as f:
        m = json.load(f)
    assert m["knob_overrides"]["sim_window.start"] == "2020-04-01"
    assert m["knob_overrides"]["sim_window.custom_end"] == "2020-04-08"


def test_timestamp_wrong_type_rejected(config_dir):
    reg = load_knob_registry(config_dir / "knobs.yaml")
    with pytest.raises(KnobValidationError):
        resolve_knobs(reg, {}, {"sim_window.start": 12345}, {})
