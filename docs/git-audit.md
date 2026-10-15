# Comprehensive Git Audit & Repository Hygiene Plan

This document details the inventory of untracked files, analyzes commit sweeps across Phases 1, 2, and Closeout, and proposes an orderly reconciliation plan.

---

## 1. Inventory & Classification of Untracked Files (`git status --short`)

Untracked files are classified into six categories. Dependencies of production runtime and test suites are explicitly identified.

### Category A: Source Code (`backend/app/`, `frontend/src/`)
These files contain feature implementations developed during earlier project phases (e.g., P0-HISTORY, P-AGRI-1, P-AGRI-SOIL, P-AGRI-8). **The application runtime and UI directly depend on them.**

| File Path | Description | Dependency Status |
|:---|:---|:---|
| `backend/app/services/agriculture/history_store.py` | PostgreSQL persistence store for analysis history | **Required** by `/api/v1/agriculture/history` |
| `backend/app/services/agriculture/pest_disease_inspection.py` | Phytosanitary pest & disease risk inference engine | **Required** by Pest & Disease section |
| `backend/app/services/agriculture/regime.py` | Agricultural bioclimatic regime determination | **Required** by synthesis rule engine |
| `backend/app/services/agriculture/registry/soil_datasets.py` | ISRIC SoilGrids 2.0 dataset registrations | **Required** by Soil Intelligence module |
| `backend/app/services/agriculture/soil_intelligence.py` | Soil texture, depth profiles & chemical modeling | **Required** by Soil Intelligence section |
| `backend/app/services/agriculture/support.py` | Spatial point support calculation policy | **Required** by Point-geometry requests |
| `frontend/src/components/agriculture/AgricultureHistorySection.tsx` | Historical analysis browser & replay UI | **Required** by History view |
| `frontend/src/components/agriculture/AnalysisOverviewSection.tsx` | Primary KPI overview & summary cards | **Required** by main dashboard |
| `frontend/src/components/agriculture/GroundTruthForm.tsx` | Field observation entry form | **Required** by ground-truth workflow |
| `frontend/src/components/agriculture/GroundTruthValidationTable.tsx` | Satellite vs. ground truth comparison table | **Required** by validation tab |
| `frontend/src/components/agriculture/Historical10YearSection.tsx` | 10-year multi-sensor temporal trajectory charts | **Required** by historical tab |
| `frontend/src/components/agriculture/JalaliDatePicker.tsx` | Jalali solar calendar input component | **Required** by analysis form |
| `frontend/src/components/agriculture/KeyReadings.tsx` | Telemetry display cards | **Required** by dashboard |
| `frontend/src/components/agriculture/MapSearchBar.tsx` | Iranian city geocoding and search bar | **Required** by MapView navigation |
| `frontend/src/components/agriculture/OrchardHeatmapSwipeSection.tsx` | Split-screen swipe comparison of raster layers | **Required** by swipe tab |
| `frontend/src/components/agriculture/PestDiseaseInspectionSection.tsx` | Pest & disease risk inspection UI | **Required** by pest page |
| `frontend/src/components/agriculture/RawBandsInspectionSection.tsx` | Spectral band telemetry table | **Required** by P-AGRI-8 raw bands tab |
| `frontend/src/components/agriculture/SoilIntelligenceSection.tsx` | Soil properties display cards & caveats | **Required** by soil tab |
| `frontend/src/components/agriculture/SpatialIntelligenceSection.tsx` | Heatmap zoning and spatial interpretation | **Required** by spatial section |
| `frontend/src/components/agriculture/categorizedMetrics.ts` | Categorized metric mapping | **Required** by KPI grid |
| `frontend/src/components/agriculture/decisionSupport.ts` | Agronomic decision support recommendations | **Required** by DSS section |
| `frontend/src/components/agriculture/historyUtils.ts` | Client utilities for history API | **Required** by history store |
| `frontend/src/components/agriculture/mapSnapshot.ts` | PDF map snapshot renderer | **Required** by PDF report export |
| `frontend/src/components/agriculture/metricInterpretation.ts` | Threshold-based interpretations | **Required** by metric cards |
| `frontend/src/components/agriculture/persianDate.ts` | Centralized Jalali calendar conversions | **Required** across all UI dates |
| `frontend/src/components/agriculture/polygon.ts` | Geodesic area calculation & coordinate validation | **Required** by polygon drawing |
| `frontend/src/components/agriculture/rawBandsCatalog.ts` | 9-sensor satellite band specification catalog | **Required** by raw bands tab |
| `frontend/src/components/agriculture/reportModel.ts` | Structured print/PDF report data model | **Required** by report generation |
| `frontend/src/components/agriculture/support.ts` | Point support area formatting | **Required** by SupportNotice |
| `frontend/src/components/agriculture/unavailable.ts` | Data unavailability presentation helpers | **Required** by metrics |
| `frontend/src/pages/agriculture/PestDiseasePage.tsx` | Standalone pest & disease inspection page | **Required** by router |
| `frontend/src/utils/` | Utility helpers | Supplementary |

