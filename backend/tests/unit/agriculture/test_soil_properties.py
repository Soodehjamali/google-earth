"""Tests for soil properties and root-zone soil context.

This module exercises the soil property domain: static physical and
chemical characteristics of the soil profile as opposed to soil moisture
(water currently in the soil). The governing risks are:

1. **Scale-factor confusion.** SoilGrids bands are stored as integers
   with non-trivial scale factors. Applying the factor twice, omitting
   it, or applying the wrong one produces plausible-looking numbers that
   are wrong by exactly the factor. Every metric that reads SoilGrids
   layers must apply the scale factor exactly once.

2. **Depth-weighting errors.** An arithmetic mean across the six
   SoilGrids depth intervals would implicitly treat layers of 5, 10, 15,
   30, and 40 cm as equally thick. The correct aggregation is a
   thickness-weighted mean. A metric that gets this wrong produces a
   number biased toward the thinner surface layers.

3. **Silent depth substitution.** When a requested depth does not
   correspond to an actual SoilGrids layer, the metric must refuse
   rather than silently select the nearest layer.

4. **STATIC temporal contract.** SoilGrids is a static modelled
   prediction. A 2024 request must compute; the product date is
   provenance metadata, not a coverage gate.

5. **Unit integrity.** SoilGrids publishes in physical units after
   dividing by d-factors. The engine must publish the converted value
   under the correct unit, not the raw stored integer's unit.

6. **Unavailable metrics.** Soil organic carbon, texture, pH, CEC,
   bulk density, coarse fragments, salinity, and texture class are
   intentionally registered as unavailable because their Earth Engine
   layers do not exist. The reason must name the specific missing layer,
   not a generic "not supported".

The Earth Engine calls are exercised through a strict fake module so
the real compute paths run. No network and no credentials are required.
"""

from __future__ import annotations

import math
import sys
import types
from typing import Any, Dict, Optional, Sequence, Tuple

import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    register_metrics,
)
from app.services.agriculture.registry import get_dataset, has_dataset
from app.services.agriculture.registry.external import (
    EXTERNAL_REGISTRY,
    SOILGRIDS_PROPERTIES,
    SoilGridsProperty,
)
from app.services.agriculture.soil_properties import (
    ERA5_DAILY,
    ROOT_ZONE_DEPTH_CM,
    ROOT_ZONE_INTERVALS,
    ROOT_ZONE_LAYER_THICKNESSES_CM,
    ROOT_ZONE_TOTAL_THICKNESS_CM,
    SOILGRIDS,
    SOILGRIDS_SCALE,
    SOIL_STATIC_THRESHOLDS,
    ALL_SOIL_PROPERTY_METRICS,
    SOIL_PROPERTY_METRICS,
    UNAVAILABLE_SOIL_PROPERTY_METRICS,
    SoilAvailableWaterCapacityMetric,
    SoilFieldCapacityMetric,
    SoilTemperatureLevel1Metric,
    SoilTemperatureLevel2Metric,
    SoilWiltingPointMetric,
    combine_layer_stats,
    depth_weighted_mean,
)
from app.services.agriculture.types import (
    PENDING_VERIFICATION,
    MeasurementBasis,
    QualityLevel,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    TemporalKind,
)


# ==========================================================================
# Fake Earth Engine
# ==========================================================================

PIXEL_TALLY = 5000

COMBINED_STATS = (
    "count", "mean", "median", "min", "max",
    "stdDev", "p10", "p25", "p75", "p90",
)


class _FakeRegionResult:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeImage:
    """Carries one value per registered band, modelling raw stored integers."""

    def __init__(self, values: dict) -> None:
        self._values = dict(values)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        # Filter to only bands that exist in the image.
        # Real Earth Engine select() raises for missing bands, but our
        # tests need to model partial data (missing layers), so we keep
        # only the bands that are present and proceed.
        present = [b for b in bands if b in self._values]
        if not present:
            raise KeyError(
                f"fake image has no band {bands!r}; it has "
                f"{sorted(self._values)}"
            )
        return _FakeImage({b: self._values[b] for b in present})

    def subtract(self, other):
        """Band-wise difference, mirroring ee.Image.subtract."""
        result = {}
        for band, value in self._values.items():
            other_value = other._values.get(band)
            if value is None or other_value is None:
                result[band] = None
            else:
                result[band] = value - other_value
        return _FakeImage(result)

    def reduceRegion(self, reducer=None, geometry=None, scale=None, **_kw):
        outputs = tuple(
            getattr(reducer, "outputs", (getattr(reducer, "name", ""),))
        )

        def value_for(stat, value):
            if value is None:
                return None
            if stat == "count":
                return float(PIXEL_TALLY)
            if stat == "stdDev":
                return 0.0
            return value

        payload: dict = {}
        for band, value in self._values.items():
            for stat in outputs:
                payload[f"{band}_{stat}"] = value_for(stat, value)
        return _FakeRegionResult(payload)


class _FakeImageCollection:
    """Models an ERA5-Land daily collection filtered by date."""

    def __init__(self, band: str, values: list) -> None:
        self._band = band
        self._values = list(values)

    def filterDate(self, start, end):  # noqa: N802
        return self

    def filterBounds(self, geom):  # noqa: N802
        return self

    def select(self, bands):
        return self

    def size(self):
        return _FakeNumber(len(self._values))

    def mean(self):
        usable = [v for v in self._values if v is not None]
        if not usable:
            return _FakeImage({self._band: None})
        avg = sum(usable) / len(usable)
        return _FakeImage({self._band: avg})


