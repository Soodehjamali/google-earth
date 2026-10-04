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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ee

from app.core.config import settings
from app.core.exceptions import EarthEngineAuthError
from app.core.logging import get_logger

#: Total attempts for initialization when it fails with a transport-class
#: error (SSL EOF, connection reset, timeout): the initial try plus one
#: retry, with a short deterministic backoff. Any other failure class —
#: credential rejection, unregistered project, HTTP refusal — is definitive
#: and fails immediately. There is deliberately no unbounded retry loop.
_INIT_TRANSPORT_MAX_ATTEMPTS = 2
_INIT_BACKOFF_BASE_S = 0.5
_INIT_BACKOFF_CAP_S = 2.0

#: True once the ee client library has been successfully initialized in
#: this process. Declared at module scope so ``initialize_earth_engine``
#: can read it before the first successful assignment.
_ee_initialized: bool = False

#: Fields the Google-auth service-account loader requires in a JSON key
#: file (``google.oauth2.service_account.Credentials.from_service_account_
#: file`` enforces ``client_email`` and ``token_uri``; the signer requires
#: ``private_key``). Checked up front so a malformed key fails with a
#: clear, sanitized message instead of a library traceback.
_REQUIRED_KEY_FIELDS: Tuple[str, ...] = ("private_key", "client_email", "token_uri")

logger = get_logger(__name__)

# Public health payload codes (safe, non-secret).
CODE_NOT_CONFIGURED = "not_configured"
CODE_INVALID_CONFIGURATION = "invalid_configuration"
CODE_AUTH_FAILED = "auth_failed"
CODE_NOT_ENABLED = "not_enabled"
CODE_NOT_REGISTERED = "not_registered"
CODE_PERMISSION_DENIED = "permission_denied"
CODE_CONNECTION_FAILED = "connection_failed"

# Signal strings taken from the exact reproduced failure forms of the
# Phase A1 acceptance audit. "HTML:sentinel-phrase" entries are matched
# against the page *title* of a Google error document, never against the
# whole body: Google's block pages embed ordinary English phrases (for
# example "does not have permission" inside the "your client does not
# have permission to get URL" boilerplate) that previously caused
# network blocks to be misreported as IAM failures.
_ERROR_SIGNALS: Tuple[Tuple[str, str, str], ...] = (
    # -- authentication / credential failures ---------------------------
    ("invalid_grant", "any", CODE_AUTH_FAILED),
    ("invalid jwt", "any", CODE_AUTH_FAILED),
    ("token_endpoint", "any", CODE_AUTH_FAILED),
    ("authentication failure", "any", CODE_AUTH_FAILED),
    # -- Earth Engine API / registration problems -----------------------
    ("earth engine api has not been used", "any", CODE_NOT_ENABLED),
    ("has not been used in project", "any", CODE_NOT_ENABLED),
    ("has not been registered", "any", CODE_NOT_REGISTERED),
    # -- network / egress / DNS / TLS failures --------------------------
    ("max retries exceeded", "any", CODE_CONNECTION_FAILED),
    ("ssl", "any", CODE_CONNECTION_FAILED),
    ("connection", "any", CODE_CONNECTION_FAILED),
    ("timed out", "any", CODE_CONNECTION_FAILED),
    ("timeout", "any", CODE_CONNECTION_FAILED),
    ("name or service not known", "any", CODE_CONNECTION_FAILED),
    ("temporary failure in name resolution", "any", CODE_CONNECTION_FAILED),
    ("nodename nor servname provided", "any", CODE_CONNECTION_FAILED),
    ("getaddrinfo", "any", CODE_CONNECTION_FAILED),
    ("getaddrinfo failed", "any", CODE_CONNECTION_FAILED),
    ("certificate_verify_failed", "any", CODE_CONNECTION_FAILED),
    ("that's an error", "HTML:title", CODE_CONNECTION_FAILED),
    ("that is an error", "HTML:title", CODE_CONNECTION_FAILED),
    ("your client does not have permission", "HTML:title", CODE_CONNECTION_FAILED),
    ("this ip", "HTML:title", CODE_CONNECTION_FAILED),
    ("not appear in google", "HTML:title", CODE_CONNECTION_FAILED),
    # -- IAM / authorization failures (longest first, checked before the
    #    broad "permission" catch-all below) ----------------------------
    ("caller does not have permission", "any", CODE_PERMISSION_DENIED),
    ("service account does not have permission", "any", CODE_PERMISSION_DENIED),
    ("does not have servicemanagement.required", "any", CODE_PERMISSION_DENIED),
    ("earthengine.viewer", "any", CODE_PERMISSION_DENIED),
    ("earthengine.resourceviewer", "any", CODE_PERMISSION_DENIED),
    ("earthengine.resourcewriter", "any", CODE_PERMISSION_DENIED),
    ("permission denied on earthengine", "any", CODE_PERMISSION_DENIED),
    ("permission 'earthengine", "any", CODE_PERMISSION_DENIED),
    ("has not granted", "any", CODE_PERMISSION_DENIED),
    ("iam", "any", CODE_PERMISSION_DENIED),
    ("permission denied", "any", CODE_PERMISSION_DENIED),
)

