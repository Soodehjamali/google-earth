"""Unit conversion utilities."""

from typing import Optional


def kelvin_to_celsius(kelvin: Optional[float]) -> Optional[float]:
    """Convert Kelvin to Celsius.
    
    Args:
        kelvin: Temperature in Kelvin.
    
    Returns:
        Temperature in Celsius.
    """
    if kelvin is None:
        return None
    return round(kelvin - 273.15, 2)


def meters_to_millimeters(meters: Optional[float]) -> Optional[float]:
    """Convert meters to millimeters (for precipitation).
    
    Args:
        meters: Value in meters.
    
    Returns:
        Value in millimeters.
    """
    if meters is None:
        return None
    return round(meters * 1000, 2)


def sq_meters_to_hectares(sq_meters: Optional[float]) -> Optional[float]:
    """Convert square meters to hectares.
    
    Args:
        sq_meters: Area in square meters.
    
    Returns:
        Area in hectares.
    """
    if sq_meters is None:
        return None
    return round(sq_meters / 10000, 4)


def sq_meters_to_sq_km(sq_meters: Optional[float]) -> Optional[float]:
    """Convert square meters to square kilometers.
    
    Args:
        sq_meters: Area in square meters.
    
    Returns:
        Area in square kilometers.
    """
    if sq_meters is None:
        return None
    return round(sq_meters / 1e6, 6)


def format_area(area_sq_meters: Optional[float]) -> str:
    """Format area for display with appropriate units.
    
    Args:
        area_sq_meters: Area in square meters.
    
    Returns:
        Formatted area string.
    """
    if area_sq_meters is None:
        return "N/A"
    
    hectares = sq_meters_to_hectares(area_sq_meters)
    sq_km = sq_meters_to_sq_km(area_sq_meters)
    
    if hectares >= 1:
        return f"{hectares:.2f} ha"
    elif area_sq_meters >= 10000:
        return f"{hectares:.4f} ha"
    else:
        return f"{area_sq_meters:.0f} m²"


def format_ndvi(value: Optional[float]) -> str:
    """Format NDVI value for display.
    
    Args:
        value: NDVI value.
    
    Returns:
        Formatted NDVI string.
    """
    if value is None:
        return "N/A"
    return f"{value:.3f}"


def ndvi_health_label(value: Optional[float]) -> str:
    """Get health label for NDVI value.
    
    Args:
        value: NDVI value.
    
    Returns:
        Health label string.
    """
    if value is None:
        return "unknown"
    elif value > 0.6:
        return "excellent"
    elif value > 0.4:
        return "good"
    elif value > 0.3:
        return "moderate"
    elif value > 0.2:
        return "poor"
    else:
        return "bare"
