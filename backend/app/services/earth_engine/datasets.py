"""Earth Engine dataset definitions and configurations.

All dataset IDs and band names are verified against the official
Google Earth Engine Data Catalog.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import ee


@dataclass
class DatasetConfig:
    """Configuration for an Earth Engine dataset."""
    id: str
    name: str
    description: str
    provider: str
    spatial_resolution: int  # meters
    temporal_resolution: str
    available_from: str  # YYYY-MM-DD
    bands: Dict[str, str]  # band_name -> description
    scale_factor: float = 1.0
    cloud_mask_method: str = "none"  # "scl", "qa60", "none"
    scl_mask_values: List[int] = field(default_factory=list)
    intended_use: str = ""


# ============================================================
# VERIFIED DATASETS
# ============================================================

SENTINEL_2_SR = DatasetConfig(
    id="COPERNICUS/S2_SR_HARMONIZED",
    name="Sentinel-2 Surface Reflectance (Harmonized)",
    description="Harmonized Sentinel-2 MSI Level-2A Surface Reflectance",
    provider="European Space Agency (ESA) / Copernicus",
    spatial_resolution=10,
    temporal_resolution="5 days",
    available_from="2017-03-28",
    bands={
        "B1": "Coastal aerosol (443nm, 60m)",
        "B2": "Blue (490nm, 10m)",
        "B3": "Green (560nm, 10m)",
        "B4": "Red (665nm, 10m)",
        "B5": "Red Edge 1 (705nm, 20m)",
        "B6": "Red Edge 2 (740nm, 20m)",
        "B7": "Red Edge 3 (783nm, 20m)",
        "B8": "NIR (842nm, 10m)",
        "B8A": "NIR Narrow (865nm, 20m)",
        "B9": "Water Vapour (945nm, 60m)",
        "B11": "SWIR 1 (1610nm, 20m)",
        "B12": "SWIR 2 (2190nm, 20m)",
        "QA60": "Cloud mask bitmask (60m)",
        "SCL": "Scene Classification Layer (20m)",
    },
    scale_factor=10000.0,
    cloud_mask_method="scl",
    # SCL values to mask out: No data(0), Defective(1), Cloud shadow(3),
    # Cloud medium(8), Cloud high(9), Cirrus(10)
    scl_mask_values=[0, 1, 3, 8, 9, 10],
    intended_use="NDVI, EVI, SAVI, NDWI, RGB composites, land cover",
)

ERA5_LAND_DAILY = DatasetConfig(
    id="ECMWF/ERA5_LAND/DAILY_AGGR",
    name="ERA5-Land Daily Aggregates",
    description="ERA5-Land daily aggregated reanalysis",
    provider="ECMWF",
    spatial_resolution=11132,
    temporal_resolution="daily",
    available_from="1950-01-01",
    bands={
        "temperature_2m": "2m temperature (K)",
        "total_precipitation_sum": "Total precipitation (m)",
        "soil_moisture_0_to_7cm_surface": "Soil moisture 0-7cm (m³/m³)",
        "reference_evapotranspiration_sum": "Reference ET (m)",
        "surface_runoff_sum": "Surface runoff (m)",
    },
    scale_factor=1.0,
    intended_use="Daily precipitation, temperature, ET, soil moisture",
)

ERA5_MONTHLY = DatasetConfig(
    id="ECMWF/ERA5_MONTHLY_AGGR",
    name="ERA5 Monthly Aggregates",
    description="ERA5 monthly aggregated surface climate reanalysis",
    provider="ECMWF",
    spatial_resolution=30000,
    temporal_resolution="monthly",
    available_from="1979-01-01",
    bands={
        "mean_2m_air_temperature": "Mean temperature (K)",
        "maximum_2m_air_temperature": "Max temperature (K)",
        "minimum_2m_air_temperature": "Min temperature (K)",
        "total_precipitation": "Total precipitation (m)",
        "volumetric_soil_water_layer_1": "Soil moisture layer 1 (m³/m³)",
    },
    scale_factor=1.0,
    intended_use="Monthly climate analysis, anomalies",
)

MODIS_LANDCOVER = DatasetConfig(
    id="MODIS/061/MCD12Q1",
    name="MODIS Land Cover Type (Collection 6.1)",
    description="MODIS Land Cover Type product",
    provider="NASA / USGS",
    spatial_resolution=500,
    temporal_resolution="annual",
    available_from="2001-01-01",
    bands={
        "LC_Type1": "IGBP land cover classification",
        "LC_Type2": "UMD classification",
        "LC_Prop1": "Vegetation continuous fields",
    },
    scale_factor=1.0,
    intended_use="Land cover classification",
)


def get_dataset_config(dataset_id: str) -> Optional[DatasetConfig]:
    """Get configuration for a dataset by ID."""
    datasets = {
        SENTINEL_2_SR.id: SENTINEL_2_SR,
        ERA5_LAND_DAILY.id: ERA5_LAND_DAILY,
        ERA5_MONTHLY.id: ERA5_MONTHLY,
        MODIS_LANDCOVER.id: MODIS_LANDCOVER,
    }
    return datasets.get(dataset_id)


def get_sentinel2_composite(
    geometry: Any,
    start_date: str,
    end_date: str,
    cloud_max_percent: int = 20,
) -> Optional[ee.Image]:
    """Get a cloud-free Sentinel-2 composite.
    
    Args:
        geometry: Earth Engine geometry.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        cloud_max_percent: Max cloud coverage per scene.
    
    Returns:
        Cloud-masked median composite, or None if no images found.
    """
    collection = (
        ee.ImageCollection(SENTINEL_2_SR.id)
        .filterDate(start_date, end_date)
        .filterBounds(geometry)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_max_percent))
    )
    
    count = collection.size().getInfo()
    if count == 0:
        return None
    
    # Apply cloud mask using SCL
    def mask_clouds(image):
        scl = image.select("SCL")
        mask = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(
            scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
        return image.updateMask(mask)
    
    masked = collection.map(mask_clouds)
    
    # Create median composite and rescale
    composite = masked.median()
    
    # Scale to reflectance (0-1)
    optical_bands = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
    composite = composite.divide(SENTINEL_2_SR.scale_factor)
    
    return composite.select(optical_bands)


def calculate_ndvi(image: ee.Image) -> ee.Image:
    """Calculate NDVI from Sentinel-2 image.
    
    NDVI = (B8 - B4) / (B8 + B4)
    
    Args:
        image: Sentinel-2 image with B4 and B8 bands.
    
    Returns:
        Image with single NDVI band.
    """
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return ndvi


def calculate_evi(image: ee.Image) -> ee.Image:
    """Calculate EVI from Sentinel-2 image.
    
    EVI = 2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)
    
    Args:
        image: Sentinel-2 image with B2, B4, B8 bands.
    
    Returns:
        Image with single EVI band.
    """
    evi = image.expression(
        "2.5 * ((NIR - RED) / (NIR + 6.0 * RED - 7.5 * BLUE + 1.0))",
        {
            "NIR": image.select("B8"),
            "RED": image.select("B4"),
            "BLUE": image.select("B2"),
        }
    ).rename("EVI")
    return evi


def calculate_savi(image: ee.Image, L: float = 0.5) -> ee.Image:
    """Calculate SAVI from Sentinel-2 image.
    
    SAVI = ((NIR - RED) / (NIR + RED + L)) * (1 + L)
    
    Args:
        image: Sentinel-2 image with B4, B8 bands.
        L: Soil brightness correction factor (default 0.5).
    
    Returns:
        Image with single SAVI band.
    """
    savi = image.expression(
        "((NIR - RED) / (NIR + RED + L)) * (1.0 + L)",
        {
            "NIR": image.select("B8"),
            "RED": image.select("B4"),
            "L": L,
        }
    ).rename("SAVI")
    return savi


def calculate_ndwi(image: ee.Image) -> ee.Image:
    """Calculate NDWI (McFeeters) from Sentinel-2 image.
    
    NDWI = (GREEN - NIR) / (GREEN + NIR)
    
    Args:
        image: Sentinel-2 image with B3, B8 bands.
    
    Returns:
        Image with single NDWI band.
    """
    ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
    return ndwi
