"""Unit tests for Phase 3 Close-out V2: Displayed Critical Temperature equals Engine Applied Threshold."""

import pytest
from app.services.agriculture.frost_orchard_service import (
    assess_single_orchard_risk,
)
from app.services.agriculture.forecast import FakeForecastProvider


@pytest.mark.asyncio
async def test_v2_critical_temp_stale_stage_applies_most_sensitive_threshold():
    """Verify that when stage is stale, critical_temperature_c reported equals the most sensitive stage (-1.7 °C for published_v1)."""
    stale_orchard = {
        "id": "stale-orchard-v2",
        "name": "باغ منقضی تست V2",
        "latitude": 32.315,
        "longitude": 54.020,
        "elevation": 1040.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",  # Normal threshold is -4.0 C in published_v1
        "stage_is_stale": True,
        "stage_updated_at": "2026-08-01T00:00:00Z",  # Over 20 days old
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[54.01, 32.31], [54.03, 32.31], [54.03, 32.33], [54.01, 32.33], [54.01, 32.31]]],
        },
    }

    report = await assess_single_orchard_risk(
        orchard=stale_orchard,
        threshold_set="published_v1",
        forecast_provider=FakeForecastProvider(),
        use_cache=False,
    )

    assert report.stage_is_stale is True
    # Most sensitive stage in published_v1 is bloom (-1.7 C)
    assert report.critical_temperature_c == -1.7, (
        f"Stale stage must apply most sensitive critical temperature -1.7 C, got {report.critical_temperature_c}"
    )

    # Verify that every night's temperature factor and GATE used -1.7 C
    for night in report.nights:
        temp_factor = next((f for f in night.factors if f["id"] == "temperature_duration"), None)
        assert temp_factor is not None
        assert temp_factor["details"]["critical_temperature_c"] == -1.7
        assert "آستانه -1.7 °C" in temp_factor["raw_value"]


@pytest.mark.asyncio
async def test_v2_critical_temp_fresh_stage_applies_stage_threshold():
    """Verify that when stage is fresh, critical_temperature_c reported equals the current stage threshold."""
    fresh_orchard = {
        "id": "fresh-orchard-v2",
        "name": "باغ تازه تست V2",
        "latitude": 32.315,
        "longitude": 54.020,
        "elevation": 1040.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",  # Base threshold is -4.0 C in published_v1
        "stage_is_stale": False,
        "stage_updated_at": "2026-10-18T00:00:00Z",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[54.01, 32.31], [54.03, 32.31], [54.03, 32.33], [54.01, 32.33], [54.01, 32.31]]],
        },
    }

    report = await assess_single_orchard_risk(
        orchard=fresh_orchard,
        threshold_set="published_v1",
        forecast_provider=FakeForecastProvider(),
        use_cache=False,
    )

    assert report.stage_is_stale is False
    assert report.critical_temperature_c == -4.0, (
        f"Fresh unopened_bud stage must apply -4.0 C, got {report.critical_temperature_c}"
    )

    for night in report.nights:
        temp_factor = next((f for f in night.factors if f["id"] == "temperature_duration"), None)
        assert temp_factor is not None
        assert temp_factor["details"]["critical_temperature_c"] == -4.0
        assert "آستانه -4.0 °C" in temp_factor["raw_value"]
