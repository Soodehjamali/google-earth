"""Tests for the P2.1 multispectral spectral-profile foundation.

Covers the supported Sentinel-2 band set, wavelength metadata, the
reflectance/unit contract, visible/red-edge/NIR/SWIR groups, missing
and insufficient-quality handling, temporal identity, provenance,
deterministic ordering, geometry reuse, multiple observations,
unsupported-band refusal, the Pydantic round-trip, and the
terminology guards (no cause attribution, no hyperspectral claim).

Earth Engine is exercised through an injected fake serving one
configured outcome per requested window in chronological order.  No
network and no credentials are required.
"""

from __future__ import annotations

import math
import re
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.spectral_profile import (
    COMPOSITE_METHOD,
    NIR_BANDS,
    RED_EDGE_BANDS,
    S2_BAND_RESOLUTION_M,
    S2_BAND_WAVELENGTH_NM,
    S2_DATASET_ID,
    SPECTRAL_SCALE_FACTOR,
    SPECTRAL_UNIT,
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT,
    STATUS_UNAVAILABLE,
    SUPPORTED_SPECTRAL_BANDS,
    SWIR_BANDS,
    VISIBLE_BANDS,
    WAVELENGTH_SOURCE,
    SPECTRAL_CHANGE_POSSIBLE_CAUSES,
    SpectralObservation,
    SpectralProfile,
    band_resolution_m,
    band_series,
    band_wavelength_nm,
    build_spectral_observation,
    build_spectral_profile,
    describe_processing,
    is_supported_band,
    make_spectral_observation,
    nir_samples,
    normalize_band_set,
    observation_for_window,
    red_edge_samples,
    reflectance_scale_factor,
    require_supported_band,
    spectral_cache_dimensions,
    spectral_slopes,
    swir_samples,
    visible_samples,
)

AREA_SQ_M = 10000.0


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {"type": "Point", "coordinates": [51.0, 35.0]},
        "start_date": "2024-03-01",
        "end_date": "2024-03-31",
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": AREA_SQ_M},
    }
    fields.update(overrides)
    return MetricContext(**fields)


# ==========================================================================
# Injected fake Earth Engine (production composite path, no network)
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


_ALLOWED_FAKE_BANDS = set(SUPPORTED_SPECTRAL_BANDS) | {"SCL"}


class FakeSpectralEE:
    """One queued outcome per requested window, chronological order.

    Each month is ``{"scenes": int, "means": {band: value | None}}``.
    ``size()`` pops the next month; the following ``n_bands``
    reductions serve that month's band means before the month is
    released.
    """

    def __init__(
        self,
        months: List[Dict[str, Any]],
        n_bands: int,
        area_sq_m: float = AREA_SQ_M,
    ) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(months)
        self._n_bands = n_bands
        self._area = area_sq_m
        self._current: Optional[Dict[str, Any]] = None
        self._served = 0
        self.size_calls = 0
        self.selected_bands: List[str] = []
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeSpectralCollection(self)

    # -- month plumbing -------------------------------------------------
    def _pop_month(self) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake spectral queue exhausted on size()")
        self.size_calls += 1
        self._current = self._queue.popleft()
        self._served = 0
        return self._current

    def _serve_band(self, band: str, scale: int) -> Dict[str, Any]:
        if self._current is None:
            raise AssertionError(
                "fake spectral reduction with no current month"
            )
        means = self._current.get("means", {})
        if band not in means and band not in SUPPORTED_SPECTRAL_BANDS:
            raise AssertionError(f"fake asked for unknown band {band!r}")
        self.selected_bands.append(band)
        mean = means.get(band)
        self._served += 1
        if self._served >= self._n_bands:
            self._current = None
            self._served = 0
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        if not math.isfinite(mean):
            return {}
        value = float(mean)
        total = int(self._area / (scale * scale))
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


class _FakeSpectralCollection:
    def __init__(self, fake: FakeSpectralEE) -> None:
        self._fake = fake

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def size(self):
        return _FakeNumber(self._fake._pop_month()["scenes"])

    def map(self, func):
        func(_FakeSpectralImage(self._fake))
        return _FakeSpectralMapped(self._fake)


class _FakeSpectralMapped:
    def __init__(self, fake: FakeSpectralEE) -> None:
        self._fake = fake

    def median(self):
        return _FakeSpectralComposite(self._fake)


