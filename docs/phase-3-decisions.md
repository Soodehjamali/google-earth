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
- **Decision:** Apply the production `correct_temperature_for_elevation` function from `backend/app/services/agriculture/quality_gating.py` to every forecast timestep. Cell mean elevation ($z_{\text{cell}}$) is computed over the GFS cell radius ($13,915\,\text{m} \approx 27.8\,\text{km} / 2$) from NASADEM 30m, and site elevation ($z_{\text{site}}$) is computed over the parcel geometry. The lapse rate $\Gamma = -6.5\,^\circ\text{C/km}$ calculates $\Delta T = \Gamma \cdot \frac{z_{\text{site}} - z_{\text{cell}}}{1000}$, ensuring that when a site is higher than the cell mean ($\Delta z > 0$), $\Delta T$ is negative and the corrected temperature is colder ($T_{\text{corr}} = T_{\text{cell}} + \Delta T$).
- **Why:** Prevents elevation-induced warm/cold bias in mountainous or basin terrain (e.g. Iranian central plateau pistachio regions).

### 3.1.3 Forecast Uncertainty Formulation and API Contract
- **Decision:** Total temperature uncertainty is formulated as the quadrature sum of elevation correction uncertainty and lead-time forecast uncertainty:
  $$\sigma_{\text{total}} = \sqrt{\sigma_{\text{elevation}}^2 + \sigma_{\text{lead\_time}}^2}$$
  with default piecewise lead-time bounds: $0-24\text{h}: 1.0\,^\circ\text{C}$; $24-48\text{h}: 1.5\,^\circ\text{C}$; $48-72\text{h}: 2.0\,^\circ\text{C}$; $72-120\text{h}: 2.5\,^\circ\text{C}$; $120-240\text{h}: 3.5\,^\circ\text{C}$; $240-384\text{h}: 4.5\,^\circ\text{C}$.
  Forecast series bounds are canonicalized as `lower_bound_c` and `upper_bound_c` ($T \pm \sigma_{\text{total}}$). The previous naming `temperature_min_c` / `temperature_max_c` is retained as a deprecated alias to avoid breaking legacy consumers, but documentation, schemas, and UI components now standardize on `lower_bound_c` / `upper_bound_c` to make clear they denote uncertainty envelopes ($T \pm \sigma$) rather than diurnal extremes.
- **Rounding Rule:** To eliminate float discrepancies where `round(raw) + round(delta) != round(corrected)`, rounding is applied consistently: `raw_rounded = round(t_cell, 2)`, `delta_rounded = round(delta_c, 2)`, and `corrected_rounded = round(raw_rounded + delta_rounded, 2)`. This ensures $T_{\text{corr}} = T_{\text{raw}} + \Delta T$ strictly holds across all outputs.
- **Calibration Status:** The elevation lapse rate ($\Gamma = -6.5\,^\circ\text{C/km}$) and daytime/nighttime elevation uncertainties ($1.0\,^\circ\text{C}$ and $2.0\,^\circ\text{C}$) are empirical defaults marked as placeholders "needs calibration" in `config/frost_thresholds.yaml` and `QualityGatingConfig`, pending regional sensor network tuning.
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

---

## Task 3.3: Risk Model & Threshold Engine Decisions

### 3.3.1 External Phenological Thresholds & Provenance Enforcement
- **Decision:** All crop threshold definitions are strictly isolated in `config/frost_thresholds.yaml` (external to Python source code). For pistachio, all stages (`dormant`, `bud_burst`, `early_bloom`, `full_bloom`, `fruit_set`) are explicitly configured with `status: placeholder`, `source: null`, and `verified: false`.
- **Loader Validation Rule:** The parser (`load_frost_thresholds_config`) strictly validates provenance metadata. It rejects configuration files if `status` is missing, if `status == "placeholder"` while `source` is non-null or `verified` is true, or if $T_{\text{crit,90}} \ge T_{\text{crit,10}}$ (a violation of the monotonic mortality curve).
- **Why:** Guarantees that unverified placeholder values cannot silently pose as calibrated agronomic facts, ensuring safe operational boundaries.

### 3.3.2 Local Night Aggregation Across UTC Midnight
- **Decision:** Night windows are defined according to local Iranian time (IRST = UTC+3:30) from 18:00 local on date $D$ to 09:00 local on date $D+1$ (spanning 15 hours). In UTC, this corresponds to 14:30 UTC on date $D$ to 05:30 UTC on date $D+1$, crossing the 00:00 UTC boundary.
- **Why:** Radiation frost events reach their temperature nadir immediately before dawn; segmenting by UTC calendar days would split the single physical freeze event across two calendar dates, obscuring minimum temperature and duration of freeze.

### 3.3.3 Cold-Air-Pooling Temperature Bump & Wind Damping
- **Decision:** During radiative conditions, topographic depressions experience additional nocturnal cooling below the regional NWP grid. When `pooling_risk_proxy > 0.40`, a cooling bump is applied to minimum temperature:
  $$\Delta T_{\text{pool}} = \frac{\text{proxy} - 0.40}{0.60} \times 2.5\,^\circ\text{C} \times f_{\text{wind}}$$
  where $f_{\text{wind}} = 1.0$ for wind $\le 1.5\,\text{m/s}$, decreasing linearly to $0.0$ at wind $\ge 4.0\,\text{m/s}$.
- **Why:** Physical realism: stable stratification and cold pooling require calm conditions; turbulent shear in breezy weather destroys inversion layers and prevents cold pooling.

### 3.3.4 Physical-Only Cultural Defense Recommendations
- **Decision:** Advisory recommendations are strictly limited to proven physical and cultural orchard practices:
  1. Pre-freeze surface or furrow irrigation (to increase soil thermal conductivity and release latent heat).
  2. Wind machines / selective inverted sinks in the presence of radiation inversion.
  3. Clean-burning orchard heaters placed in depressions.
  4. Maintaining firm, moist, uncultivated soil surface.
  Chemical and hormonal recommendations (e.g. anti-transpirants, copper sprays, gibberellins, or unproven foliar sprays) are strictly excluded from the recommendation database.
- **Why:** Regulatory safety, scientific honesty, and avoidance of hazardous agronomic practices.

---

## Task 3.4: API & Minimal Storage Decisions

### 3.4.1 Alembic Migration 002_frost & Multi-Dialect Compatibility
- **Decision:** Implemented Alembic migration `002_frost_tables.py` creating `orchards`, `alert_rules`, and `notification_log` tables with foreign key cascades and composite indexes. Added SQLite JSONB compiler shim (`@compiles(JSONB, 'sqlite')`) to support local SQLite in-memory test suites while keeping native PostgreSQL `JSONB` and `UUID` in production. Fully verified upgrade -> downgrade -> upgrade cycle in automated tests.
- **Why:** Production relational schema integrity without requiring a live PostgreSQL instance for unit testing.

### 3.4.2 Outbound Dispatch Safety Lock
- **Decision:** Implemented an automated safety lock (`dispatch_alert_with_safety_lock`). If `thresholds_verified=False` (unverified placeholder thresholds), any attempt to dispatch notifications through real external network providers (SMS, Telegram, webhook, email) is strictly refused with `UnverifiedThresholdsSafetyLockError` unless an explicit `admin_override=True` flag is supplied. Only `StubNotificationProvider` and dry-run dispatches are permitted.
- **Why:** Prevents accidental panic or false-alarm broadcasts to real farmers using uncalibrated placeholder thresholds.

### 3.4.3 PII and Recipient Protection in Server Logs
- **Decision:** Implemented `mask_recipient()` which masks phone numbers (e.g. `+989123456789` -> `+989***89`) and emails before writing to server logs or returning summary notifications.
- **Why:** Strict adherence to privacy requirements forbidding plain phone numbers in application logs.

### 3.4.4 Idempotency & Upward-Only Escalation
- **Decision:** Alert evaluation targets the earliest upcoming night with elevated frost risk. Queries `notification_log` for previous dispatches for `(orchard_id, target_night)`. If an alert has already been dispatched at equal or greater severity, dispatch is skipped (idempotent). If the forecast worsens (e.g. from `watch` to `warning`), an escalation alert is dispatched ("escalate upward only").
- **Why:** Protects growers from alert fatigue while guaranteeing immediate escalation when forecast freeze severity increases.

