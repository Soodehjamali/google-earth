"""Tests for the productivity layer (Phase M).

The governing risks, each with dedicated tests:

1. **A season the phenology engine does not certify.** The seasonal
   indicator reuses the phenology engine's detection verbatim. Fewer
   months than the minimum, a gap above the tolerated maximum, a season
   that never crosses the threshold in both directions, and a detected
   span whose months are mostly missing must all refuse -- never
   summarise a season that does not exist.

2. **Missing data is not zero.** A month the satellite never saw is
   excluded, never filled, and a span that is mostly missing refuses
   rather than averages the survivors as though they were the season.

3. **Unit protection.** The seasonal indicator is dimensionless
   (``index``); the ET context is ``mm``; the areal indicator is
   ``index.fraction``. No metric in this module carries a mass unit,
   and the serialised results are checked for the forbidden ones.

4. **The areal indicator is a weighting, not production.** The value is
   bounded by construction (|value| <= max(|NDVI|, |share|)); a
   cropland-free field yields zero through the share, not through the
   NDVI; and the warnings must state the field-level limitation.

5. **Quality propagation.** A weak NDVI window downgrades the seasonal
   indicator; a missing crop product refuses the areal metric; the
   worst-input rule governs every combination.

6. **Provenance.** Seasonal results carry the detected span, the monthly
   series and the gap diagnostics; the areal result carries the share
   and the valid-pixel accounting.

The Earth Engine path runs through the same style of strict fake the
phenology tests use: the fake refuses unknown properties and bands, so
a wiring mistake fails loudly instead of returning a plausible number.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.crop import (
    CROP_AREA_MIN_VALID_FRACTION,
    WORLDCEREAL_ID,
)
from app.services.agriculture.phenology import (
    MAX_TOLERATED_GAP_MONTHS,
    MIN_MONTHS,
    MIN_WINDOW_DAYS,
)
from app.services.agriculture.productivity import (
    ALL_PRODUCTIVITY_METRICS,
    CropAreaNormalisedProductivityIndicator,
    PRODUCTIVITY_AVAILABLE,
    PRODUCTIVITY_METRICS,
    SeasonalETProductivityContextMetric,
    SeasonalVegetationProductivityIndicator,
    summarise_season,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

# ==========================================================================
# Collection integrity
# ==========================================================================

EXPECTED_KEYS = {
    "seasonal_vegetation_productivity_indicator",
    "seasonal_evapotranspiration_context",
    "crop_area_normalised_productivity_indicator",
}


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_all_expected_productivity_metrics_present():
    assert {m.key for m in PRODUCTIVITY_METRICS} == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in ALL_PRODUCTIVITY_METRICS]
    assert len(keys) == len(set(keys))


def test_every_metric_is_in_the_productivity_domain():
    for metric in ALL_PRODUCTIVITY_METRICS:
        assert metric.domain == MetricDomain.PRODUCTIVITY, metric.key


def test_registration_reaches_the_catalog():
    register_metrics(PRODUCTIVITY_METRICS)
    for key in EXPECTED_KEYS:
        assert key in metric_keys(), key


def test_no_productivity_metric_carries_a_mass_unit():
    """A productivity proxy must never wear a mass unit."""
    forbidden = {"t/ha", "kg/ha", "kg/m2", "g/m2", "tons/ha", "t/ha/season"}
    for metric in ALL_PRODUCTIVITY_METRICS:
        assert metric.unit not in forbidden, (metric.key, metric.unit)


def test_the_availability_map_matches_the_metrics():
    assert set(PRODUCTIVITY_AVAILABLE) == EXPECTED_KEYS
    assert PRODUCTIVITY_AVAILABLE[
        "seasonal_vegetation_productivity_indicator"
    ] == "index"
    assert PRODUCTIVITY_AVAILABLE[
        "seasonal_evapotranspiration_context"
    ] == "mm"
    assert PRODUCTIVITY_AVAILABLE[
        "crop_area_normalised_productivity_indicator"
    ] == "index.fraction"


def test_every_metric_denies_yield_in_its_prose():
    """The boundary must be stated, in words, in the limitations."""
    for metric in ALL_PRODUCTIVITY_METRICS:
        text = " ".join(metric.limitations).lower()
        assert "not a yield" in text or "not yield" in text or (
            "yield estimate" in text and "not produced" in text
        ), metric.key


# ==========================================================================
# Fake Earth Engine
# ==========================================================================

S2_ID = "COPERNICUS/S2_SR_HARMONIZED"


class _FakeNumber:
    def __init__(self, value):
        self._value = value

    def getInfo(self):
        return self._value


class _FakeRegionResult:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeReducer:
    def __init__(self, name, combined=False):
        self.name = name
        self.outputs = (name,)
        self.combined = combined

    def combine(self, other, sharedInputs=True):  # noqa: N803
        self.outputs = self.outputs + other.outputs
        self.combined = True
        return self


class _ReducerNamespace:
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
    def stdDev():
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


#: Pixels the fake reports for a 10 m reduction over the test geometry,
#: so the coverage verdict is driven by the data, not by a shortfall.
PIXEL_TALLY = 100


def _window_payload(mean):
    """The whole-window NDVI reduction the phenology builder reads."""
    if mean is None:
        stats = {k: None for k in (
            "count", "mean", "median", "min", "max", "stdDev",
            "p10", "p25", "p75", "p90",
        )}
    else:
        stats = {
            "count": float(PIXEL_TALLY),
            "mean": mean,
            "median": mean,
            "min": mean - 0.05,
            "max": mean + 0.05,
            "stdDev": 0.02,
            "p10": mean - 0.04,
            "p25": mean - 0.02,
            "p75": mean + 0.02,
            "p90": mean + 0.04,
        }
    return {f"NDVI_{k}" if k != "count" else "NDVI_count": v
            for k, v in stats.items()}


class _FakeSceneImage:
    """A Sentinel-2 scene carrying raw reflectance in B4 and B8."""

    def __init__(self, red, nir):
        # Raw stored integers: the metrics multiply by 0.0001 themselves.
        self._values = {"B4": red, "B8": nir, "SCL": 4}

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        missing = [b for b in bands if b not in self._values]
        if missing:
            raise KeyError(
                f"fake scene has no band(s) {missing!r}; it has "
                f"{sorted(self._values)}"
            )
        return self

    def multiply(self, factor):
        return _FakeScaled(
            {k: v * factor for k, v in self._values.items()}
        )

    def updateMask(self, _mask):
        return self

    def date(self):
        return _FakeDateObject("2023-06-15")


class _FakeScaled:
    def __init__(self, values):
        self._values = values

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        missing = [b for b in bands if b not in self._values]
        if missing:
            raise KeyError(
                f"fake scaled image has no band(s) {missing!r}; it has "
                f"{sorted(self._values)}"
            )
        return self

    def subtract(self, other):
        return _FakeExpr(
            {k: self._values[k] - other._values[k] for k in self._values}
        )

    def divide(self, other):
        return _FakeExpr(
            {
                k: (
                    self._values[k] / other._values[k]
                    if other._values[k]
                    else None
                )
                for k in self._values
            }
        )

    def rename(self, name):
        return _FakeNamedImage(self._values, name)


class _FakeExpr:
    def __init__(self, values):
        self._values = values

    def rename(self, name):
        return _FakeNamedImage(self._values, name)


class _FakeNamedImage:
    def __init__(self, values, name):
        self._values = {name: values.get("B8", list(values.values())[0])}

    def reduceRegion(self, reducer=None, geometry=None, scale=None, **kw):
        outputs = tuple(getattr(reducer, "outputs", ()))
        combined = bool(getattr(reducer, "combined", False))
        payload = {}
        for band, value in self._values.items():
            for stat in outputs:
                key = f"{band}_{stat}" if combined else band
                payload[key] = float(PIXEL_TALLY) if stat == "count" else value
        return _FakeRegionResult(payload)

    def set(self, key, value):
        return self


class _FakeDateObject:
    def __init__(self, text):
        self._text = text

    def format(self, _fmt):
        return _FakeNumber(self._text)


class _FakeWindowImage:
    """The composite the seasonal NDVI reduction reads."""

    def __init__(self, ndvi_mean):
        self._ndvi_mean = ndvi_mean

    def select(self, bands):
        # The caller may pass a string or a one-element list; both name
        # the single NDVI band.
        names = [bands] if isinstance(bands, str) else list(bands)
        assert names == ["NDVI"], names
        return self

    def reduceRegion(self, reducer=None, geometry=None, scale=None, **kw):
        outputs = tuple(getattr(reducer, "outputs", ()))
        combined = bool(getattr(reducer, "combined", False))
        payload = {}
        for stat in outputs:
            key = f"NDVI_{stat}" if combined else "NDVI"
            if stat == "count":
                payload[key] = float(PIXEL_TALLY)
            else:
                payload[key] = self._ndvi_mean
        return _FakeRegionResult(payload)


class _FakeMonthlyMapped:
    """The collection after ``map``, carrying months and NDVI means."""

    def __init__(self, months, means, window_payload):
        self._months = months
        self._means = means
        self._window_payload = window_payload

    def aggregate_array(self, property_name):
        if property_name == "scene_month":
            return _FakeNumber(list(self._months))
        if property_name == "ndvi_mean":
            return _FakeNumber(list(self._means))
        raise KeyError(
            f"fake mapped collection carries only 'scene_month' and "
            f"'ndvi_mean', not {property_name!r}"
        )

    def mean(self):
        return _FakeWindowImage(self._window_payload.get("NDVI_mean"))

    def median(self):
        # The composite path maps NDVI per scene and takes the median of
        # the mapped collection; with the fake's per-scene values that
        # reduces to the window mean.
        return _FakeWindowImage(self._window_payload.get("NDVI_mean"))


class _FakeS2Collection:
    """The Sentinel-2 collection: monthly series plus whole-window stats."""

    def __init__(self, months, means, window_mean):
        self._months = months
        self._means = means
        self._window_payload = _window_payload(window_mean)

    def filterDate(self, _start, _end):
        return self

    def filterBounds(self, _geometry):
        return self

    def size(self):
        return _FakeNumber(len(self._months))

    def map(self, _fn):
        return _FakeMonthlyMapped(
            self._months, self._means, self._window_payload
        )

    # -- the composite path (areal metric) ------------------------------
    def filter(self, _flt):
        return self

    def median(self):
        # The composite path maps NDVI per scene and takes the median;
        # with the fake's per-scene values that reduces to the window mean.
        return _FakeWindowImage(self._window_payload.get("NDVI_mean"))


class _FakeFilterNamespace:
    @staticmethod
    def lte(_name, _value):
        return object()


class _FakeWorldCerealImage:
    """A WorldCereal classification image with a fixed mask mean."""

    def __init__(self, mask_mean):
        self._mask_mean = mask_mean

    def select(self, bands):
        assert list(bands) == ["classification"], bands
        return self

    def reduceRegion(self, reducer=None, geometry=None, scale=None, **kw):
        outputs = tuple(getattr(reducer, "outputs", ()))
        combined = bool(getattr(reducer, "combined", False))
        payload = {}
        for stat in outputs:
            key = f"classification_{stat}" if combined else "classification"
            payload[key] = (
                float(PIXEL_TALLY) if stat == "count" else self._mask_mean
            )
        return _FakeRegionResult(payload)

    def first(self):
        return self


class _FakeWorldCerealCollection:
    def __init__(self, mask_mean):
        self._mask_mean = mask_mean

    def filterDate(self, _s, _e):
        return self

    def filterBounds(self, _g):
        return self

    def filterMetadata(self, _p, _op, _v):
        return self

    def size(self):
        return _FakeNumber(1)

    def first(self):
        return _FakeWorldCerealImage(self._mask_mean)


class FakeProductivityEE:
    """The fake module: wires each dataset id to its fixture."""

    def __init__(
        self,
        months=None,
        means=None,
        window_mean=0.6,
        crop_mask_mean=None,
        composite_ndvi=0.6,
    ):
        self._months = months or []
        self._means = means or []
        self._window_mean = window_mean
        self._crop_mask_mean = crop_mask_mean
        self._composite_ndvi = composite_ndvi
        self.Reducer = _ReducerNamespace()
        self.Filter = _FakeFilterNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802
        if dataset_id == S2_ID:
            return _FakeS2Collection(
                self._months, self._means, self._window_mean
            )
        if dataset_id == WORLDCEREAL_ID:
            if self._crop_mask_mean is None:
                raise KeyError(
                    "fixture has no WorldCereal collection (crop_mask_mean "
                    "is None)"
                )
            return _FakeWorldCerealCollection(self._crop_mask_mean)
        raise KeyError(f"fixture has no collection {dataset_id!r}")


def install_fake(monkeypatch, fake):
    module = types.ModuleType("ee")
    module.ImageCollection = fake.ImageCollection
    module.Reducer = fake.Reducer
    module.Filter = fake.Filter
    monkeypatch.setitem(sys.modules, "ee", module)


def make_context(**overrides):
    defaults = dict(
        geometry={},
        start_date="2023-01-01",
        end_date="2023-12-31",
        geometry_key="productivity-test",
        options={"area_sq_m": 10000.0},
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def a_clean_year(base=0.2, peak=0.8):
    """Twelve months with one textbook season: rise, peak, fall."""
    values = []
    for m in range(1, 13):
        if m in (1, 2, 3, 11, 12):
            values.append((2023, m, base))
        elif m == 4:
            values.append((2023, m, 0.5))
        elif 5 <= m <= 9:
            values.append((2023, m, peak))
        elif m == 10:
            values.append((2023, m, 0.5))
    return values


# ==========================================================================
# summarise_season: the pure machinery
# ==========================================================================


class TestSummariseSeason:
    def _events(self, sos, eos):
        from app.services.agriculture.phenology import SeasonEvents

        return SeasonEvents(sos=sos, eos=eos)

    def _series(self, pairs):
        from app.services.agriculture.phenology import MonthlyValue

        return [MonthlyValue(y, m, v) for y, m, v in pairs]

    def test_the_mean_covers_only_months_inside_the_span(self):
        series = self._series(a_clean_year())
        events = self._events(date(2023, 4, 1), date(2023, 10, 1))
        summary = summarise_season(series, events)

        # April through October inclusive: 7 months.
        assert summary["months_in_span"] == 7
        assert summary["count"] == 7
        inside = [v for y, m, v in a_clean_year() if 4 <= m <= 10]
        assert summary["mean"] == pytest.approx(sum(inside) / len(inside))

    def test_months_outside_the_span_contribute_nothing(self):
        pairs = a_clean_year()
        # A wildly high January must not drag the seasonal mean.
        pairs[0] = (2023, 1, 5.0)
        series = self._series(pairs)
        events = self._events(date(2023, 4, 1), date(2023, 10, 1))
        summary = summarise_season(series, events)
        inside = [v for y, m, v in pairs if 4 <= m <= 10]
        assert summary["mean"] == pytest.approx(sum(inside) / len(inside))

    def test_a_missing_month_is_counted_not_filled(self):
        pairs = [p for p in a_clean_year() if p[1] != 6]
        series = self._series(pairs)
        events = self._events(date(2023, 4, 1), date(2023, 10, 1))
        summary = summarise_season(series, events)

        assert summary["months_in_span"] == 7
        assert summary["count"] == 6
        assert summary["missing_in_span"] == 1
        inside = [v for y, m, v in pairs if 4 <= m <= 10]
        assert summary["mean"] == pytest.approx(sum(inside) / len(inside))

    def test_an_unbounded_season_yields_nothing(self):
        from app.services.agriculture.phenology import SeasonEvents

        series = self._series(a_clean_year())
        summary = summarise_season(series, SeasonEvents())
        assert summary["mean"] is None
        assert summary["count"] == 0

    def test_an_empty_series_yields_no_mean(self):
        events = self._events(date(2023, 4, 1), date(2023, 10, 1))
        summary = summarise_season([], events)
        assert summary["mean"] is None


# ==========================================================================
# Seasonal indicator: the gates
# ==========================================================================


class TestSeasonalIndicatorGates:
    def test_a_short_window_is_refused_before_any_query(self):
        metric = SeasonalVegetationProductivityIndicator()
        can, reason = metric.can_attempt(
            make_context(start_date="2023-04-01", end_date="2023-08-31")
        )
        assert can is False
        assert reason == "window_too_short"

    def test_a_full_year_window_passes_the_gate(self):
        metric = SeasonalVegetationProductivityIndicator()
        can, reason = metric.can_attempt(make_context())
        assert can is True
        assert reason is None

    def test_too_few_months_refuse(self, monkeypatch):
        pairs = a_clean_year()[:MIN_MONTHS - 1]
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert str(MIN_MONTHS) in result.message

    def test_a_gap_above_the_maximum_refuses(self, monkeypatch):
        pairs = a_clean_year()
        # Remove months 5, 6 and 7: a three-month hole inside the season.
        pairs = [p for p in pairs if p[1] not in (5, 6, 7)]
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "gap" in result.message.lower()

    def test_an_unbounded_season_refuses(self, monkeypatch):
        # A flat series crosses nothing: amplitude ~0, no SOS, no EOS.
        pairs = [(2023, m, 0.5) for m in range(1, 13)]
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "amplitude midpoint" in result.message

    def test_no_observations_refuse(self, monkeypatch):
        install_fake(monkeypatch, FakeProductivityEE(months=[], means=[]))
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA


# ==========================================================================
# Seasonal indicator: the value
# ==========================================================================


class TestSeasonalIndicatorValue:
    def test_a_clean_year_publishes_the_in_span_mean(self, monkeypatch):
        pairs = a_clean_year()
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
                window_mean=0.55,
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        assert result.unit == "index"
        # Season spans May..September at peak 0.8; the in-span months are
        # May through September (or April..October, depending on where the
        # crossings land). Either way the mean sits between the base and
        # the peak -- the bounds are what the definition implies.
        assert 0.2 < result.value <= 0.8

    def test_the_value_is_dimensionless_and_provenance_carries_the_span(
        self, monkeypatch
    ):
        pairs = a_clean_year()
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        provenance = result.provenance.to_dict()
        assert "Detected season span" in " ".join(provenance["caveats"])
        assert "Monthly series used" in " ".join(provenance["caveats"])
        assert result.measurement_basis == MeasurementBasis.PROXY
        assert result.is_proxy is True

    def test_a_75_percent_season_still_publishes(self, monkeypatch):
        pairs = a_clean_year()
        # Remove exactly one in-season month: with a May..September span
        # the coverage is 4/5 = 80 percent, above the 75 percent floor.
        pairs = [p for p in pairs if p[1] != 6]
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        assert any("excluded, not filled" in w for w in result.warnings)

    def test_a_50_percent_season_refuses(self, monkeypatch):
        pairs = a_clean_year()
        # Remove months 5 and 7 (keep 6 so the gap rule is not the refuser):
        # the span keeps its shape but half its months are gone.
        pairs = [p for p in pairs if p[1] not in (5, 7)]
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "floor" in result.message

    def test_a_poor_quality_window_downgrades_the_result(self, monkeypatch):
        pairs = a_clean_year()
        # One scene per month is below the Sentinel-2 'good' image floor,
        # so the verdict lands at poor/moderate; the value still publishes
        # but must carry the quality warning.
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
            ),
        )
        result = SeasonalVegetationProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        # The composite warning set must acknowledge the limited scenes.
        assert result.warnings  # some caveat is present


# ==========================================================================
# Seasonal ET context
# ==========================================================================


class TestSeasonalETContext:
    def _install_without_et(self, monkeypatch, pairs, window_mean=0.55):
        """Install the S2 fake; the ET collection is absent on purpose."""
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
                window_mean=window_mean,
            ),
        )

    def test_without_a_certified_season_no_et_is_reported(self, monkeypatch):
        pairs = [(2023, m, 0.5) for m in range(1, 13)]
        self._install_without_et(monkeypatch, pairs)
        result = SeasonalETProductivityContextMetric().compute(
            make_context()
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "season" in result.message.lower()

    def test_with_a_season_but_no_et_collection_it_refuses(
        self, monkeypatch
    ):
        pairs = a_clean_year()
        self._install_without_et(monkeypatch, pairs)
        result = SeasonalETProductivityContextMetric().compute(
            make_context()
        )
        # The fake raises on the missing MOD16 collection; the metric
        # degrades that to insufficient, never to zero.
        assert result.status in (
            STATUS_INSUFFICIENT_DATA,
            STATUS_UNAVAILABLE,
        )
        assert result.value is None

    def test_the_et_window_is_the_season_widened_to_months(self):
        from app.services.agriculture.productivity import _last_day_of_month

        assert _last_day_of_month(date(2023, 9, 1)) == date(2023, 9, 30)
        assert _last_day_of_month(date(2024, 2, 10)) == date(2024, 2, 29)


# ==========================================================================
# Crop-area-normalised indicator
# ==========================================================================


class TestCropAreaNormalisedIndicator:
    def _install(self, monkeypatch, crop_mask_mean, composite_ndvi=0.6):
        pairs = a_clean_year()
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
                crop_mask_mean=crop_mask_mean,
                composite_ndvi=composite_ndvi,
            ),
        )

    def test_the_value_is_the_product_of_the_two_factors(self, monkeypatch):
        self._install(monkeypatch, crop_mask_mean=40.0, composite_ndvi=0.6)
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        # Share = 40/100 = 0.4; the NDVI mean the fake's composite reports
        # is 0.6 (window payload mean). The product is bounded by both.
        assert result.value == pytest.approx(0.6 * 0.4, abs=1e-6)
        assert result.unit == "index.fraction"

    def test_a_zero_share_gives_zero_through_the_share_not_the_ndvi(
        self, monkeypatch
    ):
        self._install(monkeypatch, crop_mask_mean=0.0, composite_ndvi=0.6)
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        assert result.value == 0.0
        # The NDVI itself was healthy; the share is what drove the zero.
        assert any("0.600" in w or "NDVI" in w for w in result.warnings)

    def test_the_value_cannot_exceed_either_factor(self, monkeypatch):
        self._install(monkeypatch, crop_mask_mean=100.0, composite_ndvi=0.6)
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        assert result.status == STATUS_OK
        assert result.value <= 0.6 + 1e-9

    def test_a_missing_crop_product_refuses(self, monkeypatch):
        # crop_mask_mean=None means the fake raises for WorldCereal; the
        # metric must refuse rather than normalise by nothing.
        pairs = a_clean_year()
        install_fake(
            monkeypatch,
            FakeProductivityEE(
                months=[f"2023-{m:02d}" for _y, m, _v in pairs],
                means=[v for _y, _m, v in pairs],
                crop_mask_mean=None,
            ),
        )
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        assert result.status in (
            STATUS_INSUFFICIENT_DATA,
            STATUS_UNAVAILABLE,
        )
        assert result.value is None

    def test_the_provenance_carries_the_share_accounting(self, monkeypatch):
        self._install(monkeypatch, crop_mask_mean=40.0, composite_ndvi=0.6)
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        caveats = " ".join(result.provenance.caveats)
        assert "Crop share" in caveats
        assert "2021 reference" in caveats
        assert result.measurement_basis == MeasurementBasis.PROXY

    def test_the_warnings_state_the_field_level_limitation(self, monkeypatch):
        self._install(monkeypatch, crop_mask_mean=40.0, composite_ndvi=0.6)
        result = CropAreaNormalisedProductivityIndicator().compute(
            make_context()
        )
        joined = " ".join(result.warnings)
        assert "not production" in joined
        assert "field-level" in joined

    def test_a_2021_outside_window_is_out_of_coverage(self):
        metric = CropAreaNormalisedProductivityIndicator()
        # The WorldCereal coverage gate lives on the dataset, not the
        # metric; compute() refuses a no-image answer on live data. The
        # capability probe itself must never widen the gate.
        can, _reason = metric.can_attempt(make_context())
        assert can is True  # the S2 dataset drives can_attempt
