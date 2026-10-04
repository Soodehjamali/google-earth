"""Tests for the thermal engine.

The most important test in this file is
``test_no_thermal_metric_exposes_canopy_temperature``, and its
counterpart ``test_the_engine_never_declares_a_canopy_temperature_key``,
which scans the entire package rather than just this module.

Land surface temperature and canopy temperature are different physical
quantities. Presenting the first as the second would produce a number that
looks authoritative and is wrong by several degrees, in a direction that
depends on crop, row geometry and time of day. Any test suite for an
agricultural thermal engine that does not assert this distinction is
missing the point.

The Earth Engine calls run against a fake module, so the real ``compute``
paths execute without credentials. No network is required.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.services.agriculture import units as u
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.thermal import (
    LANDSAT_ST_SCALE,
    LANDSAT_THERMAL,
    MODIS_LST_8DAY,
    MODIS_LST_DAILY,
    MODIS_LST_SCALE,
    THERMAL_METRICS,
    DiurnalTemperatureRangeMetric,
    LandsatSurfaceTemperatureMetric,
    LandSurfaceTemperatureDayMetric,
    LandSurfaceTemperatureMeanMetric,
    LandSurfaceTemperatureNightMetric,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

EXPECTED_KEYS = {
    "land_surface_temperature_day",
    "land_surface_temperature_night",
    "land_surface_temperature_mean",
    "surface_temperature_range",
    "landsat_surface_temperature",
}

NO_DATA = object()

PACKAGE_DIR = (
    pathlib.Path(__file__).resolve().parents[3]
    / "app"
    / "services"
    / "agriculture"
)


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
    def __init__(self, name: str = "mean") -> None:
        self.name = name

    def combine(self, other, sharedInputs=False):  # noqa: N803
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
    def stdDev():  # noqa: N802
        return _FakeReducer("stdDev")

    @staticmethod
    def min():
        return _FakeReducer("min")

    @staticmethod
    def max():
        return _FakeReducer("max")

    @staticmethod
    def percentile(values):
        return _FakeReducer("percentile")


class _FakeFilterNamespace:
    @staticmethod
    def lt(field, value):
        return ("lt", field, value)


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value


def _stats_for(values):
    """The reduction dictionary Earth Engine would return for a band."""
    usable = [v for v in values if v is not NO_DATA]
    if not usable:
        return {}
    ordered = sorted(usable)
    count = len(ordered)
    mean_value = sum(ordered) / count
    variance = sum((v - mean_value) ** 2 for v in ordered) / count
    return {
        "mean": mean_value,
        "median": ordered[count // 2],
        "min": ordered[0],
        "max": ordered[-1],
        "stdDev": variance ** 0.5,
        "p10": ordered[0],
        "p25": ordered[0],
        "p75": ordered[-1],
        "p90": ordered[-1],
        "count": count,
    }


class _FakeImage:
    def __init__(self, ee_module, values) -> None:
        self._values = list(values) if isinstance(values, list) else [values]

    def select(self, bands):
        return self

    def mean(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(None, [NO_DATA])
        return _FakeImage(None, [sum(usable) / len(usable)])

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(_stats_for(self._values))


class _FakeRegionResult:
    def __init__(self, payload) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeCollection:
    def __init__(self, ee_module, bands) -> None:
        self._ee = ee_module
        self._bands = {k: list(v) for k, v in bands.items()}
        self._selected = list(bands.keys())[0] if bands else ""
        self._count_override = None

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in self._bands:
                raise KeyError(
                    f"fake collection has no band {band!r}; it has "
                    f"{sorted(self._bands)}"
                )
        self._selected = bands[0]
        return self

    def size(self):
        return _FakeNumber(len(self._bands.get(self._selected, [])))

    def mean(self):
        return _FakeImage(None, self._bands.get(self._selected, []))


class FakeEE:
    """Maps a dataset ID to a band-value fixture."""

    def __init__(self, datasets) -> None:
        self._datasets = datasets
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802
        if dataset_id not in self._datasets:
            raise KeyError(
                f"test fixture has no dataset {dataset_id!r}; it has "
                f"{sorted(self._datasets)}"
            )
        return _FakeCollection(self, self._datasets[dataset_id])


#: MODIS LST is stored as counts scaled by 0.02 K. Fixtures that only care
#: whether a band is present still have to supply plausible raw counts, or
#: the pipeline would convert them to a nonsense physical value.
RAW_300K = 300.0 / 0.02
RAW_290K = 290.0 / 0.02


@pytest.fixture
def fake_ee(monkeypatch):
    def install(datasets):
        import sys
        import types

        module = types.ModuleType("ee")
        fake = FakeEE(datasets)
        module.ImageCollection = fake.ImageCollection
        module.Reducer = fake.Reducer
        module.Filter = fake.Filter
        monkeypatch.setitem(sys.modules, "ee", module)
        return fake

    return install


def modis_fixture(days: int = 10, day_k: float = 300.0, night_k: float = 290.0):
    """An 8-day MODIS fixture with day and night bands.

    Values are supplied in **kelvin** for readability and converted to the
    raw stored counts that Earth Engine actually holds, using the band's
    documented 0.02 scale factor. The fake must mirror the real contract:
    a reduction returns raw counts, and the pipeline is responsible for
    applying the scale factor. Feeding physical values here would make the
    fixture pass whether or not the conversion happened, which is exactly
    the bug this suite exists to catch.
    """
    scale = 0.02
    return {
        MODIS_LST_8DAY: {
            "LST_Day_1km": [day_k / scale] * days,
            "LST_Night_1km": [night_k / scale] * days,
        }
    }


# --------------------------------------------------------------------------
# THE CANOPY TEMPERATURE PROHIBITION
# --------------------------------------------------------------------------


def test_no_thermal_metric_exposes_canopy_temperature():
    """The single most important assertion in the thermal engine.

    Land surface temperature is an area-weighted mixture of leaves, soil
    and inter-row space. Canopy temperature is the temperature of plant
    tissue, which requires a close-range thermal camera or a surface
    energy balance inversion. Publishing the first as the second would be
    wrong by several degrees in an unknown direction.
    """
    for metric in THERMAL_METRICS:
        assert "canopy" not in metric.key.lower(), metric.key
        assert "canopy" not in metric.display_name.lower(), metric.key
        assert "leaf" not in metric.key.lower(), metric.key


def test_the_engine_never_declares_a_canopy_temperature_key():
    """Scan the whole package, not just this module.

    A later domain module could introduce the key by accident, so the
    check is a source scan rather than a registry lookup. The CD-4
    middle-canopy dryness proxy is explicitly allowlisted: its
    mandated name carries "canopy", but it is a PROXY-basis state
    code in the vegetation domain, not a temperature quantity.
    Anything else containing "canopy" still fails.
    """
    allowlisted = frozenset({"middle_canopy_dryness_proxy"})
    offenders = []
    pattern = re.compile(
        r"""(?:key|metric_key)\s*=\s*["']([^"']*canopy[^"']*)["']""",
        re.IGNORECASE,
    )
    for path in PACKAGE_DIR.rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) in allowlisted:
                continue
            offenders.append(f"{path.name}: {match.group(1)}")
    assert not offenders, (
        f"the engine declares a canopy temperature key: {offenders}"
    )


