"""Opt-in integration tests for the thermal engine.

Skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set. These verify against
real Earth Engine that the MODIS and Landsat band names resolve, that the
scale factors produce physically possible temperatures, and — most
importantly — that the reduction pipeline returns kelvin rather than raw
counts.

That last check is the reason this file exists. The unit suite uses a fake
Earth Engine and a fixture that supplies raw counts, so it verifies the
conversion logic but cannot verify that a real reduction returns what the
fake assumes. Wired the wrong way, MODIS LST comes back as fifteen
thousand degrees, which is conspicuous; wired slightly differently, a
band with a scale factor of 1.0 would come back raw and look almost
right.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration/test_thermal_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.thermal import (
    LANDSAT_THERMAL,
    MODIS_LST_8DAY,
    MODIS_LST_DAILY,
    THERMAL_METRICS,
    DiurnalTemperatureRangeMetric,
    LandsatSurfaceTemperatureMetric,
    LandSurfaceTemperatureDayMetric,
    LandSurfaceTemperatureNightMetric,
)
from app.services.agriculture.types import STATUS_OK

pytestmark = pytest.mark.integration


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

#: A full month, so the 8-day composite has several windows and Landsat
#: has a reasonable chance of at least one scene.
START_DATE = "2025-06-01"
END_DATE = "2025-06-30"


@pytest.fixture(scope="module")
def gee_context():
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
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Could not initialise Earth Engine: {exc}")

    return MetricContext(
        geometry=ee.Geometry(KARAJ_PARCEL),
        start_date=START_DATE,
        end_date=END_DATE,
        geometry_key="karaj-parcel",
        options={"area_sq_m": 4_000_000.0},
    )


def test_modis_lst_datasets_resolve(gee_context):
    import ee

    for dataset_id in (MODIS_LST_8DAY, MODIS_LST_DAILY):
        size = int(ee.ImageCollection(dataset_id).size().getInfo())
        assert size > 0, f"{dataset_id} is empty"


def test_modis_lst_bands_exist(gee_context):
    """Both day and night bands must be present on both products.

    A misspelled night band would make the range metric silently
    unavailable rather than wrong, which is quieter than it sounds.
    """
    import ee

    for dataset_id in (MODIS_LST_8DAY, MODIS_LST_DAILY):
        live = set(ee.ImageCollection(dataset_id).first().bandNames().getInfo())
        for band in ("LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night"):
            assert band in live, f"{dataset_id} is missing {band}"


def test_modis_reduction_returns_raw_counts_not_kelvin(gee_context):
    """The contract the fixture assumes: Earth Engine returns raw counts.

    If this ever starts returning physical values, the band_spec
    conversion would silently double-apply, and a value of 300 K would
    come back as 6 K.
    """
    import ee

    raw = (
        ee.ImageCollection(MODIS_LST_8DAY)
        .select(["LST_Day_1km"])
        .first()
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=gee_context.geometry,
            scale=1000,
            maxPixels=1e9,
            bestEffort=True,
        )
        .getInfo()
    )
    value = (raw or {}).get("LST_Day_1km")
    if value is None:
        pytest.skip("no valid pixel in the first scene for this geometry")

    # Raw counts for a real surface are in the thousands. A value under
    # 1000 would mean the dataset now returns physical kelvin.
    assert value > 1000.0, (
        f"expected raw counts, got {value}. If the dataset now returns "
        "physical values, the band_spec conversion double-applies."
    )
    # And the conversion must land in a physically possible range.
    kelvin = value * 0.02
    assert 150.0 < kelvin < 400.0


def test_daytime_lst_is_in_a_physically_possible_range(gee_context):
    result = LandSurfaceTemperatureDayMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.value is not None
    # A June daytime surface temperature over irrigated cropland.
    assert -30.0 < result.value < 75.0
    # The classic unit error: raw counts reported as degrees.
    assert result.value < 1000.0
    assert result.unit == "degC"


def test_nighttime_lst_is_cooler_than_daytime(gee_context):
    """Over land at this latitude in June, day exceeds night.

    If the two bands were wired to the same source this would fail, and
    it would fail loudly rather than returning a plausible small number.
    """
    day = LandSurfaceTemperatureDayMetric().compute(gee_context)
    night = LandSurfaceTemperatureNightMetric().compute(gee_context)

    assert day.status == STATUS_OK, day.message
    assert night.status == STATUS_OK, night.message
    assert day.value > night.value


def test_the_range_equals_day_minus_night(gee_context):
    day = LandSurfaceTemperatureDayMetric().compute(gee_context)
    night = LandSurfaceTemperatureNightMetric().compute(gee_context)
    span = DiurnalTemperatureRangeMetric().compute(gee_context)

    assert span.status == STATUS_OK, span.message
    assert span.value == pytest.approx(day.value - night.value, abs=0.5)
    assert span.unit == "K"


def test_the_range_is_positive_for_this_location(gee_context):
    """Day minus night over land is positive; a negative value would
    indicate the bands were swapped."""
    span = DiurnalTemperatureRangeMetric().compute(gee_context)
    assert span.value > 0.0


def test_lst_provenance_reports_the_1km_resolution(gee_context):
    result = LandSurfaceTemperatureDayMetric().compute(gee_context)
    resolution = result.provenance.spatial_resolution
    assert "1000" in resolution or "1 km" in resolution.lower()


def test_lst_provenance_carries_the_canopy_disclaimer(gee_context):
    """The prohibition must survive into a real provenance record."""
    result = LandSurfaceTemperatureDayMetric().compute(gee_context)
    limitations = " ".join(result.provenance.limitations).lower()
    assert "not canopy temperature" in limitations


def test_landsat_band_exists_and_converts_sensibly(gee_context):
    """Landsat may legitimately have no scene; the band must still exist."""
    import ee

    live = set(
        ee.ImageCollection(LANDSAT_THERMAL)
        .filterDate(START_DATE, END_DATE)
        .filterBounds(gee_context.geometry)
        .first()
        .bandNames()
        .getInfo()
    )
    assert "ST_B10" in live, "Landsat surface temperature band is missing"

    result = LandsatSurfaceTemperatureMetric().compute(gee_context)
    if result.status == STATUS_OK:
        assert -40.0 < result.value < 80.0


def test_landsat_reduces_at_100m_not_30m(gee_context):
    """The provenance must not claim the 30 m delivery grid."""
    metric = LandsatSurfaceTemperatureMetric()
    assert metric.effective_scale(gee_context) == 100


def test_the_whole_thermal_collection_executes(gee_context):
    outcomes, unknown = execute_metrics(THERMAL_METRICS, gee_context)

    assert not unknown, f"unexpectedly unknown metrics: {unknown}"

    failures = {
        key: outcome.result.message
        for key, outcome in outcomes.items()
        if outcome.result is not None and outcome.result.status != STATUS_OK
    }
    assert not failures, f"thermal metrics failed on real data: {failures}"

    for key, outcome in outcomes.items():
        result = outcome.result
        assert result.provenance is not None, key
        assert result.provenance.quality_level is not None, key
        # Every thermal result must state the canopy distinction.
        limitations = " ".join(result.provenance.limitations).lower()
        assert "not canopy temperature" in limitations, key


def test_no_thermal_metric_emits_a_canopy_temperature_key(gee_context):
    """Checked against the live engine, not just the source."""
    outcomes, _ = execute_metrics(THERMAL_METRICS, gee_context)
    for key in outcomes:
        assert "canopy" not in key.lower(), key
        assert "leaf" not in key.lower(), key
