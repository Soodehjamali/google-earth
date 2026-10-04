"""Health check endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check():
    """Liveness probe — the process is up and serving requests."""
    return {
        "status": "healthy",
        "environment": settings.APP_ENV,
        "version": "1.0.0",
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness probe — verifies dependencies the API cannot serve without.

    Checks database connectivity with a real round trip. Returns HTTP 503
    when the database is unreachable so orchestrators stop routing traffic
    to this instance. Never returns connection strings or credentials.
    """
    from app.db.session import async_session_factory

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report class only, never details
        logger.error("Readiness check failed — database unreachable: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unreachable",
                "environment": settings.APP_ENV,
            },
        )

    return {
        "status": "ready",
        "database": "connected",
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
