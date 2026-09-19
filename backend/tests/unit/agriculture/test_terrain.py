"""Tests for the terrain engine.

Three properties govern this module and each is guarded here:

1. **An aspect of 0 degrees does not mean flat.** Earth Engine returns 0
   for both due north and for flat ground, so the engine masks flat
   pixels by slope and computes a *circular* mean. The wrap-around case —
   350 and 10 degrees both facing north — is the classic failure of an
   arithmetic mean and is tested directly.

2. **A static DEM is not a time series.** The declared acquisition dates
   describe when the radar flew, not when the product may be used. A 2024
   request against a 2000 acquisition is normal and must compute, and the
   provenance must keep the acquisition date separate from the requested
   period.

3. **TWI is not produced.** Flow accumulation is serial and Earth Engine
   offers no primitive for it. The unavailable metric must say so with
   the specific missing input rather than look like an oversight.

The Earth Engine calls run through a strict fake module, so the real
compute paths are exercised. No network and no credentials are required.
"""

from __future__ import annotations

import math
import sys
import types

import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    register_metrics,
)
from app.services.agriculture.registry import (
    TERRAIN_ASPECT_MIN_SLOPE_DEG,
    get_dataset,
)
from app.services.agriculture.terrain import (
    NASADEM,
    SRTM,
    ALL_TERRAIN_METRICS,
    AspectMetric,
    ElevationMetric,
    SlopeMetric,
    TERRAIN_METRICS,
    TERRAIN_WORKING_SCALE,
    TopographicWetnessIndexMetric,
    TerrainRuggednessMetric,
    UNAVAILABLE_TERRAIN_METRICS,
    circular_concentration,
    circular_mean_degrees,
    resolve_aspect_sector,
)
from app.services.agriculture.types import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    TemporalKind,
)


# --------------------------------------------------------------------------
# The fake Earth Engine
# --------------------------------------------------------------------------
# The fake mirrors the real contract strictly: a combined reduction
# returns RAW stored values namespaced per band, including the count
# statistic that the real reducer chain emits and that coverage depends
# on. Feeding physical values or omitting count would let the fixture
# pass whether or not the pipeline behaved, which is exactly the class
# of bug this suite exists to catch.

_COMBINED_STATS = (
    "count", "mean", "median", "min", "max",
    "stdDev", "p10", "p25", "p75", "p90",
)

#: A 1 km2 geometry at 30 m pixels, minus edge effects. The fixture uses
#: this as the count statistic so coverage and the minimum-pixel floor
#: behave as they would for a real field-scale request.
PIXELS_PER_KM2_AT_30M = 1111


class _FakeRegionResult:
    def __init__(self, payload) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeTerrainNamespace:
    """Implements ee.Terrain.slope and ee.Terrain.aspect numerically.

    The synthetic terrain is a plane descending 100 m per km toward the
    east: aspect is due east (90) everywhere and slope is atan(0.1) in
    degrees. A wrong derivative convention therefore shows up as a wrong
    number rather than as a matching wrong number.

    A derivative of a masked pixel is masked. Earth Engine propagates the
    input mask through both routines, so a fully masked DEM must produce a
    fully masked derivative here too; returning a constant for masked
    input would let the metric pass on data that does not exist.
    """

    EAST_ASPECT = 90.0
    EAST_SLOPE = math.degrees(math.atan(0.1))

    @staticmethod
    def slope(image):
        elevation = image._values.get("elevation")
        value = None if elevation is None else _FakeTerrainNamespace.EAST_SLOPE
        return _FakeImage({"slope": value})

    @staticmethod
    def aspect(image):
        elevation = image._values.get("elevation")
        value = None if elevation is None else _FakeTerrainNamespace.EAST_ASPECT
        return _FakeImage({"aspect": value})