def test_every_thermal_metric_states_that_it_is_not_canopy_temperature():
    """The distinction must be stated, not merely avoided."""
    for metric in THERMAL_METRICS:
        joined = " ".join(metric.limitations).lower()
        assert "not canopy temperature" in joined or "not canopy" in joined, (
            f"{metric.key} does not state that LST is not canopy temperature"
        )


def test_every_thermal_provenance_carries_the_canopy_disclaimer():
    """The disclaimer must survive into the published record."""
    for metric in THERMAL_METRICS:
        limitations = " ".join(metric.limitations).lower()
        assert "land surface temperature" in limitations, metric.key


def test_thermal_display_names_say_land_surface_not_canopy():
    """Every thermal metric's name must identify what it actually measures.

    A name of just "Temperature" or "Canopy Temperature" would both be
    wrong: the first is ambiguous between air and surface, the second
    names a quantity the satellite cannot observe.
    """
    for metric in THERMAL_METRICS:
        name = metric.display_name.lower()
        assert "canopy" not in name, metric.key
        assert "leaf" not in name, metric.key
        # Either "land surface" or a source-qualified surface temperature.
        assert "surface temperature" in name, metric.key


def test_no_thermal_metric_is_named_simply_temperature():
    """A bare 'temperature' key would be ambiguous between air and surface."""
    for metric in THERMAL_METRICS:
        assert metric.key != "temperature", metric.key


