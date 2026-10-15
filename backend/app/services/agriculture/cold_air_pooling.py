"""Cold-Air-Pooling Risk Proxy (Topography-Derived).

THIS MODULE COMPUTES A TOPOGRAPHY-DERIVED HEURISTIC PROXY, NOT A PHYSICAL
MICROCLIMATE ATMOSPHERIC BOUNDARY LAYER DYNAMICS MODEL (CFD).

Physical Principle:
During clear, calm radiative frost nights, cold dense air forms near the ground
due to radiative cooling, drains downslope under gravity (katabatic drainage),
and pools in topographic depressions, valley bottoms, and enclosed basins.
Terrain with low slope, negative Topographic Position Index (TPI), and low height
above the local drainage base/valley floor exhibits heightened susceptibility to
cold-air accumulation and severe radiation frosts.

Data Source:
NASADEM Merged DEM Global 1 arcsecond (~30m): ``NASA/NASADEM_HGT/001``

Mathematical Components:
1. Height above local valley floor (H_floor = z - z_min_local):
   f_floor = clamp(1.0 - (z - z_min_local) / scale_floor, 0.0, 1.0)
2. Micro-scale TPI (300m radius):
   f_tpi_300 = clamp(0.5 - (z - mean_300) / (2.0 * scale_tpi300), 0.0, 1.0)
3. Meso-scale TPI (1000m radius):
   f_tpi_1000 = clamp(0.5 - (z - mean_1000) / (2.0 * scale_tpi1000), 0.0, 1.0)
4. Slope flatness factor:
   f_slope = clamp(1.0 - slope_deg / max_slope_deg, 0.0, 1.0)

Combined Index:
   pooling_risk_proxy = (
       w_floor * f_floor +
       w_tpi300 * f_tpi_300 +
       w_tpi1000 * f_tpi_1000 +
       w_slope * f_slope
   )
All weights and scaling constants are exposed via ColdAirPoolingConfig.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.logging import get_logger
from app.services.agriculture.tile_auth import generate_signed_layer_token
from app.services.cache_service import cache_service

logger = get_logger(__name__)

NASADEM_DATASET_ID = "NASA/NASADEM_HGT/001"
NASADEM_ELEVATION_BAND = "elevation"

# Palette for Cold-Air-Pooling risk proxy (0.0 = low pooling risk, 1.0 = high pooling risk)
# Light yellow/green -> teal -> deep cobalt blue
POOLING_VIS_PALETTE = ["#f7fcf0", "#bae4bc", "#7bccc4", "#43a2ca", "#0868ac"]

POOLING_DISCLAIMER_FA = (
    "شاخص تجمع هوای سرد یک تخمین تقریبی و مبتنی بر عوارض توپوگرافی (مدل رقومی ارتفاعی NASADEM ۳۰ متری) "
    "است و یک شبیه‌ساز دینامیکی میکرواقلیم محسوب نمی‌شود (pooling_risk_proxy). "
    "این شاخص پتانسیل زهکشی و انباشت هوای سرد در فرورفتگی‌ها را ارزیابی می‌کند."
)


@dataclass
class ColdAirPoolingConfig:
    """Configurable weights and spatial scales for the cold-air-pooling proxy."""

    # Search radii in meters
    tpi_inner_radius_m: float = 300.0
    tpi_outer_radius_m: float = 1000.0
    valley_floor_radius_m: float = 2000.0

    # Heuristic weights (must sum to 1.0)
    weight_height_above_floor: float = 0.35
    weight_tpi_inner: float = 0.25
    weight_tpi_outer: float = 0.25
    weight_slope: float = 0.15

    # Scaling normalizers (in physical units)
    max_valley_height_scale_m: float = 50.0  # Beyond 50m above valley floor, pooling ~ 0
    tpi_inner_scale_m: float = 15.0         # TPI range [-15m, +15m]
    tpi_outer_scale_m: float = 30.0         # TPI range [-30m, +30m]
    slope_max_deg: float = 15.0             # Slopes > 15 deg have fast katabatic drainage (pooling ~ 0)

    def validate(self) -> None:
        """Validate weight normalization."""
        total_w = (
            self.weight_height_above_floor
            + self.weight_tpi_inner
            + self.weight_tpi_outer
            + self.weight_slope
        )
        if abs(total_w - 1.0) > 1e-4:
            raise ValueError(f"ColdAirPoolingConfig weights must sum to 1.0, got {total_w:.4f}")


DEFAULT_POOLING_CONFIG = ColdAirPoolingConfig()


@dataclass
class ColdAirPoolingResult:
    """Standard payload for cold-air-pooling topography analysis."""

    mean_pooling_risk_proxy: float
    p90_pooling_risk_proxy: float
    min_pooling_risk_proxy: float
    max_pooling_risk_proxy: float
    min_elevation_m: float
    max_elevation_m: float
    mean_elevation_m: float
    height_above_valley_floor_m: float
    mean_slope_deg: float
    tpi_300m: float
    tpi_1000m: float
    tile_url: Optional[str] = None
    tile_token: Optional[str] = None
    quality_state: str = "coarse_proxy"
    is_heuristic_proxy: bool = True
    disclaimer_fa: str = POOLING_DISCLAIMER_FA
    config_used: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Pure NumPy Implementation (for Unit/Synthetic Tests & Offline Processing)
# ---------------------------------------------------------------------------

def _circular_kernel_mean(grid: np.ndarray, radius_px: int) -> np.ndarray:
    """Compute local circular neighborhood mean using 2D uniform / circular convolution."""
    r = max(1, radius_px)
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    mask = (x * x + y * y) <= (r * r)
    kernel = mask.astype(float)
    kernel /= kernel.sum()

    # Pad array with edge replication to preserve boundary behavior
    padded = np.pad(grid, r, mode="edge")
    out = np.zeros_like(grid, dtype=float)

    # Convolution via 2D spatial correlation
    kh, kw = kernel.shape
    for i in range(kh):
        for j in range(kw):
            if kernel[i, j] > 0:
                out += kernel[i, j] * padded[i : i + grid.shape[0], j : j + grid.shape[1]]

    return out


def _circular_kernel_min(grid: np.ndarray, radius_px: int) -> np.ndarray:
    """Compute local minimum over a neighborhood."""
    r = max(1, radius_px)
    padded = np.pad(grid, r, mode="edge")
    out = np.full_like(grid, fill_value=np.inf, dtype=float)
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    mask = (x * x + y * y) <= (r * r)

    coords = np.argwhere(mask) - r
    for dy, dx in coords:
        slice_view = padded[r + dy : r + dy + grid.shape[0], r + dx : r + dx + grid.shape[1]]
        out = np.minimum(out, slice_view)
    return out


def _circular_kernel_max(grid: np.ndarray, radius_px: int) -> np.ndarray:
    """Compute local maximum over a neighborhood."""
    r = max(1, radius_px)
    padded = np.pad(grid, r, mode="edge")
    out = np.full_like(grid, fill_value=-np.inf, dtype=float)
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    mask = (x * x + y * y) <= (r * r)

    coords = np.argwhere(mask) - r
    for dy, dx in coords:
        slice_view = padded[r + dy : r + dy + grid.shape[0], r + dx : r + dx + grid.shape[1]]
        out = np.maximum(out, slice_view)
    return out


def compute_pooling_index_from_dem_array(
    dem: np.ndarray,
    cell_size_m: float = 30.0,
    config: Optional[ColdAirPoolingConfig] = None,
) -> Dict[str, Any]:
    """Compute cold-air-pooling proxy on a 2D DEM grid using pure NumPy.

    Fully independent of Earth Engine, suitable for mathematical unit tests,
    monotonicity checks, and elevation-independence verification.
    """
    cfg = config or DEFAULT_POOLING_CONFIG
    cfg.validate()

    dem = np.asarray(dem, dtype=float)
    if dem.ndim != 2:
        raise ValueError(f"Expected 2D DEM array, got shape {dem.shape}")

    # 1. Slope in degrees
    gy, gx = np.gradient(dem, cell_size_m)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))

    # 2. TPI at inner radius (e.g. 300m)
    r_inner_px = max(1, int(round(cfg.tpi_inner_radius_m / cell_size_m)))
    mean_inner = _circular_kernel_mean(dem, r_inner_px)
    tpi_inner = dem - mean_inner

    # 3. TPI at outer radius (e.g. 1000m)
    r_outer_px = max(1, int(round(cfg.tpi_outer_radius_m / cell_size_m)))
    mean_outer = _circular_kernel_mean(dem, r_outer_px)
    tpi_outer = dem - mean_outer

    # 4. Height above local valley floor and basin confinement (e.g. 2000m)
    r_valley_px = max(1, int(round(cfg.valley_floor_radius_m / cell_size_m)))
    min_valley = _circular_kernel_min(dem, r_valley_px)
    max_valley = _circular_kernel_max(dem, r_valley_px)
    local_relief = np.maximum(0.0, max_valley - min_valley)
    confinement = np.clip(local_relief / cfg.max_valley_height_scale_m, 0.0, 1.0)
    height_above_floor = np.maximum(0.0, dem - min_valley)

    # 5. Component normalization into [0.0, 1.0]
    # Inverted: lower height above floor modulated by local relief confinement
    f_floor = confinement * np.clip(1.0 - (height_above_floor / cfg.max_valley_height_scale_m), 0.0, 1.0)

    # Inverted: negative TPI (depression) -> higher pooling risk
    f_tpi_inner = np.clip(0.5 - (tpi_inner / (2.0 * cfg.tpi_inner_scale_m)), 0.0, 1.0)
    f_tpi_outer = np.clip(0.5 - (tpi_outer / (2.0 * cfg.tpi_outer_scale_m)), 0.0, 1.0)

    # Inverted: flatter slopes -> higher cold air stagnation
    f_slope = np.clip(1.0 - (slope_deg / cfg.slope_max_deg), 0.0, 1.0)

    # 6. Combined Heuristic Proxy
    pooling_risk_proxy = (
        cfg.weight_height_above_floor * f_floor
        + cfg.weight_tpi_inner * f_tpi_inner
        + cfg.weight_tpi_outer * f_tpi_outer
        + cfg.weight_slope * f_slope
    )
    pooling_risk_proxy = np.clip(pooling_risk_proxy, 0.0, 1.0)

    # Center pixel values (useful for single-site synthetic tests)
    cy, cx = dem.shape[0] // 2, dem.shape[1] // 2

    return {
        "pooling_risk_proxy": float(pooling_risk_proxy[cy, cx]),
        "pooling_risk_proxy_grid": pooling_risk_proxy,
        "center_pooling_risk_proxy": float(pooling_risk_proxy[cy, cx]),
        "mean_pooling_risk_proxy": float(np.mean(pooling_risk_proxy)),
        "p90_pooling_risk_proxy": float(np.percentile(pooling_risk_proxy, 90)),
        "min_pooling_risk_proxy": float(np.min(pooling_risk_proxy)),
        "max_pooling_risk_proxy": float(np.max(pooling_risk_proxy)),
        "center_tpi_inner": float(tpi_inner[cy, cx]),
        "center_tpi_outer": float(tpi_outer[cy, cx]),
        "center_height_above_floor": float(height_above_floor[cy, cx]),
        "center_slope_deg": float(slope_deg[cy, cx]),
        "is_heuristic_proxy": True,
        "quality_state": "coarse_proxy",
        "disclaimer_fa": POOLING_DISCLAIMER_FA,
    }


# ---------------------------------------------------------------------------
# Earth Engine Integration & Signed Tile Layer
# ---------------------------------------------------------------------------

def calculate_cold_air_pooling_ee(
    geometry: Any,
    config: Optional[ColdAirPoolingConfig] = None,
    buffer_m: float = 2000.0,
) -> ColdAirPoolingResult:
    """Compute cold-air-pooling raster & statistics using Google Earth Engine NASADEM.

    Generates an HMAC-signed slippy tile URL proxyable via
    ``/api/v1/agriculture/tiles/{layer_token}/{z}/{x}/{y}.png``.
    """
    import ee
    from app.services.earth_engine.authentication import initialize_earth_engine

    initialize_earth_engine()
    cfg = config or DEFAULT_POOLING_CONFIG
    cfg.validate()

    # Build EE Geometry
    if isinstance(geometry, dict):
        ee_geom = ee.Geometry(geometry)
    elif hasattr(geometry, "__geo_interface__"):
        ee_geom = ee.Geometry(geometry.__geo_interface__)
    else:
        ee_geom = geometry

    # Spatial context with buffer (valley context)
    buffered_geom = ee_geom.buffer(buffer_m)
    bounds_dict = ee_geom.bounds().getInfo()
    coords = bounds_dict["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    bbox_4 = [min(lons), min(lats), max(lons), max(lats)]

    # Load NASADEM
    dem = ee.Image(NASADEM_DATASET_ID).select(NASADEM_ELEVATION_BAND)

    # 1. Slope
    slope = ee.Terrain.slope(dem)

    # 2. TPI inner (e.g. 300m)
    mean_inner = dem.focal_mean(cfg.tpi_inner_radius_m, "circle", "meters")
    tpi_inner = dem.subtract(mean_inner).rename("tpi_inner")

    # 3. TPI outer (e.g. 1000m)
    mean_outer = dem.focal_mean(cfg.tpi_outer_radius_m, "circle", "meters")
    tpi_outer = dem.subtract(mean_outer).rename("tpi_outer")

    # 4. Valley floor, ridge max, and relief confinement (focal over buffer)
    valley_floor = dem.focal_min(cfg.valley_floor_radius_m, "circle", "meters")
    valley_max = dem.focal_max(cfg.valley_floor_radius_m, "circle", "meters")
    relief = valley_max.subtract(valley_floor)
    confinement = relief.divide(cfg.max_valley_height_scale_m).clamp(0.0, 1.0)
    height_above_floor = dem.subtract(valley_floor).rename("height_above_floor")

    # 5. Component normalization into [0.0, 1.0]
    f_floor = confinement.multiply(
        ee.Image(1.0)
        .subtract(height_above_floor.divide(cfg.max_valley_height_scale_m))
        .clamp(0.0, 1.0)
    )
    f_tpi_inner = (
        ee.Image(0.5)
        .subtract(tpi_inner.divide(2.0 * cfg.tpi_inner_scale_m))
        .clamp(0.0, 1.0)
    )
    f_tpi_outer = (
        ee.Image(0.5)
        .subtract(tpi_outer.divide(2.0 * cfg.tpi_outer_scale_m))
        .clamp(0.0, 1.0)
    )
    f_slope = (
        ee.Image(1.0)
        .subtract(slope.divide(cfg.slope_max_deg))
        .clamp(0.0, 1.0)
    )

    # 6. Combined Heuristic Proxy
    pooling_proxy = (
        f_floor.multiply(cfg.weight_height_above_floor)
        .add(f_tpi_inner.multiply(cfg.weight_tpi_inner))
        .add(f_tpi_outer.multiply(cfg.weight_tpi_outer))
        .add(f_slope.multiply(cfg.weight_slope))
        .rename("pooling_risk_proxy")
    )

    # 7. Parcel Summary Reductions
    combined = (
        pooling_proxy
        .addBands(dem.rename("elevation"))
        .addBands(height_above_floor)
        .addBands(slope.rename("slope"))
        .addBands(tpi_inner)
        .addBands(tpi_outer)
    )

    stats = combined.reduceRegion(
        reducer=(
            ee.Reducer.mean()
            .combine(ee.Reducer.percentile([90]), sharedInputs=True)
            .combine(ee.Reducer.minMax(), sharedInputs=True)
        ),
        geometry=ee_geom,
        scale=30,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    # 8. Generate signed tile proxy URL
    vis_params = {
        "min": 0.0,
        "max": 1.0,
        "palette": POOLING_VIS_PALETTE,
    }
    clipped = pooling_proxy.clip(buffered_geom)
    map_id = clipped.getMapId(vis_params)
    tile_url_template = map_id["tile_fetcher"].url_format

    token_id = hashlib.sha256(tile_url_template.encode("utf-8")).hexdigest()[:16]
    cache_service.set(f"tile_template:{token_id}", tile_url_template, ttl=7200)

    layer_token = generate_signed_layer_token(
        metric="pooling_risk_proxy",
        start_date="2000-02-11",
        end_date="2000-02-21",
        bbox=bbox_4,
        token_id=token_id,
        ttl_seconds=7200,
    )
    proxied_tile_url = f"/api/v1/agriculture/tiles/{layer_token}/{{z}}/{{x}}/{{y}}.png"

    mean_proxy = float(stats.get("pooling_risk_proxy_mean", 0.5))
    p90_proxy = float(stats.get("pooling_risk_proxy_p90", mean_proxy))
    min_proxy = float(stats.get("pooling_risk_proxy_min", mean_proxy))
    max_proxy = float(stats.get("pooling_risk_proxy_max", mean_proxy))
    min_elev = float(stats.get("elevation_min", 1000.0))
    max_elev = float(stats.get("elevation_max", 1000.0))
    mean_elev = float(stats.get("elevation_mean", 1000.0))
    haf = float(stats.get("height_above_floor_mean", 0.0))
    slp = float(stats.get("slope_mean", 0.0))
    tpi_in = float(stats.get("tpi_inner_mean", 0.0))
    tpi_out = float(stats.get("tpi_outer_mean", 0.0))

    return ColdAirPoolingResult(
        mean_pooling_risk_proxy=round(mean_proxy, 3),
        p90_pooling_risk_proxy=round(p90_proxy, 3),
        min_pooling_risk_proxy=round(min_proxy, 3),
        max_pooling_risk_proxy=round(max_proxy, 3),
        min_elevation_m=round(min_elev, 1),
        max_elevation_m=round(max_elev, 1),
        mean_elevation_m=round(mean_elev, 1),
        height_above_valley_floor_m=round(haf, 1),
        mean_slope_deg=round(slp, 1),
        tpi_300m=round(tpi_in, 2),
        tpi_1000m=round(tpi_out, 2),
        tile_url=proxied_tile_url,
        tile_token=layer_token,
        quality_state="coarse_proxy",
        is_heuristic_proxy=True,
        disclaimer_fa=POOLING_DISCLAIMER_FA,
        config_used=asdict(cfg),
    )
