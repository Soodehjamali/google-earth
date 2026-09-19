"""Tests for the metric contract.

Covers context construction, cache key determinism, coverage-window
capability checks, and the constructor validation that stops a
half-declared metric from being registered.

No network and no Earth Engine are required: the context accepts an
opaque geometry object, and the tests pass dictionaries.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.agriculture.base import (
    Metric,
    MetricContext,
    MetricDomain,
    coverage_overlap_days,
)
from app.services.agriculture.types import (
    NOT_AVAILABLE_REASON_OUT_OF_COVERAGE,
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
)


# --------------------------------------------------------------------------
# A concrete metric for exercising the base class
# --------------------------------------------------------------------------


class _EchoMetric(Metric):
    key = "echo"
    display_name = "Echo"
    display_name_fa = "پژواک"
    domain = MetricDomain.VEGETATION
    unit = "index"
    dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
    measurement_basis = MeasurementBasis.DIRECT
    description = "Returns a fixed value, for testing."
    limitations = ("Not a real metric.",)

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = self.build_provenance(
            context=context,
            dataset=self.primary_dataset(),
            bands=["B4", "B8"],
            formula="fixed",
            quality=QualityLevel.GOOD,
            image_count=5,
        )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=0.5,
            unit=self.unit,
            provenance=provenance,
        )


# --------------------------------------------------------------------------
# Constructor validation
# --------------------------------------------------------------------------


def test_metric_requires_a_key():
    class NoKey(Metric):
        display_name = "X"
        display_name_fa = "ایکس"
        domain = MetricDomain.VEGETATION

        def compute(self, context):  # pragma: no cover - never called
            raise NotImplementedError

    with pytest.raises(ValueError, match="non-empty 'key'"):
        NoKey()


def test_metric_requires_bilingual_display_name():
    class NoPersian(Metric):
        key = "x"
        display_name = "X"
        display_name_fa = ""
        domain = MetricDomain.VEGETATION

        def compute(self, context):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="display_name_fa"):
        NoPersian()


def test_metric_requires_a_known_domain():
    class BadDomain(Metric):
        key = "x"
        display_name = "X"
        display_name_fa = "ایکس"
        domain = "astrology"

        def compute(self, context):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="unknown domain"):
        BadDomain()


def test_valid_metric_constructs():
    metric = _EchoMetric()
    assert metric.key == "echo"
    assert metric.domain == MetricDomain.VEGETATION
    assert repr(metric).startswith("<_EchoMetric")


def test_metric_domains_are_the_expected_set():
    assert set(MetricDomain.ALL) == {
        "vegetation", "water", "soil", "climate",
        "thermal", "terrain", "crop", "phenology",
        "landcover",
    }


def test_landcover_is_a_distinct_domain_from_crop():
    """Generic land cover must not be filed under the crop domain.

    The two answer different questions. ``landcover`` describes what
    covers the ground using a generic classification scheme; ``crop`` is
    reserved for genuinely crop-specific metrics, such as a crop-type or
    crop-condition metric that names a species. Filing MCD12Q1's generic
    IGBP classes under ``crop`` would invite a consumer to read a
    land-cover class as a crop identification, which it is not.
    """
    assert MetricDomain.LANDCOVER == "landcover"
    assert MetricDomain.CROP == "crop"
    assert MetricDomain.LANDCOVER != MetricDomain.CROP


def test_the_domain_tuple_is_free_of_duplicates():
    assert len(MetricDomain.ALL) == len(set(MetricDomain.ALL))


# --------------------------------------------------------------------------
# Cache keys
# --------------------------------------------------------------------------


def _context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2026-05-01",
        end_date="2026-05-31",
        geometry_key="abc123",
        cloud_max_percent=20.0,
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def test_cache_key_is_deterministic():
    context = _context()
    assert context.cache_key("ndvi") == context.cache_key("ndvi")


def test_cache_key_differs_by_metric():
    context = _context()
    assert context.cache_key("ndvi") != context.cache_key("evi")


def test_cache_key_differs_by_geometry():
    a = _context(geometry_key="aaa")
    b = _context(geometry_key="bbb")
    assert a.cache_key("ndvi") != b.cache_key("ndvi")


def test_cache_key_differs_by_dates():
    a = _context(start_date="2026-05-01")
    b = _context(start_date="2026-06-01")
    assert a.cache_key("ndvi") != b.cache_key("ndvi")


def test_cache_key_differs_by_scale():
    a = _context(scale=10)
    b = _context(scale=20)
    assert a.cache_key("ndvi") != b.cache_key("ndvi")


def test_cache_key_differs_by_cloud_tolerance():
    a = _context(cloud_max_percent=10.0)
    b = _context(cloud_max_percent=30.0)
    assert a.cache_key("ndvi") != b.cache_key("ndvi")


def test_cache_key_differs_by_dataset_version():
    """A dataset revision must invalidate cached results."""
    a = _context(dataset_versions={"S2": "v1"})
    b = _context(dataset_versions={"S2": "v2"})
    assert a.cache_key("ndvi") != b.cache_key("ndvi")


def test_cache_key_ignores_dataset_version_ordering():
    a = _context(dataset_versions={"A": "1", "B": "2"})
    b = _context(dataset_versions={"B": "2", "A": "1"})
    assert a.cache_key("ndvi") == b.cache_key("ndvi")


def test_cache_key_folds_in_extras():
    context = _context()
    assert context.cache_key("ndvi", aggregation="mean") != context.cache_key(
        "ndvi", aggregation="median"
    )


def test_cache_key_is_a_hex_digest():
    key = _context().cache_key("ndvi")
    assert len(key) == 64
    int(key, 16)  # raises if not hexadecimal


# --------------------------------------------------------------------------
# Date parsing on the context
# --------------------------------------------------------------------------


def test_context_start_and_end_parse_iso_dates():
    context = _context(start_date="2026-05-01", end_date="2026-05-31")
    assert context.start == date(2026, 5, 1)
    assert context.end == date(2026, 5, 31)


def test_context_parses_full_iso_timestamps():
    context = _context(start_date="2026-05-01T00:00:00Z")
    assert context.start == date(2026, 5, 1)


def test_context_unparseable_date_is_none():
    context = _context(start_date="not a date")
    assert context.start is None


def test_context_option_lookup():
    context = _context(options={"threshold": 0.3})
    assert context.option("threshold") == 0.3
    assert context.option("missing") is None
    assert context.option("missing", "fallback") == "fallback"


# --------------------------------------------------------------------------
# Coverage overlap
# --------------------------------------------------------------------------


def test_overlap_fully_inside_coverage():
    days = coverage_overlap_days(
        date(2026, 5, 1), date(2026, 5, 31), "2017-03-28", None
    )
    assert days == 31


def test_overlap_entirely_before_coverage():
    """Sentinel-2 did not exist in 2010."""
    days = coverage_overlap_days(
        date(2010, 5, 1), date(2010, 5, 31), "2017-03-28", None
    )
    assert days == 0


def test_overlap_straddling_the_start_of_coverage():
    days = coverage_overlap_days(
        date(2010, 2, 1), date(2018, 1, 31), "2017-03-28", None
    )
    # From 2017-03-28 to 2018-01-31 inclusive.
    assert days == 310


def test_overlap_respects_a_closed_dataset():
    """MOD16A2 starts 2021; a 2015 request must not overlap at all."""
    days = coverage_overlap_days(
        date(2015, 1, 1), date(2015, 12, 31), "2021-01-01", None
    )
    assert days == 0


def test_overlap_after_a_closed_dataset_ends():
    days = coverage_overlap_days(
        date(2030, 1, 1), date(2030, 12, 31), "2001-01-01", "2024-01-01"
    )
    assert days == 0


def test_overlap_with_no_dates_is_zero():
    assert coverage_overlap_days(None, date(2026, 5, 1), "2017-03-28", None) == 0
    assert coverage_overlap_days(date(2026, 5, 1), None, "2017-03-28", None) == 0


def test_overlap_with_inverted_range_is_zero():
    days = coverage_overlap_days(
        date(2026, 5, 31), date(2026, 5, 1), "2017-03-28", None
    )
    assert days == 0


# --------------------------------------------------------------------------
# Capability check
# --------------------------------------------------------------------------


def test_can_attempt_returns_true_inside_coverage():
    metric = _EchoMetric()
    can, reason = metric.can_attempt(_context())
    assert can is True
    assert reason is None


def test_can_attempt_reports_out_of_coverage():
    """A pre-launch request must be refused with a specific reason."""
    metric = _EchoMetric()
    context = _context(start_date="2010-01-01", end_date="2010-12-31")
    can, reason = metric.can_attempt(context)
    assert can is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


# --------------------------------------------------------------------------
# Provenance building
# --------------------------------------------------------------------------


def test_build_provenance_includes_metric_and_dataset_limitations():
    metric = _EchoMetric()
    context = _context()
    provenance = metric.build_provenance(
        context=context,
        dataset=metric.primary_dataset(),
        bands=["B4", "B8"],
        formula="(B8 - B4) / (B8 + B4)",
        quality=QualityLevel.GOOD,
        image_count=12,
    )
    assert isinstance(provenance, Provenance)
    assert provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    assert provenance.bands == ["B4", "B8"]
    assert provenance.image_count == 12
    assert provenance.quality_level is QualityLevel.GOOD
    assert provenance.measurement_basis is MeasurementBasis.DIRECT
    assert provenance.date_start == "2026-05-01"
    # The metric's own limitation must survive.
    assert "Not a real metric." in provenance.limitations
    # And the dataset's caveats must be carried through.
    assert provenance.caveats
    assert provenance.citation


def test_build_provenance_accepts_extra_limitations():
    metric = _EchoMetric()
    provenance = metric.build_provenance(
        context=_context(),
        dataset=metric.primary_dataset(),
        bands=["B4"],
        formula="f",
        quality=QualityLevel.MODERATE,
        extra_limitations=("Extra caveat.",),
        extra_caveats=("Extra dataset caveat.",),
    )
    assert "Extra caveat." in provenance.limitations
    assert "Extra dataset caveat." in provenance.caveats


def test_build_provenance_records_fallback_source():
    metric = _EchoMetric()
    provenance = metric.build_provenance(
        context=_context(),
        dataset=metric.primary_dataset(),
        bands=["B4"],
        formula="f",
        quality=QualityLevel.MODERATE,
        fallback_from="SOME/OTHER/DATASET",
    )
    assert provenance.fallback_from == "SOME/OTHER/DATASET"


# --------------------------------------------------------------------------
# Scale resolution
# --------------------------------------------------------------------------


def test_effective_scale_prefers_metric_default():
    metric = _EchoMetric()
    metric.default_scale = 20
    assert metric.effective_scale(_context(scale=10)) == 20


def test_effective_scale_falls_back_to_context():
    metric = _EchoMetric()
    metric.default_scale = None
    assert metric.effective_scale(_context(scale=30)) == 30


def test_effective_scale_falls_back_to_ten():
    metric = _EchoMetric()
    metric.default_scale = None
    assert metric.effective_scale(_context(scale=None)) == 10


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


def test_metadata_shape():
    metadata = _EchoMetric().metadata()
    assert metadata["key"] == "echo"
    assert metadata["domain"] == "vegetation"
    assert metadata["display_name_fa"] == "پژواک"
    assert metadata["measurement_basis"] == "direct"
    assert metadata["dataset_ids"] == ["COPERNICUS/S2_SR_HARMONIZED"]
    assert metadata["is_proxy"] is False


def test_primary_dataset_resolves_from_registry():
    metric = _EchoMetric()
    dataset = metric.primary_dataset()
    assert dataset.id == "COPERNICUS/S2_SR_HARMONIZED"
    assert dataset.name


def test_primary_dataset_id_property():
    assert _EchoMetric().primary_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"


def test_metric_without_datasets_raises_on_lookup():
    class NoDataset(Metric):
        key = "nodata"
        display_name = "No Data"
        display_name_fa = "بدون داده"
        domain = MetricDomain.VEGETATION
        dataset_ids = ()

        def compute(self, context):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="declares no datasets"):
        NoDataset().primary_dataset()


# --------------------------------------------------------------------------
# The temporal contract: OBSERVATION vs STATIC
# --------------------------------------------------------------------------
# A DEM acquired in February 2000 is still the correct elevation model for
# a 2024 request; a soil map is not invalidated by the calendar. These
# tests pin the shared eligibility logic so no dataset can be silently
# rejected for the wrong reason, and so no static product can smuggle an
# inverted or unparseable date range past validation.


class _StaticMetric(Metric):
    key = "static_echo"
    display_name = "Static Echo"
    display_name_fa = "پژواک ایستا"
    domain = MetricDomain.TERRAIN
    unit = "m"
    dataset_ids = ("NASA/NASADEM_HGT/001",)
    measurement_basis = MeasurementBasis.PRODUCT
    description = "Echoes over a static dataset, for testing."
    limitations = ("Not a real metric.",)

    def compute(self, context: MetricContext) -> MetricResult:
        raise NotImplementedError  # pragma: no cover


def test_static_dataset_accepts_a_realistic_historical_request():
    """2024 against a 2000 acquisition is a normal request, not an error."""
    metric = _StaticMetric()
    context = _context(start_date="2024-04-01", end_date="2024-04-30")
    can, reason = metric.can_attempt(context)
    assert can is True
    assert reason is None


def test_static_dataset_accepts_a_future_request():
    """The acquisition date is context, not a validity window."""
    metric = _StaticMetric()
    context = _context(start_date="2026-01-01", end_date="2026-01-31")
    can, reason = metric.can_attempt(context)
    assert can is True
    assert reason is None


def test_static_dataset_is_not_gated_by_acquisition_window():
    """A request that does not overlap the acquisition must still pass."""
    metric = _StaticMetric()
    # 2000-02-11 to 2000-02-22 is the declared acquisition; nothing in
    # 2024 overlaps it, and that must not matter.
    context = _context(start_date="2024-04-01", end_date="2024-04-30")
    can, _reason = metric.can_attempt(context)
    assert can is True


def test_static_dataset_still_rejects_an_inverted_range():
    """Static is not a licence to skip request validation."""
    metric = _StaticMetric()
    context = _context(start_date="2024-04-30", end_date="2024-04-01")
    can, reason = metric.can_attempt(context)
    assert can is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


def test_static_dataset_still_rejects_an_unparseable_start():
    metric = _StaticMetric()
    context = _context(start_date="not a date", end_date="2024-04-30")
    can, reason = metric.can_attempt(context)
    assert can is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


def test_static_dataset_still_rejects_an_unparseable_end():
    metric = _StaticMetric()
    context = _context(start_date="2024-04-01", end_date="")
    can, reason = metric.can_attempt(context)
    assert can is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


def test_observation_dataset_is_still_gated_by_its_window():
    """The fix must not weaken the existing coverage behaviour."""
    metric = _EchoMetric()
    context = _context(start_date="2010-01-01", end_date="2010-12-31")
    can, reason = metric.can_attempt(context)
    assert can is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


def test_observation_dataset_inside_its_window_still_passes():
    metric = _EchoMetric()
    can, reason = metric.can_attempt(_context())
    assert can is True
    assert reason is None


def test_static_provenance_records_product_date_separately_from_request():
    """A 2024 result from a 2000 surface must not read as a 2024 surface."""
    metric = _StaticMetric()
    context = _context(start_date="2024-04-01", end_date="2024-04-30")
    provenance = metric.build_provenance(
        context=context,
        dataset=metric.primary_dataset(),
        bands=["elevation"],
        formula="test",
        quality=QualityLevel.GOOD,
    )
    assert provenance.temporal_kind.value == "static"
    assert provenance.requested_start == "2024-04-01"
    assert provenance.requested_end == "2024-04-30"
    assert provenance.product_date == "2000-02-11"
    assert provenance.product_date not in ("2024-04-01", "2024-04-30")


def test_observation_provenance_does_not_invent_a_product_date():
    """product_date is meaningless for a series; leaving it empty is right."""
    metric = _EchoMetric()
    provenance = metric.build_provenance(
        context=_context(),
        dataset=metric.primary_dataset(),
        bands=["B4"],
        formula="test",
        quality=QualityLevel.GOOD,
    )
    assert provenance.temporal_kind.value == "observation"
    assert provenance.product_date is None
    assert provenance.date_start == "2026-05-01"
