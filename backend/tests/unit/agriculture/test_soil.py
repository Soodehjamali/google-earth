"""Tests for the soil moisture engine.

The governing risk in this module is a units-and-quantity confusion, and
it is a serious one because every wrong answer looks like a plausible
soil moisture value:

1. **A volume fraction presented as a mass per unit area, or the
   reverse.** ``m3/m3``, ``kg/m2`` and ``mm`` are three different
   quantities. ``kg/m2`` depends on how thick the layer is, so converting
   it to ``m3/m3`` requires the layer depth and the water density. Doing
   it silently produces a number with no physical meaning that is
   nonetheless in a believable range.

2. **Two overpasses averaged into a time that does not exist.** Surface
   soil moisture has a strong diurnal cycle. Averaging the SMAP morning
   and evening retrievals describes neither 06:00 nor 18:00.

3. **A retrieval conflated with a model.** The SMAP L3 value is a
   radiometer retrieval of the top 0 to 5 cm. The SMAP L4 value is an
   assimilated model of the top 0 to 100 cm. The ERA5 value is a pure
   model field. They must not be compared as though they measured the
   same thing.

4. **A skipped retrieval read as a dry one.** The SMAP quality flag is
   not a good/bad integer. A pixel whose retrieval was skipped holds a
   fill value, and reading that as a measurement understates soil water.

5. **A missing value reported as zero.** A dry soil and an unobserved
   soil are different claims and must not be collapsed.

The Earth Engine calls are exercised through a strict fake module rather
than skipped, so the real ``compute`` paths run. No network and no
credentials are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture.aggregation import parse_reduction_result
from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.quality import (
    SMAP_RETRIEVAL_NOT_ATTEMPTED,
    SMAP_RETRIEVAL_RECOMMENDED,
    SMAP_RETRIEVAL_SKIPPED,
    SMAP_RETRIEVAL_UNCERTAIN,
    decode_smap_retrieval_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.soil import (
    ERA5_DAILY,
    ERA5_LAYER_DEPTHS_CM,
    GLDAS_NATIVE_SCALE,
    GLDAS_NOAH,
    SMAP_L3_CURRENT,
    SMAP_L3_PREVIOUS,
    SMAP_L4,
    SMAP_NATIVE_SCALE,
    SOIL_METRICS,
    RootZoneSoilMoistureGLDASMetric,
    SoilMoistureRootZoneERA5Metric,
    SoilMoistureRootZoneMetric,
    SoilMoistureSurfaceEveningMetric,
    SoilMoistureSurfaceMetric,
    SoilMoistureWetnessMetric,
    _smap_dataset_id,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

EXPECTED_KEYS = {
    "soil_moisture_surface",
    "soil_moisture_surface_evening",
    "soil_moisture_rootzone",
    "soil_moisture_rootzone_era5",
    "soil_moisture_wetness",
    "root_zone_soil_moisture_gldas",
}

#: The one soil metric published in a mass per unit area rather than a
#: volume fraction, because its product reports a mass per unit area and no
#: defensible conversion to m3/m3 exists.
MASS_PER_AREA_KEY = "root_zone_soil_moisture_gldas"

#: Sentinel that lets a test mark a pixel as having no data.
NO_DATA = object()

#: A plausible pixel tally, large enough to clear the threshold floors.
#: Without it every result would be ``insufficient`` for a reason that
#: has nothing to do with the quantity under test.
PIXEL_TALLY = 5000


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
    """One band of one image.

    ``select`` raises when asked for a band this image does not hold, so
    a metric reading the morning band when it declared the evening one
    fails loudly rather than returning the same number for both.
    """

    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        if isinstance(values, list):
            self._values = list(values)
        else:
            self._values = [values]
        self._properties = {}
        self._masked = False

    @property
    def band(self) -> str:
        return self._band

    @property
    def masked(self) -> bool:
        """Whether a quality mask was applied to this image."""
        return self._masked

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

    def updateMask(self, mask):  # noqa: N802 - mirrors ee.Image
        """Record that a mask was applied and drop the masked pixels.

        The fake honours the mask rather than ignoring it, so a metric
        that fails to mask a skipped retrieval is observably different
        from one that does.
        """
        masked = _FakeImage(self._ee, self._band, self._values)
        masked._masked = True
        if isinstance(mask, _FakeImage) and mask._values:
            # A mask value of 1 keeps the pixel, 0 drops it.
            keep = [bool(v) for v in mask._values]
            if len(keep) == len(masked._values):
                masked._values = [
                    v if keep[i] else NO_DATA
                    for i, v in enumerate(masked._values)
                ]
        return masked

    def bitwiseAnd(self, other):  # noqa: N802 - mirrors ee.Image
        # Bitwise operations are integer-only on Earth Engine, and the
        # service rejects them based on the band's type: a float-typed
        # band fails even when every value is a whole number. The fake
        # stores values without types, so float values stand in for a
        # float-typed band and are rejected the same way.
        for v in self._values:
            if isinstance(v, float):
                raise TypeError(
                    "Image.bitwiseAnd: Bitwise operands must be integer only"
                )
        return _FakeImage(
            self._ee, self._band, [int(v) & int(other) for v in self._values]
        )

    def round(self):  # noqa: N802 - mirrors ee.Image
        return _FakeImage(
            self._ee, self._band, [round(v) for v in self._values]
        )

    def toInt(self):  # noqa: N802 - mirrors ee.Image
        return _FakeImage(
            self._ee, self._band, [int(v) for v in self._values]
        )

    def neq(self, other):  # noqa: N802 - mirrors ee.Image
        return _FakeImage(
            self._ee, self._band, [v != other for v in self._values]
        )

    def Not(self):  # noqa: N802 - mirrors ee.Image boolean invert
        """Invert a boolean image, as ``.Not()`` does.

        Values are normalised to 0/1 so that ``updateMask`` can use them
        directly: a mask of 1 keeps a pixel and 0 drops it.
        """
        return _FakeImage(
            self._ee, self._band, [0 if v else 1 for v in self._values]
        )

    def lt(self, other):
        return _FakeImage(
            self._ee, self._band, [v < other for v in self._values]
        )

    def rename(self, name):
        return _FakeImage(self._ee, name, self._values)

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(_reduce_values(self._values))


class _FakeMultiBandImage:
    """One image carrying the whole dataset's bands at one time index.

    This is the shape an unselected ``ee.Image`` has, and it is what the
    SMAP masking step receives. It supports selecting either band, so a
    metric that masks the soil band using the flag band behaves the way
    it would against Earth Engine: the flag is read, a boolean mask is
    derived, and the soil values are dropped where the mask is false.

    A mask is only applied when the metric actually calls
    ``updateMask``. A metric that forgets to mask therefore leaves the
    raw values in place, which the skip-bit tests detect.
    """

    def __init__(self, ee_module, values) -> None:
        self._ee = ee_module
        self._values = {k: v for k, v in values.items()}
        self._properties = {}

    def set(self, key, value, **_kwargs):
        self._properties[key] = value
        return self

    def get(self, key):
        return self._properties.get(key)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        band = bands[0]
        if band not in self._values:
            raise KeyError(
                f"fake image holds {sorted(self._values)}, not {band!r}"
            )
        return _FakeImage(self._ee, band, self._values[band])

    def rename(self, name):
        # Only meaningful for a single-band image; used after a select.
        if len(self._values) == 1:
            return _FakeImage(self._ee, name, next(iter(self._values.values())))
        raise AssertionError("cannot rename a multi-band fake image")


class _FakeCollectionSelector:
    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        self._values = list(values)

    def size(self):
        return _FakeNumber(len(self._values))

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

    def map(self, func):
        return _FakeMapped(self._ee, [func(self._day(v)) for v in self._values])

    def _day(self, value):
        return _FakeImage(self._ee, self._band, value)


class _FakeMapped:
    """A mapped collection, still able to composite and expose properties.

    The real client cannot call ``getInfo`` on a mapped collection, so
    that is deliberately a failure here. It can, however, composite the
    mapped images with a reducer, and it can read a per-image property
    back with ``aggregate_array``.
    """

    def __init__(self, ee_module, items) -> None:
        self._ee = ee_module
        self._items = items

    def _flatten(self):
        """Every value across every mapped image.

        ``NO_DATA`` entries are kept as a marker so a composite can drop
        them; masking a pixel sets it to ``NO_DATA`` rather than removing
        it from the list, so the arithmetic has to skip it.
        """
        values = []
        for item in self._items:
            if isinstance(item, _FakeImage):
                values.extend(item._values)
            else:
                values.append(NO_DATA)
        return values

    def aggregate_array(self, name):
        values = []
        for item in self._items:
            getter = getattr(item, "get", None)
            value = getter(name) if callable(getter) else None
            values.append(None if value is NO_DATA else value)
        return _FakeNumber(values)

    def median(self):
        """Median across the mapped images, per band.

        This is the reduction the SMAP path applies after masking. Pixels
        the mask dropped are excluded, so a skipped retrieval cannot
        enter the composite as a dry value.
        """
        usable = [v for v in self._flatten() if v is not NO_DATA]
        band = self._items[0]._band if self._items else ""
        if not usable:
            return _FakeImage(self._ee, band, [NO_DATA])
        if len(usable) == 1:
            return _FakeImage(self._ee, band, [usable[0]])
        ordered = sorted(usable)
        middle = len(ordered) // 2
        if len(ordered) % 2 == 0:
            value = (ordered[middle - 1] + ordered[middle]) / 2.0
        else:
            value = ordered[middle]
        return _FakeImage(self._ee, band, [value])

    def mean(self):
        usable = [v for v in self._flatten() if v is not NO_DATA]
        band = self._items[0]._band if self._items else ""
        if not usable:
            return _FakeImage(self._ee, band, [NO_DATA])
        return _FakeImage(self._ee, band, [sum(usable) / len(usable)])

    def size(self):
        return _FakeNumber(len(self._items))

    def getInfo(self):
        raise AssertionError(
            "getInfo() on a mapped collection is not a list of values; "
            "use aggregate_array(property).getInfo() instead"
        )


class _LazyCollection:
    def __init__(self, ee_module, dataset_id, emit) -> None:
        self._ee = ee_module
        self._dataset_id = dataset_id

    def _bands(self):
        return self._ee._by_dataset.get(self._dataset_id)

    def _length(self):
        """How many images this collection holds.

        A real collection's size does not depend on which band is
        selected, so every band belonging to the dataset must agree on
        the length. Where they disagree the fixture is malformed, and
        that is raised rather than papered over.
        """
        available = self._bands()
        if not available:
            return 0
        lengths = {len(v) for v in available.values()}
        if len(lengths) != 1:
            raise ValueError(
                f"fixture for {self._dataset_id!r} has bands of differing "
                f"length: {sorted(lengths)}"
            )
        return lengths.pop()

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def size(self):
        """Count before a band is chosen, as a real collection allows."""
        return _FakeNumber(self._length())

    def map(self, func):
        """Map over the collection before a band is selected.

        The SMAP metric reads two bands from each image — the soil value
        and its quality flag — so the images handed to ``func`` carry
        every band of the dataset, one value per image index, exactly as
        an unselected ``ee.Image`` does.
        """
        available = self._bands() or {}
        items = []
        for index in range(self._length()):
            values = {band: v[index] for band, v in available.items()}
            items.append(_FakeMultiBandImage(self._ee, values))
        return _FakeMapped(self._ee, [func(image) for image in items])

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        band = bands[0]
        available = self._bands()
        if available is None:
            raise KeyError(
                f"test fixture has no data for dataset {self._dataset_id!r}"
            )
        if band not in available:
            raise KeyError(
                f"fixture for {self._dataset_id!r} holds "
                f"{sorted(available)}, not {band!r}"
            )
        return _Selecting(self, band, available[band])


class _Selecting:
    """A collection narrowed to one band.

    ``select`` on the collection is what a metric uses to strip the
    quality flag before compositing, and ``map`` is where a metric
    applies its mask. This wrapper supports both without losing track of
    which band is in play.
    """

    def __init__(self, collection, band, values) -> None:
        self._collection = collection
        self._ee = collection._ee
        self._band = band
        self._values = list(values)

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        if bands and bands[0] != self._band:
            raise KeyError(
                f"selection holds {self._band!r}, not {bands!r}"
            )
        return self

    def size(self):
        return _FakeNumber(len(self._values))

    def map(self, func):
        return _FakeMapped(
            self._ee, [func(self._day(v)) for v in self._values]
        )

    def _day(self, value):
        """One day's image.

        The value is the selected band's own value. A metric that reads
        a second band from this image will raise, because the image only
        carries the selected band, which is what a real ``select`` leaves
        behind.
        """
        return _FakeImage(self._ee, self._band, value)

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


class FakeEE:
    """Minimal Earth Engine stand-in.

    Bands are supplied as ``{dataset_id: {band_name: [values]}}``. The
    flat ``{band_name: [values]}`` form is accepted as sugar and is
    registered under every soil dataset, so a single-dataset fixture
    stays readable.

    A SMAP soil moisture band always ships alongside its quality flag in
    the real product, and the two are registered in the same collection,
    so when a fixture supplies a soil band but no flag, a permissive
    flag of all zeros is added automatically. Tests that care about the
    flag's content supply it explicitly, and the explicit value wins.
    """

    #: Soil moisture bands and the flag that pairs with each.
    _SMAP_FLAG_FOR = {
        "soil_moisture_am": "retrieval_qual_flag_am",
        "soil_moisture_pm": "retrieval_qual_flag_pm",
    }

    def __init__(self, bands) -> None:
        if bands and all(isinstance(v, dict) for v in bands.values()):
            self._by_dataset = {
                k: {b: list(v) for b, v in inner.items()}
                for k, inner in bands.items()
            }
        else:
            self._by_dataset = {
                dataset_id: {k: list(v) for k, v in bands.items()}
                for dataset_id in (SMAP_L3_CURRENT, SMAP_L3_PREVIOUS,
                                   SMAP_L4, ERA5_DAILY, GLDAS_NOAH)
            }
        self._add_implied_smap_flags()
        self.Reducer = _FakeReducerNamespace()

    def _add_implied_smap_flags(self):
        """Give every SMAP soil band the flag band the product ships.

        The implied flag is all zeros, meaning a recommended-quality
        retrieval, so a fixture that does not care about quality does not
        have to state it. A fixture that does care supplies its own flag,
        and this leaves it untouched.
        """
        for inner in self._by_dataset.values():
            for soil_band, flag_band in self._SMAP_FLAG_FOR.items():
                if soil_band in inner and flag_band not in inner:
                    inner[flag_band] = [0] * len(inner[soil_band])

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        return _LazyCollection(self, dataset_id, None)

    def Filter(self):  # noqa: N802 - mirrors ee API
        return _FakeReducer("filter")


@pytest.fixture
def fake_ee(monkeypatch):
    """Install a fake ``ee`` for the duration of a test.

    The real ``ee`` package's attributes are replaced, not just the
    ``sys.modules`` entry, because each ``compute`` does a function-local
    ``import ee`` which would otherwise bind the real module.
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