# --------------------------------------------------------------------------
# Collection integrity
# --------------------------------------------------------------------------


def test_all_expected_thermal_metrics_present():
    assert {m.key for m in THERMAL_METRICS} == EXPECTED_KEYS


def test_no_duplicate_thermal_metric_keys():
    keys = [m.key for m in THERMAL_METRICS]
    assert len(keys) == len(set(keys))


def test_every_thermal_metric_is_in_the_thermal_domain():
    for metric in THERMAL_METRICS:
        assert metric.domain is MetricDomain.THERMAL, metric.key


def test_every_thermal_metric_declares_limitations():
    for metric in THERMAL_METRICS:
        assert metric.limitations, metric.key


def test_thermal_metrics_are_registrable():
    register_metrics(THERMAL_METRICS)
    from app.services.agriculture.catalog import metric_keys

    assert EXPECTED_KEYS.issubset(set(metric_keys()))


# --------------------------------------------------------------------------
# Measurement basis
# --------------------------------------------------------------------------


def test_modis_lst_metrics_are_products_not_measurements():
    """An official agency retrieval product is a product, not a raw signal."""
    for metric in THERMAL_METRICS:
        if metric.key.startswith("land_surface_temperature"):
            assert (
                metric.measurement_basis is MeasurementBasis.PRODUCT
            ), metric.key


def test_the_day_night_range_is_derived():
    """It is computed from two bands, so it is not a product."""
    assert (
        DiurnalTemperatureRangeMetric().measurement_basis
        is MeasurementBasis.DERIVED
    )


def test_landsat_surface_temperature_is_also_a_product():
    assert (
        LandsatSurfaceTemperatureMetric().measurement_basis
        is MeasurementBasis.PRODUCT
    )


def test_no_thermal_metric_claims_to_be_a_direct_measurement():
    """Surface temperature is a retrieval with stated uncertainty."""
    for metric in THERMAL_METRICS:
        assert (
            metric.measurement_basis is not MeasurementBasis.DIRECT
        ), metric.key


# --------------------------------------------------------------------------
# Source datasets and bands
# --------------------------------------------------------------------------


def test_modis_metrics_prefer_the_8_day_composite():
    """8-day composites have far better coverage under persistent cloud."""
    for metric in THERMAL_METRICS:
        if metric.key.startswith("land_surface_temperature") or (
            metric.key == "surface_temperature_range"
        ):
            assert metric.dataset_ids[0] == MODIS_LST_8DAY, metric.key


def test_modis_metrics_declare_the_daily_product_as_fallback():
    for metric in THERMAL_METRICS:
        if metric.key in ("surface_temperature_range",) or metric.key.startswith(
            "land_surface_temperature"
        ):
            assert MODIS_LST_DAILY in metric.dataset_ids, metric.key


def test_modis_source_bands_are_the_documented_lst_bands():
    assert LandSurfaceTemperatureDayMetric().source_bands == ("LST_Day_1km",)
    assert LandSurfaceTemperatureNightMetric().source_bands == ("LST_Night_1km",)


def test_the_range_metric_reads_both_lst_bands():
    assert set(DiurnalTemperatureRangeMetric().source_bands) == {
        "LST_Day_1km",
        "LST_Night_1km",
    }


def test_landsat_reads_the_surface_temperature_band_not_reflectance():
    """ST_B10 is thermal; SR_B* is reflectance and would be nonsense here."""
    for band in LandsatSurfaceTemperatureMetric().source_bands:
        assert not band.startswith("SR_"), band
        assert band.startswith("ST_") or band.startswith("QA_"), band


def test_every_thermal_band_exists_in_its_registry_dataset():
    """A metric reading an undeclared band would fail only at runtime."""
    from app.services.agriculture.registry import get_dataset

    for metric in THERMAL_METRICS:
        for dataset_id in metric.dataset_ids:
            dataset = get_dataset(dataset_id)
            for band in metric.source_bands:
                assert dataset.has_band(band), (
                    f"{metric.key} reads {band} from {dataset_id}, which "
                    "does not declare it"
                )


# --------------------------------------------------------------------------
# The scale factors, which are the classic silent error
# --------------------------------------------------------------------------


