"""Health check endpoints."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
        "version": "1.0.0",
    }


@router.get("/health/earth-engine")
def earth_engine_health():
    """Live Earth Engine connection status.

    Runs a real authenticated request against Earth Engine when configured.
    Never returns credentials — only status, the project ID and a sanitized
    message.

    Connected example::

        {"status": "connected", "project": "...", "earth_engine": true}

    Error example::

        {"status": "error", "earth_engine": false, "message": "..."}
    """
    from app.services.earth_engine.authentication import get_earth_engine_health

    return get_earth_engine_health()
