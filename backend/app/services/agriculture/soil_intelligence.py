"""Soil Intelligence Engine (Phase P-AGRI-SOIL).

Computes real Google Earth Engine soil moisture and verified SoilGrids 2.0 properties.
Guarantees:
1. Real GEE data only: NO fabricated, mock, random, or interpolated fallback numbers.
2. Depth is ALWAYS explicit (e.g. 0-5 cm, 0-100 cm).
3. Coarse resolution warnings are clearly disclosed.
4. Static modelled baselines are never conflated with dynamic time-series.
5. Nutrients without GEE satellite coverage are honestly marked UNAVAILABLE.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.services.cache_service import cache_service
from app.services.earth_engine.authentication import initialize_earth_engine
from app.services.agriculture.registry.soil_datasets import (
    SOIL_DATASETS,
    SOILGRIDS_STANDARD_DEPTHS,
    ERA5_MOISTURE_DEPTHS,
    UNAVAILABLE_NUTRIENTS,
    SoilDatasetSpec,
    build_data_availability_matrix,
)
from app.schemas.agriculture import PointGeometry, PolygonGeometry

logger = get_logger(__name__)

# USDA Soil Texture Classifier
def classify_usda_texture(sand_pct: float, silt_pct: float, clay_pct: float) -> Tuple[str, str]:
    """Classify soil texture into standard USDA texture triangle classes."""
    if sand_pct + silt_pct + clay_pct <= 0:
        return "Unknown", "نامشخص"
    
    # Normalize if slightly off 100%
    total = sand_pct + silt_pct + clay_pct
    s = (sand_pct / total) * 100
    si = (silt_pct / total) * 100
    c = (clay_pct / total) * 100

    if c >= 40:
        if s <= 45 and si < 40:
            return "Clay", "رس (Clay)"
        elif si >= 40:
            return "Silty Clay", "رس سیلتی (Silty Clay)"
        else:
            return "Sandy Clay", "رس شنی (Sandy Clay)"
    elif c >= 27:
        if s <= 20:
            return "Silty Clay Loam", "لوم رس سیلتی (Silty Clay Loam)"
        elif s <= 45:
            return "Clay Loam", "لوم رسی (Clay Loam)"
        else:
            return "Sandy Clay Loam", "لوم رس شنی (Sandy Clay Loam)"
    elif c >= 20:
        if s >= 52:
            return "Sandy Clay Loam", "لوم رس شنی (Sandy Clay Loam)"
        elif si >= 50:
            return "Silt Loam", "لوم سیلتی (Silt Loam)"
        else:
            return "Loam", "لوم (Loam)"
    elif c >= 7:
        if si >= 50:
            return "Silt Loam", "لوم سیلتی (Silt Loam)"
        elif s >= 52:
            return "Sandy Loam", "لوم شنی (Sandy Loam)"
        else:
            return "Loam", "لوم (Loam)"
    else:  # clay < 7%
        if si >= 80:
            return "Silt", "سیلت (Silt)"
        elif si >= 50:
            return "Silt Loam", "لوم سیلتی (Silt Loam)"
        elif s >= 85:
            return "Sand", "ماسه / شن (Sand)"
        elif s >= 70:
            return "Loamy Sand", "ماسه لومی (Loamy Sand)"
        else:
            return "Sandy Loam", "لوم شنی (Sandy Loam)"


def _to_ee_geom(geometry_dict: Dict[str, Any], ee_module: Any) -> Tuple[Any, float]:
    """Convert geometry mapping to ee.Geometry with appropriate scale."""
    geom_type = geometry_dict.get("type", "Point")
    coords = geometry_dict.get("coordinates", [53.688, 32.4279])
    if geom_type == "Point":
        pt = ee_module.Geometry.Point([coords[0], coords[1]])
        return pt.buffer(60), 10.0
    elif geom_type == "Polygon":
        return ee_module.Geometry.Polygon(coords), 10.0
    return ee_module.Geometry.Point([53.688, 32.4279]).buffer(60), 10.0


def compute_soil_intelligence(
    geometry: Dict[str, Any] | Any,
    start_date: str,
    end_date: str,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Compute comprehensive real soil intelligence from Earth Engine.

    Returns:
    - soil moisture (surface, root-zone, multi-layer)
    - soil properties (SOC, N, pH, Sand, Silt, Clay, CEC, Water Retention)
    - depth profiles
    - texture classification
    - unavailable nutrients
    - lab sample architecture
    """
    if hasattr(geometry, "model_dump"):
        geom_dict = geometry.model_dump()
    elif isinstance(geometry, dict):
        geom_dict = geometry
    else:
        geom_dict = dict(geometry)

    cache_raw = json.dumps({"g": geom_dict, "s": start_date, "e": end_date}, sort_keys=True)
    cache_key = f"agri:soil_intel:{hashlib.md5(cache_raw.encode('utf-8')).hexdigest()}"

    if use_cache:
        try:
            cached = cache_service.get(cache_key)
            if cached:
                logger.info(f"Soil intelligence cache hit for {cache_key}")
                return cached
        except Exception as exc:
            logger.warning(f"Soil cache read failed: {exc}")

    initialize_earth_engine()
    import ee

    ee_geom, _ = _to_ee_geom(geom_dict, ee)

    # ----------------------------------------------------------------------
    # 1. Soil Moisture (Dynamic observation)
    # ----------------------------------------------------------------------
    moisture_results = _extract_soil_moisture(ee_geom, start_date, end_date, ee)

    # ----------------------------------------------------------------------
    # 2. Soil Properties (Static ISRIC SoilGrids 2.0 baseline)
    # ----------------------------------------------------------------------
    properties_results = _extract_soil_properties(ee_geom, ee)

    # ----------------------------------------------------------------------
    # 3. Assemble Data Availability Matrix and Response Payload
    # ----------------------------------------------------------------------
    extracted_metric_values: Dict[str, Any] = {
        "soil_moisture_surface": (moisture_results.get("surface") or {}).get("value"),
        "soil_moisture_rootzone": (moisture_results.get("rootzone") or {}).get("value"),
        "soil_organic_carbon": (properties_results.get("soc") or {}).get("root_zone_value"),
        "soil_ph": (properties_results.get("phh2o") or {}).get("root_zone_value"),
        "soil_total_nitrogen": (properties_results.get("nitrogen") or {}).get("root_zone_value"),
        "soil_sand_content": (properties_results.get("sand") or {}).get("root_zone_value"),
        "soil_silt_content": (properties_results.get("silt") or {}).get("root_zone_value"),
        "soil_clay_content": (properties_results.get("clay") or {}).get("root_zone_value"),
        "soil_cec": (properties_results.get("cec") or {}).get("root_zone_value"),
        "soil_field_capacity": (properties_results.get("water_retention") or {}).get("field_capacity_33kpa"),
        "soil_wilting_point": (properties_results.get("water_retention") or {}).get("wilting_point_1500kpa"),
    }
    availability_matrix = build_data_availability_matrix(
        extracted_metric_values,
        start_date=start_date,
        end_date=end_date,
    )

    response = {
        "start_date": start_date,
        "end_date": end_date,
        "moisture": moisture_results,
        "properties": properties_results,
        "unavailable_nutrients": list(UNAVAILABLE_NUTRIENTS.values()),
        "data_availability_matrix": availability_matrix,
        "laboratory_framework": {
            "is_lab_calibrated": False,
            "ml_nutrient_mapping_status": "DEACTIVATED",
            "message_fa": "مدل‌سازی یادگیری ماشین عناصر غذایی خاک نیازمند دیتاست کالیبراسیون آزمون میدانی خاک است و در حال حاضر غیرفعال است.",
            "message_en": "ML nutrient mapping requires calibrated field laboratory soil datasets and is currently deactivated.",
            "supported_sample_fields": [
                "sample_id",
                "location",
                "sample_date",
                "depth_from_cm",
                "depth_to_cm",
                "property",
                "value",
                "unit",
                "lab_name",
                "method",
                "quality_flag",
            ],
        },
        "limitations": [
            "رطوبت خاک بر پایه مشاهدات ماهواره‌ای و بازتحلیل با وضوح ۹ تا ۱۱ کیلومتر است و تغییرات در مقیاس چند متری درون باغ را نشان نمی‌دهد.",
            "ویژگی‌های فیزیکی و شیمیایی خاک بر اساس خط مبنای مدل‌شده SoilGrids 2.0 با وضوح ۲۵۰ متر است و جایگزین آزمایش مستقیم آزمایشگاهی خاک برای کودهی دقیق نیست.",
            "عناصر غذایی معدنی (فسفر، پتاسیم، روی، آهن و نیترات) و شوری (EC) به علت عدم امکان سنجش ماهواره‌ای، صراحتاً نیازمند راستی‌آزمایی آزمایشگاهی (REQUIRES_LAB_VALIDATION) اعلام شده‌اند.",
        ],
    }

    if use_cache:
        try:
            cache_service.set(cache_key, response)
        except Exception as exc:
            logger.warning(f"Soil cache write failed: {exc}")

    return response


