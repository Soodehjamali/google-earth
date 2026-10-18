"""Unit tests for Per-Orchard Frost Risk Service and API endpoints (R5).

Verifies:
1. Single orchard risk evaluation with all 10 platform factors.
2. Contributions sum to risk index; weights sum to 100.0%.
3. Absolute Safety Gate (GATE): lethal temperature is never diluted by favorable modifiers.
4. Recommendations surfaced only when warning or critical; suppressed when none or watch.
5. GFS forecast cell sharing across multiple orchards in the same GFS cell.
6. Summary endpoint sorting (worst-night risk descending).
7. Full API lifecycle: POST create -> GET risk -> GET summary -> PUT update stage -> DELETE orchard.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
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
    GUIDANCE_LABEL_FA,
)
from app.services.agriculture.frost_weighted_model import load_frost_factor_weights_config

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

SAMPLE_POLYGON_2 = {
    "type": "Polygon",
    "coordinates": [
        [
            [56.020, 30.000],
            [56.030, 30.000],
            [56.030, 30.010],
            [56.020, 30.010],
            [56.020, 30.000],
        ]
    ],
}


@pytest.fixture
def sample_orchard():
    now_utc = datetime.now(timezone.utc)
    return Orchard(
        id=uuid.uuid4(),
        name="باغ نمونه پسته رفسنجان",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=now_utc,
        elevation=1250.0,
        latitude=30.005,
        longitude=56.005,
    )


@pytest.mark.asyncio
async def test_assess_single_orchard_risk_factors_and_contributions(sample_orchard):
    """Verify that all 10 factors are evaluated, weights sum to 100, and contributions sum to risk_index."""
    provider = FakeForecastProvider(base_tmin_c=2.0, z_site_m=1250.0)
    report = await assess_single_orchard_risk(
        orchard=sample_orchard,
        horizon_h=72,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    assert report.orchard_id == str(sample_orchard.id)
    assert report.orchard_name == sample_orchard.name
    assert report.crop == "pistachio"
    assert report.current_stage == "unopened_bud"
    assert report.stage_is_stale is False
    assert report.critical_temperature_c == -4.0  # unopened_bud in published_v1 is -4.0
    assert report.index_is_probability is False
    assert report.guidance_risk_label_fa == GUIDANCE_LABEL_FA

    assert len(report.nights) > 0
    night0 = report.nights[0]

    # Verify all 10 factor rows exist
    expected_factors = {
        "temperature_duration",
        "phenological_stage",
        "soil_rootzone_moisture",
        "soil_texture_depth",
        "wind_speed",
        "wind_direction",
        "cloud_cover",
        "humidity_dewpoint",
        "topography_pooling",
        "topography_slope_aspect",
    }
    present_factors = {f["id"] for f in night0.factors}
    assert expected_factors == present_factors

    # Verify weights sum to 100.0%
    assert night0.total_weight == pytest.approx(100.0, abs=0.01)

    # Verify total_contribution equals risk_index
    assert night0.total_contribution == pytest.approx(night0.risk_index, abs=0.01)


@pytest.mark.asyncio
async def test_gate_trigger_overrides_favorable_modifiers(sample_orchard):
    """Verify GATE: when effective Tmin <= Tcrit, final category is at least warning regardless of other factors."""
    # unopened_bud Tcrit is -4.0 C; set base_tmin_c to -5.0 C (below Tcrit)
    provider = FakeForecastProvider(base_tmin_c=-5.0, z_site_m=1250.0)
    report = await assess_single_orchard_risk(
        orchard=sample_orchard,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    worst = report.worst_night
    assert worst is not None
    assert worst["gate_triggered"] is True
    assert worst["final_category"] in ("warning", "critical")
    assert report.overall_final_category in ("warning", "critical")
    # Recommendations MUST be populated when category is warning or critical
    assert len(report.recommendations_fa) > 0


@pytest.mark.asyncio
async def test_recommendations_suppressed_when_no_hazard(sample_orchard):
    """Verify recommendations are empty when temperature remains well above critical threshold."""
    provider = FakeForecastProvider(base_tmin_c=12.0, z_site_m=1250.0)
    report = await assess_single_orchard_risk(
        orchard=sample_orchard,
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    assert report.overall_final_category in ("none", "watch")
    # Informational or suppressed recommendations when safe
    assert len(report.recommendations_fa) == 0


@pytest.mark.asyncio
async def test_assess_orchards_summary_gfs_cell_sharing_and_sorting():
    """Verify that multiple orchards in same GFS cell share the forecast fetch and are sorted descending by risk."""
    now_utc = datetime.now(timezone.utc)
    # Orchard 1: Low elevation, unopened bud (more resistant)
    orchard_low = Orchard(
        id=uuid.uuid4(),
        name="باغ الف (ارتفاع کم)",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="unopened_bud",
        current_stage="unopened_bud",
        stage_updated_at=now_utc,
        elevation=1000.0,
        latitude=30.005,
        longitude=56.005,
    )

    # Orchard 2: High elevation (cooler by lapse rate), bloomed flower (more sensitive)
    orchard_high = Orchard(
        id=uuid.uuid4(),
        name="باغ ب (ارتفاع زیاد)",
        geometry=SAMPLE_POLYGON_2,
        crop="pistachio",
        default_phenology_stage="full_bloom",
        current_stage="full_bloom",
        stage_updated_at=now_utc,
        elevation=1800.0,
        latitude=30.006,
        longitude=56.025,
    )

    # Both orchards fall within the same GFS 0.25 deg cell (lng 56.005 and 56.025)
    call_counter = {"count": 0}
    provider = FakeForecastProvider(base_tmin_c=-2.0, z_site_m=1000.0)
    real_get_hourly = provider.get_hourly_forecast

    async def counted_get_hourly(*args, **kwargs):
        call_counter["count"] += 1
        return await real_get_hourly(*args, **kwargs)

    provider.get_hourly_forecast = counted_get_hourly

    summaries = await assess_orchards_summary(
        orchards=[orchard_low, orchard_high],
        horizon_h=48,
        threshold_set="published_v1",
        forecast_provider=provider,
        use_cache=False,
    )

    assert len(summaries) == 2
    # Verify GFS fetch was called only ONCE for both orchards
    assert call_counter["count"] == 1

    # Verify sorting: Orchard High (higher risk) must be first, Orchard Low second
    assert summaries[0].orchard_id == str(orchard_high.id)
    assert summaries[1].orchard_id == str(orchard_low.id)
    assert summaries[0].risk_index >= summaries[1].risk_index


@pytest.mark.asyncio
async def test_orchard_risk_api_crud_and_evaluation_lifecycle(monkeypatch):
    """End-to-end API test: create orchard, get risk report, get summary, update stage, delete."""
    from app.db.session import dispose_engine
    await dispose_engine()

    monkeypatch.setattr(settings, "ADMIN_API_KEY", "admin-secret-token")
    monkeypatch.setattr(settings, "FROST_USE_LIVE_GEE", False)
    headers = {"X-Admin-Token": "admin-secret-token"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create Orchard
        create_payload = {
            "name": "باغ آزمایشی زرند",
            "geometry": SAMPLE_POLYGON,
            "crop": "pistachio",
            "default_phenology_stage": "opening_bud",
            "current_stage": "opening_bud",
            "elevation": 1350.0,
        }
        res_create = await client.post("/api/v1/agriculture/frost/orchards", json=create_payload, headers=headers)
        assert res_create.status_code == 201, f"Create failed: {res_create.text}"
        orchard_data = res_create.json()
        orchard_id = orchard_data["id"]
        assert orchard_data["current_stage"] == "opening_bud"
        assert orchard_data["stage_updated_at"] is not None

        # 2. Get Single Orchard Risk Evaluation
        res_risk = await client.get(
            f"/api/v1/agriculture/frost/orchards/{orchard_id}/risk?horizon_h=48&threshold_set=published_v1",
            headers=headers,
        )
        assert res_risk.status_code == 200, f"Risk evaluation failed: {res_risk.text}"
        risk_data = res_risk.json()
        assert risk_data["orchard_id"] == orchard_id
        assert risk_data["current_stage"] == "opening_bud"
        assert "nights" in risk_data
        assert "guidance_risk_label_fa" in risk_data
        assert len(risk_data["nights"]) > 0

        # Check factor breakdown on first night
        n0 = risk_data["nights"][0]
        assert "factors" in n0
        assert len(n0["factors"]) == 10
        assert n0["total_weight"] == pytest.approx(100.0, abs=0.01)

        # 3. Get Orchards Risk Summary
        res_summary = await client.get(
            "/api/v1/agriculture/frost/orchards/risk-summary?horizon_h=48",
            headers=headers,
        )
        assert res_summary.status_code == 200, f"Summary failed: {res_summary.text}"
        summary_list = res_summary.json()
        assert isinstance(summary_list, list)
        matching = [item for item in summary_list if item["orchard_id"] == orchard_id]
        assert len(matching) == 1
        assert matching[0]["name"] == "باغ آزمایشی زرند"

        # 4. Update Orchard Stage
        update_payload = {
            "current_stage": "full_bloom",
        }
        res_update = await client.put(
            f"/api/v1/agriculture/frost/orchards/{orchard_id}",
            json=update_payload,
            headers=headers,
        )
        assert res_update.status_code == 200, f"Update failed: {res_update.text}"
        updated_data = res_update.json()
        assert updated_data["current_stage"] == "full_bloom"

        # 5. Delete Orchard
        res_del = await client.delete(
            f"/api/v1/agriculture/frost/orchards/{orchard_id}",
            headers=headers,
        )
        assert res_del.status_code == 204, f"Delete failed: {res_del.text}"

        # 6. Verify Orchard is gone
        res_get_deleted = await client.get(
            f"/api/v1/agriculture/frost/orchards/{orchard_id}/risk",
            headers=headers,
        )
        assert res_get_deleted.status_code == 404
