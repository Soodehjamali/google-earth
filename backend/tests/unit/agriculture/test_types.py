"""Tests for the core result and provenance types.

These tests enforce the engine's central contract: a number is never
published without an attributable source, and a proxy is never allowed to
present itself as a measurement.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import pytest

from app.services.agriculture.types import (
    NOT_AVAILABLE_REASON_ERROR,
    NOT_AVAILABLE_REASON_INSUFFICIENT,
    NOT_AVAILABLE_REASON_UNSUPPORTED,
    STATUS_ERROR,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    BandSpec,
    DatasetSpec,
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
    TemporalKind,
)


def _provenance(
    quality: QualityLevel = QualityLevel.GOOD,
    basis: MeasurementBasis = MeasurementBasis.DIRECT,
) -> Provenance:
    return Provenance(
        source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        source_dataset_name="Sentinel-2 MSI Level-2A",
        bands=["B4", "B8"],
        formula="(B8 - B4) / (B8 + B4)",
        unit="index",
        spatial_resolution="10 m",
        temporal_resolution="5 days",
        aggregation_method="mean",
        measurement_basis=basis,
        quality_level=quality,
    )


# --------------------------------------------------------------------------
# The provenance requirement
# --------------------------------------------------------------------------


def test_value_without_provenance_is_rejected():
    """The most important invariant in the engine."""
    with pytest.raises(ValueError) as exc:
        MetricResult(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="شاخص سبزینگی",
            status=STATUS_OK,
            value=0.42,
            provenance=None,
        )
    assert "provenance" in str(exc.value).lower()


def test_value_with_unavailable_quality_is_rejected():
    """A number cannot claim to exist while its quality says unavailable."""
    with pytest.raises(ValueError):
        MetricResult(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="شاخص سبزینگی",
            status=STATUS_OK,
            value=0.42,
            provenance=_provenance(QualityLevel.UNAVAILABLE),
        )


def test_well_formed_result_is_accepted():
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=STATUS_OK,
        value=0.42,
        unit="index",
        provenance=_provenance(),
    )
    assert result.value == 0.42
    assert result.provenance is not None
    assert result.provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"


def test_result_without_a_value_needs_no_provenance():
    """Unavailable results are legal with no provenance attached."""
    result = MetricResult(
        metric_key="twi",
        display_name="Topographic Wetness Index",
        display_name_fa="شاخص رطوبت توپوگرافی",
        status=STATUS_UNAVAILABLE,
    )
    assert result.value is None
    assert result.provenance is None


# --------------------------------------------------------------------------
# Constructors for non-ok states
# --------------------------------------------------------------------------


def test_unavailable_constructor():
    result = MetricResult.unavailable(
        metric_key="twi",
        display_name="TWI",
        display_name_fa="شاخص رطوبت توپوگرافی",
        reason=NOT_AVAILABLE_REASON_UNSUPPORTED,
        message="No native flow accumulation in Earth Engine.",
    )
    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None
    assert result.reason == NOT_AVAILABLE_REASON_UNSUPPORTED
    assert not result.is_usable


def test_unavailable_constructor_forces_quality_to_unavailable():
    prov = _provenance(QualityLevel.EXCELLENT)
    result = MetricResult.unavailable(
        metric_key="twi",
        display_name="TWI",
        display_name_fa="شاخص رطوبت توپوگرافی",
        provenance=prov,
    )
    # The caller passed a contradictory quality; the constructor corrects it.
    assert result.provenance is not None
    assert result.provenance.quality_level is QualityLevel.UNAVAILABLE


def test_insufficient_constructor():
    result = MetricResult.insufficient(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        message="Only 1 valid scene in the requested period.",
    )
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.reason == NOT_AVAILABLE_REASON_INSUFFICIENT
    assert result.value is None


def test_error_constructor_carries_no_value_and_no_provenance():
    result = MetricResult.error(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        message="Upstream computation failed.",
    )
    assert result.status == STATUS_ERROR
    assert result.reason == NOT_AVAILABLE_REASON_ERROR
    assert result.value is None
    assert result.provenance is None


def test_insufficient_result_is_not_usable():
    """Critically: insufficient is not a publishable value."""
    result = MetricResult.insufficient(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        message="Too few scenes.",
    )
    assert not result.is_usable


# --------------------------------------------------------------------------
# Usability gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quality",
    [
        QualityLevel.EXCELLENT,
        QualityLevel.GOOD,
        QualityLevel.MODERATE,
        QualityLevel.POOR,
    ],
)
def test_is_usable_tracks_quality_level(quality: QualityLevel):
    """A value may exist at levels down to 'poor', but only usable ones ship.

    'poor' is allowed to carry a number (it is a real observation, just a
    weak one) yet ``is_usable`` must still report False so callers gate on
    it rather than publishing a weak value as though it were sound.
    """
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=STATUS_OK,
        value=0.4,
        provenance=_provenance(quality),
    )
    expected = quality in (
        QualityLevel.EXCELLENT,
        QualityLevel.GOOD,
        QualityLevel.MODERATE,
    )
    assert result.is_usable is expected


def test_value_at_poor_quality_is_rejected_by_the_usable_gate():
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=STATUS_OK,
        value=0.4,
        provenance=_provenance(QualityLevel.POOR),
    )
    assert result.value == 0.4
    assert not result.is_usable


def test_value_at_insufficient_quality_cannot_be_constructed():
    """Insufficient means 'no value'; a number there is a contradiction."""
    with pytest.raises(ValueError):
        MetricResult(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="شاخص سبزینگی",
            status=STATUS_OK,
            value=0.4,
            provenance=_provenance(QualityLevel.INSUFFICIENT),
        )


def test_result_with_no_provenance_has_unavailable_quality():
    result = MetricResult(
        metric_key="x", display_name="X", display_name_fa="ایکس"
    )
    assert result.quality_level is QualityLevel.UNAVAILABLE


# --------------------------------------------------------------------------
# Proxy labelling
# --------------------------------------------------------------------------


def test_proxy_basis_marks_result_as_proxy():
    result = MetricResult(
        metric_key="CWSI_proxy",
        display_name="Crop Water Stress Index (proxy)",
        display_name_fa="شاخص تنش آبی (تقریبی)",
        status=STATUS_OK,
        value=0.7,
        provenance=_provenance(QualityLevel.MODERATE, MeasurementBasis.PROXY),
    )
    assert result.is_proxy
    assert result.measurement_basis is MeasurementBasis.PROXY


def test_inference_basis_also_counts_as_proxy():
    result = MetricResult(
        metric_key="vegetation_stress",
        display_name="Vegetation Stress",
        display_name_fa="تنش پوشش گیاهی",
        status=STATUS_OK,
        value=1.0,
        provenance=_provenance(QualityLevel.MODERATE, MeasurementBasis.INFERENCE),
    )
    assert result.is_proxy


def test_direct_basis_is_not_a_proxy():
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=STATUS_OK,
        value=0.4,
        provenance=_provenance(QualityLevel.GOOD, MeasurementBasis.DIRECT),
    )
    assert not result.is_proxy


def test_modelled_and_proxy_and_inference_require_disclaimer():
    assert MeasurementBasis.MODELLED.requires_disclaimer
    assert MeasurementBasis.PROXY.requires_disclaimer
    assert MeasurementBasis.INFERENCE.requires_disclaimer
    assert not MeasurementBasis.DIRECT.requires_disclaimer
    assert not MeasurementBasis.DERIVED.requires_disclaimer
    assert not MeasurementBasis.PRODUCT.requires_disclaimer


# --------------------------------------------------------------------------
# Coverage semantics
# --------------------------------------------------------------------------


def test_missing_data_is_never_silently_zero():
    """An empty aggregation must report zero pixels, not a zero value."""
    stats = SpatialStats()
    assert stats.mean is None
    assert stats.valid_pixel_count == 0
    assert not stats.has_values


def test_coverage_percent_derivation():
    stats = SpatialStats(
        mean=0.5,
        valid_pixel_count=75,
        total_pixel_count=100,
        missing_pixel_count=25,
        missing_percent=25.0,
    )
    assert stats.coverage_percent == pytest.approx(75.0)
    assert stats.has_values


def test_total_promoted_to_valid_when_unspecified():
    """With valid pixels but no stated total, coverage is full by inference.

    There is no evidence of missing data, so reporting zero coverage would
    understate what we actually have. The total is promoted to match the
    valid count and coverage becomes 100 percent.
    """
    stats = SpatialStats(mean=0.5, valid_pixel_count=10)
    assert stats.total_pixel_count == 10
    assert stats.missing_pixel_count == 0
    assert stats.coverage_percent == pytest.approx(100.0)


def test_coverage_is_zero_when_there_are_no_pixels_at_all():
    stats = SpatialStats()
    assert stats.total_pixel_count == 0
    assert stats.coverage_percent == 0.0


def test_stats_normalisation_enforces_consistency():
    """A hand-built instance cannot contradict itself."""
    stats = SpatialStats(valid_pixel_count=50, total_pixel_count=100)
    assert stats.missing_pixel_count == 50
    assert stats.missing_percent == pytest.approx(50.0)
    assert stats.coverage_percent == pytest.approx(50.0)


def test_stats_total_below_valid_is_corrected():
    stats = SpatialStats(valid_pixel_count=100, total_pixel_count=10)
    assert stats.total_pixel_count == 100
    assert stats.missing_percent == pytest.approx(0.0)


def test_stats_to_dict_omits_nulls_but_keeps_coverage():
    stats = SpatialStats(
        mean=0.42,
        valid_pixel_count=100,
        total_pixel_count=120,
        missing_percent=16.67,
    )
    payload = stats.to_dict()
    assert payload["mean"] == 0.42
    assert "median" not in payload  # null statistics are dropped
    assert payload["valid_pixel_count"] == 100
    assert "coverage_percent" in payload
    assert payload["coverage_percent"] == pytest.approx(83.33, abs=0.01)


def test_stats_to_dict_includes_percentiles_when_present():
    stats = SpatialStats(
        mean=0.4, p10=0.1, p90=0.8, valid_pixel_count=50, total_pixel_count=50,
    )
    payload = stats.to_dict()
    assert payload["p10"] == 0.1
    assert payload["p90"] == 0.8
    assert "p25" not in payload


# --------------------------------------------------------------------------
# Serialisation round trip
# --------------------------------------------------------------------------


def test_metric_result_to_dict_shape():
    stats = SpatialStats(mean=0.42, valid_pixel_count=100, total_pixel_count=100)
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="شاخص سبزینگی",
        status=STATUS_OK,
        value=0.42,
        unit="index",
        stats=stats,
        provenance=_provenance(),
    )
    payload = result.to_dict()
    assert payload["metric_key"] == "ndvi"
    assert payload["value"] == 0.42
    assert payload["unit"] == "index"
    assert payload["status"] == STATUS_OK
    assert payload["provenance"]["source_dataset_id"] == "COPERNICUS/S2_SR_HARMONIZED"
    assert payload["provenance"]["measurement_basis"] == "direct"
    assert payload["provenance"]["quality_level"] == "good"
    assert payload["stats"]["mean"] == 0.42
    assert payload["is_proxy"] is False
    assert payload["measurement_basis"] == "direct"
    assert payload["quality_level"] == "good"


def test_provenance_to_dict_contains_all_required_metadata():
    """Every field the spec demands must be present in serialised provenance."""
    payload = _provenance().to_dict()
    for key in (
        "source_dataset_id",
        "source_dataset_name",
        "bands",
        "formula",
        "unit",
        "spatial_resolution",
        "temporal_resolution",
        "aggregation_method",
        "measurement_basis",
        "quality_level",
        "date_start",
        "date_end",
        "image_count",
        "fallback_from",
        "limitations",
        "caveats",
        "citation",
        "computed_at",
    ):
        assert key in payload, f"provenance is missing required field {key!r}"


def test_unavailable_result_serialises_cleanly():
    result = MetricResult.unavailable(
        metric_key="twi",
        display_name="TWI",
        display_name_fa="شاخص رطوبت توپوگرافی",
        reason=NOT_AVAILABLE_REASON_UNSUPPORTED,
        message="Not supported.",
    )
    payload = result.to_dict()
    assert payload["value"] is None
    assert payload["provenance"] is None
    assert payload["stats"] is None
    assert payload["status"] == STATUS_UNAVAILABLE


# --------------------------------------------------------------------------
# BandSpec conversion edge cases
# --------------------------------------------------------------------------


def test_band_spec_applies_offset_with_scale():
    band = BandSpec("ST_B10", "Surface temperature", "K", 0.00341802, 149.0)
    assert band.to_physical(0) == pytest.approx(149.0)


def test_band_spec_nodata_none_is_honoured():
    band = BandSpec("B4", "Red", "reflectance", 0.0001, 0.0, nodata_values=(0.0,))
    assert band.to_physical(0.0) is None
    assert band.to_physical(2500) == pytest.approx(0.25)


def test_band_spec_boolean_input_is_rejected():
    band = BandSpec("B4", "Red", "reflectance", 0.0001)
    assert band.to_physical(True) is None  # type: ignore[arg-type]


def test_dataset_verified_flag():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert spec.is_verified


# --------------------------------------------------------------------------
# Temporal semantics: OBSERVATION vs STATIC
# --------------------------------------------------------------------------
# A dataset's declared dates do not mean one thing for every product. For
# a time series they bound when observations exist. For a static surface
# they record when it was made. Collapsing the two made the engine refuse
# every realistic request against a static product, so the distinction is
# now explicit, typed, and tested here.


def test_temporal_kind_values_are_exactly_the_two_documented_kinds():
    """No third kind may appear by accident: each one changes eligibility."""
    kinds = {kind.value for kind in TemporalKind}
    assert kinds == {"observation", "static"}


def test_every_dataset_defaults_to_observation():
    """Backward compatibility is a property of the default, not a promise.

    A spec built without thinking about the field must keep the behaviour
    every dataset had before it existed, so the default is OBSERVATION and
    is tested against a bare spec.
    """
    spec = DatasetSpec(
        id="TEST/DEFAULT",
        name="Default",
        name_fa="پیش‌فرض",
        provider="Test",
        description="A minimal spec.",
        spatial_resolution="10 m",
        temporal_resolution="daily",
        available_from="2020-01-01",
        available_to="2020-12-31",
    )
    assert spec.temporal_kind is TemporalKind.OBSERVATION
    assert spec.is_static is False


def test_static_spec_reports_is_static():
    spec = _static_spec()
    assert spec.temporal_kind is TemporalKind.STATIC
    assert spec.is_static is True


def test_static_spec_without_static_temporal_resolution_is_rejected():
    """The declaration and the description must agree, or neither is honest."""
    with pytest.raises(ValueError, match="static"):
        DatasetSpec(
            id="TEST/BAD",
            name="Bad",
            name_fa="بد",
            provider="Test",
            description="Static kind but a series description.",
            spatial_resolution="30 m",
            temporal_resolution="daily",
            available_from="2000-02-11",
            available_to="2000-02-22",
            temporal_kind=TemporalKind.STATIC,
        )


def test_static_spec_with_static_temporal_resolution_is_accepted():
    spec = DatasetSpec(
        id="TEST/GOOD",
        name="Good",
        name_fa="خوب",
        provider="Test",
        description="Consistent static declaration.",
        spatial_resolution="30 m",
        temporal_resolution="static (single acquisition)",
        available_from="2000-02-11",
        available_to="2000-02-22",
        temporal_kind=TemporalKind.STATIC,
    )
    assert spec.is_static is True


def test_observation_spec_never_mentions_static_requirement():
    """An OBSERVATION spec with 'static' in its description is a lie."""
    with pytest.raises(ValueError, match="observation"):
        DatasetSpec(
            id="TEST/CONFUSED",
            name="Confused",
            name_fa="گیج",
            provider="Test",
            description="Claims to be a series.",
            spatial_resolution="10 m",
            temporal_resolution="static (single product)",
            available_from="2020-01-01",
            temporal_kind=TemporalKind.OBSERVATION,
        )


def test_provenance_defaults_to_observation_semantics():
    provenance = Provenance(
        source_dataset_id="X",
        source_dataset_name="X",
    )
    assert provenance.temporal_kind is TemporalKind.OBSERVATION
    assert provenance.product_date is None


def test_provenance_serialises_the_temporal_distinction():
    provenance = Provenance(
        source_dataset_id="NASA/NASADEM_HGT/001",
        source_dataset_name="NASADEM",
        temporal_kind=TemporalKind.STATIC,
        requested_start="2024-04-01",
        requested_end="2024-04-30",
        product_date="2000-02-11",
        date_start="2024-04-01",
        date_end="2024-04-30",
    )
    payload = provenance.to_dict()
    assert payload["temporal_kind"] == "static"
    # The requested period and the product date are three different
    # things and must remain distinguishable in the published record.
    assert payload["requested_start"] == "2024-04-01"
    assert payload["requested_end"] == "2024-04-30"
    assert payload["product_date"] == "2000-02-11"
    assert payload["date_start"] == "2024-04-01"
    assert payload["date_end"] == "2024-04-30"


def _static_spec() -> DatasetSpec:
    """A correctly-declared static spec, for the eligibility tests."""
    return DatasetSpec(
        id="TEST/STATIC",
        name="Static",
        name_fa="ایستا",
        provider="Test",
        description="A static surface.",
        spatial_resolution="30 m",
        temporal_resolution="static (acquired 2000-02-11)",
        available_from="2000-02-11",
        available_to="2000-02-22",
        temporal_kind=TemporalKind.STATIC,
    )
