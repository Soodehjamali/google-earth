"""Tests for the vegetation metric wiring.

These tests verify that every vegetation metric is correctly declared and
that its required bands actually exist in its source dataset. That check
matters because a metric referencing a non-existent band would fail only
at runtime, inside an Earth Engine call, far from the mistake.

The Earth Engine expressions themselves are not executed here; they
cannot be without credentials. What is verified is that the pure formulas
and the declared band roles agree, which is the part that goes wrong
silently.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import pytest

from app.services.agriculture import indices as pure
from app.services.agriculture.base import Metric, MetricDomain
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.types import MeasurementBasis, QualityLevel, Provenance
from app.services.agriculture.vegetation import (
    EVIMetric,
    FCOVERMetric,
    FPARMetric,
    LAIMetric,
    MSAVIMetric,
    NDREMetric,
    NDVIMetric,
    SAVIMetric,
    VEGETATION_METRICS,
)

EXPECTED_KEYS = {
    "ndvi", "evi", "savi", "msavi", "ndre", "lai", "fapar", "fcover",
}


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# --------------------------------------------------------------------------
# Collection integrity
# --------------------------------------------------------------------------


def test_all_expected_vegetation_metrics_present():
    keys = {m.key for m in VEGETATION_METRICS}
    assert keys == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in VEGETATION_METRICS]
    assert len(keys) == len(set(keys))


def test_all_vegetation_metrics_share_the_domain():
    for metric in VEGETATION_METRICS:
        assert metric.domain == MetricDomain.VEGETATION, metric.key


def test_all_metrics_are_metric_instances():
    for metric in VEGETATION_METRICS:
        assert isinstance(metric, Metric)


def test_vegetation_metrics_register_cleanly():
    register_metrics(VEGETATION_METRICS)
    from app.services.agriculture.catalog import all_metrics

    assert {m.key for m in all_metrics()} == EXPECTED_KEYS


# --------------------------------------------------------------------------
# Required bands must exist in the source dataset
# --------------------------------------------------------------------------


def test_spectral_index_bands_exist_in_sentinel2_registry():
    """The check that catches a typo'd band name before it reaches Earth Engine."""
    for metric in VEGETATION_METRICS:
        required = getattr(metric, "required_bands", ())
        if not required:
            continue
        dataset = metric.primary_dataset()
        for band in required:
            assert dataset.has_band(band), (
                f"Metric {metric.key!r} requires band {band!r} but dataset "
                f"{dataset.id!r} does not declare it"
            )


def test_modis_structural_metrics_use_registered_bands():
    for metric in (LAIMetric(), FPARMetric(), FCOVERMetric()):
        dataset = metric.primary_dataset()
        assert dataset.has_band(metric.source_band), (
            f"{metric.key} uses {metric.source_band} which is not in "
            f"{dataset.id}"
        )


def test_band_roles_match_the_declared_required_bands():
    """The pure formula's band roles must match what the metric requests.

    A mismatch here means the Earth Engine expression would read different
    bands from the ones the provenance reports, which would make the
    provenance a lie even though the number was computed.
    """
    for metric in VEGETATION_METRICS:
        required = getattr(metric, "required_bands", ())
        index_name = getattr(metric, "index_name", None)
        if not required or not index_name:
            continue
        roles = pure.BAND_ROLES.get(index_name.lower())
        assert roles is not None, f"no band roles declared for {index_name}"
        assert set(roles) == set(required), (
            f"{metric.key}: formula uses bands {sorted(roles)} but the "
            f"metric requests {sorted(required)}"
        )


# --------------------------------------------------------------------------
# Scale selection respects band resolution
# --------------------------------------------------------------------------


def test_ndre_uses_twenty_metre_scale():
    """The red edge band is 20 m; reducing it at 10 m would misreport resolution."""
    assert NDREMetric().band_scale == 20


def test_ten_metre_indices_use_ten_metre_scale():
    for metric in (NDVIMetric(), EVIMetric(), SAVIMetric(), MSAVIMetric()):
        assert metric.band_scale == 10, metric.key


def test_modis_metrics_use_five_hundred_metre_scale():
    for metric in (LAIMetric(), FPARMetric(), FCOVERMetric()):
        assert metric.default_scale == 500, metric.key


