"""Spatial Heatmap Layer Service (Phase P-AGRI-3).

Generates real Earth Engine raster tile layers for spatial visualization MVP.
Strictly adheres to real satellite data only:
- NDVI: Sentinel-2 SR Harmonized (10 m)
- LST Day: MODIS MOD11A2 (1000 m)
- Soil Moisture: SMAP SPL4SMGP root-zone moisture (9000 m)
- SAR VH: Sentinel-1 GRD backscatter (10 m)

If real spatial data is unavailable, returns honest unavailable status.
Never interpolates, fabricates, or replicates scalar values across tiles.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.schemas.agriculture import (
    PointGeometry,
    PolygonGeometry,
    SpatialLayerRequest,
    SpatialLayerResponse,
    SpatialMetricType,
)
from app.services.agriculture.tile_auth import generate_signed_layer_token
from app.services.cache_service import cache_service
from app.services.earth_engine import initialize_earth_engine

logger = get_logger(__name__)

# Metric configuration registry
SPATIAL_METRIC_CONFIGS: Dict[str, Dict[str, Any]] = {
    "ndvi": {
        "metric": "ndvi",
        "display_name": "NDVI (Normalized Difference Vegetation Index)",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "native_resolution_m": 10.0,
        "spatial_resolution": "10 m",
        "unit": "index",
        "min_val": 0.0,
        "max_val": 0.8,
        "palette": ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Optical composite filtered by cloud cover; median over requested window.",
    },
    "ndmi": {
        "metric": "ndmi",
        "display_name": "NDMI (Normalized Difference Moisture Index)",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "native_resolution_m": 20.0,
        "spatial_resolution": "20 m",
        "unit": "index",
        "min_val": -0.4,
        "max_val": 0.4,
        "palette": ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Optical canopy moisture index (B8, B11) filtered by cloud cover; median over requested window.",
    },
    "ndre": {
        "metric": "ndre",
        "display_name": "NDRE (Normalized Difference Red Edge)",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "native_resolution_m": 20.0,
        "spatial_resolution": "20 m",
        "unit": "index",
        "min_val": 0.0,
        "max_val": 0.5,
        "palette": ["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Sentinel-2 red-edge chlorophyll proxy (B8A, B5); median over requested window.",
    },
    "msi": {
        "metric": "msi",
        "display_name": "MSI (Moisture Stress Index)",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "native_resolution_m": 20.0,
        "spatial_resolution": "20 m",
        "unit": "index",
        "min_val": 0.4,
        "max_val": 2.0,
        "palette": ["#006837", "#78c679", "#ffffbf", "#fe9929", "#d7301f"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Canopy moisture stress ratio (SWIR B11 / NIR B8); elevated values reflect moisture stress.",
    },
    "lst_day": {
        "metric": "lst_day",
        "display_name": "Day Land Surface Temperature",
        "source_dataset": "MODIS/061/MOD11A2",
        "native_resolution_m": 1000.0,
        "spatial_resolution": "1000 m",
        "unit": "°C",
        "min_val": 20.0,
        "max_val": 55.0,
        "palette": [
            "#313695",
            "#4575b4",
            "#74add1",
            "#ffffbf",
            "#fee090",
            "#f46d43",
            "#a50026",
        ],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Thermal infrared 1 km spatial resolution, 8-day composite mean.",
    },
    "soil_moisture": {
        "metric": "soil_moisture",
        "display_name": "Root-Zone Soil Moisture",
        "source_dataset": "NASA/SMAP/SPL4SMGP/008",
        "native_resolution_m": 9000.0,
        "spatial_resolution": "9000 m",
        "unit": "m³/m³",
        "min_val": 0.0,
        "max_val": 0.35,
        "palette": ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
        "default_point_radius_m": 15000.0,
        "limitation_note": "SMAP L4 modeled root-zone moisture at 9 km grid resolution.",
    },
    "sar_vh": {
        "metric": "sar_vh",
        "display_name": "Sentinel-1 Radar Backscatter (VH)",
        "source_dataset": "COPERNICUS/S1_GRD",
        "native_resolution_m": 10.0,
        "spatial_resolution": "10 m",
        "unit": "dB",
        "min_val": -25.0,
        "max_val": -10.0,
        "palette": ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "C-band synthetic aperture radar backscatter in cross-polarization (VH, IW mode).",
    },
    "soil_soc": {
        "metric": "soil_soc",
        "display_name": "Soil Organic Carbon (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/soc_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "g/kg",
        "min_val": 0.0,
        "max_val": 20.0,
        "palette": ["#ffffe5", "#fff7bc", "#fee391", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#8c2d04"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "soil_ph": {
        "metric": "soil_ph",
        "display_name": "Soil pH in H2O (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/phh2o_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "pH",
        "min_val": 5.5,
        "max_val": 8.5,
        "palette": ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "soil_clay": {
        "metric": "soil_clay",
        "display_name": "Soil Clay Content (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/clay_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "%",
        "min_val": 5.0,
        "max_val": 50.0,
        "palette": ["#ffffd9", "#edf8b1", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#0c2c84"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "soil_sand": {
        "metric": "soil_sand",
        "display_name": "Soil Sand Content (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/sand_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "%",
        "min_val": 10.0,
        "max_val": 80.0,
        "palette": ["#ffffd4", "#fed98e", "#fe9929", "#d95f0e", "#993404"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "soil_cec": {
        "metric": "soil_cec",
        "display_name": "Cation Exchange Capacity (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/cec_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "cmol(c)/kg",
        "min_val": 5.0,
        "max_val": 40.0,
        "palette": ["#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#807dba", "#6a51a3", "#4a1486"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "soil_nitrogen": {
        "metric": "soil_nitrogen",
        "display_name": "Total Nitrogen (0–30 cm)",
        "source_dataset": "projects/soilgrids-isric/nitrogen_mean",
        "native_resolution_m": 250.0,
        "spatial_resolution": "250 m",
        "unit": "g/kg",
        "min_val": 0.0,
        "max_val": 3.0,
        "palette": ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#005a32"],
        "default_point_radius_m": 5000.0,
        "limitation_note": "ISRIC SoilGrids 2.0 static modelled raster (250 m) weighted across 0–30 cm topsoil.",
    },
    "true_color": {
        "metric": "true_color",
        "display_name": "Sentinel-2 True Color (RGB)",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "native_resolution_m": 10.0,
        "spatial_resolution": "10 m",
        "unit": "reflectance",
        "min_val": 0.0,
        "max_val": 3000.0,
        "palette": [],
        "default_point_radius_m": 5000.0,
        "limitation_note": "Sentinel-2 MSI 10m natural color composite (B4, B3, B2), cloud filtered.",
    },
}

# Agricultural interpretation concepts registry (Phase P-AGRI-4)
AGRICULTURAL_CONCEPTS: Dict[str, Dict[str, Any]] = {
    "vegetation_condition": {
        "concept": "vegetation_condition",
        "source_metric": "ndvi",
        "display_name": "Vegetation Condition",
        "display_name_fa": "وضعیت پوشش گیاهی",
        "interpretation": (
            "Spatial vegetation signal derived from Sentinel-2 NDVI. "
            "Indicates relative density and greenness of photosynthetic canopy across the field."
        ),
        "interpretation_fa": (
            "سیگنال مکانی پوشش گیاهی حاصل از شاخص NDVI ماهواره سنتینل-۲؛ "
            "نشان‌دهنده تراکم و سبزی نسبی کانوپی فتوسنتزی در سطح زمین."
        ),
        "scientific_caution": (
            "This layer reflects vegetation vigor signal only; it does not diagnose crop disease, "
            "pest presence, soil pathogen, or specific crop health."
        ),
        "scientific_caution_fa": (
            "این لایه صرفاً بازتاب‌دهنده سیگنال رشد رویشی گیاه است و به هیچ عنوان به معنی "
            "تشخیص بیماری، آفت گیاهی یا سلامت فیزیولوژیک قطعی محصول نیست."
        ),
        "qualitative_legend": [
            "Very Low (بسیار کم)",
            "Low (کم)",
            "Moderate (متوسط)",
            "High (زیاد)",
        ],
    },
    "thermal_stress": {
        "concept": "thermal_stress",
        "source_metric": "lst_day",
        "display_name": "Thermal Stress Proxy",
        "display_name_fa": "نمایه تنش حرارتی سطح زمین",
        "interpretation": (
            "Thermal load proxy based on MODIS daytime land surface temperature (LST). "
            "Identifies elevated surface heating across the landscape."
        ),
        "interpretation_fa": (
            "نمایه بار حرارتی مبتنی بر دمای سطح زمین (LST) سنجنده مودیس؛ "
            "نشان‌دهنده مناطق با بار حرارتی شدید در گستره مکانی منطقه."
        ),
        "scientific_caution": (
            "Thermal stress proxy based on land surface temperature; this layer does not "
            "directly measure or prove plant cellular stress. Native resolution is ~1000 m (1 km) "
            "and does not represent sub-field variation."
        ),
        "scientific_caution_fa": (
            "نمایه حرارتی مبتنی بر دمای سطح زمین؛ این لایه به‌تنهایی تنش گیاه را اثبات نمی‌کند. "
            "تفکیک مکانی سنسور ۱ کیلومتر است و تغییرات درون مزرعه را تفکیک نمی‌کند."
        ),
        "qualitative_legend": [
            "Low Thermal Load (بار حرارتی کم)",
            "Moderate (متوسط)",
            "High (زیاد)",
            "Very High (بسیار زیاد)",
        ],
    },
    "surface_dryness": {
        "concept": "surface_dryness",
        "source_metric": "ndmi",
        "display_name": "Surface Dryness Proxy (NDMI)",
        "display_name_fa": "نمایه خشکی سطح و کانوپی",
        "interpretation": (
            "Surface and canopy moisture proxy derived from Sentinel-2 NDMI (Gao 1996). "
            "Lower values reflect drier surface and canopy conditions, while higher values indicate moisture presence."
        ),
        "interpretation_fa": (
            "نمایه رطوبت سطح و کانوپی بر پایه شاخص NDMI سنتینل-۲؛ "
            "مقادیر پایین‌تر نشان‌دهنده شرایط خشک‌تر سطح و کانوپی و مقادیر بالاتر نشان‌دهنده حضور آب آزاد یا رطوبت در بافت است."
        ),
        "scientific_caution": (
            "This layer is an optical spectral proxy of canopy/surface moisture; it does NOT "
            "confirm plant water stress or cellular dehydration without root-zone and transpiration evidence."
        ),
        "scientific_caution_fa": (
            "این لایه یک نمایه طیفی نوری از رطوبت سطحی/کانوپی است و به هیچ عنوان به تنهایی "
            "تنش آبی محصول یا تشنگی بوته را بدون شواهد رطوبت ریشه و تعرق اثبات نمی‌کند."
        ),
        "qualitative_legend": [
            "Dry Surface (سطح بسیار خشک)",
            "Moderate Dryness (خشکی متوسط)",
            "Moist (مرطوب)",
            "High Moisture (رطوبت بالا)",
        ],
    },
    "soil_organic_carbon": {
        "concept": "soil_organic_carbon",
        "source_metric": "soil_soc",
        "display_name": "Soil Organic Carbon",
        "display_name_fa": "کربن آلی خاک (SOC)",
        "interpretation": (
            "Modelled baseline distribution of soil organic carbon content across 0–30 cm depth."
        ),
        "interpretation_fa": (
            "توزیع خط مبنای مدل‌شده کربن آلی خاک در لایه ۰ تا ۳۰ سانتی‌متری (ISRIC SoilGrids 2.0)."
        ),
        "scientific_caution": (
            "This raster is a 250m machine-learning global estimate; it does not replace laboratory wet-oxidation soil analysis."
        ),
        "scientific_caution_fa": (
            "این لایه برآورد یادگیری ماشین ۲۵۰ متری است و جایگزین آزمون خاک آزمایشگاهی برای توصیه کودی نیست."
        ),
        "qualitative_legend": [
            "Very Low (بسیار کم)",
            "Low (کم)",
            "Moderate (متوسط)",
            "High (مناسب)",
        ],
    },
    "soil_acidity_ph": {
        "concept": "soil_acidity_ph",
        "source_metric": "soil_ph",
        "display_name": "Soil pH in H2O",
        "display_name_fa": "اسیدیته خاک (pH)",
        "interpretation": (
            "Modelled baseline distribution of soil pH in water across 0–30 cm depth."
        ),
        "interpretation_fa": (
            "توزیع خط مبنای اسیدیته خاک (pH در آب) در عمق ۰ تا ۳۰ سانتی‌متر."
        ),
        "scientific_caution": (
            "Static baseline model at 250m resolution; cannot capture localized soil salinity or immediate amendment impacts."
        ),
        "scientific_caution_fa": (
            "خط مبنای مدل‌شده در وضوح ۲۵۰ متر؛ تغییرات موضعی شوری یا اصلاحات کودی اخیر را نشان نمی‌دهد."
        ),
        "qualitative_legend": [
            "Acidic (اسیدی)",
            "Neutral (خنثی)",
            "Moderately Alkaline (کمی قلیایی)",
            "Strongly Alkaline (بسیار قلیایی)",
        ],
    },
    "soil_texture_clay": {
        "concept": "soil_texture_clay",
        "source_metric": "soil_clay",
        "display_name": "Soil Clay Content",
        "display_name_fa": "محتوای رس خاک",
        "interpretation": (
            "Modelled baseline distribution of soil clay fraction percentage across 0–30 cm depth."
        ),
        "interpretation_fa": (
            "توزیع خط مبنای درصد رس خاک در لایه سطحی (۰ تا ۳۰ سانتی‌متر)."
        ),
        "scientific_caution": (
            "Modelled soil physical property at 250m; represents regional texture trend."
        ),
        "scientific_caution_fa": (
            "ویژگی فیزیکی مدل‌شده در وضوح ۲۵۰ متر که بافت عمومی خاک منطقه را نشان می‌دهد."
        ),
        "qualitative_legend": [
            "Low Clay (سبک / ماسه‌ای)",
            "Moderate Clay (متوسط / لومی)",
            "High Clay (سنگین / رسی)",
        ],
    },
}


def _build_cache_key(
    request: SpatialLayerRequest,
    resolved_metric: str,
    resolved_concept: Optional[str] = None,
) -> str:
    """Build deterministic cache key for spatial layer request."""
    geom_data = (
        request.geometry.model_dump()
        if hasattr(request.geometry, "model_dump")
        else dict(request.geometry)
    )
    geom_str = json.dumps(geom_data, sort_keys=True)
    geom_hash = hashlib.sha256(geom_str.encode("utf-8")).hexdigest()[:16]
    radius_str = str(request.support_radius_m or "default")
    concept_part = resolved_concept or "none"
    return (
        f"spatial_layer:{resolved_metric}:{concept_part}:{geom_hash}:"
        f"{request.start_date}:{request.end_date}:{request.cloud_max_percent}:{radius_str}"
    )


def _compute_bounds_and_region(
    request: SpatialLayerRequest,
    default_radius: float,
) -> Tuple[Any, List[float], str, Optional[float], float]:
    """Parse geometry into EE region, bounding box [W, S, E, N], type, radius, and area."""
    import ee

    geom = request.geometry
    if isinstance(geom, PointGeometry) or (
        isinstance(geom, dict) and geom.get("type") == "Point"
    ):
        coords = (
            geom.coordinates if hasattr(geom, "coordinates") else geom["coordinates"]
        )
        lon, lat = coords[0], coords[1]
        radius = request.support_radius_m or default_radius
        ee_point = ee.Geometry.Point([lon, lat])
        region = ee_point.buffer(radius)
        geom_type = "Point"
        area_sq_m = math.pi * (radius**2)

        # Approximate bounding box in degrees WGS84
        d_lat = radius / 111320.0
        cos_lat = math.cos(math.radians(lat))
        d_lon = radius / (111320.0 * max(cos_lat, 0.001))
        bounds = [lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat]
        return region, bounds, geom_type, radius, area_sq_m

    elif isinstance(geom, PolygonGeometry) or (
        isinstance(geom, dict) and geom.get("type") == "Polygon"
    ):
        coords = (
            geom.coordinates if hasattr(geom, "coordinates") else geom["coordinates"]
        )
        ee_poly = ee.Geometry.Polygon(coords)
        region = ee_poly
        geom_type = "Polygon"

        # Compute bounding box from outer ring
        outer_ring = coords[0]
        lons = [p[0] for p in outer_ring]
        lats = [p[1] for p in outer_ring]
        bounds = [min(lons), min(lats), max(lons), max(lats)]

        # Estimate area via bounding box projection
        mid_lat = (min(lats) + max(lats)) / 2.0
        width_m = (max(lons) - min(lons)) * 111320.0 * math.cos(math.radians(mid_lat))
        height_m = (max(lats) - min(lats)) * 111320.0
        approx_area_sq_m = abs(width_m * height_m)
        return region, bounds, geom_type, None, approx_area_sq_m

    else:
        # Fallback
        coords_raw = (
            geom.coordinates if hasattr(geom, "coordinates") else geom.get("coordinates", [0, 0])
        )
        if isinstance(coords_raw[0], (int, float)):
            lon, lat = coords_raw[0], coords_raw[1]
            radius = request.support_radius_m or default_radius
            region = ee.Geometry.Point([lon, lat]).buffer(radius)
            bounds = [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]
            return region, bounds, "Point", radius, math.pi * (radius**2)
        else:
            region = ee.Geometry.Polygon(coords_raw)
            return region, [0.0, 0.0, 0.0, 0.0], "Polygon", None, 0.0


def generate_spatial_layer(request: SpatialLayerRequest) -> SpatialLayerResponse:
    """Generate real Google Earth Engine raster map tiles for the requested metric or concept.

    Returns SpatialLayerResponse containing the tile URL template if available,
    or honest unavailable status if no satellite images match the criteria.
    """
    concept_str = (
        request.concept.value
        if hasattr(request.concept, "value")
        else str(request.concept)
        if request.concept
        else None
    )
    metric_str = (
        request.metric.value
        if hasattr(request.metric, "value")
        else str(request.metric)
        if request.metric
        else None
    )

    concept_info = None
    if concept_str in AGRICULTURAL_CONCEPTS:
        concept_info = AGRICULTURAL_CONCEPTS[concept_str]
        metric_str = concept_info["source_metric"]
    elif metric_str in AGRICULTURAL_CONCEPTS:
        concept_info = AGRICULTURAL_CONCEPTS[metric_str]
        concept_str = metric_str
        metric_str = concept_info["source_metric"]
    elif not metric_str:
        metric_str = "ndvi"

    if metric_str not in SPATIAL_METRIC_CONFIGS:
        return SpatialLayerResponse(
            metric=metric_str,
            display_name=metric_str,
            source_dataset="Unknown",
            tile_url_template=None,
            min_val=0.0,
            max_val=1.0,
            unit="",
            palette=[],
            native_resolution_m=0.0,
            spatial_resolution="unknown",
            geometry_type="Point",
            start_date=request.start_date,
            end_date=request.end_date,
            status="unavailable",
            unavailable_reason=f"Unsupported spatial metric: '{metric_str}'",
            limitations=[f"Metric '{metric_str}' is not supported in spatial MVP."],
        )

    cfg = SPATIAL_METRIC_CONFIGS[metric_str]

    # Check cache
    cache_key = _build_cache_key(request, metric_str, concept_str)
    try:
        cached = cache_service.get(cache_key)
        if cached:
            logger.info(f"Spatial layer cache hit for {cache_key}")
            return SpatialLayerResponse.model_validate(cached)
    except Exception as exc:
        logger.warning(f"Spatial layer cache get error: {exc}")

    # Initialize Earth Engine
    try:
        initialize_earth_engine()
        import ee
    except Exception as exc:
        logger.error(f"Failed to initialize Earth Engine: {exc}")
        return SpatialLayerResponse(
            metric=metric_str,
            display_name=cfg["display_name"],
            source_dataset=cfg["source_dataset"],
            tile_url_template=None,
            min_val=cfg["min_val"],
            max_val=cfg["max_val"],
            unit=cfg["unit"],
            palette=cfg["palette"],
            native_resolution_m=cfg["native_resolution_m"],
            spatial_resolution=cfg["spatial_resolution"],
            geometry_type="Point",
            start_date=request.start_date,
            end_date=request.end_date,
            status="unavailable",
            unavailable_reason=f"Earth Engine initialization failed: {exc}",
            limitations=["Earth Engine service unavailable."],
        )

    try:
        region, bounds, geom_type, radius_m, area_sq_m = _compute_bounds_and_region(
            request, cfg["default_point_radius_m"]
        )

        image = None
        count = 0

        if metric_str == "ndvi":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            count = col.size().getInfo()
            if count > 0:
                med = col.median()
                image = med.normalizedDifference(["B8", "B4"])

        elif metric_str == "ndmi":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            count = col.size().getInfo()
            if count > 0:
                med = col.median()
                image = med.normalizedDifference(["B8", "B11"])

        elif metric_str == "ndre":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            count = col.size().getInfo()
            if count > 0:
                med = col.median()
                image = med.normalizedDifference(["B8A", "B5"])

        elif metric_str == "msi":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            count = col.size().getInfo()
            if count > 0:
                med = col.median()
                image = med.select("B11").divide(med.select("B8"))

        elif metric_str == "lst_day":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
            )
            count = col.size().getInfo()
            if count > 0:
                raw_lst = col.select("LST_Day_1km").mean()
                # MODIS scale factor is 0.02, then - 273.15 Kelvin to Celsius
                image = raw_lst.multiply(0.02).subtract(273.15)

        elif metric_str == "soil_moisture":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
            )
            count = col.size().getInfo()
            if count > 0:
                image = col.select("sm_rootzone").mean()
            else:
                # Fallback to ERA5-Land daily aggregate layer 1
                era5_col = (
                    ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
                    .filterBounds(region)
                    .filterDate(request.start_date, request.end_date)
                )
                era5_cnt = era5_col.size().getInfo()
                if era5_cnt > 0:
                    image = era5_col.select("volumetric_soil_water_layer_1").mean()
                    count = era5_cnt

        elif metric_str == "sar_vh":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.eq("instrumentMode", "IW"))
            )
            count = col.size().getInfo()
            if count > 0:
                image = col.select("VH").mean()

        elif metric_str in ("soil_soc", "soil_ph", "soil_clay", "soil_sand", "soil_cec", "soil_nitrogen"):
            scale_factor = 0.01 if metric_str == "soil_nitrogen" else 0.1
            prop_key = metric_str.replace("soil_", "")
            if prop_key == "ph":
                prop_key = "phh2o"
            raw_img = ee.Image(cfg["source_dataset"])
            b1 = f"{prop_key}_0-5cm_mean"
            b2 = f"{prop_key}_5-15cm_mean"
            b3 = f"{prop_key}_15-30cm_mean"
            weighted_topsoil = (
                raw_img.select(b1).multiply(5.0)
                .add(raw_img.select(b2).multiply(10.0))
                .add(raw_img.select(b3).multiply(15.0))
            ).divide(30.0).multiply(scale_factor)
            image = weighted_topsoil
            count = 1

        elif metric_str == "true_color":
            col = (
                ee.ImageCollection(cfg["source_dataset"])
                .filterBounds(region)
                .filterDate(request.start_date, request.end_date)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            count = col.size().getInfo()
            if count > 0:
                image = col.median().select(["B4", "B3", "B2"])

        if count == 0 or image is None:
            logger.warning(
                f"No spatial imagery found for {metric_str} ({request.start_date} to {request.end_date})"
            )
            unavail_resp = SpatialLayerResponse(
                metric=metric_str,
                display_name=concept_info["display_name"] if concept_info else cfg["display_name"],
                source_dataset=cfg["source_dataset"],
                tile_url_template=None,
                min_val=cfg["min_val"],
                max_val=cfg["max_val"],
                unit=cfg["unit"],
                palette=cfg["palette"],
                native_resolution_m=cfg["native_resolution_m"],
                spatial_resolution=cfg["spatial_resolution"],
                geometry_type=geom_type,
                support_radius_m=radius_m,
                support_area_sq_m=area_sq_m,
                start_date=request.start_date,
                end_date=request.end_date,
                status="unavailable",
                unavailable_reason="insufficient_coverage",
                limitations=[
                    f"No satellite scenes acquired by {cfg['source_dataset']} for this geometry "
                    f"between {request.start_date} and {request.end_date}."
                ],
                bounds=bounds,
                concept=concept_info["concept"] if concept_info else None,
                concept_name=concept_info["display_name"] if concept_info else None,
                concept_name_fa=concept_info["display_name_fa"] if concept_info else None,
                interpretation=concept_info["interpretation"] if concept_info else None,
                interpretation_fa=concept_info["interpretation_fa"] if concept_info else None,
                qualitative_legend=list(concept_info["qualitative_legend"]) if concept_info else [],
                scientific_caution=concept_info["scientific_caution"] if concept_info else None,
                scientific_caution_fa=concept_info["scientific_caution_fa"] if concept_info else None,
            )
            return unavail_resp

        # Clip to region and obtain Earth Engine XYZ tile URL template
        clipped = image.clip(region)
        if metric_str == "true_color":
            vis_params = {
                "bands": ["B4", "B3", "B2"],
                "min": 0,
                "max": 3000,
            }
        else:
            vis_params = {
                "min": cfg["min_val"],
                "max": cfg["max_val"],
                "palette": cfg["palette"],
            }
        map_id = clipped.getMapId(vis_params)
        tile_url_template = map_id["tile_fetcher"].url_format

        # Backend proxy layer token (HMAC-signed, bound to metric, date range, and bbox)
        token_id = hashlib.sha256(tile_url_template.encode("utf-8")).hexdigest()[:16]
        cache_service.set(f"tile_template:{token_id}", tile_url_template, ttl=7200)
        layer_token = generate_signed_layer_token(
            metric=metric_str,
            start_date=request.start_date,
            end_date=request.end_date,
            bbox=bounds,
            token_id=token_id,
            ttl_seconds=7200,
        )
        proxied_tile_url_template = f"/api/v1/agriculture/tiles/{layer_token}/{{z}}/{{x}}/{{y}}.png"

        display_title = (
            f"{concept_info['display_name']} ({cfg['display_name']})"
            if concept_info
            else cfg["display_name"]
        )

        lims = [
            cfg["limitation_note"],
            f"Aggregated from {count} real Earth Engine satellite scenes.",
        ]
        if concept_info:
            lims.insert(0, concept_info["scientific_caution"])

        response = SpatialLayerResponse(
            metric=metric_str,
            display_name=display_title,
            source_dataset=cfg["source_dataset"],
            tile_url_template=tile_url_template,
            proxied_tile_url_template=proxied_tile_url_template,
            min_val=cfg["min_val"],
            max_val=cfg["max_val"],
            unit=cfg["unit"],
            palette=cfg["palette"],
            native_resolution_m=cfg["native_resolution_m"],
            spatial_resolution=cfg["spatial_resolution"],
            geometry_type=geom_type,
            support_radius_m=radius_m,
            support_area_sq_m=area_sq_m,
            start_date=request.start_date,
            end_date=request.end_date,
            status="available",
            unavailable_reason=None,
            limitations=lims,
            bounds=bounds,
            concept=concept_info["concept"] if concept_info else None,
            concept_name=concept_info["display_name"] if concept_info else None,
            concept_name_fa=concept_info["display_name_fa"] if concept_info else None,
            interpretation=concept_info["interpretation"] if concept_info else None,
            interpretation_fa=concept_info["interpretation_fa"] if concept_info else None,
            qualitative_legend=list(concept_info["qualitative_legend"]) if concept_info else [],
            scientific_caution=concept_info["scientific_caution"] if concept_info else None,
            scientific_caution_fa=concept_info["scientific_caution_fa"] if concept_info else None,
        )

        # Cache response
        try:
            cache_service.set(cache_key, response.model_dump())
        except Exception as exc:
            logger.warning(f"Spatial layer cache set error: {exc}")

        return response

    except Exception as exc:
        logger.error(f"Error generating spatial layer for {metric_str}: {exc}", exc_info=True)
        return SpatialLayerResponse(
            metric=metric_str,
            display_name=cfg["display_name"],
            source_dataset=cfg["source_dataset"],
            tile_url_template=None,
            min_val=cfg["min_val"],
            max_val=cfg["max_val"],
            unit=cfg["unit"],
            palette=cfg["palette"],
            native_resolution_m=cfg["native_resolution_m"],
            spatial_resolution=cfg["spatial_resolution"],
            geometry_type="Point",
            start_date=request.start_date,
            end_date=request.end_date,
            status="unavailable",
            unavailable_reason=str(exc),
            limitations=[f"Earth Engine processing error: {exc}"],
        )
