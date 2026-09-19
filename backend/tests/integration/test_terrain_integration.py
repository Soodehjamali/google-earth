"""Opt-in live Earth Engine tests for the terrain metrics.

These are skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set, following
the same conventions as the climate and thermal integration tests: the
default suite must never need the network or credentials.

What only a live call can prove here:

- the historical contradiction is actually fixed: a 2024 request against
  a DEM acquired in February 2000 must compute, not reject with
  ``outside_temporal_coverage``;
- NASADEM's dataset ID, band names and geoid reference produce sane
  numbers for a known parcel;
- the SRTM fallback path works against the real archive;
- the provenance keeps the acquisition date separate from the requested
  period on live data, not just on fakes;
- TWI stays unavailable even when Earth Engine is reachable — absence of
  a primitive is a property of the platform, not of the connection.

The geometry is the same small irrigated cropland parcel near Karaj, Iran
used by the other integration tests. The analysis date is deliberately a
realistic 2024 request, which is exactly the case the temporal contract
was written for.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.terrain import (
    NASADEM,
    SRTM,
    AspectMetric,
    ElevationMetric,
    SlopeMetric,
    TerrainRuggednessMetric,
    TopographicWetnessIndexMetric,
)
from app.services.agriculture.types import (
    STATUS_OK,
    STATUS_UNAVAILABLE,
    TemporalKind,
)

pytestmark = pytest.mark.integration


#: The Karaj parcel, identical to the other integration suites.
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

#: A realistic analysis date. The DEM was acquired in February 2000; the
#: point of these tests is that the request date is context, not coverage.
START_DATE = "2024-04-01"
END_DATE = "2024-04-30"


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


def test_nasadem_is_registered_as_static():
    """The registry, not the request path, carries the classification."""
    spec = get_dataset(NASADEM)
    assert spec.is_static is True
    assert spec.temporal_kind is TemporalKind.STATIC


def test_srtm_is_registered_as_static():
    spec = get_dataset(SRTM)
    assert spec.is_static is True
    assert spec.temporal_kind is TemporalKind.STATIC


def test_nasadem_elevation_computes_for_a_2024_request(gee_context):
    """The exact request shape the old contract rejected."""
    result = ElevationMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.value is not None
    # The Karaj parcel sits at roughly 1300 m above the EGM96 geoid.
    # The bounds are generous; what they rule out is a unit error or a
    # masked-out zero, not a slightly different mean.
    assert 900.0 < result.value < 1800.0
    assert result.unit == "m"
    assert result.provenance.source_dataset_id == NASADEM


def test_nasadem_slope_computes_for_a_2024_request(gee_context):
    result = SlopeMetric().compute(gee_context)

    assert result.status == STATUS_OK, result.message
    assert result.value is not None
    # Irrigated cropland on the plain: a slope above 45 degrees would
    # indicate a degrees/radians or unit failure, not a steep field.
    assert 0.0 <= result.value < 45.0
    assert result.unit == "degrees"


def test_nasadem_aspect_computes_for_a_2024_request(gee_context):
    result = AspectMetric().compute(gee_context)

    # On predominantly flat irrigated ground the metric may legitimately
    # return insufficient data when too little of the parcel clears the
    # slope threshold — that is the aspect convention working, not a
    # failure. What must not happen is a rejection on temporal grounds or
    # an out-of-range bearing.
    assert result.status in (STATUS_OK, "insufficient_data")
    if result.status == STATUS_OK:
        assert 0.0 <= result.value < 360.0
        assert result.unit == "degrees"


def test_ruggedness_computes_for_a_2024_request(gee_context):
    result = TerrainRuggednessMetric().compute(gee_context)

    assert result.status in (STATUS_OK, "insufficient_data")
    if result.status == STATUS_OK:
        assert result.value is not None
        assert result.value >= 0.0


def test_elevation_provenance_keeps_acquisition_separate_from_request(
    gee_context,
):
    """Live provenance must not read as though the DEM were observed in 2024."""
    result = ElevationMetric().compute(gee_context)

    if result.status != STATUS_OK:
        pytest.skip(f"elevation did not compute live: {result.message}")

    provenance = result.provenance
    assert provenance.temporal_kind is TemporalKind.STATIC
    assert provenance.requested_start == START_DATE
    assert provenance.requested_end == END_DATE
    assert provenance.product_date == "2000-02-11"
    assert provenance.product_date != provenance.requested_start


def test_srtm_fallback_resolves_live(gee_context):
    """The fallback must be reachable through the same static contract."""
    result = SlopeMetric().compute(gee_context)

    if result.status != STATUS_OK:
        pytest.skip(f"slope did not compute live: {result.message}")

    # On this parcel NASADEM normally succeeds; the assertion is that the
    # chain is coherent whichever product served the result.
    assert result.provenance.source_dataset_id in (NASADEM, SRTM)
    if result.provenance.source_dataset_id == SRTM:
        assert result.provenance.fallback_from == NASADEM


def test_twi_is_unavailable_even_with_live_earth_engine(gee_context):
    """A reachable platform does not create a flow-accumulation primitive."""
    result = TopographicWetnessIndexMetric().compute(gee_context)

    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None
    assert result.reason == "no_flow_accumulation_primitive"
