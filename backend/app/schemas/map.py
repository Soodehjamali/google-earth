"""Map visualization Pydantic schemas."""

from typing import Dict, List, Optional

from pydantic import BaseModel


class MapLayer(BaseModel):
    """A single map layer configuration."""
    id: str
    name: str
    name_fa: Optional[str] = None  # Persian name
    visible: bool = True
    opacity: float = 1.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    palette: Optional[List[str]] = None
    dataset_id: Optional[str] = None
    band: Optional[str] = None


class MapVisualization(BaseModel):
    """Map visualization configuration for an analysis."""
    analysis_id: str
    center: List[float]  # [lng, lat]
    zoom: float
    layers: List[MapLayer]
    bounds: Optional[List[List[float]]] = None  # [[sw_lng, sw_lat], [ne_lng, ne_lat]]


class MapLegend(BaseModel):
    """Legend for a map layer."""
    layer_id: str
    title: str
    items: List[Dict[str, str]]  # [{"color": "#00ff00", "label": "Healthy"}]