class _FakeNumber:
    def __init__(self, value) -> None:
        self._value = value

    def getInfo(self):
        return self._value


class _FakeReducer:
    def __init__(self, name: str = "mean") -> None:
        self.name = name
        self.outputs = (name,)

    def combine(self, other, sharedInputs=True):  # noqa: N802
        self.outputs = self.outputs + other.outputs
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
        r = _FakeReducer("percentile")
        r.outputs = tuple(f"p{v}" for v in values)
        return r


class FakeEE:
    """Minimal Earth Engine stub for soil property tests."""

    def __init__(self, images: Dict[str, _FakeImage]) -> None:
        self._images = images
        self.Reducer = _FakeReducerNamespace()
        self.Image = self._make_image_type()
        self.ImageCollection = self._make_collection_type()

    def _make_image_type(self):
        images = self._images

        class _ImageType:
            def __new__(cls, asset_id):
                if asset_id not in images:
                    raise KeyError(
                        f"test fixture has no asset {asset_id!r}; "
                        f"it has {sorted(images)}"
                    )
                return images[asset_id]

        return _ImageType

    def _make_collection_type(self):
        return _FakeImageCollection


def _build_soilgrids_image(
    raw_values: Dict[str, float],
) -> _FakeImage:
    """Build a SoilGrids image with raw stored integer values.

    The scale factors are defined in the dataset registry. This function
    supplies raw integers that the reduction pipeline will convert.
    """
    return _FakeImage(raw_values)


def _make_context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2024-04-01",
        end_date="2024-04-30",
        geometry_key="soil-properties-test",
        options={"area_sq_m": 1_000_000.0},
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def _install_soilgrids(
    monkeypatch,
    wv0033_values: Optional[dict] = None,
    wv1500_values: Optional[dict] = None,
) -> None:
    """Install SoilGrids fixtures for the water retention assets.

    ``wv0033_values`` and ``wv1500_values`` are dictionaries keyed by
    the registered band name (e.g. ``val_0_5cm_mean``) holding raw
    stored integer values.
    """
    if wv0033_values is None:
        wv0033_values = {}
    if wv1500_values is None:
        wv1500_values = {}

    images = {
        SOILGRIDS + "/wv0033": _FakeImage(wv0033_values),
        SOILGRIDS + "/wv1500": _FakeImage(wv1500_values),
    }
    module = types.ModuleType("ee")
    fake = FakeEE(images)
    module.Image = fake.Image
    module.Reducer = fake.Reducer
    module.ImageCollection = fake.ImageCollection
    monkeypatch.setitem(sys.modules, "ee", module)


def _install_era5(
    monkeypatch,
    band: str,
    values: list,
) -> None:
    """Install an ERA5-Land collection fixture."""
    module = types.ModuleType("ee")
    fake = FakeEE({})
    module.Image = fake.Image
    module.Reducer = fake.Reducer
    module.ImageCollection = lambda _id: _FakeImageCollection(band, values)
    monkeypatch.setitem(sys.modules, "ee", module)


def _all_depths_raw(mean_value: float) -> dict:
    """Build a raw band dict for all root-zone depths at one value.

    The raw integer is ``mean_value / scale_factor`` for each band.
    The wv0033/wv1500 bands use scale_factor=0.001, so a physical
    value of 0.30 corresponds to a raw integer of 300.
    """
    bands = {}
    for depth, _ in ROOT_ZONE_INTERVALS:
        band_name = f"val_{depth}_mean"
        # Raw integer = physical value / scale_factor
        bands[band_name] = int(mean_value / 0.001)
    return bands


# ==========================================================================
# Dataset registration and verification
# ==========================================================================


class TestDatasetRegistration:
    """Verify the SoilGrids dataset is correctly registered."""

    def test_soilgrids_dataset_is_registered(self):
        assert has_dataset(SOILGRIDS)

    def test_soilgrids_is_static(self):
        spec = get_dataset(SOILGRIDS)
        assert spec.temporal_kind is TemporalKind.STATIC

    def test_soilgrids_temporal_resolution_says_static(self):
        spec = get_dataset(SOILGRIDS)
        assert "static" in spec.temporal_resolution.lower()

    def test_soilgrids_has_all_root_zone_bands(self):
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            assert spec.has_band(band_name), f"missing band {band_name}"

    def test_soilgrids_band_scale_factor_is_0001(self):
        """The catalogue states 10^-3 cm3/cm3, i.e. scale 0.001."""
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            band = spec.band(band_name)
            assert band.scale_factor == 0.001, (
                f"{band_name}: expected scale_factor 0.001, got "
                f"{band.scale_factor}"
            )

    def test_soilgrids_band_unit_is_cm3_cm3(self):
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            band = spec.band(band_name)
            assert band.unit == "cm3/cm3", (
                f"{band_name}: expected unit cm3/cm3, got {band.unit}"
            )

    def test_soilgrids_band_valid_range(self):
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            band = spec.band(band_name)
            assert band.valid_range is not None
            low, high = band.valid_range
            assert low == 0.0
            assert high == 0.65

    def test_soilgrids_measurement_basis_is_modelled(self):
        spec = get_dataset(SOILGRIDS)
        assert spec.measurement_basis is MeasurementBasis.MODELLED

    def test_soilgrids_spatial_resolution(self):
        spec = get_dataset(SOILGRIDS)
        assert "250" in spec.spatial_resolution

    def test_soilgrids_scale_matches_registry(self):
        assert SOILGRIDS_SCALE == 250

    def test_soilgrids_dataset_is_verified(self):
        spec = get_dataset(SOILGRIDS)
        assert spec.is_verified

    def test_era5_dataset_is_registered(self):
        assert has_dataset(ERA5_DAILY)

    def test_era5_has_soil_temperature_bands(self):
        spec = get_dataset(ERA5_DAILY)
        assert spec.has_band("soil_temperature_level_1")
        assert spec.has_band("soil_temperature_level_2")


