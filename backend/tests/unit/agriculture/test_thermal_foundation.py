"""Tests for the P4.1 thermal data foundation contract.

Audit outcome (see module docstring of the thermal and climate
engines): the repository already holds two production-supported
thermal sources with correct physical-quantity labeling, so P4.1
selects them rather than introducing new dependencies:

* land-surface temperature: ``MODIS/061/MOD11A2`` (8-day primary)
  with ``MODIS/061/MOD11A1`` (daily) as fallback, read through
  ``land_surface_temperature_day``;
* air temperature: ``ECMWF/ERA5_LAND/DAILY_AGGR`` band
  ``temperature_2m``, read through ``temperature_mean``.

Per the phase rule ("only implement metrics backed by an actually
supported production dataset; do not create both merely for
symmetry") no new metric is introduced here.  This file locks the
foundation contract instead: registration, metadata, exact
dataset/band identity, physical quantity, native and output units,
single-application conversion, temporal coverage and exact-window
behavior, missingness and quality semantics, provenance
completeness, masking and aggregation contracts, serialization,
discovery, and the scientific safeguards (no zero-fill, no
interpolation, no canopy-temperature mislabeling, no biological
interpretation).

Earth Engine calls run against small fakes, so the real compute
paths execute without credentials.  No network is required.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from app.services.agriculture import units as u
from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.climate import (
    ERA5_DAILY,
    TemperatureMeanMetric,
)
from app.services.agriculture.thermal import (
    MODIS_LST_8DAY,
    MODIS_LST_DAILY,
    THERMAL_METRICS,
    LandSurfaceTemperatureDayMetric,
)
from app.services.agriculture.types import (
    NOT_AVAILABLE_REASON_OUT_OF_COVERAGE,
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

LST_METRIC_KEY = "land_surface_temperature_day"
AIR_METRIC_KEY = "temperature_mean"
LST_BAND = "LST_Day_1km"
AIR_BAND = "temperature_2m"

NO_DATA = object()


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": "2024-05-01",
        "end_date": "2024-05-31",
        "geometry_key": "test-geometry",
    }
    fields.update(overrides)
    return MetricContext(**fields)


# --------------------------------------------------------------------------
# Fake Earth Engine (MODIS-style and ERA5-style reductions)
# --------------------------------------------------------------------------


class _FakeReducer:
    def __init__(self, name: str = "mean", percentiles=None) -> None:
        self.name = name
        self.percentiles = percentiles or []

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
        return _FakeReducer("percentile", list(values))


class _FakeFilterNamespace:
    @staticmethod
    def lt(field, value):
        return ("lt", field, value)


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value


def _reduce_values(values):
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
        "stdDev": math.sqrt(variance),
        "p10": ordered[0],
        "p25": ordered[0],
        "p75": ordered[-1],
        "p90": ordered[-1],
        "count": count,
    }


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
    def __init__(self, band, values) -> None:
        self._band = band
        self._values = list(values) if isinstance(values, list) else [values]
        self._properties = {}

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

    def mean(self):
        usable = [v for v in self._values if v is not NO_DATA]
        if not usable:
            return _FakeImage(self._band, [NO_DATA])
        return _FakeImage(self._band, [sum(usable) / len(usable)])

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(_reduce_values(self._values))


class _FakeMapped:
    def __init__(self, items) -> None:
        self._items = items

    def aggregate_array(self, name):
        values = []
        for item in self._items:
            value = item.get(name) if isinstance(item, _FakeImage) else None
            values.append(None if value is NO_DATA else value)
        return _FakeNumber(values)


class _FakeCollection:
    def __init__(self, band, values) -> None:
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
                f"fake collection holds {self._band!r}, not {bands!r}"
            )
        return self

    def size(self):
        return _FakeNumber(len(self._values))

    def map(self, func):
        return _FakeMapped(
            [func(_FakeImage(self._band, value)) for value in self._values]
        )

    def mean(self):
        # Compositing preserves the observation stack for the reducer;
        # the spatial mean is computed by reduceRegion, not here.
        # Averaging here would collapse the pixel tally to one and
        # misrepresent coverage.
        return _FakeImage(self._band, list(self._values))


class FakeEE:
    """Maps dataset IDs to ``{band: [values]}`` fixtures."""

    def __init__(self, datasets) -> None:
        self._datasets = datasets
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802
        if dataset_id not in self._datasets:
            raise KeyError(f"no fixture dataset {dataset_id!r}")
        bands = self._datasets[dataset_id]

        class _DatasetCollection(_FakeCollection):
            def select(self, select_bands):
                if isinstance(select_bands, str):
                    select_bands = [select_bands]
                if select_bands[0] not in bands:
                    raise KeyError(
                        f"fake dataset {dataset_id!r} has no band "
                        f"{select_bands[0]!r}"
                    )
                return _FakeCollection(select_bands[0], bands[select_bands[0]])

        return _DatasetCollection("", [])


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


def _modis_datasets(day_raw_values):
    return {
        MODIS_LST_8DAY: {
            LST_BAND: list(day_raw_values),
            "LST_Night_1km": [290.0 / 0.02] * max(len(day_raw_values), 1),
        }
    }


def _era5_datasets(values):
    return {ERA5_DAILY: {AIR_BAND: list(values)}}


# --------------------------------------------------------------------------
# 1-2, 22. Registration and discovery
# --------------------------------------------------------------------------


def test_lst_day_metric_registered_and_discoverable():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    assert LST_METRIC_KEY in metric_keys()
    assert get_metric(LST_METRIC_KEY).key == LST_METRIC_KEY


def test_era5_mean_air_temperature_registered_and_discoverable():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    assert AIR_METRIC_KEY in metric_keys()
    assert get_metric(AIR_METRIC_KEY).key == AIR_METRIC_KEY


def test_thermal_domain_has_no_canopy_temperature_key():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    for key in metric_keys():
        assert key != "canopy_temperature", key
        assert "canopy_temperature" not in key, key


def test_foundation_metric_metadata():
    lst = LandSurfaceTemperatureDayMetric()
    assert lst.key == LST_METRIC_KEY
    assert lst.display_name and lst.display_name_fa
    assert lst.domain is MetricDomain.THERMAL
    assert lst.unit == "degC"
    assert lst.description
    assert lst.limitations
    assert lst.measurement_basis is MeasurementBasis.PRODUCT

    air = TemperatureMeanMetric()
    assert air.key == AIR_METRIC_KEY
    assert air.display_name and air.display_name_fa
    assert air.domain is MetricDomain.CLIMATE
    assert air.unit == "degC"
    assert air.description
    assert air.limitations
    assert air.measurement_basis is MeasurementBasis.MODELLED


# --------------------------------------------------------------------------
# 3-5, 18. Dataset, band, and physical-quantity identity
# --------------------------------------------------------------------------


def test_modis_dataset_identity():
    metric = LandSurfaceTemperatureDayMetric()
    assert metric.dataset_ids[0] == "MODIS/061/MOD11A2"
    assert "MODIS/061/MOD11A1" in metric.dataset_ids


def test_modis_thermal_band_identity():
    from app.services.agriculture.registry import get_dataset

    metric = LandSurfaceTemperatureDayMetric()
    assert metric.source_bands == (LST_BAND,)
    assert get_dataset(MODIS_LST_8DAY).has_band(LST_BAND)
    assert get_dataset(MODIS_LST_DAILY).has_band(LST_BAND)


def test_lst_physical_quantity_is_land_surface():
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(MODIS_LST_8DAY).band(LST_BAND)
    assert "land surface temperature" in band.description.lower()
    caveats = " ".join(get_dataset(MODIS_LST_8DAY).caveats).lower()
    assert "land surface temperature" in caveats
    metric = LandSurfaceTemperatureDayMetric()
    assert "land surface temperature" in metric.description.lower()


def test_era5_dataset_and_band_identity():
    from app.services.agriculture.registry import get_dataset

    metric = TemperatureMeanMetric()
    assert metric.dataset_ids == (ERA5_DAILY,)
    assert metric.source_bands == (AIR_BAND,)
    band = get_dataset(ERA5_DAILY).band(AIR_BAND)
    assert band.description == "Air temperature at 2 m"
    assert get_dataset(ERA5_DAILY).has_band(AIR_BAND)


def test_air_temperature_quantity_is_not_canopy():
    metric = TemperatureMeanMetric()
    text = " ".join(
        [metric.description, *metric.limitations]
    ).lower()
    assert "air temperature" in text
    # The only canopy mention is the honest distinction: 2 m air
    # differs from conditions within the crop canopy.
    assert "canopy temperature" not in text
    assert "leaf temperature" not in text
    assert "crop canopy" in text


# --------------------------------------------------------------------------
# 6-9. Units and single-application conversion
# --------------------------------------------------------------------------


def test_native_units_are_kelvin():
    from app.services.agriculture.registry import get_dataset

    assert get_dataset(MODIS_LST_8DAY).band(LST_BAND).unit == "K"
    assert get_dataset(ERA5_DAILY).band(AIR_BAND).unit == "K"


def test_output_units_are_celsius():
    assert LandSurfaceTemperatureDayMetric().unit == "degC"
    assert TemperatureMeanMetric().unit == "degC"


def test_modis_scale_offset_sentinel_and_range():
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(MODIS_LST_8DAY).band(LST_BAND)
    assert band.scale_factor == pytest.approx(0.02)
    assert band.offset == pytest.approx(0.0)
    assert 0.0 in band.nodata_values
    assert band.valid_range[0] >= 100.0
    assert band.to_physical(0.0) is None
    assert band.to_physical(15000.0) == pytest.approx(300.0)


def test_era5_temperature_band_is_identity_scale():
    from app.services.agriculture.registry import get_dataset

    band = get_dataset(ERA5_DAILY).band(AIR_BAND)
    assert band.scale_factor == pytest.approx(1.0)
    assert band.offset == pytest.approx(0.0)
    assert band.to_physical(300.0) == pytest.approx(300.0)


def test_modis_conversion_applied_exactly_once(fake_ee):
    fake_ee(_modis_datasets([15000.0] * 6))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.status == STATUS_OK, result.message
    # 15000 counts x 0.02 = 300 K = 26.85 degC.
    assert result.value == pytest.approx(26.85)
    assert result.unit == "degC"
    # A second application of either step gives a detectably different
    # number, so equality above proves single application.
    assert result.value != pytest.approx(15000.0 * 0.02 * 0.02 - 273.15)
    assert result.value != pytest.approx(300.0 - 2 * 273.15)
    formula = result.provenance.formula.lower()
    assert "0.02" in formula
    assert "273.15" in formula


def test_era5_conversion_applied_exactly_once(fake_ee):
    fake_ee(_era5_datasets([300.0] * 5))
    result = TemperatureMeanMetric().compute(make_context())
    assert result.status == STATUS_OK, result.message
    assert result.value == pytest.approx(26.85)
    assert result.unit == "degC"
    assert result.value != pytest.approx(300.0 - 2 * 273.15)
    assert "273.15" in result.provenance.formula


# --------------------------------------------------------------------------
# 10-13. Temporal coverage and exact-window behavior
# --------------------------------------------------------------------------


def test_temporal_coverage_bounds():
    from app.services.agriculture.registry import get_dataset

    assert get_dataset(MODIS_LST_8DAY).available_from == "2000-02-18"
    assert get_dataset(ERA5_DAILY).available_from == "1950-01-02"


def test_pre_coverage_requests_refused():
    lst = LandSurfaceTemperatureDayMetric()
    can_attempt, reason = lst.can_attempt(
        make_context(start_date="1999-01-01", end_date="1999-01-31")
    )
    assert can_attempt is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE

    air = TemperatureMeanMetric()
    can_attempt, reason = air.can_attempt(
        make_context(start_date="1940-06-01", end_date="1940-06-30")
    )
    assert can_attempt is False
    assert reason == NOT_AVAILABLE_REASON_OUT_OF_COVERAGE


def test_in_coverage_requests_accepted():
    lst = LandSurfaceTemperatureDayMetric()
    can_attempt, _ = lst.can_attempt(make_context())
    assert can_attempt is True

    air = TemperatureMeanMetric()
    can_attempt, _ = air.can_attempt(make_context())
    assert can_attempt is True


def test_exact_requested_window_preserved(fake_ee):
    fake_ee(_modis_datasets([15000.0] * 6))
    context = make_context(start_date="2024-05-01", end_date="2024-05-31")
    result = LandSurfaceTemperatureDayMetric().compute(context)
    assert result.status == STATUS_OK
    assert result.provenance.requested_start == "2024-05-01"
    assert result.provenance.requested_end == "2024-05-31"
    assert result.provenance.date_start == "2024-05-01"
    assert result.provenance.date_end == "2024-05-31"


# --------------------------------------------------------------------------
# 14-16. Missingness and quality semantics
# --------------------------------------------------------------------------


def test_no_scenes_is_insufficient_not_zero(fake_ee):
    fake_ee({MODIS_LST_8DAY: {LST_BAND: []}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_era5_no_days_is_insufficient_not_zero(fake_ee):
    fake_ee(_era5_datasets([]))
    result = TemperatureMeanMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_no_valid_pixels_is_insufficient_not_zero(fake_ee):
    fake_ee({MODIS_LST_8DAY: {LST_BAND: [NO_DATA] * 5}})
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert "zero" in result.message.lower()


def test_quality_propagated_from_coverage(fake_ee):
    fake_ee(_modis_datasets([15000.0] * 10))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.provenance.quality_level in set(QualityLevel)
    assert result.provenance.quality_level not in (
        QualityLevel.UNAVAILABLE,
        QualityLevel.INSUFFICIENT,
    )

    fake_ee(_era5_datasets([290.0] * 31))
    air = TemperatureMeanMetric().compute(make_context())
    assert air.provenance.quality_level in set(QualityLevel)


# --------------------------------------------------------------------------
# 17, 19, 20. Provenance completeness, masking, aggregation
# --------------------------------------------------------------------------


def test_provenance_completeness(fake_ee):
    from app.services.agriculture.registry import get_dataset

    fake_ee(_modis_datasets([15000.0] * 6))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    provenance = result.provenance
    assert provenance.source_dataset_id == MODIS_LST_8DAY
    assert provenance.bands == [LST_BAND]
    assert provenance.formula
    assert provenance.unit == "degC"
    assert provenance.spatial_resolution
    assert provenance.temporal_resolution
    assert provenance.aggregation_method
    assert provenance.image_count == 6
    assert provenance.limitations
    assert provenance.citation
    # Native-unit conversion facts live in the registry band spec and
    # the dataset coverage record, completing the audit trail.
    band = get_dataset(MODIS_LST_8DAY).band(LST_BAND)
    assert (band.unit, band.scale_factor, band.offset) == ("K", 0.02, 0.0)
    assert get_dataset(MODIS_LST_8DAY).available_from == "2000-02-18"

    fake_ee(_era5_datasets([300.0] * 5))
    air = TemperatureMeanMetric().compute(make_context())
    assert air.provenance.source_dataset_id == ERA5_DAILY
    assert air.provenance.bands == [AIR_BAND]
    assert air.provenance.image_count == 5
    assert air.provenance.limitations


def test_masking_contract():
    from app.services.agriculture.registry import get_dataset

    dataset = get_dataset(MODIS_LST_8DAY)
    assert dataset.cloud_mask_band == "QC_Day"
    assert dataset.has_band("QC_Day")
    assert dataset.has_band("QC_Night")


def test_aggregation_contract(fake_ee):
    raw_300 = 300.0 / 0.02
    raw_310 = 310.0 / 0.02
    fake_ee(_modis_datasets([raw_300] * 3 + [raw_310] * 3))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    assert result.status == STATUS_OK
    # Time mean of the two retrievals (305 K), then spatial mean,
    # then a single Kelvin-to-Celsius conversion.
    assert result.value == pytest.approx(u.kelvin_to_celsius(305.0))
    assert "time mean" in result.provenance.aggregation_method.lower()
    assert "spatial mean" in result.provenance.aggregation_method.lower()


# --------------------------------------------------------------------------
# 21. Serialization round-trip
# --------------------------------------------------------------------------


def test_serialization_round_trip(fake_ee):
    fake_ee(_modis_datasets([15000.0] * 6))
    result = LandSurfaceTemperatureDayMetric().compute(make_context())
    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["metric_key"] == LST_METRIC_KEY
    assert payload["provenance"]["source_dataset_id"] == MODIS_LST_8DAY
    metadata = json.loads(
        json.dumps(LandSurfaceTemperatureDayMetric().metadata())
    )
    assert metadata["key"] == LST_METRIC_KEY
    assert metadata["domain"] == "thermal"
    air_metadata = json.loads(
        json.dumps(TemperatureMeanMetric().metadata())
    )
    assert air_metadata["key"] == AIR_METRIC_KEY


# --------------------------------------------------------------------------
# 23-26. Scientific safeguards
# --------------------------------------------------------------------------


def test_no_zero_fill_and_no_interpolation(fake_ee):
    # Empty inputs stay missing; nothing is invented.
    fake_ee({MODIS_LST_8DAY: {LST_BAND: []}})
    assert (
        LandSurfaceTemperatureDayMetric().compute(make_context()).value
        is None
    )
    fake_ee(_era5_datasets([]))
    assert TemperatureMeanMetric().compute(make_context()).value is None

    for module_name in ("thermal", "climate"):
        path = (
            Path(__file__).resolve().parents[3]
            / "app"
            / "services"
            / "agriculture"
            / f"{module_name}.py"
        )
        code = re.sub(
            r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
        )
        for snippet in ("fillna", "interpolate", "resample(", "asfreq"):
            assert snippet not in code, f"{module_name}: {snippet!r}"


def test_no_canopy_temperature_mislabeling():
    for metric in (LandSurfaceTemperatureDayMetric(), TemperatureMeanMetric()):
        assert "canopy_temperature" not in metric.key
        name = metric.display_name.lower()
        assert "canopy" not in name, metric.key
        assert "leaf temperature" not in name, metric.key
        assert "crop temperature" not in name, metric.key
    # The LST quantity is named as land-surface temperature, and the
    # disclaimer travels on the metric itself.
    lst_text = " ".join(
        [
            LandSurfaceTemperatureDayMetric().description,
            *LandSurfaceTemperatureDayMetric().limitations,
        ]
    )
    assert "land surface temperature" in lst_text.lower()
    assert "NOT canopy temperature" in lst_text


def test_no_biological_interpretation():
    forbidden = (
        "pest",
        "disease",
        "pathogen",
        "infection",
        "nutrient",
        "chlorosis",
        "diagnos",
    )
    for metric in (LandSurfaceTemperatureDayMetric(), TemperatureMeanMetric()):
        text = " ".join(
            [metric.description, *metric.limitations]
        ).lower()
        for word in forbidden:
            assert word not in text, f"{metric.key} mentions {word!r}"
        assert "water stress" not in text, metric.key