def test_effective_scale_is_the_band_scale_for_index_metrics():
    from app.services.agriculture.base import MetricContext

    context = MetricContext(
        geometry={}, start_date="2026-05-01", end_date="2026-05-31",
        geometry_key="k",
    )
    assert NDREMetric().effective_scale(context) == 20
    assert NDVIMetric().effective_scale(context) == 10


# --------------------------------------------------------------------------
# Measurement basis honesty
# --------------------------------------------------------------------------


def test_spectral_indices_are_derived_not_measured():
    """An index computed from bands is derived, and must say so."""
    for metric in (NDVIMetric(), EVIMetric(), SAVIMetric(), MSAVIMetric(), NDREMetric()):
        assert metric.measurement_basis is MeasurementBasis.DERIVED, metric.key


def test_modis_structural_metrics_are_products():
    for metric in (LAIMetric(), FPARMetric(), FCOVERMetric()):
        assert metric.measurement_basis is MeasurementBasis.PRODUCT, metric.key


def test_no_vegetation_metric_is_marked_as_a_proxy():
    """None of these are proxies; they are derived or product values."""
    for metric in VEGETATION_METRICS:
        assert metric.measurement_basis not in (
            MeasurementBasis.PROXY,
            MeasurementBasis.INFERENCE,
        ), metric.key


# --------------------------------------------------------------------------
# Safety: no diagnostic language, and an explicit non-diagnostic caveat
# --------------------------------------------------------------------------


FORBIDDEN_WORDS = (
    "disease", "diseased", "pest", "infestation",
    "infected", "pathogen", "diagnos",
)

#: Phrases that mark a sentence as a disclaimer rather than a claim. A
#: metric may only mention a forbidden term when it is denying it.
NEGATION_MARKERS = (
    "cannot", "does not", "do not", "not ", "no ", "unable",
    "without", "neither", "rather than", "instead of",
)


@pytest.mark.parametrize("metric", VEGETATION_METRICS, ids=lambda m: m.key)
def test_descriptions_avoid_diagnostic_language(metric: Metric):
    """Satellite indices must never claim to diagnose a cause.

    A metric is allowed, and indeed encouraged, to say that it *cannot*
    diagnose disease or pests: stating the limitation explicitly is more
    useful than staying silent. What it must never do is assert a
    diagnosis.

    So this check does not ban the words outright. For each forbidden
    term it inspects the sentence containing it, and requires that
    sentence to carry a negation. "Detects disease" would fail;
    "does not distinguish disease" passes.
    """
    text = " ".join([
        metric.description,
        metric.display_name,
        *metric.limitations,
    ]).lower()

    # Split on sentence boundaries only. Splitting on commas as well would
    # tear a disclaimer apart and leave a bare forbidden word with no
    # surrounding negation to find.
    import re

    sentences = [
        s.strip()
        for s in re.split(r"[.;]\s+|\n", text)
        if s.strip()
    ]

    for word in FORBIDDEN_WORDS:
        for sentence in sentences:
            if word not in sentence:
                continue
            # Check the whole sentence for a negation marker.
            assert any(marker in sentence for marker in NEGATION_MARKERS), (
                f"Metric {metric.key!r} mentions {word!r} in a sentence with "
                f"no negation, which reads as a diagnostic claim: "
                f"{sentence!r}"
            )


@pytest.mark.parametrize("metric", VEGETATION_METRICS, ids=lambda m: m.key)
def test_every_metric_declares_limitations(metric: Metric):
    assert metric.limitations, f"{metric.key} declares no limitations"


def test_vegetation_metrics_carry_a_non_diagnostic_limitation():
    """The explicit statement that an index is not a diagnosis."""
    for metric in VEGETATION_METRICS:
        joined = " ".join(metric.limitations).lower()
        assert "not" in joined or "cannot" in joined, (
            f"{metric.key} does not state what it cannot determine"
        )


# --------------------------------------------------------------------------
# Metadata completeness
# --------------------------------------------------------------------------


@pytest.mark.parametrize("metric", VEGETATION_METRICS, ids=lambda m: m.key)
def test_metadata_is_complete(metric: Metric):
    metadata = metric.metadata()
    assert metadata["key"] == metric.key
    assert metadata["display_name"]
    assert metadata["display_name_fa"]
    assert metadata["domain"] == "vegetation"
    assert metadata["unit"]
    assert metadata["description"]
    assert metadata["dataset_ids"]
    assert metadata["limitations"]
    assert metadata["is_proxy"] is False


