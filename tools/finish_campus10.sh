#!/usr/bin/env bash
# Waits for run_campus10.sh to finish, then validates every building's
# batch_manifest.json (counts D5/hard errors) and generates the HTML report.
# Launched in background alongside the generation driver.
set -uo pipefail
cd /home/rishav/v2b_syndata
LOG=data/output/campus10/finish.log
: > "$LOG"

echo "[$(date +%F_%H:%M:%S)] finisher armed; waiting for generation to complete" >>"$LOG"
# Wait until the driver is gone AND the completion marker is in run.log.
while pgrep -f run_campus10.sh >/dev/null 2>&1; do sleep 60; done
# Grace: also wait for the marker (driver may exit via error); cap the wait.
for _ in $(seq 1 30); do
  grep -q "ALL 10 BUILDINGS COMPLETE" data/output/campus10/run.log 2>/dev/null && break
  sleep 10
done
echo "[$(date +%F_%H:%M:%S)] generation finished; validating" >>"$LOG"

# Aggregate validation across all 10 buildings.
uv run python - <<'PY' >>"$LOG" 2>&1
import json, glob
tot_units=tot_pass=tot_err=tot_warn=0
print(f"{'bldg':>5} {'units':>6} {'passed':>7} {'errors':>7} {'warnings':>9}")
for m in sorted(glob.glob("data/output/campus10/b*/batch_manifest.json")):
    b=m.split("/")[3]
    d=json.load(open(m))
    vs=d.get("validation_summary",{})
    u=vs.get("n_units",0); p=vs.get("n_passed",0)
    e=vs.get("total_errors",0); w=vs.get("total_warnings",0)
    tot_units+=u; tot_pass+=p; tot_err+=e; tot_warn+=w
    print(f"{b:>5} {u:>6} {p:>7} {e:>7} {w:>9}")
print("-"*40)
print(f"{'ALL':>5} {tot_units:>6} {tot_pass:>7} {tot_err:>7} {tot_warn:>9}")
print(f"\nRESULT: {'CLEAN — 0 hard errors' if tot_err==0 else str(tot_err)+' HARD ERRORS'} "
      f"across {tot_units} units")
PY

echo "[$(date +%F_%H:%M:%S)] building report" >>"$LOG"
uv run python tools/analyze_campus.py >>"$LOG" 2>&1
echo "[$(date +%F_%H:%M:%S)] DONE. Report at data/output/campus10/analysis.html" >>"$LOG"
touch data/output/campus10/.finished
