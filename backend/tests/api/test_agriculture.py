"""Tests for the Agricultural Intelligence API (Phase Q).

All tests are deterministic, seed-independent, and use mocks for
Earth Engine.  No live GEE calls, no database required.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import agriculture
from app.core.exceptions import AppException, DateRangeError, ValidationError
from app.schemas.agriculture import (
    AgriculturalAnalysisResponse,
    AgricultureAnalysisRequest,
    AgricultureHealthResponse,
    DomainSummaryResponse,
    EvidenceBundleResponse,
    EvidenceConflictResponse,
    EvidenceItemResponse,
    EvidenceSufficiencyResponse,
    ProvenanceResponse,
    SynthesisStatementResponse,
)
from app.services.agriculture.evidence import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
    SufficiencyLevel,
)
from app.services.agriculture.synthesis import (
    AgriculturalSynthesis,
    DomainSummary,
    PatternState,
    SynthesisDomain,
    SynthesisEngine,
    SynthesisStatement,
)
from app.services.agriculture.types import (
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)


# ---------------------------------------------------------------------------
# 1. Test app setup
# ---------------------------------------------------------------------------


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app for testing."""
    app = FastAPI()
    app.include_router(agriculture.router, prefix="/api/v1/agriculture")

    # Register the same exception handlers as the main app
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Any, exc: AppException) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    return app


app = _create_test_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _register_metrics():
    """Ensure the metric registry is populated for every test."""
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    yield


# ---------------------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------------------


def _make_provenance(
    dataset: str = "MODIS/061/MOD13A2",
    name: str = "MODIS NDVI",
) -> Provenance:
    return Provenance(
        source_dataset_id=dataset,
        source_dataset_name=name,
        bands=["NDVI"],
        formula="NDVI = (NIR - RED) / (NIR + RED)",
        unit="index",
        spatial_resolution="1 km",
        temporal_resolution="16-day",
        measurement_basis=QualityLevel.GOOD,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2024-07-01",
        requested_end="2024-07-31",
    )


def _make_metric_result(
    key: str = "ndvi",
    value: float = 0.65,
    status: str = "ok",
    unit: str = "index",
) -> MetricResult:
    return MetricResult(
        metric_key=key,
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=status,
        value=value,
        unit=unit,
        provenance=_make_provenance(),
        warnings=[],
    )


def _make_evidence_item(
    metric_key: str = "ndvi_anomaly_absolute",
    value: Optional[float] = -0.15,
    quality: QualityLevel = QualityLevel.GOOD,
    source: str = "modis_ndvi",
) -> EvidenceItem:
    return EvidenceItem(
        metric_key=metric_key,
        value=value,
        unit="index",
        status=EvidenceStatus.DERIVED,
        temporal_start=date(2024, 7, 1),
        temporal_end=date(2024, 7, 31),
        quality_level=quality,
        provenance=_make_provenance(),
        source_dataset_id=source,
    )


def _make_water_bundle(
    precip: float = -0.8,
    soil: float = -0.6,
    et: float = -0.4,
) -> EvidenceBundle:
    bundle = EvidenceBundle(
        name="water",
        items=[
            _make_evidence_item("precipitation_anomaly", precip, source="era5_land"),
            _make_evidence_item("soil_moisture_rootzone_anomaly", soil, source="smap_l4"),
            _make_evidence_item("evapotranspiration_anomaly", et, source="modis_et"),
        ],
    )
    bundle.assess_sufficiency()
    return bundle


def _make_veg_bundle(
    ndvi_abs: float = -0.15,
    ndvi_rel: float = -0.25,
) -> EvidenceBundle:
    bundle = EvidenceBundle(
        name="vegetation",
        items=[
            _make_evidence_item("ndvi_anomaly_absolute", ndvi_abs, source="modis_ndvi"),
            _make_evidence_item("ndvi_anomaly_relative", ndvi_rel, source="sentinel2_ndvi"),
        ],
    )
    bundle.assess_sufficiency()
    return bundle


# ---------------------------------------------------------------------------
# 3. Schema tests
# ---------------------------------------------------------------------------


class TestRequestSchema:
    def test_valid_point_request(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        assert req.geometry.type == "Point"
        assert req.start_date == "2024-07-01"
        assert req.end_date == "2024-07-31"
        assert req.domains is None
        assert req.cloud_max_percent == 20.0

    def test_valid_polygon_request(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={
                "type": "Polygon",
                "coordinates": [[[51.0, 35.0], [51.5, 35.0], [51.5, 36.0], [51.0, 36.0], [51.0, 35.0]]],
            },
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "water"],
        )
        assert req.geometry.type == "Polygon"
        assert req.domains == ["vegetation", "water"]

    def test_request_with_domains(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "water", "thermal"],
        )
        assert len(req.domains) == 3


# ---------------------------------------------------------------------------
# 4. Response schema tests
# ---------------------------------------------------------------------------


