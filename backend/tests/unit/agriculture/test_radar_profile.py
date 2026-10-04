"""Tests for the P2.3 Sentinel-1 radar temporal profile foundation.

Covers registry discovery of the four CD-3 radar metrics,
supported/unsupported behavior, chronological calendar-month
ordering, temporal identity, missing/unavailable/failed months,
value/unit preservation, per-metric provenance, the IW /
descending / VV+VH acquisition policy, determinism, and the
terminology guards (no cause attribution, no anomaly logic).

Earth Engine is exercised through an injected fake serving one
configured outcome per requested month in chronological order,
recording the production filter and band selections.  No network
and no credentials are required.
"""

from __future__ import annotations

import math
import re
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.core.exceptions import DateRangeError
from app.services.agriculture.base import MetricContext
from app.services.agriculture.radar import (
    S1_DATASET_ID,
    S1_MODE,
    S1_PASS,
    S1_SCALE,
    RVIMetric,
    VHBackscatterMetric,
    VHVVRatioMetric,
    VVBackscatterMetric,
)
from app.services.agriculture.radar_profile import (
    SUPPORTED_RADAR_PROFILE_METRICS,
    RadarProfile,
    build_radar_profile,
    radar_metadata,
    to_temporal_profile,
    usable_values,
)

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


# ==========================================================================
# Injected fake Earth Engine (production S1 call chain, no network)
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


class FakeS1EE:
    """One queued outcome per requested month, chronological order.

    Each month is ``{"acquisitions": int, "mean": float | None}``.
    A month with ``"raise": True`` fails inside ``size()``.  The
    filter and band selections of the production path are recorded
    for policy assertions.
    """

    def __init__(self, months: List[Dict[str, Any]]) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(months)
        self._current: Optional[Dict[str, Any]] = None
        self.size_calls = 0
        self.filter_calls: List[Any] = []
        self.collection_selects: List[Any] = []
        self.image_selects: List[Any] = []
        self.renames: List[str] = []
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilter(self)
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeS1Collection(self)

    def _pop_month(self) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake S1 queue exhausted on size()")
        self.size_calls += 1
        month = self._queue.popleft()
        if month.get("raise"):
            raise RuntimeError("fake acquisition failure")
        self._current = month
        return month

    def _serve_stats(self, band: str, scale: int) -> Dict[str, Any]:
        if self._current is None:
            raise AssertionError("fake S1 reduction with no current month")
        mean = self._current.get("mean")
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        if not math.isfinite(mean):
            return {}
        value = float(mean)
        total = int(AREA_SQ_M / (scale * scale))
        return {
            f"{band}_mean": value,
            f"{band}_median": value,
            f"{band}_min": value,
            f"{band}_max": value,
            f"{band}_stdDev": 0.0,
            f"{band}_p10": value,
            f"{band}_p25": value,
            f"{band}_p75": value,
            f"{band}_p90": value,
            f"{band}_count": total,
        }


class _FakeFilter:
    def __init__(self, fake: FakeS1EE) -> None:
        self._fake = fake

    def eq(self, key, value):  # noqa: N802 - mirrors ee
        self._fake.filter_calls.append(("eq", key, value))
        return ("eq", key, value)

    def listContains(self, key, value):  # noqa: N802 - mirrors ee
        self._fake.filter_calls.append(("listContains", key, value))
        return ("listContains", key, value)


class _FakeImageNamespace:
    @staticmethod
    def constant(_value):
        return _FakeNumber(0)


