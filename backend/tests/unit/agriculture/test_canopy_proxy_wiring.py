"""CD-5 production-wiring tests for the middle-canopy dryness proxy.

Proves the already-registered CD-4 metric flows through the normal
production path untouched: registry domain, API evidence
serialization, deterministic cache keys, and synthesis routing via
five explicit proxy-state rules.  No new metric logic is exercised
here beyond wiring; CD-4 semantics are asserted intact.

No Earth Engine calls.  No database.  No network beyond the local
FastAPI TestClient with mocked execution.
"""

from __future__ import annotations

import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.agriculture.base import MetricContext
from app.services.agriculture.canopy_proxy import (
    MiddleCanopyDrynessProxyMetric,
)
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    has_metric,
)
from app.services.agriculture.evidence import EvidenceBundle, EvidenceItem
from app.services.agriculture.synthesis import (
    CANOPY_PROXY_RULES,
    DEFAULT_RULES,
    PatternState,
    SynthesisDomain,
    SynthesisEngine,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _register_metrics():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    yield


def _proxy_provenance(**overrides) -> Provenance:
    fields = {
        "source_dataset_id": "COPERNICUS/S2_SR_HARMONIZED",
        "source_dataset_name": "Sentinel-2",
        "bands": ["B8", "B11", "B5", "VV", "VH"],
        "formula": "concordance of ndmi/msi/ndre signs with radar context",
        "unit": "state",
        "spatial_resolution": "10 m",
        "temporal_resolution": "mixed",
        "aggregation_method": "votes counted, never averaged",
        "measurement_basis": MeasurementBasis.PROXY,
        "quality_level": QualityLevel.GOOD,
        "temporal_kind": TemporalKind.OBSERVATION,
        "requested_start": "2024-07-01",
        "requested_end": "2024-07-31",
        "limitations": [
            "This is a multi-sensor evidence proxy and does not directly "
            "measure, isolate, or quantify middle-canopy leaves."
        ],
        "caveats": [
            "optical: ndmi_anomaly=-0.1000 (stress vote, quality good)",
            "radar context: 4 of 4 usable",
            "concordance state: CONCORDANT_STRESS (3)",
            "confidence: HIGH (categorical grade of support, not a probability)",
        ],
        "citation": "CD-4 proxy",
    }
    fields.update(overrides)
    return Provenance(**fields)


def _proxy_result(value: Optional[float] = 3.0, **overrides) -> MetricResult:
    metric = MiddleCanopyDrynessProxyMetric()
    if value is None:
        return MetricResult.insufficient(
            metric_key=metric.key,
            display_name=metric.display_name,
            display_name_fa=metric.display_name_fa,
            message="no evidence",
            unit=metric.unit,
            provenance=_proxy_provenance(
                quality_level=QualityLevel.INSUFFICIENT, **overrides
            ),
        )
    return MetricResult(
        metric_key=metric.key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status="ok",
        value=value,
        unit=metric.unit,
        provenance=_proxy_provenance(**overrides),
        warnings=[],
    )


def _outcome(result: MetricResult) -> MagicMock:
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = result.metric_key
    return outcome


def _veg_bundle_with_proxy(value: Optional[float]) -> EvidenceBundle:
    from app.api.v1.agriculture import _build_evidence_bundles

    outcomes = {"middle_canopy_dryness_proxy": _outcome(_proxy_result(value))}
    bundles = _build_evidence_bundles(outcomes)
    assert SynthesisDomain.VEGETATION in bundles
    return bundles[SynthesisDomain.VEGETATION]


# ---------------------------------------------------------------------------
# 1. Registration intact (CD-4 untouched)
# ---------------------------------------------------------------------------


def test_proxy_registration_intact():
    assert has_metric("middle_canopy_dryness_proxy")
    metric = get_metric("middle_canopy_dryness_proxy")
    assert metric.domain == "vegetation"
    assert metric.measurement_basis is MeasurementBasis.PROXY
    assert metric.unit == "state"
    assert metric.key == "middle_canopy_dryness_proxy"


# ---------------------------------------------------------------------------
# 2. API exposure through the normal registered-metric flow
# ---------------------------------------------------------------------------


def test_analysis_api_exposes_proxy_in_vegetation_bundle():
    outcomes = {"middle_canopy_dryness_proxy": _outcome(_proxy_result(3.0))}
    with patch(
        "app.utils.geometry.create_ee_geometry",
        return_value=MagicMock(),
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
    items = data["evidence_bundles"]["vegetation"]["items"]
    proxy_items = [
        i for i in items if i["metric_key"] == "middle_canopy_dryness_proxy"
    ]
    assert len(proxy_items) == 1
    item = proxy_items[0]
    assert item["value"] == pytest.approx(3.0)
    assert item["unit"] == "state"
    assert item["status"] == "proxy"
    assert item["is_proxy"] is True
    assert item["provenance"]["measurement_basis"] == "proxy"
    caveats = " ".join(item["provenance"]["caveats"])
    assert "CONCORDANT_STRESS" in caveats
    assert "confidence: HIGH" in caveats
    limitations = " ".join(item["provenance"]["limitations"])
    assert "does not directly measure" in limitations


def test_analysis_api_domain_filter_keeps_proxy_under_vegetation():
    outcomes = {"middle_canopy_dryness_proxy": _outcome(_proxy_result(1.0))}
    with patch(
        "app.utils.geometry.create_ee_geometry",
        return_value=MagicMock(),
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
    keys = [
        i["metric_key"]
        for i in response.json()["evidence_bundles"]["vegetation"]["items"]
    ]
    assert "middle_canopy_dryness_proxy" in keys


def test_insufficient_proxy_serializes_without_value():
    # NOTE: geometry differs from the other API tests on purpose: the
    # analysis cache is process-global, so reusing an identical request
    # would return the earlier cached response instead of this one.
    outcomes = {"middle_canopy_dryness_proxy": _outcome(_proxy_result(None))}
    with patch(
        "app.utils.geometry.create_ee_geometry",
        return_value=MagicMock(),
    ), patch(
        "app.services.agriculture.executor.execute_metrics",
        return_value=(outcomes, []),
    ):
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [52.0, 36.0]},
                "start_date": "2024-07-01",
                "end_date": "2024-07-31",
            },
        )
    assert response.status_code == 200
    bundle = response.json()["evidence_bundles"]["vegetation"]
    assert "middle_canopy_dryness_proxy" in bundle["unavailable"]
    assert not [
        i
        for i in bundle["items"]
        if i["metric_key"] == "middle_canopy_dryness_proxy" and i["value"] is not None
    ]