class _FakeSpectralImage:
    def __init__(self, fake: FakeSpectralEE) -> None:
        self._fake = fake

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in _ALLOWED_FAKE_BANDS:
                raise KeyError(f"fake holds {_ALLOWED_FAKE_BANDS}")
        return self

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee
        return self

    def multiply(self, _factor):
        return self

    def eq(self, _other):
        return _FakeNumber(0)


class _FakeSpectralComposite:
    def __init__(self, fake: FakeSpectralEE) -> None:
        self._fake = fake

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        return _FakeSpectralBandImage(self._fake, bands[0])


class _FakeSpectralBandImage:
    def __init__(self, fake: FakeSpectralEE, band: str) -> None:
        self._fake = fake
        self._band = band

    def reduceRegion(self, **kwargs):
        scale = kwargs.get("scale", 10)
        return _FakeSpectralRegion(self._fake, self._band, scale)


class _FakeSpectralRegion:
    def __init__(self, fake: FakeSpectralEE, band: str, scale: int) -> None:
        self._fake = fake
        self._band = band
        self._scale = scale

    def getInfo(self):
        return self._fake._serve_band(self._band, self._scale)


def _full_means(value: float = 0.25) -> Dict[str, float]:
    return {band: value for band in SUPPORTED_SPECTRAL_BANDS}


def _month(
    means: Optional[Mapping[str, Optional[float]]] = None,
    scenes: int = 6,
) -> Dict[str, Any]:
    return {"scenes": scenes, "means": dict(means or {})}


# ==========================================================================
# Supported band set
# ==========================================================================


def test_supported_band_set_is_exactly_the_ten_production_bands():
    assert SUPPORTED_SPECTRAL_BANDS == (
        "B2",
        "B3",
        "B4",
        "B5",
        "B6",
        "B7",
        "B8",
        "B8A",
        "B11",
        "B12",
    )


def test_supported_bands_match_registry_reflectance_bands():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset(S2_DATASET_ID)
    for band in SUPPORTED_SPECTRAL_BANDS:
        band_spec = spec.band(band)
        assert band_spec.unit == "reflectance"
        assert band_spec.scale_factor == SPECTRAL_SCALE_FACTOR


def test_b6_b7_flow_through_production_composite_path():
    fake = FakeSpectralEE([_month(_full_means(0.30))], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    assert "B6" in fake.selected_bands
    assert "B7" in fake.selected_bands
    assert observation.sample("B6").value == pytest.approx(0.30)
    assert observation.sample("B7").value == pytest.approx(0.30)


# ==========================================================================
# Band ordering and determinism
# ==========================================================================


def test_normalize_orders_by_wavelength_regardless_of_input_order():
    assert normalize_band_set(["B12", "B2", "B8A", "B4"]) == (
        "B2",
        "B4",
        "B8A",
        "B12",
    )


def test_normalize_deduplicates_and_defaults_to_full_set():
    assert normalize_band_set(None) == SUPPORTED_SPECTRAL_BANDS
    assert normalize_band_set(["B4", "B4", "B2"]) == ("B2", "B4")


def test_normalize_rejects_empty_set():
    with pytest.raises(ValueError):
        normalize_band_set([])


def test_observation_samples_are_in_wavelength_order():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        _full_means(0.2),
        quality="good",
    )
    assert observation.band_order == SUPPORTED_SPECTRAL_BANDS
    wavelengths = [sample.wavelength_nm for sample in observation.samples]
    assert wavelengths == sorted(wavelengths)


def test_deterministic_ordering_across_repeated_builds():
    first = make_spectral_observation(
        "2024-03-01", "2024-03-31", _full_means(0.2), quality="good"
    )
    second = make_spectral_observation(
        "2024-03-01", "2024-03-31", _full_means(0.2), quality="good"
    )
    assert first.to_dict() == second.to_dict()


# ==========================================================================
# Wavelength metadata
# ==========================================================================


def test_wavelength_metadata_values():
    assert S2_BAND_WAVELENGTH_NM == {
        "B2": 490.0,
        "B3": 560.0,
        "B4": 665.0,
        "B5": 705.0,
        "B6": 740.0,
        "B7": 783.0,
        "B8": 842.0,
        "B8A": 865.0,
        "B11": 1610.0,
        "B12": 2190.0,
    }


def test_wavelength_source_is_documented():
    assert "COPERNICUS/S2_SR_HARMONIZED" in WAVELENGTH_SOURCE
    assert "DATASETS.md" in WAVELENGTH_SOURCE
    assert "discrete" in WAVELENGTH_SOURCE


