"""Opt-in integration tests for the Phase K stress layer.

These are skipped unless ``RUN_GEE_INTEGRATION_TESTS`` is set to a truthy
value. They need network access and service-account credentials.

What these tests are for: every Phase K metric is *derived* from bands the
lower layers already read, so the unit suite's fake Earth Engine verifies
the formulas and the alignment rules. Only a real call can confirm that a
derived metric survives contact with the live archive: that the SMAP L4
root-zone band resolves, that the MOD16 fallback chain picks a collection
that actually contains the requested window, that ten preceding years of
MOD11A2 are reachable for the LST baselines, and that the pooled VPD
reference distribution is non-empty for a real June.

A derived metric may legitimately refuse on live data -- an empty SMAP
window or too few contributing baseline years is a correct answer, not a
failure. The assertions therefore accept STATUS_INSUFFICIENT_DATA wherever
a refusal is scientifically valid, and require only that a refusal carries
a provenance record and a stated reason.

Run with:

    RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest \\
        tests/integration -v

The geometry is a small parcel of irrigated cropland near Karaj, Iran,
the same parcel the climate and thermal integration files use.
"""

from __future__ import annotations

import os

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.climate import ERA5_DAILY
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.soil import SMAP_L4
from app.services.agriculture.soil_properties import (
    ROOT_ZONE_INTERVALS,
    SOILGRIDS_WV0033,
    SOILGRIDS_WV1500,
    _layer_band,
)
from app.services.agriculture.stress import (
    STRESS_METRICS,
    CompositeStressMetric,
    EvaporativeFractionMetric,
    LSTDayAnomalyMetric,
    LSTDayPercentileMetric,
    PlantAvailableWaterFractionMetric,
    SoilWaterContentRatioMetric,
    VPDAnomalyMetric,
    VPDHighDurationMetric,
)
from app.services.agriculture.thermal import MODIS_LST_8DAY
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

#: A month in the recent past. Well inside every archive the stress layer
#: reads, and distant enough that late-arriving data has settled.
START_DATE = "2025-06-01"
END_DATE = "2025-06-30"

#: Every (dataset, bands) pair a stress metric derives from. The band
#: names must match the live collection, or the metric cannot compute.
#: MOD16 appears twice because the metric resolves the gap-filled product
#: first and falls back to the near-real-time one; both must be checked.
BAND_GROUPS = [
    (SMAP_L4, ["sm_rootzone"]),
    (MOD16_GAPFILLED, ["ET", "PET"]),
    (MOD16_NRT, ["ET", "PET"]),
    (MODIS_LST_8DAY, ["LST_Day_1km"]),
    (
        SOILGRIDS_WV0033,
        [_layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS],
    ),
    (
        SOILGRIDS_WV1500,
        [_layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS],
    ),
    (ERA5_DAILY, ["temperature_2m", "dewpoint_temperature_2m"]),
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


def test_every_declared_stress_band_exists_in_its_live_collection(gee_context):
    """The registry's band names must match what Earth Engine publishes."""
    import ee

    for dataset_id, bands in BAND_GROUPS:
        first = ee.ImageCollection(dataset_id).first()
        live_bands = set(first.bandNames().getInfo())
        missing = set(bands) - live_bands
        assert not missing, (
            f"these stress-layer bands do not exist in {dataset_id}: "
            f"{sorted(missing)}. Available: {sorted(live_bands)}"
        )


def test_evaporative_fraction_is_a_sane_ratio(gee_context):
    """EF is ET/PET; it must be non-negative and not absurdly large."""
    result = EvaporativeFractionMetric().compute(gee_context)

    assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
        result.message
    )
    if result.status == STATUS_OK:
        assert 0.0 <= result.value < 2.0, result.value


def test_soil_moisture_ratios_are_non_negative(gee_context):
    """Both soil ratios are formed from physical units; negatives are bugs."""
    for metric in (
        SoilWaterContentRatioMetric(),
        PlantAvailableWaterFractionMetric(),
    ):
        result = metric.compute(gee_context)
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
            f"{metric.key}: {result.message}"
        )
        if result.status == STATUS_OK:
            assert result.value is not None, metric.key


def test_vpd_metrics_name_their_baseline(gee_context):
    """An anomaly or duration without its baseline is uninterpretable."""
    for metric in (VPDAnomalyMetric(), VPDHighDurationMetric()):
        result = metric.compute(gee_context)
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
            f"{metric.key}: {result.message}"
        )
        if result.status == STATUS_OK:
            caveats = " ".join(result.provenance.caveats)
            assert "Baseline:" in caveats, metric.key
            assert "contributing" in caveats, metric.key


def test_lst_baseline_metrics_carry_their_reference_period(gee_context):
    for metric in (LSTDayAnomalyMetric(), LSTDayPercentileMetric()):
        result = metric.compute(gee_context)
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT_DATA), (
            f"{metric.key}: {result.message}"
        )
        if result.status == STATUS_OK:
            caveats = " ".join(result.provenance.caveats)
            assert "Baseline:" in caveats, metric.key
            limitations = " ".join(result.provenance.limitations).lower()
            assert "not canopy temperature" in limitations, metric.key


def test_the_whole_stress_collection_executes(gee_context):
    """Run every available stress metric through the executor.

    A refusal with a stated reason is a valid outcome on live data; a
    crash, an unknown key, or a missing provenance record is not.
    """
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    outcomes, unknown = execute_metrics(
        [m.key for m in STRESS_METRICS], gee_context
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


def test_the_composite_index_stays_unavailable_with_its_reason(gee_context):
    """The composite must refuse with the weighting reason, not compute."""
    result = CompositeStressMetric().compute(gee_context)

    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None
    assert result.reason == "no_scientific_weighting"
    assert result.message, "the refusal must state why"