### 3.4.5 GEE Outage Error Envelope
- **Decision:** When `use_live_gee=True` encounters an Earth Engine timeout or service outage, the API returns a structured HTTP 503 response conforming to the unified error envelope with `code: ERR_GEE_UNAVAILABLE`.
- **Why:** Clear error contract without leaking raw exception tracebacks to API consumers.

---

## Task 3.5: Frontend "Frost" Domain Page Decisions

### 3.5.1 Navigation IA & Autonomous Domain Page Design
- **Decision:** Added Frost Risk Advisory (`id: 'frost'`, `labelFa: 'هشدار سرمازدگی'`, icon: `❄️`) to `Layout.tsx` under the Agriculture Navigation hierarchy, and routed to `FrostRiskPage.tsx` under `/agriculture/frost` in `App.tsx`. Like `PestDiseasePage.tsx`, Frost Risk is designed as an autonomous operational dashboard with its own forecast parameter controls, coordinates input, live GEE toggle, and orchard alert subscription management rather than a static evidence-bundle viewer.
- **Why:** Frost risk requires forward-looking hourly forecast time-series, topographic pooling proxies, and alert rules rather than standard retrospective satellite indices.

### 3.5.2 Timeline Chart with Uncertainty Bands & Night Shading
- **Decision:** Implemented `FrostTimelineChart.tsx` using Recharts `ComposedChart`. Plots:
  1. Corrected temperature forecast line ($T_{\text{corr}} = T_{\text{grid}} - \Gamma \cdot \Delta z$).
  2. Uncertainty envelope ($T_{\min} \dots T_{\max}$) derived from quadrature lead-time and elevation uncertainty.
  3. Phenological critical threshold reference lines ($T_{c10}$, $T_{c90}$) and zero freezing line ($0\,^\circ\text{C}$).
  4. Shaded nocturnal windows crossing midnight (18:00 to 09:00 local time).
- **Why:** Gives growers and agronomists an honest, scientifically grounded visualization of freezing risk and forecast confidence.

### 3.5.3 Explicit Unverified Thresholds Warning & Coarse Context Disclosures
- **Decision:** Rendered `FrostWarningBanner.tsx` prominently whenever `thresholds_verified === false`, explicitly noting that current thresholds are placeholders requiring local calibration. Integrated `CoarseContextBadge` displaying `"تفکیک مکانی ~۲۸ کیلومتر (GFS)"` to honestly disclose the synoptic NWP resolution.
- **Why:** Avoids false confidence and prevents growers from treating uncalibrated placeholder models as definitive agronomic facts.

### 3.5.4 Cold-Air-Pooling Map Overlay & Ramp Legend
- **Decision:** Implemented `ColdAirPoolingSection.tsx` with topographic metrics, heuristic proxy disclaimer, and an interactive raster map toggle that loads the signed tile URL (`pooling.tile_url`) in `MapView` with the 5-step color ramp (`["#f7fcf0", "#bae4bc", "#7bccc4", "#43a2ca", "#0868ac"]`).
- **Why:** Allows growers to visualize micro-topographic cold air stagnation bowls directly on high-resolution satellite basemaps.

### 3.5.5 LTR Presentation & Mathematical Minus Sign Isolation
- **Decision:** All sub-zero temperatures, negative adjustments, and uncertainty intervals are rendered with `<FormattedNumber>` and tabular numerals, ensuring mathematical minus signs (`U+2212`) always remain on the left of digits without RTL inversion in Persian UI contexts.
- **Why:** Prevents dangerous temperature reading confusions (e.g. reading $-2.5\,^\circ\text{C}$ as $+2.5\,^\circ\text{C}$).

---

## Item C3 Decisions: Formulas, Constants, and Pooling Clipping

### C3.1 Lapse-Rate Correction Sign Convention
- **Formula:**
  $$\Delta z_{\text{km}} = \frac{z_{\text{site}} - z_{\text{cell}}}{1000}$$
  $$\Delta T = \Gamma \cdot \Delta z_{\text{km}} \quad (\text{with } \Gamma = -6.5\,^\circ\text{C/km})$$
  $$T_{\text{corr}} = T_{\text{cell}} + \Delta T$$
- **Directional Proof:** For a site higher than the cell mean ($z_{\text{site}} = 1500\,\text{m}, z_{\text{cell}} = 1000\,\text{m}$), $\Delta z = +0.5\,\text{km}$, yielding $\Delta T = -3.25\,^\circ\text{C}$ and $T_{\text{corr}} < T_{\text{cell}}$. A higher site is strictly colder.

### C3.2 Non-Warming Constraint on Cold-Air-Pooling
- **Safety Constraint:** The cold-air-pooling adjustment must **never warm** the forecast temperature. The pooling cooling bump is clipped at $0.0$:
  $$\Delta T_{\text{pool}} = \max(0.0, \text{raw\_bump})$$
  $$T_{\text{adjusted}} = T_{\text{raw}} - \Delta T_{\text{pool}} \le T_{\text{raw}}$$
- **Rationale:** Topographic ridges or elevated convexities drain cold air, but must not be credited with artificial warming during freezing nights. The dangerous error direction for agriculture is false-safe (underestimating frost risk).

### C3.3 Externalization of Physical Constants to Config
- The following empirical constants have been moved into `config/frost_thresholds.yaml` (under `cold_air_pooling`) and `ColdAirPoolingAdjustmentConfig`, explicitly marked as **placeholder / "needs calibration"**:
  1. `min_pooling_proxy_threshold: 0.40` — Below this proxy value, terrain is considered neutral or self-draining, and no pooling cooling bump is applied.
  2. `max_cooling_bump_c: 2.5` — Maximum radiative cooling depression under calm stagnation conditions.
  3. `wind_speed_calm_mps: 1.5` — Wind threshold below which full cold-air pooling develops.
  4. `wind_speed_drain_mps: 4.0` — Wind threshold above which turbulent boundary-layer mixing completely disrupts the cold pool.
- **Evidence Level:** All frost advisory outputs enforce strict evidence tiering: while phenological thresholds are unverified (`thresholds_verified=false`), `evidence_level = "C"` (uncalibrated placeholder thresholds). The evidence level transitions to `evidence_level = "B"` only when `thresholds_verified=true` following agronomic calibration and field verification against local phenological records. Level A would require in-situ canopy telemetry.

---

## Item C5 Decisions: PostgreSQL Migration & Idempotency

### C5.1 Schema Idempotency & Unique Constraints
- Table `notification_logs` enforces DB-level uniqueness:
  - `uq_notification_orchard_night_category` on `(orchard_id, alert_date, risk_category)`.
  - Column `idempotency_key` (VARCHAR 128) with unique index `ix_notification_log_idempotency_key`.
- Deterministic key generation: `hashlib.sha256(f"{orchard_id}:{alert_date}:{risk_category}".encode()).hexdigest()`.

### C5.2 Alembic Environment Cleanup
- Removed dialect-specific SQLite JSONB compilation hacks from `backend/alembic/env.py`. Moved all SQLite workarounds cleanly to `backend/tests/conftest.py` so production migration scripts remain pure PostgreSQL.
- Verified real migration cycle against live PostgreSQL on port 5434: `alembic downgrade -1` followed by `alembic upgrade head`.

---

## Item C6 Decisions: Endpoint Security, Auth, and PII Masking

### C6.1 Route Authorization
- `/api/v1/agriculture/frost/evaluate-alerts` is protected by `require_admin_auth` dependency validating the `X-Admin-Token` header against `settings.ADMIN_API_KEY`.
- Other read/assess endpoints (`/frost/assess`, `/frost/orchards`) remain accessible for standard user queries.

