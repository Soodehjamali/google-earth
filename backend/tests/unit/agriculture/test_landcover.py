"""Tests for the land cover engine.

The governing risk in this module is different from every other module in
this engine, and it is worse because the wrong answer *looks* right:

1. **A class code treated as a quantity.** Class 4 is not twice class 2,
   and the difference between class 12 and class 13 is not a distance.
   The mean of a field that is half water (17) and half cropland (12) is
   14.5, which describes neither and collides with a real class,
   Cropland/Natural Vegetation Mosaics. A mean, a median or a percentile
   of ``LC_Type1`` is therefore not an imprecise answer; it is a
   meaningless one dressed as a measurement.

2. **Class 0 injected for the frontend's benefit.** The IGBP legend used
   by ``LC_Type1`` has seventeen classes numbered 1 to 17 and no class 0.
   Water Bodies is 17. Emitting a class 0 to satisfy a consumer that
   expects one would invent water where there is none and hide real water
   in a class the consumer does not render. (The ``LC_Type2`` and
   ``LC_Type3`` legends *do* start at 0; that is a different legend and
   asserting it here would be a false generalisation.)

3. **Merged cropland classes.** Class 12 is Croplands, over 60%
   cultivated. Class 14 is Cropland/Natural Vegetation Mosaics, 40-60%
   cultivated. Adding them is defensible only when stated; silently
   presenting their sum as "cropland" overstates cultivated extent.

4. **A confidence score invented from QC.** The ``QC`` band's ten values
   are unordered post-processing events. ``1 - QC / 9`` is a fabricated
   index with no meaning in the product documentation, and presenting it
   as a confidence percentage would be a lie with a plausible magnitude.

5. **A crop species read out of a generic class.** ``LC_Type1`` offers
   one Croplands class. It cannot say wheat, maize, rice or pistachio,
   and any metric that named one would be inventing it.

6. **A substituted year.** The product is annual and lags. Silently
   answering a 2025 request with the 2023 map would present an old
   landscape as the current one.

The Earth Engine calls are exercised through a strict fake module rather
than skipped, so the real ``compute`` paths run. No network and no
credentials are required.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.agriculture.aggregation import (
    build_class_reducer,
    parse_class_histogram,
)
from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.landcover import (
    ALL_LANDCOVER_METRICS,
    CROP_TYPE_UNAVAILABLE_CODE,
    CROP_TYPE_UNAVAILABLE_REASON,
    CropTypeMetric,
    IGBP_WATER_BODIES,
    IRRIGATION_UNAVAILABLE_CODE,
    IRRIGATION_UNAVAILABLE_REASON,
    IrrigationMetric,
    LANDCOVER_METRICS,
    LANDCOVER_WORKING_SCALE,
    LandCoverClassMetric,
    LandCoverQualityMetric,
    MCD12Q1,
    UNAVAILABLE_LANDCOVER_METRICS,
    _collect_class_histogram,
    resolve_product_year,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.registry.datasets import (
    MCD12Q1_CROPLAND_CLASSES,
    MCD12Q1_CROPLAND_MOSAIC_CLASS,
    MCD12Q1_IGBP_CLASSES,
    MCD12Q1_QC_CLASSES,
    MCD12Q1_QC_PRIMARY_VALUES,
    MCD12Q1_STRICT_CROPLAND_CLASS,
    WORLDCEREAL_BINARY_VALUES,
    WORLDCEREAL_PRODUCTS,
    WORLDCEREAL_SEASONS,
)
from app.services.agriculture.types import (
    ClassHistogram,
    ClassHistogramEntry,
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

EXPECTED_KEYS = {"land_cover_class", "land_cover_quality"}

#: The dataset id WorldCereal lives under, spelled once.
WORLDCEREAL = "ESA/WorldCereal/2021/MODELS/v100"

#: Sentinel that lets a fixture mark a pixel as carrying no class.
NO_DATA = object()

#: A pixel tally above the MODIS validity floor.
PIXEL_TALLY = 5000


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
        "geometry_key": "test-geometry",
    }
    fields.update(overrides)
    return MetricContext(**fields)


# ==========================================================================
# Fake Earth Engine
# ==========================================================================
#
# Deliberately smaller than the soil harness: this module reduces a single
# categorical band, so it needs a histogram reducer and a first() call and
# nothing else. The parts that exist nonetheless enforce the same
# discipline -- a band the fixture does not hold raises rather than
# returning a plausible number.


class _FakeReducer:
    def __init__(self, name: str, payload=None) -> None:
        self.name = name
        self.payload = payload

    def combine(self, other, sharedInputs=False):  # noqa: N803 - mirrors ee
        return self


class _FakeReducerNamespace:
    @staticmethod
    def mean():
        return _FakeReducer("mean")

    @staticmethod
    def frequencyHistogram():  # noqa: N802 - mirrors ee API
        return _FakeReducer("frequencyHistogram")


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value


class _FakeRegionResult:
    def __init__(self, payload) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeImage:
    """One image holding one categorical band.

    ``select`` raises when asked for a band this image does not hold, so
    a metric that reads ``QC`` when it declared ``LC_Type1`` fails loudly
    instead of silently reducing the wrong band.
    """

    def __init__(self, ee_module, band: str, values, histogram=None) -> None:
        self._ee = ee_module
        self._band = band
        self._values = list(values)
        #: Pre-computed counting result, so a test can state what the
        #: reduction should produce without the fake having to derive it.
        self._histogram = histogram
        self._masked = False

    @property
    def band(self) -> str:
        return self._band

    @property
    def masked(self) -> bool:
        return self._masked

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        if bands and bands[0] != self._band:
            raise KeyError(f"fake image holds {self._band!r}, not {bands!r}")
        return self

    def reduceRegion(self, **kwargs):
        reducer = kwargs.get("reducer")
        assert reducer is not None, "reduceRegion called without a reducer"
        assert reducer.name == "frequencyHistogram", (
            "a categorical band must be reduced with a histogram; "
            f"got reducer {reducer.name!r}"
        )
        if self._histogram is None:
            return _FakeRegionResult({})
        # Earth Engine nests a histogram reducer's output under the band
        # name, and serialises the bucket keys as strings.
        return _FakeRegionResult(
            {self._band: {str(k): v for k, v in self._histogram.items()}}
        )


class _FakeCollection:
    def __init__(self, ee_module, dataset_id, bands, histogram=None) -> None:
        self._ee = ee_module
        self._dataset_id = dataset_id
        self._bands = bands
        self._histogram = histogram
        self._selected = None

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        band = bands[0]
        if self._bands is not None and band not in self._bands:
            raise KeyError(
                f"fixture for {self._dataset_id!r} holds "
                f"{sorted(self._bands or [])}, not {band!r}"
            )
        clone = _FakeCollection(
            self._ee, self._dataset_id, self._bands, self._histogram
        )
        clone._selected = band
        return clone

    def size(self):
        if self._bands is None:
            raise KeyError(
                f"test fixture has no data for dataset {self._dataset_id!r}"
            )
        return _FakeNumber(len(self._bands))

    def first(self):
        """The single annual classification.

        A collection with no images yields ``None`` rather than an empty
        image, which is what a metric has to handle if it filters first
        and counts afterwards.
        """
        if self._bands is None or len(self._bands) == 0:
            return None
        band = self._selected or next(iter(self._bands))
        return _FakeImage(
            self._ee, band, [], histogram=self._histogram
        )


class FakeEE:
    """Minimal Earth Engine stand-in for categorical reductions.

    Fixtures are supplied as
    ``FakeEE({dataset_id: {"LC_Type1": PIXEL_TALLY}}, histogram={12: 3000})``
    where the histogram maps class code to pixel count.
    """

    def __init__(self, bands_by_dataset, histogram=None) -> None:
        self._bands_by_dataset = bands_by_dataset
        self._histogram = histogram
        self.Reducer = _FakeReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        # A fixture that omits the band set is treated as an empty
        # collection, so a metric that forgets to filter gets zero images
        # rather than an unbounded one.
        bands = self._bands_by_dataset.get(dataset_id)
        return _FakeCollection(self, dataset_id, bands, self._histogram)


def install_fake_ee(monkeypatch, dataset_id=MCD12Q1, band="LC_Type1",
                    histogram=None, image_count=1):
    """Install a fake ``ee`` whose single dataset holds ``band``."""
    bands = None if image_count is None else {band: [0] * image_count}
    fake = FakeEE({dataset_id: bands} if bands is not None else {},
                  histogram=histogram)

    # The attribute is patched by its dotted path rather than by importing
    # the package, so this suite never depends on Earth Engine being
    # installed or initialised.
    for name in ("ImageCollection", "Reducer"):
        monkeypatch.setattr(f"ee.{name}", getattr(fake, name))
    return fake


# ==========================================================================
# The categorical aggregation helper
# ==========================================================================


def test_a_histogram_is_not_a_mean():
    """Class codes must be counted, never averaged."""

    class _ReducerNamespace:
        @staticmethod
        def mean():
            return _FakeReducer("mean")

        @staticmethod
        def frequencyHistogram():  # noqa: N802 - mirrors ee API
            return _FakeReducer("frequencyHistogram")

    class _Module:
        Reducer = _ReducerNamespace

    reducer = build_class_reducer(_Module)
    assert reducer.name == "frequencyHistogram"
    assert reducer.name != "mean"


def test_a_histogram_with_an_empty_payload_yields_no_entries():
    histogram = parse_class_histogram({}, class_names=MCD12Q1_IGBP_CLASSES)
    assert isinstance(histogram, ClassHistogram)
    assert histogram.entries == []
    assert histogram.dominant_code is None


def test_none_histogram_payload_yields_no_entries():
    histogram = parse_class_histogram(None, class_names=MCD12Q1_IGBP_CLASSES)
    assert histogram.entries == []


def test_string_keys_are_parsed_back_to_integers():
    """Earth Engine serialises histogram keys as strings."""
    histogram = parse_class_histogram(
        {"12": 300, "17": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=400,
    )
    codes = {e.code for e in histogram.entries}
    assert codes == {12, 17}
    assert all(isinstance(e.code, int) for e in histogram.entries)


def test_percentages_sum_to_one_hundred():
    histogram = parse_class_histogram(
        {"12": 500, "14": 250, "17": 250},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=1000,
    )
    assert sum(e.percent for e in histogram.entries) == pytest.approx(100.0)


def test_percent_of_geometry_is_measured_against_the_whole_field():
    """A class can dominate the classified area and still be minor here."""
    histogram = parse_class_histogram(
        {"12": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=1000,
    )
    entry = histogram.entries[0]
    assert entry.percent == pytest.approx(100.0)
    assert entry.percent_of_geometry == pytest.approx(10.0)


def test_entries_are_sorted_by_descending_extent():
    histogram = parse_class_histogram(
        {"12": 100, "17": 900, "14": 500},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=1500,
    )
    assert [e.code for e in histogram.entries] == [17, 14, 12]


def test_the_dominant_class_is_the_largest_one():
    histogram = parse_class_histogram(
        {"12": 100, "17": 900},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=1000,
    )
    assert histogram.dominant_code == IGBP_WATER_BODIES
    assert histogram.dominant_code == 17
    assert histogram.dominant_name == "Water Bodies"


def test_a_zero_pixel_class_is_dropped():
    """An absent class padded into the histogram would look like extent."""
    histogram = parse_class_histogram(
        {"12": 100, "17": 0},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=100,
    )
    assert [e.code for e in histogram.entries] == [12]


def test_a_negative_pixel_count_is_dropped():
    histogram = parse_class_histogram(
        {"12": 100, "17": -5},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=100,
    )
    assert [e.code for e in histogram.entries] == [12]


def test_an_unknown_class_code_is_kept_not_dropped():
    """Dropping it would hide area and break the percentage total."""
    histogram = parse_class_histogram(
        {"12": 100, "99": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=200,
    )
    codes = {e.code for e in histogram.entries}
    assert 99 in codes
    unknown = next(e for e in histogram.entries if e.code == 99)
    assert "Unknown" in unknown.name
    assert sum(e.percent for e in histogram.entries) == pytest.approx(100.0)


def test_a_fractional_class_code_is_rejected_rather_than_rounded():
    """A fractional key means the band was not categorical."""
    histogram = parse_class_histogram(
        {"12.5": 100, "12": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=200,
    )
    assert [e.code for e in histogram.entries] == [12]


def test_a_boolean_key_is_not_read_as_class_one():
    """``bool`` is an ``int`` subclass, so True would become class 1."""
    histogram = parse_class_histogram(
        {True: 100, "1": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=200,
    )
    assert histogram.valid_pixel_count == 100


def test_a_malformed_key_is_dropped_not_coerced():
    histogram = parse_class_histogram(
        {"cropland": 100, "12": 50},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=150,
    )
    assert [e.code for e in histogram.entries] == [12]


def test_a_histogram_nested_under_the_band_name_is_unwrapped():
    """The nested form must not be mistaken for an unlabelled area.

    A nested payload passed through as though it were flat has no
    parseable keys and yields an empty histogram, which is
    indistinguishable from a field with no land cover at all. That is the
    failure this guards against.
    """
    histogram = parse_class_histogram(
        {"LC_Type1": {"12": 3000, "17": 2000}},
        class_names=MCD12Q1_IGBP_CLASSES,
        band="LC_Type1",
    )
    assert {e.code for e in histogram.entries} == {12, 17}


def test_a_nested_histogram_is_unwrapped_without_a_band_name():
    histogram = parse_class_histogram(
        {"LC_Type1": {"12": 3000, "17": 2000}},
        class_names=MCD12Q1_IGBP_CLASSES,
    )
    assert {e.code for e in histogram.entries} == {12, 17}


def test_a_flat_histogram_is_left_alone():
    """A flat histogram's values are counts, never dictionaries."""
    histogram = parse_class_histogram(
        {"12": 3000, "17": 2000},
        class_names=MCD12Q1_IGBP_CLASSES,
        band="LC_Type1",
    )
    assert {e.code for e in histogram.entries} == {12, 17}


