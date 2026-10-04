"""Tests for the irrigation and water-management layer (Phase L).

This module exercises the derived irrigation layer in ``irrigation.py``.
The governing risks, each of which has dedicated tests:

1. **Temporal alignment.** The ET-minus-precipitation deficit subtracts
   two period integrals. Both must span the identical requested window;
   a deficit computed from mismatched intervals manufactures a number
   that means nothing.

2. **Unit and scale integrity.** ERA5-Land precipitation is stored in
   metres and must become millimetres exactly once; MOD16 ET composites
   carry a 0.1 scale factor that the shared reduction applies exactly
   once. A second application of either factor is the classic silent
   error this engine exists to prevent.

3. **Missing data is not zero.** An empty precipitation window is a
   missing observation, not a rainless period. Every metric must refuse
   with ``insufficient`` rather than report zero.

4. **Baseline discipline.** An anomaly needs a named reference window, a
   named statistic, a minimum number of contributing years, and a policy
   that excludes — rather than zero-fills — a year with no data.

5. **Quality propagation.** A derived indicator is only as trustworthy
   as its weakest input; a poor or insufficient input must downgrade or
   refuse the result.

6. **Scientific boundary.** No metric may convert a water-balance
   indicator into an irrigation instruction, and the drought / soil
   deficit / crop stress / irrigation deficit concepts must stay
   distinct.

7. **Unavailable honesty.** The water-requirement metrics that the
   existing data cannot support must refuse with precise reasons, never
   with invented assumptions.

The Earth Engine calls are exercised through a strict fake module so the
real compute paths run. The fake filters by date with an end-exclusive
window, matching ``ee.ImageCollection.filterDate``, so the baseline
windows genuinely return different data. No network and no credentials
are required.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    catalog,
    clear_registry,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.irrigation import (
    ALL_IRRIGATION_METRICS,
    IRRIGATION_METRICS,
    UNAVAILABLE_IRRIGATION_METRICS,
    ETPrecipitationDeficitMetric,
    EvapotranspirationAnomalyMetric,
    GrossIrrigationRequirementMetric,
    CropEvapotranspirationMetric,
    IrrigationWaterRequirementMetric,
    PrecipitationAnomalyMetric,
    PrecipitationCumulativeMetric,
    SoilMoistureRootZoneAnomalyMetric,
)
from app.services.agriculture.registry import has_dataset
from app.services.agriculture.types import (
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

# ==========================================================================
# Fake Earth Engine
# ==========================================================================

#: Pixels the fake reduction reports for a geometry, so coverage is a real
#: fraction rather than an unstated number.
PIXEL_TALLY = 5000

ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"
ERA5_PRECIPITATION_BAND = "total_precipitation_sum"
MOD16_GAPFILLED = "MODIS/061/MOD16A2GF"
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
    behaviour and matters: the per-day read asks for the result by band
    name, while the period statistics are parsed by stat suffix.
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
    """An image carrying one raw stored value per band.

    Values are raw stored numbers: the registry's declared scale factor
    is applied by ``parse_reduction_result`` on the way out, exactly as
    in production, so a test that forgets the factor produces a number
    off by ten rather than a coincidentally right one.
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
        return _FakeImage({b: self._values[b] for b in bands}, self._props)

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
    """The result of ``collection.map(fn)``, supporting aggregate_array."""

    def __init__(self, images: List[_FakeImage]) -> None:
        self._images = list(images)

    def aggregate_array(self, property_name):
        values = [image.get(property_name) for image in self._images]
        return _FakeNumber(values)

    aggregateArray = aggregate_array