def _extract_soil_moisture(
    ee_geom: Any, start_date: str, end_date: str, ee: Any
) -> Dict[str, Any]:
    """Extract real soil moisture observations across SMAP and ERA5-Land."""
    results: Dict[str, Any] = {
        "surface": None,
        "rootzone": None,
        "multilayer_era5": [],
        "coarse_warning": True,
        "spatial_resolution_m": 9000,
        "limitations": [
            "Coarse spatial resolution (9 km - 11 km); represents regional contextual moisture.",
            "Satellite microwave radiometer is sensitive to surface roughness and dense vegetation.",
        ],
    }

    # For coarse grids (9–11 km), sampling at the centroid ensures proper pixel retrieval
    # even when the field geometry is smaller than the grid cell.
    centroid_pt = ee_geom.centroid(1)

    # 1. ERA5-Land Multi-layer Daily Aggregate
    try:
        era5_col = (
            ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
            .filterDate(start_date, end_date)
            .filterBounds(centroid_pt)
        )
        era5_count = int(era5_col.size().getInfo())
        if era5_count > 0:
            era5_mean = era5_col.mean()
            bands = [
                "volumetric_soil_water_layer_1",
                "volumetric_soil_water_layer_2",
                "volumetric_soil_water_layer_3",
                "volumetric_soil_water_layer_4",
            ]
            raw = era5_mean.select(bands).reduceRegion(ee.Reducer.first(), centroid_pt, 11132).getInfo() or {}
            
            layers_info = [
                ("volumetric_soil_water_layer_1", "0–7 cm (Surface)", "۰ تا ۷ سانتی‌متر (سطحی)", 0.0, 7.0),
                ("volumetric_soil_water_layer_2", "7–28 cm (Upper root zone)", "۷ تا ۲۸ سانتی‌متر (ریشه فوقانی)", 7.0, 28.0),
                ("volumetric_soil_water_layer_3", "28–100 cm (Deep root zone)", "۲۸ تا ۱۰۰ سانتی‌متر (ریشه تحتانی)", 28.0, 100.0),
                ("volumetric_soil_water_layer_4", "100–289 cm (Subsoil)", "۱۰۰ تا ۲۸۹ سانتی‌متر (زیر خاک)", 100.0, 289.0),
            ]
            
            multi_layers = []
            for b_name, d_en, d_fa, top_cm, bot_cm in layers_info:
                val = raw.get(b_name)
                val_clean = round(float(val), 4) if val is not None and not math.isnan(val) else None
                multi_layers.append({
                    "band": b_name,
                    "depth_en": d_en,
                    "depth_fa": d_fa,
                    "depth_top_cm": top_cm,
                    "depth_bottom_cm": bot_cm,
                    "value": val_clean,
                    "unit": "m3/m3",
                    "status": "available" if val_clean is not None else "unavailable",
                    "source": "ERA5-Land",
                    "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
                    "scale_m": 11132,
                    "modelled": True,
                })
            results["multilayer_era5"] = multi_layers

            # Weighted Root-zone average (0-100 cm: layer 1 (7cm) + layer 2 (21cm) + layer 3 (72cm))
            l1 = raw.get("volumetric_soil_water_layer_1")
            l2 = raw.get("volumetric_soil_water_layer_2")
            l3 = raw.get("volumetric_soil_water_layer_3")
            if l1 is not None and l2 is not None and l3 is not None:
                rz_era5 = round((float(l1) * 7.0 + float(l2) * 21.0 + float(l3) * 72.0) / 100.0, 4)
                results["rootzone"] = {
                    "value": rz_era5,
                    "unit": "m3/m3",
                    "depth": "0–100 cm",
                    "depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                    "source": "ERA5-Land Multi-layer (Weighted 0–100 cm)",
                    "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
                    "scale_m": 11132,
                    "status": "available",
                    "data_status": "available",
                    "measurement_basis": "MODELLED",
                    "scientific_status": "REANALYSIS_MODEL",
                    "scientific_status_fa": "خروجی مدل بازتحلیل / شبیه‌سازی زمین (ERA5-Land)",
                    "validation_status": "NOT_LAB_VERIFIED",
                    "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
                }
    except Exception as exc:
        logger.error(f"ERA5 soil moisture extraction failed: {exc}")

    # 2. SMAP L3 Surface (9 km radiometer)
    try:
        smap_ds = "NASA/SMAP/SPL3SMP_E/006" if start_date >= "2023-12-04" else "NASA/SMAP/SPL3SMP_E/005"
        smap_col = ee.ImageCollection(smap_ds).filterDate(start_date, end_date).filterBounds(centroid_pt)
        if int(smap_col.size().getInfo()) > 0:
            smap_raw = smap_col.select("soil_moisture_am").median().reduceRegion(
                ee.Reducer.first(), centroid_pt, 9000
            ).getInfo() or {}
            val = smap_raw.get("soil_moisture_am")
            if val is not None and not math.isnan(val) and val > 0:
                results["surface"] = {
                    "value": round(float(val), 4),
                    "unit": "m3/m3",
                    "depth": "0–5 cm",
                    "depth_fa": "۰ تا ۵ سانتی‌متر (سطحی)",
                    "source": "SMAP L3 Enhanced Radiometer",
                    "dataset": smap_ds,
                    "scale_m": 9000,
                    "status": "available",
                    "data_status": "available",
                    "measurement_basis": "PRODUCT",
                    "scientific_status": "SATELLITE_OBSERVATION",
                    "scientific_status_fa": "مشاهده سنجش از دور ماهواره‌ای (SMAP L3)",
                    "validation_status": "NOT_LAB_VERIFIED",
                    "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
                }
    except Exception as exc:
        logger.warning(f"SMAP surface moisture extraction warning: {exc}")

    # Fallback surface to ERA5 layer 1 if SMAP was masked/absent
    if results["surface"] is None and results["multilayer_era5"]:
        l1 = results["multilayer_era5"][0]
        if l1.get("value") is not None:
            results["surface"] = {
                "value": l1["value"],
                "unit": "m3/m3",
                "depth": "0–7 cm",
                "depth_fa": "۰ تا ۷ سانتی‌متر (سطحی)",
                "source": "ERA5-Land Layer 1",
                "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
                "scale_m": 11132,
                "status": "available",
                "data_status": "available",
                "measurement_basis": "MODELLED",
                "scientific_status": "REANALYSIS_MODEL",
                "scientific_status_fa": "خروجی مدل بازتحلیل ERA5-Land",
                "validation_status": "NOT_LAB_VERIFIED",
                "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
            }

    # 3. SMAP L4 Root-zone
    try:
        smap_l4 = ee.ImageCollection("NASA/SMAP/SPL4SMGP/008").filterDate(start_date, end_date).filterBounds(centroid_pt)
        if int(smap_l4.size().getInfo()) > 0:
            smap_l4_raw = smap_l4.select("sm_rootzone").median().reduceRegion(
                ee.Reducer.first(), centroid_pt, 9000
            ).getInfo() or {}
            val = smap_l4_raw.get("sm_rootzone")
            if val is not None and not math.isnan(val) and val > 0:
                results["rootzone"] = {
                    "value": round(float(val), 4),
                    "unit": "m3/m3",
                    "depth": "0–100 cm",
                    "depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                    "source": "SMAP L4 Assimilated Land Model",
                    "dataset": "NASA/SMAP/SPL4SMGP/008",
                    "scale_m": 9000,
                    "status": "available",
                    "data_status": "available",
                    "measurement_basis": "MODELLED",
                    "scientific_status": "REANALYSIS_MODEL",
                    "scientific_status_fa": "خروجی مدل بازتحلیل / شبیه‌سازی زمین (SMAP L4)",
                    "validation_status": "NOT_LAB_VERIFIED",
                    "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
                }
    except Exception as exc:
        logger.warning(f"SMAP L4 extraction warning: {exc}")

    return results