def test_a_large_multi_class_histogram_survives_nesting():
    """A wide histogram must not be collapsed to one class by unwrapping."""
    payload = {str(code): 100 * code for code in MCD12Q1_IGBP_CLASSES}
    histogram = parse_class_histogram(
        {"LC_Type1": payload},
        class_names=MCD12Q1_IGBP_CLASSES,
        band="LC_Type1",
    )
    assert len(histogram.entries) == len(MCD12Q1_IGBP_CLASSES)


def test_drop_codes_are_excluded_entirely():
    histogram = parse_class_histogram(
        {"0": 100, "12": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=200,
        drop_codes=(0,),
    )
    assert [e.code for e in histogram.entries] == [12]
    assert histogram.valid_pixel_count == 100


def test_the_helper_never_produces_a_mean_or_a_median():
    """The histogram type carries no continuous statistic at all."""
    histogram = parse_class_histogram(
        {"12": 100, "17": 100},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=200,
    )
    for attribute in ("mean", "median", "stats", "p10", "std_dev"):
        assert not hasattr(histogram, attribute), attribute


# ==========================================================================
# Annual product semantics
# ==========================================================================


def test_a_single_year_request_resolves_to_that_year():
    year, years, reason = resolve_product_year("2023-01-01", "2023-12-31")
    assert year == 2023
    assert years == [2023]
    assert reason is None


def test_a_mid_year_request_resolves_to_the_containing_product_year():
    """A six-month window still describes one annual image."""
    year, years, reason = resolve_product_year("2023-04-01", "2023-09-30")
    assert year == 2023
    assert years == [2023]
    assert reason is None


def test_a_multi_year_request_lists_every_year_and_names_no_single_one():
    """Reporting one year for a multi-year request would narrow the answer."""
    year, years, reason = resolve_product_year("2019-01-01", "2021-12-31")
    assert year is None
    assert years == [2019, 2020, 2021]
    assert reason is None


def test_a_request_before_the_product_is_unavailable_not_clamped():
    year, years, reason = resolve_product_year("1995-01-01", "1998-12-31")
    assert year is None
    assert years == []
    assert reason == "outside_product_coverage"


def test_a_request_after_the_product_is_unavailable_not_clamped():
    year, years, reason = resolve_product_year("2025-01-01", "2025-12-31")
    assert year is None
    assert years == []
    assert reason == "outside_product_coverage"


def test_a_partially_overlapping_request_is_not_silently_truncated():
    """The overlapping years are named; the rest is not invented.

    The request runs into 2026, well past the product's 2024-01-01 end.
    Both 2023 and 2024 genuinely overlap the requested window, so both
    are reported; nothing is extrapolated into 2025 or 2026.
    """
    year, years, reason = resolve_product_year("2023-06-01", "2026-06-01")
    assert years == [2023, 2024]
    assert year is None
    assert reason is None
    assert 2025 not in years
    assert 2026 not in years


def test_reversed_dates_are_rejected():
    year, years, reason = resolve_product_year("2023-12-31", "2023-01-01")
    assert reason == "invalid_dates"


def test_unparseable_dates_are_rejected():
    year, years, reason = resolve_product_year("not-a-date", "2023-01-01")
    assert reason == "invalid_dates"


def test_the_product_year_resolver_reads_the_registry_coverage():
    """The coverage bounds must come from the dataset, not from a guess."""
    dataset = get_dataset(MCD12Q1)
    year, years, reason = resolve_product_year(
        "1990-01-01",
        "1990-12-31",
        available_from=dataset.available_from,
        available_to=dataset.available_to,
    )
    assert reason == "outside_product_coverage"


# ==========================================================================
# Metric collection integrity
# ==========================================================================


def test_all_expected_landcover_metrics_present():
    assert {m.key for m in LANDCOVER_METRICS} == EXPECTED_KEYS


def test_no_duplicate_landcover_metric_keys():
    keys = [m.key for m in ALL_LANDCOVER_METRICS]
    assert len(keys) == len(set(keys))


def test_every_landcover_metric_is_in_the_landcover_domain():
    for metric in ALL_LANDCOVER_METRICS:
        assert metric.domain is MetricDomain.LANDCOVER, metric.key


def test_every_landcover_metric_declares_a_unit():
    for metric in ALL_LANDCOVER_METRICS:
        assert metric.unit and metric.unit != "unknown", metric.key


def test_every_landcover_metric_declares_limitations():
    for metric in ALL_LANDCOVER_METRICS:
        assert metric.limitations, metric.key


def test_landcover_metrics_reduce_at_the_products_own_500_metres():
    """Reducing finer would resample a 500 m map and misreport it."""
    for metric in LANDCOVER_METRICS:
        assert metric.default_scale == LANDCOVER_WORKING_SCALE, metric.key
        assert metric.default_scale == 500, metric.key


def test_landcover_metrics_read_the_annual_modis_product():
    for metric in LANDCOVER_METRICS:
        assert metric.dataset_ids == (MCD12Q1,), metric.key


def test_no_landcover_metric_claims_to_be_direct():
    for metric in ALL_LANDCOVER_METRICS:
        assert metric.measurement_basis is not MeasurementBasis.DIRECT, metric.key


def test_the_class_metric_reads_the_igbp_band():
    assert LandCoverClassMetric().source_bands == ("LC_Type1",)


def test_the_quality_metric_reads_the_qc_band():
    assert LandCoverQualityMetric().source_bands == ("QC",)


def test_the_two_metrics_read_different_bands():
    """A copy-paste that left both on LC_Type1 would be invisible."""
    assert (
        LandCoverClassMetric().source_bands
        != LandCoverQualityMetric().source_bands
    )


def test_every_landcover_metric_is_registrable():
    register_metrics(ALL_LANDCOVER_METRICS)
    assert EXPECTED_KEYS.issubset(set(metric_keys()))


def test_registration_is_idempotent():
    register_metrics(ALL_LANDCOVER_METRICS)
    first = set(metric_keys())
    register_metrics(ALL_LANDCOVER_METRICS)
    assert set(metric_keys()) == first
    assert get_metric("land_cover_class") is get_metric("land_cover_class")


def test_the_unavailable_metrics_are_registered_but_marked_unavailable():
    register_metrics(ALL_LANDCOVER_METRICS)
    for metric in UNAVAILABLE_LANDCOVER_METRICS:
        registered = get_metric(metric.key)
        assert registered is not None, metric.key
        assert registered.metadata()["available"] is False, metric.key


# ==========================================================================
# MetricResult.class_histogram
# ==========================================================================


def _provenance(quality=QualityLevel.GOOD):
    metric = LandCoverClassMetric()
    return metric.build_provenance(
        context=make_context(),
        dataset=metric.primary_dataset(),
        bands=["LC_Type1"],
        formula="test",
        quality=quality,
        image_count=1,
        aggregation_method="test",
    )


def test_a_histogram_result_needs_provenance():
    with pytest.raises(ValueError, match="provenance"):
        MetricResult(
            metric_key="land_cover_class",
            display_name="x",
            display_name_fa="x",
            class_histogram=ClassHistogram(entries=[ClassHistogramEntry(12)]),
        )


def test_a_histogram_under_unavailable_quality_is_refused():
    with pytest.raises(ValueError, match="Contradictory"):
        MetricResult(
            metric_key="land_cover_class",
            display_name="x",
            display_name_fa="x",
            class_histogram=ClassHistogram(entries=[ClassHistogramEntry(12)]),
            provenance=_provenance(QualityLevel.UNAVAILABLE),
        )


def test_a_histogram_and_a_value_cannot_coexist():
    """A categorical product has no numeric value to report."""
    with pytest.raises(ValueError, match="pick one representation"):
        MetricResult(
            metric_key="land_cover_class",
            display_name="x",
            display_name_fa="x",
            value=12.5,
            class_histogram=ClassHistogram(entries=[ClassHistogramEntry(12)]),
            provenance=_provenance(),
        )


def test_a_histogram_only_result_is_usable():
    result = MetricResult(
        metric_key="land_cover_class",
        display_name="x",
        display_name_fa="x",
        class_histogram=ClassHistogram(
            entries=[ClassHistogramEntry(12, "Croplands", 100)]
        ),
        provenance=_provenance(),
    )
    assert result.is_usable is True


def test_an_empty_histogram_is_not_a_usable_result():
    result = MetricResult(
        metric_key="land_cover_class",
        display_name="x",
        display_name_fa="x",
        class_histogram=ClassHistogram(entries=[]),
        provenance=_provenance(),
    )
    assert result.is_usable is False


def test_continuous_results_are_unchanged_by_the_new_field():
    """Every existing metric must serialise exactly as it did before."""
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="NDVI",
        value=0.42,
        provenance=_provenance(),
    )
    assert result.class_histogram is None
    assert result.to_dict()["value"] == pytest.approx(0.42)
    assert result.to_dict()["class_histogram"] is None
    assert result.is_usable is True