def test_synthesis_only_endpoint_routes_proxy_statement():
    response = client.post(
        "/api/v1/agriculture/analysis/synthesis-only",
        json={
            "evidence_bundles": {
                "vegetation": {
                    "items": [
                        {
                            "metric_key": "middle_canopy_dryness_proxy",
                            "value": 3.0,
                            "unit": "state",
                            "status": "proxy",
                            "quality": "good",
                            "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
                            "display_name": "Middle-Canopy Dryness Proxy",
                        }
                    ]
                }
            },
            "time_start": "2024-07-01",
            "time_end": "2024-07-31",
        },
    )
    assert response.status_code == 200
    statements = response.json()["domain_summaries"]["vegetation"]["statements"]
    assert [s["rule_id"] for s in statements] == ["canopy_proxy_concordant_stress"]


# ---------------------------------------------------------------------------
# 3. Cache contract (unchanged path, documented by test)
# ---------------------------------------------------------------------------


def test_cache_key_covers_domains_windows_geometry():
    from app.api.v1.agriculture import _build_analysis_cache_key
    from app.schemas.agriculture import AgricultureAnalysisRequest

    def _request(**overrides) -> AgricultureAnalysisRequest:
        payload = {
            "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
            "start_date": "2024-07-01",
            "end_date": "2024-07-31",
        }
        payload.update(overrides)
        return AgricultureAnalysisRequest(**payload)

    base = _build_analysis_cache_key(_request())
    assert _build_analysis_cache_key(_request()) == base  # deterministic
    assert _build_analysis_cache_key(_request(domains=["vegetation"])) != base
    assert (
        _build_analysis_cache_key(_request(domains=["vegetation", "water"]))
        != _build_analysis_cache_key(_request(domains=["vegetation"]))
    )
    assert (
        _build_analysis_cache_key(
            _request(start_date="2024-06-01", end_date="2024-06-30")
        )
        != base
    )
    # The proxy adds no request parameters of its own, so the existing
    # five dimensions (geometry, dates, domains, cloud tolerance) fully
    # distinguish proxy-bearing analyses.
    assert (
        _build_analysis_cache_key(_request(cloud_max_percent=10.0)) != base
    )


# ---------------------------------------------------------------------------
# 4. Synthesis routing: one rule per proxy state, nothing else
# ---------------------------------------------------------------------------


def test_proxy_rules_consume_only_the_proxy_key():
    assert len(CANOPY_PROXY_RULES) == 5
    for rule in CANOPY_PROXY_RULES:
        assert rule.domain == SynthesisDomain.VEGETATION
        assert rule.inputs == ("middle_canopy_dryness_proxy",)
        assert len(rule.statement) > 0
        assert len(rule.scientific_basis) > 0
        assert len(rule.limitations) > 0


def test_each_reported_state_fires_exactly_its_rule():
    expected = {
        1.0: ("canopy_proxy_optical_stress_only", "below_context"),
        2.0: ("canopy_proxy_radar_context_only", "near_context"),
        3.0: ("canopy_proxy_concordant_stress", "coherent"),
        4.0: ("canopy_proxy_mixed", "mixed_evidence"),
        5.0: ("canopy_proxy_no_stress", "near_context"),
    }
    engine = SynthesisEngine()
    for value, (rule_id, pattern) in expected.items():
        bundle = _veg_bundle_with_proxy(value)
        summary = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
        fired = [s.rule_id for s in summary.statements if s.rule_id.startswith("canopy_proxy_")]
        assert fired == [rule_id], (value, fired)
        statement = next(
            s for s in summary.statements if s.rule_id == rule_id
        )
        assert statement.pattern.value == pattern
        assert statement.evidence_keys == ("middle_canopy_dryness_proxy",)
        assert statement.evidence_values == {"middle_canopy_dryness_proxy": value}
        assert "proxy" in statement.statement.lower()


