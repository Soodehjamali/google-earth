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


def test_elevation_correction_physics_and_signs():
    """Verify physical lapse-rate correction behavior."""
    # 1. Higher elevation site (z_site > z_cell): must be cooler
    # Site 1500m, grid 1000m -> delta_z = +500m (+0.5km)
    # At -6.5 °C/km, delta_T = -3.25 °C. 20.0 °C -> 16.75 °C
    res_higher = correct_temperature_for_elevation(
        t_cell=20.0,
        z_cell=1000.0,
        z_site=1500.0,
    )
    assert res_higher.delta_c == -3.25
    assert res_higher.corrected_value == 16.75
    assert res_higher.uncertainty_c == 1.0  # default daytime uncertainty

    # 2. Lower elevation site / valley (z_site < z_cell): must be warmer
    # Site 800m, grid 1000m -> delta_z = -200m (-0.2km)
    # At -6.5 °C/km, delta_T = +1.30 °C. 20.0 °C -> 21.30 °C
    res_lower = correct_temperature_for_elevation(
        t_cell=20.0,
        z_cell=1000.0,
        z_site=800.0,
    )
    assert res_lower.delta_c == 1.30
    assert res_lower.corrected_value == 21.30

    # 3. Exact equal elevations: zero delta, exact equality
    res_equal = correct_temperature_for_elevation(
        t_cell=25.0,
        z_cell=1200.0,
        z_site=1200.0,
    )
    assert res_equal.delta_c == 0.0
    assert res_equal.corrected_value == 25.0

    # 4. Custom lapse rate: -5.0 °C/km
    res_custom = correct_temperature_for_elevation(
        t_cell=20.0,
        z_cell=1000.0,
        z_site=2000.0,
        lapse_rate_c_per_km=-5.0,
    )
    assert res_custom.delta_c == -5.0
    assert res_custom.corrected_value == 15.0

    # 5. Nighttime minimum temperature: higher uncertainty (±2.0 °C) & inversion warning
    res_night = correct_temperature_for_elevation(
        t_cell=5.0,
        z_cell=1000.0,
        z_site=1200.0,
        is_night_minimum=True,
    )
    assert res_night.uncertainty_c == 2.0
    assert "وارونگی" in res_night.uncertainty_note_fa
    assert "اینورژن" in res_night.uncertainty_note_fa


def test_aggregate_hourly_to_local_days():
    """Verify that UTC timestamps are grouped accurately into Asia/Tehran civil days."""
    from datetime import datetime, timezone

    # Timestamps in UTC:
    # 2024-05-10 21:00 UTC = 2024-05-11 00:30 Asia/Tehran (belongs to May 11th local)
    # 2024-05-11 00:30 UTC = 2024-05-11 04:00 Asia/Tehran (belongs to May 11th local)
    # 2024-05-11 11:30 UTC = 2024-05-11 15:00 Asia/Tehran (belongs to May 11th local)
    # 2024-05-11 20:00 UTC = 2024-05-11 23:30 Asia/Tehran (belongs to May 11th local)
    # 2024-05-11 21:00 UTC = 2024-05-12 00:30 Asia/Tehran (belongs to May 12th local)

    records = [
        (datetime(2024, 5, 10, 21, 0, tzinfo=timezone.utc), 14.0),
        (datetime(2024, 5, 11, 0, 30, tzinfo=timezone.utc), 10.0),
        (datetime(2024, 5, 11, 11, 30, tzinfo=timezone.utc), 28.0),
        (datetime(2024, 5, 11, 20, 0, tzinfo=timezone.utc), 22.0),
        (datetime(2024, 5, 11, 21, 0, tzinfo=timezone.utc), 12.0),
    ]

    grouped = aggregate_hourly_to_local_days(records, timezone_str="Asia/Tehran")
    assert "2024-05-11" in grouped
    assert "2024-05-12" in grouped

    # On May 11 local: min should be 10.0, max 28.0, count 4
    may11 = grouped["2024-05-11"]
    assert may11["min"] == 10.0
    assert may11["max"] == 28.0
    assert may11["count"] == 4

    # On May 12 local: value 12.0
    may12 = grouped["2024-05-12"]
    assert may12["min"] == 12.0
    assert may12["max"] == 12.0
    assert may12["count"] == 1


