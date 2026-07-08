# Zenodo deposit plan — campus-10 reference corpus (WS-F)

Status: **dry-run plan only.** No deposit was attempted (no Zenodo
credentials in the execution environment). Everything below is ready to
execute; the two items marked **USER ACTION** need the account owner.

## 1. What is deposited

`data/output/campus10/` — the 18,000-unit reference corpus the paper
releases (§7): 10 heterogeneous campus buildings × 12 months (2024) × 150
samples per building-month, clean noise profile, per-sample weather
realization re-simulated through EnergyPlus 24.1.

Measured inventory (2026-07-08, `du -sb` / `find`):

| item | value |
|---|--:|
| total size | 19,538,083,399 bytes (19 GiB; `du -sh` → 19G) |
| total files | 234,015 |
| dataset units | 18,000 (each a directory `b<N>/<MON>2024/<sample>/`) |
| files per unit | 13 CSV/JSON (`sessions`, `building_load`, `cars`, `chargers`, `battery`, `pv`, `pv_generation`, `grid_prices`, `weather_data`, `occupancy`, `policies`, `dso_commands` + `multi_building_config.json`) |
| per-building batch manifest | `b<N>/batch_manifest.json` (10 files; seeds, per-unit `duration_sec`, validation summaries) |
| corpus-level docs | `analysis.html`, `analysis_summary.csv` (18,000-row per-unit metrics), `run.log`, `finish.log` |

The per-unit `multi_building_config.json` is the authoritative record of
each unit's weather draw (the batch-level `weather_profile` field is
`"none"` because weather realization is configured per building — §7
"Corpus integrity" paragraph).

## 2. Packaging (Zenodo limits: ≤100 files/record, 50 GB default quota)

234,015 raw files exceed the per-record file cap, so package one tar per
building plus the corpus-level docs (15 files total, well under limits):

```bash
cd data/output
mkdir -p zenodo_staging
for b in b1 b2 b3 b4 b5 b6 b7 b8 b9 b10; do
  tar -C campus10 -czf zenodo_staging/campus10_${b}.tar.gz ${b}
done
cp campus10/analysis.html campus10/analysis_summary.csv zenodo_staging/
# corpus README: regeneration recipe + license + schema pointer
# (write from docs/DATASHEET.md + croissant.json before upload)
cp ../../croissant.json ../../docs/DATASHEET.md zenodo_staging/
( cd zenodo_staging && sha256sum * > SHA256SUMS )
```

Expected staging size ≈ 4–6 GB (the CSVs compress well; measure before
upload). Keep `SHA256SUMS` in the record so integrity is checkable.

## 3. Proposed Zenodo metadata

| field | value |
|---|---|
| Upload type | Dataset |
| Title | `v2b-syndata Campus-10 Reference Corpus: 18,000 Coupled Synthetic Vehicle-to-Building (V2B) Dataset Units` |
| Authors | the paper author list, with affiliations + ORCIDs (**USER ACTION**: confirm order; repository metadata names Vanderbilt University; contact rishav.sen@vanderbilt.edu) |
| Description | From `docs/DATASHEET.md` motivation + §7 "What is released": 10 buildings × 12 months × 150 seeded samples of coupled 15-min V2B data (EnergyPlus building load, calibrated EV sessions, tariffs, DR, PV, storage specs, exported weather); every unit regenerates bitwise from (generator revision, configuration, seed); SoC channels are modeled priors, never measurements. |
| License | **CC BY 4.0** (data; matches `DATA_LICENSE.md`; generator code stays MIT in the repo) |
| Keywords | synthetic data; electric vehicles; EV charging; vehicle-to-building; V2B; building energy; EnergyPlus; demand response; load forecasting; benchmark |
| Related identifiers | `IsSupplementTo` → the KDD paper (add on acceptance); `IsDerivedFrom`/`IsSourceOf` → `https://github.com/rishavsen1/v2b_syndata` (generator, exact commit tag) |
| Version | `1.0.0` (corpus generated at the commit recorded in `b*/batch_manifest.json` / `run.log`) |
| Notes | "Fully synthetic — no personal data. Calibration used public corpora aggregated to distribution parameters; no record-level content is redistributed." |

## 4. Deposit steps (Zenodo REST API)

```bash
export ZENODO_TOKEN=...   # USER ACTION: create at zenodo.org → Applications
                          # → Personal access tokens (scopes: deposit:write,
                          # deposit:actions). Use sandbox.zenodo.org first.
API=https://zenodo.org/api

# 4.1 create the deposition (empty draft)
DEP=$(curl -s -H "Authorization: Bearer $ZENODO_TOKEN" \
      -H "Content-Type: application/json" -X POST -d '{}' \
      $API/deposit/depositions)
ID=$(echo "$DEP" | jq -r .id)
BUCKET=$(echo "$DEP" | jq -r .links.bucket)

# 4.2 DOI reservation — **USER ACTION / decision point**
#     The draft's metadata.prereserve_doi.doi (e.g. 10.5281/zenodo.NNNNNNN)
#     is reserved as soon as the draft exists; put THIS DOI in the paper PDF
#     before submission. Nothing is public until "publish" is pressed.
echo "$DEP" | jq .metadata.prereserve_doi

# 4.3 set metadata (§3 above, as JSON)
curl -s -H "Authorization: Bearer $ZENODO_TOKEN" \
     -H "Content-Type: application/json" -X PUT \
     -d @zenodo_metadata.json $API/deposit/depositions/$ID

# 4.4 upload the 15 staged files (new files API streams large files;
#     ~19 GB raw → a few hours on a 100 Mbit uplink; run under tmux)
for f in data/output/zenodo_staging/*; do
  curl -s -H "Authorization: Bearer $ZENODO_TOKEN" \
       --upload-file "$f" "$BUCKET/$(basename "$f")"
done

# 4.5 verify checksums returned by the bucket listing vs SHA256SUMS
curl -s -H "Authorization: Bearer $ZENODO_TOKEN" "$BUCKET" | jq '.contents[] | {key, checksum}'

# 4.6 publish — USER ACTION (irreversible; do after paper freeze):
# curl -s -H "Authorization: Bearer $ZENODO_TOKEN" -X POST \
#      $API/deposit/depositions/$ID/actions/publish
```

## 5. Risks / notes

- **Quota:** default Zenodo record quota is 50 GB — the ~19 GB corpus fits
  without a quota request (staging tars are smaller still).
- **Bitwise recoverability:** the corpus regenerates from the repo alone
  (`tools/run_campus10.sh`, seeds in the batch manifests), so the deposit is
  a convenience artifact; state this in the description.
- **Sandbox first:** repeat §4 against `https://sandbox.zenodo.org/api`
  end-to-end (separate token) before the real deposit.
- **DOI in PDF:** CFP requires links in the submitted PDF — reserve the DOI
  (step 4.2) before the Jul 24 PDF freeze; publishing can wait until
  acceptance if preferred (reserved DOIs resolve only after publish; say
  "DOI reserved" in the availability statement if unpublished at submission).
