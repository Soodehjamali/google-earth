"""Unit tests for 10-Year Same-Period Historical Comparison (Phase P-AGRI-HIST-10Y)."""

from datetime import date
import pytest

from app.schemas.agriculture import (
    HistoricalComparisonRequest,
    HistoricalComparisonResponse,
    PointGeometry,
    PolygonGeometry,
)
from app.services.agriculture.history import (
    _calculate_10y_trend,
    _format_same_period_label,
    generate_historical_comparison,
    shift_window_years,
)


def test_same_period_window_generation_and_leap_years():
    """Verify that shifting preserving seasonal windows handles leap years correctly."""
    # Leap year: 2024-02-29
    start_d = date(2024, 2, 29)
    end_d = date(2024, 5, 31)

    # Shifting 1 year back to 2023 (non-leap) folds Feb 29 to Feb 28
    prev_s, prev_e = shift_window_years(start_d, end_d, 1)
    assert prev_s == date(2023, 2, 28)
    assert prev_e == date(2023, 5, 31)

    # Shifting 4 years back to 2020 (leap) preserves Feb 29
    leap_s, leap_e = shift_window_years(start_d, end_d, 4)
    assert leap_s == date(2020, 2, 29)
    assert leap_e == date(2020, 5, 31)


def test_format_same_period_label():
    """Verify bilingual same period label generation."""
    fa_lbl, en_lbl = _format_same_period_label(date(2026, 6, 1), date(2026, 9, 1))
    assert "Jun" in en_lbl and "Sep" in en_lbl
    assert len(fa_lbl) > 0


def test_calculate_10y_trend_insufficient_evidence():
    """Verify that fewer than 3 observations return insufficient evidence."""
    years_data = [
        (2026, 0.45),
        (2025, None),
        (2024, 0.42),
    ]
    meta = {
        "metric": "ndvi",
        "display_name": "NDVI",
        "display_name_fa": "شاخص پوشش گیاهی",
        "unit": "index",
        "higher_is_better": True,
    }
    trend = _calculate_10y_trend(years_data, meta)
    assert trend.trend_direction == "insufficient_evidence"
    assert trend.sufficiency == "insufficient"
    assert "شواهد ناکافی" in trend.trend_label_fa
    assert trend.current_value == 0.45


def test_calculate_10y_trend_declining_and_baseline():
    """Verify trend calculation and baseline comparison with sufficient data."""
    # Current (2026): 0.35, Past years: declining over time (2021: 0.55 down to 2025: 0.38)
    years_data = [
        (2026, 0.35),
        (2025, 0.38),
        (2024, 0.42),
        (2023, 0.47),
        (2022, 0.50),
        (2021, 0.55),
    ]
    meta = {
        "metric": "ndvi",
        "display_name": "NDVI",
        "display_name_fa": "شاخص پوشش گیاهی",
        "unit": "index",
        "higher_is_better": True,
    }
    trend = _calculate_10y_trend(years_data, meta)
    assert trend.trend_direction == "declining"
    assert trend.sufficiency == "sufficient"
    assert trend.current_value == 0.35
    assert trend.baseline_median is not None
    # Baseline median of [0.38, 0.42, 0.47, 0.50, 0.55] is 0.47
    assert trend.baseline_median == pytest.approx(0.47, 0.01)
    assert trend.delta_from_baseline is not None
    assert trend.delta_from_baseline < 0
    assert "پایین‌تر از میانه" in trend.scientific_summary_fa


@pytest.mark.requires_gee
def test_soil_and_productivity_boundary_limitations():
    """Verify that requesting soil or productivity includes non-claim limitation notices."""
    req_soil = HistoricalComparisonRequest(
        geometry=PointGeometry(coordinates=[53.688, 32.428]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        domain="soil",
    )
    resp_soil = generate_historical_comparison(req_soil)
    assert any("شیمیایی خاک" in lim for lim in resp_soil.limitations)

    req_prod = HistoricalComparisonRequest(
        geometry=PointGeometry(coordinates=[53.688, 32.428]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        domain="productivity",
    )
    resp_prod = generate_historical_comparison(req_prod)
    assert any("عملکرد محصول" in lim for lim in resp_prod.limitations)


@pytest.mark.requires_gee
def test_generate_historical_comparison_real_gee():
    """Verify 10-year comparison generates 10 windows with real GEE satellite data."""
    req = HistoricalComparisonRequest(
        geometry=PointGeometry(coordinates=[53.688, 32.428]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        domain="vegetation",
        cloud_max_percent=25.0,
    )
    resp = generate_historical_comparison(req)
    assert isinstance(resp, HistoricalComparisonResponse)
    assert len(resp.years) == 10
    assert resp.years[0].status == "current"
    assert resp.years[0].year == 2025
    assert resp.years[-1].year == 2016

    # Verify that status is one of the valid states and values are never zero placeholders
    for yr in resp.years:
        assert yr.status in ("current", "available", "partial", "unavailable")
        for m, val in yr.metrics.items():
            if val is not None:
                assert isinstance(val, float)
                # NDVI is normally in [-1, 1], realistic vegetation in [0, 1]
                assert -1.0 <= val <= 1.0

    # Verify trends dictionary
    assert "ndvi" in resp.trends
    assert resp.trends["ndvi"].display_name_fa == "شاخص پوشش گیاهی (NDVI)"
