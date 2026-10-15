"""Unit tests for Spatial Heatmap Layer service and API (Phase P-AGRI-3)."""

import pytest
from pydantic import ValidationError

from app.schemas.agriculture import (
    PointGeometry,
    PolygonGeometry,
    SpatialLayerRequest,
    SpatialLayerResponse,
    SpatialMetricType,
)
from app.services.agriculture.spatial_layer import (
    SPATIAL_METRIC_CONFIGS,
    generate_spatial_layer,
)


def test_spatial_metric_configs_registered():
    """Verify all 4 MVP spatial metrics are registered with correct specs."""
    assert "ndvi" in SPATIAL_METRIC_CONFIGS
    assert "lst_day" in SPATIAL_METRIC_CONFIGS
    assert "soil_moisture" in SPATIAL_METRIC_CONFIGS
    assert "sar_vh" in SPATIAL_METRIC_CONFIGS

    # NDVI
    ndvi_cfg = SPATIAL_METRIC_CONFIGS["ndvi"]
    assert ndvi_cfg["native_resolution_m"] == 10.0
    assert ndvi_cfg["unit"] == "index"
    assert ndvi_cfg["min_val"] == 0.0
    assert ndvi_cfg["max_val"] == 0.8
    assert "S2" in ndvi_cfg["source_dataset"]

    # LST Day
    lst_cfg = SPATIAL_METRIC_CONFIGS["lst_day"]
    assert lst_cfg["native_resolution_m"] == 1000.0
    assert lst_cfg["unit"] == "°C"
    assert lst_cfg["min_val"] == 20.0
    assert lst_cfg["max_val"] == 55.0
    assert "MODIS" in lst_cfg["source_dataset"]

    # Soil Moisture
    sm_cfg = SPATIAL_METRIC_CONFIGS["soil_moisture"]
    assert sm_cfg["native_resolution_m"] == 9000.0
    assert sm_cfg["unit"] == "m³/m³"
    assert sm_cfg["min_val"] == 0.0
    assert sm_cfg["max_val"] == 0.35
    assert "SMAP" in sm_cfg["source_dataset"]

    # SAR VH
    sar_cfg = SPATIAL_METRIC_CONFIGS["sar_vh"]
    assert sar_cfg["native_resolution_m"] == 10.0
    assert sar_cfg["unit"] == "dB"
    assert sar_cfg["min_val"] == -25.0
    assert sar_cfg["max_val"] == -10.0
    assert "S1" in sar_cfg["source_dataset"]


