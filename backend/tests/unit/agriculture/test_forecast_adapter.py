"""Unit tests for ForecastProvider and NOAA/GFS0P25 forecast adapter (Task 3.1)."""

import pytest
from datetime import datetime, timezone

from app.services.agriculture.forecast import (
    ForecastProvider,
    ForecastTimestep,
    ForecastResult,
    FakeForecastProvider,
    NoaaGfsForecastProvider,
    get_lead_time_uncertainty,
    GFS_SPATIAL_RESOLUTION_M,
    NOAA_GFS_DATASET_ID,
)


@pytest.mark.asyncio
async def test_fake_forecast_provider_basic_contract():
    provider = FakeForecastProvider(
        base_tmin_c=2.0,
        base_tmax_c=16.0,
        z_site_m=1300.0,
        z_cell_m=1000.0,
    )
    result = await provider.get_hourly_forecast({"type": "Point", "coordinates": [54.0, 32.0]}, horizon_h=48)

    assert isinstance(result, ForecastResult)
    assert result.source == "deterministic_fake"
    assert result.quality_state == "coarse_context"
    assert result.native_spatial_resolution_m == GFS_SPATIAL_RESOLUTION_M
    assert result.horizon_hours == 48
    assert len(result.series) == 49  # 0 to 48 inclusive

    # Check first timestep
    t0 = result.series[0]
    assert t0.lead_hours == 0.0
    assert t0.elevation_delta_m == 300.0
    # Site is 300m ABOVE cell => colder by 1.95 C (-6.5 C/km * 0.3km)
    assert t0.elevation_correction_c == pytest.approx(-1.95, abs=0.01)
    assert t0.temperature_2m_c == pytest.approx(t0.temperature_2m_c_raw - 1.95, abs=0.01)
    assert t0.is_interpolated is False


@pytest.mark.asyncio
async def test_forecast_elevation_correction_sign():
    """Verify physical sign convention: higher site is colder, lower site is warmer."""
    # Higher site
    high_site = FakeForecastProvider(z_site_m=1500.0, z_cell_m=1200.0)
    res_high = await high_site.get_hourly_forecast(None, horizon_h=1)
    step_high = res_high.series[0]
    assert step_high.elevation_delta_m == 300.0
    assert step_high.elevation_correction_c == pytest.approx(-1.95, abs=0.01)
    assert step_high.temperature_2m_c < step_high.temperature_2m_c_raw

    # Lower site
    low_site = FakeForecastProvider(z_site_m=900.0, z_cell_m=1200.0)
    res_low = await low_site.get_hourly_forecast(None, horizon_h=1)
    step_low = res_low.series[0]
    assert step_low.elevation_delta_m == -300.0
    assert step_low.elevation_correction_c == pytest.approx(1.95, abs=0.01)
    assert step_low.temperature_2m_c > step_low.temperature_2m_c_raw

    # Equal elevation
    flat_site = FakeForecastProvider(z_site_m=1200.0, z_cell_m=1200.0)
    res_flat = await flat_site.get_hourly_forecast(None, horizon_h=1)
    step_flat = res_flat.series[0]
    assert step_flat.elevation_delta_m == 0.0
    assert step_flat.elevation_correction_c == 0.0
    assert step_flat.temperature_2m_c == step_flat.temperature_2m_c_raw


def test_lead_time_uncertainty_lookup():
    assert get_lead_time_uncertainty(0) == 1.0
    assert get_lead_time_uncertainty(12) == 1.0
    assert get_lead_time_uncertainty(24) == 1.0
    assert get_lead_time_uncertainty(36) == 1.5
    assert get_lead_time_uncertainty(48) == 1.5
    assert get_lead_time_uncertainty(60) == 2.0
    assert get_lead_time_uncertainty(72) == 2.0
    assert get_lead_time_uncertainty(100) == 2.5
    assert get_lead_time_uncertainty(120) == 2.5
    assert get_lead_time_uncertainty(150) == 3.5


@pytest.mark.asyncio
async def test_native_vs_interpolated_cadence_disclosure():
    """Verify that >=120h horizons honestly disclose native 3-hourly intervals vs interpolated."""
    provider = FakeForecastProvider(z_site_m=1000.0, z_cell_m=1000.0)
    result = await provider.get_hourly_forecast(None, horizon_h=130)

    assert result.native_temporal_resolution_h == 3

    # Up to 120h, all steps are native
    for step in result.series:
        if step.lead_hours <= 120:
            assert step.is_interpolated is False
        else:
            if step.lead_hours % 3 == 0:
                assert step.is_interpolated is False
            else:
                assert step.is_interpolated is True


@pytest.mark.asyncio
async def test_uncertainty_quadrature_and_bounds():
    """Verify quadrature combination of elevation and lead-time uncertainty."""
    provider = FakeForecastProvider(z_site_m=1300.0, z_cell_m=1000.0)
    result = await provider.get_hourly_forecast(None, horizon_h=24)

    for step in result.series:
        # total_unc = sqrt(elev_unc^2 + lead_unc^2)
        expected_total = pytest.approx(
            (step.elevation_uncertainty_c**2 + step.lead_time_uncertainty_c**2) ** 0.5,
            abs=0.05,
        )
        assert step.lower_bound_c == pytest.approx(step.temperature_2m_c - step.total_uncertainty_c, abs=0.01)
        assert step.upper_bound_c == pytest.approx(step.temperature_2m_c + step.total_uncertainty_c, abs=0.01)
        assert step.temperature_min_c == step.lower_bound_c
        assert step.temperature_max_c == step.upper_bound_c


@pytest.mark.requires_gee
@pytest.mark.asyncio
async def test_live_noaa_gfs_provider():
    """Integration test with live Earth Engine NOAA/GFS0P25."""
    geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [54.015, 32.310],
                [54.025, 32.310],
                [54.025, 32.320],
                [54.015, 32.320],
                [54.015, 32.310],
            ]
        ],
    }
    provider = NoaaGfsForecastProvider()
    result = await provider.get_hourly_forecast(geom, horizon_h=24)

    assert result.source == NOAA_GFS_DATASET_ID
    assert result.quality_state == "coarse_context"
    assert len(result.series) > 0
    assert result.site_elevation_m > 0
    assert result.cell_elevation_m > 0

    first = result.series[0]
    assert -50.0 < first.temperature_2m_c < 60.0
    assert first.total_uncertainty_c > 0.0


def test_fake_forecast_provider_unreachable_in_production(monkeypatch):
    """Verify that FakeForecastProvider cannot be instantiated in production configuration."""
    from app.core.config import settings
    from app.core.exceptions import AppException

    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(AppException) as exc_info:
        FakeForecastProvider()
    assert exc_info.value.code == "ERR_FORBIDDEN"
    assert exc_info.value.status_code == 403