def test_the_histogram_reaches_the_serialised_form():
    result = MetricResult(
        metric_key="land_cover_class",
        display_name="x",
        display_name_fa="x",
        class_histogram=ClassHistogram(
            entries=[
                ClassHistogramEntry(
                    code=17,
                    name="Water Bodies",
                    pixel_count=300,
                    percent=75.0,
                    percent_of_geometry=60.0,
                )
            ],
            dominant_code=17,
            dominant_name="Water Bodies",
            valid_pixel_count=400,
            total_pixel_count=500,
        ),
        provenance=_provenance(),
    )
    payload = result.to_dict()["class_histogram"]
    assert payload["dominant_code"] == 17
    assert payload["entries"][0]["code"] == 17
    assert payload["entries"][0]["percent"] == pytest.approx(75.0)


# ==========================================================================
# land_cover_class: the IGBP legend
# ==========================================================================


def test_the_igbp_legend_has_seventeen_classes():
    assert len(MCD12Q1_IGBP_CLASSES) == 17


def test_the_igbp_legend_has_no_class_zero():
    """There is no IGBP class 0. Water Bodies is class 17."""
    assert 0 not in MCD12Q1_IGBP_CLASSES
    assert min(MCD12Q1_IGBP_CLASSES) == 1
    assert max(MCD12Q1_IGBP_CLASSES) == 17


def test_water_bodies_is_class_seventeen():
    assert MCD12Q1_IGBP_CLASSES[IGBP_WATER_BODIES] == "Water Bodies"


def test_croplands_is_class_twelve():
    assert MCD12Q1_IGBP_CLASSES[12] == "Croplands"


def test_the_cropland_mosaic_is_class_fourteen():
    assert MCD12Q1_IGBP_CLASSES[14] == "Cropland/Natural Vegetation Mosaics"


def test_the_two_cropland_classes_are_distinct_constants():
    assert MCD12Q1_STRICT_CROPLAND_CLASS == 12
    assert MCD12Q1_CROPLAND_MOSAIC_CLASS == 14
    assert MCD12Q1_CROPLAND_CLASSES == (12, 14)
    assert len(set(MCD12Q1_CROPLAND_CLASSES)) == 2


def test_the_registry_declares_the_igbp_band_range():
    spec = get_dataset(MCD12Q1).band("LC_Type1")
    assert spec.valid_range == (1.0, 17.0)


def test_the_registry_caveat_records_the_absence_of_class_zero():
    joined = " ".join(get_dataset(MCD12Q1).caveats)
    assert "no class 0" in joined
    assert "17" in joined