def test_gdd_metric_with_elevation_correction_and_hourly():
    """Verify that GDDMetric correctly accumulates GDD with elevation-corrected temperatures."""
    from datetime import datetime, timezone
    from app.services.agriculture.base import MetricContext
    from app.services.agriculture.climate import GDDMetric

    # 2 days of hourly data in Asia/Tehran
    # Day 1: min 15.0 °C, max 25.0 °C -> mean 20.0 °C. With base 10.0 °C: GDD = 10.0
    # Day 2: min 12.0 °C, max 22.0 °C -> mean 17.0 °C. With base 10.0 °C: GDD = 7.0
    # Total raw GDD = 17.0
    records = [
        # Day 1 (May 10 local)
        (datetime(2024, 5, 10, 4, 0, tzinfo=timezone.utc), 15.0),
        (datetime(2024, 5, 10, 12, 0, tzinfo=timezone.utc), 25.0),
        # Day 2 (May 11 local)
        (datetime(2024, 5, 11, 4, 0, tzinfo=timezone.utc), 12.0),
        (datetime(2024, 5, 11, 12, 0, tzinfo=timezone.utc), 22.0),
    ]

    metric = GDDMetric()

    # 1. Uncorrected (equal elevations: 1000m to 1000m)
    ctx_uncorrected = MetricContext(
        start_date="2024-05-10",
        end_date="2024-05-11",
        geometry=None,
        options={
            "hourly_temperatures": records,
            "cell_elevation_m": 1000.0,
            "site_elevation_m": 1000.0,
            "base_temperature": 10.0,
            "upper_temperature": 35.0,
        },
    )
    res_raw = metric.compute(ctx_uncorrected)
    assert res_raw.value == pytest.approx(17.0, abs=0.01)

    # 2. Corrected for higher site: site 1500m (+500m, +0.5km)
    # At -6.5 °C/km: delta_T = -3.25 °C
    # Day 1 corrected: min 11.75, max 21.75 -> mean 16.75 -> GDD = 6.75
    # Day 2 corrected: min 8.75, max 18.75 -> mean 13.75 -> GDD = 3.75
    # Total corrected GDD = 10.50
    ctx_corrected = MetricContext(
        start_date="2024-05-10",
        end_date="2024-05-11",
        geometry=None,
        options={
            "hourly_temperatures": records,
            "cell_elevation_m": 1000.0,
            "site_elevation_m": 1500.0,
            "base_temperature": 10.0,
            "upper_temperature": 35.0,
        },
    )
    res_corr = metric.compute(ctx_corrected)
    assert res_corr.value == pytest.approx(10.5, abs=0.01)
    assert res_corr.provenance.cell_elevation_m == 1000.0
    assert res_corr.provenance.site_elevation_m == 1500.0
    assert "Elevation correction" in res_corr.provenance.formula or "-3.25" in res_corr.provenance.formula


def test_coverage_summary_partitioning_and_hard_invariants():
    """Verify that coarse context metrics are NEVER counted as valid in coverage numerator N."""
    from app.services.agriculture.quality_gating import compute_coverage_summary

    # Mock outcomes:
    # 2 valid metrics (ndvi, evi)
    # 2 coarse metrics (temperature_mean, soil_moisture_rootzone)
    # 1 unavailable metric (precipitation)
    p_valid = Provenance(
        source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        source_dataset_name="Sentinel-2",
        quality_level=QualityLevel.GOOD,
        quality_state=QualityState.VALID,
    )
    p_coarse = Provenance(
        source_dataset_id="ECMWF/ERA5_LAND/DAILY_AGGR",
        source_dataset_name="ERA5-Land",
        quality_level=QualityLevel.GOOD,
        quality_state=QualityState.COARSE_CONTEXT,
    )
    p_unavail = Provenance(
        source_dataset_id="UCSB-CHG/CHIRPS/DAILY",
        source_dataset_name="CHIRPS",
        quality_level=QualityLevel.UNAVAILABLE,
        quality_state=QualityState.UNAVAILABLE,
    )

    outcomes = {
        "ndvi": MetricResult(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="شاخص سبزینگی",
            status="ok",
            value=0.55,
            provenance=p_valid,
            quality_state=QualityState.VALID,
        ),
        "evi": MetricResult(
            metric_key="evi",
            display_name="EVI",
            display_name_fa="شاخص سبزینگی بهبودیافته",
            status="ok",
            value=0.45,
            provenance=p_valid,
            quality_state=QualityState.VALID,
        ),
        "temperature_mean": MetricResult(
            metric_key="temperature_mean",
            display_name="Mean Temp",
            display_name_fa="میانگین دما",
            status="ok",
            value=25.0,
            provenance=p_coarse,
            quality_state=QualityState.COARSE_CONTEXT,
        ),
        "precipitation": MetricResult.unavailable(
            metric_key="precipitation",
            display_name="Precipitation",
            display_name_fa="بارندگی",
            reason="masked",
            provenance=p_unavail,
        ),
    }

    # When requested for vegetation and climate domains:
    # Vegetation has 14 metrics (ndvi and evi are valid, 12 unavailable)
    # Climate has 10 metrics (temperature_mean is coarse, 9 unavailable)
    # Total applicable = 14 + 10 = 24 metrics
    cov = compute_coverage_summary(
        outcomes=outcomes,
        requested_domains=["vegetation", "climate"],
    )

    # HARD INVARIANT: N = 2 (ndvi, evi only). Coarse temperature_mean MUST NOT be in N!
    assert cov["valid"] == 2
    # K = 1 (temperature_mean)
    assert cov["coarse_context"] == 1
    # Total applicable M = 24
    assert cov["total"] == 24
    # Unavailable U = 24 - 2 - 1 = 21
    assert cov["unavailable"] == 21
    # Ratio N / M = 2 / 24 = 0.0833
    assert cov["valid_ratio"] == pytest.approx(round(2 / 24, 4), abs=0.0001)

    # Verify per-domain breakdown
    assert "vegetation" in cov["by_domain"]
    veg = cov["by_domain"]["vegetation"]
    assert veg["valid"] == 2
    assert veg["coarse_context"] == 0
    assert veg["total"] == 14
    assert veg["unavailable"] == 12

    assert "climate" in cov["by_domain"]
    clim = cov["by_domain"]["climate"]
    assert clim["valid"] == 0
    assert clim["coarse_context"] == 1
    assert clim["total"] == 10
    assert clim["unavailable"] == 9


