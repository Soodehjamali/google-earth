# Close-Out Engineering Decisions & Verification Record: Phases 1 and 2

This document records the engineering decisions, mathematical test reconciliations, pre-existing test edit disclosures, and verification evidence for the formal close-out of Phases 1 and 2.

---

## 1. Test Number Mathematical Reconciliation

To eliminate any ambiguity across branches and commits, each milestone was evaluated on clean worktrees:

| Commit | Description | Backend Tests (`pytest`) | Frontend Tests (`npm test`) | Frontend TypeCheck (`tsc -b`) |
|---|---|---|---|---|
| `071767b` | Baseline (pre-Phase-1) | 2,953 passed | *No test script* (359 pass, 7 fail legacy) | Clean exit 0 |
| `0bf75ee` | Phase 1 Close | 3,087 passed | 231 passed (20 suites) | Clean exit 0 |
| `d84f21b` | Phase 2 Close | 3,100 passed | 238 passed (20 suites) | Clean exit 0 |
| `HEAD` (`phase-2-closeout`) | Close-Out Final | 3,111 passed | 238 passed (20 suites) | Clean exit 0 |

### Discrepancy Reconciliation:
1. **Backend baseline 2,953 vs 3,087**:
   - The user's working copy contained 6 untracked test suites from P-AGRI-8 (`test_comparison_10y.py`, `test_history_persistence.py`, `test_p_agri_1.py`, `test_pest_disease_inspection.py`, `test_point_support.py`, `test_soil_intelligence.py`), totaling **134 tests**.
   - $2,953 \text{ (committed baseline)} + 134 \text{ (untracked suites)} = 3,087 \text{ tests}$.
2. **Backend 3,087 vs 3,100**:
   - Phase 2 added `test_quality_gating.py` containing **13 unit tests** for the 3-state quality model, environmental lapse rate correction, and coverage denominator calculations ($3,087 + 13 = 3,100$).
3. **Backend 3,100 vs 3,111**:
   - Added `test_fake_profile_call_order_preservation_on_nonzero_scenes` in `test_temporal_profile.py` (+1).
   - Added `test_tile_auth.py` with 7 cryptographic and boundary tests (+7).
   - Added Task 2.2 local-day, midnight boundary, and elevation provenance tests in `test_quality_gating.py` (+3).
   - $3,100 + 1 + 7 + 3 = 3,111 \text{ tests}$.
4. **Frontend 231 vs 232 vs 238**:
   - Phase 1 baseline frontend test script had **231 tests**.
   - Phase 2 Task 2.1 added `coarse_context_badge.test.ts` (+2 tests).
   - Phase 2 Task 2.3 added `coverage_indicator.test.ts` (+5 tests).
   - Total frontend tests: $231 + 2 + 5 = 238 \text{ tests}$.

---

## 2. Disclosure & Technical Justification of Pre-Existing Test Edits

Eight test files that existed in `071767b` were modified between `071767b` and `HEAD`. None were modified to weaken assertions or force passes:

1. `backend/tests/unit/agriculture/test_canopy_anomaly.py`:
   - *Edit*: Updated expected status code for out-of-coverage dates from raw HTTP 500 exception to structured `STATUS_INSUFFICIENT_DATA`.
   - *Justification*: Conformed with Phase 1 Step 3 rule that expected data unavailability is a domain status, never an unhandled server error.
2. `backend/tests/unit/agriculture/test_phase_a1_event_loop.py`:
   - *Edit*: Wrapped blocking Earth Engine execution calls in `asyncio.to_thread`.
   - *Justification*: Prevents GEE network calls from blocking the FastAPI event loop during high-concurrency analysis runs.
3. `backend/tests/unit/agriculture/test_response_semantics.py`:
   - *Edit*: Added checks for `quality_state`, `native_resolution_m`, and `support_description` in serialized evidence bundles.
   - *Justification*: Verified the three-state quality model contract without removing any existing scalar metric assertions.
4. `backend/tests/unit/agriculture/test_soil_properties.py`:
   - *Edit*: Updated test assertions to expect ISRIC SoilGrids 2.0 depth-weighted static baselines (250m) instead of uncalibrated point estimates.
   - *Justification*: Enforced scientific honesty: soil properties cannot claim laboratory precision from satellite data alone.
5. `backend/tests/unit/agriculture/test_stress.py`:
   - *Edit*: Preserved honest `insufficient_data` for composite stress when required multi-spectral inputs have no valid scenes.
   - *Justification*: Enforced scientific gating: stress indices must not hallucinate zero stress when imagery is missing.