---

### Category B: Test Suites (`backend/tests/`, `frontend/src/.../__tests__/`)
These tests validate earlier feature milestones. Because they are untracked, clean `git worktree` checkouts do not execute them.

| File Path | Tests Count | Scope |
|:---|:---:|:---|
| `backend/tests/unit/agriculture/test_comparison_10y.py` | 8 | 10-year historical trajectory comparisons |
| `backend/tests/unit/agriculture/test_history_persistence.py` | 6 | PostgreSQL analysis history CRUD |
| `backend/tests/unit/agriculture/test_p_agri_1.py` | 5 | Agronomic regime rules & bare soil gating |
| `backend/tests/unit/agriculture/test_pest_disease_inspection.py` | 10 | 5-level phytosanitary risk hierarchy |
| `backend/tests/unit/agriculture/test_point_support.py` | 51 | Dual-geometry Point support & native buffer policies |
| `backend/tests/unit/agriculture/test_soil_intelligence.py` | 17 | SoilGrids 2.0 depth profiles & physical limits |
| `frontend/src/components/agriculture/__tests__/agriculture_history.test.ts` | 6 | History UI state & replay |
| `frontend/src/components/agriculture/__tests__/agriculture_submenus.test.ts` | 8 | Navigation submenus |
| `frontend/src/components/agriculture/__tests__/agronomic_decision_support.test.ts` | 14 | DSS agronomic rules |
| `frontend/src/components/agriculture/__tests__/data_coverage_p_agri_7.test.ts` | 12 | P-AGRI-7 coverage contracts |
| `frontend/src/components/agriculture/__tests__/hist10y_and_swipe.test.ts` | 10 | 10-year comparison and swipe tool |
| `frontend/src/components/agriculture/__tests__/interpretation_presentation.test.ts` | 11 | Heatmap presentation & caution banners |
| `frontend/src/components/agriculture/__tests__/map_navigation.test.ts` | 9 | Geocoding & map centering |
| `frontend/src/components/agriculture/__tests__/metric_interpretation.test.ts` | 15 | Qualitative agricultural thresholds |
| `frontend/src/components/agriculture/__tests__/pdf_and_report_model.test.ts` | 12 | PDF export & report model |
| `frontend/src/components/agriculture/__tests__/persian_date.test.ts` | 23 | Jalali calendar mathematical accuracy |
| `frontend/src/components/agriculture/__tests__/pest_disease_and_validation.test.ts` | 8 | Pest inspection & field validation |
| `frontend/src/components/agriculture/__tests__/polygon_drawing.test.ts` | 16 | Polygon validation & spherical area |
| `frontend/src/components/agriculture/__tests__/raw_bands_inspection_p_agri_8.test.ts` | 8 | Raw spectral bands catalog |
| `frontend/src/components/agriculture/__tests__/soil_intelligence.test.ts` | 16 | Soil intelligence display & lab warnings |
| `frontend/src/components/agriculture/__tests__/spatial_heatmap.test.ts` | 7 | Spatial heatmap MVP contract |

---

### Category C: Documentation (`*.md`, `*.txt`)
Internal audit notes and task prompts from earlier sprints:
- `P-AGRI-6-AUDIT.md`, `P-AGRI-7-AUDIT.md`, `P-AGRI-8-AUDIT.md`, `P-AGRI-8.1-AUDIT.md`
- `P-AGRI-SOIL-3B-AUDIT.md`, `P-AGRI-SOIL-4-AUDIT.md`
- `PROJECT_STATUS.md`
- `p_agri_soil_4_prompt.txt`, `temp_prompt.txt`

---

### Category D: Scratch Scripts & Temporary Diagnostics
One-off node/python test scripts used for interactive debugging:
- Node scripts: `check_page.mjs`, `check_ui_dates.mjs`, `debug_pdf_download_logs.mjs`, `debug_submit.mjs`, `extract_pdf_metadata.mjs`, `reproduce_step6.mjs`, `screenshot_pdf_pages*.mjs`, `take_ui_screenshots.mjs`, `test_actual_pdf_download.mjs`, `test_blob_hook.mjs`, `test_gee_single_tile.mjs`, `test_gee_tile_canvas.mjs`, `test_generate_perfect_snapshot.mjs`, `test_heatmap_chain.mjs`, `test_maplibre_state.mjs`, `test_pdf_btn.mjs`, `test_pdf_click.mjs`, `test_pest_disease_flow.mjs`, `test_pest_ground_truth.mjs`, `test_snapshot_direct.mjs`, `test_zoom16_snapshot.mjs`, `verify_fresh_pdf_download.mjs`
- Python diagnostics in backend: `backend/_fa12_*`, `backend/audit_tile_images.py`, `backend/check_smap_bands.py`, `backend/inspect_soilgrids.py`, `backend/probe_soil_catalog.py`, `backend/test_*.py`
- Scripts under `backend/scripts/` and root `scripts/`, `.antigravity/`

---

