"""Unit tests for Soil Intelligence (Phase P-AGRI-SOIL).

Verifies:
1. USDA soil texture classification against standard soil triangle benchmarks.
2. ISRIC SoilGrids 2.0 and SMAP/ERA5 dataset registry metadata and scale factors.
3. Explicit UNAVAILABLE status for satellite unobservable nutrients (P, K, Zn, Fe, Nitrate).
4. Additive Pydantic schema serialization for SoilIntelligenceResponse.
5. 10-Year historical comparison domain configuration for soil moisture.
6. Spatial layer heatmap configurations for SoilGrids 2.0 properties.
"""
from __future__ import annotations

import pytest
from app.services.agriculture.registry.soil_datasets import (
    SOIL_DATASETS,
    SOILGRIDS_STANDARD_DEPTHS,
    ERA5_MOISTURE_DEPTHS,
    UNAVAILABLE_NUTRIENTS,
)
from app.services.agriculture.soil_intelligence import classify_usda_texture
from app.schemas.agriculture import (
    SoilIntelligenceRequest,
    SoilIntelligenceResponse,
    SoilMoistureResponseModel,
    SoilPropertyRecordModel,
    SoilTextureClassificationModel,
    UnavailableNutrientModel,
    SpatialMetricType,
    SpatialConceptType,
)
from app.services.agriculture.history import HIST_DOMAIN_METRICS, HIST_METRIC_META
from app.services.agriculture.spatial_layer import SPATIAL_METRIC_CONFIGS, AGRICULTURAL_CONCEPTS


def test_usda_texture_classification():
    """Verify USDA soil texture triangle classification across distinct archetypes."""
    # Sandy Loam (e.g. from our live orchard coordinates: Sand=61.5, Silt=22.1, Clay=16.4)
    cls_en, cls_fa = classify_usda_texture(61.5, 22.1, 16.4)
    assert cls_en == "Sandy Loam"
    assert "لوم شنی" in cls_fa

    # Pure Sand
    cls_en, cls_fa = classify_usda_texture(90.0, 5.0, 5.0)
    assert cls_en == "Sand"
    assert "ماسه" in cls_fa or "شن" in cls_fa

    # Heavy Clay
    cls_en, cls_fa = classify_usda_texture(20.0, 20.0, 60.0)
    assert cls_en == "Clay"
    assert "رس" in cls_fa

    # Silt Loam
    cls_en, cls_fa = classify_usda_texture(20.0, 65.0, 15.0)
    assert cls_en == "Silt Loam"
    assert "لوم سیلتی" in cls_fa

    # Balanced Loam
    cls_en, cls_fa = classify_usda_texture(40.0, 40.0, 20.0)
    assert cls_en == "Loam"
    assert "لوم" in cls_fa


def test_soilgrids_standard_depths_integrity():
    """Verify standard GlobalSoilMap 6 depth intervals are correctly specified."""
    assert len(SOILGRIDS_STANDARD_DEPTHS) == 6
    depth_codes = [d.code for d in SOILGRIDS_STANDARD_DEPTHS]
    assert depth_codes == ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]

    # Verify root-zone cumulative thickness (0 to 100 cm = 100 cm)
    rootzone_depths = [d for d in SOILGRIDS_STANDARD_DEPTHS if d.code != "100-200cm"]
    total_thickness = sum(d.thickness_cm for d in rootzone_depths)
    assert total_thickness == 100.0


def test_unavailable_nutrients_honesty_gate():
    """Verify non-observable macronutrients and micronutrients are strictly marked UNAVAILABLE."""
    expected_nutrients = ["phosphorus", "potassium", "iron", "zinc", "nitrate"]
    for nut in expected_nutrients:
        assert nut in UNAVAILABLE_NUTRIENTS
        spec = UNAVAILABLE_NUTRIENTS[nut]
        assert spec["status"] == "UNAVAILABLE"
        assert spec["reason"] == "NO_SATELLITE_SENSOR_EXISTS"
        assert "آزمایشگاهی" in spec["message_fa"] or "آزمون" in spec["message_fa"]


