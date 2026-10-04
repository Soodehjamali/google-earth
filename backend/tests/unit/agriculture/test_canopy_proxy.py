"""Tests for the CD-4 Middle-Canopy Dryness Proxy.

Covers the evidence-concordance states (NO_EVIDENCE through
NO_STRESS_EVIDENCE), anomaly-sign interpretation, radar-as-context
discipline, categorical confidence, ledger provenance, temporal
alignment, and the absence of weights, percentages, and physical
leaf-layer claims.

Pure-logic tests run without Earth Engine. End-to-end proxy tests use
a combined fake serving the Sentinel-2 anomaly path (requested window
plus ten baseline years per optical component) and the Sentinel-1
window path. No network and no credentials are required.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.canopy_proxy import (
    CONFIDENCE_HIGH,
    CONFIDENCE_INSUFFICIENT,
    CONFIDENCE_LOW,
    CONFIDENCE_MODERATE,
    PROXY_STATE_LEGEND,
    MiddleCanopyDrynessProxyMetric,
    CANOPY_PROXY_METRICS,
    ProxyState,
    classify_concordance,
    classify_optical,
    confidence_for,
)
from app.services.agriculture.catalog import clear_registry, register_metrics
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    TemporalKind,
)

AREA_SQ_M = 10000.0
S2_FULL_COUNT = 25  # 1 ha at 20 m.
S1_FULL_COUNT = 100  # 1 ha at 10 m.

NDMI_BASE, MSI_BASE, NDRE_BASE = 0.35, 0.80, 0.45


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
# Combined fake Earth Engine (Sentinel-2 anomaly path + Sentinel-1 path)
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


_S2_BANDS = {"SCL", "B2", "B3", "B4", "B5", "B8", "B11"}
_S1_BANDS = {"VV", "VH"}


class _FakeRegion:
    def __init__(self, fake: "FakeMultiEE", which: str) -> None:
        self._fake = fake
        self._which = which

    def getInfo(self):
        return self._fake._pop_stats(self._which)


class _FakeImage:
    def __init__(self, fake: "FakeMultiEE", which: str) -> None:
        self._fake = fake
        self._which = which
        self._bands = set(_S2_BANDS if which == "s2" else _S1_BANDS)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in self._bands:
                raise KeyError(f"fake {self._which} holds {sorted(self._bands)}")
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

    def reduceRegion(self, **_kwargs):
        return _FakeRegion(self._fake, self._which)


class _FakeMapped:
    def __init__(self, fake: "FakeMultiEE", which: str) -> None:
        self._fake = fake
        self._which = which

    def median(self):
        return _FakeImage(self._fake, self._which)


class _FakeCollection:
    def __init__(self, fake: "FakeMultiEE", which: str) -> None:
        self._fake = fake
        self._which = which

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        allowed = _S2_BANDS if self._which == "s2" else _S1_BANDS
        for band in bands:
            if band not in allowed:
                raise KeyError(f"fake {self._which} holds {sorted(allowed)}")
        return self

    def size(self):
        return _FakeNumber(self._fake._peek_scenes(self._which))

    def map(self, func):
        func(_FakeImage(self._fake, self._which))
        return _FakeMapped(self._fake, self._which)

    def mean(self):
        return _FakeImage(self._fake, self._which)


class FakeMultiEE:
    """Separate outcome queues for the S2 anomaly path and the S1 path.

    S2 outcomes serve, in order, three full anomaly evaluations
    (requested window + ten baseline years each). S1 outcomes serve
    the four single-window radar signals in metric order.
    """

    def __init__(
        self,
        s2_outcomes: List[Dict[str, Any]],
        s1_outcomes: List[Dict[str, Any]],
    ) -> None:
        self._s2: Deque[Dict[str, Any]] = deque(s2_outcomes)
        self._s1: Deque[Dict[str, Any]] = deque(s1_outcomes)
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee
        if dataset_id == "COPERNICUS/S1_GRD":
            return _FakeCollection(self, "s1")
        return _FakeCollection(self, "s2")

    def _peek_scenes(self, which: str) -> int:
        queue = self._s2 if which == "s2" else self._s1
        if not queue:
            raise AssertionError(f"fake {which} queue exhausted on size()")
        return int(queue[0]["scenes"])

    def _pop_stats(self, which: str) -> Dict[str, Any]:
        queue = self._s2 if which == "s2" else self._s1
        if not queue:
            raise AssertionError(f"fake {which} queue exhausted")
        outcome = queue.popleft()
        mean = outcome["mean"]
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        value = float(mean)
        count = S2_FULL_COUNT if which == "s2" else S1_FULL_COUNT
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
            "count": count,
        }


@pytest.fixture
def fake_multi(monkeypatch):
    def install(
        s2_outcomes: List[Dict[str, Any]], s1_outcomes: List[Dict[str, Any]]
    ) -> FakeMultiEE:
        fake = FakeMultiEE(s2_outcomes, s1_outcomes)
        import ee

        for name in ("ImageCollection", "Reducer", "Filter", "Image"):
            monkeypatch.setattr(ee, name, getattr(fake, name))
        return fake

    return install


def _s2(mean: Optional[float], scenes: int = 6) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


def _s1(mean: Optional[float], scenes: int = 4) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


def _anomaly_windows(current: Optional[float], baseline: float) -> List[Dict[str, Any]]:
    return [_s2(current)] + [_s2(baseline) for _ in range(10)]


def _radar_full(vv=-10.5, vh=-17.2, vh_vv=-6.7, rvi=0.65) -> List[Dict[str, Any]]:
    return [_s1(vv), _s1(vh), _s1(vh_vv), _s1(rvi)]


def _radar_empty() -> List[Dict[str, Any]]:
    return [_s1(None, scenes=0) for _ in range(4)]


def _s2_empty() -> List[Dict[str, Any]]:
    return [_s2(None, scenes=0) for _ in range(33)]


# ==========================================================================
# Pure logic: optical votes (required cases 8-10)
# ==========================================================================


def test_ndmi_negative_anomaly_votes_stress():
    record = classify_optical(
        {"ndmi_anomaly": -0.10, "msi_anomaly": None, "ndre_anomaly": None}
    )
    assert record["votes"] == {"ndmi_anomaly": "stress"}
    assert record["state"] == "stress"


def test_msi_positive_anomaly_votes_stress():
    record = classify_optical(
        {"ndmi_anomaly": None, "msi_anomaly": 0.40, "ndre_anomaly": None}
    )
    assert record["votes"] == {"msi_anomaly": "stress"}
    assert record["state"] == "stress"


def test_ndre_negative_anomaly_votes_stress():
    record = classify_optical(
        {"ndmi_anomaly": None, "msi_anomaly": None, "ndre_anomaly": -0.15}
    )
    assert record["votes"] == {"ndre_anomaly": "stress"}
    assert record["state"] == "stress"


def test_opposite_anomaly_signs_vote_anti():
    record = classify_optical(
        {"ndmi_anomaly": 0.08, "msi_anomaly": -0.20, "ndre_anomaly": 0.05}
    )
    assert record["state"] == "no_stress"
    assert set(record["votes"].values()) == {"anti"}


def test_zero_anomaly_votes_neutral_not_stress():
    record = classify_optical(
        {"ndmi_anomaly": 0.0, "msi_anomaly": 0.0, "ndre_anomaly": 0.0}
    )
    assert record["state"] == "no_stress"
    assert set(record["votes"].values()) == {"neutral"}


def test_radar_keys_never_enter_optical_votes():
    """RVI and VH/VV values cannot steer the optical classification."""
    record = classify_optical(
        {
            "ndmi_anomaly": -0.10,
            "msi_anomaly": None,
            "ndre_anomaly": None,
            "rvi": 0.95,
            "vh_vv": -4.0,
            "vv": -8.0,
            "vh": -12.0,
        }
    )
    assert set(record["votes"]) == {"ndmi_anomaly"}


# ==========================================================================
# Pure logic: concordance states (required cases 1-7 framing)
# ==========================================================================


def test_concordance_state_table():
    assert classify_concordance("missing", False) is None  # NO_EVIDENCE
    assert (
        classify_concordance("stress", False) == ProxyState.OPTICAL_STRESS_ONLY
    )
    assert (
        classify_concordance("missing", True)
        == ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY
    )
    assert classify_concordance("stress", True) == ProxyState.CONCORDANT_STRESS
    assert (
        classify_concordance("contradictory", True)
        == ProxyState.MIXED_OR_CONTRADICTORY
    )
    assert (
        classify_concordance("contradictory", False)
        == ProxyState.MIXED_OR_CONTRADICTORY
    )
    assert (
        classify_concordance("no_stress", True) == ProxyState.NO_STRESS_EVIDENCE
    )
    assert (
        classify_concordance("no_stress", False) == ProxyState.NO_STRESS_EVIDENCE
    )


def test_confidence_table_is_deterministic():
    cases = [
        (None, 0, 0, False, CONFIDENCE_INSUFFICIENT),
        (ProxyState.MIXED_OR_CONTRADICTORY, 2, 4, False, CONFIDENCE_LOW),
        (ProxyState.OPTICAL_STRESS_ONLY, 3, 0, False, CONFIDENCE_LOW),
        (ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY, 0, 4, False, CONFIDENCE_LOW),
        (ProxyState.NO_STRESS_EVIDENCE, 3, 4, False, CONFIDENCE_MODERATE),
        (ProxyState.NO_STRESS_EVIDENCE, 1, 0, False, CONFIDENCE_LOW),
        (ProxyState.CONCORDANT_STRESS, 3, 4, False, CONFIDENCE_HIGH),
        (ProxyState.CONCORDANT_STRESS, 2, 4, False, CONFIDENCE_MODERATE),
        (ProxyState.CONCORDANT_STRESS, 3, 4, True, CONFIDENCE_LOW),
        (ProxyState.CONCORDANT_STRESS, 1, 4, False, CONFIDENCE_LOW),
    ]
    for state, n_opt, n_rad, poor, expected in cases:
        assert confidence_for(state, n_opt, n_rad, poor) == expected
        # Deterministic: identical inputs always agree.
        assert confidence_for(state, n_opt, n_rad, poor) == expected


def test_state_legend_covers_all_reported_codes():
    assert set(PROXY_STATE_LEGEND) == {1, 2, 3, 4, 5}
    assert PROXY_STATE_LEGEND[3] == "CONCORDANT_STRESS"


# ==========================================================================
# End-to-end proxy states (required cases 1-5)
# ==========================================================================


def test_no_inputs_gives_no_evidence(fake_multi):
    fake_multi(_s2_empty(), _radar_empty())
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_optical_only_gives_optical_stress_only(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_empty(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.OPTICAL_STRESS_ONLY))
    assert "LOW" in " ".join(result.provenance.caveats)


def test_radar_only_gives_structural_context_only(fake_multi):
    fake_multi(_s2_empty(), _radar_full())
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(
        float(ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY)
    )


def test_concordant_optical_plus_radar(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.CONCORDANT_STRESS))
    caveats = " ".join(result.provenance.caveats)
    assert "CONCORDANT_STRESS" in caveats
    assert "confidence: HIGH" in caveats


def test_contradictory_optical_signals_give_mixed(fake_multi):
    # NDMI drier but MSI less stressed than reference: material disagreement.
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(0.60, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(
        float(ProxyState.MIXED_OR_CONTRADICTORY)
    )


def test_no_stress_evidence_when_all_signals_favourable(fake_multi):
    fake_multi(
        _anomaly_windows(0.45, NDMI_BASE)
        + _anomaly_windows(0.60, MSI_BASE)
        + _anomaly_windows(0.55, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.NO_STRESS_EVIDENCE))


# ==========================================================================
# Missing-evidence discipline (required cases 6-7)
# ==========================================================================


def test_missing_radar_is_not_negative_evidence(fake_multi):
    """Optical stress without radar is OPTICAL_STRESS_ONLY, never mixed
    and never no-evidence: absence of corroboration is not contradiction."""
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(None, MSI_BASE)
        + _anomaly_windows(None, NDRE_BASE),
        _radar_empty(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.OPTICAL_STRESS_ONLY))


def test_missing_optical_is_not_negative_evidence(fake_multi):
    fake_multi(_s2_empty(), _radar_full())
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.value == pytest.approx(
        float(ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY)
    )
    assert "not negative evidence" in " ".join(result.provenance.caveats)


# ==========================================================================
# Radar discipline (required cases 11-12)
# ==========================================================================


def test_rvi_recorded_as_context_never_moisture(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(rvi=0.95),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    rvi_lines = [
        line
        for line in result.provenance.caveats
        if line.startswith("radar: rvi=")
    ]
    assert len(rvi_lines) == 1
    assert "context" in rvi_lines[0]
    assert "moisture" not in rvi_lines[0]


def test_vh_vv_recorded_as_db_context(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    vh_vv_lines = [
        line
        for line in result.provenance.caveats
        if line.startswith("radar: vh_vv=")
    ]
    assert len(vh_vv_lines) == 1
    assert "context" in vh_vv_lines[0]
    assert "linear" not in vh_vv_lines[0].lower()


# ==========================================================================
# Output honesty (required cases 13-14, 18)
# ==========================================================================


def test_no_percentage_output_anywhere(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    text = " ".join(
        [
            result.message or "",
            *result.warnings,
            *result.provenance.caveats,
            *result.provenance.limitations,
            MiddleCanopyDrynessProxyMetric().description,
        ]
    )
    assert "%" not in text
    assert "percent" not in text.lower()


def test_no_physical_leaf_water_output(fake_multi):
    metric = MiddleCanopyDrynessProxyMetric()
    assert not hasattr(metric, "to_leaf_water_content")
    assert not hasattr(metric, "to_dry_percentage")
    assert not hasattr(metric, "to_canopy_water_content")
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.value in (1.0, 2.0, 3.0, 4.0, 5.0)


def test_no_arbitrary_weighted_sum_in_source():
    import app.services.agriculture.canopy_proxy as module

    source = open(module.__file__, encoding="utf-8").read()
    import re

    assert not re.search(r"\d\.\d\s*\*\s*\w", source), "coefficient found"
    assert "no weights" in source.lower()


# ==========================================================================
# Temporal alignment (required case 15)
# ==========================================================================


def test_mismatched_component_window_is_excluded():
    """A component reporting a different window than requested is
    discarded rather than mixed into the concordance."""
    metric = MiddleCanopyDrynessProxyMetric()
    context = make_context()
    provenance = Provenance(
        source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        source_dataset_name="Sentinel-2",
        measurement_basis=MeasurementBasis.DERIVED,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2020-01-01",
        requested_end="2020-01-31",
    )
    result = MetricResult(
        metric_key="ndmi_anomaly",
        display_name="x",
        display_name_fa="x",
        value=-0.10,
        unit="index",
        provenance=provenance,
    )

    class _Mismatched:
        key = "ndmi_anomaly"

        @staticmethod
        def compute(_context):
            return result

    assert metric._component_result(_Mismatched, context) is None


def test_matching_component_window_is_kept():
    metric = MiddleCanopyDrynessProxyMetric()
    context = make_context()
    provenance = Provenance(
        source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        source_dataset_name="Sentinel-2",
        measurement_basis=MeasurementBasis.DERIVED,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2025-07-01",
        requested_end="2025-07-31",
    )
    result = MetricResult(
        metric_key="ndmi_anomaly",
        display_name="x",
        display_name_fa="x",
        value=-0.10,
        unit="index",
        provenance=provenance,
    )

    class _Matched:
        key = "ndmi_anomaly"

        @staticmethod
        def compute(_context):
            return result

    assert metric._component_result(_Matched, context) is result


def test_failing_component_becomes_missing_not_fatal(fake_multi, monkeypatch):
    """A component that raises is recorded missing; the proxy still
    classifies on the survivors."""
    from app.services.agriculture.radar import RVIMetric

    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )

    def _raise(_self, _context):
        raise RuntimeError("simulated EE failure")

    monkeypatch.setattr(RVIMetric, "compute", _raise)
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.CONCORDANT_STRESS))


# ==========================================================================
# Provenance ledger (required case 16)
# ==========================================================================


def test_ledger_preserves_every_component(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(None, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    caveats = result.provenance.caveats
    for key in (
        "ndmi_anomaly",
        "msi_anomaly",
        "ndre_anomaly",
        "vv",
        "vh",
        "vh_vv",
        "rvi",
    ):
        assert any(line.startswith(f"optical: {key}=") or line.startswith(f"radar: {key}=") for line in caveats), key
    assert any("optical votes:" in line for line in caveats)
    assert any("radar context:" in line for line in caveats)
    assert any("concordance state:" in line for line in caveats)
    assert any("confidence:" in line for line in caveats)
    assert any("temporal alignment:" in line for line in caveats)
    assert any("does not directly measure" in line for line in caveats)


def test_proxy_provenance_identifies_both_sensors(fake_multi):
    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    provenance = result.provenance
    assert provenance.source_dataset_id == "COPERNICUS/S2_SR_HARMONIZED"
    for band in ("B8", "B11", "B5", "VV", "VH"):
        assert band in provenance.bands


# ==========================================================================
# Flags, confidence quality, registration
# ==========================================================================


def test_derived_proxy_flags_are_correct(fake_multi):
    from app.services.agriculture.evidence import EvidenceItem

    fake_multi(
        _anomaly_windows(0.25, NDMI_BASE)
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE),
        _radar_full(),
    )
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.provenance.measurement_basis is MeasurementBasis.PROXY
    assert MiddleCanopyDrynessProxyMetric().metadata()["is_proxy"] is True
    item = EvidenceItem.from_result(result)
    assert item.is_proxy is True
    assert item.metric_key == "middle_canopy_dryness_proxy"


def test_poor_component_quality_caps_confidence(fake_multi):
    """One usable scene is poor quality: still concordant, but LOW."""
    s2 = (
        [_s2(0.25, scenes=1)]
        + [_s2(NDMI_BASE) for _ in range(10)]
        + _anomaly_windows(1.20, MSI_BASE)
        + _anomaly_windows(0.30, NDRE_BASE)
    )
    fake_multi(s2, _radar_full())
    result = MiddleCanopyDrynessProxyMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(ProxyState.CONCORDANT_STRESS))
    assert "confidence: LOW" in " ".join(result.provenance.caveats)


def test_proxy_registers_cleanly_and_reports_can_attempt():
    register_metrics(CANOPY_PROXY_METRICS)
    from app.services.agriculture.catalog import has_metric

    assert has_metric("middle_canopy_dryness_proxy")
    metric = MiddleCanopyDrynessProxyMetric()
    assert metric.source_bands == ("B8", "B11", "B5", "VV", "VH")
    can, reason = metric.can_attempt(make_context())
    assert can is True and reason is None
    old, _ = metric.can_attempt(
        make_context(start_date="2010-01-01", end_date="2010-12-31")
    )
    assert old is False