class TestResponseSchemas:
    def test_provenance_response(self) -> None:
        resp = ProvenanceResponse(
            source_dataset_id="MODIS/061/MOD13A2",
            source_dataset_name="MODIS NDVI",
            bands=["NDVI"],
            formula="NDVI = (NIR - RED) / (NIR + RED)",
            unit="index",
            spatial_resolution="1 km",
            temporal_resolution="16-day",
            measurement_basis="product",
            quality_level="good",
            temporal_kind="observation",
        )
        d = resp.model_dump()
        assert d["source_dataset_id"] == "MODIS/061/MOD13A2"
        assert d["bands"] == ["NDVI"]
        assert d["measurement_basis"] == "product"

    def test_evidence_item_response(self) -> None:
        resp = EvidenceItemResponse(
            metric_key="ndvi_anomaly_absolute",
            value=-0.15,
            unit="index",
            status="derived",
            quality="good",
            source_dataset="modis_ndvi",
            is_usable=True,
        )
        d = resp.model_dump()
        assert d["metric_key"] == "ndvi_anomaly_absolute"
        assert d["value"] == pytest.approx(-0.15)
        assert d["is_usable"] is True

    def test_evidence_bundle_response(self) -> None:
        resp = EvidenceBundleResponse(
            name="water",
            items=[
                EvidenceItemResponse(
                    metric_key="precipitation_anomaly",
                    value=-0.8,
                    unit="mm/day",
                    status="modelled",
                    quality="good",
                )
            ],
            available=["precipitation_anomaly"],
            unavailable=[],
            source_datasets=["era5_land"],
        )
        d = resp.model_dump()
        assert d["name"] == "water"
        assert len(d["items"]) == 1
        assert d["available"] == ["precipitation_anomaly"]

    def test_synthesis_statement_response(self) -> None:
        resp = SynthesisStatementResponse(
            rule_id="water_below_baseline",
            domain="water",
            pattern="below_context",
            statement="Multiple water-availability indicators show below-baseline values.",
            evidence_keys=["precipitation_anomaly", "soil_moisture_rootzone_anomaly"],
            evidence_values={"precipitation_anomaly": -0.8},
            scientific_basis="Precipitation and soil moisture are independently measured.",
            limitations=["Different temporal response lags."],
            sufficiency="sufficient",
        )
        d = resp.model_dump()
        assert d["rule_id"] == "water_below_baseline"
        assert d["domain"] == "water"
        assert len(d["evidence_keys"]) == 2
        assert d["scientific_basis"] != ""
        assert len(d["limitations"]) == 1

    def test_domain_summary_response(self) -> None:
        resp = DomainSummaryResponse(
            domain="water",
            statement_count=1,
            statements=[
                SynthesisStatementResponse(
                    rule_id="water_below_baseline",
                    domain="water",
                    pattern="below_context",
                    statement="Below baseline.",
                    evidence_keys=["precipitation_anomaly"],
                    evidence_values={},
                    scientific_basis="Basis.",
                    limitations=["Limitation."],
                )
            ],
            unavailable_evidence=[],
            sufficiency="sufficient",
        )
        d = resp.model_dump()
        assert d["domain"] == "water"
        assert d["statement_count"] == 1
        assert d["sufficiency"] == "sufficient"

    def test_agricultural_analysis_response(self) -> None:
        resp = AgriculturalAnalysisResponse(
            request_id="test-123",
            time_start="2024-07-01",
            time_end="2024-07-31",
            spatial_context="test field",
            generated_at="2024-08-01T00:00:00",
            overall_sufficiency="sufficient",
            available_domains=["water", "vegetation"],
            unavailable_domains=["thermal"],
        )
        d = resp.model_dump()
        assert d["request_id"] == "test-123"
        assert d["overall_sufficiency"] == "sufficient"
        assert "water" in d["available_domains"]
        assert "thermal" in d["unavailable_domains"]

    def test_error_response(self) -> None:
        from app.schemas.agriculture import ErrorResponse

        resp = ErrorResponse(
            error="Invalid geometry",
            detail={"field": "coordinates"},
            reason_code="invalid_geometry",
        )
        d = resp.model_dump()
        assert d["error"] == "Invalid geometry"
        assert d["reason_code"] == "invalid_geometry"


# ---------------------------------------------------------------------------
# 5. Serialization helper tests
# ---------------------------------------------------------------------------


