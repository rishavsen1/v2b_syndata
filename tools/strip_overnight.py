#!/usr/bin/env python3
"""Strip overnight stays (sessions crossing midnight) from generated datasets.

A session is "overnight" iff its departure lands on a later calendar day than
its arrival (``arrival[:10] != departure[:10]``) — the C12 invariant the
renderer now enforces. This tool retro-cleans already-generated artifacts:

    - drops every overnight row from each ``sessions.csv`` (cells are otherwise
      kept byte-for-byte; csv module preserves exact tokens);
    - updates the sibling ``manifest.json`` so ``csv_sha256["sessions"]`` and
      ``csv_row_counts["sessions"]`` match the rewritten file — otherwise
      validate()'s I2/I3 checks fail on every cleaned dir.

``previous_day_external_use_soc`` is left as rendered. It is NOT recomputable
from the stored columns: noise.py jitters ``arrival_soc`` (and D5-truncates
``required_soc_at_depart``) *after* the renderer freezes prev_ext, so the
render-time algebra no longer holds in the CSV. Nothing reads its value
(grep: only sessions.py writes it, validate.py only checks schema membership),
so a stale value on the row following a removed session is cosmetic. The path
to pristine prev_ext is regeneration with the fixed generator, which chains it
correctly over an overnight-free session set.

SCOPE: synthetic outputs only. ``calibration_validation`` is excluded on
purpose — it compares synthetic output against REAL data (e.g. INL residential)
that legitimately contains overnight charging — and the real source CSVs under
``data/calibration`` / test fixtures are never touched.

Usage:
    python tools/strip_overnight.py [--dry-run] [DIR ...]

With no DIR args, defaults to the synthetic output dirs under ``data/``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

# Synthetic generated-output dirs only. NOT calibration_validation, NOT
# calibration (real source), NOT stations / load_pipeline_cache.
DEFAULT_DIRS = [
    "output", "output2", "output3", "outputs", "outputs_new",
    "paper_bench", "sensitivity", "sweep",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _update_manifest(path: Path) -> bool:
    """Refresh csv_sha256/csv_row_counts for sessions.csv. Returns True if the
    manifest existed and carried a sessions entry to update."""
    mpath = path.parent / "manifest.json"
    if not mpath.exists():
        return False
    manifest = json.loads(mpath.read_text())
    touched = False
    if "sessions" in manifest.get("csv_sha256", {}):
        manifest["csv_sha256"]["sessions"] = _sha256(path)
        touched = True
    if "sessions" in manifest.get("csv_row_counts", {}):
        with path.open() as fh:
            manifest["csv_row_counts"]["sessions"] = max(0, sum(1 for _ in fh) - 1)
        touched = True
    if touched:
        with mpath.open("w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return touched


def process(path: Path, dry: bool) -> tuple[int, bool]:
    """Return (rows_dropped, rewritten)."""
    with path.open(newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return 0, False
    header = rows[0]
    idx = {c: i for i, c in enumerate(header)}
    if "arrival" not in idx or "departure" not in idx:
        return 0, False  # not a sessions.csv
    ai, di = idx["arrival"], idx["departure"]

    data = rows[1:]
    kept = [r for r in data if r[ai][:10] == r[di][:10]]
    dropped = len(data) - len(kept)
    if dropped == 0:
        return 0, False
    if not dry:
        with path.open("w", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(header)
            w.writerows(kept)
        _update_manifest(path)
    return dropped, True


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    dirs = [a for a in argv if not a.startswith("--")] or DEFAULT_DIRS

    files: list[Path] = []
    for d in dirs:
        base = (DATA / d) if not Path(d).is_absolute() else Path(d)
        files.extend(sorted(base.rglob("sessions.csv")))

    tot_dropped = tot_files = 0
    for f in files:
        dropped, rewritten = process(f, dry)
        if rewritten:
            tot_files += 1
            tot_dropped += dropped
            try:
                shown = f.relative_to(REPO)
            except ValueError:
                shown = f
            print(f"{'[dry] ' if dry else ''}{shown}: -{dropped} overnight")

    verb = "would clean" if dry else "cleaned"
    print(f"\n{verb} {tot_files} file(s) of {len(files)} scanned; "
          f"{tot_dropped} overnight rows dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