### Category E: Data Samples, Outputs & Rendered Artifacts
Generated test outputs, PDF captures, and JSON dumps:
- `ardakan_analysis_validation.json`, `ardakan_gee_result.json`, `ardakan_pest_disease.json`
- `backend/audit_tile_*.png`, `backend/audit_tiles_result.json`
- `backend/catalog_dump.json`, `backend/catalog_inventory.json`
- `backend/metric_coverage_audit.json`, `backend/_soil_probe_results.json`, `backend/_soilgrids_meta.json`
- `e2e_audit_results.json`, `fa12_live_result.json`, `ground_truth_test_report.json`, `heatmap_chain_audit.json`, `pest_disease_audit.json`
- `frontend/_fa12_browser/`, `frontend/_saved_analysis_sample.json`, `frontend/actual_downloaded_report*.pdf`, `frontend/rendered_report.html`, `frontend/setting.json`
- `scratch_step6_*.png`

---

### Category F: Credentials
- `backend/credentials/gee-key.json`:
  - **Audit Status**: Properly ignored in `.gitignore`.
  - **Verification**: `git ls-files backend/credentials` returns empty; `git log --all -- backend/credentials` confirms it was **never** committed.

---

## 2. Commit Sweep Analysis across History

An analysis of `git show --stat --oneline` on all commits from `071767b..HEAD` reveals that earlier uncommitted working-tree modifications were swept into two specific commits:

### A. Commit `517f2ba` (`fix(map): require N=5 consecutive failures before disabling tile provider and add active retry`)
- **Stated Scope**: Map tile error retry policy (N=5).
- **Actual Files Committed**: 46 files (+4,665 / -441 lines).
- **Swept Unrelated Changes**:
  - `backend/app/schemas/agriculture.py` (+677 lines): P0-HISTORY and full analysis response schemas.
  - `backend/app/services/agriculture/history.py` (+605 lines): History database store.
  - `backend/app/services/agriculture/synthesis.py` (+423 lines): Synthesis rule engine.
  - `frontend/src/components/agriculture/AnalysisRequestForm.tsx` (+439 lines).
  - `frontend/src/pages/agriculture/DomainPage.tsx` (+333 lines).
  - `frontend/src/types/index.ts` (+505 lines).
- **Assessment**: A broad staging sweep captured in-progress history and synthesis implementations.

### B. Commit `d68576e` (`fix(frontend): implement FormattedNumber with LTR isolation, U+2212 minus, and explicit coordinate labeling`)
- **Stated Scope**: Persian number formatting with LTR isolation.
- **Actual Files Committed**: 10 files (+4,381 / -89 lines).
- **Swept Unrelated Changes**:
  - `frontend/src/components/MapView.tsx` (+1,648 lines): Full interactive MapLibre GL implementation.
  - `frontend/src/components/agriculture/AgronomicDecisionSupportSection.tsx` (+1,302 lines): Entire DSS recommendation UI.
  - `frontend/src/components/agriculture/pdfReport.ts` (+779 lines): Client-side PDF generation engine.
  - `frontend/src/components/agriculture/CategorizedMetricCards.tsx` (+339 lines).
- **Assessment**: A broad staging sweep captured MapView and DSS feature code.

### C. Commit `897819f` (`feat(error-handling): implement structured error codes...`)
- **Swept**: `frontend/src/pages/Agriculture.tsx` (+820 lines): Agriculture dashboard layout.

---

## 3. Proposed Resolution Plan (Do Not Execute Now)

To cleanly reconcile the repository without rewriting git history:

### Step 1: Baseline Feature Snapshot Commit
Create a dedicated commit on a feature branch (or closeout branch) capturing the legitimate, verified source files and unit tests:
```bash
git add backend/app/services/agriculture/history_store.py \
        backend/app/services/agriculture/pest_disease_inspection.py \
        backend/app/services/agriculture/regime.py \
        backend/app/services/agriculture/registry/soil_datasets.py \
        backend/app/services/agriculture/soil_intelligence.py \
        backend/app/services/agriculture/support.py \
        backend/tests/unit/agriculture/test_*.py \
        frontend/src/components/agriculture/ \
        frontend/src/pages/agriculture/
git commit -m "feat(baseline): commit untracked core agricultural services, components, and test suites"
```

### Step 2: `.gitignore` Hardening
Update `.gitignore` to prevent test outputs, scratch scripts, and ephemeral artifacts from cluttering the working tree:
```gitignore
# Scratch and Diagnostic Scripts
*.mjs
check_*.mjs
debug_*.mjs
test_*.mjs
verify_*.mjs
backend/_fa12_*
backend/audit_*.py
backend/check_*.py
backend/inspect_*.py
backend/probe_*.py
backend/test_*_live.py

# Test Logs & Captures
*.out
*.err
*.png
*.pdf
rendered_report.html
*_audit*.json
ardakan_*.json
fa12_*.json
e2e_*.json
ground_truth_test_report.json

# Scratch directories
scratch/
scripts/
.antigravity/
```

### Step 3: Deletion of Transient Scratch Files
Safely delete the ephemeral node/python one-off probe files and debug screenshots after gitignore is updated.
