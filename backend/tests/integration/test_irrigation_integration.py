"""Opt-in integration tests for the Phase L irrigation analytics layer.

These are skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set to a truthy
value. They need network access and service-account credentials.

What these tests are for: every Phase L metric is *derived* from bands the
lower layers already read -- cumulative precipitation from the ERA5-Land
daily total, the ET-minus-precipitation deficit from the Phase K water
metric plus that precipitation sum, and the anomaly metrics from whole-year
baseline shifts of the same inputs. The unit suite's fake Earth Engine
verifies the formulas and the alignment rules; only a real call can confirm
that a derived metric survives contact with the live archive: that the
ERA5-Land precipitation band resolves in metres and converts exactly once,
that the MOD16 fallback chain picks a collection that actually contains the
requested window, and that ten preceding years of ERA5-Land (or five of
SMAP L4) are reachable for the baselines.

A derived metric may legitimately refuse on live data -- an empty window or
too few contributing baseline years is a correct answer, not a failure. The
assertions therefore accept STATUS_INSUFFICIENT_DATA wherever a refusal is
scientifically valid, and require only that a refusal carries a provenance
record and a stated reason. These tests confirm the metrics execute against
the live archive; they do not validate the numbers scientifically.

The service account needs at least the ``roles/earthengine.viewer`` IAM
role (or a custom role granting ``earthengine.assets.list`` and read access
to the public catalogs used here). The codebase documents this as
infrastructure, not as a test concern; without it every test skips.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration -v

The geometry is a small parcel of irrigated cropland near Karaj, Iran,
the same parcel the climate, thermal and stress integration files use.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.climate import ERA5_DAILY
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.irrigation import (
    IRRIGATION_METRICS,
    CropEvapotranspirationMetric,
    ETPrecipitationDeficitMetric,
    EvapotranspirationAnomalyMetric,
    GrossIrrigationRequirementMetric,
    IrrigationWaterRequirementMetric,
    PrecipitationAnomalyMetric,
    PrecipitationCumulativeMetric,
    SoilMoistureRootZoneAnomalyMetric,
)
from app.services.agriculture.irrigation import ERA5_PRECIPITATION_BAND
from app.services.agriculture.soil import SMAP_L4
from app.services.agriculture.types import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.water import MOD16_GAPFILLED, MOD16_NRT

pytestmark = pytest.mark.integration


#: A small agricultural parcel in Karaj, Iran. Roughly 2 km across, which
#: comfortably contains several ERA5-Land and SMAP L4 grid cells.
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

#: A month in the recent past. Well inside every archive the irrigation
#: layer reads, and distant enough that late-arriving data has settled.
START_DATE = "2025-06-01"
END_DATE = "2025-06-30"

#: Every (dataset, bands) pair an irrigation metric derives from. The band
#: names must match the live collection, or the metric cannot compute.
#: MOD16 appears twice because the water metric resolves the gap-filled
#: product first and falls back to the near-real-time one; both must be
#: checked.
BAND_GROUPS = [
    (ERA5_DAILY, [ERA5_PRECIPITATION_BAND]),
    (MOD16_GAPFILLED, ["ET"]),
    (MOD16_NRT, ["ET"]),
    (SMAP_L4, ["sm_rootzone"]),
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
        geometry_key="karaj-parcel",
        options={"area_sq_m": 4_000_000.0},
    )


def test_every_declared_irrigation_band_exists_in_its_live_collection(
    gee_context,
):
    """The metric band names must match what Earth Engine publishes."""
    import ee

    for dataset_id, bands in BAND_GROUPS:
        first = ee.ImageCollection(dataset_id).first()
        live_bands = set(first.bandNames().getInfo())
        missing = set(bands) - live_bands
        assert not missing, (
            f"these irrigation-layer bands do not exist in {dataset_id}: "
            f"{sorted(missing)}. Available: {sorted(live_bands)}"
        )


def test_cumulative_precipitation_is_non_negative(gee_context):
    """A precipitation integral cannot be negative."""
    result = PrecipitationCumulativeMetric().compute(gee_context)

    assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
        result.message
    )
    if result.status == STATUS_OK:
        assert result.value is not None
        assert result.value >= 0.0, result.value
        assert result.unit == "mm"


def test_the_deficit_carries_its_water_balance_terms(gee_context):
    """The deficit must label observed versus unavailable balance terms."""
    result = ETPrecipitationDeficitMetric().compute(gee_context)

    assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
        result.message
    )
    if result.status == STATUS_OK:
        assert result.value is not None
        caveats = " ".join(result.provenance.caveats)
        assert "Water-balance terms:" in caveats
        assert "runoff (unavailable" in caveats
        assert "drainage (unavailable" in caveats
        assert "Inputs:" in caveats


def test_anomaly_metrics_name_their_baseline(gee_context):
    """An anomaly without its baseline window is uninterpretable."""
    for metric in (
        PrecipitationAnomalyMetric(),
        EvapotranspirationAnomalyMetric(),
        SoilMoistureRootZoneAnomalyMetric(),
    ):
        result = metric.compute(gee_context)
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
            f"{metric.key}: {result.message}"
        )
        if result.status == STATUS_OK:
            caveats = " ".join(result.provenance.caveats)
            assert "Baseline:" in caveats, metric.key
            assert "Requested window:" in caveats, metric.key


def test_the_unavailable_trio_refuses_with_its_codes(gee_context):
    """The water-requirement metrics must refuse, with precise reasons."""
    expected = {
        IrrigationWaterRequirementMetric: "unsupported_water_balance_terms",
        GrossIrrigationRequirementMetric: "no_efficiency_parameter",
        CropEvapotranspirationMetric: "no_verified_crop_coefficient",
    }
    for metric_type, code in expected.items():
        result = metric_type().compute(gee_context)
        assert result.status == STATUS_UNAVAILABLE, (
            f"{metric_type().key}: {result.status}"
        )
        assert result.value is None
        assert result.reason == code, (metric_type().key, result.reason)
        assert result.message, metric_type().key


def test_the_whole_irrigation_collection_executes(gee_context):
    """Run every available irrigation metric through the executor.

    A refusal with a stated reason is a valid outcome on live data; a
    crash, an unknown key, or a missing provenance record is not.
    """
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    outcomes, unknown = execute_metrics(
        [m.key for m in IRRIGATION_METRICS], gee_context
    )

    assert not unknown, f"unexpectedly unknown metrics: {unknown}"

    for key, outcome in outcomes.items():
        result = outcome.result
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
            f"{key}: {result.status} {result.message}"
        )
        assert result.provenance is not None, key
        assert result.provenance.quality_level is not None, key
        if result.status == STATUS_OK:
            assert result.value is not None, key