class TestExternalSoilGridsRegistry:
    """Verify the external (REST API) SoilGrids registry entries."""

    def test_external_registry_has_soilgrids(self):
        assert "ISRIC/SOILGRIDS/V2" in EXTERNAL_REGISTRY

    def test_soilgrids_properties_are_registered(self):
        expected_keys = {
            "clay", "sand", "silt", "soc", "bdod", "phh2o",
            "nitrogen", "cec", "cfvo",
        }
        assert set(SOILGRIDS_PROPERTIES.keys()) == expected_keys

    def test_all_properties_have_verified_d_factors(self):
        for key, prop in SOILGRIDS_PROPERTIES.items():
            assert prop.d_factor_verified, (
                f"{key}: d_factor not verified"
            )

    def test_clay_d_factor_is_10(self):
        assert SOILGRIDS_PROPERTIES["clay"].d_factor == 10

    def test_clay_unit_is_percent(self):
        assert SOILGRIDS_PROPERTIES["clay"].unit == "%"

    def test_soc_d_factor_is_10(self):
        assert SOILGRIDS_PROPERTIES["soc"].d_factor == 10

    def test_soc_unit_is_g_per_kg(self):
        assert SOILGRIDS_PROPERTIES["soc"].unit == "g/kg"

    def test_bdod_d_factor_is_100(self):
        assert SOILGRIDS_PROPERTIES["bdod"].d_factor == 100

    def test_bdod_unit_is_kg_dm3(self):
        assert SOILGRIDS_PROPERTIES["bdod"].unit == "kg/dm3"

    def test_phh2o_d_factor_is_10(self):
        assert SOILGRIDS_PROPERTIES["phh2o"].d_factor == 10

    def test_phh2o_unit_is_pH(self):
        assert SOILGRIDS_PROPERTIES["phh2o"].unit == "pH"

    def test_to_physical_applies_d_factor(self):
        prop = SOILGRIDS_PROPERTIES["clay"]
        # Raw value 500 g/kg -> 50% after dividing by 10
        assert prop.to_physical(500) == pytest.approx(50.0)

    def test_to_physical_returns_none_for_unverified(self):
        prop = SoilGridsProperty(
            "test", "Test", "unit", PENDING_VERIFICATION, False
        )
        assert prop.to_physical(100) is None

    def test_to_physical_returns_none_for_none(self):
        prop = SOILGRIDS_PROPERTIES["clay"]
        assert prop.to_physical(None) is None


# ==========================================================================
# Depth model
# ==========================================================================


class TestDepthModel:
    """Verify the depth intervals and root-zone definition."""

    def test_root_zone_depth_is_0_to_100_cm(self):
        assert ROOT_ZONE_DEPTH_CM == (0.0, 100.0)

    def test_five_intervals_cover_0_to_100_cm(self):
        total = sum(t for _, t in ROOT_ZONE_INTERVALS)
        assert total == pytest.approx(100.0)

    def test_interval_names_match_soilgrids_bands(self):
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            spec = get_dataset(SOILGRIDS)
            assert spec.has_band(band_name)

    def test_layer_thicknesses_are_correct(self):
        expected = [5.0, 10.0, 15.0, 30.0, 40.0]
        assert list(ROOT_ZONE_LAYER_THICKNESSES_CM) == expected

    def test_total_thickness_matches_depth(self):
        assert ROOT_ZONE_TOTAL_THICKNESS_CM == pytest.approx(100.0)

    def test_100_200cm_layer_is_excluded(self):
        depths = [d for d, _ in ROOT_ZONE_INTERVALS]
        assert "100_200cm" not in depths

    def test_six_depths_in_full_soilgrids_set(self):
        from app.services.agriculture.soil_properties import SOILGRIDS_DEPTHS
        assert len(SOILGRIDS_DEPTHS) == 6

    def test_100_200cm_exists_in_full_set_but_not_root_zone(self):
        from app.services.agriculture.soil_properties import SOILGRIDS_DEPTHS
        assert "100_200cm" in SOILGRIDS_DEPTHS


# ==========================================================================
# depth_weighted_mean
# ==========================================================================