def test_absent_proxy_fires_no_proxy_rule():
    engine = SynthesisEngine()
    bundle = _veg_bundle_with_proxy(None)
    summary = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
    assert [
        s.rule_id for s in summary.statements if s.rule_id.startswith("canopy_proxy_")
    ] == []


def test_proxy_rules_coexist_with_existing_vegetation_rules():
    """ndvi anomalies still drive the legacy vegetation statements
    independently of the proxy state."""
    from app.services.agriculture.evidence import EvidenceStatus
    from app.services.agriculture.types import QualityLevel as QL

    def _item(key: str, value: float) -> EvidenceItem:
        return EvidenceItem(
            metric_key=key,
            value=value,
            unit="index",
            status=EvidenceStatus.DERIVED,
            temporal_start=None,
            temporal_end=None,
            quality_level=QL.GOOD,
            provenance=None,
            source_dataset_id="x",
        )

    bundle = EvidenceBundle(
        name="vegetation",
        items=[
            _item("ndvi_anomaly_absolute", -0.20),
            _item("ndvi_anomaly_relative", -0.30),
            EvidenceItem(
                metric_key="middle_canopy_dryness_proxy",
                value=3.0,
                unit="state",
                status=EvidenceStatus.PROXY,
                temporal_start=None,
                temporal_end=None,
                quality_level=QL.GOOD,
                provenance=_proxy_provenance(),
                source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
            ),
        ],
    )
    summary = SynthesisEngine().evaluate_domain(SynthesisDomain.VEGETATION, bundle)
    fired = {s.rule_id for s in summary.statements}
    assert "vegetation_below_historical" in fired
    assert "canopy_proxy_concordant_stress" in fired


def test_proxy_statements_carry_basis_and_limitations():
    engine = SynthesisEngine()
    bundle = _veg_bundle_with_proxy(3.0)
    summary = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
    statement = next(
        s for s in summary.statements if s.rule_id == "canopy_proxy_concordant_stress"
    )
    assert len(statement.scientific_basis) > 0
    assert len(statement.limitations) > 0
    assert "evidence proxy" in statement.statement.lower()
    assert any("identifier" in limitation for limitation in statement.limitations)


def test_no_physical_quantity_in_proxy_routing():
    engine = SynthesisEngine()
    for value in (1.0, 2.0, 3.0, 4.0, 5.0):
        bundle = _veg_bundle_with_proxy(value)
        summary = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
        for statement in summary.statements:
            if not statement.rule_id.startswith("canopy_proxy_"):
                continue
            text = " ".join(
                [
                    statement.statement,
                    statement.scientific_basis,
                    *statement.limitations,
                    json.dumps(statement.evidence_values, default=str),
                ]
            ).lower()
            assert "%" not in text
            assert "probability" not in text
            # Percentage / moisture-content language appears only inside
            # the required denial, never as an affirmative claim.
            assert "not a magnitude, percentage, or moisture content" in text


def test_no_radar_direction_in_proxy_rules():
    """Rules may read the proxy state code only; radar keys must not
    appear as rule inputs anywhere in the proxy routing."""
    for rule in CANOPY_PROXY_RULES:
        assert "vv" not in rule.inputs
        assert "vh" not in rule.inputs
        assert "rvi" not in rule.inputs
        assert "ndmi" not in rule.inputs
        assert "msi" not in rule.inputs
        assert "ndre" not in rule.inputs


# ---------------------------------------------------------------------------
# 5. Source-scan safety contract
# ---------------------------------------------------------------------------


def test_no_temperature_moisture_or_ml_language_in_proxy_wiring():
    import app.services.agriculture.canopy_proxy as proxy_module
    import app.services.agriculture.synthesis as synthesis_module

    with open(proxy_module.__file__, encoding="utf-8") as handle:
        proxy_source = handle.read().lower()
    assert "canopy temperature" not in proxy_source
    assert "leaf_temp" not in proxy_source
    assert "machine learning" not in proxy_source
    assert "training data" not in proxy_source
    # The synthesis module legitimately discusses canopy temperature
    # in its pre-existing thermal disclaimers, so only the CD-5 proxy
    # rule block is scanned here.
    with open(synthesis_module.__file__, encoding="utf-8") as handle:
        synthesis_source = handle.read()
    start = synthesis_source.index("# -- Canopy-proxy rules")
    end = synthesis_source.index("# -- Thermal rules")
    block = synthesis_source[start:end].lower()
    assert "canopy temperature" not in block
    assert "leaf_temp" not in block
    assert "machine learning" not in block
    assert "training data" not in block
    proxy_source_raw = open(proxy_module.__file__, encoding="utf-8").read()
    import re

    assert not re.search(r"\d\.\d\s*\*\s*\w", proxy_source_raw)