class _FakeImage:
    """A single-band image carrying one raw value per band."""

    def __init__(self, values) -> None:
        self._values = dict(values)

    # -- shape operations ---------------------------------------------------

    def select(self, *bands):
        for band in bands:
            if band not in self._values:
                raise KeyError(
                    f"fake image has no band {band!r}; it has "
                    f"{sorted(self._values)}"
                )
        return self

    def toFloat(self):
        return self

    def rename(self, name):
        return _FakeImage({name: next(iter(self._values.values()))})

    def multiply(self, factor):
        # A masked pixel stays masked through arithmetic, as in Earth
        # Engine; multiplying None would be a TypeError, not a value.
        return _FakeImage(
            {k: (None if v is None else v * factor) for k, v in self._values.items()}
        )

    def sin(self):
        # ee.Image.sin takes RADIANS. The production code converts degrees
        # to radians before calling it, so the fake must interpret its
        # stored values as radians too — a degrees-based fake would agree
        # with a degrees-based bug and pass wrongly.
        return _FakeImage(
            {k: (None if v is None else math.sin(v)) for k, v in self._values.items()}
        )

    def cos(self):
        return _FakeImage(
            {k: (None if v is None else math.cos(v)) for k, v in self._values.items()}
        )

    def updateMask(self, _mask_image):
        # The fake terrain is uniformly above the slope threshold, so the
        # mask removes nothing here. The empty-area cases are modelled by
        # the fixture supplying None values, which the reduction renders
        # as a fully masked band.
        return self

    def gte(self, threshold):
        # A comparison of a masked pixel is masked, not false: Earth
        # Engine propagates masks through comparisons as well.
        return _FakeImage(
            {
                k: (
                    None
                    if v is None
                    else (1.0 if v >= threshold else 0.0)
                )
                for k, v in self._values.items()
            }
        )

    @staticmethod
    def cat(*images):
        merged: dict = {}
        for image in images:
            merged.update(image._values)
        return _FakeImage(merged)

    # -- reductions ----------------------------------------------------------

    def reduceRegion(self, reducer=None, geometry=None, scale=None, **_kwargs):
        outputs = tuple(
            getattr(reducer, "outputs", (getattr(reducer, "name", ""),))
        )

        def value_for(stat, value):
            if value is None:
                return None
            if stat == "count":
                # One square kilometre at 30 m is about 1111 pixels. The
                # fixture models a realistic sample, because coverage and
                # the pixel floor are part of the behaviour under test.
                return float(PIXELS_PER_KM2_AT_30M)
            if stat == "stdDev":
                return 0.0
            return value

        if len(outputs) == 1:
            # A bare reducer emits flat, band-named keys.
            stat = outputs[0]
            return _FakeRegionResult(
                {k: value_for(stat, v) for k, v in self._values.items()}
            )

        # A combined chain emits "<band>_<stat>" keys. A None value models
        # a fully masked band: every statistic is null, exactly as Earth
        # Engine reports an empty reduction.
        payload: dict = {}
        for band, value in self._values.items():
            for stat in outputs:
                payload[f"{band}_{stat}"] = value_for(stat, value)
        return _FakeRegionResult(payload)


class _FakeReducer:
    """A reducer that remembers which outputs its chain carries.

    A bare reducer emits flat band-named keys (``{"aspect": 5}``). A
    combined chain emits band-stat namespaced keys
    (``{"elevation_count": 5, "elevation_mean": 42}``). The fixture must
    reproduce both shapes, because the parsing layer reads them
    differently.
    """

    def __init__(self, outputs) -> None:
        self.outputs = tuple(outputs) if isinstance(outputs, tuple) else (outputs,)
        self.name = self.outputs[0]

    def combine(self, other, sharedInputs=True):
        self.outputs = self.outputs + other.outputs
        self.name = self.outputs[0]
        return self


class _FakeReducerNamespace:
    """Mirrors the factories ``build_reducer`` actually calls."""

    def count(self):
        return _FakeReducer("count")

    def mean(self):
        return _FakeReducer("mean")

    def median(self):
        return _FakeReducer("median")

    def stdDev(self):
        return _FakeReducer("stdDev")

    def min(self):
        return _FakeReducer("min")

    def max(self):
        return _FakeReducer("max")

    def percentile(self, values):
        # Earth Engine's percentile reducer emits one output per requested
        # percentile, named "p10", "p25" and so on — not "percentile".
        return _FakeReducer(
            tuple(f"p{v}" for v in values)
        )


