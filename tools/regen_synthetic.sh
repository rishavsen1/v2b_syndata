#!/usr/bin/env bash
# Regenerate the scriptable synthetic dataset dirs after the calibration/noise
# fixes (overnight C12, <30-min filter, ACN tz). Runs sequentially to avoid
# CPU oversubscription. Ad-hoc dirs (output, output2, output3, outputs,
# outputs_new) have no reproducible command and are NOT regenerated here.
set -uo pipefail
cd "$(dirname "$0")/.."

# Wait for any in-flight sensitivity sweep to finish first.
while pgrep -f "sensitivity_sweep" >/dev/null 2>&1; do sleep 10; done

echo "=== [1/2] sweep ==="
rm -rf data/sweep/scenarios
python tools/run_bench_sweep.py --output data/sweep --skip-figures

echo "=== [2/2] paper_bench ==="
rm -rf data/paper_bench/scenarios
python tools/paper_bench.py --output data/paper_bench

echo "=== validate: overnight / <30min across regenerated synthetic dirs ==="
python3 - <<'PY'
import glob, csv
for d in ("sensitivity", "sweep", "paper_bench"):
    tot=ov=u30=0
    for f in glob.glob(f"data/{d}/**/sessions.csv", recursive=True):
        with open(f) as fh:
            r=csv.DictReader(fh)
            if "arrival" not in (r.fieldnames or []): continue
            for x in r:
                tot+=1
                if x["arrival"][:10]!=x["departure"][:10]: ov+=1
                if int(x["duration_sec"])<1800: u30+=1
    print(f"{d}: sessions={tot} overnight={ov} <30min={u30}")
PY
echo "=== regen done ==="
