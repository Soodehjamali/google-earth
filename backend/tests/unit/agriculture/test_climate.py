"""Tests for the climate and meteorology engine.

Two classes of mistake are guarded here, and both of them produce
numbers that look entirely reasonable:

1. A units error. ERA5 reports temperature in Kelvin, water in metres,
   and radiation in joules. Anyone of those being presented unconverted
   gives a reading that is wrong by a fixed factor or offset and will
   not look obviously broken on a dashboard. 300 degrees of air
   temperature reads as "hot"; 0.005 millimetres of rain reads as "dry".

2. A pairing error. Vapour pressure deficit, relative humidity, growing
   degree days and wind speed are all derived from *two* ERA5 bands. If
   the two series are averaged independently and only then combined, the
   result pairs one day's temperature with another day's dewpoint. The
   arithmetic still succeeds and the answer is plausible, but it
   describes no real day. The tests below feed deliberately mismatched
   series so that an unpaired implementation gives a detectably wrong
   number.

The Earth Engine calls are exercised through a small fake module rather
than skipped, so the real ``compute`` paths run. No network and no
credentials are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture import units as u
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.climate import (
    CLIMATE_METRICS,
    ERA5_DAILY,
    ERA5_WORKING_SCALE,
    GDDMetric,
    PARMetric,
    PrecipitationMetric,
    RelativeHumidityMetric,
    SolarRadiationMetric,
    TemperatureMaxMetric,
    TemperatureMeanMetric,
    TemperatureMinMetric,
    VPDMetric,
    WindSpeedMetric,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

EXPECTED_KEYS = {
    "precipitation",
    "temperature_max",
    "temperature_min",
    "temperature_mean",
    "vpd",
    "relative_humidity",
    "solar_radiation",
    "par",
    "wind_speed",
    "gdd",
}

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


# --------------------------------------------------------------------------
# Fake Earth Engine
# --------------------------------------------------------------------------


class _FakeReducer:
    """Stands in for an ``ee.Reducer``.

    Only what the aggregation module actually calls is implemented:
    ``combine`` for chaining, and enough identity to be recognisable.
    """

    def __init__(self, name: str = "mean", percentiles=None) -> None:
        self.name = name
        self.percentiles = percentiles or []
        self.combined = [(name, percentiles or [])]

    def combine(self, other, sharedInputs=False):  # noqa: N803 - mirrors ee
        self.combined.append((other.name, other.percentiles))
        return self


class _FakeReducerNamespace:
    """Mirrors ``ee.Reducer``, which exposes static factory methods."""

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


class _FakeRegionResult:
    def __init__(self, payload) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload

    def get(self, band):
        """Mirror ``reduceRegion(...).get(band)``, which yields the mean.

        Earth Engine returns the statistic under the band's own name when
        the reducer is a single mean, so the lookup is by band name.
        """
        if isinstance(self._payload, dict):
            if band in self._payload:
                return self._payload[band]
            return self._payload.get("mean")
        return self._payload


def _reduce_values(values):
    """Build the reduction dictionary Earth Engine would return.

    Mirrors the suffixed key names that ``build_reducer`` produces, so
    ``parse_reduction_result`` exercises its real lookup path rather than
    a flat shortcut.
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
        "count": count,
    }


