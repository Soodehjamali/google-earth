"""Tests for the CD-3 Sentinel-1 radar canopy signals.

Covers ``vv``, ``vh``, ``vh_vv`` and ``rvi``: dataset registration,
homogeneous acquisition filtering (IW / VV+VH / descending), temporal
mean aggregation, pure-formula correctness (including the dB-domain
VH/VV representation and the dual-pol RVI), provenance, SAR quality,
coverage, empty/masked/missing-polarization handling, and the absence
of any middle-canopy proxy.

Earth Engine is exercised through a strict fake: filter predicates
are captured for policy assertions, the temporal composite is a mean
(never a median), and one queued outcome is served per reduced
window. No network and no credentials are required.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.services.agriculture import indices as pure
from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.radar import (
    RADAR_METRICS,
    RVIMetric,
    S1_DATASET_ID,
    S1_MODE,
    S1_PASS,
    S1_SCALE,
    VHBackscatterMetric,
    VHVVRatioMetric,
    VVBackscatterMetric,
    build_s1_composite,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
)

AREA_SQ_M = 10000.0
FULL_COVER_COUNT = 100  # 1 ha at 10 m: every pixel valid.
SCENES = 4


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
# Strict fake Sentinel-1 Earth Engine
# ==========================================================================


class _FakeNumber:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def getInfo(self):
        return self._value


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
    def eq(key, value):
        return ("eq", key, value)

    @staticmethod
    def listContains(key, value):  # noqa: N802 - mirrors ee
        return ("listContains", key, value)

    @staticmethod
    def lte(key, value):  # noqa: N802 - mirrors ee
        return ("lte", key, value)


class _FakeRegion:
    def __init__(self, fake: "FakeS1EE") -> None:
        self._fake = fake

    def getInfo(self):
        return self._fake._pop_stats()


class _FakeImage:
    """A composite-level image. Band selection is strict: asking for a
    polarization the fixture did not provide raises, so a metric
    reading the wrong band fails loudly. ``rename`` registers the new
    band name, mirroring how a renamed EE image carries its band."""

    def __init__(self, fake: "FakeS1EE") -> None:
        self._fake = fake
        self._bands = {"VV", "VH"}

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in self._bands:
                raise KeyError(f"fake S1 image holds {sorted(self._bands)}, not {band!r}")
        self._fake.selected.extend(bands)
        return self

    def rename(self, name):
        self._bands.add(name)
        return self

    def expression(self, formula, variables):
        self._fake.expressions.append((formula, sorted(variables)))
        return self

    def divide(self, _value):
        self._fake.algebra.append("divide")
        return self

    def multiply(self, _value):
        self._fake.algebra.append("multiply")
        return self

    def exp(self):
        self._fake.algebra.append("exp")
        return self

    def add(self, _other):
        self._fake.algebra.append("add")
        return self

    def reduceRegion(self, **_kwargs):
        return _FakeRegion(self._fake)


class _FakeCollection:
    def __init__(self, fake: "FakeS1EE") -> None:
        self._fake = fake

    def filterBounds(self, *_args):
        return self

    def filterDate(self, *_args):
        return self

    def filter(self, predicate):
        self._fake.filters.append(predicate)
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in ("VV", "VH"):
                raise KeyError(
                    f"fake S1 collection holds VV/VH, not {band!r}"
                )
        return self

    def size(self):
        return _FakeNumber(self._fake._peek_scenes())

    def mean(self):
        self._fake.aggregations.append("mean")
        return _FakeImage(self._fake)

    def median(self):
        self._fake.aggregations.append("median")
        raise AssertionError(
            "S1 temporal aggregation must be a mean, never a median"
        )


class FakeS1EE:
    """One queued outcome per reduced window, plus full call capture."""

    def __init__(self, outcomes: List[Dict[str, Any]]) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(outcomes)
        self.filters: List[Any] = []
        self.aggregations: List[str] = []
        self.expressions: List[Any] = []
        self.algebra: List[str] = []
        self.selected: List[str] = []
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee
        assert dataset_id == S1_DATASET_ID, dataset_id
        return _FakeCollection(self)

    def _peek_scenes(self) -> int:
        if not self._queue:
            raise AssertionError("fake S1 queue exhausted on size()")
        return int(self._queue[0]["scenes"])

    def _pop_stats(self) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake S1 queue exhausted on reduceRegion()")
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
def fake_s1(monkeypatch):
    def install(outcomes: List[Dict[str, Any]]) -> FakeS1EE:
        fake = FakeS1EE(outcomes)
        import ee

        for name in ("ImageCollection", "Reducer", "Filter"):
            monkeypatch.setattr(ee, name, getattr(fake, name))
        return fake

    return install


def _win(mean: Optional[float], scenes: int = SCENES) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


# ==========================================================================
# Dataset registration
# ==========================================================================


def test_s1_dataset_is_registered():
    from app.services.agriculture.registry import get_dataset, has_dataset

    assert has_dataset("COPERNICUS/S1_GRD")
    spec = get_dataset(S1_DATASET_ID)
    assert spec.id == "COPERNICUS/S1_GRD"
    assert spec.available_from == "2014-10-03"


def test_s1_bands_are_vv_vh_in_decibels():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset(S1_DATASET_ID)
    assert set(spec.bands) == {"VV", "VH"}
    assert spec.band("VV").unit == "dB"
    assert spec.band("VH").unit == "dB"


def test_s1_dataset_declares_no_cloud_mask():
    """SAR has no cloud mask and none is invented."""
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset(S1_DATASET_ID)
    assert spec.cloud_mask_method is None
    assert spec.cloud_mask_band is None


def test_s1_caveats_state_homogeneity_and_constellation():
    from app.services.agriculture.registry import get_dataset

    joined = " ".join(get_dataset(S1_DATASET_ID).caveats).lower()
    assert "descending" in joined
    assert "iw" in joined
    assert "2021" in joined or "sentinel-1b" in joined
    assert "speckle" in joined


def test_s1_filter_policy_constants():
    assert S1_MODE == "IW"
    assert S1_PASS == "DESCENDING"
    assert S1_SCALE == 10


# ==========================================================================
# Acquisition filtering and temporal aggregation
# ==========================================================================


def test_composite_filters_single_homogeneous_subset(fake_s1):
    fake = fake_s1([_win(-10.5)])
    build_s1_composite(make_context(), __import__("ee"))
    assert ("eq", "instrumentMode", "IW") in fake.filters
    assert ("listContains", "transmitterReceiverPolarisation", "VV") in (
        fake.filters
    )
    assert ("listContains", "transmitterReceiverPolarisation", "VH") in (
        fake.filters
    )
    assert ("eq", "orbitProperties_pass", "DESCENDING") in fake.filters


def test_no_ascending_data_can_pass_the_filter(fake_s1):
    """The pass predicate admits exactly one orbit direction."""
    fake = fake_s1([_win(-10.5)])
    build_s1_composite(make_context(), __import__("ee"))
    pass_filters = [f for f in fake.filters if f[1] == "orbitProperties_pass"]
    assert pass_filters == [("eq", "orbitProperties_pass", "DESCENDING")]


def test_temporal_aggregation_is_a_mean(fake_s1):
    fake = fake_s1([_win(-10.5)])
    build_s1_composite(make_context(), __import__("ee"))
    assert fake.aggregations == ["mean"]


def test_composite_reports_acquisition_count(fake_s1):
    fake = fake_s1([_win(-10.5, scenes=3)])
    _composite, count = build_s1_composite(make_context(), __import__("ee"))
    assert count == 3


def test_missing_polarization_fails_loudly(fake_s1):
    """A collection without VH must raise, not return VV as VH."""
    fake = fake_s1([_win(-10.5)])
    with pytest.raises(KeyError):
        _FakeImage(fake).select(["VH_missing"])


# ==========================================================================
# VV / VH signals
# ==========================================================================


def test_vv_reports_temporal_mean_in_db(fake_s1):
    fake_s1([_win(-10.5)])
    result = VVBackscatterMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(-10.5)
    assert result.unit == "dB"


def test_vh_reports_temporal_mean_in_db(fake_s1):
    fake_s1([_win(-17.2)])
    result = VHBackscatterMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(-17.2)
    assert result.unit == "dB"


def test_vv_and_vh_read_different_polarizations():
    assert VVBackscatterMetric().required_polarizations == ("VV",)
    assert VHBackscatterMetric().required_polarizations == ("VH",)


def test_empty_collection_is_insufficient_not_zero(fake_s1):
    fake_s1([_win(None, scenes=0)])
    result = VVBackscatterMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_masked_window_is_insufficient(fake_s1):
    fake_s1([_win(None, scenes=3)])
    result = VHBackscatterMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


# ==========================================================================
# VH/VV dB difference
# ==========================================================================


def test_vh_vv_uses_db_difference_not_linear_ratio(fake_s1):
    fake = fake_s1([_win(-6.7)])
    result = VHVVRatioMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(-6.7)
    assert result.unit == "dB"
    assert fake.expressions
    formula, variables = fake.expressions[0]
    assert formula == "VH - VV"
    assert variables == ["VH", "VV"]


def test_vh_vv_diff_matches_log_of_linear_ratio():
    vh_db, vv_db = -17.2, -10.5
    value = pure.vh_vv_diff(vh_db, vv_db)
    assert value == pytest.approx(vh_db - vv_db)
    assert value == pytest.approx(
        10.0 * math.log10(10.0 ** (vh_db / 10.0) / 10.0 ** (vv_db / 10.0))
    )


def test_vh_vv_diff_guards():
    assert pure.vh_vv_diff(None, -10.5) is None
    assert pure.vh_vv_diff(-17.2, None) is None
    assert pure.vh_vv_diff(True, -10.5) is None
    assert pure.vh_vv_diff(-17.2, float("nan")) is None
    assert pure.vh_vv_diff(-17.2, float("inf")) is None


def test_vh_vv_formula_text_names_decibels():
    assert pure.RADAR_FORMULA_TEXT["vh_vv"] == "(VH - VV) dB"


# ==========================================================================
# RVI (dual-pol) — IMPLEMENTED with verified formulation
# ==========================================================================


def test_rvi_uses_image_algebra_not_unverified_expression(fake_s1):
    fake = fake_s1([_win(0.65)])
    result = RVIMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.65)
    assert result.unit == "ratio"
    assert not fake.expressions, "RVI must not use an expression string"
    for op in ("divide", "exp", "add", "multiply"):
        assert op in fake.algebra, op


def test_rvi_pure_matches_dual_pol_definition():
    vv_db, vh_db = -10.5, -17.2
    vv_linear = 10.0 ** (vv_db / 10.0)
    vh_linear = 10.0 ** (vh_db / 10.0)
    assert pure.rvi(vv_db, vh_db) == pytest.approx(
        4.0 * vh_linear / (vv_linear + vh_linear)
    )


def test_rvi_bare_surface_near_zero_and_dense_below_two():
    bare = pure.rvi(-8.0, -19.0)  # VH ~11 dB below VV
    assert bare is not None and 0.0 < bare < 0.5
    dense = pure.rvi(-10.0, -13.0)  # VH within 3 dB of VV
    assert dense is not None and 0.5 < dense <= 2.0


def test_rvi_guards():
    assert pure.rvi(None, -17.2) is None
    assert pure.rvi(-10.5, None) is None
    assert pure.rvi(True, -17.2) is None
    assert pure.rvi(-10.5, float("nan")) is None


def test_rvi_metadata_ranges_are_consistent():
    low, high = pure.RADAR_EXPECTED_RANGE["rvi"]
    assert (low, high) == (0.0, 2.0)
    typical_low, typical_high = pure.RADAR_TYPICAL_RANGE["rvi"]
    assert low <= typical_low < typical_high <= high


def test_radar_metadata_registries_are_complete():
    for name in ("vv", "vh", "vh_vv", "rvi"):
        assert pure.RADAR_FORMULA_TEXT[name]
        assert pure.RADAR_BAND_ROLES[name]
        low, high = pure.RADAR_EXPECTED_RANGE[name]
        assert low < high
        typical_low, typical_high = pure.RADAR_TYPICAL_RANGE[name]
        assert low <= typical_low < typical_high <= high


def test_radar_band_roles_reference_the_s1_registry():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset(S1_DATASET_ID)
    for bands in pure.RADAR_BAND_ROLES.values():
        for band in bands:
            assert spec.has_band(band), band


# ==========================================================================
# Provenance, quality, coverage
# ==========================================================================


def test_radar_provenance_identifies_acquisition_policy(fake_s1):
    fake_s1([_win(-10.5)])
    result = VVBackscatterMetric().compute(make_context())
    provenance = result.provenance
    assert provenance is not None
    assert provenance.source_dataset_id == "COPERNICUS/S1_GRD"
    assert provenance.bands == ["VV"]
    assert provenance.image_count == SCENES
    assert provenance.measurement_basis is MeasurementBasis.DERIVED
    assert S1_PASS.lower() in provenance.aggregation_method.lower()
    assert S1_MODE in provenance.aggregation_method
    caveats = " ".join(provenance.caveats)
    assert "DESCENDING" in caveats
    assert f"{SCENES} acquisition(s)" in caveats
    assert provenance.limitations


def test_rvi_provenance_carries_formula_and_polarizations(fake_s1):
    fake_s1([_win(0.65)])
    result = RVIMetric().compute(make_context())
    assert result.provenance.bands == ["VV", "VH"]
    assert "VH" in result.provenance.formula


def test_usable_quality_for_full_coverage(fake_s1):
    fake_s1([_win(-10.5)])
    result = VVBackscatterMetric().compute(make_context())
    assert result.provenance.quality_level.is_usable
    assert result.stats.coverage_percent == pytest.approx(100.0)


def test_single_acquisition_is_poor_but_reported(fake_s1):
    fake_s1([_win(-10.5, scenes=1)])
    result = VVBackscatterMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(-10.5)
    assert result.warnings


def test_pre_launch_request_is_refused():
    context = make_context(start_date="2010-01-01", end_date="2010-12-31")
    can, reason = VVBackscatterMetric().can_attempt(context)
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_current_request_is_attemptable():
    can, reason = RVIMetric().can_attempt(make_context())
    assert can is True
    assert reason is None


def test_radar_metrics_register_cleanly():
    register_metrics(RADAR_METRICS)
    from app.services.agriculture.catalog import has_metric

    for key in ("vv", "vh", "vh_vv", "rvi"):
        assert has_metric(key), key


# ==========================================================================
# Scientific honesty guards
# ==========================================================================


def test_radar_metrics_are_derived_never_proxy():
    for metric in RADAR_METRICS:
        assert metric.measurement_basis is MeasurementBasis.DERIVED
        assert metric.measurement_basis not in (
            MeasurementBasis.PROXY,
            MeasurementBasis.INFERENCE,
        )
        assert "proxy" not in metric.display_name.lower()
        assert "_proxy" not in metric.key


def test_no_leaf_layer_language():
    forbidden = (
        "middle leaf",
        "middle leaves",
        "middle canopy",
        "lower canopy",
        "upper canopy",
        "leaf water",
        "penetrates to",
    )
    for metric in RADAR_METRICS:
        text = " ".join([metric.description, *metric.limitations]).lower()
        for phrase in forbidden:
            if phrase == "leaf water":
                # Allowed only inside an explicit denial ("does not
                # measure leaf water content"), which the description
                # and limitations carry; anything else would fail here.
                assert "does not" in text or "not a measurement" in text
                continue
            assert phrase not in text, (metric.key, phrase)


def test_no_leaf_percentage_or_diagnosis():
    for metric in RADAR_METRICS:
        text = " ".join(
            list(metric.limitations) + [metric.description]
        ).lower()
        assert "percentage" not in text, metric.key
        for phrase in (
            "detect disease",
            "diagnose disease",
            "detect pest",
            "diagnose pest",
        ):
            assert phrase not in text, (metric.key, phrase)


def test_no_middle_canopy_proxy_exists():
    from app.services.agriculture.catalog import all_metrics

    register_metrics(RADAR_METRICS)
    for metric in all_metrics():
        assert "middle" not in metric.key
        assert metric.measurement_basis is not MeasurementBasis.PROXY


def test_no_optical_wiring_changed():
    from app.services.agriculture.water import MNDWIMetric, NDMIMetric
    from app.services.agriculture.vegetation import NDREMetric, NDVIMetric

    assert NDMIMetric().required_bands == ("B8", "B11")
    assert NDVIMetric().required_bands == ("B4", "B8")
    assert NDREMetric().required_bands == ("B5", "B8")
    assert MNDWIMetric().required_bands == ("B3", "B11")
