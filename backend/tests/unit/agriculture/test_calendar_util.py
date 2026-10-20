"""Tests for Gregorian to Jalali calendar conversion and Persian night display formatting (Z2)."""

from datetime import date
import pytest
from app.services.agriculture.calendar_util import (
    gregorian_to_jalali,
    format_night_display_fa,
)


def test_gregorian_to_jalali_october_2026_dates():
    """Verify exact correspondence of October 2026 dates with Persian calendar (Mehr 1405).

    2026-10-19 -> 1405-07-27 (۲۷ مهر ۱۴۰۵)
    2026-10-20 -> 1405-07-28 (۲۸ مهر ۱۴۰۵)
    2026-10-21 -> 1405-07-29 (۲۹ مهر ۱۴۰۵)
    2026-10-22 -> 1405-07-30 (۳۰ مهر ۱۴۰۵)
    """
    assert gregorian_to_jalali(date(2026, 10, 19)) == (1405, 7, 27)
    assert gregorian_to_jalali(date(2026, 10, 20)) == (1405, 7, 28)
    assert gregorian_to_jalali(date(2026, 10, 21)) == (1405, 7, 29)
    assert gregorian_to_jalali(date(2026, 10, 22)) == (1405, 7, 30)


def test_format_night_display_fa():
    """Verify night display labels for the 4 forecast nights."""
    assert format_night_display_fa("2026-10-19") == "شب ۲۷ مهر"
    assert format_night_display_fa("2026-10-20") == "شب ۲۸ مهر"
    assert format_night_display_fa("2026-10-21") == "شب ۲۹ مهر"
    assert format_night_display_fa("2026-10-22") == "شب ۳۰ مهر"


def test_format_night_display_fa_edge_cases():
    """Verify fallback and edge case behavior."""
    assert format_night_display_fa(None) == "شب نامشخص"
    assert format_night_display_fa("") == "شب نامشخص"
    assert format_night_display_fa("invalid-date") == "شب invalid-date"