### C6.2 Server-Side Only Admin Override
- Client requests cannot bypass the unverified-thresholds safety lock. `EvaluateAlertsRequest` configures `model_config = ConfigDict(extra="forbid")` and explicitly omits `admin_override`. Any payload attempting to supply `admin_override` is rejected immediately with HTTP 422 `ERR_VALIDATION_FAILED`.
- `admin_override` is evaluated strictly from server-side configuration (`settings.ALERT_ADMIN_OVERRIDE`).

### C6.3 PII Storage and Strict Masking
- **Storage:** Raw phone numbers and recipient identifiers are stored exclusively in PostgreSQL in:
  1. Table `alert_rules`, column `recipient` (VARCHAR 255).
  2. Table `notification_logs`, column `recipient` (VARCHAR 255).
- **Masking:** All API responses (`GET /frost/orchards`, `POST /frost/alert-rules`, `POST /frost/evaluate-alerts`) and uvicorn/application log records mask recipient identifiers using `mask_recipient()`:
  - Format: `+98-***-***-1234` or `***1234` (only the last 4 digits visible).
  - Raw phone numbers are never returned over HTTP or printed to standard log streams.

### C6.4 Database-Level Idempotency Verification
- Proved via `test_concurrent_duplicate_alert_insertion_db_constraint` that attempting to insert duplicate records for the same parcel, date, and risk tier triggers an `IntegrityError` / `UniqueViolation` in the database engine, preventing multi-dispatch race conditions.

---

## Item C7 Decisions: Log Masking and Tile Token Scrubbing

### C7.1 Tile Token Canonical Location & Transport Channels
The frontend MapLibre GL raster tile client strictly consumes the **URL Path Segment** as its canonical location:
1. **Canonical Path Segment:** Standard slippy map tile URLs follow `/api/v1/agriculture/tiles/{layer_token}/{z}/{x}/{y}.png`.
2. **Query String Rejection:** Query-string tokens (`?token=...` or `?tile_token=...`) are rejected by the backend with HTTP 400 (`ERR_CANONICAL_PATH_TOKEN_REQUIRED`). Enforcing a single canonical location eliminates token smuggling and ambiguity.

### C7.2 Sanitization Filter & Verification
`TileTokenMaskingFilter` intercepts and scrubs tile URLs across string messages, tuples, dicts, and list arguments in `logging.LogRecord`:
- Regex `r'(/tiles/)[^/?\s]+'` sanitizes path segments to `/tiles/***MASKED***`.
- Regex `r'([?&](?:token|tile_token|api_key|secret)=)[^&\s]+'` sanitizes query strings to `\1***MASKED***`.

Verified via `test_uvicorn_access_logrecord_filtering` in `backend/tests/unit/test_logging.py`, producing sanitized output:
```text
INFO: 127.0.0.1:54321 - "GET /api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED***&x=1 HTTP/1.1" 200
```
And live server log line under Uvicorn:
```text
INFO: 127.0.0.1:62209 - "GET /api/v1/agriculture/tiles/***MASKED***/10/681/412.png?token=***MASKED*** HTTP/1.1" 403 Forbidden
```

### C7.3 URL Log Exposure & The True Security Protections
Because HTTP request URLs (both path segments and query strings) are inherently recorded by intermediate reverse proxies, Application Load Balancers (ALB, Nginx, Envoy, Cloudflare), CDN edge access logs, and user browser navigation history, application-level log scrubbing (`TileTokenMaskingFilter`) protects internal server logs but cannot prevent upstream infrastructure or browser history recording of requested URLs.

Consequently, URL secrecy is NOT a sufficient boundary. The **real cryptographic and architectural protections** against tile URL leakage and replay are:
1. **Short Expiry TTL:** Tokens expire automatically within $\le 2$ hours (`exp` epoch timestamp verified via HMAC-SHA256).
2. **Strict Bounding-Box (`bbox`) Binding:** Every token cryptographically binds the parcel's spatial boundary $[lon_{min}, lat_{min}, lon_{max}, lat_{max}]$; tiles outside this bounding box return HTTP 404 (`ERR_TILE_OUT_OF_BOUNDS`).
3. **Zoom Level Clamping:** Coordinates are bounded to zoom levels $z \in [8, 20]$.
4. **Per-IP Rate Limiting:** In-memory sliding window rate limits of 180 requests/min per IP mitigate rapid bulk harvesting even with a valid token.

---

## Item C8 Decisions: Response Contract Integrity

### C8.1 Response Contract Specifications
All responses from the frost assessment endpoint (`POST /api/v1/agriculture/frost/assess`) adhere strictly to the Phase 3 contract:
1. `thresholds_verified: false` — Explicit boolean indicator preventing premature operational lock-in.
2. `evidence_level: "C"` (or `"B"` only when `thresholds_verified: true`) — Rigorous confidence tier reflecting whether phenological thresholds have undergone local agronomist calibration.
3. `quality_state: "coarse_context"` — Honestly flagging the synoptic ~28km grid resolution.
4. `native_spatial_resolution_m: 27830.0` — Disclosing NOAA GFS 0.25° grid footprint.
5. `issue_time_utc` — ISO 8601 UTC timestamp of model run origin.
6. Per-step uncertainty metrics — Every timestep in `series` carries `lead_time_uncertainty_c`, `elevation_uncertainty_c`, and `total_uncertainty_c`.
7. Persian advisory & warning text — `thresholds_warning_fa`, `disclaimer_fa`, `stage_fa`, `crop_fa`, and `overall_risk_level_fa`.
8. Unknown-stage fallback — When an empty, unknown, or unrecognized phenological stage is supplied, the system adopts the precautionary principle, selecting the most sensitive developmental stage (e.g., fruit set / `fruit_set` with $T_{c10} = -1.0^\circ\text{C}$ for pistachio) and appending a descriptive warning in Persian.

---

## Item C9 Decisions: UI Evidence & Responsive Verification

### C9.1 Screenshot Artifacts (Saved Outside Repository)
- Desktop Viewport (1280x1600): `C:\Users\Jamali\Desktop\google_ui_screenshots\frost_desktop_1280.png` (224 KB).
- Mobile Viewport (390x2000): `C:\Users\Jamali\Desktop\google_ui_screenshots\frost_mobile_390.png` (303 KB).

### C9.2 Visual & Semantic Audit
1. **Unverified-Thresholds Banner:** Prominently rendered with warning icon and explicit notice:
   `آستانه‌ها هنوز توسط کارشناس تأیید نشده‌اند (وضعیت: Placeholder)`.
2. **Coarse-Context Badge:** Prominently discloses NWP resolution:
   `تفکیک مکانی ~۲۸ کیلومتر (GFS) - پیش‌بینی منطقه‌ای با تصحیح تراز ارتفاع DEM`.
3. **Timeline Shaded Band:** Fixed legend and tooltip labels in `FrostTimelineChart.tsx` to prevent confusion with climatological extremes:
   - Area: `باند عدم‌قطعیت پیش‌بینی (دمای تصحیح‌شده ± عدم‌قطعیت)`
   - Upper bound: `حد بالای عدم‌قطعیت (+σ)`
   - Lower bound: `حد پایین عدم‌قطعیت (−σ)`
4. **Mathematical Negative Numbers:** Sub-zero temperatures are rendered with mathematical minus (`U+2212`) wrapped in LTR isolation tags (`<FormattedNumber>` / `<span dir="ltr">`), preventing inverted minus glyphs in Persian RTL context.
5. **Color Hierarchy:** Red (`#dc2626`, `#ef4444`) is strictly reserved for critical 90% threshold lines and severe warning alerts. Standard advisory levels use informational blue (`#3b82f6`, `#0891b2`) and amber (`#f59e0b`).

---

## Item D11 Decisions: Deliverables & Headless Visual Verification

