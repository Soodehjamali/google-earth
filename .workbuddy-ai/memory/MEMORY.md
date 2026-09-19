# Project Memory

## Running tests (important)

- Use the project venv: `backend/.venv/Scripts/python.exe -m pytest`.
  The managed bundled interpreter has no pytest installed.
- Integration tests are skipped by default (26 skips across the two
  `tests/integration/test_*_integration.py` files); gate with
  `RUN_GEE_INTEGRATION_TESTS=1`.
- `backend/app/services/agriculture/` and `backend/tests/` are
  **untracked** in git, so `git diff` shows nothing for them. Use
  `git ls-files --others --exclude-standard` to enumerate them.

## Test-count history

| After phase | Passed | Skipped |
|-------------|--------|---------|
| Phase F | 885 | 26 |
| Phase G | 1041 | 26 |
| Phase H | 1135 | 35 (26 gated + 9 terrain integration) |

## Roadmap (current numbering)

A foundation, B primitives, C vegetation, D climate, E thermal,
F water & soil moisture, G land cover, **H terrain**, I soil
properties, J crop & phenology, K quality/fallback/provenance,
L unified API v1.

## Project conventions

### Stack
- Backend: FastAPI 0.115 + SQLAlchemy 2.0 async + asyncpg + Alembic, Postgres (port 5433)
- Earth Engine: `earthengine-api==1.1.4`, service account via `credentials/gee-key.json`
- Frontend: React 19 + TypeScript 5.8 + Vite 6 + MapLibre GL 4.7 + Recharts 2.15, pnpm
- UI is bilingual: Persian (`name_fa`) and English labels throughout

### Running things
- Backend venv: `backend/.venv` (Python 3.11)
- Tests: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/unit -q`
- Docker: `docker-compose.yml` at repo root (postgres 5433, backend 8000, frontend 5173)
- GEE integration tests are opt-in: `RUN_GEE_INTEGRATION_TESTS=1`
- GEE service account currently LACKS `roles/earthengine.viewer`, so all
  live-compute integration tests skip with that exact IAM reason. The
  import bug that made them skip silently is fixed (see 2026-09-18 notes);
  they will run once the IAM role is granted. Unit suite is unaffected.

### Code conventions (established, follow these)
- **Logging: use positional `%s` formatting, never keyword arguments.**
  `app/core/logging.py::get_logger` returns a plain stdlib
  `logging.Logger`, not a structlog logger, despite structlog being in
  requirements. `logger.info("msg", key=value)` raises TypeError, but only
  when a record is actually emitted, so it hides at INFO level and breaks
  on error paths. There are regression tests for this.
- **Nothing may hardcode a dataset ID, band name, scale factor or unit.**
  Everything goes through `app/services/agriculture/registry/`.
- **`parse_reduction_result` must be given a `band_spec` for any band
  whose `scale_factor` is not 1.0.** Earth Engine returns *raw stored
  counts*; the conversion to physical units happens at this one boundary.
  Omitting it returns raw counts silently — a MODIS LST value comes back
  as ~15000 instead of ~300 K. The exception is normalised indices, whose
  scale factor is applied inside the image expression before reduction.
- **Pure formulas live separately from Earth Engine expressions.** The pure
  version is what the tests pin; the `ee` version mirrors it. Modules that
  must stay importable without credentials accept `ee` as an injected
  argument.
- **Test fakes must mirror the real contract, not the convenient one.**
  The Earth Engine fake supplies *raw counts* so that a missing
  scale-factor conversion fails the test rather than passing it.
- **`Metric.limitations` entries must be plain strings**, and
  `MetricResult.limitations` must be strings too. A single-element tuple
  silently nests, and the resulting `TypeError` appears only at render.
- `app/services/agriculture/` must import cleanly without `ee` being
  initialised. There is a test verifying this.

## Hard rules established for this project

These came from the user's specification and must not be relaxed.

1. **Never guess dataset parameters.** Dataset ID, band name, temporal
   coverage, spatial resolution, unit, and scale factor must each be
   verified against the GEE Data Catalog or official agency docs. If a
   value cannot be verified, mark it unverified — never substitute a
   plausible number.
2. **Every output carries provenance**: source dataset, dataset ID, bands,
   formula, unit, spatial resolution, temporal resolution, aggregation
   method, quality, and limitations.
3. **Never diagnose disease, pests or nutrient deficiency** from satellite
   data. Only `vegetation stress`, `water stress`,
   `chlorophyll-related signal`, or `possible anomaly`.
4. **Credentials never reach the frontend.** `credentials/gee-key.json`
   stays server-side only.
5. **Missing data is not zero.** Return `insufficient_data`, never a
   silent zero.
6. **Proxies are named as proxies.** e.g. `CWSI_proxy`, `salinity_proxy`,
   `PAR_proxy`.
7. **Preserve and reuse existing architecture.** Do not re-implement
   capabilities that already exist.
8. **Never emit a `canopy_temperature` metric.** Land surface temperature
   is a mixed-pixel skin temperature; canopy temperature requires a
   close-range thermal camera or a surface-energy-balance inversion. A
   source-scan test enforces this across the whole package.

## Architecture notes

### Existing code worth reusing (pre-engine)
- `app/services/earth_engine/authentication.py` — robust auth with 7 error
  codes, never leaks credentials. Reuse as-is.
- `app/services/earth_engine/preprocessing.py` — SCL and QA60 cloud masking.
- `app/services/earth_engine/indices.py` — NDVI/EVI/SAVI/NDWI + combined
  reducer (mean/stdDev/min/max/median/percentiles).
- `app/db/models/` — Location, Analysis, DatasetUsage, TimeSeries, Report.
  `result_data` is JSONB, which is sufficient; no new tables needed.
- `app/core/exceptions.py` — 11 exception classes with status codes.

### Known defects found during audit (not yet fixed)
- `frontend/src/components/MapView.tsx` — layer toggle targets
  `{layerId}-layer` IDs that are never added to the map, so toggling does
  nothing. Legend is hardcoded to three fixed items. Opacity slider state
  is never applied via `setPaintProperty`.
- `backend/app/api/v1/maps.py` — returns palettes but no tile URLs, so no
  raster layer can actually render. Also has a redundant duplicate
  `select(Analysis)` query.
- `backend/app/services/cache_service.py` — implemented but wired to no
  endpoint.
- `backend/app/services/earth_engine/statistics.py` — loads the S2
  ImageCollection a second time just to count images.
- `backend/app/services/earth_engine/reducers.py` — `reduce_temporal` calls
  `getInfo()` per image; the `add_date_band` helper is defined but unused.
- `backend/app/api/v1/{climate,soil,water,landcover,stress,risk}.py` — all
  return `not_implemented` stubs.
- `backend/_check_keys.py`, `backend/_diag_key.py` — stray diagnostic
  scripts, flagged for cleanup in Phase N.

## External service notes

- **ISRIC SoilGrids REST API** (`rest.isric.org/soilgrids/v2.0/`) is
  currently **paused** with no restoration timeline, and is labelled beta
  with no uptime guarantee. Conversion factors (d-factors) and depth
  interval strings remain unverified as a result and are marked
  `PENDING_VERIFICATION` in the registry.
- **Earth Engine has no native flow accumulation / flow direction / TWI
  function.** Only local per-pixel derivatives exist in `ee.Terrain`
  (`slope`, `aspect`, `hillshade`, `products`, `fillMinima`).
