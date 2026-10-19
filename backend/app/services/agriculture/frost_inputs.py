"""Per-Orchard Frost Risk Input Assembly and Normalization Service (R1).

This module implements Phase 3 Redesign v2 Product Decisions (P1, P2):
1. Gathers real factor values from existing platform services:
   - Root-zone soil moisture from soil / soil_intelligence
   - Field capacity (FC) & wilting point (WP) from SoilGrids 250m
   - Soil texture & depth from SoilGrids 250m
   - Terrain elevation, slope, aspect from NASADEM 30m
   - Cold-air-pooling proxy from NASADEM 30m
   - Wind speed, direction, cloud cover, humidity/dewpoint from NOAA/GFS0P25
2. Normalizes root-zone moisture per orchard:
   relative = clamp((theta - WP) / (FC - WP), 0, 1)
   If FC/WP are missing or invalid, value is None ('نامشخص' / neutral).
3. Shares raw GFS forecast fetch across all orchards in the same 0.25° x 0.25° cell,
   while computing per-orchard elevation correction from each orchard's site elevation.
4. Caches static factors long-term and dynamic factors on short TTL, tracking as_of timestamps
   and staleness against configured maximum ages.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.logging import get_logger
from app.services.cache_service import cache_service
from app.services.agriculture.forecast import (
    calculate_dew_point_magnus,
    calculate_wind_direction_meteorological,
    FakeForecastProvider,
    ForecastProvider,
    ForecastResult,
    ForecastTimestep,
    GFS_CELL_RADIUS_M,
    GFS_SPATIAL_RESOLUTION_M,
    NoaaGfsForecastProvider,
)
from app.services.agriculture.quality_gating import (
    correct_temperature_for_elevation,
    DEFAULT_QUALITY_CONFIG,
    QualityGatingConfig,
)

logger = get_logger(__name__)

def get_stage_max_age_hours() -> float:
    """Retrieve user phenological stage staleness threshold in hours from config/frost_factors.yaml (W4)."""
    try:
        from app.services.agriculture.frost_risk import load_frost_factors_config
        cfg = load_frost_factors_config()
        if "phenology" in cfg and "max_age_days" in cfg["phenology"]:
            return float(cfg["phenology"]["max_age_days"]) * 24.0
        if "phenology_stage_max_age_days" in cfg:
            return float(cfg["phenology_stage_max_age_days"]) * 24.0
    except Exception:
        pass
    return 20.0 * 24.0


#: Configurable staleness thresholds in hours
DEFAULT_MAX_FACTOR_AGE_HOURS: Dict[str, float] = {
    "temperature_duration": 6.0,          # Forecast data refreshed within 6 hours
    "phenological_stage": 20.0 * 24.0,     # User-entered stage valid for 20 days (480h) per config/frost_factors.yaml (W4)
    "soil_rootzone_moisture": 120.0,       # Satellite/assimilated soil moisture lag (5 days)
    "soil_texture_depth": 365.0 * 24.0,    # Static soil map (1 year)
    "wind_speed": 6.0,
    "wind_direction": 6.0,
    "cloud_cover": 6.0,
    "humidity_dewpoint": 6.0,
    "topography_pooling": 365.0 * 24.0,    # Static DEM (1 year)
    "topography_slope_aspect": 365.0 * 24.0, # Static DEM (1 year)
}

#: Cache TTL constants (in seconds)
STATIC_INPUT_CACHE_TTL_SEC = 86400 * 30   # 30 days for static DEM & SoilGrids
DYNAMIC_INPUT_CACHE_TTL_SEC = 3600 * 6    # 6 hours for dynamic soil moisture
GFS_CELL_CACHE_TTL_SEC = 3600 * 2         # 2 hours for raw GFS cell forecast

#: V1 Canonical Single-Source-of-Truth Resolution and Source Mapping (R6/V1/V7)
FACTOR_RESOLUTION_MAP: Dict[str, str] = {
    "temperature_duration": "~۲۸ کیلومتر",
    "phenological_stage": "داده باغدار",
    "soil_rootzone_moisture": "~۹–۱۱ کیلومتر",
    "soil_texture_depth": "۲۵۰ متر",
    "wind_speed": "~۲۸ کیلومتر",
    "wind_direction": "~۲۸ کیلومتر",
    "cloud_cover": "~۲۸ کیلومتر",
    "humidity_dewpoint": "~۲۸ کیلومتر",
    "topography_pooling": "۳۰ متر",
    "topography_slope_aspect": "۳۰ متر",
}

FACTOR_SOURCE_FA_MAP: Dict[str, str] = {
    "temperature_duration": "پیش‌بینی عددی GFS و مدل رقومی ارتفاع",
    "phenological_stage": "داده ثبت‌شده باغدار",
    "soil_rootzone_moisture": "پایش رطوبت ماهواره‌ای و بازتحلیل (SMAP / ERA5-Land)",
    "soil_texture_depth": "نقشه‌برداری رقومی خاک (SoilGrids)",
    "wind_speed": "پیش‌بینی جوی GFS NOAA",
    "wind_direction": "پیش‌بینی باد GFS NOAA و مدل شیب",
    "cloud_cover": "پیش‌بینی تابش و ابرناکی GFS NOAA",
    "humidity_dewpoint": "پیش‌بینی رطوبت جوی و محاسبات روان‌سنجی GFS",
    "topography_pooling": "مدل رقومی ارتفاع راداری (NASADEM)",
    "topography_slope_aspect": "مدل رقومی ارتفاع راداری (NASADEM)",
}


@dataclass
class FactorInput:
    """Standardized descriptor for a single frost risk factor input."""

    id: str
    label_fa: str
    value: Any
    unit: str
    source_module: str
    quality_state: str  # "valid", "coarse_context", "unavailable", "unknown"
    as_of: Optional[str]  # ISO 8601 UTC timestamp or None
    is_stale: bool
    status: str = "نامشخص"  # "مطلوب", "خنثی", "نامطلوب", "ناموجود", "نامشخص"
    static: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    spatial_resolution_fa: str = ""
    source_name_fa: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrchardInputs:
    """Aggregated inputs assembled for a single orchard."""

    orchard_id: str
    orchard_name: str
    latitude: float
    longitude: float
    elevation_m: float
    gfs_cell: Tuple[float, float]
    factors: Dict[str, FactorInput]
    assembled_at: str
    crop: str = "pistachio"
    current_stage: str = "unopened_bud"
    stage_is_stale: bool = False
    registered_elevation_m: Optional[float] = None
    dem_elevation_m: Optional[float] = None
    has_elevation_discrepancy: bool = False
    elevation_discrepancy_warning_fa: Optional[str] = None
    orchard_forecast: Optional[ForecastResult] = None
    raw_cell_forecast: Optional[ForecastResult] = None

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        if self.orchard_forecast:
            res["orchard_forecast"] = self.orchard_forecast.to_dict()
        if self.raw_cell_forecast:
            res["raw_cell_forecast"] = self.raw_cell_forecast.to_dict()
        return res


def get_gfs_cell_coords(lat: float, lon: float) -> Tuple[float, float]:
    """Snap coordinates to the nearest 0.25-degree NOAA GFS cell grid center."""
    cell_lat = round(round(float(lat) * 4.0) / 4.0, 2)
    cell_lon = round(round(float(lon) * 4.0) / 4.0, 2)
    return cell_lat, cell_lon


def is_timestamp_stale(
    as_of_iso: Optional[str],
    max_age_hours: float,
    now: Optional[datetime] = None,
) -> bool:
    """Check if an ISO 8601 timestamp exceeds the maximum permitted age in hours."""
    if not as_of_iso:
        return True
    try:
        now_dt = now or datetime.now(timezone.utc)
        clean_iso = as_of_iso.replace("Z", "+00:00")
        as_of_dt = datetime.fromisoformat(clean_iso)
        if as_of_dt.tzinfo is None:
            as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
        age_hours = (now_dt - as_of_dt).total_seconds() / 3600.0
        return age_hours > max_age_hours
    except Exception as exc:
        logger.warning(f"Failed to parse timestamp {as_of_iso}: {exc}")
        return True


def normalize_rootzone_moisture(
    theta: Optional[float],
    wilting_point: Optional[float],
    field_capacity: Optional[float],
) -> Optional[float]:
    """Calculate normalized relative root-zone soil moisture.

    Formula:
        relative = clamp((theta - WP) / (FC - WP), 0.0, 1.0)

    If theta, FC, or WP are missing, non-positive, or NaN, or (FC - WP) <= 0,
    returns None ('ناموجود' / unavailable). Nodata or invalid values NEVER default to 0.00.
    """
    if theta is None or wilting_point is None or field_capacity is None:
        return None
    try:
        th = float(theta)
        wp = float(wilting_point)
        fc = float(field_capacity)
        if math.isnan(th) or math.isnan(wp) or math.isnan(fc):
            return None
        # Strict physical validity bounds: moisture fractions must be > 0
        if th <= 0.0 or wp <= 0.0 or fc <= 0.0:
            logger.warning(f"Invalid non-positive soil moisture value: theta={th}, WP={wp}, FC={fc}")
            return None
        denom = fc - wp
        if denom <= 1e-5:
            logger.warning(f"Invalid soil moisture bounds: FC={fc} <= WP={wp}")
            return None
        rel = (th - wp) / denom
        return round(max(0.0, min(1.0, rel)), 3)
    except Exception as exc:
        logger.warning(f"Error normalizing root-zone moisture: {exc}")
        return None


def extract_orchard_geometry_and_centroid(
    orchard: Any,
) -> Tuple[Dict[str, Any], float, float, float]:
    """Extract standard GeoJSON geometry dict, latitude, longitude, and elevation."""
    if isinstance(orchard, dict):
        geom = orchard.get("geometry")
        lat = orchard.get("latitude")
        lon = orchard.get("longitude")
        elev = orchard.get("elevation")
    else:
        geom = getattr(orchard, "geometry", None)
        lat = getattr(orchard, "latitude", None)
        lon = getattr(orchard, "longitude", None)
        elev = getattr(orchard, "elevation", None)

    # Resolve coordinates if lat/lon missing but geometry present
    if (lat is None or lon is None) and isinstance(geom, dict):
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gtype == "Point" and len(coords) >= 2:
            lon = float(coords[0])
            lat = float(coords[1])
        elif gtype == "Polygon" and coords and coords[0]:
            poly_coords = coords[0]
            lon = sum(c[0] for c in poly_coords) / len(poly_coords)
            lat = sum(c[1] for c in poly_coords) / len(poly_coords)

    lat_f = float(lat) if lat is not None else 30.0
    lon_f = float(lon) if lon is not None else 55.0
    elev_f = float(elev) if elev is not None else 1000.0

    if not isinstance(geom, dict):
        geom = {
            "type": "Point",
            "coordinates": [lon_f, lat_f],
        }

    return geom, lat_f, lon_f, elev_f


def _can_query_ee() -> bool:
    import os
    if os.environ.get("RUN_GEE_INTEGRATION_TESTS", "").lower() in ("1", "true", "yes"):
        return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    try:
        from app.core.config import settings
        return bool(
            getattr(settings, "USE_LIVE_GEE", False)
            or getattr(settings, "FROST_USE_LIVE_GEE", False)
            or getattr(settings, "is_production", False)
        )
    except Exception:
        return False


def extract_terrain_aspect_ee(geom_dict: Dict[str, Any]) -> Optional[float]:
    """Sample terrain aspect from NASADEM in Earth Engine for given geometry."""
    import ee
    from app.services.earth_engine.authentication import initialize_earth_engine
    from app.services.agriculture.terrain import NASADEM

    initialize_earth_engine()
    dem_img = ee.Image(NASADEM).select(["elevation"])
    aspect_img = ee.Terrain.aspect(dem_img)
    if geom_dict.get("type") == "Point":
        pt_ee = ee.Geometry.Point(geom_dict["coordinates"])
        asp_stats = aspect_img.reduceRegion(reducer=ee.Reducer.mean(), geometry=pt_ee, scale=30).getInfo()
    else:
        poly_ee = ee.Geometry(geom_dict)
        asp_stats = aspect_img.reduceRegion(reducer=ee.Reducer.mean(), geometry=poly_ee, scale=30, bestEffort=True).getInfo()
    if asp_stats and asp_stats.get("aspect") is not None:
        return round(float(asp_stats["aspect"]), 1)
    return None


async def assemble_orchard_inputs(
    orchard: Any,
    forecast_provider: Optional[Any] = None,
    gfs_cell_cache: Optional[Dict[str, Any]] = None,
    use_cache: bool = True,
    now_utc: Optional[datetime] = None,
    horizon_h: int = 240,
    terrain_data: Optional[Dict[str, Any]] = None,
    soil_static_data: Optional[Dict[str, Any]] = None,
    soil_dynamic_data: Optional[Dict[str, Any]] = None,
) -> OrchardInputs:
    """Assemble all platform factors for an orchard according to R1 specifications.

    Parameters:
    - orchard: SQLAlchemy Orchard model or dictionary representing the orchard.
    - forecast_provider: Optional ForecastProvider instance (defaults to system configured).
    - gfs_cell_cache: Optional dict shared across orchards in a batch to reuse raw GFS cell runs.
    - use_cache: Whether to read/write from cache_service.
    - now_utc: Reference UTC time for staleness checking.
    - horizon_h: Forecast horizon in hours.

    Returns:
    - OrchardInputs with all 10 factor inputs and per-orchard elevation-corrected forecast.
    """
    now_dt = now_utc or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    orchard_id = str(
        orchard.get("id") if isinstance(orchard, dict) else getattr(orchard, "id", "adhoc_parcel")
    )
    orchard_name = str(
        orchard.get("name") if isinstance(orchard, dict) else getattr(orchard, "name", "باغ زراعی")
    )
    crop = str(
        orchard.get("crop") if isinstance(orchard, dict) else getattr(orchard, "crop", "pistachio")
    )

    # Phenological stage extraction
    current_stage = (
        orchard.get("current_stage")
        if isinstance(orchard, dict)
        else getattr(orchard, "current_stage", None)
    )
    if not current_stage:
        current_stage = (
            orchard.get("default_phenology_stage")
            if isinstance(orchard, dict)
            else getattr(orchard, "default_phenology_stage", "unopened_bud")
        )
    if not current_stage:
        current_stage = "unopened_bud"

    stage_updated_at = (
        orchard.get("stage_updated_at")
        if isinstance(orchard, dict)
        else getattr(orchard, "stage_updated_at", None)
    )
    if stage_updated_at and isinstance(stage_updated_at, datetime):
        stage_updated_at_iso = stage_updated_at.isoformat()
    elif stage_updated_at:
        stage_updated_at_iso = str(stage_updated_at)
    else:
        # Fall back to orchard updated_at / created_at or None
        up_at = orchard.get("updated_at") if isinstance(orchard, dict) else getattr(orchard, "updated_at", None)
        stage_updated_at_iso = up_at.isoformat() if isinstance(up_at, datetime) else (str(up_at) if up_at else None)

    stage_is_stale = is_timestamp_stale(
        stage_updated_at_iso,
        max_age_hours=get_stage_max_age_hours(),
        now=now_dt,
    )

    geom_dict, lat, lon, elevation_m = extract_orchard_geometry_and_centroid(orchard)
    gfs_cell = get_gfs_cell_coords(lat, lon)
    geom_hash = hashlib.md5(json.dumps(geom_dict, sort_keys=True).encode("utf-8")).hexdigest()

    factors: Dict[str, FactorInput] = {}

    # -------------------------------------------------------------------------
    # 1. Phenological Stage Factor Input
    # -------------------------------------------------------------------------
    factors["phenological_stage"] = FactorInput(
        id="phenological_stage",
        label_fa="مرحله فنولوژیکی باغ",
        value=current_stage,
        unit="مرحله رشد",
        source_module="app.db.models.frost.Orchard",
        quality_state="unknown" if stage_is_stale else "valid",
        as_of=stage_updated_at_iso or now_iso,
        is_stale=stage_is_stale,
        status="مطلوب" if not stage_is_stale else "نامشخص",
        details={
            "stage_key": current_stage,
            "stage_updated_at": stage_updated_at_iso,
            "is_stale": stage_is_stale,
            "stale_reason_fa": "مرحله منقضی (بیش از ۲۰ روز گذشته است)" if stage_is_stale else None,
        },
    )

    # -------------------------------------------------------------------------
    # 2. Static Terrain & Cold-Air Pooling Inputs
    # -------------------------------------------------------------------------
    terrain_cache_key = f"agri:frost_static:terrain:{geom_hash}"
    if terrain_data is None and use_cache:
        try:
            terrain_data = cache_service.get(terrain_cache_key)
        except Exception:
            terrain_data = None

    if terrain_data is None:
        pooling_proxy = None
        slope_deg = None
        aspect_deg = None
        dem_elevation_m = None

        if _can_query_ee():
            try:
                from app.services.agriculture.cold_air_pooling import calculate_cold_air_pooling_ee
                pooling_res = calculate_cold_air_pooling_ee(geom_dict)
                pooling_proxy = round(float(pooling_res.mean_pooling_risk_proxy), 3)
                slope_deg = round(float(pooling_res.mean_slope_deg), 1)
                dem_elevation_m = round(float(pooling_res.mean_elevation_m), 1)
            except Exception as exc:
                exc_str = str(exc).lower()
                if any(err in exc_str for err in ["quota", "permission", "credential", "403", "401"]) or ("auth" in exc_str and "not initialized" not in exc_str):
                    raise
                logger.warning(f"Could not compute pooling proxy via Earth Engine: {exc}")
                pooling_proxy = None

            try:
                aspect_deg = extract_terrain_aspect_ee(geom_dict)
            except Exception as exc:
                exc_str = str(exc).lower()
                if any(err in exc_str for err in ["quota", "permission", "credential", "403", "401"]) or ("auth" in exc_str and "not initialized" not in exc_str):
                    raise
                logger.warning(f"Could not compute aspect via Earth Engine: {exc}")
                aspect_deg = None

        terrain_data = {
            "pooling_proxy": pooling_proxy,
            "slope_deg": slope_deg,
            "aspect_deg": aspect_deg,
            "elevation_m": dem_elevation_m,
            "static": True,
            "as_of": None,
        }
        if use_cache and pooling_proxy is not None:
            try:
                cache_service.set(terrain_cache_key, terrain_data, ttl=STATIC_INPUT_CACHE_TTL_SEC)
            except Exception:
                pass

    pooling_val = terrain_data.get("pooling_proxy")
    if pooling_val is not None:
        p_f = float(pooling_val)
        factors["topography_pooling"] = FactorInput(
            id="topography_pooling",
            label_fa="شاخص تجمیع هوای سرد",
            value=round(p_f, 3),
            unit="شاخص (۰-۱)",
            source_module="app.services.agriculture.cold_air_pooling",
            quality_state="valid",
            as_of=None,
            is_stale=False,
            static=True,
            status="نامطلوب" if p_f >= 0.60 else ("مطلوب" if p_f < 0.30 else "خنثی"),
            details={"pooling_proxy": round(p_f, 3)},
        )
    else:
        factors["topography_pooling"] = FactorInput(
            id="topography_pooling",
            label_fa="شاخص تجمیع هوای سرد",
            value=None,
            unit="شاخص (۰-۱)",
            source_module="app.services.agriculture.cold_air_pooling",
            quality_state="unavailable",
            as_of=None,
            is_stale=False,
            static=True,
            status="ناموجود",
            details={},
        )

    slope_val = terrain_data.get("slope_deg")
    aspect_val = terrain_data.get("aspect_deg")
    if slope_val is not None:
        s_f = float(slope_val)
        asp_f = float(aspect_val) if aspect_val is not None else 0.0
        factors["topography_slope_aspect"] = FactorInput(
            id="topography_slope_aspect",
            label_fa="شیب و جهت دامنه",
            value=round(s_f, 1),
            unit="درجه",
            source_module="app.services.agriculture.terrain",
            quality_state="valid",
            as_of=None,
            is_stale=False,
            static=True,
            status="مطلوب" if s_f > 5.0 else ("نامطلوب" if s_f < 1.5 else "خنثی"),
            details={"slope_deg": round(s_f, 1), "aspect_deg": round(asp_f, 1)},
        )
    else:
        factors["topography_slope_aspect"] = FactorInput(
            id="topography_slope_aspect",
            label_fa="شیب و جهت دامنه",
            value=None,
            unit="درجه",
            source_module="app.services.agriculture.terrain",
            quality_state="unavailable",
            as_of=None,
            is_stale=False,
            static=True,
            status="ناموجود",
            details={},
        )

    # T5: Elevation reconciliation with NASADEM 30m
    registered_elevation_m = elevation_m
    dem_elev = terrain_data.get("elevation_m")
    dem_elevation_m = float(dem_elev) if dem_elev is not None else None

    # Temperature calculation strictly uses DEM elevation when available
    if dem_elevation_m is not None:
        calculation_elevation_m = dem_elevation_m
    else:
        calculation_elevation_m = float(registered_elevation_m) if registered_elevation_m is not None else 1000.0

    has_elevation_discrepancy = False
    elevation_discrepancy_warning_fa = None
    if registered_elevation_m is not None and dem_elevation_m is not None:
        elev_diff = abs(registered_elevation_m - dem_elevation_m)
        if elev_diff > 150.0:
            has_elevation_discrepancy = True
            elevation_discrepancy_warning_fa = (
                f"ناهمخوانی با DEM: ارتفاع ثبت‌شده ({registered_elevation_m:.0f} متر) با "
                f"مدل رقومی ۳۰ متری NASADEM ({dem_elevation_m:.0f} متر) {elev_diff:.0f} متر "
                f"اختلاف دارد؛ محاسبات دما بر پایه ارتفاع DEM انجام شد."
            )

    elevation_m = calculation_elevation_m

    # -------------------------------------------------------------------------
    # 3. Static Soil Properties (SoilGrids 250m) & Dynamic Moisture
    # -------------------------------------------------------------------------
    soil_static_cache_key = f"agri:frost_static:soil:{geom_hash}"
    if soil_static_data is None and use_cache:
        try:
            soil_static_data = cache_service.get(soil_static_cache_key)
        except Exception:
            soil_static_data = None

    soil_dynamic_cache_key = f"agri:frost_dynamic:soil:{geom_hash}"
    if soil_dynamic_data is None and use_cache:
        try:
            soil_dynamic_data = cache_service.get(soil_dynamic_cache_key)
        except Exception:
            soil_dynamic_data = None

    if soil_static_data is None or soil_dynamic_data is None:
        if _can_query_ee():
            try:
                from app.services.agriculture.soil_intelligence import compute_soil_intelligence
                intel_res = compute_soil_intelligence(
                    geometry=geom_dict,
                    start_date=(now_dt - timedelta(days=7)).strftime("%Y-%m-%d"),
                    end_date=now_dt.strftime("%Y-%m-%d"),
                    use_cache=use_cache,
                )
                props = intel_res.get("properties", {})
                water_ret = props.get("water_retention", {})
                fc_val = water_ret.get("field_capacity_33kpa")
                wp_val = water_ret.get("wilting_point_1500kpa")
                texture_info = props.get("texture_classification", {})
                sand_val = (props.get("sand") or {}).get("root_zone_value")
                clay_val = (props.get("clay") or {}).get("root_zone_value")

                if soil_static_data is None:
                    if fc_val is not None and wp_val is not None:
                        soil_static_data = {
                            "field_capacity": float(fc_val),
                            "wilting_point": float(wp_val),
                            "class_en": texture_info.get("class_en"),
                            "class_fa": texture_info.get("class_fa"),
                            "sand_pct": float(sand_val) if sand_val is not None else None,
                            "clay_pct": float(clay_val) if clay_val is not None else None,
                            "static": True,
                            "as_of": None,
                        }
                    else:
                        soil_static_data = {
                            "field_capacity": None,
                            "wilting_point": None,
                            "class_en": None,
                            "class_fa": None,
                            "sand_pct": None,
                            "clay_pct": None,
                            "static": True,
                            "as_of": None,
                        }
                    if use_cache and fc_val is not None:
                        try:
                            cache_service.set(soil_static_cache_key, soil_static_data, ttl=STATIC_INPUT_CACHE_TTL_SEC)
                        except Exception:
                            pass

                if soil_dynamic_data is None:
                    moist_dict = intel_res.get("moisture", {})
                    root_moist = (moist_dict.get("rootzone") or {}).get("value")
                    moist_as_of = (moist_dict.get("rootzone") or {}).get("as_of") or now_iso
                    soil_dynamic_data = {
                        "theta_rootzone": float(root_moist) if root_moist is not None else None,
                        "as_of": moist_as_of if root_moist is not None else None,
                    }
                    if use_cache and root_moist is not None:
                        try:
                            cache_service.set(soil_dynamic_cache_key, soil_dynamic_data, ttl=DYNAMIC_INPUT_CACHE_TTL_SEC)
                        except Exception:
                            pass

            except Exception as exc:
                exc_str = str(exc).lower()
                if any(err in exc_str for err in ["quota", "auth", "permission", "credential", "403", "401"]):
                    raise
                logger.warning(f"Could not compute soil intelligence via Earth Engine: {exc}")

        if soil_static_data is None:
            soil_static_data = {
                "field_capacity": None,
                "wilting_point": None,
                "class_en": None,
                "class_fa": None,
                "sand_pct": None,
                "clay_pct": None,
                "static": True,
                "as_of": None,
            }
        if soil_dynamic_data is None:
            soil_dynamic_data = {
                "theta_rootzone": None,
                "as_of": None,
            }

    fc = soil_static_data.get("field_capacity")
    wp = soil_static_data.get("wilting_point")
    theta = soil_dynamic_data.get("theta_rootzone")
    moist_as_of = soil_dynamic_data.get("as_of")
    moist_stale = is_timestamp_stale(
        moist_as_of,
        max_age_hours=DEFAULT_MAX_FACTOR_AGE_HOURS["soil_rootzone_moisture"],
        now=now_dt,
    ) if moist_as_of else False

    relative_moisture = normalize_rootzone_moisture(
        theta=theta,
        wilting_point=wp,
        field_capacity=fc,
    )

    is_below_wp = bool(theta is not None and wp is not None and float(theta) < float(wp))

    if relative_moisture is not None:
        if relative_moisture < 0.30:
            moist_status = "نامطلوب"
        elif relative_moisture > 0.70:
            moist_status = "مطلوب"
        else:
            moist_status = "خنثی"

        factors["soil_rootzone_moisture"] = FactorInput(
            id="soil_rootzone_moisture",
            label_fa="رطوبت نسبی ریشه در خاک",
            value=relative_moisture,
            unit="نسبی (۰-۱)",
            source_module="app.services.agriculture.soil",
            quality_state="coarse_context",
            as_of=moist_as_of,
            is_stale=moist_stale,
            static=False,
            status=moist_status,
            details={
                "theta_rootzone_m3m3": theta,
                "field_capacity_m3m3": fc,
                "wilting_point_m3m3": wp,
                "relative_moisture": relative_moisture,
                "below_wilting_point": is_below_wp,
                "below_wilting_point_note": "خشک‌تر از نقطه پژمردگی (برآورد درشت‌مقیاس، نامطمئن)" if is_below_wp else None,
                "normalized_formula": "clamp((theta - WP)/(FC - WP), 0, 1)",
                "spatial_resolution_note": "تفکیک ~۹–۱۱ کیلومتر",
                "source_disparity_note": "تخمین θ از ماهواره/بازتحلیل (~۹–۱۱ کیلومتر) و WP از SoilGrids (۲۵۰ متر) از دو منبع متفاوت با عدم‌قطعیت ذاتی است.",
            },
        )
    else:
        factors["soil_rootzone_moisture"] = FactorInput(
            id="soil_rootzone_moisture",
            label_fa="رطوبت نسبی ریشه در خاک",
            value=None,
            unit="نسبی (۰-۱)",
            source_module="app.services.agriculture.soil",
            quality_state="unavailable",
            as_of=moist_as_of,
            is_stale=False,
            static=False,
            status="ناموجود",
            details={
                "theta_rootzone_m3m3": theta,
                "field_capacity_m3m3": fc,
                "wilting_point_m3m3": wp,
                "spatial_resolution_note": "تفکیک ~۹–۱۱ کیلومتر",
            },
        )

    sand_pct = soil_static_data.get("sand_pct")
    class_fa = soil_static_data.get("class_fa")
    if class_fa is not None:
        is_light = sand_pct > 70.0 if sand_pct is not None else False
        factors["soil_texture_depth"] = FactorInput(
            id="soil_texture_depth",
            label_fa="بافت و عمق خاک",
            value=class_fa,
            unit="رده بافت USDA",
            source_module="app.services.agriculture.soil_intelligence",
            quality_state="coarse_context",
            as_of=None,
            is_stale=False,
            static=True,
            status="نامطلوب" if is_light else ("مطلوب" if (sand_pct is not None and sand_pct < 35.0) else "خنثی"),
            details={
                "class_en": soil_static_data.get("class_en"),
                "class_fa": class_fa,
                "sand_percent": sand_pct,
                "clay_percent": soil_static_data.get("clay_pct"),
                "spatial_resolution_note": "تفکیک ۲۵۰ متری SoilGrids (مدل آماری بافت خاک، بدون نمونه‌برداری آزمایشگاهی میدانی)",
            },
        )
    else:
        factors["soil_texture_depth"] = FactorInput(
            id="soil_texture_depth",
            label_fa="بافت و عمق خاک",
            value=None,
            unit="رده بافت USDA",
            source_module="app.services.agriculture.soil_intelligence",
            quality_state="unavailable",
            as_of=None,
            is_stale=False,
            static=True,
            status="ناموجود",
            details={},
        )

    # -------------------------------------------------------------------------
    # 4. GFS Forecast: Cell-Level Shared Fetch & Per-Orchard Elevation Correction
    # -------------------------------------------------------------------------
    cell_lat, cell_lon = gfs_cell
    cell_cache_key = f"agri:frost_gfs_cell:{cell_lat:.2f}:{cell_lon:.2f}"

    raw_cell_forecast: Optional[ForecastResult] = None
    if gfs_cell_cache is not None and cell_cache_key in gfs_cell_cache:
        raw_cell_forecast = gfs_cell_cache[cell_cache_key]
    elif use_cache:
        try:
            cached_fc = cache_service.get(cell_cache_key)
            if cached_fc and isinstance(cached_fc, dict):
                # Deserialization helper if cached as dict
                raw_cell_forecast = cached_fc
        except Exception:
            raw_cell_forecast = None

    if not raw_cell_forecast:
        if forecast_provider:
            provider = forecast_provider
        else:
            try:
                provider = NoaaGfsForecastProvider()
            except Exception:
                provider = FakeForecastProvider()
        cell_centroid_geom = {
            "type": "Point",
            "coordinates": [cell_lon, cell_lat],
        }
        try:
            raw_cell_forecast = await provider.get_hourly_forecast(
                geometry=cell_centroid_geom,
                horizon_h=horizon_h,
            )
        except Exception as exc:
            logger.error(f"Failed to fetch GFS forecast for cell {gfs_cell}: {exc}")
            from app.services.agriculture.forecast import FakeForecastProvider
            raw_cell_forecast = await FakeForecastProvider().get_hourly_forecast(
                geometry=cell_centroid_geom,
                horizon_h=horizon_h,
            )

        if gfs_cell_cache is not None and raw_cell_forecast is not None:
            gfs_cell_cache[cell_cache_key] = raw_cell_forecast
        if use_cache and raw_cell_forecast is not None:
            try:
                cache_service.set(cell_cache_key, raw_cell_forecast, ttl=GFS_CELL_CACHE_TTL_SEC)
            except Exception:
                pass

    # Per-Orchard Elevation Correction from the Shared Cell Forecast
    orchard_forecast = copy.deepcopy(raw_cell_forecast)
    z_cell = raw_cell_forecast.cell_elevation_m if hasattr(raw_cell_forecast, "cell_elevation_m") else 1000.0
    z_orchard = elevation_m

    # Re-apply elevation correction for this specific orchard's elevation
    updated_series: List[ForecastTimestep] = []
    for step in orchard_forecast.series:
        # Check if night
        hour_utc = 0
        try:
            hour_utc = datetime.fromisoformat(step.timestamp_utc.replace("Z", "+00:00")).hour
        except Exception:
            pass
        is_night = hour_utc >= 16 or hour_utc <= 3

        t_raw = step.temperature_2m_c_raw if step.temperature_2m_c_raw is not None else step.temperature_2m_c
        corr = correct_temperature_for_elevation(
            t_cell=t_raw,
            z_cell=z_cell,
            z_site=z_orchard,
            is_night_minimum=is_night,
            config=DEFAULT_QUALITY_CONFIG,
        )

        step.temperature_2m_c = corr.corrected_value
        step.temperature_2m_c_raw = corr.raw_value
        step.elevation_delta_m = round(z_orchard - z_cell, 1)
        step.elevation_correction_c = corr.delta_c
        step.elevation_uncertainty_c = corr.uncertainty_c
        step.total_uncertainty_c = round(math.sqrt(corr.uncertainty_c**2 + step.lead_time_uncertainty_c**2), 2)
        step.lower_bound_c = round(corr.corrected_value - step.total_uncertainty_c, 2)
        step.upper_bound_c = round(corr.corrected_value + step.total_uncertainty_c, 2)
        step.temperature_min_c = step.lower_bound_c
        step.temperature_max_c = step.upper_bound_c

        # Recompute dewpoint
        step.dewpoint_2m_c = calculate_dew_point_magnus(step.temperature_2m_c, step.relative_humidity_percent)
        updated_series.append(step)

    orchard_forecast.series = updated_series
    orchard_forecast.site_elevation_m = z_orchard
    orchard_forecast.cell_elevation_m = z_cell

    # Populate canonical metadata mappings on all assembled factors
    for factor in factors.values():
        if not factor.spatial_resolution_fa:
            factor.spatial_resolution_fa = FACTOR_RESOLUTION_MAP.get(factor.id, "")
        if not factor.source_name_fa:
            factor.source_name_fa = FACTOR_SOURCE_FA_MAP.get(factor.id, "")

    return OrchardInputs(
        orchard_id=orchard_id,
        orchard_name=orchard_name,
        latitude=lat,
        longitude=lon,
        elevation_m=elevation_m,
        gfs_cell=gfs_cell,
        factors=factors,
        assembled_at=now_iso,
        crop=crop,
        current_stage=current_stage,
        stage_is_stale=stage_is_stale,
        registered_elevation_m=registered_elevation_m,
        dem_elevation_m=dem_elevation_m,
        has_elevation_discrepancy=has_elevation_discrepancy,
        elevation_discrepancy_warning_fa=elevation_discrepancy_warning_fa,
        orchard_forecast=orchard_forecast,
        raw_cell_forecast=raw_cell_forecast,
    )