def test_band_wavelength_helper_rejects_unsupported():
    assert band_wavelength_nm("B5") == 705.0
    with pytest.raises(ValueError):
        band_wavelength_nm("B1")


def test_band_resolution_matches_catalogue_grids():
    assert band_resolution_m("B2") == 10
    assert band_resolution_m("B8") == 10
    assert band_resolution_m("B5") == 20
    assert band_resolution_m("B11") == 20
    assert S2_BAND_RESOLUTION_M.keys() == S2_BAND_WAVELENGTH_NM.keys()


# ==========================================================================
# Reflectance / unit contract
# ==========================================================================


def test_reflectance_unit_and_single_scale_factor():
    assert SPECTRAL_UNIT == "reflectance"
    assert reflectance_scale_factor() == 0.0001
    assert reflectance_scale_factor() == SPECTRAL_SCALE_FACTOR


def test_scale_factor_matches_every_registered_band():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset(S2_DATASET_ID)
    for band in SUPPORTED_SPECTRAL_BANDS:
        assert spec.band(band).scale_factor == reflectance_scale_factor()


def test_builder_passes_reflectance_through_unchanged():
    served = {
        "B2": 0.10,
        "B3": 0.15,
        "B4": 0.20,
        "B5": 0.25,
        "B6": 0.28,
        "B7": 0.32,
        "B8": 0.45,
        "B8A": 0.46,
        "B11": 0.22,
        "B12": 0.12,
    }
    fake = FakeSpectralEE([_month(served)], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    for band, expected in served.items():
        sample = observation.sample(band)
        assert sample.value == pytest.approx(expected)
        assert sample.unit == "reflectance"
    assert observation.unit == "reflectance"


def test_processing_description_states_single_scaling():
    processing = describe_processing()
    assert processing["scale_factor"] == 0.0001
    assert processing["unit"] == "reflectance"
    assert processing["dataset_id"] == S2_DATASET_ID


# ==========================================================================
# Spectral regions
# ==========================================================================


def test_visible_bands():
    assert VISIBLE_BANDS == ("B2", "B3", "B4")
    observation = make_spectral_observation(
        "2024-03-01", "2024-03-31", _full_means(0.2), quality="good"
    )
    assert [s.band for s in visible_samples(observation)] == ["B2", "B3", "B4"]


def test_red_edge_bands_are_independent():
    assert RED_EDGE_BANDS == ("B5", "B6", "B7")
    values = _full_means(0.2)
    values.update({"B5": 0.25, "B6": 0.30, "B7": 0.35})
    observation = make_spectral_observation(
        "2024-03-01", "2024-03-31", values, quality="good"
    )
    edge = red_edge_samples(observation)
    assert [s.band for s in edge] == ["B5", "B6", "B7"]
    assert [s.value for s in edge] == [0.25, 0.30, 0.35]
    assert [s.wavelength_nm for s in edge] == [705.0, 740.0, 783.0]
    # No single merged red-edge value exists on the observation.
    assert not hasattr(observation, "ndre")
    assert observation.sample("B5").value != observation.sample("B6").value


def test_nir_bands_are_independent():
    assert NIR_BANDS == ("B8", "B8A")
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B8": 0.45, "B8A": 0.46, **{b: 0.2 for b in ("B2",)}},
        band_set=["B8", "B8A"],
        quality="good",
    )
    assert [s.band for s in nir_samples(observation)] == ["B8", "B8A"]
    assert observation.sample("B8").wavelength_nm == 842.0
    assert observation.sample("B8A").wavelength_nm == 865.0


def test_swir_bands():
    assert SWIR_BANDS == ("B11", "B12")
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B11": 0.22, "B12": 0.12},
        band_set=["B11", "B12"],
        quality="good",
    )
    assert [s.band for s in swir_samples(observation)] == ["B11", "B12"]
    assert observation.sample("B11").wavelength_nm == 1610.0
    assert observation.sample("B12").wavelength_nm == 2190.0


def test_spectral_slopes_between_adjacent_bands():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B2": 0.10, "B3": 0.15, "B4": 0.20},
        band_set=["B2", "B3", "B4"],
        quality="good",
    )
    slopes = spectral_slopes(observation)
    assert len(slopes) == 2
    assert slopes[0].from_band == "B2"
    assert slopes[0].to_band == "B3"
    assert slopes[0].slope_per_nm == pytest.approx((0.15 - 0.10) / (560.0 - 490.0))
    assert slopes[1].slope_per_nm == pytest.approx((0.20 - 0.15) / (665.0 - 560.0))


