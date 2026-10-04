"""Tests for the P4.2 thermal temporal profile and harmonization contract.

Locks the observation layer built on the P4.1 foundation: the MODIS
LST monthly profile (``LST_PROFILE``), the ERA5-Land 2 m
air-temperature monthly profile (``AIR_TEMPERATURE_PROFILE``), exact
source/window/band/quantity identity, chronological ordering, exact
window preservation, missing/unavailable/insufficient handling with
no fill or interpolation, MOD11A2/MOD11A1 fallback semantics (single
selected source, never double-counted), per-point provenance, the
monthly harmonization contract (sides kept separate, never averaged,
no canopy quantity), serialization round-trips, determinism,
lineage, quality/coverage propagation, limitation preservation, and
the no-interpretation guards.

Earth Engine calls run against small per-month fakes, so the real
compute paths execute without credentials. No network is required.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.core.exceptions import DateRangeError
from app.services.agriculture.base import MetricContext
from app.services.agriculture.climate import ERA5_DAILY
from app.services.agriculture.thermal import MODIS_LST_8DAY, MODIS_LST_DAILY
from app.services.agriculture.thermal_profile import (
    AIR_METRIC_KEY,
    AIR_SOURCE_BAND,
    HARMONIZATION_METHOD,
    HARMONIZATION_MONTHLY,
    LST_METRIC_KEY,
    LST_SOURCE_BAND,
    PHYSICAL_QUANTITY_AIR,
    PHYSICAL_QUANTITY_LST,
    STEP_CALENDAR_MONTH,
    SUPPORTED_THERMAL_PROFILE_METRICS,
    THERMAL_PROFILE_KIND_AIR,
    THERMAL_PROFILE_KIND_LST,
    ThermalHarmonizedProfile,
    ThermalSourceProfile,
    build_air_temperature_profile,
    build_lst_profile,
    build_thermal_harmonized_monthly,
    build_thermal_source_profile,
    harmonize_thermal_monthly,
    month_windows,
    thermal_metadata,
    usable_values,
)
from app.utils.dates import get_monthly_periods

LST_RAW_300K = 15000.0  # 15000 x 0.02 = 300 K = 26.85 degC
LST_RAW_FALLBACK = 17000.0  # 340 K decoy: must never leak into the profile
AIR_KELVIN = 290.0  # 16.85 degC

NO_DATA = object()
AREA_SQ_M = 10000.0


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {"type": "Point", "coordinates": [51.0, 35.0]},
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": AREA_SQ_M},
    }
    fields.update(overrides)
    return MetricContext(**fields)


# --------------------------------------------------------------------------
# Fake Earth Engine with per-month outcomes and call recording
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
    """Values resolve per requested month start; calls are recorded."""

    def __init__(self, fake, dataset_id) -> None:
        self._fake = fake
        self._dataset_id = dataset_id
        self._band: Optional[str] = None
        self._values: List[Any] = []
        self._start: Optional[str] = None
        self._end: Optional[str] = None

    def filterDate(self, start, end):
        self._start = start
        self._end = end
        self._fake.calls.append(
            {"dataset": self._dataset_id, "start": start, "end": end}
        )
        if start in self._fake.fail_months:
            raise RuntimeError(f"fake EE failure for month {start}")
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        band = bands[0]
        month_fixture = self._fake.by_month.get(self._start or "", {})
        dataset_fixture = month_fixture.get(
            self._dataset_id, self._fake.default.get(self._dataset_id, {})
        )
        if band not in dataset_fixture:
            raise KeyError(
                f"fake dataset {self._dataset_id!r} has no band {band!r}"
            )
        self._band = band
        self._values = list(dataset_fixture[band])
        return self

    def size(self):
        return _FakeNumber(len(self._values))

    def map(self, func):
        return _FakeMapped(
            [func(_FakeImage(self._band, value)) for value in self._values]
        )

    def mean(self):
        return _FakeImage(self._band, list(self._values))


class FakeEE:
    """Per-month fixtures plus a default; records every observation call."""

    def __init__(self, by_month=None, default=None, fail_months=()) -> None:
        self.by_month: Dict[str, Dict[str, Dict[str, list]]] = dict(
            by_month or {}
        )
        self.default: Dict[str, Dict[str, list]] = dict(default or {})
        self.fail_months = set(fail_months)
        self.calls: List[Dict[str, str]] = []
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802
        return _FakeCollection(self, dataset_id)


@pytest.fixture
def fake_ee(monkeypatch):
    installed = {}

    def install(by_month=None, default=None, fail_months=()):
        import sys
        import types

        module = types.ModuleType("ee")
        fake = FakeEE(by_month, default, fail_months)
        module.ImageCollection = fake.ImageCollection
        module.Reducer = fake.Reducer
        module.Filter = fake.Filter
        monkeypatch.setitem(sys.modules, "ee", module)
        installed["fake"] = fake
        return fake

    install.fake = lambda: installed["fake"]
    return install


def _lst_default(raw_values) -> dict:
    return {MODIS_LST_8DAY: {LST_SOURCE_BAND: list(raw_values)}}


def _air_default(values) -> dict:
    return {ERA5_DAILY: {AIR_SOURCE_BAND: list(values)}}


def _combined_default(lst_raw, air_k) -> dict:
    merged = _lst_default(lst_raw)
    merged.update(_air_default(air_k))
    return merged


# --------------------------------------------------------------------------
# 1-2. MODIS LST profile construction and source identity
# --------------------------------------------------------------------------


def test_lst_profile_builds_one_point_per_calendar_month(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(make_context())
    assert profile.profile_kind == THERMAL_PROFILE_KIND_LST
    assert profile.metric_key == LST_METRIC_KEY
    assert profile.step == STEP_CALENDAR_MONTH
    assert profile.n_points == 3
    assert [p.window_start for p in profile.points] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
    ]
    for point in profile.points:
        assert point.value == pytest.approx(26.85)
        assert point.unit == "degC"


def test_lst_source_and_band_identity(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(make_context())
    assert profile.dataset_id == MODIS_LST_8DAY
    assert profile.band == LST_SOURCE_BAND
    for point in profile.points:
        assert point.source_dataset_id == MODIS_LST_8DAY
        assert point.source_band == LST_SOURCE_BAND


def test_lst_physical_quantity_is_skin_not_canopy_or_air(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(make_context())
    assert profile.physical_quantity == PHYSICAL_QUANTITY_LST == (
        "land_surface_temperature"
    )
    assert profile.measurement_basis == "product"
    for point in profile.points:
        assert point.physical_quantity == "land_surface_temperature"
    assert "canopy_temperature" not in profile.physical_quantity
    assert profile.physical_quantity != "air_temperature_2m"


# --------------------------------------------------------------------------
# 3-4. ERA5 air-temperature profile and quantity separation
# --------------------------------------------------------------------------


def test_air_profile_builds_one_point_per_calendar_month(fake_ee):
    fake_ee(default=_air_default([AIR_KELVIN] * 5))
    profile = build_air_temperature_profile(make_context())
    assert profile.profile_kind == THERMAL_PROFILE_KIND_AIR
    assert profile.metric_key == AIR_METRIC_KEY
    assert profile.step == STEP_CALENDAR_MONTH
    assert profile.n_points == 3
    for point in profile.points:
        assert point.value == pytest.approx(16.85)
        assert point.unit == "degC"


def test_air_source_band_and_modelled_identity(fake_ee):
    fake_ee(default=_air_default([AIR_KELVIN] * 5))
    profile = build_air_temperature_profile(make_context())
    assert profile.dataset_id == ERA5_DAILY
    assert profile.band == AIR_SOURCE_BAND
    assert profile.physical_quantity == PHYSICAL_QUANTITY_AIR == (
        "air_temperature_2m"
    )
    assert profile.measurement_basis == "modelled"
    for point in profile.points:
        assert point.source_dataset_id == ERA5_DAILY
        assert point.source_band == AIR_SOURCE_BAND
        assert point.physical_quantity == "air_temperature_2m"


def test_lst_and_air_quantities_stay_distinct(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    air = build_air_temperature_profile(make_context())
    assert THERMAL_PROFILE_KIND_LST != THERMAL_PROFILE_KIND_AIR
    assert lst.profile_kind == "LST_PROFILE"
    assert air.profile_kind == "AIR_TEMPERATURE_PROFILE"
    assert "temperature_profile" not in (
        lst.profile_kind,
        air.profile_kind,
    )
    assert lst.dataset_id != air.dataset_id
    assert lst.band != air.band
    assert lst.points[0].value != pytest.approx(air.points[0].value)


# --------------------------------------------------------------------------
# 5-6. Native temporal semantics and chronological ordering
# --------------------------------------------------------------------------


def test_native_temporal_semantics_preserved(fake_ee):
    fake = fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    air = build_air_temperature_profile(make_context())
    # Registry-native cadence is reported, not homogenised.
    assert lst.temporal_resolution == "8 days"
    assert air.temporal_resolution == "daily"
    # Both sides keep the audited window-mean contract.
    assert lst.aggregation_method == "time mean, then spatial mean"
    assert air.aggregation_method == "time mean, then spatial mean"
    # Source observation counts travel with the points; a 91-day
    # window yields 3 monthly observations, never 91 daily slots.
    assert lst.n_points == 3
    assert air.n_points == 3
    assert lst.points[0].image_count == 6
    assert air.points[0].image_count == 5
    assert {c["dataset"] for c in fake.calls} == {
        MODIS_LST_8DAY,
        ERA5_DAILY,
    }


def test_points_are_chronological_with_exact_windows(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    context = make_context()
    profile = build_lst_profile(context)
    expected = get_monthly_periods(context.start_date, context.end_date)
    assert [(p.window_start, p.window_end) for p in profile.points] == (
        expected
    )
    starts = [p.window_start for p in profile.points]
    assert starts == sorted(starts)
    for point, (start, end) in zip(profile.points, expected):
        assert point.window_start == start
        assert point.window_end == end
        # The point window is the window the metric actually ran.
        assert point.provenance["requested_start"] == start
        assert point.provenance["requested_end"] == end
        assert point.provenance["date_start"] == start
        assert point.provenance["date_end"] == end


# --------------------------------------------------------------------------
# 7-9. Missingness: gaps, unavailable coverage, insufficient quality
# --------------------------------------------------------------------------


def test_missing_month_stays_missing_without_zero_fill(fake_ee):
    fake_ee(
        by_month={
            "2024-02-01": {MODIS_LST_8DAY: {LST_SOURCE_BAND: []}},
        },
        default=_lst_default([LST_RAW_300K] * 6),
    )
    profile = build_lst_profile(make_context())
    assert profile.points[0].value == pytest.approx(26.85)
    gap = profile.points[1]
    assert gap.value is None
    assert gap.window_start == "2024-02-01"
    assert profile.points[2].value == pytest.approx(26.85)
    # Neighbours are untouched by the gap; gaps are dropped, not filled.
    assert usable_values(profile) == pytest.approx([26.85, 26.85])


def test_full_window_outside_coverage_is_unavailable_without_ee(fake_ee):
    fake = fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(
        make_context(start_date="1999-01-01", end_date="1999-03-31")
    )
    assert profile.n_points == 3
    assert profile.n_usable == 0
    for point in profile.points:
        assert point.value is None
        assert point.quality == "unavailable"
    assert fake.calls == []


def test_partially_covered_window_marks_only_outer_months(fake_ee):
    fake = fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(
        make_context(start_date="2000-01-01", end_date="2000-03-31")
    )
    # MODIS coverage starts 2000-02-18: January cannot be attempted.
    assert profile.points[0].value is None
    assert profile.points[0].quality == "unavailable"
    assert profile.points[1].value == pytest.approx(26.85)
    assert profile.points[2].value == pytest.approx(26.85)
    assert [c["start"] for c in fake.calls] == [
        "2000-02-01",
        "2000-03-01",
    ]


def test_insufficient_quality_preserved_verbatim(fake_ee):
    fake_ee(
        by_month={
            "2024-02-01": {MODIS_LST_8DAY: {LST_SOURCE_BAND: []}},
        },
        default=_lst_default([LST_RAW_300K] * 6),
    )
    profile = build_lst_profile(make_context())
    gap = profile.points[1]
    assert gap.value is None
    assert gap.quality == "insufficient"
    assert gap.source_dataset_id == MODIS_LST_8DAY


def test_poor_but_usable_month_keeps_its_value_and_quality(fake_ee):
    # A wide geometry estimate drops coverage below 40% while the
    # image count still clears the MODIS floor: the verdict is POOR
    # yet the month carries a value with its caveat intact.
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    context = make_context(options={"area_sq_m": 20_000_000.0})
    profile = build_lst_profile(context)
    assert profile.points[0].value == pytest.approx(26.85)
    assert profile.points[0].quality == "poor"
    assert profile.points[0].coverage_percent == pytest.approx(30.0)


# --------------------------------------------------------------------------
# 10-11. No interpolation, no substitution, failed months
# --------------------------------------------------------------------------


def test_no_interpolation_across_gap(fake_ee):
    fake_ee(
        by_month={
            "2024-01-01": {
                MODIS_LST_8DAY: {LST_SOURCE_BAND: [14000.0] * 6}
            },
            "2024-02-01": {MODIS_LST_8DAY: {LST_SOURCE_BAND: []}},
            "2024-03-01": {
                MODIS_LST_8DAY: {LST_SOURCE_BAND: [16000.0] * 6}
            },
        },
        default=_lst_default([LST_RAW_300K] * 6),
    )
    profile = build_lst_profile(make_context())
    # 14000 x 0.02 = 280 K = 6.85 degC; 16000 x 0.02 = 320 K = 46.85.
    assert profile.points[0].value == pytest.approx(6.85)
    assert profile.points[1].value is None
    assert profile.points[2].value == pytest.approx(46.85)
    assert usable_values(profile) == pytest.approx([6.85, 46.85])


def test_no_nearest_observation_substitution_on_failure(fake_ee):
    fake_ee(
        default=_lst_default([LST_RAW_300K] * 6),
        fail_months={"2024-02-01"},
    )
    profile = build_lst_profile(make_context())
    failed = profile.points[1]
    assert failed.value is None
    # The failed month keeps its own window identity; it does not
    # borrow a neighbour's value or window.
    assert failed.window_start == "2024-02-01"
    assert failed.window_end == "2024-02-29"
    assert failed.quality == "unavailable"
    assert profile.points[0].value == pytest.approx(26.85)
    assert profile.points[2].value == pytest.approx(26.85)


# --------------------------------------------------------------------------
# 12-13. MODIS fallback semantics
# --------------------------------------------------------------------------


def test_fallback_product_is_never_double_counted(fake_ee):
    fake = fake_ee(
        default={
            MODIS_LST_8DAY: {LST_SOURCE_BAND: [LST_RAW_300K] * 6},
            MODIS_LST_DAILY: {LST_SOURCE_BAND: [LST_RAW_FALLBACK] * 6},
        }
    )
    profile = build_lst_profile(make_context())
    # Value follows the primary 8-day source only (26.85 degC); the
    # daily fallback decoy (66.85 degC) and any average of the two
    # (46.85 degC) must not appear.
    for point in profile.points:
        assert point.value == pytest.approx(26.85)
        assert point.value != pytest.approx(46.85)
    assert {c["dataset"] for c in fake.calls} == {MODIS_LST_8DAY}
    assert profile.fallback_dataset_id == MODIS_LST_DAILY


def test_selected_source_exposed_in_provenance(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    profile = build_lst_profile(make_context())
    for point in profile.points:
        assert point.provenance["source_dataset_id"] == MODIS_LST_8DAY
        assert point.provenance["bands"] == [LST_SOURCE_BAND]
        assert point.provenance.get("fallback_from") is None


# --------------------------------------------------------------------------
# 14-15. Provenance and aggregation lineage
# --------------------------------------------------------------------------


def test_point_provenance_is_complete(fake_ee):
    from app.services.agriculture.registry import get_dataset

    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    point = lst.points[0]
    provenance = point.provenance
    assert provenance["source_dataset_id"] == MODIS_LST_8DAY
    assert provenance["bands"] == [LST_SOURCE_BAND]
    assert provenance["formula"]
    assert provenance["unit"] == "degC"
    assert provenance["spatial_resolution"]
    assert provenance["temporal_resolution"] == "8 days"
    assert provenance["aggregation_method"]
    assert provenance["image_count"] == 6
    assert provenance["limitations"]
    assert provenance["citation"]
    band = get_dataset(MODIS_LST_8DAY).band(LST_SOURCE_BAND)
    assert (band.unit, band.scale_factor, band.offset) == ("K", 0.02, 0.0)
    assert point.temporal_resolution == "8 days"
    assert point.aggregation_method == "time mean, then spatial mean"

    air = build_air_temperature_profile(make_context())
    air_point = air.points[0]
    assert air_point.provenance["source_dataset_id"] == ERA5_DAILY
    assert air_point.provenance["bands"] == [AIR_SOURCE_BAND]
    assert air_point.temporal_resolution == "daily"


def test_thermal_metadata_reports_scale_offset_and_basis():
    lst_meta = thermal_metadata(LST_METRIC_KEY)
    assert lst_meta["native_unit"] == "K"
    assert lst_meta["scale_factor"] == pytest.approx(0.02)
    assert lst_meta["offset"] == pytest.approx(0.0)
    assert lst_meta["measurement_basis"] == "product"
    air_meta = thermal_metadata(AIR_METRIC_KEY)
    assert air_meta["scale_factor"] == pytest.approx(1.0)
    assert air_meta["measurement_basis"] == "modelled"


# --------------------------------------------------------------------------
# 16-18. Harmonized monthly periods
# --------------------------------------------------------------------------


def test_harmonized_months_pair_both_sides(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    harmonized = build_thermal_harmonized_monthly(make_context())
    assert harmonized.harmonization == HARMONIZATION_MONTHLY
    assert harmonized.harmonization_method == HARMONIZATION_METHOD
    assert harmonized.n_periods == 3
    assert harmonized.n_with_both == 3
    for period in harmonized.periods:
        assert period.lst is not None and period.air is not None
        assert period.lst.value == pytest.approx(26.85)
        assert period.air.value == pytest.approx(16.85)


def test_harmonized_sides_remain_separate_without_generic_scalar(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    harmonized = build_thermal_harmonized_monthly(make_context())
    payload = harmonized.to_dict()

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(payload))
    assert "lst_celsius" in keys
    assert "air_temperature_celsius" in keys
    assert "temperature" not in keys
    assert "canopy_temperature" not in keys
    period = harmonized.periods[0].to_dict()
    assert period["lst_celsius"] == pytest.approx(26.85)
    assert period["air_temperature_celsius"] == pytest.approx(16.85)
    # No averaging of the two quantities anywhere in the payload.
    blob = json.dumps(payload)
    assert "21.85" not in blob  # (26.85 + 16.85) / 2 must not appear


def test_harmonized_partial_coverage_keeps_present_side(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    context = make_context(
        start_date="1999-12-01", end_date="2000-03-31"
    )
    harmonized = build_thermal_harmonized_monthly(context)
    assert harmonized.n_periods == 4
    # ERA5 covers the whole window; MODIS only from 2000-02-18.
    assert harmonized.n_with_air == 4
    assert harmonized.n_with_lst == 2
    first = harmonized.periods[0]
    assert first.lst is not None and first.lst.value is None
    assert first.air is not None and first.air.value == pytest.approx(
        16.85
    )
    last = harmonized.periods[-1]
    assert last.lst is not None and last.lst.value == pytest.approx(26.85)


def test_harmonize_rejects_swapped_or_foreign_profiles(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    air = build_air_temperature_profile(make_context())
    with pytest.raises(ValueError):
        harmonize_thermal_monthly(air, lst)
    with pytest.raises(ValueError):
        harmonize_thermal_monthly(air, air)
    foreign = replace(lst, profile_kind="ndvi")
    with pytest.raises(ValueError):
        harmonize_thermal_monthly(foreign, air)


# --------------------------------------------------------------------------
# 19-21. Serialization, determinism, lineage
# --------------------------------------------------------------------------


def test_serialization_round_trip(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    blob = json.loads(json.dumps(lst.to_dict()))
    rebuilt = ThermalSourceProfile.from_dict(blob)
    assert rebuilt.to_dict() == lst.to_dict()

    harmonized = build_thermal_harmonized_monthly(make_context())
    h_blob = json.loads(json.dumps(harmonized.to_dict()))
    h_rebuilt = ThermalHarmonizedProfile.from_dict(h_blob)
    assert h_rebuilt.to_dict() == harmonized.to_dict()
    assert h_rebuilt.periods[0].to_dict()["lst_celsius"] == pytest.approx(
        26.85
    )


def _scrub_computed_at(node):
    if isinstance(node, dict):
        return {
            key: _scrub_computed_at(value)
            for key, value in node.items()
            if key != "computed_at"
        }
    if isinstance(node, list):
        return [_scrub_computed_at(item) for item in node]
    return node


def test_repeated_evaluation_is_deterministic(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    context = make_context()
    # Provenance carries a `computed_at` timestamp by repository
    # contract, so observation determinism is compared with that
    # volatile field scrubbed; values, windows, quality, coverage,
    # lineage, and methods must be exactly repeatable.
    first_lst = _scrub_computed_at(build_lst_profile(context).to_dict())
    second_lst = _scrub_computed_at(build_lst_profile(context).to_dict())
    assert first_lst == second_lst
    assert _scrub_computed_at(
        build_air_temperature_profile(context).to_dict()
    ) == _scrub_computed_at(
        build_air_temperature_profile(context).to_dict()
    )
    assert _scrub_computed_at(
        build_thermal_harmonized_monthly(context).to_dict()
    ) == _scrub_computed_at(
        build_thermal_harmonized_monthly(context).to_dict()
    )


def test_source_observation_lineage(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    harmonized = build_thermal_harmonized_monthly(make_context())
    for period in harmonized.periods:
        assert period.contributing_lst_windows == (
            (period.window_start, period.window_end),
        )
        assert period.contributing_air_windows == (
            (period.window_start, period.window_end),
        )
        assert period.lst is not None and period.air is not None
        assert (
            period.lst.provenance["requested_start"]
            == period.window_start
        )
        assert (
            period.air.provenance["requested_start"]
            == period.window_start
        )


# --------------------------------------------------------------------------
# 22-24. Quality, coverage, and limitation propagation
# --------------------------------------------------------------------------


def test_quality_propagates_verbatim_to_harmonized_periods(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    context = make_context()
    lst = build_lst_profile(context)
    air = build_air_temperature_profile(context)
    harmonized = harmonize_thermal_monthly(lst, air)
    for period, lst_point, air_point in zip(
        harmonized.periods, lst.points, air.points
    ):
        assert period.lst is not None and period.air is not None
        assert period.lst.quality == lst_point.quality
        assert period.air.quality == air_point.quality
        assert period.harmonization_method == HARMONIZATION_METHOD


def test_coverage_propagates_verbatim(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    air = build_air_temperature_profile(make_context())
    harmonized = harmonize_thermal_monthly(lst, air)
    for period, lst_point, air_point in zip(
        harmonized.periods, lst.points, air.points
    ):
        assert period.lst is not None and period.air is not None
        assert period.lst.coverage_percent == lst_point.coverage_percent
        assert period.air.coverage_percent == air_point.coverage_percent
        assert period.lst.image_count == lst_point.image_count
        assert period.air.image_count == air_point.image_count


def test_scientific_limitations_preserved(fake_ee):
    fake_ee(
        default=_combined_default([LST_RAW_300K] * 6, [AIR_KELVIN] * 5)
    )
    lst = build_lst_profile(make_context())
    air = build_air_temperature_profile(make_context())
    lst_text = " ".join(lst.limitations)
    assert "NOT canopy temperature" in lst_text
    assert "land surface temperature" in lst_text.lower()
    air_text = " ".join(air.limitations)
    assert "NOT canopy temperature" in air_text
    assert "11 km" in air_text
    harmonized = harmonize_thermal_monthly(lst, air)
    harm_text = " ".join(harmonized.limitations).lower()
    assert "never be averaged" in harm_text
    assert "canopy temperature" in harm_text


# --------------------------------------------------------------------------
# 25-27. Contract guards: support, windows, no interpretation
# --------------------------------------------------------------------------


def test_supported_metrics_registry_shape():
    assert set(SUPPORTED_THERMAL_PROFILE_METRICS) == {
        LST_METRIC_KEY,
        AIR_METRIC_KEY,
    }
    with pytest.raises(ValueError):
        build_thermal_source_profile("ndvi", make_context())
    with pytest.raises(ValueError):
        build_thermal_source_profile("temperature_profile", make_context())
    with pytest.raises(ValueError):
        build_thermal_source_profile("canopy_temperature", make_context())
    with pytest.raises(ValueError):
        thermal_metadata("vv")


def test_invalid_windows_rejected(fake_ee):
    fake_ee(default=_lst_default([LST_RAW_300K] * 6))
    with pytest.raises(DateRangeError):
        build_lst_profile(
            make_context(start_date="2024-03-31", end_date="2024-01-01")
        )
    with pytest.raises(DateRangeError):
        build_air_temperature_profile(
            make_context(start_date="2024-01-01", end_date="2024-01-01")
        )
    with pytest.raises(DateRangeError):
        build_thermal_harmonized_monthly(
            make_context(start_date="2024-03-01", end_date="2024-01-01")
        )


def test_no_thermal_interpretation_in_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "agriculture"
        / "thermal_profile.py"
    )
    code = re.sub(
        r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    for snippet in (
        "canopy_temperature",
        "z_score",
        "zscore",
        "percentile",
        "breakpoint",
        "anomaly",
        "stress",
        "pest",
        "disease",
        "risk",
        "fillna",
        "interpolate",
        "resample(",
        "asfreq",
    ):
        assert snippet not in code, f"thermal_profile: {snippet!r}"
    import app.services.agriculture.thermal_profile as module

    public = [name for name in dir(module) if not name.startswith("_")]
    blob = " ".join(public).lower()
    for snippet in ("anomaly", "stress", "risk", "pest", "canopy"):
        assert snippet not in blob, f"public API: {snippet!r}"


def test_month_windows_reuse_repository_semantic():
    assert month_windows("2024-01-01", "2024-03-31") == get_monthly_periods(
        "2024-01-01", "2024-03-31"
    )