def test_soil_intelligence_schema_validation():
    """Verify SoilIntelligenceResponse serializes cleanly with all nested models."""
    sample_payload = {
        "start_date": "2026-06-01",
        "end_date": "2026-09-01",
        "moisture": {
            "surface": {
                "value": 0.145,
                "unit": "m3/m3",
                "depth": "0–5 cm",
                "depth_fa": "۰ تا ۵ سانتی‌متر (سطحی)",
                "source": "SMAP L3",
                "dataset": "NASA/SMAP/SPL3SMP_E/006",
                "scale_m": 9000.0,
                "status": "available",
                "measurement_basis": "PRODUCT",
            },
            "rootzone": {
                "value": 0.182,
                "unit": "m3/m3",
                "depth": "0–100 cm",
                "depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                "source": "ERA5-Land",
                "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
                "scale_m": 11132.0,
                "status": "available",
                "measurement_basis": "MODELLED",
            },
            "multilayer_era5": [
                {
                    "band": "volumetric_soil_water_layer_1",
                    "depth_en": "0–7 cm",
                    "depth_fa": "۰ تا ۷ سانتی‌متر",
                    "depth_top_cm": 0.0,
                    "depth_bottom_cm": 7.0,
                    "value": 0.145,
                    "unit": "m3/m3",
                    "status": "available",
                    "source": "ERA5-Land",
                    "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
                    "scale_m": 11132.0,
                    "modelled": True,
                }
            ],
            "coarse_warning": True,
            "spatial_resolution_m": 9000,
            "limitations": ["Coarse satellite resolution (9 km - 11 km)"],
        },
        "properties": {
            "soc": {
                "property_key": "soc",
                "name_fa": "کربن آلی خاک (SOC)",
                "name_en": "Soil Organic Carbon",
                "unit": "g/kg",
                "root_zone_value": 3.4,
                "root_zone_depth": "0–100 cm",
                "root_zone_depth_fa": "۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)",
                "depth_profiles": [
                    {
                        "depth_code": "0-5cm",
                        "depth_en": "0–5 cm",
                        "depth_fa": "۰ تا ۵ سانتی‌متر",
                        "depth_top_cm": 0.0,
                        "depth_bottom_cm": 5.0,
                        "thickness_cm": 5.0,
                        "value": 4.1,
                        "unit": "g/kg",
                        "status": "available",
                    }
                ],
                "source": "ISRIC SoilGrids 2.0 (Verified GEE)",
                "dataset_id": "projects/soilgrids-isric/soc_mean",
                "scale_m": 250.0,
                "status": "available",
                "is_modelled_baseline": True,
            },
            "texture_classification": {
                "class_en": "Sandy Loam",
                "class_fa": "لوم شنی (Sandy Loam)",
                "sand_percent": 61.5,
                "silt_percent": 22.1,
                "clay_percent": 16.4,
                "method": "USDA Soil Texture Triangle",
                "status": "available",
            },
        },
        "unavailable_nutrients": list(UNAVAILABLE_NUTRIENTS.values()),
        "laboratory_framework": {
            "is_lab_calibrated": False,
            "ml_nutrient_mapping_status": "DEACTIVATED",
            "message_fa": "مدل‌سازی غیرفعال است",
            "message_en": "ML nutrient mapping is deactivated",
            "supported_sample_fields": ["sample_id", "property", "value"],
        },
        "limitations": ["Real satellite and gridded baseline only"],
    }

    model = SoilIntelligenceResponse.model_validate(sample_payload)
    assert model.moisture.surface.value == 0.145
    assert model.moisture.rootzone.depth == "0–100 cm"
    assert model.properties["texture_classification"]["class_en"] == "Sandy Loam"
    assert len(model.unavailable_nutrients) == len(UNAVAILABLE_NUTRIENTS)


def test_10y_historical_soil_domain_configuration():
    """Verify that domain 'soil' is registered in historical comparison engine."""
    assert "soil" in HIST_DOMAIN_METRICS
    assert "soil_moisture" in HIST_DOMAIN_METRICS["soil"]
    assert "soil_moisture" in HIST_METRIC_META
    assert HIST_METRIC_META["soil_moisture"]["dataset"] == "ECMWF/ERA5_LAND/DAILY_AGGR"


def test_spatial_layer_soil_configurations():
    """Verify soil metrics and concepts in spatial heatmap layer service."""
    soil_metrics = ["soil_soc", "soil_ph", "soil_clay", "soil_sand", "soil_cec", "soil_nitrogen"]
    for m in soil_metrics:
        assert m in SPATIAL_METRIC_CONFIGS
        assert SPATIAL_METRIC_CONFIGS[m]["native_resolution_m"] == 250.0
        assert "projects/soilgrids-isric" in SPATIAL_METRIC_CONFIGS[m]["source_dataset"]

    assert "soil_organic_carbon" in AGRICULTURAL_CONCEPTS
    assert "soil_acidity_ph" in AGRICULTURAL_CONCEPTS
    assert "soil_texture_clay" in AGRICULTURAL_CONCEPTS


