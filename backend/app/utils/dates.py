"""Date utility functions."""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.core.exceptions import DateRangeError
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_date_format(date_str: str) -> None:
    """Validate date string format (YYYY-MM-DD).
    
    Args:
        date_str: Date string to validate.
    
    Raises:
        DateRangeError: If format is invalid.
    """
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise DateRangeError(
            message=f"Invalid date format: {date_str}. Expected YYYY-MM-DD",
            detail={"date": date_str},
        )


def validate_date_range(start_date: str, end_date: str) -> None:
    """Validate a date range.
    
    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
    
    Raises:
        DateRangeError: If range is invalid.
    """
    validate_date_format(start_date)
    validate_date_format(end_date)
    
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    if end <= start:
        raise DateRangeError(
            message="End date must be after start date",
            detail={"start_date": start_date, "end_date": end_date},
        )
    
    # Check if dates are too far in the future
    if end > datetime.now() + timedelta(days=30):
        raise DateRangeError(
            message="End date is too far in the future",
            detail={"end_date": end_date, "max_future": "30 days from now"},
        )
    
    # Check Sentinel-2 availability
    sentinel_start = datetime(2017, 3, 28)
    if start < sentinel_start:
        logger.warning(
            f"Start date {start_date} is before Sentinel-2 availability (2017-03-28). "
            "Results may be limited."
        )


def get_default_date_range() -> Tuple[str, str]:
    """Get a default date range (last 3 months).
    
    Returns:
        Tuple of (start_date, end_date).
    """
    end = datetime.now()
    start = end - timedelta(days=90)
    return (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def format_date_for_display(date_str: str) -> str:
    """Format date string for display.
    
    Args:
        date_str: Date string (YYYY-MM-DD).
    
    Returns:
        Formatted date string.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return date_str


def get_monthly_periods(start_date: str, end_date: str) -> list:
    """Generate monthly periods between two dates.
    
    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
    
    Returns:
        List of (month_start, month_end) tuples.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    periods = []
    current = start.replace(day=1)
    
    while current < end:
        # First day of next month
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)
        
        period_end = min(next_month - timedelta(days=1), end)
        periods.append((
            current.strftime("%Y-%m-%d"),
            period_end.strftime("%Y-%m-%d"),
        ))
        
        current = next_month
    
    return periods
