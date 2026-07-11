#!/usr/bin/env bash
# Building-major generation for a campus: one per-building batch each into
# data/output/campus<TAG>/b1 .. b{N}  (same layout as campus10). 12 months x
# 150 samples/month = 1,800 samples/building. Noise clean; per-building weather
# from each split config (configs/_campus<TAG>_split/). Sequential buildings;
# each parallelizes internally via --workers.
#
# TAG is any suffix: a number ("20", "50") or a name ("10_new"). N (building
# count) is inferred from the number of split configs.
#
# RESUMABLE: a building whose data/output/campus<TAG>/b{i}/batch_manifest.json
# already reports status=succeeded is skipped, so re-running continues an
# interrupted run.
#
# Usage:  tools/run_campus_bmajor.sh <TAG> [WORKERS]
set -uo pipefail
cd /home/rishav/v2b_syndata

TAG="${1:?usage: run_campus_bmajor.sh <TAG> [WORKERS]}"
WORKERS="${2:-${WORKERS:-20}}"
SPLIT="configs/_campus${TAG}_split"
OUT="data/output/campus${TAG}"
mkdir -p "$OUT"

[ -d "$SPLIT" ] || { echo "missing $SPLIT — run tools/split_campus_config.py $TAG"; exit 2; }
N=$(ls "$SPLIT"/b*.yaml 2>/dev/null | wc -l)
[ "$N" -gt 0 ] || { echo "no split configs in $SPLIT"; exit 2; }

echo "=== campus${TAG} building-major: ${N} buildings, ${WORKERS} workers, out=$OUT ==="
for i in $(seq 1 "$N"); do
  man="$OUT/b${i}/batch_manifest.json"
  if [ -f "$man" ] && grep -q '"status": *"succeeded"' "$man" 2>/dev/null; then
    echo "=== [$(date +%H:%M:%S)] b$i already succeeded — skip ==="
    continue
  fi
  echo "=== [$(date +%H:%M:%S)] b$i starting ==="
  uv run python -m v2b_syndata.cli generate-multi \
    --config "$SPLIT/b${i}.yaml" \
    --start-month 2024-01 --end-month 2024-12 --samples-per-month 150 \
    --noise-profile clean --workers "$WORKERS" \
    --output-dir "$OUT/b${i}/" --force
  echo "=== [$(date +%H:%M:%S)] b$i DONE ==="
done
echo "=== campus${TAG}: ALL ${N} BUILDINGS COMPLETE [$(date +%H:%M:%S)] ==="
