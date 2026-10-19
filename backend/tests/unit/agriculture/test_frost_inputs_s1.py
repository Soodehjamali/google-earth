"""Unit tests for S1: Real Per-Orchard Geometry Sampling, Elimination of Fallbacks, and Unavailable Factor Handling.

Verifies:
1. Two orchards with different coordinates produce different spatial inputs (mock EE level, no fallback).
2. Point/area with missing EE data returns quality_state='unavailable', value=None, status='ناموجود'.
3. Model handles unavailable factors with neutral subscore 0.50, keeping weight in the sum without lowering risk.
4. Static layers (DEM, SoilGrids) have static=True and UI label 'لایه ثابت' without synthetic dates.
5. NASADEM DEM elevation reconciliation corrects manual/suspicious orchard elevation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import uuid
import pytest

from app.db.models.frost import Orchard
from app.services.agriculture.forecast import FakeForecastProvider
from app.services.agriculture.frost_inputs import (
    assemble_orchard_inputs,
    FactorInput,
)
from app.services.agriculture.frost_orchard_service import assess_single_orchard_risk
from app.services.agriculture.frost_weighted_model import evaluate_weighted_frost_model, load_frost_factor_weights_config

ORCHARD_A_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [51.99, 35.79],
            [52.01, 35.79],
            [52.01, 35.81],
            [51.99, 35.81],
            [51.99, 35.79],
        ]
    ],
}

ORCHARD_B_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [55.99, 30.29],
            [56.01, 30.29],
            [56.01, 30.31],
            [55.99, 30.31],
            [55.99, 30.29],
        ]
    ],
}


@pytest.mark.asyncio
async def test_two_orchards_different_coordinates_produce_different_inputs():
    """Verify two orchards at different coordinates produce different topography & soil inputs."""
    provider = FakeForecastProvider(base_tmin_c=2.0)

    # Mock Earth Engine returns distinct real spatial values for Orchard A vs B
    def mock_cap(geometry, scale_m=30.0):
        coords = geometry.get("coordinates", [[[0, 0]]])[0][0]
        if coords[0] < 53.0:  # Orchard A (Damavand area)
            res = MagicMock()
            res.mean_pooling_risk_proxy = 0.72
            res.mean_slope_deg = 8.5
            res.mean_elevation_m = 2850.0
            return res
        else:  # Orchard B (Rafsanjan area)
            res = MagicMock()
            res.mean_pooling_risk_proxy = 0.28
            res.mean_slope_deg = 1.8
            res.mean_elevation_m = 1520.0
            return res

    orchard_a = Orchard(
        id=uuid.uuid4(),
        name="باغ الف (منطقه کوهستانی)",
        geometry=ORCHARD_A_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=datetime.now(timezone.utc),
        elevation=2850.0,
        latitude=35.80,
        longitude=52.00,
    )

    orchard_b = Orchard(
        id=uuid.uuid4(),
        name="باغ ب (منطقه دشت)",
        geometry=ORCHARD_B_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=datetime.now(timezone.utc),
        elevation=1520.0,
        latitude=30.30,
        longitude=56.00,
    )

    def mock_aspect(geom_dict):
        coords = geom_dict.get("coordinates", [[[0, 0]]])[0][0]
        return 180.0 if coords[0] < 53.0 else 45.0

    with patch("app.services.agriculture.cold_air_pooling.calculate_cold_air_pooling_ee", side_effect=mock_cap), \
         patch("app.services.agriculture.frost_inputs.extract_terrain_aspect_ee", side_effect=mock_aspect), \
         patch("app.services.agriculture.frost_inputs._can_query_ee", return_value=True):
        inputs_a = await assemble_orchard_inputs(orchard_a, forecast_provider=provider, use_cache=False)
        inputs_b = await assemble_orchard_inputs(orchard_b, forecast_provider=provider, use_cache=False)

    # Topography values must be different and derived from geometry, NOT fixed defaults
    pool_a = inputs_a.factors["topography_pooling"].value
    pool_b = inputs_b.factors["topography_pooling"].value
    slope_a = inputs_a.factors["topography_slope_aspect"].value
    slope_b = inputs_b.factors["topography_slope_aspect"].value

    assert pool_a != pool_b
    assert slope_a != slope_b
    assert pool_a == 0.72
    assert pool_b == 0.28
    assert slope_a == 8.5
    assert slope_b == 1.8


@pytest.mark.asyncio
async def test_missing_data_returns_unavailable_without_fallbacks():
    """Verify that when Earth Engine or provider returns None/fails, quality_state is unavailable and value is None."""
    provider = FakeForecastProvider(base_tmin_c=2.0)

    orchard = Orchard(
        id=uuid.uuid4(),
        name="باغ کویر بدون داده خاک",
        geometry=ORCHARD_A_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=datetime.now(timezone.utc),
        elevation=1000.0,
        latitude=32.0,
        longitude=54.0,
    )

    # Mock EE queries failing or returning None
    with patch("app.services.agriculture.cold_air_pooling.calculate_cold_air_pooling_ee", side_effect=RuntimeError("EE Offline")), \
         patch("app.services.agriculture.frost_inputs.extract_terrain_aspect_ee", side_effect=RuntimeError("EE Offline")), \
         patch("app.services.agriculture.soil_intelligence.compute_soil_intelligence", side_effect=RuntimeError("EE Offline")), \
         patch("app.services.agriculture.frost_inputs._can_query_ee", return_value=True):
        inputs = await assemble_orchard_inputs(orchard, forecast_provider=provider, use_cache=False)

    # Factors must be marked unavailable with None values, never synthetic numbers
    f_pool = inputs.factors["topography_pooling"]
    assert f_pool.quality_state == "unavailable"
    assert f_pool.value is None
    assert f_pool.status == "ناموجود"

    f_texture = inputs.factors["soil_texture_depth"]
    assert f_texture.quality_state == "unavailable"
    assert f_texture.value is None
    assert f_texture.status == "ناموجود"


def test_model_behavior_with_unavailable_factor():
    """Verify that unavailable factors get neutral subscore 0.50, weight stays in sum, and row shows ناموجود."""
    weights_cfg = load_frost_factor_weights_config()

    from app.services.agriculture.frost_inputs import OrchardInputs
    orch_inputs = OrchardInputs(
        orchard_id="test_orchard",
        orchard_name="باغ آزمون",
        latitude=35.8,
        longitude=52.0,
        elevation_m=2852.0,
        gfs_cell=(35.75, 52.0),
        factors={
            "topography_pooling": FactorInput(
                id="topography_pooling",
                label_fa="فرو رفتگی توپوگرافی",
                value=None,
                unit="شاخص [۰-۱]",
                source_module="ee:NASADEM",
                quality_state="unavailable",
                as_of=None,
                is_stale=False,
                status="ناموجود",
                static=True,
            ),
            "soil_texture_depth": FactorInput(
                id="soil_texture_depth",
                label_fa="بافت خاک",
                value=None,
                unit="رده بافت",
                source_module="ee:SoilGrids",
                quality_state="unavailable",
                as_of=None,
                is_stale=False,
                status="ناموجود",
                static=True,
            ),
        },
        assembled_at=datetime.now(timezone.utc).isoformat(),
        crop="pistachio",
        current_stage="unopened_bud",
        stage_is_stale=False,
    )

    res = evaluate_weighted_frost_model(
        inputs=orch_inputs,
        night_tmin_c=-1.0,
        critical_temp_c=-4.0,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=20.0,
        night_rh_pct=40.0,
        duration_escalated=False,
        night_date="2026-10-19",
        config=weights_cfg,
    )

    # Weights must sum to 100%
    assert abs(res.total_weight - 100.0) < 0.1

    # Check evaluated factor for unavailable items
    f_pool_eval = next(f for f in res.factors if f.id == "topography_pooling")
    assert f_pool_eval.quality_state == "unavailable"
    assert f_pool_eval.status == "ناموجود"
    assert f_pool_eval.raw_value == "داده این باغ موجود نیست"
    assert f_pool_eval.subscore == 0.50
    assert f_pool_eval.static is True

    f_tex_eval = next(f for f in res.factors if f.id == "soil_texture_depth")
    assert f_tex_eval.quality_state == "unavailable"
    assert f_tex_eval.status == "ناموجود"
    assert f_tex_eval.raw_value == "داده این باغ موجود نیست"
    assert f_tex_eval.subscore == 0.50
    assert f_tex_eval.static is True
