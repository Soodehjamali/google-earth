"""Earth Engine statistics computation for vegetation analysis."""

from typing import Any, Dict, List, Optional

import ee

from app.core.logging import get_logger
from app.services.earth_engine.datasets import (
    get_sentinel2_composite,
    calculate_ndvi,
    calculate_evi,
    calculate_savi,
    calculate_ndwi,
)
from app.services.earth_engine.indices import compute_indices, compute_index_statistics

logger = get_logger(__name__)


def compute_vegetation_analysis(
    geometry: Any,
    start_date: str,
    end_date: str,
    cloud_max_percent: int = 20,
    scale: int = 10,
) -> Dict[str, Any]:
    """Compute full vegetation analysis for a geometry.
    
    Args:
        geometry: Earth Engine geometry.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        cloud_max_percent: Max cloud coverage per scene.
        scale: Analysis resolution in meters.
    
    Returns:
        Dictionary with vegetation statistics and metadata.
    """
    logger.info(f"Computing vegetation analysis: {start_date} to {end_date}")
    
    # Get cloud-free composite
    composite = get_sentinel2_composite(
        geometry=geometry,
        start_date=start_date,
        end_date=end_date,
        cloud_max_percent=cloud_max_percent,
    )
    
    if composite is None:
        return {
            "status": "no_data",
            "message": "No cloud-free imagery available for the given period",
            "data_quality": "insufficient",
        }
    
    # Compute indices
    indices_image = compute_indices(composite, ["NDVI", "EVI", "SAVI", "NDWI"])
    
    # Compute statistics
    stats = compute_index_statistics(
        image=indices_image,
        geometry=geometry,
        indices=["NDVI", "EVI", "SAVI", "NDWI"],
        scale=scale,
    )
    
    # Get image count
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(start_date, end_date)
        .filterBounds(geometry)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_max_percent))
    )
    image_count = collection.size().getInfo()
    
    # Determine data quality
    data_quality = _assess_data_quality(image_count, stats)
    
    # Determine vegetation health
    ndvi_mean = stats.get("NDVI", {}).get("mean")
    overall_health = _assess_vegetation_health(ndvi_mean)
    
    return {
        "status": "completed",
        "data_quality": data_quality,
        "image_count": image_count,
        "date_range": {"start": start_date, "end": end_date},
        "statistics": stats,
        "vegetation_health": overall_health,
        "interpretation": _generate_interpretation(ndvi_mean, overall_health),
    }


def _assess_data_quality(image_count: int, stats: Dict) -> str:
    """Assess data quality based on observations and statistics."""
    if image_count == 0:
        return "insufficient"
    elif image_count < 3:
        return "limited"
    elif image_count < 8:
        return "acceptable"
    else:
        return "good"


def _assess_vegetation_health(ndvi_mean: Optional[float]) -> str:
    """Assess vegetation health based on mean NDVI."""
    if ndvi_mean is None:
        return "unknown"
    elif ndvi_mean > 0.6:
        return "excellent"
    elif ndvi_mean > 0.4:
        return "good"
    elif ndvi_mean > 0.3:
        return "moderate"
    elif ndvi_mean > 0.2:
        return "poor"
    else:
        return "bare"


def _generate_interpretation(ndvi_mean: Optional[float], health: str) -> str:
    """Generate a human-readable interpretation."""
    if ndvi_mean is None:
        return "Insufficient data for vegetation assessment."
    
    interpretations = {
        "excellent": f"Dense, healthy vegetation detected (NDVI={ndvi_mean:.3f}). Field inspection recommended to confirm crop status.",
        "good": f"Good vegetation cover detected (NDVI={ndvi_mean:.3f}). Vegetation appears healthy.",
        "moderate": f"Moderate vegetation cover (NDVI={ndvi_mean:.3f}). Some stress may be present. Field inspection recommended.",
        "poor": f"Low vegetation cover (NDVI={ndvi_mean:.3f}). Stress or early growth stage detected.",
        "bare": f"Minimal vegetation detected (NDVI={ndvi_mean:.3f}). Field may be fallow, harvested, or experiencing severe stress.",
    }
    
    return interpretations.get(health, f"Vegetation assessment: NDVI={ndvi_mean:.3f}")
