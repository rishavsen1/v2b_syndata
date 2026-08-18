#!/usr/bin/env bash
# Generic building-major campus runner (TEMPLATE).
#
# Runs each single-building split config (SPLIT/b*.yaml) through generate-multi
# into a building-major tree:  <OUT>/b{i}/<MONTH>/<sample>/ .
# Sequential over buildings; each building parallelizes internally via --workers.
#
# RESUMABLE: a building whose batch_manifest.json reports top-level
# status=succeeded is skipped, so re-running continues an interrupted run.
# (Checks the TOP-LEVEL batch status, not the per-sample "succeeded" strings —
#  a `partial` building is correctly re-run.)
#
# Prepare a split dir first:
#   uv run python tools/split_campus_config.py configs/campus_base.yaml
#
# Usage:
#   tools/run_campus.sh [WORKERS]
# Config via environment (defaults shown):
#   SPLIT=configs/_campus_base_split   dir of per-building b*.yaml split configs
#   OUT=data/output/campus_base        output root (building-major)
#   START=2024-01                      first month (inclusive, YYYY-MM)
#   END=2024-06                        last  month (inclusive, YYYY-MM)
#   SAMPLES=100                        samples per month
#   NOISE=clean                        batch noise profile
#   WORKERS=20                         internal parallelism (also arg $1)
#
# Example — 12 months, 150 samples, a different split/out:
#   SPLIT=configs/_campus_base_split OUT=data/output/campus_base \
#   START=2024-01 END=2024-12 SAMPLES=150 tools/run_campus.sh 30
set -uo pipefail
cd /home/rishav/programs/v2b_syndata

SPLIT="${SPLIT:-configs/_campus_base_split}"
OUT="${OUT:-data/output/campus_base}"
START="${START:-2024-01}"
END="${END:-2024-06}"
SAMPLES="${SAMPLES:-100}"
NOISE="${NOISE:-clean}"
WORKERS="${1:-${WORKERS:-20}}"
mkdir -p "$OUT"

mapfile -t CFGS < <(ls "$SPLIT"/b*.yaml 2>/dev/null | sort -V)
N=${#CFGS[@]}
[ "$N" -gt 0 ] || { echo "no split configs in $SPLIT — run tools/split_campus_config.py first"; exit 2; }

echo "=== campus runner: ${N} buildings, ${WORKERS} workers, ${START}..${END} x${SAMPLES}/mo, noise=${NOISE}"
echo "===   split=${SPLIT}  out=${OUT}"
for cfg in "${CFGS[@]}"; do
  bid="$(basename "$cfg" .yaml)"            # b1, b2, … (also handles b11+)
  man="$OUT/${bid}/batch_manifest.json"
  if [ -f "$man" ] && \
     uv run python -c "import json,sys;sys.exit(0 if json.load(open('$man')).get('status')=='succeeded' else 1)" 2>/dev/null; then
    echo "=== [$(date +%H:%M:%S)] ${bid} already succeeded — skip ==="
    continue
  fi
  echo "=== [$(date +%H:%M:%S)] ${bid} starting ==="
  uv run python -m v2b_syndata.cli generate-multi \
    --config "$cfg" \
    --start-month "$START" --end-month "$END" --samples-per-month "$SAMPLES" \
    --noise-profile "$NOISE" --workers "$WORKERS" \
    --output-dir "$OUT/${bid}/" --force
  echo "=== [$(date +%H:%M:%S)] ${bid} DONE ==="
done
echo "=== campus runner: ALL ${N} BUILDINGS COMPLETE [$(date +%H:%M:%S)] ==="