### D11.1 Screenshot Artifacts (Saved Outside Repository)
Visual proof captured via headless Chromium at `1440x2600` (device scale factor 1.5) saved in artifact directory:
- `C:\Users\Jamali\.gemini\antigravity\brain\ab34bb1c-3358-4573-8926-0174ec94ce4f\screenshot_frost_overview.png` (695 KB) — Full page overview with unverified banner, parameters, timeline chart, nightly risk cards, and alert rules form.
- `C:\Users\Jamali\.gemini\antigravity\brain\ab34bb1c-3358-4573-8926-0174ec94ce4f\screenshot_lead_time_uncertainty.png` (28 KB) — Timeline chart with explicit lead-time uncertainty bands ($T \pm \sigma$) widening monotonically with forecast horizon.
- `C:\Users\Jamali\.gemini\antigravity\brain\ab34bb1c-3358-4573-8926-0174ec94ce4f\screenshot_pooling_legend.png` (13 KB) — Cold air pooling section with live raster layer and 5-class discrete color ramp legend (`0.0` ridge to `1.0` closed cold pool).
- `C:\Users\Jamali\.gemini\antigravity\brain\ab34bb1c-3358-4573-8926-0174ec94ce4f\screenshot_resolution_no_smoothing.png` (8 KB) — Prominent coarse context badge honestly stating `"تفکیک مکانی ~۲۸ کیلومتر (GFS) - پیش‌بینی منطقه‌ای با تصحیح تراز ارتفاع DEM"`.

### D11.2 Visual Confirmations
1. **Lead-Time Uncertainty Note:** Confirmed visible tooltip, legend entries (`حد بالای عدم‌قطعیت (+σ)`, `حد پایین عدم‌قطعیت (−σ)`, `باند عدم‌قطعیت پیش‌بینی (دمای تصحیح‌شده ± عدم‌قطعیت)`), and local night shaded windows (`۱۸:۰۰ الی ۰۹:۰۰ روز بعد`).
2. **Pooling Legend:** Confirmed 5-step discrete ramp with hex codes `['#f7fcf0', '#bae4bc', '#7bccc4', '#43a2ca', '#0868ac']` and Persian morphological classifications.
3. **No Smoothing Beyond Native Resolution:** GFS synoptic cell footprints (~28 km) are directly disclosed without synthetic spatial smoothing or sub-grid spatial interpolation.

---

## Item D12 Decisions: Full-History Secrets Audit & Commit Traversal

### D12.1 `detect-secrets` Full History Audit Summary
Executed `detect-secrets` over the full history of all commits across all branches (`git rev-list --all`, 150 commits total):
```text
================ FULL HISTORY AUDIT SUMMARY ================
Total commits scanned across all refs: 150
Total branch commits: 60 (branches: main, phase-1-bugfixes, phase-2-closeout, phase-2-data-quality, phase-2-selfcontained, phase-3-frost)
External checkpoint/stash commits: 90 (cline session snapshots)

Breakdown by Detector Type across full history:
  - Basic Auth Credentials (example/dummy strings in .env.example / alembic.ini): 38
  - Private Key (test/dummy mock keys in _diag_key.py / test_executor.py): 14
  - Secret Keyword (placeholder in docker-compose.yml): 1

Current Head State (Phase 3 Frost):
  - Zero hardcoded passwords, production keys, or service-account JSON files committed.
  - Gate G2 commit (1336149) purged legacy development defaults from configuration files.
  - Phase 3 Close-Out strictly consumes credentials from shell environment variables exclusively.
```

### D12.2 Raw `git log -S"postgres123" --all --oneline` Output
```text
1336149 fix(config): remove embedded passwords, real project IDs, and service accounts from dev defaults (Gate G2)
0739268 fix(auth): remove upward EE key traversal and add requires_gee auto-skip marker (Gate G1)
cb7421d fix(config): provide development defaults for DATABASE_URL and EE_PROJECT_ID
de3fcd5 test(backend): commit untracked backend test suites for soil, support, pest, history
071767b new
5108113 untracked files on cline checkpoint
2b23f32 untracked files on cline checkpoint
115d2a8 untracked files on cline checkpoint
65b4abf untracked files on cline checkpoint
f79b23d untracked files on cline checkpoint
885ce88 untracked files on cline checkpoint
cf40793 untracked files on cline checkpoint
77ea051 untracked files on cline checkpoint
d5e8dba untracked files on cline checkpoint
831f994 untracked files on cline checkpoint
18a286b untracked files on cline checkpoint
074daf4 untracked files on cline checkpoint
2ed670e untracked files on cline checkpoint
ef0d5f8 untracked files on cline checkpoint
9ebb94b untracked files on cline checkpoint
ec233be untracked files on cline checkpoint
30ec77e untracked files on cline checkpoint
4d99fca untracked files on cline checkpoint
b1511f3 untracked files on cline checkpoint
7507462 untracked files on cline checkpoint
8c9f00c untracked files on cline checkpoint
aa5b907 untracked files on cline checkpoint
9f3da4b new vwesion
```

---

## Close-Out 3 Decisions: Sourced Research & Item E0

### Sourced Research Provenance & Author Independence
- **Decision:** Sources `[S1]` (Hokmabadi 2010) and `[S2]` (Hokmabadi 2011) are authored by the **SAME author** (H. Hokmabadi). Therefore, they **do not constitute independent confirmations** of pistachio critical temperature thresholds. Where discrepancies exist (notably bloomed flowers: $-1.7^\circ\text{C}$ in S1 vs $+2.0^\circ\text{C}$ in S2), the discrepancy must be explicitly exposed to the user as a conflicting published value rather than averaged or arbitrarily selected.
- **Why:** Adheres strictly to scientific honesty and peer-review rigor.

### Item E0 Decisions: Tile Proxy & Forecast Source Integrity
1. **Multi-Worker Tile Template Resolution & Cache Miss Regeneration:**
   - *Root Cause:* `CacheService` was strictly an in-memory dictionary local to each Python process. In a multi-worker production environment (e.g. Uvicorn with multiple worker processes), the worker that generated the signed tile token cached `tile_template:<id>` in its local memory. Subsequent browser tile fetches hit different worker processes, encountering a cache miss (`None`) and returning HTTP 404 `ERR_TILE_LAYER_EXPIRED`.
   - *Fix:* `CacheService` now integrates a host-shared disk-backed store in `tempfile.gettempdir() / "antigravity_tile_cache"` for all `tile_template:*` keys. If a worker process does not find the key in memory, it checks the shared host store. If the template is absent from both (e.g. expired or evicted), `regenerate_tile_template_from_payload(payload)` deterministically reconstructs the Earth Engine tile template from the HMAC-verified parameters in the signed token payload (`m`, `b`, `s`, `e`).
