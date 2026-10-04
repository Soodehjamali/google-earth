"""Tests for the CD-2 seasonal canopy-moisture anomalies.

Covers ``ndmi_anomaly``, ``msi_anomaly`` and ``ndre_anomaly``: seasonal
alignment, current-minus-baseline arithmetic, per-index direction,
sufficient/partial/insufficient coverage, counts, provenance, quality,
and the absence of synthetic baselines or leaf-percentage conversions.

Earth Engine is exercised through a strict queue-based fake: each test
declares the per-window outcomes (requested window first, then the ten
baseline years in order) and the fake serves them deterministically.
No network and no credentials are required.
"""

from __future__ import annotations

from collections import deque
from datetime import date
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.canopy_moisture import (
    CANOPY_ANOMALY_BASELINE_YEARS,
    CANOPY_ANOMALY_MIN_YEARS,
    CANOPY_MOISTURE_METRICS,
    MSIAnomalyMetric,
    NDMIAnomalyMetric,
    NDREAnomalyMetric,
)
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.stress import baseline_windows, shift_window_years
from app.services.agriculture.types import (
    MeasurementBasis,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

AREA_SQ_M = 10000.0
FULL_COVER_COUNT = 25  # 1 ha at 20 m: every pixel valid.
SCENES = 6


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": "2025-07-01",
        "end_date": "2025-07-31",
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": AREA_SQ_M},
    }
    fields.update(overrides)
    return MetricContext(**fields)


# ==========================================================================
# Queue-based fake Sentinel-2 Earth Engine
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
    def lte(_key, _value):
        return object()


class _FakeImageNamespace:
    @staticmethod
    def constant(_value):
        return _FakeNumber(0)


class _FakeRegion:
    def __init__(self, fake: "FakeS2EE") -> None:
        self._fake = fake

    def getInfo(self):
        return self._fake._pop_stats()


class _FakeImage:
    def __init__(self, fake: "FakeS2EE") -> None:
        self._fake = fake

    def select(self, _bands):
        return self

    def eq(self, _other):
        return _FakeNumber(0)

    def neq(self, _other):  # noqa: N802 - mirrors ee
        return _FakeNumber(0)

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee
        return self

    def multiply(self, _factor):
        return self

    def rename(self, _name):
        return self

    def normalizedDifference(self, _bands):  # noqa: N802 - mirrors ee
        return self

    def expression(self, _formula, _variables):
        return self

    def reduceRegion(self, **_kwargs):
        return _FakeRegion(self._fake)


class _FakeMapped:
    def __init__(self, fake: "FakeS2EE") -> None:
        self._fake = fake

    def median(self):
        return _FakeImage(self._fake)


class _FakeCollection:
    def __init__(self, fake: "FakeS2EE") -> None:
        self._fake = fake

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, _bands):
        return self

    def size(self):
        return _FakeNumber(self._fake._peek_scenes())

    def map(self, func):
        func(_FakeImage(self._fake))
        return _FakeMapped(self._fake)


class FakeS2EE:
    """Serves one queued outcome per reduced window, in call order.

    Each outcome is ``{"mean": float | None, "scenes": int}``. The
    requested window is served first, then baseline years 1..10. A
    ``None`` mean reduces to ``{}``, which the real
    ``parse_reduction_result`` reads as no valid pixels — the same
    shape a fully masked window produces.
    """

    def __init__(self, outcomes: List[Dict[str, Any]]) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(outcomes)
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeCollection(self)

    def _peek_scenes(self) -> int:
        if not self._queue:
            raise AssertionError("fake S2 queue exhausted on size()")
        return int(self._queue[0]["scenes"])

    def _pop_stats(self) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake S2 queue exhausted on reduceRegion()")
        outcome = self._queue.popleft()
        mean = outcome["mean"]
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        value = float(mean)
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
            "count": FULL_COVER_COUNT,
        }