def _extract_soil_properties(ee_geom: Any, ee: Any) -> Dict[str, Any]:
    """Extract verified ISRIC SoilGrids 2.0 properties across 6 standard depths."""
    property_configs = [
        ("soc", "projects/soilgrids-isric/soc_mean", "کربن آلی خاک (SOC)", "Soil Organic Carbon", "g/kg", 0.1),
        ("phh2o", "projects/soilgrids-isric/phh2o_mean", "اسیدیته خاک (pH)", "Soil pH in H2O", "pH", 0.1),
        ("clay", "projects/soilgrids-isric/clay_mean", "درصد رس", "Clay Content", "%", 0.1),
        ("sand", "projects/soilgrids-isric/sand_mean", "درصد شن (ماسه)", "Sand Content", "%", 0.1),
        ("silt", "projects/soilgrids-isric/silt_mean", "درصد سیلت (لای)", "Silt Content", "%", 0.1),
        ("cec", "projects/soilgrids-isric/cec_mean", "ظرفیت تبادل کاتیونی (CEC)", "Cation Exchange Capacity", "cmol(c)/kg", 0.1),
        ("nitrogen", "projects/soilgrids-isric/nitrogen_mean", "نیتروژن کل خاک", "Total Nitrogen", "g/kg", 0.01),
    ]

    depth_codes = [d.code for d in SOILGRIDS_STANDARD_DEPTHS]
    thicknesses = [d.thickness_cm for d in SOILGRIDS_STANDARD_DEPTHS]

    results: Dict[str, Any] = {}

    for prop_key, asset_id, name_fa, name_en, unit, scale in property_configs:
        try:
            img = ee.Image(asset_id)
            bands = [f"{prop_key}_{d}_mean" for d in depth_codes]
            raw = img.select(bands).reduceRegion(ee.Reducer.mean(), ee_geom, 250).getInfo() or {}

            depth_profiles = []
            weighted_sum = 0.0
            weight_total = 0.0

            for d_spec in SOILGRIDS_STANDARD_DEPTHS:
                b_name = f"{prop_key}_{d_spec.code}_mean"
                raw_val = raw.get(b_name)
                val_scaled = round(float(raw_val) * scale, 3) if raw_val is not None and not math.isnan(raw_val) else None
                depth_profiles.append({
                    "depth_code": d_spec.code,
                    "depth_en": d_spec.label_en,
                    "depth_fa": d_spec.label_fa,
                    "depth_top_cm": d_spec.depth_top_cm,
                    "depth_bottom_cm": d_spec.depth_bottom_cm,
                    "thickness_cm": d_spec.thickness_cm,
                    "value": val_scaled,
                    "unit": unit,
                    "status": "available" if val_scaled is not None else "unavailable",
                })
                # Exclude 100-200cm from root-zone weighted mean
                if d_spec.code != "100-200cm" and val_scaled is not None:
                    weighted_sum += val_scaled * d_spec.thickness_cm
                    weight_total += d_spec.thickness_cm

            rz_mean = round(weighted_sum / weight_total, 3) if weight_total > 0 else None

            results[prop_key] = {
                "property_key": prop_key,
                "name_fa": name_fa,
                "name_en": name_en,
                "unit": unit,
                "root_zone_value": rz_mean,
                "root_zone_depth": "0–100 cm",
                "root_zone_depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                "depth_profiles": depth_profiles,
                "source": "ISRIC SoilGrids 2.0 (Verified GEE)",
                "dataset_id": asset_id,
                "scale_m": 250,
                "reference_period": "Static modelled baseline (~2020)",
                "reference_period_fa": "خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
                "status": "available" if rz_mean is not None else "unavailable",
                "data_status": "available" if rz_mean is not None else "unavailable",
                "scientific_status": "GRIDDED_SOIL_BASELINE",
                "scientific_status_fa": "خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
                "validation_status": "NOT_LAB_VERIFIED",
                "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
                "is_modelled_baseline": True,
                "is_ground_truth": False,
                "requires_lab_validation": True,
                "note_fa": "نیتروژن کل مدل‌شده؛ با نیترات قابل جذب گیاه (NO3-) متفاوت است." if prop_key == "nitrogen" else None,
            }
        except Exception as exc:
            logger.error(f"Soil property {prop_key} extraction failed: {exc}")
            results[prop_key] = {
                "property_key": prop_key,
                "name_fa": name_fa,
                "name_en": name_en,
                "unit": unit,
                "root_zone_value": None,
                "status": "unavailable",
                "data_status": "unavailable",
                "reason": str(exc),
            }

    # Extract Water Retention (FC, WP, AWC)
    try:
        fc_img = ee.Image("ISRIC/SoilGrids250m/v2_0/wv0033")
        wp_img = ee.Image("ISRIC/SoilGrids250m/v2_0/wv1500")
        wv_bands = [f"val_{d.replace('-', '_')}_mean" for d in depth_codes]
        
        fc_raw = fc_img.select(wv_bands).reduceRegion(ee.Reducer.mean(), ee_geom, 250).getInfo() or {}
        wp_raw = wp_img.select(wv_bands).reduceRegion(ee.Reducer.mean(), ee_geom, 250).getInfo() or {}

        fc_sum = 0.0
        wp_sum = 0.0
        w_total = 0.0

        for d_spec in SOILGRIDS_STANDARD_DEPTHS:
            if d_spec.code != "100-200cm":
                b_name = f"val_{d_spec.code.replace('-', '_')}_mean"
                fc_v = fc_raw.get(b_name)
                wp_v = wp_raw.get(b_name)
                if fc_v is not None and wp_v is not None:
                    fc_sum += float(fc_v) * d_spec.thickness_cm
                    wp_sum += float(wp_v) * d_spec.thickness_cm
                    w_total += d_spec.thickness_cm

        if w_total > 0:
            fc_mean = round(fc_sum / w_total, 4)
            wp_mean = round(wp_sum / w_total, 4)
            awc_mean = round(fc_mean - wp_mean, 4)
            results["water_retention"] = {
                "field_capacity_33kpa": fc_mean,
                "wilting_point_1500kpa": wp_mean,
                "available_water_capacity": awc_mean,
                "unit": "m3/m3",
                "depth": "0–100 cm",
                "depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                "source": "ISRIC SoilGrids 2.0 wv0033 / wv1500",
                "dataset_id": "ISRIC/SoilGrids250m/v2_0",
                "scale_m": 250,
                "status": "available",
                "data_status": "available",
                "scientific_status": "GRIDDED_SOIL_BASELINE",
                "scientific_status_fa": "خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
                "validation_status": "NOT_LAB_VERIFIED",
                "validation_note_fa": "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
            }
    except Exception as exc:
        logger.error(f"Water retention extraction failed: {exc}")

    # Compute USDA Soil Texture Class from Root-Zone Sand, Silt, Clay
    sand_val = results.get("sand", {}).get("root_zone_value")
    silt_val = results.get("silt", {}).get("root_zone_value")
    clay_val = results.get("clay", {}).get("root_zone_value")

    if sand_val is not None and silt_val is not None and clay_val is not None:
        tex_en, tex_fa = classify_usda_texture(sand_val, silt_val, clay_val)
        results["texture_classification"] = {
            "class_en": tex_en,
            "class_fa": tex_fa,
            "sand_percent": sand_val,
            "silt_percent": silt_val,
            "clay_percent": clay_val,
            "method": "USDA Soil Texture Triangle (0–100 cm Weighted Profile)",
            "status": "available",
            "data_status": "available",
            "scientific_status": "DERIVED",
            "scientific_status_fa": "محاسباتی مشتق‌شده (مثلث بافت خاک USDA)",
            "validation_status": "NOT_LAB_VERIFIED",
            "validation_note_fa": "طبقه‌بندی مشتق‌شده از مقادیر شن، سیلت و رس؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        }
    else:
        results["texture_classification"] = {
            "class_en": "Unknown",
            "class_fa": "نامشخص",
            "status": "unavailable",
            "data_status": "unavailable",
        }

    return results