def test_unified_soil_metric_registry_integrity():
    """Verify SOIL_METRIC_REGISTRY contains all 17 standardized scientific soil metrics."""
    from app.services.agriculture.registry.soil_datasets import SOIL_METRIC_REGISTRY

    expected_keys = {
        "soil_moisture_surface",
        "soil_moisture_rootzone",
        "soil_organic_carbon",
        "soil_ph",
        "soil_total_nitrogen",
        "soil_sand_content",
        "soil_silt_content",
        "soil_clay_content",
        "soil_cec",
        "soil_field_capacity",
        "soil_wilting_point",
        "available_phosphorus",
        "exchangeable_potassium",
        "soil_nitrate",
        "soil_electrical_conductivity",
        "soil_zinc",
        "soil_iron",
    }
    assert expected_keys.issubset(set(SOIL_METRIC_REGISTRY.keys()))

    for key, spec in SOIL_METRIC_REGISTRY.items():
        assert spec.metric_key == key
        assert len(spec.label_fa) > 0
        assert len(spec.unit) > 0
        assert spec.is_ground_truth is False  # Never claim satellite/model is ground truth
        assert spec.requires_lab_validation is True


def test_total_nitrogen_vs_nitrate_scientific_distinction():
    """Verify Total Nitrogen is strictly separated from Nitrate (NO3-) in status and notes."""
    from app.services.agriculture.registry.soil_datasets import SOIL_METRIC_REGISTRY

    total_n_spec = SOIL_METRIC_REGISTRY["soil_total_nitrogen"]
    nitrate_spec = SOIL_METRIC_REGISTRY["soil_nitrate"]

    # Total N is a modelled static baseline from SoilGrids 2.0
    assert total_n_spec.default_status == "MODELLED_BASELINE"
    assert total_n_spec.source == "ISRIC SoilGrids 2.0"
    assert "nitrate" in total_n_spec.reason_en.lower()

    # Nitrate strictly requires lab validation and has no satellite sensor
    assert nitrate_spec.default_status == "REQUIRES_LAB_VALIDATION"
    assert nitrate_spec.validation_status == "LAB_REQUIRED"
    assert nitrate_spec.source is None


def test_data_availability_matrix_builder():
    """Verify build_data_availability_matrix creates complete, calibrated matrix without fake data."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix

    test_extracted = {
        "soil_moisture_surface": 0.12,
        "soil_moisture_rootzone": 0.18,
        "soil_organic_carbon": 0.35,
        "soil_ph": 7.8,
        "soil_total_nitrogen": 0.08,
        "soil_sand_content": 60.0,
        "soil_silt_content": 25.0,
        "soil_clay_content": 15.0,
        "soil_cec": 12.5,
        "soil_field_capacity": 0.22,
        "soil_wilting_point": 0.09,
    }

    matrix = build_data_availability_matrix(test_extracted)
    matrix_dict = {item["metric_key"]: item for item in matrix}

    # Available/Modelled metrics have real values
    assert matrix_dict["soil_moisture_surface"]["value"] == 0.12
    assert matrix_dict["soil_moisture_surface"]["status"] == "AVAILABLE"
    assert matrix_dict["soil_total_nitrogen"]["value"] == 0.08
    assert matrix_dict["soil_total_nitrogen"]["status"] == "MODELLED_BASELINE"

    # Chemical nutrients have strictly None values and require lab validation
    for unavail_key in ["available_phosphorus", "exchangeable_potassium", "soil_nitrate", "soil_electrical_conductivity"]:
        assert matrix_dict[unavail_key]["value"] is None
        assert matrix_dict[unavail_key]["status"] == "REQUIRES_LAB_VALIDATION"
        assert matrix_dict[unavail_key]["validation_status"] == "LAB_REQUIRED"
        assert matrix_dict[unavail_key]["is_ground_truth"] is False
        assert matrix_dict[unavail_key]["requires_lab_validation"] is True
        assert len(matrix_dict[unavail_key]["next_action"]) > 0


def test_soil_observation_schema_validation():
    """Verify SoilObservation schema validates physical laboratory records without derived claims."""
    from app.schemas.agriculture import SoilObservation

    valid_sample = SoilObservation(
        observation_id="LAB-YAZD-2026-001",
        latitude=32.4279,
        longitude=53.6880,
        sample_date="2026-05-20",
        depth_top_cm=0.0,
        depth_bottom_cm=30.0,
        pH=7.6,
        EC=2.4,
        total_n=0.09,
        available_p=14.2,
        exchangeable_k=185.0,
        nitrate=28.5,
        laboratory="Yazd Agricultural Soil & Water Reference Lab",
        method="Olsen P, Ammonium Acetate K, Conductometry ECe",
        quality="verified",
        notes="Representative core composite sample from pistachio orchard",
        source_type="laboratory",
        is_derived=False,
    )
    assert valid_sample.observation_id == "LAB-YAZD-2026-001"
    assert valid_sample.is_derived is False
    assert valid_sample.source_type == "laboratory"
    assert valid_sample.available_p == 14.2
    assert valid_sample.exchangeable_k == 185.0


def test_real_retrieved_value_remains_visible_when_lab_validation_pending():
    """Requirement 1: A real retrieved value remains visible when laboratory validation is pending."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix

    extracted = {"soil_moisture_surface": 0.145, "soil_organic_carbon": 0.42}
    matrix = build_data_availability_matrix(extracted, start_date="2026-06-01", end_date="2026-09-01")
    items_by_key = {item["metric_key"]: item for item in matrix}

    # Surface moisture: retrieved real value must be visible
    surf = items_by_key["soil_moisture_surface"]
    assert surf["value"] == 0.145
    assert surf["data_status"] == "AVAILABLE"
    assert surf["validation_status"] == "NOT_LAB_VERIFIED"
    assert "اعتبارسنجی میدانی هنوز انجام نشده است" in surf["validation_note_fa"]
    assert surf["scientific_status"] == "SATELLITE_OBSERVATION"

    # SOC: retrieved modelled baseline value must be visible
    soc = items_by_key["soil_organic_carbon"]
    assert soc["value"] == 0.42
    assert soc["data_status"] == "AVAILABLE"
    assert soc["validation_status"] == "NOT_LAB_VERIFIED"
    assert "اعتبارسنجی میدانی هنوز انجام نشده است" in soc["validation_note_fa"]


