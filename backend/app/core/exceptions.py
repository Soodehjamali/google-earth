"""Custom exception classes."""

from typing import Any, Dict, Optional


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 500,
        detail: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)


class ValidationError(AppException):
    """Validation error for coordinates, polygons, dates."""

    def __init__(self, message: str = "Validation error", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=400, detail=detail)


class GeometryError(AppException):
    """Invalid geometry error."""

    def __init__(self, message: str = "Invalid geometry", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=400, detail=detail)


class DateRangeError(AppException):
    """Invalid date range error."""

    def __init__(self, message: str = "Invalid date range", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=400, detail=detail)


class EarthEngineError(AppException):
    """Earth Engine operation error."""

    def __init__(self, message: str = "Earth Engine error", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=503, detail=detail)


class EarthEngineAuthError(AppException):
    """Earth Engine authentication error."""

    def __init__(self, message: str = "Earth Engine authentication failed", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=503, detail=detail)


class DatasetError(AppException):
    """Dataset not found or inaccessible."""

    def __init__(self, message: str = "Dataset not available", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=404, detail=detail)


class EmptyDatasetError(AppException):
    """No data available for the given parameters."""

    def __init__(self, message: str = "No data available", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=204, detail=detail)


class AnalysisNotFoundError(AppException):
    """Analysis not found."""

    def __init__(self, analysis_id: str = "", detail: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Analysis {analysis_id} not found",
            status_code=404,
            detail=detail,
        )


class RateLimitError(AppException):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", detail: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=429, detail=detail)
