"""Unit tests for Phase 2: Three-State Quality Model & Gating."""

import pytest
from app.services.agriculture.quality_gating import (
    QualityState,
    QualityGatingConfig,
    DEFAULT_QUALITY_CONFIG,
    classify_quality_state,
    describe_support,
    describe_support_fa,
    normalize_legacy_quality_state,
    correct_temperature_for_elevation,
    aggregate_hourly_to_local_days,
)
from app.services.agriculture.types import (
    MetricResult,
    Provenance,
    QualityLevel,
    MeasurementBasis,
    TemporalKind,
    STATUS_OK,
    STATUS_INSUFFICIENT_DATA,
)
from app.services.agriculture.evidence import (
    EvidenceItem,
    EvidenceStatus,
    EvidenceBundle,
    SufficiencyLevel,
)
from app.services.agriculture.synthesis import (
    SynthesisDomain,
    SynthesisRule,
    SynthesisStatement,
    PatternState,
    _evaluate_rule,
)
from app.schemas.agriculture import (
    ProvenanceResponse,
    EvidenceItemResponse,
)


def test_quality_state_properties():
    assert QualityState.VALID.is_usable_data is True
    assert QualityState.VALID.is_field_scale is True

    assert QualityState.COARSE_CONTEXT.is_usable_data is True
    assert QualityState.COARSE_CONTEXT.is_field_scale is False

    assert QualityState.UNAVAILABLE.is_usable_data is False
    assert QualityState.UNAVAILABLE.is_field_scale is False


def test_classify_quality_state():
    # 1. 10m Sentinel-2 -> VALID
    state_s2 = classify_quality_state(native_resolution_m=10.0)
    assert state_s2 == QualityState.VALID

    # 2. 30m Landsat/DEM -> VALID
    state_landsat = classify_quality_state(native_resolution_m=30.0)
    assert state_landsat == QualityState.VALID

    # 3. ERA5 11km -> COARSE_CONTEXT
    state_era5 = classify_quality_state(
        native_resolution_m=11132.0,
        dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
    )
    assert state_era5 == QualityState.COARSE_CONTEXT

    # 4. SMAP 9km -> COARSE_CONTEXT
    state_smap = classify_quality_state(
        native_resolution_m=9000.0,
        dataset_id="NASA/SMAP/SPL3SMP_E/006",
    )
    assert state_smap == QualityState.COARSE_CONTEXT

    # 5. Computation error or missing pixels -> UNAVAILABLE
    state_err = classify_quality_state(
        native_resolution_m=10.0,
        has_valid_pixels=False,
    )
    assert state_err == QualityState.UNAVAILABLE

    state_qc = classify_quality_state(
        native_resolution_m=10.0,
        qc_passed=False,
    )
    assert state_qc == QualityState.UNAVAILABLE


def test_describe_support_text():
    # Field scale
    assert describe_support(10.0) == "Field-scale polygon reduction"
    assert describe_support_fa(10.0) == "داده دقیق مزرعه"

    # Coarse context
    supp_en = describe_support(11132.0, is_point_queryable=True)
    assert "11.1 km" in supp_en

    supp_fa = describe_support_fa(11132.0)
    assert "۱۱" in supp_fa or "11" in supp_fa or "کیلومتر" in supp_fa


def test_metric_result_coarse_context_allows_value():
    """Verify that COARSE_CONTEXT results can carry real numeric values without contradiction."""
    prov = Provenance(
        source_dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
        source_dataset_name="ERA5-Land Daily",
        bands=["temperature_2m"],
        formula="temperature in °C",
        unit="°C",
        spatial_resolution="11132 m",
        temporal_resolution="daily",
        temporal_kind=TemporalKind.OBSERVATION,
        aggregation_method="spatial mean",
        measurement_basis=MeasurementBasis.MODELLED,
        quality_level=QualityLevel.POOR,  # coarse grid may score POOR coverage at field scale
        quality_state=QualityState.COARSE_CONTEXT,
        native_resolution_m=11132.0,
    )

    # Must NOT raise ValueError
    res = MetricResult(
        metric_key="temperature_mean",
        display_name="Mean Air Temperature",
        display_name_fa="میانگین دما",
        status=STATUS_OK,
        value=24.5,
        unit="°C",
        provenance=prov,
    )
    assert res.quality_state == QualityState.COARSE_CONTEXT
    assert res.is_usable is True

    d = res.to_dict()
    assert d["quality_state"] == "coarse_context"
    assert d["value"] == 24.5


