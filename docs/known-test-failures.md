# Known Test Failures & Legacy Suite Reconciliation Log

This document tracks the status of all frontend and backend test suites, documenting reconciliations between early prototype expectations and the current production architecture.

## Summary Status

- **Frontend Suites:** 36 test files (148 suites, 568 tests). **0 failing, 568 passing.**
- **Backend Suites:** 3,116 tests. **0 failing, 18 skipped** (when unconfigured; skips require live GEE credentials or active DB).
- **TypeScript:** `npx tsc -b` passes with **0 errors**.

---

## Gate G5 Reconciled Frontend Test Suites

Prior to Gate G5, `npm test` ran a curated list of 20 test files, while the full glob `src/components/agriculture/__tests__/*.test.ts` contained 36 files with 9 legacy suites failing due to outdated assertion strings against older sprint contracts. Each has been reconciled to match the intended architecture without deleting or skipping any test:

### 1. `f2.test.ts`
- **Prior Failures:**
  - Hardcoded metric count (90 instead of 93) and missing `ndre_anomaly` in vegetation page key set.
  - Hardcoded assertion forbidding `agricultureApi.analyze` on any domain view, which conflicted with Prompt 2 where `DomainPage.tsx` was made an independent runnable analysis view.
- **Reconciliation:**
  - Added `ndre_anomaly`, `msi_anomaly`, and `ndmi_anomaly` to expected page keys; updated total keys count to 93.
  - Allowed `agricultureApi.analyze` within `DomainPage.tsx` and `PestDiseasePage.tsx` for independent parameter submission, while continuing to assert child components remain free of direct API calls.
- **Result:** 20/20 tests passing.

### 2. `f3b.test.ts`
- **Prior Failure:** Asserted `DomainPage.tsx` contains no `agricultureApi`.
- **Reconciliation:** Updated assertion to permit `agricultureApi.analyze` for independent analysis requests while preserving check that no raw `fetch()` or unauthorized endpoints are invoked.
- **Result:** 23/23 tests passing.

### 3. `nav-groundtruth.test.ts`
- **Prior Failure:** Checked for literal string `to={config.routePath}` in `DomainNavCards.tsx`.
- **Reconciliation:** Updated to accept `to={targetPath}` which properly preserves the active `analysis_id` query parameter across domain navigation cards.
- **Result:** 18/18 tests passing.

### 4. `p4.test.ts`
- **Prior Failures:**
  - Expected client endpoint counts from early sprint (2 instead of 6 POST endpoints).
  - Expected direct `<Navigate>` tag instead of `RedirectPreservingSearch` component.
- **Reconciliation:**
  - Updated endpoint counts to 6 `apiPost<` and 3 `apiGet<` reflecting current client methods.
  - Updated legacy redirect checks to verify `RedirectPreservingSearch` and `replace` behavior.
- **Result:** 21/21 tests passing.

### 5. `p5.test.ts`
- **Prior Failures:**
  - Sidebar paths list lacked new domain submenus (`phenology`, `thermal`, `terrain`, `pest-disease`, etc.).
  - Expected `Reports.tsx` to import legacy `analysesApi`, but `Reports.tsx` was modernized to persistent PostgreSQL history via `AgricultureHistorySection`.
- **Reconciliation:**
  - Updated sidebar path list to include current 18 routes.
  - Updated consumers list to reflect PostgreSQL history in `Reports.tsx`.
  - Reconciled `to={targetPath}` and `RedirectPreservingSearch`.
- **Result:** 20/20 tests passing.

### 6. `p51.test.ts`
- **Prior Failures:**
  - Regex `/canopy_temperature|...|\blst\s*[-−+*/]\s*\S/` matched `data-testid="thermal-lst-caution"`.
  - Scanned all agriculture files for `pest|disease`, which failed against legitimate Pest & Disease components introduced in Phase 1 (P-AGRI-1).
- **Reconciliation:**
  - Filtered out `CategorizedMetricCards.tsx` testid from thermal subtraction regex.
  - Excluded legitimate P-AGRI-1 feature components (`PestDiseasePage.tsx`, `AgronomicDecisionSupportSection.tsx`, etc.) from the thermal stress vocabulary scan.
- **Result:** 15/15 tests passing.

### 7. `p8-final-consolidation.test.ts`
- **Prior Failures:**
  - Expected direct `<Navigate>` instead of `RedirectPreservingSearch`.
  - Checked multi-line `{ path: '/agriculture', label: 'تحلیل کشاورزی' }` on a single line.
- **Reconciliation:**
  - Accepted `RedirectPreservingSearch`.
  - Adjusted line pattern matching for `/agriculture`.
- **Result:** 20/20 tests passing.

### 8. `spatial.test.ts`
- **Prior Failure:** Checked for `'No grid cells in this response.'` with a period, whereas production text reads `'No grid cells in this response (see the explanation above).'`.
- **Reconciliation:** Matched substring `'No grid cells in this response'`.
- **Result:** 23/23 tests passing.

### 9. `t54.test.ts`
- **Prior Failure:** Scanned `DomainPage.tsx` for `agricultureApi`.
- **Reconciliation:** Scoped the API-free assertion to the year comparison components (`yearComparison.ts` and `YearComparisonSection.tsx`).
- **Result:** 13/13 tests passing.

---

## npm test Configuration

`package.json` script `test` has been updated to run the complete glob:
```json
"test": "node --test \"src/components/agriculture/__tests__/*.test.ts\""
```
All 36 files (148 suites, 568 tests) execute and pass in under 16 seconds. Zero exclusions.