# ==========================================================================
# land_cover_class: computation
# ==========================================================================


def test_the_class_metric_returns_a_histogram(monkeypatch):
    install_fake_ee(
        monkeypatch,
        histogram={12: 3000, 17: 2000},
        image_count=1,
    )
    result = LandCoverClassMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.class_histogram is not None
    assert result.value is None
    assert result.stats is None
    assert result.unit == "class"


def test_the_class_histogram_reports_the_igbp_codes_as_published(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 3000, 17: 2000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    codes = {e.code for e in result.class_histogram.entries}
    assert codes == {12, 17}
    assert 0 not in codes


def test_water_is_reported_as_class_seventeen(monkeypatch):
    install_fake_ee(monkeypatch, histogram={17: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    entry = result.class_histogram.entries[0]
    assert entry.code == 17
    assert entry.name == "Water Bodies"


def test_no_class_zero_is_injected_for_a_water_only_area(monkeypatch):
    """The frontend expects a class 0; the product does not have one."""
    install_fake_ee(monkeypatch, histogram={17: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert all(e.code != 0 for e in result.class_histogram.entries)


def test_the_dominant_class_is_identified(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 1000, 17: 4000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.class_histogram.dominant_code == 17
    assert result.class_histogram.dominant_name == "Water Bodies"


def test_the_class_percentages_sum_to_one_hundred(monkeypatch):
    install_fake_ee(
        monkeypatch, histogram={12: 1000, 14: 1000, 17: 2000}, image_count=1
    )
    result = LandCoverClassMetric().compute(make_context())

    total = sum(e.percent for e in result.class_histogram.entries)
    assert total == pytest.approx(100.0)


def test_the_two_cropland_classes_are_never_merged(monkeypatch):
    """Class 12 and class 14 must each appear under their own code."""
    install_fake_ee(monkeypatch, histogram={12: 1000, 14: 1000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    codes = {e.code for e in result.class_histogram.entries}
    assert codes == {12, 14}
    merged = [e for e in result.class_histogram.entries if e.code not in (12, 14)]
    assert merged == []


def test_no_combined_cropland_fraction_is_reported(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 1000, 14: 1000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    joined = (result.message or "") + " ".join(result.warnings)
    assert "cropland_fraction" not in joined.lower()


def test_a_multi_class_field_reports_every_class(monkeypatch):
    install_fake_ee(
        monkeypatch,
        histogram={10: 100, 12: 200, 14: 300, 17: 400},
        image_count=1,
    )
    result = LandCoverClassMetric().compute(make_context())

    assert {e.code for e in result.class_histogram.entries} == {10, 12, 14, 17}


def test_the_valid_area_is_the_sum_of_the_class_extents(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 300, 17: 700}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.class_histogram.valid_pixel_count == 1000


def test_the_provenance_names_the_dataset_and_band(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.provenance.source_dataset_id == MCD12Q1
    assert result.provenance.bands == ["LC_Type1"]


def test_the_provenance_describes_the_aggregation(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    method = result.provenance.aggregation_method.lower()
    assert "histogram" in method


def test_the_provenance_states_the_product_year(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    joined = " ".join(result.provenance.limitations).lower()
    assert "2023" in joined


def test_the_provenance_forbids_a_mean_of_class_codes(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    joined = " ".join(result.provenance.limitations).lower()
    assert "mean" in joined
    assert "label" in joined or "not a class" in joined


def test_no_mean_is_produced_for_a_categorical_band(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 2500, 17: 2500}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.value is None
    assert result.stats is None


def test_an_empty_reduction_is_insufficient_not_zero(monkeypatch):
    install_fake_ee(monkeypatch, histogram={}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.status != STATUS_OK
    assert result.value is None
    assert result.class_histogram is None
    assert "insufficient" in (result.reason or "")


def test_a_year_outside_the_product_is_unavailable(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    context = make_context(start_date="1995-01-01", end_date="1995-12-31")
    result = LandCoverClassMetric().compute(context)

    assert result.status == STATUS_UNAVAILABLE
    assert result.reason == "outside_product_coverage"


def test_a_future_year_is_unavailable_and_no_year_is_substituted(monkeypatch):
    """Answering a 2026 request with the 2023 map would be a false claim."""
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    context = make_context(start_date="2026-01-01", end_date="2026-12-31")
    result = LandCoverClassMetric().compute(context)

    assert result.status == STATUS_UNAVAILABLE
    assert result.reason == "outside_product_coverage"
    assert result.class_histogram is None
    assert result.value is None


def test_the_unavailable_message_states_the_coverage_not_a_substitute(
    monkeypatch,
):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    context = make_context(start_date="1990-01-01", end_date="1990-12-31")
    result = LandCoverClassMetric().compute(context)

    assert "2001-01-01" in result.message
    assert "no other year" in result.message.lower()


def test_the_class_metric_is_never_unavailable_for_a_covered_year(monkeypatch):
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())
    assert result.status == STATUS_OK


def test_no_class_name_claims_a_crop_species(monkeypatch):
    """Class names come from the product's own legend."""
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    for entry in result.class_histogram.entries:
        assert entry.name == "Croplands", entry.name


def test_the_metric_never_asserts_a_crop_species(monkeypatch):
    """Wheat, maize, rice and pistachio must only ever appear in a denial.

    The metric *does* name these species, but only to say it cannot
    identify them. Asserting a bare absence of the words would forbid the
    clearest possible statement of the limitation, so the guard is that
    each mention sits in a sentence denying the capability.
    """
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    metric = LandCoverClassMetric()
    result = metric.compute(make_context())

    text = " ".join(metric.limitations).lower()
    text += " " + metric.description.lower()
    text += " " + " ".join(result.provenance.limitations).lower()
    for species in ("wheat", "maize", "rice", "pistachio"):
        if species not in text:
            continue
        assert "cannot" in text or "not a crop type" in text, species

    # And the reported class names must never be a species.
    for entry in result.class_histogram.entries:
        assert entry.name not in ("Wheat", "Maize", "Rice", "Pistachio")


def test_the_metric_states_it_is_not_a_crop_type():
    joined = " ".join(LandCoverClassMetric().limitations).lower()
    assert "not a crop type" in joined


def test_the_metric_states_the_500_metre_pixel_limit():
    joined = " ".join(LandCoverClassMetric().limitations).lower()
    assert "500 m" in joined
    assert "hectare" in joined


def test_the_metric_states_the_annual_limitation():
    joined = " ".join(LandCoverClassMetric().limitations).lower()
    assert "annual" in joined


def test_the_metric_states_the_publication_lag():
    joined = " ".join(LandCoverClassMetric().limitations).lower()
    assert "lag" in joined or "not yet published" in joined


# ==========================================================================
# land_cover_quality: the QC band is not a confidence score
# ==========================================================================


def test_the_qc_legend_has_ten_values():
    assert len(MCD12Q1_QC_CLASSES) == 10
    assert sorted(MCD12Q1_QC_CLASSES) == list(range(10))


def test_the_quality_metric_returns_a_histogram_of_raw_flags(monkeypatch):
    install_fake_ee(
        monkeypatch, band="QC", histogram={0: 4000, 8: 1000}, image_count=1
    )
    result = LandCoverQualityMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.class_histogram is not None
    assert {e.code for e in result.class_histogram.entries} == {0, 8}


def test_the_quality_metric_reports_no_numeric_score(monkeypatch):
    """QC must not be converted into a 0-100 confidence value."""
    install_fake_ee(
        monkeypatch, band="QC", histogram={0: 4000, 9: 1000}, image_count=1
    )
    result = LandCoverQualityMetric().compute(make_context())

    assert result.value is None
    assert result.stats is None


def test_the_quality_metric_does_not_invert_the_codes(monkeypatch):
    """``1 - QC / 9`` would be a fabricated index; it must not appear."""
    install_fake_ee(monkeypatch, band="QC", histogram={0: 5000}, image_count=1)
    metric = LandCoverQualityMetric()
    result = metric.compute(make_context())

    text = (result.message or "") + " ".join(result.warnings)
    text += " " + metric.description + " " + " ".join(metric.limitations)
    assert "1 - qc" not in text.lower()
    assert "qc/9" not in text.lower()
    assert "qc / 9" not in text.lower()


def test_the_quality_metric_says_qc_is_not_a_confidence_score():
    joined = " ".join(LandCoverQualityMetric().limitations).lower()
    assert "not a confidence score" in joined


def test_the_quality_metric_says_higher_is_not_worse():
    joined = " ".join(LandCoverQualityMetric().limitations).lower()
    assert "not worse" in joined or "not a monotonic" in joined


def test_the_quality_metric_admits_the_product_publishes_no_confidence():
    joined = " ".join(LandCoverQualityMetric().limitations).lower()
    assert "no confidence percentage" in joined


def test_the_quality_metric_reports_the_flag_distribution(monkeypatch):
    install_fake_ee(
        monkeypatch,
        band="QC",
        histogram={0: 3000, 2: 1000, 8: 1000},
        image_count=1,
    )
    result = LandCoverQualityMetric().compute(make_context())

    codes = sorted(e.code for e in result.class_histogram.entries)
    assert codes == [0, 2, 8]


def test_the_quality_warning_counts_only_the_primary_flags(monkeypatch):
    """Arithmetic on extents is legitimate; arithmetic on codes is not."""
    install_fake_ee(
        monkeypatch,
        band="QC",
        histogram={0: 3000, 2: 1000, 8: 1000},
        image_count=1,
    )
    result = LandCoverQualityMetric().compute(make_context())

    assert result.warnings
    joined = " ".join(result.warnings)
    assert "80.0%" in joined
    assert sorted(MCD12Q1_QC_PRIMARY_VALUES) == [0, 2]


def test_the_quality_provenance_forbids_a_derived_score(monkeypatch):
    install_fake_ee(monkeypatch, band="QC", histogram={0: 5000}, image_count=1)
    result = LandCoverQualityMetric().compute(make_context())

    joined = " ".join(result.provenance.limitations).lower()
    assert "no aggregate quality score" in joined


def test_the_quality_metric_rejects_an_out_of_range_year(monkeypatch):
    install_fake_ee(monkeypatch, band="QC", histogram={0: 5000}, image_count=1)
    context = make_context(start_date="2030-01-01", end_date="2030-12-31")
    result = LandCoverQualityMetric().compute(context)

    assert result.status == STATUS_UNAVAILABLE
    assert result.reason == "outside_product_coverage"


# ==========================================================================
# Scientific guards
# ==========================================================================


def test_the_class_band_is_reduced_with_a_histogram_not_a_mean(monkeypatch):
    """The fake rejects any reducer other than a histogram."""
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())

    assert result.class_histogram is not None
    assert result.value is None


def test_no_class_codes_are_averaged_anywhere_in_the_module():
    """The *categorical* section of the module must never average.

    The Dynamic World probability section (Phase I) legitimately uses the
    continuous reducer, because per-class probabilities are quantities,
    not labels. The guard is therefore scoped to the code above that
    section, where every band is a class code or an unordered flag.
    """
    import inspect

    import app.services.agriculture.landcover as landcover

    source = inspect.getsource(landcover)
    categorical_source = source.split("DYNAMIC_WORLD = ")[0].lower()
    for forbidden in (
        "reducer.mean()",
        "reducer.median()",
        "build_reducer(",
        "parse_reduction_result(",
    ):
        assert forbidden not in categorical_source, forbidden


def test_the_parse_helper_produces_no_continuous_statistic():
    histogram = parse_class_histogram(
        {"12": 100, "17": 300},
        class_names=MCD12Q1_IGBP_CLASSES,
        total_pixel_count=400,
    )
    assert not hasattr(histogram, "mean")
    assert isinstance(histogram, ClassHistogram)


def test_only_the_first_annual_image_is_used(monkeypatch):
    """A mean over several years would interpolate between labels."""
    install_fake_ee(monkeypatch, histogram={12: 5000}, image_count=1)
    result = LandCoverClassMetric().compute(make_context())
    assert result.class_histogram.valid_pixel_count == 5000


def test_a_metric_that_reads_the_wrong_band_fails_loudly(monkeypatch):
    """Reading LC_Type1 when QC was declared must raise, not return data."""
    bands = {MCD12Q1: {"QC": [0]}}
    fake = FakeEE(bands, histogram={0: 5000})

    for name in ("ImageCollection", "Reducer"):
        monkeypatch.setattr(f"ee.{name}", getattr(fake, name))

    with pytest.raises(KeyError):
        LandCoverClassMetric().compute(make_context())


# ==========================================================================
# Deliberately unavailable metrics
# ==========================================================================


def test_the_crop_type_metric_is_registered_but_unavailable():
    metric = CropTypeMetric()
    result = metric.compute(make_context())

    assert result.status == STATUS_UNAVAILABLE
    assert metric.metadata()["available"] is False
    assert metric.metadata()["unavailable_code"] == CROP_TYPE_UNAVAILABLE_CODE


def test_the_crop_type_metric_carries_no_value():
    result = CropTypeMetric().compute(make_context())
    assert result.value is None
    assert result.class_histogram is None


def test_the_crop_type_reason_names_the_missing_input():
    assert "crop species" in CROP_TYPE_UNAVAILABLE_REASON.lower()
    assert "MCD12Q1" in CROP_TYPE_UNAVAILABLE_REASON


def test_the_crop_type_reason_names_species_only_to_deny_them():
    """It may list the species it cannot identify; it must deny them."""
    lowered = CROP_TYPE_UNAVAILABLE_REASON.lower()
    assert "does not identify crop species" in lowered
    for species in ("wheat", "maize", "rice", "pistachio"):
        if species not in lowered:
            continue
        assert "cannot report" in lowered or "not a crop-type" in lowered


def test_the_crop_type_reason_explains_why_worldcereal_is_not_used():
    lowered = CROP_TYPE_UNAVAILABLE_REASON.lower()
    assert "worldcereal" in lowered
    assert "binary" in lowered
    assert "2021" in lowered


def test_the_irrigation_metric_is_registered_but_unavailable():
    metric = IrrigationMetric()
    result = metric.compute(make_context())

    assert result.status == STATUS_UNAVAILABLE
    assert metric.metadata()["available"] is False
    assert metric.metadata()["unavailable_code"] == IRRIGATION_UNAVAILABLE_CODE


def test_the_irrigation_metric_carries_no_value():
    result = IrrigationMetric().compute(make_context())
    assert result.value is None
    assert result.class_histogram is None


def test_the_irrigation_reason_states_the_products_limitations():
    lowered = IRRIGATION_UNAVAILABLE_REASON.lower()
    assert "binary" in lowered
    assert "2021" in lowered
    assert "agro-ecological" in lowered or "aez" in lowered
    assert "incomplete" in lowered


def test_the_irrigation_reason_refuses_a_proxy_from_land_cover():
    lowered = IRRIGATION_UNAVAILABLE_REASON.lower()
    assert "mcd12q1" in lowered
    assert "no irrigation proxy" in lowered


def test_no_unavailable_metric_can_produce_a_result_by_configuration():
    """The unavailability is structural, not a flag that could flip."""
    for metric in UNAVAILABLE_LANDCOVER_METRICS:
        result = metric.compute(make_context())
        assert result.value is None, metric.key
        assert result.class_histogram is None, metric.key
        assert result.status == STATUS_UNAVAILABLE, metric.key


def test_the_unavailable_metrics_declare_an_inference_basis():
    for metric in UNAVAILABLE_LANDCOVER_METRICS:
        assert metric.measurement_basis is MeasurementBasis.INFERENCE, metric.key


# ==========================================================================
# Registry: MCD12Q1
# ==========================================================================


def test_the_modis_landcover_dataset_is_registered():
    dataset = get_dataset(MCD12Q1)
    assert dataset is not None
    assert dataset.is_verified is True


def test_the_modis_landcover_dataset_declares_its_real_coverage():
    dataset = get_dataset(MCD12Q1)
    assert dataset.available_from == "2001-01-01"
    assert dataset.available_to == "2024-01-01"


def test_the_modis_landcover_dataset_declares_500_metres():
    dataset = get_dataset(MCD12Q1)
    assert "500" in dataset.spatial_resolution


def test_the_modis_landcover_dataset_declares_annual_cadence():
    dataset = get_dataset(MCD12Q1)
    assert "year" in dataset.temporal_resolution.lower()


def test_the_igbp_band_is_declared_as_a_class_not_a_quantity():
    spec = get_dataset(MCD12Q1).band("LC_Type1")
    assert spec.unit == "class"
    assert spec.scale_factor == pytest.approx(1.0)
    assert spec.offset == pytest.approx(0.0)


def test_the_qc_band_is_declared_with_its_real_range():
    spec = get_dataset(MCD12Q1).band("QC")
    assert spec.valid_range == (0.0, 9.0)
    assert spec.unit == "class"


def test_no_invented_nodata_is_declared_for_the_class_band():
    """The class band is not padded with a sentinel the catalogue lacks."""
    spec = get_dataset(MCD12Q1).band("LC_Type1")
    assert spec.nodata_values == ()


def test_the_catalogue_bands_are_all_present():
    """The registry must reflect the published band set, not a subset."""
    spec = get_dataset(MCD12Q1)
    for band in (
        "LC_Type1",
        "LC_Type2",
        "LC_Type3",
        "LC_Type4",
        "LC_Type5",
        "LC_Prop1",
        "LC_Prop2",
        "LC_Prop3",
        "LC_Prop1_Assessment",
        "LC_Prop2_Assessment",
        "LC_Prop3_Assessment",
        "LW",
        "QC",
    ):
        assert spec.has_band(band), band


def test_the_registry_records_the_annual_image_semantics():
    joined = " ".join(get_dataset(MCD12Q1).caveats).lower()
    assert "annual" in joined or "yearly" in joined


def test_the_registry_records_the_publication_lag():
    joined = " ".join(get_dataset(MCD12Q1).caveats).lower()
    assert "lag" in joined or "2024-01-01" in joined


def test_the_registry_does_not_claim_qc_is_a_confidence_score():
    joined = " ".join(get_dataset(MCD12Q1).caveats).lower()
    assert "qc is not a confidence score" in joined


# ==========================================================================
# Registry: WorldCereal corrections
# ==========================================================================


def test_the_worldcereal_classification_band_is_binary():
    spec = get_dataset(WORLDCEREAL).band("classification")
    assert spec.valid_range == (0.0, 100.0)
    assert WORLDCEREAL_BINARY_VALUES == (0, 100)


def test_the_worldcereal_band_declares_no_invented_nodata():
    """The registry previously declared a 255 fill the catalogue lacks."""
    for band in ("classification", "confidence"):
        spec = get_dataset(WORLDCEREAL).band(band)
        assert spec.nodata_values == (), band
        assert 255 not in spec.nodata_values, band


def test_the_worldcereal_products_are_enumerated():
    assert set(WORLDCEREAL_PRODUCTS) == {
        "temporarycrops",
        "maize",
        "wintercereals",
        "springcereals",
        "irrigation",
    }


def test_the_worldcereal_seasons_are_enumerated():
    assert "tc-annual" in WORLDCEREAL_SEASONS
    assert "tc-maize-main" in WORLDCEREAL_SEASONS
    assert len(set(WORLDCEREAL_SEASONS)) == len(WORLDCEREAL_SEASONS)


def test_the_worldcereal_caveats_require_product_and_season_filters():
    joined = " ".join(get_dataset(WORLDCEREAL).caveats).lower()
    assert "product" in joined
    assert "season" in joined


def test_the_worldcereal_caveats_require_an_aez_filter():
    joined = " ".join(get_dataset(WORLDCEREAL).caveats).lower()
    assert "aez" in joined or "agro-ecological" in joined


def test_the_worldcereal_coverage_is_recorded_as_reference_year_limited():
    dataset = get_dataset(WORLDCEREAL)
    assert dataset.available_from == "2020-01-01"
    assert dataset.available_to == "2021-12-31"


def test_no_landcover_metric_reads_worldcereal():
    """It is corrected in the registry, but no metric is built from it."""
    for metric in ALL_LANDCOVER_METRICS:
        assert WORLDCEREAL not in metric.dataset_ids, metric.key


# ==========================================================================
# Dynamic World is deliberately excluded from this phase
# ==========================================================================


def test_dynamic_world_remains_registered():
    """Excluding the metric must not delete the dataset registration."""
    dataset = get_dataset("GOOGLE/DYNAMICWORLD/V1")
    assert dataset is not None
    assert dataset.is_verified is True


def test_no_landcover_metric_uses_dynamic_world():
    for metric in ALL_LANDCOVER_METRICS:
        assert "GOOGLE/DYNAMICWORLD/V1" not in metric.dataset_ids, metric.key


def test_dynamic_world_keeps_its_own_ten_metre_character():
    """Its resolution differs from the 500 m product this phase uses."""
    dataset = get_dataset("GOOGLE/DYNAMICWORLD/V1")
    assert "10" in dataset.spatial_resolution


# ==========================================================================
# Analysis service wiring
# ==========================================================================
#
# The service layer owns no science; it builds the context, runs the
# metrics through the shared executor, and serialises their results into
# the payload the API and the frontend read. These tests pin the contract
# at that boundary, because a correct metric can still be misreported by
# the layer that formats it.


def _service_fake_ee(monkeypatch, histograms, image_count=1):
    """Install a fake ``ee`` for the analysis service path.

    ``histograms`` maps band name to ``{class_code: pixel_count}``. The
    reduction nests the result under the band name, as Earth Engine does.
    """

    class _Region:
        def __init__(self, payload):
            self._payload = payload

        def getInfo(self):
            return self._payload

    class _Red:
        def __init__(self, name):
            self.name = name

        def combine(self, other, sharedInputs=False):  # noqa: N803
            return self

    class _Image:
        def __init__(self, band):
            self._band = band

        def select(self, bands):
            return self

        def reduceRegion(self, **kwargs):
            reducer = kwargs["reducer"]
            assert reducer.name == "frequencyHistogram", reducer.name
            counts = histograms.get(self._band, {})
            return _Region(
                {self._band: {str(k): v for k, v in counts.items()}}
            )

    class _Collection:
        def __init__(self, selected=None):
            self._selected = selected

        def filterDate(self, *_args):
            return self

        def filterBounds(self, *_args):
            return self

        def select(self, bands):
            bands = [bands] if isinstance(bands, str) else bands
            return _Collection(bands[0])

        def size(self):
            return _Region(image_count)

        def first(self):
            # The first annual classification, for whichever band was
            # selected. ``None`` when the collection is empty, which is
            # what a metric filtering outside coverage would see.
            if image_count <= 0:
                return None
            return _Image(self._selected or "LC_Type1")

    monkeypatch.setattr(
        "ee.Reducer",
        type(
            "R",
            (),
            {
                "frequencyHistogram": staticmethod(
                    lambda: _Red("frequencyHistogram")
                )
            },
        ),
    )
    monkeypatch.setattr("ee.ImageCollection", lambda _dataset_id: _Collection())


@pytest.fixture(autouse=True)
def _clear_service_cache():
    """Isolate the service-level analysis cache between tests.

    ``AnalysisService.create_analysis`` caches completed analyses by
    request parameters (Phase S.4). These service tests deliberately reuse
    one request shape with different fake Earth Engine histograms, so
    without clearing, the first test's cached result would be served to
    every later test and the per-test fakes would never run.
    """
    from app.services.cache_service import cache_service

    cache_service.clear()
    yield
    cache_service.clear()


def _run_service_analysis(monkeypatch, histograms, start="2023-01-01",
                          end="2023-12-31", image_count=1, area_sq_m=250000.0):
    """Run a land cover analysis through the service with a fake ``ee``."""
    import asyncio

    import app.services.analysis_service as service_module
    from app.services.analysis_service import analysis_service

    _service_fake_ee(monkeypatch, histograms, image_count=image_count)
    monkeypatch.setattr(
        service_module, "create_ee_geometry", lambda geometry: {"type": "polygon"}
    )
    monkeypatch.setattr(
        service_module, "_geometry_area_sq_m", lambda geometry: area_sq_m
    )

    return asyncio.run(
        analysis_service.create_analysis(
            db=None,
            geometry={
                "type": "Polygon",
                "coordinates": [[[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5], [0, 0]]],
            },
            start_date=start,
            end_date=end,
            analysis_type="landcover",
            temporal_resolution="yearly",
        )
    )


def test_the_service_produces_a_landcover_block(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 3000, 17: 2000}, "QC": {0: 4000, 8: 1000}},
    )
    assert result["status"] == "completed"
    assert "landcover" in result["result_data"]


def test_the_service_reports_class_codes_as_the_product_publishes_them(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 3000, 17: 2000}, "QC": {0: 4000, 8: 1000}},
    )
    classes = result["result_data"]["landcover"]["classes"]

    assert set(classes) == {"12", "17"}
    assert classes["12"] == pytest.approx(60.0)
    assert classes["17"] == pytest.approx(40.0)


def test_the_service_never_emits_a_class_zero(monkeypatch):
    """The frontend's legend keys water at '0'; IGBP has no such class."""
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {17: 5000}, "QC": {0: 5000}},
    )
    classes = result["result_data"]["landcover"]["classes"]

    assert "0" not in classes
    assert classes["17"] == pytest.approx(100.0)


def test_the_service_reports_water_as_class_seventeen(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {17: 5000}, "QC": {0: 5000}},
    )
    landcover = result["result_data"]["landcover"]

    assert landcover["dominant_class"] == "17"
    assert landcover["dominant_class_name"] == "Water Bodies"


def test_the_service_flags_the_frontend_class_zero_mismatch(monkeypatch):
    """The mismatch must be reported, not silently worked around."""
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {17: 5000}, "QC": {0: 5000}},
    )
    warnings = " ".join(result["result_data"]["landcover"]["warnings"])

    assert "class 17" in warnings
    assert "class 0" in warnings


def test_the_service_reports_the_dominant_class(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 4000, 17: 1000}, "QC": {0: 5000}},
    )
    landcover = result["result_data"]["landcover"]

    assert landcover["dominant_class"] == "12"
    assert landcover["dominant_class_name"] == "Croplands"


def test_the_service_keeps_the_two_cropland_classes_apart(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 2000, 14: 3000}, "QC": {0: 5000}},
    )
    classes = result["result_data"]["landcover"]["classes"]

    assert set(classes) == {"12", "14"}
    assert classes["12"] == pytest.approx(40.0)
    assert classes["14"] == pytest.approx(60.0)


