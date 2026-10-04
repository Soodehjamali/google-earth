"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    setup_logging()
    logger.info("Agricultural Intelligence Platform starting (env=%s)", settings.APP_ENV)
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


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle custom application exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions.

    The full traceback goes to the server logs only; clients receive a
    generic message so internals never leak in responses.
    """
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": {},
        },
    )


# API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Agricultural Intelligence Platform API", "health": "/api/v1/health"}
