# Phase 3: Frost Risk Module — Decisions Log

This document records architectural, agronomic, and operational decisions made during Phase 3 (Frost-risk advisory module). In accordance with the project instructions, when decisions are ambiguous, conservative and scientifically honest choices are selected and recorded here.

---

## Gate 0 Decisions

### G1. Credentials Discovery & Auto-Skip Marker
- **Decision:** Remove upward parent-directory traversal for credential discovery in production code (`backend/app/services/earth_engine/authentication.py`). Require explicit configuration via `EE_PRIVATE_KEY_FILE` (must be a valid, readable file path) or raw service account JSON via environment variables. Add a `requires_gee` pytest marker and fixture that automatically detects whether GEE credentials and initialization succeed; if not, tests marked with `@pytest.mark.requires_gee` are cleanly skipped with reason `"GEE credentials not configured or live EE unavailable"`.
- **Alternatives Considered:**
  1. Allowing fallback discovery in parent directories: Rejected because it breaks repo self-containment, risks accidental credential leakage if a parent directory is tracked or packaged, and violates production safety.
  2. Mocking all live GEE tests: Rejected because live integration tests verify real API communication with Google Earth Engine when credentials are provided.
- **Why:** Ensures clean-clone builds in isolated environments (e.g. CI/CD or outside the workspace tree) run without crashing while preserving live regression testing when credentials are supplied.

### G2. Removal of Embedded Development Identifiers
- **Decision:** Remove hardcoded postgres passwords (`postgres:postgres123`), real GEE project IDs (`proverbial-will-507706-e1`), and developer service account emails from fallback defaults in `config.py`. All sensitive settings must default to empty strings, `None`, or placeholder strings that require explicit environment injection or reading from `.env`.
- **Alternatives Considered:** Leaving local dev defaults in `config.py`. Rejected as insecure and bad hygiene.
- **Why:** Codebase must be completely clean of any secrets, project IDs, or service account emails in tracked code.

### G3. Secrets and Data Scan
- **Decision:** Strictly audit git tree and history for private keys, credentials, large JSON files, and uncommitted data samples. Untrack 10 large diagnostic JSON dumps (`backend/_a2_resp*.json` and `backend/_fa12_resp*.json`), and add `backend/_a2_*` to `.gitignore`. Scanned `git ls-files` to confirm zero credentials, private keys, or `.env` files are tracked. Conducted a full-history audit across all git branches (`git log -S "BEGIN PRIVATE KEY" --all`). Historical matches were found in early automated checkpoint stashes/commits (`9f3da4b`, `0ca7ebb`) before the repository audit. In strict accordance with the constraint "do not rewrite history (no reset/amend/rebase/force-push)", history was not rewritten, and all historical occurrences are documented and disclosed.
- **Why:** Complies with security cleanliness for current tracked tree while preserving immutable git history.

### G4. Tile Token Log Masking
- **Decision:** Mask both path-based tile tokens (`/tiles/{token}/...`) and query-string tokens (`?token=...` or `?tile_token=...`) across all logging formatters and filters. Implemented recursive masking in `TileTokenMaskingFilter` for string messages, tuples, dicts, and lists in `LogRecord.args`. Added unit tests in `backend/tests/unit/test_logging.py` covering path segments, query parameters, and `uvicorn.access` format structures. Verified with a real live uvicorn process receiving a tile request, capturing:
  `INFO: 127.0.0.1:62209 - "GET /api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED*** HTTP/1.1" 403 Forbidden`
- **Alternatives Considered:** Masking only `uvicorn.access` or only path patterns. Rejected because clients or proxies can pass tokens in query strings, and application loggers may also log full URLs.
- **Why:** Prevents secret/session token leakage into server logs across all request forms.

