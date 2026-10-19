"""Unit Tests for Per-Orchard Input Assembly Service (R1).

Verifies:
1. Soil root-zone moisture normalization: clamp((theta - WP) / (FC - WP), 0, 1) and 'نامشخص' on missing.
2. 0.25-degree GFS grid cell calculation.
3. GFS forecast sharing across multiple orchards in the same cell with per-orchard elevation correction.
4. Input assembly structure, factor attributes, and staleness detection.
"""

from datetime import datetime, timedelta, timezone
import pytest

from app.services.agriculture.forecast import FakeForecastProvider
from app.services.agriculture.frost_inputs import (
    assemble_orchard_inputs,
    get_gfs_cell_coords,
    is_timestamp_stale,
    normalize_rootzone_moisture,
    FactorInput,
    OrchardInputs,
)


def test_normalize_rootzone_moisture_standard_and_clamping():
    """Verify standard linear normalization and [0, 1] clamping."""
    wp = 0.10
    fc = 0.25

    # Midpoint: (0.175 - 0.10) / 0.15 = 0.50
    assert normalize_rootzone_moisture(0.175, wilting_point=wp, field_capacity=fc) == 0.50

    # At wilting point: (0.10 - 0.10) / 0.15 = 0.0
    assert normalize_rootzone_moisture(0.10, wilting_point=wp, field_capacity=fc) == 0.0

    # Below wilting point: clamped to 0.0
    assert normalize_rootzone_moisture(0.05, wilting_point=wp, field_capacity=fc) == 0.0

    # At field capacity: (0.25 - 0.10) / 0.15 = 1.0
    assert normalize_rootzone_moisture(0.25, wilting_point=wp, field_capacity=fc) == 1.0

    # Above field capacity (saturation/ponding): clamped to 1.0
    assert normalize_rootzone_moisture(0.35, wilting_point=wp, field_capacity=fc) == 1.0


def test_normalize_rootzone_moisture_missing_and_invalid():
    """Verify that missing or unphysical WP/FC bounds return None ('نامشخص')."""
    # Missing parameters
    assert normalize_rootzone_moisture(None, 0.10, 0.25) is None
    assert normalize_rootzone_moisture(0.18, None, 0.25) is None
    assert normalize_rootzone_moisture(0.18, 0.10, None) is None

    # Unphysical bounds: FC <= WP
    assert normalize_rootzone_moisture(0.18, wilting_point=0.25, field_capacity=0.10) is None
    assert normalize_rootzone_moisture(0.18, wilting_point=0.20, field_capacity=0.20) is None


def test_gfs_cell_calculation():
    """Verify that coordinates snap to 0.25-degree GFS cell grid centers."""
    # (30.41, 55.91) rounds to 30.50, 56.00
    assert get_gfs_cell_coords(30.41, 55.91) == (30.50, 56.00)
    # (30.48, 55.98) also rounds to 30.50, 56.00 (same cell)
    assert get_gfs_cell_coords(30.48, 55.98) == (30.50, 56.00)
    # (30.10, 55.10) rounds to 30.00, 55.00 (different cell)
    assert get_gfs_cell_coords(30.10, 55.10) == (30.00, 55.00)


def test_staleness_detection():
    """Verify staleness detection against configurable thresholds."""
    now = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 10 days old: within 14-day phenology threshold
    ts_fresh = (now - timedelta(days=10)).isoformat()
    assert is_timestamp_stale(ts_fresh, max_age_hours=14 * 24, now=now) is False

    # 15 days old: exceeds 14-day threshold
    ts_stale = (now - timedelta(days=15)).isoformat()
    assert is_timestamp_stale(ts_stale, max_age_hours=14 * 24, now=now) is True

    # Missing timestamp is treated as stale
    assert is_timestamp_stale(None, max_age_hours=24, now=now) is True


@pytest.mark.asyncio
async def test_assemble_orchard_inputs_cell_sharing_and_elevation_isolation():
    """Verify that two orchards in the same GFS cell share the forecast fetch but get different corrected temperatures."""
    shared_gfs_cache = {}
    provider = FakeForecastProvider()

    # Orchard 1: Low elevation (1000m)
    orchard1 = {
        "id": "orchard_valley",
        "name": "باغ دره",
        "latitude": 30.42,
        "longitude": 55.91,
        "elevation": 1000.0,
        "crop": "pistachio",
        "current_stage": "bloom",
        "stage_updated_at": "2026-04-10T08:00:00Z",
    }

    # Orchard 2: High elevation (1800m) in the SAME GFS cell (30.50, 56.00)
    orchard2 = {
        "id": "orchard_hill",
        "name": "باغ کوهپایه",
        "latitude": 30.46,
        "longitude": 55.93,
        "elevation": 1800.0,
        "crop": "pistachio",
        "current_stage": "unopened_bud",
        "stage_updated_at": "2026-04-10T08:00:00Z",
    }

    inputs1 = await assemble_orchard_inputs(
        orchard1,
        forecast_provider=provider,
        gfs_cell_cache=shared_gfs_cache,
        use_cache=False,
    )

    inputs2 = await assemble_orchard_inputs(
        orchard2,
        forecast_provider=provider,
        gfs_cell_cache=shared_gfs_cache,
        use_cache=False,
    )

    # Verify both share the exact same GFS cell
    assert inputs1.gfs_cell == inputs2.gfs_cell == (30.50, 56.00)
    # Verify the cell cache now holds the shared raw forecast
    assert len(shared_gfs_cache) == 1
    assert "agri:frost_gfs_cell:30.50:56.00" in shared_gfs_cache

    # Verify thermodynamic isolation: high elevation orchard is colder than valley orchard
    t1_min = min(s.temperature_2m_c for s in inputs1.orchard_forecast.series)
    t2_min = min(s.temperature_2m_c for s in inputs2.orchard_forecast.series)
    assert t2_min < t1_min, f"Hill orchard ({t2_min}°C) must be colder than valley orchard ({t1_min}°C)"

    # Verify factor attributes presence and schema contract
    for factor_key, factor in inputs1.factors.items():
        assert isinstance(factor, FactorInput)
        assert factor.id == factor_key
        assert factor.label_fa
        assert factor.unit
        assert factor.source_module
        assert factor.quality_state in ("valid", "coarse_context", "unknown", "unavailable")
        assert factor.status in ("مطلوب", "خنثی", "نامطلوب", "نامشخص", "ناموجود")
        if factor.quality_state != "unavailable":
            assert factor.as_of