def test_evidence_item_coarse_context():
    prov = Provenance(
        source_dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
        source_dataset_name="ERA5-Land Daily",
        bands=["temperature_2m"],
        formula="none",
        unit="°C",
        spatial_resolution="11132 m",
        temporal_resolution="daily",
        temporal_kind=TemporalKind.OBSERVATION,
        aggregation_method="spatial mean",
        measurement_basis=MeasurementBasis.MODELLED,
        quality_level=QualityLevel.POOR,
        quality_state=QualityState.COARSE_CONTEXT,
        native_resolution_m=11132.0,
    )
    res = MetricResult(
        metric_key="temperature_mean",
        display_name="Mean Air Temperature",
        display_name_fa="میانگین دما",
        status=STATUS_OK,
        value=24.5,
        unit="°C",
        provenance=prov,
    )
    item = EvidenceItem.from_result(res)
    assert item.is_usable is True
    assert item.is_coarse_context is True
    assert item.is_field_scale is False
    assert item.quality_state == QualityState.COARSE_CONTEXT


def test_synthesis_hard_invariant_coarse_cannot_raise_level_a():
    """Coarse context evidence cannot raise sufficiency to SUFFICIENT for field-scale statements."""
    prov = Provenance(
        source_dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
        source_dataset_name="ERA5-Land Daily",
        bands=["volumetric_soil_water_layer_1"],
        formula="weighted mean",
        unit="m3/m3",
        spatial_resolution="11132 m",
        temporal_resolution="daily",
        temporal_kind=TemporalKind.OBSERVATION,
        aggregation_method="spatial mean",
        measurement_basis=MeasurementBasis.MODELLED,
        quality_level=QualityLevel.MODERATE,
        quality_state=QualityState.COARSE_CONTEXT,
        native_resolution_m=11132.0,
    )
    item = EvidenceItem(
        metric_key="soil_moisture_rootzone_era5",
        value=0.12,
        unit="m3/m3",
        status=EvidenceStatus.MODELLED,
        temporal_start=None,
        temporal_end=None,
        quality_level=QualityLevel.MODERATE,
        quality_state=QualityState.COARSE_CONTEXT,
        provenance=prov,
        source_dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
    )

    bundle = EvidenceBundle(
        name="water",
        items=[item],
    )
    # Even if bundle has SUFFICIENT sufficiency set artificially:
    from app.services.agriculture.evidence import EvidenceSufficiency
    bundle.sufficiency = EvidenceSufficiency(
        level=SufficiencyLevel.SUFFICIENT,
        available_count=1,
        unavailable_count=0,
        distinct_sources=1,
        min_quality=QualityLevel.MODERATE,
        has_conflicts=False,
        key_reasons=(),
    )

    rule = SynthesisRule(
        rule_id="test_water_field_rule",
        domain=SynthesisDomain.WATER,  # Field-level domain, not CLIMATE
        inputs=("soil_moisture_rootzone_era5",),
        conditions=lambda ev, val: True,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement="Field rootzone moisture is low.",
        scientific_basis="ERA5 regional indicator",
        limitations=(),
    )

    statement = _evaluate_rule(rule, bundle)
    assert statement is not None
    # Capped at LIMITED, not SUFFICIENT!
    assert statement.sufficiency == SufficiencyLevel.LIMITED


def test_legacy_report_deserialization_backward_compatibility():
    """Stored PostgreSQL reports lacking quality_state must deserialize cleanly."""
    legacy_prov_dict = {
        "source_dataset_id": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "source_dataset_name": "ERA5-Land",
        "bands": ["temperature_2m"],
        "formula": "none",
        "unit": "°C",
        "spatial_resolution": "0.1 degree (~11 km)",
        "temporal_resolution": "daily",
        "temporal_kind": "series",
        "aggregation_method": "mean",
        "measurement_basis": "modelled",
        "quality_level": "moderate",
        # Note: NO quality_state in legacy payload!
    }

    parsed_prov = ProvenanceResponse.model_validate(legacy_prov_dict)
    assert parsed_prov.quality_state == QualityState.COARSE_CONTEXT
    assert parsed_prov.native_resolution_m is not None
    assert parsed_prov.support_description_fa is not None

    legacy_evidence_dict = {
        "metric_key": "temperature_mean",
        "value": 22.4,
        "unit": "°C",
        "status": "modelled",
        "quality": "moderate",
        "source_dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "display_name": "Mean Air Temperature",
        "is_usable": True,
        "is_proxy": False,
        "provenance": legacy_prov_dict,
        # NO quality_state in legacy payload!
    }

    parsed_item = EvidenceItemResponse.model_validate(legacy_evidence_dict)
    assert parsed_item.quality_state == QualityState.COARSE_CONTEXT
    assert parsed_item.is_coarse_context is True
