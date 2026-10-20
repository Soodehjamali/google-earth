"""Unit test verifying that effective_tmin_c equals exactly min(hourly corrected temperature) (Z1).

Contract:
For each evaluated local night, night.effective_tmin_c MUST be exactly identical to the
minimum of the hourly corrected temperature series (temperature_2m_c) within that night's window.
"""

from datetime import datetime, timezone
import pytest
from app.db.models.frost import Orchard
from app.services.agriculture.forecast import FakeForecastProvider
from app.services.agriculture.frost_orchard_service import (
    assess_single_orchard_risk,
    aggregate_forecast_by_local_night,
)

ORCHARD_DEFINITIONS = [
    {
        "name": "باغ آزمایشی (مختصات نمونه)",
        "lat": 30.004,
        "lon": 56.004,
        "elevation": 1350.0,
        "crop": "pistachio",
        "stage": "bloom",
        "geom": {"type": "Polygon", "coordinates": [[[56.0, 30.0], [56.01, 30.0], [56.01, 30.01], [56.0, 30.01], [56.0, 30.0]]]},
    },
    {
        "name": "باغ پسته اردکان",
        "lat": 32.31,
        "lon": 54.02,
        "elevation": 1215.0,
        "crop": "pistachio",
        "stage": "bloom",
        "geom": {"type": "Polygon", "coordinates": [[[54.015, 32.305], [54.025, 32.305], [54.025, 32.315], [54.015, 32.315], [54.015, 32.305]]]},
    },
    {
        "name": "باغ مرتفع دماوند",
        "lat": 35.8,
        "lon": 52.0,
        "elevation": 4500.0,
        "crop": "pistachio",
        "stage": "bloom",
        "geom": {"type": "Point", "coordinates": [52.0, 35.8]},
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("orchard_info", ORCHARD_DEFINITIONS)
async def test_effective_tmin_equals_min_hourly_corrected(orchard_info):
    """Verify that effective_tmin_c is mathematically identical to min(hourly corrected temperature)."""
    orchard = Orchard(
        name=orchard_info["name"],
        latitude=orchard_info["lat"],
        longitude=orchard_info["lon"],
        elevation=orchard_info["elevation"],
        crop=orchard_info["crop"],
        current_stage=orchard_info["stage"],
        default_phenology_stage=orchard_info["stage"],
        stage_updated_at=datetime.now(timezone.utc),
        geometry=orchard_info["geom"],
    )

    provider = FakeForecastProvider(base_tmin_c=2.0, z_site_m=orchard_info["elevation"])

    report = await assess_single_orchard_risk(
        orchard=orchard,
        horizon_h=72,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    assert len(report.nights) > 0
    assert len(report.hourly_series) > 0

    # Group the returned hourly series by local night (18:00 to 09:00 local time)
    series_by_night = {}
    from datetime import timedelta
    tz_local = timezone(timedelta(hours=3.5))

    for step in report.hourly_series:
        dt_utc = datetime.fromisoformat(step["timestamp_utc"].replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(tz_local)
        hour = dt_local.hour
        # Night window: 18:00 to 23:59 belongs to today's night; 00:00 to 08:59 belongs to yesterday's night
        if hour >= 18:
            n_key = dt_local.strftime("%Y-%m-%d")
        elif hour < 9:
            n_key = (dt_local - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            continue
        series_by_night.setdefault(n_key, []).append(step)

    for night in report.nights:
        n_key = night.night_date
        steps_in_window = series_by_night.get(n_key, [])
        assert len(steps_in_window) > 0, f"Night {n_key} must have hourly forecast steps"

        min_corrected_in_window = min(s["temperature_2m_c"] for s in steps_in_window)
        # Assert exact identity
        assert night.effective_tmin_c == pytest.approx(min_corrected_in_window, abs=1e-4), (
            f"Orchard '{orchard_info['name']}' night {n_key}: "
            f"effective_tmin_c ({night.effective_tmin_c}) must equal "
            f"min hourly corrected ({min_corrected_in_window})"
        )
