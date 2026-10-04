"""Tests for the Moisture Stress Index (MSI, Hunt and Rock).

Phase CD-1 of the Canopy Dryness roadmap: MSI joins the existing
Sentinel-2 spectral-index infrastructure alongside NDMI, reusing the
same pure-formula registry, metric base class, SCL quality path and
provenance contract. No Sentinel-1, no baseline/anomaly, no proxy and
no composite score are introduced here.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture import indices as pure
from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    has_metric,
    register_metrics,
)
from app.services.agriculture.types import MeasurementBasis, Provenance, QualityLevel
from app.services.agriculture.water import MSIMetric, NDMIMetric, NDWIMetric


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "geometry_key": "test-geometry",
    }
    fields.update(overrides)
    return MetricContext(**fields)


# --------------------------------------------------------------------------
# Pure formula
# --------------------------------------------------------------------------


def test_msi_healthy_canopy():
    # High NIR, low SWIR1: a well-watered canopy.
    value = pure.msi(swir1=0.12, nir=0.35)
    assert value == pytest.approx(0.12 / 0.35)


def test_msi_rises_for_dry_canopy():
    wet = pure.msi(0.12, 0.35)
    dry = pure.msi(0.30, 0.30)
    assert wet is not None and dry is not None
    assert dry > wet


def test_msi_moves_opposite_ndmi():
    """MSI rises with stress where NDMI falls; both use NIR and SWIR1."""
    wet_ndmi = pure.ndmi(0.35, 0.12)
    dry_ndmi = pure.ndmi(0.30, 0.30)
    wet_msi = pure.msi(0.12, 0.35)
    dry_msi = pure.msi(0.30, 0.30)
    assert wet_ndmi is not None and dry_ndmi is not None
    assert wet_msi is not None and dry_msi is not None
    assert wet_ndmi > dry_ndmi
    assert wet_msi < dry_msi


def test_msi_is_the_ratio_counterpart_of_ndmi():
    """MSI = (1 - NDMI) / (1 + NDMI) for identical reflectances."""
    for nir, swir1 in ((0.35, 0.12), (0.30, 0.18), (0.20, 0.20)):
        ndmi_value = pure.ndmi(nir, swir1)
        msi_value = pure.msi(swir1, nir)
        assert ndmi_value is not None and msi_value is not None
        assert msi_value == pytest.approx(
            (1.0 - ndmi_value) / (1.0 + ndmi_value)
        )


def test_msi_zero_swir_is_zero_not_missing():
    """A genuine zero ratio is real data, not a gap."""
    assert pure.msi(0.0, 0.35) == pytest.approx(0.0)


def test_msi_zero_nir_is_undefined():
    """Division by zero must give no value, never inf."""
    value = pure.msi(0.12, 0.0)
    assert value is None
    assert pure.msi(0.0, 0.0) is None


def test_msi_missing_inputs_give_none():
    assert pure.msi(None, 0.35) is None
    assert pure.msi(0.12, None) is None
    assert pure.msi(None, None) is None


def test_msi_non_finite_gives_none():
    assert pure.msi(float("nan"), 0.35) is None
    assert pure.msi(0.12, float("inf")) is None
    assert pure.msi(float("-inf"), 0.35) is None


def test_msi_boolean_input_rejected():
    """bool is an int subclass and must not be treated as a reflectance."""
    assert pure.msi(True, 0.35) is None
    assert pure.msi(0.12, False) is None


def test_msi_rejects_non_numeric():
    assert pure.msi("0.12", 0.35) is None
    assert pure.msi(0.12, [0.35]) is None


def test_msi_result_is_finite_for_valid_input():
    value = pure.msi(0.18, 0.30)
    assert value is not None
    assert math.isfinite(value)


# --------------------------------------------------------------------------
# Metadata registry
# --------------------------------------------------------------------------


def test_msi_has_formula_text():
    assert pure.FORMULA_TEXT["msi"] == "(B11 / B8)"


def test_msi_has_band_roles():
    assert pure.BAND_ROLES["msi"] == ("B11", "B8")


def test_msi_has_expected_range():
    low, high = pure.EXPECTED_RANGE["msi"]
    assert low < high
    assert low >= 0.0


def test_msi_has_typical_range_within_expected():
    typical_low, typical_high = pure.TYPICAL_VEGETATION_RANGE["msi"]
    assert typical_low < typical_high
    expected_low, expected_high = pure.EXPECTED_RANGE["msi"]
    assert expected_low <= typical_low <= expected_high
    assert expected_low <= typical_high <= expected_high


def test_msi_band_roles_reference_real_sentinel2_bands():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    for band in pure.BAND_ROLES["msi"]:
        assert spec.has_band(band), f"MSI references unknown band {band}"


def test_sample_msi_lands_in_typical_range():
    value = pure.msi(0.18, 0.30)
    low, high = pure.TYPICAL_VEGETATION_RANGE["msi"]
    assert value is not None
    assert low <= value <= high


# --------------------------------------------------------------------------
# Metric wiring
# --------------------------------------------------------------------------


def test_msi_uses_swir_and_nir():
    metric = MSIMetric()
    assert metric.key == "msi"
    assert metric.index_name == "MSI"
    assert metric.required_bands == ("B11", "B8")


def test_msi_required_bands_match_the_pure_registry():
    metric = MSIMetric()
    assert metric.required_bands == pure.BAND_ROLES[metric.index_name.lower()]


def test_msi_is_not_ndwi_and_not_ndmi():
    msi = MSIMetric()
    assert msi.required_bands != NDWIMetric().required_bands
    assert msi.required_bands != NDMIMetric().required_bands
    assert msi.index_name != NDWIMetric().index_name
    assert msi.index_name != NDMIMetric().index_name


def test_msi_reduces_at_twenty_metres():
    """B11 is acquired at 20 m; reducing at 10 m would resample it."""
    assert MSIMetric().band_scale == 20


def test_msi_scale_is_not_overridable_by_the_context():
    context = make_context(scale=10)
    assert MSIMetric().effective_scale(context) == 20


def test_msi_expression_is_swir_over_nir():
    seen: dict = {}

    class _SpyBand:
        def __init__(self, name: str) -> None:
            self.name = name

    class _SpyComposite:
        def select(self, band: str):
            seen.setdefault("selected", []).append(band)
            return _SpyBand(band)

        def expression(self, formula: str, variables: dict):
            seen["formula"] = formula
            seen["variables"] = {
                key: value.name for key, value in variables.items()
            }
            return seen

    MSIMetric().build_expression(_SpyComposite(), None)
    assert seen["formula"] == "SWIR / NIR"
    assert seen["variables"] == {"SWIR": "B11", "NIR": "B8"}
    assert seen["selected"] == ["B11", "B8"]


def test_msi_bands_exist_in_sentinel2_registry():
    metric = MSIMetric()
    dataset = metric.primary_dataset()
    for band in metric.required_bands:
        assert dataset.has_band(band)


# --------------------------------------------------------------------------
# Measurement basis honesty
# --------------------------------------------------------------------------


def test_msi_is_derived_not_measured():
    metric = MSIMetric()
    assert metric.measurement_basis is MeasurementBasis.DERIVED
    assert metric.measurement_basis not in (
        MeasurementBasis.PROXY,
        MeasurementBasis.INFERENCE,
        MeasurementBasis.DIRECT,
    )


def test_msi_is_not_flagged_as_proxy_in_metadata():
    assert MSIMetric().metadata()["is_proxy"] is False


def test_msi_domain_note_names_ndmi_not_leaf_layers():
    note = MSIMetric().domain_note.lower()
    assert "ndmi" in note
    assert "middle" not in note
    assert "dry leaves" not in note


def test_msi_limitations_deny_leaf_fraction_conversion():
    joined = " ".join(MSIMetric().limitations).lower()
    assert "not a fraction of dry leaves" in joined


def test_msi_does_not_claim_to_detect_disease_or_pests():
    forbidden_claims = (
        "detect disease",
        "detects disease",
        "diagnose disease",
        "identify disease",
        "detect pest",
        "diagnose pest",
        "nutrient deficiency",
    )
    text = " ".join(
        list(MSIMetric().limitations) + [MSIMetric().description]
    ).lower()
    for phrase in forbidden_claims:
        assert phrase not in text


def test_msi_metadata_is_complete():
    metadata = MSIMetric().metadata()
    assert metadata["key"] == "msi"
    assert metadata["display_name"]
    assert metadata["display_name_fa"]
    assert metadata["domain"] == "water"
    assert metadata["unit"]
    assert metadata["description"]
    assert metadata["dataset_ids"]
    assert metadata["limitations"]
    assert any("\u0600" <= ch <= "\u06ff" for ch in metadata["display_name_fa"])


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_msi_provenance_is_complete():
    metric = MSIMetric()
    context = make_context()
    provenance = metric.build_provenance(
        context=context,
        dataset=metric.primary_dataset(),
        bands=list(metric.required_bands),
        formula=pure.FORMULA_TEXT["msi"],
        quality=QualityLevel.GOOD,
        image_count=7,
    )
    assert isinstance(provenance, Provenance)
    assert provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    assert provenance.bands == ["B11", "B8"]
    assert provenance.formula == "(B11 / B8)"
    assert provenance.unit == "index"
    assert provenance.spatial_resolution
    assert provenance.temporal_resolution
    assert provenance.aggregation_method
    assert provenance.measurement_basis is MeasurementBasis.DERIVED
    assert provenance.quality_level is QualityLevel.GOOD
    assert provenance.date_start == "2026-05-01"
    assert provenance.image_count == 7
    assert provenance.limitations
    assert provenance.citation


# --------------------------------------------------------------------------
# Coverage windows
# --------------------------------------------------------------------------


def test_msi_rejects_pre_launch_requests():
    context = make_context(start_date="2010-01-01", end_date="2010-12-31")
    can, reason = MSIMetric().can_attempt(context)
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_msi_accepts_current_requests():
    context = make_context()
    can, reason = MSIMetric().can_attempt(context)
    assert can is True
    assert reason is None


# --------------------------------------------------------------------------
# Registration and neighbours intact
# --------------------------------------------------------------------------


def test_msi_registers_cleanly():
    from app.services.agriculture.water import WATER_METRICS

    register_metrics(WATER_METRICS)
    assert has_metric("msi")
    assert get_metric("msi").key == "msi"


def test_ndmi_wiring_is_unchanged():
    assert NDMIMetric().required_bands == ("B8", "B11")
    assert NDMIMetric().index_name == "NDMI"
    assert NDMIMetric().band_scale == 20


def test_ndwi_wiring_is_unchanged():
    assert NDWIMetric().required_bands == ("B3", "B8")
    assert NDWIMetric().index_name == "NDWI"
