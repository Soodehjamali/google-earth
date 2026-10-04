# Legacy Consolidation — Product Sign-off Contract (P7)

**Status:** DECISION/CONTRACT ONLY. This document records product decisions. It authorizes
no code change by itself; route migrations happen in subsequent phases.

**Source of truth for technical facts:** the P6 Final Report — Final Product Sign-off Audit
(read-only repository audit, 0 files changed). This document converts the verified P6
findings into explicit product decisions. It introduces no new technical claims.

**How to read this document:** each route section distinguishes three things:

1. **Verified technical facts (P6)** — what the code does today.
2. **Product decision** — what is accepted / held.
3. **Future engineering** — what is explicitly out of scope for this phase.

---

## 1. Vegetation — `/vegetation` → `/agriculture/vegetation`

### 1.1 Verified technical facts (P6)

- Legacy `/vegetation` (`frontend/src/pages/Vegetation.tsx`) provides: NDVI/EVI/SAVI/NDWI
  stat blocks; a single `vegetation_health` verdict; a one-sentence `interpretation`;
  hardcoded KPI thresholds (`>0.4` good / `>0.2` warning; health mapping
  excellent/good/moderate/poor/bare from NDVI mean cut-offs 0.6/0.4/0.3/0.2 in
  `backend/app/services/earth_engine/statistics.py`); a full percentile table; an NDVI
  trend chart; a map.
- Comprehensive `/agriculture/vegetation` (`frontend/src/components/agriculture/domainPages.ts`,
  `backend/app/services/agriculture/vegetation.py`) provides: NDVI, EVI, SAVI, MSAVI,
  NDRE, LAI, FAPAR, FCOVER, middle-canopy dryness proxy (explicitly proxy-labeled),
  monthly optical + radar temporal profiles with anomaly/change/joint/concordance
  information, per-metric evidence, provenance, validation, and spatial outputs.
- NDWI is intentionally served under Water, not Vegetation.
- P6 verified the legacy `/timeseries` chart path returns empty in production
  (no producer writes `TimeSeries` rows or `result_data["timeseries"]`).

### 1.2 Product decision — APPROVED

**Accept the removal of:**

- vegetation health verdict;
- interpretation sentence;
- hardcoded KPI thresholds.

Do NOT reintroduce them. NDWI remaining under Water is accepted and is not considered loss.

### 1.3 Future engineering

None required before migration.

---

## 2. Climate — `/climate` → `/agriculture/climate`

### 2.1 Verified technical facts (P6)

- Legacy `/climate` (`frontend/src/pages/Climate.tsx`) shows: temperature mean/min/max,
  precipitation total, evapotranspiration total, ERA5-Land ~11 km label, a temperature
  line chart and a precipitation bar chart.
- P6 verified the old combined temperature/precipitation chart has **no real production
  data path**: the contracted `TimeSeriesPoint` (`backend/app/schemas/analysis.py`)
  carries only ndvi/evi/savi/ndwi, and no producer ever writes temperature/precipitation
  series. It was not a functioning production capability.
- Comprehensive `/agriculture/climate` provides: temperature mean/min/max, VPD, relative
  humidity, wind speed, solar radiation, PAR, precipitation, GDD, a real monthly
  air-temperature profile through the P4 `climate + thermal` routing fix
  (`frontend/src/components/agriculture/request.ts`, `domainPages.ts`), plus provenance,
  evidence, validation, and spatial output.
- Precipitation remains scalar/period-total (locked by `p4.test.ts`: no precipitation
  temporal profile). ET belongs to Water. Anomaly/stress information belongs to
  Stress & Irrigation.

### 2.2 Product decision — APPROVED

**Accept:**

- precipitation remaining scalar-only;
- ET being represented under Water;
- anomaly/stress information being represented under Stress & Irrigation;
- removal of the old combined temperature/precipitation chart because it was not a
  functioning production capability.

Do NOT create a precipitation temporal series in this phase.

### 2.3 Future engineering

None required before migration.

---

## 3. Water — `/water` → `/agriculture/water`

### 3.1 Verified technical facts (P6)

- Legacy `/water` (`frontend/src/pages/Water.tsx`) shows: NDWI, soil moisture,
  precipitation, and a single `stress_level` verdict.
- P6 verified `stress_level` is backed by a real legacy contract based on NDWI
  thresholds (`backend/app/services/analysis_service.py`, covered by
  `backend/tests/unit/test_analysis_service.py`).
- Comprehensive deliberately does not expose a combined overall water-stress score. It
  provides individual water/moisture/ET indicators with detailed evidence
  (`frontend/src/components/agriculture/domainPages.ts` water + stress-irrigation configs).

### 3.2 Product decision — APPROVED

**Accept removal of the legacy `stress_level` verdict.**

Do NOT create:

- a replacement combined stress score;
- new thresholds;
- a new verdict;
- a `composite_stress` KPI.

Keep individual indicators and their evidence.

### 3.3 Future engineering

