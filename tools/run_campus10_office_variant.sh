#!/usr/bin/env bash
# Generate ONE weather variant of the 10-building ACN office campus
# (configs/campus10_office_variants/) in building-major layout:
#   data/output/campus10_office_<variant>/bybuildings/b1 .. b10/<MONTH>/<sample>/
#
# Usage:
#   ./tools/run_campus10_office_variant.sh slight
#   ./tools/run_campus10_office_variant.sh moderate
#
# Defaults: 12 months x 150 samples/month = 1,800 samples/building (18,000
# units/variant). Pilot slice:
#   MONTHS_END=2024-01 SAMPLES=3 ./tools/run_campus10_office_variant.sh slight
#
# WORKERS defaults to a CPU-aware value (half the idle cores, min 2).
# On a dedicated machine, override: WORKERS=24 ./tools/run_... slight
#
# Portable: repo root derived from this script's location.
set -euo pipefail
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

VARIANT=${1:?usage: run_campus10_office_variant.sh <slight|moderate>}
case "$VARIANT" in slight|moderate) ;; *)
  echo "unknown variant '$VARIANT' (want slight|moderate)" >&2; exit 2;;
esac

SPLIT_DIR=configs/campus10_office_variants/_campus_10_office_${VARIANT}_split
OUT=${OUT:-data/output/campus10_office_${VARIANT}/bybuildings}
MONTHS_START=${MONTHS_START:-2024-01}
MONTHS_END=${MONTHS_END:-2024-12}
SAMPLES=${SAMPLES:-150}

if [ -z "${WORKERS:-}" ]; then
  ncpu=$(nproc)
  load=$(awk '{printf "%d", $1 + 0.5}' /proc/loadavg)
  idle=$(( ncpu - load ))
  [ "$idle" -lt 2 ] && idle=2
  WORKERS=$(( idle / 2 ))
  [ "$WORKERS" -lt 2 ] && WORKERS=2
fi
echo "=== campus10_office_$VARIANT: $MONTHS_START..$MONTHS_END x $SAMPLES samples, workers=$WORKERS ==="

mkdir -p "$OUT"

for i in $(seq 1 10); do
  echo "=== [$(date +%H:%M:%S)] $VARIANT b$i starting ==="
  uv run python -m v2b_syndata.cli generate-multi \
    --config "$SPLIT_DIR/b${i}.yaml" \
    --start-month "$MONTHS_START" --end-month "$MONTHS_END" \
    --samples-per-month "$SAMPLES" \
    --noise-profile clean --workers "$WORKERS" \
    --output-dir "$OUT/b${i}/" --force
  echo "=== [$(date +%H:%M:%S)] $VARIANT b$i DONE ==="
done
echo "=== VARIANT $VARIANT: ALL 10 BUILDINGS COMPLETE [$(date +%H:%M:%S)] ==="
