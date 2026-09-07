"""Earth Engine client wrapper."""

from typing import Any, Optional

import ee

from app.services.earth_engine.authentication import initialize_earth_engine
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_ee_client() -> Any:
    """Get an initialized Earth Engine client.
    
    Initializes Earth Engine if not already initialized.
    
    Returns:
        The ee module (initialized).
    """
    initialize_earth_engine()
    return ee


def get_ee_image(
    dataset_id: str,
    start_date: str,
    end_date: str,
    geometry: Any,
    cloud_max_percent: int = 20,
) -> Optional[ee.Image]:
    """Get a cloud-free composite image from an Earth Engine collection.
    
    Args:
        dataset_id: Earth Engine dataset ID.
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
        geometry: Earth Engine geometry.
        cloud_max_percent: Maximum cloud coverage percentage.
    
    Returns:
        Cloud-free composite image or None.
    """
    ee_module = get_ee_client()
    
    logger.info(f"Fetching image: {dataset_id} ({start_date} to {end_date})")
    
    collection = (
        ee_module.ImageCollection(dataset_id)
        .filterDate(start_date, end_date)
        .filterBounds(geometry)
        .filter(ee_module.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_max_percent))
    )
    
    # Get image count
    image_count = collection.size().getInfo()
    logger.info(f"Found {image_count} images")
    
    if image_count == 0:
        return None
    
    # Create median composite
    composite = collection.median()
    
    return composite


def get_collection_info(dataset_id: str) -> dict:
    """Get metadata about an Earth Engine collection."""
    ee_module = get_ee_client()
    
    collection = ee_module.ImageCollection(dataset_id)
    
    # Get basic info
    first_image = collection.first()
    
    return {
        "dataset_id": dataset_id,
        "first_image_date": first_image.date().format("YYYY-MM-dd").getInfo(),
        "band_names": first_image.bandNames().getInfo(),
    }
