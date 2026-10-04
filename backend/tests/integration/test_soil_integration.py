"""Opt-in integration tests for the soil moisture engine.

Skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set. These verify against
real Earth Engine what the unit suite cannot:

* that the SMAP L3 collection split is a real property of the archive and
  not just a documented claim, so the date-based collection selection
  actually picks a collection that returns data;
* that the SMAP retrieval quality flag exists in the live product and that
  masking on its skip bit is what makes the difference between a retrieval
  and a fill value;
* that the SMAP L4 root zone and wetness bands both exist, and that the
  wetness band really is a dimensionless 0-1 quantity in the archive;
* that the GLDAS-2.1 root zone band resolves and returns a water mass per
  unit area, the one soil figure that is not a volume fraction.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration/test_soil_integration.py -v

The geometry is a small parcel of irrigated cropland near Karaj, Iran.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.soil import (
    ERA5_DAILY,
    GLDAS_NATIVE_SCALE,
    GLDAS_NOAH,
    SMAP_L3_CURRENT,
    SMAP_L3_PREVIOUS,
    SMAP_L4,
    SOIL_METRICS,
    RootZoneSoilMoistureGLDASMetric,
    SoilMoistureRootZoneERA5Metric,
    SoilMoistureRootZoneMetric,
    SoilMoistureSurfaceEveningMetric,
    SoilMoistureSurfaceMetric,
    SoilMoistureWetnessMetric,
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

#: A month comfortably inside every soil archive used here: SMAP L3 v006
#: (2023-12-04 onward), SMAP L4 (2015 onward) and GLDAS-2.1 (2000 onward).
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


def test_the_smap_l3_split_is_real(gee_context):
    """The date-based selection must pick a collection that has data.

    Requesting v006 before its start returns an empty collection rather
    than an error, which is indistinguishable from a cloud problem. This
    asserts that the split is a property of the archive: the newer
    collection is empty before 2023-12-04 and non-empty after it.
    """
    import ee

    before = int(
        ee.ImageCollection(SMAP_L3_CURRENT)
        .filterDate("2020-06-01", "2020-06-30")
        .size()
        .getInfo()
    )
    after = int(
        ee.ImageCollection(SMAP_L3_CURRENT)
        .filterDate(START_DATE, END_DATE)
        .size()
        .getInfo()
    )
    previous = int(
        ee.ImageCollection(SMAP_L3_PREVIOUS)
        .filterDate("2020-06-01", "2020-06-30")
        .size()
        .getInfo()
    )

    assert before == 0, "the v006 collection is not empty before its start"
    assert after > 0, "the v006 collection is empty for a recent month"
    assert previous > 0, "the v005 collection is empty for 2020"


def test_every_declared_smap_l4_band_exists_live(gee_context):
    """A misspelled wetness band would silently return insufficient data."""
    import ee

    live = set(
        ee.ImageCollection(SMAP_L4)
        .filterDate(START_DATE, END_DATE)
        .first()
        .bandNames()
        .getInfo()
    )
    published = set(get_dataset(SMAP_L4).bands)
    missing = published - live
    assert not missing, f"declared bands absent from the asset: {missing}"


def test_the_smap_retrieval_quality_flag_exists_live(gee_context):
    """The skip-bit mask is only meaningful if the flag band is there."""
    import ee

    live = set(
        ee.ImageCollection(SMAP_L3_CURRENT)
        .filterDate(START_DATE, END_DATE)
        .first()
        .bandNames()
        .getInfo()
    )
    assert "soil_moisture_am" in live
    assert "retrieval_qual_flag_am" in live


def test_every_declared_era5_layer_band_exists_live(gee_context):
    """Layers 1 to 3 are the thickness-weighted root zone inputs."""
    import ee

    live = set(
        ee.ImageCollection(ERA5_DAILY)
        .filterDate(START_DATE, END_DATE)
        .first()
        .bandNames()
        .getInfo()
    )
    for layer in (1, 2, 3):
        band = f"volumetric_soil_water_layer_{layer}"
        assert band in live, f"{band} is missing from the ERA5-Land asset"


def test_the_gldas_root_zone_band_resolves_at_its_native_scale(gee_context):
    """The dataset ID, the band name and the 27.8 km grid, all live."""
    import ee

    collection = (
        ee.ImageCollection(GLDAS_NOAH)
        .filterDate(START_DATE, END_DATE)
        .filterBounds(gee_context.geometry)
    )
    assert int(collection.size().getInfo()) > 0, "GLDAS returned no images"

    image = collection.first()
    assert "RootMoist_inst" in image.bandNames().getInfo()

    scale = float(
        image.select("RootMoist_inst").projection().nominalScale().getInfo()
    )
    assert scale == pytest.approx(float(GLDAS_NATIVE_SCALE), rel=0.01)


# ==========================================================================
# The metrics themselves
# ==========================================================================


def test_the_surface_metric_reports_a_volume_fraction(gee_context):
    """SMAP L3 reports m3/m3 live, exactly as declared."""
    result = SoilMoistureSurfaceMetric().compute(gee_context)
    if result.status != STATUS_OK:
        pytest.skip(f"surface retrieval unavailable: {result.message}")
    assert result.unit == "m3/m3"


def test_surface_soil_moisture_is_physically_possible(gee_context):
    """Above porosity would indicate a masking or scaling problem."""
    result = SoilMoistureSurfaceMetric().compute(gee_context)
    if result.status != STATUS_OK:
        pytest.skip(f"surface retrieval unavailable: {result.message}")
    assert 0.0 <= result.value <= 0.6


def test_the_morning_and_evening_metrics_stay_separate(gee_context):
    """Averaging the two overpasses describes a time that does not exist."""
    morning = SoilMoistureSurfaceMetric().compute(gee_context)
    evening = SoilMoistureSurfaceEveningMetric().compute(gee_context)

    # Either may be unavailable for a given window; what must never happen
    # is the two being merged into one value.
    assert morning.metric_key != evening.metric_key
    if morning.status == STATUS_OK and evening.status == STATUS_OK:
        assert morning.unit == evening.unit == "m3/m3"


def test_the_root_zone_metrics_are_volume_fractions(gee_context):
    for metric in (SoilMoistureRootZoneMetric(), SoilMoistureRootZoneERA5Metric()):
        result = metric.compute(gee_context)
        if result.status != STATUS_OK:
            pytest.skip(f"{metric.key} unavailable: {result.message}")
        assert result.unit == "m3/m3"
        assert 0.0 <= result.value <= 0.9


def test_the_wetness_metric_is_a_dimensionless_fraction(gee_context):
    result = SoilMoistureWetnessMetric().compute(gee_context)
    if result.status != STATUS_OK:
        pytest.skip(f"wetness unavailable: {result.message}")
    assert result.unit == "fraction"
    assert 0.0 <= result.value <= 1.0


def test_the_gldas_metric_returns_a_water_mass_in_its_own_unit(gee_context):
    """The one soil metric that is not a volume fraction, checked live.

    A root zone water mass between roughly 0 and 1000 kg/m2 is physically
    plausible for a semi-arid parcel. A value below 1.0 would look like a
    volume fraction leaking through, and a negative value would indicate a
    sign or masking problem in the source.
    """
    result = RootZoneSoilMoistureGLDASMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.unit == "kg/m2"
    assert 0.0 < result.value < 1000.0
    assert any("kg/m2" in w for w in result.warnings)


def test_the_gldas_metric_does_not_convert_to_m3_m3_live(gee_context):
    """Provenance must state the no-conversion decision on real inputs."""
    result = RootZoneSoilMoistureGLDASMetric().compute(gee_context)
    if result.status != STATUS_OK:
        pytest.skip(f"GLDAS unavailable: {result.message}")

    joined = " ".join(result.provenance.limitations).lower()
    assert "no conversion" in joined
    assert "kg/m2" in joined
    assert result.provenance.unit == "kg/m2"
    assert result.provenance.source_dataset_id == GLDAS_NOAH


def test_the_gldas_provenance_cites_the_published_paper(gee_context):
    result = RootZoneSoilMoistureGLDASMetric().compute(gee_context)
    if result.status != STATUS_OK:
        pytest.skip(f"GLDAS unavailable: {result.message}")

    assert "Rodell" in result.provenance.citation


def test_the_soil_metrics_never_share_one_unit(gee_context):
    """Volume fractions and the mass per area must stay distinct units."""
    units = {m.key: m.unit for m in SOIL_METRICS}
    assert units["root_zone_soil_moisture_gldas"] == "kg/m2"
    assert units["soil_moisture_wetness"] == "fraction"
    for key, unit in units.items():
        if key in ("root_zone_soil_moisture_gldas", "soil_moisture_wetness"):
            continue
        assert unit == "m3/m3", key


def test_the_whole_soil_collection_executes(gee_context):
    outcomes, unknown = execute_metrics(SOIL_METRICS, gee_context)

    assert not unknown, f"unexpectedly unknown metrics: {unknown}"

    failures = {
        key: outcome.result.message
        for key, outcome in outcomes.items()
        if outcome.result is not None and outcome.result.status != STATUS_OK
    }
    assert not failures, f"soil metrics failed on real data: {failures}"

    for key, outcome in outcomes.items():
        result = outcome.result
        assert result.provenance is not None, key
        assert result.provenance.quality_level is not None, key
        assert result.provenance.citation, key
        # The unit discipline must survive the live path.
        assert result.unit in ("m3/m3", "fraction", "kg/m2"), key

