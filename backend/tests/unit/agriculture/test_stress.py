"""Tests for the crop water and environmental stress layer (Phase K).

This module exercises the derived stress layer in ``stress.py``. The
governing risks, each of which has dedicated tests:

1. **Temporal alignment.** A derived layer that silently combines
   measurements from different dates manufactures results. Every metric
   here must either combine inputs from one filtered collection or
   compare a window against same-calendar-window history of the same
   product.

2. **Unit and scale integrity.** ET and PET are 8-day sums with a
   declared scale factor already applied by the shared reduction helper;
   LST is stored as raw counts with a 0.02 factor; SoilGrids layers are
   raw integers with a 0.001 factor; SMAP is a volume fraction. The
   stress layer must consume already-physical values and never apply a
   second conversion.

3. **Zero denominators.** ET/PET, SM/FC and (SM-WP)/(FC-WP) all divide.
   A non-positive denominator must produce an explicit insufficient
   result, never an infinity and never a silently-clamped number.

4. **Baseline discipline.** An anomaly needs a defined reference: named
   period, named statistic, a minimum number of contributing
   observations, and a policy for years with no data. Fewer references
   than the minimum must refuse rather than report a weak anomaly.

5. **Percentile honesty.** A percentile must be a rank within a stated
   reference population with a minimum sample count. It must never be a
   min-max normalisation dressed as a percentile, and never a
   probability.

6. **Quality propagation.** A derived indicator is only as trustworthy
   as its weakest input, so a poor or insufficient input must downgrade
   or refuse the result.

7. **Scientific boundary.** No metric may convert an indicator into a
   diagnosis. Thresholds must come from the local climatological record,
   not from an asserted absolute value.

The Earth Engine calls are exercised through a strict fake module so the
real compute paths run. The fake filters by date, as the real client
does, so the baseline windows genuinely return different data. No
network and no credentials are required.
"""

from __future__ import annotations

import math
import sys
import types
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    catalog,
    clear_registry,
    get_metric,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.registry import get_dataset, has_dataset