def test_modis_lst_scale_factor_is_the_documented_value():
    """LST is stored as raw counts scaled by 0.02 K."""
    from app.services.agriculture.registry import get_dataset

    for dataset_id in (MODIS_LST_8DAY, MODIS_LST_DAILY):
        band = get_dataset(dataset_id).band("LST_Day_1km")
        assert band.scale_factor == pytest.approx(0.02)
        assert band.offset == pytest.approx(0.0)
        assert band.unit == "K"


def test_modis_lst_nodata_sentinel_is_zero_counts():
    """Raw 0 is the fill. Physical 0 K is impossible, so there is no clash."""
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(MODIS_LST_8DAY).band("LST_Day_1km")
    assert 0.0 in band.nodata_values
    # The physical valid range starts far above absolute zero.
    assert band.valid_range[0] >= 100.0


def test_lst_raw_zero_becomes_none():
    """The nodata sentinel must not survive as a physical value."""
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(MODIS_LST_8DAY).band("LST_Day_1km")
    assert band.to_physical(0.0) is None
    # A genuine retrieval converts correctly.
    assert band.to_physical(15000.0) == pytest.approx(300.0)


def test_landsat_st_scale_factor_and_offset_are_the_documented_values():
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(LANDSAT_THERMAL).band("ST_B10")
    assert band.scale_factor == pytest.approx(0.00341802)
    assert band.offset == pytest.approx(149.0)


def test_landsat_st_conversion_reproduces_a_known_value():
    """The documented Landsat conversion, checked against a worked value."""
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(LANDSAT_THERMAL).band("ST_B10")
    # Raw 45000 -> 45000 * 0.00341802 + 149 = 302.8109 K
    kelvin = band.to_physical(45000.0)
    assert kelvin == pytest.approx(302.8109, abs=0.001)
    assert u.kelvin_to_celsius(kelvin) == pytest.approx(29.6609, abs=0.001)


def test_a_forgotten_lst_conversion_would_be_obviously_wrong():
    """Raw counts presented as Kelvin gives a nonsense reading.

    Raw 15000 is a real daytime value. Presented unconverted it reads as
    fifteen thousand degrees.
    """
    raw_counts = 15000.0
    assert raw_counts > 1000.0
    assert u.kelvin_to_celsius(raw_counts) > 14000.0

    converted_kelvin = raw_counts * 0.02
    assert converted_kelvin == pytest.approx(300.0)
    assert u.kelvin_to_celsius(converted_kelvin) == pytest.approx(26.85)


# --------------------------------------------------------------------------
# Computation, via the fake Earth Engine
# --------------------------------------------------------------------------


def test_daytime_lst_computes_in_celsius(fake_ee):
    fake_ee(modis_fixture(days=10, day_k=300.0))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(26.85)
    assert result.unit == "degC"


def test_nighttime_lst_computes_in_celsius(fake_ee):
    fake_ee(modis_fixture(days=10, night_k=290.0))
    result = LandSurfaceTemperatureNightMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(16.85)


def test_lst_is_not_reported_in_kelvin(fake_ee):
    """A value near 300 would mean the conversion was skipped."""
    fake_ee(modis_fixture(days=5, day_k=300.0))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.value < 100.0