def test_all_expected_soil_metrics_present():
    assert {m.key for m in SOIL_METRICS} == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in SOIL_METRICS]
    assert len(keys) == len(set(keys))


def test_every_soil_metric_is_in_the_soil_domain():
    for metric in SOIL_METRICS:
        assert metric.domain is MetricDomain.SOIL, metric.key


def test_every_soil_metric_declares_a_unit():
    for metric in SOIL_METRICS:
        assert metric.unit and metric.unit != "unknown", metric.key


def test_every_soil_metric_declares_limitations():
    for metric in SOIL_METRICS:
        assert metric.limitations, metric.key


def test_every_soil_metric_is_registrable():
    register_metrics(SOIL_METRICS)
    from app.services.agriculture.catalog import metric_keys

    assert EXPECTED_KEYS.issubset(set(metric_keys()))


def test_no_soil_metric_claims_to_be_direct():
    """No in-situ probe is read, so nothing here is a direct measurement."""
    for metric in SOIL_METRICS:
        assert metric.measurement_basis is not MeasurementBasis.DIRECT, metric.key


def test_soil_moisture_units_are_volume_fractions():
    """Soil-moisture metrics report a volume fraction, not a mass or a depth.

    Presenting kg/m2 or mm under an m3/m3 label is the error this asserts
    against. Two exceptions are deliberate and are each asserted
    separately: the wetness metric reports a dimensionless relative
    saturation, and the GLDAS metric reports a mass per unit area because
    that is the unit its product publishes.
    """
    for metric in SOIL_METRICS:
        if metric.key == "soil_moisture_wetness":
            assert metric.unit == "fraction", metric.key
            continue
        if metric.key == MASS_PER_AREA_KEY:
            assert metric.unit == "kg/m2", metric.key
            continue
        assert metric.unit == "m3/m3", metric.key


