#!/usr/bin/env bash
# Master chain: building-major generate + analyze each campus in order
# (20, then 10_new, then 50). Resumable (per-building skip in
# run_campus_bmajor.sh; a finished campus is skipped at generation and its
# analysis re-run only if analysis.html is missing). Launch once and leave.
set -uo pipefail
cd /home/rishav/v2b_syndata
WORKERS="${WORKERS:-20}"

run_one() {
  local tag="$1"
  echo "############ campus${tag} GENERATION START $(date -u +%FT%TZ) ############"
  bash tools/run_campus_bmajor.sh "$tag" "$WORKERS"
  local html="data/output/campus${tag}/analysis.html"
  if [ -f "$html" ]; then
    echo "############ campus${tag} analysis.html exists — skip analysis ############"
  else
    echo "############ campus${tag} ANALYSIS START $(date -u +%FT%TZ) ############"
    uv run python tools/analyze_campus.py --base "data/output/campus${tag}"
  fi
  echo "############ campus${tag} COMPLETE $(date -u +%FT%TZ) ############"
}

run_one 20     2>&1 | tee data/output/campus20_run.log
run_one 10_new 2>&1 | tee data/output/campus10_new_run.log
run_one 50     2>&1 | tee data/output/campus50_run.log
echo "############ ALL CAMPUSES COMPLETE $(date -u +%FT%TZ) ############"
