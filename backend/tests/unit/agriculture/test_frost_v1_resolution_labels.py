"""Unit tests for Phase 3 Close-out V1: Single Source of Truth Resolution Labels."""

import pytest
from app.services.agriculture.frost_inputs import (
    FACTOR_RESOLUTION_MAP,
    FACTOR_SOURCE_FA_MAP,
    assemble_orchard_inputs,
)
from app.services.agriculture.frost_weighted_model import (
    evaluate_weighted_frost_model,
    load_frost_factor_weights_config,
)
from app.services.agriculture.forecast import FakeForecastProvider


def test_v1_factor_resolution_mapping_constants():
    """Verify exact resolution labels specified in V1:
    - GFS rows (temperature, wind, cloud, relative humidity): '~۲۸ کیلومتر'
    - SMAP/ERA5-Land soil moisture: '~۹–۱۱ کیلومتر'
    - SoilGrids: '۲۵۰ متر'
    - DEM: '۳۰ متر'
    """
    # GFS rows
    gfs_factors = [
        "temperature_duration",
        "wind_speed",
        "wind_direction",
        "cloud_cover",
        "humidity_dewpoint",
    ]
    for fid in gfs_factors:
        assert FACTOR_RESOLUTION_MAP.get(fid) == "~۲۸ کیلومتر", (
            f"GFS factor {fid} must have resolution '~۲۸ کیلومتر', got {FACTOR_RESOLUTION_MAP.get(fid)}"
        )

    # Soil moisture
    assert FACTOR_RESOLUTION_MAP.get("soil_rootzone_moisture") == "~۹–۱۱ کیلومتر"

    # Soil texture
    assert FACTOR_RESOLUTION_MAP.get("soil_texture_depth") == "۲۵۰ متر"

    # DEM rows
    dem_factors = ["topography_pooling", "topography_slope_aspect"]
    for fid in dem_factors:
        assert FACTOR_RESOLUTION_MAP.get(fid) == "۳۰ متر", (
            f"DEM factor {fid} must have resolution '۳۰ متر', got {FACTOR_RESOLUTION_MAP.get(fid)}"
        )

    # Farm level / farmer entry
    assert FACTOR_RESOLUTION_MAP.get("phenological_stage") == "داده باغدار"


def test_v1_all_10_factors_in_mapping():
    """Verify all 10 factors configured in the model have resolution and Persian source mappings."""
    cfg = load_frost_factor_weights_config()
    assert len(cfg.factors) == 10

    for factor in cfg.factors:
        assert factor.id in FACTOR_RESOLUTION_MAP, f"Factor {factor.id} missing in FACTOR_RESOLUTION_MAP"
        assert FACTOR_RESOLUTION_MAP[factor.id], f"Factor {factor.id} has empty resolution string"
        assert factor.id in FACTOR_SOURCE_FA_MAP, f"Factor {factor.id} missing in FACTOR_SOURCE_FA_MAP"
        assert FACTOR_SOURCE_FA_MAP[factor.id], f"Factor {factor.id} has empty source name"


@pytest.mark.asyncio
async def test_v1_evaluated_factors_populate_resolution_and_source_mapping():
    """Verify that evaluated factor outputs in the model strictly populate spatial_resolution_fa and source_name_fa."""
    dummy_orchard = {
        "id": "test-v1-orchard",
        "name": "باغ تست نگاشت وضوح",
        "latitude": 32.315,
        "longitude": 54.020,
        "elevation": 1040.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[54.01, 32.31], [54.03, 32.31], [54.03, 32.33], [54.01, 32.33], [54.01, 32.31]]],
        },
    }

    inputs = await assemble_orchard_inputs(
        orchard=dummy_orchard,
        forecast_provider=FakeForecastProvider(),
        use_cache=False,
    )

    result = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=2.5,
        critical_temp_c=-4.0,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=30.0,
        night_rh_pct=40.0,
    )

    assert len(result.factors) == 10
    for ef in result.factors:
        expected_res = FACTOR_RESOLUTION_MAP[ef.id]
        expected_src = FACTOR_SOURCE_FA_MAP[ef.id]
        assert ef.spatial_resolution_fa == expected_res, (
            f"Factor {ef.id} spatial_resolution_fa mismatch: {ef.spatial_resolution_fa} != {expected_res}"
        )
        assert ef.source_name_fa == expected_src, (
            f"Factor {ef.id} source_name_fa mismatch: {ef.source_name_fa} != {expected_src}"
        )