def test_smap_surface_metrics_span_both_collections():
    """The product was split in two; both halves must be declared."""
    for metric in (SoilMoistureSurfaceMetric(), SoilMoistureSurfaceEveningMetric()):
        assert metric.dataset_ids == (SMAP_L3_CURRENT, SMAP_L3_PREVIOUS), metric.key


def test_smap_surface_metrics_reduce_at_the_native_nine_kilometres():
    """Reducing at 10 m would resample a 9 km grid and misreport it."""
    for metric in (SoilMoistureSurfaceMetric(), SoilMoistureSurfaceEveningMetric()):
        assert metric.default_scale == SMAP_NATIVE_SCALE, metric.key


# ==========================================================================
# The SMAP L3 collection split
# ==========================================================================


def test_smap_collection_selection_after_the_split():
    dataset_id, fallback = _smap_dataset_id("2024-06-01")
    assert dataset_id == SMAP_L3_CURRENT
    assert fallback is None


def test_smap_collection_selection_on_the_split_day():
    """The split day itself belongs to the newer collection."""
    dataset_id, _ = _smap_dataset_id("2023-12-04")
    assert dataset_id == SMAP_L3_CURRENT


def test_smap_collection_selection_before_the_split():
    dataset_id, fallback = _smap_dataset_id("2020-06-01")
    assert dataset_id == SMAP_L3_PREVIOUS
    assert fallback is None


def test_smap_collection_selection_one_day_before_the_split():
    dataset_id, _ = _smap_dataset_id("2023-12-03")
    assert dataset_id == SMAP_L3_PREVIOUS


def test_smap_collections_have_distinct_coverage():
    """Requesting v006 before its start would return an empty set.

    An empty collection is indistinguishable from a cloud problem, so
    the date-based selection exists precisely to avoid that.
    """
    current = get_dataset(SMAP_L3_CURRENT)
    previous = get_dataset(SMAP_L3_PREVIOUS)
    assert current.available_from == "2023-12-04"
    assert previous.available_from == "2015-03-31"