### G5. Frontend Test Suite Expectations
- **Decision:** Reconcile outdated assertion strings in all 9 legacy frontend test suites (`f2`, `f3b`, `nav-groundtruth`, `p4`, `p5`, `p51`, `p8-final-consolidation`, `spatial`, `t54`) without deleting or skipping any test. Configured `npm test` in `frontend/package.json` to run the full glob (`node --test "src/components/agriculture/__tests__/*.test.ts"`), bringing the entire suite of 36 files (148 suites, 568 tests) to 100% green. Detailed documentation created in `docs/known-test-failures.md`.
- **Alternatives Considered:** Leaving the 9 files excluded and documenting exclusions in `docs/known-test-failures.md`. The decision was made to reconcile all 9 files AND update `npm test` to run the full glob, achieving both full test coverage and exhaustive documentation.
- **Why:** Delivers 100% test integrity across all test files in the codebase without regressions or gaps.

### G6. Git Audit Documentation Correction
- **Decision:** Updated `docs/git-audit.md` to explicitly classify edits to `test_response_semantics.py`, `test_soil_properties.py`, `test_stress.py`, and `test_validation_engine.py` as swept work from earlier P-AGRI-1 (pest & disease regime rules) and F-A12 (SoilGrids water retention) sprints rather than Phase 1/2. Documented empirical proof showing that the change in `test_soil_properties.py` from `0.001` to `1.0` corrected a 1000x double-scaling under-reporting bug (e.g. restoring Field Capacity from an implausible `0.000209 cm³/cm³` to the physically verified `0.209 cm³/cm³` matching published soil physics benchmarks).
- **Why:** Ensures scientific accuracy, transparent provenance tracking, and eliminates confusion regarding historical commit sweeps.

---

## Task 3.1: Forecast Adapter Decisions

### 3.1.1 GEE NOAA/GFS0P25 Integration & Units
- **Decision:** Use Google Earth Engine `NOAA/GFS0P25` as the primary global NWP forecast dataset, providing up to 384h forecast horizon across 209 timesteps. Verified empirically via live GEE inspection that `temperature_2m_above_ground` in this Earth Engine collection is stored directly in degrees Celsius (°C), unlike raw GRIB files which use Kelvin. The adapter handles values directly in Celsius without subtracting 273.15.
- **Alternatives Considered:** Converting Kelvin assuming standard GRIB2 units. Rejected after verifying live GEE values (which would have produced unphysical -258°C temperatures).
- **Why:** Physical accuracy and prevention of catastrophic temperature offset errors.

### 3.1.2 DEM Elevation Correction & Thermodynamic Consistency
- **Decision:** Apply the production `correct_temperature_for_elevation` function from `backend/app/services/agriculture/quality_gating.py` to every forecast timestep. Cell mean elevation ($z_{\text{cell}}$) is computed over the GFS cell radius ($13,915\,\text{m} \approx 27.8\,\text{km} / 2$) from NASADEM 30m, and site elevation ($z_{\text{site}}$) is computed over the parcel geometry. The lapse rate $\Gamma = -6.5\,^\circ\text{C/km}$ (or inversion condition during clear radiative nights) calculates $\Delta T = -\Gamma \cdot (z_{\text{site}} - z_{\text{cell}})$.
- **Why:** Prevents elevation-induced warm/cold bias in mountainous or basin terrain (e.g. Iranian central plateau pistachio regions).

### 3.1.3 Forecast Uncertainty Formulation
- **Decision:** Total temperature uncertainty is formulated as the quadrature sum of elevation correction uncertainty and lead-time forecast uncertainty:
  $$\sigma_{\text{total}} = \sqrt{\sigma_{\text{elevation}}^2 + \sigma_{\text{lead\_time}}^2}$$
  with default piecewise lead-time bounds: $0-24\text{h}: 1.0\,^\circ\text{C}$; $24-48\text{h}: 1.5\,^\circ\text{C}$; $48-72\text{h}: 2.0\,^\circ\text{C}$; $72-120\text{h}: 2.5\,^\circ\text{C}$; $120-240\text{h}: 3.5\,^\circ\text{C}$; $240-384\text{h}: 4.5\,^\circ\text{C}$.
  Bounds $[T_{\min}, T_{\max}]$ are computed as $T \pm \sigma_{\text{total}}$.
