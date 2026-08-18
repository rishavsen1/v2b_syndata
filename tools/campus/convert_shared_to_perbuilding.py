#!/usr/bin/env python3
"""Convert a *shared* multi-building batch tree into a *per-building* tree.

Source layout (``output_mode: shared`` — e.g. ``data/output/campus10_slight``)::

    <src>/
      batch_manifest.json
      <MONTH>/<sample>/*.csv          # every CSV holds all N buildings
                                      #   (distinguished by a ``building_id`` column)
      <MONTH>/<sample>/multi_building_config.json   # lists all N buildings

Target layout (per-building — matches ``data/output/campus10_new``)::

    <dst>/
      b1/ .. bN/
        batch_manifest.json           # single-building manifest
        <MONTH>/<sample>/*.csv        # only that building's rows,
                                      #   with building_id re-mapped to 0
        <MONTH>/<sample>/multi_building_config.json   # single building (id 0)

Folder mapping is ``b{building_id + 1}`` (building_id 0 -> ``b1``).

Transform rules, one per CSV kind:

* **leading-index + ``building_id``** (``cars``, ``chargers``, ``grid_prices``,
  ``sessions``): keep the building's rows, renumber the leading unnamed index
  column to ``0..m-1``, set ``building_id`` -> ``0``.
* **no-index + ``building_id``** (``battery``, ``building_load``, ``occupancy``,
  ``policies``, ``pv``, ``pv_generation``, ``weather_data``): keep the building's
  rows, set ``building_id`` -> ``0``.
* **no ``building_id``** (``dso_commands``): a global file, copied verbatim into
  every building folder.

All other cell values pass through untouched, so the split is byte-faithful for
every column except the two that must change (index + ``building_id``).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import shutil
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger("convert_shared_to_perbuilding")

MONTH_RE = re.compile(r"^[A-Z]{3}\d{4}$")
SAMPLE_RE = re.compile(r"^\d+$")

BUILDING_ID_COL = "building_id"


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def split_csv(
    src_path: Path,
    dst_dirs: dict[int, Path],
) -> None:
    """Split one CSV into per-building copies under ``dst_dirs[building_id]``.

    Handles all three file kinds (see module docstring). ``dst_dirs`` maps a
    building_id to the destination sample directory for that building.
    """
    header, rows = _read_csv(src_path)
    name = src_path.name

    if BUILDING_ID_COL not in header:
        # Global file (dso_commands): copy verbatim into every building.
        for dst_dir in dst_dirs.values():
            shutil.copyfile(src_path, dst_dir / name)
        return

    bid_idx = header.index(BUILDING_ID_COL)
    has_index = header[0] == ""

    grouped: dict[int, list[list[str]]] = defaultdict(list)
    for row in rows:
        grouped[int(row[bid_idx])].append(row)

    for bid, dst_dir in dst_dirs.items():
        out_rows: list[list[str]] = []
        for out_i, row in enumerate(grouped.get(bid, [])):
            row = list(row)
            row[bid_idx] = "0"
            if has_index:
                row[0] = str(out_i)
            out_rows.append(row)
        _write_csv(dst_dir / name, header, out_rows)


# --------------------------------------------------------------------------- #
# JSON (config + manifest) helpers
# --------------------------------------------------------------------------- #
def _filter_validation_summary(vs: dict, building_id: int) -> dict:
    """Reduce a multi-building ``validation_summary`` to a single building.

    Emits the same key order and shape ``campus10_new`` uses (building_id -> 0,
    n_units == 1).
    """
    warned = [
        w for w in vs.get("warned_units", []) if w.get("building_id") == building_id
    ]
    failed = [
        f for f in vs.get("failed_units", []) if f.get("building_id") == building_id
    ]

    new_warned = [
        {
            "building_id": 0,
            "seed": w.get("seed"),
            "n_warnings": w.get("n_warnings"),
            "warnings": w.get("warnings"),
        }
        for w in warned
    ]
    new_failed = [
        {
            "building_id": 0,
            "seed": f.get("seed"),
            "n_errors": f.get("n_errors"),
            "errors": f.get("errors"),
        }
        for f in failed
    ]

    return {
        "failed_units": new_failed,
        "n_failed": len(new_failed),
        "n_passed": 1 - len(new_failed),
        "n_units": 1,
        "n_units_with_warnings": 1 if new_warned else 0,
        "total_errors": sum((f.get("n_errors") or 0) for f in failed),
        "total_warnings": sum((w.get("n_warnings") or 0) for w in warned),
        "warned_units": new_warned,
    }


def split_config(src_path: Path, dst_dirs: dict[int, Path]) -> None:
    """Split ``multi_building_config.json`` into per-building single configs."""
    cfg = json.loads(src_path.read_text())
    by_id = {b["building_id"]: b for b in cfg["buildings"]}

    for bid, dst_dir in dst_dirs.items():
        building = json.loads(json.dumps(by_id[bid]))  # deep copy
        building["building_id"] = 0
        out = dict(cfg)
        out["buildings"] = [building]
        out["validation_summary"] = _filter_validation_summary(
            cfg.get("validation_summary", {}), bid
        )
        (dst_dir / src_path.name).write_text(json.dumps(out, indent=2))


def _building_base_seeds(src_root: Path) -> dict[int, int]:
    """Map building_id -> base seed, read from any per-sample config."""
    for cfg_path in sorted(src_root.glob("*/*/multi_building_config.json")):
        cfg = json.loads(cfg_path.read_text())
        return {b["building_id"]: b.get("seed") for b in cfg["buildings"]}
    return {}


def build_building_manifest(
    src_manifest: dict, building_id: int, base_seed: int | None
) -> dict:
    """Derive a single-building ``batch_manifest.json`` from the shared one.

    Mirrors ``campus10_new``'s manifest structure: a per-sample ``samples`` list
    with single-building validation, and a rolled-up ``validation_summary`` whose
    ``warned_units`` use the stringified-dict warning format (seed == base seed +
    seed_base + sample_idx).
    """
    seed_base = src_manifest.get("seed_base", 0) or 0
    out = dict(src_manifest)
    out["n_buildings"] = 1

    bwp = src_manifest.get("building_weather_profiles")
    if isinstance(bwp, list) and building_id < len(bwp):
        out["building_weather_profiles"] = [bwp[building_id]]

    samples_out: list[dict] = []
    roll_warned: list[dict] = []
    roll_failed: list[dict] = []
    n_units = n_passed = n_failed = 0
    total_errors = total_warnings = n_with_warnings = 0

    for sample in src_manifest.get("samples", []):
        vs = sample.get("validation", {})
        filt = _filter_validation_summary(vs, building_id)
        new_sample = dict(sample)
        new_sample["validation"] = filt
        samples_out.append(new_sample)

        n_units += 1
        n_passed += filt["n_passed"]
        n_failed += filt["n_failed"]
        total_errors += filt["total_errors"]
        total_warnings += filt["total_warnings"]
        n_with_warnings += filt["n_units_with_warnings"]

        month = sample.get("month")
        sample_idx = sample.get("sample_idx")
        seed = None if base_seed is None else base_seed + seed_base + (sample_idx or 0)

        if filt["warned_units"]:
            w = filt["warned_units"][0]
            warn_dict = {
                "building_id": 0,
                "seed": seed,
                "n_warnings": w["n_warnings"],
                "warnings": w["warnings"],
            }
            roll_warned.append(
                {
                    "month": month,
                    "sample": sample_idx,
                    "n_warnings": w["n_warnings"],
                    "warnings": [str(warn_dict)],
                }
            )
        if filt["failed_units"]:
            f = filt["failed_units"][0]
            fail_dict = {
                "building_id": 0,
                "seed": seed,
                "n_errors": f["n_errors"],
                "errors": f["errors"],
            }
            roll_failed.append(
                {
                    "month": month,
                    "sample": sample_idx,
                    "n_errors": f["n_errors"],
                    "errors": [str(fail_dict)],
                }
            )

    out["n_total"] = n_units
    out["n_succeeded"] = n_units - n_failed
    out["n_failed"] = n_failed
    out["samples"] = samples_out
    out["validation_summary"] = {
        "n_units": n_units,
        "n_passed": n_passed,
        "n_failed": n_failed,
        "total_errors": total_errors,
        "failed_units": roll_failed,
        "n_units_with_warnings": n_with_warnings,
        "total_warnings": total_warnings,
        "warned_units": roll_warned,
    }
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def discover_building_ids(src_root: Path) -> list[int]:
    for cfg_path in sorted(src_root.glob("*/*/multi_building_config.json")):
        cfg = json.loads(cfg_path.read_text())
        return sorted(b["building_id"] for b in cfg["buildings"])
    raise FileNotFoundError(f"no multi_building_config.json under {src_root}")


def discover_months(src_root: Path) -> list[str]:
    return sorted(
        p.name for p in src_root.iterdir() if p.is_dir() and MONTH_RE.match(p.name)
    )


def discover_samples(month_dir: Path) -> list[str]:
    return sorted(
        (p.name for p in month_dir.iterdir() if p.is_dir() and SAMPLE_RE.match(p.name)),
        key=int,
    )


def convert_sample(
    src_sample: Path, dst_root: Path, month: str, sample: str, building_ids: list[int]
) -> None:
    dst_dirs: dict[int, Path] = {}
    for bid in building_ids:
        d = dst_root / f"b{bid + 1}" / month / sample
        d.mkdir(parents=True, exist_ok=True)
        dst_dirs[bid] = d

    for item in sorted(src_sample.iterdir()):
        if item.suffix == ".csv":
            split_csv(item, dst_dirs)
        elif item.name == "multi_building_config.json":
            split_config(item, dst_dirs)
        else:
            for d in dst_dirs.values():
                shutil.copyfile(item, d / item.name)


def _convert_sample_task(args: tuple) -> None:
    """Top-level worker wrapper (must be picklable for ProcessPoolExecutor)."""
    src_root, dst_root, month, sample, building_ids = args
    convert_sample(src_root / month / sample, dst_root, month, sample, building_ids)


def convert_tree(
    src_root: Path,
    dst_root: Path,
    limit_months: int | None = None,
    limit_samples: int | None = None,
    workers: int = 1,
) -> dict:
    building_ids = discover_building_ids(src_root)
    months = discover_months(src_root)
    if limit_months is not None:
        months = months[:limit_months]

    logger.info(
        "converting %s -> %s  (%d buildings, %d months, %d workers)",
        src_root,
        dst_root,
        len(building_ids),
        len(months),
        workers,
    )

    tasks: list[tuple] = []
    for month in months:
        samples = discover_samples(src_root / month)
        if limit_samples is not None:
            samples = samples[:limit_samples]
        for sample in samples:
            tasks.append((src_root, dst_root, month, sample, building_ids))

    n_samples = len(tasks)
    if workers <= 1:
        for t in tasks:
            _convert_sample_task(t)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_convert_sample_task, t) for t in tasks]
            done = 0
            for fut in as_completed(futures):
                fut.result()  # surface any worker exception
                done += 1
                if done % 500 == 0 or done == n_samples:
                    logger.info("  %d/%d sample dirs", done, n_samples)

    # Per-building manifests.
    manifest_path = src_root / "batch_manifest.json"
    if manifest_path.exists():
        src_manifest = json.loads(manifest_path.read_text())
        base_seeds = _building_base_seeds(src_root)
        for bid in building_ids:
            manifest = build_building_manifest(
                src_manifest, bid, base_seeds.get(bid)
            )
            out = dst_root / f"b{bid + 1}" / "batch_manifest.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(manifest, indent=2))
    else:
        logger.warning("no batch_manifest.json in %s — skipping manifests", src_root)

    logger.info("done: %d sample dirs converted", n_samples)
    return {"building_ids": building_ids, "months": months, "n_samples": n_samples}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="shared batch root")
    parser.add_argument(
        "--dst", type=Path, required=True, help="per-building output root"
    )
    parser.add_argument("--limit-months", type=int, default=None)
    parser.add_argument("--limit-samples", type=int, default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, (os.cpu_count() or 2)),
        help="parallel sample workers (default: min(8, ncpu))",
    )
    parser.add_argument(
        "--force", action="store_true", help="allow writing into an existing --dst"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.dst.exists() and not args.force and any(args.dst.iterdir()):
        parser.error(f"{args.dst} exists and is non-empty; pass --force to proceed")

    convert_tree(
        args.src,
        args.dst,
        args.limit_months,
        args.limit_samples,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