def test_smap_surface_metric_uses_the_previous_collection_for_old_dates(fake_ee):
    fake_ee(
        {
            SMAP_L3_PREVIOUS: {
                "soil_moisture_am": [0.25] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2020-06-01", end_date="2020-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.provenance.source_dataset_id == SMAP_L3_PREVIOUS


def test_smap_surface_metric_uses_the_current_collection_for_new_dates(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.provenance.source_dataset_id == SMAP_L3_CURRENT


# ==========================================================================
# Band selection and the morning / evening distinction
# ==========================================================================


def test_morning_metric_reads_the_am_band():
    metric = SoilMoistureSurfaceMetric()
    assert metric.source_band == "soil_moisture_am"
    assert metric.quality_band == "retrieval_qual_flag_am"


def test_evening_metric_reads_the_pm_band():
    metric = SoilMoistureSurfaceEveningMetric()
    assert metric.source_band == "soil_moisture_pm"
    assert metric.quality_band == "retrieval_qual_flag_pm"


def test_the_two_overpasses_read_different_bands():
    """A copy-paste that left both on the AM band would be invisible."""
    morning = SoilMoistureSurfaceMetric()
    evening = SoilMoistureSurfaceEveningMetric()
    assert morning.source_band != evening.source_band
    assert morning.quality_band != evening.quality_band


def test_the_two_overpasses_are_separate_metrics():
    """They must not be averaged into a time of day that does not exist."""
    assert SoilMoistureSurfaceMetric().key != SoilMoistureSurfaceEveningMetric().key


def test_the_evening_metric_explains_why_it_is_separate():
    joined = " ".join(SoilMoistureSurfaceEveningMetric().limitations).lower()
    assert "diurnal" in joined
    assert "averag" in joined


def test_the_morning_metric_describes_the_morning_overpass():
    joined = " ".join(SoilMoistureSurfaceMetric().limitations).lower()
    assert "morning" in joined or "overnight" in joined


def test_morning_and_evening_compute_different_values(fake_ee):
    """Given unequal overpasses, the two metrics must differ."""
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30] * 5,
                "soil_moisture_pm": [0.18] * 5,
                "retrieval_qual_flag_am": [0] * 5,
                "retrieval_qual_flag_pm": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    morning = SoilMoistureSurfaceMetric().compute(context)
    evening = SoilMoistureSurfaceEveningMetric().compute(context)

    assert morning.value == pytest.approx(0.30)
    assert evening.value == pytest.approx(0.18)
    assert morning.value != evening.value


# ==========================================================================
# Units: the volume fraction must survive unchanged
# ==========================================================================


def test_soil_moisture_is_not_scaled(fake_ee):
    """SMAP stores a volume fraction directly; a scale factor would be wrong.

    Applying the Sentinel-2 reflectance factor of 0.0001 to a 0.30
    volume fraction would report 0.00003, and applying 0.1 would report
    0.03. Both are believable-looking numbers and both are wrong.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.value == pytest.approx(0.30)
    assert result.unit == "m3/m3"
    assert result.value != pytest.approx(0.00003)
    assert result.value != pytest.approx(0.03)


def test_the_smap_band_spec_declares_a_unit_scale_factor():
    spec = get_dataset(SMAP_L3_CURRENT).band("soil_moisture_am")
    assert spec.scale_factor == pytest.approx(1.0)
    assert spec.offset == pytest.approx(0.0)
    assert spec.unit == "m3/m3"


def test_the_smap_band_declares_a_physical_valid_range():
    """A value above the declared range signals an upstream problem."""
    spec = get_dataset(SMAP_L3_CURRENT).band("soil_moisture_am")
    assert spec.valid_range == (0.0, 0.6)


def test_a_volume_fraction_above_the_porosity_floor_is_warned_about(fake_ee):
    """0.75 m3/m3 is above the porosity of any mineral soil."""
    fake_ee({SMAP_L3_CURRENT: {"soil_moisture_am": [0.75] * 5}})
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.value == pytest.approx(0.75)
    assert result.warnings
    assert any("porosity" in w.lower() for w in result.warnings)


def test_a_realistic_volume_fraction_carries_no_porosity_warning(fake_ee):
    fake_ee({SMAP_L3_CURRENT: {"soil_moisture_am": [0.25] * 5}})
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert not any("porosity" in w.lower() for w in result.warnings)


def test_the_era5_layer_bands_are_declared_in_volume_fraction():
    for layer in (1, 2, 3, 4):
        spec = get_dataset(ERA5_DAILY).band(f"volumetric_soil_water_layer_{layer}")
        assert spec.unit == "m3/m3", layer


# ==========================================================================
# The SMAP retrieval quality flag
# ==========================================================================


def test_flag_zero_is_recommended_quality():
    quality = decode_smap_retrieval_quality(0)
    assert quality.bits == SMAP_RETRIEVAL_RECOMMENDED
    assert quality.is_recommended is True
    assert quality.is_usable is True
    assert quality.was_skipped is False


def test_flag_one_is_uncertain_but_usable():
    """An uncertain retrieval is still a real observation."""
    quality = decode_smap_retrieval_quality(1)
    assert quality.bits == SMAP_RETRIEVAL_UNCERTAIN
    assert quality.is_uncertain is True
    assert quality.is_usable is True
    assert quality.was_skipped is False


def test_flag_two_is_a_skipped_retrieval():
    """This is the trap: 2 is not 'worse than 1', it is 'no retrieval'."""
    quality = decode_smap_retrieval_quality(2)
    assert quality.bits == SMAP_RETRIEVAL_SKIPPED
    assert quality.was_skipped is True
    assert quality.is_usable is False


def test_flag_three_is_not_attempted():
    quality = decode_smap_retrieval_quality(3)
    assert quality.bits == SMAP_RETRIEVAL_NOT_ATTEMPTED
    assert quality.was_skipped is True
    assert quality.is_usable is False


def test_only_the_two_low_bits_matter():
    """Higher bits carry other flags and must not change usability."""
    for high_bits in (0, 4, 8, 16, 64, 128):
        recommended = decode_smap_retrieval_quality(high_bits + 0)
        skipped = decode_smap_retrieval_quality(high_bits + 2)
        assert recommended.is_recommended is True, high_bits
        assert skipped.was_skipped is True, high_bits


def test_quality_decoder_rejects_missing_input():
    """An absent flag must never be read as a good one."""
    assert decode_smap_retrieval_quality(None) is None


def test_quality_decoder_rejects_booleans():
    assert decode_smap_retrieval_quality(True) is None
    assert decode_smap_retrieval_quality(False) is None


def test_quality_decoder_rejects_negative_values():
    assert decode_smap_retrieval_quality(-1) is None


def test_quality_decoder_rejects_malformed_input():
    assert decode_smap_retrieval_quality("abc") is None
    assert decode_smap_retrieval_quality([]) is None


def test_the_metric_masks_on_the_skip_bit(fake_ee):
    """A flag with bit 1 set must remove the pixel, not merely downgrade it.

    The soil band and the flag band are supplied with a skipped day for
    every pixel. If the mask were ignored, that day's fill value would
    enter the statistics.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30, 0.30, 0.30],
                "retrieval_qual_flag_am": [2, 2, 2],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    # Every pixel was skipped, so nothing remains to report.
    assert result.value is None
    assert result.status == STATUS_INSUFFICIENT_DATA


def test_the_metric_keeps_uncertain_retrievals(fake_ee):
    """Flag 1 is uncertain, not skipped, and must still contribute."""
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.24, 0.24],
                "retrieval_qual_flag_am": [1, 1],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.24)


def test_the_metric_keeps_recommended_retrievals(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.22, 0.22],
                "retrieval_qual_flag_am": [0, 0],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.22)


def test_masking_actually_changes_the_value(fake_ee):
    """The skip mask must be load-bearing, not decorative.

    One day has a good retrieval at 0.30; two days were skipped and hold
    a low fill value of 0.02. If the mask works, the median of the
    retained days is 0.30. If the fill values leaked in, the median
    would be 0.02 and the field would look falsely dry.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30, 0.02, 0.02],
                "retrieval_qual_flag_am": [0, 2, 2],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.value == pytest.approx(0.30)
    assert result.value != pytest.approx(0.02)


def test_a_skipped_retrieval_is_not_read_as_a_dry_reading(fake_ee):
    """An unobserved pixel and a dry pixel are different claims.

    Every pixel was skipped, so no value exists. The fill values must
    not be published as a very dry soil.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.02, 0.02, 0.02],
                "retrieval_qual_flag_am": [2, 2, 2],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.value is None
    assert result.status == STATUS_INSUFFICIENT_DATA


def test_the_morning_and_evening_flags_are_not_interchanged(fake_ee):
    """Masking the evening metric on the morning flag would be silent."""
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30, 0.30],
                "soil_moisture_pm": [0.20, 0.20],
                # The morning retrieval is fine; the evening one was skipped.
                "retrieval_qual_flag_am": [0, 0],
                "retrieval_qual_flag_pm": [2, 2],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    morning = SoilMoistureSurfaceMetric().compute(context)
    evening = SoilMoistureSurfaceEveningMetric().compute(context)

    assert morning.status == STATUS_OK
    assert morning.value == pytest.approx(0.30)
    # The evening metric must respect its own flag, not the morning's.
    assert evening.value is None


def test_bitwise_and_on_a_float_flag_fails_like_earth_engine():
    """The fake rejects bitwise ops on float-typed bands, as EE does.

    The SMAP L3 catalogue serves the retrieval quality flag with float
    precision. Earth Engine rejects bitwise operations on float bands
    even when the values are whole numbers, and the fake must reproduce
    that contract so the regression this suite guards against is
    observable in a unit test.
    """
    flag = _FakeImage(None, "retrieval_qual_flag_am", [2.0, 1.0, 0.0])
    with pytest.raises(TypeError, match="integer only"):
        flag.bitwiseAnd(0b10)