class TestDepthWeightedMean:
    """Test the thickness-weighted aggregation function."""

    def test_equal_values_returns_that_value(self):
        values = [0.30, 0.30, 0.30, 0.30, 0.30]
        result = depth_weighted_mean(values, ROOT_ZONE_LAYER_THICKNESSES_CM)
        assert result == pytest.approx(0.30)

    def test_weighted_mean_prefers_thicker_layers(self):
        """A 40 cm layer at 0.20 should dominate a 5 cm layer at 0.40."""
        values = [0.40, 0.20, 0.20, 0.20, 0.20]
        weights = [5.0, 10.0, 15.0, 30.0, 40.0]
        result = depth_weighted_mean(values, weights)
        # Expected: (5*0.40 + 10*0.20 + 15*0.20 + 30*0.20 + 40*0.20) / 100
        expected = (2.0 + 2.0 + 3.0 + 6.0 + 8.0) / 100.0
        assert result == pytest.approx(expected)

    def test_unweighted_mean_would_be_different(self):
        """Arithmetic mean would be 0.24, weighted is ~0.22."""
        values = [0.40, 0.20, 0.20, 0.20, 0.20]
        weights = [5.0, 10.0, 15.0, 30.0, 40.0]
        weighted = depth_weighted_mean(values, weights)
        unweighted = sum(values) / len(values)
        assert weighted != pytest.approx(unweighted, abs=0.001)

    def test_none_values_are_skipped(self):
        values = [0.30, None, 0.30, 0.30, 0.30]
        weights = [5.0, 10.0, 15.0, 30.0, 40.0]
        result = depth_weighted_mean(values, weights)
        # Layer 1 (None) is skipped; denominator = 5+15+30+40 = 90
        # All non-None values are 0.30, so the weighted mean is 0.30
        expected = (5*0.30 + 15*0.30 + 30*0.30 + 40*0.30) / 90.0
        assert result == pytest.approx(expected)

    def test_all_none_returns_none(self):
        values = [None, None, None, None, None]
        result = depth_weighted_mean(values, ROOT_ZONE_LAYER_THICKNESSES_CM)
        assert result is None

    def test_empty_sequences_returns_none(self):
        result = depth_weighted_mean([], [])
        assert result is None

    def test_none_weights_returns_none(self):
        result = depth_weighted_mean([0.30], None)
        assert result is None

    def test_zero_weight_is_ignored(self):
        values = [0.30, 0.50]
        weights = [0.0, 10.0]
        result = depth_weighted_mean(values, weights)
        assert result == pytest.approx(0.50)

    def test_negative_weight_is_ignored(self):
        values = [0.30, 0.50]
        weights = [-5.0, 10.0]
        result = depth_weighted_mean(values, weights)
        assert result == pytest.approx(0.50)

    def test_nan_value_is_ignored(self):
        values = [float("nan"), 0.30]
        weights = [5.0, 10.0]
        result = depth_weighted_mean(values, weights)
        assert result == pytest.approx(0.30)

    def test_inf_value_is_ignored(self):
        values = [float("inf"), 0.30]
        weights = [5.0, 10.0]
        result = depth_weighted_mean(values, weights)
        assert result == pytest.approx(0.30)


class TestCombineLayerStats:
    """Test the thickness-weighted combination of SpatialStats."""

    def test_returns_empty_when_no_stats(self):
        from app.services.agriculture.types import SpatialStats
        result = combine_layer_stats([], ROOT_ZONE_LAYER_THICKNESSES_CM)
        assert result.valid_pixel_count == 0

    def test_minimum_coverage_across_layers(self):
        from app.services.agriculture.types import SpatialStats
        stats = [
            SpatialStats(mean=0.30, valid_pixel_count=100, total_pixel_count=200),
            SpatialStats(mean=0.25, valid_pixel_count=50, total_pixel_count=200),
        ]
        result = combine_layer_stats(stats, [50.0, 50.0])
        # Coverage is min, not mean
        assert result.valid_pixel_count == 50


# ==========================================================================
# SoilFieldCapacityMetric
# ==========================================================================