None required before migration.

---

## 4. Landcover — `/landcover` → `/agriculture/land-crop`

### 4.1 Verified technical facts (P6)

- Legacy `/landcover` (`frontend/src/pages/LandCover.tsx`) shows: IGBP classes,
  percentages, dominant class, per-class km², Total Area km² KPI, hardcoded class palette.
- P6 verified Comprehensive provides: authoritative IGBP class names, class codes,
  percentage, percent_of_geometry, pixel counts, dominant class, QC information,
  Dynamic World context, and WorldCereal crop context.
- The Comprehensive land-cover contract has **no geometry-area field** suitable for
  deriving km². Per-class and total-area km² figures therefore cannot be reproduced
  without fabrication.
- `temporary_crop_area.stats.valid_area_sq_m` is the **classified** area
  (`valid_pixels × pixel area`, `backend/app/services/agriculture/crop.py`) and must
  NOT be interpreted as total geometry area. Total geometry area travels separately
  (warnings only); the metric value itself stays a share fraction.

### 4.2 Product decision — APPROVED

**Accept removal of:**

- per-class km²;
- Total Area km² KPI;
- legacy hardcoded class palette.

Use authoritative taxonomy, percentages, pixel counts, and dominant class instead.

Do NOT invent or derive geometry area. Do NOT reuse `temporary_crop_area` as total
land-cover area.

### 4.3 Future engineering

None required before migration.

---

## 5. Historical — `/historical` → `/agriculture/history` — HOLD

### 5.1 Verified technical facts (P6)

- Legacy `/historical` (`frontend/src/pages/Historical.tsx`) provides: 2020–2026 year
  chips, per-year analysis, per-year NDVI series, comparison chart, per-year summary table.
- Comprehensive `/agriculture/history` provides substantially deeper analytical metrics:
  NDVI absolute/relative/standardized anomaly, percentile context, trend, Mann-Kendall
  trend, anomaly persistence, change shift, climate trend, season timing history,
  5-year baseline logic, and the P1 year-over-year NDVI comparison.
- `MAX_TEMPORAL_MONTHS = 36` (`backend/app/services/agriculture/temporal_section.py`):
  a single Comprehensive request cannot reproduce a 2020–2026 comparison. Longer windows
  yield an empty temporal section with a limitation, not data.
- Comprehensive does not currently reproduce the old per-year summary table.

### 5.2 Product decision — HOLD (do NOT migrate yet)

**`/historical` remains legacy** until a separate product decision is made regarding:

1. acceptable comparison window;
2. whether the per-year summary table is required;
3. whether multi-request historical comparison is required.

Do NOT change the 36-month limit. Do NOT implement multi-request comparison.
Do NOT migrate `/historical` in the phases authorized below.

### 5.3 Future engineering (separate decision, not this phase)

Multi-request historical comparison, an extended temporal bound, and/or a per-year
summary equivalent — only if the separate product decision requires them.

---

## 6. Product policy

### 6.1 No silent recreation of legacy verdicts

The Comprehensive architecture is evidence-first. Do not recreate legacy health scores,
stress scores, or threshold-based verdicts unless explicitly approved as a new product
feature.

### 6.2 No fabricated data

Do not create:

- precipitation temporal profiles without backend support;
- geometry area from unrelated classified-area fields;
- unsupported historical periods;
- synthetic time-series values.

### 6.3 Domain separation is intentional

Some capabilities moved between domains. This is not considered loss when the capability
remains available elsewhere:

- NDWI → Water;
- soil moisture → Soil;
- ET → Water;
- stress/anomaly indicators → Stress & Irrigation;
- LST → Thermal.

---

## 7. Decision matrix (approved)

| Route         | Decision | Approved product differences                                                 | Engineering required before migration |
| ------------- | -------- | ---------------------------------------------------------------------------- | ------------------------------------- |
| `/vegetation` | APPROVED | health verdict/interpretation/thresholds removed; NDWI in Water              | None                                  |
| `/climate`    | APPROVED | precipitation scalar-only; ET/anomalies elsewhere; dead legacy chart removed | None                                  |
| `/water`      | APPROVED | legacy stress_level removed; no replacement combined score                   | None                                  |
| `/landcover`  | APPROVED | km² and legacy palette removed                                               | None                                  |
| `/historical` | HOLD     | 36-month limit + missing yearly summary require decision                     | Separate product decision             |

Routes are not ranked. Order follows the audit scope only.

---

## 8. Migration authorization

Routing migration is authorized for ONLY:

- `/vegetation`
- `/climate`
- `/water`
- `/landcover`

Migration of `/historical` is NOT authorized. The actual route migrations happen in
subsequent phases, which may migrate only the four APPROVED routes above.

---

## 9. Change record

- P7: created this contract from the verified P6 audit findings. Documentation artifact
  only — no routes, navigation, components, backend, API contracts, schemas, tests,
  metrics, thresholds, UI, or pages were changed.