def test_float_flag_is_cast_to_int_before_the_bit_test(fake_ee):
    """The regression: the SMAP flag band is served with float precision.

    Earth Engine serves ``retrieval_qual_flag_am`` as a float band and
    rejects ``bitwiseAnd`` on non-integer operands, which made both
    surface soil moisture metrics fail with "Bitwise operands must be
    integer only". The flag codes are whole numbers, so casting to
    integer before the bit test is a no-op on real data and keeps the
    masking semantics exactly as they were.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.30, 0.02, 0.02],
                # Float precision, exactly as the catalogue serves it.
                "retrieval_qual_flag_am": [0.0, 2.0, 2.0],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    result = SoilMoistureSurfaceMetric().compute(context)

    # The skipped days still contribute nothing, as before the cast.
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.30)


def test_float_flag_evening_metric_is_computable(fake_ee):
    """The evening overpass ships the same float-typed flag band."""
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_pm": [0.21, 0.03, 0.03],
                "retrieval_qual_flag_pm": [1.0, 2.0, 2.0],
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    result = SoilMoistureSurfaceEveningMetric().compute(context)

    # Flag 1 is an uncertain-but-real retrieval and is kept; the skipped
    # days are dropped by the same bit test after the integer cast.
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.21)


def test_the_quality_band_is_declared_in_provenance(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 4,
                "retrieval_qual_flag_am": [0] * 4,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert set(result.provenance.bands) == {
        "soil_moisture_am",
        "retrieval_qual_flag_am",
    }


def test_the_surface_metric_explains_the_flag_policy(fake_ee):
    """The masking rule must be stated, not merely implemented.

    The policy is carried as an extra limitation, which is what lands in
    the provenance record, so it is asserted there rather than only on
    the class-level limitations tuple.
    """
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    joined = " ".join(result.provenance.limitations).lower()
    assert "flag" in joined
    assert "skipped" in joined
    assert "uncertain" in joined


# ==========================================================================
# SMAP L3 is a retrieval, not a model
# ==========================================================================


def test_the_surface_metric_is_declared_a_product():
    """An agency retrieval is a product, not a raw instrument reading."""
    assert SoilMoistureSurfaceMetric().measurement_basis is MeasurementBasis.PRODUCT


def test_the_surface_metric_says_it_is_not_in_situ():
    joined = " ".join(SoilMoistureSurfaceMetric().limitations).lower()
    assert "not an in-situ measurement" in joined


def test_the_surface_metric_states_the_nine_kilometre_footprint():
    joined = " ".join(SoilMoistureSurfaceMetric().limitations).lower()
    assert "9 km" in joined


def test_the_surface_metric_states_that_it_is_not_the_root_zone():
    """The L-band signal only reaches the top few centimetres."""
    joined = " ".join(SoilMoistureSurfaceMetric().limitations).lower()
    assert "root zone" in joined


def test_the_surface_metric_states_that_frozen_ground_is_excluded():
    joined = " ".join(SoilMoistureSurfaceMetric().limitations).lower()
    assert "frozen" in joined or "thawed" in joined


# ==========================================================================
# SMAP L4 root zone — an assimilated model
# ==========================================================================


def test_l4_reads_the_root_zone_band():
    assert SoilMoistureRootZoneMetric().source_bands == ("sm_rootzone",)


def test_l4_uses_the_smap_l4_dataset():
    assert SoilMoistureRootZoneMetric().dataset_ids == (SMAP_L4,)


def test_l4_is_declared_modelled():
    """It assimilates observations into a model, so it is not a retrieval."""
    assert SoilMoistureRootZoneMetric().measurement_basis is MeasurementBasis.MODELLED


def test_l4_states_that_it_is_not_the_l3_retrieval():
    """Conflating 0-5 cm with 0-100 cm is the key confusion to prevent."""
    joined = " ".join(SoilMoistureRootZoneMetric().limitations).lower()
    assert "not the same quantity as the smap l3 retrieval" in joined
    assert "0 to 5 cm" in joined
    assert "0 to 100 cm" in joined


def test_l4_states_that_it_is_assimilated_not_measured():
    joined = " ".join(SoilMoistureRootZoneMetric().limitations).lower()
    assert "assimilated model" in joined


def test_l4_computes_a_root_zone_value(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone": [0.28] * 6}})
    result = SoilMoistureRootZoneMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.28)
    assert result.unit == "m3/m3"


def test_l4_always_carries_a_model_warning(fake_ee):
    """A modelled value must never be presented without saying so."""
    fake_ee({SMAP_L4: {"sm_rootzone": [0.28] * 6}})
    result = SoilMoistureRootZoneMetric().compute(make_context())

    assert result.warnings
    assert any("model" in w.lower() for w in result.warnings)


def test_l4_with_no_timestep_is_insufficient(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone": []}})
    result = SoilMoistureRootZoneMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_l4_with_no_valid_pixel_is_insufficient(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone": [NO_DATA] * 6}})
    result = SoilMoistureRootZoneMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_l4_band_declares_its_own_valid_range():
    """The catalogue's maximum for this product is 0.9, not 1.0."""
    spec = get_dataset(SMAP_L4).band("sm_rootzone")
    assert spec.valid_range == (0.0, 0.9)
    assert spec.unit == "m3/m3"


def test_l4_wetness_bands_are_a_different_quantity_from_the_volume_fraction():
    """Relative saturation is dimensionless and must not be read as m3/m3."""
    dataset = get_dataset(SMAP_L4)
    frozen = dataset.band("sm_rootzone")
    wetness = dataset.band("sm_rootzone_wetness")
    assert frozen.unit == "m3/m3"
    assert wetness.unit == "fraction"
    assert frozen.unit != wetness.unit


# ==========================================================================
# ERA5-Land root zone — a model field, thickness-weighted
# ==========================================================================


def test_era5_root_zone_reads_three_layers():
    assert SoilMoistureRootZoneERA5Metric().source_bands == (
        "volumetric_soil_water_layer_1",
        "volumetric_soil_water_layer_2",
        "volumetric_soil_water_layer_3",
    )


def test_era5_root_zone_excludes_the_deepest_layer():
    """Layer 4 reaches 289 cm, which is not a crop root zone."""
    assert "volumetric_soil_water_layer_4" not in (
        SoilMoistureRootZoneERA5Metric().source_bands
    )


def test_era5_root_zone_uses_the_era5_dataset():
    assert SoilMoistureRootZoneERA5Metric().dataset_ids == (ERA5_DAILY,)


def test_era5_root_zone_is_declared_modelled():
    assert (
        SoilMoistureRootZoneERA5Metric().measurement_basis
        is MeasurementBasis.MODELLED
    )


def test_the_layer_depths_match_the_catalogue():
    """0-7, 7-28, 28-100 cm, from the ERA5-Land band descriptions."""
    assert ERA5_LAYER_DEPTHS_CM[1] == (0.0, 7.0)
    assert ERA5_LAYER_DEPTHS_CM[2] == (7.0, 28.0)
    assert ERA5_LAYER_DEPTHS_CM[3] == (28.0, 100.0)
    assert ERA5_LAYER_DEPTHS_CM[4] == (100.0, 289.0)


def test_the_layer_weights_are_the_layer_thicknesses():
    metric = SoilMoistureRootZoneERA5Metric()
    assert metric.layer_weights == (7.0, 21.0, 72.0)
    assert sum(metric.layer_weights) == pytest.approx(100.0)


def test_the_root_zone_is_the_thickness_weighted_mean(fake_ee):
    """Drier subsoil must pull the profile mean down, not average flatly.

    Layer 1 is wet (0.30), layer 2 is middling (0.20), layer 3 is dry
    (0.10). A flat mean gives 0.20. The thickness-weighted mean gives
    (7*0.30 + 21*0.20 + 72*0.10) / 100 = 0.135, which is much drier.
    """
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx((7 * 0.30 + 21 * 0.20 + 72 * 0.10) / 100)
    assert result.value == pytest.approx(0.135)
    # A flat mean would be materially different, so the weighting matters.
    assert result.value != pytest.approx(0.20)