class TestSoilFieldCapacity:
    """Test the field capacity (33 kPa) metric."""

    def test_metric_identity(self):
        m = SoilFieldCapacityMetric()
        assert m.key == "soil_field_capacity"
        assert m.domain == MetricDomain.SOIL
        assert m.unit == "cm3/cm3"

    def test_metric_is_modelled(self):
        m = SoilFieldCapacityMetric()
        assert m.measurement_basis is MeasurementBasis.MODELLED

    def test_static_contract_allows_2024_request(self):
        can, reason = SoilFieldCapacityMetric().can_attempt(_make_context())
        assert can is True
        assert reason is None

    def test_static_contract_allows_future_request(self):
        can, _ = SoilFieldCapacityMetric().can_attempt(
            _make_context(start_date="2030-01-01", end_date="2030-01-31")
        )
        assert can is True

    def test_rejects_inverted_dates(self):
        can, reason = SoilFieldCapacityMetric().can_attempt(
            _make_context(start_date="2024-04-30", end_date="2024-04-01")
        )
        assert can is False
        assert reason == "outside_temporal_coverage"

    def test_computes_with_uniform_profile(self, monkeypatch):
        """All layers at 0.30 cm3/cm3 should produce 0.30."""
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.30, abs=0.001)
        assert result.unit == "cm3/cm3"

    def test_computes_with_varying_profile(self, monkeypatch):
        """A profile that increases with depth."""
        raw = {}
        values_by_depth = [0.20, 0.25, 0.30, 0.35, 0.40]
        for (depth, _), val in zip(ROOT_ZONE_INTERVALS, values_by_depth):
            raw[f"val_{depth}_mean"] = int(val / 0.001)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        # Expected: (5*0.20 + 10*0.25 + 15*0.30 + 30*0.35 + 40*0.40) / 100
        expected = (1.0 + 2.5 + 4.5 + 10.5 + 16.0) / 100.0
        assert result.value == pytest.approx(expected, abs=0.001)

    def test_provenance_carries_static_kind(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        provenance = result.provenance
        assert provenance is not None
        assert provenance.temporal_kind is TemporalKind.STATIC
        assert provenance.requested_start == "2024-04-01"
        assert provenance.requested_end == "2024-04-30"
        assert provenance.product_date is not None

    def test_provenance_names_depth_weighting(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        formula = result.provenance.formula
        assert "0-100" in formula or "0 to 100" in formula.lower()

    def test_has_static_disclaimer_in_warnings(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        warnings_text = " ".join(result.warnings).lower()
        assert "static" in warnings_text or "model" in warnings_text

    def test_has_convention_disclaimer_in_limitations(self):
        m = SoilFieldCapacityMetric()
        limitations_text = " ".join(m.limitations).lower()
        assert "33 kpa" in limitations_text or "convention" in limitations_text

    def test_insufficient_when_missing_layer(self, monkeypatch):
        """If one layer is missing, the aggregate must be refused."""
        raw = _all_depths_raw(0.30)
        # Remove the 30-60 cm layer
        del raw["val_30_60cm_mean"]
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert result.value is None

    def test_insufficient_when_no_data(self, monkeypatch):
        _install_soilgrids(
            monkeypatch,
            wv0033_values={b: None for b in [
                f"val_{d}_mean" for d, _ in ROOT_ZONE_INTERVALS
            ]},
        )
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA

    def test_is_in_soil_property_metrics(self):
        keys = {m.key for m in SOIL_PROPERTY_METRICS}
        assert "soil_field_capacity" in keys

    def test_declares_limitations(self):
        m = SoilFieldCapacityMetric()
        assert len(m.limitations) >= 3


# ==========================================================================
# SoilWiltingPointMetric
# ==========================================================================


class TestSoilWiltingPoint:
    """Test the wilting point (1500 kPa) metric."""

    def test_metric_identity(self):
        m = SoilWiltingPointMetric()
        assert m.key == "soil_wilting_point"
        assert m.domain == MetricDomain.SOIL
        assert m.unit == "cm3/cm3"

    def test_uses_wv1500_asset(self):
        m = SoilWiltingPointMetric()
        assert "wv1500" in m.asset_id

    def test_computes_with_uniform_profile(self, monkeypatch):
        raw = _all_depths_raw(0.12)
        _install_soilgrids(monkeypatch, wv1500_values=raw)
        result = SoilWiltingPointMetric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.12, abs=0.001)

    def test_static_contract(self):
        can, reason = SoilWiltingPointMetric().can_attempt(_make_context())
        assert can is True

    def test_is_in_soil_property_metrics(self):
        keys = {m.key for m in SOIL_PROPERTY_METRICS}
        assert "soil_wilting_point" in keys


# ==========================================================================
# SoilAvailableWaterCapacityMetric
# ==========================================================================


class TestSoilAvailableWaterCapacity:
    """Test the AWC metric: theta(33 kPa) - theta(1500 kPa)."""

    def test_metric_identity(self):
        m = SoilAvailableWaterCapacityMetric()
        assert m.key == "soil_available_water_capacity"
        assert m.domain == MetricDomain.SOIL
        assert m.unit == "cm3/cm3"

    def test_is_difference_metric(self):
        m = SoilAvailableWaterCapacityMetric()
        assert m.is_difference is True

    def test_has_both_suction_assets(self):
        m = SoilAvailableWaterCapacityMetric()
        assert m.asset_id  # 33 kPa
        assert m.subtract_asset_id  # 1500 kPa

    def test_awc_is_fc_minus_wp(self, monkeypatch):
        """With uniform profiles, AWC = FC - WP exactly."""
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.18, abs=0.001)

    def test_awc_with_zero_wp(self, monkeypatch):
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.0)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.30, abs=0.001)

    def test_formula_mentions_both_suctions(self, monkeypatch):
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        formula = result.provenance.formula
        assert "33" in formula and "1500" in formula

    def test_has_awc_disclaimer_in_warnings(self, monkeypatch):
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        warnings_text = " ".join(result.warnings).lower()
        assert "uncertainty" in warnings_text or "difference" in warnings_text

    def test_is_in_soil_property_metrics(self):
        keys = {m.key for m in SOIL_PROPERTY_METRICS}
        assert "soil_available_water_capacity" in keys

    def test_insufficient_when_one_layer_missing(self, monkeypatch):
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        del fc_raw["val_15_30cm_mean"]
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA


# ==========================================================================
# SoilTemperatureMetrics
# ==========================================================================