#: Phrases that appear in plain Google block-page boilerplate. When the
#: matched text carries one of these alongside an "HTML:" signal, the
#: finding is demoted to a network failure rather than an IAM failure.
# Sanitized, user-facing guidance per classification code. Kept in one
# place so the wording stays consistent between the health endpoint and
# every failure path that routes through _classify_error.
_USER_MESSAGES: Dict[str, str] = {
    CODE_AUTH_FAILED: (
        "Earth Engine rejected the service-account credentials. Verify that "
        "EE_SERVICE_ACCOUNT matches the client_email in the key file, the "
        "private key is valid, and the server clock is synchronized. If all "
        "of those hold, the key may have been deleted or replaced in Google "
        "Cloud Console (IAM & Admin > Service Accounts > Keys) — create a "
        "new JSON key and update EE_PRIVATE_KEY_FILE."
    ),
    CODE_NOT_ENABLED: (
        "The Earth Engine API is not enabled for this Cloud project. Enable "
        "'Google Earth Engine API' (APIs & Services > Library) in the Google "
        "Cloud Console, then retry."
    ),
    CODE_NOT_REGISTERED: (
        "This Cloud project is not registered for Earth Engine. Register it "
        "at https://code.earthengine.google.com/register, then retry."
    ),
    CODE_PERMISSION_DENIED: (
        "Earth Engine denied the request. Check that the project is "
        "registered for Earth Engine and the service account has the "
        "'Earth Engine Resource Viewer' IAM role "
        "(roles/earthengine.viewer) on the Cloud project."
    ),
    CODE_CONNECTION_FAILED: (
        "Earth Engine could not be reached from this server. Verify outbound "
        "HTTPS access to earthengine.googleapis.com and oauth2.googleapis.com "
        "(network, proxy, DNS, and TLS), then retry."
    ),
}

_HTML_BLOCK_HINTS = (
    "</html>",
    "<!doctype html",
    "<html",
    "<style",
    "error page",
)


def _looks_like_html_document(text: str) -> bool:
    """True when the error text is (or embeds) an HTML document."""
    lowered = text[:4096].lower()
    return any(hint in lowered for hint in _HTML_BLOCK_HINTS)


def _signal_matches(text: str, lowered: str, signal: str, scope: str) -> bool:
    """Whether one signal string matches under its scope rule."""
    if scope == "HTML:title":
        # Only the <title>...</title> region of an embedded document (or
        # a leading plain-text banner before any markup) is searched, so
        # phrases from the page body can never drive classification.
        title_start = lowered.find("<title>")
        title_end = lowered.find("</title>")
        if title_start != -1 and title_end > title_start:
            region = lowered[title_start:title_end]
        else:
            # No markup found at all: treat the first 200 characters as
            # the "banner" region and stop at the first tag-like token.
            region = lowered[:200]
        return signal in region
    return signal in lowered


def _signal_table_match(text: str) -> Optional[str]:
    """Match the audited failure forms against the signal table.

    Returns a classification code, or ``None`` when nothing matched.
    """
    lowered = text.lower()
    is_html = _looks_like_html_document(text)
    for signal, scope, code in _ERROR_SIGNALS:
        if not _signal_matches(text, lowered, signal, scope):
            continue
        # An IAM instruction must never come out of a Google block page:
        # inside HTML, "permission denied"-family signals may only win if
        # they appear as an API-structured denial, not as page boilerplate.
        if (
            is_html
            and code == CODE_PERMISSION_DENIED
            and scope == "any"
        ):
            return CODE_CONNECTION_FAILED
        return code
    return None