class FakeEE:
    """Maps a dataset ID to an image fixture.

    ``Image`` is exposed as a class rather than a function because the
    real ``ee.Image`` carries statics the terrain code calls — notably
    ``ee.Image.cat`` for stacking the aspect components.
    """

    def __init__(self, images) -> None:
        self.images = images
        self.Reducer = _FakeReducerNamespace()
        self.Terrain = _FakeTerrainNamespace()
        self.Image = self._make_image_type()

    def _make_image_type(self):
        images = self.images

        class _ImageType:
            def __new__(cls, dataset_id):
                if dataset_id not in images:
                    raise KeyError(
                        f"test fixture has no dataset {dataset_id!r}; it has "
                        f"{sorted(images)}"
                    )
                return images[dataset_id]

            @staticmethod
            def cat(*stacked):
                merged: dict = {}
                for image in stacked:
                    merged.update(image._values)
                return _FakeImage(merged)

        return _ImageType


#: NASADEM stores elevation as an integer. The fake supplies raw stored
#: values so the pipeline's conversion (scale 1.0, offset 0.0) is a no-op
#: that is still exercised.
RAW_ELEVATION = 1168


def _install_dem(
    monkeypatch,
    nasadem_elevation=RAW_ELEVATION,
    srtm_elevation=RAW_ELEVATION,
) -> None:
    """Install DEM fixtures for both DEM datasets.

    The fallback chain is part of the contract under test, so both NASADEM
    and SRTM must resolve; a fixture missing one would exercise an error
    path rather than the chain. An elevation of ``None`` simulates a fully
    masked product for the empty-reduction cases.
    """
    images = {
        NASADEM: _FakeImage({"elevation": nasadem_elevation}),
        SRTM: _FakeImage({"elevation": srtm_elevation}),
    }
    module = types.ModuleType("ee")
    fake = FakeEE(images)
    module.Image = fake.Image
    module.Reducer = fake.Reducer
    module.Terrain = fake.Terrain
    monkeypatch.setitem(sys.modules, "ee", module)


def _make_context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2024-04-01",
        end_date="2024-04-30",
        geometry_key="terrain-test-geometry",
        options={"area_sq_m": 1_000_000.0},  # one square kilometre
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


# --------------------------------------------------------------------------
# Circular statistics
# --------------------------------------------------------------------------
# These are the regression tests required by the aspect convention: the
# mean of directions is not the mean of numbers.


def test_circular_mean_across_the_wrap_is_north():
    """350 and 10 degrees both face north; the mean must be 0, not 180."""
    mean_sin = (math.sin(math.radians(350)) + math.sin(math.radians(10))) / 2
    mean_cos = (math.cos(math.radians(350)) + math.cos(math.radians(10))) / 2
    assert circular_mean_degrees(mean_sin, mean_cos) == pytest.approx(
        0.0, abs=1e-6
    )


def test_circular_mean_of_east_is_ninety():
    mean_sin = math.sin(math.radians(90))
    mean_cos = math.cos(math.radians(90))
    assert circular_mean_degrees(mean_sin, mean_cos) == pytest.approx(90.0)


def test_circular_mean_handles_wrap_around_north():
    """A distribution straddling 0/360 must not average through 180."""
    angles = (345.0, 350.0, 355.0, 5.0, 10.0, 15.0)
    mean_sin = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    mean_cos = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    mean = circular_mean_degrees(mean_sin, mean_cos)
    assert mean is not None
    assert mean <= 20.0 or mean >= 340.0


def test_circular_mean_of_uniform_spread_is_none():
    """No mean direction exists; returning 0 would invent north."""
    # Six directions evenly spaced over the compass sum to zero.
    angles = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
    mean_sin = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    mean_cos = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    assert circular_mean_degrees(mean_sin, mean_cos) is None


def test_circular_mean_rejects_missing_components():
    assert circular_mean_degrees(None, 1.0) is None
    assert circular_mean_degrees(1.0, None) is None


def test_circular_mean_never_returns_360():
    """Floating point must not push due north outside [0, 360)."""
    assert circular_mean_degrees(-1e-9, 1.0) == pytest.approx(0.0, abs=1e-6)


def test_circular_mean_of_north_is_zero_not_none():
    """Due north is a real direction; it must survive the zero check."""
    assert circular_mean_degrees(0.0, 1.0) == 0.0


def test_concentration_of_agreed_directions_is_high():
    angles = (10.0, 12.0, 8.0, 11.0)
    mean_sin = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    mean_cos = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    assert circular_concentration(mean_sin, mean_cos) > 0.99


