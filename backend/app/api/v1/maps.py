"""Map visualization endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis
from app.schemas.map import MapVisualization, MapLayer, MapLegend

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/maps", response_model=MapVisualization)
async def get_map_visualization(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get map visualization configuration for an analysis.

    Returns Earth Engine visualization parameters that the frontend
    uses to render map layers. No EE credentials are exposed.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if analysis.status != "completed" or not analysis.result_data:
        raise HTTPException(
            status_code=400,
            detail="Analysis not yet complete",
        )

    result_data = analysis.result_data
    stats = result_data.get("statistics", {})

    # Get location geometry for center/bounds
    location_result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    location = analysis.location

    # Calculate center from location
    center_lat = location.centroid_lat or location.latitude or 0
    center_lng = location.centroid_lng or location.longitude or 0

    # Determine zoom based on geometry type
    zoom = 10.0
    if location.geometry_type == "Point":
        zoom = 12.0
    elif location.area_sq_meters and location.area_sq_meters > 1e6:
        zoom = 9.0
    elif location.area_sq_meters and location.area_sq_meters > 1e7:
        zoom = 8.0

    # Build layers
    layers = []

    # RGB Composite layer
    layers.append(MapLayer(
        id="rgb",
        name="True Color (RGB)",
        name_fa="تصویر واقعی",
        visible=True,
        opacity=0.8,
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        band="true_color",
    ))

    # NDVI layer
    ndvi_stats = stats.get("NDVI", {})
    ndvi_mean = ndvi_stats.get("mean")
    layers.append(MapLayer(
        id="ndvi",
        name="NDVI",
        name_fa="شاخص سبزینگی",
        visible=True,
        opacity=0.7,
        min_value=0.0,
        max_value=0.8,
        palette=["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#91cf60", "#1a9850"],
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        band="NDVI",
    ))

    # EVI layer
    layers.append(MapLayer(
        id="evi",
        name="EVI",
        name_fa="شاخص بهبودیافته سبزینگی",
        visible=False,
        opacity=0.7,
        min_value=0.0,
        max_value=0.6,
        palette=["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"],
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        band="EVI",
    ))

    # NDWI layer
    layers.append(MapLayer(
        id="ndwi",
        name="NDWI",
        name_fa="شاخص آب",
        visible=False,
        opacity=0.7,
        min_value=-0.5,
        max_value=0.5,
        palette=["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#01665e"],
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        band="NDWI",
    ))

    return MapVisualization(
        analysis_id=str(analysis_id),
        center=[center_lng, center_lat],
        zoom=zoom,
        layers=layers,
        bounds=None,
    )


@router.get("/{analysis_id}/maps/{layer_id}/legend", response_model=MapLegend)
async def get_map_legend(
    analysis_id: uuid.UUID,
    layer_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get legend for a specific map layer."""
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    legends = {
        "ndvi": MapLegend(
            layer_id="ndvi",
            title="NDVI (Vegetation Health)",
            items=[
                {"color": "#d73027", "label": "Bare soil (0.0–0.1)"},
                {"color": "#fc8d59", "label": "Sparse (0.1–0.2)"},
                {"color": "#fee08b", "label": "Moderate (0.2–0.4)"},
                {"color": "#d9ef8b", "label": "Good (0.4–0.6)"},
                {"color": "#91cf60", "label": "Dense (0.6–0.7)"},
                {"color": "#1a9850", "label": "Very dense (0.7+)"},
            ],
        ),
        "evi": MapLegend(
            layer_id="evi",
            title="EVI (Enhanced Vegetation)",
            items=[
                {"color": "#8c510a", "label": "Bare (≤0.0)"},
                {"color": "#d8b365", "label": "Sparse (0.0–0.2)"},
                {"color": "#f6e8c3", "label": "Moderate (0.2–0.3)"},
                {"color": "#c7eae5", "label": "Good (0.3–0.4)"},
                {"color": "#5ab4ac", "label": "Dense (0.4–0.5)"},
                {"color": "#01665e", "label": "Very dense (0.5+)"},
            ],
        ),
        "ndwi": MapLegend(
            layer_id="ndwi",
            title="NDWI (Water Index)",
            items=[
                {"color": "#8c510a", "label": "Dry (≤-0.3)"},
                {"color": "#d8b365", "label": "Low moisture (-0.3–0.0)"},
                {"color": "#f6e8c3", "label": "Moderate (0.0–0.2)"},
                {"color": "#c7eae5", "label": "Wet (0.2–0.4)"},
                {"color": "#5ab4ac", "label": "Very wet (0.4–0.6)"},
                {"color": "#01665e", "label": "Open water (0.6+)"},
            ],
        ),
        "rgb": MapLegend(
            layer_id="rgb",
            title="True Color Composite",
            items=[
                {"color": "#ffffff", "label": "Clouds"},
                {"color": "#006400", "label": "Vegetation"},
                {"color": "#8B4513", "label": "Soil"},
                {"color": "#000080", "label": "Water"},
            ],
        ),
    }

    legend = legends.get(layer_id)
    if not legend:
        raise HTTPException(status_code=404, detail=f"Legend not found for layer: {layer_id}")

    return legend