class _FakeS1Collection:
    def __init__(self, fake: FakeS1EE) -> None:
        self._fake = fake

    def filterBounds(self, *_args):
        return self

    def filterDate(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        self._fake.collection_selects.append(list(bands))
        return self

    def size(self):
        return _FakeNumber(self._fake._pop_month()["acquisitions"])

    def mean(self):
        return _FakeS1Image(self._fake)


class _FakeS1Image:
    def __init__(self, fake: FakeS1EE) -> None:
        self._fake = fake

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        self._fake.image_selects.extend(bands)
        return self

    def expression(self, _formula, _variables):
        return self

    def rename(self, name):
        self._fake.renames.append(name)
        return self

    def divide(self, _value):
        return self

    def multiply(self, _value):
        return self

    def exp(self):
        return self

    def add(self, _other):
        return self

    def reduceRegion(self, **kwargs):
        return _FakeS1Region(
            self._fake, kwargs.get("scale", 10), self._fake.renames[-1]
        )


class _FakeS1Region:
    def __init__(self, fake: FakeS1EE, scale: int, band: str) -> None:
        self._fake = fake
        self._scale = scale
        self._band = band

    def getInfo(self):
        return self._fake._serve_stats(self._band, self._scale)


def _month(
    mean: Optional[float], acquisitions: int = 3, **extra
) -> Dict[str, Any]:
    outcome: Dict[str, Any] = {"mean": mean, "acquisitions": acquisitions}
    outcome.update(extra)
    return outcome


# ==========================================================================
# Registry discovery and supported set
# ==========================================================================


def test_radar_metrics_discovered_from_real_registry():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import get_metric, has_metric

    register_all_metrics()
    for key in ("vv", "vh", "vh_vv", "rvi"):
        assert has_metric(key)
        assert get_metric(key).key == key


def test_supported_set_maps_to_production_metric_classes():
    assert SUPPORTED_RADAR_PROFILE_METRICS == {
        "vv": VVBackscatterMetric,
        "vh": VHBackscatterMetric,
        "vh_vv": VHVVRatioMetric,
        "rvi": RVIMetric,
    }


def test_supported_metrics_share_one_production_contract():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import get_metric

    register_all_metrics()
    dataset_ids = set()
    for key in SUPPORTED_RADAR_PROFILE_METRICS:
        metric = get_metric(key)
        assert metric.primary_dataset_id == S1_DATASET_ID
        assert metric.default_scale == S1_SCALE
        dataset_ids.add(metric.primary_dataset_id)
    assert dataset_ids == {S1_DATASET_ID}


@pytest.mark.parametrize("key", ["ndvi", "VV", "rvi2", "unknown", ""])
def test_unsupported_metrics_are_refused_without_substitution(key: str):
    with pytest.raises(ValueError, match="Supported radar metrics"):
        build_radar_profile(key, make_context())
    with pytest.raises(ValueError, match="Supported radar metrics"):
        radar_metadata(key)


def test_malformed_window_is_rejected():
    with pytest.raises(DateRangeError):
        build_radar_profile(
            "vv",
            make_context(start_date="2024-03-31", end_date="2024-01-01"),
        )


# ==========================================================================
# Monthly temporal contract
# ==========================================================================


def _install_fake(monkeypatch, fake: FakeS1EE) -> None:
    import ee

    monkeypatch.setattr(ee, "ImageCollection", fake.ImageCollection)
    monkeypatch.setattr(ee, "Reducer", fake.Reducer)
    monkeypatch.setattr(ee, "Filter", fake.Filter)
    monkeypatch.setattr(ee, "Image", fake.Image)


def test_exact_calendar_month_windows_in_order(monkeypatch):
    fake = FakeS1EE([_month(-12.0), _month(-11.0), _month(-10.0)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vv", make_context())
    assert [(p.window_start, p.window_end) for p in profile.points] == [
        ("2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),
        ("2024-03-01", "2024-03-31"),
    ]
    assert profile.n_points == 3
    assert profile.step == "calendar_month"


def test_one_observation_per_month_preserves_identity(monkeypatch):
    fake = FakeS1EE([_month(-12.0), _month(-11.5), _month(-11.0)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vh", make_context())
    assert [p.value for p in profile.points] == [-12.0, -11.5, -11.0]
    assert profile.n_usable == 3
    assert usable_values(profile) == [-12.0, -11.5, -11.0]


def test_value_and_unit_preservation_per_metric(monkeypatch):
    _install_fake(monkeypatch, FakeS1EE([_month(-12.5)]))
    vv = build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert vv.points[0].value == pytest.approx(-12.5)
    assert vv.points[0].unit == "dB"
    assert vv.unit == "dB"

    _install_fake(monkeypatch, FakeS1EE([_month(0.65)]))
    rvi = build_radar_profile(
        "rvi", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert rvi.points[0].value == pytest.approx(0.65)
    assert rvi.points[0].unit == "ratio"
    assert rvi.unit == "ratio"


def test_missing_month_stays_missing_without_filling(monkeypatch):
    fake = FakeS1EE([_month(-12.0), _month(None), _month(-11.0)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vv", make_context())
    assert profile.n_points == 3
    assert profile.n_usable == 2
    assert profile.points[1].value is None
    assert profile.points[1].quality == "insufficient"
    assert usable_values(profile) == [-12.0, -11.0]


def test_zero_acquisitions_is_insufficient_not_zero(monkeypatch):
    fake = FakeS1EE([_month(None, acquisitions=0)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile(
        "vh", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert profile.points[0].value is None
    # The metric reports metric-level insufficient without provenance
    # (nothing ran), so the point vocabulary reads "unavailable" —
    # the P1.1 convention for windows where nothing ran at all.
    assert profile.points[0].quality == "unavailable"
    assert profile.points[0].image_count is None


def test_out_of_coverage_is_unavailable_without_ee_calls(monkeypatch):
    fake = FakeS1EE([])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile(
        "vv",
        make_context(start_date="2010-01-01", end_date="2010-03-31"),
    )
    assert fake.size_calls == 0
    assert profile.n_points == 3
    assert profile.n_usable == 0
    assert all(p.value is None for p in profile.points)
    assert all(p.quality == "unavailable" for p in profile.points)


def test_failed_month_is_explicitly_unavailable(monkeypatch):
    fake = FakeS1EE(
        [_month(-12.0), {"raise": True}, _month(-11.0)]
    )
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vv", make_context())
    assert [p.value for p in profile.points] == [-12.0, None, -11.0]
    assert profile.points[1].quality == "unavailable"
    assert profile.n_usable == 2


def _without_timestamps(body: Dict[str, Any]) -> Dict[str, Any]:
    """Drop wall-clock provenance stamps before determinism comparison."""
    import copy

    cleaned = copy.deepcopy(body)
    for point in cleaned.get("points", []):
        provenance = point.get("provenance") or {}
        provenance.pop("computed_at", None)
    return cleaned


def test_deterministic_ordering(monkeypatch):
    _install_fake(monkeypatch, FakeS1EE([_month(-12.0), _month(-11.0)]))
    first = build_radar_profile(
        "vh_vv", make_context(end_date="2024-02-29")
    ).to_dict()
    _install_fake(monkeypatch, FakeS1EE([_month(-12.0), _month(-11.0)]))
    second = build_radar_profile(
        "vh_vv", make_context(end_date="2024-02-29")
    ).to_dict()
    assert _without_timestamps(first) == _without_timestamps(second)


# ==========================================================================
# Provenance per metric
# ==========================================================================


def _one_month_point(monkeypatch, key: str, mean: float) -> Any:
    _install_fake(monkeypatch, FakeS1EE([_month(mean)]))
    profile = build_radar_profile(
        key, make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert profile.n_usable == 1
    return profile.points[0]


def test_vv_provenance(monkeypatch):
    point = _one_month_point(monkeypatch, "vv", -12.5)
    provenance = point.provenance
    assert provenance["source_dataset_id"] == S1_DATASET_ID
    assert provenance["bands"] == ["VV"]
    assert provenance["formula"] == "VV (dB)"
    assert provenance["unit"] == "dB"
    assert "temporal mean" in provenance["aggregation_method"]
    assert provenance["image_count"] == 3
    assert provenance["quality_level"] == point.quality


def test_vh_provenance(monkeypatch):
    point = _one_month_point(monkeypatch, "vh", -19.0)
    provenance = point.provenance
    assert provenance["source_dataset_id"] == S1_DATASET_ID
    assert provenance["bands"] == ["VH"]
    assert provenance["formula"] == "VH (dB)"
    assert provenance["unit"] == "dB"


def test_vh_vv_provenance_uses_registered_derivation(monkeypatch):
    point = _one_month_point(monkeypatch, "vh_vv", -7.0)
    provenance = point.provenance
    assert provenance["source_dataset_id"] == S1_DATASET_ID
    assert provenance["bands"] == ["VV", "VH"]
    assert provenance["unit"] == "dB"
    assert "temporal mean" in provenance["aggregation_method"]
    # Observed production quirk (CD-3, unmodified): the VHVV radar
    # name misses the formula registry key, so the formula field is
    # empty rather than fabricated.  Recorded, not repaired, here.
    assert provenance["formula"] == ""


def test_rvi_provenance(monkeypatch):
    point = _one_month_point(monkeypatch, "rvi", 0.65)
    provenance = point.provenance
    assert provenance["source_dataset_id"] == S1_DATASET_ID
    assert provenance["bands"] == ["VV", "VH"]
    assert "VH_linear" in provenance["formula"]
    assert provenance["unit"] == "ratio"


def test_sentinel1_dataset_identity(monkeypatch):
    _install_fake(monkeypatch, FakeS1EE([_month(-12.0)]))
    profile = build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert profile.dataset_id == S1_DATASET_ID == "COPERNICUS/S1_GRD"


# ==========================================================================
# Acquisition policy: IW mode, descending pass, polarizations
# ==========================================================================


def test_iw_descending_polarization_filter_policy(monkeypatch):
    fake = FakeS1EE([_month(-12.0)])
    _install_fake(monkeypatch, fake)
    build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert ("eq", "instrumentMode", "IW") in fake.filter_calls
    assert ("eq", "orbitProperties_pass", "DESCENDING") in fake.filter_calls
    assert (
        "listContains",
        "transmitterReceiverPolarisation",
        "VV",
    ) in fake.filter_calls
    assert (
        "listContains",
        "transmitterReceiverPolarisation",
        "VH",
    ) in fake.filter_calls
    assert ["VV", "VH"] in fake.collection_selects


def test_profile_carries_acquisition_policy(monkeypatch):
    _install_fake(monkeypatch, FakeS1EE([_month(-12.0)]))
    profile = build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert profile.mode == S1_MODE == "IW"
    assert profile.orbit_pass == S1_PASS == "DESCENDING"
    assert profile.scale_m == S1_SCALE == 10
    assert profile.polarizations == ("VV",)


def test_polarization_metadata_per_metric():
    assert radar_metadata("vv")["polarizations"] == ("VV",)
    assert radar_metadata("vh")["polarizations"] == ("VH",)
    assert radar_metadata("vh_vv")["polarizations"] == ("VV", "VH")
    assert radar_metadata("rvi")["polarizations"] == ("VV", "VH")
    for key in SUPPORTED_RADAR_PROFILE_METRICS:
        meta = radar_metadata(key)
        assert meta["mode"] == "IW"
        assert meta["orbit_pass"] == "DESCENDING"
        assert meta["scale_m"] == 10
        assert meta["dataset_id"] == S1_DATASET_ID


def test_no_silent_metric_substitution(monkeypatch):
    fake_vv = FakeS1EE([_month(-12.0)])
    _install_fake(monkeypatch, fake_vv)
    vv_profile = build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert vv_profile.metric_key == "vv"
    assert vv_profile.points[0].provenance["bands"] == ["VV"]
    assert "VH" not in fake_vv.image_selects

    fake_vh = FakeS1EE([_month(-12.0)])
    _install_fake(monkeypatch, fake_vh)
    vh_profile = build_radar_profile(
        "vh", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert vh_profile.metric_key == "vh"
    assert vh_profile.points[0].provenance["bands"] == ["VH"]
    assert "VV" not in fake_vh.image_selects


def test_vv_run_reads_only_vv(monkeypatch):
    fake = FakeS1EE([_month(-12.0)])
    _install_fake(monkeypatch, fake)
    build_radar_profile(
        "vv", make_context(start_date="2024-01-01", end_date="2024-01-31")
    )
    assert fake.image_selects == ["VV", "VV"]
    assert fake.renames == ["VV"]


# ==========================================================================
# Geometry contract
# ==========================================================================


def test_geometry_contract_reuses_metric_context():
    context = make_context(geometry_key="field-42")
    assert context.geometry_key == "field-42"
    assert context.geometry == {
        "type": "Point",
        "coordinates": [51.0, 35.0],
    }


def test_no_new_geometry_representation():
    import app.services.agriculture.radar_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "class MetricContext" not in source
    assert "ee.Geometry" not in source


# ==========================================================================
# Historical hook and serialisation
# ==========================================================================


def test_temporal_adapter_preserves_months_for_p12(monkeypatch):
    fake = FakeS1EE([_month(v) for v in (-13.0, -12.0, -11.0)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vv", make_context())
    adapted = to_temporal_profile(profile)
    assert adapted.metric_key == "vv"
    assert adapted.dataset_id == S1_DATASET_ID
    assert adapted.unit == "dB"
    assert [p.value for p in adapted.points] == [-13.0, -12.0, -11.0]
    assert [p.window_start for p in adapted.points] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
    ]


def test_p12_baseline_machinery_consumes_adapter(monkeypatch):
    from app.services.agriculture.baseline_anomaly import build_baseline

    fake = FakeS1EE([_month(-14.0 + i * 0.5) for i in range(8)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile(
        "vv",
        make_context(start_date="2024-01-01", end_date="2024-08-31"),
    )
    baseline = build_baseline(to_temporal_profile(profile))
    assert baseline is not None
    assert baseline.n_usable == 8


def test_serialised_profile_shape():
    profile = RadarProfile(
        metric_key="rvi",
        dataset_id=S1_DATASET_ID,
        unit="ratio",
        polarizations=("VV", "VH"),
        mode="IW",
        orbit_pass="DESCENDING",
        scale_m=10,
        window_start="2024-01-01",
        window_end="2024-01-31",
        points=(),
    )
    body = profile.to_dict()
    assert body["polarizations"] == ["VV", "VH"]
    assert body["mode"] == "IW"
    assert body["orbit_pass"] == "DESCENDING"
    assert body["scale_m"] == 10
    assert body["step"] == "calendar_month"


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip(monkeypatch):
    from app.schemas.agriculture import RadarProfileModel

    fake = FakeS1EE([_month(-12.0), _month(None)])
    _install_fake(monkeypatch, fake)
    profile = build_radar_profile("vh_vv", make_context(end_date="2024-02-29"))
    model = RadarProfileModel.model_validate(profile.to_dict())
    assert model.metric_key == "vh_vv"
    assert model.dataset_id == S1_DATASET_ID
    assert model.polarizations == ["VV", "VH"]
    assert model.mode == "IW"
    assert model.orbit_pass == "DESCENDING"
    assert model.scale_m == 10
    assert len(model.points) == 2
    assert model.points[0].value == pytest.approx(-12.0)
    assert model.points[1].value is None
    assert model.points[0].provenance["source_dataset_id"] == S1_DATASET_ID
    dumped = model.model_dump()
    assert RadarProfileModel.model_validate(dumped) == model


# ==========================================================================
# Guards: no database, no cause attribution, no anomaly logic
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.radar_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_no_pest_disease_terminology_in_classifications():
    import app.services.agriculture.radar_profile as module

    code = _code_without_docstrings().lower()
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "fungal",
        "chlorosis",
        "diagnos",
        "severity",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    assert set(module.SUPPORTED_RADAR_PROFILE_METRICS) == {
        "vv",
        "vh",
        "vh_vv",
        "rvi",
    }


def test_no_hyperspectral_terminology():
    code = _code_without_docstrings().lower()
    assert "hyperspectral" not in code


def test_no_anomaly_risk_probability_logic():
    code = _code_without_docstrings()
    lowered = code.replace("SAR_THRESHOLDS", "")
    for stem in (
        "z_score",
        "zscore",
        "anomal",
        "breakpoint",
        "persist",
        "risk",
        "probab",
        "sklearn",
        "torch",
        "tensorflow",
        "predict",
    ):
        assert stem not in lowered, f"forbidden stem {stem!r} in code"
    import app.services.agriculture.radar_profile as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "anomal" not in names
    assert "thermal" not in names


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_docstrings().lower()
    assert "interpolat" not in code
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.radar_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window


def test_module_registers_no_metrics_and_touches_no_cache():
    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code
