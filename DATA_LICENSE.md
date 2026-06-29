# Data License — Creative Commons Attribution 4.0 International (CC BY 4.0)

The **synthetic datasets** produced by `v2b_syndata` (the generated CSVs —
`users`, `cars`, `chargers`, `sessions`, `building_load`, `pv_generation`,
`pv`, `battery`, `battery_dispatch`, `grid_prices`, `dr_events`) and the
original data artifacts committed in this repository (e.g.
`data/buildingload_reference/` characterizations, calibration result blocks in
`configs/populations.yaml`) are licensed under the **Creative Commons
Attribution 4.0 International License (CC BY 4.0)**.

- Human-readable summary: https://creativecommons.org/licenses/by/4.0/
- Full legal code: https://creativecommons.org/licenses/by/4.0/legalcode

## You are free to
- **Share** — copy and redistribute the material in any medium or format.
- **Adapt** — remix, transform, and build upon the material for any purpose,
  even commercially.

## Under the following terms
- **Attribution** — You must give appropriate credit, provide a link to the
  license, and indicate if changes were made.

**Suggested citation / attribution:**

> Synthetic V2B (Vehicle-to-Building) dataset generated with `v2b_syndata`
> (Rishav Sen and contributors, 2026), licensed under CC BY 4.0.

## Scope and third-party data

- The generator **source code** is licensed separately under the **MIT License**
  (see `LICENSE`).
- CC BY 4.0 here applies to the **synthetic output** and this repository's
  **original** data artifacts only.
- The behavioral models are **calibrated** from third-party charging datasets —
  **ACN-Data** (Caltech/JPL/Office001), **ElaadNL / 4TU**, **EV WATTS**, and
  **INL EV Project**. Those source datasets retain their **own upstream
  licenses and terms of use** and are **not** covered or relicensed by this
  file. Users intending to redistribute any derived artifact should consult the
  original providers' terms. No raw third-party session records are distributed
  in this repository (only fitted distribution parameters and synthetic output).