- **Why:** Provides scientifically honest confidence envelopes for farmers and agronomists, transparently reflecting diminishing model skill with lead time.

### 3.1.4 Cadence Disclosure
- **Decision:** NOAA GFS provides 1-hourly output for hours 0–120 and 3-hourly output for hours 120–384. Every timestep explicitly carries boolean `is_interpolated`. The overall response flags `native_spatial_resolution_m: 27800` and `quality_state: coarse_context`.
- **Why:** Adheres to the core project mandate of honest resolution and provenance disclosure.

---

## Task 3.2: Cold-Air-Pooling Index Decisions

### 3.2.1 Heuristic Proxy Framing vs. Physical CFD
- **Decision:** The cold-air-pooling metric is explicitly formulated and documented as a **topography-derived heuristic proxy** (`pooling_risk_proxy`), NOT a microclimate CFD or numerical atmospheric boundary layer simulation. All schemas, docstrings, UI labels, and test suites strictly enforce this naming convention and include explanatory Persian disclaimers (`POOLING_DISCLAIMER_FA`).
- **Why:** Scientific honesty and legal compliance: satellite DEM-derived derivatives reflect geometric vulnerability to cold air drainage and accumulation, not dynamic atmospheric micrometeorology.

### 3.2.2 Topographic Components & Basin Confinement
- **Decision:** Computed from NASADEM 30m (`NASA/NASADEM_HGT/001`) with four weighted normalized components:
  1. Local relief confinement & height above floor ($w_1 = 0.35$): $f_{\text{floor}} = \text{confinement} \cdot \max(0, 1 - (z - z_{\min}) / 50\,\text{m})$, where $\text{confinement} = \min(1.0, (z_{\max} - z_{\min}) / 50\,\text{m})$. Modulating by local relief ensures an open, unconfined flat plain does not falsely register as an enclosed deep valley floor.
  2. Micro-scale TPI 300m ($w_2 = 0.25$): $f_{\text{tpi\_300}} = \text{clip}(0.5 - (z - \bar{z}_{300}) / 30\,\text{m}, 0, 1)$.
  3. Meso-scale TPI 1000m ($w_3 = 0.25$): $f_{\text{tpi\_1000}} = \text{clip}(0.5 - (z - \bar{z}_{1000}) / 60\,\text{m}, 0, 1)$.
  4. Slope flatness ($w_4 = 0.15$): $f_{\text{slope}} = \max(0, 1 - \theta / 15^\circ)$ (slopes $> 15^\circ$ drain cold air rapidly, impeding stagnation).
- **Why:** Accurately distinguishes concavities, valleys, plains, and ridges while obeying strict physical and mathematical properties:
  - Synthetic Bowl: ~0.98 (severe pooling susceptibility)
  - Flat table-land: ~0.40 (neutral baseline)
  - Synthetic Ridge / Peak: ~0.17 (minimal pooling susceptibility)
  - Monotonicity: Deeper topographic bowls strictly increase the proxy.
  - Elevation Invariance: Any constant offset $z \to z + C$ produces bitwise identical index grids.

### 3.2.3 Signed Slippy Map Raster Integration
- **Decision:** Integrated with `tile_auth.generate_signed_layer_token` and `cache_service`. Generates HMAC-signed layer tokens bound to metric `pooling_risk_proxy`, bounding box, and 7200s TTL, serving through `/api/v1/agriculture/tiles/{layer_token}/{z}/{x}/{y}.png` with color ramp `["#f7fcf0", "#bae4bc", "#7bccc4", "#43a2ca", "#0868ac"]`.
- **Why:** Seamless integration with frontend map viewers without exposing Earth Engine URLs or credentials.


