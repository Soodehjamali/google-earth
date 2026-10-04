"""Tests for the cross-metric evidence composition layer (Phase O).

The governing risks, each with dedicated tests:

1. **Incorrect evidence wrapping.** ``EvidenceItem.from_result`` must
   correctly extract status, quality, temporal context, and dataset from
   a ``MetricResult``.  Missing provenance must not produce a usable
   item.

2. **Temporal misalignment.** Two metrics covering different time
   windows must not be silently compared as if they represent the same
   observation period.

3. **Spatial misalignment.** A 500 m MODIS product must not be
   presented as comparable to a 10 m Sentinel-2 product without an
   explicit contextual label.

4. **Unit incompatibility.** NDVI (index) must never be numerically
   compared against precipitation (mm).

5. **Quality propagation.** A degraded-quality input must degrade the
   combined evidence, never upgrade it.

6. **Directional consistency.** Metrics with a registered relationship
   must be checked for directional agreement; metrics without a
   relationship must not be forced into one.

7. **Conflict detection.** Contradictions must be reported
   descriptively, not diagnosed automatically.

8. **Independence.** Metrics derived from the same satellite source
   must not be counted as independent evidence.

9. **Evidence sufficiency.** The sufficiency assessment must be
   rule-based, never a subjective score.

10. **Regression.** All existing Phase K/L/M/N behaviour remains
    unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pytest

from app.services.agriculture.evidence import (
    AlignmentStatus,
    ConsistencyStatus,
    DirectionalCheck,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceItem,
    EvidenceSufficiency,
    EvidenceStatus,
    ExpectedRelationship,
    QualityCompatibility,
    RelationshipRegistry,
    RelationshipSpec,
    SpatialAlignment,
    SufficiencyLevel,
    TemporalAlignment,
    UnitCategory,
    UnitCompatibility,
    _categorise_unit,
    _parse_resolution_meters,
    _status_from_basis,
    _value_direction,
    assess_quality_compatibility,
    assess_spatial_alignment,
    assess_sufficiency,
    assess_temporal_alignment,
    assess_unit_compatibility,
    check_directional_consistency,
    detect_conflict,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provenance(
    dataset_id: str = "COPERNICUS/S2_SR_HARMONIZED",
    quality: QualityLevel = QualityLevel.MODERATE,
    start: str = "2024-06-01",
    end: str = "2024-08-31",
    spatial: str = "10 m",
    temporal: str = "monthly",
    basis: MeasurementBasis = MeasurementBasis.DERIVED,
) -> Provenance:
    return Provenance(
        source_dataset_id=dataset_id,
        source_dataset_name="Test Dataset",
        bands=["B4", "B8"],
        formula="test",
        unit="index",
        spatial_resolution=spatial,
        temporal_resolution=temporal,
        aggregation_method="mean",
        measurement_basis=basis,
        quality_level=quality,
        requested_start=start,
        requested_end=end,
    )


def _make_result(
    key: str = "ndvi",
    value: float = 0.6,
    unit: str = "index",
    quality: QualityLevel = QualityLevel.MODERATE,
    start: str = "2024-06-01",
    end: str = "2024-08-31",
    dataset: str = "COPERNICUS/S2_SR_HARMONIZED",
    basis: MeasurementBasis = MeasurementBasis.DERIVED,
    spatial: str = "10 m",
    temporal: str = "monthly",
    status: str = STATUS_OK,
) -> MetricResult:
    return MetricResult(
        metric_key=key,
        display_name=key,
        display_name_fa=key,
        status=status,
        value=value,
        unit=unit,
        provenance=_make_provenance(
            dataset_id=dataset,
            quality=quality,
            start=start,
            end=end,
            spatial=spatial,
            temporal=temporal,
            basis=basis,
        ),
    )


def _make_item(
    key: str = "ndvi",
    value: float = 0.6,
    unit: str = "index",
    quality: QualityLevel = QualityLevel.MODERATE,
    start: str = "2024-06-01",
    end: str = "2024-08-31",
    dataset: str = "COPERNICUS/S2_SR_HARMONIZED",
    basis: MeasurementBasis = MeasurementBasis.DERIVED,
    spatial: str = "10 m",
    temporal: str = "monthly",
    status: str = STATUS_OK,
) -> EvidenceItem:
    return EvidenceItem.from_result(
        _make_result(
            key=key,
            value=value,
            unit=unit,
            quality=quality,
            start=start,
            end=end,
            dataset=dataset,
            basis=basis,
            spatial=spatial,
            temporal=temporal,
            status=status,
        )
    )


# ==========================================================================
# EvidenceItem
# ==========================================================================


class TestEvidenceItem:
    def test_from_result_extracts_status(self):
        item = _make_item(basis=MeasurementBasis.DIRECT)
        assert item.status == EvidenceStatus.OBSERVED

    def test_from_result_modelled_basis(self):
        item = _make_item(basis=MeasurementBasis.MODELLED)
        assert item.status == EvidenceStatus.MODELLED

    def test_from_result_proxy_basis(self):
        item = _make_item(basis=MeasurementBasis.PROXY)
        assert item.status == EvidenceStatus.PROXY

    def test_from_result_derived_basis(self):
        item = _make_item(basis=MeasurementBasis.DERIVED)
        assert item.status == EvidenceStatus.DERIVED

    def test_from_result_unavailable_status(self):
        item = _make_item(status=STATUS_UNAVAILABLE, value=None)
        assert item.status == EvidenceStatus.UNAVAILABLE
        assert not item.is_usable

    def test_from_result_extracts_temporal_window(self):
        item = _make_item(start="2024-06-01", end="2024-08-31")
        assert item.temporal_start == date(2024, 6, 1)
        assert item.temporal_end == date(2024, 8, 31)

    def test_from_result_extracts_quality(self):
        item = _make_item(quality=QualityLevel.GOOD)
        assert item.quality_level == QualityLevel.GOOD

    def test_from_result_extracts_dataset(self):
        item = _make_item(dataset="MODIS/061/MOD16A2GF")
        assert item.source_dataset_id == "MODIS/061/MOD16A2GF"

    def test_from_result_extracts_spatial_resolution(self):
        item = _make_item(spatial="500 m")
        assert item.spatial_resolution == "500 m"

    def test_from_result_extracts_temporal_resolution(self):
        item = _make_item(temporal="8-day")
        assert item.temporal_resolution == "8-day"

    def test_is_usable_requires_value_and_quality(self):
        item = _make_item(value=0.5, quality=QualityLevel.MODERATE)
        assert item.is_usable

    def test_is_not_usable_without_value(self):
        item = _make_item(value=None)
        assert not item.is_usable

    def test_is_not_usable_with_unavailable_quality(self):
        # MetricResult enforces: value + UNAVAILABLE quality = contradiction.
        # Construct EvidenceItem directly to test the property.
        item = EvidenceItem(
            metric_key="ndvi",
            value=None,
            unit="index",
            status=EvidenceStatus.UNAVAILABLE,
            temporal_start=None,
            temporal_end=None,
            quality_level=QualityLevel.UNAVAILABLE,
            provenance=None,
            source_dataset_id=None,
        )
        assert not item.is_usable

    def test_is_proxy(self):
        item = _make_item(basis=MeasurementBasis.PROXY)
        assert item.is_proxy
        assert not item.is_modelled

    def test_is_modelled(self):
        item = _make_item(basis=MeasurementBasis.MODELLED)
        assert item.is_modelled
        assert not item.is_proxy

    def test_no_provenance_yields_unavailable_quality(self):
        item = EvidenceItem(
            metric_key="test",
            value=0.5,
            unit="index",
            status=EvidenceStatus.DERIVED,
            temporal_start=None,
            temporal_end=None,
            quality_level=QualityLevel.UNAVAILABLE,
            provenance=None,
            source_dataset_id=None,
        )
        assert item.quality_level == QualityLevel.UNAVAILABLE
        assert item.source_dataset_id is None


# ==========================================================================
# Unit categorisation
# ==========================================================================


class TestUnitCategorisation:
    def test_index(self):
        assert _categorise_unit("index") == UnitCategory.INDEX

    def test_fraction(self):
        assert _categorise_unit("fraction") == UnitCategory.FRACTION

    def test_mm(self):
        assert _categorise_unit("mm") == UnitCategory.LENGTH_MM

    def test_degC(self):
        assert _categorise_unit("degC") == UnitCategory.TEMPERATURE_C

    def test_kPa(self):
        assert _categorise_unit("kPa") == UnitCategory.PRESSURE_KPA

    def test_z_score(self):
        assert _categorise_unit("z") == UnitCategory.Z_SCORE

    def test_percent(self):
        assert _categorise_unit("percent") == UnitCategory.PERCENT

    def test_days(self):
        assert _categorise_unit("days") == UnitCategory.DAYS

    def test_unknown(self):
        assert _categorise_unit("bogus") == UnitCategory.UNKNOWN


# ==========================================================================
# Status mapping
# ==========================================================================


class TestStatusMapping:
    def test_direct_is_observed(self):
        assert _status_from_basis(MeasurementBasis.DIRECT) == EvidenceStatus.OBSERVED

    def test_product_is_observed(self):
        assert _status_from_basis(MeasurementBasis.PRODUCT) == EvidenceStatus.OBSERVED

    def test_derived(self):
        assert _status_from_basis(MeasurementBasis.DERIVED) == EvidenceStatus.DERIVED

    def test_modelled(self):
        assert _status_from_basis(MeasurementBasis.MODELLED) == EvidenceStatus.MODELLED

    def test_proxy(self):
        assert _status_from_basis(MeasurementBasis.PROXY) == EvidenceStatus.PROXY

    def test_inference(self):
        assert _status_from_basis(MeasurementBasis.INFERENCE) == EvidenceStatus.INFERRED


# ==========================================================================
# Value direction
# ==========================================================================


class TestValueDirection:
    def test_positive(self):
        assert _value_direction(0.5) == "positive"

    def test_negative(self):
        assert _value_direction(-0.3) == "negative"

    def test_zero(self):
        assert _value_direction(0.0) == "zero"

    def test_none(self):
        assert _value_direction(None) is None

    def test_with_threshold(self):
        assert _value_direction(0.001, threshold=0.01) == "zero"


# ==========================================================================
# Temporal alignment
# ==========================================================================


class TestTemporalAlignment:
    def test_exact_overlap(self):
        a = _make_item(start="2024-06-01", end="2024-08-31")
        b = _make_item(start="2024-06-01", end="2024-08-31")
        result = assess_temporal_alignment(a, b)
        assert result.status == AlignmentStatus.ALIGNED
        assert result.overlap_days > 0
        assert result.overlap_fraction == pytest.approx(1.0)

    def test_partial_overlap(self):
        a = _make_item(start="2024-06-01", end="2024-08-31")
        b = _make_item(start="2024-07-01", end="2024-10-31")
        result = assess_temporal_alignment(a, b)
        assert result.status in (
            AlignmentStatus.ALIGNED,
            AlignmentStatus.PARTIALLY_ALIGNED,
        )
        assert result.overlap_days > 0

    def test_no_overlap(self):
        a = _make_item(start="2024-01-01", end="2024-03-31")
        b = _make_item(start="2024-06-01", end="2024-08-31")
        result = assess_temporal_alignment(a, b)
        assert result.status == AlignmentStatus.INSUFFICIENT_OVERLAP
        assert result.overlap_days == 0

    def test_missing_window_returns_unavailable(self):
        a = _make_item(start=None, end=None)
        b = _make_item(start="2024-06-01", end="2024-08-31")
        result = assess_temporal_alignment(a, b)
        assert result.status == AlignmentStatus.UNAVAILABLE

    def test_incompatible_resolution(self):
        a = _make_item(
            start="2024-06-01", end="2024-08-31", temporal="daily"
        )
        b = _make_item(
            start="2024-06-01", end="2024-08-31", temporal="yearly"
        )
        result = assess_temporal_alignment(a, b)
        assert result.status == AlignmentStatus.INCOMPATIBLE_RESOLUTION

    def test_aligned_property(self):
        result = TemporalAlignment(status=AlignmentStatus.ALIGNED)
        assert result.is_aligned

    def test_not_aligned_property(self):
        result = TemporalAlignment(status=AlignmentStatus.PARTIALLY_ALIGNED)
        assert not result.is_aligned


# ==========================================================================
# Spatial alignment
# ==========================================================================


class TestSpatialAlignment:
    def test_same_resolution(self):
        a = _make_item(spatial="10 m")
        b = _make_item(spatial="10 m")
        result = assess_spatial_alignment(a, b)
        assert result.status == AlignmentStatus.ALIGNED
        assert result.resolution_ratio == pytest.approx(1.0)

    def test_compatible_resolution(self):
        a = _make_item(spatial="10 m")
        b = _make_item(spatial="20 m")
        result = assess_spatial_alignment(a, b)
        assert result.status == AlignmentStatus.ALIGNED
        assert result.resolution_ratio == pytest.approx(2.0)

    def test_moderate_mismatch(self):
        a = _make_item(spatial="10 m")
        b = _make_item(spatial="50 m")
        result = assess_spatial_alignment(a, b)
        assert result.status == AlignmentStatus.PARTIALLY_ALIGNED

    def test_large_mismatch(self):
        a = _make_item(spatial="10 m")
        b = _make_item(spatial="10000 m")
        result = assess_spatial_alignment(a, b)
        assert result.status == AlignmentStatus.FOOTPRINT_MISMATCH

    def test_missing_resolution(self):
        a = _make_item(spatial=None)
        b = _make_item(spatial="10 m")
        result = assess_spatial_alignment(a, b)
        assert result.status == AlignmentStatus.UNAVAILABLE

    def test_parse_resolution_meters(self):
        assert _parse_resolution_meters("10 m") == 10.0
        assert _parse_resolution_meters("250m") == 250.0
        assert _parse_resolution_meters("500 meters") == 500.0
        assert _parse_resolution_meters(None) is None
        assert _parse_resolution_meters("abc") is None

    def test_aligned_property(self):
        result = SpatialAlignment(status=AlignmentStatus.ALIGNED)
        assert result.is_aligned


# ==========================================================================
# Unit compatibility
# ==========================================================================


class TestUnitCompatibility:
    def test_same_units(self):
        a = _make_item(unit="index")
        b = _make_item(unit="index")
        result = assess_unit_compatibility(a, b)
        assert result.compatible

    def test_index_and_fraction_compatible(self):
        a = _make_item(unit="index")
        b = _make_item(unit="fraction")
        result = assess_unit_compatibility(a, b)
        assert result.compatible

    def test_mm_and_index_incompatible(self):
        a = _make_item(unit="mm")
        b = _make_item(unit="index")
        result = assess_unit_compatibility(a, b)
        assert not result.compatible

    def test_temperature_compatible(self):
        a = _make_item(unit="degC")
        b = _make_item(unit="degC")
        result = assess_unit_compatibility(a, b)
        assert result.compatible

    def test_pressure_and_mm_incompatible(self):
        a = _make_item(unit="kPa")
        b = _make_item(unit="mm")
        result = assess_unit_compatibility(a, b)
        assert not result.compatible

    def test_unknown_unit_with_known(self):
        a = _make_item(unit="bogus")
        b = _make_item(unit="index")
        result = assess_unit_compatibility(a, b)
        # Unknown with known: may be valid (at least one unclassified)
        assert result.compatible


# ==========================================================================
# Quality compatibility
# ==========================================================================


class TestQualityCompatibility:
    def test_both_good(self):
        a = _make_item(quality=QualityLevel.GOOD)
        b = _make_item(quality=QualityLevel.GOOD)
        result = assess_quality_compatibility(a, b)
        assert result.is_acceptable

    def test_one_moderate_degrades(self):
        a = _make_item(quality=QualityLevel.GOOD)
        b = _make_item(quality=QualityLevel.MODERATE)
        result = assess_quality_compatibility(a, b)
        assert result.status == "degraded"

    def test_poor_not_usable(self):
        # POOR is not usable (is_usable=False), so quality is insufficient
        a = EvidenceItem(
            metric_key="a",
            value=0.5,
            unit="index",
            status=EvidenceStatus.DERIVED,
            temporal_start=None,
            temporal_end=None,
            quality_level=QualityLevel.POOR,
            provenance=None,
            source_dataset_id=None,
        )
        b = _make_item(quality=QualityLevel.GOOD)
        result = assess_quality_compatibility(a, b)
        assert result.status == "insufficient"

    def test_both_moderate(self):
        a = _make_item(quality=QualityLevel.MODERATE)
        b = _make_item(quality=QualityLevel.MODERATE)
        result = assess_quality_compatibility(a, b)
        assert result.status == "degraded"


# ==========================================================================
# Directional consistency
# ==========================================================================


class TestDirectionalConsistency:
    def test_same_direction_positive(self):
        a = _make_item(value=0.5)
        b = _make_item(value=0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.SAME_DIRECTION
        )
        assert result.consistent

    def test_same_direction_mixed(self):
        a = _make_item(value=0.5)
        b = _make_item(value=-0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.SAME_DIRECTION
        )
        assert not result.consistent

    def test_opposite_direction(self):
        a = _make_item(value=0.5)
        b = _make_item(value=-0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.OPPOSITE_DIRECTION
        )
        assert result.consistent

    def test_opposite_direction_both_positive(self):
        a = _make_item(value=0.5)
        b = _make_item(value=0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.OPPOSITE_DIRECTION
        )
        assert not result.consistent

    def test_no_assumed_relationship(self):
        a = _make_item(value=0.5)
        b = _make_item(value=-0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.NO_ASSUMED_RELATIONSHIP
        )
        assert result.consistent

    def test_unusable_item(self):
        a = _make_item(value=None)
        b = _make_item(value=0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.SAME_DIRECTION
        )
        assert not result.consistent

    def test_conditional_relationship(self):
        a = _make_item(value=0.5)
        b = _make_item(value=0.3)
        result = check_directional_consistency(
            a, b, ExpectedRelationship.CONDITIONAL
        )
        assert result.consistent


# ==========================================================================
# Relationship registry
# ==========================================================================


class TestRelationshipRegistry:
    def test_register_and_get(self):
        registry = RelationshipRegistry()
        spec = RelationshipSpec(
            metric_a="ndvi",
            metric_b="evi",
            expected=ExpectedRelationship.SAME_DIRECTION,
            scientific_basis="Both are vegetation indices.",
        )
        registry.register(spec)
        assert registry.has_relationship("ndvi", "evi")
        assert registry.has_relationship("evi", "ndvi")  # symmetric
        retrieved = registry.get("ndvi", "evi")
        assert retrieved is not None
        assert retrieved.expected == ExpectedRelationship.SAME_DIRECTION

    def test_get_nonexistent_returns_none(self):
        registry = RelationshipRegistry()
        assert registry.get("ndvi", "precipitation") is None

    def test_default_registry_has_vegetation_pairs(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        assert DEFAULT_REGISTRY.has_relationship("ndvi", "evi")
        assert DEFAULT_REGISTRY.has_relationship("ndvi", "lai")

    def test_default_registry_has_water_pairs(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        assert DEFAULT_REGISTRY.has_relationship(
            "precipitation", "soil_moisture_rootzone"
        )

    def test_default_registry_has_thermal_pairs(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        assert DEFAULT_REGISTRY.has_relationship(
            "land_surface_temperature_day", "ndvi"
        )

    def test_all_relationships(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        all_rels = DEFAULT_REGISTRY.all_relationships()
        assert len(all_rels) > 0
        assert all(isinstance(r, RelationshipSpec) for r in all_rels)


# ==========================================================================
# Conflict detection
# ==========================================================================


class TestConflictDetection:
    def test_consistent_items(self):
        a = _make_item(
            key="ndvi",
            value=0.5,
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        b = _make_item(
            key="evi",
            value=0.4,
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        conflict = detect_conflict(a, b)
        assert conflict.status == ConsistencyStatus.CONSISTENT

    def test_incompatible_units(self):
        a = _make_item(key="ndvi", value=0.5, unit="index")
        b = _make_item(key="precipitation", value=50.0, unit="mm")
        conflict = detect_conflict(a, b)
        assert conflict.status == ConsistencyStatus.CONFLICTING

    def test_temporal_mismatch(self):
        a = _make_item(
            key="ndvi",
            value=0.5,
            start="2024-01-01",
            end="2024-03-31",
        )
        b = _make_item(
            key="evi",
            value=0.4,
            start="2024-06-01",
            end="2024-08-31",
        )
        conflict = detect_conflict(a, b)
        assert conflict.status in (
            ConsistencyStatus.PARTIALLY_CONSISTENT,
            ConsistencyStatus.CONSISTENT,
        )
        assert any("Temporal" in e for e in conflict.possible_explanations)

    def test_unusable_item(self):
        a = _make_item(value=None)
        b = _make_item(value=0.3)
        conflict = detect_conflict(a, b)
        assert conflict.status == ConsistencyStatus.INSUFFICIENT_EVIDENCE

    def test_with_relationship_same_direction(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        a = _make_item(
            key="ndvi",
            value=0.5,
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        b = _make_item(
            key="evi",
            value=0.4,
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        rel = DEFAULT_REGISTRY.get("ndvi", "evi")
        conflict = detect_conflict(a, b, rel)
        assert conflict.status == ConsistencyStatus.CONSISTENT

    def test_with_relationship_opposite_violated(self):
        from app.services.agriculture.evidence import DEFAULT_REGISTRY

        a = _make_item(
            key="land_surface_temperature_day",
            value=35.0,
            unit="degC",
            start="2024-06-01",
            end="2024-08-31",
            spatial="1000 m",
        )
        b = _make_item(
            key="ndvi",
            value=0.7,
            unit="degC",
            start="2024-06-01",
            end="2024-08-31",
            spatial="1000 m",
        )
        rel = DEFAULT_REGISTRY.get(
            "land_surface_temperature_day", "ndvi"
        )
        conflict = detect_conflict(a, b, rel)
        # Both positive => opposite relationship violated
        assert conflict.status == ConsistencyStatus.PARTIALLY_CONSISTENT


# ==========================================================================
# Evidence sufficiency
# ==========================================================================


class TestEvidenceSufficiency:
    def test_sufficient_with_two_sources(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
                quality=QualityLevel.GOOD,
            ),
            _make_item(
                key="precipitation",
                dataset="ECMWF/ERA5_LAND/DAILY_AGGR",
                quality=QualityLevel.GOOD,
            ),
        ]
        result = assess_sufficiency(items)
        assert result.level == SufficiencyLevel.SUFFICIENT

    def test_insufficient_with_one_source(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
            _make_item(
                key="evi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
        ]
        result = assess_sufficiency(items)
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert result.distinct_sources == 1

    def test_limited_with_degraded_quality(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
                quality=QualityLevel.MODERATE,
            ),
            _make_item(
                key="precipitation",
                dataset="ECMWF/ERA5_LAND/DAILY_AGGR",
                quality=QualityLevel.GOOD,
            ),
        ]
        result = assess_sufficiency(items)
        # MODERATE needs_caveat => one degraded reason => LIMITED
        assert result.level == SufficiencyLevel.LIMITED

    def test_insufficient_with_conflicts(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
            _make_item(
                key="precipitation",
                dataset="ECMWF/ERA5_LAND/DAILY_AGGR",
            ),
        ]
        conflicts = [
            EvidenceConflict(
                metric_a="ndvi",
                metric_b="precipitation",
                status=ConsistencyStatus.CONFLICTING,
                explanation="test conflict",
            )
        ]
        result = assess_sufficiency(items, conflicts)
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert result.has_conflicts

    def test_insufficient_with_no_items(self):
        result = assess_sufficiency([])
        assert result.level == SufficiencyLevel.INSUFFICIENT
        assert result.available_count == 0

    def test_is_sufficient_property(self):
        result = EvidenceSufficiency(
            level=SufficiencyLevel.SUFFICIENT,
            available_count=3,
            unavailable_count=0,
            distinct_sources=3,
            min_quality=QualityLevel.GOOD,
            has_conflicts=False,
            key_reasons=(),
        )
        assert result.is_sufficient


# ==========================================================================
# Evidence bundle
# ==========================================================================


class TestEvidenceBundle:
    def test_bundle_available_items(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(key="ndvi", value=0.5),
                _make_item(key="precipitation", value=None),
            ],
        )
        assert len(bundle.available_items) == 1
        assert len(bundle.unavailable_items) == 1
        assert bundle.available_keys == ["ndvi"]

    def test_bundle_metric_keys(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(key="ndvi"),
                _make_item(key="evi"),
            ],
        )
        assert bundle.metric_keys == ["ndvi", "evi"]

    def test_bundle_source_datasets(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(dataset="S2"),
                _make_item(dataset="ERA5"),
            ],
        )
        assert set(bundle.source_datasets) == {"S2", "ERA5"}

    def test_bundle_pairwise_alignment(self):
        a = _make_item(
            key="ndvi",
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        b = _make_item(
            key="evi",
            start="2024-06-01",
            end="2024-08-31",
            spatial="10 m",
        )
        bundle = EvidenceBundle(name="test", items=[a, b])
        alignment = bundle.pairwise_alignment(a, b)
        assert "temporal" in alignment
        assert "spatial" in alignment
        assert "units" in alignment
        assert "quality" in alignment

    def test_bundle_run_consistency_checks(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(
                    key="ndvi",
                    value=0.5,
                    start="2024-06-01",
                    end="2024-08-31",
                    spatial="10 m",
                ),
                _make_item(
                    key="evi",
                    value=0.4,
                    start="2024-06-01",
                    end="2024-08-31",
                    spatial="10 m",
                ),
            ],
        )
        conflicts = bundle.run_consistency_checks()
        assert len(conflicts) == 1
        assert conflicts[0].status == ConsistencyStatus.CONSISTENT

    def test_bundle_assess_sufficiency(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(
                    key="ndvi",
                    dataset="S2",
                    quality=QualityLevel.GOOD,
                ),
                _make_item(
                    key="precipitation",
                    dataset="ERA5",
                    quality=QualityLevel.GOOD,
                ),
            ],
        )
        sufficiency = bundle.assess_sufficiency()
        assert sufficiency.level == SufficiencyLevel.SUFFICIENT

    def test_bundle_to_dict(self):
        bundle = EvidenceBundle(
            name="water_context",
            items=[_make_item(key="ndvi", value=0.5)],
            limitations=["test limitation"],
        )
        d = bundle.to_dict()
        assert d["name"] == "water_context"
        assert len(d["items"]) == 1
        assert d["items"][0]["metric_key"] == "ndvi"
        assert "test limitation" in d["limitations"]

    def test_bundle_has_conflicts(self):
        bundle = EvidenceBundle(
            name="test",
            items=[
                _make_item(key="ndvi"),
                _make_item(key="precipitation"),
            ],
            conflicts=[
                EvidenceConflict(
                    metric_a="ndvi",
                    metric_b="precipitation",
                    status=ConsistencyStatus.CONFLICTING,
                    explanation="test",
                )
            ],
        )
        assert bundle.has_conflicts


# ==========================================================================
# Independence (same-source counting)
# ==========================================================================


class TestIndependence:
    def test_same_source_not_independent(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
            _make_item(
                key="evi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
        ]
        sources = {
            i.source_dataset_id
            for i in items
            if i.source_dataset_id is not None
        }
        assert len(sources) == 1

    def test_different_sources_are_independent(self):
        items = [
            _make_item(
                key="ndvi",
                dataset="COPERNICUS/S2_SR_HARMONIZED",
            ),
            _make_item(
                key="precipitation",
                dataset="ECMWF/ERA5_LAND/DAILY_AGGR",
            ),
        ]
        sources = {
            i.source_dataset_id
            for i in items
            if i.source_dataset_id is not None
        }
        assert len(sources) == 2

    def test_sufficiency_counts_distinct_sources(self):
        items = [
            _make_item(key="ndvi", dataset="S2"),
            _make_item(key="evi", dataset="S2"),
            _make_item(key="precipitation", dataset="ERA5"),
        ]
        result = assess_sufficiency(items)
        assert result.distinct_sources == 2


# ==========================================================================
# STATIC dataset handling
# ==========================================================================


class TestStaticDatasetHandling:
    def test_static_dataset_item(self):
        result = _make_result(
            key="terrain_historical_trend",
            value=None,
            status=STATUS_UNAVAILABLE,
            dataset="NASA/NASADEM_HGT/001",
            spatial="30 m",
            temporal="static",
        )
        item = EvidenceItem.from_result(result)
        assert item.status == EvidenceStatus.UNAVAILABLE
        assert not item.is_usable


# ==========================================================================
# Regression: existing contracts unchanged
# ==========================================================================


class TestRegression:
    def test_quality_level_enum_unchanged(self):
        assert QualityLevel.EXCELLENT.is_usable
        assert QualityLevel.GOOD.is_usable
        assert QualityLevel.MODERATE.is_usable
        assert not QualityLevel.POOR.is_usable
        assert not QualityLevel.INSUFFICIENT.is_usable
        assert not QualityLevel.UNAVAILABLE.is_usable

    def test_measurement_basis_enum_unchanged(self):
        assert MeasurementBasis.DIRECT.requires_disclaimer is False
        assert MeasurementBasis.MODELLED.requires_disclaimer is True
        assert MeasurementBasis.PROXY.requires_disclaimer is True

    def test_temporal_kind_enum_unchanged(self):
        assert TemporalKind.OBSERVATION.value == "observation"
        assert TemporalKind.STATIC.value == "static"

    def test_metric_result_invariants(self):
        result = _make_result()
        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.provenance is not None

    def test_combine_quality_still_works(self):
        from app.services.agriculture.quality import combine_quality

        result = combine_quality(
            [QualityLevel.GOOD, QualityLevel.MODERATE, QualityLevel.POOR]
        )
        assert result == QualityLevel.POOR

    def test_combine_quality_empty(self):
        from app.services.agriculture.quality import combine_quality

        result = combine_quality([])
        assert result == QualityLevel.UNAVAILABLE
