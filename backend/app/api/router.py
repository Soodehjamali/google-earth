"""Main API router."""

from fastapi import APIRouter

from app.api.v1 import (
    health,
    locations,
    analyses,
    vegetation,
    climate,
    soil,
    water,
    landcover,
    stress,
    risk,
    maps,
    timeseries,
    reports,
)

api_router = APIRouter()

# V1 routes
api_router.include_router(health.router, prefix="/v1", tags=["Health"])
api_router.include_router(locations.router, prefix="/v1/locations", tags=["Locations"])
api_router.include_router(analyses.router, prefix="/v1/analyses", tags=["Analyses"])
api_router.include_router(vegetation.router, prefix="/v1/vegetation", tags=["Vegetation"])
api_router.include_router(climate.router, prefix="/v1/analyses", tags=["Climate"])
api_router.include_router(soil.router, prefix="/v1/analyses", tags=["Soil"])
api_router.include_router(water.router, prefix="/v1/analyses", tags=["Water"])
api_router.include_router(landcover.router, prefix="/v1/analyses", tags=["Land Cover"])
api_router.include_router(stress.router, prefix="/v1/analyses", tags=["Stress"])
api_router.include_router(risk.router, prefix="/v1/analyses", tags=["Risk"])
api_router.include_router(maps.router, prefix="/v1/analyses", tags=["Maps"])
api_router.include_router(timeseries.router, prefix="/v1/analyses", tags=["Time Series"])
api_router.include_router(reports.router, prefix="/v1/reports", tags=["Reports"])
