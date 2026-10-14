"""Custom exception classes with stable error codes and sanitized reasons."""

from typing import Any, Dict, Optional


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 500,
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_INTERNAL_SERVER_ERROR",
        reason: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        self.code = code
        self.reason = reason or message
        super().__init__(self.message)


class ValidationError(AppException):
    """Validation error for coordinates, polygons, dates."""

    def __init__(
        self,
        message: str = "Validation error",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_VALIDATION_FAILED",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            detail=detail,
            code=code,
            reason=reason or "Input parameters failed validation",
        )


class GeometryError(AppException):
    """Invalid geometry error."""

    def __init__(
        self,
        message: str = "Invalid geometry",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_INVALID_GEOMETRY",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            detail=detail,
            code=code,
            reason=reason or "The specified field boundary geometry is invalid",
        )


class DateRangeError(AppException):
    """Invalid date range error."""

    def __init__(
        self,
        message: str = "Invalid date range",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_INVALID_DATE_RANGE",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            detail=detail,
            code=code,
            reason=reason or "The specified observation date range is invalid",
        )


class EarthEngineError(AppException):
    """Earth Engine operation error."""

    def __init__(
        self,
        message: str = "Earth Engine service temporarily unavailable",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_GEE_UNAVAILABLE",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=503,
            detail=detail,
            code=code,
            reason=reason or "Google Earth Engine service is temporarily unavailable",
        )


class EarthEngineAuthError(AppException):
    """Earth Engine authentication error."""

    def __init__(
        self,
        message: str = "Earth Engine authentication failed",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_GEE_AUTH_FAILED",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=503,
            detail=detail,
            code=code,
            reason=reason or "Earth Engine credentials or service authentication failed",
        )


class DatasetError(AppException):
    """Dataset not found or inaccessible."""

    def __init__(
        self,
        message: str = "Dataset not available",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_DATASET_UNAVAILABLE",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=404,
            detail=detail,
            code=code,
            reason=reason or "The requested satellite dataset is currently unavailable",
        )


class EmptyDatasetError(AppException):
    """No data available for the given parameters (expected unavailability)."""

    def __init__(
        self,
        message: str = "No data available",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_INSUFFICIENT_DATA",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=200,
            detail=detail,
            code=code,
            reason=reason or "No valid satellite imagery found for this location and time range",
        )


class AnalysisNotFoundError(AppException):
    """Analysis not found."""

    def __init__(
        self,
        analysis_id: str = "",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_RECORD_NOT_FOUND",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=f"Analysis {analysis_id} not found",
            status_code=404,
            detail=detail,
            code=code,
            reason=reason or "The requested analysis report was not found in history",
        )


class RateLimitError(AppException):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        detail: Optional[Dict[str, Any]] = None,
        code: str = "ERR_RATE_LIMIT_EXCEEDED",
        reason: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            detail=detail,
            code=code,
            reason=reason or "Rate limit exceeded. Please wait before submitting further requests",
        )
