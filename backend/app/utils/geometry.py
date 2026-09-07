"""Geometry utility functions for validation and conversion."""

from typing import Any, Dict, List, Optional, Tuple

import ee

from app.core.exceptions import GeometryError, ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate GPS coordinates.
    
    Args:
        latitude: GPS latitude (-90 to 90).
        longitude: GPS longitude (-180 to 180).
    
    Raises:
        ValidationError: If coordinates are invalid.
    """
    if not (-90 <= latitude <= 90):
        raise ValidationError(
            message=f"Invalid latitude: {latitude}. Must be between -90 and 90.",
            detail={"latitude": latitude},
        )
    if not (-180 <= longitude <= 180):
        raise ValidationError(
            message=f"Invalid longitude: {longitude}. Must be between -180 and 180.",
            detail={"longitude": longitude},
        )


def validate_geometry(geometry: Dict[str, Any]) -> None:
    """Validate a GeoJSON geometry.
    
    Args:
        geometry: GeoJSON geometry dictionary.
    
    Raises:
        GeometryError: If geometry is invalid.
    """
    if not isinstance(geometry, dict):
        raise GeometryError(message="Geometry must be a dictionary")
    
    geom_type = geometry.get("type")
    if geom_type not in ("Point", "Polygon"):
        raise GeometryError(
            message=f"Unsupported geometry type: {geom_type}",
            detail={"supported_types": ["Point", "Polygon"]},
        )
    
    if geom_type == "Point":
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            raise GeometryError(message="Point must have at least 2 coordinates")
        validate_coordinates(coords[1], coords[0])  # [lng, lat]
    
    elif geom_type == "Polygon":
        rings = geometry.get("coordinates", [])
        if not rings or not rings[0]:
            raise GeometryError(message="Polygon must have at least one ring")
        
        ring = rings[0]
        if len(ring) < 4:
            raise GeometryError(
                message="Polygon ring must have at least 4 points",
                detail={"points": len(ring)},
            )
        
        # Check closure
        if ring[0] != ring[-1]:
            raise GeometryError(message="Polygon ring must be closed (first == last point)")
        
        # Validate all coordinates
        for coord in ring:
            if len(coord) >= 2:
                validate_coordinates(coord[1], coord[0])


def calculate_area_sq_meters(geometry: Dict[str, Any]) -> Optional[float]:
    """Calculate area of a polygon in square meters.
    
    Args:
        geometry: GeoJSON geometry.
    
    Returns:
        Area in square meters, or None for points.
    """
    if geometry.get("type") == "Point":
        return None
    
    try:
        ee_geom = create_ee_geometry(geometry)
        area = ee_geom.area().getInfo()
        return area
    except Exception as e:
        logger.warning(f"Could not calculate area: {e}")
        return None


def calculate_centroid(geometry: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Calculate centroid of a geometry.
    
    Args:
        geometry: GeoJSON geometry.
    
    Returns:
        Tuple of (latitude, longitude).
    """
    if geometry.get("type") == "Point":
        coords = geometry.get("coordinates", [])
        if len(coords) >= 2:
            return (coords[1], coords[0])  # [lng, lat] -> (lat, lng)
        return (None, None)
    
    try:
        ee_geom = create_ee_geometry(geometry)
        centroid = ee_geom.centroid().coordinates().getInfo()
        return (centroid[1], centroid[0])  # [lng, lat] -> (lat, lng)
    except Exception as e:
        logger.warning(f"Could not calculate centroid: {e}")
        return (None, None)


def calculate_bounding_box(geometry: Dict[str, Any]) -> Optional[List[List[float]]]:
    """Calculate bounding box of a geometry.
    
    Args:
        geometry: GeoJSON geometry.
    
    Returns:
        Bounding box as [[west, south], [east, north]] or None.
    """
    try:
        ee_geom = create_ee_geometry(geometry)
        bounds = ee_geom.bounds().bounds().coordinates().getInfo()
        coords = bounds[0] if bounds else []
        if len(coords) >= 4:
            # coords is [[sw], [nw], [ne], [se], [sw]]
            lats = [c[1] for c in coords]
            lngs = [c[0] for c in coords]
            return [[min(lngs), min(lats)], [max(lngs), max(lats)]]
        return None
    except Exception as e:
        logger.warning(f"Could not calculate bounding box: {e}")
        return None


def create_ee_geometry(geometry: Dict[str, Any]) -> Any:
    """Convert GeoJSON geometry to Earth Engine geometry.
    
    Args:
        geometry: GeoJSON geometry dictionary.
    
    Returns:
        Earth Engine geometry.
    """
    validate_geometry(geometry)
    
    geom_type = geometry.get("type")
    
    if geom_type == "Point":
        coords = geometry.get("coordinates", [])
        return ee.Geometry.Point(coords)
    
    elif geom_type == "Polygon":
        coords = geometry.get("coordinates", [])
        return ee.Geometry.Polygon(coords)
    
    raise GeometryError(f"Cannot convert geometry type: {geom_type}")
