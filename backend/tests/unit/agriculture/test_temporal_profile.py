"""Tests for the P1.1 temporal-profile foundation.

Covers one-year and multi-year profiles, all seven supported
metrics, missing-observation preservation (never zero, never
filled), chronological ordering, per-point provenance, invalid and
empty windows, unsupported metrics, determinism, and the API
contract round-trip.

Earth Engine is exercised through a strict queue-based fake serving
one configured outcome per calendar month in chronological order.
No network and no credentials are required.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.core.exceptions import DateRangeError
from app.services.agriculture.base import MetricContext
from app.services.agriculture.temporal_profile import (
    SUPPORTED_PROFILE_METRICS,
    TemporalProfile,
    TemporalProfilePoint,
    build_temporal_profile,
    month_windows,
    usable_values,
)

AREA_SQ_M = 10000.0


@pytest.fixture(autouse=True)
def _clean_registry():
    from app.services.agriculture.catalog import clear_registry

    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": AREA_SQ_M},
    }
    fields.update(overrides)
    return MetricContext(**fields)


# ==========================================================================
# Queue-based fake Earth Engine (S2 index path + S1 radar path)
# ==========================================================================


class _FakeNumber:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def getInfo(self):
        return self._value

    def Or(self, _other):  # noqa: N802 - mirrors ee
        return self

    def Not(self):  # noqa: N802 - mirrors ee
        return self

    def eq(self, _other):
        return self


class _FakeReducer:
    def combine(self, _other, sharedInputs=False):  # noqa: N803 - mirrors ee
        return self


class _FakeReducerNamespace:
    @staticmethod
    def count():
        return _FakeReducer()

    @staticmethod
    def mean():
        return _FakeReducer()

    @staticmethod
    def median():
        return _FakeReducer()

    @staticmethod
    def stdDev():  # noqa: N802 - mirrors ee
        return _FakeReducer()

    @staticmethod
    def min():
        return _FakeReducer()

    @staticmethod
    def max():
        return _FakeReducer()

    @staticmethod
    def percentile(_values):
        return _FakeReducer()


class _FakeFilterNamespace:
    @staticmethod
    def eq(_key, _value):
        return ("eq",)

    @staticmethod
    def lte(_key, _value):  # noqa: N802 - mirrors ee
        return ("lte",)

    @staticmethod
    def listContains(_key, _value):  # noqa: N802 - mirrors ee
        return ("listContains",)


class _FakeImageNamespace:
    @staticmethod
    def constant(_value):
        return _FakeNumber(0)


_ALLOWED_BANDS = {"SCL", "B2", "B3", "B4", "B5", "B8", "B11", "VV", "VH"}


class _FakeRegion:
    def __init__(self, fake: "FakeProfileEE", scale: int = 10) -> None:
        self._fake = fake
        self._scale = scale

    def getInfo(self):
        return self._fake._pop_stats(self._scale)


class _FakeImage:
    def __init__(self, fake: "FakeProfileEE") -> None:
        self._fake = fake
        self._bands = set(_ALLOWED_BANDS)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in self._bands:
                raise KeyError(f"fake profile image holds {sorted(self._bands)}")
        return self

    def rename(self, name):
        self._bands.add(name)
        return self

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee
        return self

    def multiply(self, _factor):
        return self

    def normalizedDifference(self, _bands):  # noqa: N802 - mirrors ee
        return self

    def expression(self, _formula, _variables):
        return self

    def divide(self, _value):
        return self

    def exp(self):
        return self

    def add(self, _other):
        return self

    def eq(self, _other):
        return _FakeNumber(0)

    def reduceRegion(self, **kwargs):
        scale = kwargs.get("scale", 10)
        return _FakeRegion(self._fake, scale)


class _FakeMapped:
    def __init__(self, fake: "FakeProfileEE") -> None:
        self._fake = fake

    def median(self):
        return _FakeImage(self._fake)


class _FakeCollection:
    def __init__(self, fake: "FakeProfileEE") -> None:
        self._fake = fake

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
            if band not in _ALLOWED_BANDS:
                raise KeyError(f"fake profile collection holds {_ALLOWED_BANDS}")
        return self

    def size(self):
        return _FakeNumber(self._fake._peek_scenes())

    def map(self, func):
        func(_FakeImage(self._fake))
        return _FakeMapped(self._fake)

    def mean(self):
        return _FakeImage(self._fake)


class FakeProfileEE:
    """One queued outcome per reduced month, chronological order."""

    def __init__(self, outcomes: List[Dict[str, Any]]) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(outcomes)
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeCollection(self)

    def _peek_scenes(self) -> int:
        if not self._queue:
            raise AssertionError("fake profile queue exhausted on size()")
        return int(self._queue[0]["scenes"])

    def _pop_stats(self, scale: int = 10) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake profile queue exhausted on reduceRegion()")
        outcome = self._queue.popleft()
        mean = outcome["mean"]
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        value = float(mean)
        total = int(AREA_SQ_M / (scale * scale))
        return {
            "mean": value,
            "median": value,
            "min": value,
            "max": value,
            "stdDev": 0.0,
            "p10": value,
            "p25": value,
            "p75": value,
            "p90": value,
            "count": total,
        }


@pytest.fixture
def fake_profile(monkeypatch):
    def install(outcomes: List[Dict[str, Any]]) -> FakeProfileEE:
        fake = FakeProfileEE(outcomes)
        import ee

        for name in ("ImageCollection", "Reducer", "Filter", "Image"):
            monkeypatch.setattr(ee, name, getattr(fake, name))
        return fake

    return install


def _month(mean: Optional[float], scenes: int = 6) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


# ==========================================================================
# Supported set
# ==========================================================================


def test_supported_metrics_are_exactly_the_p1_candidates():
    assert sorted(SUPPORTED_PROFILE_METRICS) == [
        "msi",
        "ndmi",
        "ndre",
        "ndvi",
        "vh",
        "vh_vv",
        "vv",
    ]


def test_supported_metrics_are_registered_window_metrics():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import get_metric

    register_all_metrics()
    for key in SUPPORTED_PROFILE_METRICS:
        assert get_metric(key).key == key


# ==========================================================================
# One-year and multi-year profiles
# ==========================================================================


def test_one_year_profile_has_twelve_chronological_points(fake_profile):
    fake_profile([_month(0.50 + i * 0.01) for i in range(12)])
    profile = build_temporal_profile("ndvi", make_context())
    assert isinstance(profile, TemporalProfile)
    assert profile.metric_key == "ndvi"
    assert profile.unit == "index"
    assert profile.dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    assert profile.step == "calendar_month"
    assert profile.window_start == "2024-01-01"
    assert profile.window_end == "2024-12-31"
    assert profile.n_points == 12
    assert profile.n_usable == 12
    starts = [point.window_start for point in profile.points]
    assert starts == sorted(starts)
    assert starts[0] == "2024-01-01"
    assert starts[-1] == "2024-12-01"
    assert [point.value for point in profile.points] == [
        pytest.approx(0.50 + i * 0.01) for i in range(12)
    ]


def test_two_year_profile_has_twenty_four_points(fake_profile):
    fake_profile([_month(0.40) for _ in range(24)])
    context = make_context(start_date="2022-01-01", end_date="2023-12-31")
    profile = build_temporal_profile("ndmi", context)
    assert profile.n_points == 24
    assert profile.n_usable == 24
    assert profile.points[0].window_start == "2022-01-01"
    assert profile.points[-1].window_start == "2023-12-01"


def test_three_year_profile_has_thirty_six_points(fake_profile):
    fake_profile([_month(0.30) for _ in range(36)])
    context = make_context(start_date="2021-01-01", end_date="2023-12-31")
    profile = build_temporal_profile("ndvi", context)
    assert profile.n_points == 36
    assert profile.points[-1].window_end == "2023-12-31"


def test_month_windows_follow_the_repository_calendar_semantic():
    windows = month_windows("2024-03-15", "2024-05-10")
    assert windows[0] == ("2024-03-01", "2024-03-31")
    assert windows[-1] == ("2024-05-01", "2024-05-10")
    assert len(windows) == 3


# ==========================================================================
# Multiple supported metrics
# ==========================================================================


def test_each_supported_metric_reports_its_own_dataset_and_unit(fake_profile):
    expected = {
        "ndvi": ("COPERNICUS/S2_SR_HARMONIZED", "index"),
        "ndmi": ("COPERNICUS/S2_SR_HARMONIZED", "index"),
        "ndre": ("COPERNICUS/S2_SR_HARMONIZED", "index"),
        "msi": ("COPERNICUS/S2_SR_HARMONIZED", "index"),
        "vv": ("COPERNICUS/S1_GRD", "dB"),
        "vh": ("COPERNICUS/S1_GRD", "dB"),
        "vh_vv": ("COPERNICUS/S1_GRD", "dB"),
    }
    for key, (dataset_id, unit) in expected.items():
        fake_profile([_month(-10.0), _month(-11.0), _month(-12.0)])
        context = make_context(start_date="2025-01-01", end_date="2025-03-31")
        profile = build_temporal_profile(key, context)
        assert profile.dataset_id == dataset_id, key
        assert profile.unit == unit, key
        assert profile.n_points == 3, key
        assert [point.value for point in profile.points] == [
            pytest.approx(-10.0),
            pytest.approx(-11.0),
            pytest.approx(-12.0),
        ], key


# ==========================================================================
# Missing observations are preserved, never filled or zeroed
# ==========================================================================


def test_gaps_stay_gaps_and_zero_stays_zero(fake_profile):
    fake_profile(
        [_month(0.60), _month(None, scenes=4), _month(0.0), _month(None, scenes=0)]
        + [_month(0.60) for _ in range(8)]
    )
    profile = build_temporal_profile("ndvi", make_context())
    values = [point.value for point in profile.points]
    assert values[0] == pytest.approx(0.60)
    assert values[1] is None
    assert values[2] == pytest.approx(0.0)
    assert values[3] is None
    assert profile.n_usable == 10
    assert usable_values(profile) == [pytest.approx(0.60), pytest.approx(0.0)] + [
        pytest.approx(0.60)
    ] * 8


def test_fully_masked_month_reports_insufficient_quality(fake_profile):
    fake_profile([_month(None, scenes=4)] + [_month(0.60) for _ in range(11)])
    profile = build_temporal_profile("ndvi", make_context())
    assert profile.points[0].value is None
    assert profile.points[0].quality == "insufficient"
    assert profile.points[0].image_count == 4


def test_no_scene_month_reports_unavailable_quality(fake_profile):
    fake_profile([_month(None, scenes=0)] + [_month(0.60) for _ in range(11)])
    profile = build_temporal_profile("ndvi", make_context())
    assert profile.points[0].value is None
    assert profile.points[0].quality == "unavailable"
    assert profile.points[0].image_count is None


def test_usable_values_selects_without_transforming(fake_profile):
    fake_profile([_month(0.20), _month(None), _month(0.80)])
    context = make_context(start_date="2025-01-01", end_date="2025-03-31")
    profile = build_temporal_profile("ndmi", context)
    assert usable_values(profile) == [pytest.approx(0.20), pytest.approx(0.80)]


# ==========================================================================
# Provenance preservation
# ==========================================================================


def test_every_point_carries_provenance_metadata(fake_profile):
    fake_profile([_month(-12.5) for _ in range(3)])
    context = make_context(start_date="2025-01-01", end_date="2025-03-31")
    profile = build_temporal_profile("vh", context)
    for point in profile.points:
        assert point.quality in ("excellent", "good", "moderate")
        assert point.image_count == 6
        assert point.coverage_percent == pytest.approx(100.0)
        assert point.unit == "dB"
    assert profile.points[0].window_start == "2025-01-01"
    assert profile.points[-1].window_end == "2025-03-31"


# ==========================================================================
# Invalid, empty, unsupported, and out-of-coverage windows
# ==========================================================================


def test_end_before_start_raises():
    with pytest.raises(DateRangeError):
        build_temporal_profile("ndvi", make_context(start_date="2024-12-31", end_date="2024-01-01"))


def test_equal_start_and_end_raises_as_empty():
    with pytest.raises(DateRangeError):
        build_temporal_profile("ndvi", make_context(start_date="2024-05-01", end_date="2024-05-01"))


def test_malformed_date_raises():
    with pytest.raises(DateRangeError):
        build_temporal_profile("ndvi", make_context(start_date="not-a-date"))


def test_unknown_metric_raises_with_supported_list():
    with pytest.raises(ValueError, match="Supported profile metrics"):
        build_temporal_profile("no_such_metric", make_context())


def test_registered_but_unsupported_metrics_raise(fake_profile):
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    for key in ("soil_field_capacity", "rvi", "ndvi_anomaly_absolute", "middle_canopy_dryness_proxy"):
        with pytest.raises(ValueError, match="not supported"):
            build_temporal_profile(key, make_context())


def test_out_of_coverage_window_emits_missing_months_without_ee(fake_profile):
    # Empty queue: any Earth Engine call would exhaust it and fail.
    fake_profile([])
    context = make_context(start_date="2010-01-01", end_date="2010-12-31")
    profile = build_temporal_profile("vh", context)
    assert profile.n_points == 12
    assert profile.n_usable == 0
    assert all(point.value is None for point in profile.points)


# ==========================================================================
# Determinism and contract round-trip
# ==========================================================================


def test_identical_inputs_give_identical_profiles(fake_profile):
    outcomes = [_month(0.55 + (i % 4) * 0.01) for i in range(12)]
    fake_profile(list(outcomes))
    first = build_temporal_profile("ndvi", make_context())
    fake_profile(list(outcomes))
    second = build_temporal_profile("ndvi", make_context())
    assert first == second


def test_to_dict_round_trips_through_the_api_contract_models():
    from app.schemas.agriculture import TemporalProfileModel

    profile = TemporalProfile(
        metric_key="ndvi",
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        unit="index",
        window_start="2025-01-01",
        window_end="2025-03-31",
        points=tuple(
            TemporalProfilePoint(
                window_start=f"2025-0{i + 1}-01",
                window_end=f"2025-0{i + 1}-28",
                value=0.50,
                unit="index",
                quality="good",
                coverage_percent=100.0,
                image_count=6,
            )
            for i in range(3)
        ),
    )
    model = TemporalProfileModel(**profile.to_dict())
    assert model.metric_key == "ndvi"
    assert len(model.points) == 3
    assert model.points[0].value == pytest.approx(0.50)
    assert model.step == "calendar_month"