@pytest.fixture
def fake_s2(monkeypatch):
    def install(outcomes: List[Dict[str, Any]]) -> FakeS2EE:
        fake = FakeS2EE(outcomes)
        import ee

        for name in ("ImageCollection", "Reducer", "Filter", "Image"):
            monkeypatch.setattr(ee, name, getattr(fake, name))
        return fake

    return install


def _win(mean: Optional[float], scenes: int = SCENES) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


def _full_baseline(value: float) -> List[Dict[str, Any]]:
    return [_win(value) for _ in range(CANOPY_ANOMALY_BASELINE_YEARS)]


# ==========================================================================
# Policy and declaration
# ==========================================================================


def test_baseline_policy_uses_ten_windows_min_three():
    assert CANOPY_ANOMALY_BASELINE_YEARS == 10
    assert CANOPY_ANOMALY_MIN_YEARS == 3
    for metric in CANOPY_MOISTURE_METRICS:
        assert metric.baseline_years == 10, metric.key
        assert metric.min_years == 3, metric.key


def test_anomaly_metrics_live_in_existing_domains():
    assert NDMIAnomalyMetric().domain == "water"
    assert MSIAnomalyMetric().domain == "water"
    assert NDREAnomalyMetric().domain == "vegetation"


def test_anomaly_metrics_are_derived_index_differences():
    for metric in CANOPY_MOISTURE_METRICS:
        assert metric.measurement_basis is MeasurementBasis.DERIVED, metric.key
        assert metric.unit == "index", metric.key
        assert metric.default_scale == 20, metric.key


def test_anomaly_source_bands_match_sibling_indices():
    assert NDMIAnomalyMetric().source_bands == ("B8", "B11")
    assert MSIAnomalyMetric().source_bands == ("B11", "B8")
    assert NDREAnomalyMetric().source_bands == ("B5", "B8")


def test_anomaly_metrics_carry_limitations_and_formulas():
    for metric in CANOPY_MOISTURE_METRICS:
        assert metric.limitations, metric.key
        assert metric.formula_text, metric.key
        assert metric.aggregation_text, metric.key
        assert "same calendar window" in metric.formula_text, metric.key


def test_canopy_moisture_metrics_register_cleanly():
    register_metrics(CANOPY_MOISTURE_METRICS)
    from app.services.agriculture.catalog import has_metric

    for key in ("ndmi_anomaly", "msi_anomaly", "ndre_anomaly"):
        assert has_metric(key), key


# ==========================================================================
# Seasonal alignment
# ==========================================================================


def test_baseline_windows_preserve_month_day_span():
    start, end = date(2025, 7, 1), date(2025, 7, 31)
    windows = baseline_windows(start, end, CANOPY_ANOMALY_BASELINE_YEARS)
    assert len(windows) == CANOPY_ANOMALY_BASELINE_YEARS
    for years_back, win_start, win_end in windows:
        assert (win_start.month, win_start.day) == (7, 1)
        assert (win_end.month, win_end.day) == (7, 31)
        assert win_start.year == 2025 - years_back
        assert win_end.year == 2025 - years_back


def test_baseline_windows_are_ordered_most_recent_first():
    windows = baseline_windows(date(2025, 7, 1), date(2025, 7, 31), 10)
    assert [w[0] for w in windows] == list(range(1, 11))


def test_leap_day_folds_onto_feb_28():
    start, end = date(2024, 2, 29), date(2024, 3, 31)
    shifted_start, shifted_end = shift_window_years(start, end, 1)
    assert shifted_start == date(2023, 2, 28)
    assert shifted_end == date(2023, 3, 31)


def test_request_longer_than_a_year_is_refused(fake_s2):
    fake_s2([])
    context = make_context(start_date="2024-01-01", end_date="2025-06-01")
    result = NDMIAnomalyMetric().compute(context)
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


# ==========================================================================
# Current-minus-baseline arithmetic and direction
# ==========================================================================


