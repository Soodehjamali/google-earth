"""Earth Engine reducer utilities for spatial and temporal aggregation."""

from typing import Any, Dict, List, Optional

import ee

from app.core.logging import get_logger

logger = get_logger(__name__)


def reduce_spatial(
    image: ee.Image,
    geometry: ee.Geometry,
    scale: int = 10,
    bands: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Reduce an image spatially over a geometry.
    
    Computes mean, median, min, max, std, and percentiles.
    
    Args:
        image: Earth Engine image.
        geometry: Area of interest.
        scale: Resolution in meters.
        bands: Bands to reduce. If None, reduces all bands.
    
    Returns:
        Dictionary of statistics per band.
    """
    if bands:
        image = image.select(bands)
    
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.min(), sharedInputs=True)
        .combine(ee.Reducer.max(), sharedInputs=True)
        .combine(ee.Reducer.percentile([10, 25, 50, 75, 90]), sharedInputs=True)
    )
    
    stats = image.reduceRegion(
        reducer=reducer,
        geometry=geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    )
    
    return stats.getInfo()


def reduce_temporal(
    collection: ee.ImageCollection,
    geometry: ee.Geometry,
    scale: int = 10,
    temporal_resolution: str = "monthly",
    bands: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Reduce an image collection temporally.
    
    Groups images by time period and computes statistics.
    
    Args:
        collection: Earth Engine image collection.
        geometry: Area of interest.
        scale: Resolution in meters.
        temporal_resolution: "daily", "weekly", "monthly", "seasonal", "yearly".
        bands: Bands to include.
    
    Returns:
        List of time-series data points.
    """
    # Define time filter based on resolution
    if temporal_resolution == "monthly":
        date_format = "YYYY-MM"
    elif temporal_resolution == "yearly":
        date_format = "YYYY"
    elif temporal_resolution == "seasonal":
        date_format = "YYYY-MM"  # Group by month for seasonal
    else:
        date_format = "YYYY-MM-dd"
    
    # Use map to add date band for grouping
    def add_date_band(image):
        date_str = image.date().format(date_format)
        return image.addBands(ee.Image.constant(0).rename("date_band").set("system:time_start", image.date().millis()))
    
    # Reduce each image to statistics
    results = []
    
    def reduce_image(image):
        if bands:
            img = image.select(bands)
        else:
            img = image
        
        stats = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        )
        
        date = ee.Date(image.date()).format(date_format)
        
        return ee.Feature(None, stats.combine({"date": date}))
    
    features = collection.map(reduce_image)
    
    # Convert to list
    result_list = features.getInfo()
    
    # Extract properties
    time_series = []
    for feature in result_list:
        props = feature.get("properties", {})
        entry = {"date": props.get("date", "")}
        for band in (bands or []):
            entry[band] = props.get(band)
        time_series.append(entry)
    
    return time_series
