"""Central dataset registry for the Agricultural Intelligence Engine.

Every dataset used anywhere in this engine must be declared here, with
verified parameters. Nothing downstream may hardcode a dataset ID, band
name, scale factor, or unit.

Verification policy
-------------------
Each entry records what was confirmed and from where. Where a parameter
could not be confirmed against an official source it is marked
:data:`~app.services.agriculture.types.PENDING_VERIFICATION` and noted in
the dataset's ``caveats``. A plausible-looking guessed number is treated
as a bug, not a convenience.

Corrections applied during verification (these were wrong in the initial
audit and are fixed here):

* MOD16 ET bands are ``ET``/``PET``/``LE``/``PLE``. The names ``PF_ET``
  and ``PF_PET`` do not exist in the MODIS 061 collection.
* ``MODIS/061/MOD16A2GF`` covers 2000-01-01 onwards and IS the
  recommended historical product. ``MODIS/061/MOD16A2`` starts only at
  2021-01-01. The fallback chain is ordered accordingly.
* ``NASA/SMAP/SPL4SMGP/007`` is deprecated; ``/008`` is used instead.
* ``NASA/SMAP/SPL2SMAP_S/001`` does not resolve in the catalog and has
  been removed entirely.
* The WorldCereal ID requires the ``v100`` suffix.
* ERA5 ``total_evaporation_sum`` is negative for upward flux (verified).
  ``potential_evaporation_sum`` follows the same convention but this is
  inferred, not explicitly documented, and is flagged as such.

Corrections applied during Phase G verification (these were wrong in the
registry and are fixed here):

* ``ESA/WorldCereal/2021/MODELS/v100`` was described as a multi-class
  "Crop classification". It is a **binary mask**, values exactly 0 or
  100, published separately per product and season. It is not a crop-type
  classifier and cannot answer "which crop?".
* The same entry declared ``nodata_values=(255,)`` on both bands. The
  catalogue documents **no** fill or nodata value for either band, so an
  invented sentinel would have silently discarded real pixels. Removed.
* ``MODIS/061/MCD12Q1`` declared only ``LC_Type1`` and ``QC`` out of 13
  catalogue bands, and ``QC`` with unit ``class`` but no valid range. The
  full band set is now registered.
* ``MCD12Q1`` ``QC`` was described as "Classification quality", which
  invites an ordinal reading. Its ten values are post-processing event
  codes, not a quality ranking, and the caveat now says so.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.services.agriculture.types import (
    PENDING_VERIFICATION,
    BandSpec,
    DatasetSpec,
    MeasurementBasis,
    TemporalKind,
)

__all__ = [
    "REGISTRY",
    "get_dataset",
    "get_datasets",
    "has_dataset",
    "dataset_ids",
    "find_by_role",
    "S2_SCL_INVALID_CLASSES",
    "SOILGRIDS_WV_DEPTHS",
    "SOILGRIDS_WV_SUCTIONS",
]


# --------------------------------------------------------------------------
# SCL classes that indicate unusable pixels in Sentinel-2 L2A
# --------------------------------------------------------------------------
# 0  No data
# 1  Saturated or defective
# 3  Cloud shadows
# 8  Cloud medium probability
# 9  Cloud high probability
# 10 Thin cirrus
# (7 = cloud low probability is retained; it is commonly still usable.)
S2_SCL_INVALID_CLASSES: Tuple[int, ...] = (0, 1, 3, 8, 9, 10)


REGISTRY: Dict[str, DatasetSpec] = {}


def _register(spec: DatasetSpec) -> DatasetSpec:
    REGISTRY[spec.id] = spec
    return spec


# ==========================================================================
# OPTICAL — Sentinel-2
# ==========================================================================

_register(DatasetSpec(
    id="COPERNICUS/S2_SR_HARMONIZED",
    name="Sentinel-2 MSI Level-2A Surface Reflectance (Harmonized)",
    name_fa="سنتینل-۲ بازتاب سطحی",
    provider="ESA / Copernicus",
    description=(
        "Harmonized Sentinel-2 Level-2A surface reflectance. The "
        "harmonized collection removes the radiometric offset introduced "
        "by processing baseline 04.00, so time series remain consistent "
        "across the 2022-01-25 transition."
    ),
    spatial_resolution="10 m (B2,B3,B4,B8) / 20 m (B5,B8A,B11,B12,SCL) / 60 m (B1,B9,B10)",
    temporal_resolution="5 days (combined S2A + S2B revisit)",
    available_from="2017-03-28",
    available_to=None,
    measurement_basis=MeasurementBasis.DIRECT,
    cloud_mask_method="scl",
    cloud_mask_band="SCL",
    bands={
        "B2": BandSpec("B2", "Blue", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B3": BandSpec("B3", "Green", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B4": BandSpec("B4", "Red", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B5": BandSpec("B5", "Red Edge 1 (705 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B6": BandSpec("B6", "Red Edge 2 (740 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B7": BandSpec("B7", "Red Edge 3 (783 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B8": BandSpec("B8", "NIR (842 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B8A": BandSpec("B8A", "Narrow NIR (865 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B11": BandSpec("B11", "SWIR 1 (1610 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "B12": BandSpec("B12", "SWIR 2 (2190 nm)", "reflectance", 0.0001, 0.0, (0.0, 1.0)),
        "SCL": BandSpec("SCL", "Scene Classification Layer", "class", 1.0, 0.0, (0.0, 11.0), ()),
    },
    caveats=(
        "L2A coverage is not global before 2019; early scenes may be absent outside Europe.",
        "The QA60 cloud band is not populated from 2022-01-25 to 2024-02-28; SCL is the reliable mask for that window.",
        "SCL class 7 (cloud low probability) is retained by this engine; it may include thin cloud.",
        "A 20 m band and a 10 m band cannot be combined without an explicit resampling choice, which the engine records per metric.",
    ),
    citation="Copernicus Sentinel-2 MSI Level-2A, ESA",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED",
))


# ==========================================================================
# OPTICAL — Landsat 8/9 for finer thermal and long-term optical
# ==========================================================================

_register(DatasetSpec(
    id="LANDSAT/LC08/C02/T1_L2",
    name="Landsat 8 Collection 2 Level-2",
    name_fa="لندست ۸ سطح ۲",
    provider="USGS / NASA",
    description=(
        "Landsat 8 Collection 2 Level-2 surface reflectance and surface "
        "temperature, atmospherically corrected."
    ),
    spatial_resolution="30 m (optical) / 30 m resampled from 100 m (thermal)",
    temporal_resolution="16 days",
    available_from="2013-03-18",
    available_to=None,
    measurement_basis=MeasurementBasis.DIRECT,
    cloud_mask_method="qa_pixel",
    cloud_mask_band="QA_PIXEL",
    bands={
        "SR_B2": BandSpec("SR_B2", "Blue", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "SR_B3": BandSpec("SR_B3", "Green", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "SR_B4": BandSpec("SR_B4", "Red", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "SR_B5": BandSpec("SR_B5", "NIR", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "SR_B6": BandSpec("SR_B6", "SWIR 1", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "SR_B7": BandSpec("SR_B7", "SWIR 2", "reflectance", 2.75e-05, -0.2, (0.0, 1.0)),
        "ST_B10": BandSpec("ST_B10", "Surface temperature", "K", 0.00341802, 149.0, (150.0, 400.0), (0.0,)),
        "ST_QA": BandSpec("ST_QA", "Surface temperature quality", "K", 0.01, 0.0, None, ()),
        "QA_PIXEL": BandSpec("QA_PIXEL", "Pixel quality bitmask", "bitmask", 1.0, 0.0, None, ()),
    },
    caveats=(
        "ST_* bands are fully masked in scenes whose PROCESSING_LEVEL is L2SR.",
        "The thermal band is acquired at 100 m and resampled to 30 m; the true thermal resolution remains 100 m.",
        "Only Landsat 8 is registered; Landsat 9 (LC09) is not yet in this registry.",
    ),
    citation="USGS Landsat 8 Collection 2 Level-2, USGS/NASA",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/LANDSAT_LC08_C02_T1_L2",
))


# ==========================================================================
# RADAR — Sentinel-1 GRD (C-band SAR, log scaling)
# ==========================================================================

_register(DatasetSpec(
    id="COPERNICUS/S1_GRD",
    name="Sentinel-1 SAR GRD: C-band Ground Range Detected (log scaling)",
    name_fa="رادار سنتینل-۱ (GRD)",
    provider="ESA / Copernicus",
    description=(
        "Calibrated, ortho-corrected C-band (5.405 GHz) Synthetic "
        "Aperture Radar Ground Range Detected scenes in log scaling. "
        "Backscatter is stored in decibels. Only the bands this engine "
        "reads are registered; HH, HV and the incidence-angle band exist "
        "in the collection but are deliberately omitted so that a metric "
        "cannot silently read a band the registry does not declare."
    ),
    spatial_resolution="10 m (IW GRD)",
    temporal_resolution="12 days single satellite (6 days with two active)",
    available_from="2014-10-03",
    available_to=None,
    measurement_basis=MeasurementBasis.DIRECT,
    bands={
        "VV": BandSpec("VV", "Co-polarized backscatter, vertical transmit/vertical receive", "dB", 1.0, 0.0, (-50.0, 1.0)),
        "VH": BandSpec("VH", "Cross-polarized backscatter, vertical transmit/horizontal receive", "dB", 1.0, 0.0, (-50.0, 1.0)),
    },
    caveats=(
        "There is no cloud mask for SAR: C-band largely penetrates cloud, so no cloud-mask band or method is declared.",
        "This engine reads only Interferometric Wide Swath (IW) dual-polarization VV+VH descending-pass acquisitions; other modes, polarizations and passes are excluded by the metric filter for acquisition homogeneity.",
        "The constellation changed over the archive: Sentinel-1B was unavailable from December 2021 to the arrival of Sentinel-1C in December 2024, leaving a single-satellite 12-day revisit in between, and early-archive coverage is sparse.",
        "Incidence-angle variation between satellite tracks is not corrected; acquisitions share the orbit pass but may come from different relative orbits.",
        "Speckle is mitigated by temporal-mean compositing; single-scene backscatter is noisy and must not be read as a field condition.",
        "Backscatter mixes canopy structure, biomass, soil and roughness contributions; it is moisture-sensitive but is not a measurement of leaf water content.",
    ),
    citation="Sentinel-1 SAR GRD, ESA/Copernicus",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S1_GRD",
))


# ==========================================================================
# VEGETATION STRUCTURE — MODIS
# ==========================================================================

_register(DatasetSpec(
    id="MODIS/061/MCD15A3H",
    name="MODIS LAI/FPAR 4-Day Composite",
    name_fa="شاخص سطح برگ مودیس",
    provider="NASA LP DAAC",
    description=(
        "Leaf Area Index, Fraction of Photosynthetically Active Radiation "
        "absorbed, and Fraction of Vegetation Cover, 4-day composite."
    ),
    spatial_resolution="500 m",
    temporal_resolution="4 days",
    available_from="2002-07-04",
    available_to=None,
    measurement_basis=MeasurementBasis.PRODUCT,
    cloud_mask_band="FparLai_QC",
    bands={
        "Lai": BandSpec("Lai", "Leaf Area Index", "m2/m2", 0.1, 0.0, (0.0, 100.0), (249, 250, 251, 252, 253, 254, 255)),
        "Fpar": BandSpec("Fpar", "Fraction of absorbed PAR", "fraction", 0.01, 0.0, (0.0, 1.0), (249, 250, 251, 252, 253, 254, 255)),
        "Fcov": BandSpec("Fcov", "Fraction of vegetation cover", "fraction", 0.01, 0.0, (0.0, 1.0), (249, 250, 251, 252, 253, 254, 255)),
        "LaiStdDev": BandSpec("LaiStdDev", "LAI standard deviation", "m2/m2", 0.1, 0.0, None, (248, 249, 250, 251, 252, 253, 254, 255)),
        "FparStdDev": BandSpec("FparStdDev", "FPAR standard deviation", "fraction", 0.01, 0.0, None, (248, 249, 250, 251, 252, 253, 254, 255)),
        "FparLai_QC": BandSpec("FparLai_QC", "Quality control", "bitmask", 1.0, 0.0, None, (255,)),
    },
    caveats=(
        "500 m resolution cannot resolve within-field variability for typical smallholder plots.",
        "The retrieval algorithm assumes a biome look-up table; accuracy degrades for agricultural land.",
        "Values at the documented fill sentinels must be excluded, which this registry declares as nodata.",
    ),
    citation="MCD15A3H v061, NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD15A3H",
))


# ==========================================================================
# LAND COVER — MODIS
# ==========================================================================

_register(DatasetSpec(
    id="MODIS/061/MCD12Q1",
    name="MODIS Land Cover Type Yearly (IGBP)",
    name_fa="پوشش زمین مودیس",
    provider="NASA LP DAAC",
    description=(
        "Yearly global land cover classification at 500 m. Five "
        "independent classification schemes (IGBP, UMD, LAI, BGC, PFT), "
        "three FAO-LCCS continuous-field layers, a product QC band and a "
        "land/water mask."
    ),
    spatial_resolution="500 m",
    temporal_resolution="yearly",
    available_from="2001-01-01",
    available_to="2024-01-01",
    measurement_basis=MeasurementBasis.PRODUCT,
    bands={
        # -- classification schemes -------------------------------------
        "LC_Type1": BandSpec("LC_Type1", "IGBP land cover class", "class", 1.0, 0.0, (1.0, 17.0), ()),
        "LC_Type2": BandSpec("LC_Type2", "UMD land cover class", "class", 1.0, 0.0, (0.0, 15.0), ()),
        "LC_Type3": BandSpec("LC_Type3", "LAI/FPAR land cover class", "class", 1.0, 0.0, (0.0, 10.0), ()),
        "LC_Type4": BandSpec("LC_Type4", "BGC land cover class", "class", 1.0, 0.0, (0.0, 8.0), ()),
        "LC_Type5": BandSpec("LC_Type5", "Plant functional type class", "class", 1.0, 0.0, (0.0, 11.0), ()),
        # -- FAO-LCCS continuous fields --------------------------------
        "LC_Prop1": BandSpec("LC_Prop1", "LCCS1 land cover layer", "class", 1.0, 0.0, None, ()),
        "LC_Prop2": BandSpec("LC_Prop2", "LCCS2 land use layer", "class", 1.0, 0.0, None, ()),
        "LC_Prop3": BandSpec("LC_Prop3", "LCCS3 surface hydrology layer", "class", 1.0, 0.0, None, ()),
        "LC_Prop1_Assessment": BandSpec("LC_Prop1_Assessment", "LCCS1 layer confidence", "percent", 1.0, 0.0, (0.0, 100.0), ()),
        "LC_Prop2_Assessment": BandSpec("LC_Prop2_Assessment", "LCCS2 layer confidence", "percent", 1.0, 0.0, (0.0, 100.0), ()),
        "LC_Prop3_Assessment": BandSpec("LC_Prop3_Assessment", "LCCS3 layer confidence", "percent", 1.0, 0.0, (0.0, 100.0), ()),
        # -- quality and mask ------------------------------------------
        "QC": BandSpec("QC", "Product quality flags", "class", 1.0, 0.0, (0.0, 9.0), ()),
        "LW": BandSpec("LW", "Land (2) / water (1) mask from MOD44W", "class", 1.0, 0.0, (1.0, 2.0), ()),
    },
    caveats=(
        "LC_Type1 has no class 0; its values run 1 to 17 and Water Bodies is class 17.",
        "LC_Type2 and LC_Type3 do carry a class 0 meaning Water Bodies, so a class 0 is not universally invalid across this product.",
        "Each yearly image is a single classification for that year, not a composite over it.",
        "The product is published with roughly a one-year lag and stops at 2024-01-01 in this catalogue.",
        "QC is not a confidence score. Its ten values encode specific post-processing events such as water-mask disagreements and backfilled labels, and they are not ordered by quality.",
    ),
    citation="MCD12Q1 v061, NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD12Q1",
))

#: IGBP class values for LC_Type1, used for interpretation downstream.
#: Water Bodies is 17. There is deliberately no entry for 0.
MCD12Q1_IGBP_CLASSES: Dict[int, str] = {
    1: "Evergreen Needleleaf Forests",
    2: "Evergreen Broadleaf Forests",
    3: "Deciduous Needleleaf Forests",
    4: "Deciduous Broadleaf Forests",
    5: "Mixed Forests",
    6: "Closed Shrublands",
    7: "Open Shrublands",
    8: "Woody Savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent Wetlands",
    12: "Croplands",
    13: "Urban and Built-up Lands",
    14: "Cropland/Natural Vegetation Mosaics",
    15: "Permanent Snow and Ice",
    16: "Barren",
    17: "Water Bodies",
}

#: The two IGBP classes that contain cultivation, kept apart on purpose.
#:
#: Class 12 is dominated by cultivation (>60% cropland). Class 14 is a
#: mosaic where cultivation covers only 40-60% and the remainder is
#: natural vegetation. Summing them into one "cropland" figure would
#: overstate cultivated extent for class 14 pixels by a factor that
#: depends on the mosaic, and the product gives no sub-pixel breakdown to
#: correct it with. They are therefore reported separately and never
#: merged into a single fraction.
MCD12Q1_STRICT_CROPLAND_CLASS = 12
MCD12Q1_CROPLAND_MOSAIC_CLASS = 14
MCD12Q1_CROPLAND_CLASSES: Tuple[int, ...] = (
    MCD12Q1_STRICT_CROPLAND_CLASS,
    MCD12Q1_CROPLAND_MOSAIC_CLASS,
)

#: QC values for MCD12Q1. These are event codes, not a quality ranking.
MCD12Q1_QC_CLASSES: Dict[int, str] = {
    0: "Classified land",
    1: "Unclassified land (missing data, labelled barren)",
    2: "Classified water",
    3: "Unclassified water (missing data)",
    4: "Classified sea ice",
    5: "Misclassified water (switched to secondary label)",
    6: "Omitted snow/ice (relabelled as snow/ice)",
    7: "Misclassified snow/ice (relabelled as barren)",
    8: "Backfilled label (from pre-stabilised result)",
    9: "Forest type changed",
}

#: QC values that mean the label is not a straight classification of the
#: surface. USABLE_QC_VALUES were classified and agreed with the water
#: mask; the rest were altered by post-processing.
MCD12Q1_QC_PRIMARY_VALUES: Tuple[int, ...] = (0, 2)


# ==========================================================================
# LAND COVER — Dynamic World (10 m, with per-class probabilities)
# ==========================================================================

_register(DatasetSpec(
    id="GOOGLE/DYNAMICWORLD/V1",
    name="Dynamic World Near Real-Time Land Cover",
    name_fa="پوشش زمین پویا",
    provider="Google / World Resources Institute",
    description=(
        "Near real-time 10 m land cover with per-class probabilities "
        "derived from Sentinel-2."
    ),
    spatial_resolution="10 m",
    temporal_resolution="2 to 5 days",
    available_from="2015-06-27",
    available_to=None,
    measurement_basis=MeasurementBasis.PRODUCT,
    bands={
        "water": BandSpec("water", "Water probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "trees": BandSpec("trees", "Trees probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "grass": BandSpec("grass", "Grass probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "flooded_vegetation": BandSpec("flooded_vegetation", "Flooded vegetation probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "crops": BandSpec("crops", "Crops probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "shrub_and_scrub": BandSpec("shrub_and_scrub", "Shrub and scrub probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "built": BandSpec("built", "Built probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "bare": BandSpec("bare", "Bare ground probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "snow_and_ice": BandSpec("snow_and_ice", "Snow and ice probability", "probability", 1.0, 0.0, (0.0, 1.0), ()),
        "label": BandSpec("label", "Argmax class label", "class", 1.0, 0.0, (0.0, 8.0), ()),
    },
    caveats=(
        "Predictions exist only for Sentinel-2 L1C scenes with CLOUDY_PIXEL_PERCENTAGE <= 35.",
        "The argmax label can be confidently wrong when the top probability is low; consumers should threshold on the probability band, not the label.",
        "There is a known temporal offset between a Dynamic World image and its Sentinel-2 source scene.",
    ),
    citation="Dynamic World, Brown et al. 2022, Google/WRI",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1",
))

#: Dynamic World label values, in the documented probability band order.
DYNAMIC_WORLD_CLASSES: Dict[int, str] = {
    0: "water",
    1: "trees",
    2: "grass",
    3: "flooded_vegetation",
    4: "crops",
    5: "shrub_and_scrub",
    6: "built",
    7: "bare",
    8: "snow_and_ice",
}


# ==========================================================================
# CROP TYPE — ESA WorldCereal
# ==========================================================================

_register(DatasetSpec(
    id="ESA/WorldCereal/2021/MODELS/v100",
    name="ESA WorldCereal 10 m 2021 Products",
    name_fa="محصولات جهانی سرآلی ۲۰۲۱",
    provider="ESA WorldCereal",
    description=(
        "Global 10 m annual and seasonal crop and irrigation maps for the "
        "2021 reference year. Each image is a BINARY mask for one specific "
        "product and season, not a multi-class crop-type map."
    ),
    spatial_resolution="10 m",
    temporal_resolution="annual (single reference year 2021)",
    available_from="2020-01-01",
    available_to="2021-12-31",
    measurement_basis=MeasurementBasis.PRODUCT,
    bands={
        # Binary mask, not a class code. Values are exactly 0 or 100.
        "classification": BandSpec(
            "classification",
            "Binary product mask: 0 = not this product, 100 = this product",
            "class",
            1.0,
            0.0,
            (0.0, 100.0),
            (),
        ),
        "confidence": BandSpec(
            "confidence",
            "Classification confidence",
            "percent",
            1.0,
            0.0,
            (0.0, 100.0),
            (),
        ),
    },
    caveats=(
        "Each image is a BINARY mask, with values of exactly 0 or 100, for one product and one season. It is not a multi-class crop-type classification, and it cannot answer 'which crop is grown here?'.",
        "The available products are temporarycrops, maize, wintercereals, springcereals and irrigation. Cereals here means the Triticeae tribe: wheat, barley and rye.",
        "Images must be filtered by aez_id, product AND season. There are up to 106 agro-ecological zone images per product, each processed for its own regional seasonality, and they are independent products that must not be mixed.",
        "This product covers the single reference year 2021 and cannot describe any other season.",
        "Not every agro-ecological zone has an irrigation product. Zones without one were not processed because thermal Landsat data was unavailable there.",
        "Minimum mapping unit is around 0.5 hectares; smaller plots are unreliable.",
        "The catalogue documents no fill or nodata value for either band, so none is declared.",
    ),
    citation="ESA WorldCereal 2021, Van Tricht et al.",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCereal_2021_MODELS_v100",
))

#: WorldCereal product names, verified against the catalogue. Each is a
#: separate binary product; they are not classes within one layer.
WORLDCEREAL_PRODUCTS: Tuple[str, ...] = (
    "temporarycrops",
    "maize",
    "wintercereals",
    "springcereals",
    "irrigation",
)

#: WorldCereal seasons, verified against the catalogue.
WORLDCEREAL_SEASONS: Tuple[str, ...] = (
    "tc-annual",
    "tc-wintercereals",
    "tc-springcereals",
    "tc-maize-main",
    "tc-maize-second",
)

#: The two values a WorldCereal classification band can hold.
WORLDCEREAL_BINARY_VALUES: Tuple[int, ...] = (0, 100)


# ==========================================================================
# CLIMATE — ERA5-Land
# ==========================================================================

_register(DatasetSpec(
    id="ECMWF/ERA5_LAND/DAILY_AGGR",
    name="ERA5-Land Daily Aggregated",
    name_fa="ERA5-Land روزانه",
    provider="ECMWF / Copernicus Climate Change Service",
    description=(
        "Daily aggregated reanalysis of land surface variables at 0.1 "
        "degree resolution."
    ),
    spatial_resolution="11132 m (0.1 degree)",
    temporal_resolution="daily",
    available_from="1950-01-02",
    available_to=None,
    measurement_basis=MeasurementBasis.MODELLED,
    bands={
        "total_precipitation_sum": BandSpec(
            "total_precipitation_sum", "Total precipitation", "m", 1.0, 0.0, (0.0, 1.0), ()),
        "temperature_2m": BandSpec(
            "temperature_2m", "Air temperature at 2 m", "K", 1.0, 0.0, (150.0, 350.0), ()),
        "temperature_2m_min": BandSpec(
            "temperature_2m_min", "Minimum air temperature at 2 m", "K", 1.0, 0.0, (150.0, 350.0), ()),
        "temperature_2m_max": BandSpec(
            "temperature_2m_max", "Maximum air temperature at 2 m", "K", 1.0, 0.0, (150.0, 350.0), ()),
        "dewpoint_temperature_2m": BandSpec(
            "dewpoint_temperature_2m", "Dewpoint temperature at 2 m", "K", 1.0, 0.0, (150.0, 350.0), ()),
        "surface_solar_radiation_downwards_sum": BandSpec(
            "surface_solar_radiation_downwards_sum", "Surface solar radiation downwards", "J/m2", 1.0, 0.0, (0.0, 6.0e7), ()),
        "u_component_of_wind_10m": BandSpec(
            "u_component_of_wind_10m", "Eastward wind at 10 m", "m/s", 1.0, 0.0, (-50.0, 50.0), ()),
        "v_component_of_wind_10m": BandSpec(
            "v_component_of_wind_10m", "Northward wind at 10 m", "m/s", 1.0, 0.0, (-50.0, 50.0), ()),
        "potential_evaporation_sum": BandSpec(
            "potential_evaporation_sum", "Potential evaporation", "m", 1.0, 0.0, (-1.0, 0.0), ()),
        "total_evaporation_sum": BandSpec(
            "total_evaporation_sum", "Total evaporation", "m water equivalent", 1.0, 0.0, (-1.0, 0.0), ()),
        "volumetric_soil_water_layer_1": BandSpec(
            "volumetric_soil_water_layer_1", "Volumetric soil water, layer 1 (0-7 cm)", "m3/m3", 1.0, 0.0, (0.0, 1.0), ()),
        "volumetric_soil_water_layer_2": BandSpec(
            "volumetric_soil_water_layer_2", "Volumetric soil water, layer 2 (7-28 cm)", "m3/m3", 1.0, 0.0, (0.0, 1.0), ()),
        # Layers 3 and 4 complete the ECMWF soil column. Layer 3 (28-100 cm)
        # is the deeper half of the 0-100 cm root zone; layer 4 (100-289 cm)
        # lies below almost all crop roots and is declared for completeness
        # so a depth-weighted integration can be expressed explicitly.
        "volumetric_soil_water_layer_3": BandSpec(
            "volumetric_soil_water_layer_3", "Volumetric soil water, layer 3 (28-100 cm)", "m3/m3", 1.0, 0.0, (0.0, 1.0), ()),
        "volumetric_soil_water_layer_4": BandSpec(
            "volumetric_soil_water_layer_4", "Volumetric soil water, layer 4 (100-289 cm)", "m3/m3", 1.0, 0.0, (0.0, 1.0), ()),
        "soil_temperature_level_1": BandSpec(
            "soil_temperature_level_1", "Soil temperature, level 1 (0-7 cm)", "K", 1.0, 0.0, (150.0, 350.0), ()),
        "soil_temperature_level_2": BandSpec(
            "soil_temperature_level_2", "Soil temperature, level 2 (7-28 cm)", "K", 1.0, 0.0, (150.0, 350.0), ()),
    },
    caveats=(
        "This is a reanalysis product, not a measurement. It is a model field constrained by observations.",
        "At 0.1 degree (about 11 km) it cannot represent within-field conditions; it is only defensible as a regional context layer.",
        "VERIFIED: total_evaporation_sum is negative for upward flux (evaporation), positive for condensation, following the ECMWF convention where downward fluxes are positive.",
        "INFERRED, NOT EXPLICITLY DOCUMENTED: potential_evaporation_sum is assumed to follow the same downward-positive convention. The catalog page does not state this for the band. The engine treats it as negated evaporation but records the assumption.",
        "The _sum suffixed bands are daily accumulated totals, not instantaneous hourly snapshots.",
        "Three ET component bands in the source have swapped values; do not decompose ET from this dataset without accounting for that.",
    ),
    citation="ERA5-Land daily aggregated, Munoz-Sabater et al. 2021, ECMWF/C3S",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR",
))


# ==========================================================================
# CLIMATE — TerraClimate (long, stable monthly record)
# ==========================================================================

_register(DatasetSpec(
    id="IDAHO_EPSCOR/TERRACLIMATE",
    name="TerraClimate Monthly Climate and Water Balance",
    name_fa="تراکلیمیت ماهانه",
    provider="University of Idaho / Climatology Lab",
    description=(
        "Monthly climate and climatic water balance at 1/24 degree, "
        "spanning 1958 to present."
    ),
    spatial_resolution="4638.3 m (1/24 degree)",
    temporal_resolution="monthly",
    available_from="1958-01-01",
    available_to=None,
    measurement_basis=MeasurementBasis.MODELLED,
    bands={
        # Valid ranges are the catalogue's own min/max multiplied by the
        # band's declared scale factor, so they bound the PHYSICAL value
        # rather than the stored integer. The catalogue marks these as
        # estimated, which is why they are wide.
        "pet": BandSpec("pet", "Reference evapotranspiration (ASCE Penman-Monteith)", "mm", 0.1, 0.0, (0.0, 454.8), ()),
        "aet": BandSpec("aet", "Actual evapotranspiration", "mm", 0.1, 0.0, (0.0, 314.0), ()),
        "soil": BandSpec("soil", "Soil moisture", "mm", 0.1, 0.0, (0.0, 888.2), ()),
        "def": BandSpec("def", "Climatic water deficit", "mm", 0.1, 0.0, (0.0, 454.8), ()),
        "pdsi": BandSpec("pdsi", "Palmer Drought Severity Index", "index", 0.01, 0.0, (-43.17, 34.18), ()),
        "pr": BandSpec("pr", "Precipitation accumulation", "mm", 0.1, 0.0, (0.0, 724.5), ()),
        "ro": BandSpec("ro", "Runoff", "mm", 0.1, 0.0, (0.0, 1256.0), ()),
        "swe": BandSpec("swe", "Snow water equivalent", "mm", 1.0, 0.0, (0.0, 32767.0), ()),
        "srad": BandSpec("srad", "Downward surface shortwave radiation", "W/m2", 0.1, 0.0, (0.0, 547.7), ()),
        "tmmn": BandSpec("tmmn", "Minimum temperature", "degC", 0.1, 0.0, (-77.0, 38.7), ()),
        "tmmx": BandSpec("tmmx", "Maximum temperature", "degC", 0.1, 0.0, (-67.0, 57.6), ()),
        "vap": BandSpec("vap", "Vapor pressure", "kPa", 0.001, 0.0, (0.0, 14.749), ()),
        "vpd": BandSpec("vpd", "Vapor pressure deficit", "kPa", 0.01, 0.0, (0.0, 11.13), ()),
        "vs": BandSpec("vs", "Wind speed at 10 m", "m/s", 0.01, 0.0, (0.0, 29.23), ()),
    },
    caveats=(
        "The water balance model is deliberately simple and does not represent vegetation-type heterogeneity.",
        "Long-term trends in this product are inherited from parent datasets and must not be used for independent trend assessment.",
        "The monthly cadence is too coarse for within-season crop monitoring.",
        "pet is REFERENCE evapotranspiration computed with the ASCE Penman-Monteith method. It is not the same quantity as MOD16 potential evapotranspiration, which is not reference ET. The two must not be substituted for one another.",
        "soil is a depth-integrated water balance state in millimetres of water, not a volumetric water content. It cannot be compared with a m3/m3 product without knowing the soil column depth and porosity.",
    ),
    citation="TerraClimate, Abatzoglou et al. 2018",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/IDAHO_EPSCOR_TERRACLIMATE",
))


# ==========================================================================
# EVAPOTRANSPIRATION — MODIS MOD16
# ==========================================================================

_register(DatasetSpec(
    id="MODIS/061/MOD16A2GF",
    name="MODIS Evapotranspiration Gap-Filled (8-day)",
    name_fa="تبخیر-تعرق مودیس (پر شده)",
    provider="NASA LP DAAC",
    description=(
        "Gap-filled 8-day evapotranspiration, latent heat flux and "
        "potential evapotranspiration. This is the recommended product "
        "for historical records."
    ),
    spatial_resolution="500 m",
    temporal_resolution="8 days",
    available_from="2000-01-01",
    available_to=None,
    measurement_basis=MeasurementBasis.PRODUCT,
    cloud_mask_band="ET_QC",
    roles=("primary",),
    bands={
        "ET": BandSpec("ET", "Evapotranspiration, 8-day sum", "kg/m2/8day", 0.1, 0.0, (0.0, 100.0), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "PET": BandSpec("PET", "Potential evapotranspiration, 8-day sum", "kg/m2/8day", 0.1, 0.0, (0.0, 100.0), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "LE": BandSpec("LE", "Latent heat flux, 8-day average", "J/m2/day", 10000.0, 0.0, (0.0, 1.0e9), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "PLE": BandSpec("PLE", "Potential latent heat flux, 8-day average", "J/m2/day", 10000.0, 0.0, (0.0, 1.0e9), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "ET_QC": BandSpec("ET_QC", "Quality control", "bitmask", 1.0, 0.0, None, ()),
    },
    caveats=(
        "ET and PET values are 8-day sums, not daily rates. Divide by the number of days in the period to obtain mm/day.",
        "LE and PLE are 8-day averages, so they must NOT be divided by the period length.",
        "Fill values 32761 to 32767 may hold inaccurate data and are excluded by the nodata declaration.",
        "The MOD16 algorithm performs poorly over sparse vegetation and arid surfaces, which includes much of Iran.",
    ),
    citation="MOD16A2GF v061, Running et al., NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD16A2GF",
))

_register(DatasetSpec(
    id="MODIS/061/MOD16A2",
    name="MODIS Evapotranspiration (8-day, near real-time)",
    name_fa="تبخیر-تعرق مودیس (نزدیک به زمان واقعی)",
    provider="NASA LP DAAC",
    description=(
        "Non gap-filled 8-day evapotranspiration. Only available from "
        "2021 onward; use MOD16A2GF for earlier periods."
    ),
    spatial_resolution="500 m",
    temporal_resolution="8 days",
    available_from="2021-01-01",
    available_to=None,
    measurement_basis=MeasurementBasis.PRODUCT,
    cloud_mask_band="ET_QC",
    roles=("fallback", "recent"),
    bands={
        "ET": BandSpec("ET", "Evapotranspiration, 8-day sum", "kg/m2/8day", 0.1, 0.0, (0.0, 100.0), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "PET": BandSpec("PET", "Potential evapotranspiration, 8-day sum", "kg/m2/8day", 0.1, 0.0, (0.0, 100.0), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "LE": BandSpec("LE", "Latent heat flux, 8-day average", "J/m2/day", 10000.0, 0.0, (0.0, 1.0e9), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "PLE": BandSpec("PLE", "Potential latent heat flux, 8-day average", "J/m2/day", 10000.0, 0.0, (0.0, 1.0e9), (32761, 32762, 32763, 32764, 32765, 32766, 32767)),
        "ET_QC": BandSpec("ET_QC", "Quality control", "bitmask", 1.0, 0.0, None, ()),
    },
    caveats=(
        "There is NO data before 2021-01-01 in this product. Requests for earlier dates must fall back to MOD16A2GF.",
        "Not gap-filled, so gaps are expected and reduce valid pixel coverage.",
        "The gap-filled product lags roughly one year, which is why this near real-time product exists.",
    ),
    citation="MOD16A2 v061, Running et al., NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD16A2",
))


# ==========================================================================
# THERMAL — MODIS Land Surface Temperature
# ==========================================================================

_register(DatasetSpec(
    id="MODIS/061/MOD11A2",
    name="MODIS Land Surface Temperature 8-Day",
    name_fa="دمای سطح زمین مودیس (۸ روزه)",
    provider="NASA LP DAAC",
    description=(
        "8-day composite land surface temperature from MODIS Terra."
    ),
    spatial_resolution="1000 m",
    temporal_resolution="8 days",
    available_from="2000-02-18",
    available_to=None,
    measurement_basis=MeasurementBasis.DIRECT,
    cloud_mask_band="QC_Day",
    roles=("primary",),
    bands={
        "LST_Day_1km": BandSpec("LST_Day_1km", "Daytime land surface temperature", "K", 0.02, 0.0, (150.0, 400.0), (0.0,)),
        "LST_Night_1km": BandSpec("LST_Night_1km", "Nighttime land surface temperature", "K", 0.02, 0.0, (150.0, 400.0), (0.0,)),
        "QC_Day": BandSpec("QC_Day", "Daytime quality control", "bitmask", 1.0, 0.0, None, ()),
        "QC_Night": BandSpec("QC_Night", "Nighttime quality control", "bitmask", 1.0, 0.0, None, ()),
    },
    caveats=(
        "This is LAND SURFACE TEMPERATURE, the radiometric skin temperature. It is not canopy temperature and must never be labelled as such.",
        "Over partially vegetated pixels the signal mixes soil and vegetation, biasing the estimate away from canopy conditions.",
        "The 8-day composite is a simple mean of all daily values with no QA filtering applied; the reported QC is a majority vote of the inputs.",
        "The final composite period of each year spans only 5 to 6 days.",
    ),
    citation="MOD11A2 v061, Wan et al., NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD11A2",
))

_register(DatasetSpec(
    id="MODIS/061/MOD11A1",
    name="MODIS Land Surface Temperature Daily",
    name_fa="دمای سطح زمین مودیس (روزانه)",
    provider="NASA LP DAAC",
    description="Daily land surface temperature from MODIS Terra.",
    spatial_resolution="1000 m",
    temporal_resolution="daily",
    available_from="2000-02-18",
    available_to=None,
    measurement_basis=MeasurementBasis.DIRECT,
    cloud_mask_band="QC_Day",
    roles=("fallback", "daily"),
    bands={
        "LST_Day_1km": BandSpec("LST_Day_1km", "Daytime land surface temperature", "K", 0.02, 0.0, (150.0, 400.0), (0.0,)),
        "LST_Night_1km": BandSpec("LST_Night_1km", "Nighttime land surface temperature", "K", 0.02, 0.0, (150.0, 400.0), (0.0,)),
        "QC_Day": BandSpec("QC_Day", "Daytime quality control", "bitmask", 1.0, 0.0, None, ()),
        "QC_Night": BandSpec("QC_Night", "Nighttime quality control", "bitmask", 1.0, 0.0, None, ()),
    },
    caveats=(
        "Same land surface temperature caveats as MOD11A2 apply.",
        "Daily retrievals are far more affected by cloud than the 8-day composite, producing lower valid coverage.",
    ),
    citation="MOD11A1 v061, Wan et al., NASA LP DAAC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD11A1",
))


# ==========================================================================
# SOIL MOISTURE — SMAP
# ==========================================================================

_register(DatasetSpec(
    id="NASA/SMAP/SPL3SMP_E/006",
    name="SMAP L3 Radiometer Global Daily 9 km Soil Moisture",
    name_fa="رطوبت خاک SMAP سطح ۳ (روزانه)",
    provider="NASA NSIDC",
    description=(
        "Daily composite of global land surface soil moisture retrieved by "
        "the SMAP L-band radiometer. This is a RETRIEVAL from brightness "
        "temperature, not a land surface model output."
    ),
    spatial_resolution="9000 m (9 km, EASE-Grid 2.0)",
    temporal_resolution="daily",
    available_from="2023-12-04",
    available_to=None,
    measurement_basis=MeasurementBasis.PRODUCT,
    roles=("primary",),
    bands={
        # The catalogue gives no numeric min/max for the soil moisture
        # bands; the physical bound is set to 0.6 m3/m3, above the
        # porosity of any mineral soil, so that a retrieval is never
        # rejected for being "too wet".
        "soil_moisture_am": BandSpec(
            "soil_moisture_am",
            "Retrieved soil moisture, AM overpass (descending)",
            "m3/m3", 1.0, 0.0, (0.0, 0.6), ()),
        "soil_moisture_pm": BandSpec(
            "soil_moisture_pm",
            "Retrieved soil moisture, PM overpass (ascending)",
            "m3/m3", 1.0, 0.0, (0.0, 0.6), ()),
        "retrieval_qual_flag_am": BandSpec(
            "retrieval_qual_flag_am",
            "Retrieval quality flag, AM overpass",
            "bitmask", 1.0, 0.0, None, ()),
        "retrieval_qual_flag_pm": BandSpec(
            "retrieval_qual_flag_pm",
            "Retrieval quality flag, PM overpass",
            "bitmask", 1.0, 0.0, None, ()),
        "vegetation_water_content_am": BandSpec(
            "vegetation_water_content_am",
            "Vegetation water content, AM overpass",
            "kg/m2", 1.0, 0.0, (0.0, 30.0), ()),
        "vegetation_water_content_pm": BandSpec(
            "vegetation_water_content_pm",
            "Vegetation water content, PM overpass",
            "kg/m2", 1.0, 0.0, (0.0, 30.0), ()),
    },
    caveats=(
        "This collection holds data from 2023-12-04 onward. Earlier dates live in NASA/SMAP/SPL3SMP_E/005 and are NOT covered by this entry.",
        "The AM overpass is the descending pass at about 06:00 local solar time; the PM overpass is the ascending pass at about 18:00. They are two different retrievals of the same day and must not be averaged into one number without saying so, because surface soil moisture has a strong diurnal cycle.",
        "The retrieval is only valid over thawed, unfrozen ground. Frozen ground retrievals are flagged and should not be read as soil moisture.",
        "At 9 km a single pixel is far larger than a typical field. This is a regional context layer, not a within-field measurement.",
        "Retrieval quality is reported per pixel in the quality flag bands; the engine filters on them rather than reading the flag as a value.",
        "VERIFIED against the NSIDC help centre: in retrieval_qual_flag, bit 0 = 0 means recommended quality and bit 0 = 1 means uncertain quality; bit 1 = 1 means the retrieval was SKIPPED and the corresponding soil moisture value is not a retrieval at all. A value is only usable when bit 0 = 0 AND bit 1 = 0.",
    ),
    citation="SMAP Enhanced L3 Radiometer v006, O'Neill et al., NASA NSIDC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL3SMP_E_006",
))

_register(DatasetSpec(
    id="NASA/SMAP/SPL3SMP_E/005",
    name="SMAP L3 Radiometer Global Daily 9 km Soil Moisture (v005)",
    name_fa="رطوبت خاک SMAP سطح ۳ نسخه ۵",
    provider="NASA NSIDC",
    description=(
        "Older version of the SMAP L3 daily 9 km soil moisture retrieval, "
        "covering dates before 2023-12-04."
    ),
    spatial_resolution="9000 m (9 km, EASE-Grid 2.0)",
    temporal_resolution="daily",
    available_from="2015-03-31",
    available_to="2023-12-03",
    measurement_basis=MeasurementBasis.PRODUCT,
    roles=("fallback", "historical"),
    bands={
        "soil_moisture_am": BandSpec(
            "soil_moisture_am",
            "Retrieved soil moisture, AM overpass (descending)",
            "m3/m3", 1.0, 0.0, (0.0, 0.6), ()),
        "soil_moisture_pm": BandSpec(
            "soil_moisture_pm",
            "Retrieved soil moisture, PM overpass (ascending)",
            "m3/m3", 1.0, 0.0, (0.0, 0.6), ()),
        "retrieval_qual_flag_am": BandSpec(
            "retrieval_qual_flag_am",
            "Retrieval quality flag, AM overpass",
            "bitmask", 1.0, 0.0, None, ()),
        "retrieval_qual_flag_pm": BandSpec(
            "retrieval_qual_flag_pm",
            "Retrieval quality flag, PM overpass",
            "bitmask", 1.0, 0.0, None, ()),
        "vegetation_water_content_am": BandSpec(
            "vegetation_water_content_am",
            "Vegetation water content, AM overpass",
            "kg/m2", 1.0, 0.0, (0.0, 30.0), ()),
        "vegetation_water_content_pm": BandSpec(
            "vegetation_water_content_pm",
            "Vegetation water content, PM overpass",
            "kg/m2", 1.0, 0.0, (0.0, 30.0), ()),
    },
    caveats=(
        "Superseded by NASA/SMAP/SPL3SMP_E/006 for dates from 2023-12-04 onward. NASA plans to reprocess these dates into the newer collection.",
        "Same retrieval caveats as the v006 collection apply, including the requirement for thawed ground and the 9 km footprint.",
    ),
    citation="SMAP Enhanced L3 Radiometer v005, O'Neill et al., NASA NSIDC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL3SMP_E_005",
))


# ==========================================================================
# SOIL MOISTURE — SMAP L4 (assimilated model)
# ==========================================================================

_register(DatasetSpec(
    id="NASA/SMAP/SPL4SMGP/008",
    name="SMAP Level-4 Surface and Root Zone Soil Moisture",
    name_fa="رطوبت خاک SMAP سطح ۴",
    provider="NASA NSIDC",
    description=(
        "Surface (0-5 cm) and root zone (0-100 cm) soil moisture from the "
        "SMAP L4 geophysical model with brightness temperature "
        "assimilation."
    ),
    spatial_resolution="11000 m (9 km EASE-Grid 2.0, delivered on an 11 km pixel)",
    temporal_resolution="3 hourly",
    available_from="2015-03-31",
    available_to=None,
    measurement_basis=MeasurementBasis.MODELLED,
    roles=("assimilated_model",),
    bands={
        # The catalogue states the maximum as 0.9 volume fraction, which
        # is the saturation porosity the land model allows. Declaring 1.0
        # would silently admit physically impossible values.
        "sm_surface": BandSpec(
            "sm_surface", "Surface soil moisture, 0-5 cm", "m3/m3",
            1.0, 0.0, (0.0, 0.9), ()),
        "sm_rootzone": BandSpec(
            "sm_rootzone", "Root zone soil moisture, 0-100 cm", "m3/m3",
            1.0, 0.0, (0.0, 0.9), ()),
        "sm_profile": BandSpec(
            "sm_profile", "Profile soil moisture, 0 cm to model bedrock depth",
            "m3/m3", 1.0, 0.0, (0.0, 0.9), ()),
        # Wetness bands are dimensionless relative saturation between the
        # driest and wettest state the model admits. They are NOT volume
        # fractions and must never be averaged with one.
        "sm_surface_wetness": BandSpec(
            "sm_surface_wetness",
            "Surface relative saturation (wetness), 0-5 cm",
            "fraction", 1.0, 0.0, (0.0, 1.0), ()),
        "sm_rootzone_wetness": BandSpec(
            "sm_rootzone_wetness",
            "Root zone relative saturation (wetness), 0-100 cm",
            "fraction", 1.0, 0.0, (0.0, 1.0), ()),
        "sm_profile_wetness": BandSpec(
            "sm_profile_wetness",
            "Profile relative saturation (wetness)",
            "fraction", 1.0, 0.0, (0.0, 1.0), ()),
    },
    caveats=(
        "At 9 km this cannot describe field-scale soil moisture. It is a regional context layer only.",
        "During instrument outages the values are pure land model output with no assimilation. Documented outages include 2019-06-19 to 2019-07-23 and 2022-08-06 to 2022-09-20.",
        "The 9 km product supersedes the earlier /007 collection, which is deprecated.",
        "This is an ASSIMILATED MODEL product, not a direct retrieval. It is not interchangeable with the L3 radiometer retrieval for the same day.",
        "The wetness bands are dimensionless relative saturation, not volume fractions, and are on a different scale from the soil moisture bands.",
    ),
    citation="SMAP L4 SPL4SMGP v008, NASA NSIDC",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL4SMGP_008",
))


# ==========================================================================
# SOIL MOISTURE — GLDAS-2.1 Noah (open-loop land surface model)
# ==========================================================================
#
# Registered when the deferred ``root_zone_soil_moisture_gldas`` metric was
# closed. Every parameter below was verified against the official Earth
# Engine catalogue entry and its STAC record:
#
#   https://developers.google.com/earth-engine/datasets/catalog/NASA_GLDAS_V021_NOAH_G025_T3H
#   https://storage.googleapis.com/earthengine-stac/catalog/NASA/NASA_GLDAS_V021_NOAH_G025_T3H.json
#
# Confirmed: cadence 3 hours, pixel size 27830 m, availability from
# 2000-01-01T03:00:00Z, band ``RootMoist_inst`` described as "Root zone
# soil moisture" with units ``kg/m^2``, and an explicit statement that
# GLDAS-2.1 is OPEN-LOOP, i.e. it assimilates no observations.

_register(DatasetSpec(
    id="NASA/GLDAS/V021/NOAH/G025/T3H",
    name="GLDAS-2.1 Noah land surface model",
    name_fa="مدل سطح زمین GLDAS-2.1 (نوح)",
    provider="NASA GES DISC at NASA Goddard Space Flight Center",
    description=(
        "Global Land Data Assimilation System version 2.1: the Noah land "
        "surface model run open-loop on a 0.25 degree grid, forced with "
        "GDAS atmospheric analyses, disaggregated GPCP precipitation and "
        "AGRMET radiation. Root zone soil moisture is published as a water "
        "mass per unit area in kg/m2."
    ),
    spatial_resolution="27830 m (0.25 degree global grid)",
    temporal_resolution="3 hourly",
    available_from="2000-01-01",
    available_to=None,
    measurement_basis=MeasurementBasis.MODELLED,
    roles=("modelled_root_zone",),
    bands={
        # Unit is a MASS PER UNIT AREA, not a volume fraction. The
        # catalogue documents no validity range for this band, only an
        # estimated one (2 to 949.6 kg/m2, flagged as estimated), which is
        # deliberately not used as a filter — see the caveats.
        "RootMoist_inst": BandSpec(
            "RootMoist_inst",
            "Root zone soil moisture, as a water mass per unit area",
            "kg/m2", 1.0, 0.0, None, ()),
    },
    caveats=(
        "GLDAS-2.1 is an OPEN-LOOP simulation: it assimilates no soil moisture observations at all. It is a land surface model driven by observation-based meteorology, so it is neither a measurement nor a data-assimilation product.",
        "The value is a water MASS PER UNIT AREA (kg/m2). Converting it to a volume fraction (m3/m3) requires the thickness of the layer and the density of water, and the catalogue does not document the depth interval that the root zone band covers, so no conversion is performed anywhere in this engine.",
        "The catalogue publishes only an ESTIMATED range for this band (2 to 949.6 kg/m2, flagged 'estimated'). It is therefore not used as a validity filter, because a genuine near-zero value would be wrongly rejected by the lower bound.",
        "At 27 830 m per pixel the value describes a region of hundreds of kilometres. It cannot describe a field, and it cannot represent irrigation, which this model does not simulate at that scale.",
        "Not comparable with SMAP L3, SMAP L4 or ERA5-Land soil moisture, all of which report a volume fraction. Placing them side by side without an explicit, documented conversion compares two different quantities.",
        "The soil moisture profile layers (SoilMoi0_10cm_inst, SoilMoi10_40cm_inst, SoilMoi40_100cm_inst, SoilMoi100_200cm_inst, all in kg/m2) exist in the same asset and are not declared here because no metric reads them.",
    ),
    citation=(
        "Rodell, M., P.R. Houser, U. Jambor, J. Gottschalck, K. Mitchell, "
        "C.-J. Meng, K. Arsenault, B. Cosgrove, J. Radakovich, M. "
        "Bosilovich, J.K. Entin, J.P. Walker, D. Lohmann and D. Toll, "
        "The Global Land Data Assimilation System, Bulletin of the "
        "American Meteorological Society, 85(3), 381-394, 2004"
    ),
    docs_url=(
        "https://developers.google.com/earth-engine/datasets/catalog/"
        "NASA_GLDAS_V021_NOAH_G025_T3H"
    ),
))


# ==========================================================================
# SOIL PROPERTIES — SoilGrids water retention (native Earth Engine)
# ==========================================================================

#: SoilGrids depth band names, keyed by the depth interval they represent.
SOILGRIDS_WV_DEPTHS: Tuple[str, ...] = (
    "0_5cm", "5_15cm", "15_30cm", "30_60cm", "60_100cm", "100_200cm",
)

#: Suction levels available as separate SoilGrids assets. The band name is
#: identical in each asset; only the asset path differs.
SOILGRIDS_WV_SUCTIONS: Dict[str, str] = {
    "wv0010": "10 kPa, approximately field capacity",
    "wv0033": "33 kPa",
    "wv1500": "1500 kPa, approximately permanent wilting point",
}


def _soilgrids_wv_bands() -> Dict[str, "BandSpec"]:
    """Build the mean-value bands for all six depths.

    Only the ``mean`` quantile is registered. The Q0.05 and Q0.95 bands are
    deliberately omitted: a metric that needs an uncertainty envelope can
    have them added explicitly later, and registering them now would imply
    the engine uses them when it does not.
    """
    bands: Dict[str, BandSpec] = {}
    for depth in SOILGRIDS_WV_DEPTHS:
        name = f"val_{depth}_mean"
        bands[name] = BandSpec(
            name,
            f"Volumetric water content, mean, {depth.replace('_', '-')}",
            "cm3/cm3",
            # The catalogue states 10^-3 cm^3/cm^3, which is the same
            # numeric scale as m3/m3. The stored integer is therefore
            # converted to a volume fraction by multiplying by 0.001.
            0.001,
            0.0,
            (0.0, 0.65),
            (),
        )
    return bands


_register(DatasetSpec(
    id="ISRIC/SoilGrids250m/v2_0",
    name="SoilGrids 2.0 Volumetric Water Content",
    name_fa="SoilGrids نگهداشت آب خاک",
    provider="ISRIC - World Soil Information",
    description=(
        "Predicted volumetric water content at three suction levels "
        "(10, 33 and 1500 kPa) at six standard depths, from a quantile "
        "random forest digital soil mapping model. This is a STATIC soil "
        "property map, not a time series."
    ),
    spatial_resolution="250 m",
    temporal_resolution="static (single product, no time dimension)",
    available_from="1905-04-01",
    available_to="2016-07-05",
    temporal_kind=TemporalKind.STATIC,
    measurement_basis=MeasurementBasis.MODELLED,
    roles=("static_soil_property",),
    # The three suction assets share a band naming scheme. The engine
    # selects the asset by suffix, which is why the roles are recorded
    # rather than three separate near-identical dataset entries.
    bands=_soilgrids_wv_bands(),
    caveats=(
        "This is a PREDICTION from a digital soil mapping model with a global training set. It is not a laboratory measurement at the field.",
        "The three suction levels live in separate Earth Engine assets (/wv0010, /wv0033, /wv1500) that share the same band names. The asset suffix must be selected explicitly.",
        "There is no uncertainty band; the catalogue recommends computing it as (Q0.95 - Q0.05) / Q0.50, which this engine does not yet do.",
        "A 250 m soil map cannot represent within-field soil variability, which is often the largest source of error in a water balance.",
        "The data carry no observation date; the temporal extent reflects the range of the underlying soil profiles, not when the map is valid.",
    ),
    citation=(
        "SoilGrids 2.0 water retention, Turek et al. 2023, "
        "International Soil and Water Conservation Research"
    ),
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/ISRIC_SoilGrids250m_v2_0",
))


# ==========================================================================
# TERRAIN — DEMs
# ==========================================================================

#: NASADEM 'num' band codes. This band is a *source index*, not a quality
#: score, and the codes are unordered, so no arithmetic may be applied to
#: it and a larger value does not mean better data.
NASADEM_NUM_SOURCE_CODES: Dict[int, str] = {
    0: "Water in corrected SRTM water body data",
    1: "SRTM source scene index 1 (up to 23)",
    41: "PRISM source index 41 (up to 94)",
    110: "GDEM3 source index 110 (saturated at 50)",
    170: "GDEM2 source index 170 (saturated at 50)",
    231: "SRTMv3 from GDEM3",
    232: "SRTMv2 from GDEM3",
    233: "SRTMv2 from GDEM2",
    234: "SRTM with NGA fill from GDEM2",
    241: "NED from GDEM2 (USA)",
    242: "NED from GDEM3 (USA)",
    243: "CDED from GDEM2 (Canada)",
    244: "CDED from GDEM3 (Canada)",
    245: "Alaska from GDEM2",
    246: "Alaska from GDEM3",
    250: "Interpolation",
    251: "Quad edge averaged where neighbouring quads disagreed",
    255: "ERROR (source index missing)",
}

#: NASADEM 'num' codes that mean the pixel is not a clean single-source
#: observation: 251 is a disagreement average and 255 marks a missing index.
NASADEM_NUM_SUSPECT_CODES: Tuple[int, ...] = (251, 255)

#: NASADEM 'swb' water body mask. The catalogue publishes exactly two
#: values, and the water value is 255 — not 1. Reading this band as a
#: 0/1 flag would classify every water pixel as land.
NASADEM_SWB_LAND = 0
NASADEM_SWB_WATER = 255

#: Threshold, in degrees, below which a pixel's aspect is not meaningful.
#:
#: Earth Engine's `ee.Terrain.aspect` returns degrees clockwise from north
#: for the downslope direction, and returns 0 on flat ground. That makes a
#: bare aspect value of 0 ambiguous: it is simultaneously "faces due north"
#: and "has no downslope direction at all". Verified empirically against
#: live Earth Engine with synthetic planes (a plane descending eastward
#: gives 90, northward gives 0; flat terrain also gives 0).
#:
#: This engine therefore reports aspect only for pixels at or above this
#: slope, and reports the fraction of the area that fell below it
#: separately. The threshold is a reporting convention chosen here, not a
#: published product property, and it is stated in every result.
TERRAIN_ASPECT_MIN_SLOPE_DEG = 1.0

#: Compass sectors used to summarise aspect without collapsing it to a mean.
TERRAIN_ASPECT_SECTORS: Tuple[Tuple[str, float, float], ...] = (
    ("N", 337.5, 22.5),
    ("NE", 22.5, 67.5),
    ("E", 67.5, 112.5),
    ("SE", 112.5, 157.5),
    ("S", 157.5, 202.5),
    ("SW", 202.5, 247.5),
    ("W", 247.5, 292.5),
    ("NW", 292.5, 337.5),
)


_register(DatasetSpec(
    id="NASA/NASADEM_HGT/001",
    name="NASADEM Global Digital Elevation Model",
    name_fa="مدل ارتفاعی NASADEM",
    provider="NASA JPL",
    description=(
        "Reprocessed SRTM elevation with improved void filling and ICESat "
        "GLAS control."
    ),
    spatial_resolution="30 m",
    temporal_resolution="static (acquired 2000-02-11 to 2000-02-22)",
    available_from="2000-02-11",
    available_to="2000-02-22",
    temporal_kind=TemporalKind.STATIC,
    measurement_basis=MeasurementBasis.PRODUCT,
    roles=("primary",),
    bands={
        # Valid ranges below are the catalogue's published min/max, which the
        # catalogue marks as estimates. They are widening bounds for sanity
        # checks, not nodata sentinels: NASADEM uses masking, not a sentinel.
        "elevation": BandSpec("elevation", "Elevation above EGM96 geoid", "m", 1.0, 0.0, (-512.0, 8768.0), ()),
        "num": BandSpec(
            "num",
            "Source-scene index: which source data produced each pixel",
            "index",
            1.0,
            0.0,
            (0.0, 255.0),
            (),
        ),
        "swb": BandSpec(
            "swb",
            "Surface water body mask: 0 = land, 255 = water",
            "class",
            1.0,
            0.0,
            (0.0, 255.0),
            (),
        ),
    },
    caveats=(
        "Elevation is referenced to the EGM96 geoid, not to the WGS84 ellipsoid.",
        "The acquisition window is a single 11-day mission in 2000; the surface may have changed since.",
        "Heights over dense vegetation reflect a surface influenced by canopy, biasing slope and aspect in forested terrain.",
        "The 'num' band is a source-scene index, not a quality score, and its codes are "
        "unordered: 0 means water in corrected SRTM water body data, 1-23 are SRTM "
        "source scenes, 41-94 are PRISM, 110-160 GDEM3, 170-220 GDEM2, 231-246 are "
        "per-region fill sources, 250 is interpolation, 251 marks a quad edge average "
        "where neighbouring quads disagreed, and 255 marks an error. A high value is "
        "not better data, and a mean of this band would be meaningless.",
        "Values of 251 and 255 in the 'num' band indicate fill or error rather than a "
        "clean single-source observation.",
        "Ocean is masked by the product rather than returned as a zero or a nodata "
        "sentinel, so a water surface has no elevation here, not an elevation of zero.",
    ),
    citation="NASADEM, NASA JPL 2020",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/NASA_NASADEM_HGT_001",
))

_register(DatasetSpec(
    id="USGS/SRTMGL1_003",
    name="SRTM Void Filled 30 m",
    name_fa="مدل ارتفاعی SRTM",
    provider="USGS / NASA",
    description="SRTM 1 arc-second global elevation, void filled.",
    spatial_resolution="30 m",
    temporal_resolution="static (acquired 2000-02-11 to 2000-02-22)",
    available_from="2000-02-11",
    available_to="2000-02-22",
    temporal_kind=TemporalKind.STATIC,
    measurement_basis=MeasurementBasis.PRODUCT,
    roles=("fallback",),
    bands={
        "elevation": BandSpec("elevation", "Elevation", "m", 1.0, 0.0, (-10.0, 6500.0), ()),
    },
    caveats=(
        "Superseded by NASADEM, which has fewer voids; this is retained as a fallback only.",
        "Void filling used ASTER GDEM2, GMTED2010 and NED, so it is not purely SRTM data.",
        "The published valid range is -10 to 6500 m, narrower than NASADEM's. It is a "
        "stated data range, not a nodata sentinel, so it must not be used to mask.",
        "This product carries only an elevation band: there is no source-scene index "
        "and no water body mask, so a fallback cannot report provenance of that kind.",
    ),
    citation="SRTMGL1 v003, NASA/USGS",
    docs_url="https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003",
))


# ==========================================================================
# Registry access API
# ==========================================================================


def get_dataset(dataset_id: str) -> DatasetSpec:
    """Return a dataset spec by ID, raising a clear error if unknown."""
    try:
        return REGISTRY[dataset_id]
    except KeyError:
        raise KeyError(
            f"Dataset {dataset_id!r} is not registered. Add it to "
            "app.services.agriculture.registry.datasets with verified "
            "parameters before using it in a metric."
        ) from None


def get_datasets() -> List[DatasetSpec]:
    """Return all registered datasets, ordered by ID for stable output."""
    return [REGISTRY[k] for k in sorted(REGISTRY)]


def has_dataset(dataset_id: str) -> bool:
    return dataset_id in REGISTRY


def dataset_ids() -> List[str]:
    return sorted(REGISTRY)


def find_by_role(role: str) -> List[DatasetSpec]:
    """Return datasets declaring a given role, e.g. 'primary' or 'fallback'."""
    return [d for d in get_datasets() if role in d.roles]
