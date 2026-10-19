"""Unit tests for S8 (User Stage Dropdown & API) and S2 (Coarse Cadence Duration Integrity).

Verifies:
1. Stage change from 'unopened_bud' to 'bloom' on identical forecast changes critical threshold and risk.
2. 'swelling_bud' acts conservatively using the most sensitive stage (-1.7°C) without fake numbers.
3. Expired stage (> 20 days since update) triggers stage_is_stale and uses the most sensitive stage (-1.7°C).
4. PATCH /api/v1/agriculture/frost/orchards/{id}/stage validates against allowed stages (200 on valid, 422 on invalid).
5. Coarse cadence night below threshold never produces zero duration or 'هیچ شب زیر آستانه نیست'.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import uuid
import httpx
import pytest

from app.core.config import settings
from app.db.models.frost import Orchard
from app.main import app
from app.services.agriculture.forecast import FakeForecastProvider
from app.services.agriculture.frost_orchard_service import (
    assess_single_orchard_risk,
    assess_orchards_summary,
)
from app.services.agriculture.frost_risk import (
    calculate_interval_duration_run,
    evaluate_duration_rule_category,
    ForecastTimestep,
)

SAMPLE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [56.000, 30.000],
            [56.010, 30.000],
            [56.010, 30.010],
            [56.000, 30.010],
            [56.000, 30.000],
        ]
    ],
}


@pytest.mark.asyncio
async def test_stage_transition_changes_threshold_and_risk():
    """Verify that changing stage from unopened_bud to bloom changes critical threshold and increases risk."""
    now_utc = datetime.now(timezone.utc)
    provider = FakeForecastProvider(base_tmin_c=-3.0, z_site_m=1250.0)

    # 1. Unopened bud stage (critical temp = -4.0°C)
    orchard_unopened = Orchard(
        id=uuid.uuid4(),
        name="باغ پسته ۱",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=now_utc,
        elevation=1250.0,
        latitude=30.005,
        longitude=56.005,
    )
    report_unopened = await assess_single_orchard_risk(
        orchard=orchard_unopened,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    # 2. Bloom stage (critical temp = -1.7°C)
    orchard_bloom = Orchard(
        id=uuid.uuid4(),
        name="باغ پسته ۱",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="bloom",
        current_stage="bloom",
        stage_updated_at=now_utc,
        elevation=1250.0,
        latitude=30.005,
        longitude=56.005,
    )
    report_bloom = await assess_single_orchard_risk(
        orchard=orchard_bloom,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    # Thresholds must differ
    assert report_unopened.critical_temperature_c == -4.0
    assert report_bloom.critical_temperature_c == -1.7

    # At -3.0°C base temp, bloom must be in lethal/critical damage range, unopened_bud is safer
    assert report_bloom.critical_temperature_c > report_unopened.critical_temperature_c
    assert report_bloom.worst_night is not None
    assert report_unopened.worst_night is not None
    assert report_bloom.worst_night["risk_index"] > report_unopened.worst_night["risk_index"]


@pytest.mark.asyncio
async def test_swelling_bud_acts_conservatively_with_most_sensitive_stage():
    """Verify swelling_bud has no sourced threshold and engine acts conservatively with most sensitive stage (-1.7°C)."""
    now_utc = datetime.now(timezone.utc)
    provider = FakeForecastProvider(base_tmin_c=0.0, z_site_m=1250.0)

    orchard_swelling = Orchard(
        id=uuid.uuid4(),
        name="باغ جوانه متورم",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="swelling_bud",
        current_stage="swelling_bud",
        stage_updated_at=now_utc,
        elevation=1250.0,
        latitude=30.005,
        longitude=56.005,
    )
    report = await assess_single_orchard_risk(
        orchard=orchard_swelling,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    # Must resolve conservatively to most sensitive stage in published_v1 (-1.7°C)
    assert report.critical_temperature_c == -1.7


@pytest.mark.asyncio
async def test_stale_stage_acts_conservatively_with_most_sensitive_stage():
    """Verify stage older than 20 days is marked stale and uses most sensitive stage (-1.7°C) per R4/S8."""
    stale_date = datetime.now(timezone.utc) - timedelta(days=25)
    provider = FakeForecastProvider(base_tmin_c=0.0, z_site_m=1250.0)

    orchard_stale = Orchard(
        id=uuid.uuid4(),
        name="باغ منقضی",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",  # normally -4.0°C, but stale (>20 days)
        stage_updated_at=stale_date,
        elevation=1250.0,
        latitude=30.005,
        longitude=56.005,
    )
    report = await assess_single_orchard_risk(
        orchard=orchard_stale,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    assert report.stage_is_stale is True
    # Must use most sensitive stage (-1.7°C) instead of unopened_bud (-4.0°C)
    assert report.critical_temperature_c == -1.7


@pytest.mark.asyncio
async def test_patch_stage_api_endpoint_valid_and_invalid():
    """Verify PATCH /api/v1/agriculture/frost/orchards/{id}/stage endpoint (200 on valid, 422 on invalid, 404 on missing)."""
    from app.api.v1.agriculture import patch_orchard_stage_endpoint
    from app.core.exceptions import AppException
    from unittest.mock import MagicMock

    orchard_id = uuid.uuid4()
    mock_orchard = Orchard(
        id=orchard_id,
        name="باغ آزمون PATCH مرحله",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        elevation=1250.0,
    )

    class MockDbSession:
        async def execute(self, stmt):
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = mock_orchard
            return mock_res

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    mock_db = MockDbSession()

    # 1. PATCH with valid stage 'bloom'
    res_valid = await patch_orchard_stage_endpoint(
        orchard_id=orchard_id,
        stage_in={"current_stage": "bloom"},
        db=mock_db,
        _=True,
    )
    assert res_valid["current_stage"] == "bloom"
    assert res_valid["stage_updated_at"] is not None

    # 2. PATCH with invalid stage -> raises AppException 422
    with pytest.raises(AppException) as exc_info:
        await patch_orchard_stage_endpoint(
            orchard_id=orchard_id,
            stage_in={"current_stage": "invalid_fake_stage"},
            db=mock_db,
            _=True,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "ERR_INVALID_STAGE"

    # 3. PATCH missing orchard -> raises AppException 404
    class MockDbEmpty:
        async def execute(self, stmt):
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = None
            return mock_res

    with pytest.raises(AppException) as exc_missing:
        await patch_orchard_stage_endpoint(
            orchard_id=uuid.uuid4(),
            stage_in={"current_stage": "bloom"},
            db=MockDbEmpty(),
            _=True,
        )
    assert exc_missing.value.status_code == 404



def test_coarse_cadence_night_below_threshold_never_returns_zero_nights():
    """Verify that when step spacing > 1.5h and temperature <= threshold, duration is not zeroed out per S2."""
    now_utc = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
    steps = [
        ForecastTimestep(
            timestamp_utc=(now_utc + timedelta(hours=i * 3)).isoformat(),
            lead_hours=float(i * 3),
            temperature_2m_c=-5.2,
            temperature_2m_c_raw=-5.2,
            elevation_delta_m=0.0,
            elevation_correction_c=0.0,
            elevation_uncertainty_c=0.5,
            lead_time_uncertainty_c=1.0,
            total_uncertainty_c=1.1,
            lower_bound_c=-6.3,
            upper_bound_c=-4.1,
            temperature_min_c=-6.3,
            temperature_max_c=-4.1,
            is_interpolated=False,
            relative_humidity_percent=45.0,
            wind_speed_10m_mps=1.5,
            wind_direction_10m_deg=180.0,
            u_wind_10m_mps=0.0,
            v_wind_10m_mps=-1.5,
            total_cloud_cover_percent=10.0,
            dewpoint_2m_c=-15.0,
        )
        for i in range(4)
    ]

    res = calculate_interval_duration_run(
        steps=steps,
        reference_temp_c=-4.0,
        cooling_bump_c=0.0,
    )
    total_h, longest_h, start_loc, end_loc, is_resolvable = res

    # Under S2:
    # 1. is_resolvable is False (3-hourly cadence > 1.5h)
    assert is_resolvable is False
    # 2. Total hours is NOT 0.0 (4 steps * 3 hours = 12.0 hours)
    assert total_h == 12.0
    assert longest_h == 12.0
    # 3. Cadence label is 'تفکیک ۳ ساعته'
    assert res.cadence_label_fa == "تفکیک ۳ ساعته"
    assert start_loc is not None
    assert end_loc is not None