class TestSerializationHelpers:
    def test_serialize_provenance_none(self) -> None:
        result = agriculture._serialize_provenance(None)
        assert result is None

    def test_serialize_provenance_full(self) -> None:
        prov = _make_provenance()
        result = agriculture._serialize_provenance(prov)
        assert result is not None
        assert result.source_dataset_id == "MODIS/061/MOD13A2"
        assert result.temporal_kind == "observation"
        assert result.quality_level == "good"
        assert len(result.bands) == 1

    def test_serialize_evidence_item(self) -> None:
        item = _make_evidence_item()
        result = agriculture._serialize_evidence_item(item)
        assert result.metric_key == "ndvi_anomaly_absolute"
        assert result.value == pytest.approx(-0.15)
        assert result.is_usable is True
        assert result.temporal_start == "2024-07-01"
        assert result.provenance is not None

    def test_serialize_evidence_item_unavailable(self) -> None:
        item = EvidenceItem(
            metric_key="missing_metric",
            value=None,
            unit="index",
            status=EvidenceStatus.UNAVAILABLE,
            temporal_start=None,
            temporal_end=None,
            quality_level=QualityLevel.UNAVAILABLE,
            provenance=None,
            source_dataset_id=None,
        )
        result = agriculture._serialize_evidence_item(item)
        assert result.is_usable is False
        assert result.value is None
        assert result.status == "unavailable"

    def test_serialize_evidence_bundle(self) -> None:
        bundle = _make_water_bundle()
        result = agriculture._serialize_evidence_bundle(bundle)
        assert result.name == "water"
        assert len(result.items) == 3
        assert result.sufficiency is not None
        assert result.sufficiency.level == "sufficient"

    def test_serialize_synthesis_statement(self) -> None:
        stmt = SynthesisStatement(
            rule_id="water_below_baseline",
            domain=SynthesisDomain.WATER,
            pattern=PatternState.BELOW_CONTEXT,
            statement="Below baseline.",
            evidence_keys=("precipitation_anomaly", "soil_moisture_rootzone_anomaly"),
            evidence_values={"precipitation_anomaly": -0.8},
            scientific_basis="Basis.",
            limitations=("Limitation.",),
        )
        result = agriculture._serialize_synthesis_statement(stmt)
        assert result.rule_id == "water_below_baseline"
        assert result.domain == "water"
        assert result.pattern == "below_context"
        assert result.evidence_values == {"precipitation_anomaly": -0.8}

    def test_serialize_domain_summary(self) -> None:
        summary = DomainSummary(
            domain=SynthesisDomain.WATER,
            statements=[
                SynthesisStatement(
                    rule_id="water_below_baseline",
                    domain=SynthesisDomain.WATER,
                    pattern=PatternState.BELOW_CONTEXT,
                    statement="Below baseline.",
                    evidence_keys=("precipitation_anomaly",),
                    evidence_values={},
                    scientific_basis="Basis.",
                    limitations=("Limitation.",),
                )
            ],
            sufficiency=SufficiencyLevel.SUFFICIENT,
        )
        result = agriculture._serialize_domain_summary(summary)
        assert result.domain == "water"
        assert result.statement_count == 1
        assert result.statements[0].rule_id == "water_below_baseline"

    def test_serialize_synthesis_full(self) -> None:
        bundles = {
            SynthesisDomain.WATER: _make_water_bundle(),
            SynthesisDomain.VEGETATION: _make_veg_bundle(),
        }
        engine = SynthesisEngine()
        synthesis = engine.synthesise(
            bundles,
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        result = agriculture._serialize_synthesis(synthesis, bundles)
        assert result.time_start == "2024-07-01"
        assert result.time_end == "2024-07-31"
        assert "water" in result.domain_summaries
        assert "vegetation" in result.domain_summaries
        assert "water" in result.evidence_bundles
        assert result.generated_at is not None


# ---------------------------------------------------------------------------
# 6. Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_request(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        agriculture._validate_request(req)  # Should not raise

    def test_invalid_date_format(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="not-a-date",
            end_date="2024-07-31",
        )
        with pytest.raises(ValidationError):
            agriculture._validate_request(req)

    def test_end_before_start(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-31",
            end_date="2024-07-01",
        )
        with pytest.raises(DateRangeError):
            agriculture._validate_request(req)

    def test_same_date(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-01",
        )
        with pytest.raises(DateRangeError):
            agriculture._validate_request(req)

    def test_invalid_domain(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "invalid_domain"],
        )
        with pytest.raises(ValidationError):
            agriculture._validate_request(req)

    def test_valid_domains(self) -> None:
        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "water", "thermal"],
        )
        agriculture._validate_request(req)  # Should not raise


# ---------------------------------------------------------------------------
# 7. Domain mapping tests
# ---------------------------------------------------------------------------


class TestDomainMapping:
    def test_vegetation_keys(self) -> None:
        keys = agriculture._domain_to_metric_keys(["vegetation"])
        assert "ndvi" in keys
        assert "evi" in keys

    def test_water_keys(self) -> None:
        keys = agriculture._domain_to_metric_keys(["water"])
        assert "ndwi" in keys
        assert "ndmi" in keys

    def test_multiple_domains(self) -> None:
        keys = agriculture._domain_to_metric_keys(["vegetation", "water"])
        assert len(keys) > 2

    def test_metric_key_to_domain_vegetation(self) -> None:
        assert agriculture._metric_key_to_domain("ndvi") == "vegetation"
        assert agriculture._metric_key_to_domain("evi") == "vegetation"

    def test_metric_key_to_domain_water(self) -> None:
        assert agriculture._metric_key_to_domain("ndwi") == "water"
        assert agriculture._metric_key_to_domain("ndmi") == "water"

    def test_metric_key_to_domain_thermal(self) -> None:
        assert agriculture._metric_key_to_domain("land_surface_temperature_day") == "thermal"

    def test_metric_key_to_domain_soil(self) -> None:
        assert agriculture._metric_key_to_domain("soil_moisture_rootzone") == "soil"

    def test_metric_key_to_domain_climate(self) -> None:
        assert agriculture._metric_key_to_domain("vpd") == "climate"

    def test_metric_key_to_domain_crop(self) -> None:
        assert agriculture._metric_key_to_domain("temporary_crop_context") == "crop"

    def test_metric_key_to_domain_phenology(self) -> None:
        assert agriculture._metric_key_to_domain("vegetation_season_onset") == "phenology"

    def test_metric_key_to_domain_productivity(self) -> None:
        assert agriculture._metric_key_to_domain("seasonal_vegetation_productivity_indicator") == "productivity"

    def test_metric_key_to_domain_history(self) -> None:
        assert agriculture._metric_key_to_domain("ndvi_anomaly_absolute") == "history"

    def test_metric_key_to_domain_terrain(self) -> None:
        assert agriculture._metric_key_to_domain("elevation") == "terrain"

    def test_metric_key_to_domain_stress(self) -> None:
        assert agriculture._metric_key_to_domain("vpd_anomaly") == "stress"

    def test_metric_key_to_domain_irrigation(self) -> None:
        assert agriculture._metric_key_to_domain("precipitation_cumulative") == "irrigation"

    def test_metric_key_to_domain_landcover(self) -> None:
        assert agriculture._metric_key_to_domain("land_cover_class") == "landcover"

    def test_metric_key_to_domain_unknown_returns_none(self) -> None:
        assert agriculture._metric_key_to_domain("unknown_metric") is None


