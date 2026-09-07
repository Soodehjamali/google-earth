"""Vegetation index calculation engine.

All formulas are documented in docs/INDICES.md.
"""

from typing import Dict, List, Optional, Tuple

import ee

from app.services.earth_engine.datasets import (
    calculate_ndvi,
    calculate_evi,
    calculate_savi,
    calculate_ndwi,
)


# Index definitions for documentation and validation
INDEX_DEFINITIONS = {
    "NDVI": {
        "formula": "(B8 - B4) / (B8 + B4)",
        "required_bands": ["B4", "B8"],
        "expected_range": (-1.0, 1.0),
        "typical_vegetation_range": (0.2, 0.8),
        "unit": "dimensionless",
        "interpretation": "Vegetation greenness and density",
    },
    "EVI": {
        "formula": "2.5 * (B8 - B4) / (B8 + 6*B4 - 7.5*B2 + 1)",
        "required_bands": ["B2", "B4", "B8"],
        "expected_range": (-1.0, 1.0),
        "typical_vegetation_range": (0.2, 0.6),
        "unit": "dimensionless",
        "interpretation": "Enhanced vegetation signal with atmospheric correction",
    },
    "SAVI": {
        "formula": "((B8 - B4) / (B8 + B4 + L)) * (1 + L), L=0.5",
        "required_bands": ["B4", "B8"],
        "expected_range": (-1.0, 1.0),
        "typical_vegetation_range": (0.1, 0.7),
        "unit": "dimensionless",
        "interpretation": "Soil-adjusted vegetation index for sparse vegetation",
    },
    "NDWI": {
        "formula": "(B3 - B8) / (B3 + B8)",
        "required_bands": ["B3", "B8"],
        "expected_range": (-1.0, 1.0),
        "typical_vegetation_range": (-0.5, 0.5),
        "unit": "dimensionless",
        "interpretation": "Water body detection and vegetation water content",
    },
}


def compute_indices(
    image: ee.Image,
    indices: Optional[List[str]] = None,
) -> ee.Image:
    """Compute vegetation indices on a Sentinel-2 image.
    
    Args:
        image: Cloud-masked Sentinel-2 image (rescaled to reflectance).
        indices: List of index names to compute. Default: all.
    
    Returns:
        Image with computed index bands added.
    """
    if indices is None:
        indices = ["NDVI", "EVI", "SAVI", "NDWI"]
    
    result = image
    
    for index_name in indices:
        if index_name == "NDVI":
            result = result.addBands(calculate_ndvi(image))
        elif index_name == "EVI":
            result = result.addBands(calculate_evi(image))
        elif index_name == "SAVI":
            result = result.addBands(calculate_savi(image))
        elif index_name == "NDWI":
            result = result.addBands(calculate_ndwi(image))
    
    return result


def compute_index_statistics(
    image: ee.Image,
    geometry: ee.Geometry,
    indices: Optional[List[str]] = None,
    scale: int = 10,
) -> Dict[str, Dict[str, float]]:
    """Compute spatial statistics for vegetation indices.
    
    Args:
        image: Image with index bands.
        geometry: Area of interest.
        indices: Index names to compute statistics for.
        scale: Resolution in meters.
    
    Returns:
        Dictionary mapping index names to statistics.
    """
    if indices is None:
        indices = ["NDVI", "EVI", "SAVI", "NDWI"]
    
    results = {}
    
    for index_name in indices:
        band = image.select(index_name)
        
        stats = band.reduceRegion(
            reducer=ee.Reducer.mean() \
                .combine(ee.Reducer.stdDev(), sharedInputs=True) \
                .combine(ee.Reducer.min(), sharedInputs=True) \
                .combine(ee.Reducer.max(), sharedInputs=True) \
                .combine(ee.Reducer.percentile([10, 25, 75, 90]), sharedInputs=True) \
                .combine(ee.Reducer.median(), sharedInputs=True),
            geometry=geometry,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        )
        
        stats_dict = stats.getInfo()
        
        results[index_name] = {
            "mean": stats_dict.get(f"{index_name}_mean"),
            "std": stats_dict.get(f"{index_name}_stdDev"),
            "min": stats_dict.get(f"{index_name}_min"),
            "max": stats_dict.get(f"{index_name}_max"),
            "median": stats_dict.get(f"{index_name}_median"),
            "percentile_10": stats_dict.get(f"{index_name}_p10"),
            "percentile_25": stats_dict.get(f"{index_name}_p25"),
            "percentile_75": stats_dict.get(f"{index_name}_p75"),
            "percentile_90": stats_dict.get(f"{index_name}_p90"),
        }
    
    return results


def get_index_definition(index_name: str) -> Optional[Dict]:
    """Get documentation for a vegetation index."""
    return INDEX_DEFINITIONS.get(index_name)


def get_all_index_definitions() -> Dict[str, Dict]:
    """Get documentation for all vegetation indices."""
    return INDEX_DEFINITIONS.copy()
