# Phase 2 Engineering & Scientific Decisions Log

This document records architectural, scientific, and implementation decisions made during Phase 2 (Data-quality gating, climate fix, and coverage indicator).
Every decision prioritizes scientific honesty, conservative data gating, backward compatibility, and the preservation of A/B/C evidence levels.

---

## Decision 2.1.1: Three-State Quality Model Taxonomy & Legacy Mapping

- **Context:** Climate (ERA5-Land ~11 km) and coarse soil moisture (SMAP ~9 km, SoilGrids 250 m) provide valuable regional context, but treating them either as field-level measurements (causing false precision) or as "insufficient data" (hiding real data) is unacceptable.
- **Decision:**
  - Introduce `QualityState = "valid" | "coarse_context" | "unavailable"`.
  - Field-scale metrics (native pixel resolution $\le 30\text{ m}$ or pixel size $\le 50\%$ of polygon extent) with valid pixels receive `QualityState.VALID`.
  - Real satellite/reanalysis data with footprint larger than the polygon receive `QualityState.COARSE_CONTEXT`. They must carry `native_resolution_m` and support descriptions.
  - Missing data, masked pixels, QC failures, or computation errors receive `QualityState.UNAVAILABLE`.
  - **Legacy Database Deserialization Mapping:**
    - If `quality_state` is missing from JSON (legacy reports stored in PostgreSQL):
      - If `value is None` or `status in ("unavailable", "error", "insufficient_data")` or `quality in ("insufficient", "unavailable")` $\to$ `QualityState.UNAVAILABLE`.
      - Else if dataset/metric is known coarse (e.g. ERA5-Land, SMAP, TerraClimate, MOD16, or resolution $\ge 250\text{ m}$ on small parcels) $\to$ `QualityState.COARSE_CONTEXT`.
      - Else $\to$ `QualityState.VALID`.
- **Alternatives Considered:**
  1. *Binary (Valid / Invalid):* Rejected because it collapses regional climate into either field-level claims or total silence.
  2. *Five-state continuous grading:* Rejected as overly complex; three states clearly map to user-facing decisions (field action vs regional context vs missing).
- **Why Chosen:** Preserves existing database records, enforces zero data loss, and prevents diagnostic overreach.

---

## Decision 2.1.2: Hard Invariants on `coarse_context` Data

- **Context:** Scientific honesty requires that coarse-footprint products must never be used to draw field-level conclusions.
- **Decision:**
  - `coarse_context` metrics are NEVER allowed for within-field spatial zoning, clustering, or variability analysis.
  - `coarse_context` metrics CANNOT raise the evidence level of a field-level synthesis statement to Level A.
  - `coarse_context` metrics may only support regional-context statements (e.g. regional heatwave or drought conditions).
- **Why Chosen:** A 11 km ERA5 grid cell covers over 10,000 hectares; claiming within-field temperature variation from it is scientifically fraudulent.

---

## Decision 2.2.1: Elevation Reference for ERA5-Land Cell Footprint ($z_\text{cell}$)

- **Context:** ERA5-Land daily aggregation in GEE (`ECMWF/ERA5_LAND/DAILY_AGGR`) does not publish an orography/surface geopotential band in the Earth Engine catalog.
- **Decision:**
  - Use the project's primary digital elevation model (`NASA/NASADEM_HGT/001`, 30 m) averaged over the ERA5 cell footprint to compute $z_\text{cell}$.
  - Compute parcel elevation $z_\text{site}$ as the mean DEM over the polygon boundary (also storing min and max elevation).
- **Alternatives Considered:**
  1. *Using standard sea-level lapse without cell elevation:* Rejected because many Iranian pistachio regions (e.g., Kerman, Yazd, Rafsanjan) sit on high plateaus (1000–1800 m ASL), causing enormous systematic temperature biases.
  2. *Using GLO-30 or SRTM:* NASADEM is already registered as the primary verified DEM in `backend/app/services/agriculture/registry/datasets.py`.
- **Why Chosen:** Physically sound and utilizes the already validated 30 m elevation model.

---

## Decision 2.2.2: Scope of Elevation Correction and Handling of VPD/Humidity

- **Context:** Temperature drops with altitude, but lapse rates for humidity, VPD, precipitation, and wind are complex, non-linear, and microclimate-dependent.
- **Decision:**
  - Apply lapse-rate elevation correction **ONLY** to 2 m air temperatures (`temperature_2m`, `temperature_2m_min`, `temperature_2m_max`, and temperature feeding GDD).
  - Do **NOT** apply lapse rate to precipitation, solar radiation, or wind.
  - For VPD and relative humidity: Leave uncorrected, classify as `coarse_context`, carry an explicit note: `"VPD/رطوبت نسبی بدون تصحیح ارتفاعی گزارش می‌شود تا از فرضیات غیرکالیبره‌شده در مورد نقطه شبنم پرهیز شود."`
- **Alternatives Considered:**
  1. *Inventing a dewpoint lapse rate:* Strongly rejected. Dewpoint lapse rates vary drastically with air mass stability and humidity, risking false frost or drought alerts.
- **Why Chosen:** Strictly adheres to remote sensing physics and avoids fabricated constants.

---

## Decision 2.2.3: Configurable Lapse Rate and Uncertainty Bounds

- **Context:** Atmospheric environmental lapse rate varies between dry adiabatic (-9.8 °C/km) and saturated adiabatic (-4 to -6 °C/km). In arid Central Iran, nocturnal inversions and cold-air pooling frequently occur.
- **Decision:**
  - Default lapse rate set to $-6.5\ ^\circ\text{C/km}$ (standard tropospheric environmental lapse rate), tagged with `"needs calibration with local data"`.
  - Daytime temperature uncertainty: $\pm 1.0\ ^\circ\text{C}$.
  - Nighttime minimum temperature uncertainty: $\pm 2.0\ ^\circ\text{C}$, with an explicit Persian warning: `"تصحیح بر اساس نرخ افت دما در شب‌های آرام و صاف به دلیل احتمال وارونگی دمایی (inversion) و تجمع هوای سرد غیرقابل اتکا است."`
- **Why Chosen:** Protects growers from relying on simple lapse rates during inversion frost events.

---

## Decision 2.2.4: Local-Day Aggregation for Minimum/Maximum Temperatures

- **Context:** UTC days split the local night (Asia/Tehran = UTC+03:30) across two calendar dates, splitting the minimum night frost across consecutive UTC days.
- **Decision:**
  - Temperature minimum and maximum are evaluated over local midnight-to-midnight windows (`Asia/Tehran`).
  - GDD is accumulated over local days using corrected local $(T_\text{min} + T_\text{max})/2$.
- **Why Chosen:** Ensures agronomic accuracy for frost warnings and chill/heat accumulation.

---

## Decision 2.3.1: Metric Applicability for Coverage Denominator ($M$)

- **Context:** The total number of metrics in the catalog is ~118 across 9 domains. When a user requests specific domains (e.g. vegetation and water), counting all 118 metrics would misleadingly report low coverage (e.g. 15 of 118).
- **Decision:**
  - When `domains` is requested, $M$ (total) is strictly the number of registered metrics belonging to the requested domains.
  - When all domains are analyzed (`domains=None`), $M$ is the count of all registered active domain metrics.
  - Coarse context metrics ($K$) are strictly partitioned from valid field metrics ($N$).
  - Coverage ratio $= N / M$.
- **Why Chosen:** Unambiguous mathematical honesty.
