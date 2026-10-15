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


def test_earth_engine_outage_returns_503_and_unified_envelope():
    """Verify that an Earth Engine failure returns HTTP 503 and the unified error envelope."""
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    valid_payload = {
        "geometry": {"type": "Point", "coordinates": [53.688, 32.4279]},
        "start_date": "2025-05-01",
        "end_date": "2025-05-15",
        "domains": ["vegetation"],
    }
    with patch("app.utils.geometry.create_ee_geometry", return_value=MagicMock()), patch(
        "app.services.agriculture.executor.execute_metrics",
        side_effect=RuntimeError("Earth Engine computational error: User memory limit exceeded"),
    ):
        resp = client.post("/api/v1/agriculture/analysis", json=valid_payload)
        assert resp.status_code == 503
        data = resp.json()
        assert data["code"] == "ERR_GEE_UNAVAILABLE"
        assert data["reason"] == "Earth Engine service failed to process satellite imagery"
        assert data["status_code"] == 503
        # Assert raw runtime error text is completely shielded
        assert "User memory limit exceeded" not in resp.text


def test_tile_rate_limiter_spoofing_protection():
    """Verify that untrusted client peers cannot spoof X-Forwarded-For to bypass rate limits."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.v1.agriculture import _tile_ip_requests, _MAX_TILE_REQUESTS_PER_MINUTE
    import time

    client = TestClient(app, raise_server_exceptions=False)

    # Clean rate limit history
    _tile_ip_requests.clear()

    # When client connects from untrusted socket peer, X-Forwarded-For is ignored
    # TestClient default peer is "testclient" (which is NOT in TRUSTED_PROXIES)
    spoofed_ip_1 = "198.51.100.99"
    spoofed_ip_2 = "198.51.100.100"

    # Fill rate limit under the testclient socket peer (ignoring spoofed_ip_1)
    for _ in range(_MAX_TILE_REQUESTS_PER_MINUTE):
        client.get(
            "/api/v1/agriculture/tiles/dummy_token/10/500/500.png",
            headers={"x-forwarded-for": spoofed_ip_1},
        )

    # Next request with a DIFFERENT spoofed IP should STILL be blocked because peer is untrusted
    blocked_resp = client.get(
        "/api/v1/agriculture/tiles/dummy_token/10/500/500.png",
        headers={"x-forwarded-for": spoofed_ip_2},
    )
    assert blocked_resp.status_code == 429
    assert blocked_resp.json()["code"] == "ERR_TILE_RATE_LIMIT"

    # Reset
    _tile_ip_requests.clear()


def test_tile_request_token_masked_in_access_logs(caplog):
    """Verify that layer tokens in tile URLs are masked in logs and never exposed."""
    import logging
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.logging import TileTokenMaskingFilter

    # Attach filter to root logger or uvicorn
    logger = logging.getLogger("uvicorn.access")
    logger.setLevel(logging.INFO)
    token_filter = TileTokenMaskingFilter()
    logger.addFilter(token_filter)

    secret_token = "SUPER_SECRET_HMAC_TOKEN_XYZ_12345"
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.INFO):
        client.get(f"/api/v1/agriculture/tiles/{secret_token}/10/500/500.png")

    # The filter must mask the token
    test_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f'GET /api/v1/agriculture/tiles/{secret_token}/10/500/500.png HTTP/1.1 403',
        args=(),
        exc_info=None,
    )
    token_filter.filter(test_record)
    assert secret_token not in test_record.msg
    assert "/tiles/***MASKED***/10/500/500.png" in test_record.msg