class TestSoilTemperature:
    """Test the ERA5-Land soil temperature metrics."""

    def test_level1_identity(self):
        m = SoilTemperatureLevel1Metric()
        assert m.key == "soil_temperature_0_7cm"
        assert m.domain == MetricDomain.SOIL
        assert m.unit == "degC"

    def test_level2_identity(self):
        m = SoilTemperatureLevel2Metric()
        assert m.key == "soil_temperature_7_28cm"
        assert m.domain == MetricDomain.SOIL

    def test_level1_uses_correct_band(self):
        m = SoilTemperatureLevel1Metric()
        assert m.source_band == "soil_temperature_level_1"

    def test_level2_uses_correct_band(self):
        m = SoilTemperatureLevel2Metric()
        assert m.source_band == "soil_temperature_level_2"

    def test_level1_is_observational(self):
        """ERA5-Land is a daily time series, not static."""
        m = SoilTemperatureLevel1Metric()
        can, reason = m.can_attempt(_make_context())
        assert can is True

    def test_level1_computes_celsius(self, monkeypatch):
        # 300 K = 26.85 degC
        _install_era5(monkeypatch, "soil_temperature_level_1", [300.0])
        result = SoilTemperatureLevel1Metric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(26.85, abs=0.01)
        assert result.unit == "degC"

    def test_level1_converts_kelvin_to_celsius(self, monkeypatch):
        _install_era5(monkeypatch, "soil_temperature_level_1", [273.15])
        result = SoilTemperatureLevel1Metric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.0, abs=0.01)

    def test_level2_computes_celsius(self, monkeypatch):
        _install_era5(monkeypatch, "soil_temperature_level_2", [290.0])
        result = SoilTemperatureLevel2Metric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(290.0 - 273.15, abs=0.01)

    def test_insufficient_when_no_days(self, monkeypatch):
        _install_era5(monkeypatch, "soil_temperature_level_1", [])
        result = SoilTemperatureLevel1Metric().compute(_make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA

    def test_level1_distinct_from_air_temperature(self):
        """The limitation must distinguish soil from air temperature."""
        m = SoilTemperatureLevel1Metric()
        limitations = " ".join(m.limitations).lower()
        assert "soil" in limitations
        assert "air" in limitations or "2 m" in limitations

    def test_level1_mentions_model_not_measurement(self):
        m = SoilTemperatureLevel1Metric()
        limitations = " ".join(m.limitations).lower()
        assert "model" in limitations or "reanalysis" in limitations

    def test_is_in_soil_property_metrics(self):
        keys = {m.key for m in SOIL_PROPERTY_METRICS}
        assert "soil_temperature_0_7cm" in keys
        assert "soil_temperature_7_28cm" in keys

    def test_provenance_carries_era5_dataset_id(self, monkeypatch):
        _install_era5(monkeypatch, "soil_temperature_level_1", [300.0])
        result = SoilTemperatureLevel1Metric().compute(_make_context())
        assert result.provenance.source_dataset_id == ERA5_DAILY


# ==========================================================================
# Unavailable metrics
# ==========================================================================


class TestUnavailableMetrics:
    """Verify every unavailable metric returns a specific reason."""

    UNAVAILABLE_KEYS = {
        "soil_organic_carbon",
        "soil_clay_content",
        "soil_sand_content",
        "soil_silt_content",
        "soil_bulk_density",
        "soil_ph",
        "soil_cation_exchange_capacity",
        "soil_coarse_fragments",
        "soil_texture_class",
        "soil_salinity",
    }

    @pytest.fixture(autouse=True)
    def _register_unavailable(self):
        """Register unavailable metrics for get_metric() lookups."""
        clear_registry()
        register_metrics(UNAVAILABLE_SOIL_PROPERTY_METRICS)
        yield
        clear_registry()

    def test_all_unavailable_keys_are_registered(self):
        registered = {m.key for m in UNAVAILABLE_SOIL_PROPERTY_METRICS}
        assert self.UNAVAILABLE_KEYS == registered

    @pytest.mark.parametrize("key", sorted(UNAVAILABLE_KEYS))
    def test_unavailable_metric_returns_unavailable(self, key):
        metric = get_metric(key)
        result = metric.compute(_make_context())
        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None

    @pytest.mark.parametrize("key", sorted(UNAVAILABLE_KEYS))
    def test_unavailable_metric_has_reason(self, key):
        metric = get_metric(key)
        result = metric.compute(_make_context())
        assert result.reason is not None
        assert result.reason != "not_supported"

    @pytest.mark.parametrize("key", sorted(UNAVAILABLE_KEYS))
    def test_unavailable_metric_has_message(self, key):
        metric = get_metric(key)
        result = metric.compute(_make_context())
        assert result.message is not None
        assert len(result.message) > 50

    @pytest.mark.parametrize("key", sorted(UNAVAILABLE_KEYS))
    def test_unavailable_metric_metadata(self, key):
        metric = get_metric(key)
        metadata = metric.metadata()
        assert metadata["available"] is False
        assert "unavailable_code" in metadata
        assert "unavailable_reason" in metadata

    def test_soc_reason_names_missing_earth_engine_layer(self):
        from app.services.agriculture.soil_properties import (
            SoilOrganicCarbonMetric,
        )
        m = SoilOrganicCarbonMetric()
        # _reason() formats the template with actual property/code values
        reason = m._reason().lower()
        assert "earth engine" in reason
        assert "soc" in reason

    def test_clay_reason_names_missing_layer(self):
        from app.services.agriculture.soil_properties import (
            SoilClayContentMetric,
        )
        m = SoilClayContentMetric()
        reason = m._reason().lower()
        assert "clay" in reason

    def test_texture_class_reason_names_missing_fractions(self):
        from app.services.agriculture.soil_properties import (
            SoilTextureClassMetric,
        )
        m = SoilTextureClassMetric()
        reason = m.unavailable_reason.lower()
        assert "sand" in reason
        assert "silt" in reason
        assert "clay" in reason

    def test_salinity_reason_names_no_direct_observation(self):
        from app.services.agriculture.soil_properties import SoilSalinityMetric
        m = SoilSalinityMetric()
        reason = m.unavailable_reason.lower()
        assert "salinity" in reason
        assert "electrical" in reason or "ec" in reason

    def test_salinity_does_not_use_ph_as_proxy(self):
        from app.services.agriculture.soil_properties import SoilSalinityMetric
        m = SoilSalinityMetric()
        reason = m.unavailable_reason.lower()
        assert "not salinity" in reason or "not used" in reason

    def test_ph_limitations_distinguish_from_nutrient_deficiency(self):
        from app.services.agriculture.soil_properties import SoilPhMetric
        m = SoilPhMetric()
        limitations = " ".join(m.limitations).lower()
        assert "nutrient" in limitations or "fertiliser" in limitations

    def test_bulk_density_unit_is_kg_dm3(self):
        from app.services.agriculture.soil_properties import (
            SoilBulkDensityMetric,
        )
        m = SoilBulkDensityMetric()
        assert m.property_unit == "kg/dm3"

    def test_cec_unit_is_cmol_c_kg(self):
        from app.services.agriculture.soil_properties import (
            SoilCationExchangeCapacityMetric,
        )
        m = SoilCationExchangeCapacityMetric()
        assert m.property_unit == "cmol(c)/kg"

    def test_coarse_fragments_unit(self):
        from app.services.agriculture.soil_properties import (
            SoilCoarseFragmentsMetric,
        )
        m = SoilCoarseFragmentsMetric()
        assert m.property_unit == "cm3/100cm3"

    def test_all_unavailable_metrics_are_in_soil_domain(self):
        for m in UNAVAILABLE_SOIL_PROPERTY_METRICS:
            assert m.domain == MetricDomain.SOIL

    def test_all_unavailable_metrics_have_limitations(self):
        for m in UNAVAILABLE_SOIL_PROPERTY_METRICS:
            assert m.limitations


# ==========================================================================
# Scale factor regression tests
# ==========================================================================


class TestScaleFactorRegression:
    """Regression tests protecting against the scale-factor class of bugs.

    The project previously discovered a systemic reduction-layer
    scale-factor bug. These tests verify that:
    1. Raw SoilGrids integers are not published directly.
    2. The scale factor is applied exactly once.
    3. Units are correct after scaling.
    """

    def test_field_capacity_applies_scale_factor(self, monkeypatch):
        """A raw value of 300 should become 0.30 cm3/cm3, not 300."""
        raw = _all_depths_raw(0.30)
        # Verify raw values are integers (not already physical)
        for v in raw.values():
            assert isinstance(v, int)
            assert v > 1  # Would be implausible as cm3/cm3
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        # Physical value must be in [0, 0.65], not [0, 650]
        assert 0.0 < result.value < 1.0

    def test_scale_factor_not_applied_twice(self, monkeypatch):
        """If scale were applied twice, 0.30 would become 0.00030."""
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.status == STATUS_OK
        assert result.value > 0.01  # Not double-scaled

    def test_wilting_point_raw_to_physical(self, monkeypatch):
        """Raw 120 -> physical 0.12 cm3/cm3."""
        raw = _all_depths_raw(0.12)
        for v in raw.values():
            assert v == 120  # 0.12 / 0.001 = 120
        _install_soilgrids(monkeypatch, wv1500_values=raw)
        result = SoilWiltingPointMetric().compute(_make_context())
        assert result.value == pytest.approx(0.12, abs=0.001)

    def test_awc_scale_factor_consistency(self, monkeypatch):
        """Both suction assets use the same scale factor, so AWC is exact."""
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        # AWC = 0.30 - 0.12 = 0.18
        assert result.value == pytest.approx(0.18, abs=0.001)

    def test_dataset_band_scale_factor_is_0001(self):
        """Pin the scale factor in the registry to 0.001."""
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            band = spec.band(band_name)
            assert band.scale_factor == 0.001

    def test_dataset_band_offset_is_zero(self):
        """No offset should be applied to SoilGrids water retention."""
        spec = get_dataset(SOILGRIDS)
        for depth, _ in ROOT_ZONE_INTERVALS:
            band_name = f"val_{depth}_mean"
            band = spec.band(band_name)
            assert band.offset == 0.0


# ==========================================================================
# Quality control
# ==========================================================================


class TestQualityControl:
    """Verify quality thresholds and assessment."""

    def test_static_thresholds_have_floor_image_count(self):
        assert SOIL_STATIC_THRESHOLDS.excellent_min_images == 1
        assert SOIL_STATIC_THRESHOLDS.good_min_images == 1
        assert SOIL_STATIC_THRESHOLDS.moderate_min_images == 1
        assert SOIL_STATIC_THRESHOLDS.poor_min_images == 1

    def test_static_thresholds_require_minimum_pixels(self):
        assert SOIL_STATIC_THRESHOLDS.min_valid_pixels == 10

    def test_static_thresholds_require_minimum_coverage(self):
        assert SOIL_STATIC_THRESHOLDS.min_coverage_percent == 20.0

    def test_field_capacity_has_quality_assessment(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.provenance.quality_level in (
            QualityLevel.EXCELLENT,
            QualityLevel.GOOD,
            QualityLevel.MODERATE,
            QualityLevel.POOR,
        )


# ==========================================================================
# Metric collection completeness
# ==========================================================================


class TestMetricCollection:
    """Verify all expected metrics are in the collections."""

    def test_soil_property_metrics_count(self):
        assert len(SOIL_PROPERTY_METRICS) == 5

    def test_unavailable_soil_property_metrics_count(self):
        assert len(UNAVAILABLE_SOIL_PROPERTY_METRICS) == 10

    def test_all_metrics_count(self):
        assert len(ALL_SOIL_PROPERTY_METRICS) == 15

    def test_all_soil_property_metrics_are_soil_domain(self):
        for m in ALL_SOIL_PROPERTY_METRICS:
            assert m.domain == MetricDomain.SOIL

    def test_available_metrics_have_values_not_unavailable(self):
        for m in SOIL_PROPERTY_METRICS:
            assert m.unit != "unavailable"

    def test_unavailable_metrics_have_unavailable_unit(self):
        for m in UNAVAILABLE_SOIL_PROPERTY_METRICS:
            assert m.unit == "unavailable"


# ==========================================================================
# STATIC temporal semantics
# ==========================================================================


class TestStaticTemporalSemantics:
    """Verify the Phase H STATIC contract for SoilGrids."""

    def test_soilgrids_primary_dataset_is_static(self):
        m = SoilFieldCapacityMetric()
        spec = m.primary_dataset()
        assert spec.temporal_kind is TemporalKind.STATIC

    def test_can_attempt_returns_true_for_any_date(self):
        """A STATIC dataset does not restrict analysis dates."""
        m = SoilFieldCapacityMetric()
        can, reason = m.can_attempt(
            _make_context(start_date="2030-06-01", end_date="2030-06-30")
        )
        assert can is True

    def test_can_attempt_returns_true_for_historical_date(self):
        m = SoilFieldCapacityMetric()
        can, reason = m.can_attempt(
            _make_context(start_date="2000-01-01", end_date="2000-01-31")
        )
        assert can is True

    def test_still_rejects_malformed_dates(self):
        m = SoilFieldCapacityMetric()
        can, reason = m.can_attempt(
            _make_context(start_date="2024-12-01", end_date="2024-01-01")
        )
        assert can is False

    def test_product_date_is_not_analysis_date(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(
            _make_context(start_date="2024-04-01", end_date="2024-04-30")
        )
        provenance = result.provenance
        # product_date should be the dataset's available_from, not the request
        assert provenance.product_date is not None
        assert provenance.product_date != "2024-04-01"

    def test_provenance_temporal_kind_is_static(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        assert result.provenance.temporal_kind is TemporalKind.STATIC

    def test_serialised_provenance_carries_static(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        payload = result.to_dict()
        assert payload["provenance"]["temporal_kind"] == "static"


# ==========================================================================
# Provenance completeness
# ==========================================================================


class TestProvenance:
    """Verify every result carries complete provenance."""

    def test_field_capacity_provenance_has_all_fields(self, monkeypatch):
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(_make_context())
        prov = result.provenance
        assert prov.source_dataset_id
        assert prov.source_dataset_name
        assert prov.bands
        assert prov.formula
        assert prov.unit
        assert prov.spatial_resolution
        assert prov.temporal_resolution
        assert prov.aggregation_method
        assert prov.measurement_basis
        assert prov.quality_level
        assert prov.requested_start
        assert prov.requested_end
        assert prov.limitations

    def test_awc_provenance_names_both_suctions(self, monkeypatch):
        fc_raw = _all_depths_raw(0.30)
        wp_raw = _all_depths_raw(0.12)
        _install_soilgrids(
            monkeypatch, wv0033_values=fc_raw, wv1500_values=wp_raw
        )
        result = SoilAvailableWaterCapacityMetric().compute(_make_context())
        formula = result.provenance.formula
        assert "33" in formula
        assert "1500" in formula

    def test_temperature_provenance_has_era5_info(self, monkeypatch):
        _install_era5(monkeypatch, "soil_temperature_level_1", [300.0])
        result = SoilTemperatureLevel1Metric().compute(_make_context())
        prov = result.provenance
        assert prov.source_dataset_id == ERA5_DAILY
        assert prov.bands == ["soil_temperature_level_1"]


# ==========================================================================
# Contract tests
# ==========================================================================


class TestContractTests:
    """Phase J contract tests: STATIC historical and future requests."""

    def test_static_historical_request_computes(self, monkeypatch):
        """SoilGrids is static; a request for 2010 must compute."""
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(
            _make_context(start_date="2010-01-01", end_date="2010-01-31")
        )
        assert result.status == STATUS_OK

    def test_static_future_request_computes(self, monkeypatch):
        """SoilGrids is static; a request for 2030 must compute."""
        raw = _all_depths_raw(0.30)
        _install_soilgrids(monkeypatch, wv0033_values=raw)
        result = SoilFieldCapacityMetric().compute(
            _make_context(start_date="2030-06-01", end_date="2030-06-30")
        )
        assert result.status == STATUS_OK

    def test_malformed_date_range_rejected(self):
        can, reason = SoilFieldCapacityMetric().can_attempt(
            _make_context(start_date="2024-04-30", end_date="2024-04-01")
        )
        assert can is False

    def test_era5_observation_contract(self):
        """ERA5-Land is OBSERVATION; it should reject dates before 1950."""
        from app.services.agriculture.base import coverage_overlap_days
        can, reason = SoilTemperatureLevel1Metric().can_attempt(
            _make_context(start_date="1940-01-01", end_date="1940-01-31")
        )
        # ERA5-Land available_from is 1950-01-02
        assert can is False


# ==========================================================================
# Registration safety
# ==========================================================================


class TestRegistrationSafety:
    """Verify idempotent registration and no key collisions."""

    def test_soil_property_metrics_register_without_error(self):
        clear_registry()
        register_metrics(SOIL_PROPERTY_METRICS)
        keys = {m.key for m in SOIL_PROPERTY_METRICS}
        for key in keys:
            assert get_metric(key) is not None

    def test_unavailable_metrics_register_without_error(self):
        clear_registry()
        register_metrics(UNAVAILABLE_SOIL_PROPERTY_METRICS)
        keys = {m.key for m in UNAVAILABLE_SOIL_PROPERTY_METRICS}
        for key in keys:
            assert get_metric(key) is not None

    def test_no_key_collision_with_soil_moisture_metrics(self):
        from app.services.agriculture.soil import SOIL_METRICS
        soil_keys = {m.key for m in SOIL_METRICS}
        property_keys = {m.key for m in ALL_SOIL_PROPERTY_METRICS}
        assert soil_keys.isdisjoint(property_keys)

    def test_catalog_includes_soil_properties(self):
        clear_registry()
        register_metrics(ALL_SOIL_PROPERTY_METRICS)
        from app.services.agriculture.catalog import catalog
        cat = catalog()
        metric_keys = {m["key"] for m in cat["metrics"]}
        assert "soil_field_capacity" in metric_keys
        assert "soil_organic_carbon" in metric_keys
