"""Tests for the P2.2 red-edge diagnostics foundation.

Covers the exact slope formula, wavelength ordering, each of the
four slopes, the normalized diagnostics, insufficient/unavailable
handling, missing months, temporal ordering, previous-observation
changes, provenance, units/metadata, determinism, and the
terminology guards (no cause attribution, no hyperspectral claim).

Diagnostics consume finished P2.1 observations built directly
(P2.1 proves they come out of the production composite path); one
test additionally feeds a fake Earth Engine composite through the
real P2.1 builder into the diagnostics.  No network and no
credentials are required.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pytest

from app.services.agriculture.red_edge import (
    INDEX_UNIT,
    RED_EDGE_DIAGNOSTIC_IDS,
    RED_EDGE_DIAGNOSTIC_SPECS,
    RED_EDGE_INPUT_BANDS,
    RED_EDGE_NORMALIZED_IDS,
    SLOPE_UNIT,
    RedEdgeSeries,
    analyze_red_edge_series,
    compute_red_edge_diagnostics,
    diagnostic_series,
    red_edge_slope,
    to_temporal_profile,
)
from app.services.agriculture.spectral_profile import (
    COMPOSITE_METHOD,
    S2_DATASET_ID,
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT,
    STATUS_UNAVAILABLE,
    SUPPORTED_SPECTRAL_BANDS,
    SpectralProfile,
    build_spectral_observation,
    make_spectral_observation,
)
from app.services.agriculture.base import MetricContext


def make_observation(
    values: Mapping[str, Optional[float]],
    window_start: str = "2024-03-01",
    window_end: str = "2024-03-31",
    quality: str = "good",
    band_set=None,
    **kwargs,
):
    return make_spectral_observation(
        window_start,
        window_end,
        dict(values),
        image_count=6,
        coverage_percent=90.0,
        quality=quality,
        band_set=band_set,
        **kwargs,
    )


FULL_VALUES = {
    "B2": 0.10,
    "B3": 0.14,
    "B4": 0.20,
    "B5": 0.30,
    "B6": 0.36,
    "B7": 0.42,
    "B8": 0.50,
    "B8A": 0.52,
    "B11": 0.25,
    "B12": 0.15,
}


def make_profile(month_values: List[Mapping[str, Optional[float]]]) -> SpectralProfile:
    observations = tuple(
        make_observation(
            values,
            window_start=f"2024-{index + 1:02d}-01",
            window_end=f"2024-{index + 1:02d}-28",
        )
        for index, values in enumerate(month_values)
    )
    return SpectralProfile(
        band_set=SUPPORTED_SPECTRAL_BANDS,
        dataset_id=S2_DATASET_ID,
        unit="reflectance",
        composite_method=COMPOSITE_METHOD,
        window_start="2024-01-01",
        window_end="2024-03-28",
        observations=observations,
    )


# ==========================================================================
# Registry and ordering
# ==========================================================================


def test_diagnostic_registry_is_exactly_the_seven_implemented():
    assert RED_EDGE_DIAGNOSTIC_IDS == (
        "re_slope_b4_b5",
        "re_slope_b5_b6",
        "re_slope_b6_b7",
        "re_slope_b7_b8a",
        "re_nd_b6_b5",
        "re_nd_b7_b5",
        "re_nd_b8a_b5",
    )


def test_wavelength_ordering_of_inputs():
    from app.services.agriculture.spectral_profile import S2_BAND_WAVELENGTH_NM

    assert RED_EDGE_INPUT_BANDS == ("B4", "B5", "B6", "B7", "B8A")
    for identifier in RED_EDGE_DIAGNOSTIC_IDS:
        spec = RED_EDGE_DIAGNOSTIC_SPECS[identifier]
        bands = spec["inputs"]
        wavelengths = [S2_BAND_WAVELENGTH_NM[band] for band in bands]
        if spec["kind"] == "slope":
            # Slopes run low to high wavelength.
            assert wavelengths == sorted(wavelengths)
        else:
            # Normalized differences store formula order (high, low);
            # wavelengths stay aligned with the input bands.
            assert wavelengths == sorted(wavelengths, reverse=True)
        assert len(bands) == 2


def test_monthly_sets_follow_registry_order():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    assert monthly.diagnostic_order == RED_EDGE_DIAGNOSTIC_IDS


# ==========================================================================
# Exact slope formula: (r2 - r1) / (wl2 - wl1)
# ==========================================================================


def test_slope_formula_is_explicit_and_wavelength_aware():
    assert RED_EDGE_DIAGNOSTIC_SPECS["re_slope_b4_b5"]["formula"] == (
        "(B5 - B4) / (705 - 665)"
    )
    assert RED_EDGE_DIAGNOSTIC_SPECS["re_slope_b7_b8a"]["formula"] == (
        "(B8A - B7) / (865 - 783)"
    )
    assert red_edge_slope(0.20, 0.30, "B4", "B5") == pytest.approx(
        (0.30 - 0.20) / (705.0 - 665.0)
    )
    assert red_edge_slope(0.20, 0.30, "B4", "B5") == pytest.approx(0.0025)


def test_b4_b5_slope():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    item = monthly.diagnostic("re_slope_b4_b5")
    assert item.value == pytest.approx((0.30 - 0.20) / 40.0)
    assert item.unit == SLOPE_UNIT == "reflectance/nm"
    assert item.status == STATUS_AVAILABLE
    assert item.input_bands == ("B4", "B5")
    assert item.wavelengths_nm == (665.0, 705.0)


def test_b5_b6_slope():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    item = monthly.diagnostic("re_slope_b5_b6")
    assert item.value == pytest.approx((0.36 - 0.30) / 35.0)


def test_b6_b7_slope():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    item = monthly.diagnostic("re_slope_b6_b7")
    assert item.value == pytest.approx((0.42 - 0.36) / 43.0)


def test_b7_b8a_slope():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    item = monthly.diagnostic("re_slope_b7_b8a")
    assert item.value == pytest.approx((0.52 - 0.42) / 82.0)
    assert item.wavelengths_nm == (783.0, 865.0)


def test_slope_returns_none_for_missing_ends():
    assert red_edge_slope(None, 0.3, "B4", "B5") is None
    assert red_edge_slope(0.2, None, "B4", "B5") is None
    assert red_edge_slope(float("nan"), 0.3, "B4", "B5") is None


def test_b7_b8a_slope_does_not_read_b8():
    without_b8 = {k: v for k, v in FULL_VALUES.items() if k != "B8"}
    first = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    second = compute_red_edge_diagnostics(make_observation(without_b8))
    assert second.diagnostic("re_slope_b7_b8a").value == pytest.approx(
        first.diagnostic("re_slope_b7_b8a").value
    )
    altered = dict(FULL_VALUES)
    altered["B8"] = 0.99
    third = compute_red_edge_diagnostics(make_observation(altered))
    assert third.diagnostic("re_slope_b7_b8a").value == pytest.approx(
        first.diagnostic("re_slope_b7_b8a").value
    )


# ==========================================================================
# Normalized diagnostics
# ==========================================================================


def test_normalized_diagnostic_formulas():
    assert RED_EDGE_DIAGNOSTIC_SPECS["re_nd_b6_b5"]["formula"] == (
        "(B6 - B5) / (B6 + B5)"
    )
    assert RED_EDGE_DIAGNOSTIC_SPECS["re_nd_b7_b5"]["formula"] == (
        "(B7 - B5) / (B7 + B5)"
    )
    assert RED_EDGE_DIAGNOSTIC_SPECS["re_nd_b8a_b5"]["formula"] == (
        "(B8A - B5) / (B8A + B5)"
    )
    assert RED_EDGE_NORMALIZED_IDS == (
        "re_nd_b6_b5",
        "re_nd_b7_b5",
        "re_nd_b8a_b5",
    )


def test_normalized_values_are_hand_computed():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    assert monthly.diagnostic("re_nd_b6_b5").value == pytest.approx(
        (0.36 - 0.30) / (0.36 + 0.30)
    )
    assert monthly.diagnostic("re_nd_b7_b5").value == pytest.approx(
        (0.42 - 0.30) / (0.42 + 0.30)
    )
    assert monthly.diagnostic("re_nd_b8a_b5").value == pytest.approx(
        (0.52 - 0.30) / (0.52 + 0.30)
    )
    for identifier in RED_EDGE_NORMALIZED_IDS:
        assert monthly.diagnostic(identifier).unit == INDEX_UNIT == "index"


def test_zero_denominator_is_insufficient_not_zero():
    values = dict(FULL_VALUES)
    values.update({"B5": 0.0, "B6": 0.0, "B7": 0.0, "B8A": 0.0})
    monthly = compute_red_edge_diagnostics(
        make_observation(values, quality="moderate")
    )
    for identifier in RED_EDGE_NORMALIZED_IDS:
        item = monthly.diagnostic(identifier)
        assert item.value is None
        assert item.status == STATUS_INSUFFICIENT


# ==========================================================================
# Insufficient / unavailable handling
# ==========================================================================


def test_insufficient_inputs_yield_explicit_missing():
    values = dict(FULL_VALUES)
    values["B6"] = None
    monthly = compute_red_edge_diagnostics(
        make_observation(values, quality="moderate")
    )
    assert monthly.diagnostic("re_slope_b5_b6").value is None
    assert monthly.diagnostic("re_slope_b5_b6").status == STATUS_INSUFFICIENT
    assert monthly.diagnostic("re_slope_b6_b7").status == STATUS_INSUFFICIENT
    assert monthly.diagnostic("re_nd_b6_b5").status == STATUS_INSUFFICIENT
    # Diagnostics whose inputs are intact remain available.
    assert monthly.diagnostic("re_slope_b4_b5").status == STATUS_AVAILABLE
    assert monthly.diagnostic("re_nd_b8a_b5").status == STATUS_AVAILABLE


def test_unavailable_observation_yields_unavailable_diagnostics():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {},
        quality="unavailable",
        band_set=list(SUPPORTED_SPECTRAL_BANDS),
        default_status="unavailable",
    )
    monthly = compute_red_edge_diagnostics(observation)
    assert monthly.n_available == 0
    for item in monthly.diagnostics:
        assert item.value is None
        assert item.status == STATUS_UNAVAILABLE


def test_subset_band_set_marks_only_affected_diagnostics():
    observation = make_observation(
        {"B4": 0.2, "B5": 0.3, "B6": 0.36, "B7": 0.42},
        band_set=["B4", "B5", "B6", "B7"],
        quality="good",
    )
    monthly = compute_red_edge_diagnostics(observation)
    assert monthly.diagnostic("re_slope_b4_b5").status == STATUS_AVAILABLE
    assert monthly.diagnostic("re_slope_b7_b8a").status == STATUS_INSUFFICIENT
    assert monthly.diagnostic("re_nd_b8a_b5").status == STATUS_INSUFFICIENT


def test_full_identifier_set_present_when_inputs_missing():
    values = dict(FULL_VALUES)
    values["B5"] = None
    monthly = compute_red_edge_diagnostics(
        make_observation(values, quality="moderate")
    )
    assert monthly.diagnostic_order == RED_EDGE_DIAGNOSTIC_IDS
    assert len(monthly.diagnostics) == 7


# ==========================================================================
# Temporal behavior
# ==========================================================================


def test_temporal_ordering_preserved():
    profile = make_profile([FULL_VALUES, FULL_VALUES, FULL_VALUES])
    series = analyze_red_edge_series(profile)
    assert series.n_months == 3
    assert [m.window_start for m in series.monthly] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
    ]
    assert series.window_start == "2024-01-01"
    assert series.dataset_id == S2_DATASET_ID


def test_previous_observation_change_behavior():
    first = dict(FULL_VALUES)
    second = dict(FULL_VALUES)
    second["B6"] = 0.40  # slope b5->b6 rises from (0.36-0.30)/35
    profile = make_profile([first, second])
    series = analyze_red_edge_series(profile)
    slope_changes = [
        c for c in series.changes if c.diagnostic_id == "re_slope_b5_b6"
    ]
    assert len(slope_changes) == 2
    expected_prev = (0.36 - 0.30) / 35.0
    expected_curr = (0.40 - 0.30) / 35.0
    # First month has no predecessor: the direction reads
    # INSUFFICIENT while the month's own value is preserved
    # (the P1.3 month_changes convention).
    assert slope_changes[0].direction == "INSUFFICIENT"
    assert slope_changes[0].value == pytest.approx(expected_prev)
    assert slope_changes[0].previous_value is None
    assert slope_changes[0].absolute_change is None
    # Second month compares against the exact predecessor.
    change = slope_changes[1]
    assert change.previous_value == pytest.approx(expected_prev)
    assert change.value == pytest.approx(expected_curr)
    assert change.absolute_change == pytest.approx(expected_curr - expected_prev)
    assert change.relative_change == pytest.approx(
        (expected_curr - expected_prev) / abs(expected_prev)
    )
    assert change.previous_window_start == "2024-01-01"
    assert change.window_start == "2024-02-01"
    assert change.days_elapsed == 31
    assert change.rate_per_day == pytest.approx(
        (expected_curr - expected_prev) / 31
    )
    assert change.direction == "INCREASE"


def test_decrease_stable_and_zero_previous_conventions():
    base = dict(FULL_VALUES)
    lower = dict(FULL_VALUES)
    lower["B6"] = 0.32
    repeated = dict(lower)
    profile = make_profile([base, lower, repeated])
    series = analyze_red_edge_series(profile)
    slope_changes = [
        c for c in series.changes if c.diagnostic_id == "re_slope_b5_b6"
    ]
    assert slope_changes[1].direction == "DECREASE"
    # Identical consecutive months produce an exact-zero step: STABLE.
    assert slope_changes[2].absolute_change == pytest.approx(0.0)
    assert slope_changes[2].direction == "STABLE"


def test_relative_change_is_none_when_previous_is_zero():
    flat = {"B4": 0.2, "B5": 0.2, "B6": 0.2, "B7": 0.2, "B8A": 0.2}
    risen = {"B4": 0.2, "B5": 0.2, "B6": 0.25, "B7": 0.2, "B8A": 0.2}
    profile = make_profile([flat, risen])
    series = analyze_red_edge_series(profile)
    change = [
        c for c in series.changes if c.diagnostic_id == "re_slope_b5_b6"
    ][1]
    assert change.previous_value == pytest.approx(0.0)
    assert change.relative_change is None
    assert change.direction == "INCREASE"


def test_missing_month_breaks_the_step_without_bridging():
    gap = {band: None for band in FULL_VALUES}
    profile = make_profile([FULL_VALUES, gap, FULL_VALUES])
    series = analyze_red_edge_series(profile)
    slope_changes = [
        c for c in series.changes if c.diagnostic_id == "re_slope_b5_b6"
    ]
    assert slope_changes[1].direction == "INSUFFICIENT"
    assert slope_changes[1].absolute_change is None
    # The month after the gap also refuses: its exact predecessor
    # carries no finite value.
    assert slope_changes[2].direction == "INSUFFICIENT"
    assert slope_changes[2].value is not None
    assert slope_changes[2].previous_value is None


def test_missing_months_are_never_zero_filled():
    gap = {band: None for band in FULL_VALUES}
    profile = make_profile([FULL_VALUES, gap])
    series = analyze_red_edge_series(profile)
    assert series.monthly[1].n_available == 0
    rows = diagnostic_series(series, "re_slope_b4_b5")
    assert rows[1]["value"] is None
    assert all(row["value"] != 0 for row in rows if row["value"] is None)


# ==========================================================================
# Provenance, units, metadata
# ==========================================================================


def test_provenance_preservation_per_diagnostic():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    payload = monthly.diagnostic_provenance("re_slope_b4_b5")
    assert payload["source_dataset_id"] == S2_DATASET_ID
    assert payload["diagnostic_id"] == "re_slope_b4_b5"
    assert payload["formula"] == "(B5 - B4) / (705 - 665)"
    assert payload["input_bands"] == ["B4", "B5"]
    assert payload["wavelengths_nm"] == [665.0, 705.0]
    assert payload["unit"] == SLOPE_UNIT
    assert payload["status"] == STATUS_AVAILABLE
    assert payload["requested_start"] == "2024-03-01"
    assert payload["quality_level"] == "good"
    assert payload["image_count"] == 6
    assert "limitations" in payload and payload["limitations"]


def test_serialised_series_carries_windows_quality_and_provenance():
    profile = make_profile([FULL_VALUES, FULL_VALUES])
    body = analyze_red_edge_series(profile).to_dict()
    assert body["diagnostic_ids"] == list(RED_EDGE_DIAGNOSTIC_IDS)
    assert body["dataset_id"] == S2_DATASET_ID
    assert body["step"] == "calendar_month"
    first = body["monthly"][0]
    assert first["window_start"] == "2024-01-01"
    assert first["quality"] == "good"
    assert first["provenance"]["source_dataset_id"] == S2_DATASET_ID
    assert len(first["diagnostics"]) == 7
    assert first["diagnostics"][0]["provenance"]["diagnostic_id"] == (
        "re_slope_b4_b5"
    )
    assert len(body["changes"]) == 2 * 7


def test_diagnostic_lookup_refuses_unknown_ids():
    monthly = compute_red_edge_diagnostics(make_observation(FULL_VALUES))
    with pytest.raises(KeyError):
        monthly.diagnostic("re_slope_b2_b3")
    profile = make_profile([FULL_VALUES])
    series = analyze_red_edge_series(profile)
    with pytest.raises(ValueError, match="Supported diagnostics"):
        diagnostic_series(series, "ndre")
    with pytest.raises(ValueError, match="Supported diagnostics"):
        to_temporal_profile(series, "ndre")


# ==========================================================================
# Determinism and no-interpolation
# ==========================================================================


def test_deterministic_output():
    profile = make_profile([FULL_VALUES, FULL_VALUES])
    first = analyze_red_edge_series(profile).to_dict()
    second = analyze_red_edge_series(profile).to_dict()
    assert first == second


def test_no_interpolated_wavelengths_in_formulas():
    slope_formulas = " ".join(
        RED_EDGE_DIAGNOSTIC_SPECS[identifier]["formula"]
        for identifier in RED_EDGE_DIAGNOSTIC_IDS[:4]
    )
    for invented in ("720", "750", "760", "800", "830"):
        assert invented not in slope_formulas


# ==========================================================================
# P1.2 historical hook: generic baseline machinery consumes the adapter
# ==========================================================================


def test_p12_baseline_machinery_consumes_diagnostic_series():
    from app.services.agriculture.baseline_anomaly import build_baseline

    months = []
    for index in range(8):
        values = dict(FULL_VALUES)
        values["B6"] = 0.34 + index * 0.01
        months.append(values)
    series = analyze_red_edge_series(make_profile(months))
    adapted = to_temporal_profile(series, "re_slope_b5_b6")
    assert adapted.metric_key == "re_slope_b5_b6"
    assert adapted.unit == SLOPE_UNIT
    assert adapted.n_points == 8
    assert [p.window_start for p in adapted.points] == [
        f"2024-{index + 1:02d}-01" for index in range(8)
    ]
    baseline = build_baseline(adapted)
    assert baseline is not None
    assert baseline.n_usable == 8


# ==========================================================================
# Production-path integration: fake composite -> P2.1 -> diagnostics
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
        return _FakeNumber(0)


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
    def lte(_key, _value):  # noqa: N802 - mirrors ee
        return ("lte",)


class _FakeImageNamespace:
    @staticmethod
    def constant(_value):
        return _FakeNumber(0)


class _FakeEE:
    def __init__(self, means: Dict[str, float], area: float = 10000.0) -> None:
        self._means = means
        self._area = area
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeCollection(self)


class _FakeCollection:
    def __init__(self, fake: _FakeEE) -> None:
        self._fake = fake

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def size(self):
        return _FakeNumber(6)

    def map(self, func):
        func(_FakeImage())
        return _FakeMapped(self._fake)


class _FakeMapped:
    def __init__(self, fake: _FakeEE) -> None:
        self._fake = fake

    def median(self):
        return _FakeComposite(self._fake)


class _FakeImage:
    def select(self, _bands):
        return self

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee
        return self

    def multiply(self, _factor):
        return self

    def eq(self, _other):
        return _FakeNumber(0)


class _FakeComposite:
    def __init__(self, fake: _FakeEE) -> None:
        self._fake = fake

    def select(self, bands):
        return _FakeBand(self._fake, bands[0] if isinstance(bands, list) else bands)


class _FakeBand:
    def __init__(self, fake: _FakeEE, band: str) -> None:
        self._fake = fake
        self._band = band

    def reduceRegion(self, **kwargs):
        return _FakeRegion(self._fake, self._band, kwargs.get("scale", 10))


class _FakeRegion:
    def __init__(self, fake: _FakeEE, band: str, scale: int) -> None:
        self._fake = fake
        self._band = band
        self._scale = scale

    def getInfo(self):
        value = self._fake._means[self._band]
        total = int(self._fake._area / (self._scale * self._scale))
        key = self._band
        return {
            f"{key}_mean": value,
            f"{key}_median": value,
            f"{key}_min": value,
            f"{key}_max": value,
            f"{key}_stdDev": 0.0,
            f"{key}_p10": value,
            f"{key}_p25": value,
            f"{key}_p75": value,
            f"{key}_p90": value,
            f"{key}_count": total,
        }


def test_diagnostics_consume_production_builder_output():
    context = MetricContext(
        geometry={"type": "Point", "coordinates": [51.0, 35.0]},
        start_date="2024-03-01",
        end_date="2024-03-31",
        geometry_key="test-geometry",
        options={"area_sq_m": 10000.0},
    )
    observation = build_spectral_observation(
        context, bands=None, ee_module=_FakeEE(dict(FULL_VALUES))
    )
    monthly = compute_red_edge_diagnostics(observation)
    assert monthly.n_available == 7
    assert monthly.diagnostic("re_slope_b4_b5").value == pytest.approx(
        (0.30 - 0.20) / 40.0
    )
    assert monthly.diagnostic_provenance("re_nd_b8a_b5")[
        "source_dataset_id"
    ] == S2_DATASET_ID


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip():
    from app.schemas.agriculture import RedEdgeChangeModel, RedEdgeSeriesModel

    profile = make_profile([FULL_VALUES, FULL_VALUES])
    series = analyze_red_edge_series(profile)
    model = RedEdgeSeriesModel.model_validate(series.to_dict())
    assert model.diagnostic_ids == list(RED_EDGE_DIAGNOSTIC_IDS)
    assert len(model.monthly) == 2
    assert len(model.monthly[0].diagnostics) == 7
    assert model.monthly[0].diagnostics[0].diagnostic_id == "re_slope_b4_b5"
    assert model.monthly[0].diagnostics[0].wavelengths_nm == [665.0, 705.0]
    dumped = model.model_dump()
    assert RedEdgeSeriesModel.model_validate(dumped) == model
    change = RedEdgeChangeModel.model_validate(series.changes[7].to_dict())
    assert change.direction in ("INCREASE", "DECREASE", "STABLE", "INSUFFICIENT")


# ==========================================================================
# Guards: no database, no cause attribution, no over-claims
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.red_edge as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_no_biological_terminology_in_runtime_classifications():
    import app.services.agriculture.red_edge as module

    code = _code_without_docstrings().lower()
    # The reused P1.3 direction helper is change semantics, not a
    # biological label; allowlist its identifier.
    code = code.replace("classify_direction", "")
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "fungal",
        "chlorosis",
        "diagnosi",
        "diagnose",
        "severity",
        "risk",
        "probab",
        "threshold",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    assert set(module.DIRECTION_LABELS) == {
        "INCREASE",
        "DECREASE",
        "STABLE",
        "INSUFFICIENT",
    }


def test_no_hyperspectral_terminology_in_implementation():
    import app.services.agriculture.red_edge as module

    code = _code_without_docstrings().lower()
    assert "hyperspectral" not in code
    assert "continuous" not in code
    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    assert "discrete multispectral" in source
    for match in re.finditer(r"hyperspectral", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "not" in window


def test_no_scoring_modelling_thermal_or_radar_implementation():
    code = _code_without_docstrings().lower()
    assert "sklearn" not in code
    assert "tensorflow" not in code
    assert "torch" not in code
    assert "thermal" not in code
    assert "radar" not in code
    assert "sentinel-1" not in code and "sentinel_1" not in code
    assert "def predict" not in code
    assert "register_metric" not in code
    assert "cache_service" not in code
    import app.services.agriculture.red_edge as module

    names = " ".join(dir(module)).lower()
    assert "thermal" not in names
    assert "radar" not in names
    assert "risk" not in names
    assert "probab" not in names


def test_module_reuses_p21_structures():
    import app.services.agriculture.red_edge as module
    import app.services.agriculture.spectral_profile as p21

    assert module.S2_DATASET_ID == p21.S2_DATASET_ID
    assert module.COMPOSITE_METHOD == p21.COMPOSITE_METHOD
    assert set(module.RED_EDGE_INPUT_BANDS) <= set(p21.SUPPORTED_SPECTRAL_BANDS)