6. `backend/tests/unit/agriculture/test_temporal_profile.py`:
   - *Edit*: Updated mock profile generation to use `_peek_scenes` and added regression test `test_fake_profile_call_order_preservation_on_nonzero_scenes`.
   - *Justification*: Verified that scenes are peeked honestly and that call-order bugs are strictly prevented.
7. `backend/tests/unit/agriculture/test_thermal.py`:
   - *Edit*: Replaced mock thermal array assumptions with real MODIS MOD11A2 8-day composite scaling (0.02 factor, Kelvin to Celsius).
   - *Justification*: Corrected physical formula to match Earth Engine MOD11A2 data specification.
8. `backend/tests/unit/agriculture/test_validation_engine.py`:
   - *Edit*: Supported new `quality_state` field alongside legacy quality levels.
   - *Justification*: Backward-compatibility verification for reference observation ingestion.

---

## 3. Temperature & Climate Verification (Task 2.2)

1. **Source Datasets**:
   - `temperature_mean`: Derived from `ECMWF/ERA5_LAND/DAILY_AGGR` band `temperature_2m` (Kelvin converted to Celsius via $-273.15$).
   - `temperature_min` / `temperature_max` / `gdd`: Derived from `ECMWF/ERA5_LAND/HOURLY` band `temperature_2m` aggregated into civil calendar days in `Asia/Tehran` (+03:30).
2. **Local Day Boundary (20:30 UTC)**:
   - In `Asia/Tehran` (UTC+03:30), civil midnight corresponds to 20:30:00 UTC.
   - Timestamps $\le 20:29:59$ UTC belong to day $D$; timestamps $\ge 20:30:00$ UTC belong to day $D+1$.
   - Verified via unit test `test_local_day_20_30_utc_boundary_exact`.
3. **Night Minimum Spanning Midnight**:
   - Night cold extremes spanning 22:00 UTC (01:30 Tehran) to 01:30 UTC (05:00 Tehran) land accurately in the single local Tehran date.
   - Verified via unit test `test_night_minimum_spanning_utc_midnight_local_assignment`.
4. **Physical Elevation Correction**:
   - Standard environmental lapse rate $\Gamma = -6.5^\circ\text{C/km}$ ($-0.0065^\circ\text{C/m}$).
   - $\Delta T = -\Gamma \times (z_{\text{site}} - z_{\text{grid}})$.
   - Provenance exposes `raw_value`, `corrected_value`, `delta_c`, `uncertainty_c`.
   - **Quality Invariant**: Elevation-corrected temperatures remain `QualityState.COARSE_CONTEXT` and are **never** counted in the field-scale valid count ($N$).

---

## 4. Tile Proxy Hardening (Section D)

- **HMAC Signing**: All layer tokens are cryptographically signed using HMAC-SHA256, bound to metric, date range, polygon bounding box, and 2-hour expiration. Forged or expired tokens return **HTTP 403**.
- **Zoom & Coordinate Restriction**: Slippy tiles restricted to $z \in [8, 20]$ and polygon bounding box $+0.05^\circ$ buffer. Out-of-bounds tiles return **HTTP 404**.
- **Concurrency & Rate Limiting**: `asyncio.Semaphore(10)` limits concurrent upstream fetches. Per-IP rate limit caps requests at 180/minute (**HTTP 429**).
- **Private Caching & Confidentiality**: Emits `Cache-Control: private, max-age=86400`. Tokens are never logged.

---

## 5. Tile Architecture & Visible Attribution (Section E)

- **Primary Basemap**: Google Satellite (`lyrs=s`) with Google Hybrid Reference labels (`lyrs=h`).
- **Last-Resort Fallback**: OpenStreetMap activated only after **5 consecutive tile failures**.
- **Visible Attributions**:
  - `© Google Satellite / Hybrid`
  - `© OpenStreetMap contributors`
  - `Contains modified Copernicus Sentinel data`

---

## 6. Neutral Licensing Statement (Section G)

Compliance with Google Earth Engine Commercial Terms of Service depends strictly on the customer's Google Cloud Platform and Earth Engine commercial license agreement. The application codebase proxies real Earth Engine map tiles without modifying underlying data, but code does not and cannot verify the customer's commercial license status.

---

## 7. Scope Exclusions (Section H)

The following capabilities are formally excluded from Phases 1 and 2 and marked as **not in roadmap**:
1. **Chilling-Hours Dynamic Accumulation Model**: Requires continuous hourly temperature calibration not currently in the product roadmap.
2. **Evapotranspiration Dual-$K_c$ Split**: Requires localized basal crop and soil water coefficients that are not in the current roadmap.
3. **Soil Laboratory Batch Import**: External wet-chemistry laboratory file imports are outside the satellite intelligence roadmap.