def test_spatial_layer_request_validation():
    """Verify request validation enforces valid metrics and reject invalid metrics."""
    # Valid Point request
    req = SpatialLayerRequest(
        metric=SpatialMetricType.NDVI,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    assert req.metric == SpatialMetricType.NDVI

    # Invalid metric string rejected by schema
    with pytest.raises(ValidationError):
        SpatialLayerRequest(
            metric="unsupported_metric",  # type: ignore
            geometry=PointGeometry(coordinates=[53.688, 32.4279]),
            start_date="2025-06-01",
            end_date="2025-09-01",
        )


@pytest.mark.requires_gee
def test_generate_spatial_layer_ndvi():
    """Verify real Earth Engine NDVI generation for Point geometry."""
    req = SpatialLayerRequest(
        metric=SpatialMetricType.NDVI,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        cloud_max_percent=20.0,
    )
    resp = generate_spatial_layer(req)
    assert isinstance(resp, SpatialLayerResponse)
    assert resp.status == "available"
    assert resp.metric == "ndvi"
    assert resp.tile_url_template is not None
    assert "earthengine.googleapis.com" in resp.tile_url_template
    assert resp.spatial_resolution == "10 m"
    assert resp.native_resolution_m == 10.0
    assert resp.unit == "index"
    assert resp.geometry_type == "Point"
    assert resp.support_radius_m is not None
    assert resp.support_area_sq_m is not None
    assert resp.bounds is not None
    assert len(resp.bounds) == 4


@pytest.mark.requires_gee
def test_generate_spatial_layer_all_four_metrics():
    """Verify that all four MVP metrics generate valid real responses with proper metadata."""
    for metric_type in [
        SpatialMetricType.NDVI,
        SpatialMetricType.LST_DAY,
        SpatialMetricType.SOIL_MOISTURE,
        SpatialMetricType.SAR_VH,
    ]:
        req = SpatialLayerRequest(
            metric=metric_type,
            geometry=PointGeometry(coordinates=[53.688, 32.4279]),
            start_date="2025-06-01",
            end_date="2025-09-01",
        )
        resp = generate_spatial_layer(req)
        assert resp.status == "available"
        assert resp.tile_url_template is not None
        assert len(resp.palette) > 0
        assert resp.min_val < resp.max_val
        assert resp.native_resolution_m > 0
        assert resp.unit != ""


@pytest.mark.requires_gee
def test_generate_spatial_layer_polygon():
    """Verify spatial layer generation for Polygon geometry."""
    poly = PolygonGeometry(
        coordinates=[
            [
                [53.65, 32.40],
                [53.72, 32.40],
                [53.72, 32.45],
                [53.65, 32.45],
                [53.65, 32.40],
            ]
        ]
    )
    req = SpatialLayerRequest(
        metric=SpatialMetricType.NDVI,
        geometry=poly,
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.geometry_type == "Polygon"
    assert resp.support_radius_m is None
    assert resp.support_area_sq_m is not None
    assert resp.support_area_sq_m > 0


@pytest.mark.requires_gee
def test_no_data_honest_response():
    """Verify that when no imagery exists, honest unavailable status is returned."""
    # Future or invalid date range with 0 images
    req = SpatialLayerRequest(
        metric=SpatialMetricType.NDVI,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="1980-01-01",
        end_date="1980-01-02",  # Sentinel-2 did not exist in 1980
        cloud_max_percent=20.0,
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "unavailable"
    assert resp.tile_url_template is None
    assert resp.unavailable_reason == "insufficient_coverage"
    assert len(resp.limitations) > 0


# =========================================================================
# P-AGRI-4 Agricultural Interpretation Heatmap Tests
# =========================================================================


def test_agricultural_concepts_registered():
    """Verify all 3 agricultural concepts are registered with required metadata."""
    from app.services.agriculture.spatial_layer import AGRICULTURAL_CONCEPTS

    assert "vegetation_condition" in AGRICULTURAL_CONCEPTS
    assert "thermal_stress" in AGRICULTURAL_CONCEPTS
    assert "surface_dryness" in AGRICULTURAL_CONCEPTS

    # vegetation_condition
    veg = AGRICULTURAL_CONCEPTS["vegetation_condition"]
    assert veg["source_metric"] == "ndvi"
    assert veg["display_name"] == "Vegetation Condition"
    assert "وضعیت پوشش گیاهی" in veg["display_name_fa"]
    assert "photosynthetic canopy" in veg["interpretation"]
    assert "does not diagnose" in veg["scientific_caution"].lower()
    assert len(veg["qualitative_legend"]) >= 3

    # thermal_stress
    therm = AGRICULTURAL_CONCEPTS["thermal_stress"]
    assert therm["source_metric"] == "lst_day"
    assert therm["display_name"] == "Thermal Stress Proxy"
    assert "تنش حرارتی" in therm["display_name_fa"]
    assert "MODIS" in therm["interpretation"]
    assert "does not directly measure or prove plant cellular stress" in therm["scientific_caution"]
    assert "1000 m" in therm["scientific_caution"]
    assert len(therm["qualitative_legend"]) >= 3

    # surface_dryness
    dry = AGRICULTURAL_CONCEPTS["surface_dryness"]
    assert dry["source_metric"] == "ndmi"
    assert dry["display_name"] == "Surface Dryness Proxy (NDMI)"
    assert "خشکی سطح" in dry["display_name_fa"]
    assert "NDMI" in dry["interpretation"]
    assert "plant water stress" in dry["scientific_caution"]
    assert len(dry["qualitative_legend"]) >= 3


def test_spatial_layer_request_with_concept():
    """Verify request validation accepts concept and rejects missing concept and metric."""
    from app.schemas.agriculture import SpatialConceptType

    # Valid request with concept enum
    req = SpatialLayerRequest(
        concept=SpatialConceptType.VEGETATION_CONDITION,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    assert req.concept == SpatialConceptType.VEGETATION_CONDITION
    assert req.metric is None

    # Valid request with concept string
    req2 = SpatialLayerRequest(
        concept="surface_dryness",  # type: ignore
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    assert req2.concept == "surface_dryness"

    # Reject request when both concept and metric are missing
    with pytest.raises(ValidationError):
        SpatialLayerRequest(
            geometry=PointGeometry(coordinates=[53.688, 32.4279]),
            start_date="2025-06-01",
            end_date="2025-09-01",
        )


@pytest.mark.requires_gee
def test_generate_spatial_layer_vegetation_condition():
    """Verify vegetation_condition concept generates real GEE NDVI tile with qualitative interpretation."""
    from app.schemas.agriculture import SpatialConceptType

    req = SpatialLayerRequest(
        concept=SpatialConceptType.VEGETATION_CONDITION,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        cloud_max_percent=20.0,
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.concept == "vegetation_condition"
    assert resp.concept_name == "Vegetation Condition"
    assert resp.metric == "ndvi"
    assert resp.tile_url_template is not None
    assert "earthengine.googleapis.com" in resp.tile_url_template
    assert resp.spatial_resolution == "10 m"
    assert resp.native_resolution_m == 10.0
    assert resp.interpretation is not None
    assert resp.scientific_caution is not None
    assert "does not diagnose" in resp.scientific_caution.lower()
    assert resp.qualitative_legend is not None
    assert len(resp.qualitative_legend) >= 3


@pytest.mark.requires_gee
def test_generate_spatial_layer_thermal_stress():
    """Verify thermal_stress concept generates real GEE LST tile with honest scientific caution."""
    from app.schemas.agriculture import SpatialConceptType

    req = SpatialLayerRequest(
        concept=SpatialConceptType.THERMAL_STRESS,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.concept == "thermal_stress"
    assert resp.metric == "lst_day"
    assert resp.tile_url_template is not None
    assert resp.spatial_resolution == "1000 m"
    assert resp.native_resolution_m == 1000.0
    assert resp.interpretation is not None
    assert resp.scientific_caution is not None
    assert "cellular stress" in resp.scientific_caution
    assert resp.qualitative_legend is not None


@pytest.mark.requires_gee
def test_generate_spatial_layer_surface_dryness():
    """Verify surface_dryness concept generates real GEE NDMI tile with honest optical proxy caution."""
    from app.schemas.agriculture import SpatialConceptType

    req = SpatialLayerRequest(
        concept=SpatialConceptType.SURFACE_DRYNESS,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
        cloud_max_percent=20.0,
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.concept == "surface_dryness"
    assert resp.metric == "ndmi"
    assert resp.tile_url_template is not None
    assert resp.spatial_resolution == "20 m"
    assert resp.native_resolution_m == 20.0
    assert resp.interpretation is not None
    assert resp.scientific_caution is not None
    assert "root-zone" in resp.scientific_caution
    assert resp.qualitative_legend is not None


@pytest.mark.requires_gee
def test_generate_spatial_layer_ndmi_metric_direct():
    """Verify raw NDMI metric request works directly (backward & raw compatibility)."""
    from app.schemas.agriculture import SpatialMetricType

    req = SpatialLayerRequest(
        metric=SpatialMetricType.NDMI,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.metric == "ndmi"
    assert resp.native_resolution_m == 20.0
    assert resp.unit == "index"
    assert resp.tile_url_template is not None
    assert resp.proxied_tile_url_template is not None
    assert "/api/v1/agriculture/tiles/" in resp.proxied_tile_url_template


@pytest.mark.requires_gee
def test_generate_spatial_layer_true_color():
    """Verify true_color Sentinel-2 RGB composite generation and proxied tile URL."""
    from app.schemas.agriculture import SpatialMetricType

    req = SpatialLayerRequest(
        metric=SpatialMetricType.TRUE_COLOR,
        geometry=PointGeometry(coordinates=[53.688, 32.4279]),
        start_date="2025-06-01",
        end_date="2025-09-01",
    )
    resp = generate_spatial_layer(req)
    assert resp.status == "available"
    assert resp.metric == "true_color"
    assert resp.native_resolution_m == 10.0
    assert resp.tile_url_template is not None
    assert resp.proxied_tile_url_template is not None
    assert "/api/v1/agriculture/tiles/" in resp.proxied_tile_url_template


def test_tile_proxy_endpoint_and_cache():
    """Verify the /api/v1/agriculture/tiles/ proxy returns cached tiles and protects clients."""
    from starlette.testclient import TestClient
    from app.main import app
    from app.services.agriculture.tile_auth import generate_signed_layer_token
    from app.services.cache_service import cache_service

    client = TestClient(app)
    # Coordinate: lon=53.688, lat=32.4279 -> slippy tile at z=14 is x=10635, y=6630
    bbox = [53.65, 32.40, 53.72, 32.45]
    token_id = "testlayerid12345"
    signed_token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id=token_id,
        ttl_seconds=3600,
    )
    cache_service.set(f"tile_template:{token_id}", "https://mock.earthengine.google.com/{z}/{x}/{y}")

    # Case 1: Pre-cached tile returns directly with private cache-control
    cache_service.set(f"tile_img:{token_id}:14:10635:6630", b"fake_png_bytes")
    resp = client.get(f"/api/v1/agriculture/tiles/{signed_token}/14/10635/6630.png")
    assert resp.status_code == 200
    assert resp.content == b"fake_png_bytes"
    assert "image/png" in resp.headers["content-type"]
    assert "private" in resp.headers["cache-control"]

    # Case 2: Forged token signature returns 403 Forbidden
    forged_token = signed_token[:-4] + "dead"
    resp_forged = client.get(f"/api/v1/agriculture/tiles/{forged_token}/14/10635/6630.png")
    assert resp_forged.status_code == 403
    assert resp_forged.json()["code"] == "ERR_TILE_FORBIDDEN"

    # Case 3: Expired token returns 403 Forbidden
    expired_token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="expired_tid_123",
        ttl_seconds=-10,  # expired 10 seconds ago
    )
    resp_expired = client.get(f"/api/v1/agriculture/tiles/{expired_token}/14/10635/6630.png")
    assert resp_expired.status_code == 403
    assert resp_expired.json()["code"] == "ERR_TILE_EXPIRED"

    # Case 4: Zoom level out of bounds (< 8 or > 20) returns 404
    resp_z7 = client.get(f"/api/v1/agriculture/tiles/{signed_token}/7/80/50.png")
    assert resp_z7.status_code == 404
    assert resp_z7.json()["code"] == "ERR_TILE_OUT_OF_BOUNDS"

    resp_z21 = client.get(f"/api/v1/agriculture/tiles/{signed_token}/21/1000/1000.png")
    assert resp_z21.status_code == 404
    assert resp_z21.json()["code"] == "ERR_TILE_OUT_OF_BOUNDS"

    # Case 5: Spatial bounding box out of bounds returns 404
    # Tile at z=14 x=500 y=500 is in the Atlantic/Europe, far outside Ardakan bbox [53.65, 32.40, ...]
    resp_oob = client.get(f"/api/v1/agriculture/tiles/{signed_token}/14/500/500.png")
    assert resp_oob.status_code == 404
    assert resp_oob.json()["code"] == "ERR_TILE_OUT_OF_BOUNDS"