def test_the_layer_weighting_is_reported_in_provenance(fake_ee):
    """The result depends on the weights, so they must be recorded."""
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    formula = result.provenance.formula
    assert "7" in formula and "21" in formula and "72" in formula
    limitations = " ".join(result.provenance.limitations)
    assert "7 cm" in limitations or "weight" in limitations.lower()


def test_the_root_zone_metric_declares_all_three_bands(fake_ee):
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())
    assert set(result.provenance.bands) == set(
        SoilMoistureRootZoneERA5Metric().source_bands
    )


def test_the_root_zone_metric_must_say_it_is_a_model(fake_ee):
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    assert result.warnings
    joined = " ".join(result.warnings).lower()
    assert "model" in joined


def test_the_root_zone_metric_states_irrigation_is_not_represented():
    joined = " ".join(SoilMoistureRootZoneERA5Metric().limitations).lower()
    assert "irrigation" in joined


def test_the_root_zone_metric_states_it_is_not_a_measurement():
    joined = " ".join(SoilMoistureRootZoneERA5Metric().limitations).lower()
    assert "not a measurement" in joined


def test_the_root_zone_metric_warns_that_it_differs_from_the_surface_value():
    joined = " ".join(SoilMoistureRootZoneERA5Metric().limitations).lower()
    assert "different quantity" in joined or "must not be compared" in joined


def test_the_root_zone_metric_with_no_days_is_insufficient(fake_ee):
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [],
                "volumetric_soil_water_layer_2": [],
                "volumetric_soil_water_layer_3": [],
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_the_root_zone_metric_survives_one_missing_layer(fake_ee):
    """A partially available profile must use what it has, not fail.

    Layers 1 and 3 are present, layer 2 is not. The weighted mean is
    taken over the layers that returned a value, renormalised by their
    combined thickness.
    """
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [NO_DATA] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    assert result.status == STATUS_OK
    expected = (7 * 0.30 + 72 * 0.10) / (7 + 72)
    assert result.value == pytest.approx(expected)


def test_the_root_zone_metric_with_no_usable_layer_is_insufficient(fake_ee):
    fake_ee(
        {
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [NO_DATA] * 5,
                "volumetric_soil_water_layer_2": [NO_DATA] * 5,
                "volumetric_soil_water_layer_3": [NO_DATA] * 5,
            }
        }
    )
    result = SoilMoistureRootZoneERA5Metric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


# ==========================================================================
# Relative saturation / wetness — dimensionless, and not volumetric water
# ==========================================================================


def test_wetness_reads_the_root_zone_wetness_band():
    assert SoilMoistureWetnessMetric().source_bands == ("sm_rootzone_wetness",)


def test_wetness_uses_the_smap_l4_dataset():
    assert SoilMoistureWetnessMetric().dataset_ids == (SMAP_L4,)


def test_wetness_is_dimensionless_not_a_volume_fraction():
    """The central distinction this metric exists to preserve."""
    metric = SoilMoistureWetnessMetric()
    assert metric.unit == "fraction"
    assert metric.unit != "m3/m3"


def test_wetness_is_declared_modelled():
    assert SoilMoistureWetnessMetric().measurement_basis is MeasurementBasis.MODELLED


def test_wetness_band_is_declared_as_a_fraction_in_the_registry():
    spec = get_dataset(SMAP_L4).band("sm_rootzone_wetness")
    assert spec.unit == "fraction"
    assert spec.scale_factor == pytest.approx(1.0)
    assert spec.valid_range == (0.0, 1.0)


def test_wetness_band_differs_from_the_volumetric_band():
    """The two bands are different quantities and must not be conflated."""
    dataset = get_dataset(SMAP_L4)
    wetness = dataset.band("sm_rootzone_wetness")
    volumetric = dataset.band("sm_rootzone")
    assert wetness.unit != volumetric.unit
    assert wetness.valid_range != volumetric.valid_range


def test_wetness_computes_a_dimensionless_value(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.42] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.42)
    assert result.unit == "fraction"


def test_wetness_is_not_scaled(fake_ee):
    """A 0 to 1 relative saturation must pass through unchanged.

    Applying the SoilGrids 0.001 factor, or any other, would collapse a
    meaningful 0.42 to 0.00042.
    """
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.42] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.value == pytest.approx(0.42)
    assert result.value != pytest.approx(0.00042)


def test_wetness_never_exceeds_one(fake_ee):
    """The value stays within the band's declared 0 to 1 range."""
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.99] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())
    assert 0.0 <= result.value <= 1.0


def test_wetness_zero_is_a_real_value_not_missing_data(fake_ee):
    """A completely air-dry soil is an observation, not an absence."""
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.0] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


def test_wetness_one_is_a_real_value(fake_ee):
    """Full saturation is an observation."""
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [1.0] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(1.0)


def test_wetness_warns_that_it_is_not_volumetric(fake_ee):
    """A caller must be told not to read the number as m3/m3."""
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.42] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    joined = " ".join(result.warnings).lower()
    assert "relative saturation" in joined
    assert "not volumetric" in joined


def test_wetness_provenance_states_no_conversion_applied(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.42] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    limitations = " ".join(result.provenance.limitations).lower()
    assert "no conversion" in limitations


def test_wetness_provenance_records_the_declined_soilgrids_derivation(fake_ee):
    """The decision not to force a SoilGrids normalisation is recorded."""
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [0.42] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    limitations = " ".join(result.provenance.limitations).lower()
    assert "soilgrids" in limitations


def test_wetness_records_the_declined_derivation_on_the_class():
    """It must also be visible without running a computation."""
    joined = " ".join(SoilMoistureWetnessMetric().limitations).lower()
    assert "soilgrids" in joined
    assert "declined" in joined or "deliberately" in joined


def test_wetness_states_the_scale_is_soil_specific():
    """The 0 to 1 scale is per-soil, so cross-location comparison is limited."""
    joined = " ".join(SoilMoistureWetnessMetric().limitations).lower()
    assert "per soil" in joined or "for this soil" in joined


def test_wetness_with_no_timestep_is_insufficient(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": []}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_wetness_with_no_valid_pixel_is_insufficient(fake_ee):
    fake_ee({SMAP_L4: {"sm_rootzone_wetness": [NO_DATA] * 6}})
    result = SoilMoistureWetnessMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_wetness_and_volumetric_root_zone_are_distinct_metrics(fake_ee):
    """Same dataset, different band, different quantity, different unit."""
    fake_ee(
        {
            SMAP_L4: {
                "sm_rootzone": [0.28] * 6,
                "sm_rootzone_wetness": [0.42] * 6,
            }
        }
    )
    volumetric = SoilMoistureRootZoneMetric().compute(make_context())
    wetness = SoilMoistureWetnessMetric().compute(make_context())

    assert volumetric.unit != wetness.unit
    assert volumetric.value != wetness.value
    assert volumetric.metric_key != wetness.metric_key


# ==========================================================================
# Insufficient data discipline
# ==========================================================================


def test_no_smap_scene_is_insufficient_not_zero(fake_ee):
    """A dry soil and an unobserved soil are different claims."""
    fake_ee({SMAP_L3_CURRENT: {"soil_moisture_am": []}})
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_a_genuine_zero_is_reported_as_zero(fake_ee):
    """Zero soil water is physically possible and is real data."""
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.0] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


