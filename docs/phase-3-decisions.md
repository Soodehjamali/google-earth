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
- **Evidence Level:** All frost advisory outputs maintain an evidence level of $\le \text{B}$ (`evidence_level: "B"`), reflecting the combination of synoptic NWP forecast and topographic proxy modeling without direct in-canopy telemetry.

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

### C7.1 Tile Token Transport Channels
Tile tokens travel via two primary channels depending on client integration:
1. **URL Path Segment:** Standard slippy map tile URLs follow `/api/v1/agriculture/tiles/{tile_token}/{z}/{x}/{y}.png`. Here the token is a path parameter.
2. **Query String Parameter:** Proxied tile requests or ad-hoc imagery queries supply `?token={token}` or `?tile_token={token}`.

### C7.2 Sanitization Filter & Verification
`TileTokenMaskingFilter` intercepts and scrubs both channels recursively across string messages, tuples, dicts, and list arguments in `logging.LogRecord`:
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






