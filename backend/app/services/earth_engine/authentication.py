"""Google Earth Engine authentication service.

All Earth Engine credentials live **server-side only**. This module:

- validates the environment configuration (``EE_PROJECT_ID``,
  ``EE_SERVICE_ACCOUNT``, ``EE_PRIVATE_KEY_FILE``),
- initializes the official ``earthengine-api`` Python client using
  service-account credentials (production) or locally stored developer
  credentials (``earthengine authenticate``),
- exposes a live health check consumed by
  ``GET /api/v1/health/earth-engine``.

Nothing in this module ever returns key material, access tokens, OAuth
tokens, or the service-account credential JSON. Error messages returned to
the API layer are sanitized and only describe *which* environment setting
is missing or which failure class occurred.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ee

from app.core.config import settings
from app.core.exceptions import EarthEngineAuthError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Public health payload codes (safe, non-secret).
CODE_NOT_CONFIGURED = "not_configured"
CODE_INVALID_CONFIGURATION = "invalid_configuration"
CODE_AUTH_FAILED = "auth_failed"
CODE_NOT_ENABLED = "not_enabled"
CODE_NOT_REGISTERED = "not_registered"
CODE_PERMISSION_DENIED = "permission_denied"
CODE_CONNECTION_FAILED = "connection_failed"

_ee_initialized = False

# Fields every Google service-account JSON key must contain.
_REQUIRED_KEY_FIELDS = ("type", "project_id", "client_email", "private_key")


def _service_account_configured() -> bool:
    """True when a service account email and a key file are both configured."""
    return bool(settings.EE_SERVICE_ACCOUNT and settings.EE_PRIVATE_KEY_FILE)


def _key_file() -> Optional[Path]:
    """Configured service-account key file path, or None."""
    if not settings.EE_PRIVATE_KEY_FILE:
        return None
    return Path(settings.EE_PRIVATE_KEY_FILE)


def _has_default_credentials() -> bool:
    """True when developer/ADC credentials exist on the server.

    Checks for a token stored by ``earthengine authenticate`` or a
    ``GOOGLE_APPLICATION_CREDENTIALS`` file. Only existence is checked —
    contents are never read here.
    """
    token_file = Path.home() / ".config" / "earthengine" / "credentials"
    if token_file.exists():
        return True
    adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if adc_path and Path(adc_path).exists():
        return True
    return False


def configuration_problems() -> List[str]:
    """Human-readable Earth Engine configuration problems.

    Safe for logs and API responses: mentions environment variable names and
    file paths only — never key material or tokens.

    Missing service-account variables are *not* reported when the developer
    fallback (``earthengine authenticate`` / ADC) may still work; in that
    case a missing credential is reported by the failed initialization
    attempt instead.
    """
    problems: List[str] = []

    if not settings.EE_PROJECT_ID:
        problems.append(
            "EE_PROJECT_ID is not set — required: a Google Cloud project ID "
            "that is registered for Earth Engine."
        )

    sa_set = bool(settings.EE_SERVICE_ACCOUNT)
    key_set = bool(settings.EE_PRIVATE_KEY_FILE)

    if sa_set and not key_set:
        problems.append(
            "EE_SERVICE_ACCOUNT is set but EE_PRIVATE_KEY_FILE is missing."
        )
    elif key_set and not sa_set:
        problems.append(
            "EE_PRIVATE_KEY_FILE is set but EE_SERVICE_ACCOUNT is missing."
        )
    elif sa_set and key_set:
        key_path = _key_file()
        if key_path is None:
            problems.append("EE_PRIVATE_KEY_FILE is not a valid path.")
        elif not key_path.exists():
            problems.append(
                f"EE_PRIVATE_KEY_FILE does not exist: {settings.EE_PRIVATE_KEY_FILE}"
            )
        elif not key_path.is_file():
            problems.append(
                f"EE_PRIVATE_KEY_FILE is not a regular file: {settings.EE_PRIVATE_KEY_FILE}"
            )

    return problems


def _now_iso() -> str:
    """Current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _classify_error(exc: Exception) -> Tuple[str, str]:
    """Map an Earth Engine exception to a (code, safe message) pair.

    Messages are generic and never echo the raw exception, which can embed
    URLs, request bodies or credential fragments.
    """
    text = str(exc)
    lowered = text.lower()

    if "invalid_grant" in lowered or "token_endpoint" in lowered or "authentication failure" in lowered:
        return CODE_AUTH_FAILED, (
            "Earth Engine rejected the service-account credentials. Verify that "
            "EE_SERVICE_ACCOUNT matches the client_email in the key file, the "
            "private key is valid, and the server clock is synchronized."
        )

    if "has not been used" in lowered or "not been used" in lowered:
        return CODE_NOT_ENABLED, (
            "The Earth Engine API is not enabled for this Cloud project. Enable "
            "'Google Earth Engine API' (APIs & Services > Library) in the Google "
            "Cloud Console, then retry."
        )

    if "not authenticated" in lowered or "earthengine authenticate" in lowered:
        return CODE_AUTH_FAILED, (
            "No Earth Engine credentials were found on the server. Configure "
            "EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY_FILE, or run "
            "`earthengine authenticate` for local development."
        )

    if "default credentials" in lowered or "could not automatically determine" in lowered:
        return CODE_AUTH_FAILED, (
            "Earth Engine default credentials could not be resolved on the server. "
            "Configure EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY_FILE, or set "
            "GOOGLE_APPLICATION_CREDENTIALS."
        )

    if "does not have permission" in lowered or "permission denied" in lowered:
        return CODE_PERMISSION_DENIED, (
            "The service account does not have permission to use Earth Engine. "
            "Grant it at least the 'Earth Engine Resource Viewer' IAM role "
            "(roles/earthengine.viewer) on the Cloud project."
        )

    if "register" in lowered and "project" in lowered:
        return CODE_NOT_REGISTERED, (
            "This Cloud project is not registered for Earth Engine. Register it "
            "at https://code.earthengine.google.com/register, then retry."
        )

    if "does not exist" in lowered and "project" in lowered:
        return CODE_NOT_REGISTERED, (
            "The configured Earth Engine project was not found. Verify "
            "EE_PROJECT_ID and make sure the project is registered for Earth "
            "Engine at https://code.earthengine.google.com/register."
        )

    if "forbidden" in lowered or "401" in text or "403" in text:
        return CODE_PERMISSION_DENIED, (
            "Earth Engine denied the request (forbidden). Check that the project "
            "is registered for Earth Engine and the service account has the "
            "'Earth Engine Resource Viewer' IAM role."
        )

    return CODE_CONNECTION_FAILED, (
        "Earth Engine initialization failed on the server. See the backend logs "
        "for the underlying error."
    )