def test_the_service_reports_area_at_the_products_own_resolution(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 2000}, "QC": {0: 2000}},
    )
    landcover = result["result_data"]["landcover"]

    # 2000 pixels of 500 m by 500 m is 2000 * 250000 square metres.
    assert landcover["total_area_sq_meters"] == pytest.approx(2000 * 250000.0)
    assert landcover["spatial_resolution_m"] == 500


def test_the_service_reports_the_dataset_and_scheme(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
    )
    landcover = result["result_data"]["landcover"]

    assert landcover["dataset"] == MCD12Q1
    assert "IGBP" in landcover["class_scheme"]
    assert landcover["temporal_resolution"] == "annual"


def test_the_service_reports_qc_flags_without_a_score(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 4000, 8: 1000}},
    )
    quality = result["result_data"]["landcover"]["quality"]

    assert quality["flags"] == {"0": 4000, "8": 1000}
    assert "not a confidence score" in quality["note"]
    assert "score" not in quality


def test_the_service_reports_unavailable_outside_coverage(monkeypatch):
    """2025 is past the product's end; no year may be substituted.

    The executor's capability check rejects the range before ``compute``
    runs, so the reason is the generic out-of-coverage code rather than the
    metric's own more specific one. Both mean the same thing, and both are
    distinct from a substituted year, which is what actually matters.
    """
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
        start="2025-01-01",
        end="2025-12-31",
    )
    landcover = result["result_data"]["landcover"]

    assert landcover["status"] != STATUS_OK
    assert "coverage" in landcover["reason"]
    assert landcover["classes"] == {}
    assert landcover["dominant_class"] is None