def test_spectral_slope_is_missing_when_a_band_is_missing():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B2": 0.10, "B3": None, "B4": 0.20},
        band_set=["B2", "B3", "B4"],
        quality="moderate",
    )
    slopes = spectral_slopes(observation)
    assert slopes[0].slope_per_nm is None
    assert slopes[1].slope_per_nm is None


# ==========================================================================
# Missing data and quality
# ==========================================================================


def test_missing_bands_stay_explicit_and_never_zero():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B2": 0.10, "B4": None},
        band_set=["B2", "B3", "B4"],
        quality="moderate",
    )
    assert [s.band for s in observation.samples] == ["B2", "B3", "B4"]
    assert observation.sample("B2").status == STATUS_AVAILABLE
    assert observation.sample("B3").value is None
    assert observation.sample("B3").status == STATUS_INSUFFICIENT
    assert observation.sample("B4").value is None
    assert all(s.value != 0 for s in observation.samples if s.value is None)


def test_non_finite_values_are_gaps():
    observation = make_spectral_observation(
        "2024-03-01",
        "2024-03-31",
        {"B2": float("nan"), "B3": float("inf"), "B4": True},  # type: ignore[dict-item]
        band_set=["B2", "B3", "B4"],
        quality="moderate",
    )
    assert all(s.value is None for s in observation.samples)
    assert all(s.status == STATUS_INSUFFICIENT for s in observation.samples)