def test_modelled_soilgrids_value_displayed_with_correct_provenance():
    """Requirement 2: A modelled SoilGrids value is displayed with its correct provenance."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix

    extracted = {"soil_organic_carbon": 0.55, "soil_ph": 7.82, "soil_total_nitrogen": 0.085}
    matrix = build_data_availability_matrix(extracted)
    items_by_key = {item["metric_key"]: item for item in matrix}

    for key, expected_dataset in [
        ("soil_organic_carbon", "projects/soilgrids-isric/soc_mean"),
        ("soil_ph", "projects/soilgrids-isric/phh2o_mean"),
        ("soil_total_nitrogen", "projects/soilgrids-isric/nitrogen_mean"),
    ]:
        item = items_by_key[key]
        assert item["dataset_id"] == expected_dataset
        assert item["source"] == "ISRIC SoilGrids 2.0"
        assert item["spatial_resolution_m"] == 250.0
        assert item["depth"] == "0–100 cm (Weighted Profile)"
        # Must be labeled as gridded baseline, NOT satellite observation
        assert item["scientific_status"] == "GRIDDED_SOIL_BASELINE"
        assert "خط مبنای مدل‌شده" in item["scientific_status_fa"]
        assert len(item["limitations"]) > 0


def test_null_or_failed_source_never_replaced_with_zero_or_fabricated_number():
    """Requirement 3: A null or failed source is never replaced with zero or a fabricated number."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix

    # Empty extraction simulation
    matrix = build_data_availability_matrix({})
    items_by_key = {item["metric_key"]: item for item in matrix}

    for key, item in items_by_key.items():
        # NEVER convert null to 0 or 0.0
        assert item["value"] is None
        assert item["value"] != 0
        assert item["value"] != 0.0
        assert item["data_status"] in ("INSUFFICIENT_DATA", "UNAVAILABLE")
        assert "داده واقعی در منبع فعلی موجود نیست" in item["availability_message_fa"]


def test_total_n_and_nitrate_remain_distinct_metrics():
    """Requirement 4: Total N and nitrate remain distinct metrics."""
    from app.services.agriculture.registry.soil_datasets import SOIL_METRIC_REGISTRY, build_data_availability_matrix

    total_n_def = SOIL_METRIC_REGISTRY["soil_total_nitrogen"]
    nitrate_def = SOIL_METRIC_REGISTRY["soil_nitrate"]

    # Distinct keys, units, and scientific status
    assert total_n_def.metric_key != nitrate_def.metric_key
    assert total_n_def.unit == "g/kg"
    assert nitrate_def.unit == "mg/kg"
    assert total_n_def.scientific_status == "GRIDDED_SOIL_BASELINE"
    assert nitrate_def.scientific_status == "UNOBSERVABLE_SATELLITE"

    # Total N cannot substitute for nitrate
    matrix = build_data_availability_matrix({"soil_total_nitrogen": 0.085})
    items = {m["metric_key"]: m for m in matrix}
    assert items["soil_total_nitrogen"]["value"] == 0.085
    assert items["soil_nitrate"]["value"] is None
    assert items["soil_nitrate"]["data_status"] == "UNAVAILABLE"
    assert items["soil_nitrate"]["validation_status"] == "LAB_REQUIRED"