def test_the_service_reports_no_area_when_there_is_no_result(monkeypatch):
    """An unavailable analysis must not report a zero area as a measurement."""
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
        start="2025-01-01",
        end="2025-12-31",
    )
    landcover = result["result_data"]["landcover"]

    assert "total_area_sq_meters" not in landcover
    assert "valid_pixel_count" not in landcover


def test_the_service_does_not_report_zeros_for_missing_data(monkeypatch):
    """Missing data returns insufficient_data, never a zeroed distribution."""
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {}, "QC": {}},
    )
    landcover = result["result_data"]["landcover"]

    assert landcover["status"] != STATUS_OK
    assert landcover["classes"] == {}


def test_the_service_carries_the_metric_provenance(monkeypatch):
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
    )
    provenance = result["result_data"]["landcover"]["provenance"]

    assert provenance["source_dataset_id"] == MCD12Q1
    assert provenance["bands"] == ["LC_Type1"]


def test_the_service_reaches_the_metrics_without_a_startup_hook(monkeypatch):
    """A metric lookup against an empty registry would find nothing.

    Nothing in the application calls ``register_all_metrics`` on the way
    in, so the service has to guarantee the registry itself. Without that,
    every key misses and the analysis degrades to "unknown metric".
    """
    from app.services.agriculture.catalog import clear_registry, metric_keys

    clear_registry()
    assert metric_keys() == []

    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
    )
    landcover = result["result_data"]["landcover"]

    assert "unknown_metrics" not in landcover
    assert landcover["status"] == STATUS_OK

    clear_registry()