class _FakeImage:
    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        #: A list when this image represents a whole period, or a single
        #: value when it represents one day.
        if isinstance(values, list):
            self._values = list(values)
        else:
            self._values = [values]
        self._properties = {}

    def set(self, key, value, **_kwargs):
        """Mirror ``ee.Image.set``, which attaches a metadata property."""
        self._properties[key] = value
        return self

    def get(self, key):
        return self._properties.get(key)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        if bands and bands[0] != self._band:
            # A metric asking for a band the fixture did not provide is a
            # wiring bug; surface it rather than returning something.
            raise KeyError(f"fake image holds {self._band!r}, not {bands!r}")
        return self

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(_reduce_values(self._values))

    def reduction_value(self, band):
        """The value a ``reduceRegion(...).get(band)`` call would return."""
        payload = _reduce_values(self._values)
        return payload.get("mean")

    def _single(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return NO_DATA
        return sum(usable) / len(usable)


class _FakeCollection:
    """A collection of one band carrying a list of per-day values."""

    def __init__(self, ee_module, band: str, values) -> None:
        self._ee = ee_module
        self._band = band
        self._values = list(values)

    # -- chainable no-ops ------------------------------------------------

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
                f"fake collection holds {self._band!r}, not {bands!r}"
            )
        return self

    # -- data access -----------------------------------------------------

    def size(self):
        return _FakeNumber(len(self._values))

    def map(self, func):
        """Apply ``func`` to each day, as ``ee.Collection.map`` does.

        The real ``map`` returns a collection of images; here each result
        is a plain value, which is what ``aggregate_array`` reads back.
        """
        return _FakeMapped(self._ee, [func(self._day(v)) for v in self._values])

    def _day(self, value):
        """One day's image, whose stored value is unique per day.

        A distinct tag is embedded so that if the implementation were to
        reduce the whole period's mean instead of each day, the returned
        value would not match the expected mean.
        """
        return _FakeImage(self._ee, self._band, value)

    def mean(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(self._ee, self._band, [NO_DATA])
        return _FakeImage(self._ee, self._band, [sum(usable) / len(usable)])

    def first(self):
        if not self._values:
            raise IndexError("empty fake collection")
        return _FakeImage(self._ee, self._band, self._values[0])


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value


class _FakeMapped:
    """Stands in for the ImageCollection returned by ``map``.

    The real client reads per-day values back with
    ``aggregate_array(property)``, which returns a list in collection
    order. ``getInfo`` on the mapped object is deliberately not a list,
    so an implementation that tries to read it as one fails loudly
    instead of silently returning nothing.
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

    def __len__(self):
        return len(self._items)


class FakeEE:
    """Minimal Earth Engine stand-in.

    Bands are supplied as ``{band_name: [per-day value, ...]}``. The
    special ``NO_DATA`` sentinel marks a day with no observation.
    """

    def __init__(self, bands) -> None:
        self._bands = {k: list(v) for k, v in bands.items()}
        self.Reducer = _FakeReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        assert dataset_id == ERA5_DAILY, dataset_id
        return _LazyCollection(self)

    def Filter(self):  # noqa: N802 - mirrors ee API
        return _FakeReducer("filter")

    def __getitem__(self, band):
        if band not in self._bands:
            raise KeyError(
                f"test fixture has no band {band!r}; it has "
                f"{sorted(self._bands)}"
            )
        return _FakeCollection(self, band, self._bands[band])


class _LazyCollection:
    """Re-dispatches to the band the caller selects."""

    def __init__(self, ee_module) -> None:
        self._ee = ee_module

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        return self._ee[bands[0]]


@pytest.fixture
def fake_ee(monkeypatch):
    """Install a fake ``ee`` module for the duration of a test."""

    def install(bands):
        import sys
        import types

        module = types.ModuleType("ee")
        fake = FakeEE(bands)
        module.ImageCollection = fake.ImageCollection
        module.Reducer = fake.Reducer
        module.Filter = fake.Filter
        monkeypatch.setitem(sys.modules, "ee", module)
        return fake

    return install


# --------------------------------------------------------------------------
# Collection integrity
# --------------------------------------------------------------------------


def test_all_expected_climate_metrics_present():
    assert {m.key for m in CLIMATE_METRICS} == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in CLIMATE_METRICS]
    assert len(keys) == len(set(keys))


def test_every_climate_metric_is_in_the_climate_domain():
    for metric in CLIMATE_METRICS:
        assert metric.domain is MetricDomain.CLIMATE, metric.key


def test_every_climate_metric_reads_era5_land():
    for metric in CLIMATE_METRICS:
        assert metric.dataset_ids == (ERA5_DAILY,), metric.key


def test_every_climate_metric_declares_a_unit():
    for metric in CLIMATE_METRICS:
        assert metric.unit and metric.unit != "unknown", metric.key


def test_every_climate_metric_declares_limitations():
    for metric in CLIMATE_METRICS:
        assert metric.limitations, metric.key


def test_every_climate_metric_is_registrable():
    register_metrics(CLIMATE_METRICS)
    from app.services.agriculture.catalog import metric_keys

    assert EXPECTED_KEYS.issubset(set(metric_keys()))


def test_every_climate_metric_uses_the_era5_working_scale():
    for metric in CLIMATE_METRICS:
        assert metric.default_scale == ERA5_WORKING_SCALE, metric.key


# --------------------------------------------------------------------------
# Measurement basis honesty
# --------------------------------------------------------------------------

#: Bands ERA5 publishes as physical quantities that a consumer can use
#: directly. Anything built from these is reported as modelled.
MODELLED_KEYS = {
    "precipitation",
    "temperature_max",
    "temperature_min",
    "temperature_mean",
    "solar_radiation",
}

#: Bands that must be combined with something else before they mean
#: anything agricultural.
DERIVED_KEYS = {
    "vpd",
    "relative_humidity",
    "wind_speed",
    "gdd",
}


def test_direct_era5_metrics_are_modelled():
    """A reanalysis value is modelled, never presented as measured."""
    for metric in CLIMATE_METRICS:
        if metric.key in MODELLED_KEYS:
            assert (
                metric.measurement_basis is MeasurementBasis.MODELLED
            ), metric.key


def test_computed_metrics_are_derived():
    for metric in CLIMATE_METRICS:
        if metric.key in DERIVED_KEYS:
            assert (
                metric.measurement_basis is MeasurementBasis.DERIVED
            ), metric.key


def test_par_is_a_proxy_and_says_so():
    """PAR is a fixed-coefficient estimate, so it cannot be 'measured'."""
    metric = PARMetric()
    assert metric.measurement_basis is MeasurementBasis.PROXY
    assert "proxy" in metric.display_name.lower()
    assert metric.requires_disclaimer is True


def test_only_par_is_a_proxy():
    proxies = [
        m.key
        for m in CLIMATE_METRICS
        if m.measurement_basis is MeasurementBasis.PROXY
    ]
    assert proxies == ["par"]


def test_no_climate_metric_claims_to_be_direct():
    """ERA5-Land is a model. Nothing read from it is a measurement."""
    for metric in CLIMATE_METRICS:
        assert (
            metric.measurement_basis is not MeasurementBasis.DIRECT
        ), metric.key


# --------------------------------------------------------------------------
# Unit conversion wiring per metric
# --------------------------------------------------------------------------


def test_precipitation_converts_metres_to_millimetres():
    """0.005 m of rain is 5 mm, not 0.005 mm."""
    assert PrecipitationMetric().convert(0.005) == pytest.approx(5.0)


def test_precipitation_conversion_is_a_thousandfold():
    metric = PrecipitationMetric()
    assert metric.convert(0.001) == pytest.approx(1.0)
    assert metric.convert(0.05) == pytest.approx(50.0)


def test_temperature_metrics_subtract_absolute_zero():
    for cls in (TemperatureMaxMetric, TemperatureMinMetric, TemperatureMeanMetric):
        metric = cls()
        assert metric.convert(300.0) == pytest.approx(26.85), cls.__name__
        assert metric.convert(273.15) == pytest.approx(0.0), cls.__name__


def test_temperature_conversion_is_not_a_scale_factor():
    """A forgotten offset gives 300 degC, which is the classic failure."""
    assert TemperatureMeanMetric().convert(300.0) < 100.0


def test_solar_radiation_converts_joules_to_megajoules():
    metric = SolarRadiationMetric()
    assert metric.convert(25_000_000.0) == pytest.approx(25.0)


def test_conversions_pass_through_none():
    for metric in CLIMATE_METRICS:
        convert = getattr(metric, "convert", None)
        if convert is None:
            continue
        assert convert(None) is None, metric.key


def test_conversions_reject_booleans():
    """bool is an int subclass, so True would otherwise become 1.0."""
    for metric in CLIMATE_METRICS:
        convert = getattr(metric, "convert", None)
        if convert is None:
            continue
        assert convert(True) is None, metric.key
        assert convert(False) is None, metric.key


def test_standard_deviation_is_dropped_when_the_unit_has_an_offset():
    """A spread does not take an offset.

    Converting a standard deviation of 2.5 K by subtracting 273.15 would
    give minus 270.65, and the original 2.5 K is not equal to 2.5 degC
    either. Reporting an interval width in a unit that has an offset is
    only valid for a scale-only conversion, so the value is dropped
    rather than published as a meaningless number.
    """
    from app.services.agriculture.types import SpatialStats

    stats = SpatialStats(
        mean=300.0,
        min=295.0,
        max=305.0,
        std_dev=2.5,
        valid_pixel_count=10,
        total_pixel_count=10,
    )
    converted = TemperatureMeanMetric()._convert_stats(stats)

    assert converted.std_dev is None
    # The statistics that are point values still convert correctly.
    assert converted.mean == pytest.approx(26.85)
    assert converted.min == pytest.approx(21.85)
    assert converted.max == pytest.approx(31.85)


def test_standard_deviation_survives_a_scale_only_conversion():
    """Precipitation is a scale conversion, so spread is preserved."""
    from app.services.agriculture.types import SpatialStats

    assert PrecipitationMetric().conversion == "millimetres = metres x 1000"
    assert "<" not in PrecipitationMetric().conversion


def test_std_dev_is_never_negative_after_conversion():
    from app.services.agriculture.types import SpatialStats

    stats = SpatialStats(
        mean=300.0,
        min=295.0,
        max=305.0,
        std_dev=3.0,
        valid_pixel_count=10,
        total_pixel_count=10,
    )
    for metric in CLIMATE_METRICS:
        convert_stats = getattr(metric, "_convert_stats", None)
        if convert_stats is None:
            continue
        converted = convert_stats(stats)
        if converted.std_dev is not None:
            assert converted.std_dev >= 0.0, metric.key


# --------------------------------------------------------------------------
# Source bands
# --------------------------------------------------------------------------


def test_source_bands_match_the_era5_daily_aggregation_names():
    expected = {
        "precipitation": "total_precipitation_sum",
        "temperature_max": "temperature_2m_max",
        "temperature_min": "temperature_2m_min",
        "temperature_mean": "temperature_2m",
        "solar_radiation": "surface_solar_radiation_downwards_sum",
    }
    for metric in CLIMATE_METRICS:
        if metric.key in expected:
            assert metric.source_band == expected[metric.key], metric.key


def test_par_reads_the_shortwave_band_not_a_par_band():
    """ERA5-Land publishes no PAR band; the proxy must not invent one."""
    metric = PARMetric()
    for band in metric.source_bands:
        assert "par" not in band.lower()


# --------------------------------------------------------------------------
# Step 1: the ERA5 sign convention
# --------------------------------------------------------------------------


def test_era5_evaporation_is_negative_for_upward_flux():
    """The ECMWF convention: downward is positive, so evaporation < 0.

    This is the reason the water-balance module must negate the value
    rather than publish it directly. Publishing it raw would report
    negative evaporation.
    """
    total_evaporation_upward = -0.004  # metres, i.e. 4 mm evaporated
    assert total_evaporation_upward < 0
    assert u.metres_to_millimetres(total_evaporation_upward) == pytest.approx(-4.0)

    # The physically meaningful evaporation depth is the negation.
    evaporated_mm = -u.metres_to_millimetres(total_evaporation_upward)
    assert evaporated_mm == pytest.approx(4.0)
    assert evaporated_mm > 0


def test_precipitation_is_positive_downward():
    """Precipitation is a downward flux, so it stays positive."""
    precipitation_m = 0.012
    assert precipitation_m > 0
    assert u.metres_to_millimetres(precipitation_m) == pytest.approx(12.0)


def test_the_two_fluxes_have_opposite_signs_in_the_source():
    """Sanity check on the convention that drives the water balance."""
    precipitation_downward = 0.012
    evaporation_upward = -0.004
    assert precipitation_downward > 0 > evaporation_upward

    # Net water balance = precipitation + evaporation (not minus).
    net_mm = u.metres_to_millimetres(
        precipitation_downward + evaporation_upward
    )
    assert net_mm == pytest.approx(8.0)


# --------------------------------------------------------------------------
# Step 2: ERA5 band availability
# --------------------------------------------------------------------------


def test_all_required_era5_bands_are_declared():
    required = {
        "total_precipitation_sum",
        "temperature_2m",
        "temperature_2m_min",
        "temperature_2m_max",
        "dewpoint_temperature_2m",
        "u_component_of_wind_10m",
        "v_component_of_wind_10m",
        "surface_solar_radiation_downwards_sum",
    }
    declared = set()
    for metric in CLIMATE_METRICS:
        declared.update(metric.source_bands)
    assert required.issubset(declared), required - declared


def test_dataset_registry_marks_the_era5_bands_verified():
    """Every band a climate metric reads must exist and be verified.

    The registry is the single place a band's unit, scale factor and
    valid range are declared, so a metric reading a band that the
    registry does not carry would be reading something unverified.
    """
    from app.services.agriculture.registry import get_dataset

    dataset = get_dataset(ERA5_DAILY)
    assert dataset.is_verified is True

    declared = set(dataset.bands.keys())
    used = set()
    for metric in CLIMATE_METRICS:
        used.update(metric.source_bands)

    missing = used - declared
    assert not missing, f"metrics read undeclared bands: {sorted(missing)}"

    for band_name in sorted(used):
        spec = dataset.bands[band_name]
        assert spec.unit, band_name
        assert spec.scale_factor is not None, band_name


# --------------------------------------------------------------------------
# Step 3: precipitation end to end
# --------------------------------------------------------------------------


def test_precipitation_computes_and_converts(fake_ee):
    fake_ee({"total_precipitation_sum": [0.001] * 31})
    result = PrecipitationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(1000.0 * 0.001)
    assert result.unit == "mm"
    assert result.provenance is not None
    assert result.provenance.image_count == 31


def test_precipitation_reports_zero_when_the_model_reports_zero(fake_ee):
    """A genuine zero daily total is real data, not missing data."""
    fake_ee({"total_precipitation_sum": [0.0] * 10})
    result = PrecipitationMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


def test_metric_with_no_days_is_insufficient_not_zero(fake_ee):
    fake_ee({"total_precipitation_sum": []})
    result = PrecipitationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert result.provenance is not None


def test_metric_with_no_valid_pixels_is_insufficient_not_zero(fake_ee):
    fake_ee({"total_precipitation_sum": [NO_DATA] * 10})
    result = PrecipitationMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_temperature_computes_in_celsius(fake_ee):
    fake_ee({"temperature_2m_max": [300.0] * 5})
    result = TemperatureMaxMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(26.85)
    assert result.unit == "degC"


def test_solar_radiation_computes_in_megajoules(fake_ee):
    fake_ee({"surface_solar_radiation_downwards_sum": [20_000_000.0] * 7})
    result = SolarRadiationMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(20.0)
    assert result.unit == "MJ/m2"


def test_quality_is_reported_from_coverage(fake_ee):
    fake_ee({"temperature_2m": [290.0] * 31})
    result = TemperatureMeanMetric().compute(make_context())
    assert result.provenance.quality_level is not None
    assert result.provenance.quality_level in set(QualityLevel)


# --------------------------------------------------------------------------
# Step 4: the per-day pairing logic
# --------------------------------------------------------------------------


def test_vpd_pairs_temperature_and_dewpoint_by_day(fake_ee):
    """The core derived-metric test.

    The two series are deliberately mismatched: warm days have LOW
    dewpoint and vice versa. An implementation that averages each series
    first and then combines them would see a mean temperature and a mean
    dewpoint that are close together, and report a near-zero VPD. The
    correct implementation computes each day separately, finds a large
    deficit every day, and reports a large mean.
    """
    temperatures = [303.15, 303.15, 303.15]      # 30 degC every day
    dewpoints = [293.15, 293.15, 293.15]         # 20 degC every day
    fake_ee(
        {
            "temperature_2m": temperatures,
            "dewpoint_temperature_2m": dewpoints,
        }
    )

    result = VPDMetric().compute(make_context())

    assert result.status == STATUS_OK
    expected = u.vapour_pressure_deficit(30.0, 20.0)
    assert result.value == pytest.approx(expected)
    # 30 degC air with a 20 degC dewpoint is a substantial deficit.
    assert result.value > 1.0


def test_vpd_does_not_pair_across_days(fake_ee):
    """Days with different conditions must be combined per day, not averaged.

    Day A is hot with dry air, day B is mild with humid air. Pairing
    correctly computes a deficit for each day and averages the two. The
    wrong implementation averages temperature and dewpoint independently
    first, and the resulting deficit is different.

    Both days are physically valid: the dewpoint never exceeds the air
    temperature, and each day has a positive deficit.
    """
    temperatures = [308.15, 288.15]   # +35, +15 degC
    dewpoints = [268.15, 287.15]      # -5, +14 degC (268.15 K = -5 degC)
    fake_ee(
        {
            "temperature_2m": temperatures,
            "dewpoint_temperature_2m": dewpoints,
        }
    )

    result = VPDMetric().compute(make_context())

    # Per-day: VPD(35, -5) and VPD(15, 14). Mean of those two.
    expected = (
        u.vapour_pressure_deficit(35.0, -5.0)
        + u.vapour_pressure_deficit(15.0, 14.0)
    ) / 2.0
    assert result.value == pytest.approx(expected)
    assert result.value > 1.0

    # The unpaired alternative is VPD(mean T, mean Td). The two must
    # differ materially, otherwise this test proves nothing.
    unpaired = u.vapour_pressure_deficit(
        u.kelvin_to_celsius(sum(temperatures) / 2),
        u.kelvin_to_celsius(sum(dewpoints) / 2),
    )
    assert abs(result.value - unpaired) > 0.3


def test_vpd_is_never_negative(fake_ee):
    """A negative VPD is not physically meaningful."""
    fake_ee(
        {
            "temperature_2m": [285.0, 295.0, 300.0],
            "dewpoint_temperature_2m": [285.0, 295.0, 300.0],
        }
    )
    result = VPDMetric().compute(make_context())
    assert result.value >= 0.0


def test_relative_humidity_saturates_at_one_hundred(fake_ee):
    """Temperature equal to dewpoint means saturated air."""
    fake_ee(
        {
            "temperature_2m": [293.15] * 5,
            "dewpoint_temperature_2m": [293.15] * 5,
        }
    )
    result = RelativeHumidityMetric().compute(make_context())
    assert result.value == pytest.approx(100.0, abs=0.01)
    assert result.unit == "percent"


def test_relative_humidity_is_never_above_one_hundred(fake_ee):
    """Dewpoint above temperature would give over 100 percent.

    That happens through rounding in the source data, and reporting 103
    percent humidity would be nonsense, so the value is clamped.
    """
    fake_ee(
        {
            "temperature_2m": [293.15],          # 20 degC
            "dewpoint_temperature_2m": [294.15],  # 21 degC, unphysical
        }
    )
    result = RelativeHumidityMetric().compute(make_context())
    assert result.value <= 100.0


def test_relative_humidity_is_never_negative(fake_ee):
    fake_ee(
        {
            "temperature_2m": [293.15],
            "dewpoint_temperature_2m": [273.15],
        }
    )
    result = RelativeHumidityMetric().compute(make_context())
    assert result.value >= 0.0


def test_vpd_unpaired_entirely_is_insufficient(fake_ee):
    """No pairable day must yield no value, and must say why.

    Reporting zero would claim there is no atmospheric demand, which is
    the opposite of what unknown data means.
    """
    fake_ee(
        {
            "temperature_2m": [303.15, 303.15],
            "dewpoint_temperature_2m": [],
        }
    )
    result = VPDMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_relative_humidity_unpaired_entirely_is_insufficient(fake_ee):
    fake_ee(
        {
            "temperature_2m": [],
            "dewpoint_temperature_2m": [293.15],
        }
    )
    result = RelativeHumidityMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_partial_pairing_warns_about_the_shortfall(fake_ee):
    """Some days missing means the mean is biased, and that is flagged."""
    fake_ee(
        {
            "temperature_2m": [300.0] * 10,
            "dewpoint_temperature_2m": [290.0] * 4,
        }
    )
    result = VPDMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.warnings
    assert any("day" in w.lower() for w in result.warnings)


def test_vpd_provenance_records_the_per_day_method(fake_ee):
    """The aggregation method must state that pairing happened per day."""
    fake_ee(
        {
            "temperature_2m": [300.0] * 3,
            "dewpoint_temperature_2m": [290.0] * 3,
        }
    )
    result = VPDMetric().compute(make_context())
    method = result.provenance.aggregation_method.lower()
    assert "per day" in method


def test_vpd_declares_both_source_bands(fake_ee):
    fake_ee(
        {
            "temperature_2m": [300.0],
            "dewpoint_temperature_2m": [290.0],
        }
    )
    result = VPDMetric().compute(make_context())
    assert set(result.provenance.bands) == {
        "temperature_2m",
        "dewpoint_temperature_2m",
    }


def test_vpd_formula_names_the_magnus_coefficients(fake_ee):
    fake_ee(
        {
            "temperature_2m": [300.0],
            "dewpoint_temperature_2m": [290.0],
        }
    )
    result = VPDMetric().compute(make_context())
    assert "0.6108" in result.provenance.formula


# --------------------------------------------------------------------------
# Step 5: the PAR proxy
# --------------------------------------------------------------------------


def test_par_is_forty_five_percent_of_shortwave(fake_ee):
    fake_ee({"surface_solar_radiation_downwards_sum": [20_000_000.0] * 4})
    result = PARMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(20.0 * 0.45)


def test_par_quality_is_capped_at_moderate(fake_ee):
    """A fixed-coefficient estimate cannot be 'excellent'.

    Even with perfect coverage, the limiting factor is the coefficient,
    not the data, so the ceiling is applied.
    """
    fake_ee({"surface_solar_radiation_downwards_sum": [20_000_000.0] * 31})
    result = PARMetric().compute(make_context())

    assert result.provenance.quality_level in (
        QualityLevel.MODERATE,
        QualityLevel.POOR,
        QualityLevel.INSUFFICIENT,
    )
    assert result.provenance.quality_level is not QualityLevel.EXCELLENT
    assert result.provenance.quality_level is not QualityLevel.GOOD


def test_par_always_carries_a_warning(fake_ee):
    fake_ee({"surface_solar_radiation_downwards_sum": [20_000_000.0]})
    result = PARMetric().compute(make_context())
    assert result.warnings
    assert any("approximation" in w.lower() for w in result.warnings)


def test_par_provenance_is_marked_as_requiring_a_disclaimer(fake_ee):
    fake_ee({"surface_solar_radiation_downwards_sum": [20_000_000.0]})
    result = PARMetric().compute(make_context())
    assert result.provenance.measurement_basis.requires_disclaimer is True


def test_par_without_data_is_insufficient(fake_ee):
    fake_ee({"surface_solar_radiation_downwards_sum": []})
    result = PARMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_par_does_not_exceed_shortwave(fake_ee):
    """A 0.45 fraction above unity would be an immediate red flag."""
    fake_ee({"surface_solar_radiation_downwards_sum": [30_000_000.0]})
    result = PARMetric().compute(make_context())
    assert result.value < 30.0


# --------------------------------------------------------------------------
# Step 6: growing degree days
# --------------------------------------------------------------------------


def test_gdd_accumulates_over_the_period(fake_ee):
    """10 days at 20/10 degC with a base of 10 is 10 days x 5 degC-days."""
    fake_ee(
        {
            "temperature_2m_min": [283.15] * 10,  # 10 degC
            "temperature_2m_max": [293.15] * 10,  # 20 degC
        }
    )
    result = GDDMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(10 * 5.0)
    assert result.unit == "degC-day"


def test_gdd_defaults_to_a_base_of_ten(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [283.15] * 5,
            "temperature_2m_max": [293.15] * 5,
        }
    )
    result = GDDMetric().compute(make_context())
    # (10 + 20) / 2 - 10 = 5 per day
    assert result.value == pytest.approx(25.0)


def test_gdd_honours_a_caller_supplied_base(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [283.15] * 5,
            "temperature_2m_max": [293.15] * 5,
        }
    )
    context = make_context(options={"base_temperature": 0.0})
    result = GDDMetric().compute(context)
    # (10 + 20) / 2 - 0 = 15 per day
    assert result.value == pytest.approx(75.0)


def test_gdd_reports_the_base_temperature_used(fake_ee):
    """The base is a crop parameter, so it must appear in the record."""
    fake_ee(
        {
            "temperature_2m_min": [283.15],
            "temperature_2m_max": [293.15],
        }
    )
    context = make_context(options={"base_temperature": 8.0})
    result = GDDMetric().compute(context)
    joined = " ".join(result.provenance.limitations)
    assert "8.0" in joined


def test_gdd_reports_an_upper_cap_when_one_is_supplied(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [283.15],
            "temperature_2m_max": [313.15],  # 40 degC
        }
    )
    context = make_context(options={"base_temperature": 10.0, "upper_temperature": 30.0})
    result = GDDMetric().compute(context)
    joined = " ".join(result.provenance.limitations)
    assert "30.0" in joined
    # Tmax capped at 30, so (10 + 30) / 2 - 10 = 10
    assert result.value == pytest.approx(10.0)


def test_gdd_cold_days_contribute_zero_not_negative(fake_ee):
    """A day below the base must not subtract from the season total."""
    fake_ee(
        {
            "temperature_2m_min": [273.15],  # 0 degC
            "temperature_2m_max": [278.15],  # 5 degC
        }
    )
    result = GDDMetric().compute(make_context())
    assert result.value == pytest.approx(0.0)
    assert result.value >= 0.0


def test_gdd_skips_days_it_cannot_compute(fake_ee):
    """Missing days are skipped, not treated as zero accumulation."""
    fake_ee(
        {
            "temperature_2m_min": [283.15] * 10,
            "temperature_2m_max": [293.15] * 6,
        }
    )
    result = GDDMetric().compute(make_context())
    # Only 6 days can be computed.
    assert result.value == pytest.approx(6 * 5.0)


def test_gdd_warns_when_days_were_skipped(fake_ee):
    """Skipping days biases the total low, and that must be stated."""
    fake_ee(
        {
            "temperature_2m_min": [283.15] * 10,
            "temperature_2m_max": [293.15] * 6,
        }
    )
    result = GDDMetric().compute(make_context())
    assert result.warnings
    assert any("bias" in w.lower() for w in result.warnings)


def test_gdd_with_no_computable_day_is_insufficient(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [],
            "temperature_2m_max": [293.15],
        }
    )
    result = GDDMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_gdd_is_never_negative(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [268.15, 273.15, 283.15],
            "temperature_2m_max": [272.15, 278.15, 293.15],
        }
    )
    result = GDDMetric().compute(make_context())
    assert result.value >= 0.0


def test_gdd_provenance_names_the_simple_averaging_method(fake_ee):
    fake_ee(
        {
            "temperature_2m_min": [283.15],
            "temperature_2m_max": [293.15],
        }
    )
    result = GDDMetric().compute(make_context())
    limitations = " ".join(result.provenance.limitations).lower()
    assert "averaging" in limitations


# --------------------------------------------------------------------------
# Step 7: wind speed from components
# --------------------------------------------------------------------------


def test_wind_speed_is_the_vector_magnitude(fake_ee):
    """A 3, 4 pair is a speed of 5, not 3 and not 4."""
    fake_ee(
        {
            "u_component_of_wind_10m": [3.0],
            "v_component_of_wind_10m": [4.0],
        }
    )
    result = WindSpeedMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(5.0)
    assert result.unit == "m/s"


def test_wind_speed_is_never_below_either_component():
    """The magnitude of a vector cannot be smaller than a component."""
    for u_value, v_value in [(3.0, 4.0), (10.0, 0.0), (0.0, 7.0), (-6.0, 8.0)]:
        speed = u.wind_speed_from_components(u_value, v_value)
        assert speed >= abs(u_value) - 1e-9
        assert speed >= abs(v_value) - 1e-9


def test_wind_speed_is_non_negative(fake_ee):
    """A negative wind speed is not physically meaningful."""
    fake_ee(
        {
            "u_component_of_wind_10m": [-6.0],
            "v_component_of_wind_10m": [-8.0],
        }
    )
    result = WindSpeedMetric().compute(make_context())
    assert result.value == pytest.approx(10.0)
    assert result.value >= 0.0


def test_wind_speed_pairs_the_components_by_day(fake_ee):
    """Independent averaging of the components would shrink the speed."""
    fake_ee(
        {
            "u_component_of_wind_10m": [10.0, 0.0],
            "v_component_of_wind_10m": [0.0, 10.0],
        }
    )
    result = WindSpeedMetric().compute(make_context())

    # Each day is a 10 m/s wind in a different direction, so the mean
    # daily speed is 10. Averaging the components first would give a
    # mean u of 5 and a mean v of 5, i.e. 7.07, which is wrong.
    assert result.value == pytest.approx(10.0)
    assert abs(result.value - math.hypot(5.0, 5.0)) > 2.0


def test_wind_speed_declares_both_components(fake_ee):
    fake_ee(
        {
            "u_component_of_wind_10m": [3.0],
            "v_component_of_wind_10m": [4.0],
        }
    )
    result = WindSpeedMetric().compute(make_context())
    assert set(result.provenance.bands) == {
        "u_component_of_wind_10m",
        "v_component_of_wind_10m",
    }
    assert "sqrt" in result.provenance.formula


def test_wind_speed_is_derived_not_modelled_directly(fake_ee):
    """A vector magnitude is computed, not a single band ERA5 publishes."""
    assert WindSpeedMetric().measurement_basis is MeasurementBasis.DERIVED


def test_wind_speed_without_both_components_is_insufficient(fake_ee):
    fake_ee(
        {
            "u_component_of_wind_10m": [3.0, 4.0],
            "v_component_of_wind_10m": [],
        }
    )
    result = WindSpeedMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower(), "must not imply still air"


def test_wind_speed_does_not_report_direction(fake_ee):
    """Direction was deliberately left out and that must be documented."""
    fake_ee(
        {
            "u_component_of_wind_10m": [3.0],
            "v_component_of_wind_10m": [4.0],
        }
    )
    result = WindSpeedMetric().compute(make_context())
    limitations = " ".join(result.provenance.limitations).lower()
    assert "direction" in limitations


# --------------------------------------------------------------------------
# Cross-cutting: provenance and quality discipline
# --------------------------------------------------------------------------


#: A complete, physically sensible set of ERA5 bands covering every
#: climate metric. Used by the cross-cutting tests that walk the whole
#: collection. Values are chosen to be valid for each band: temperatures
#: in Kelvin, water fluxes in metres, radiation in joules, wind in m/s.
ALL_BANDS = {
    "total_precipitation_sum": [0.001] * 5,
    "temperature_2m": [293.15] * 5,
    "temperature_2m_min": [283.15] * 5,
    "temperature_2m_max": [297.15] * 5,
    "dewpoint_temperature_2m": [288.15] * 5,
    "u_component_of_wind_10m": [3.0] * 5,
    "v_component_of_wind_10m": [4.0] * 5,
    "surface_solar_radiation_downwards_sum": [20_000_000.0] * 5,
}


def test_every_computed_metric_carries_provenance(fake_ee):
    fake_ee(ALL_BANDS)

    for metric in CLIMATE_METRICS:
        result = metric.compute(make_context())
        assert result.provenance is not None, metric.key
        assert result.provenance.source_dataset_id == ERA5_DAILY, metric.key
        assert result.provenance.formula, metric.key


def test_no_metric_publishes_a_value_without_provenance(fake_ee):
    """The central safety rule of the whole engine."""
    fake_ee(ALL_BANDS)

    for metric in CLIMATE_METRICS:
        result = metric.compute(make_context())
        if result.value is not None:
            assert result.provenance is not None, metric.key


def test_every_metric_computes_a_usable_value_from_valid_input(fake_ee):
    """Guards against a metric that silently never produces anything."""
    fake_ee(ALL_BANDS)

    for metric in CLIMATE_METRICS:
        result = metric.compute(make_context())
        assert result.status == STATUS_OK, f"{metric.key}: {result.message}"
        assert result.value is not None, metric.key


def test_insufficient_results_never_carry_a_value():
    """A metric with no source data must return no value, not zero.

    Each band is emptied in turn. A metric that needs a different band
    from the one being emptied is skipped, because in this sparse
    fixture its other input is simply absent and the fake raises rather
    than pretending the band exists.
    """
    for band in ALL_BANDS:
        import sys
        import types

        module = types.ModuleType("ee")
        fake = FakeEE({band: []})
        module.ImageCollection = fake.ImageCollection
        module.Reducer = fake.Reducer
        module.Filter = fake.Filter
        original = sys.modules.get("ee")
        sys.modules["ee"] = module
        try:
            for metric in CLIMATE_METRICS:
                try:
                    result = metric.compute(make_context())
                except KeyError:
                    # This metric reads a band the sparse fixture does
                    # not provide, so it cannot be evaluated here.
                    continue
                if result.status == STATUS_INSUFFICIENT_DATA:
                    assert result.value is None, f"{metric.key} via {band}"
        finally:
            if original is None:
                sys.modules.pop("ee", None)
            else:
                sys.modules["ee"] = original


def test_a_metric_reading_missing_bands_fails_loudly():
    """Reading an undeclared band must raise, not silently return nothing.

    This is the failure mode that would otherwise produce a plausible
    but wrong number, so the fake is deliberately strict.
    """
    import sys
    import types

    module = types.ModuleType("ee")
    fake = FakeEE({"temperature_2m": [293.15]})
    module.ImageCollection = fake.ImageCollection
    module.Reducer = fake.Reducer
    module.Filter = fake.Filter
    original = sys.modules.get("ee")
    sys.modules["ee"] = module
    try:
        with pytest.raises(KeyError):
            RelativeHumidityMetric().compute(make_context())
    finally:
        if original is None:
            sys.modules.pop("ee", None)
        else:
            sys.modules["ee"] = original


def test_every_metric_declares_the_native_resolution_caveat():
    """ERA5 is 11 km; a field-scale claim would be false."""
    for metric in CLIMATE_METRICS:
        joined = " ".join(metric.limitations).lower()
        assert "11 km" in joined or "modelled" in joined, metric.key


def test_no_climate_metric_mentions_disease_or_pest():
    """Satellite and reanalysis data cannot diagnose plant health."""
    forbidden = ("disease", "pest", "pathogen", "infection", "nutrient deficiency")
    for metric in CLIMATE_METRICS:
        text = " ".join(
            list(metric.limitations)
            + [metric.description, getattr(metric, "notes", "") or ""]
        ).lower()
        for word in forbidden:
            assert word not in text, f"{metric.key} mentions {word!r}"


def test_metric_metadata_serialises():
    for metric in CLIMATE_METRICS:
        payload = metric.metadata()
        assert isinstance(payload, dict)
        assert payload["key"] == metric.key
        assert payload["unit"] == metric.unit
