#!/usr/bin/env bash
# Generate the 10-building San Jose OFFICE campus (ACN-calibrated, SoC chain,
# sessions_soc.csv): one per-building batch run each into
# data/output/campus10_office/bybuildings/b1 .. b10 (building-major layout).
#
# Defaults: 12 months x 150 samples/month = 1,800 samples/building.
# Override for a pilot:  MONTHS_END=2024-01 SAMPLES=3 ./tools/run_campus10_office.sh
#
# WORKERS defaults to a CPU-aware value: half the idle cores (leaves headroom
# for whatever else the box is running). Override with WORKERS=N.
set -euo pipefail
cd /home/rishav/v2b_syndata

OUT=${OUT:-data/output/campus10_office/bybuildings}
MONTHS_START=${MONTHS_START:-2024-01}
MONTHS_END=${MONTHS_END:-2024-12}
SAMPLES=${SAMPLES:-150}

if [ -z "${WORKERS:-}" ]; then
  ncpu=$(nproc)
  # 1-min load average, rounded to an integer.
  load=$(awk '{printf "%d", $1 + 0.5}' /proc/loadavg)
  idle=$(( ncpu - load ))
  [ "$idle" -lt 2 ] && idle=2
  WORKERS=$(( idle / 2 ))
  [ "$WORKERS" -lt 2 ] && WORKERS=2
fi
echo "=== campus10_office: months $MONTHS_START..$MONTHS_END x $SAMPLES samples, workers=$WORKERS ==="

mkdir -p "$OUT"

for i in $(seq 1 10); do
  echo "=== [$(date +%H:%M:%S)] building b$i starting ==="
  uv run python -m v2b_syndata.cli generate-multi \
    --config configs/_campus10_office_split/b${i}.yaml \
    --start-month "$MONTHS_START" --end-month "$MONTHS_END" \
    --samples-per-month "$SAMPLES" \
    --noise-profile clean --workers "$WORKERS" \
    --output-dir "$OUT/b${i}/" --force
  echo "=== [$(date +%H:%M:%S)] building b$i DONE ==="
done
echo "=== ALL 10 BUILDINGS COMPLETE [$(date +%H:%M:%S)] ==="