def test_the_service_pins_the_landcover_metric_keys():
    from app.services.analysis_service import LANDCOVER_METRIC_KEYS

    assert set(LANDCOVER_METRIC_KEYS) == EXPECTED_KEYS


def test_the_service_reports_a_point_geometry_without_a_fabricated_area(
    monkeypatch,
):
    """A point has no area, so no extent figure may be invented for it."""
    result = _run_service_analysis(
        monkeypatch,
        {"LC_Type1": {12: 5000}, "QC": {0: 5000}},
        area_sq_m=None,
    )
    landcover = result["result_data"]["landcover"]

    # The classification is still reported; the geometry-relative
    # percentage simply has no denominator.
    assert landcover["classes"] == {"12": pytest.approx(100.0)}


# ==========================================================================
# API endpoint
# ==========================================================================
#
# The handler reads the stored payload back. These tests use a stub session
# so no database is needed, which keeps the unit suite free of I/O.


class _StubAnalysis:
    def __init__(self, result_data, analysis_type="landcover"):
        self.result_data = result_data
        self.analysis_type = analysis_type
        self.id = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _StubResult:
    def __init__(self, analysis):
        self._analysis = analysis

    def scalar_one_or_none(self):
        return self._analysis


class _StubSession:
    def __init__(self, analysis):
        self._analysis = analysis

    async def execute(self, _statement):
        return _StubResult(self._analysis)


def _call_endpoint(analysis):
    import asyncio

    from app.api.v1.landcover import get_landcover_analysis

    return asyncio.run(
        get_landcover_analysis(
            analysis_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            db=_StubSession(analysis),
        )
    )


def test_the_endpoint_returns_the_stored_landcover_block():
    stored = {
        "status": "ok",
        "classes": {"12": 60.0, "17": 40.0},
        "dominant_class": "12",
        "total_area_sq_meters": 1250000000.0,
    }
    payload = _call_endpoint(_StubAnalysis({"landcover": stored}))

    assert payload == stored


def test_the_endpoint_reports_water_at_class_seventeen():
    stored = {
        "status": "ok",
        "classes": {"17": 100.0},
        "dominant_class": "17",
    }
    payload = _call_endpoint(_StubAnalysis({"landcover": stored}))

    assert payload["dominant_class"] == "17"
    assert "0" not in payload["classes"]


def test_the_endpoint_explains_a_missing_landcover_block():
    """A different analysis type must not look like bare ground."""
    payload = _call_endpoint(
        _StubAnalysis({"statistics": {}}, analysis_type="vegetation")
    )

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "no_landcover_result_stored"
    assert payload["classes"] == {}
    assert payload["analysis_type"] == "vegetation"


def test_the_endpoint_states_the_scheme_and_the_water_class():
    payload = _call_endpoint(_StubAnalysis(None))

    assert payload["dataset"] == MCD12Q1
    assert "IGBP" in payload["class_scheme"]
    assert payload["water_bodies_class"] == IGBP_WATER_BODIES


def test_the_endpoint_raises_not_found_for_an_unknown_analysis():
    import asyncio

    from fastapi import HTTPException

    from app.api.v1.landcover import get_landcover_analysis

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            get_landcover_analysis(
                analysis_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                db=_StubSession(None),
            )
        )

    assert excinfo.value.status_code == 404


def test_the_endpoint_does_not_import_the_metric_layer():
    """The handler must orchestrate nothing; the service owns that.

    A second computation path inside the API layer is exactly the
    duplication this phase is required to avoid.
    """
    import inspect

    import app.api.v1.landcover as endpoint

    source = inspect.getsource(endpoint)
    for forbidden in (
        "MetricContext",
        "execute_metrics",
        "LandCoverClassMetric",
        "import ee",
    ):
        assert forbidden not in source, forbidden


# ==========================================================================
# Dynamic World: per-class probabilities (Phase I)
# ==========================================================================
#
# The risks here differ from the MCD12Q1 ones: the product is
# *probabilistic*, so the temptation to misuse is not averaging class
# codes but treating a probability as an area or a classification. The
# tests pin all three denials.