# ---------------------------------------------------------------------------
# 8. Evidence bundle parsing tests
# ---------------------------------------------------------------------------


class TestEvidenceBundleParsing:
    def test_parse_empty_bundles(self) -> None:
        result = agriculture._parse_evidence_bundles({})
        assert len(result) == 0

    def test_parse_valid_bundle(self) -> None:
        raw = {
            "water": {
                "items": [
                    {
                        "metric_key": "precipitation_anomaly",
                        "value": -0.8,
                        "unit": "mm/day",
                        "status": "modelled",
                        "quality": "good",
                        "source_dataset": "era5_land",
                    }
                ]
            }
        }
        result = agriculture._parse_evidence_bundles(raw)
        assert "water" in result
        bundle = result[SynthesisDomain.WATER]
        assert len(bundle.items) == 1
        assert bundle.items[0].metric_key == "precipitation_anomaly"
        assert bundle.items[0].value == pytest.approx(-0.8)

    def test_parse_invalid_domain_ignored(self) -> None:
        raw = {
            "invalid_domain": {
                "items": [{"metric_key": "test", "value": 0.0}]
            }
        }
        result = agriculture._parse_evidence_bundles(raw)
        assert len(result) == 0

    def test_parse_multiple_domains(self) -> None:
        raw = {
            "water": {
                "items": [{"metric_key": "precip_anomaly", "value": -0.5, "unit": "mm"}]
            },
            "vegetation": {
                "items": [{"metric_key": "ndvi_anomaly", "value": -0.2, "unit": "index"}]
            },
        }
        result = agriculture._parse_evidence_bundles(raw)
        assert len(result) == 2
        assert SynthesisDomain.WATER in result
        assert SynthesisDomain.VEGETATION in result


# ---------------------------------------------------------------------------
# 9. API endpoint tests
# ---------------------------------------------------------------------------


class TestAgricultureHealthEndpoint:
    def test_health_returns_200(self) -> None:
        response = client.get("/api/v1/agriculture/health")
        assert response.status_code == 200

    def test_health_structure(self) -> None:
        response = client.get("/api/v1/agriculture/health")
        data = response.json()
        assert "status" in data
        assert "metrics_registered" in data
        assert "evidence_layer" in data
        assert "synthesis_layer" in data
        assert "message" in data

    def test_health_json_serializable(self) -> None:
        response = client.get("/api/v1/agriculture/health")
        data = response.json()
        json_str = json.dumps(data)
        assert len(json_str) > 0


class TestAgricultureHealthRegistryRegression:
    """Regression for the stale ``from app.services.agriculture import
    metric_keys`` import inside ``agriculture_health``.

    The package ``__init__`` intentionally exposes only types plus
    ``register_all_metrics``/``ensure_registered``; ``metric_keys`` lives in
    ``app.services.agriculture.catalog``. The stale package-level import
    raised ImportError at request time, which the endpoint swallowed into
    ``status="degraded"`` with the ImportError text — the 200 + structure
    assertions above passed despite the bug, so this class locks the
    healthy behavior explicitly.
    """

    def test_health_reports_ok_with_registered_metrics(self) -> None:
        response = client.get("/api/v1/agriculture/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok", data
        assert data["metrics_registered"] > 0
        assert "ImportError" not in data["message"]
        assert "metric_keys" not in data["message"]

    def test_metric_keys_canonical_source_is_catalog(self) -> None:
        from app.services.agriculture import catalog

        assert callable(catalog.metric_keys)
        assert len(catalog.metric_keys()) > 0

    def test_metric_keys_stays_catalog_scoped(self) -> None:
        import app.services.agriculture as pkg

        assert "metric_keys" not in vars(pkg), (
            "metric_keys must stay catalog-scoped; do not add a "
            "package-level compatibility alias"
        )


class TestAgricultureAnalysisEndpoint:
    def test_analysis_invalid_date_format(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                "start_date": "not-a-date",
                "end_date": "2024-07-31",
            },
        )
        assert response.status_code == 400

    def test_analysis_end_before_start(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                "start_date": "2024-07-31",
                "end_date": "2024-07-01",
            },
        )
        assert response.status_code == 400

    def test_analysis_invalid_domain(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                "start_date": "2024-07-01",
                "end_date": "2024-07-31",
                "domains": ["invalid_domain"],
            },
        )
        assert response.status_code == 400

    def test_analysis_error_response_structure(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                "start_date": "not-a-date",
                "end_date": "2024-07-31",
            },
        )
        data = response.json()
        assert "error" in data
        assert isinstance(data["error"], str)
        assert len(data["error"]) > 0