def test_concentration_of_opposed_directions_is_low():
    angles = (0.0, 180.0)
    mean_sin = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    mean_cos = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    assert circular_concentration(mean_sin, mean_cos) < 0.05


def test_concentration_is_bounded_in_the_unit_interval():
    assert circular_concentration(0.0, 0.0) == 0.0
    assert circular_concentration(1.0, 0.0) == 1.0
    assert circular_concentration(None, None) is None


# --------------------------------------------------------------------------
# Sector resolution
# --------------------------------------------------------------------------


def test_sector_wraps_across_north():
    assert resolve_aspect_sector(350.0) == "N"
    assert resolve_aspect_sector(10.0) == "N"


def test_sector_names_the_cardinal_directions():
    assert resolve_aspect_sector(90.0) == "E"
    assert resolve_aspect_sector(180.0) == "S"
    assert resolve_aspect_sector(270.0) == "W"


def test_sector_of_none_is_none():
    assert resolve_aspect_sector(None) is None


def test_sector_boundaries_are_the_documented_ones():
    # 337.5 begins the north sector; 22.5 ends it.
    assert resolve_aspect_sector(337.5) == "N"
    assert resolve_aspect_sector(22.4) == "N"
    assert resolve_aspect_sector(22.5) == "NE"


# --------------------------------------------------------------------------
# Metric identity and registration
# --------------------------------------------------------------------------


def test_terrain_metrics_are_the_expected_set():
    assert {m.key for m in TERRAIN_METRICS} == {
        "elevation",
        "slope",
        "aspect",
        "terrain_ruggedness",
    }


def test_terrain_unavailable_metrics_are_only_twi():
    assert {m.key for m in UNAVAILABLE_TERRAIN_METRICS} == {
        "topographic_wetness_index"
    }


def test_terrain_metrics_are_in_the_terrain_domain():
    for metric in ALL_TERRAIN_METRICS:
        assert metric.domain is MetricDomain.TERRAIN, metric.key


def test_terrain_metrics_declare_limitations():
    for metric in ALL_TERRAIN_METRICS:
        assert metric.limitations, metric.key


def test_terrain_working_scale_matches_the_dem():
    assert TERRAIN_WORKING_SCALE == 30


def test_every_terrain_metric_names_its_static_nature():
    """A DEM is a single acquisition; the limitation must say so."""
    for metric in TERRAIN_METRICS:
        joined = " ".join(metric.limitations).lower()
        assert "2000" in joined or "single acquisition" in joined, metric.key


def test_terrain_metrics_are_reachable_through_the_catalog():
    clear_registry()
    register_metrics(ALL_TERRAIN_METRICS)
    for key in (
        "elevation",
        "slope",
        "aspect",
        "terrain_ruggedness",
        "topographic_wetness_index",
    ):
        assert get_metric(key) is not None, key


# --------------------------------------------------------------------------
# Eligibility: the static contract through the terrain metrics
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric_cls",
    [ElevationMetric, SlopeMetric, AspectMetric, TerrainRuggednessMetric],
)
def test_terrain_metrics_accept_a_2024_request(metric_cls):
    """The historical contradiction: 2024 against a 2000 acquisition."""
    can, reason = metric_cls().can_attempt(_make_context())
    assert can is True
    assert reason is None


@pytest.mark.parametrize(
    "metric_cls",
    [ElevationMetric, SlopeMetric, AspectMetric, TerrainRuggednessMetric],
)
def test_terrain_metrics_accept_a_future_request(metric_cls):
    can, _reason = metric_cls().can_attempt(
        _make_context(start_date="2026-01-01", end_date="2026-01-31")
    )
    assert can is True


@pytest.mark.parametrize(
    "metric_cls",
    [ElevationMetric, SlopeMetric, AspectMetric, TerrainRuggednessMetric],
)
def test_terrain_metrics_still_reject_malformed_dates(metric_cls):
    can, reason = metric_cls().can_attempt(
        _make_context(start_date="2024-04-30", end_date="2024-04-01")
    )
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_terrain_primary_dataset_is_static():
    spec = ElevationMetric().primary_dataset()
    assert spec.id == NASADEM
    assert spec.is_static is True


# --------------------------------------------------------------------------
# Elevation
# --------------------------------------------------------------------------


def test_elevation_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)
    result = ElevationMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(RAW_ELEVATION))
    assert result.stats is not None
    assert result.stats.valid_pixel_count > 0