def test_coverage_summary_domain_applicability_denominator():
    """Verify denominator M dynamically reflects requested domains, not a flat 118."""
    from app.services.agriculture.quality_gating import compute_coverage_summary

    # Empty outcomes: all metrics will be counted as unavailable
    cov_veg = compute_coverage_summary(outcomes={}, requested_domains=["vegetation"])
    assert cov_veg["total"] == 14
    assert cov_veg["valid"] == 0
    assert cov_veg["unavailable"] == 14
    assert cov_veg["valid_ratio"] == 0.0

    cov_veg_water = compute_coverage_summary(
        outcomes={}, requested_domains=["vegetation", "water"]
    )
    # 14 vegetation + 13 water = 27
    assert cov_veg_water["total"] == 27
    assert cov_veg_water["valid"] == 0
    assert cov_veg_water["unavailable"] == 27

    cov_all = compute_coverage_summary(outcomes={}, requested_domains=None)
    # All registered metrics across all domains
    assert cov_all["total"] == 118


def test_agricultural_analysis_response_legacy_coverage_auto_derivation():
    """Verify that deserializing a legacy report without coverage dynamically populates coverage."""
    from app.schemas.agriculture import AgriculturalAnalysisResponse

    p_valid_dict = {
        "source_dataset_id": "COPERNICUS/S2_SR_HARMONIZED",
        "source_dataset_name": "Sentinel-2",
        "quality_level": "good",
        "quality_state": "valid",
    }
    p_coarse_dict = {
        "source_dataset_id": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "source_dataset_name": "ERA5-Land",
        "quality_level": "good",
        "quality_state": "coarse_context",
    }

    legacy_payload = {
        "time_start": "2024-05-01",
        "time_end": "2024-05-31",
        "overall_sufficiency": "limited",
        "evidence_bundles": {
            "vegetation": {
                "name": "vegetation",
                "items": [
                    {
                        "metric_key": "ndvi",
                        "value": 0.45,
                        "unit": "index",
                        "status": "direct",
                        "quality": "good",
                        "quality_state": "valid",
                        "is_usable": True,
                        "is_proxy": False,
                        "provenance": p_valid_dict,
                    }
                ],
                "unavailable": [],
            },
            "climate": {
                "name": "climate",
                "items": [
                    {
                        "metric_key": "temperature_mean",
                        "value": 24.0,
                        "unit": "°C",
                        "status": "modelled",
                        "quality": "good",
                        "quality_state": "coarse_context",
                        "is_usable": True,
                        "is_proxy": False,
                        "provenance": p_coarse_dict,
                    }
                ],
                "unavailable": [],
            },
        },
        # NOTE: 'coverage' is missing completely!
    }

    resp = AgriculturalAnalysisResponse.model_validate(legacy_payload)
    assert resp.coverage is not None
    assert resp.coverage.valid == 1
    assert resp.coverage.coarse_context == 1
    assert resp.coverage.total == 118
    assert resp.coverage.unavailable == 116
    assert resp.coverage.valid_ratio == pytest.approx(round(1 / 118, 4), abs=0.0001)


