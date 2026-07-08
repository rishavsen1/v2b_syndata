#!/usr/bin/env bash
# Generate the 10-building San Jose campus: one per-building batch run each into
# data/output/campus10/b1 .. b10 (building-major layout). 12 months x 150
# samples/month = 1,800 samples/building. Noise clean; per-building weather in
# each split config. Sequential runs; each parallelizes internally via --workers.
set -euo pipefail
cd /home/rishav/v2b_syndata

OUT=data/output/campus10
WORKERS=${WORKERS:-30}
mkdir -p "$OUT"

for i in $(seq 1 10); do
  echo "=== [$(date +%H:%M:%S)] building b$i starting ==="
  uv run python -m v2b_syndata.cli generate-multi \
    --config configs/_campus_split/b${i}.yaml \
    --start-month 2024-01 --end-month 2024-12 --samples-per-month 150 \
    --noise-profile clean --workers "$WORKERS" \
    --output-dir "$OUT/b${i}/" --force
  echo "=== [$(date +%H:%M:%S)] building b$i DONE ==="
done
echo "=== ALL 10 BUILDINGS COMPLETE [$(date +%H:%M:%S)] ==="