def test_ndmi_negative_anomaly_when_drier_than_baseline(fake_s2):
    fake_s2([_win(0.25)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.25 - 0.35)


def test_msi_positive_anomaly_when_more_stressed_than_baseline(fake_s2):
    fake_s2([_win(1.20)] + _full_baseline(0.80))
    result = MSIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(1.20 - 0.80)


def test_ndre_negative_anomaly_when_condition_below_baseline(fake_s2):
    fake_s2([_win(0.30)] + _full_baseline(0.45))
    result = NDREAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.30 - 0.45)


def test_baseline_is_the_mean_of_per_year_window_means(fake_s2):
    baselines = [0.30, 0.32, 0.28, 0.34, 0.31, 0.29, 0.33, 0.27, 0.35, 0.30]
    fake_s2([_win(0.25)] + [_win(v) for v in baselines])
    result = NDMIAnomalyMetric().compute(make_context())
    expected = 0.25 - sum(baselines) / len(baselines)
    assert result.value == pytest.approx(expected)


def test_zero_anomaly_is_reported_not_refused(fake_s2):
    """Identical current and baseline is a real statement, not a gap."""
    fake_s2([_win(0.35)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


# ==========================================================================
# Coverage: sufficient / partial / insufficient
# ==========================================================================


def test_no_baseline_year_is_insufficient(fake_s2):
    fake_s2([_win(0.25)] + [_win(None) for _ in range(10)])
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_single_baseline_year_is_insufficient(fake_s2):
    fake_s2([_win(0.25), _win(0.35)] + [_win(None) for _ in range(9)])
    result = MSIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_two_baseline_years_is_insufficient(fake_s2):
    fake_s2([_win(0.30), _win(0.45), _win(0.44)] + [_win(None) for _ in range(8)])
    result = NDREAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_partial_baseline_reports_value_with_warning(fake_s2):
    """Five contributing years clears the minimum but weakens the reference."""
    fake_s2([_win(0.25)] + [_win(0.35)] * 5 + [_win(None)] * 5)
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.25 - 0.35)
    assert result.warnings, "a partial baseline must carry a warning"


def test_missing_current_window_is_insufficient(fake_s2):
    fake_s2([_win(None)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_masked_current_window_is_insufficient(fake_s2):
    """Scenes found but every pixel masked: observed, yet no value."""
    fake_s2([_win(None, scenes=4)] + _full_baseline(0.35))
    result = MSIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_pre_launch_baseline_years_contribute_nothing(fake_s2):
    """A 2019 request: 2016 and earlier have no S2 scenes, so the
    reference is thin and the metric refuses rather than inventing
    history."""
    context = make_context(start_date="2019-07-01", end_date="2019-07-31")
    fake_s2(
        [_win(0.25), _win(0.35), _win(0.34)]
        + [_win(None, scenes=0) for _ in range(8)]
    )
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_recent_request_tolerates_pre_launch_years_as_partial(fake_s2):
    """A 2025 request: 2015-2016 predate S2, the other eight years
    contribute, and the weakened baseline is flagged, not hidden."""
    fake_s2([_win(0.25)] + [_win(0.35)] * 8 + [_win(None, scenes=0)] * 2)
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.25 - 0.35)
    assert result.warnings


def test_non_finite_baseline_values_are_excluded(fake_s2):
    fake_s2(
        [_win(0.25)]
        + [_win(float("nan")), _win(float("inf"))]
        + [_win(0.35)] * 8
    )
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.25 - 0.35)


# ==========================================================================
# Counts, provenance, quality, evidence
# ==========================================================================


def test_provenance_records_current_and_baseline_observations(fake_s2):
    fake_s2([_win(0.25)] + [_win(0.35)] * 8 + [_win(None)] * 2)
    result = NDMIAnomalyMetric().compute(make_context())
    provenance = result.provenance
    assert provenance is not None
    assert provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    assert provenance.bands == ["B8", "B11"]
    assert provenance.image_count == SCENES
    assert provenance.measurement_basis is MeasurementBasis.DERIVED
    caveats = " ".join(provenance.caveats)
    assert "8 contributing" in caveats
    assert any(
        "whole years" in limitation for limitation in provenance.limitations
    )


def test_provenance_names_baseline_period_and_statistic(fake_s2):
    fake_s2([_win(1.20)] + _full_baseline(0.80))
    result = MSIAnomalyMetric().compute(make_context())
    caveats = " ".join(result.provenance.caveats)
    assert "mean of per-year window means" in caveats
    assert "2015-2024" in caveats
    assert "10 contributing" in caveats


def test_provenance_carries_requested_window_and_formula(fake_s2):
    fake_s2([_win(0.30)] + _full_baseline(0.45))
    result = NDREAnomalyMetric().compute(make_context())
    provenance = result.provenance
    assert provenance.requested_start == "2025-07-01"
    assert provenance.requested_end == "2025-07-31"
    assert provenance.bands == ["B5", "B8"]
    assert "B8" in provenance.formula and "B5" in provenance.formula
    assert provenance.limitations


def test_usable_quality_for_full_coverage(fake_s2):
    fake_s2([_win(0.25)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.provenance.quality_level.is_usable


def test_poor_current_quality_still_reports_with_warning(fake_s2):
    """One usable scene is poor quality, not missing data: the value is
    reported and the weakness is flagged."""
    fake_s2([_win(0.25, scenes=1)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.25 - 0.35)
    assert result.warnings


def test_anomaly_evidence_item_is_derived_not_proxy(fake_s2):
    from app.services.agriculture.evidence import EvidenceItem

    fake_s2([_win(0.25)] + _full_baseline(0.35))
    result = NDMIAnomalyMetric().compute(make_context())
    item = EvidenceItem.from_result(result)
    assert item.metric_key == "ndmi_anomaly"
    assert item.value == pytest.approx(0.25 - 0.35)
    assert item.is_proxy is False
    assert item.provenance is not None


# ==========================================================================
# Scientific honesty guards
# ==========================================================================


def test_no_leaf_percentage_conversion_exists():
    for metric in CANOPY_MOISTURE_METRICS:
        assert not hasattr(metric, "to_leaf_fraction")
        assert not hasattr(metric, "to_dry_percentage")
        joined = " ".join(metric.limitations).lower()
        assert "percentage of dry leaves" in joined, metric.key


def test_no_layer_specific_language():
    forbidden = ("middle canopy", "middle leaf", "lower canopy", "upper canopy")
    for metric in CANOPY_MOISTURE_METRICS:
        text = " ".join(
            [metric.description, *metric.limitations]
        ).lower()
        for phrase in forbidden:
            assert phrase not in text, (metric.key, phrase)


def test_no_diagnostic_claims():
    forbidden_claims = (
        "detect disease",
        "detects disease",
        "diagnose disease",
        "identify disease",
        "detect pest",
        "diagnose pest",
        "nutrient deficiency",
    )
    for metric in CANOPY_MOISTURE_METRICS:
        text = " ".join(
            list(metric.limitations) + [metric.description]
        ).lower()
        for phrase in forbidden_claims:
            assert phrase not in text, (metric.key, phrase)


def test_no_sentinel1_or_proxy_machinery():
    import app.services.agriculture.canopy_moisture as module

    source = open(module.__file__, encoding="utf-8").read()
    for token in ("S1_", "SENTINEL-1", "COPERNICUS/S1", "/S1_", "RVI", "VH", "VV"):
        assert token not in source, token
    for metric in CANOPY_MOISTURE_METRICS:
        assert metric.measurement_basis is not MeasurementBasis.PROXY
        assert metric.measurement_basis is not MeasurementBasis.INFERENCE
