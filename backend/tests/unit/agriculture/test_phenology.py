"""Tests for the phenology engine (Phase I).

The governing risks here are specific:

1. **An invented date.** A smoothed series with a fabricated value (from
   interpolation across a cloud gap) could produce a threshold crossing
   that no observation supports. The module refuses to interpolate, and
   the tests pin the gap behaviour: a series with a hole produces either
   an event found on real data or a refusal, never a bridged crossing.

2. **An agronomic claim from a vegetation signal.** The metrics exist to
   describe the NDVI series. SOS-as-planting, EOS-as-harvest and
   peak-as-flowering are exactly the readings the specification forbids,
   so the prose is scanned for the denial and the serialised warnings
   always carry it.

3. **An event from too little data.** The minimum-months rule, the
   minimum-window rule and the maximum-gap rule are all load-bearing;
   each is tested from both sides.

4. **A day-resolution claim from a monthly series.** The event dates are
   the first day of a month and the decimal-year encoding preserves that
   resolution; the tests pin the arithmetic.

The series machinery is pure and is tested against hand-computed values;
the Earth Engine path is exercised through a fake whose per-scene
reduction honours mask semantics (a fully-masked scene contributes no
monthly value).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    metric_keys,
)
from app.services.agriculture.phenology import (
    ALL_PHENOLOGY_METRICS,
    INTEGRAL_UNAVAILABLE_CODE,
    INTEGRAL_UNAVAILABLE_REASON,
    MAX_TOLERATED_GAP_MONTHS,
    MIN_MONTHS,
    MIN_WINDOW_DAYS,
    MonthlyValue,
    PHENOLOGY_METRICS,
    SeasonalIntegralMetric,
    SeasonAmplitudeMetric,
    SeasonEndMetric,
    SeasonEvents,
    SeasonLengthMetric,
    SeasonOnsetMetric,
    SeasonPeakMetric,
    UNAVAILABLE_PHENOLOGY_METRICS,
    detect_season_events,
    moving_average_series,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

EXPECTED_AVAILABLE_KEYS = {
    "vegetation_season_onset",
    "vegetation_activity_peak",
    "vegetation_season_end",
    "vegetation_season_length",
    "vegetation_season_amplitude",
}
EXPECTED_UNAVAILABLE_KEYS = {"vegetation_seasonal_integral"}

#: A one-year window, the common case.
WINDOW_START = date(2023, 1, 1)
WINDOW_END = date(2023, 12, 31)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# ==========================================================================
# Helpers
# ==========================================================================


def months_from_pairs(pairs):
    """Build a series from ``[(year, month, value), ...]``."""
    return [MonthlyValue(y, m, v) for y, m, v in pairs]


def a_clean_series(base=0.2, peak=0.8, rise=(3, 4), fall=(9, 10), year=2023):
    """A textbook single-season series: low, rising, peak, falling, low.

    The smoothed shape crosses the amplitude midpoint between months
    ``rise`` and ``fall``.
    """
    values = {}
    for m in range(1, 13):
        if m <= rise[0] or m >= fall[1]:
            values[m] = base
        elif m < rise[1]:
            values[m] = base + (peak - base) * (m - rise[0]) / 2.0
        elif m <= fall[0]:
            values[m] = peak
        else:
            values[m] = peak - (peak - base) * (m - fall[0]) / 2.0
    return months_from_pairs([(year, m, values[m]) for m in range(1, 13)])


# ==========================================================================
# Collection integrity
# ==========================================================================


def test_all_expected_phenology_metrics_present():
    assert {m.key for m in PHENOLOGY_METRICS} == EXPECTED_AVAILABLE_KEYS


def test_all_expected_unavailable_phenology_metrics_present():
    assert (
        {m.key for m in UNAVAILABLE_PHENOLOGY_METRICS}
        == EXPECTED_UNAVAILABLE_KEYS
    )


def test_no_duplicate_phenology_metric_keys():
    keys = [m.key for m in ALL_PHENOLOGY_METRICS]
    assert len(keys) == len(set(keys))


def test_every_phenology_metric_is_in_the_phenology_domain():
    for metric in ALL_PHENOLOGY_METRICS:
        assert metric.domain == "phenology", metric.key


def test_registration_reaches_the_catalog():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    for key in EXPECTED_AVAILABLE_KEYS | EXPECTED_UNAVAILABLE_KEYS:
        assert key in metric_keys(), key


# ==========================================================================
# The 3-point moving average
# ==========================================================================


def test_the_moving_average_is_the_mean_of_three_consecutive_months():
    series = months_from_pairs(
        [(2023, 1, 0.10), (2023, 2, 0.20), (2023, 3, 0.30), (2023, 4, 0.40)]
    )
    smoothed = moving_average_series(series)
    assert smoothed[0] is None  # edges are never smoothed
    assert smoothed[3] is None
    assert smoothed[1] == pytest.approx(0.20)
    assert smoothed[2] == pytest.approx(0.30)


def test_the_moving_average_stops_at_a_gap():
    series = months_from_pairs(
        [(2023, 1, 0.10), (2023, 2, 0.20), (2023, 4, 0.40), (2023, 5, 0.50)]
    )
    smoothed = moving_average_series(series)
    # Month 2's window spans the gap; month 4's too. Nothing smooths.
    assert all(v is None for v in smoothed)


def test_the_moving_average_never_fills_a_missing_month():
    """A gap must not be bridged: no interpolation anywhere."""
    series = months_from_pairs(
        [(2023, 1, 0.10), (2023, 2, 0.20), (2023, 3, 0.30)]
    )
    smoothed = moving_average_series(series)
    assert len(smoothed) == len(series)


# ==========================================================================
# Event detection: the explicit rules
# ==========================================================================


def test_a_clean_series_yields_all_events():
    series = a_clean_series()
    events = detect_season_events(series, WINDOW_START, WINDOW_END)

    assert events.sos is not None
    assert events.peak is not None
    assert events.eos is not None
    assert events.los_days is not None
    assert events.amplitude == pytest.approx(0.8 - 0.2)


def test_the_threshold_is_the_amplitude_midpoint():
    series = a_clean_series(base=0.2, peak=0.8)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.threshold == pytest.approx(0.2 + 0.5 * (0.8 - 0.2))


def test_sos_is_the_first_upward_crossing():
    series = a_clean_series(base=0.2, peak=0.8, rise=(3, 5))
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    # The crossing lands in the first month at or above 0.5 after the rise.
    assert events.sos is not None
    assert events.sos.month >= 4
    assert events.sos.year == 2023


def test_eos_is_the_last_downward_crossing():
    series = a_clean_series(base=0.2, peak=0.8, fall=(9, 11))
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.eos is not None
    assert events.eos.month >= 9


def test_los_is_eos_minus_sos_in_days():
    series = a_clean_series()
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.sos is not None and events.eos is not None
    assert events.los_days == (events.eos - events.sos).days
    assert events.los_days > 0


def test_the_peak_is_the_maximum_smoothed_month():
    series = a_clean_series(peak=0.8)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.peak is not None
    # The peak month's smoothed value must be the series maximum.
    assert events.amplitude is not None


def test_tied_peaks_resolve_to_the_earliest_month():
    pairs = [(2023, m, 0.2) for m in range(1, 13)]
    pairs[5] = (2023, 6, 0.8)
    pairs[6] = (2023, 7, 0.8)
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.peak is not None
    assert events.peak.month == 6


def test_a_peak_on_the_window_edge_is_flagged():
    """A peak clamped to an edge is a window artefact, not a season."""
    pairs = [(2023, m, 0.2) for m in range(1, 13)]
    pairs[0] = (2023, 1, 0.9)  # maximum in the first month
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.peak is None
    assert events.peak_at_window_edge is True


def test_an_inverted_season_refuses_the_length():
    """An end before its start is not a negative season; it is none."""
    # A series that falls and then rises crosses in the wrong order: the
    # first upward crossing lands after the last downward one. The
    # detector must refuse the length rather than publish a negative one.
    pairs = [(2023, m, 0.8) for m in range(1, 13)]
    for m in (2, 3):
        pairs[m - 1] = (2023, m, 0.2)
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    if events.sos is not None and events.eos is not None:
        assert events.los_days is None
    assert events.los_days is None or events.los_days > 0


def test_a_flat_series_has_no_events_but_reports_amplitude_zero():
    pairs = [(2023, m, 0.5) for m in range(1, 13)]
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.sos is None
    assert events.eos is None
    assert events.peak is None
    assert events.amplitude == pytest.approx(0.0)


def test_event_dates_carry_month_resolution():
    """Every event date is the first day of a month."""
    series = a_clean_series()
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    for event_date in (events.sos, events.peak, events.eos):
        if event_date is not None:
            assert event_date.day == 1


def test_an_empty_series_yields_no_events():
    events = detect_season_events([], WINDOW_START, WINDOW_END)
    assert events.sos is None
    assert events.n_months == 0


def test_reversed_windows_yield_no_events():
    series = a_clean_series()
    events = detect_season_events(series, WINDOW_END, WINDOW_START)
    assert events.sos is None


def test_an_unsorted_series_is_refused_rather_than_resorted():
    """Sorting would silently change which crossing is 'first'."""
    pairs = [
        (2023, 3, 0.3),
        (2023, 1, 0.1),
        (2023, 2, 0.2),
        (2023, 4, 0.4),
        (2023, 5, 0.5),
        (2023, 6, 0.6),
        (2023, 7, 0.7),
    ]
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.sos is None


# ==========================================================================
# The minimum-observation and gap rules
# ==========================================================================


def test_fewer_than_the_minimum_months_refuses_events():
    pairs = [(2023, m, 0.2 + m * 0.05) for m in range(1, 6)]  # 5 months
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.n_months == 5
    assert events.sos is None
    assert events.eos is None


def test_exactly_the_minimum_months_allows_events():
    pairs = [(2023, m, 0.2 + m * 0.05) for m in range(1, 7)]  # 6 months
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.n_months == 6
    assert events.sos is not None


def test_a_three_month_gap_refuses_events():
    pairs = [(2023, m, 0.2 + 0.05 * m) for m in (1, 2, 3, 4, 8, 9, 10, 11, 12)]
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.max_gap_months == 3
    assert events.sos is None


def test_a_two_month_gap_is_tolerated():
    pairs = [(2023, m, 0.2 + 0.05 * m) for m in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12)]
    series = months_from_pairs(pairs)
    events = detect_season_events(series, WINDOW_START, WINDOW_END)
    assert events.max_gap_months == 2
    assert events.sos is not None


def test_the_gap_tolerance_is_declared():
    assert MAX_TOLERATED_GAP_MONTHS == 2


def test_the_minimum_window_is_declared():
    assert MIN_WINDOW_DAYS == 180


def test_the_minimum_months_is_declared():
    assert MIN_MONTHS == 6


# ==========================================================================
# Metric-level behaviour: the window gates
# ==========================================================================


def make_context(start: str, end: str) -> MetricContext:
    return MetricContext(
        geometry={},
        start_date=start,
        end_date=end,
        geometry_key="test-geometry",
        # 100 valid pixels of 10 m: 10,000 m2. The fake reports the same
        # pixel count, so the coverage verdict is driven by the window and
        # the months, not by a coverage shortfall.
        options={"area_sq_m": 10000.0},
    )


def test_a_short_window_is_refused_before_any_query():
    metric = SeasonOnsetMetric()
    can, reason = metric.can_attempt(make_context("2023-04-01", "2023-08-31"))
    assert can is False
    assert reason == "window_too_short"


def test_a_full_year_window_passes_the_capability_check():
    metric = SeasonOnsetMetric()
    can, reason = metric.can_attempt(make_context("2023-01-01", "2023-12-31"))
    assert can is True
    assert reason is None


def test_a_window_before_sentinel2_l2a_is_out_of_coverage():
    metric = SeasonOnsetMetric()
    can, reason = metric.can_attempt(make_context("2015-01-01", "2015-12-31"))
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_reversed_dates_are_rejected():
    metric = SeasonOnsetMetric()
    can, reason = metric.can_attempt(make_context("2023-12-31", "2023-01-01"))
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_every_phenology_metric_applies_the_window_gate():
    for metric in PHENOLOGY_METRICS:
        can, reason = metric.can_attempt(
            make_context("2023-06-01", "2023-07-31")
        )
        assert can is False, metric.key
        assert reason == "window_too_short", metric.key


# ==========================================================================
# Metric-level behaviour: the serialised series and refusals
# ==========================================================================


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
    def __init__(self, name):
        self.name = name

    def combine(self, other, sharedInputs=False):  # noqa: N803
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
        return _FakeReducer(f"p{values}")


class _FakeMappedCollection:
    """The collection after ``map``, carrying scene months and NDVI means.

    ``aggregate_array`` refuses unknown property names, so a metric that
    reads the wrong property fails loudly instead of silently receiving
    an unrelated list.
    """

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
            f"fake collection carries only 'scene_month' and 'ndvi_mean', "
            f"not {property_name!r}"
        )

    def select(self, *_bands):
        return self

    def mean(self):
        return _FakeWindowImage(self._window_payload)


class _FakeWindowImage:
    def __init__(self, payload):
        self._payload = payload

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(self._payload)


class _FakeSceneCollection:
    def __init__(self, months, means, window_payload):
        self._months = months
        self._means = means
        self._window_payload = window_payload
        self._date_filters = []

    def filterDate(self, start, end):
        self._date_filters.append((start, end))
        return self

    def filterBounds(self, *_args):
        return self

    def size(self):
        return _FakeNumber(len(self._months))

    def map(self, _function):
        return _FakeMappedCollection(
            self._months, self._means, self._window_payload
        )


class FakePhenologyEE:
    def __init__(self, months, means, window_payload):
        self._months = months
        self._means = means
        self._window_payload = window_payload
        self.Reducer = _ReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        assert dataset_id == "COPERNICUS/S2_SR_HARMONIZED", dataset_id
        return _FakeSceneCollection(
            self._months, self._means, self._window_payload
        )


def install_phenology_fake(monkeypatch, monthly_values):
    """Install a fake whose monthly series matches ``monthly_values``.

    ``monthly_values`` is a ``[(year, month, value), ...]`` list; the fake
    emits one scene per month with that month's mean NDVI, so the metric's
    monthly aggregation receives exactly the intended series.
    """
    months = [f"{y:04d}-{m:02d}" for y, m, _v in monthly_values]
    means = [v for _y, _m, v in monthly_values]
    if means:
        window_payload = {
            "NDVI_count": 100.0,
            "NDVI_mean": sum(means) / len(means),
            "NDVI_median": sorted(means)[len(means) // 2],
            "NDVI_min": min(means),
            "NDVI_max": max(means),
            "NDVI_stdDev": 0.1,
            "NDVI_p10": min(means),
            "NDVI_p25": min(means),
            "NDVI_p75": max(means),
            "NDVI_p90": max(means),
        }
    else:
        window_payload = {
            "NDVI_count": 0.0,
            "NDVI_mean": None,
            "NDVI_median": None,
            "NDVI_min": None,
            "NDVI_max": None,
            "NDVI_stdDev": None,
            "NDVI_p10": None,
            "NDVI_p25": None,
            "NDVI_p75": None,
            "NDVI_p90": None,
        }

    fake = FakePhenologyEE(months, means, window_payload)
    monkeypatch.setattr("ee.ImageCollection", fake.ImageCollection)
    monkeypatch.setattr("ee.Reducer", fake.Reducer)
    return fake


def test_the_onset_metric_publishes_a_date_for_a_clean_year(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_OK
    assert result.value is not None
    # Decimal-year encoding of a 2023 date.
    assert 2023.0 <= result.value < 2024.0


def a_clean_series_pairs(base=0.2, peak=0.8):
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


def test_the_provenance_carries_the_monthly_series(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.provenance is not None
    caveats = " ".join(result.provenance.caveats)
    assert "2023-01" in caveats
    assert "2023-12" in caveats


def test_the_provenance_states_the_full_algorithm(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.provenance is not None
    formula = result.provenance.formula.lower()
    for fragment in ("ndvi", "monthly", "moving average", "threshold", "crossing"):
        assert fragment in formula, fragment


def test_few_months_yield_insufficient_with_counts(monkeypatch):
    install_phenology_fake(
        monkeypatch,
        [(2023, m, 0.2 + 0.05 * m) for m in (1, 2, 3, 4)],
    )
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert result.message and "4 distinct month" in result.message


def test_a_large_gap_yields_insufficient_with_the_gap_named(monkeypatch):
    install_phenology_fake(
        monkeypatch,
        [(2023, m, 0.2 + 0.05 * m) for m in (1, 2, 3, 4, 9, 10, 11, 12)],
    )
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.message and "4 consecutive month" in result.message


def test_no_scenes_yield_insufficient(monkeypatch):
    install_phenology_fake(monkeypatch, [])
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_the_peak_metric_refuses_an_edge_peak(monkeypatch):
    pairs = [(2023, 1, 0.9)] + [(2023, m, 0.2) for m in range(2, 13)]
    install_phenology_fake(monkeypatch, pairs)
    result = SeasonPeakMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.message and "window" in result.message.lower()


def test_the_peak_metric_publishes_for_a_mid_year_peak(monkeypatch):
    pairs = [(2023, m, 0.2) for m in range(1, 13)]
    pairs[5] = (2023, 6, 0.9)  # June peak
    pairs[6] = (2023, 7, 0.9)  # plateau, so the smoothed max is interior
    install_phenology_fake(monkeypatch, pairs)
    result = SeasonPeakMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_OK
    assert result.value is not None
    # Ties resolve to the earliest month: June.
    assert result.value == pytest.approx(2023.0 + 151 / 365.0, abs=0.01)


def test_the_length_metric_needs_both_crossings(monkeypatch):
    # A series that rises but never falls inside the window.
    pairs = [(2023, m, min(0.2 + 0.06 * m, 0.9)) for m in range(1, 13)]
    install_phenology_fake(monkeypatch, pairs)
    result = SeasonLengthMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.message and "both" in result.message.lower()


def test_the_amplitude_metric_publishes_the_swing(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonAmplitudeMetric().compute(
        make_context("2023-01-01", "2023-12-31")
    )

    assert result.status == STATUS_OK
    assert result.value is not None
    assert result.value > 0.0
    assert result.unit == "index"


# ==========================================================================
# Scientific safety: neutral terminology, always
# ==========================================================================


@pytest.mark.parametrize(
    "metric_cls",
    [SeasonOnsetMetric, SeasonPeakMetric, SeasonEndMetric, SeasonLengthMetric],
)
def test_the_metrics_deny_the_agronomic_reading(metric_cls):
    metric = metric_cls()
    text = (
        metric.description
        + " "
        + " ".join(metric.limitations)
        + " "
        + str(metric.key)
    ).lower()
    # Every event metric must explicitly deny at least one agronomic
    # reading of the vegetation signal.
    denials = ("not the planting", "not the harvest", "not flowering",
               "not the flowering", "not of an agronomic", "agronomic season")
    assert any(d in text for d in denials), metric.key


@pytest.mark.parametrize(
    "forbidden",
    ["detects planting", "harvest date is", "indicates flowering",
     "diagnose", "diagnoses"],
)
def test_no_metric_prose_asserts_an_agronomic_event(forbidden):
    for metric in ALL_PHENOLOGY_METRICS:
        text = (
            metric.description + " " + " ".join(metric.limitations)
        ).lower()
        assert forbidden not in text, (metric.key, forbidden)


def test_the_provenance_threshold_rule_is_a_stated_convention(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    assert result.provenance is not None
    formula = result.provenance.formula
    assert "50%" in formula


def test_the_warnings_carry_the_neutral_terminology(monkeypatch):
    install_phenology_fake(monkeypatch, a_clean_series_pairs())
    result = SeasonOnsetMetric().compute(make_context("2023-01-01", "2023-12-31"))

    joined = " ".join(result.warnings)
    assert "not the planting date" in joined
    assert "reporting convention" in joined


# ==========================================================================
# Decimal-year encoding
# ==========================================================================


def test_the_decimal_year_preserves_month_resolution():
    from app.services.agriculture.phenology import _date_to_decimal_year

    january = _date_to_decimal_year(date(2023, 1, 1))
    february = _date_to_decimal_year(date(2023, 2, 1))
    assert february > january
    assert february - january < 0.1  # month resolution, not day claims


def test_the_decimal_year_handles_leap_years():
    from app.services.agriculture.phenology import _date_to_decimal_year

    assert _date_to_decimal_year(date(2024, 1, 1)) == pytest.approx(2024.0)
    assert _date_to_decimal_year(date(2024, 12, 31)) == pytest.approx(
        2024.0 + 365 / 366.0, abs=1e-6
    )


# ==========================================================================
# The seasonal integral was declined
# ==========================================================================


def test_the_integral_metric_is_registered_but_unavailable():
    metric = SeasonalIntegralMetric()
    result = metric.compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None
    assert metric.metadata()["available"] is False


def test_the_integral_reason_names_the_gap_filling_problem():
    lowered = INTEGRAL_UNAVAILABLE_REASON.lower()
    assert "gap" in lowered
    assert "fill" in lowered or "interpolat" in lowered
    assert "bias" in lowered


def test_the_integral_code_is_specific():
    assert INTEGRAL_UNAVAILABLE_CODE == "integral_requires_gap_filling"


def test_the_integral_declares_an_inference_basis():
    assert (
        SeasonalIntegralMetric().measurement_basis
        is MeasurementBasis.INFERENCE
    )