def test_no_scenes_means_insufficient_not_zero():
    fake = FakeSpectralEE([_month({}, scenes=0)], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    assert observation.image_count == 0
    assert observation.quality == STATUS_INSUFFICIENT
    assert all(s.value is None for s in observation.samples)
    assert all(s.status == STATUS_INSUFFICIENT for s in observation.samples)


def test_fully_masked_bands_are_insufficient():
    fake = FakeSpectralEE([_month({}, scenes=4)], n_bands=3)
    observation = build_spectral_observation(
        make_context(), bands=["B2", "B3", "B4"], ee_module=fake
    )
    assert observation.quality == STATUS_INSUFFICIENT
    assert all(s.value is None for s in observation.samples)
    assert all(s.status == STATUS_INSUFFICIENT for s in observation.samples)


def test_out_of_coverage_window_is_unavailable_without_observation():
    fake = FakeSpectralEE([], n_bands=10)
    observation = build_spectral_observation(
        make_context(start_date="2015-01-01", end_date="2015-01-31"),
        bands=None,
        ee_module=fake,
    )
    assert fake.size_calls == 0
    assert observation.quality == STATUS_UNAVAILABLE
    assert all(s.status == STATUS_UNAVAILABLE for s in observation.samples)


def test_unknown_quality_and_status_are_rejected():
    with pytest.raises(ValueError):
        make_spectral_observation(
            "2024-03-01", "2024-03-31", _full_means(0.2), quality="superb"
        )
    with pytest.raises(ValueError):
        make_spectral_observation(
            "2024-03-01",
            "2024-03-31",
            _full_means(0.2),
            quality="good",
            band_statuses={"B2": "excellent"},
        )


# ==========================================================================
# Temporal identity and multiple observations
# ==========================================================================


def test_single_window_uses_one_composite():
    fake = FakeSpectralEE([_month(_full_means(0.25))], n_bands=10)
    build_spectral_observation(make_context(), bands=None, ee_module=fake)
    assert fake.size_calls == 1


def test_single_observation_documents_composite_method():
    fake = FakeSpectralEE([_month(_full_means(0.25))], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    assert observation.composite_method == COMPOSITE_METHOD
    assert "median composite" in observation.composite_method


def test_profile_preserves_temporal_identity():
    months = [
        _month({"B2": 0.10 + i * 0.01, **{b: 0.2 for b in SUPPORTED_SPECTRAL_BANDS if b != "B2"}})
        for i in range(3)
    ]
    fake = FakeSpectralEE(months, n_bands=10)
    profile = build_spectral_profile(
        make_context(start_date="2024-01-01", end_date="2024-03-31"),
        bands=None,
        ee_module=fake,
    )
    assert profile.n_observations == 3
    windows = [
        (obs.window_start, obs.window_end) for obs in profile.observations
    ]
    assert windows == [
        ("2024-01-01", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),
        ("2024-03-01", "2024-03-31"),
    ]
    values = [obs.sample("B2").value for obs in profile.observations]
    assert values == [pytest.approx(0.10), pytest.approx(0.11), pytest.approx(0.12)]


def test_profile_keeps_gaps_without_collapsing():
    months = [_month(_full_means(0.2)), _month({}, scenes=0), _month(_full_means(0.3))]
    fake = FakeSpectralEE(months, n_bands=10)
    profile = build_spectral_profile(
        make_context(start_date="2024-01-01", end_date="2024-03-31"),
        bands=None,
        ee_module=fake,
    )
    assert profile.n_observations == 3
    assert profile.n_usable == 2
    assert profile.observations[1].n_available == 0
    assert profile.observations[1].samples[0].value is None


def test_profile_failed_month_becomes_missing():
    class _ExplodingEE(FakeSpectralEE):
        def ImageCollection(self, _dataset_id):  # noqa: N802
            raise RuntimeError("boom")

    profile = build_spectral_profile(
        make_context(start_date="2024-01-01", end_date="2024-01-31"),
        bands=["B2", "B4"],
        ee_module=_ExplodingEE([], n_bands=2),
    )
    assert profile.n_observations == 1
    assert profile.n_usable == 0
    assert all(
        s.status == STATUS_UNAVAILABLE
        for s in profile.observations[0].samples
    )


def test_band_series_and_window_lookup_support_history_hook():
    profile = SpectralProfile(
        band_set=("B2", "B4"),
        dataset_id=S2_DATASET_ID,
        unit=SPECTRAL_UNIT,
        composite_method=COMPOSITE_METHOD,
        window_start="2024-01-01",
        window_end="2024-02-29",
        observations=(
            make_spectral_observation(
                "2024-01-01", "2024-01-31", {"B2": 0.1, "B4": 0.2},
                band_set=["B2", "B4"], quality="good",
            ),
            make_spectral_observation(
                "2024-02-01", "2024-02-29", {"B2": None, "B4": 0.25},
                band_set=["B2", "B4"], quality="moderate",
            ),
        ),
    )
    series = band_series(profile, "B4")
    assert [entry["value"] for entry in series] == [0.2, 0.25]
    assert [entry["window_start"] for entry in series] == [
        "2024-01-01",
        "2024-02-01",
    ]
    assert observation_for_window(profile, "2024-02-01") is not None
    assert observation_for_window(profile, "2024-03-01") is None


# ==========================================================================
# Provenance
# ==========================================================================


def test_provenance_identifies_dataset_band_window_and_processing():
    fake = FakeSpectralEE([_month(_full_means(0.25))], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    payload = observation.provenance_payload()
    assert payload["source_dataset_id"] == S2_DATASET_ID
    assert payload["bands"] == list(SUPPORTED_SPECTRAL_BANDS)
    assert payload["requested_start"] == "2024-03-01"
    assert payload["requested_end"] == "2024-03-31"
    assert payload["unit"] == "reflectance"
    assert payload["quality_level"] == observation.quality
    assert payload["image_count"] == observation.image_count
    assert payload["scale_factor"] == 0.0001
    assert payload["cloud_mask_method"] == "scl"
    assert payload["wavelength_source"] == WAVELENGTH_SOURCE
    assert payload["measurement_basis"] == "direct"


def test_serialised_profile_carries_provenance_per_observation():
    fake = FakeSpectralEE([_month(_full_means(0.25))], n_bands=2)
    profile = build_spectral_profile(
        make_context(start_date="2024-03-01", end_date="2024-03-31"),
        bands=["B2", "B4"],
        ee_module=fake,
    )
    body = profile.to_dict()
    assert body["band_set"] == ["B2", "B4"]
    assert body["dataset_id"] == S2_DATASET_ID
    assert body["step"] == "calendar_month"
    assert body["observations"][0]["provenance"]["source_dataset_id"] == (
        S2_DATASET_ID
    )


# ==========================================================================
# Geometry and cache dimensions
# ==========================================================================


def test_geometry_contract_reuses_metric_context():
    context = make_context(geometry_key="field-42")
    dimensions = spectral_cache_dimensions(context, ["B4", "B2"])
    assert dimensions["geometry"] == "field-42"
    assert dimensions["window_start"] == "2024-03-01"
    assert dimensions["window_end"] == "2024-03-31"
    assert dimensions["band_set"] == ["B2", "B4"]
    assert dimensions["dataset_id"] == S2_DATASET_ID
    assert dimensions["band_scales_m"] == {"B2": 10, "B4": 10}
    assert "cloud_max_percent" in dimensions


def test_no_new_geometry_representation():
    import app.services.agriculture.spectral_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "class MetricContext" not in source
    assert "GeoJSON" not in source or "MetricContext" in source


# ==========================================================================
# Unsupported bands
# ==========================================================================


@pytest.mark.parametrize(
    "band", ["B1", "B9", "B10", "QA60", "SCL", "B13", "VV", "NDVI"]
)
def test_unsupported_bands_are_refused(band: str):
    assert not is_supported_band(band)
    with pytest.raises(ValueError, match="Supported Sentinel-2"):
        require_supported_band(band)
    with pytest.raises(ValueError, match="Supported Sentinel-2"):
        normalize_band_set(["B2", band])


def test_subset_selection_keeps_order_and_refuses_gaps():
    assert normalize_band_set(["B8A", "B2"]) == ("B2", "B8A")
    with pytest.raises(ValueError):
        normalize_band_set(["B2", "B1"])


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip():
    from app.schemas.agriculture import (
        SpectralObservationModel,
        SpectralProfileModel,
    )

    fake = FakeSpectralEE([_month(_full_means(0.25))], n_bands=10)
    observation = build_spectral_observation(
        make_context(), bands=None, ee_module=fake
    )
    profile = build_spectral_profile(
        make_context(start_date="2024-03-01", end_date="2024-03-31"),
        bands=["B2", "B4"],
        ee_module=FakeSpectralEE([_month({"B2": 0.1, "B4": 0.2})], n_bands=2),
    )
    obs_model = SpectralObservationModel.model_validate(
        observation.to_dict()
    )
    assert len(obs_model.samples) == 10
    assert obs_model.samples[0].band == "B2"
    assert obs_model.samples[0].wavelength_nm == 490.0

    profile_model = SpectralProfileModel.model_validate(profile.to_dict())
    assert profile_model.band_set == ["B2", "B4"]
    assert len(profile_model.observations) == 1
    dumped = profile_model.model_dump()
    assert SpectralProfileModel.model_validate(dumped) == profile_model


# ==========================================================================
# Guards: no database, no cause attribution, no over-claims
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.spectral_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    # Strip triple-quoted docstrings so denial statements and the
    # neutral cause documentation are not mistaken for behaviour.
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_no_cause_attribution_in_status_vocabulary():
    import app.services.agriculture.spectral_profile as module

    assert set(module.BAND_STATUSES) == {
        "available",
        "insufficient",
        "unavailable",
    }
    code = _code_without_docstrings().lower()
    # The neutral cause list is the only place these stems may appear.
    causes_block = re.search(
        r"spectral_change_possible_causes.*?\((.*?)\)", code, flags=re.DOTALL
    )
    assert causes_block is not None
    redacted = code.replace(causes_block.group(0), "")
    for stem in (
        "chlorosis",
        "defoliation",
        "wood-boring",
        "wood_boring",
        "diagnos",
        "risk_score",
        "probability",
        "anomaly threshold",
        "abnormal",
    ):
        assert stem not in redacted, f"forbidden stem {stem!r} in code"


def test_neutral_cause_list_covers_required_context():
    lowered = [cause.lower() for cause in SPECTRAL_CHANGE_POSSIBLE_CAUSES]
    joined = " ".join(lowered)
    for expected in (
        "phenology",
        "water status",
        "canopy structure",
        "management",
        "pests",
        "disease",
    ):
        assert expected in joined


def test_no_hyperspectral_or_continuity_claim():
    import app.services.agriculture.spectral_profile as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    assert "discrete multispectral observations" in source
    assert "not continuous" in source or "not\ncontinuous" in source
    for match in re.finditer(r"hyperspectral", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "not" in window, (
            "hyperspectral may only appear in an explicit denial"
        )
    code = _code_without_docstrings().lower()
    assert "interpolat" not in code or "never" in code or "not" in code


def test_no_scoring_modelling_or_thermal_implementation():
    code = _code_without_docstrings().lower()
    assert "sklearn" not in code
    assert "tensorflow" not in code
    assert "torch" not in code
    assert "risk_score" not in code
    assert "probability" not in code
    assert "thermal" not in code
    assert "lst_" not in code
    assert "def predict" not in code
    import app.services.agriculture.spectral_profile as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "probab" not in names
    assert "thermal" not in names
    assert "predict" not in names


def test_module_registers_no_metrics_and_touches_no_cache():
    import app.services.agriculture.spectral_profile as module

    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code
    assert "Metric(" not in code