def test_ndvi_and_ndmi_cannot_substitute_for_nutrient_measurements():
    """Requirement 5: NDVI and NDMI cannot silently substitute for nutrient measurements."""
    from app.services.agriculture.registry.soil_datasets import UNAVAILABLE_NUTRIENTS, SOIL_METRIC_REGISTRY

    # Neither Available P, Exchangeable K, nor Nitrate may use optical vegetation indices
    for nut_key in ["available_phosphorus", "exchangeable_potassium", "soil_nitrate"]:
        reg_item = SOIL_METRIC_REGISTRY[nut_key]
        assert reg_item.source is None
        assert reg_item.dataset_id is None
        assert reg_item.variable is None
        assert reg_item.scientific_status == "UNOBSERVABLE_SATELLITE"
        assert reg_item.default_status == "REQUIRES_LAB_VALIDATION"
        assert "NO_SATELLITE_SENSOR_EXISTS" in UNAVAILABLE_NUTRIENTS[nut_key.replace("soil_", "").replace("available_", "").replace("exchangeable_", "")]["reason"]


def test_missing_validation_prevents_unsupported_fertilizer_recommendations():
    """Requirement 6: Missing validation prevents unsupported fertilizer recommendations, not source presentation."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix
    from app.services.agriculture.soil_properties import _PROPERTY_LIMITATIONS

    extracted = {"soil_organic_carbon": 0.62, "soil_ph": 7.8, "soil_total_nitrogen": 0.09}
    matrix = build_data_availability_matrix(extracted)
    items = {m["metric_key"]: m for m in matrix}

    # Data presentation is unblocked
    assert items["soil_organic_carbon"]["value"] == 0.62
    assert items["soil_ph"]["value"] == 7.8
    assert items["soil_total_nitrogen"]["value"] == 0.09

    # But fertilizer recommendations and fertility diagnosis are strictly prohibited in limitations
    limitations_text = " ".join(items["soil_organic_carbon"]["limitations"]) + " " + " ".join(_PROPERTY_LIMITATIONS)
    assert "fertiliser recommendation" in limitations_text or "fertilizer" in limitations_text.lower()
    assert "deficiency" in limitations_text.lower() or "diagnosis" in limitations_text.lower()


def test_api_response_compatibility_and_soil_data_availability_contract():
    """Requirement 7: Existing API response compatibility and soil data availability contract are preserved."""
    from app.services.agriculture.registry.soil_datasets import build_data_availability_matrix
    from app.schemas.agriculture import SoilMetricAvailabilityItem

    extracted = {
        "soil_moisture_surface": 0.12,
        "soil_moisture_rootzone": 0.17,
        "soil_organic_carbon": 0.40,
        "soil_ph": 7.5,
        "soil_total_nitrogen": 0.08,
    }
    matrix = build_data_availability_matrix(extracted, start_date="2026-06-01", end_date="2026-09-01")

    # Must contain exactly 17 metrics
    assert len(matrix) == 17

    # Validate each against the Pydantic schema
    for item in matrix:
        validated = SoilMetricAvailabilityItem(**item)
        assert validated.metric_key == item["metric_key"]
        assert validated.label_en == item["label_en"]
        assert validated.label_fa == item["label_fa"]
        assert validated.unit == item["unit"]
        assert validated.status == item["status"]
        assert validated.data_status in ("AVAILABLE", "INSUFFICIENT_DATA", "UNAVAILABLE")
        assert validated.scientific_status in (
            "SATELLITE_OBSERVATION",
            "REANALYSIS_MODEL",
            "GRIDDED_SOIL_BASELINE",
            "DERIVED",
            "UNOBSERVABLE_SATELLITE",
        )
        assert validated.validation_status in ("NOT_LAB_VERIFIED", "LAB_REQUIRED", "REQUIRES_LAB_VALIDATION")
        assert validated.depth == item["depth"]
        assert validated.spatial_resolution == item["spatial_resolution"]
        assert validated.temporal_period is not None
        assert isinstance(validated.limitations, list)