def initialize_earth_engine() -> None:
    """Initialize the Earth Engine client once per process.

    Raises:
        EarthEngineAuthError: With a sanitized message if configuration is
            incomplete or initialization fails.
    """
    global _ee_initialized

    if _ee_initialized:
        return

    problems = configuration_problems()
    if problems:
        all_missing = (
            not settings.EE_PROJECT_ID
            and not settings.EE_SERVICE_ACCOUNT
            and not settings.EE_PRIVATE_KEY_FILE
        )
        code = CODE_NOT_CONFIGURED if all_missing else CODE_INVALID_CONFIGURATION
        raise EarthEngineAuthError(
            message=f"Earth Engine is not configured. {problems[0]}",
            detail={"code": code, "problems": problems},
        )

    try:
        if _service_account_configured():
            _initialize_service_account()
        else:
            _initialize_default_credentials()
    except EarthEngineAuthError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalized below
        _reset_client()
        code, message = _classify_error(exc)
        logger.error("Earth Engine initialization failed: %s", exc)
        raise EarthEngineAuthError(message=message, detail={"code": code}) from exc

    _ee_initialized = True
    logger.info(
        "Earth Engine initialized (project=%s, auth=%s)",
        settings.EE_PROJECT_ID,
        "service_account" if _service_account_configured() else "developer_credentials",
    )


def _initialize_service_account() -> None:
    """Initialize with EE_SERVICE_ACCOUNT + EE_PRIVATE_KEY_FILE (production)."""
    key_path = _key_file()
    service_account = settings.EE_SERVICE_ACCOUNT
    project_id = settings.EE_PROJECT_ID

    if key_path is None or not key_path.exists():
        raise EarthEngineAuthError(
            message=f"EE_PRIVATE_KEY_FILE does not exist: {settings.EE_PRIVATE_KEY_FILE}",
            detail={"code": CODE_INVALID_CONFIGURATION},
        )

    # Parse the key file up front to fail fast on malformed files. Contents are
    # validated but never logged or returned.
    try:
        with open(key_path, "r", encoding="utf-8") as key_handle:
            key_data = json.load(key_handle)
    except json.JSONDecodeError:
        raise EarthEngineAuthError(
            message=f"EE_PRIVATE_KEY_FILE is not valid JSON: {settings.EE_PRIVATE_KEY_FILE}",
            detail={"code": CODE_INVALID_CONFIGURATION},
        ) from None
    except OSError as exc:
        raise EarthEngineAuthError(
            message=f"EE_PRIVATE_KEY_FILE could not be read: {settings.EE_PRIVATE_KEY_FILE}",
            detail={"code": CODE_INVALID_CONFIGURATION},
        ) from exc

    missing_fields = [
        field for field in _REQUIRED_KEY_FIELDS if field not in key_data
    ]
    if missing_fields:
        raise EarthEngineAuthError(
            message=(
                f"The service-account key file is missing required fields: "
                f"{', '.join(missing_fields)}"
            ),
            detail={"code": CODE_INVALID_CONFIGURATION},
        )

    credentials = ee.ServiceAccountCredentials(
        service_account, key_file=str(key_path)
    )
    ee.Initialize(credentials, project=project_id)


