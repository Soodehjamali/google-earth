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









