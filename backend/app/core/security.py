"""Security utilities."""

from typing import List

from app.core.config import settings


def get_earth_engine_credentials() -> dict:
    """Get Earth Engine credentials from environment.
    
    Returns:
        Dictionary with EE credentials configuration.
    """
    return {
        "project_id": settings.EE_PROJECT_ID,
        "service_account": settings.EE_SERVICE_ACCOUNT,
        "private_key_file": settings.EE_PRIVATE_KEY_FILE,
    }


def get_cors_origins() -> List[str]:
    """Get allowed CORS origins."""
    return settings.CORS_ORIGINS