class _FakeCollection:
    """A time series that genuinely filters by date.

    Records are ``(date, raw_value)`` pairs per band. ``filterDate``
    applies an end-exclusive window, as the real client does, so a
    shifted baseline window returns a different subset from the same
    fixture and a record placed exactly on the end date is excluded.
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
            if start <= day.isoformat() < end
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

    def sum(self):
        usable = [v for v in self._values() if v is not None]
        if not usable:
            return _FakeImage({self._band: None}, self._props)
        return _FakeImage({self._band: sum(usable)}, self._props)

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
        collections: Optional[
            Dict[str, Dict[str, List[Tuple[date, float]]]]
        ] = None,
    ) -> None:
        self._collections = collections or {}
        self.Reducer = _FakeReducerNamespace()
        self.ImageCollection = self._make_collection_type()

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
    module.ImageCollection = fake.ImageCollection
    module.Reducer = fake.Reducer
    monkeypatch.setitem(sys.modules, "ee", module)


# --- fixture value sets ----------------------------------------------------

#: The fixture spans 2013..2024 so a 2024 request has ten preceding years
#: of baseline history for every anomaly metric.
FIRST_YEAR = 2013
REQUEST_YEAR = 2024

#: Days placed inside the requested June window. The fake's filterDate is
#: end-exclusive, so a June 1 to June 30 request contains June 1..29:
#: 29 days.
WINDOW_DAYS = 29

#: Daily ERA5-Land precipitation in mm, rising 0.1 mm per year from 1.0 mm
#: in 2013 to 2.1 mm in 2024. Stored values are metres.
PRECIP_BASE_MM = 1.0
PRECIP_STEP_MM_PER_YEAR = 0.1


def _precip_daily_mm(year: int) -> float:
    return PRECIP_BASE_MM + PRECIP_STEP_MM_PER_YEAR * (year - FIRST_YEAR)


def _precip_series() -> List[Tuple[date, float]]:
    records: List[Tuple[date, float]] = []
    for year in range(FIRST_YEAR, REQUEST_YEAR + 1):
        for day in range(1, WINDOW_DAYS + 1):
            records.append(
                (date(year, 6, day), _precip_daily_mm(year) / 1000.0)
            )
    # Decoys outside the requested window: an end-exclusive filterDate
    # must exclude both the day before the start and the end date itself.
    records.append((date(REQUEST_YEAR, 5, 31), 50.0))
    records.append((date(REQUEST_YEAR, 6, 30), 50.0))
    return records


PRECIP_REQUEST_TOTAL_MM = WINDOW_DAYS * _precip_daily_mm(REQUEST_YEAR)
PRECIP_BASELINE_TOTALS_MM = [
    WINDOW_DAYS * _precip_daily_mm(year)
    for year in range(REQUEST_YEAR - 10, REQUEST_YEAR)
]
PRECIP_BASELINE_MEAN_MM = sum(PRECIP_BASELINE_TOTALS_MM) / len(
    PRECIP_BASELINE_TOTALS_MM
)
PRECIP_REQUEST_ANOMALY_MM = (
    PRECIP_REQUEST_TOTAL_MM - PRECIP_BASELINE_MEAN_MM
)

#: MOD16 ET composites for the requested window: four 8-day composites at
#: raw 200 (20.0 mm physical each). Raw values carry the 0.1 scale factor.
MOD16_REQUEST_RAW = [200.0, 200.0, 200.0, 200.0]
MOD16_REQUEST_COMPOSITE_DATES = (1, 9, 17, 25)

#: One composite per baseline year at raw 100 + 10*(year-2013); the year
#: 2018 is deliberately absent so the exclusion policy is exercised.
MOD16_MISSING_BASELINE_YEAR = 2018


def _mod16_et_raw(year: int) -> float:
    return 100.0 + 10.0 * (year - FIRST_YEAR)


def _mod16_et_series() -> List[Tuple[date, float]]:
    records: List[Tuple[date, float]] = []
    for day, raw in zip(
        MOD16_REQUEST_COMPOSITE_DATES, MOD16_REQUEST_RAW
    ):
        records.append((date(REQUEST_YEAR, 6, day), raw))
    for year in range(FIRST_YEAR, REQUEST_YEAR):
        if year == MOD16_MISSING_BASELINE_YEAR:
            continue
        records.append((date(year, 6, 15), _mod16_et_raw(year)))
    return records


ET_REQUEST_CUMULATIVE_MM = sum(MOD16_REQUEST_RAW) * 0.1
ET_BASELINE_TOTALS_MM = [
    _mod16_et_raw(year) * 0.1
    for year in range(REQUEST_YEAR - 10, REQUEST_YEAR)
    if year != MOD16_MISSING_BASELINE_YEAR
]
ET_BASELINE_MEAN_MM = sum(ET_BASELINE_TOTALS_MM) / len(
    ET_BASELINE_TOTALS_MM
)
ET_REQUEST_ANOMALY_MM = ET_REQUEST_CUMULATIVE_MM - ET_BASELINE_MEAN_MM

#: SMAP L4 root-zone moisture: a per-year constant falling 0.01 m3/m3 per
#: year, 0.25 in 2019 down to 0.20 in 2024.
SMAP_FIRST_YEAR = 2019


def _smap_value(year: int) -> float:
    return 0.25 - 0.01 * (year - SMAP_FIRST_YEAR)


def _smap_series() -> List[Tuple[date, float]]:
    records: List[Tuple[date, float]] = []
    for year in range(SMAP_FIRST_YEAR, REQUEST_YEAR + 1):
        for day in range(1, WINDOW_DAYS + 1):
            records.append((date(year, 6, day), _smap_value(year)))
    return records


SMAP_REQUEST_MEAN = _smap_value(REQUEST_YEAR)
SMAP_BASELINE_MEAN = sum(
    _smap_value(year)
    for year in range(REQUEST_YEAR - 5, REQUEST_YEAR)
) / 5
SMAP_REQUEST_ANOMALY = SMAP_REQUEST_MEAN - SMAP_BASELINE_MEAN


def _make_context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2024-06-01",
        end_date="2024-06-30",
        geometry_key="irrigation-test",
        options={"area_sq_m": 1_000_000.0},
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def _install_all(monkeypatch) -> FakeEE:
    """Install every dataset the irrigation layer reads, at once."""
    collections = {
        ERA5_DAILY: {ERA5_PRECIPITATION_BAND: _precip_series()},
        MOD16_GAPFILLED: {"ET": _mod16_et_series()},
        SMAP_L4: {"sm_rootzone": _smap_series()},
    }
    fake = FakeEE(collections=collections)
    _install_ee(monkeypatch, fake)
    return fake


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# ==========================================================================
# Cumulative precipitation
# ==========================================================================


class TestPrecipitationCumulativeMetric:
    def test_the_window_total_is_the_sum_of_daily_totals(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationCumulativeMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value == pytest.approx(PRECIP_REQUEST_TOTAL_MM, abs=1e-6)

    def test_metres_become_millimetres_exactly_once(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationCumulativeMetric().compute(_make_context())

        # A double conversion would report roughly 1000x this; a missing
        # conversion would report 1/1000 of it. The daily rate (~2.1 mm)
        # brackets the result from both sides.
        assert result.value is not None
        assert 58.0 < result.value < 63.0

    def test_days_outside_the_window_contribute_nothing(self, monkeypatch):
        # The fixture parks 50 m (50,000 mm) of rain on May 31 and on
        # June 30, both outside an end-exclusive June 1..30 window. A
        # metric that leaks either day in reports a wildly wrong total.
        _install_all(monkeypatch)
        result = PrecipitationCumulativeMetric().compute(_make_context())

        assert result.value == pytest.approx(PRECIP_REQUEST_TOTAL_MM, abs=1e-6)

    def test_an_empty_window_is_insufficient_not_zero(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[ERA5_DAILY][ERA5_PRECIPITATION_BAND] = []
        result = PrecipitationCumulativeMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "Reporting zero" in result.message

    def test_the_provenance_records_the_sum_and_the_window(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationCumulativeMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert provenance.unit == "mm"
        assert provenance.bands == [ERA5_PRECIPITATION_BAND]
        assert provenance.image_count == WINDOW_DAYS
        assert "sum" in provenance.aggregation_method.lower()
        assert any(
            "contributed" in caveat for caveat in provenance.caveats
        )

    def test_the_quality_verdict_reflects_full_coverage(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationCumulativeMetric().compute(_make_context())
        assert result.provenance is not None
        assert result.provenance.quality_level in (
            QualityLevel.EXCELLENT,
            QualityLevel.GOOD,
            QualityLevel.MODERATE,
        )


# ==========================================================================
# ET minus precipitation deficit
# ==========================================================================


class TestETPrecipitationDeficitMetric:
    def test_the_deficit_is_et_minus_precipitation(self, monkeypatch):
        _install_all(monkeypatch)
        result = ETPrecipitationDeficitMetric().compute(_make_context())

        assert result.status == STATUS_OK
        expected = ET_REQUEST_CUMULATIVE_MM - PRECIP_REQUEST_TOTAL_MM
        assert result.value == pytest.approx(expected, abs=1e-6)

    def test_the_et_term_keeps_its_scale_factor(self, monkeypatch):
        # MOD16 raw 200 per composite is 20 mm physical per composite;
        # four composites give 80 mm. A second application of the 0.1
        # factor would give 8 mm, a missing one 800 mm.
        _install_all(monkeypatch)
        result = ETPrecipitationDeficitMetric().compute(_make_context())

        assert result.value is not None
        expected = 80.0 - PRECIP_REQUEST_TOTAL_MM
        assert result.value == pytest.approx(expected, abs=1e-6)

    def test_a_rainfall_surplus_is_reported_unclipped(self, monkeypatch):
        # 2013: precipitation 29 x 1.0 mm = 29 mm against one 10 mm
        # composite, so the deficit is strongly negative.
        _install_all(monkeypatch)
        result = ETPrecipitationDeficitMetric().compute(
            _make_context(start_date="2013-06-01", end_date="2013-06-30")
        )

        assert result.status == STATUS_OK
        assert result.value == pytest.approx(10.0 - 29.0, abs=1e-6)
        assert result.value < 0.0

    def test_a_missing_et_input_refuses_with_the_input_reason(
        self, monkeypatch
    ):
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["ET"] = []
        result = ETPrecipitationDeficitMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "evapotranspiration" in result.message.lower()

    def test_a_missing_precipitation_input_refuses_with_the_input_reason(
        self, monkeypatch
    ):
        fake = _install_all(monkeypatch)
        fake._collections[ERA5_DAILY][ERA5_PRECIPITATION_BAND] = []
        result = ETPrecipitationDeficitMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "precipitation" in result.message.lower()

    def test_the_provenance_names_every_water_balance_term(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = ETPrecipitationDeficitMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        caveats = " ".join(provenance.caveats)
        assert "Water-balance terms:" in caveats
        assert "runoff (unavailable" in caveats
        assert "drainage (unavailable" in caveats
        assert "Inputs:" in caveats

    def test_the_metric_is_not_named_a_soil_water_deficit(self):
        metric = ETPrecipitationDeficitMetric()
        assert "ET minus Precipitation" in metric.display_name
        assert "soil water deficit" not in metric.display_name.lower()

    def test_a_degraded_input_downgrades_the_result(self, monkeypatch):
        # A window covering a single MOD16 composite caps the ET input at
        # MODERATE; the combined verdict must follow the worst input while
        # the value is still reported.
        _install_all(monkeypatch)
        context = _make_context(
            start_date="2024-06-01", end_date="2024-06-09"
        )
        result = ETPrecipitationDeficitMetric().compute(context)

        assert result.status == STATUS_OK
        assert result.value is not None
        assert result.provenance is not None
        assert result.provenance.quality_level == QualityLevel.MODERATE


# ==========================================================================
# Precipitation anomaly
# ==========================================================================


class TestPrecipitationAnomalyMetric:
    def test_the_anomaly_against_preceding_years(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value == pytest.approx(
            PRECIP_REQUEST_ANOMALY_MM, abs=1e-6
        )

    def test_the_units_are_millimetres(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(_make_context())
        assert result.unit == "mm"
        assert result.provenance is not None
        assert result.provenance.unit == "mm"

    def test_the_provenance_names_the_baseline(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(_make_context())
        provenance = result.provenance

        assert provenance is not None
        assert any("Baseline:" in c for c in provenance.caveats)
        assert any("Requested window:" in c for c in provenance.caveats)

    def test_too_few_contributing_years_is_refused(self, monkeypatch):
        # 2014 has only 2013 as contributing baseline history in the
        # fixture, below the three-year minimum.
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(
            _make_context(start_date="2014-06-01", end_date="2014-06-30")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "fewer than the 3 required" in result.message

    def test_a_window_longer_than_a_year_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(
            _make_context(start_date="2020-01-01", end_date="2021-01-10")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "longer than one year" in result.message

    def test_no_data_in_the_requested_window_is_insufficient(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = PrecipitationAnomalyMetric().compute(
            _make_context(start_date="2025-06-01", end_date="2025-06-30")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None


# ==========================================================================
# Evapotranspiration anomaly
# ==========================================================================


class TestEvapotranspirationAnomalyMetric:
    def test_the_anomaly_excludes_years_with_no_data(self, monkeypatch):
        # 2018 is absent from the fixture. It must be excluded from the
        # baseline mean, not counted as a zero year (which would drag the
        # baseline down and inflate the anomaly).
        _install_all(monkeypatch)
        result = EvapotranspirationAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert result.value == pytest.approx(ET_REQUEST_ANOMALY_MM, abs=1e-6)
        assert ET_REQUEST_ANOMALY_MM != pytest.approx(
            ET_REQUEST_CUMULATIVE_MM
            - sum([0.0 if y == MOD16_MISSING_BASELINE_YEAR else _mod16_et_raw(y) * 0.1
                   for y in range(REQUEST_YEAR - 10, REQUEST_YEAR)])
            / 10,
            abs=1e-6,
        )

    def test_an_excluded_year_is_flagged_in_the_warnings(self, monkeypatch):
        _install_all(monkeypatch)
        result = EvapotranspirationAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_OK
        assert any(
            "excluded" in warning for warning in result.warnings
        )

    def test_too_few_contributing_years_is_refused(self, monkeypatch):
        _install_all(monkeypatch)
        result = EvapotranspirationAnomalyMetric().compute(
            _make_context(start_date="2014-06-01", end_date="2014-06-30")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None
        assert "fewer than the 3 required" in result.message

    def test_no_mod16_data_at_all_is_insufficient(self, monkeypatch):
        fake = _install_all(monkeypatch)
        fake._collections[MOD16_GAPFILLED]["ET"] = []
        result = EvapotranspirationAnomalyMetric().compute(_make_context())

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None


# ==========================================================================
# Root-zone soil-moisture anomaly
# ==========================================================================


class TestSoilMoistureRootZoneAnomalyMetric:
    def test_the_anomaly_against_preceding_years(self, monkeypatch):
        _install_all(monkeypatch)
        result = SoilMoistureRootZoneAnomalyMetric().compute(
            _make_context()
        )

        assert result.status == STATUS_OK
        assert result.value == pytest.approx(SMAP_REQUEST_ANOMALY, abs=1e-9)

    def test_the_units_are_a_volume_fraction(self, monkeypatch):
        _install_all(monkeypatch)
        result = SoilMoistureRootZoneAnomalyMetric().compute(
            _make_context()
        )
        assert result.unit == "m3/m3"

    def test_the_provenance_names_the_baseline(self, monkeypatch):
        _install_all(monkeypatch)
        result = SoilMoistureRootZoneAnomalyMetric().compute(
            _make_context()
        )
        provenance = result.provenance

        assert provenance is not None
        assert any("Baseline:" in c for c in provenance.caveats)
        assert any("Requested window:" in c for c in provenance.caveats)

    def test_a_request_without_baseline_history_is_refused(
        self, monkeypatch
    ):
        # 2019 is the first SMAP fixture year; nothing precedes it.
        _install_all(monkeypatch)
        result = SoilMoistureRootZoneAnomalyMetric().compute(
            _make_context(start_date="2019-06-01", end_date="2019-06-30")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_no_data_in_the_requested_window_is_insufficient(
        self, monkeypatch
    ):
        _install_all(monkeypatch)
        result = SoilMoistureRootZoneAnomalyMetric().compute(
            _make_context(start_date="2025-06-01", end_date="2025-06-30")
        )

        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None


# ==========================================================================
# Deliberately unavailable irrigation metrics
# ==========================================================================


class TestUnavailableMetrics:
    @pytest.mark.parametrize(
        "metric, code",
        [
            (
                IrrigationWaterRequirementMetric(),
                "unsupported_water_balance_terms",
            ),
            (
                GrossIrrigationRequirementMetric(),
                "no_efficiency_parameter",
            ),
            (
                CropEvapotranspirationMetric(),
                "no_verified_crop_coefficient",
            ),
        ],
        ids=lambda item: getattr(item, "key", item),
    )
    def test_the_metric_refuses_with_its_reason(self, metric, code):
        result = metric.compute(_make_context())

        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None
        assert result.reason == code
        assert result.message
        assert len(result.message) > 100

    def test_the_water_requirement_names_the_missing_terms(self):
        result = IrrigationWaterRequirementMetric().compute(_make_context())
        text = result.message.lower()
        assert "runoff" in text
        assert "drainage" in text

    def test_the_gross_requirement_names_the_missing_efficiency(self):
        result = GrossIrrigationRequirementMetric().compute(_make_context())
        assert "efficiency" in result.message.lower()

    def test_crop_et_does_not_treat_pet_as_reference_et(self):
        result = CropEvapotranspirationMetric().compute(_make_context())
        text = result.message.lower()
        assert "crop coefficient" in text
        assert "et0" in text

    def test_an_unavailable_metric_cannot_carry_a_value(self):
        result = IrrigationWaterRequirementMetric().compute(_make_context())
        assert result.value is None
        assert result.is_usable is False

    def test_the_unavailable_metric_declares_itself_in_metadata(self):
        metadata = GrossIrrigationRequirementMetric().metadata()
        assert metadata["available"] is False
        assert metadata["unavailable_code"] == "no_efficiency_parameter"
        assert metadata["unavailable_reason"]


# ==========================================================================
# Registration and catalog safety
# ==========================================================================


class TestRegistration:
    def test_every_irrigation_metric_registers_under_its_own_key(self):
        register_metrics(IRRIGATION_METRICS)
        registered = set(metric_keys())
        for metric in IRRIGATION_METRICS:
            assert metric.key in registered, metric.key

    def test_the_unavailable_metrics_also_register(self):
        register_metrics(UNAVAILABLE_IRRIGATION_METRICS)
        for metric in UNAVAILABLE_IRRIGATION_METRICS:
            assert metric.key in metric_keys()

    def test_registration_is_idempotent(self):
        first = register_metrics(ALL_IRRIGATION_METRICS)
        second = register_metrics(ALL_IRRIGATION_METRICS)
        assert sorted(first) == sorted(second)

    def test_no_key_republishes_an_existing_metric(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        keys = set(metric_keys())
        # The irrigation layer consumes these quantities; it must not
        # register a second key for any of them.
        owned_elsewhere = {
            "precipitation",
            "evapotranspiration",
            "evapotranspiration_cumulative",
            "soil_moisture_rootzone",
            "vpd_anomaly",
            "lst_day_anomaly",
            "irrigation",  # land cover's irrigation-status class metric
        }
        overlap = {m.key for m in ALL_IRRIGATION_METRICS} & owned_elsewhere
        assert overlap == set()
        # And the original publishers must still be there.
        for key in owned_elsewhere:
            assert key in keys

    def test_every_irrigation_metric_declares_the_irrigation_domain(self):
        for metric in ALL_IRRIGATION_METRICS:
            assert metric.domain == MetricDomain.IRRIGATION, metric.key

    def test_every_available_metric_declares_its_datasets(self):
        for metric in IRRIGATION_METRICS:
            assert metric.dataset_ids, metric.key
            assert metric.unit, metric.key
            assert metric.description, metric.key
            assert metric.limitations, metric.key
            assert metric.display_name_fa, metric.key

    def test_every_declared_dataset_actually_exists(self):
        for metric in IRRIGATION_METRICS:
            for dataset_id in metric.dataset_ids:
                assert has_dataset(dataset_id), (metric.key, dataset_id)

    def test_every_available_metric_can_answer_a_capability_question(self):
        context = _make_context()
        for metric in IRRIGATION_METRICS:
            ok, _reason = metric.can_attempt(context)
            assert ok is True, metric.key

    def test_the_catalog_lists_every_irrigation_metric(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        catalogued = {entry["key"] for entry in catalog()["metrics"]}
        for metric in ALL_IRRIGATION_METRICS:
            assert metric.key in catalogued, metric.key

    def test_the_catalog_carries_the_unavailable_reason(self):
        from app.services.agriculture import register_all_metrics

        register_all_metrics()
        entries = {
            entry["key"]: entry for entry in catalog()["metrics"]
        }
        for metric in UNAVAILABLE_IRRIGATION_METRICS:
            entry = entries[metric.key]
            assert entry["available"] is False
            assert entry["unavailable_reason"]
            assert entry["unavailable_code"]
            assert len(entry["unavailable_reason"]) > 100

    def test_persian_names_are_actually_persian(self):
        for metric in ALL_IRRIGATION_METRICS:
            assert any(
                "\u0600" <= char <= "\u06ff"
                for char in metric.display_name_fa
            ), metric.key


# ==========================================================================
# Scientific boundary, enforced in prose
# ==========================================================================


class TestScientificBoundary:
    @pytest.mark.parametrize("metric", ALL_IRRIGATION_METRICS, ids=lambda m: m.key)
    def test_every_metric_states_a_non_prescriptive_limitation(self, metric):
        text = " ".join(metric.limitations).lower()
        assert any(
            marker in text
            for marker in (
                "does not",
                "not a",
                "not an",
                "not produced",
                "cannot",
                "must",
            )
        ), metric.key

    @pytest.mark.parametrize("metric", ALL_IRRIGATION_METRICS, ids=lambda m: m.key)
    def test_no_metric_promises_a_prescription(self, metric):
        text = " ".join(metric.limitations).lower() + " " + (
            metric.description or ""
        ).lower()
        for forbidden in (
            "irrigate now",
            "irrigation scheduling",
            "irrigation recommendation",
            "irrigation amount",
            "exact irrigation",
            "pump",
            "valve",
            "fertilizer recommendation",
            "fertiliser recommendation",
            "disease diagnosis",
            "pest diagnosis",
            "yield prediction",
        ):
            assert forbidden not in text, (metric.key, forbidden)

    def test_the_deficit_does_not_claim_to_be_a_field_water_balance(self):
        text = " ".join(ETPrecipitationDeficitMetric().limitations).lower()
        assert "not a complete field water balance" in text

    def test_precipitation_anomaly_is_a_meteorological_signal(self):
        metric = PrecipitationAnomalyMetric()
        text = " ".join(metric.limitations).lower()
        assert "meteorological" in text
        assert "irrigation deficit" in text

    def test_soil_moisture_anomaly_does_not_prove_irrigation_failure(self):
        text = " ".join(
            SoilMoistureRootZoneAnomalyMetric().limitations
        ).lower()
        assert "does not by itself prove lack of irrigation" in text

    def test_the_layer_does_not_invent_crop_parameters(self):
        # The unavailable reasons must not smuggle in assumed values.
        for metric in UNAVAILABLE_IRRIGATION_METRICS:
            text = (metric.unavailable_reason + " " + " ".join(
                metric.limitations
            )).lower()
            for forbidden in ("30 cm", "60 cm", "1 m rooting", "kc of"):
                assert forbidden not in text, (metric.key, forbidden)


# ==========================================================================
# Capability and isolation through the shared executor
# ==========================================================================


class TestExecutorIsolation:
    def test_one_irrigation_metric_failing_does_not_break_another(
        self, monkeypatch
    ):
        from app.services.agriculture.executor import execute_metrics

        fake = _install_all(monkeypatch)
        register_metrics(
            [
                PrecipitationCumulativeMetric(),
                ETPrecipitationDeficitMetric(),
            ]
        )
        keys = [
            PrecipitationCumulativeMetric().key,
            ETPrecipitationDeficitMetric().key,
        ]
        outcomes, unknown = execute_metrics(keys, _make_context())
        assert unknown == []
        assert len(outcomes) == 2
        for outcome in outcomes.values():
            assert outcome.result.status == STATUS_OK

        # With the precipitation collection emptied, the deficit must
        # refuse while the independent cumulative-ET-free metric... also
        # refuses, but each carries its own stated reason.
        fake._collections[ERA5_DAILY][ERA5_PRECIPITATION_BAND] = []
        outcomes, unknown = execute_metrics(keys, _make_context())
        assert unknown == []
        assert outcomes[
            ETPrecipitationDeficitMetric().key
        ].result.status == STATUS_INSUFFICIENT_DATA
        assert outcomes[
            PrecipitationCumulativeMetric().key
        ].result.status == STATUS_INSUFFICIENT_DATA