def _is_init_transport_error(exc: BaseException) -> bool:
    """True only for transport-class failures during initialization.

    Mirrors the executor's rule: SSL/connection/timeout failures never
    completed a request, so one short retry is reasonable. An HttpError —
    including Google's 403 block page — means the server answered and the
    failure is definitive, so it is never retried. Authentication
    failures are likewise definitive.
    """
    if isinstance(exc, EarthEngineAuthError):
        return False

    import requests.exceptions as _requests_exc

    if isinstance(exc, _requests_exc.HTTPError):
        return False
    if isinstance(
        exc,
        (
            _requests_exc.SSLError,
            _requests_exc.ConnectionError,
            _requests_exc.Timeout,
            _requests_exc.ChunkedEncodingError,
            _requests_exc.RequestException,
            ConnectionError,
            TimeoutError,
        ),
    ):
        return True

    import socket

    if isinstance(exc, (socket.timeout, OSError)):
        return True
    return False


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

    Classification uses reliable signals — structured API error text and
    typed network exceptions — rather than arbitrary substring matches on
    response bodies. Google's block pages (IP-block 403 HTML) embed
    ordinary English phrases such as "does not have permission", which a
    naive match misreports as an IAM failure; the signal table therefore
    scopes HTML-originated signals to the page title and demotes
    permission-sounding phrases found inside an HTML document to network
    failures. Verified in the Phase A1 audit:

    * IP-block 403 HTML → network, never IAM instructions
    * SSL EOF / connection retries → network, never IAM instructions
    * ``invalid_grant`` / "Invalid JWT Signature" → credential failure
    * genuine IAM denials ("Caller does not have permission...") → IAM
    """
    text = str(exc)

    # 1. Signals from the audited failure forms, in table order.
    table_code = _signal_table_match(text)
    if table_code is not None:
        return table_code, _USER_MESSAGES[table_code]

    # 2. Typed network errors from the transport layer, matched on the
    #    exception type rather than on message text at all.
    import requests.exceptions as _requests_exc

    if isinstance(
        exc,
        (
            _requests_exc.RequestException,
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    ):
        return CODE_CONNECTION_FAILED, _USER_MESSAGES[CODE_CONNECTION_FAILED]

    # 3. Plain-text fallbacks for the remaining audited forms. A Google
    #    block page (HTML) is a network-layer refusal regardless of any
    #    status code it carries, so it must never reach the IAM fallback.
    lowered = text.lower()
    if _looks_like_html_document(text):
        return CODE_CONNECTION_FAILED, _USER_MESSAGES[CODE_CONNECTION_FAILED]

    if "forbidden" in lowered or "403" in text or "401" in text:
        return CODE_PERMISSION_DENIED, _USER_MESSAGES[CODE_PERMISSION_DENIED]

    return CODE_CONNECTION_FAILED, _USER_MESSAGES[CODE_CONNECTION_FAILED]


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

    # Bounded transport-only retry: at most one extra attempt, and only
    # when the failure was transport-class (SSL EOF, connection reset,
    # timeout). Configuration, credential and HTTP-refusal failures break
    # out of the loop immediately — retrying them can never help.
    last_transport_exc: Optional[Exception] = None
    for attempt in range(1, _INIT_TRANSPORT_MAX_ATTEMPTS + 1):
        try:
            if _service_account_configured():
                _initialize_service_account()
            else:
                _initialize_default_credentials()
            break
        except EarthEngineAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized below
            if attempt < _INIT_TRANSPORT_MAX_ATTEMPTS and _is_init_transport_error(exc):
                delay = min(
                    _INIT_BACKOFF_CAP_S,
                    _INIT_BACKOFF_BASE_S * (2 ** (attempt - 1)),
                )
                logger.warning(
                    "Earth Engine initialization transport failure (%s) on "
                    "attempt %d/%d, retrying in %.2fs",
                    type(exc).__name__,
                    attempt,
                    _INIT_TRANSPORT_MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
                continue
            last_transport_exc = exc
            break

    if last_transport_exc is not None:
        exc = last_transport_exc
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
