"""Unit tests for stable error codes, clean reasons, and expected unavailability handling (Phase 1 Step 3)."""

import pytest
from app.core.exceptions import (
    AppException,
    ValidationError,
    GeometryError,
    DateRangeError,
    EarthEngineError,
    EarthEngineAuthError,
    DatasetError,
    EmptyDatasetError,
    AnalysisNotFoundError,
    RateLimitError,
)


def test_app_exception_stable_codes_and_reasons():
    exc = AppException("Something broke", status_code=500)
    assert exc.code == "ERR_INTERNAL_SERVER_ERROR"
    assert exc.reason == "Something broke"
    assert exc.status_code == 500


def test_validation_error_code():
    exc = ValidationError("Bad coordinates")
    assert exc.code == "ERR_VALIDATION_FAILED"
    assert exc.status_code == 400
    assert "validation" in exc.reason.lower()


def test_geometry_error_code():
    exc = GeometryError("Self-intersecting ring")
    assert exc.code == "ERR_INVALID_GEOMETRY"
    assert exc.status_code == 400
    assert "geometry" in exc.reason.lower()


def test_date_range_error_code():
    exc = DateRangeError("Reversed dates")
    assert exc.code == "ERR_INVALID_DATE_RANGE"
    assert exc.status_code == 400
    assert "date range" in exc.reason.lower()


def test_earth_engine_error_code_and_sanitization():
    raw_socket_error = "ee.EEException: Socket closed after 120000ms"
    exc = EarthEngineError(
        message="Service unavailable",
        detail={"raw": raw_socket_error},
    )
    assert exc.code == "ERR_GEE_UNAVAILABLE"
    assert exc.status_code == 503
    # Reason must be clean, never raw socket dump
    assert "Socket closed" not in exc.reason
    assert "Earth Engine" in exc.reason


def test_earth_engine_auth_error_code():
    exc = EarthEngineAuthError()
    assert exc.code == "ERR_GEE_AUTH_FAILED"
    assert exc.status_code == 503


def test_dataset_error_code():
    exc = DatasetError()
    assert exc.code == "ERR_DATASET_UNAVAILABLE"
    assert exc.status_code == 404


def test_empty_dataset_is_insufficient_data_status():
    """Expected unavailability must be a status / non-fatal result, not an unhandled error."""
    exc = EmptyDatasetError()
    assert exc.code == "ERR_INSUFFICIENT_DATA"
    assert exc.status_code == 200


def test_analysis_not_found_code():
    exc = AnalysisNotFoundError(analysis_id="123e4567-e89b-12d3-a456-426614174000")
    assert exc.code == "ERR_RECORD_NOT_FOUND"
    assert exc.status_code == 404
    assert "123e4567" in exc.message


def test_rate_limit_error_code():
    exc = RateLimitError()
    assert exc.code == "ERR_RATE_LIMIT_EXCEEDED"
    assert exc.status_code == 429


def test_unified_error_envelope_shapes_on_fastapi_app():
    """Verify that every error handler returns the unified {code, reason, status_code} envelope."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)

    # 1. 404 Route Not Found (StarletteHTTPException)
    resp_404 = client.get("/api/v1/nonexistent_route_404")
    assert resp_404.status_code == 404
    data_404 = resp_404.json()
    assert set(data_404.keys()) == {"code", "reason", "status_code"}
    assert data_404["code"] == "ERR_RECORD_NOT_FOUND"
    assert data_404["status_code"] == 404

    # 2. 405 Method Not Allowed (StarletteHTTPException)
    resp_405 = client.delete("/api/v1/health")
    assert resp_405.status_code == 405
    data_405 = resp_405.json()
    assert set(data_405.keys()) == {"code", "reason", "status_code"}
    assert data_405["code"] == "ERR_METHOD_NOT_ALLOWED"
    assert data_405["status_code"] == 405

    # 3. 422 RequestValidationError (never echoes raw input or internal model names)
    resp_422 = client.post("/api/v1/agriculture/analysis", json={"invalid": "payload"})
    assert resp_422.status_code == 422
    data_422 = resp_422.json()
    assert set(data_422.keys()) == {"code", "reason", "status_code"}
    assert data_422["code"] == "ERR_VALIDATION_FAILED"
    assert data_422["status_code"] == 422
    assert "payload" not in str(data_422)  # no user input echoed
    assert "PointGeometry" not in str(data_422)  # no internal model names

