"""Tests for spatial aggregation and coverage reporting.

The behaviours that matter most here:

* A reduction that returned nothing must produce stats with no values and
  zero valid pixels, never a zero-valued statistic.
* Missing percentage must be derived consistently, so coverage is honest.
* Merging across time steps must not invent statistics that were absent.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture.aggregation import (
    PERCENTILE_VALUES,
    STAT_KEYS,
    estimate_pixel_count,
    merge_stats,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.types import SpatialStats


# --------------------------------------------------------------------------
# parse_reduction_result: the happy path
# --------------------------------------------------------------------------


def test_flat_reduction_is_parsed():
    raw = {
        "mean": 0.42,
        "median": 0.41,
        "min": 0.10,
        "max": 0.80,
        "stdDev": 0.12,
        "p10": 0.20,
        "p25": 0.30,
        "p75": 0.55,
        "p90": 0.70,
        "count": 1500,
    }
    stats = parse_reduction_result(raw, total_pixel_count=2000, pixel_area_sq_m=100.0)
    assert stats.mean == 0.42
    assert stats.median == 0.41
    assert stats.min == 0.10
    assert stats.max == 0.80
    assert stats.std_dev == 0.12
    assert stats.p10 == 0.20
    assert stats.p90 == 0.70
    assert stats.valid_pixel_count == 1500
    assert stats.total_pixel_count == 2000
    assert stats.valid_area_sq_m == pytest.approx(150000.0)
    assert stats.missing_pixel_count == 500
    assert stats.missing_percent == pytest.approx(25.0)
    assert stats.coverage_percent == pytest.approx(75.0)


def test_band_namespaced_reduction_is_parsed():
    raw = {
        "NDVI_mean": 0.42,
        "NDVI_median": 0.41,
        "NDVI_min": 0.10,
        "NDVI_max": 0.80,
        "NDVI_stdDev": 0.12,
        "NDVI_p10": 0.20,
        "NDVI_p25": 0.30,
        "NDVI_p75": 0.55,
        "NDVI_p90": 0.70,
        "NDVI_count": 800,
    }
    stats = parse_reduction_result(raw, band="NDVI", total_pixel_count=1000)
    assert stats.mean == 0.42
    assert stats.p90 == 0.70
    assert stats.valid_pixel_count == 800


def test_band_lookup_falls_back_to_bare_key():
    """Some reductions emit unsuffixed keys; those must still be read."""
    raw = {"mean": 0.5, "count": 100}
    stats = parse_reduction_result(raw, band="NDVI", total_pixel_count=100)
    assert stats.mean == 0.5
    assert stats.valid_pixel_count == 100


# --------------------------------------------------------------------------
# parse_reduction_result: the empty and degenerate cases
# --------------------------------------------------------------------------


def test_empty_reduction_yields_no_values_not_zero():
    """The central safety property: absence must not become zero."""
    stats = parse_reduction_result({}, total_pixel_count=1000)
    assert stats.mean is None
    assert stats.median is None
    assert stats.min is None
    assert stats.max is None
    assert stats.valid_pixel_count == 0
    assert not stats.has_values
    assert stats.coverage_percent == 0.0


def test_all_null_statistics_yields_no_values():
    raw = {key: None for key in STAT_KEYS}
    raw["count"] = 0
    stats = parse_reduction_result(raw, total_pixel_count=500)
    assert stats.mean is None
    assert not stats.has_values


def test_nan_statistics_are_discarded():
    raw = {"mean": float("nan"), "count": 10}
    stats = parse_reduction_result(raw, total_pixel_count=10)
    assert stats.mean is None


def test_infinite_statistics_are_discarded():
    raw = {"mean": float("inf"), "max": float("-inf"), "count": 10}
    stats = parse_reduction_result(raw, total_pixel_count=10)
    assert stats.mean is None
    assert stats.max is None


def test_stringified_numbers_are_coerced():
    """Earth Engine occasionally serialises numbers as strings."""
    raw = {"mean": "0.42", "count": "1500"}
    stats = parse_reduction_result(raw, total_pixel_count=2000)
    assert stats.mean == pytest.approx(0.42)
    assert stats.valid_pixel_count == 1500


def test_non_numeric_string_is_discarded():
    raw = {"mean": "not a number", "count": 10}
    stats = parse_reduction_result(raw, total_pixel_count=10)
    assert stats.mean is None


def test_boolean_statistic_is_discarded():
    raw = {"mean": True, "count": 10}
    stats = parse_reduction_result(raw, total_pixel_count=10)
    assert stats.mean is None


# --------------------------------------------------------------------------
# Coverage arithmetic
# --------------------------------------------------------------------------


def test_full_coverage():
    raw = {"mean": 0.5, "count": 100}
    stats = parse_reduction_result(raw, total_pixel_count=100)
    assert stats.missing_pixel_count == 0
    assert stats.missing_percent == pytest.approx(0.0)
    assert stats.coverage_percent == pytest.approx(100.0)


def test_total_never_below_valid():
    """A caller understating the total must not produce negative missing."""
    raw = {"mean": 0.5, "count": 500}
    stats = parse_reduction_result(raw, total_pixel_count=100)
    assert stats.total_pixel_count == 500
    assert stats.missing_pixel_count == 0
    assert stats.missing_percent == pytest.approx(0.0)


def test_explicit_valid_count_overrides_reported_count():
    raw = {"mean": 0.5, "count": 999}
    stats = parse_reduction_result(
        raw, total_pixel_count=1000, valid_pixel_count=250
    )
    assert stats.valid_pixel_count == 250
    assert stats.missing_percent == pytest.approx(75.0)


def test_negative_valid_count_is_clamped():
    raw = {"mean": 0.5}
    stats = parse_reduction_result(
        raw, total_pixel_count=100, valid_pixel_count=-5
    )
    assert stats.valid_pixel_count == 0


def test_zero_total_means_zero_coverage_not_full():
    raw = {"mean": 0.5, "count": 0}
    stats = parse_reduction_result(raw, total_pixel_count=0)
    assert stats.coverage_percent == 0.0


def test_valid_area_uses_pixel_area():
    raw = {"mean": 0.5, "count": 40}
    stats = parse_reduction_result(
        raw, total_pixel_count=40, pixel_area_sq_m=100.0
    )
    assert stats.valid_area_sq_m == pytest.approx(4000.0)


def test_missing_pixel_area_when_no_pixel_area_given():
    raw = {"mean": 0.5, "count": 40}
    stats = parse_reduction_result(raw, total_pixel_count=40)
    assert stats.valid_area_sq_m == 0.0


# --------------------------------------------------------------------------
# Pixel geometry helpers
# --------------------------------------------------------------------------


def test_pixel_area_sq_m():
    assert pixel_area_sq_m(10) == pytest.approx(100.0)
    assert pixel_area_sq_m(20) == pytest.approx(400.0)
    assert pixel_area_sq_m(500) == pytest.approx(250000.0)


def test_pixel_area_handles_bad_scale():
    assert pixel_area_sq_m(0) == 0.0
    assert pixel_area_sq_m(-5) == 0.0
    assert pixel_area_sq_m(None) == 0.0  # type: ignore[arg-type]


def test_estimate_pixel_count():
    # A 10 hectare field at 10 m resolution is 1000 pixels.
    assert estimate_pixel_count(100000.0, 10) == 1000


def test_estimate_pixel_count_rounds_down():
    """Rounding down avoids understating the missing percentage."""
    # 1050 sq m at 10 m scale is 10.5 pixels -> 10.
    assert estimate_pixel_count(1050.0, 10) == 10


def test_estimate_pixel_count_bad_inputs():
    assert estimate_pixel_count(None, 10) == 0
    assert estimate_pixel_count(0.0, 10) == 0
    assert estimate_pixel_count(-100.0, 10) == 0
    assert estimate_pixel_count(1000.0, 0) == 0


# --------------------------------------------------------------------------
# merge_stats
# --------------------------------------------------------------------------


def test_merge_empty_list():
    merged = merge_stats([])
    assert merged.mean is None
    assert merged.valid_pixel_count == 0


def test_merge_single_stats():
    original = SpatialStats(
        mean=0.4, median=0.4, min=0.1, max=0.8, p10=0.2, p25=0.3,
        p75=0.5, p90=0.7, valid_pixel_count=100, total_pixel_count=100,
    )
    merged = merge_stats([original])
    assert merged.mean == pytest.approx(0.4)
    assert merged.min == pytest.approx(0.1)
    assert merged.max == pytest.approx(0.8)


def test_merge_averages_means_and_sums_counts():
    a = SpatialStats(mean=0.4, valid_pixel_count=100, total_pixel_count=100)
    b = SpatialStats(mean=0.6, valid_pixel_count=100, total_pixel_count=100)
    merged = merge_stats([a, b])
    assert merged.mean == pytest.approx(0.5)
    assert merged.valid_pixel_count == 200


def test_merge_takes_extremes_across_inputs():
    a = SpatialStats(mean=0.4, min=0.1, max=0.6)
    b = SpatialStats(mean=0.5, min=0.05, max=0.9)
    merged = merge_stats([a, b])
    assert merged.min == pytest.approx(0.05)
    assert merged.max == pytest.approx(0.9)


def test_merge_weights_affect_the_mean():
    a = SpatialStats(mean=0.0, valid_pixel_count=10)
    b = SpatialStats(mean=1.0, valid_pixel_count=10)
    merged = merge_stats([a, b], weights=[3.0, 1.0])
    assert merged.mean == pytest.approx(0.25)


def test_merge_skips_stats_without_a_mean():
    a = SpatialStats(mean=0.4, valid_pixel_count=100)
    b = SpatialStats(mean=None, valid_pixel_count=50)
    merged = merge_stats([a, b])
    assert merged.mean == pytest.approx(0.4)
    assert merged.valid_pixel_count == 150


def test_merge_drops_medians_when_any_input_lacks_one():
    """An average of medians is not a median, so it must not be invented."""
    a = SpatialStats(mean=0.4, median=0.4)
    b = SpatialStats(mean=0.5, median=None)
    merged = merge_stats([a, b])
    assert merged.median is None


def test_merge_keeps_medians_when_all_inputs_have_them():
    a = SpatialStats(mean=0.4, median=0.35)
    b = SpatialStats(mean=0.5, median=0.45)
    merged = merge_stats([a, b])
    assert merged.median == pytest.approx(0.40)


def test_merge_percentiles_require_all_inputs():
    """A percentile missing from any input must not be averaged in.

    Here p10 is absent from the second input, so it cannot be reported.
    p90 is present in both, so averaging it is legitimate.
    """
    a = SpatialStats(mean=0.4, p10=0.1, p90=0.8)
    b = SpatialStats(mean=0.5, p10=None, p90=0.9)
    merged = merge_stats([a, b])
    assert merged.p10 is None
    assert merged.p90 == pytest.approx(0.85)


def test_merge_percentiles_all_absent_stays_absent():
    a = SpatialStats(mean=0.4)
    b = SpatialStats(mean=0.5)
    merged = merge_stats([a, b])
    assert merged.p10 is None
    assert merged.p25 is None
    assert merged.p75 is None
    assert merged.p90 is None


def test_merge_std_dev_of_means():
    a = SpatialStats(mean=0.0)
    b = SpatialStats(mean=1.0)
    merged = merge_stats([a, b])
    assert merged.std_dev is not None
    assert merged.std_dev == pytest.approx(0.5)


def test_merge_single_value_has_no_spread():
    """One sample has no dispersion; inventing zero dispersion would lie."""
    merged = merge_stats([SpatialStats(mean=0.5)])
    assert merged.std_dev is None


def test_merge_missing_percent_is_recomputed():
    a = SpatialStats(mean=0.4, valid_pixel_count=50, total_pixel_count=100)
    b = SpatialStats(mean=0.5, valid_pixel_count=50, total_pixel_count=100)
    merged = merge_stats([a, b])
    assert merged.valid_pixel_count == 100
    assert merged.total_pixel_count == 200
    assert merged.missing_percent == pytest.approx(50.0)


def test_merge_weight_length_mismatch_raises():
    a = SpatialStats(mean=0.4)
    b = SpatialStats(mean=0.5)
    with pytest.raises(ValueError):
        merge_stats([a, b], weights=[1.0])


def test_merge_ignores_none_entries():
    a = SpatialStats(mean=0.4, valid_pixel_count=10)
    merged = merge_stats([a, None])  # type: ignore[list-item]
    assert merged.mean == pytest.approx(0.4)


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------


def test_stat_keys_are_the_required_set():
    required = {
        "mean", "median", "min", "max", "stdDev",
        "p10", "p25", "p75", "p90",
    }
    assert set(STAT_KEYS) == required


def test_percentile_values_match_keys():
    assert set(PERCENTILE_VALUES) == {10, 25, 75, 90}


# --------------------------------------------------------------------------
# build_reducer with an injected fake ee module
# --------------------------------------------------------------------------


class _FakeReducer:
    """Minimal stand-in for an Earth Engine reducer, recording calls."""

    def __init__(self, name: str, calls: list):
        self.name = name
        self._calls = calls
        self._calls.append(name)

    def combine(self, other, sharedInputs=False):
        self._calls.append(("combine", other.name, sharedInputs))
        return self


class _FakeEEModule:
    def __init__(self):
        self.calls: list = []
        outer = self

        class _Reducers:
            @staticmethod
            def count():
                return _FakeReducer("count", outer.calls)

            @staticmethod
            def mean():
                return _FakeReducer("mean", outer.calls)

            @staticmethod
            def median():
                return _FakeReducer("median", outer.calls)

            @staticmethod
            def stdDev():
                return _FakeReducer("stdDev", outer.calls)

            @staticmethod
            def min():
                return _FakeReducer("min", outer.calls)

            @staticmethod
            def max():
                return _FakeReducer("max", outer.calls)

            @staticmethod
            def percentile(values):
                outer.calls.append(("percentile", tuple(values)))
                return _FakeReducer("percentile", outer.calls)

        self.Reducer = _Reducers()


def test_build_reducer_combines_all_statistics():
    from app.services.agriculture.aggregation import build_reducer

    fake = _FakeEEModule()
    build_reducer(fake)

    names = [c for c in fake.calls if isinstance(c, str)]
    for expected in ("count", "mean", "median", "stdDev", "min", "max"):
        assert expected in names, f"reducer missing {expected}"

    percentiles = [c for c in fake.calls if isinstance(c, tuple)]
    assert ("percentile", (10, 25, 75, 90)) in percentiles

    combines = [c for c in fake.calls if isinstance(c, tuple) and c[0] == "combine"]
    assert len(combines) == 6, "expected count + mean + 5 combined reducers"
    assert all(c[2] is True for c in combines), "sharedInputs must be True"
    # The count reducer must lead the chain: parse_reduction_result reads
    # valid_pixel_count from the 'count' key it emits, and coverage for
    # every quality verdict downstream is derived from that count.
    assert fake.calls[0] == "count", (
        "the combined reducer chain must start with the count reducer"
    )


# --------------------------------------------------------------------------
# Band scale factor and offset application
# --------------------------------------------------------------------------


def test_parse_without_a_band_spec_returns_raw_values():
    """The default is raw, because the caller may already have converted."""
    from app.services.agriculture.aggregation import parse_reduction_result

    raw = {
        "mean": 15000.0,
        "median": 15000.0,
        "min": 15000.0,
        "max": 15000.0,
        "stdDev": 0.0,
        "p10": 15000.0,
        "p25": 15000.0,
        "p75": 15000.0,
        "p90": 15000.0,
        "count": 4,
    }
    stats = parse_reduction_result(raw, band="LST_Day_1km")
    assert stats.mean == pytest.approx(15000.0)


def test_parse_with_a_band_spec_applies_the_scale_factor():
    """MODIS LST is stored as counts scaled by 0.02 K.

    This is the defect that motivated the parameter: a reduction returning
    15000 raw counts was being reported as a land surface temperature of
    fifteen thousand degrees, and the number was plausible enough at a
    glance that nothing caught it.
    """
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {
        "mean": 15000.0,
        "median": 15000.0,
        "min": 15000.0,
        "max": 15000.0,
        "stdDev": 100.0,
        "p10": 15000.0,
        "p25": 15000.0,
        "p75": 15000.0,
        "p90": 15000.0,
        "count": 4,
    }
    spec = get_dataset("MODIS/061/MOD11A2").band("LST_Day_1km")
    stats = parse_reduction_result(raw, band="LST_Day_1km", band_spec=spec)

    assert stats.mean == pytest.approx(300.0)
    assert stats.min == pytest.approx(300.0)
    assert stats.max == pytest.approx(300.0)


def test_parse_applies_the_offset_as_well_as_the_scale():
    """Landsat surface temperature needs both."""
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {"mean": 45000.0, "count": 4}
    spec = get_dataset("LANDSAT/LC08/C02/T1_L2").band("ST_B10")
    stats = parse_reduction_result(raw, band="ST_B10", band_spec=spec)

    # 45000 * 0.00341802 + 149.0
    assert stats.mean == pytest.approx(302.8109, abs=0.001)


def test_parse_drops_the_spread_when_the_conversion_has_an_offset():
    """A standard deviation does not take an offset.

    Landsat surface temperature has a +149 K offset. Converting a spread
    of 10 K by adding 149 would give 159, which is meaningless as a
    spread, so the value is dropped rather than mangled.
    """
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {"mean": 45000.0, "stdDev": 100.0, "count": 4}
    spec = get_dataset("LANDSAT/LC08/C02/T1_L2").band("ST_B10")
    stats = parse_reduction_result(raw, band="ST_B10", band_spec=spec)

    assert stats.std_dev is None
    # The point statistics still convert.
    assert stats.mean is not None


def test_parse_scales_the_spread_when_there_is_no_offset():
    """With a pure scale conversion the spread does convert."""
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {"mean": 0.005, "stdDev": 0.001, "count": 4}
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR").band(
        "total_precipitation_sum"
    )
    stats = parse_reduction_result(
        raw, band="total_precipitation_sum", band_spec=spec
    )
    # ERA5 uses a scale of 1.0 and no offset, so values pass through.
    assert stats.std_dev == pytest.approx(0.001)


def test_parse_drops_the_raw_nodata_sentinel():
    """A raw fill value must not survive as a physical measurement."""
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {"mean": 0.0, "count": 4}
    spec = get_dataset("MODIS/061/MOD11A2").band("LST_Day_1km")
    stats = parse_reduction_result(raw, band="LST_Day_1km", band_spec=spec)

    # Raw 0 is the fill, so there is no physical value.
    assert stats.mean is None


def test_parse_rejects_booleans_through_the_band_spec():
    """bool is an int subclass, so True would become the scale factor."""
    from app.services.agriculture.aggregation import parse_reduction_result
    from app.services.agriculture.registry import get_dataset

    raw = {"mean": True, "count": 4}
    spec = get_dataset("MODIS/061/MOD11A2").band("LST_Day_1km")
    stats = parse_reduction_result(raw, band="LST_Day_1km", band_spec=spec)
    assert stats.mean is None