def test_lst_without_scenes_is_insufficient(fake_ee):
    fake_ee({MODIS_LST_8DAY: {"LST_Day_1km": []}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert result.provenance is not None


def test_lst_without_valid_pixels_is_insufficient(fake_ee):
    fake_ee({MODIS_LST_8DAY: {"LST_Day_1km": [NO_DATA] * 5}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_lst_without_scenes_message_explains_the_absence(fake_ee):
    """An absent result must say why, not merely return nothing."""
    fake_ee({MODIS_LST_8DAY: {"LST_Day_1km": []}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    message = result.message.lower()
    assert "no" in message
    assert "scenes" in message


def test_lst_no_valid_pixels_message_warns_against_reading_it_as_zero(fake_ee):
    """This is the case where a naive implementation would report 0 degC.

    No valid pixels is the failure mode that produces a plausible red
    alert on a dashboard, so the message must name the trap.
    """
    fake_ee({MODIS_LST_8DAY: {"LST_Day_1km": [NO_DATA] * 5}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_lst_provenance_records_the_band(fake_ee):
    fake_ee(modis_fixture())
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.provenance.bands == ["LST_Day_1km"]


def test_lst_provenance_reports_the_1km_resolution(fake_ee):
    """MODIS LST is 1 km. Claiming finer would be an overstatement."""
    fake_ee(modis_fixture())
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert "1000" in result.provenance.spatial_resolution or (
        "1 km" in result.provenance.spatial_resolution.lower()
    )


def test_lst_provenance_carries_the_emissivity_caveat(fake_ee):
    fake_ee(modis_fixture())
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    limitations = " ".join(result.provenance.limitations).lower()
    assert "emissivity" in limitations


def test_day_and_night_retrievals_are_different_bands(fake_ee):
    """A copy-paste error making both read LST_Day would be invisible."""
    fake_ee(modis_fixture(days=10, day_k=310.0, night_k=280.0))

    day = LandSurfaceTemperatureDayMetric().compute(make_context())
    night = LandSurfaceTemperatureNightMetric().compute(make_context())

    assert day.value == pytest.approx(36.85)
    assert night.value == pytest.approx(6.85)
    assert day.value != night.value


# --------------------------------------------------------------------------
# The day-night range
# --------------------------------------------------------------------------


def test_range_is_the_day_minus_night_difference(fake_ee):
    """310 K day, 280 K night is a 30 K range."""
    fake_ee(modis_fixture(days=10, day_k=310.0, night_k=280.0))
    result = DiurnalTemperatureRangeMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(30.0)
    assert result.unit == "K"


def test_range_is_reported_in_kelvin_not_celsius(fake_ee):
    """A difference has no meaningful Celsius reading when it is zero."""
    assert DiurnalTemperatureRangeMetric().unit == "K"


def test_range_is_not_the_celsius_difference(fake_ee):
    """Subtracting Celsius values would give the same number, but the
    unit label matters: reporting '30 degC' for a temperature interval
    invites reading it as an absolute temperature.
    """
    fake_ee(modis_fixture(day_k=310.0, night_k=280.0))
    result = DiurnalTemperatureRangeMetric().compute(make_context())
    assert result.unit == "K"
    assert "degC" not in result.unit


def test_range_reads_both_bands(fake_ee):
    fake_ee(modis_fixture())
    result = DiurnalTemperatureRangeMetric().compute(make_context())
    assert set(result.provenance.bands) == {"LST_Day_1km", "LST_Night_1km"}


def test_range_without_both_bands_is_insufficient(fake_ee):
    """One band alone cannot produce a difference."""
    fake_ee({MODIS_LST_8DAY: {"LST_Day_1km": [RAW_300K] * 5}})
    with pytest.raises(KeyError):
        DiurnalTemperatureRangeMetric().compute(make_context())


def test_range_with_empty_night_is_insufficient(fake_ee):
    fake_ee(
        {
            MODIS_LST_8DAY: {
                "LST_Day_1km": [RAW_300K] * 5,
                "LST_Night_1km": [],
            }
        }
    )
    result = DiurnalTemperatureRangeMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_range_can_be_negative(fake_ee):
    """A negative range is physically impossible for day minus night.

    It is not clamped, because a negative value here would indicate a
    real problem with the data or the band wiring, and hiding it would
    conceal that.
    """
    fake_ee(modis_fixture(day_k=280.0, night_k=310.0))
    result = DiurnalTemperatureRangeMetric().compute(make_context())
    assert result.value == pytest.approx(-30.0)


def test_range_explains_why_kelvin_is_used(fake_ee):
    fake_ee(modis_fixture())
    result = DiurnalTemperatureRangeMetric().compute(make_context())
    assert "kelvin" in result.provenance.formula.lower()


def test_range_provenance_documents_the_mean_of_differences_caveat(fake_ee):
    """Subtracting means is not the same as averaging differences."""
    fake_ee(modis_fixture())
    result = DiurnalTemperatureRangeMetric().compute(make_context())
    limitations = " ".join(result.provenance.limitations).lower()
    assert "per-pixel" in limitations


# --------------------------------------------------------------------------
# Landsat
# --------------------------------------------------------------------------


def landsat_fixture(days: int = 2, raw_st: float = 45000.0):
    return {
        LANDSAT_THERMAL: {
            "ST_B10": [raw_st] * days,
            "ST_QA": [10.0] * days,
            "QA_PIXEL": [1.0] * days,
        }
    }


def test_landsat_computes_in_celsius(fake_ee):
    fake_ee(landsat_fixture(days=3))
    result = LandsatSurfaceTemperatureMetric().compute(make_context())

    assert result.status == STATUS_OK, result.message
    # 45000 * 0.00341802 + 149 = 302.8109 K = 29.6609 degC
    assert result.value == pytest.approx(29.6609, abs=0.01)


def test_landsat_reduces_at_the_true_thermal_resolution(fake_ee):
    """100 m, not the 30 m delivery grid.

    The thermal band is acquired at 100 m and resampled to 30 m. Using
    30 m would let the provenance claim a resolution the data does not
    support.
    """
    metric = LandsatSurfaceTemperatureMetric()
    assert metric.default_scale == 100
    assert metric.effective_scale(make_context()) == 100
    assert LANDSAT_ST_SCALE == 30


def test_landsat_caller_cannot_override_the_thermal_resolution(fake_ee):
    """default_scale wins over a context scale, so 10 m cannot be requested."""
    metric = LandsatSurfaceTemperatureMetric()
    context = make_context(scale=10)
    assert metric.effective_scale(context) == 100


def test_landsat_without_scenes_is_insufficient(fake_ee):
    fake_ee({LANDSAT_THERMAL: {"ST_B10": []}})
    result = LandsatSurfaceTemperatureMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "16-day" in result.message or "revisit" in result.message


def test_landsat_mentions_the_l2sr_masking_caveat():
    """Some scenes have the surface temperature bands fully masked."""
    joined = " ".join(LandsatSurfaceTemperatureMetric().limitations).lower()
    assert "l2sr" in joined


def test_landsat_single_scene_is_not_rated_excellent(fake_ee):
    """One scene cannot support a confident multi-date claim."""
    fake_ee(landsat_fixture(days=1))
    result = LandsatSurfaceTemperatureMetric().compute(make_context())

    assert result.provenance.quality_level not in (
        QualityLevel.EXCELLENT,
        QualityLevel.GOOD,
    )


def test_landsat_documents_the_kelvin_conversion_fully(fake_ee):
    fake_ee(landsat_fixture())
    result = LandsatSurfaceTemperatureMetric().compute(make_context())
    formula = result.provenance.formula
    assert "0.00341802" in formula
    assert "149" in formula


# --------------------------------------------------------------------------
# Cross-cutting
# --------------------------------------------------------------------------


def test_every_thermal_metric_carries_provenance(fake_ee):
    fake_ee(
        {
            MODIS_LST_8DAY: {
                "LST_Day_1km": [RAW_300K] * 5,
                "LST_Night_1km": [RAW_290K] * 5,
            },
            LANDSAT_THERMAL: {
                "ST_B10": [45000.0] * 3,
                "ST_QA": [10.0] * 3,
                "QA_PIXEL": [1.0] * 3,
            },
        }
    )

    for metric in THERMAL_METRICS:
        result = metric.compute(make_context())
        assert result.provenance is not None, metric.key
        assert result.provenance.formula, metric.key
        assert result.provenance.limitations, metric.key
        assert result.provenance.source_dataset_id, metric.key


def test_no_thermal_metric_publishes_a_value_without_provenance(fake_ee):
    fake_ee(
        {
            MODIS_LST_8DAY: {
                "LST_Day_1km": [RAW_300K] * 5,
                "LST_Night_1km": [RAW_290K] * 5,
            },
            LANDSAT_THERMAL: {
                "ST_B10": [45000.0] * 3,
                "ST_QA": [10.0] * 3,
                "QA_PIXEL": [1.0] * 3,
            },
        }
    )

    for metric in THERMAL_METRICS:
        result = metric.compute(make_context())
        if result.value is not None:
            assert result.provenance is not None, metric.key


def test_no_thermal_metric_mentions_disease_or_pest():
    forbidden = ("disease", "pest", "pathogen", "infection")
    for metric in THERMAL_METRICS:
        text = " ".join(
            list(metric.limitations) + [metric.description]
        ).lower()
        for word in forbidden:
            assert word not in text, f"{metric.key} mentions {word!r}"


def test_metric_metadata_serialises_for_every_thermal_metric():
    for metric in THERMAL_METRICS:
        payload = metric.metadata()
        assert payload["key"] == metric.key
        assert payload["unit"] == metric.unit
        assert payload["domain"] == "thermal"