def _initialize_default_credentials() -> None:
    """Initialize with developer credentials (``earthengine authenticate``/ADC).

    Development convenience only. Service-account credentials are the
    supported production path.
    """
    if not _has_default_credentials():
        raise EarthEngineAuthError(
            message=(
                "No Earth Engine credentials found on the server. Configure "
                "EE_SERVICE_ACCOUNT and EE_PRIVATE_KEY_FILE, or run "
                "`earthengine authenticate` for local development."
            ),
            detail={"code": CODE_INVALID_CONFIGURATION},
        )
    ee.Initialize(project=settings.EE_PROJECT_ID)


def _reset_client() -> None:
    """Reset the ee client so a later call can retry initialization."""
    try:
        ee.Reset()
    except Exception:  # noqa: BLE001 - reset is best-effort
        pass


def verify_connection() -> None:
    """Make a real authenticated Earth Engine request.

    Runs a trivial server-side computation so the health check reflects an
    actual authenticated round trip, not just local state.

    Raises:
        EarthEngineAuthError: If the authenticated request fails.
    """
    try:
        ee.Number(1).getInfo()
    except Exception as exc:  # noqa: BLE001 - normalized below
        code, message = _classify_error(exc)
        logger.error("Earth Engine connection check failed: %s", exc)
        raise EarthEngineAuthError(message=message, detail={"code": code}) from exc


def get_earth_engine_health() -> Dict[str, Any]:
    """Public Earth Engine health payload (never contains credentials).

    Connected example::

        {"status": "connected", "project": "...", "earth_engine": true}

    Error example::

        {"status": "error", "earth_engine": false, "message": "..."}
    """
    problems = configuration_problems()
    if problems:
        all_missing = (
            not settings.EE_PROJECT_ID
            and not settings.EE_SERVICE_ACCOUNT
            and not settings.EE_PRIVATE_KEY_FILE
        )
        code = CODE_NOT_CONFIGURED if all_missing else CODE_INVALID_CONFIGURATION
        return {
            "status": "error",
            "earth_engine": False,
            "authenticated": False,
            "code": code,
            "message": f"Earth Engine is not configured. {problems[0]}",
            "checked_at": _now_iso(),
        }

    try:
        initialize_earth_engine()
        verify_connection()
    except EarthEngineAuthError as exc:
        return {
            "status": "error",
            "earth_engine": False,
            "authenticated": False,
            "code": exc.detail.get("code", CODE_CONNECTION_FAILED),
            "message": exc.message,
            "checked_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001 - never leak internals
        logger.error("Unexpected Earth Engine health check error: %s", exc)
        return {
            "status": "error",
            "earth_engine": False,
            "authenticated": False,
            "code": CODE_CONNECTION_FAILED,
            "message": "Earth Engine health check failed unexpectedly — see backend logs.",
            "checked_at": _now_iso(),
        }

    return {
        "status": "connected",
        "earth_engine": True,
        "authenticated": True,
        "project": settings.EE_PROJECT_ID,
        "checked_at": _now_iso(),
    }


def log_earth_engine_startup_status() -> None:
    """Log a clear Earth Engine status line at application startup.

    Missing configuration is logged as warnings (the rest of the platform can
    still start); a configured-but-failing Earth Engine is logged as an error.
    """
    problems = configuration_problems()
    if problems:
        for problem in problems:
            logger.warning("Earth Engine BLOCKED — %s", problem)
        return

    try:
        initialize_earth_engine()
    except EarthEngineAuthError as exc:
        logger.error(
            "Earth Engine BLOCKED — initialization failed at startup (%s): %s",
            exc.detail.get("code", CODE_CONNECTION_FAILED),
            exc.message,
        )
    else:
        logger.info("Earth Engine ready — project: %s", settings.EE_PROJECT_ID)