class TestSynthesisOnlyEndpoint:
    def test_synthesis_empty_bundles(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {},
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_sufficiency"] == "insufficient"
        assert data["available_domains"] == []

    def test_synthesis_with_evidence(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                            {
                                "metric_key": "evapotranspiration_anomaly",
                                "value": -0.4,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "modis_et",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "water" in data["domain_summaries"]
        water_summary = data["domain_summaries"]["water"]
        assert water_summary["statement_count"] >= 1

    def test_synthesis_response_structure(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                            {
                                "metric_key": "evapotranspiration_anomaly",
                                "value": -0.4,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "modis_et",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        # Verify all expected top-level keys
        assert "request_id" in data
        assert "time_start" in data
        assert "time_end" in data
        assert "domain_summaries" in data
        assert "cross_domain_statements" in data
        assert "overall_sufficiency" in data
        assert "evidence_bundles" in data
        assert "available_domains" in data
        assert "unavailable_domains" in data
        assert "limitations" in data
        assert "metadata" in data
        assert "generated_at" in data

    def test_synthesis_statement_traceability(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                            {
                                "metric_key": "evapotranspiration_anomaly",
                                "value": -0.4,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "modis_et",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        water = data["domain_summaries"]["water"]
        for stmt in water["statements"]:
            # Every statement must have traceability
            assert "rule_id" in stmt
            assert "domain" in stmt
            assert "pattern" in stmt
            assert "statement" in stmt
            assert "evidence_keys" in stmt
            assert "scientific_basis" in stmt
            assert "limitations" in stmt
            assert len(stmt["evidence_keys"]) > 0
            assert len(stmt["scientific_basis"]) > 0
            assert len(stmt["limitations"]) > 0

    def test_synthesis_json_serializable(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        # Should be fully JSON serializable
        json_str = json.dumps(data, default=str)
        assert len(json_str) > 0
        # Should not contain NaN or Infinity
        assert "NaN" not in json_str
        assert "Infinity" not in json_str

    def test_synthesis_evidence_preserved(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        bundles = data["evidence_bundles"]
        assert "water" in bundles
        water_bundle = bundles["water"]
        assert len(water_bundle["items"]) == 2
        # Verify evidence items preserve values
        items_by_key = {i["metric_key"]: i for i in water_bundle["items"]}
        assert items_by_key["precipitation_anomaly"]["value"] == pytest.approx(-0.8)
        assert items_by_key["soil_moisture_rootzone_anomaly"]["value"] == pytest.approx(-0.6)
        # Verify sufficiency is present
        assert water_bundle["sufficiency"] is not None
        assert water_bundle["sufficiency"]["level"] == "sufficient"

    def test_synthesis_multiple_domains(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                            {
                                "metric_key": "evapotranspiration_anomaly",
                                "value": -0.4,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "modis_et",
                            },
                        ]
                    },
                    "vegetation": {
                        "items": [
                            {
                                "metric_key": "ndvi_anomaly_absolute",
                                "value": -0.15,
                                "unit": "index",
                                "status": "derived",
                                "quality": "good",
                                "source_dataset": "modis_ndvi",
                            },
                            {
                                "metric_key": "ndvi_anomaly_relative",
                                "value": -0.25,
                                "unit": "index",
                                "status": "derived",
                                "quality": "good",
                                "source_dataset": "sentinel2_ndvi",
                            },
                        ]
                    },
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        assert "water" in data["domain_summaries"]
        assert "vegetation" in data["domain_summaries"]
        assert "water" in data["available_domains"]
        assert "vegetation" in data["available_domains"]

    def test_synthesis_unavailable_reason_preserved(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": None,
                                "unit": "mm/day",
                                "status": "unavailable",
                                "quality": "unavailable",
                                "source_dataset": None,
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        water = data["domain_summaries"]["water"]
        assert len(water["unavailable_evidence"]) > 0
        assert "precipitation_anomaly" in water["unavailable_evidence"]


# ---------------------------------------------------------------------------
# 10. No-secret-leak tests
# ---------------------------------------------------------------------------


class TestNoSecretLeak:
    def test_health_no_secrets(self) -> None:
        response = client.get("/api/v1/agriculture/health")
        data = response.json()
        json_str = json.dumps(data)
        # Should not contain filesystem paths, credentials, or internal info
        assert "password" not in json_str.lower()
        assert "secret" not in json_str.lower()
        assert "token" not in json_str.lower()
        assert "credential" not in json_str.lower()

    def test_synthesis_no_secrets(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        json_str = json.dumps(data, default=str)
        assert "password" not in json_str.lower()
        assert "secret" not in json_str.lower()
        assert "token" not in json_str.lower()
        assert "service_account" not in json_str.lower()


# ---------------------------------------------------------------------------
# 11. Determinism tests
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_synthesis_deterministic(self) -> None:
        payload = {
            "evidence_bundles": {
                "water": {
                    "items": [
                        {
                            "metric_key": "precipitation_anomaly",
                            "value": -0.8,
                            "unit": "mm/day",
                            "status": "modelled",
                            "quality": "good",
                            "source_dataset": "era5_land",
                        },
                        {
                            "metric_key": "soil_moisture_rootzone_anomaly",
                            "value": -0.6,
                            "unit": "index",
                            "status": "modelled",
                            "quality": "good",
                            "source_dataset": "smap_l4",
                        },
                    ]
                }
            },
            "time_start": "2024-07-01",
            "time_end": "2024-07-31",
        }
        r1 = client.post(
            "/api/v1/agriculture/analysis/synthesis-only", json=payload
        ).json()
        r2 = client.post(
            "/api/v1/agriculture/analysis/synthesis-only", json=payload
        ).json()
        # Everything except generated_at and request_id should be identical
        assert r1["overall_sufficiency"] == r2["overall_sufficiency"]
        assert r1["domain_summaries"] == r2["domain_summaries"]
        assert r1["cross_domain_statements"] == r2["cross_domain_statements"]
        assert r1["available_domains"] == r2["available_domains"]


# ---------------------------------------------------------------------------
# 12. Scientific safety tests
# ---------------------------------------------------------------------------


class TestScientificSafety:
    def test_no_health_score_in_response(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        json_str = json.dumps(data, default=str).lower()
        # Should not contain health score, confidence score, or recommendation
        assert "health_score" not in json_str
        assert "confidence_score" not in json_str
        assert "recommendation" not in json_str
        assert "diagnosis" not in json_str
        assert "risk_score" not in json_str

    def test_statements_are_descriptive(self) -> None:
        response = client.post(
            "/api/v1/agriculture/analysis/synthesis-only",
            json={
                "evidence_bundles": {
                    "water": {
                        "items": [
                            {
                                "metric_key": "precipitation_anomaly",
                                "value": -0.8,
                                "unit": "mm/day",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "era5_land",
                            },
                            {
                                "metric_key": "soil_moisture_rootzone_anomaly",
                                "value": -0.6,
                                "unit": "index",
                                "status": "modelled",
                                "quality": "good",
                                "source_dataset": "smap_l4",
                            },
                        ]
                    }
                },
                "time_start": "2024-07-01",
                "time_end": "2024-07-31",
            },
        )
        data = response.json()
        for domain_summary in data["domain_summaries"].values():
            for stmt in domain_summary.get("statements", []):
                # Every statement must have scientific basis
                assert len(stmt["scientific_basis"]) > 0
                # Every statement must have limitations
                assert len(stmt["limitations"]) > 0


# ---------------------------------------------------------------------------
# 13. Success-path API test (S.1.5 / S.1.6)
# ---------------------------------------------------------------------------


class TestAnalysisSuccessPath:
    """Real success-path test for POST /api/v1/agriculture/analysis.

    Exercises the full pipeline: valid request -> metric execution
    (mocked EE) -> evidence construction -> domain grouping ->
    synthesis -> API serialization -> successful response.
    """

    def test_full_analysis_success(self) -> None:
        """A valid analysis request returns structured, grouped output."""
        from app.services.agriculture.catalog import get_metric

        # Mock the EE geometry creation and metric execution
        mock_geometry = MagicMock()

        # Build mock outcomes that span multiple domains
        def _make_outcome(key: str, value: float, domain: str) -> MagicMock:
            """Create a mock ExecutionOutcome for a metric."""
            metric = get_metric(key)
            result = MetricResult(
                metric_key=key,
                display_name=metric.display_name,
                display_name_fa=metric.display_name_fa,
                status="ok",
                value=value,
                unit=metric.unit,
                provenance=Provenance(
                    source_dataset_id=metric.dataset_ids[0] if metric.dataset_ids else "unknown",
                    source_dataset_name=metric.display_name,
                    bands=[],
                    formula="",
                    unit=metric.unit,
                    spatial_resolution="1 km",
                    temporal_resolution="16-day",
                    measurement_basis=QualityLevel.GOOD,
                    quality_level=QualityLevel.GOOD,
                    temporal_kind=TemporalKind.OBSERVATION,
                    requested_start="2024-07-01",
                    requested_end="2024-07-31",
                ),
                warnings=[],
            )
            outcome = MagicMock()
            outcome.result = result
            outcome.metric_key = key
            return outcome

        # Select metrics from domains that the old heuristic misclassified
        # These must come from the registry's actual domain declarations
        test_metrics = {
            # Soil: old heuristic might misclassify soil_* metrics
            "soil_moisture_rootzone": 0.25,
            # Terrain: old heuristic had no terrain handling at all
            "elevation": 1200.0,
            # Water: ndmi is a water index, old heuristic put it in vegetation
            "ndmi": 0.3,
            # Stress: old heuristic had no stress handling
            "vpd_anomaly": 1.5,
            # Irrigation: old heuristic had no irrigation handling
            "precipitation_cumulative": 45.0,
            # Landcover: old heuristic had no landcover handling
            "land_cover_class": 10.0,
            # Vegetation: should stay vegetation
            "ndvi": 0.65,
        }

        outcomes = {}
        for key, value in test_metrics.items():
            outcomes[key] = _make_outcome(key, value, "")

        with patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=mock_geometry,
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            response = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        assert response.status_code == 200
        data = response.json()

        # Verify top-level structure
        assert "domain_summaries" in data
        assert "evidence_bundles" in data
        assert "overall_sufficiency" in data
        assert "available_domains" in data
        assert "metadata" in data

        # Verify evidence is grouped under the registry's actual domain
        bundles = data["evidence_bundles"]

        # soil_moisture_rootzone has domain "soil" in the registry
        assert "soil" in bundles, (
            "soil_moisture_rootzone should be grouped under 'soil', "
            f"got domains: {list(bundles.keys())}"
        )
        soil_keys = [i["metric_key"] for i in bundles["soil"]["items"]]
        assert "soil_moisture_rootzone" in soil_keys

        # elevation has domain "terrain" in the registry
        assert "terrain" in bundles, (
            "elevation should be grouped under 'terrain', "
            f"got domains: {list(bundles.keys())}"
        )
        terrain_keys = [i["metric_key"] for i in bundles["terrain"]["items"]]
        assert "elevation" in terrain_keys

        # ndmi has domain "water" in the registry (NOT vegetation)
        assert "water" in bundles, (
            "ndmi should be grouped under 'water', "
            f"got domains: {list(bundles.keys())}"
        )
        water_keys = [i["metric_key"] for i in bundles["water"]["items"]]
        assert "ndmi" in water_keys

        # vpd_anomaly has domain "stress" in the registry
        assert "stress" in bundles, (
            "vpd_anomaly should be grouped under 'stress', "
            f"got domains: {list(bundles.keys())}"
        )
        stress_keys = [i["metric_key"] for i in bundles["stress"]["items"]]
        assert "vpd_anomaly" in stress_keys

        # precipitation_cumulative has domain "irrigation" in the registry
        assert "irrigation" in bundles, (
            "precipitation_cumulative should be grouped under 'irrigation', "
            f"got domains: {list(bundles.keys())}"
        )
        irrigation_keys = [i["metric_key"] for i in bundles["irrigation"]["items"]]
        assert "precipitation_cumulative" in irrigation_keys

        # land_cover_class has domain "landcover" in the registry
        assert "landcover" in bundles, (
            "land_cover_class should be grouped under 'landcover', "
            f"got domains: {list(bundles.keys())}"
        )
        landcover_keys = [i["metric_key"] for i in bundles["landcover"]["items"]]
        assert "land_cover_class" in landcover_keys

        # ndvi has domain "vegetation" in the registry
        assert "vegetation" in bundles, (
            "ndvi should be grouped under 'vegetation', "
            f"got domains: {list(bundles.keys())}"
        )
        veg_keys = [i["metric_key"] for i in bundles["vegetation"]["items"]]
        assert "ndvi" in veg_keys

        # Verify provenance survives serialization
        for bundle_data in bundles.values():
            for item in bundle_data["items"]:
                if item.get("provenance") is not None:
                    prov = item["provenance"]
                    assert "source_dataset_id" in prov
                    assert "temporal_kind" in prov

    def test_analysis_with_domain_filter(self) -> None:
        """Domain filtering works with the new registry-based lookup."""
        from app.services.agriculture.catalog import get_metric

        mock_geometry = MagicMock()

        def _make_outcome(key: str, value: float) -> MagicMock:
            metric = get_metric(key)
            result = MetricResult(
                metric_key=key,
                display_name=metric.display_name,
                display_name_fa=metric.display_name_fa,
                status="ok",
                value=value,
                unit=metric.unit,
                provenance=Provenance(
                    source_dataset_id=metric.dataset_ids[0] if metric.dataset_ids else "unknown",
                    source_dataset_name=metric.display_name,
                    bands=[],
                    formula="",
                    unit=metric.unit,
                    spatial_resolution="1 km",
                    temporal_resolution="16-day",
                    measurement_basis=QualityLevel.GOOD,
                    quality_level=QualityLevel.GOOD,
                    temporal_kind=TemporalKind.OBSERVATION,
                    requested_start="2024-07-01",
                    requested_end="2024-07-31",
                ),
                warnings=[],
            )
            outcome = MagicMock()
            outcome.result = result
            return outcome

        outcomes = {
            "ndvi": _make_outcome("ndvi", 0.65),
            "soil_moisture_rootzone": _make_outcome("soil_moisture_rootzone", 0.25),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=mock_geometry,
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            response = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 14. Domain mapping regression tests (S.1.7)
# ---------------------------------------------------------------------------


class TestDomainMappingRegression:
    """Regression tests ensuring the registry drives domain classification.

    These tests would fail under the old heuristic implementation.
    """

    def test_ndmi_is_water_not_vegetation(self) -> None:
        """ndmi is a water index (Moisture Index), not vegetation.

        The old heuristic classified ndmi as vegetation because it
        matched the 'ndmi' substring in the vegetation check. The
        registry declares ndmi with domain='water'.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("ndmi")
        assert metric.domain == "water"

        domain = agriculture._metric_key_to_domain("ndmi")
        assert domain == "water"

    def test_elevation_is_terrain(self) -> None:
        """elevation is a terrain metric.

        The old heuristic had no terrain handling and would default
        to vegetation. The registry declares elevation with
        domain='terrain'.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("elevation")
        assert metric.domain == "terrain"

        domain = agriculture._metric_key_to_domain("elevation")
        assert domain == "terrain"

    def test_vpd_anomaly_is_stress(self) -> None:
        """vpd_anomaly is a stress metric.

        The old heuristic classified vpd_anomaly as climate because it
        matched 'vpd'. The registry declares vpd_anomaly with
        domain='stress'.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("vpd_anomaly")
        assert metric.domain == "stress"

        domain = agriculture._metric_key_to_domain("vpd_anomaly")
        assert domain == "stress"

    def test_precipitation_cumulative_is_irrigation(self) -> None:
        """precipitation_cumulative is an irrigation metric.

        The old heuristic classified precipitation_cumulative as water
        because it matched 'precipitation'. The registry declares it
        with domain='irrigation'.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("precipitation_cumulative")
        assert metric.domain == "irrigation"

        domain = agriculture._metric_key_to_domain("precipitation_cumulative")
        assert domain == "irrigation"

    def test_land_cover_class_is_landcover(self) -> None:
        """land_cover_class is a landcover metric.

        The old heuristic had no landcover handling and would default
        to vegetation. The registry declares it with
        domain='landcover'.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("land_cover_class")
        assert metric.domain == "landcover"

        domain = agriculture._metric_key_to_domain("land_cover_class")
        assert domain == "landcover"

    def test_soil_moisture_surface_is_soil(self) -> None:
        """soil_moisture_surface is a soil metric.

        The old heuristic correctly classified this, but now it must
        come from the registry, not from name matching.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("soil_moisture_surface")
        assert metric.domain == "soil"

        domain = agriculture._metric_key_to_domain("soil_moisture_surface")
        assert domain == "soil"

    def test_ndvi_anomaly_absolute_is_history(self) -> None:
        """ndvi_anomaly_absolute is a history metric.

        The old heuristic classified it as 'historical' (matching
        'anomaly'). The registry declares it with domain='history'.
        The API normalises 'history' to 'historical' for
        SynthesisDomain compatibility.
        """
        from app.services.agriculture.catalog import get_metric

        metric = get_metric("ndvi_anomaly_absolute")
        assert metric.domain == "history"

        domain = agriculture._metric_key_to_domain("ndvi_anomaly_absolute")
        assert domain == "history"

    def test_registry_driven_not_name_based(self) -> None:
        """Domain comes from registry, not from metric name prefixes.

        A metric whose name contains 'soil' but is NOT in the soil
        domain must NOT be classified as soil just because of its name.
        """
        from app.services.agriculture.catalog import get_metric

        # soil_water_content_ratio is a stress metric, not soil
        metric = get_metric("soil_water_content_ratio")
        assert metric.domain == "stress"

        domain = agriculture._metric_key_to_domain("soil_water_content_ratio")
        assert domain == "stress"

    def test_unknown_metric_returns_none(self) -> None:
        """Unknown metrics return None, not a default domain."""
        domain = agriculture._metric_key_to_domain("nonexistent_metric_xyz")
        assert domain is None

    def test_all_registered_metrics_have_valid_domain(self) -> None:
        """Every registered metric has a domain in MetricDomain.ALL."""
        from app.services.agriculture.base import MetricDomain
        from app.services.agriculture.catalog import all_metrics

        for metric in all_metrics():
            assert metric.domain in MetricDomain.ALL, (
                f"Metric {metric.key} has invalid domain {metric.domain!r}"
            )


# ---------------------------------------------------------------------------
# 15. Domain completeness contract test (S.1.8)
# ---------------------------------------------------------------------------


class TestDomainCompleteness:
    """Contract test ensuring backend and frontend domain sets are aligned.

    Prevents the class of defect where the backend adds a domain and
    the frontend silently falls back to raw key display.
    """

    def test_all_backend_domains_have_frontend_metadata(self) -> None:
        """Every MetricDomain value has a corresponding DOMAIN_META entry.

        The backend uses "history" while the API normalises it to
        "historical" for SynthesisDomain compatibility. The frontend
        only needs to cover the normalised form.
        """
        from app.services.agriculture.base import MetricDomain

        # Read DOMAIN_META from the frontend types file
        import re

        ts_path = (
            __import__("pathlib").Path(__file__).resolve().parents[3]
            / "frontend" / "src" / "types" / "index.ts"
        )
        ts_content = ts_path.read_text(encoding="utf-8")

        # Extract all keys from DOMAIN_META
        meta_keys = set(re.findall(r"^\s+(\w+):\s*\{", ts_content, re.MULTILINE))

        # The API normalises "history" -> "historical", so the frontend
        # only needs "historical", not "history".
        backend_to_frontend = {"history": "historical"}

        for domain in MetricDomain.ALL:
            frontend_key = backend_to_frontend.get(domain, domain)
            assert frontend_key in meta_keys, (
                f"Backend domain {domain!r} (frontend: {frontend_key!r}) "
                f"is missing from frontend DOMAIN_META"
            )

    def test_all_synthesis_domains_have_frontend_metadata(self) -> None:
        """Every SynthesisDomain value has a corresponding DOMAIN_META entry."""
        import re

        ts_path = (
            __import__("pathlib").Path(__file__).resolve().parents[3]
            / "frontend" / "src" / "types" / "index.ts"
        )
        ts_content = ts_path.read_text(encoding="utf-8")

        meta_keys = set(re.findall(r"^\s+(\w+):\s*\{", ts_content, re.MULTILINE))

        for member in SynthesisDomain:
            assert member.value in meta_keys, (
                f"SynthesisDomain {member.name!r} ({member.value!r}) "
                f"is missing from frontend DOMAIN_META"
            )

    def test_valid_domains_match_metric_domain_set(self) -> None:
        """VALID_DOMAINS covers all MetricDomain values (minus history)."""
        from app.services.agriculture.base import MetricDomain

        # VALID_DOMAINS uses "historical" while MetricDomain uses "history"
        expected = set(MetricDomain.ALL) - {"history"} | {"historical"}
        assert agriculture.VALID_DOMAINS == expected, (
            f"VALID_DOMAINS mismatch: "
            f"missing={expected - agriculture.VALID_DOMAINS}, "
            f"extra={agriculture.VALID_DOMAINS - expected}"
        )

    def test_synthesis_domain_covers_metric_domains(self) -> None:
        """SynthesisDomain covers all MetricDomain values (minus history)."""
        from app.services.agriculture.base import MetricDomain

        synthesis_values = {m.value for m in SynthesisDomain}
        # SynthesisDomain uses "historical" while MetricDomain uses "history"
        expected = set(MetricDomain.ALL) - {"history"} | {"historical"}
        # SynthesisDomain also has "cross_domain" which MetricDomain doesn't
        assert expected.issubset(synthesis_values), (
            f"SynthesisDomain missing: {expected - synthesis_values}"
        )
