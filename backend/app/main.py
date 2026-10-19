"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import AppException
from app.api.router import api_router

logger = get_logger(__name__)


def validate_earth_engine_on_startup() -> None:
    """Validate Earth Engine configuration and report status clearly.

    Runs during startup so operators immediately see whether Earth Engine is
    ready, blocked by missing configuration, or failing to initialize.
    Startup continues regardless — the health endpoint stays available to
    report the live status.
    """
    # Imported lazily so the app can still boot if the EE service has an issue.
    from app.services.earth_engine.authentication import log_earth_engine_startup_status

    log_earth_engine_startup_status()


def validate_production_frost_safety() -> None:
    """Enforce that FakeForecastProvider is never permitted in production environment (X5)."""
    import os
    env = (os.environ.get("ENVIRONMENT") or os.environ.get("APP_ENV") or settings.APP_ENV or "").lower()
    is_prod = settings.is_production or env == "production"
    use_live_env = os.environ.get("FROST_USE_LIVE_GEE")

    if is_prod:
        if use_live_env == "0":
            raise RuntimeError(
                "CRITICAL_PRODUCTION_SAFETY_VIOLATION: FROST_USE_LIVE_GEE=0 or FakeForecastProvider "
                "is strictly forbidden in production environment."
            )
        is_live = (use_live_env == "1") or getattr(settings, "FROST_USE_LIVE_GEE", False) or getattr(settings, "USE_LIVE_GEE", False)
        if not is_live:
            raise RuntimeError(
                "CRITICAL_PRODUCTION_SAFETY_VIOLATION: FROST_USE_LIVE_GEE=0 or FakeForecastProvider "
                "is strictly forbidden in production environment."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    setup_logging()
    logger.info("Agricultural Intelligence Platform starting (env=%s)", settings.APP_ENV)
    validate_production_frost_safety()
    try:
        validate_earth_engine_on_startup()
    except Exception as exc:  # never block startup on EE reporting issues
        logger.error("Earth Engine startup check failed: %s", exc)
    yield
    # Graceful shutdown: release database connections before the process exits.
    from app.db.session import dispose_engine

    await dispose_engine()
    logger.info("Agricultural Intelligence Platform shut down cleanly")


# Interactive API documentation is a development aid; disable it in
# production to reduce the exposed surface area.
_docs_url = "/docs" if not settings.is_production else None
_redoc_url = "/redoc" if not settings.is_production else None
_openapi_url = "/openapi.json" if not settings.is_production else None

app = FastAPI(
    title="Agricultural Intelligence Platform",
    description="Satellite-based agricultural analysis and decision support",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# CORS — explicit origins from configuration; no wildcard methods/headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)


_STATUS_TO_ERROR_CODE = {
    400: "ERR_VALIDATION_FAILED",
    401: "ERR_UNAUTHORIZED",
    403: "ERR_FORBIDDEN",
    404: "ERR_RECORD_NOT_FOUND",
    405: "ERR_METHOD_NOT_ALLOWED",
    422: "ERR_VALIDATION_FAILED",
    429: "ERR_RATE_LIMIT_EXCEEDED",
    502: "ERR_GEE_UNAVAILABLE",
    503: "ERR_GEE_UNAVAILABLE",
    504: "ERR_GEE_TIMEOUT",
}

_STATUS_TO_REASON = {
    400: "Input parameters failed validation",
    401: "Authentication credentials are required or invalid",
    403: "Access to the requested resource is forbidden",
    404: "The requested resource was not found",
    405: "The requested HTTP method is not allowed for this route",
    422: "Request parameter validation failed: invalid or missing parameters",
    429: "Too many requests. Please wait before submitting further requests",
    502: "Upstream satellite service bad gateway",
    503: "Satellite processing service is temporarily unavailable",
    504: "Satellite processing service request timed out",
}


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle custom application exceptions with unified error envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": getattr(exc, "code", "ERR_INTERNAL_SERVER_ERROR"),
            "reason": getattr(exc, "reason", "An error occurred during request processing"),
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with unified envelope, never echoing raw input or models."""
    return JSONResponse(
        status_code=422,
        content={
            "code": "ERR_VALIDATION_FAILED",
            "reason": "Request parameter validation failed: invalid or missing parameters",
            "status_code": 422,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle standard HTTP exceptions with unified error envelope."""
    code = _STATUS_TO_ERROR_CODE.get(exc.status_code, "ERR_INTERNAL_SERVER_ERROR")
    reason = (
        exc.detail
        if isinstance(exc.detail, str) and exc.detail and not any(kw in exc.detail for kw in ("Traceback", "Exception", "Error:"))
        else _STATUS_TO_REASON.get(exc.status_code, "HTTP request failed")
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "reason": reason,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions with unified error envelope.

    The full traceback goes to the server logs only; clients receive a
    stable error code and clean generic reason so internals never leak.
    """
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": "ERR_INTERNAL_SERVER_ERROR",
            "reason": "An unexpected server error occurred during processing",
            "status_code": 500,
        },
    )


# API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Agricultural Intelligence Platform API", "health": "/api/v1/health"}