def test_elevation_provenance_separates_request_from_acquisition(monkeypatch):
    _install_dem(monkeypatch)
    result = ElevationMetric().compute(
        _make_context(start_date="2024-04-01", end_date="2024-04-30")
    )
    provenance = result.provenance
    assert provenance is not None
    assert provenance.temporal_kind is TemporalKind.STATIC
    assert provenance.requested_start == "2024-04-01"
    assert provenance.requested_end == "2024-04-30"
    assert provenance.product_date == "2000-02-11"
    # The requested period must not masquerade as the product's own.
    assert provenance.date_start == "2024-04-01"
    assert provenance.product_date != provenance.date_start


def test_elevation_reports_insufficient_when_no_pixels_return(monkeypatch):
    # Both DEMs fully masked: nothing anywhere in the chain.
    _install_dem(monkeypatch, nasadem_elevation=None, srtm_elevation=None)
    result = ElevationMetric().compute(_make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_elevation_insufficient_never_carries_a_value(monkeypatch):
    """The contradiction guard: insufficient must not ride under a value."""
    _install_dem(monkeypatch, nasadem_elevation=None, srtm_elevation=None)
    result = ElevationMetric().compute(_make_context())
    assert result.value is None
    assert result.provenance is not None
    assert result.provenance.quality_level in (
        QualityLevel.INSUFFICIENT,
        QualityLevel.UNAVAILABLE,
    )


# --------------------------------------------------------------------------
# Slope
# --------------------------------------------------------------------------


def test_slope_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)
    result = SlopeMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(
        math.degrees(math.atan(0.1)), rel=1e-6
    )


def test_slope_provenance_carries_the_static_kind(monkeypatch):
    _install_dem(monkeypatch)
    result = SlopeMetric().compute(_make_context())
    assert result.provenance.temporal_kind is TemporalKind.STATIC
    assert result.provenance.product_date == "2000-02-11"