def test_the_insufficient_message_explains_the_frozen_ground_case(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 5,
                "retrieval_qual_flag_am": [2] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    message = (result.message or "").lower()
    assert "frozen" in message or "skipped" in message


def test_insufficient_results_never_carry_a_value(fake_ee):
    """Emptying each dataset in turn must never yield zero."""
    for dataset_id, band in (
        (SMAP_L3_CURRENT, "soil_moisture_am"),
        (SMAP_L4, "sm_rootzone"),
        (ERA5_DAILY, "volumetric_soil_water_layer_1"),
    ):
        fake_ee({dataset_id: {band: []}})
        for metric in SOIL_METRICS:
            try:
                result = metric.compute(
                    make_context(start_date="2024-06-01", end_date="2024-06-30")
                )
            except KeyError:
                # The sparse fixture does not hold this metric's band.
                continue
            if result.status == STATUS_INSUFFICIENT_DATA:
                assert result.value is None, f"{metric.key} via {band}"


def test_a_metric_reading_an_undeclared_band_fails_loudly(monkeypatch):
    """A wrong band name must raise, not return a plausible number."""
    fake = FakeEE({SMAP_L3_CURRENT: {"soil_moisture_pm": [0.2] * 4}})
    # Only the PM band exists, but the flag band is also missing, so a
    # metric that needs it must fail rather than invent a value.
    for name in ("ImageCollection", "Reducer", "Filter"):
        monkeypatch.setattr(f"ee.{name}", getattr(fake, name))

    with pytest.raises(KeyError):
        SoilMoistureSurfaceMetric().compute(
            make_context(start_date="2024-06-01", end_date="2024-06-30")
        )


# ==========================================================================
# Cross-cutting provenance discipline
# ==========================================================================


def test_every_soil_metric_carries_provenance(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 5,
                "soil_moisture_pm": [0.20] * 5,
                "retrieval_qual_flag_am": [0] * 5,
                "retrieval_qual_flag_pm": [0] * 5,
            },
            SMAP_L4: {
                "sm_rootzone": [0.28] * 5,
                "sm_rootzone_wetness": [0.42] * 5,
            },
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            },
            GLDAS_NOAH: {
                "RootMoist_inst": [150.0] * 5,
            },
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    for metric in SOIL_METRICS:
        result = metric.compute(context)
        assert result.provenance is not None, metric.key
        assert result.provenance.source_dataset_id, metric.key
        assert result.provenance.formula, metric.key


def test_no_soil_metric_publishes_a_value_without_provenance(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {"soil_moisture_am": [0.25] * 5},
            SMAP_L4: {
                "sm_rootzone": [0.28] * 5,
                "sm_rootzone_wetness": [0.42] * 5,
            },
            ERA5_DAILY: {
                "volumetric_soil_water_layer_1": [0.30] * 5,
                "volumetric_soil_water_layer_2": [0.20] * 5,
                "volumetric_soil_water_layer_3": [0.10] * 5,
            },
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")

    for metric in SOIL_METRICS:
        try:
            result = metric.compute(context)
        except KeyError:
            continue
        if result.value is not None:
            assert result.provenance is not None, metric.key


def test_every_soil_metric_declares_a_native_resolution_caveat():
    for metric in SOIL_METRICS:
        joined = " ".join(metric.limitations).lower()
        assert "km" in joined, metric.key


def test_no_soil_metric_claims_to_diagnose_a_condition():
    """Soil moisture is not a diagnosis of anything."""
    forbidden_claims = (
        "detect disease",
        "diagnose disease",
        "identify disease",
        "detect pest",
        "diagnose pest",
        "nutrient deficiency",
    )
    for metric in SOIL_METRICS:
        text = " ".join(
            list(metric.limitations)
            + [metric.description, getattr(metric, "notes", "") or ""]
        ).lower()
        for phrase in forbidden_claims:
            assert phrase not in text, f"{metric.key} claims {phrase!r}"


def test_metric_metadata_serialises():
    for metric in SOIL_METRICS:
        payload = metric.metadata()
        assert isinstance(payload, dict)
        assert payload["key"] == metric.key
        assert payload["unit"] == metric.unit
        assert payload["domain"] == MetricDomain.SOIL


def test_every_soil_metric_can_attempt_a_recent_period():
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    for metric in SOIL_METRICS:
        can_attempt, reason = metric.can_attempt(context)
        assert can_attempt, f"{metric.key}: {reason}"


def test_the_soil_module_does_not_convert_between_quantity_families():
    """A structural guard on the module's central promise.

    The module never converts kg/m2 to m3/m3 or mm, because doing so
    needs a layer thickness and a density that the satellite record does
    not supply. Every metric therefore reports a volume fraction, an
    explicitly dimensionless relative saturation, or — for the one product
    that publishes a mass per unit area — that mass per unit area under
    its own unit label. Depth units are still forbidden outright: nothing
    here produces one.
    """
    permitted = {"m3/m3", "fraction", "kg/m2"}
    for metric in SOIL_METRICS:
        assert metric.unit in permitted, metric.key
        # No depth unit may appear anywhere in this module's output.
        assert metric.unit not in {"mm", "cm", "m"}, metric.key


def test_exactly_one_soil_metric_is_a_mass_per_unit_area():
    """The exception is singular and named, not a general hole.

    If a second metric started reporting kg/m2, the unit guard above would
    still pass while the module's promise quietly eroded. This pins the
    count.
    """
    mass_per_area = [m.key for m in SOIL_METRICS if m.unit == "kg/m2"]
    assert mass_per_area == [MASS_PER_AREA_KEY]


def test_the_mass_per_area_metric_is_never_labelled_as_a_volume_fraction():
    """The one metric whose unit differs must be unambiguous about it.

    Its unit, its description, its limitations and its provenance text all
    have to say kg/m2, and none of them may present it as an m3/m3 value.
    """
    metric = RootZoneSoilMoistureGLDASMetric()
    assert metric.unit == "kg/m2"

    described = " ".join((
        metric.description,
        *metric.limitations,
    )).lower()
    assert "kg/m2" in described
    assert "not a volume fraction" in described
    assert "m3/m3" in described


def test_the_wetness_metric_is_dimensionless():
    """Relative saturation is not volumetric water content."""
    metric = SoilMoistureWetnessMetric()
    assert metric.unit == "fraction"
    assert metric.unit != "m3/m3"


def test_quality_is_reported_from_coverage(fake_ee):
    fake_ee(
        {
            SMAP_L3_CURRENT: {
                "soil_moisture_am": [0.25] * 5,
                "retrieval_qual_flag_am": [0] * 5,
            }
        }
    )
    context = make_context(start_date="2024-06-01", end_date="2024-06-30")
    result = SoilMoistureSurfaceMetric().compute(context)

    assert result.provenance.quality_level is not None
    assert result.provenance.quality_level in set(QualityLevel)


# ==========================================================================
# GLDAS-2.1 root zone metric — the mass-per-unit-area exception
#
# This metric closes the deferral recorded when the water and soil moisture
# engine was first built: the product publishes a water mass per unit area
# (kg/m2) whereas every other soil metric publishes a volume fraction. The
# decision taken is the "separate unit label" branch — publish the product's
# own unit and never convert. The conversion branch was rejected because the
# catalogue does not document the root zone layer thickness.
# ==========================================================================


def test_gldas_metric_is_published_in_kg_per_m2():
    assert RootZoneSoilMoistureGLDASMetric().unit == "kg/m2"


def test_gldas_metric_is_declared_modelled_not_measured():
    """GLDAS-2.1 is open-loop: no observation is assimilated."""
    metric = RootZoneSoilMoistureGLDASMetric()
    assert metric.measurement_basis is MeasurementBasis.MODELLED
    assert metric.measurement_basis is not MeasurementBasis.DIRECT
    assert metric.measurement_basis is not MeasurementBasis.PRODUCT


def test_gldas_metric_declares_the_verified_dataset():
    assert RootZoneSoilMoistureGLDASMetric().dataset_ids == (GLDAS_NOAH,)


def test_gldas_metric_reads_only_the_root_zone_band():
    metric = RootZoneSoilMoistureGLDASMetric()
    assert metric.source_bands == ("RootMoist_inst",)
    assert get_dataset(GLDAS_NOAH).has_band("RootMoist_inst")


def test_gldas_metric_reads_no_retrieval_quality_flag():
    """The SMAP skip-bit mask does not apply to a model field.

    The GLDAS asset publishes no retrieval quality flag, and applying the
    SMAP mask logic here would be meaningless. This pins that no flag band
    is read.
    """
    metric = RootZoneSoilMoistureGLDASMetric()
    for band in metric.source_bands:
        assert "flag" not in band.lower()


def test_gldas_metric_reduces_at_the_native_scale():
    """Reducing at 10 m would resample a 27.8 km grid and misreport it."""
    assert GLDAS_NATIVE_SCALE == 27830
    assert RootZoneSoilMoistureGLDASMetric().default_scale == GLDAS_NATIVE_SCALE


def test_gldas_metric_computes_the_period_mean_of_the_band(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [100.0, 200.0, 300.0]}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(200.0)
    assert result.unit == "kg/m2"


def test_gldas_metric_applies_no_conversion_to_a_volume_fraction(fake_ee):
    """The load-bearing check of this metric's decision.

    A 200 kg/m2 root zone value would become 0.2 if it were divided by a
    one-metre layer and the density of water. The metric must instead
    publish the product's own number under its own unit.
    """
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [200.0]}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(200.0)
    assert result.value != pytest.approx(0.2)
    assert result.unit == "kg/m2"
    assert result.unit != "m3/m3"


