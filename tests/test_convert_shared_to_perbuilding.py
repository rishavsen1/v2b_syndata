"""Tests for tools/campus/convert_shared_to_perbuilding.py.

The strong test is a *round-trip*: split a real shared slice into per-building
folders, then reconstruct the original shared CSVs from the pieces and assert
they match the source byte-for-value. That proves the split loses/corrupts
nothing. A second group asserts the output *format* matches the reference
``campus10_new`` tree (folder mapping, building_id==0, index reset, file sets).
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC_SHARED = REPO / "data/output/campus10_slight"
REF_PERBUILDING = REPO / "data/output/campus10_new"

# Import the converter module by path (it lives in tools/campus/, not the package).
_spec = importlib.util.spec_from_file_location(
    "convert_shared_to_perbuilding",
    REPO / "tools/campus/convert_shared_to_perbuilding.py",
)
conv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conv)

pytestmark = pytest.mark.skipif(
    not (SRC_SHARED / "batch_manifest.json").exists(),
    reason="campus10_slight shared tree not present",
)


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


@pytest.fixture(scope="module")
def converted(tmp_path_factory) -> tuple[Path, dict]:
    dst = tmp_path_factory.mktemp("perbuilding")
    info = conv.convert_tree(SRC_SHARED, dst, limit_months=1, limit_samples=2)
    return dst, info


def _months_samples(info: dict) -> list[tuple[str, str]]:
    out = []
    for month in info["months"]:
        for sample in conv.discover_samples(SRC_SHARED / month)[:2]:
            out.append((month, sample))
    return out


# --------------------------------------------------------------------------- #
# Round-trip: reconstruct the shared CSVs from the per-building pieces.
# --------------------------------------------------------------------------- #
def test_roundtrip_reconstructs_source_csvs(converted):
    dst, info = converted
    building_ids = info["building_ids"]
    csv_names = [
        p.name
        for p in sorted((SRC_SHARED / info["months"][0] / "0").iterdir())
        if p.suffix == ".csv"
    ]

    for month, sample in _months_samples(info):
        for name in csv_names:
            src_header, src_rows = _read_csv(SRC_SHARED / month / sample / name)
            has_index = src_header[0] == ""
            has_bid = conv.BUILDING_ID_COL in src_header

            # Reconstruct by concatenating each building's split output, undoing
            # the two deterministic edits (building_id -> 0 and index reset).
            recon: list[list[str]] = []
            for bid in building_ids:
                pb = dst / f"b{bid + 1}" / month / sample / name
                header, rows = _read_csv(pb)
                assert header == src_header, f"{name} header drift"
                if not has_bid:
                    # Global file: identical copy in every building; check once.
                    if bid == building_ids[0]:
                        assert rows == src_rows, f"{name} global copy differs"
                    continue
                bid_idx = header.index(conv.BUILDING_ID_COL)
                for row in rows:
                    row = list(row)
                    assert row[bid_idx] == "0", f"{name} building_id not reset"
                    row[bid_idx] = str(bid)  # undo remap
                    recon.append(row)

            if not has_bid:
                continue

            if has_index:
                # Index was reset per building; source index is a global 0..n
                # range, so overwrite both sides' index col before comparing the
                # data payload, then separately assert the source index is a
                # contiguous range (which our reset reproduces per building).
                for i, row in enumerate(src_rows):
                    assert row[0] == str(i), f"{name} source index not a range"
                strip = lambda rs: [r[1:] for r in rs]  # noqa: E731
                assert strip(recon) == strip(src_rows), f"{name} payload differs"
            else:
                assert recon == src_rows, f"{name} rows differ after reassembly"


# --------------------------------------------------------------------------- #
# Format parity with campus10_new.
# --------------------------------------------------------------------------- #
def test_folder_mapping_and_file_sets(converted):
    dst, info = converted
    for bid in info["building_ids"]:
        bdir = dst / f"b{bid + 1}"
        assert bdir.is_dir()
        assert (bdir / "batch_manifest.json").exists()
        for month, sample in _months_samples(info):
            sdir = bdir / month / sample
            got = sorted(p.name for p in sdir.iterdir())
            ref = sorted(
                p.name for p in (SRC_SHARED / month / sample).iterdir()
            )
            assert got == ref, f"{bdir.name}/{month}/{sample} file set drift"


def test_building_id_is_zero_everywhere(converted):
    dst, info = converted
    for bid in info["building_ids"]:
        for month, sample in _months_samples(info):
            sdir = dst / f"b{bid + 1}" / month / sample
            for csv_path in sdir.glob("*.csv"):
                header, rows = _read_csv(csv_path)
                if conv.BUILDING_ID_COL not in header:
                    continue
                idx = header.index(conv.BUILDING_ID_COL)
                assert all(r[idx] == "0" for r in rows), csv_path


def test_per_sample_config_single_building(converted):
    dst, info = converted
    for bid in info["building_ids"]:
        month, sample = _months_samples(info)[0]
        cfg = json.loads(
            (dst / f"b{bid + 1}" / month / sample / "multi_building_config.json").read_text()
        )
        assert len(cfg["buildings"]) == 1
        assert cfg["buildings"][0]["building_id"] == 0
        assert cfg["validation_summary"]["n_units"] == 1


def test_leading_index_resets_per_building(converted):
    dst, info = converted
    month, sample = _months_samples(info)[0]
    # cars.csv has a leading unnamed index column.
    for bid in info["building_ids"]:
        header, rows = _read_csv(
            dst / f"b{bid + 1}" / month / sample / "cars.csv"
        )
        assert header[0] == ""
        assert [r[0] for r in rows] == [str(i) for i in range(len(rows))]


@pytest.mark.skipif(
    not (REF_PERBUILDING / "b1").exists(),
    reason="campus10_new reference tree not present",
)
def test_headers_match_reference_new(converted):
    dst, info = converted
    month, sample = _months_samples(info)[0]
    for csv_path in (REF_PERBUILDING / "b1" / month / "0").glob("*.csv"):
        ref_header, _ = _read_csv(csv_path)
        our, _ = _read_csv(dst / "b1" / month / sample / csv_path.name)
        assert our == ref_header, f"{csv_path.name} header differs from campus10_new"


def test_manifest_structure(converted):
    dst, info = converted
    mani = json.loads((dst / "b1" / "batch_manifest.json").read_text())
    assert mani["n_buildings"] == 1
    # Manifest is derived from the source batch_manifest (full batch), not the
    # limited slice, so n_units tracks n_total.
    assert mani["validation_summary"]["n_units"] == mani["n_total"]
    assert mani["n_total"] == mani["n_succeeded"] + mani["n_failed"]
