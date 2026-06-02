#!/usr/bin/env python3
"""Regenerate the ad-hoc batch output dirs (output, output2, ... ) from their
own batch_manifest.json, so the calibration/<30-min/overnight fixes propagate
into them too. Each manifest records the exact scenario / month range / samples
/ seed / noise / overrides, so the regen is faithful.

Usage: python tools/regen_batch_dirs.py [dir ...]   (default: all 5 ad-hoc dirs)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from v2b_syndata.batch import run_batch

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "configs"
DEFAULT = ["output", "output2", "output3", "outputs", "outputs_new"]


def main(argv: list[str]) -> int:
    dirs = argv or DEFAULT
    for d in dirs:
        out = REPO / "data" / d
        man = out / "batch_manifest.json"
        if not man.exists():
            print(f"SKIP {d}: no batch_manifest.json")
            continue
        m = json.loads(man.read_text())
        print(f"=== regen {d}: {m['scenario_id']} {m['start_month']}..{m['end_month']} "
              f"x{m['samples_per_month']} seed_base={m.get('seed_base', 0)} ===")
        run_batch(
            scenario_id=m["scenario_id"],
            output_dir=out,
            config_dir=CONFIG,
            start_month=m["start_month"],
            end_month=m["end_month"],
            samples_per_month=int(m["samples_per_month"]),
            workers=int(m.get("workers", 4)),
            seed_base=int(m.get("seed_base", 0)),
            noise_profile=m.get("noise_profile", "tmyx_stochastic"),
            extra_overrides=m.get("extra_overrides", {}),
            force=True,
        )
    print("=== validate: overnight / <30min ===")
    import csv, glob
    for d in dirs:
        tot = ov = u30 = 0
        for f in glob.glob(f"data/{d}/**/sessions.csv", recursive=True):
            with open(f) as fh:
                r = csv.DictReader(fh)
                if "arrival" not in (r.fieldnames or []):
                    continue
                for x in r:
                    tot += 1
                    if x["arrival"][:10] != x["departure"][:10]:
                        ov += 1
                    if int(x["duration_sec"]) < 1800:
                        u30 += 1
        print(f"  {d}: sessions={tot} overnight={ov} <30min={u30}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
