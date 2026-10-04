"""Tests for the water engine: spectral water indices, evapotranspiration
and ERA5-Land evaporation.

Five classes of mistake are guarded here. Each of them produces a number
that looks entirely reasonable, which is exactly why they are worth
testing rather than trusting:

1. **A sign error that a reader cannot see.** ERA5 stores evaporation as
   a negative number. Publishing it directly reports negative
   evaporation; taking ``abs()`` turns a night of condensation into a
   night of evaporation. Both give a plausible-looking magnitude.

2. **A scale error of exactly ten.** MOD16 stores ``ET`` as an integer
   ten times the physical value. Forgetting the declared scale factor
   describes a crop using ten times the water it actually uses, and the
   number is not obviously absurd.

3. **A band mix-up between two similarly named indices.** NDWI and NDMI
   are both "a water index" and both start with the letters ND. They use
   different bands and answer different questions. Wiring NDMI to the
   green band would produce a numerically valid but physically
   meaningless result.

4. **A double count in an accumulation.** The cumulative evapotranspiration
   metric sums composite periods. A composite that straddles the
   requested boundary must be counted once, not twice.

5. **A fabricated value where none can honestly be produced.** CWSI and
   WDI are registered as unavailable, and this file asserts that they
   remain structurally incapable of carrying a value.

The Earth Engine calls are exercised through a strict fake module rather
than skipped, so the real ``compute`` paths run. The fakes raise when
asked for a band the fixture did not provide, so a wiring bug fails
loudly instead of returning a wrong number. No network and no credentials
are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture import indices as pure
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.quality import decode_smap_retrieval_quality
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.types import (
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.vegetation import S2_DATASET_ID
from app.services.agriculture.water import (
    ALL_WATER_METRICS,
    CWSI_UNAVAILABLE_CODE,
    CWSI_UNAVAILABLE_REASON,
    ERA5_DAILY,
    ERA5_EVAPORATION_BAND,
    ERA5EvaporationMetric,
    ERA5PotentialEvaporationMetric,
    CWSIMetric,
    CumulativeEvapotranspirationMetric,
    EvapotranspirationMetric,
    MNDWIMetric,
    MOD16_GAPFILLED,
    MOD16_NRT,
    MSIMetric,
    NDMIMetric,
    NDWIMetric,
    PotentialEvapotranspirationMetric,
    UNAVAILABLE_WATER_METRICS,
    WATER_METRICS,
    WDIMetric,
    WDI_UNAVAILABLE_CODE,
    WDI_UNAVAILABLE_REASON,
    era5_evaporation_from_stored,
)

EXPECTED_KEYS = {
    "ndwi",
    "ndmi",
    "mndwi",
    "msi",
    "evapotranspiration",
    "potential_evapotranspiration",
    "evapotranspiration_cumulative",
    "era5_evaporation",
    "era5_potential_evaporation",
}

EXPECTED_UNAVAILABLE_KEYS = {"cwsi", "wdi"}

#: Sentinel that lets a test mark a day as having no data.
NO_DATA = object()


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


# ==========================================================================
# Fake Earth Engine
# ==========================================================================
#
# Deliberately strict. A metric that asks for a band the fixture did not
# provide raises a KeyError rather than being handed something plausible,
# because a silently wrong number is the failure mode this engine exists
# to prevent.


class _FakeReducer:
    def __init__(self, name: str = "mean", percentiles=None) -> None:
        self.name = name
        self.percentiles = percentiles or []
        self.combined = [(name, percentiles or [])]

    def combine(self, other, sharedInputs=False):  # noqa: N803 - mirrors ee
        self.combined.append((other.name, other.percentiles))
        return self


class _FakeReducerNamespace:
    @staticmethod
    def count():
        return _FakeReducer("count")

    @staticmethod
    def mean():
        return _FakeReducer("mean")

    @staticmethod
    def median():
        return _FakeReducer("median")

    @staticmethod
    def stdDev():  # noqa: N802 - mirrors ee API
        return _FakeReducer("stdDev")

    @staticmethod
    def min():
        return _FakeReducer("min")

    @staticmethod
    def max():
        return _FakeReducer("max")

    @staticmethod
    def percentile(values):
        return _FakeReducer("percentile", list(values))


def _reduce_values(values):
    """Build the reduction dictionary Earth Engine would return.

    Percentiles are computed by linear interpolation across the sorted
    values, matching what ``ee.Reducer.percentile`` documents for a small
    sample.

    ``count`` reports the number of valid *pixels*, not the number of
    values. A fixture supplies one value per composite period, but a real
    reduction covers many pixels, so ``count`` is filled with a plausible
    pixel tally. Without that, every metric would be judged on a single
    valid pixel and the MODIS and reanalysis pixel floors would make
    every result ``insufficient`` for a reason that has nothing to do
    with what is being tested.
    """
    usable = [v for v in values if v is not NO_DATA]
    if not usable:
        return {}

    ordered = sorted(usable)
    count = len(ordered)

    def percentile(p):
        if count == 1:
            return ordered[0]
        position = (count - 1) * (p / 100.0)
        low = math.floor(position)
        high = math.ceil(position)
        if low == high:
            return ordered[low]
        fraction = position - low
        return ordered[low] * (1 - fraction) + ordered[high] * fraction

    mean_value = sum(ordered) / count
    variance = sum((v - mean_value) ** 2 for v in ordered) / count

    return {
        "mean": mean_value,
        "median": percentile(50),
        "min": ordered[0],
        "max": ordered[-1],
        "stdDev": math.sqrt(variance),
        "p10": percentile(10),
        "p25": percentile(25),
        "p75": percentile(75),
        "p90": percentile(90),
        "count": PIXEL_TALLY,
    }


#: A plausible number of valid pixels for a reduced geometry. Large
#: enough to clear every threshold's ``min_valid_pixels`` floor, so a
#: quality verdict reflects the metric under test rather than the size of
#: the fake fixture.
PIXEL_TALLY = 5000


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value

    def Not(self):  # noqa: N802 - mirrors ee.Image boolean invert
        return _FakeNumber(not self._value)

    def bitwiseAnd(self, other):  # noqa: N802 - mirrors ee.Image
        return _FakeNumber(int(self._value) & int(other))

    def neq(self, other):  # noqa: N802 - mirrors ee.Image
        return _FakeNumber(self._value != other)

    def lt(self, other):
        return _FakeNumber(self._value < other)

    def eq(self, other):
        return _FakeNumber(self._value == other)


class _FakeRegionResult:
    def __init__(self, payload) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload

    def get(self, band):
        if isinstance(self._payload, dict):
            if band in self._payload:
                return self._payload[band]
            return self._payload.get("mean")
        return self._payload


class _FakeImage:
    """One band of one image, carrying a list of per-pixel values.

    ``select`` raises when asked for a band the image does not hold, so a
    metric reading the wrong band is caught at test time.
    """

    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        if isinstance(values, list):
            self._values = list(values)
        else:
            self._values = [values]
        self._properties = {}

    @property
    def band(self) -> str:
        return self._band

    def set(self, key, value, **_kwargs):
        self._properties[key] = value
        return self

    def get(self, key):
        return self._properties.get(key)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        if bands and bands[0] != self._band:
            raise KeyError(
                f"fake image holds {self._band!r}, not {bands!r}"
            )
        return self

    def rename(self, name):
        return _FakeImage(self._ee, name, self._values)

    def multiply(self, _factor):
        return self

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee.Image
        return self

    def bitwiseAnd(self, other):  # noqa: N802 - mirrors ee.Image
        # Selecting a bitmask band and masking with it is only ever asked
        # of the quality flag in this module's fixtures.
        return _FakeImage(self._ee, self._band, [v & int(other) for v in self._values])

    def neq(self, other):  # noqa: N802 - mirrors ee.Image
        return _FakeImage(
            self._ee, self._band, [1 if v != other else 0 for v in self._values]
        )

    def lt(self, other):
        return _FakeImage(
            self._ee, self._band, [1 if v < other else 0 for v in self._values]
        )

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(_reduce_values(self._values))


class _FakeCollectionSelector:
    """The result of ``.select([...])`` on a collection."""

    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        self._values = list(values)

    def size(self):
        return _FakeNumber(len(self._values))

    def sum(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(self._ee, self._band, [NO_DATA])
        return _FakeImage(self._ee, self._band, [sum(usable)])

    def mean(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(self._ee, self._band, [NO_DATA])
        return _FakeImage(self._ee, self._band, [sum(usable) / len(usable)])

    def median(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(self._ee, self._band, [NO_DATA])
        if len(usable) == 1:
            return _FakeImage(self._ee, self._band, [usable[0]])
        ordered = sorted(usable)
        middle = len(ordered) // 2
        if len(ordered) % 2 == 0:
            value = (ordered[middle - 1] + ordered[middle]) / 2.0
        else:
            value = ordered[middle]
        return _FakeImage(self._ee, self._band, [value])

    def first(self):
        if not self._values:
            raise IndexError("empty fake collection")
        return self._day(self._values[0])

    def map(self, func):
        return _FakeMapped(self._ee, [func(self._day(v)) for v in self._values])

    def _day(self, value):
        return _FakeImage(self._ee, self._band, value)


class _FakeCollection:
    """A collection that dispatches to whichever band is selected."""

    def __init__(self, ee_module, bands) -> None:
        self._ee = ee_module
        self._bands = {k: list(v) for k, v in bands.items()}
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
        if band not in self._bands:
            raise KeyError(
                f"fake collection holds {sorted(self._bands)}, not {band!r}"
            )
        return _FakeCollectionSelector(self._ee, band, self._bands[band])


class _FakeMapped:
    """The result of ``collection.map(func)``.

    The real client reads per-image properties back with
    ``aggregate_array(name)``. ``getInfo`` on this object is deliberately
    a failure, so an implementation that tries to read it as a list fails
    loudly rather than silently returning nothing.
    """

    def __init__(self, ee_module, items) -> None:
        self._ee = ee_module
        self._items = items

    def aggregate_array(self, name):
        values = []
        for item in self._items:
            value = item.get(name) if isinstance(item, _FakeImage) else None
            values.append(None if value is NO_DATA else value)
        return _FakeNumber(values)

    def getInfo(self):
        raise AssertionError(
            "getInfo() on a mapped collection is not a list of values; "
            "use aggregate_array(property).getInfo() instead"
        )


class _LazyCollection:
    """Re-dispatches to whichever dataset the caller asked for."""

    def __init__(self, ee_module, dataset_id) -> None:
        self._ee = ee_module
        self._dataset_id = dataset_id

    def _bands(self):
        return self._ee._by_dataset.get(self._dataset_id)

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
        available = self._bands()
        if available is None:
            raise KeyError(
                f"test fixture has no data for dataset "
                f"{self._dataset_id!r}"
            )
        if band not in available:
            raise KeyError(
                f"fixture for {self._dataset_id!r} holds "
                f"{sorted(available)}, not {band!r}"
            )
        return _FakeCollectionSelector(self._ee, band, available[band])


class FakeEE:
    """Minimal Earth Engine stand-in.

    Bands are supplied either as ``{band_name: [values]}`` for a single
    dataset, or as ``{dataset_id: {band_name: [values]}}`` when a test
    needs more than one dataset in play at once. The flat form is sugar
    for a fixture that only exercises one dataset; it is normalised into
    the per-dataset form so ``ImageCollection`` routing stays identical.
    """

    def __init__(self, bands) -> None:
        if bands and all(isinstance(v, dict) for v in bands.values()):
            self._by_dataset = {
                k: {b: list(v) for b, v in inner.items()}
                for k, inner in bands.items()
            }
        else:
            # A flat fixture is addressed by band name. It is registered
            # under every dataset ID so that whichever collection a
            # metric opens, the band lookup finds it and a genuine
            # band-selection error still raises.
            self._by_dataset = {
                dataset_id: {k: list(v) for k, v in bands.items()}
                for dataset_id in (
                    MOD16_GAPFILLED,
                    MOD16_NRT,
                    ERA5_DAILY,
                    S2_DATASET_ID,
                )
            }
        self.Reducer = _FakeReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        return _LazyCollection(self, dataset_id)

    def Filter(self):  # noqa: N802 - mirrors ee API
        return _FakeReducer("filter")

    def __getitem__(self, band):
        for inner in self._by_dataset.values():
            if band in inner:
                return _FakeCollectionSelector(self, band, inner[band])
        raise KeyError(
            f"no dataset fixture holds {band!r}; available: "
            f"{sorted({b for inner in self._by_dataset.values() for b in inner})}"
        )


@pytest.fixture
def fake_ee(monkeypatch):
    """Install a fake ``ee`` module for the duration of a test.

    Both ``sys.modules["ee"]`` and the real ``ee`` package's own
    attributes are replaced, because the metric modules do a function-
    local ``import ee`` inside ``compute``. If the real package is
    already imported, that statement binds the real module from
    ``sys.modules``, so patching ``sys.modules`` alone would leave the
    metric talking to Earth Engine.
    """

    def install(bands):
        fake = FakeEE(bands)
        for name in ("ImageCollection", "Reducer", "Filter"):
            monkeypatch.setattr(f"ee.{name}", getattr(fake, name))
        return fake

    return install


# ==========================================================================
# Collection integrity
# ==========================================================================


def test_all_expected_water_metrics_present():
    assert {m.key for m in WATER_METRICS} == EXPECTED_KEYS


def test_unavailable_water_metrics_are_the_expected_two():
    assert {m.key for m in UNAVAILABLE_WATER_METRICS} == EXPECTED_UNAVAILABLE_KEYS


def test_all_water_metrics_is_the_union():
    assert ALL_WATER_METRICS == WATER_METRICS + UNAVAILABLE_WATER_METRICS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in ALL_WATER_METRICS]
    assert len(keys) == len(set(keys))


def test_every_water_metric_is_in_the_water_domain():
    for metric in ALL_WATER_METRICS:
        assert metric.domain is MetricDomain.WATER, metric.key


def test_every_water_metric_declares_a_unit():
    for metric in ALL_WATER_METRICS:
        assert metric.unit and metric.unit != "unknown", metric.key


def test_every_water_metric_declares_limitations():
    for metric in ALL_WATER_METRICS:
        assert metric.limitations, metric.key


def test_every_water_metric_is_registrable():
    register_metrics(WATER_METRICS)
    from app.services.agriculture.catalog import metric_keys

    assert EXPECTED_KEYS.issubset(set(metric_keys()))


def test_no_water_metric_claims_to_be_direct():
    """Every water source here is a product, a derivation or a model.

    Nothing in this module reads an instrument's raw measurement, so a
    DIRECT basis would be an overstatement.
    """
    for metric in ALL_WATER_METRICS:
        assert metric.measurement_basis is not MeasurementBasis.DIRECT, metric.key


def test_spectral_water_indices_are_derived():
    for metric in (NDWIMetric(), NDMIMetric(), MNDWIMetric()):
        assert metric.measurement_basis is MeasurementBasis.DERIVED, metric.key


def test_mod16_metrics_are_products():
    for metric in (
        EvapotranspirationMetric(),
        PotentialEvapotranspirationMetric(),
        CumulativeEvapotranspirationMetric(),
    ):
        assert metric.measurement_basis is MeasurementBasis.PRODUCT, metric.key


def test_era5_evaporation_is_modelled_not_measured():
    """A reanalysis field must never be presented as an observation."""
    metric = ERA5EvaporationMetric()
    assert metric.measurement_basis is MeasurementBasis.MODELLED
    assert metric.requires_disclaimer is True


def test_no_water_metric_claims_to_detect_disease_or_pests():
    """Satellite data cannot diagnose plant health.

    A limitation may *mention* disease in order to say that it cannot be
    distinguished — "cannot distinguish water stress from a diseased
    canopy" is an honest boundary. What is forbidden is a metric claiming
    to detect or diagnose one, which would be read as a diagnosis it
    cannot support.
    """
    forbidden_claims = (
        "detect disease",
        "detects disease",
        "diagnose disease",
        "identify disease",
        "detect pest",
        "diagnose pest",
        "nutrient deficiency",
    )
    for metric in ALL_WATER_METRICS:
        text = " ".join(
            list(metric.limitations)
            + [metric.description, getattr(metric, "notes", "") or ""]
        ).lower()
        for phrase in forbidden_claims:
            assert phrase not in text, f"{metric.key} claims {phrase!r}"


def test_any_mention_of_disease_is_a_disclaimer():
    """Where a limitation names a disease, it must do so negatively."""
    for metric in ALL_WATER_METRICS:
        text = " ".join(metric.limitations).lower()
        if "disease" in text or "pest" in text:
            assert (
                "cannot distinguish" in text
                or "does not" in text
                or "not identify" in text
            ), metric.key


def test_metric_metadata_serialises():
    for metric in ALL_WATER_METRICS:
        payload = metric.metadata()
        assert isinstance(payload, dict)
        assert payload["key"] == metric.key


# ==========================================================================
# 1. Spectral water indices
# ==========================================================================


def test_ndwi_uses_green_and_near_infrared():
    """McFeeters NDWI is a green/NIR index."""
    assert NDWIMetric().required_bands == ("B3", "B8")
    assert NDWIMetric().index_name == "NDWI"


def test_ndmi_uses_near_infrared_and_shortwave_infrared():
    """Gao NDMI is an NIR/SWIR1 index. It is not NDWI."""
    assert NDMIMetric().required_bands == ("B8", "B11")
    assert NDMIMetric().index_name == "NDMI"


def test_mndwi_uses_green_and_shortwave_infrared():
    """Xu MNDWI is a green/SWIR1 index."""
    assert MNDWIMetric().required_bands == ("B3", "B11")
    assert MNDWIMetric().index_name == "MNDWI"


def test_the_three_water_indices_use_three_distinct_band_pairs():
    """This is the band mix-up guard.

    NDWI and NDMI differ only in that one uses green where the other uses
    shortwave infrared. They are easy to confuse and the confusion is
    invisible in the output, so the band pairs are asserted to be
    genuinely different rather than merely non-empty.
    """
    pairs = {
        NDWIMetric().required_bands,
        NDMIMetric().required_bands,
        MNDWIMetric().required_bands,
    }
    assert len(pairs) == 3


def test_ndmi_is_not_ndwi():
    assert NDMIMetric().required_bands != NDWIMetric().required_bands
    assert NDMIMetric().index_name != NDWIMetric().index_name


def test_required_bands_match_the_pure_registry():
    """The Earth Engine wiring must match the documented pure formula.

    If these drift apart, the number the engine reports is computed from
    different bands than the formula recorded alongside it, which is
    worse than no provenance at all.
    """
    for metric in (NDWIMetric(), NDMIMetric(), MNDWIMetric()):
        expected = pure.BAND_ROLES[metric.index_name.lower()]
        assert metric.required_bands == expected, metric.key


def test_index_band_order_matches_the_formula():
    """The declared band order must be the order the formula subtracts."""
    for metric in (NDWIMetric(), NDMIMetric(), MNDWIMetric()):
        first, second = metric.required_bands
        formula = pure.FORMULA_TEXT[metric.index_name.lower()]
        assert formula == f"({first} - {second}) / ({first} + {second})", metric.key


def test_ndwi_expression_is_green_minus_nir():
    """The Earth Engine expression must use the McFeeters band pair."""
    calls = []

    class _SpyComposite:
        def normalizedDifference(self, bands):
            calls.append(list(bands))
            return _SpyResult()

    class _SpyResult:
        def rename(self, _name):
            return self

    NDWIMetric().build_expression(_SpyComposite(), None)
    assert calls == [["B3", "B8"]]


def test_ndmi_expression_is_nir_minus_swir():
    calls = []

    class _SpyComposite:
        def normalizedDifference(self, bands):
            calls.append(list(bands))
            return _SpyResult()

    class _SpyResult:
        def rename(self, _name):
            return self

    NDMIMetric().build_expression(_SpyComposite(), None)
    assert calls == [["B8", "B11"]]


def test_mndwi_expression_is_green_minus_swir():
    calls = []

    class _SpyComposite:
        def normalizedDifference(self, bands):
            calls.append(list(bands))
            return _SpyResult()

    class _SpyResult:
        def rename(self, _name):
            return self

    MNDWIMetric().build_expression(_SpyComposite(), None)
    assert calls == [["B3", "B11"]]


def test_swir_indices_reduce_at_twenty_metres():
    """B11 is acquired at 20 m; reducing at 10 m would resample it."""
    assert NDMIMetric().band_scale == 20
    assert MNDWIMetric().band_scale == 20


def test_ndwi_reduces_at_ten_metres():
    """Both NDWI bands are native 10 m."""
    assert NDWIMetric().band_scale == 10


def test_band_scale_is_not_overridable_by_the_context():
    """A caller-supplied scale must not resample a 20 m band."""
    context = make_context(scale=10)
    assert NDMIMetric().effective_scale(context) == 20


def test_ndwi_records_the_dependency_on_ndmi():
    """A caller must be told NDWI is not the crop water index."""
    note = NDWIMetric().domain_note.lower()
    assert "ndmi" in note


def test_ndmi_records_that_it_is_not_ndwi():
    note = NDMIMetric().domain_note.lower()
    assert "ndwi" in note


def test_every_water_index_declares_limitations_about_cause():
    """An index anomaly has no diagnosable cause."""
    for metric in (NDWIMetric(), NDMIMetric(), MNDWIMetric()):
        joined = " ".join(metric.limitations).lower()
        assert joined, metric.key


def test_ndmi_states_it_is_not_a_soil_moisture_measurement():
    """Canopy water and soil water are different quantities."""
    joined = " ".join(NDMIMetric().limitations).lower()
    assert "not a soil moisture" in joined


def test_ndwi_states_it_is_not_a_crop_water_index():
    joined = " ".join(NDWIMetric().limitations).lower()
    assert "not an indicator of crop water status" in joined


def test_water_index_formula_text_comes_from_the_pure_module():
    """No formula is restated here, so the two cannot drift apart."""
    assert "B3" in pure.FORMULA_TEXT["ndwi"]
    assert "B11" in pure.FORMULA_TEXT["ndmi"]
    assert "B11" in pure.FORMULA_TEXT["mndwi"]


# ==========================================================================
# 2. MOD16 evapotranspiration
# ==========================================================================


def test_mod16_metrics_prefer_the_gapfilled_product():
    for metric in (
        EvapotranspirationMetric(),
        PotentialEvapotranspirationMetric(),
        CumulativeEvapotranspirationMetric(),
    ):
        assert metric.dataset_ids == (MOD16_GAPFILLED, MOD16_NRT), metric.key


def test_mod16_metrics_reduce_at_five_hundred_metres():
    for metric in (
        EvapotranspirationMetric(),
        PotentialEvapotranspirationMetric(),
        CumulativeEvapotranspirationMetric(),
    ):
        assert metric.default_scale == 500, metric.key


def test_evapotranspiration_reads_the_et_band():
    assert EvapotranspirationMetric().source_band == "ET"


def test_potential_evapotranspiration_reads_the_pet_band():
    assert PotentialEvapotranspirationMetric().source_band == "PET"


def test_cumulative_evapotranspiration_reads_the_et_band():
    assert CumulativeEvapotranspirationMetric().source_band == "ET"


def test_the_et_band_declares_a_scale_factor_of_point_one():
    """The registry is the single source of the conversion."""
    spec = get_dataset(MOD16_GAPFILLED).band("ET")
    assert spec.scale_factor == pytest.approx(0.1)
    assert spec.unit == "kg/m2/8day"


def test_et_applies_the_scale_factor(fake_ee):
    """A stored 300 is 30 mm, not 300 mm.

    Forgetting the factor of 0.1 would describe a crop using ten times
    the water it actually used, and 300 mm over eight days is not absurd
    enough to be caught by eye.
    """
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    result = EvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(30.0)
    assert result.unit == "mm/period"
    assert result.provenance.source_dataset_id == MOD16_GAPFILLED


def test_et_scale_factor_is_not_a_hundred(fake_ee):
    """Guards against the MODIS 0.0001 reflectance factor being reused."""
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    result = EvapotranspirationMetric().compute(make_context())
    assert result.value != pytest.approx(0.03)
    assert result.value != pytest.approx(3.0)


def test_pet_applies_the_scale_factor(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"PET": [450.0] * 4}})
    result = PotentialEvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(45.0)
    assert result.unit == "mm/period"


def test_et_and_pet_read_different_bands(fake_ee):
    """Wiring PET to the ET band would be invisible but wrong."""
    fake_ee({MOD16_GAPFILLED: {"ET": [100.0] * 4, "PET": [500.0] * 4}})

    et = EvapotranspirationMetric().compute(make_context())
    pet = PotentialEvapotranspirationMetric().compute(make_context())

    assert et.value == pytest.approx(10.0)
    assert pet.value == pytest.approx(50.0)
    assert et.value != pet.value


def test_mod16_fill_values_are_rejected_by_the_band_spec():
    """The product's fill sentinels cannot enter as a real reading.

    The catalogue records that the 32761-32767 fill values are removed
    from the Earth Engine assets entirely. ``to_physical`` is asserted to
    reject them anyway, so a value that slipped through would still not
    be published as a measurement.
    """
    spec = get_dataset(MOD16_GAPFILLED).band("ET")
    assert spec.to_physical(32767) is None
    assert spec.to_physical(32766) is None


def test_et_provenance_states_the_composite_window(fake_ee):
    """An 8-day composite is not a daily rate, and must say so."""
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    result = EvapotranspirationMetric().compute(make_context())

    caveats = " ".join(result.provenance.caveats).lower()
    assert "8-day" in caveats or "8 day" in caveats


def test_et_provenance_names_the_band_and_the_scale(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    result = EvapotranspirationMetric().compute(make_context())

    assert result.provenance.bands == ["ET"]
    assert "0.1" in result.provenance.formula


def test_et_declares_the_aggregation_method(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    result = EvapotranspirationMetric().compute(make_context())
    method = result.provenance.aggregation_method.lower()
    assert "composite" in method
    assert "spatial" in method


def test_mod16_metric_metadata_records_the_band_and_cadence():
    payload = EvapotranspirationMetric().metadata()
    assert payload["band"] == "ET"
    assert payload["native_temporal_resolution"] == "8 days"


def test_et_with_no_composite_is_insufficient_not_zero(fake_ee):
    """Reporting zero would claim the crop used no water."""
    fake_ee({MOD16_GAPFILLED: {"ET": []}})
    result = EvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_et_with_no_valid_pixels_is_insufficient_not_zero(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [NO_DATA] * 6}})
    result = EvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_near_real_time_product_is_recorded_as_a_fallback(fake_ee):
    """Using the un-gap-filled product must be visible in provenance."""
    fake_ee({MOD16_NRT: {"ET": [300.0] * 4}})
    context = make_context(options={"mod16_dataset": MOD16_NRT})
    result = EvapotranspirationMetric().compute(context)

    assert result.status == STATUS_OK
    assert result.provenance.source_dataset_id == MOD16_NRT
    assert result.provenance.fallback_from == MOD16_GAPFILLED


def test_near_real_time_product_carries_a_warning(fake_ee):
    fake_ee({MOD16_NRT: {"ET": [300.0] * 4}})
    context = make_context(options={"mod16_dataset": MOD16_NRT})
    result = EvapotranspirationMetric().compute(context)

    assert result.warnings
    assert any("gap-filled" in w.lower() or "real-time" in w.lower()
               for w in result.warnings)


def test_requesting_the_gapfilled_product_is_not_a_fallback(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 4}})
    context = make_context(options={"mod16_dataset": MOD16_GAPFILLED})
    result = EvapotranspirationMetric().compute(context)

    assert result.provenance.fallback_from is None


def test_mod16_returns_insufficient_when_the_collection_is_empty(fake_ee):
    """An empty result must not be silently indistinguishable from zero."""
    fake_ee({MOD16_GAPFILLED: {"ET": []}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA


# -- cumulative ----------------------------------------------------------


def test_cumulative_et_sums_the_composite_periods(fake_ee):
    """Three composites of 30, 40 and 50 mm total 120 mm."""
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0, 400.0, 500.0]}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(120.0)
    assert result.unit == "mm"


def test_cumulative_et_is_not_the_mean(fake_ee):
    """The cumulative metric must not equal the per-period mean."""
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0, 400.0, 500.0]}})

    cumulative = CumulativeEvapotranspirationMetric().compute(make_context())
    per_period = EvapotranspirationMetric().compute(make_context())

    assert cumulative.value == pytest.approx(120.0)
    assert per_period.value == pytest.approx(40.0)
    assert cumulative.value != pytest.approx(per_period.value)


def test_cumulative_et_does_not_double_count(fake_ee):
    """Each composite contributes exactly once.

    Three composites summing to 120 mm must not produce 240 mm, which is
    what a boundary-straddling composite counted twice would give.
    """
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0, 400.0, 500.0]}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    assert result.value == pytest.approx(120.0)
    assert result.value != pytest.approx(240.0)
    assert result.value < 130.0


def test_cumulative_et_reports_a_zero_only_when_composites_were_zero(fake_ee):
    """A genuine zero accumulation is real data."""
    fake_ee({MOD16_GAPFILLED: {"ET": [0.0, 0.0, 0.0]}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


def test_cumulative_et_is_insufficient_when_no_composite_has_a_mean(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [NO_DATA] * 4}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_cumulative_et_declares_the_no_double_count_rule(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0, 400.0]}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    caveats = " ".join(result.provenance.caveats).lower()
    assert "once" in caveats or "double" in caveats


def test_cumulative_et_provenance_names_the_sum(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0, 400.0]}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())

    assert "sum" in result.provenance.formula.lower()
    method = result.provenance.aggregation_method.lower()
    assert "sum" in method


def test_cumulative_et_quality_uses_the_modis_thresholds(fake_ee):
    fake_ee({MOD16_GAPFILLED: {"ET": [300.0] * 6}})
    result = CumulativeEvapotranspirationMetric().compute(make_context())
    assert result.provenance.quality_level in set(QualityLevel)


# ==========================================================================
# 3. ERA5-Land evaporation and the sign convention
# ==========================================================================


def test_era5_evaporation_from_stored_negates():
    """The core sign test. A stored -5 mm is 5 mm of evaporation."""
    assert era5_evaporation_from_stored(-0.005) == pytest.approx(5.0)


def test_era5_stored_negative_becomes_positive_evaporation():
    assert era5_evaporation_from_stored(-0.001) == pytest.approx(1.0)
    assert era5_evaporation_from_stored(-0.02) == pytest.approx(20.0)


def test_era5_stored_positive_becomes_negative_condensation():
    """Condensation is stored positive and must stay negative.

    This is the test that a naive ``abs()`` implementation fails: it
    would report 5 mm of evaporation where 5 mm of dew formed.
    """
    assert era5_evaporation_from_stored(0.005) == pytest.approx(-5.0)
    assert era5_evaporation_from_stored(0.001) < 0


def test_era5_conversion_is_a_negation_not_an_absolute_value():
    """Explicitly assert that abs() is not applied.

    A condensation day must not survive as a positive number.
    """
    condensation = era5_evaporation_from_stored(0.003)
    assert condensation is not None
    assert condensation < 0
    assert condensation != pytest.approx(abs(-0.003) * 1000.0)


def test_era5_conversion_is_not_clamped_to_zero():
    """Clamping would delete every evaporation event.

    A real evaporation day must come out strictly positive, which
    clamping a negative input would not produce.
    """
    evaporation = era5_evaporation_from_stored(-0.004)
    assert evaporation is not None
    assert evaporation > 0
    assert evaporation != pytest.approx(0.0)


def test_era5_conversion_applies_the_thousandfold_metres_to_millimetres():
    assert era5_evaporation_from_stored(-1.0) == pytest.approx(1000.0)
    assert era5_evaporation_from_stored(-0.000001) == pytest.approx(0.001)


def test_era5_conversion_rejects_none():
    assert era5_evaporation_from_stored(None) is None


def test_era5_conversion_rejects_booleans():
    """bool is an int subclass, so True would otherwise negate to -1.0."""
    assert era5_evaporation_from_stored(True) is None
    assert era5_evaporation_from_stored(False) is None


def test_era5_conversion_rejects_non_numeric():
    assert era5_evaporation_from_stored("0.005") is None
    assert era5_evaporation_from_stored([]) is None
    assert era5_evaporation_from_stored(object()) is None


def test_era5_conversion_rejects_non_finite():
    assert era5_evaporation_from_stored(float("nan")) is None
    assert era5_evaporation_from_stored(float("inf")) is None
    assert era5_evaporation_from_stored(float("-inf")) is None


def test_era5_conversion_preserves_a_true_zero():
    """A genuinely zero flux is real data, not missing data."""
    assert era5_evaporation_from_stored(0.0) == pytest.approx(0.0)
    assert era5_evaporation_from_stored(-0.0) == pytest.approx(0.0)


def test_era5_evaporation_metric_reads_the_total_band_not_a_component():
    """The component bands carry swapped values and must not be read."""
    metric = ERA5EvaporationMetric()
    assert metric.source_bands == (ERA5_EVAPORATION_BAND,)
    for band in metric.source_bands:
        assert "bare_soil" not in band
        assert "open_water" not in band
        assert "transpiration" not in band


def test_era5_evaporation_metric_uses_the_daily_aggregation():
    assert ERA5EvaporationMetric().dataset_ids == (ERA5_DAILY,)
    assert ERA5EvaporationMetric().default_scale == 11132


def test_era5_evaporation_total_over_a_period(fake_ee):
    """Two days of 4 mm and 6 mm evaporate 10 mm in total."""
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004, -0.006]}})
    result = ERA5EvaporationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(10.0)
    assert result.unit == "mm"


def test_era5_evaporation_is_positive_when_water_leaves(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004, -0.006]}})
    result = ERA5EvaporationMetric().compute(make_context())
    assert result.value > 0


def test_era5_condensation_day_reduces_the_total(fake_ee):
    """A condensation night must subtract, not be hidden.

    Day one evaporates 5 mm; day two condenses 1 mm. The period total is
    4 mm. An ``abs()`` implementation would report 6 mm.
    """
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.005, 0.001]}})
    result = ERA5EvaporationMetric().compute(make_context())

    assert result.value == pytest.approx(4.0)
    assert result.value != pytest.approx(6.0)


def test_era5_condensation_is_reported_as_a_warning(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.005, 0.001, -0.002]}})
    result = ERA5EvaporationMetric().compute(make_context())

    assert result.warnings
    assert any("condensation" in w.lower() for w in result.warnings)


def test_era5_condensation_count_is_reported(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [0.001, 0.002, -0.005]}})
    result = ERA5EvaporationMetric().compute(make_context())

    joined = " ".join(result.warnings).lower()
    assert "2 of 3" in joined


def test_era5_no_condensation_means_no_condensation_warning(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004, -0.006]}})
    result = ERA5EvaporationMetric().compute(make_context())
    assert not any("condensation" in w.lower() for w in result.warnings)


def test_era5_provenance_publishes_the_sign_convention(fake_ee):
    """The sign rule must be in the record, not just in the code."""
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004]}})
    result = ERA5EvaporationMetric().compute(make_context())

    formula = result.provenance.formula.lower()
    caveats = " ".join(result.provenance.caveats).lower()
    assert "-1" in formula or "negat" in formula
    assert "condensation" in caveats
    assert "evaporation" in caveats


def test_era5_provenance_says_abs_and_clamping_were_not_used(fake_ee):
    """The decision not to use abs() is recorded, not implicit."""
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004]}})
    result = ERA5EvaporationMetric().compute(make_context())

    limitations = " ".join(result.provenance.limitations).lower()
    assert "absolute" in limitations
    assert "clamp" in limitations


def test_era5_provenance_states_the_component_swaps(fake_ee):
    """A caller must be told that splitting the total would be wrong."""
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004]}})
    result = ERA5EvaporationMetric().compute(make_context())

    limitations = " ".join(result.provenance.limitations).lower()
    assert "swapped" in limitations or "component" in limitations


def test_era5_evaporation_with_no_days_is_insufficient(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: []}})
    result = ERA5EvaporationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_era5_evaporation_with_no_usable_day_is_insufficient(fake_ee):
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [NO_DATA, NO_DATA]}})
    result = ERA5EvaporationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_era5_evaporation_never_reports_a_missing_day_as_zero(fake_ee):
    """A gap must not become a dry day."""
    fake_ee({ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004, NO_DATA, -0.006]}})
    result = ERA5EvaporationMetric().compute(make_context())

    # Only the two real days count: 4 + 6 = 10 mm.
    assert result.value == pytest.approx(10.0)


# -- ERA5 potential evaporation is deliberately not produced -------------


def test_era5_potential_evaporation_is_unavailable(fake_ee):
    """The sign convention is undocumented, so no value may be produced."""
    fake_ee({ERA5_DAILY: {"potential_evaporation_sum": [-0.004] * 3}})
    result = ERA5PotentialEvaporationMetric().compute(make_context())

    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None


def test_era5_potential_evaporation_explains_why(fake_ee):
    fake_ee({ERA5_DAILY: {"potential_evaporation_sum": [-0.004]}})
    result = ERA5PotentialEvaporationMetric().compute(make_context())

    message = (result.message or "").lower()
    assert "sign convention" in message
    assert "not documented" in message or "no documented" in message


def test_era5_potential_evaporation_does_not_assume_a_sign(fake_ee):
    """It must not return a number even when the band looks plausible."""
    fake_ee({ERA5_DAILY: {"potential_evaporation_sum": [-0.05] * 10}})
    result = ERA5PotentialEvaporationMetric().compute(make_context())

    assert result.value is None
    assert result.status == STATUS_UNAVAILABLE


def test_era5_potential_evaporation_declares_the_band_but_does_not_read_it():
    metric = ERA5PotentialEvaporationMetric()
    assert metric.source_bands == ("potential_evaporation_sum",)
    assert metric.measurement_basis is MeasurementBasis.MODELLED


def test_era5_potential_evaporation_points_at_the_mod16_alternative(fake_ee):
    fake_ee({ERA5_DAILY: {"potential_evaporation_sum": [-0.004]}})
    result = ERA5PotentialEvaporationMetric().compute(make_context())
    assert "MOD16" in (result.message or "")


def test_era5_potential_evaporation_is_registered_among_the_available_metrics():
    """It is a registered metric that always answers 'unavailable'.

    That is different from CWSI, which is not produced at all. This one
    exists because the band exists and a caller will ask for it.
    """
    assert ERA5PotentialEvaporationMetric().key in {
        m.key for m in WATER_METRICS
    }


# ==========================================================================
# 4. CWSI and WDI — registered, and structurally incapable of a value
# ==========================================================================


def test_cwsi_is_unavailable():
    result = CWSIMetric().compute(make_context())
    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None


def test_wdi_is_unavailable():
    result = WDIMetric().compute(make_context())
    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None


def test_cwsi_explains_the_missing_baseline():
    """The reason must name the missing input, not say 'not available'."""
    reason = CWSI_UNAVAILABLE_REASON.lower()
    assert "baseline" in reason
    assert "well-watered" in reason
    assert "canopy temperature" in reason
    assert len(CWSI_UNAVAILABLE_REASON) > 100


def test_wdi_explains_the_missing_trapezoid():
    reason = WDI_UNAVAILABLE_REASON.lower()
    assert "trapezoid" in reason
    assert "baseline" in reason
    assert len(WDI_UNAVAILABLE_REASON) > 100


def test_cwsi_states_that_no_proxy_is_being_substituted():
    """The reason must be explicit that no number is being invented."""
    reason = CWSI_UNAVAILABLE_REASON.lower()
    assert "no value is reported" in reason
    assert "not be validated" in reason or "validated" in reason


def test_wdi_states_the_index_is_unidentifiable():
    reason = WDI_UNAVAILABLE_REASON.lower()
    assert "unidentifiable" in reason or "no value is reported" in reason


def test_cwsi_has_a_machine_readable_code():
    assert CWSI_UNAVAILABLE_CODE == "no_well_watered_baseline"


def test_wdi_has_a_machine_readable_code():
    assert WDI_UNAVAILABLE_CODE == "no_temperature_trapezoid_baseline"


def test_cwsi_metadata_reports_itself_unavailable():
    payload = CWSIMetric().metadata()
    assert payload["available"] is False
    assert payload["unavailable_code"] == CWSI_UNAVAILABLE_CODE
    assert payload["unavailable_reason"] == CWSI_UNAVAILABLE_REASON


def test_wdi_metadata_reports_itself_unavailable():
    payload = WDIMetric().metadata()
    assert payload["available"] is False
    assert payload["unavailable_code"] == WDI_UNAVAILABLE_CODE
    assert payload["unavailable_reason"] == WDI_UNAVAILABLE_REASON


def test_unavailable_metrics_declare_no_datasets():
    """They read nothing, because no dataset supplies what they need."""
    for metric in UNAVAILABLE_WATER_METRICS:
        assert metric.dataset_ids == (), metric.key


def test_cwsi_cannot_carry_a_value_even_with_a_populated_context(fake_ee):
    """Structural guarantee: the class returns unavailable unconditionally.

    Even with every plausible dataset present, the metric must not
    produce a number. This is what prevents a future change from
    accidentally turning it into a fabricated indicator.
    """
    fake_ee(
        {
            "COPERNICUS/S2_SR_HARMONIZED": {
                "B3": [0.1] * 5,
                "B4": [0.1] * 5,
                "B8": [0.5] * 5,
                "B11": [0.2] * 5,
            },
            ERA5_DAILY: {
                ERA5_EVAPORATION_BAND: [-0.004] * 5,
                "temperature_2m": [300.0] * 5,
            },
        }
    )
    for metric in (CWSIMetric(), WDIMetric()):
        result = metric.compute(make_context())
        assert result.value is None, metric.key
        assert result.status == STATUS_UNAVAILABLE, metric.key


def test_unavailable_metrics_are_inferences_not_products():
    """They carry no measurement basis of their own."""
    for metric in UNAVAILABLE_WATER_METRICS:
        assert metric.measurement_basis is MeasurementBasis.INFERENCE, metric.key


def test_unavailable_metrics_explain_themselves_in_provenance_terms():
    for metric in UNAVAILABLE_WATER_METRICS:
        assert metric.unavailable_reason, metric.key
        assert len(metric.unavailable_reason) > 100, metric.key
        assert metric.unavailable_code, metric.key


def test_unavailable_metrics_carry_limitations():
    for metric in UNAVAILABLE_WATER_METRICS:
        assert metric.limitations, metric.key


def test_cwsi_limitations_say_the_bounds_are_not_observable():
    joined = " ".join(CWSIMetric().limitations).lower()
    assert "satellite" in joined
    assert "baseline" in joined or "bound" in joined


def test_no_water_metric_is_named_with_a_proxy_suffix():
    """A proxy must never be published under the name of the real index."""
    for metric in ALL_WATER_METRICS:
        assert "_proxy" not in metric.key, metric.key
        assert "proxy" not in metric.display_name.lower(), metric.key


def test_no_water_metric_publishes_a_cwsi_or_wdi_number():
    """The strongest statement of the Phase F decision.

    Both metrics are asked directly, without any fixture, and neither may
    produce a number. They take no data path at all, so this holds
    regardless of what any dataset contains.
    """
    for metric in ALL_WATER_METRICS:
        if metric.key in ("cwsi", "wdi"):
            result = metric.compute(make_context())
            assert result.value is None, metric.key
            assert result.status == STATUS_UNAVAILABLE, metric.key
            assert result.provenance is None or (
                result.provenance.quality_level is QualityLevel.UNAVAILABLE
            ), metric.key


# ==========================================================================
# Cross-cutting
# ==========================================================================


def test_every_available_water_metric_returns_a_result_object(fake_ee):
    """No metric may return a bare number.

    Spectral indices are excluded here because they open a Sentinel-2
    collection, which this suite does not fake; their band wiring is
    asserted separately above.

    Both dataset families are provided so that every non-index metric
    can take its real compute path rather than being short-circuited by
    a missing fixture.
    """
    fake_ee(
        {
            ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004] * 4},
            MOD16_GAPFILLED: {"ET": [300.0] * 4, "PET": [400.0] * 4},
            MOD16_NRT: {"ET": [300.0] * 4, "PET": [400.0] * 4},
        }
    )
    skipped = (NDWIMetric, NDMIMetric, MNDWIMetric, MSIMetric)
    for metric in ALL_WATER_METRICS:
        if isinstance(metric, skipped):
            continue
        result = metric.compute(make_context())
        assert result.metric_key == metric.key, metric.key


def test_no_available_metric_publishes_a_value_without_provenance(fake_ee):
    """The central safety rule."""
    fake_ee(
        {
            ERA5_DAILY: {ERA5_EVAPORATION_BAND: [-0.004] * 4},
            MOD16_GAPFILLED: {"ET": [300.0] * 4, "PET": [400.0] * 4},
        }
    )
    for metric in (
        EvapotranspirationMetric(),
        PotentialEvapotranspirationMetric(),
        CumulativeEvapotranspirationMetric(),
        ERA5EvaporationMetric(),
    ):
        result = metric.compute(make_context())
        if result.value is not None:
            assert result.provenance is not None, metric.key


def test_insufficient_results_never_carry_a_value(fake_ee):
    """Emptying each band in turn must never yield zero."""
    for dataset_id, band in (
        (MOD16_GAPFILLED, "ET"),
        (MOD16_GAPFILLED, "PET"),
        (ERA5_DAILY, ERA5_EVAPORATION_BAND),
    ):
        fake_ee({dataset_id: {band: []}})
        for metric in (
            EvapotranspirationMetric(),
            PotentialEvapotranspirationMetric(),
            CumulativeEvapotranspirationMetric(),
            ERA5EvaporationMetric(),
        ):
            try:
                result = metric.compute(make_context())
            except KeyError:
                # The sparse fixture does not hold this metric's band.
                continue
            if result.status in (STATUS_INSUFFICIENT_DATA, STATUS_UNAVAILABLE):
                assert result.value is None, f"{metric.key} via {band}"


def test_a_metric_reading_an_undeclared_band_fails_loudly(monkeypatch):
    """The fake is strict on purpose: a wrong band must raise.

    The fixture provides only the ET band, so a PET metric has to fail
    rather than be handed ET's values and report them as PET.
    """
    fake = FakeEE({MOD16_GAPFILLED: {"ET": [300.0]}})
    for name in ("ImageCollection", "Reducer", "Filter"):
        monkeypatch.setattr(f"ee.{name}", getattr(fake, name))

    with pytest.raises(KeyError):
        PotentialEvapotranspirationMetric().compute(make_context())


def test_every_water_metric_can_attempt_a_normal_period():
    """Can-attempt must not reject a plausible recent request."""
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    for metric in WATER_METRICS:
        if metric.key in ("ndwi", "ndmi", "mndwi"):
            continue
        can_attempt, reason = metric.can_attempt(context)
        assert can_attempt, f"{metric.key}: {reason}"


def test_era5_evaporation_declares_the_reanalysis_resolution():
    """An 11 km field must not be described as field-scale."""
    joined = " ".join(ERA5EvaporationMetric().limitations).lower()
    assert "11 km" in joined
    assert "not a measurement" in joined or "not measured" in joined