2. **Tile Proxy Resilience, Proxy Environment, and Error Envelopes:**
   - Upstream client configured with `httpx.AsyncClient(timeout=timeout_sec, trust_env=True)` ensuring that corporate or staging HTTP/HTTPS proxies (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`) are automatically respected.
   - Upstream timeouts raise `AppException` with HTTP 504 and `ERR_TILE_UPSTREAM_TIMEOUT`. Upstream HTTP 5xx or connection failures raise `AppException` with HTTP 502 and `ERR_TILE_UPSTREAM_ERROR`, ensuring all proxy errors conform to the platform's unified error envelope.
   - Tile responses carry strict `Cache-Control: private, max-age=86400` on success and `Cache-Control: private, no-cache` on empty 404 responses.
   - `CacheService` is bounded (`max_entries=5000` with LRU/expired entry eviction), preventing memory leaks.
3. **Server-Controlled Forecast Provider Integrity:**
   - The choice of forecast provider (live GEE vs deterministic fake) is strictly a **server configuration setting** (`settings.FROST_USE_LIVE_GEE` or `settings.is_production`).
   - The `use_live_gee` request field is deprecated and ignored on the server. A client sending `use_live_gee: false` **cannot obtain fake data** when the server is configured for live GEE or running in production.
   - In production configuration (`settings.is_production == True`), `FakeForecastProvider` is strictly unreachable and immediately raises HTTP 403 `ERR_FORBIDDEN` if instantiated.
   - Every forecast response honestly reports its true `source`: `"deterministic_fake"` for fake provider and `"NOAA/GFS0P25"` for live GEE provider.

---

### Item E7 Decisions: Shared Location Inheritance & Coordinate Input Elimination
1. **Shared Scope Context Inheritance:**
   - The frost advisory page (`FrostRiskPage.tsx`) consumes the parent-owned comprehensive analysis context (`useAgricultureContext`), identical to the other domain pages (`DomainPage.tsx`, `PestDiseasePage.tsx`).
   - Separate manual lat/lon input fields and two-point coordinate inputs are completely eliminated from `FrostRiskPage.tsx`.
   - If no analysis location has been set in the platform scope box, the page renders an empty state card with prompt `"ابتدا موقعیت را در کادر محدوده تعیین کنید"`.
2. **Point vs Polygon Geometry Support & Sampling Disclosures:**
   - **Single GPS Point (`Point`):** Forecast samples at point coordinates; elevation is sampled from NASADEM 30m at point; cold-air-pooling proxy aggregates over a configurable 500m buffer (`"Point GPS: cold-air pooling aggregated over 500.0m buffer"`).
   - **Field Polygon (`Polygon`):** Forecast evaluates at parcel centroid cell; elevation = polygon mean DEM; cold-air-pooling proxy aggregates parcel area statistics (`"Polygon: cold-air pooling aggregated across parcel area statistics"`).
   - Every API response explicitly reports `geometry_type` and `location_sampling_method`.
3. **Save as Orchard Workflow:**
   - Orchard registration ("Save as orchard") directly reuses the shared analysis geometry (`sharedGeometry`) rather than requiring manual coordinate re-entry.
   - Centroid coordinates (`latitude`, `longitude`) for registered orchards are computed automatically from Point or Polygon coordinates without manual entry.

---

### Item E8 Decisions: Published Duration Rules, Sourced Thresholds, and Interval Exposure
1. **Same-Author Sourced Literature Integrity:**
   - Literature sources [S1] (Hokmabadi H., 2010, *Options Méditerranéennes* A94, pp. 71-78) and [S2] (Hokmabadi H., 10 Apr 2011 / 21 Farvardin 1390, Iran Pistachio Association) are by the **same author** (Dr. Hossein Hokmabadi). Therefore, they are explicitly recorded as non-independent observations rather than mutually corroborating scientific citations.
2. **Published Duration Threshold Rules:**
   - Per S1 (p. 72): For flower and bud stages, temperature $\le -4^\circ\text{C}$ for $\ge 2.0\text{ h}$ causes light injury / bloom delay and necrosis of flowers (`critical`); $\le -4^\circ\text{C}$ (specifically $-4$ to $-6^\circ\text{C}$) for $\approx 6.0\text{ h}$ causes complete necrosis of very young pistils (`critical`).
   - Bloom stage: Critical temperature is $-1.7^\circ\text{C}$ per S1 (p. 77). The conflicting value $+2.0^\circ\text{C}$ published in S2 is recorded as `conflicting_published_value: 2.0` and `conflicting_notes_fa` and is **not** used as a lethal damage threshold.
   - Stages without published duration data (such as `dormant`, `bloom`, and `fruit`) strictly receive `duration_rules: null`. In the UI, they display: `"برای این مرحله داده منتشرشده‌ای برای مدت ماندن زیر آستانه وجود ندارد؛ دسته‌بندی فقط بر اساس دما است"`.
3. **Interval Arithmetic & Cadence Rules:**
   - Exposure duration is computed strictly from native hourly timesteps ($\Delta t \le 1.5\text{h}$). Each step below threshold represents an interval duration of $1.0\text{ hour}$.
   - Discontinuous runs do not sum to satisfy continuous rule thresholds; only the longest continuous run triggers duration escalation.
   - A brief dip ($< 1.0\text{h}$) below critical threshold is classified as `watch` (short dip flag).
   - Runs beyond 120h (GFS 3-hourly cadence) are flagged `duration_resolvable: false`; severity is evaluated strictly on temperature.
   - **Pessimistic Run Escalation:** When nominal temperature remains above threshold, a pessimistic run ($T - \sigma \le T_{\text{crit}}$) may **only** raise severity to `watch`, never to `warning` or `critical`.
   - Minimum temperature and run timestamps are reported in local `Asia/Tehran` time (`HH:MM`).

---

### Item E9 Decisions: Factor Model v2, Asymmetric Conservatism, and Published Thresholds
1. **Rejection of Uncalibrated Weighted Scores (0-100):**
   - The platform strictly rejects synthetic 0-100 weighted index scores (e.g. 40/25/15/10/5/5). Such arbitrary weights double-count developmental phenology, conflate physical hazard with biological vulnerability, and lack empirical or agronomic grounding.
   - Phenological stage strictly selects the physical critical damage thresholds. Hazard is defined physically by $T_{\text{effective, min}} + \text{duration exposure}$.
2. **Real Earth Engine Band List of `NOAA/GFS0P25` & Dewpoint Derivation:**
   - Real GEE band inspection confirms `NOAA/GFS0P25` contains:
     `['downward_shortwave_radiation_flux', 'precipitable_water_entire_atmosphere', 'relative_humidity_2m_above_ground', 'specific_humidity_2m_above_ground', 'temperature_2m_above_ground', 'total_cloud_cover_entire_atmosphere', 'total_precipitation_surface', 'u_component_of_wind_10m_above_ground', 'v_component_of_wind_10m_above_ground']`.
   - `dewpoint_2m` is absent from GFS0P25. Dewpoint temperature ($T_{\text{dew}}$) is computed rigorously using the Magnus-Tetens formula from 2m air temperature and relative humidity:
     $$\alpha(T, RH) = \frac{17.625 \cdot T}{243.04 + T} + \ln\left(\frac{RH}{100.0}\right)$$
     $$T_{\text{dew}} = \frac{243.04 \cdot \alpha}{17.625 - \alpha}$$
3. **Factor Register & Asymmetric Conservatism:**
   - Modifiers adjust effective temperature in degrees Celsius ($^\circ\text{C}$) via the centralized `config/frost_factors.yaml` register.
   - **Asymmetric Conservatism Rule:** Aggravating factors (e.g. cold-air pooling bump, light sandy soil exposure per S2) apply unconditionally even from `coarse_context` regional data. Conversely, protective factors (e.g. firm, moist, weed-free soil, pre-freeze wetting) apply **ONLY** when their quality state is `valid` (verified via user-entered orchard management attributes).
   - When protective factors are derived from coarse satellite data (e.g. SMAP / ERA5-Land coarse soil moisture), they are surfaced in the UI as *"حفاظت احتمالی (اعمال‌نشده)"* with tooltip *"اطلاعات ماهواره‌ای کلان برای اعمال تخفیف حفاظتی کافی نیست؛ نیازمند تایید کاربر است"* and an effect of $0.0^\circ\text{C}$.
   - Total protective credit is strictly capped at $1.0^\circ\text{C}$ (the conservative lower bound of the $1.0\dots 1.7^\circ\text{C}$ range cited in S1 p. 72 from Snyder & Connell 1993).
   - Missing data never lowers risk. Evidence level remains `"C"` while thresholds remain unverified.
4. **Frost Regime Classification & Protection Advisory:**
   - **Radiative:** Clear skies ($\text{cloud cover} \le 30\%$) and calm winds ($\text{wind speed} \le 2.0\,\text{m/s}$). Strong nocturnal surface inversion allows active thermal methods (heaters, wind machines, selective inverted sinks / SIS) to be effective.
   - **Advective:** Windy ($\text{wind speed} \ge 4.5\,\text{m/s}$) with cold air advection, often accompanied by clouds. Active methods are ineffective due to turbulent mixing and absence of an inversion layer; advice focuses on passive soil management and pre-freeze soil moisture.
   - **Mixed / Unknown:** Intermediate or unresolvable atmospheric conditions.
   - Active methods vs advective conditions are accompanied by an agronomic review flag.
5. **Threshold Sets (`published_v1` vs `engine_default_v0`):**
   - Added `published_v1` in `config/frost_thresholds.yaml` with values from S1 and S2: unopened bud $-4^\circ\text{C}$, opening bud $-2^\circ\text{C}$, fruit $-2^\circ\text{C}$, swelling bud `null`; bloom $-1.7^\circ\text{C}$ (S1) with S2's $+2.0^\circ\text{C}$ stored as `conflicting_published_value`.
   - `engine_default_v0` is retained and explicitly labelled legacy / uncalibrated.
6. **Topographic Advice:**
   - Added explicit advice: *"بادشکن‌ها نباید مسیر تخلیه هوای سرد رو به پایین‌دست (Cold-Air Drainage) را مسدود کنند."*

---

### Item E10 Decisions: Orchard Ground-Truth Observations & Model Calibration
1. **Schema & Migration Integrity:**
   - Alembic migration `005_orchard_observations.py` establishes table `orchard_observations` (`id`, `orchard_id`, `observation_date`, `phenological_stage`, `min_temp_observed_c`, `damage_observed_fa`, `damage_severity`, `notes_fa`, `created_at`, `updated_at`).
   - Foreign key constraint references `orchards.id` with `ondelete="CASCADE"`.
   - Indexes added on `orchard_id`, `observation_date`, `damage_severity`, and composite `(orchard_id, observation_date)`.
   - Migration verified via clean `upgrade -> downgrade -> upgrade` cycle on PostgreSQL and SQLite.
2. **Ground-Truth CRUD API & Query Filtering:**
   - Complete CRUD endpoints implemented under `/api/v1/agriculture/frost/orchards/{id}/observations` protected by `require_frost_auth`:
     - `POST /observations`: Record ground-truth observation (201 Created).
     - `GET /observations`: List observations with optional filtering by `start_date`, `end_date`, and `damage_severity` (`none`, `light`, `moderate`, `severe`, `total`).
     - `GET /observations/{obs_id}`: Retrieve single observation.
     - `PUT /observations/{obs_id}`: Update observation severity and notes.
     - `DELETE /observations/{obs_id}`: Delete observation record (204 No Content).
---

## Phase 3 Redesign v2 Decisions

### Item R1: Per-Orchard Input Assembly, Soil Moisture Normalization & Spatial GFS Sharing
1. **Single Source of Truth for Platform Factors (P1):**
   - In accordance with Product Decision P1, input factors utilize existing platform analysis services:
     - Root-zone soil moisture from `app.services.agriculture.soil` / `soil_intelligence` (SMAP / ERA5-Land).
     - Field capacity ($FC$) and wilting point ($WP$) from `soil_intelligence` (ISRIC SoilGrids 250m water retention: wv0033 and wv1500).
     - Soil texture classification and sand content from `soil_intelligence` (ISRIC SoilGrids 250m).
     - Site elevation, slope, and aspect from `app.services.agriculture.terrain` (NASADEM 30m).
     - Cold-air pooling proxy from `app.services.agriculture.cold_air_pooling` (NASADEM 30m).
     - Dynamic atmospheric forecast factors (wind speed, direction, cloud cover, relative humidity/dewpoint) are extracted from NOAA/GFS0P25.
2. **Relative Soil Moisture Normalization:**
   - Moisture is normalized against the orchard's own physical soil characteristics:
     $$\text{relative} = \text{clamp}\left(\frac{\theta - WP}{FC - WP}, 0.0, 1.0\right)$$
   - If either $FC$ or $WP$ is unavailable, or if $FC \le WP$, normalized moisture is set to `None`, status is marked `"نامشخص"`, and subscore falls back to neutral $0.50$.
3. **GFS Spatial Cell Sharing and Thermodynamic Isolation:**
   - Raw GFS forecasts are indexed by 0.25-degree grid cells ($(\text{round}(\text{lat} \times 4)/4, \text{round}(\text{lon} \times 4)/4)$) and fetched once per cell.
   - For each orchard in that cell, elevation correction is computed strictly using the orchard's own site elevation $z_{\text{site}}$:
     $$\Delta T = \Gamma \cdot \frac{z_{\text{site}} - z_{\text{cell}}}{1000}$$
   - This ensures multiple orchards in the same macro-cell share a single network call while preserving exact local thermal differentiation.
4. **Caching Cadence and Staleness Gating:**
   - Static inputs (topography, soil texture, water retention) are cached long-term (30 days) with baseline timestamps.
   - Dynamic inputs (soil moisture) are cached for 6 hours.
   - Staleness is validated per factor against `DEFAULT_MAX_FACTOR_AGE_HOURS`:
     - Forecast series: 6 hours
     - Soil root-zone moisture: 120 hours (accounting for satellite assimilation cadence)
     - Phenological stage: 336 hours (14 days, per R4)
     - Static topography and soil maps: 8760 hours (1 year)

---

### Item R3: Weighted Factor Model Engine per Orchard, Breakpoints, and Safety Gate (GATE)
1. **Factor Group Weights (Exact Sum = 100.0%):**
   - The factor weights originate from the user's research summary (NOT from S1/S2, marked *"user research, unreferenced, no published basis"*):
     - `temperature_duration`: $40.0\%$ (margin of effective Tmin above stage critical temperature + duration rule)
     - `phenological_stage`: $25.0\%$ (S2 vulnerability ordering)
     - `soil_rootzone_moisture`: $7.5\%$ (normalized relative moisture)
     - `soil_texture_depth`: $7.5\%$ (ISRIC SoilGrids 250m texture classification & sand %)
     - `wind_speed`: $5.0\%$ (10m GFS wind speed at minimum temperature)
     - `wind_direction`: $5.0\%$ (downslope drainage alignment vs slope aspect)
     - `cloud_cover`: $2.5\%$ (total cloud cover entire atmosphere)
     - `humidity_dewpoint`: $2.5\%$ (2m relative humidity & Magnus dewpoint)
     - `topography_pooling`: $3.0\%$ (NASADEM 30m cold-air pooling proxy)
     - `topography_slope_aspect`: $2.0\%$ (NASADEM 30m slope steepness)
   - Loader validation strictly enforces $\sum w_i = 100.0\%$; any divergence raises an immediate `ValueError`.

2. **Complete Register of Placeholder Breakpoints ($s_i \in [0, 1]$):**
   All breakpoints are round, illustrative placeholders documented here for full transparency:
   - **Temperature + Duration ($w = 40.0\%$):**
     - $\Delta T = T_{\text{eff}} - T_{\text{crit}}$.
     - $\Delta T \le 0.0^\circ\text{C} \implies s = 1.00$ (adverse / lethal).
     - $\Delta T \ge 3.0^\circ\text{C} \implies s = 0.00$ (favorable / safe).
     - $0.0 < \Delta T < 3.0^\circ\text{C} \implies s = 1.0 - \frac{\Delta T}{3.0}$.
     - Duration rule met (e.g. continuous exposure) $\implies s = 1.00$.
   - **Phenological Stage ($w = 25.0\%$ per S2):**
     - `full_bloom` / `bloom`: $s = 1.00$ (most sensitive).
     - `early_bloom`: $s = 0.85$.
     - `fruit_set` / `fruit`: $s = 0.70$.
     - `bud_burst` / `opening_bud`: $s = 0.50$.
     - `unopened_bud`: $s = 0.30$ (most resistant).
     - `dormant`: $s = 0.10$.
     - Stale stage (>14 days) or unknown: $s = 1.00$ (most sensitive stage, flagged *"مرحله قدیمی/نامشخص"*).
   - **Relative Root-Zone Soil Moisture ($w = 7.5\%$):**
     - Relative moisture $m = \text{clamp}((\theta - WP)/(FC - WP), 0, 1)$.
     - $m \le 0.30 \implies s = 0.85$ (dry, adverse).
     - $m \ge 0.70 \implies s = 0.20$ (moist, favorable).
     - $0.30 < m < 0.70 \implies s = 0.85 - \frac{m - 0.30}{0.40} \times 0.65$.
     - Missing data ($FC$, $WP$, or $\theta$ missing) $\implies s = 0.50$ (neutral, status *"نامشخص"*).
   - **Soil Texture & Depth ($w = 7.5\%$):**
     - Light sandy soil ($\text{sand} > 70\%$) $\implies s = 0.80$ (adverse per S2).
     - Medium loam ($\text{sand } 35-70\%$) $\implies s = 0.50$ (neutral).
     - Heavy clay ($\text{clay} > 35\%$ or $\text{sand} < 35\%$) $\implies s = 0.20$ (favorable).
   - **Wind Speed at Tmin ($w = 5.0\%$):**
     - Calm: $v \le 1.0\,\text{m/s} \implies s = 0.85$ (radiative inversion risk, adverse).
     - Mild turbulent mixing: $1.5 \le v \le 4.0\,\text{m/s} \implies s = 0.20$ (inversion breakup, favorable).
     - Strong advective: $v \ge 6.0\,\text{m/s} \implies s = 0.85$ (advective freeze, adverse).
     - Linear transitions between $1.0\dots 1.5$ and $4.0\dots 6.0\,\text{m/s}$.
   - **Wind Direction vs Aspect ($w = 5.0\%$):**
     - Flat terrain ($\text{slope} < 1.0^\circ$) $\implies s = 0.50$ (neutral).
     - Cold advection sectors: empty list by default (flagged *"no published basis"*). If populated and wind inside sector $\implies s = 0.85$.
     - Downslope alignment $\delta = \min(|\theta_{\text{wind}} - \theta_{\text{aspect}}|, 360 - |\theta_{\text{wind}} - \theta_{\text{aspect}}|)$:
       - Along downslope ($\delta \le 45^\circ$) $\implies s = 0.30$ (ventilating, favorable).
       - Against downslope ($\delta \ge 135^\circ$) $\implies s = 0.80$ (drainage blockage, adverse).
       - Intermediate ($45^\circ < \delta < 135^\circ$): linear interpolation between $0.30$ and $0.80$.
   - **Cloud Cover ($w = 2.5\%$):**
     - Clear skies ($C \le 20\%$) $\implies s = 0.90$ (intense radiative cooling, adverse).
     - Overcast ($C \ge 70\%$) $\implies s = 0.10$ (greenhouse radiation trapping, favorable).
     - $20\% < C < 70\% \implies s = 0.90 - \frac{C - 20}{50} \times 0.80$.
   - **Relative Humidity & Dew Point ($w = 2.5\%$):**
     - Dry air ($RH \le 30\%$) $\implies s = 0.85$ (low dewpoint, rapid cooling, adverse).
     - Humid air ($RH \ge 70\%$) $\implies s = 0.20$ (latent heat of condensation, favorable).
     - $30\% < RH < 70\% \implies s = 0.85 - \frac{RH - 30}{40} \times 0.65$.
   - **Cold-Air Pooling Proxy ($w = 3.0\%$):**
     - Severe pooling ($p \ge 0.60$) $\implies s = 0.90$ (basin stagnation, adverse).
     - Minimal pooling ($p \le 0.30$) $\implies s = 0.10$ (convex terrain, favorable).
     - $0.30 < p < 0.60 \implies s = 0.10 + \frac{p - 0.30}{0.30} \times 0.80$.
   - **Slope Steepness ($w = 2.0\%$):**
     - Flat valley bottom ($\text{slope} \le 1.5^\circ$) $\implies s = 0.80$ (adverse).
     - Well-drained slope ($\text{slope} \ge 5.0^\circ$) $\implies s = 0.20$ (favorable).
     - $1.5^\circ < \text{slope} < 5.0^\circ \implies s = 0.80 - \frac{\text{slope} - 1.5}{3.5} \times 0.60$.

3. **Asymmetric Conservatism Floor:**
   - Factors designated `protective_capable: true` (`soil_rootzone_moisture`, `soil_texture_depth`) are strictly floored at $s_i \ge 0.50$ when based on `coarse_context` satellite/regional data.
   - Favorable subscores ($s_i < 0.50$) are unlocked **only** when data has `quality_state == "valid"` (e.g. verified user management input or calibrated field sensors).
   - This floor **never** applies to `temperature_duration`.

4. **Category Bands and Absolute Safety Gate (GATE):**
   - **Index Category Bands (Placeholders):**
     - $\text{Index} < 25.0 \implies$ `none` (عادی)
     - $25.0 \le \text{Index} < 45.0 \implies$ `watch` (دیده‌بانی)
     - $45.0 \le \text{Index} < 70.0 \implies$ `warning` (هشدار)
     - $\text{Index} \ge 70.0 \implies$ `critical` (بحرانی)
   - **GATE Category:**
     - If $T_{\text{effective, min}} \le T_{\text{crit}} \implies$ at least `warning`.
     - If duration rule met (E8 rules) $\implies$ `critical`.
   - **Final Category:**
     $$\text{Final Category} = \max(\text{Index Category}, \text{GATE Category})$$
   - The GATE guarantees that physical lethal conditions are **never** masked or diluted by favorable modifiers.

5. **Disclosure Metadata:**
   - `illustrative_only: true`
   - `index_is_probability: false`
   - `thresholds_verified: false`
   - `evidence_level: "C"`
   - Persian UI label: *"ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)"*

---

### Item R4: Per-Orchard Stage Tracking, Migration 006, and Conservative Staleness Gating
1. **Schema and Migration 006:**
   - Alembic migration `006_orchard_current_stage.py` adds:
     - `current_stage`: VARCHAR(50), nullable=True
     - `stage_updated_at`: DateTime(timezone=True), nullable=True
   - Model `Orchard` in `backend/app/db/models/frost.py` and schemas in `backend/app/schemas/frost.py` (`OrchardCreate`, `OrchardUpdate`, `OrchardResponse`) updated accordingly.
2. **PostgreSQL Migration Verification Cycle (Raw Command Evidence):**
   - Verified via clean `upgrade -> downgrade -> upgrade` test cycle on PostgreSQL:
   ```text
   $ alembic upgrade head
   INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
   INFO  [alembic.runtime.migration] Will assume transactional DDL.
   INFO  [alembic.runtime.migration] Running upgrade 005_orchard_observations -> 006_orchard_current_stage, Add current_stage and stage_updated_at to orchards table (R4)

   $ alembic downgrade -1
   INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
   INFO  [alembic.runtime.migration] Will assume transactional DDL.
   INFO  [alembic.runtime.migration] Running downgrade 006_orchard_current_stage -> 005_orchard_observations, Add current_stage and stage_updated_at to orchards table (R4)

   $ alembic upgrade head
   INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
   INFO  [alembic.runtime.migration] Will assume transactional DDL.
   INFO  [alembic.runtime.migration] Running upgrade 005_orchard_observations -> 006_orchard_current_stage, Add current_stage and stage_updated_at to orchards table (R4)
   ```
   - Verified columns via async SQLAlchemy reflection: `current_stage` and `stage_updated_at` confirmed present in PostgreSQL `orchards` table.
3. **Conservative Staleness Decision:**
   - Decision: A developmental stage older than 14 days (336 hours) without grower update is classified as stale and treated as unknown.
   - When stale, the risk model falls back to the **most sensitive configured developmental stage** (`full_bloom`, subscore $1.00$), flagged explicitly as *"مرحله قدیمی/نامشخص"*.
   - Rationale: In spring, phenological progression is rapid; assuming an out-of-date resistant stage (e.g. unopened bud from 3 weeks ago when trees are actually in full bloom) would dangerously underestimate mortality risk. Defaulting to maximum sensitivity ensures farmer vigilance.
   - Satellite-derived SOS/EOS phenology metrics are retained strictly as advisory hints in the UI and never overwrite grower observations.
















---

### Item R5: Per-Orchard Risk Evaluation Endpoints and Alert Dispatch
1. **Single Orchard Risk Assessment (`GET /api/v1/agriculture/frost/orchards/{id}/risk`):**
   - Coordinates input assembly (`assemble_orchard_inputs`), night aggregation across local midnight (18:00 to 09:00 IRST), duration interval calculations, and weighted factor scoring (`evaluate_weighted_frost_model`).
   - Returns multi-night evaluations with exact 10-factor breakdowns, raw values, quality states, staleness flags, subscores, contributions, GATE trigger state, and Persian category labels.
   - Preserves guidance label: `"ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)"` and flags `index_is_probability: false`, `thresholds_verified: false`.
2. **Orchards Risk Summary (`GET /api/v1/agriculture/frost/orchards/risk-summary`):**
   - Evaluates all registered orchards for the user with shared GFS 0.25° forecast caching (`shared_gfs_cell_cache`), eliminating duplicate network/GEE forecast calls for orchards located in the same GFS cell.
   - Elevation adjustments and lapse rate calculations remain strictly parcel-specific based on each orchard's own NASADEM elevation.
   - Results are sorted descending by worst-night risk severity (hierarchy: critical > warning > watch > none, then risk index descending).
3. **Alert Dispatch Gating (`POST /api/v1/agriculture/frost/evaluate-alerts`):**
   - Alerts are evaluated per orchard using `assess_single_orchard_risk` against `current_stage`.
   - Dispatch is strictly gated: notifications are dispatched ONLY for orchards where any forecast night reaches `warning` or `critical`.
   - Nights classified as `none` or `watch` do NOT trigger alerts.
   - Idempotency is preserved per rule and night: re-evaluating the same night at the same or lower severity does not send duplicate notifications; upward escalation (e.g. warning -> critical) dispatches the escalated alert.
4. **Recommendation Filtering:**
   - Agronomic recommendations (`GENERIC_RECOMMENDATIONS_FA`) are surfaced ONLY when the parcel's overall risk reaches `warning` or `critical`. For non-hazardous periods (`none`, `watch`), recommendations list is empty or informational only.

---

### Item R6: Pure Persian Per-Orchard UI Overhaul
1. **Overview Table of All Orchards:**
   - Implemented in `FrostRiskPage.tsx` using `frostApi.getFrostOrchardsRiskSummary()`.
   - Displays all registered orchards sorted descending by risk severity (hierarchy + risk index).
   - Columns: `نام باغ`, `مرحله رشدی` (with `⚠️ قدیمی/نامشخص` indicator when stale), `کمترین دمای مؤثر` (formatted in LTR with mathematical minus U+2212), `ساعات زیر آستانه` (or `"هیچ شب زیر آستانه نیست"` if 0), `رطوبت خاک` (relative root-zone moisture percent or `"نامشخص"`), `وزش باد` (speed in m/s or `"نامشخص"`), `ریسک راهنما ٪`, `رده نهایی` (colored category badge), and `عملیات` (select orchard button).
2. **Selected Orchard Multi-Night View and Exact 7-Column Factor Table:**
   - Compact nights table lists all nights with effective Tmin, hours below, guidance risk percent, GATE trigger status, and final category.
   - For the selected night, renders ONE factor table with the EXACT 7 required column headers:
     `عامل` | `مقدار` | `منبع و کیفیت و تاریخ داده` | `وضعیت` | `وزن` | `امتیاز جزئی` | `سهم`
   - Totals row presents total weight (100.0%) and total contribution equal to the guidance risk index.
   - Prominent GATE notice is displayed whenever the safety gate triggers (`gate_triggered == true`).
3. **Collapsible Recommendations:**
   - Surfaced only when the night's final category is `warning` or `critical`.
   - When severity is `none` or `watch`, technical physical recommendations are hidden with an explicit reassurance: `"هیچ توصیه فوری برای این شب وجود ندارد (رده خطر زیر سطح هشدار است)."`
4. **Pure Persian & Disclosure Honesty:**
   - Elimination of all English phrases: no English stage names like `(Early Bloom)` or `(Pistachio)`, no `(Watch)` or `(Advisory)`, no `0.0 h below critical threshold`.
   - Exact Persian guidance label rendered: `"ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)"`.
   - Explicit disclaimer that weights and thresholds are uncalibrated and illustrative.
   - Sub-zero numbers rendered in LTR direction with mathematical minus sign U+2212 (`−`).

---

### Item R7: Published Threshold Set Fix, Single Critical Mode, and Dynamic Stages
1. **Elimination of Invented T90 Mortality Numbers:**
   - Primary research sources (Hokmabadi 2010 [S1], Hokmabadi 2011 [S2]) report single critical temperatures per phenological stage rather than multi-tier (10%/90%) mortality curves.
   - `config/frost_thresholds.yaml` threshold set `published_v1` is configured with `single_critical: true` and all `t_critical_90_c` values are set to `null`.
   - Backend `load_frost_threshold_set` parses `single_critical: true`, avoids defaulting to synthesized $T_{10} - 2^\circ\text{C}$ kill thresholds, and sets `CropThresholdConfig.single_critical = True`.
   - Frontend components (`FrostNightCards.tsx`, `FrostTimelineChart.tsx`, `FrostRiskPage.tsx`) drop the 90% duration column, reference lines, and labels when single-critical threshold sets are active.
2. **Explicit Disclosure of Missing Swelling Bud Data:**
   - Source S2 provides no numerical critical temperature for the swelling bud stage.
   - In `config/frost_thresholds.yaml`, `swelling_bud` critical temperature is set to `null` with explicit note: `"در منبع S2 هیچ رقمی برای مرحله تورم جوانه ذکر نشده است (داده منتشرشده‌ای وجود ندارد)."`.
   - In the frontend UI stage dropdown, `swelling_bud` is disabled with that verbatim citation note.
3. **Opening Bud Label Verification:**
   - Verified that `opening_bud` in `config/frost_thresholds.yaml` and UI is labeled `"جوانه در حال باز شدن (Opening bud)"` at $-2.0^\circ\text{C}$.
4. **Dynamic Stage Dropdown per Active Threshold Set:**
   - Stage dropdown options in `FrostRiskPage.tsx` update dynamically based on the active `thresholdSet`:
     - When `published_v1`: exposes only stages defined in literature (`unopened_bud` at $-4.0^\circ\text{C}$, `opening_bud` at $-2.0^\circ\text{C}$, `bloom` at $-1.7^\circ\text{C}$, `fruit` at $-2.0^\circ\text{C}$, and disabled `swelling_bud`).
     - When `engine_default_v0`: exposes legacy placeholder stages.
   - Headless browser screenshot captured at `C:\Users\Jamali\Desktop\google_ui_screenshots\published_v1_stage_dropdown.png`.
   - Automated unit tests verified in `frontend/src/components/agriculture/__tests__/frost_r7_stage.test.ts`.

---

### Item R8: Source Honesty Banner and Native Unsmoothed Chart Points
1. **Source Honesty Banner:**
   - If a fake forecast provider is detected anywhere in the platform run (`source == "deterministic_fake"` or `provider == "FakeForecastProvider"`), a prominent warning banner is displayed at the top of the frost page:
     `داده شبیه‌سازی‌شده؛ برای تصمیم استفاده نشود`
   - Testid: `data-testid="fake-provider-honesty-banner"`.
2. **Native Chart Points and Elimination of Artificial Splines:**
   - In `FrostTimelineChart.tsx`, all curves (`<Line>` and `<Area>`) were converted from `type="monotone"` to `type="linear"`.
   - Native hourly GFS forecast timesteps are connected with straight linear segments without any cubic spline interpolation. This guarantees that the plotted temperature curve never dips lower than any discrete forecast data point.
   - Discrete forecast points are rendered visually on the primary forecast curve using `dot={{ r: 2.5, fill: '#2563eb' }}`.
3. **Explanation for Historical Sine Curve in Development Page:**
   - The user noted that during earlier development, the frost forecast temperature chart appeared as a smooth sine curve.
   - **Real Root Cause:** The chart was NOT hallucinating points or introducing an artificial trigonometric curve. Rather, `FakeForecastProvider` (used in test/dev environments prior to live GEE GFS integration) generates synthetic hourly diurnal temperatures using a mathematical cosine formula:
     ```python
     diurnal_phase = (hour - 2) * (2 * math.pi / 24.0)
     t_raw = midpoint - amplitude * math.cos(diurnal_phase)
     ```
     This deterministic synthetic diurnal model intentionally simulated a natural daily heating/cooling cycle. In contrast, real NOAA GFS 0.25° forecast data consists of physical atmospheric model outputs which exhibit complex, asymmetric weather fronts and temperature fluctuations.

