"""Opt-in integration tests for the water engine.

Skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set. These verify against
real Earth Engine what the unit suite cannot: that the MOD16 and ERA5-Land
band names resolve in the live assets, that the Sentinel-2 water indices
read the bands they claim to, that the MOD16 scale factor produces
millimetres rather than raw stored counts, and that the ERA5 sign
convention really is negative-for-upward in the archive and not merely in
the fixture.

That last check is the reason this file exists. The unit suite pins the
negation with a fake that supplies raw stored values, but only the real
asset can confirm the stored sign. A sign flipped the wrong way produces a
number of the right magnitude, which is the most dangerous class of error
in this module.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration/test_water_integration.py -v

The geometry is a small parcel of irrigated cropland near Karaj, Iran,
chosen because it has a long Sentinel-2 and ERA5 record.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.types import STATUS_OK, STATUS_UNAVAILABLE
from app.services.agriculture.water import (
    ERA5_DAILY,
    MOD16_GAPFILLED,
    WATER_METRICS,
    CumulativeEvapotranspirationMetric,
    ERA5EvaporationMetric,
    EvapotranspirationMetric,
    MNDWIMetric,
    NDMIMetric,
    NDWIMetric,
    PotentialEvapotranspirationMetric,
)

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

#: A full month, so the 8-day MOD16 composite has several windows and the
#: Sentinel-2 indices have a reasonable chance of cloud-free scenes.
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


# ==========================================================================
# The datasets themselves
# ==========================================================================


def test_mod16_datasets_resolve(gee_context):
    import ee

    size = int(ee.ImageCollection(MOD16_GAPFILLED).size().getInfo())
    assert size > 0, f"{MOD16_GAPFILLED} is empty; the ID may be wrong"


def test_every_declared_mod16_band_exists_live(gee_context):
    """A misspelled ET or PET band would silently return unavailable."""
    import ee

    live = set(
        ee.ImageCollection(MOD16_GAPFILLED).first().bandNames().getInfo()
    )
    published = set(get_dataset(MOD16_GAPFILLED).bands)
    missing = published - live
    assert not missing, f"declared bands absent from the asset: {missing}"


def test_the_mod16_scale_factor_produces_millimetres(gee_context):
    """The load-bearing scale-factor check for this module.

    MOD16 stores ET as a 0.1-scaled value in kg/m2/8day. A June value at
    this location should land in single-digit to low tens of millimetres
    per 8-day period. Raw stored counts would be ten times larger, and a
    decoded value of thousands would indicate the factor was not applied.
    """
    result = EvapotranspirationMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.unit == "mm/period"
    assert 0.0 < result.value < 200.0, (
        f"ET of {result.value} mm/period looks like raw stored counts"
    )


def test_the_era5_evaporation_band_is_negative_for_upward_flux(gee_context):
    """The sign convention, checked against the archive rather than a fake.

    ERA5-Land stores evaporation as a negative number when water leaves the
    surface. If this assertion ever fails, either the asset changed its
    convention or this module's assumption about it is wrong, and both are
    worth failing loudly for.
    """
    import ee

    stored = (
        ee.ImageCollection(ERA5_DAILY)
        .filterDate(START_DATE, END_DATE)
        .filterBounds(gee_context.geometry)
        .select(["total_evaporation_sum"])
        .mean()
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=gee_context.geometry,
            scale=11132,
            maxPixels=1e9,
            bestEffort=True,
        )
        .getInfo()
    )

    value = stored.get("total_evaporation_sum")
    assert value is not None, "no ERA5 evaporation value was returned"
    assert value < 0.0, (
        "ERA5 total_evaporation_sum is not negative for a June month; the "
        "negation in the metric assumes it is"
    )


def test_era5_evaporation_is_reported_positive_and_in_millimetres(gee_context):
    result = ERA5EvaporationMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.unit == "mm"
    # A June month in Karaj: positive evaporation, well under a metre.
    assert 0.0 < result.value < 500.0


def test_the_era5_component_bands_are_never_read():
    """The asset carries swapped component values; the total is the input.

    Asserted against the metric's declared source bands, so a later edit
    cannot quietly start reading a component.
    """
    for band in ERA5EvaporationMetric().source_bands:
        assert "from_bare_soil" not in band
        assert "from_open_water" not in band
        assert "from_vegetation_transpiration" not in band


# ==========================================================================
# The metrics themselves
# ==========================================================================


def test_the_water_indices_read_the_bands_they_claim():
    """Each index must read the band pair of its published formula.

    NDWI is green/NIR, NDMI is NIR/SWIR1 and MNDWI is green/SWIR1. Feeding
    the same pair to any two of them would produce a numerically valid but
    physically meaningless number.
    """
    assert NDWIMetric().required_bands == ("B3", "B8")
    assert NDMIMetric().required_bands == ("B8", "B11")
    assert MNDWIMetric().required_bands == ("B3", "B11")


def test_the_swir_indices_reduce_at_twenty_metres(gee_context):
    """B11 is acquired at 20 m; claiming 10 m would be false."""
    assert NDMIMetric().effective_scale(gee_context) == 20
    assert MNDWIMetric().effective_scale(gee_context) == 20
    assert NDWIMetric().effective_scale(gee_context) == 10


def test_the_water_indices_return_indices_in_range(gee_context):
    for metric in (NDWIMetric(), NDMIMetric(), MNDWIMetric()):
        result = metric.compute(gee_context)
        assert result.status == STATUS_OK, f"{metric.key}: {result.message}"
        assert -1.0 <= result.value <= 1.0, metric.key


def test_pet_is_not_far_below_et_for_this_month(gee_context):
    """PET is the atmospheric demand and ET the realised flux.

    Over an irrigated parcel in midsummer the two can be close, but PET
    should not sit far below ET. A large inversion would indicate the two
    bands were swapped.
    """
    et = EvapotranspirationMetric().compute(gee_context)
    pet = PotentialEvapotranspirationMetric().compute(gee_context)

    if pet.status != STATUS_OK:
        pytest.skip(f"PET unavailable for this period: {pet.message}")

    assert et.status == STATUS_OK, et.message
    assert pet.value > 0.0
    assert pet.value > et.value * 0.5


def test_the_cumulative_metric_is_not_smaller_than_one_period(gee_context):
    single = EvapotranspirationMetric().compute(gee_context)
    cumulative = CumulativeEvapotranspirationMetric().compute(gee_context)

    if cumulative.status != STATUS_OK:
        pytest.skip(f"cumulative ET unavailable: {cumulative.message}")

    assert single.status == STATUS_OK, single.message
    assert cumulative.unit == "mm"
    assert cumulative.value >= single.value


def test_the_refusals_carry_no_value_on_real_inputs(gee_context):
    """CWSI and WDI must be unavailable with no number, live as well."""
    from app.services.agriculture.water import UNAVAILABLE_WATER_METRICS

    for metric in UNAVAILABLE_WATER_METRICS:
        result = metric.compute(gee_context)
        assert result.status == STATUS_UNAVAILABLE, metric.key
        assert result.value is None, metric.key
        assert result.provenance is not None, metric.key


def test_the_whole_water_collection_executes(gee_context):
    outcomes, unknown = execute_metrics(WATER_METRICS, gee_context)

    assert not unknown, f"unexpectedly unknown metrics: {unknown}"

    failures = {
        key: outcome.result.message
        for key, outcome in outcomes.items()
        if outcome.result is not None and outcome.result.status != STATUS_OK
    }
    assert not failures, f"water metrics failed on real data: {failures}"

    for key, outcome in outcomes.items():
        result = outcome.result
        assert result.provenance is not None, key
        assert result.provenance.quality_level is not None, key
        assert result.provenance.citation, key

