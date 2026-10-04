"""Opt-in integration tests for the Phase M productivity layer.

These are skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set to a
truthy value. They need network access and service-account credentials.

What these tests are for: the Phase M indicators are derived from bands
the lower layers already read -- the phenology engine's Sentinel-2 NDVI
series, the MOD16 ET composites, and the ESA WorldCereal 2021 mask. The
unit suite's fake Earth Engine verifies the formulas, the gates and the
refusal rules; only a live call can confirm the indicators execute
against the real archive: that the seasonal detection survives real
cloud-gap structure, that MOD16 composites actually fall inside the
detected season, and that the WorldCereal zone images resolve for the
test parcel.

A derived indicator may legitimately refuse on live data -- an
uncertifiable season, a missing crop zone or an empty ET window are
correct answers, not failures. The assertions therefore accept
STATUS_INSUFFICIENT_DATA wherever a refusal is scientifically valid and
require only that a refusal carries a stated reason. These tests
confirm the metrics execute; they do not validate the numbers
scientifically, and they most certainly do not verify any yield.

The service account needs ``roles/earthengine.viewer`` (documented as
infrastructure in docs/AGRICULTURAL_ANALYTICS.md); without it every
test skips with that exact reason.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \
        tests/integration/test_productivity_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.productivity import (
    PRODUCTIVITY_METRICS,
    CropAreaNormalisedProductivityIndicator,
    SeasonalETProductivityContextMetric,
    SeasonalVegetationProductivityIndicator,
)
from app.services.agriculture.registry import has_dataset
from app.services.agriculture.types import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.yield_model import (
    UNAVAILABLE_YIELD_METRICS,
    YIELD_MODEL_REGISTRY,
)
from app.services.agriculture.yield_model import (
    BIOMASS_UNAVAILABLE_CODE,
    YIELD_UNAVAILABLE_CODE,
    YIELD_UNCERTAINTY_UNAVAILABLE_CODE,
)

pytestmark = pytest.mark.integration


#: A small agricultural parcel in Karaj, Iran -- the same parcel every
#: other integration file uses, chosen because it comfortably contains
#: several ERA5-Land, MODIS and WorldCereal pixels.
KARAJ_PARCEL = {
    "type": "Polygon",
    "coordinates": [
        [
            [50.94, 35.80],
            [50.96, 35.80],
            [50.96, 35.82],
            [50.94, 35.82],
            [50.94, 35.80],
        ]
    ],
}

#: A full 2021 window: the one year the WorldCereal mask can describe,
#: and long enough for the phenology engine's 180-day minimum.
START_DATE = "2021-01-01"
END_DATE = "2021-12-31"

#: The datasets the productivity layer derives from. The band names must
#: match the live collections or the metrics cannot compute.
BAND_GROUPS = [
    ("COPERNICUS/S2_SR_HARMONIZED", ["B4", "B8", "SCL"]),
    ("MODIS/061/MOD16A2GF", ["ET"]),
    ("ESA/WorldCereal/2021/MODELS/v100", ["classification"]),
]


@pytest.fixture(scope="module")
def gee_context():
    """Initialise Earth Engine and build a context, or skip."""
    if not os.environ.get("RUN_GEE_INTEGRATION_TESTS"):
        pytest.skip("RUN_GEE_INTEGRATION_TESTS is not set")

    try:
        import ee
    except ImportError:
        pytest.skip("earthengine-api is not installed")

    try:
        from app.services.earth_engine.authentication import (
            initialize_earth_engine,
        )
    except ImportError:
        pytest.skip("Earth Engine authentication helper is unavailable")

    try:
        initialize_earth_engine()
    except Exception as exc:  # noqa: BLE001 - skip rather than fail
        pytest.skip(f"Could not initialise Earth Engine: {exc}")

    geometry = ee.Geometry(KARAJ_PARCEL)
    return MetricContext(
        geometry=geometry,
        start_date=START_DATE,
        end_date=END_DATE,
        geometry_key="karaj-parcel-2021",
        options={"area_sq_m": 4_000_000.0},
    )


def test_every_declared_productivity_band_exists_in_its_live_collection(
    gee_context,
):
    """The band names must match what Earth Engine actually publishes."""
    import ee

    for dataset_id, bands in BAND_GROUPS:
        assert has_dataset(dataset_id), dataset_id
        first = ee.ImageCollection(dataset_id).first()
        live_bands = first.bandNames().getInfo()
        for band in bands:
            assert band in live_bands, (dataset_id, band)


class TestSeasonalIndicatorLive:
    def test_it_executes_and_publishes_or_refuses(self, gee_context):
        result = SeasonalVegetationProductivityIndicator().compute(
            gee_context
        )
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA)
        if result.status == STATUS_OK:
            assert result.value is not None
            assert result.unit == "index"
            # A mean NDVI inside a detected season is bounded by the
            # index's own plausible range.
            assert -0.2 <= result.value <= 1.0
            assert result.provenance is not None
            caveats = " ".join(result.provenance.caveats)
            assert "Detected season span" in caveats
        else:
            assert result.message, "a refusal must say why"

    def test_the_span_in_provenance_is_inside_the_window(self, gee_context):
        result = SeasonalVegetationProductivityIndicator().compute(
            gee_context
        )
        if result.status == STATUS_OK:
            caveats = " ".join(result.provenance.caveats)
            assert "2021" in caveats


class TestSeasonalETContextLive:
    def test_it_executes_and_publishes_or_refuses(self, gee_context):
        result = SeasonalETProductivityContextMetric().compute(gee_context)
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA)
        if result.status == STATUS_OK:
            assert result.value is not None
            assert result.unit == "mm"
            # A season's ET in a semi-arid summer climate is positive
            # water; a non-positive total would indicate a unit or
            # sign error, not a rainless season.
            assert result.value > 0.0
            caveats = " ".join(result.provenance.caveats)
            assert "ET window used" in caveats
            assert "No water-use-efficiency factor" in caveats
        else:
            assert result.message, "a refusal must say why"


class TestCropAreaNormalisedLive:
    def test_it_executes_and_publishes_or_refuses(self, gee_context):
        result = CropAreaNormalisedProductivityIndicator().compute(
            gee_context
        )
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA)
        if result.status == STATUS_OK:
            assert result.value is not None
            assert result.unit == "index.fraction"
            # A weighting of two factors in [-1, 1] and [0, 1] stays
            # within [-1, 1].
            assert -1.0 <= result.value <= 1.0
            caveats = " ".join(result.provenance.caveats)
            assert "Crop share" in caveats
        else:
            assert result.message, "a refusal must say why"


class TestUnavailableYieldMetricsLive:
    def test_the_yield_trio_refuses_on_live_data_too(self, gee_context):
        """A structural refusal holds against the live archive."""
        for metric in UNAVAILABLE_YIELD_METRICS:
            result = metric.compute(gee_context)
            assert result.status == STATUS_UNAVAILABLE, metric.key
            assert result.value is None, metric.key
            assert result.reason in (
                YIELD_UNAVAILABLE_CODE,
                BIOMASS_UNAVAILABLE_CODE,
                YIELD_UNCERTAINTY_UNAVAILABLE_CODE,
            ), metric.key

    def test_the_model_registry_is_still_empty(self):
        """Live verification must not manufacture a model."""
        assert len(YIELD_MODEL_REGISTRY) == 0


class TestWholeLayerExecution:
    def test_the_executor_runs_every_productivity_metric(self, gee_context):
        keys = [m.key for m in PRODUCTIVITY_METRICS]
        outcomes, unknown = execute_metrics(keys, gee_context)
        assert not unknown
        assert set(outcomes) == set(keys)
        for key, outcome in keys and outcomes.items():
            assert outcome.result.status in (
                STATUS_OK,
                STATUS_INSUFFICIENT_DATA,
                STATUS_UNAVAILABLE,
            ), (key, outcome.result.message)