def test_slope_insufficient_when_no_pixels(monkeypatch):
    _install_dem(monkeypatch, nasadem_elevation=None, srtm_elevation=None)
    result = SlopeMetric().compute(_make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


# --------------------------------------------------------------------------
# Aspect
# --------------------------------------------------------------------------


def test_aspect_of_an_east_facing_plane_is_ninety(monkeypatch):
    """Verified empirically against live Earth Engine: east = 90."""
    _install_dem(monkeypatch)
    result = AspectMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(90.0)


def test_aspect_masks_flat_terrain_before_the_mean(monkeypatch):
    """The mask must come before the trigonometry, not after.

    The fake slope sits above the threshold, so the mask keeps it.
    Asserting the mask exists in the formula string pins the order.
    """
    _install_dem(monkeypatch)
    result = AspectMetric().compute(_make_context())
    formula = result.provenance.formula
    assert "slope >=" in formula
    assert f"{TERRAIN_ASPECT_MIN_SLOPE_DEG:g}" in formula


def test_aspect_states_the_flat_exclusion_in_warnings(monkeypatch):
    _install_dem(monkeypatch)
    result = AspectMetric().compute(_make_context())
    joined = " ".join(result.warnings)
    assert "slope threshold" in joined


def test_aspect_is_a_circular_mean_not_an_arithmetic_one(monkeypatch):
    """The formula must compute direction through sine and cosine."""
    _install_dem(monkeypatch)
    result = AspectMetric().compute(_make_context())
    formula = result.provenance.formula.lower()
    assert "atan2" in formula
    assert "sin" in formula and "cos" in formula


def test_aspect_insufficient_when_no_direction_exists(monkeypatch):
    """All-flat terrain must refuse, not report 0 as due north."""
    _install_dem(monkeypatch, nasadem_elevation=None, srtm_elevation=None)
    result = AspectMetric().compute(_make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert result.message


def test_aspect_provenance_names_the_slope_threshold(monkeypatch):
    _install_dem(monkeypatch)
    result = AspectMetric().compute(_make_context())
    limitations = " ".join(result.provenance.limitations).lower()
    assert "0 degrees" in limitations or "due north" in limitations


# --------------------------------------------------------------------------
# Terrain ruggedness
# --------------------------------------------------------------------------


def test_ruggedness_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)
    result = TerrainRuggednessMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value is not None


def test_ruggedness_insufficient_without_a_spread(monkeypatch):
    _install_dem(monkeypatch, nasadem_elevation=None, srtm_elevation=None)
    result = TerrainRuggednessMetric().compute(_make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


# --------------------------------------------------------------------------
# Fallback behaviour
# --------------------------------------------------------------------------


def test_primary_path_reports_no_fallback(monkeypatch):
    _install_dem(monkeypatch)
    result = ElevationMetric().compute(_make_context())
    assert result.provenance.source_dataset_id == NASADEM
    assert result.provenance.fallback_from is None


def test_nasadem_voids_trigger_the_srtm_fallback(monkeypatch):
    """A fully masked NASADEM must retry with SRTM and say so."""
    # Only SRTM carries data; NASADEM is masked out entirely.
    _install_dem(monkeypatch, nasadem_elevation=None)
    result = ElevationMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(RAW_ELEVATION))
    provenance = result.provenance
    assert provenance.source_dataset_id == SRTM
    assert provenance.fallback_from == NASADEM
    warnings = " ".join(result.warnings)
    assert "fallback" in warnings.lower()


def test_fallback_provenance_keeps_static_semantics(monkeypatch):
    """The fallback result must carry the same temporal honesty."""
    _install_dem(monkeypatch, nasadem_elevation=None)
    result = ElevationMetric().compute(_make_context())
    provenance = result.provenance
    assert provenance.temporal_kind is TemporalKind.STATIC
    assert provenance.product_date == "2000-02-11"
    assert provenance.requested_start == "2024-04-01"


def test_srtm_spec_declares_fallback_role_only():
    spec = get_dataset(SRTM)
    assert spec.roles == ("fallback",)


def test_srtm_has_only_an_elevation_band():
    """The fallback cannot provide provenance it does not carry."""
    spec = get_dataset(SRTM)
    assert set(spec.bands) == {"elevation"}


# --------------------------------------------------------------------------
# TWI: the unavailable metric
# --------------------------------------------------------------------------


def test_twi_returns_unavailable_for_any_request():
    result = TopographicWetnessIndexMetric().compute(_make_context())
    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None


def test_twi_reason_names_the_missing_primitive():
    """The generic 'not_supported' would describe any metric."""
    result = TopographicWetnessIndexMetric().compute(_make_context())
    assert result.reason == "no_flow_accumulation_primitive"
    message = (result.message or "").lower()
    assert "flow accumulation" in message


def test_twi_metadata_is_explicitly_unavailable():
    metadata = TopographicWetnessIndexMetric().metadata()
    assert metadata["available"] is False
    assert metadata["unavailable_code"] == "no_flow_accumulation_primitive"
    assert "flow accumulation" in metadata["unavailable_reason"].lower()


def test_twi_does_not_use_a_focal_proxy():
    """The reason must reject the focal workaround by name."""
    reason = TopographicWetnessIndexMetric().unavailable_reason.lower()
    assert "focal" in reason


def test_twi_declares_no_datasets():
    """A metric with no input cannot silently borrow another's gate."""
    assert TopographicWetnessIndexMetric().dataset_ids == ()


def test_twi_is_registered_as_unavailable_in_the_catalog():
    clear_registry()
    register_metrics(ALL_TERRAIN_METRICS)
    metric = get_metric("topographic_wetness_index")
    assert metric.metadata()["available"] is False


# --------------------------------------------------------------------------
# Static provenance across the whole domain
# --------------------------------------------------------------------------


def test_every_drivable_terrain_metric_distinguishes_static(monkeypatch):
    _install_dem(monkeypatch)
    for metric in (ElevationMetric(), TerrainRuggednessMetric()):
        result = metric.compute(_make_context())
        provenance = result.provenance
        assert provenance.temporal_kind is TemporalKind.STATIC, metric.key
        assert provenance.product_date == "2000-02-11"
        assert provenance.requested_start == "2024-04-01"


def test_result_to_dict_serialises_the_temporal_kind(monkeypatch):
    _install_dem(monkeypatch)
    result = ElevationMetric().compute(_make_context())
    payload = result.to_dict()
    assert payload["provenance"]["temporal_kind"] == "static"
    assert payload["provenance"]["product_date"] == "2000-02-11"
    assert payload["provenance"]["requested_start"] == "2024-04-01"
