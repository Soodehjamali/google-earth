"""Opt-in integration tests that call Earth Engine for real.

These are skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set to a truthy
value. They are excluded from the default run because they need network
access and service-account credentials, and a test suite that requires
either is a test suite nobody runs.

What these tests are for: the unit suite verifies the formulas, the
wiring and the safety rules, but it uses a fake Earth Engine. Only a real
call can confirm that a band name is spelled correctly, that a dataset ID
resolves, that the date range is inside the archive, and that the
reduction returns the shape the parser expects. Those are exactly the
mistakes that reach production otherwise.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration -v

The geometry used is a small parcel of irrigated cropland near Karaj,
Iran, chosen because it has a long Sentinel-2 and ERA5 record.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.climate import CLIMATE_METRICS, ERA5_DAILY
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.types import STATUS_OK

pytestmark = pytest.mark.integration


#: A small agricultural parcel in Karaj, Iran. Roughly 1.5 km across,
#: which comfortably contains several ERA5-Land grid cells.
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

#: A month in the recent past. Well inside both archives, and distant
#: enough that late-arriving data has settled.
START_DATE = "2025-06-01"
END_DATE = "2025-06-30"


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
        geometry_key="karaj-parcel",
        options={"area_sq_m": 4_000_000.0},
    )


def test_era5_dataset_resolves(gee_context):
    """The dataset ID must exist. A typo here breaks every climate metric."""
    import ee

    collection = ee.ImageCollection(ERA5_DAILY)
    size = int(collection.size().getInfo())
    assert size > 0, "ERA5-Land collection is empty; the ID may be wrong"


def test_every_declared_era5_band_exists_in_the_live_collection(gee_context):
    """The registry's band names must match what Earth Engine publishes.

    This is the check the fake Earth Engine cannot perform, and it is the
    single most valuable integration test in this package.
    """
    import ee

    first = ee.ImageCollection(ERA5_DAILY).first()
    live_bands = set(first.bandNames().getInfo())

    declared = set()
    for metric in CLIMATE_METRICS:
        declared.update(metric.source_bands)

    missing = declared - live_bands
    assert not missing, (
        f"these registry bands do not exist in {ERA5_DAILY}: "
        f"{sorted(missing)}. Available: {sorted(live_bands)}"
    )


def test_the_archive_covers_the_requested_period(gee_context):
    """The requested dates must be inside the archive."""
    import ee

    collection = (
        ee.ImageCollection(ERA5_DAILY)
        .filterDate(START_DATE, END_DATE)
        .filterBounds(gee_context.geometry)
    )
    assert int(collection.size().getInfo()) > 0, (
        f"no ERA5-Land days between {START_DATE} and {END_DATE}"
    )


def test_precipitation_is_in_a_physically_possible_range(gee_context):
    """A month of rain must not be negative or absurd."""
    from app.services.agriculture.climate import PrecipitationMetric

    result = PrecipitationMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.value is not None
    # A June total in this region is small, but the check is that it is
    # a sane depth of water rather than the exact expected value.
    assert 0.0 <= result.value < 2000.0
    assert result.provenance.source_dataset_id == ERA5_DAILY


def test_temperature_is_in_celsius_not_kelvin(gee_context):
    """The classic failure: 300 degrees would pass a naive range check."""
    from app.services.agriculture.climate import TemperatureMeanMetric

    result = TemperatureMeanMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    # A June mean in Karaj. Kelvin would be around 300.
    assert -20.0 < result.value < 50.0
    assert result.unit == "degC"


def test_relative_humidity_is_a_percentage(gee_context):
    from app.services.agriculture.climate import RelativeHumidityMetric

    result = RelativeHumidityMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert 0.0 <= result.value <= 100.0


def test_vpd_is_non_negative_and_bounded(gee_context):
    from app.services.agriculture.climate import VPDMetric

    result = VPDMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.value >= 0.0
    # VPD above about 10 kPa would indicate a unit error.
    assert result.value < 10.0


def test_solar_radiation_is_a_sane_monthly_accumulation(gee_context):
    from app.services.agriculture.climate import SolarRadiationMetric

    result = SolarRadiationMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    # A June month at this latitude. In megajoules, not joules.
    assert 100.0 < result.value < 1000.0


def test_par_is_below_shortwave(gee_context):
    from app.services.agriculture.climate import PARMetric, SolarRadiationMetric

    par = PARMetric().compute(gee_context)
    shortwave = SolarRadiationMetric().compute(gee_context)

    assert par.status == STATUS_OK, par.message
    assert shortwave.status == STATUS_OK, shortwave.message
    assert par.value < shortwave.value
    assert par.value == pytest.approx(shortwave.value * 0.45, rel=0.02)


def test_wind_speed_is_physically_possible(gee_context):
    from app.services.agriculture.climate import WindSpeedMetric

    result = WindSpeedMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert 0.0 <= result.value < 60.0


def test_gdd_accumulates_over_a_month(gee_context):
    from app.services.agriculture.climate import GDDMetric

    result = GDDMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    # June in Karaj with a base of 10 should accumulate a few hundred.
    assert 0.0 < result.value < 1000.0
    assert result.unit == "degC-day"


def test_the_whole_climate_collection_executes(gee_context):
    """Run every climate metric through the executor.

    Verifies that no metric fails on real data, which catches reductions
    that return nothing, band lookups that come back null, and quality
    assessments that end up unavailable.
    """
    outcomes, unknown = execute_metrics(CLIMATE_METRICS, gee_context)

    assert not unknown, f"unexpectedly unknown metrics: {unknown}"

    failures = {
        key: outcome.result.message
        for key, outcome in outcomes.items()
        if outcome.result is not None
        and outcome.result.status != STATUS_OK
    }
    assert not failures, f"metrics failed on real data: {failures}"

    for key, outcome in outcomes.items():
        result = outcome.result
        assert result is not None, key
        assert result.value is not None, key
        # Nothing may be published without its derivation record.
        assert result.provenance is not None, key
        assert result.provenance.quality_level is not None, key


def test_provenance_reports_the_native_era5_resolution(gee_context):
    """ERA5-Land is 0.1 degrees, roughly 11 km. That must be stated."""
    from app.services.agriculture.climate import PrecipitationMetric

    result = PrecipitationMetric().compute(gee_context)
    provenance = result.provenance

    assert provenance.spatial_resolution
    assert "11" in provenance.spatial_resolution or "0.1" in provenance.spatial_resolution
    assert provenance.temporal_resolution
    assert provenance.citation
