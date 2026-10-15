"""Central Soil Dataset Registry for Phase P-AGRI-SOIL.

Holds verified Earth Engine assets, depths, bands, scale factors, and caveats
for soil moisture and soil properties.
All assets in this registry have been verified live against GEE runtime.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

@dataclass(frozen=True)
class SoilDepthSpec:
    code: str
    label_en: str
    label_fa: str
    depth_top_cm: float
    depth_bottom_cm: float
    thickness_cm: float

@dataclass(frozen=True)
class SoilDatasetSpec:
    id: str
    name_en: str
    name_fa: str
    provider: str
    property_key: str
    measurement_basis: str  # "PRODUCT" | "MODELLED" | "STATIC_BASELINE"
    spatial_resolution_m: int
    temporal_coverage: str
    unit: str
    scale_factor: float
    is_verified: bool
    depths: Tuple[SoilDepthSpec, ...]
    bands: Tuple[str, ...]
    caveats: Tuple[str, ...]

# Six standard GlobalSoilMap depth intervals (SoilGrids 2.0)
SOILGRIDS_STANDARD_DEPTHS: Tuple[SoilDepthSpec, ...] = (
    SoilDepthSpec("0-5cm", "0–5 cm", "۰ تا ۵ سانتی‌متر", 0.0, 5.0, 5.0),
    SoilDepthSpec("5-15cm", "5–15 cm", "۵ تا ۱۵ سانتی‌متر", 5.0, 15.0, 10.0),
    SoilDepthSpec("15-30cm", "15–30 cm", "۱۵ تا ۳۰ سانتی‌متر", 15.0, 30.0, 15.0),
    SoilDepthSpec("30-60cm", "30–60 cm", "۳۰ تا ۶۰ سانتی‌متر", 30.0, 60.0, 30.0),
    SoilDepthSpec("60-100cm", "60–100 cm", "۶۰ تا ۱۰۰ سانتی‌متر", 60.0, 100.0, 40.0),
    SoilDepthSpec("100-200cm", "100–200 cm", "۱۰۰ تا ۲۰۰ سانتی‌متر", 100.0, 200.0, 100.0),
)

# ERA5-Land Multi-layer Soil Moisture Depths
ERA5_MOISTURE_DEPTHS: Tuple[SoilDepthSpec, ...] = (
    SoilDepthSpec("layer1", "0–7 cm (Surface)", "۰ تا ۷ سانتی‌متر (سطحی)", 0.0, 7.0, 7.0),
    SoilDepthSpec("layer2", "7–28 cm (Upper root zone)", "۷ تا ۲۸ سانتی‌متر (ریشه فوقانی)", 7.0, 28.0, 21.0),
    SoilDepthSpec("layer3", "28–100 cm (Deep root zone)", "۲۸ تا ۱۰۰ سانتی‌متر (ریشه تحتانی)", 28.0, 100.0, 72.0),
    SoilDepthSpec("layer4", "100–289 cm (Subsoil)", "۱۰۰ تا ۲۸۹ سانتی‌متر (زیر خاک)", 100.0, 289.0, 189.0),
)

# Central registry of verified soil datasets
SOIL_DATASETS: Dict[str, SoilDatasetSpec] = {
    # 1. Soil Moisture
    "smap_l3_surface": SoilDatasetSpec(
        id="NASA/SMAP/SPL3SMP_E/006",
        name_en="SMAP L3 Enhanced Surface Soil Moisture",
        name_fa="رطوبت سطحی خاک ماهواره SMAP",
        provider="NASA / JPL",
        property_key="soil_moisture_surface",
        measurement_basis="PRODUCT",
        spatial_resolution_m=9000,
        temporal_coverage="2015-03-31 to Present",
        unit="m3/m3",
        scale_factor=1.0,
        is_verified=True,
        depths=(SoilDepthSpec("0-5cm", "0–5 cm", "۰ تا ۵ سانتی‌متر", 0.0, 5.0, 5.0),),
        bands=("soil_moisture_am", "soil_moisture_pm"),
        caveats=(
            "Radiometer retrieval at 9 km spatial resolution; coarse regional indicator.",
            "Represents top 5 cm only, sensitive to surface roughness and dense vegetation.",
        ),
    ),
    "smap_l4_rootzone": SoilDatasetSpec(
        id="NASA/SMAP/SPL4SMGP/008",
        name_en="SMAP L4 Global Root-Zone Soil Moisture",
        name_fa="رطوبت لایه ریشه خاک SMAP L4",
        provider="NASA / GSFC GMAO",
        property_key="soil_moisture_rootzone",
        measurement_basis="MODELLED",
        spatial_resolution_m=9000,
        temporal_coverage="2015-03-31 to Present",
        unit="m3/m3",
        scale_factor=1.0,
        is_verified=True,
        depths=(SoilDepthSpec("0-100cm", "0–100 cm (Root zone)", "۰ تا ۱۰۰ سانتی‌متر (منطقه ریشه)", 0.0, 100.0, 100.0),),
        bands=("sm_rootzone", "sm_surface"),
        caveats=(
            "Assimilated geophysical land-surface model; modelled output constrained by satellite observations.",
            "Coarse 9 km resolution; provides regional contextual moisture, not point precision.",
        ),
    ),
    "era5_land_moisture": SoilDatasetSpec(
        id="ECMWF/ERA5_LAND/DAILY_AGGR",
        name_en="ERA5-Land Daily Volumetric Soil Water",
        name_fa="آب حجمی خاک چندلایه‌ای ERA5-Land",
        provider="ECMWF",
        property_key="soil_moisture_multilayer",
        measurement_basis="MODELLED",
        spatial_resolution_m=11132,
        temporal_coverage="1950-01-01 to Present",
        unit="m3/m3",
        scale_factor=1.0,
        is_verified=True,
        depths=ERA5_MOISTURE_DEPTHS,
        bands=(
            "volumetric_soil_water_layer_1",
            "volumetric_soil_water_layer_2",
            "volumetric_soil_water_layer_3",
            "volumetric_soil_water_layer_4",
        ),
        caveats=(
            "Atmospheric reanalysis land surface model driven by meteorological observations.",
            "Provides 4 discrete depth layers down to 289 cm.",
        ),
    ),

    # 2. Soil Properties (Verified ISRIC SoilGrids 2.0 in GEE)
    "soilgrids_soc": SoilDatasetSpec(
        id="projects/soilgrids-isric/soc_mean",
        name_en="SoilGrids 2.0 Soil Organic Carbon (SOC)",
        name_fa="کربن آلی خاک (SOC)",
        provider="ISRIC - World Soil Information",
        property_key="soil_organic_carbon",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="g/kg",
        scale_factor=0.1,  # Raw is dg/kg; multiply by 0.1 to obtain g/kg
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"soc_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Machine-learning digital soil mapping prediction (Random Forest) trained on global profile databases.",
            "Represents a static modelled baseline; not a dynamic multi-year time-series.",
            "Spatial resolution 250 m; laboratory soil sample testing is required for precise parcel fertilization.",
        ),
    ),
    "soilgrids_ph": SoilDatasetSpec(
        id="projects/soilgrids-isric/phh2o_mean",
        name_en="SoilGrids 2.0 Soil pH in H2O",
        name_fa="اسیدیته خاک (pH در آب)",
        provider="ISRIC - World Soil Information",
        property_key="soil_ph",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="pH",
        scale_factor=0.1,  # Raw is pH*10; multiply by 0.1 to obtain pH
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"phh2o_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Modelled baseline at 250 m resolution.",
            "Soil pH varies locally with irrigation water quality and local amendments.",
        ),
    ),
    "soilgrids_nitrogen": SoilDatasetSpec(
        id="projects/soilgrids-isric/nitrogen_mean",
        name_en="SoilGrids 2.0 Total Nitrogen",
        name_fa="نیتروژن کل خاک",
        provider="ISRIC - World Soil Information",
        property_key="soil_total_nitrogen",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="g/kg",
        scale_factor=0.01,  # Raw is cg/kg; multiply by 0.01 to obtain g/kg
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"nitrogen_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Predicts total organic and inorganic nitrogen pool; NOT instantaneous plant-available nitrate (NO3-).",
            "Available nitrogen fluctuates rapidly with fertilization and requires laboratory testing.",
        ),
    ),
    "soilgrids_sand": SoilDatasetSpec(
        id="projects/soilgrids-isric/sand_mean",
        name_en="SoilGrids 2.0 Sand Fraction",
        name_fa="درصد ذرات ماسه (شن)",
        provider="ISRIC - World Soil Information",
        property_key="soil_sand_content",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="%",
        scale_factor=0.1,  # Raw is g/kg (0.1%); multiply by 0.1 to obtain %
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"sand_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Physical particle size fraction (> 0.05 mm, USDA classification).",
            "Static physical property at 250 m resolution.",
        ),
    ),
    "soilgrids_silt": SoilDatasetSpec(
        id="projects/soilgrids-isric/silt_mean",
        name_en="SoilGrids 2.0 Silt Fraction",
        name_fa="درصد ذرات سیلت (لای)",
        provider="ISRIC - World Soil Information",
        property_key="soil_silt_content",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="%",
        scale_factor=0.1,  # Raw is g/kg (0.1%); multiply by 0.1 to obtain %
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"silt_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Physical particle size fraction (0.002 to 0.05 mm, USDA classification).",
            "Static physical property at 250 m resolution.",
        ),
    ),
    "soilgrids_clay": SoilDatasetSpec(
        id="projects/soilgrids-isric/clay_mean",
        name_en="SoilGrids 2.0 Clay Fraction",
        name_fa="درصد ذرات رس",
        provider="ISRIC - World Soil Information",
        property_key="soil_clay_content",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="%",
        scale_factor=0.1,  # Raw is g/kg (0.1%); multiply by 0.1 to obtain %
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"clay_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Physical particle size fraction (< 0.002 mm, USDA classification).",
            "Controls cation exchange capacity and water holding capacity.",
        ),
    ),
    "soilgrids_cec": SoilDatasetSpec(
        id="projects/soilgrids-isric/cec_mean",
        name_en="SoilGrids 2.0 Cation Exchange Capacity (CEC)",
        name_fa="ظرفیت تبادل کاتیونی (CEC)",
        provider="ISRIC - World Soil Information",
        property_key="soil_cec",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline (reference ~2020)",
        unit="cmol(c)/kg",
        scale_factor=0.1,  # Raw is mmol(c)/kg; multiply by 0.1 to obtain cmol(c)/kg
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"cec_{d.code}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Buffer capacity index representing soil ability to hold exchangeable cations.",
            "Static modelled prediction at 250 m resolution.",
        ),
    ),
    "soilgrids_wv0033": SoilDatasetSpec(
        id="ISRIC/SoilGrids250m/v2_0/wv0033",
        name_en="SoilGrids 2.0 Water Retention at 33 kPa (Field Capacity)",
        name_fa="نگهداشت آب در مکش ۳۳ کیلوپاسکال (ظرفیت زراعی)",
        provider="ISRIC - World Soil Information",
        property_key="soil_field_capacity",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline",
        unit="m3/m3",
        scale_factor=1.0,
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"val_{d.code.replace('-', '_')}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Laboratory matric suction conventionally representing field capacity in temperate soils.",
        ),
    ),
    "soilgrids_wv1500": SoilDatasetSpec(
        id="ISRIC/SoilGrids250m/v2_0/wv1500",
        name_en="SoilGrids 2.0 Water Retention at 1500 kPa (Wilting Point)",
        name_fa="نگهداشت آب در مکش ۱۵۰۰ کیلوپاسکال (نقطه پژمردگی)",
        provider="ISRIC - World Soil Information",
        property_key="soil_wilting_point",
        measurement_basis="STATIC_BASELINE",
        spatial_resolution_m=250,
        temporal_coverage="Static modelled baseline",
        unit="m3/m3",
        scale_factor=1.0,
        is_verified=True,
        depths=SOILGRIDS_STANDARD_DEPTHS,
        bands=tuple(f"val_{d.code.replace('-', '_')}_mean" for d in SOILGRIDS_STANDARD_DEPTHS),
        caveats=(
            "Laboratory matric suction conventionally representing permanent wilting point.",
        ),
    ),
}

# Explicitly unverified / unavailable chemical elements and properties
UNAVAILABLE_NUTRIENTS: Dict[str, Dict[str, Any]] = {
    "phosphorus": {
        "key": "available_phosphorus",
        "name_en": "Available Phosphorus (P - Olsen)",
        "name_fa": "فسفر قابل جذب خاک (P)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "سنجنده‌های ماهواره‌ای قادر به اندازه‌گیری مستقیم فسفر قابل جذب خاک نیستند. تعیین فسفر نیازمند آزمون آزمایشگاهی عصاره اولسن است.",
        "message_en": "Satellite sensors cannot measure soil available phosphorus directly. Laboratory soil testing (Olsen method) is required.",
        "next_action": "Upload soil lab result (Olsen P method)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (روش اولسن)",
    },
    "potassium": {
        "key": "exchangeable_potassium",
        "name_en": "Exchangeable Potassium (K)",
        "name_fa": "پتاسیم قابل جذب خاک (K)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "پتاسیم تبادلی خاک فاقد بازتاب طیفی مستقیم در داده‌های ماهواره‌ای است و نیازمند آزمون آزمایشگاهی خاک است.",
        "message_en": "Exchangeable potassium has no direct spectral signature in satellite data and requires laboratory soil testing.",
        "next_action": "Upload soil lab result (Ammonium Acetate extraction)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (عصاره استات آمونیوم)",
    },
    "nitrate": {
        "key": "soil_nitrate",
        "name_en": "Soil Nitrate (NO3-)",
        "name_fa": "نیترات خاک (NO3-)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "نیترات یون متحرک و فاقد بازتاب طیفی مستقیم است که وابسته به آبیاری تغییر می‌کند؛ با نیتروژن کل متفاوت بوده و نیازمند سنجش آزمایشگاهی است.",
        "message_en": "Nitrate is a mobile ion distinct from Total Nitrogen; varies with irrigation and requires wet-chemistry laboratory testing.",
        "next_action": "Upload soil lab result (Spectrophotometric / Ion-selective method)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (اسپکتروفتومتری / الکترود انتخابی)",
    },
    "electrical_conductivity": {
        "key": "soil_electrical_conductivity",
        "name_en": "Electrical Conductivity (EC / Salinity)",
        "name_fa": "هدایت الکتریکی / شوری خاک (EC)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "شوری عصاره اشباع خاک فاقد سنجش مستقیم ماهواره‌ای در عمق ریشه بوده و نیازمند آزمون آزمایشگاهی هدایت‌سنجی (ECe) است.",
        "message_en": "Soil saturation extract salinity lacks direct remote sensing at depth; laboratory electrical conductivity testing (ECe) is required.",
        "next_action": "Upload soil lab result (ECe saturation paste)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (هدایت‌سنجی گل اشباع ECe)",
    },
    "zinc": {
        "key": "soil_zinc",
        "name_en": "Available Zinc (Zn)",
        "name_fa": "روی قابل جذب خاک (Zn)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "ریزمغذی روی به علت غلظت در مقیاس ppm از فضا قابل سنجش نیست و نیازمند آزمون خاک با عصاره‌گیر DTPA است.",
        "message_en": "Zinc micronutrient concentration (ppm level) cannot be resolved by satellite remote sensing. Requires DTPA soil testing.",
        "next_action": "Upload soil lab result (DTPA extraction)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (عصاره DTPA)",
    },
    "iron": {
        "key": "soil_iron",
        "name_en": "Available Iron (Fe)",
        "name_fa": "آهن قابل جذب خاک (Fe)",
        "status": "UNAVAILABLE",
        "scientific_status": "REQUIRES_LAB_VALIDATION",
        "validation_status": "LAB_REQUIRED",
        "reason": "NO_SATELLITE_SENSOR_EXISTS",
        "message_fa": "آهن قابل جذب خاک نیازمند آزمون مستقیم آزمایشگاهی است؛ کانی‌های سطحی آهن با آهن قابل جذب گیاه متفاوت هستند.",
        "message_en": "Plant-available iron requires direct laboratory testing; surface mineral iron does not reflect plant-available Fe.",
        "next_action": "Upload soil lab result (DTPA extraction)",
        "next_action_fa": "ثبت نتیجه آزمون آزمایشگاه خاک (عصاره DTPA)",
    },
}


@dataclass(frozen=True)
class SoilMetricDefinition:
    """Standardized scientific soil metric descriptor (Phase P-AGRI-SOIL-2 / P-AGRI-SOIL-3)."""

    metric_key: str
    label_en: str
    label_fa: str
    unit: str
    source: Optional[str]
    dataset_id: Optional[str]
    default_status: str  # "AVAILABLE" | "MODELLED_BASELINE" | "REQUIRES_LAB_VALIDATION"
    validation_status: str  # "NOT_LAB_VERIFIED" | "REQUIRES_LAB_VALIDATION" | "LAB_REQUIRED"
    depth_str: str
    depth_cm: Tuple[float, float]
    spatial_resolution_str: str
    spatial_resolution_m: Optional[float]
    temporal_resolution_str: str
    is_ground_truth: bool  # strictly False for remote-sensing & modelled datasets
    requires_lab_validation: bool  # True for agricultural decision safety
    variable: Optional[str] = None
    scientific_status: str = "GRIDDED_SOIL_BASELINE"
    scientific_status_fa: str = "خط مبنای مدل‌شده خاک"
    validation_note_fa: str = "داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است."
    limitations: Tuple[str, ...] = ()
    reason_en: Optional[str] = None
    reason_fa: Optional[str] = None
    next_action_en: Optional[str] = None
    next_action_fa: Optional[str] = None


SOIL_METRIC_REGISTRY: Dict[str, SoilMetricDefinition] = {
    # 1. Soil Moisture
    "soil_moisture_surface": SoilMetricDefinition(
        metric_key="soil_moisture_surface",
        label_en="Surface Soil Moisture",
        label_fa="رطوبت سطحی خاک",
        unit="m3/m3",
        source="NASA SMAP SPL3SMP_E / ERA5-Land",
        dataset_id="NASA/SMAP/SPL3SMP_E/006",
        default_status="AVAILABLE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–5 cm",
        depth_cm=(0.0, 5.0),
        spatial_resolution_str="9000 m (9 km)",
        spatial_resolution_m=9000.0,
        temporal_resolution_str="Daily dynamic observation",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="soil_moisture_am",
        scientific_status="SATELLITE_OBSERVATION",
        scientific_status_fa="مشاهده سنجش از دور ماهواره‌ای (SMAP L3)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Radiometer retrieval at 9 km spatial resolution; coarse regional indicator.",
            "Represents top 5 cm only, sensitive to surface roughness and dense vegetation.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="In-situ capacitive sensor verification recommended",
        next_action_fa="پایش میدانی با حسگرهای رطوبت‌سنجی خازنی",
    ),
    "soil_moisture_rootzone": SoilMetricDefinition(
        metric_key="soil_moisture_rootzone",
        label_en="Root-Zone Soil Moisture",
        label_fa="رطوبت ناحیه ریشه خاک",
        unit="m3/m3",
        source="NASA SMAP SPL4SMGP / ECMWF ERA5-Land",
        dataset_id="NASA/SMAP/SPL4SMGP/008",
        default_status="AVAILABLE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="9000 m - 11132 m (~9-11 km)",
        spatial_resolution_m=9000.0,
        temporal_resolution_str="Daily dynamic assimilation",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="sm_rootzone",
        scientific_status="REANALYSIS_MODEL",
        scientific_status_fa="خروجی مدل بازتحلیل / شبیه‌سازی زمین (SMAP L4 / ERA5-Land)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Assimilated geophysical land-surface model at 9-11 km resolution.",
            "Regional contextual moisture, not point precision.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="In-situ soil profile moisture measurement recommended",
        next_action_fa="اندازه‌گیری دوره‌ای رطوبت پروفیل خاک",
    ),

    # 2. SoilGrids 2.0 Modelled Properties (0-100 cm Weighted Mean)
    "soil_organic_carbon": SoilMetricDefinition(
        metric_key="soil_organic_carbon",
        label_en="Soil Organic Carbon (SOC)",
        label_fa="کربن آلی خاک (SOC)",
        unit="g/kg",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/soc_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline (~2020)",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="soc_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Random Forest digital soil mapping baseline (250 m).",
            "Static reference baseline (~2020); not a dynamic multi-year time-series.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Walkley-Black laboratory soil sample analysis",
        next_action_fa="آزمایش خاک آزمایشگاهی به روش والکلی-بلک",
    ),
    "soil_ph": SoilMetricDefinition(
        metric_key="soil_ph",
        label_en="Soil pH in H2O",
        label_fa="اسیدیته خاک (pH در آب)",
        unit="pH",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/phh2o_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline (~2020)",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="phh2o_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Modelled baseline at 250 m resolution.",
            "Soil pH varies locally with irrigation water quality and local amendments.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Laboratory potentiometric pH testing in 1:1 soil water suspension",
        next_action_fa="سنجش پتانسیومتری pH در گل اشباع یا عصاره ۱:۱",
    ),
    "soil_total_nitrogen": SoilMetricDefinition(
        metric_key="soil_total_nitrogen",
        label_en="Total Nitrogen (SoilGrids 2.0)",
        label_fa="نیتروژن کل خاک",
        unit="g/kg",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/nitrogen_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline (~2020)",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="nitrogen_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Modelled total organic and inorganic nitrogen pool; strictly distinct from instantaneous nitrate (NO3-).",
            "Available nitrogen fluctuates rapidly with fertilization and requires laboratory testing.",
        ),
        reason_en="Modelled total nitrogen pool; strictly distinct from instantaneous plant-available nitrate (NO3-).",
        reason_fa="پیش‌بینی مدل‌شده مخزن کل نیتروژن ارگانیک و معدنی؛ کاملاً متفاوت از نیترات قابل جذب گیاه (NO3-).",
        next_action_en="Kjeldahl total nitrogen + Nitrate extraction test in accredited lab",
        next_action_fa="اندازه‌گیری نیتروژن کل کجلدال و عصاره نیترات در آزمایشگاه معتمد",
    ),
    "soil_sand_content": SoilMetricDefinition(
        metric_key="soil_sand_content",
        label_en="Sand Fraction",
        label_fa="درصد ذرات ماسه (شن)",
        unit="%",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/sand_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="sand_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Physical particle size fraction (> 0.05 mm, USDA classification).",
            "Static physical property at 250 m resolution.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Hydrometer / Pipette texture test",
        next_action_fa="دانه‌بندی آزمایشگاهی به روش هیدرومتری",
    ),
    "soil_silt_content": SoilMetricDefinition(
        metric_key="soil_silt_content",
        label_en="Silt Fraction",
        label_fa="درصد ذرات سیلت (لای)",
        unit="%",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/silt_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="silt_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Physical particle size fraction (0.002 to 0.05 mm, USDA classification).",
            "Static physical property at 250 m resolution.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Hydrometer / Pipette texture test",
        next_action_fa="دانه‌بندی آزمایشگاهی به روش هیدرومتری",
    ),
    "soil_clay_content": SoilMetricDefinition(
        metric_key="soil_clay_content",
        label_en="Clay Fraction",
        label_fa="درصد ذرات رس",
        unit="%",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/clay_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="clay_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Physical particle size fraction (< 0.002 mm, USDA classification).",
            "Controls cation exchange capacity and water holding capacity.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Hydrometer / Pipette texture test",
        next_action_fa="دانه‌بندی آزمایشگاهی به روش هیدرومتری",
    ),
    "soil_cec": SoilMetricDefinition(
        metric_key="soil_cec",
        label_en="Cation Exchange Capacity (CEC)",
        label_fa="ظرفیت تبادل کاتیونی (CEC)",
        unit="cmol(c)/kg",
        source="ISRIC SoilGrids 2.0",
        dataset_id="projects/soilgrids-isric/cec_mean",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm (Weighted Profile)",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="cec_mean",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Buffer capacity index representing soil ability to hold exchangeable cations.",
            "Static modelled prediction at 250 m resolution.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Ammonium acetate extraction test",
        next_action_fa="آزمون تبادل کاتیونی با استات آمونیوم در آزمایشگاه",
    ),
    "soil_field_capacity": SoilMetricDefinition(
        metric_key="soil_field_capacity",
        label_en="Water Retention at 33 kPa (Field Capacity)",
        label_fa="ظرفیت زراعی خاک (FC در ۳۳ kPa)",
        unit="m3/m3",
        source="ISRIC SoilGrids 2.0 wv0033",
        dataset_id="ISRIC/SoilGrids250m/v2_0/wv0033",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="val_mean (33 kPa)",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0 wv0033)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Laboratory matric suction conventionally representing field capacity in temperate soils.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Pressure plate laboratory test",
        next_action_fa="آزمون صفحات فشاری در آزمایشگاه فیزیک خاک",
    ),
    "soil_wilting_point": SoilMetricDefinition(
        metric_key="soil_wilting_point",
        label_en="Water Retention at 1500 kPa (Wilting Point)",
        label_fa="نقطه پژمردگی دائم خاک (WP در ۱۵۰۰ kPa)",
        unit="m3/m3",
        source="ISRIC SoilGrids 2.0 wv1500",
        dataset_id="ISRIC/SoilGrids250m/v2_0/wv1500",
        default_status="MODELLED_BASELINE",
        validation_status="NOT_LAB_VERIFIED",
        depth_str="0–100 cm",
        depth_cm=(0.0, 100.0),
        spatial_resolution_str="250 m",
        spatial_resolution_m=250.0,
        temporal_resolution_str="Static modelled baseline",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable="val_mean (1500 kPa)",
        scientific_status="GRIDDED_SOIL_BASELINE",
        scientific_status_fa="خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0 wv1500)",
        validation_note_fa="داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.",
        limitations=(
            "Laboratory matric suction conventionally representing permanent wilting point.",
        ),
        reason_en=None,
        reason_fa=None,
        next_action_en="Pressure membrane laboratory test",
        next_action_fa="آزمون غشای فشاری در آزمایشگاه فیزیک خاک",
    ),

    # 3. Explicitly Unobservable / Lab Required Chemical Parameters
    "available_phosphorus": SoilMetricDefinition(
        metric_key="available_phosphorus",
        label_en="Available Phosphorus (P - Olsen)",
        label_fa="فسفر قابل جذب خاک (P)",
        unit="mg/kg",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک (عصاره اولسن)؛ سنجنده‌های ماهواره‌ای فاقد امکان سنجش هستند.",
        limitations=(
            "Satellite-only estimate not validated; no direct spectral absorption signature for soil solution orthophosphate.",
            "Laboratory soil testing (Olsen method) is strictly required.",
        ),
        reason_en="Satellite-only estimate not validated; no direct spectral absorption signature for soil solution orthophosphate.",
        reason_fa="سنجنده‌های ماهواره‌ای فاقد بازتابش طیفی مستقیم برای اندازه‌گیری ارتوپفسفات محلول خاک هستند.",
        next_action_en="Upload soil lab result (Olsen P method)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (روش اولسن)",
    ),
    "exchangeable_potassium": SoilMetricDefinition(
        metric_key="exchangeable_potassium",
        label_en="Exchangeable Potassium (K)",
        label_fa="پتاسیم تبادلی خاک (K)",
        unit="mg/kg",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک (عصاره استات آمونیوم)؛ فاقد بازتاب طیفی ماهواره‌ای.",
        limitations=(
            "No validated regional model; exchangeable K+ ion concentration has no direct satellite signature.",
            "Requires laboratory soil testing (Ammonium Acetate extraction).",
        ),
        reason_en="No validated regional model; exchangeable K+ ion concentration has no direct satellite signature.",
        reason_fa="پتاسیم تبادلی خاک فاقد ویژگی جذبی در باندهای ماهواره‌ای است و نیازمند آزمون با استات آمونیوم است.",
        next_action_en="Upload soil lab result (Ammonium Acetate extraction)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (عصاره استات آمونیوم)",
    ),
    "soil_nitrate": SoilMetricDefinition(
        metric_key="soil_nitrate",
        label_en="Soil Nitrate (NO3-)",
        label_fa="نیترات خاک (NO3-)",
        unit="mg/kg",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک؛ کاملاً متمایز از نیتروژن کل بوده و متحرک است.",
        limitations=(
            "Not equivalent to Total Nitrogen; highly dynamic mobile anion depending on irrigation and temperature.",
            "Requires direct wet-chemistry laboratory testing.",
        ),
        reason_en="Not equivalent to Total Nitrogen; highly dynamic mobile anion depending on irrigation and temperature, requires direct wet-chemistry lab test.",
        reason_fa="نیترات بر خلاف نیتروژن کل، آنیون متحرک و ناپایدار است که با آبیاری جابه‌جا شده و صرفاً با آزمون آزمایشگاهی تعیین می‌شود.",
        next_action_en="Upload soil lab result (Spectrophotometric / Ion-selective method)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (اسپکتروفتومتری / الکترود انتخابی)",
    ),
    "soil_electrical_conductivity": SoilMetricDefinition(
        metric_key="soil_electrical_conductivity",
        label_en="Electrical Conductivity (ECe / Salinity)",
        label_fa="هدایت الکتریکی عصاره اشباع خاک (ECe / شوری)",
        unit="dS/m",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک (هدایت‌سنجی گل اشباع ECe)؛ سنجش از فضا مقدور نیست.",
        limitations=(
            "Satellite estimate not validated at depth; surface salinity crusts cannot quantify root-zone ECe.",
            "Laboratory electrical conductivity testing (ECe) is strictly required.",
        ),
        reason_en="Satellite estimate not validated at depth; surface salinity crusts cannot quantify root-zone ECe.",
        reason_fa="سنجش ماهواره‌ای صرفاً بازتاب نمک‌های سپید سطحی را می‌بیند و قادر به اندازه‌گیری شوری عصاره اشباع عمق ریشه نیست.",
        next_action_en="Upload soil lab result (ECe saturation paste conductometry)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (هدایت‌سنجی گل اشباع ECe)",
    ),
    "soil_zinc": SoilMetricDefinition(
        metric_key="soil_zinc",
        label_en="Available Zinc (Zn)",
        label_fa="روی قابل جذب خاک (Zn)",
        unit="mg/kg",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک (عصاره DTPA)؛ غلظت در حد ppm از فضا قابل تفکیک نیست.",
        limitations=(
            "Zinc micronutrient concentration (ppm level) cannot be resolved by satellite remote sensing.",
            "Requires DTPA soil testing.",
        ),
        reason_en="Zinc micronutrient concentration (ppm level) cannot be resolved by satellite remote sensing. Requires DTPA soil testing.",
        reason_fa="غلظت روی در حد میلی‌گرم بر کیلوگرم (ppm) بوده و از فضا قابل تفکیک نیست؛ نیازمند آزمون DTPA در آزمایشگاه است.",
        next_action_en="Upload soil lab result (DTPA extraction)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (عصاره DTPA)",
    ),
    "soil_iron": SoilMetricDefinition(
        metric_key="soil_iron",
        label_en="Available Iron (Fe)",
        label_fa="آهن قابل جذب خاک (Fe)",
        unit="mg/kg",
        source=None,
        dataset_id=None,
        default_status="REQUIRES_LAB_VALIDATION",
        validation_status="LAB_REQUIRED",
        depth_str="0–30 cm",
        depth_cm=(0.0, 30.0),
        spatial_resolution_str="N/A",
        spatial_resolution_m=None,
        temporal_resolution_str="N/A",
        is_ground_truth=False,
        requires_lab_validation=True,
        variable=None,
        scientific_status="UNOBSERVABLE_SATELLITE",
        scientific_status_fa="عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)",
        validation_note_fa="نیازمند آزمون آزمایشگاهی خاک (عصاره DTPA)؛ کانی‌های سطحی نمایانگر آهن قابل جذب نیستند.",
        limitations=(
            "Plant-available iron requires direct laboratory testing; surface mineral iron does not reflect plant-available Fe.",
            "DTPA soil testing is strictly required.",
        ),
        reason_en="Plant-available iron requires direct laboratory testing; surface mineral iron does not reflect plant-available Fe.",
        reason_fa="کانی‌های اکسید آهن سطحی نشان‌دهنده آهن قابل جذب ریشه نیستند؛ آزمون عصاره‌گیری DTPA مورد نیاز است.",
        next_action_en="Upload soil lab result (DTPA extraction)",
        next_action_fa="ثبت نتیجه آزمون آزمایشگاه خاک (عصاره DTPA)",
    ),
}


def build_data_availability_matrix(
    extracted_values: Dict[str, Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build the comprehensive Data Availability Matrix matching Phase P-AGRI-SOIL-3 contract.

    Merges real extracted values for available/modelled metrics and explicitly documents
    unavailable/lab-required metrics with complete scientific rationale.
    Separates:
    1. Data availability (whether a real source value was successfully retrieved)
    2. Data provenance (product, dataset, band, depth, date, processing method)
    3. Scientific status (satellite observation, reanalysis/model output, gridded soil baseline, derived)
    4. Validation status (independent laboratory or field validation status)
    """
    matrix: List[Dict[str, Any]] = []

    for key, spec in SOIL_METRIC_REGISTRY.items():
        val = extracted_values.get(key)
        
        # Determine actual availability and validation status
        if spec.default_status in ("AVAILABLE", "MODELLED_BASELINE", "DERIVED"):
            if val is not None:
                current_status = spec.default_status
                data_status = "AVAILABLE"
                validation_status = spec.validation_status
                validation_note_fa = spec.validation_note_fa
                availability_message_fa = "داده واقعی منبع با موفقیت فراخوانی شد."
            else:
                current_status = "INSUFFICIENT_DATA"
                data_status = "INSUFFICIENT_DATA"
                validation_status = "REQUIRES_LAB_VALIDATION"
                validation_note_fa = "داده در منبع فعلی در دسترس نبود؛ نیازمند داده تکمیلی."
                availability_message_fa = "داده واقعی در منبع فعلی موجود نیست — عدم پوشش در بازه زمانی یا مختصات درخواستی."
        else:
            current_status = spec.default_status
            data_status = "UNAVAILABLE"
            validation_status = spec.validation_status
            validation_note_fa = spec.validation_note_fa
            availability_message_fa = f"داده واقعی در منبع فعلی موجود نیست — {spec.reason_fa or ''}"

        # Temporal period
        if start_date and end_date and "moisture" in key:
            temporal_period = f"{start_date} to {end_date}"
        elif spec.dataset_id and "soilgrids" in spec.dataset_id.lower():
            temporal_period = "Static modelled baseline (~2020)"
        elif spec.default_status == "REQUIRES_LAB_VALIDATION":
            temporal_period = "N/A"
        else:
            temporal_period = spec.temporal_resolution_str

        item = {
            "metric_key": spec.metric_key,
            "label_en": spec.label_en,
            "label_fa": spec.label_fa,
            "value": val,
            "unit": spec.unit,
            "source": spec.source,
            "dataset_id": spec.dataset_id,
            "variable": spec.variable,
            "band": spec.variable,
            "status": current_status,
            "data_status": data_status,
            "scientific_status": spec.scientific_status,
            "scientific_status_fa": spec.scientific_status_fa,
            "validation_status": validation_status,
            "validation_note_fa": validation_note_fa,
            "availability_message_fa": availability_message_fa,
            "depth": spec.depth_str,
            "depth_cm": list(spec.depth_cm),
            "spatial_resolution": spec.spatial_resolution_str,
            "spatial_resolution_m": spec.spatial_resolution_m,
            "temporal_resolution": spec.temporal_resolution_str,
            "temporal_period": temporal_period,
            "is_ground_truth": spec.is_ground_truth,
            "requires_lab_validation": spec.requires_lab_validation,
            "reason": spec.reason_en,
            "reason_fa": spec.reason_fa,
            "limitations": list(spec.limitations),
            "next_action": spec.next_action_en,
            "next_action_fa": spec.next_action_fa,
        }
        matrix.append(item)

    return matrix

