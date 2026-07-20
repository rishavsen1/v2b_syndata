# campus10_office_variants — packaged generation (new-machine handoff)

Two single-weather-profile versions of the ACN office campus
(`../campus_10_office.yaml`, which mixes slight/moderate 5/5):

| file | weather (all 10 buildings) | output tree |
|---|---|---|
| `campus_10_office_slight.yaml` | `slight` (~±1 °C / ±2 % solar) | `data/output/campus10_office_slight/bybuildings/` |
| `campus_10_office_moderate.yaml` | `moderate` (~±2.5 °C / ±5 % solar) | `data/output/campus10_office_moderate/bybuildings/` |

Split configs (`_campus_10_office_<variant>_split/b1..b10.yaml`) are
auto-generated — edit the parent yaml and re-run
`uv run python tools/split_campus_config.py configs/campus10_office_variants/<file>.yaml`.

Everything else is identical across variants: ACN-calibrated office populations
(`acn_{jpl,caltech}_office_{high,mid,low}`), load tiers 380–60 kW (peak-scaled),
chargers 25/15/10 at 50/50 uni-bi, fleet 1:1, PV 200/100/none with battery only
where PV, SoC chain on (arrival < prior departure, external use ∈ [10,50] %),
`sessions_soc.csv` emitted, noise `clean`.

## New-machine setup (once)

```bash
git clone <repo-url> v2b_syndata && cd v2b_syndata
./tools/setup.sh          # uv + deps + user-local EnergyPlus 23.2 + smoke gen
```

EPW weather files: `data/stations/*.epw` are NOT in git. Either copy them from
the old machine (13 MB — recommended, avoids network dependence):

```bash
rsync -av old-machine:v2b_syndata/data/stations/ data/stations/
```

…or let the first run download them (needs internet to climate.onebuilding.org).
Only `USA_CA_San.Jose-Mineta.Intl.AP.724945_TMYx.epw` is needed for this campus.

Optional warm-start: `data/load_pipeline_cache/` (EnergyPlus results, ~10 GB on
the old box) makes previously-simulated (building × weather-realization) units
near-instant. Skip it on a clean box — everything regenerates identically.

## Run

```bash
# Pilot slice first (ALWAYS): 1 month x 3 samples
MONTHS_END=2024-01 SAMPLES=3 ./tools/run_campus10_office_variant.sh slight

# Full: 12 months x 150 samples = 18,000 units per variant (~20 GB each)
WORKERS=24 nohup ./tools/run_campus10_office_variant.sh slight   > slight.log   2>&1 &
# after slight completes (or on another idle window):
WORKERS=24 nohup ./tools/run_campus10_office_variant.sh moderate > moderate.log 2>&1 &
```

`WORKERS` unset → auto (half the idle cores). Cold-cache cost is dominated by
EnergyPlus: ~35–45 s/unit for the large buildings down to ~10 s for small ones;
at 24 workers a full variant is roughly 4–7 h.

## Verify

Authoritative pass/fail is per building:
`data/output/campus10_office_<variant>/bybuildings/b{i}/batch_manifest.json`
→ `validation_summary` (want `n_failed: 0`). Do NOT run `cli validate` on the
optimus output dirs (schema mismatch — validation already ran inside each unit).

Determinism: any (config, seed) unit regenerated anywhere is byte-identical, so
partial corpora from different machines can be merged safely per building
(b1 from machine A + b2 from machine B is fine; do not mix within a building).