@pytest.mark.parametrize("metric", VEGETATION_METRICS, ids=lambda m: m.key)
def test_persian_display_name_is_actually_persian(metric: Metric):
    assert any("\u0600" <= ch <= "\u06ff" for ch in metric.display_name_fa), (
        f"{metric.key} has a display_name_fa that contains no Persian "
        "characters"
    )


@pytest.mark.parametrize("metric", VEGETATION_METRICS, ids=lambda m: m.key)
def test_index_metrics_have_a_formula_recorded(metric: Metric):
    index_name = getattr(metric, "index_name", None)
    if not index_name:
        return
    assert index_name.lower() in pure.FORMULA_TEXT
    assert pure.FORMULA_TEXT[index_name.lower()]


# --------------------------------------------------------------------------
# Coverage windows
# --------------------------------------------------------------------------


def test_sentinel2_metrics_reject_pre_launch_requests():
    from app.services.agriculture.base import MetricContext

    context = MetricContext(
        geometry={}, start_date="2010-01-01", end_date="2010-12-31",
        geometry_key="k",
    )
    can, reason = NDVIMetric().can_attempt(context)
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_sentinel2_metrics_accept_current_requests():
    from app.services.agriculture.base import MetricContext

    context = MetricContext(
        geometry={}, start_date="2026-05-01", end_date="2026-05-31",
        geometry_key="k",
    )
    can, reason = NDVIMetric().can_attempt(context)
    assert can is True
    assert reason is None


def test_modis_lai_rejects_pre_2002_requests():
    from app.services.agriculture.base import MetricContext

    context = MetricContext(
        geometry={}, start_date="2000-01-01", end_date="2000-12-31",
        geometry_key="k",
    )
    can, reason = LAIMetric().can_attempt(context)
    assert can is False
    assert reason == "outside_temporal_coverage"


# --------------------------------------------------------------------------
# Provenance declaration completeness
# --------------------------------------------------------------------------


def test_build_provenance_produces_a_complete_record():
    """Every field the specification demands must be populated."""
    from app.services.agriculture.base import MetricContext

    metric = NDVIMetric()
    context = MetricContext(
        geometry={}, start_date="2026-05-01", end_date="2026-05-31",
        geometry_key="k",
    )
    provenance = metric.build_provenance(
        context=context,
        dataset=metric.primary_dataset(),
        bands=list(metric.required_bands),
        formula=pure.FORMULA_TEXT["ndvi"],
        quality=QualityLevel.GOOD,
        image_count=7,
    )
    assert isinstance(provenance, Provenance)
    assert provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    assert provenance.bands == ["B4", "B8"]
    assert provenance.formula == "(B8 - B4) / (B8 + B4)"
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


def test_savi_provenance_reports_its_actual_soil_factor():
    """The L value must be traceable: the same reflectance gives different SAVI."""
    metric = SAVIMetric()
    assert metric.soil_factor == 0.5
    from app.services.agriculture.base import MetricContext

    context = MetricContext(
        geometry={}, start_date="2026-05-01", end_date="2026-05-31",
        geometry_key="k",
    )
    provenance = metric.build_provenance(
        context=context,
        dataset=metric.primary_dataset(),
        bands=["B4", "B8"],
        formula="placeholder",
        quality=QualityLevel.GOOD,
    )
    assert "L = 0.5" in provenance.formula


# --------------------------------------------------------------------------
# Class attributes used by the Earth Engine layer
# --------------------------------------------------------------------------


def test_index_metric_class_attributes_present():
    for metric in (NDVIMetric(), EVIMetric(), SAVIMetric(), MSAVIMetric(), NDREMetric()):
        assert metric.index_name, metric.key
        assert metric.required_bands, metric.key
        assert metric.band_scale > 0, metric.key


def test_band_scale_matches_registry_resolution():
    """A 20 m band must not be declared at a 10 m working scale."""
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    # B5 is documented as a 20 m band in the registry's resolution string.
    assert "20 m" in spec.spatial_resolution
    assert NDREMetric().band_scale == 20
    assert NDVIMetric().band_scale == 10