def test_gldas_metric_provenance_carries_the_unit_and_the_dataset(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0]}})

    provenance = RootZoneSoilMoistureGLDASMetric().compute(make_context()).provenance

    assert provenance.source_dataset_id == GLDAS_NOAH
    assert provenance.unit == "kg/m2"
    assert "RootMoist_inst" in provenance.bands
    assert provenance.measurement_basis is MeasurementBasis.MODELLED



def test_gldas_provenance_states_that_no_conversion_was_applied(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0]}})

    provenance = RootZoneSoilMoistureGLDASMetric().compute(make_context()).provenance
    joined = " ".join(provenance.limitations).lower()

    assert "no conversion" in joined
    assert "kg/m2" in joined
    assert "m3/m3" in joined
    assert "layer thickness" in joined


def test_gldas_provenance_carries_the_citation(fake_ee):
    """A number without a source is a guess; the citation is the source."""
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0]}})

    provenance = RootZoneSoilMoistureGLDASMetric().compute(make_context()).provenance

    assert "Rodell" in provenance.citation
    assert "Global Land Data Assimilation System" in provenance.citation


def test_gldas_metric_always_warns_that_it_is_a_model(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0]}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())
    joined = " ".join(result.warnings).lower()

    assert any("model" in w.lower() for w in result.warnings)
    assert "open-loop" in joined


def test_gldas_metric_always_warns_about_the_unit(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0]}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())
    joined = " ".join(result.warnings).lower()

    assert "kg/m2" in joined
    assert "not m3/m3" in joined


def test_gldas_metric_with_no_timestep_is_insufficient(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": []}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_gldas_metric_with_no_valid_pixel_is_insufficient(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [NO_DATA] * 4}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_gldas_metric_never_reports_zero_for_missing_data(fake_ee):
    """A dry root zone and an unobserved one are different claims."""
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": []}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.value is None
    assert result.value != 0.0


def test_gldas_metric_reports_a_negative_value_without_clamping(fake_ee):
    """A negative water mass is impossible, so it is flagged, not hidden.

    Clamping it to zero would silently invent a completely dry root zone.
    """
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [-10.0]}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(-10.0)
    assert any("negative" in w.lower() for w in result.warnings)


def test_gldas_metric_reports_quality(fake_ee):
    fake_ee({GLDAS_NOAH: {"RootMoist_inst": [150.0] * 5}})

    result = RootZoneSoilMoistureGLDASMetric().compute(make_context())

    assert result.provenance.quality_level is not None
    assert result.provenance.quality_level in set(QualityLevel)



def test_gldas_metric_reports_the_persian_label():
    metric = RootZoneSoilMoistureGLDASMetric()
    assert any("\u0600" <= char <= "\u06ff" for char in metric.display_name_fa)


def test_gldas_metric_is_not_flagged_as_a_proxy():
    """A model is modelled; it is not a proxy for a measurement."""
    metadata = RootZoneSoilMoistureGLDASMetric().metadata()

    assert metadata["available"] is True
    assert metadata["is_proxy"] is False
    assert metadata["measurement_basis"] == "modelled"
    assert metadata["dataset_ids"] == [GLDAS_NOAH]
    assert metadata["unit"] == "kg/m2"


def test_gldas_metric_is_registrable_and_appears_in_the_catalog():
    register_metrics(SOIL_METRICS)
    from app.services.agriculture.catalog import catalog, metric_keys

    assert MASS_PER_AREA_KEY in metric_keys()
    entry = next(
        e for e in catalog()["metrics"] if e["key"] == MASS_PER_AREA_KEY
    )
    assert entry["dataset_ids"] == [GLDAS_NOAH]
    assert entry["unit"] == "kg/m2"


def test_gldas_metric_refuses_a_request_before_its_coverage():
    """GLDAS-2.1 starts in 2000; a 1999 request cannot be served."""
    context = make_context(start_date="1999-06-01", end_date="1999-06-30")

    can_attempt, reason = RootZoneSoilMoistureGLDASMetric().can_attempt(context)

    assert can_attempt is False
    assert reason == "outside_temporal_coverage"


def test_gldas_dataset_records_that_it_is_open_loop():
    """The single most important caveat about this product."""
    joined = " ".join(get_dataset(GLDAS_NOAH).caveats).lower()
    assert "open-loop" in joined
    assert "assimilates no soil moisture observations" in joined


def test_gldas_dataset_records_the_conversion_requirement():
    """Why the value is published in kg/m2 rather than converted."""
    joined = " ".join(get_dataset(GLDAS_NOAH).caveats).lower()
    assert "m3/m3" in joined
    assert "thickness" in joined
    assert "density of water" in joined


def test_gldas_band_declares_no_estimated_range_as_a_validity_filter():
    """The catalogue's range for this band is flagged *estimated*.

    Using it as a filter would reject a genuine near-zero value, because
    the estimated minimum is 2 kg/m2 rather than 0.
    """
    band = get_dataset(GLDAS_NOAH).band("RootMoist_inst")
    assert band.valid_range is None

    joined = " ".join(get_dataset(GLDAS_NOAH).caveats).lower()
    assert "estimated" in joined
    assert "not used as a validity filter" in joined


def test_gldas_band_is_not_scaled():
    """The asset serves physical kg/m2; no scale factor may be applied."""
    band = get_dataset(GLDAS_NOAH).band("RootMoist_inst")
    assert band.scale_factor == 1.0
    assert band.offset == 0.0
    assert band.unit == "kg/m2"

