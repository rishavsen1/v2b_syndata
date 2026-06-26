# Calibration Notes

What was filtered, what fallbacks fired, what caveats apply to the fitted
parameters in `configs/populations.yaml`.

> This file is the calibration reference (items #1–#11), cited **by item
> number** from `populations.yaml`, scenario configs, and code — do not
> renumber. Renderer / noise / building-load engineering notes that used to
> live here moved to [`DESIGN_NOTES.md`](DESIGN_NOTES.md); open items live in
> [`PROJECT_TRACKER.md`](PROJECT_TRACKER.md). The faithfulness **results** — how
> closely generated data matches each source — are auto-generated in
> [`CALIBRATION_RESULTS.md`](CALIBRATION_RESULTS.md) by `tools/validate_calibration.py`.

## 1. Filter chain

| Stage | Filter | Notes |
|---|---|---|
| ACN-Data fetch | All sites: caltech, jpl, office001 | per D40 |
| Year window | 2019–2021 inclusive | per D41; 2018 caltech has 0% userID coverage |
| Session validity | `userID != null` | per D40 |
| Per-user filter | `n_sessions >= 5` | drops statistical noise |
| Battery inference | per-session via `WhPerMile` + `kWhRequested` | per D42 |
| Region assignment | first-match in `axes_distribution[*]` order | deterministic |

## 2. Fallback rates

The capacity-inference fallback fires when `WhPerMile` is missing, equals the
ACN-default sentinel value 299, or when miles/kWh requested are absent. The
overall rate is reported at runtime under
`calibration_metadata.capacity_inference_fallback_rate` and printed by
`v2b-syndata calibrate`. A high fallback rate indicates many sessions are
using the 60 kWh default, which biases the arrival-SoC fit toward the
fleet-median assumption.

## 3. δ proxy noise

δ (commute distance) is calibrated against `userInputs.milesRequested`, a
**user-stated charge target, not measured commute**. The miles requested is
a noisy proxy for actual round-trip commute distance because:
- It reflects how much the driver chose to charge for, not how far they drove.
- Direction-of-travel and round-trip ambiguity is unresolved.
- Some users habitually request more than they need (range buffer).

For Step 5, δ stays a hand-specified `dist_km` range per region with the
empirical mean from `milesRequested` reported as a diagnostic only (not
written into `region_distributions`). NHTS-anchored δ calibration is future
work.

## 4. Copula transform bias

The conversion `ρ_gaussian = 2·sin(π·ρ_spearman / 6)` is **exact only for
bivariate-normal copulas**. For the `(arrival_hour, dwell_hours)` joint with
truncnorm × weibull marginals, the transform is biased by < 0.05 in
simulation. Documented but not corrected; correcting would require a
likelihood-based copula fit per region.

## 5. Region overlap and assignment

Region bounds in `axes_distribution` may overlap. Assignment is **deterministic
first-match by axes_distribution order**: the user is assigned to the first
region whose `freq` and `consist` ranges contain `(φ, κ)`. This is enforced
by `tests/test_calibration/test_region_assignment.py::test_assign_first_match_deterministic`.

Users falling outside all regions are tracked under the `__unassigned__`
key. The unassigned rate is reported on `calibration_metadata.unassigned_user_rate`;
investigate if > 20%.

## 6. `ks_fit_quality` semantics

Each fitted distribution carries `ks_fit_quality`, computed as the
Kolmogorov-Smirnov statistic of the fit against the **same data the
distribution was fitted to** (training set). It is a goodness-of-fit
measure on the fit itself, NOT generalization to held-out data. Use it
only as a sanity check that the parametric family is reasonable.

Held-out KS validation (e.g. via train/test split or bootstrap resamples)
is deferred to **Step 5.5**. The placeholder soft check S2 in `validate.py`
emits a warning explaining this when calibration metadata is present.

## 7. Battery capacity sensitivity sweep

The notebook `notebooks/acn_calibration.ipynb` (cell 6) re-fits Beta(soc)
under fixed-capacity assumptions {40, 60, 75, 100} kWh. The reported alpha
and beta range across this sweep characterizes how sensitive the arrival-SoC
distribution is to the capacity heuristic. A wide range indicates the
arrival-SoC distribution should not be used for any analysis where battery
capacity matters quantitatively.

## 8. Required SoC at depart NOT calibrated

The renderer's required-SoC distribution remains the hardcoded
`TruncNorm(85, 5)` in `renderers/sessions.py`. Step 5 calibrates
arrival-SoC only. See DESIGN_NOTES.md item #22.

## 9. First real ACN-Data calibration (2026-05-06)

Run: `acn_data_2019_2021_20260506`. 42,451 sessions / 646 users post-filter.

**Region match against `consent_default`:** 12/646 users assigned (98.1% unassigned).
ACN-Data is overwhelmingly **low-frequency workplace charging** matching the
`occasional_visitor` (878 sessions) and `erratic` (421 sessions) regions. The
high-frequency `stable_commuter`/`flexible_local`/`irregular_distant` regions
get effectively zero ACN coverage.

**Implication:** the hand-specified `axes_distribution` for `consent_default`
does not reflect ACN-Data reality. Two paths forward:
- Re-anchor regions on the empirical (φ, κ) joint observed in ACN.
- Treat ACN as one population (workplace) and source other populations
  (residential, transit fleet) from different datasets.

Deferred to **Step 5.5** with NHTS-anchored δ work.

**B4 guard activations on this run** — fitter dropped 2 distributions whose
MLE estimates fell outside `DIST_PARAM_RANGES`:
- `occasional_visitor.arrival.sigma=6.45` (above `[0.01, 6.0]`)
- `occasional_visitor.soc_arrival.{alpha=267, beta=53}` (above `[0.01, 50.0]`)

The drops are warnings, not errors — generation continues using placeholder
formulas for the dropped distributions. The capacity-fallback rate (33.3%)
contributes to the soc_arrival pathology because many sessions cluster
arrival_soc near 1.0 when `kWhRequested` is small relative to the 60 kWh
default capacity assumption.

**KS fit quality on retained distributions:**
- `occasional_visitor.dwell.ks_fit_quality = 0.119` (Weibull marginal a stretch)
- `erratic.arrival.ks_fit_quality = 0.557` (TruncNorm wrong family for this region)
- Most others < 0.10.

The parametric families chosen (TruncNorm/Weibull/Beta) don't always fit the
empirical marginals; revisit family choice in Step 5.5.

## 10. φ definition fix: per-user active window

The original `aggregate_user_features` (commit `cb82e85`) computed
`φ = n_active_weekdays / n_weekdays_in_global_window`. Denominator was the
entire 3-year calibration span, so a user with 22 sessions concentrated in
a 6-month employment window got `φ ≈ 0.07` instead of `~0.7`. Result: 98%
of ACN users fell outside every region in `consent_default` and only 2/5
regions got any users.

Fixed in distribution_fitter / feature_extractor (commit TBD): denominator
is now the **per-user active window** `[first_session, last_session]`. Added
a second filter: `n_weekdays_in_user_window >= 5` to drop users whose active
span is too short for a stable estimate.

Re-run results:
- φ mean 0.074 → **0.201**
- φ max 0.588 → **1.000** (full range reachable)
- Users with φ >= 0.7: 0 → **18**
- Per-region session counts now: stable_commuter=87, irregular_distant=344,
  occasional_visitor=874, erratic=421. flexible_local still 0 (no users in
  that φ × κ box).
- Regions calibrated: 2/5 → **4/5**
- Manifest deep-channel calibrated leaves: 11 → **26**
- `unassigned_user_rate`: 0.981 → **0.952** (still high — see below).

The remaining 95% unassigned rate is a separate issue: most ACN users have
**high κ but low φ** (consistent arrival time, but only a few days per week).
That combination does not match any existing region in `consent_default`,
which pairs high κ only with high φ (stable_commuter) or pairs low φ only
with low κ (occasional_visitor, erratic). Re-anchoring regions on the
empirical (φ, κ) joint observed in ACN is the natural next step.
Deferred to Step 5.5 region re-anchor work.

## 11. Per-population calibration policy

ACN-Data calibration is no longer universal. Each population in
`configs/populations.yaml` declares `calibration_policy`:

- `acn_data` — ACN-Data fitted via `v2b-syndata calibrate`; region grid is
  ACN-anchored. Manifest source: `calibration:<provenance>`.
- `synthetic` — hand-authored `region_distributions`; no real-data fit.
  Manifest source: `hand_specified:<population_name>`. `v2b-syndata calibrate`
  skips with an informative log line.

Implemented: `evwatts` policy adds EV WATTS (DOE/EPRI, livewire.energy.gov)
as a second real-data source via the `CalibrationSource` protocol. Two
descriptors ship today — `evwatts_workplace_public` and `evwatts_dcfc_public`.
EV WATTS bulk releases historically lack stable per-driver IDs, so the source
synthesizes `user_id = "evwatts:port:<evse_id>"` and stamps
`calibration_metadata.user_id_strategy = "port_proxy"`. Consumers should read
the resulting (φ, κ) as **per-port shift-consistency**, not individual-driver
consistency. Schema TODO: the column-name constants in
`calibration/sources/evwatts.py` target a placeholder schema (start_time_utc,
end_time_utc, energy_kwh, evse_id, venue_type, rated_power_kw); confirm against
the real livewire release and bump `SCHEMA_VERSION` when the mapping changes.

**Bulk-data acquisition status (2026-05-30):** EV WATTS Public Database
(13M+ sessions, 50k+ ports, US-wide, 2019–) is hosted at
https://livewire.energy.gov/ds/evwatts/evwatts.public behind an
account-required single-page application (free account, no
programmatic API endpoint exposed in WebFetch / curl probing). Bulk
download requires manual portal navigation + likely NDA for full
attributes (per OSTI biblio 1970735, "researchers from partner
national labs can request additional attributes via
evwattsdata@energetics.com under a non-disclosure agreement"). Status:
**fixture-only with documented `EVWATTS_BULK_URL` env-var hook**.
Users with portal access can drop the bulk CSV into
`data/calibration/evwatts_cache/evwatts_<tag>.csv` and re-run
`v2b-syndata calibrate --population evwatts_workplace_public
--source-arg evwatts:release_tag=<tag>`. Real-data acquisition deferred
to v2 follow-up.

Implemented: `inl_ev_project` policy adds INL EV Project Phase 1 (Idaho
National Lab, avt.inl.gov, 2011–2013 ChargePoint+Blink fleet on ~24 kWh Leaf
and Volt EVs) as a third real-data source. One descriptor ships today:
`inl_residential_legacy`. Phase 1 release sheets exposed pseudonymized
Vehicle IDs (e.g. `Veh001`), so the source synthesizes
`user_id = "inl:vin:<vehicle_id>"` and stamps
`calibration_metadata.user_id_strategy = "vin_proxy"` — true per-driver
identity. Rows missing vehicle_id fall back to `inl:port:<evse_id>` and the
metadata strategy flips to `port_proxy`. Caveat: this is a **legacy fleet**
— do not mix with modern-battery scenarios (battery capacity assumptions
diverge). Schema TODO: column-name constants in
`calibration/sources/inl.py` (vehicle_id, start_time, end_time, energy_kwh,
evse_id, venue, evse_power_kw) target a placeholder schema; confirm against
the real avt.inl.gov Phase 1 release and bump `SCHEMA_VERSION` when the
mapping changes.

**Bulk-data acquisition status (2026-05-30):** INL EV Project Phase 1
captured ~4 million charging events across ~8,000 plug-in EVs in
2011–2014 (ECOtality-led ARRA project, INL-analyzed). Public outputs at
https://avt.inl.gov/project-type/ev-project.html are predominantly
aggregate technical reports (OSTI 1369632, 1244615). Session-level CSV
release was not located via public search or direct fetch. Status:
**fixture-only with documented `INL_BULK_URL` env-var hook**. Direct
INL contact would be required for the full Phase 1 corpus. Real-data
acquisition deferred to v2 follow-up.

Implemented: `elaadnl_open_2020` policy provides the fourth real-data
source. Geographic axis: EU coverage alongside the three US-based
sources. One descriptor ships today: `elaadnl_public_eu`.

**Real-data source (v2, 2026-05-30):** SmoothEMS met GridShield dataset,
"Electric Vehicle Charging Session Data of Large Office Parking Lot"
(a.s.r. living lab, Utrecht NL, Aug 2020 – Oct 2024), published via
4TU.ResearchData at
https://data.4tu.nl/datasets/80ef3824-3f5d-4e45-8794-3b8791efbd13 under
CC BY-NC-SA 4.0. Consortium output of ElaadNL + University of Twente +
a.s.r. + MENNEKES + Kropman + Amperapark; ElaadNL operates the data
API. 55,379 sessions / 3,409 pseudonymized EV identifiers / ~300
charging points.

**Why this dataset rather than the original ElaadNL Open Charging
Transactions:** the historical `platform.elaad.io/download-data/`
endpoint was retired; the current `data.elaad.nl` dashboard exposes
data only via interactive UI without a direct bulk-download link. The
4TU.nl Utrecht dataset is ElaadNL-collected charging data published
with a stable citable DOI, making it the closest available real-data
substitute. Loader file + class names + registry key + alias
(`elaadnl_open_2020` / "elaadnl") are preserved for back-compat with
the original PR (commit `6873127`).

**Schema substitution:** the 4TU.nl CSV has columns
`EV_id_x, start_datetime, end_datetime, total_energy, evse_uid, rail, channel,
capacity_kwh, ...` (semicolon-separated, UTF-8 BOM). Our fetcher
(`calibration/elaadnl_fetcher.py::_normalize_4tu_to_internal`) renames
these to the internal session-row schema
(`card_id, start_time, end_time, energy_kwh, evse_id, venue,
evse_power_kw`) and synthesizes `venue = "workplace"` and
`evse_power_kw = 11.0` (per README: 11 kW per plug, or 22 kW if single
plug active). The fixture CSV (75 rows) uses the internal schema
directly; the fetcher auto-detects which is in the cache.

**user_id strategy:** synthesizes `user_id = "elaadnl:card:<EV_id_x>"`
and stamps `calibration_metadata.user_id_strategy = "card_proxy"`.
Caveat: longitudinal identity is weaker than INL's vin_proxy — README
documents that a list of EV IDs were shared across drivers in the early
roll-out phase. Rows missing EV_id_x fall back to
`elaadnl:port:<evse_id>` and the metadata strategy flips to
`port_proxy`. Workplace context: 300+ charging points; charging IDs
identify a card/RFID, not a unique vehicle.

**TZ caveat:** 4TU.nl source CSVs ship naive Europe/Amsterdam
timestamps (UTC+1 winter / UTC+2 summer); for consistency with
ACN/EV WATTS/INL (which all treat naive timestamps as UTC) the source
localizes naive timestamps to UTC without shifting. Result:
per-session arrival_hour is offset by 1–2h vs. wall-clock Amsterdam
time. Distribution fits inherit the offset uniformly.

**Acquisition path for reproducibility:** download
`202410DatasetEVOfficeParking_v0.csv` from the 4TU.nl page
(direct URL pattern:
`https://data.4tu.nl/file/80ef3824-3f5d-4e45-8794-3b8791efbd13/<file-uid>`)
and place at `data/calibration/elaadnl_cache/elaadnl_utrecht_4tu_2024.csv`.
Then run:
```
v2b-syndata calibrate --population elaadnl_public_eu \
    --source-arg elaadnl:archive_tag=utrecht_4tu_2024 \
    --source-arg elaadnl:venue_filter=workplace
```

Future calibration sources (NHTS for δ) extend the policy enum without
breaking the generator.

### Population assignments

| population | policy | provenance |
|---|---|---|
| `consent_default` | synthetic | hand-authored, domain-informed |
| `acn_workplace_baseline` | acn_data | calibration:acn_data_2019_2021_<date> |
| `stable_commuter_heavy` | synthetic | (region_distributions still TODO) |
| `visitor_heavy` | synthetic | (region_distributions still TODO) |

### Real-ACN run on `acn_workplace_baseline`

`acn_data_2019_2021_20260506`. 42,451 sessions / 646 users post-filter.

| metric | acn_workplace_baseline | (vs old consent_default attempt) |
|---|---|---|
| regions calibrated | **5/5** (4/5 after 2026-06-01, see below) | 4/5 |
| n_users assigned | **634** | 31 |
| unassigned_user_rate | **0.019** | 0.952 |
| capacity fallback | 0.333 | 0.333 |

Per-region n_samples: rare_consistent 3,848; rare_inconsistent 1,424;
occasional_consistent 15,607; regular_charger 17,857; erratic 1,805.

KS fit quality varies (0.07–0.52); arrival fits are weakest. Family choice
(TruncNorm/Weibull/Beta) revisit deferred. soc_arrival fits are uniformly
high (~0.4); related to capacity-inference fallback rate.

> **2026-06-01 — ACN UTC→Pacific fix changed coverage.** ACN-Data is true UTC
> and CA sites; reading arrival in Pacific lowered arrival means ~16→~8. Because
> region assignment uses `kappa = 1 − std/mean(arrival_hour)` (origin-dependent),
> the shift re-bucketed users: the `erratic` (and for per-site cohorts also
> `rare_inconsistent`) regions emptied to ≤1 real user and fall back to
> placeholder distributions. Post-fix coverage: **acn_workplace_baseline 4/5,
> acn_jpl_baseline / acn_office001_baseline 3/5, acn_caltech_baseline 4/5**.
> Generated arrivals are sane (mean ~9–10). Fixing kappa to be origin-invariant
> + re-tuning the axes_distribution grid is tracked as a model-adequacy item
> (see docs/MODEL_SELECTION.md).

### Manifest stamps (post per-population policy)

S01 (consent_default) generation produces 35 deep-channel leaves all
stamped `hand_specified:consent_default`. Generation against
`acn_workplace_baseline` stamps the calibration provenance instead.
