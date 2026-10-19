"""Unit Tests for Per-Orchard Stage Tracking and Staleness Gating (R4).

Verifies:
1. Orchard record holds current_stage and stage_updated_at.
2. Fresh stage (< 14 days) is honored as valid.
3. Stale stage (> 14 days) is treated as unknown: uses most sensitive configured stage (full_bloom)
   flagged 'مرحله قدیمی/نامشخص'.
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest

from app.db.models.frost import Orchard
from app.services.agriculture.forecast import FakeForecastProvider
from app.services.agriculture.frost_inputs import assemble_orchard_inputs, is_timestamp_stale
from app.services.agriculture.frost_weighted_model import evaluate_weighted_frost_model, load_frost_factor_weights_config


def test_orchard_model_has_stage_columns():
    """Verify Orchard model has current_stage and stage_updated_at fields."""
    now = datetime.now(timezone.utc)
    o = Orchard(
        id=uuid.uuid4(),
        name="باغ پسته رفسنجان",
        geometry={"type": "Point", "coordinates": [55.9, 30.4]},
        latitude=30.4,
        longitude=55.9,
        elevation=1500.0,
        crop="pistachio",
        default_phenology_stage="early_bloom",
        current_stage="opening_bud",
        stage_updated_at=now,
    )
    assert o.current_stage == "opening_bud"
    assert o.stage_updated_at == now


@pytest.mark.asyncio
async def test_fresh_stage_evaluation():
    """Verify that a recently updated stage is treated as valid."""
    now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
    updated_3_days_ago = (now - timedelta(days=3)).isoformat()

    orchard_dict = {
        "id": "orchard_fresh",
        "name": "باغ تازه",
        "latitude": 30.4,
        "longitude": 55.9,
        "elevation": 1200.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",
        "stage_updated_at": updated_3_days_ago,
    }

    inputs = await assemble_orchard_inputs(
        orchard_dict,
        forecast_provider=FakeForecastProvider(),
        use_cache=False,
        now_utc=now,
    )

    stage_factor = inputs.factors["phenological_stage"]
    assert stage_factor.value == "unopened_bud"
    assert stage_factor.is_stale is False
    assert stage_factor.quality_state == "valid"

    # Evaluate model
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=2.0,
        critical_temp_c=-4.0,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    evaluated_stage = next(f for f in res.factors if f.id == "phenological_stage")
    assert evaluated_stage.subscore == 0.30  # unopened_bud
    assert evaluated_stage.is_stale is False
    assert "مرحله قدیمی" not in evaluated_stage.raw_value


@pytest.mark.asyncio
async def test_stale_stage_treated_as_unknown_conservative():
    """Verify that a stage older than 20 days is treated as unknown: uses most sensitive stage flagged 'مرحله قدیمی/نامشخص'."""
    now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
    updated_21_days_ago = (now - timedelta(days=21)).isoformat()

    orchard_dict = {
        "id": "orchard_stale",
        "name": "باغ با مرحله قدیمی",
        "latitude": 30.4,
        "longitude": 55.9,
        "elevation": 1200.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",  # would normally be 0.30
        "stage_updated_at": updated_21_days_ago,
    }

    inputs = await assemble_orchard_inputs(
        orchard_dict,
        forecast_provider=FakeForecastProvider(),
        use_cache=False,
        now_utc=now,
    )

    stage_factor = inputs.factors["phenological_stage"]
    assert stage_factor.is_stale is True

    # Evaluate model
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=2.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    evaluated_stage = next(f for f in res.factors if f.id == "phenological_stage")
    # Subscore must escalate to 1.0 (most sensitive stage) because stage is stale
    assert evaluated_stage.subscore == 1.0
    assert evaluated_stage.is_stale is True
    assert "مرحله قدیمی/نامشخص" in evaluated_stage.raw_value