from app.services.agriculture.landcover import (  # noqa: E402 - section marker
    DYNAMIC_WORLD,
    DYNAMIC_WORLD_PROBABILITY_BANDS,
    DYNAMIC_WORLD_WORKING_SCALE,
    DYNAMIC_WORLD_METRICS,
    LandCoverProbabilityMetric,
    reduce_dynamic_world_probabilities,
)


class _FakeProbNumber:
    def __init__(self, value):
        self._value = value

    def getInfo(self):
        return self._value


class _FakeProbRegion:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeProbReducer:
    def __init__(self, name):
        self.name = name

    def combine(self, other, sharedInputs=False):  # noqa: N803
        return self


class _FakeProbReducerNamespace:
    @staticmethod
    def count():
        return _FakeProbReducer("count")

    @staticmethod
    def mean():
        return _FakeProbReducer("mean")

    @staticmethod
    def median():
        return _FakeProbReducer("median")

    @staticmethod
    def stdDev():
        return _FakeProbReducer("stdDev")

    @staticmethod
    def min():
        return _FakeProbReducer("min")

    @staticmethod
    def max():
        return _FakeProbReducer("max")

    @staticmethod
    def percentile(values):
        return _FakeProbReducer(f"p{values}")

    @staticmethod
    def frequencyHistogram():  # noqa: N802 - mirrors ee API
        return _FakeProbReducer("frequencyHistogram")


class _FakeProbCollection:
    def __init__(self, bands_by_dataset, band_payloads, image_count):
        self._bands_by_dataset = bands_by_dataset
        self._band_payloads = band_payloads
        self._image_count = image_count

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in DYNAMIC_WORLD_PROBABILITY_BANDS:
                raise KeyError(
                    f"fake Dynamic World carries only the nine probability "
                    f"bands, not {band!r} — the argmax 'label' band is "
                    "deliberately absent"
                )
        return self

    def mean(self):
        return _FakeProbImage(self._band_payloads)

    def size(self):
        return _FakeProbNumber(self._image_count)


class _FakeProbImage:
    def __init__(self, band_payloads):
        self._band_payloads = band_payloads

    def reduceRegion(self, **kwargs):
        reducer = kwargs.get("reducer")
        assert reducer is not None
        assert getattr(reducer, "name", "") == "count", reducer.name
        return _FakeProbRegion(self._band_payloads)


class _FakeProbEE:
    """Fake EE for Dynamic World: probability bands only, no label band."""

    def __init__(self, band_payloads, image_count=8):
        self._band_payloads = band_payloads
        self._image_count = image_count
        self.Reducer = _FakeProbReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        assert dataset_id == DYNAMIC_WORLD, dataset_id
        # Every probability band is held, keyed for the size() contract.
        bands = {band: [0] for band in DYNAMIC_WORLD_PROBABILITY_BANDS}
        return _FakeProbCollection(
            {DYNAMIC_WORLD: bands}, self._band_payloads, self._image_count
        )


def _prob_payload(means_by_band, total_pixels=5000):
    payload = {}
    for band, mean in means_by_band.items():
        payload[f"{band}_count"] = float(total_pixels)
        payload[f"{band}_mean"] = mean
        payload[f"{band}_median"] = mean
        payload[f"{band}_min"] = min(mean, 0.0)
        payload[f"{band}_max"] = max(mean, 0.0)
        payload[f"{band}_stdDev"] = 0.1
        for p in (10, 25, 75, 90):
            payload[f"{band}_p{p}"] = mean
    return payload


def install_dw_fake(monkeypatch, means_by_band, image_count=8):
    fake = _FakeProbEE(_prob_payload(means_by_band), image_count)
    monkeypatch.setattr("ee.ImageCollection", fake.ImageCollection)
    monkeypatch.setattr("ee.Reducer", fake.Reducer)
    return fake


def dw_context(**overrides):
    fields = {
        "geometry": {},
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": 5000 * 10 * 10},
    }
    fields.update(overrides)
    return MetricContext(**fields)


def test_the_probability_metric_is_in_its_own_collection():
    """It must not silently join the pinned MCD12Q1 analysis contract."""
    from app.services.agriculture.landcover import LANDCOVER_METRICS

    assert LandCoverProbabilityMetric() not in LANDCOVER_METRICS
    assert {m.key for m in DYNAMIC_WORLD_METRICS} == {
        "land_cover_probability"
    }


def test_the_probability_metric_reads_only_probability_bands():
    metric = LandCoverProbabilityMetric()
    assert set(metric.source_bands) == set(DYNAMIC_WORLD_PROBABILITY_BANDS)
    assert "label" not in metric.source_bands


def test_the_probability_metric_never_reads_the_argmax_band(monkeypatch):
    """Selecting 'label' raises in the fake; the metric must not try."""
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())
    assert result.status == STATUS_OK


def test_the_probability_metric_reports_the_top_mean(monkeypatch):
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())

    assert result.value == pytest.approx(0.6)
    assert result.unit == "probability"


def test_the_candidate_dominant_class_is_named_as_context(monkeypatch):
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())

    joined = " ".join(result.warnings)
    assert "crops" in joined
    assert "candidate dominant" in joined.lower()
    assert "not a classification" in joined.lower()


def test_the_probability_metric_states_the_probabilities(monkeypatch):
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())

    joined = " ".join(result.warnings)
    assert "0.60" in joined or "0.6" in joined
    assert "0.20" in joined or "0.2" in joined


def test_a_low_top_probability_is_flagged(monkeypatch):
    install_dw_fake(
        monkeypatch,
        {"crops": 0.3, "trees": 0.25, "grass": 0.2, "built": 0.1,
         "water": 0.05, "bare": 0.04, "shrub_and_scrub": 0.03,
         "flooded_vegetation": 0.02, "snow_and_ice": 0.01},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())

    joined = " ".join(result.warnings)
    assert "reporting floor" in joined


def test_no_area_is_derived_from_a_probability(monkeypatch):
    """A posterior is not a cover fraction; no area may be claimed."""
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    metric = LandCoverProbabilityMetric()
    result = metric.compute(dw_context())

    # The result carries the top band's stats, whose valid_area is the
    # classified area — but no crop-area claim may appear in the prose.
    limitations = " ".join(metric.limitations).lower()
    assert "no area is derived" in limitations
    assert "not sub-pixel cover fractions" in limitations


def test_the_probability_metric_states_the_recall_limitation():
    joined = " ".join(LandCoverProbabilityMetric().limitations).lower()
    assert "60 percent producer" in joined or "producer's accuracy" in joined
    assert "89 percent user" in joined or "user's accuracy" in joined


def test_the_probability_metric_states_the_species_denial():
    joined = " ".join(LandCoverProbabilityMetric().limitations).lower()
    assert "cannot identify a crop" in joined


def test_no_predictions_yield_insufficient(monkeypatch):
    install_dw_fake(monkeypatch, {}, image_count=0)
    result = LandCoverProbabilityMetric().compute(dw_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_an_all_masked_reduction_yields_insufficient(monkeypatch):
    payload = _prob_payload({})  # no band carries a mean
    fake = _FakeProbEE(payload, image_count=3)
    monkeypatch.setattr("ee.ImageCollection", fake.ImageCollection)
    monkeypatch.setattr("ee.Reducer", fake.Reducer)

    result = LandCoverProbabilityMetric().compute(dw_context())
    assert result.status == STATUS_INSUFFICIENT_DATA


def test_the_probability_provenance_names_the_rule(monkeypatch):
    install_dw_fake(
        monkeypatch,
        {"crops": 0.6, "trees": 0.2, "grass": 0.1, "built": 0.05,
         "water": 0.02, "bare": 0.01, "shrub_and_scrub": 0.01,
         "flooded_vegetation": 0.005, "snow_and_ice": 0.005},
    )
    result = LandCoverProbabilityMetric().compute(dw_context())

    assert result.provenance is not None
    formula = result.provenance.formula.lower()
    assert "argmax label band is not read" in formula
    assert result.provenance.source_dataset_id == DYNAMIC_WORLD


def test_the_probability_metric_runs_at_ten_metres():
    metric = LandCoverProbabilityMetric()
    assert metric.default_scale == DYNAMIC_WORLD_WORKING_SCALE == 10


def test_the_probability_metric_declares_the_nine_bands():
    dataset = get_dataset(DYNAMIC_WORLD)
    for band in DYNAMIC_WORLD_PROBABILITY_BANDS:
        assert dataset.has_band(band), band
    assert dataset.has_band("label")  # registered, even though unread


def test_the_probability_metrics_registration_is_shared():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    assert "land_cover_probability" in metric_keys()
    assert get_metric("land_cover_probability") is not None
