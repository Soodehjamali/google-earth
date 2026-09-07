"""Earth Engine preprocessing utilities."""

from typing import Any, Optional

import ee

from app.core.logging import get_logger

logger = get_logger(__name__)


def apply_cloud_mask_scl(image: ee.Image) -> ee.Image:
    """Apply cloud mask using Scene Classification Layer (SCL).
    
    Masks pixels where SCL is one of:
    - 0: No data
    - 1: Saturated/defective
    - 3: Cloud shadows
    - 8: Cloud (medium probability)
    - 9: Cloud (high probability)
    - 10: Thin cirrus
    
    Args:
        image: Sentinel-2 image with SCL band.
    
    Returns:
        Cloud-masked image.
    """
    scl = image.select("SCL")
    
    mask = (
        scl.neq(0)   # No data
        .And(scl.neq(1))  # Defective
        .And(scl.neq(3))  # Cloud shadows
        .And(scl.neq(8))  # Cloud medium
        .And(scl.neq(9))  # Cloud high
        .And(scl.neq(10)) # Cirrus
    )
    
    return image.updateMask(mask)


def apply_cloud_mask_qa60(image: ee.Image) -> ee.Image:
    """Apply cloud mask using QA60 bitmask.
    
    Masks pixels where:
    - Bit 10: Opaque clouds
    - Bit 11: Cirrus clouds
    
    Note: QA60 cloud polygons stopped being produced after 2022-01-25.
    Use SCL-based masking as primary method.
    
    Args:
        image: Sentinel-2 image with QA60 band.
    
    Returns:
        Cloud-masked image.
    """
    qa60 = image.select("QA60")
    
    # Bit 10 = opaque clouds, Bit 11 = cirrus
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    
    mask = qa60.bitwiseAnd(cloud_bit_mask).eq(0).And(
        qa60.bitwiseAnd(cirrus_bit_mask).eq(0)
    )
    
    return image.updateMask(mask)


def rescale_to_reflectance(image: ee.Image, scale_factor: float = 10000.0) -> ee.Image:
    """Rescale Sentinel-2 pixel values to reflectance (0-1).
    
    Args:
        image: Sentinel-2 image with raw DN values.
        scale_factor: Scale factor (default 10000).
    
    Returns:
        Image with reflectance values.
    """
    return image.divide(scale_factor)


def clip_to_geometry(image: ee.Image, geometry: Any) -> ee.Image:
    """Clip image to geometry.
    
    Args:
        image: Earth Engine image.
        geometry: Earth Engine geometry.
    
    Returns:
        Clipped image.
    """
    return image.clip(geometry)


def calculate_cloud_coverage(
    collection: ee.ImageCollection,
    geometry: Any,
) -> float:
    """Calculate mean cloud coverage for a collection.
    
    Args:
        collection: Sentinel-2 image collection.
        geometry: Area of interest.
    
    Returns:
        Mean cloud coverage percentage.
    """
    mean_cloud = collection.select("CLOUDY_PIXEL_PERCENTAGE").mean()
    return mean_cloud.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=1000,
    ).getInfo().get("CLOUDY_PIXEL_PERCENTAGE", 0)
