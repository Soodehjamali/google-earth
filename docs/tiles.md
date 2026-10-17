# Architecture and Security Specification: Map Tiles and Raster Proxy

This document defines the multi-layer mapping architecture, failover policies, security hardening, and licensing attributions implemented across the Agricultural Intelligence Platform.

---

## 1. Basemap Architecture & Multi-Source Context

The platform provides a flexible, configurable geographic context designed for semi-arid agricultural analysis (e.g., pistachio orchards in Yazd, Kerman, and Fars):

1. **Configurable Basemap Provider**:
   - **Default Configuration**: OpenStreetMap standard raster tiles (`tile.openstreetmap.org/{z}/{x}/{y}.png`) with the Sentinel-2 true-color proxy overlay from Google Earth Engine.
   - **Direct Google Satellite Tiles**: Restricted behind the environment feature flag `ALLOW_GOOGLE_DIRECT_TILES` (or `VITE_ALLOW_GOOGLE_DIRECT_TILES=true`, default `false`). When enabled, Google Satellite Imagery (`mt0.google.com/vt/lyrs=s`, `mt1.google.com/vt/lyrs=s`) and Google Hybrid Reference (`lyrs=h`) are rendered up to zoom level 19 (~0.6 m/pixel).
2. **Street & Administrative Mode**:
   - **Source**: OpenStreetMap standard raster tiles (`tile.openstreetmap.org/{z}/{x}/{y}.png`).
3. **Resilient Failover Policy**:
   - The satellite tile provider is **not** disabled by a single transient tile error or network glitch.
   - A consecutive error counter (`consecutiveSatelliteErrorsRef`) monitors satellite tile fetch failures.
   - Only after **5 consecutive tile failures** does the map automatically switch to OpenStreetMap as a last-resort fallback.
   - When fallback occurs, a non-blocking warning banner notifies the user and provides a **"تلاش مجدد" (Retry)** button that resets the counter and attempts to re-engage the satellite provider.
4. **Token Expiration & 403 Separation**:
   - An HTTP 403 error resulting from an expired or refreshed analysis raster token triggers an automatic token refresh and retry cycle.
   - 403 errors and analysis raster layer errors are strictly excluded from the `consecutiveSatelliteErrorsRef` counter so expired analysis tokens **never** trigger an erroneous basemap fallback.

---

## 2. Analysis Raster Layers & Backend Tile Proxy

Satellite and gridded rasters computed by Google Earth Engine (Sentinel-2, MODIS, SMAP, ISRIC SoilGrids) are **never requested directly by the client browser**. All tiles are routed through a secure, caching backend proxy:

```
Endpoint: GET /api/v1/agriculture/tiles/{layer_token}/{z}/{x}/{y}.png
```

### Defense-in-Depth Security Controls:
1. **Cryptographic HMAC-SHA256 Token Signing**:
   - The `layer_token` is an HMAC-SHA256 signed structure binding:
     - `tid`: Unique layer token identifier.
     - `m`: Target metric (e.g., `ndvi`, `ndmi`, `lst_day`, `true_color`).
     - `s`, `e`: Observation date range (`YYYY-MM-DD`).
     - `b`: Polygon bounding box `[lon_min, lat_min, lon_max, lat_max]`.
     - `exp`: Epoch expiration timestamp (7200 seconds / 2 hours).
   - Any signature tampering, parameter alteration, or forged token immediately returns **HTTP 403 Forbidden** (`ERR_TILE_FORBIDDEN`).
   - Expired tokens return **HTTP 403 Forbidden** (`ERR_TILE_EXPIRED`).
2. **Slippy-Map Coordinate & Zoom Restriction**:
   - Tile zoom level is strictly bounded to $z \in [8, 20]$. Any zoom outside this range returns **HTTP 404 Not Found** (`ERR_TILE_OUT_OF_BOUNDS`).
   - Tile spatial coordinates $(z, x, y)$ are projected to WGS84 bounding box $[tile\_w, tile\_s, tile\_e, tile\_n]$ and tested against the analysis polygon bounding box (with a $+0.05^\circ$ safety buffer). Coordinates outside the boundary return **HTTP 404 Not Found** (`ERR_TILE_OUT_OF_BOUNDS`).
3. **Concurrency Semaphore**:
   - Upstream Earth Engine tile fetches are throttled through an `asyncio.Semaphore(10)`, capping concurrent requests to 10 simultaneous downloads to prevent event-loop congestion or thread exhaustion.
4. **Per-IP In-Memory Rate Limiting**:
   - The tile rate limiter is **in-memory per process**, maintaining a sliding 60-second window capped at 180 tile requests per minute.
   - Client identity is keyed by client IP, reading the `X-Forwarded-For` header when operating behind a reverse proxy (taking the first client IP) and falling back to `request.client.host`. Exceeding requests receive **HTTP 429 Too Many Requests** (`ERR_TILE_RATE_LIMIT`).
5. **Private Caching & Confidentiality**:
   - Responses emit `Cache-Control: private, max-age=86400` headers.
   - Cryptographic tokens are **masked from Uvicorn access logs and server logs** via a dedicated `TileTokenMaskingFilter` (logging `/tiles/***MASKED***/{z}/{x}/{y}.png`).
   - Upstream responses are cached in Redis/memory with key `tile_img:{token_id}:{z}:{x}:{y}`.
6. **Canonical Path Location & Real Security Protection**:
   - Tile tokens must reside exclusively in the canonical URL path segment (`/tiles/{layer_token}/{z}/{x}/{y}.png`). Query-string tokens (`?token=...` or `?tile_token=...`) are strictly rejected with **HTTP 400 Bad Request** (`ERR_CANONICAL_PATH_TOKEN_REQUIRED`).
   - Reverse proxies, Application Load Balancers (ALBs), and browser history record URLs in access logs. Application log masking protects server logs, but cannot prevent upstream infrastructure URL logging. The real protection against token leakage and reuse relies upon:
     - Ephemeral token lifespan (TTL $\le 2$ hours).
     - Strict spatial bounding box binding (`bbox`) preventing off-parcel tile requests.
     - Per-IP sliding-window rate limiting (180 req/min).

---

## 3. Layer Attributions & Licensing Compliance

### Visible Attribution Display:
The map interface renders a permanent, visible attribution bar:
- **Default Basemap**: `© OpenStreetMap contributors | Sentinel-2 True-Color (Proxy)` (ODbL / Copernicus)
- **Direct Google Satellite** (when enabled): `© Google Satellite` / `© Google Reference`
- **Copernicus Sentinel-2 Analysis**: `Contains modified Copernicus Sentinel data`

### Neutral Licensing Statement:
> [!NOTE]
> Compliance with Google Earth Engine Commercial Terms of Service depends strictly on the deploying organization's Google Cloud Platform and Earth Engine commercial license agreement. The application codebase proxies real Earth Engine map tiles without modifying underlying data, but code does not and cannot verify the customer's commercial license status.

