"""Tests for the central dataset registry.

These are the highest-value tests in the engine. If a scale factor or a
band name here is wrong, every metric built on top of it is wrong in a
way that produces plausible-looking numbers. So the registry tests are
deliberately pedantic.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import pytest

from app.services.agriculture.registry import (
    EXTERNAL_REGISTRY,
    REGISTRY,
    dataset_ids,
    find_by_role,
    get_dataset,
    get_datasets,
    get_external_dataset,
    has_dataset,
)
from app.services.agriculture.types import (
    PENDING_VERIFICATION,
    DatasetSpec,
    MeasurementBasis,
)


# --------------------------------------------------------------------------
# Access API
# --------------------------------------------------------------------------


def test_get_dataset_returns_registered_spec():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert isinstance(spec, DatasetSpec)
    assert spec.id == "COPERNICUS/S2_SR_HARMONIZED"


def test_get_dataset_unknown_id_raises_with_actionable_message():
    with pytest.raises(KeyError) as exc:
        get_dataset("NOT/A/REAL/DATASET")
    message = str(exc.value)
    # The error must tell the next developer what to do about it.
    assert "not registered" in message
    assert "verified" in message


def test_has_dataset():
    assert has_dataset("MODIS/061/MOD11A2") is True
    assert has_dataset("NOT/A/REAL/DATASET") is False


def test_dataset_ids_is_sorted_and_stable():
    ids = dataset_ids()
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids)), "duplicate dataset IDs in registry"


def test_get_datasets_matches_ids():
    assert [d.id for d in get_datasets()] == dataset_ids()


def test_find_by_role():
    primaries = find_by_role("primary")
    fallbacks = find_by_role("fallback")
    assert any(d.id == "MODIS/061/MOD16A2GF" for d in primaries)
    assert any(d.id == "MODIS/061/MOD16A2" for d in fallbacks)
    # The DEM pair: NASADEM primary, SRTM as the documented fallback.
    assert any(d.id == "NASA/NASADEM_HGT/001" for d in primaries)
    assert any(d.id == "USGS/SRTMGL1_003" for d in fallbacks)


# --------------------------------------------------------------------------
# Structural invariants across every dataset
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_every_dataset_has_required_metadata(dataset_id: str):
    spec = get_dataset(dataset_id)
    assert spec.id == dataset_id
    assert spec.name, f"{dataset_id} has no name"
    assert spec.name_fa, f"{dataset_id} is missing the Persian label"
    assert spec.provider, f"{dataset_id} has no provider"
    assert spec.description, f"{dataset_id} has no description"
    assert spec.spatial_resolution, f"{dataset_id} has no spatial resolution"
    assert spec.temporal_resolution, f"{dataset_id} has no temporal resolution"
    assert spec.available_from, f"{dataset_id} has no availability date"
    assert spec.citation, f"{dataset_id} has no citation"
    assert spec.docs_url, f"{dataset_id} has no documentation URL"


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_every_dataset_declares_bands(dataset_id: str):
    spec = get_dataset(dataset_id)
    assert spec.bands, f"{dataset_id} declares no bands"


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_every_band_has_unit_and_description(dataset_id: str):
    spec = get_dataset(dataset_id)
    for band_name, band in spec.bands.items():
        assert band_name == band.name, (
            f"{dataset_id}: dict key {band_name!r} disagrees with "
            f"BandSpec.name {band.name!r}"
        )
        assert band.unit, f"{dataset_id}.{band_name} has no unit"
        assert band.description, f"{dataset_id}.{band_name} has no description"


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_scale_factors_are_not_zero(dataset_id: str):
    """A zero scale factor would silently flatten every value to a constant."""
    spec = get_dataset(dataset_id)
    for band_name, band in spec.bands.items():
        if band.scale_factor is PENDING_VERIFICATION:
            continue
        assert band.scale_factor != 0, (
            f"{dataset_id}.{band_name} has a zero scale factor"
        )


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_valid_ranges_are_sane(dataset_id: str):
    spec = get_dataset(dataset_id)
    for band_name, band in spec.bands.items():
        if band.valid_range is None:
            continue
        low, high = band.valid_range
        assert low < high, (
            f"{dataset_id}.{band_name} has an inverted valid range {low}..{high}"
        )


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_modelled_sources_are_marked_modelled(dataset_id: str):
    """Reanalysis must never masquerade as a measurement."""
    spec = get_dataset(dataset_id)
    if "ECMWF" in dataset_id or "TERRACLIMATE" in dataset_id:
        assert spec.measurement_basis is MeasurementBasis.MODELLED


@pytest.mark.parametrize("dataset_id", dataset_ids())
def test_agency_products_are_marked_product(dataset_id: str):
    """Agency science products must be labelled as products, not measurements.

    Exception: MODIS LST is a direct radiometric retrieval of a physical
    quantity (skin temperature). It is a measurement reported in a product,
    so DIRECT is the more honest label there.
    """
    spec = get_dataset(dataset_id)
    if dataset_id.startswith("MODIS/061/MOD11"):
        assert spec.measurement_basis is MeasurementBasis.DIRECT
        return
    if dataset_id.startswith("MODIS/") or "WorldCereal" in dataset_id:
        assert spec.measurement_basis is MeasurementBasis.PRODUCT


# --------------------------------------------------------------------------
# Scale factors: the specific numbers that must be right
# --------------------------------------------------------------------------


def test_sentinel2_reflectance_scale_factor():
    """Sentinel-2 L2A reflectance is DN x 0.0001 with no offset."""
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert spec.bands["B4"].scale_factor == 0.0001
    assert spec.bands["B4"].offset == 0.0
    assert spec.bands["B8"].scale_factor == 0.0001
    assert spec.bands["B11"].scale_factor == 0.0001
    assert spec.bands["B4"].unit == "reflectance"


def test_sentinel2_scale_factor_produces_physical_values():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    red = spec.bands["B4"]
    # A raw DN of 2500 is a reflectance of 0.25, a realistic vegetated value.
    assert red.to_physical(2500) == pytest.approx(0.25)
    # Zero is a legitimate dark pixel, not a missing value, for reflectance.
    assert red.to_physical(0) == 0.0


def test_modis_lst_scale_factor_is_0_02_kelvin():
    """MODIS LST is DN x 0.02 in Kelvin, with no offset."""
    for dataset_id in ("MODIS/061/MOD11A2", "MODIS/061/MOD11A1"):
        spec = get_dataset(dataset_id)
        for band_name in ("LST_Day_1km", "LST_Night_1km"):
            band = spec.bands[band_name]
            assert band.scale_factor == 0.02, f"{dataset_id}.{band_name}"
            assert band.offset == 0.0
            assert band.unit == "K"


def test_modis_lst_zero_is_nodata():
    """LST uses 0 as its fill value, so 0 must convert to None, not to 0 K."""
    spec = get_dataset("MODIS/061/MOD11A2")
    band = spec.bands["LST_Day_1km"]
    assert band.to_physical(0) is None
    # A raw value of 15000 is 300 K, a plausible daytime surface temperature.
    assert band.to_physical(15000) == pytest.approx(300.0)


def test_landsat_surface_temperature_scale_and_offset():
    """Landsat C2 L2 ST_B10 is DN x 0.00341802 + 149.0 in Kelvin."""
    spec = get_dataset("LANDSAT/LC08/C02/T1_L2")
    band = spec.bands["ST_B10"]
    assert band.scale_factor == 0.00341802
    assert band.offset == 149.0
    assert band.unit == "K"
    # A raw DN of 44000 should land near 299.4 K, roughly 26 C.
    kelvin = band.to_physical(44000)
    assert kelvin is not None
    assert kelvin == pytest.approx(299.39, abs=0.05)


def test_landsat_reflectance_offset():
    """Landsat C2 L2 surface reflectance is DN x 2.75e-05 - 0.2."""
    spec = get_dataset("LANDSAT/LC08/C02/T1_L2")
    band = spec.bands["SR_B4"]
    assert band.scale_factor == pytest.approx(2.75e-05)
    assert band.offset == pytest.approx(-0.2)


def test_modis_lai_fpar_fcov_scale_factors():
    spec = get_dataset("MODIS/061/MCD15A3H")
    assert spec.bands["Lai"].scale_factor == 0.1
    assert spec.bands["Lai"].unit == "m2/m2"
    assert spec.bands["Fpar"].scale_factor == 0.01
    assert spec.bands["Fcov"].scale_factor == 0.01
    assert spec.bands["Fpar"].unit == "fraction"


def test_terraclimate_pet_scale_factor():
    spec = get_dataset("IDAHO_EPSCOR/TERRACLIMATE")
    assert spec.bands["pet"].scale_factor == 0.1
    assert spec.bands["pet"].unit == "mm"


def test_era5_temperature_is_kelvin_unscaled():
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR")
    for band_name in (
        "temperature_2m", "temperature_2m_min", "temperature_2m_max",
        "dewpoint_temperature_2m",
    ):
        band = spec.bands[band_name]
        assert band.scale_factor == 1.0
        assert band.unit == "K"


def test_era5_precipitation_is_metres():
    """ERA5 precipitation is in metres and must be scaled to mm by callers."""
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR")
    band = spec.bands["total_precipitation_sum"]
    assert band.unit == "m"
    assert band.scale_factor == 1.0


def test_era5_radiation_is_joules_per_square_metre():
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR")
    band = spec.bands["surface_solar_radiation_downwards_sum"]
    assert band.unit == "J/m2"


def test_smap_supersedes_deprecated_collection():
    """SPL4SMGP/007 is deprecated; the registry must reference /008."""
    assert has_dataset("NASA/SMAP/SPL4SMGP/008")
    assert not has_dataset("NASA/SMAP/SPL4SMGP/007")


def test_non_resolving_smap_collection_absent():
    """SPL2SMAP_S/001 does not resolve in the catalog, so it must not exist here."""
    assert not has_dataset("NASA/SMAP/SPL2SMAP_S/001")


def test_worldcereal_id_includes_version_suffix():
    assert has_dataset("ESA/WorldCereal/2021/MODELS/v100")


def test_mod16_band_names_are_correct():
    """Guards against the PF_ET / PF_PET naming error found during audit."""
    for dataset_id in ("MODIS/061/MOD16A2GF", "MODIS/061/MOD16A2"):
        spec = get_dataset(dataset_id)
        assert spec.has_band("ET")
        assert spec.has_band("PET")
        assert spec.has_band("LE")
        assert spec.has_band("PLE")
        assert not spec.has_band("PF_ET")
        assert not spec.has_band("PF_PET")


def test_mod16a2_starts_2021_and_gf_is_the_historical_product():
    """The fallback ordering depends on these dates being right."""
    gf = get_dataset("MODIS/061/MOD16A2GF")
    plain = get_dataset("MODIS/061/MOD16A2")
    assert gf.available_from == "2000-01-01"
    assert plain.available_from == "2021-01-01"
    assert "primary" in gf.roles
    assert "fallback" in plain.roles


# --------------------------------------------------------------------------
# Band lookup behaviour
# --------------------------------------------------------------------------


def test_band_lookup_unknown_raises_with_available_bands():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    with pytest.raises(KeyError) as exc:
        spec.band("B999")
    message = str(exc.value)
    assert "B999" in message
    assert "B8" in message  # the message lists what IS available


def test_has_band():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert spec.has_band("B8") is True
    assert spec.has_band("B999") is False


# --------------------------------------------------------------------------
# to_physical conversion guards
# --------------------------------------------------------------------------


def test_to_physical_handles_none_and_non_numeric():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    band = spec.bands["B4"]
    assert band.to_physical(None) is None
    assert band.to_physical("not a number") is None  # type: ignore[arg-type]


def test_to_physical_handles_nan_and_inf():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    band = spec.bands["B4"]
    assert band.to_physical(float("nan")) is None
    assert band.to_physical(float("inf")) is None


def test_to_physical_excludes_declared_nodata():
    """MODIS fill values must never be converted into real readings."""
    spec = get_dataset("MODIS/061/MCD15A3H")
    lai = spec.bands["Lai"]
    # 255 is the documented fill sentinel for LAI in this product.
    assert lai.to_physical(255) is None
    # A genuine LAI of 30 raw units is 3.0 m2/m2.
    assert lai.to_physical(30) == pytest.approx(3.0)


# --------------------------------------------------------------------------
# Sentinel-2 cloud masking configuration
# --------------------------------------------------------------------------


def test_sentinel2_declares_scl_cloud_mask():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert spec.cloud_mask_method == "scl"
    assert spec.cloud_mask_band == "SCL"
    assert spec.has_band("SCL")


def test_scl_invalid_classes_are_the_documented_ones():
    from app.services.agriculture.registry import S2_SCL_INVALID_CLASSES

    # 0 no data, 1 saturated/defective, 3 cloud shadow,
    # 8 cloud medium, 9 cloud high, 10 cirrus.
    assert set(S2_SCL_INVALID_CLASSES) == {0, 1, 3, 8, 9, 10}
    # Class 7 (cloud low probability) is deliberately retained.
    assert 7 not in S2_SCL_INVALID_CLASSES
    # Class 4 is vegetation: obviously not to be masked.
    assert 4 not in S2_SCL_INVALID_CLASSES


def test_sentinel2_advance_warning_caveats_present():
    """The engine must warn about the QA60 gap and the 2022 baseline shift."""
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    joined = " ".join(spec.caveats)
    assert "QA60" in joined
    assert "2022" in joined


def test_era5_evaporation_sign_convention_documented():
    """The sign convention is a documented caveat, not tacit knowledge."""
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR")
    joined = " ".join(spec.caveats)
    assert "negative" in joined.lower()
    # And the inferred (not verified) potential evaporation must be flagged.
    assert "inferred" in joined.lower() or "assumed" in joined.lower()


def test_mod11a2_carries_the_canopy_temperature_warning():
    """The single most important safety caveat in the thermal domain."""
    spec = get_dataset("MODIS/061/MOD11A2")
    joined = " ".join(spec.caveats).lower()
    assert "canopy temperature" in joined
    assert "not" in joined


def test_mod16_caveats_state_the_8_day_sum_semantics():
    spec = get_dataset("MODIS/061/MOD16A2GF")
    joined = " ".join(spec.caveats).lower()
    assert "8-day sum" in joined
    assert "mm/day" in joined


# --------------------------------------------------------------------------
# External (non-GEE) registry
# --------------------------------------------------------------------------


def test_external_registry_has_soilgrids():
    assert "ISRIC/SOILGRIDS/V2" in EXTERNAL_REGISTRY
    spec = get_external_dataset("ISRIC/SOILGRIDS/V2")
    assert spec.measurement_basis is MeasurementBasis.MODELLED
    assert "external" in spec.roles


def test_external_dataset_unverified_parameters_are_marked_pending():
    """No band may still carry an unverified conversion parameter.

    The SoilGrids d-factors were originally carried as pending during the
    ISRIC API outage. They have since been verified against ISRIC's
    official "SoilGrids layers" documentation, so the honest state is
    verified: every band now carries confirmed parameters and none may
    silently regress to the pending sentinel.
    """
    spec = get_external_dataset("ISRIC/SOILGRIDS/V2")
    pending = [
        name
        for name, band in spec.bands.items()
        if PENDING_VERIFICATION in (band.scale_factor, band.offset)
        or PENDING_VERIFICATION in band.nodata_values
    ]
    assert not pending, (
        f"SoilGrids bands still carry unverified parameters: {pending}. "
        "The factors were verified against ISRIC's official documentation; "
        "if a new band is added, verify its factor before registering it."
    )
    assert spec.is_verified


def test_external_registry_is_separate_from_gee_registry():
    for dataset_id in EXTERNAL_REGISTRY:
        assert dataset_id not in REGISTRY, (
            f"{dataset_id} appears in both registries; external sources "
            "must not be mixed into the Earth Engine registry"
        )


def test_soilgrids_depths_are_the_six_standard_intervals():
    from app.services.agriculture.registry import SOILGRIDS_DEPTHS

    assert SOILGRIDS_DEPTHS == (
        "0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm",
    )


def test_soilgrids_caveats_mention_the_service_outage():
    spec = get_external_dataset("ISRIC/SOILGRIDS/V2")
    joined = " ".join(spec.caveats).lower()
    assert "beta" in joined
    assert "paused" in joined or "no uptime guarantee" in joined


# --------------------------------------------------------------------------
# Temporal classification of the registry
# --------------------------------------------------------------------------
# The registry is where a dataset's temporal semantics are declared, so it
# is where the classification is asserted. NASADEM and SRTM are single
# 2000 acquisitions; SoilGrids is a modelled prediction with no time
# dimension. Each is static, each says so in its own description, and no
# other dataset is static without evidence.


def test_nasadem_is_declared_static():
    spec = get_dataset("NASA/NASADEM_HGT/001")
    assert spec.is_static is True
    assert spec.temporal_kind.value == "static"


def test_srtm_is_declared_static():
    spec = get_dataset("USGS/SRTMGL1_003")
    assert spec.is_static is True


def test_soilgrids_ee_is_declared_static():
    spec = get_dataset("ISRIC/SoilGrids250m/v2_0")
    assert spec.is_static is True


def test_soilgrids_external_is_declared_static():
    spec = get_external_dataset("ISRIC/SOILGRIDS/V2")
    assert spec.is_static is True


def test_sentinel2_remains_observation():
    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    assert spec.temporal_kind.value == "observation"


def test_era5_remains_observation():
    spec = get_dataset("ECMWF/ERA5_LAND/DAILY_AGGR")
    assert spec.temporal_kind.value == "observation"


def test_exactly_the_four_verified_static_datasets_are_static():
    """Pin the full list so a new STATIC entry is a reviewable event."""
    static_ids = sorted(
        dataset_id
        for dataset_id, spec in REGISTRY.items()
        if spec.is_static
    )
    assert static_ids == [
        "ISRIC/SoilGrids250m/v2_0",
        "NASA/NASADEM_HGT/001",
        "USGS/SRTMGL1_003",
    ]


def test_external_registry_static_list_is_pinned():
    static_ids = sorted(
        dataset_id
        for dataset_id, spec in EXTERNAL_REGISTRY.items()
        if spec.is_static
    )
    assert static_ids == ["ISRIC/SOILGRIDS/V2"]


def test_static_dem_dates_describe_acquisition_not_validity():
    """The dates must stay the true acquisition window, never widened.

    Widening them to fake validity would be a lie in the registry even if
    eligibility no longer depends on them.
    """
    for dataset_id in ("NASA/NASADEM_HGT/001", "USGS/SRTMGL1_003"):
        spec = get_dataset(dataset_id)
        assert spec.available_from == "2000-02-11"
        assert spec.available_to == "2000-02-22"


def test_every_static_spec_describes_itself_as_static():
    for dataset_id, spec in REGISTRY.items():
        if spec.is_static:
            assert "static" in spec.temporal_resolution.lower(), dataset_id


def test_static_datasets_declare_a_time_series_resolution_or_none():
    """A static dataset must not claim a revisit it does not have."""
    for dataset_id in ("NASA/NASADEM_HGT/001", "USGS/SRTMGL1_003"):
        spec = get_dataset(dataset_id)
        resolution = spec.temporal_resolution.lower()
        assert "static" in resolution, dataset_id


# --------------------------------------------------------------------------
# GLDAS-2.1: registered when the deferred Phase F metric was closed
# --------------------------------------------------------------------------

GLDAS_ID = "NASA/GLDAS/V021/NOAH/G025/T3H"


def test_gldas_is_registered_under_its_catalogue_id():
    assert has_dataset(GLDAS_ID)
    assert get_dataset(GLDAS_ID).id == GLDAS_ID


def test_gldas_root_zone_band_matches_the_catalogue():
    """Name and unit are quoted from the official catalogue entry."""
    band = get_dataset(GLDAS_ID).band("RootMoist_inst")
    assert band.name == "RootMoist_inst"
    assert band.unit == "kg/m2"
    assert "root zone" in band.description.lower()


def test_gldas_is_a_mass_per_unit_area_not_a_volume_fraction():
    """The registry must not label this product as an m3/m3 quantity.

    Presenting kg/m2 under an m3/m3 unit is the exact error that caused the
    metric to be deferred until the decision was recorded.
    """
    band = get_dataset(GLDAS_ID).band("RootMoist_inst")
    assert band.unit != "m3/m3"
    assert band.unit != "mm"


def test_gldas_pixel_size_and_cadence_are_the_verified_ones():
    spec = get_dataset(GLDAS_ID)
    assert "27830" in spec.spatial_resolution
    assert spec.temporal_resolution == "3 hourly"


def test_gldas_coverage_starts_in_2000():
    spec = get_dataset(GLDAS_ID)
    assert spec.available_from == "2000-01-01"
    assert spec.available_to is None


def test_gldas_is_an_observation_window_not_a_static_surface():
    """A pre-2000 request genuinely cannot be served from this product."""
    spec = get_dataset(GLDAS_ID)
    assert not spec.is_static, "GLDAS is a 3-hourly time series"


def test_gldas_is_marked_modelled():
    assert get_dataset(GLDAS_ID).measurement_basis is MeasurementBasis.MODELLED


def test_gldas_is_reported_as_verified():
    """Every registered parameter was confirmed against the catalogue."""
    assert get_dataset(GLDAS_ID).is_verified is True


def test_gldas_declares_no_validity_range_from_an_estimated_range():
    """The catalogue's range is flagged estimated, so it is not a filter."""
    band = get_dataset(GLDAS_ID).band("RootMoist_inst")
    assert band.valid_range is None


def test_gldas_citation_is_the_published_paper():
    citation = get_dataset(GLDAS_ID).citation
    assert "Rodell" in citation
    assert "Global Land Data Assimilation System" in citation


def test_gldas_docs_url_points_at_the_catalogue_entry():
    assert get_dataset(GLDAS_ID).docs_url.endswith(
        "NASA_GLDAS_V021_NOAH_G025_T3H"
    )


def test_gldas_caveats_state_that_it_assimilates_nothing():
    """Open-loop is the fact a caller is most likely to get wrong."""
    joined = " ".join(get_dataset(GLDAS_ID).caveats).lower()
    assert "open-loop" in joined
    assert "assimilates no soil moisture observations" in joined


def test_gldas_is_discoverable_by_its_role():
    assert any(d.id == GLDAS_ID for d in find_by_role("modelled_root_zone"))