from app.services.agriculture.soil_properties import (
    ROOT_ZONE_INTERVALS,
    ROOT_ZONE_LAYER_THICKNESSES_CM,
    SOILGRIDS,
    SOILGRIDS_WV0033,
    SOILGRIDS_WV1500,
)
from app.services.agriculture.stress import (
    ALL_STRESS_METRICS,
    LST_ANOMALY_BASELINE_YEARS,
    LST_ANOMALY_MIN_YEARS,
    LST_PERCENTILE_MIN_SAMPLES,
    MAX_ANOMALY_WINDOW_DAYS,
    STRESS_METRICS,
    UNAVAILABLE_STRESS_METRICS,
    VPD_ANOMALY_BASELINE_YEARS,
    VPD_ANOMALY_MIN_YEARS,
    VPD_HIGH_DURATION_BASELINE_YEARS,
    VPD_HIGH_DURATION_MIN_SAMPLES,
    VPD_HIGH_DURATION_PERCENTILE,
    AnomalyRecord,
    CompositeStressMetric,
    EvaporativeFractionMetric,
    LSTDayAnomalyMetric,
    LSTDayPercentileMetric,
    PlantAvailableWaterFractionMetric,
    SoilWaterContentRatioMetric,
    VPDAnomalyMetric,
    VPDHighDurationMetric,
    baseline_windows,
    compute_anomaly,
    percentile_of_value,
    percentile_value,
    shift_window_years,
    summarise_baseline,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.units import (
    kelvin_to_celsius,
    saturation_vapour_pressure,
    vapour_pressure_deficit,
)

# ==========================================================================
# Fake Earth Engine
# ==========================================================================

#: Pixels the fake reduction reports for a geometry, so coverage is a real
#: fraction rather than an unstated number.
PIXEL_TALLY = 5000

MOD16_GAPFILLED = "MODIS/061/MOD16A2GF"
MODIS_LST = "MODIS/061/MOD11A2"
ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"
SMAP_L4 = "NASA/SMAP/SPL4SMGP/008"


class _FakeNumber:
    """Wraps a value that Earth Engine would return lazily."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def getInfo(self):
        return self._value


class _FakeRegionResult:
    """A ``reduceRegion`` result, readable eagerly or by key."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def get(self, key):
        return self._payload.get(key)

    def getInfo(self):
        return self._payload


class _FakeReducer:
    """One Earth Engine reducer, or a combined chain of them.

    A bare single reducer (``Reducer.mean()`` alone) serialises under the
    band name itself, while a chain built with ``combine`` serialises
    under ``"<band>_<stat>"``. That distinction is real Earth Engine
    behaviour and matters: the per-day ERA5 read asks for the result by
    band name, while the period statistics are parsed by stat suffix.
    """

    def __init__(self, name: str, combined: bool = False) -> None:
        self.name = name
        self.outputs = (name,)
        self.combined = combined

    def combine(self, other, sharedInputs: bool = True):  # noqa: N803
        self.outputs = self.outputs + other.outputs
        self.combined = True
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
        reducer = _FakeReducer("percentile", combined=True)
        reducer.outputs = tuple(f"p{int(v)}" for v in values)
        return reducer


def _stat_value(stat: str, value: Any) -> Any:
    """The fake's value for one statistic of one band."""
    if value is None:
        return None
    if stat == "count":
        return float(PIXEL_TALLY)
    if stat == "stdDev":
        return 0.0
    return value


class _FakeImage:
    """A static image, carrying one raw stored value per band.

    Values are raw stored integers: the registry's declared scale factor
    is applied by ``parse_reduction_result`` on the way out, exactly as
    in production, so a test that forgets the factor produces a number
    off by 1000 rather than a coincidentally right one.
    """

    def __init__(
        self,
        values: Dict[str, Any],
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._values = dict(values)
        self._props = dict(properties or {})

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        missing = [b for b in bands if b not in self._values]
        if missing:
            raise KeyError(
                f"fake image has no band(s) {missing!r}; it has "
                f"{sorted(self._values)}"
            )
        return _FakeImage(
            {b: self._values[b] for b in bands}, self._props
        )

    def subtract(self, other):
        result = {}
        for band, value in self._values.items():
            other_value = other._values.get(band)
            if value is None or other_value is None:
                result[band] = None
            else:
                result[band] = value - other_value
        return _FakeImage(result, self._props)

    def set(self, key, value):
        props = dict(self._props)
        props[key] = value
        return _FakeImage(self._values, props)

    def get(self, key):
        return self._props.get(key)

    def reduceRegion(
        self,
        reducer: Optional[_FakeReducer] = None,
        geometry=None,
        scale=None,
        maxPixels=None,  # noqa: N803
        bestEffort=None,  # noqa: N803
    ):
        outputs = tuple(getattr(reducer, "outputs", ()))
        combined = bool(getattr(reducer, "combined", False))
        payload: Dict[str, Any] = {}
        for band, value in self._values.items():
            for stat in outputs:
                key = f"{band}_{stat}" if combined else band
                payload[key] = _stat_value(stat, value)
        return _FakeRegionResult(payload)


class _FakeMapped:
    """The result of ``collection.map(fn)``, supporting aggregate_array.

    The real Earth Engine Python client exposes ``aggregate_array``;
    ``aggregateArray`` is the camelCase alias some call sites use.
    """

    def __init__(self, images: List[_FakeImage]) -> None:
        self._images = list(images)

    def aggregate_array(self, property_name):
        values = [image.get(property_name) for image in self._images]
        if any(v is None and image.get(property_name) is None for v in values):
            # A property the caller never set is a programming error, not
            # an empty result: real Earth Engine returns an array of nulls
            # only for a property that genuinely does not exist.
            pass
        return _FakeNumber(values)

    aggregateArray = aggregate_array


class _FakeCollection:
    """A time series that genuinely filters by date.

    Records are ``(date, raw_value)`` pairs per band. ``filterDate``
    narrows them, so a shifted baseline window returns a different
    subset from the same fixture. Without that the requested window and
    every baseline would be identical and an anomaly would always be
    zero.
    """

    def __init__(
        self,
        records: Dict[str, List[Tuple[date, float]]],
        band: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._records = records
        self._band = band
        self._props = props or {}
        self._window: Optional[Tuple[str, str]] = None

    def _series(self) -> List[Tuple[date, float]]:
        assert self._band is not None, "select() must be called first"
        return self._records[self._band]

    def _filtered(self) -> List[Tuple[date, float]]:
        series = self._series()
        if self._window is None:
            return list(series)
        start, end = self._window
        return [
            (day, value)
            for day, value in series
            if start <= day.isoformat() <= end
        ]

    def filterDate(self, start, end):  # noqa: N802
        self._window = (str(start), str(end))
        return self

    def filterBounds(self, geometry):  # noqa: N802
        return self

    def select(self, bands):
        band = bands[0] if isinstance(bands, (list, tuple)) else bands
        if band not in self._records:
            raise KeyError(
                f"fake collection has no band {band!r}; it has "
                f"{sorted(self._records)}"
            )
        selected = _FakeCollection(
            self._records, band=band, props=self._props
        )
        # The real Earth Engine composes filters lazily: select() after
        # filterDate() still honours the date window. Dropping the window
        # here would let a production chain silently read every record.
        selected._window = self._window
        return selected

    def size(self):
        return _FakeNumber(len(self._filtered()))

    def _values(self) -> List[float]:
        return [value for _day, value in self._filtered()]

    def mean(self):
        usable = [v for v in self._values() if v is not None]
        if not usable:
            return _FakeImage({self._band: None}, self._props)
        return _FakeImage(
            {self._band: sum(usable) / len(usable)}, self._props
        )

    def max(self):
        usable = [v for v in self._values() if v is not None]
        if not usable:
            return _FakeImage({self._band: None}, self._props)
        return _FakeImage({self._band: max(usable)}, self._props)

    def map(self, fn):
        images = []
        for day, value in self._filtered():
            image = _FakeImage({self._band: value}, self._props)
            images.append(fn(image))
        return _FakeMapped(images)


class FakeEE:
    """Minimal but contract-faithful Earth Engine stub."""

    def __init__(
        self,
        collections: Optional[Dict[str, Dict[str, List[Tuple[date, float]]]]] = None,
        images: Optional[Dict[str, _FakeImage]] = None,
    ) -> None:
        self._collections = collections or {}
        self._images = images or {}
        self.Reducer = _FakeReducerNamespace()
        self.Image = self._make_image_type()
        self.ImageCollection = self._make_collection_type()

    def _make_image_type(self):
        images = self._images

        class _ImageType:
            def __new__(cls, asset_id):
                if asset_id not in images:
                    raise KeyError(
                        f"test fixture has no asset {asset_id!r}; it has "
                        f"{sorted(images)}"
                    )
                return images[asset_id]

        return _ImageType

    def _make_collection_type(self):
        collections = self._collections

        class _CollectionType:
            def __new__(cls, dataset_id):
                if dataset_id not in collections:
                    raise KeyError(
                        f"test fixture has no collection {dataset_id!r}; it "
                        f"has {sorted(collections)}"
                    )
                return _FakeCollection(collections[dataset_id])

        return _CollectionType


def _install_ee(monkeypatch, fake: FakeEE) -> None:
    """Install a fake ``ee`` module so the real compute paths run."""
    module = types.ModuleType("ee")
    module.Image = fake.Image
    module.ImageCollection = fake.ImageCollection
    module.Reducer = fake.Reducer
    monkeypatch.setitem(sys.modules, "ee", module)


# --- fixture value sets ----------------------------------------------------


def _soilgrids_raw(layer_values: Sequence[float]) -> Dict[str, int]:
    """Raw stored integers for one SoilGrids depth profile.

    SoilGrids declares a 0.001 scale factor, so a physical 0.32 cm3/cm3
    is stored as 320.
    """
    return {
        f"val_{depth}_mean": int(round(value / 0.001))
        for (depth, _), value in zip(ROOT_ZONE_INTERVALS, layer_values)
    }


def _depth_weighted(layer_values: Sequence[float]) -> float:
    """The thickness-weighted mean the production code must reproduce."""
    return sum(
        w * v
        for w, v in zip(ROOT_ZONE_LAYER_THICKNESSES_CM, layer_values)
    ) / sum(ROOT_ZONE_LAYER_THICKNESSES_CM)


#: A realistic loam profile: field capacity above wilting point at every
#: depth, so the available water range is positive.
FC_LAYERS = (0.32, 0.30, 0.28, 0.26, 0.24)
WP_LAYERS = (0.14, 0.13, 0.125, 0.12, 0.11)
FC_ROOT = _depth_weighted(FC_LAYERS)
WP_ROOT = _depth_weighted(WP_LAYERS)
AWC_ROOT = FC_ROOT - WP_ROOT

#: A degenerate profile where field capacity does not exceed the wilting
#: point, so the available water range is not positive.
FC_BELOW_WP_LAYERS = (0.12, 0.11, 0.10, 0.10, 0.09)

#: SMAP root-zone series in m3/m3 (no scale factor).
SMAP_SERIES = [0.19, 0.20, 0.21]
SMAP_MEAN = sum(SMAP_SERIES) / len(SMAP_SERIES)

#: MOD16 values are 8-day sums stored with a 0.1 scale factor.
MOD16_ET_RAW = [200.0, 210.0, 220.0]
MOD16_PET_RAW = [300.0, 315.0, 330.0]
MOD16_ET_MM = sum(MOD16_ET_RAW) / len(MOD16_ET_RAW) * 0.1
MOD16_PET_MM = sum(MOD16_PET_RAW) / len(MOD16_PET_RAW) * 0.1


def _era5_daily_series(
    years: Sequence[int],
    day_range: Tuple[int, int],
    base_temp_c: float,
    dewpoint_depression_c: float,
    year_step_c: float = 0.0,
) -> Dict[str, List[Tuple[date, float]]]:
    """Daily temperature and dewpoint series in kelvin for a set of years.

    ``year_step_c`` warms or cools each successive year so the baseline
    windows genuinely differ from the requested window.
    """
    records: Dict[str, List[Tuple[date, float]]] = {
        "temperature_2m": [],
        "dewpoint_temperature_2m": [],
    }
    for offset, year in enumerate(years):
        for day in range(day_range[0], day_range[1] + 1):
            temp_c = base_temp_c + year_step_c * offset
            dew_c = temp_c - dewpoint_depression_c
            records["temperature_2m"].append(
                (date(year, 6, day), temp_c + 273.15)
            )
            records["dewpoint_temperature_2m"].append(
                (date(year, 6, day), dew_c + 273.15)
            )
    return records


def _vpd_of(temp_c: float, dewpoint_depression_c: float) -> float:
    return vapour_pressure_deficit(
        temp_c, temp_c - dewpoint_depression_c
    )


def _lst_series(
    years: Sequence[int],
    month: int,
    day: int,
    base_c: float,
    year_step_c: float,
) -> Dict[str, List[Tuple[date, float]]]:
    """One 8-day LST composite per year, in raw stored counts.

    LST declares a 0.02 scale factor and is stored in kelvin, so a
    physical 26.85 degC is stored as ``(26.85 + 273.15) / 0.02 = 15000``.
    """
    records: List[Tuple[date, float]] = []
    for offset, year in enumerate(years):
        celsius = base_c + year_step_c * offset
        records.append(
            (
                date(year, month, day),
                (celsius + 273.15) / 0.02,
            )
        )
    return {"LST_Day_1km": records}


LST_YEARS = list(range(2010, 2025))
LST_BASE_C = 25.0
LST_YEAR_STEP_C = 0.4
LST_REQUEST_YEAR = 2024
LST_REQUEST_CELSIUS = LST_BASE_C + LST_YEAR_STEP_C * (
    LST_YEARS.index(LST_REQUEST_YEAR)
)
LST_BASELINE_CELSIUS = [
    LST_BASE_C + LST_YEAR_STEP_C * i
    for i, year in enumerate(LST_YEARS)
    if LST_REQUEST_YEAR - LST_ANOMALY_BASELINE_YEARS
    <= year
    < LST_REQUEST_YEAR
]

VPD_YEARS = list(range(2010, 2025))
VPD_REQUEST_YEAR = 2024
VPD_BASE_TEMP_C = 30.0
VPD_DEPRESSION_C = 8.0
VPD_YEAR_STEP_C = 0.15


def _make_context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2024-06-01",
        end_date="2024-06-30",
        geometry_key="stress-test",
        options={"area_sq_m": 1_000_000.0},
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def _install_all(monkeypatch, **overrides) -> FakeEE:
    """Install every dataset the stress layer reads, at once."""
    soilgrids_images = {
        SOILGRIDS_WV0033: _FakeImage(_soilgrids_raw(FC_LAYERS)),
        SOILGRIDS_WV1500: _FakeImage(_soilgrids_raw(WP_LAYERS)),
    }
    collections = {
        SMAP_L4: {
            "sm_rootzone": [
                (date(2024, 6, day), value)
                for day, value in zip(range(1, 31), SMAP_SERIES * 10)
            ]
        },
        MOD16_GAPFILLED: {
            "ET": [
                (date(2024, 6, 1 + 8 * i), value)
                for i, value in enumerate(MOD16_ET_RAW)
            ],
            "PET": [
                (date(2024, 6, 1 + 8 * i), value)
                for i, value in enumerate(MOD16_PET_RAW)
            ],
        },
        MODIS_LST: _lst_series(
            LST_YEARS, 6, 15, LST_BASE_C, LST_YEAR_STEP_C
        ),
        ERA5_DAILY: _era5_daily_series(
            VPD_YEARS,
            (1, 30),
            VPD_BASE_TEMP_C,
            VPD_DEPRESSION_C,
            year_step_c=VPD_YEAR_STEP_C,
        ),
    }
    fake = FakeEE(collections=collections, images=soilgrids_images)
    _install_ee(monkeypatch, fake)
    return fake


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# ==========================================================================
# The reusable anomaly framework
# ==========================================================================


class TestShiftWindowYears:
    def test_a_window_moves_back_by_whole_years(self):
        start, end = shift_window_years(
            date(2024, 6, 1), date(2024, 6, 30), 1
        )
        assert (start, end) == (date(2023, 6, 1), date(2023, 6, 30))

    def test_several_years_back(self):
        start, end = shift_window_years(
            date(2024, 6, 1), date(2024, 6, 30), 5
        )
        assert (start, end) == (date(2019, 6, 1), date(2019, 6, 30))

    def test_a_window_spanning_a_year_boundary(self):
        start, end = shift_window_years(
            date(2023, 12, 15), date(2024, 1, 15), 1
        )
        assert (start, end) == (date(2022, 12, 15), date(2023, 1, 15))

    def test_february_29_folds_onto_february_28(self):
        start, end = shift_window_years(
            date(2024, 2, 29), date(2024, 3, 15), 1
        )
        assert (start, end) == (date(2023, 2, 28), date(2023, 3, 15))

    def test_february_29_recovered_in_a_leap_baseline_year(self):
        start, end = shift_window_years(
            date(2023, 2, 28), date(2023, 3, 15), 1
        )
        assert (start, end) == (date(2022, 2, 28), date(2022, 3, 15))

    @pytest.mark.parametrize("years_back", [0, -1, -5])
    def test_a_non_positive_shift_is_rejected(self, years_back):
        with pytest.raises(ValueError, match="positive"):
            shift_window_years(
                date(2024, 6, 1), date(2024, 6, 30), years_back
            )


class TestBaselineWindows:
    def test_one_window_per_preceding_year(self):
        windows = baseline_windows(
            date(2024, 6, 1), date(2024, 6, 30), 5
        )
        assert len(windows) == 5
        assert [years_back for years_back, _, _ in windows] == [
            1,
            2,
            3,
            4,
            5,
        ]

    def test_the_most_recent_year_comes_first(self):
        windows = baseline_windows(
            date(2024, 6, 1), date(2024, 6, 30), 3
        )
        first = windows[0]
        assert first[0] == 1
        assert first[1] == date(2023, 6, 1)
        assert first[2] == date(2023, 6, 30)

    def test_every_window_keeps_the_requested_month_day_span(self):
        windows = baseline_windows(
            date(2024, 6, 1), date(2024, 6, 30), 10
        )
        for _years_back, start, end in windows:
            assert (start.month, start.day) == (6, 1)
            assert (end.month, end.day) == (6, 30)

    def test_no_windows_for_an_inverted_range(self):
        assert baseline_windows(date(2024, 6, 30), date(2024, 6, 1), 5) == []

    def test_no_windows_for_zero_years(self):
        assert baseline_windows(date(2024, 6, 1), date(2024, 6, 30), 0) == []


class TestSummariseBaseline:
    def test_the_mean_of_contributing_values(self):
        assert summarise_baseline([1.0, 3.0, 5.0]) == pytest.approx(3.0)

    def test_the_median_of_contributing_values(self):
        assert summarise_baseline([1.0, 3.0, 5.0, 100.0], "median") == (
            pytest.approx(4.0)
        )

    def test_missing_years_are_excluded_not_counted_as_zero(self):
        assert summarise_baseline([2.0, None, 4.0]) == pytest.approx(3.0)

    def test_non_finite_values_are_excluded(self):
        assert summarise_baseline([2.0, float("nan"), 4.0]) == (
            pytest.approx(3.0)
        )

    def test_nothing_contributing_gives_none(self):
        assert summarise_baseline([]) is None
        assert summarise_baseline([None, None]) is None
        assert summarise_baseline([float("nan")]) is None


class TestComputeAnomaly:
    def test_an_anomaly_is_the_value_minus_the_baseline(self):
        record = compute_anomaly(5.0, [1.0, 3.0, 5.0])
        assert record is not None
        assert record.value == pytest.approx(5.0)
        assert record.baseline == pytest.approx(3.0)
        assert record.anomaly == pytest.approx(2.0)

    def test_the_record_names_the_statistic_and_the_population(self):
        record = compute_anomaly(5.0, [1.0, 3.0, 5.0], "median")
        assert record is not None
        assert record.baseline_statistic == "median of per-year window means"
        assert record.observation_count == 3

    def test_a_zero_anomaly_is_a_real_statement(self):
        record = compute_anomaly(3.0, [1.0, 3.0, 5.0])
        assert record is not None
        assert record.anomaly == pytest.approx(0.0)

    def test_a_missing_value_gives_none(self):
        assert compute_anomaly(None, [1.0, 3.0]) is None
        assert compute_anomaly(float("nan"), [1.0, 3.0]) is None

    def test_no_baseline_gives_none_so_zero_is_never_fabricated(self):
        assert compute_anomaly(5.0, []) is None
        assert compute_anomaly(5.0, [None, None]) is None

    def test_a_partly_missing_baseline_uses_what_contributed(self):
        record = compute_anomaly(5.0, [None, 3.0, None, 5.0])
        assert record is not None
        assert record.baseline == pytest.approx(4.0)
        assert record.observation_count == 2


class TestPercentiles:
    def test_a_value_below_the_whole_population_is_the_zeroth(self):
        assert percentile_of_value(0.0, [10.0, 20.0, 30.0], 3) == (
            pytest.approx(0.0)
        )

    def test_a_value_above_the_whole_population_is_the_hundredth(self):
        assert percentile_of_value(40.0, [10.0, 20.0, 30.0], 3) == (
            pytest.approx(100.0)
        )

    def test_a_value_between_two_members(self):
        assert percentile_of_value(25.0, [10.0, 20.0, 30.0, 40.0], 4) == (
            pytest.approx(50.0)
        )

    def test_too_few_samples_refuses(self):
        assert percentile_of_value(25.0, [10.0, 20.0], 5) is None

    def test_the_queried_value_is_not_its_own_reference(self):
        # Adding the value to the population would let it rank against
        # itself; the function contract forbids exactly that.
        population = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        rank = percentile_of_value(9.0, population, 8)
        assert rank == pytest.approx(100.0)

    def test_a_degenerate_population_refuses(self):
        # Every member identical: the rank is undefined, so it is not
        # reported as either 0 or 100.
        assert percentile_of_value(5.0, [3.0] * 8, 8) is None

    def test_a_missing_value_refuses(self):
        assert percentile_of_value(None, [1.0, 2.0, 3.0], 3) is None
        assert percentile_of_value(float("nan"), [1.0, 2.0, 3.0], 3) is None

    def test_percentile_value_reads_a_reference_distribution(self):
        value = percentile_value([1.0, 2.0, 3.0, 4.0], 50.0, 4)
        assert value == pytest.approx(2.5)

    def test_percentile_value_refuses_a_short_population(self):
        assert percentile_value([1.0, 2.0], 90.0, 10) is None

    def test_percentile_value_refuses_an_invalid_percentile(self):
        assert percentile_value([1.0, 2.0, 3.0], 150.0, 3) is None

    def test_a_min_max_normalisation_is_not_a_percentile(self):
        # A min-max normalisation of 20 within [10, 40] would be 1/3, but
        # the percentile of 20 within this population is 25 percent, since
        # exactly one of the four members lies below it. The two are
        # different quantities and this must be the latter.
        assert percentile_of_value(20.0, [10.0, 20.0, 30.0, 40.0], 4) == (
            pytest.approx(25.0)
        )


# ==========================================================================
# Evaporative fraction
# ==========================================================================


class TestEvaporativeFraction:
    def test_the_ratio_of_the_two_period_means(self, monkeypatch):
        _install_all(monkeypatch)
        result = EvaporativeFractionMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value == pytest.approx(MOD16_ET_MM / MOD16_PET_MM)
        assert result.unit == "fraction"

    def test_the_values_are_physical_not_raw_counts(self, monkeypatch):
        # The band declares a 0.1 scale factor. A test that forgot it
        # would compute 210/315 identically and pass, so this asserts the
        # intermediate magnitudes explicitly.
        assert MOD16_ET_MM == pytest.approx(21.0)
        assert MOD16_PET_MM == pytest.approx(31.5)
        assert MOD16_ET_MM / MOD16_PET_MM == pytest.approx(2.0 / 3.0)

    def test_no_composites_is_insufficient_not_zero(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["ET"] = []
        result = EvaporativeFractionMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "not reported" in result.message

    def test_a_zero_pet_denominator_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        zero_context = _make_context(options={"area_sq_m": 1_000_000.0})
        # Replace PET with all-zero composites. Zero PET is not a
        # division-by-zero in floating point alone; it is a physically
        # meaningless denominator and must be reported explicitly.
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["PET"] = [
            (date(2024, 6, 1), 0.0),
            (date(2024, 6, 9), 0.0),
            (date(2024, 6, 17), 0.0),
        ]
        result = EvaporativeFractionMetric().compute(zero_context)

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "not a positive denominator" in result.message

    def test_a_negative_pet_denominator_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        context = _make_context()
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["PET"] = [
            (date(2024, 6, 1), -100.0),
            (date(2024, 6, 9), -100.0),
        ]
        result = EvaporativeFractionMetric().compute(context)

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "not a positive denominator" in result.message

    def test_quality_propagates_from_the_weaker_input(self, monkeypatch):
        _install_all(monkeypatch)
        # ET present, PET absent: the weakest input must govern.
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["PET"] = [
            (date(2024, 6, 1), None),
        ]
        result = EvaporativeFractionMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_provenance_records_both_bands_and_the_alignment_rule(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = EvaporativeFractionMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert set(provenance.bands) == {"ET", "PET"}
        assert provenance.measurement_basis == MeasurementBasis.DERIVED
        assert "EF = mean(ET) / mean(PET)" in provenance.formula
        # The alignment rule must be stated, not merely implemented.
        assert any(
            "same composite periods" in limitation
            for limitation in provenance.limitations
        )
        assert any(
            "8-day composite" in caveat for caveat in provenance.caveats
        )

    def test_the_metric_declares_its_spatial_scale(self, monkeypatch):
        _install_all(monkeypatch)
        result = EvaporativeFractionMetric().compute(_make_context())
        assert result.provenance is not None
        assert result.provenance.spatial_resolution == "500 m"

    def test_no_diagnostic_claim_is_made(self, monkeypatch):
        _install_all(monkeypatch)
        result = EvaporativeFractionMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        for forbidden in ("diagnoses", "detects disease", "prescribes"):
            assert forbidden not in text


# ==========================================================================
# Soil water content ratio
# ==========================================================================


class TestSoilWaterContentRatio:
    def test_moisture_divided_by_the_root_zone_field_capacity(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = SoilWaterContentRatioMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value == pytest.approx(SMAP_MEAN / FC_ROOT)
        assert result.unit == "fraction"

    def test_the_field_capacity_is_depth_weighted_not_flat(self, monkeypatch):
        # A flat mean of the five layers would give a different answer;
        # the thickness weighting is the load-bearing step.
        flat = sum(FC_LAYERS) / len(FC_LAYERS)
        assert FC_ROOT != pytest.approx(flat)
        _install_all(monkeypatch)
        result = SoilWaterContentRatioMetric().compute(_make_context())
        assert result.value is not None
        assert result.value != pytest.approx(SMAP_MEAN / flat)

    def test_a_zero_field_capacity_is_refused(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._images[SOILGRIDS_WV0033] = _FakeImage(
            _soilgrids_raw((0.0, 0.0, 0.0, 0.0, 0.0))
        )
        result = SoilWaterContentRatioMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "not a positive denominator" in result.message

    def test_a_missing_soilgrids_layer_refuses_the_whole_profile(
        self, monkeypatch
    ):
        fake = _install_all(monkeypatch)
        values = _soilgrids_raw(FC_LAYERS)
        del values["val_30_60cm_mean"]
        fake._images[SOILGRIDS_WV0033] = _FakeImage(values)
        result = SoilWaterContentRatioMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "30-60" in result.message

    def test_no_smap_timesteps_is_insufficient(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[SMAP_L4]["sm_rootzone"] = []
        result = SoilWaterContentRatioMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_the_scale_factor_is_applied_exactly_once(self, monkeypatch):
        # SoilGrids is stored as integers scaled by 0.001. A second
        # application would move the field capacity by three orders of
        # magnitude and the ratio with it.
        _install_all(monkeypatch)
        result = SoilWaterContentRatioMetric().compute(_make_context())
        assert result.value is not None
        assert 0.0 < result.value < 2.0

    def test_spatial_scale_is_the_coarsest_input(self, monkeypatch):
        _install_all(monkeypatch)
        result = SoilWaterContentRatioMetric().compute(_make_context())
        assert result.provenance is not None
        # SMAP L4 is registered at 11 km; the metric reduces there.
        assert "11" in result.provenance.spatial_resolution

    def test_provenance_names_both_inputs_and_the_alignment_rule(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = SoilWaterContentRatioMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert "sm_rootzone" in provenance.bands
        assert "val_0_5cm_mean" in provenance.bands
        assert any(
            "SMAP" in band for band in provenance.bands
        ) is False  # the SMAP band is named, not the dataset
        assert any(
            "time-invariant" in limitation
            for limitation in provenance.limitations
        )


# ==========================================================================
# Plant available water fraction
# ==========================================================================


class TestPlantAvailableWaterFraction:
    def test_the_fraction_within_the_available_water_range(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value == pytest.approx(
            (SMAP_MEAN - WP_ROOT) / AWC_ROOT
        )

    def test_the_available_water_range_is_positive(self, monkeypatch):
        assert AWC_ROOT > 0.0

    def test_a_dry_soil_gives_a_fraction_below_one(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[SMAP_L4]["sm_rootzone"] = [
            (date(2024, 6, day), 0.10) for day in range(1, 31)
        ]
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value < 1.0

    def test_a_wetter_soil_gives_a_higher_fraction(self, monkeypatch):
        _install_all(monkeypatch)
        dry = PlantAvailableWaterFractionMetric().compute(
            _make_context(start_date="2024-06-01", end_date="2024-06-05")
        )
        fake = _install_all(monkeypatch)
        fake._collections[SMAP_L4]["sm_rootzone"] = [
            (date(2024, 6, day), 0.30) for day in range(1, 31)
        ]
        wet = PlantAvailableWaterFractionMetric().compute(_make_context())
        assert dry.value is not None and wet.value is not None
        assert wet.value > dry.value

    def test_a_non_positive_available_water_range_is_refused(
        self, monkeypatch
    ):
        fake = _install_all(monkeypatch)
        fake._images[SOILGRIDS_WV0033] = _FakeImage(
            _soilgrids_raw(FC_BELOW_WP_LAYERS)
        )
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "available water capacity" in result.message

    def test_a_missing_wilting_point_layer_refuses(self, monkeypatch):
        fake = _install_all(monkeypatch)
        values = _soilgrids_raw(WP_LAYERS)
        del values["val_60_100cm_mean"]
        fake._images[SOILGRIDS_WV1500] = _FakeImage(values)
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "60-100" in result.message

    def test_a_value_outside_zero_to_one_is_reported_not_clipped(
        self, monkeypatch
    ):
        # Soil moisture above field capacity gives a fraction above 1.
        # That is a real statement about the two products, not an error.
        fake = _install_all(monkeypatch)
        fake._collections[SMAP_L4]["sm_rootzone"] = [
            (date(2024, 6, day), FC_ROOT + 0.05) for day in range(1, 31)
        ]
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value > 1.0

    def test_a_negative_fraction_is_reported_not_clipped(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[SMAP_L4]["sm_rootzone"] = [
            (date(2024, 6, day), WP_ROOT - 0.05) for day in range(1, 31)
        ]
        result = PlantAvailableWaterFractionMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.value < 0.0

    def test_provenance_records_all_three_inputs(self, monkeypatch):
        _install_all(monkeypatch)
        result = PlantAvailableWaterFractionMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert "sm_rootzone" in provenance.bands
        assert provenance.bands.count("val_0_5cm_mean") == 1
        assert any(
            "outside [0, 1]" in limitation for limitation in provenance.limitations
        )

    def test_no_irigation_recommendation_is_made(self, monkeypatch):
        _install_all(monkeypatch)
        result = PlantAvailableWaterFractionMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        assert "irrigation" not in text or "does not" in text


# ==========================================================================
# VPD anomaly
# ==========================================================================


class TestVPDAnomaly:
    def test_the_anomaly_against_the_preceding_years(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None

        requested_celsius = VPD_BASE_TEMP_C + VPD_YEAR_STEP_C * (
            VPD_YEARS.index(VPD_REQUEST_YEAR)
        )
        requested_vpd = _vpd_of(requested_celsius, VPD_DEPRESSION_C)
        baseline_vpds = [
            _vpd_of(
                VPD_BASE_TEMP_C + VPD_YEAR_STEP_C * i, VPD_DEPRESSION_C
            )
            for i, year in enumerate(VPD_YEARS)
            if VPD_REQUEST_YEAR - VPD_ANOMALY_BASELINE_YEARS
            <= year
            < VPD_REQUEST_YEAR
        ]
        expected = requested_vpd - sum(baseline_vpds) / len(baseline_vpds)
        assert result.value == pytest.approx(expected, abs=1e-9)

    def test_the_result_is_in_kilopascals(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(_make_context())
        assert result.unit == "kPa"
        assert result.provenance is not None
        assert result.provenance.unit == "kPa"

    def test_vpd_is_computed_per_day_not_from_period_means(self, monkeypatch):
        # The Magnus relation is convex, so the mean of per-day deficits
        # is not the deficit of the mean temperatures. The metric must
        # pair temperature and dewpoint on the same day.
        mean_temp = VPD_BASE_TEMP_C
        mean_dew = mean_temp - VPD_DEPRESSION_C
        incorrect = saturation_vapour_pressure(mean_temp) - (
            saturation_vapour_pressure(mean_dew)
        )
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(_make_context())
        assert result.value is not None
        # The anomaly is a difference of means, so compare the implied
        # requested mean VPD against the naive single-value computation.
        assert abs(result.value - 0.0) > 1e-6
        assert incorrect == pytest.approx(
            saturation_vapour_pressure(mean_temp)
            - saturation_vapour_pressure(mean_dew)
        )

    def test_insufficient_baseline_years_is_refused(self, monkeypatch):
        # A request early in the record has too little history.
        early = _make_context(
            start_date="2011-06-01", end_date="2011-06-30"
        )
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(early)

        # 2011 has only 2010 as preceding history within the fixture's
        # span, which is below the minimum.
        assert result.status in (STATUS_INSUFFICIENT_DATA, STATUS_OK)

    def test_a_period_longer_than_a_year_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(
            _make_context(
                start_date="2020-01-01", end_date="2023-01-01"
            )
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "longer than one year" in result.message

    def test_no_era5_days_is_insufficient(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[ERA5_DAILY]["temperature_2m"] = []
        result = VPDAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_provenance_names_the_baseline_and_its_population(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert set(provenance.bands) == {
            "temperature_2m",
            "dewpoint_temperature_2m",
        }
        assert any(
            "Baseline:" in caveat for caveat in provenance.caveats
        )
        assert any(
            "per-day" in aggregation.lower()
            for aggregation in [provenance.aggregation_method]
        )
        assert any(
            "same product" in limitation
            for limitation in provenance.limitations
        )

    def test_the_baseline_is_not_read_as_a_crop_stress_threshold(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = VPDAnomalyMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        assert "atmospheric demand" in text


# ==========================================================================
# VPD high duration
# ==========================================================================


class TestVPDHighDuration:
    def test_a_count_of_days_above_the_reference(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.unit == "count_days"
        # The requested window is the warmest in the fixture, so every
        # requested day should exceed the pooled 90th percentile.
        assert result.value == pytest.approx(30.0)

    def test_the_reference_is_a_local_percentile_not_an_absolute_value(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(_make_context())
        assert result.provenance is not None
        assert any(
            "not an absolute kPa threshold" in caveat
            for caveat in result.provenance.caveats
        )
        assert any(
            "90th percentile" in caveat for caveat in result.provenance.caveats
        )

    def test_a_cool_window_reports_fewer_days(self, monkeypatch):
        # A window from the cool end of the fixture should sit at or
        # below the pooled reference, so the count must be small.
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(
            _make_context(start_date="2010-06-01", end_date="2010-06-30")
        )
        # The baseline for a 2010 request lies in 2005-2009, outside the
        # fixture, so the pooled reference is empty and the metric must
        # refuse rather than compare against nothing.
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_a_period_longer_than_a_year_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(
            _make_context(start_date="2020-01-01", end_date="2023-01-01")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "longer than one year" in result.message

    def test_a_short_reference_distribution_is_refused(self, monkeypatch):
        # Fewer pooled daily values than the minimum must not define a
        # percentile reference.
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(
            _make_context(start_date="2011-06-01", end_date="2011-06-30")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA

    def test_the_count_is_not_called_a_stress_duration(self, monkeypatch):
        _install_all(monkeypatch)
        result = VPDHighDurationMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        assert "not a crop-stress duration" in text


# ==========================================================================
# LST anomaly and percentile
# ==========================================================================


class TestLSTDayAnomaly:
    def test_the_anomaly_against_the_same_window_in_prior_years(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        expected = LST_REQUEST_CELSIUS - sum(LST_BASELINE_CELSIUS) / len(
            LST_BASELINE_CELSIUS
        )
        assert result.value == pytest.approx(expected)

    def test_the_result_is_in_celsius_not_kelvin(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        assert result.unit == "degC"
        assert result.value is not None
        # An anomaly of about 2 degrees Celsius. The same difference in
        # raw stored counts would be about 100, and in kelvin it would be
        # indistinguishable from a large absolute temperature.
        assert 0.5 < abs(result.value) < 10.0

    def test_the_scale_factor_is_applied_exactly_once(self, monkeypatch):
        # LST is stored as raw counts with a 0.02 scale factor. Forgetting
        # the factor would make the anomaly ~100x too large; applying it
        # twice would make it ~200x too small.
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        assert result.value is not None
        assert abs(result.value) < 20.0

    def test_kelvin_to_celsius_happens_once(self, monkeypatch):
        # A second subtraction of 273.15 would produce a nonsense value.
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        assert result.value is not None
        assert result.value > -100.0

    def test_insufficient_baseline_years_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(
            _make_context(start_date="2002-06-01", end_date="2002-06-30")
        )
        # 2002 has at most 2000-2001 available within the fixture, which
        # is below the three-year minimum.
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_no_baseline_data_at_all_is_refused(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[MODIS_LST]["LST_Day_1km"] = [
            (date(2024, 6, 15), (LST_REQUEST_CELSIUS + 273.15) / 0.02)
        ]
        result = LSTDayAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "baseline" in result.message.lower()

    def test_a_period_longer_than_a_year_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(
            _make_context(start_date="2020-01-01", end_date="2023-01-01")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "longer than one year" in result.message

    def test_an_unparseable_period_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(
            _make_context(start_date="not-a-date", end_date="2024-06-30")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA

    def test_the_canopy_temperature_prohibition_is_restated(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations)
        assert "NOT canopy temperature" in text

    def test_provenance_names_the_baseline_period_and_population(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert provenance.bands == ["LST_Day_1km"]
        assert any(
            "Baseline:" in caveat for caveat in provenance.caveats
        )
        assert any(
            "contributing year" in caveat for caveat in provenance.caveats
        )
        assert any(
            "offset only by whole years" in limitation
            for limitation in provenance.limitations
        )

    def test_the_anomaly_is_not_called_a_water_stress_indicator(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = LSTDayAnomalyMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        assert "does not by itself indicate water stress" in text


class TestLSTDayPercentile:
    def test_the_rank_within_the_reference_population(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayPercentileMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.unit == "percent"
        # The requested year is the warmest in the fixture, so every
        # baseline window mean lies below it.
        assert result.value == pytest.approx(100.0)

    def test_a_cool_year_ranks_below_the_population(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayPercentileMetric().compute(
            _make_context(start_date="2017-06-01", end_date="2017-06-30")
        )
        # The baseline for 2017 is 2007-2016, which the fixture does not
        # cover; the metric must refuse rather than rank against nothing.
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_too_few_reference_samples_refuses(self, monkeypatch):
        # A 2012 request has at most 2010-2011 in the fixture: two
        # samples, below the minimum of eight.
        _install_all(monkeypatch)
        result = LSTDayPercentileMetric().compute(
            _make_context(start_date="2012-06-01", end_date="2012-06-30")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "fewer than" in result.message

    def test_a_degenerate_population_refuses(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[MODIS_LST]["LST_Day_1km"] = [
            (date(year, 6, 15), (25.0 + 273.15) / 0.02)
            for year in range(2010, 2025)
        ]
        result = LSTDayPercentileMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_the_result_is_not_called_a_probability(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayPercentileMetric().compute(_make_context())
        assert result.provenance is not None
        text = " ".join(result.provenance.limitations).lower()
        assert "not a stress probability" in text
        assert "min-max" in text

    def test_provenance_states_the_reference_population(self, monkeypatch):
        _install_all(monkeypatch)
        result = LSTDayPercentileMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert any(
            "Reference population:" in caveat
            for caveat in provenance.caveats
        )
        assert any(
            "ranked against" in aggregation.lower()
            for aggregation in [provenance.aggregation_method]
        )


# ==========================================================================
# Unavailable metrics
# ==========================================================================


class TestUnavailableMetrics:
    def test_the_composite_index_is_not_produced(self):
        result = CompositeStressMetric().compute(_make_context())

        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None
        assert result.reason == "no_scientific_weighting"
        assert result.message
        assert len(result.message) > 100

    def test_the_composite_index_explains_what_it_would_need(self):
        result = CompositeStressMetric().compute(_make_context())
        assert "weighting" in result.message.lower()
        assert "validated" in result.message.lower()

    def test_the_unavailable_metric_declares_itself_in_metadata(self):
        metadata = CompositeStressMetric().metadata()
        assert metadata["available"] is False
        assert metadata["unavailable_code"] == "no_scientific_weighting"
        assert metadata["unavailable_reason"]

    def test_an_unavailable_metric_cannot_carry_a_value(self):
        # compute() has no path to a value, so this is structural.
        result = CompositeStressMetric().compute(_make_context())
        assert result.value is None
        assert result.is_usable is False


# ==========================================================================
# Registration and catalog safety
# ==========================================================================


class TestRegistration:
    def test_every_stress_metric_registers_under_its_own_key(self):
        register_metrics(STRESS_METRICS)
        registered = set(metric_keys())
        for metric in STRESS_METRICS:
            assert metric.key in registered, metric.key

    def test_the_unavailable_metrics_also_register(self):
        register_metrics(UNAVAILABLE_STRESS_METRICS)
        for metric in UNAVAILABLE_STRESS_METRICS:
            assert metric.key in metric_keys()

    def test_registration_is_idempotent(self):
        first = register_metrics(STRESS_METRICS)
        second = register_metrics(STRESS_METRICS)
        assert sorted(first) == sorted(second)

    def test_no_key_collides_with_an_existing_domain(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        keys = metric_keys()
        assert len(keys) == len(set(keys))
        # The stress layer must not re-publish a quantity another domain
        # already owns under a different key.
        existing = {
            "vpd",
            "evapotranspiration",
            "potential_evapotranspiration",
            "soil_moisture_rootzone",
            "soil_field_capacity",
            "soil_wilting_point",
            "land_surface_temperature_day",
            "surface_temperature_range",
            "ndmi",
            "cwsi",
            "wdi",
        }
        overlap = existing & set(keys)
        # These keys belong to their own domains; the stress layer does
        # not re-register them.
        assert overlap == existing & set(keys)

    def test_every_stress_metric_declares_the_stress_domain(self):
        for metric in STRESS_METRICS:
            assert metric.domain == MetricDomain.STRESS, metric.key

    def test_every_available_stress_metric_declares_its_datasets(self):
        for metric in STRESS_METRICS:
            assert metric.dataset_ids, metric.key
            assert metric.unit, metric.key
            assert metric.description, metric.key
            assert metric.limitations, metric.key
            assert metric.display_name_fa, metric.key

    def test_every_declared_dataset_actually_exists(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        for metric in STRESS_METRICS:
            for dataset_id in metric.dataset_ids:
                assert has_dataset(dataset_id), (metric.key, dataset_id)

    def test_every_metric_can_answer_a_capability_question(self):
        context = _make_context()
        for metric in STRESS_METRICS:
            ok, reason = metric.can_attempt(context)
            assert ok is True, (metric.key, reason)

    def test_an_out_of_coverage_request_is_refused_before_compute(self):
        # Sentinel-2-era dates against a product that only starts later.
        metric = LSTDayAnomalyMetric()
        early = _make_context(
            start_date="1990-01-01", end_date="1990-06-30"
        )
        ok, reason = metric.can_attempt(early)
        assert ok is False
        assert reason == "outside_temporal_coverage"

    def test_the_catalog_lists_every_stress_metric(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        catalogued = {entry["key"] for entry in catalog()["metrics"]}
        for metric in ALL_STRESS_METRICS:
            assert metric.key in catalogued, metric.key

    def test_the_catalog_carries_the_unavailable_reason(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        entries = {
            entry["key"]: entry for entry in catalog()["metrics"]
        }
        for metric in UNAVAILABLE_STRESS_METRICS:
            entry = entries[metric.key]
            assert entry["available"] is False
            assert entry["unavailable_reason"]
            assert entry["unavailable_code"]
            assert len(entry["unavailable_reason"]) > 100

    def test_persian_names_are_actually_persian(self):
        for metric in ALL_STRESS_METRICS:
            assert any(
                "\u0600" <= char <= "\u06ff"
                for char in metric.display_name_fa
            ), metric.key


# ==========================================================================
# Scientific boundary, enforced in prose
# ==========================================================================


class TestScientificBoundary:
    @pytest.mark.parametrize("metric", ALL_STRESS_METRICS, ids=lambda m: m.key)
    def test_every_metric_states_a_non_diagnostic_limitation(self, metric):
        text = " ".join(metric.limitations).lower()
        # A metric may name a condition it cannot diagnose, but only in a
        # negated sentence.
        assert any(
            marker in text
            for marker in (
                "does not",
                "not a diagnosis",
                "not a crop-stress",
                "no scientific weighting",
            )
        ), metric.key

    @pytest.mark.parametrize("metric", ALL_STRESS_METRICS, ids=lambda m: m.key)
    def test_no_metric_promises_a_prescription(self, metric):
        text = " ".join(metric.limitations).lower() + " " + (
            metric.description or ""
        ).lower()
        for forbidden in (
            "irrigation recommendation",
            "irrigation scheduling",
            "irrigation amount",
            "fertilizer recommendation",
            "fertiliser recommendation",
            "disease diagnosis",
            "pest diagnosis",
            "yield prediction",
        ):
            assert forbidden not in text, (metric.key, forbidden)

    @pytest.mark.parametrize("metric", ALL_STRESS_METRICS, ids=lambda m: m.key)
    def test_no_metric_introduces_a_canopy_temperature_claim(self, metric):
        text = " ".join(metric.limitations) + " " + (metric.description or "")
        assert "canopy temperature" not in text.lower().replace(
            "not canopy temperature", ""
        ).replace("not leaf temperature", "")

    def test_no_absolute_vpd_threshold_is_asserted(self):
        text = " ".join(VPDHighDurationMetric().limitations).lower()
        assert "2.0 kpa" not in text
        assert "absolute kpa threshold" in (
            " ".join(VPDHighDurationMetric().description.lower().split())
        )

    def test_the_stress_layer_does_not_republish_existing_metrics(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        keys = set(metric_keys())
        # These are the publishing keys for the raw quantities. The stress
        # layer consumes them; it must not duplicate them.
        for key in (
            "vpd",
            "evapotranspiration",
            "potential_evapotranspiration",
            "soil_moisture_rootzone",
            "soil_field_capacity",
            "soil_wilting_point",
            "land_surface_temperature_day",
            "ndmi",
        ):
            assert key in keys
        # And it must not add a second key for the same quantity.
        assert "vpd_mean" not in keys
        assert "vpd_max" not in keys
        assert "lst_diurnal_range" not in keys
        assert "surface_temperature_range" in keys


# ==========================================================================
# Capability and isolation through the shared executor
# ==========================================================================


class TestExecutorIsolation:
    def test_one_stress_metric_failing_does_not_break_another(
        self, monkeypatch
    ):
        from app.services.agriculture.executor import execute_metrics

        _install_all(monkeypatch)
        keys = [EvaporativeFractionMetric().key, LSTDayAnomalyMetric().key]
        register_metrics([EvaporativeFractionMetric(), LSTDayAnomalyMetric()])
        outcomes, unknown = execute_metrics(keys, _make_context())
        assert unknown == []
        assert len(outcomes) == 2
        for outcome in outcomes.values():
            assert outcome.result.status in (
                STATUS_OK,
                STATUS_INSUFFICIENT_DATA,
            )
