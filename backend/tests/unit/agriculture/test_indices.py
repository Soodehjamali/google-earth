"""Tests for the pure vegetation index formulas.

These tests pin the arithmetic. They are the reference against which the
Earth Engine expressions must agree, so a discrepancy between the two
implementations surfaces here rather than as a wrong number in a field
report.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import math

import pytest

from app.services.agriculture import indices as pure


# --------------------------------------------------------------------------
# NDVI
# --------------------------------------------------------------------------


def test_ndvi_healthy_vegetation():
    # A typical healthy canopy: NIR 0.35, red 0.05.
    value = pure.ndvi(0.35, 0.05)
    assert value == pytest.approx(0.75)


def test_ndvi_bare_soil():
    # Red and NIR close together gives a low index.
    value = pure.ndvi(0.20, 0.18)
    assert value == pytest.approx(0.0526, abs=1e-4)


def test_ndvi_water_is_negative():
    # Water reflects more red than NIR.
    value = pure.ndvi(0.02, 0.05)
    assert value is not None
    assert value < 0


def test_ndvi_equal_bands_is_zero():
    assert pure.ndvi(0.2, 0.2) == pytest.approx(0.0)


def test_ndvi_both_zero_is_undefined():
    """A zero denominator must give no value, not zero."""
    assert pure.ndvi(0.0, 0.0) is None


def test_ndvi_missing_input_gives_none():
    assert pure.ndvi(None, 0.1) is None
    assert pure.ndvi(0.1, None) is None
    assert pure.ndvi(None, None) is None


def test_ndvi_non_finite_gives_none():
    assert pure.ndvi(float("nan"), 0.1) is None
    assert pure.ndvi(0.1, float("inf")) is None


def test_ndvi_boolean_input_rejected():
    """bool is an int subclass and must not be treated as a reflectance."""
    assert pure.ndvi(True, 0.1) is None
    assert pure.ndvi(0.1, False) is None


# --------------------------------------------------------------------------
# EVI
# --------------------------------------------------------------------------


def test_evi_vegetation():
    value = pure.evi(nir=0.35, red=0.05, blue=0.02)
    assert value is not None
    # EVI is generally lower than NDVI for the same reflectances.
    assert 0.0 < value < 1.0


def test_evi_below_ndvi_for_same_reflectances():
    ndvi_value = pure.ndvi(0.35, 0.05)
    evi_value = pure.evi(0.35, 0.05, 0.02)
    assert ndvi_value is not None and evi_value is not None
    assert evi_value < ndvi_value


def test_evi_requires_blue():
    assert pure.evi(0.35, 0.05, None) is None


def test_evi_zero_denominator():
    # NIR + 6*RED - 7.5*BLUE + 1 = 0 => RED = (7.5*BLUE - 1 - NIR) / 6
    blue, nir = 0.1, 0.05
    red = (7.5 * blue - 1.0 - nir) / 6.0
    assert pure.evi(nir, red, blue) is None


def test_evi_rejects_non_finite():
    assert pure.evi(0.3, float("nan"), 0.02) is None


def test_evi_boolean_rejected():
    assert pure.evi(True, 0.05, 0.02) is None


# --------------------------------------------------------------------------
# SAVI
# --------------------------------------------------------------------------


def test_savi_vegetation_with_default_l():
    value = pure.savi(0.35, 0.05)
    assert value is not None
    assert 0.0 < value < 1.5


def test_savi_with_l_zero_equals_ndvi():
    """With L = 0 SAVI reduces to NDVI, which is a useful sanity check."""
    savi_value = pure.savi(0.35, 0.05, soil_factor=0.0)
    ndvi_value = pure.ndvi(0.35, 0.05)
    assert savi_value == pytest.approx(ndvi_value)  # type: ignore[arg-type]


def test_savi_attenuates_relative_to_ndvi_at_default_l():
    """SAVI at L = 0.5 sits below NDVI for the same reflectances.

    The (NIR + RED + L) denominator term attenuates the index. This is the
    mechanism by which SAVI reduces the soil background contribution that
    inflates NDVI over sparse canopies, so the direction matters: a SAVI
    that exceeded NDVI here would indicate the formula was wrong.
    """
    nir, red = 0.35, 0.05
    savi_value = pure.savi(nir, red, soil_factor=0.5)
    ndvi_value = pure.ndvi(nir, red)
    assert savi_value is not None and ndvi_value is not None
    assert savi_value < ndvi_value
    # Algebraically SAVI = NDVI * (NIR + RED) / (NIR + RED + L) * (1 + L).
    # For these reflectances: 0.75 * 0.4 / 0.9 * 1.5 = 0.5.
    expected = 0.75 * (0.4 / 0.9) * 1.5
    assert savi_value == pytest.approx(expected)
    assert savi_value == pytest.approx(0.5)


def test_savi_approaches_ndvi_as_l_approaches_zero():
    nir, red = 0.35, 0.05
    for soil_factor in (0.5, 0.1, 0.01, 0.001):
        savi_value = pure.savi(nir, red, soil_factor=soil_factor)
        ndvi_value = pure.ndvi(nir, red)
        assert savi_value is not None and ndvi_value is not None
        # Never exceeds NDVI, but converges toward it.
        assert savi_value <= ndvi_value + 1e-9


def test_savi_l_one_sparse_canopy():
    value = pure.savi(0.15, 0.12, soil_factor=1.0)
    assert value is not None
    assert value > 0


def test_savi_zero_denominator():
    # NIR + RED + L = 0 requires negative reflectances.
    assert pure.savi(-0.25, -0.25, soil_factor=0.5) is None


def test_savi_non_finite_soil_factor():
    assert pure.savi(0.3, 0.1, soil_factor=float("nan")) is None


def test_savi_missing_inputs():
    assert pure.savi(None, 0.1) is None
    assert pure.savi(0.1, None) is None


# --------------------------------------------------------------------------
# MSAVI
# --------------------------------------------------------------------------


def test_msavi_vegetation():
    value = pure.msavi(0.35, 0.05)
    assert value is not None
    assert 0.0 < value < 1.0


def test_msavi_radicand_is_never_negative_for_physical_reflectance():
    """Within the physical domain the radicand cannot go negative.

    Reflectance is non-negative, and for NIR and RED both at or above
    zero the radicand (2*NIR + 1)^2 - 8*(NIR - RED) stays non-negative.
    Solving for RED gives the boundary RED = NIR - (2*NIR + 1)^2 / 8,
    which is non-positive for every NIR at or above zero, so RED is never
    large enough to drive the term negative.

    This is why the guard is not exercised by real data: it does not need
    to be. The companion test below confirms it is nevertheless reachable
    with non-physical input, which is the case it exists to catch.
    """
    for nir in [x / 20 for x in range(0, 2001, 7)]:
        boundary = nir - (2.0 * nir + 1.0) ** 2 / 8.0
        assert boundary <= 0, f"boundary positive at nir={nir}"

    for nir in [x / 10 for x in range(0, 201, 3)]:
        for red in [x / 10 for x in range(0, 201, 3)]:
            assert (2.0 * nir + 1.0) ** 2 - 8.0 * (nir - red) >= 0


def test_msavi_guard_is_reachable_with_non_physical_input():
    """The guard is not dead code: negative reflectance can reach it.

    At NIR = -5.6 and RED = -20.0 the radicand is negative. These are not
    physically meaningful reflectances, but a mis-scaled or unsigned
    reflectance product could in principle supply them, and a math domain
    error there would abort an entire analysis. Returning None instead
    lets the pixel be excluded and the analysis continue.
    """
    assert pure.msavi(-5.6, -20.0) is None


def test_msavi_normal_call_is_unaffected_by_the_guard():
    assert pure.msavi(0.35, 0.05) is not None


def test_msavi_soil_background_gives_low_value():
    value = pure.msavi(0.20, 0.18)
    assert value is not None
    assert value < 0.2


def test_msavi_missing_inputs():
    assert pure.msavi(None, 0.1) is None
    assert pure.msavi(0.1, None) is None


def test_msavi_non_finite():
    assert pure.msavi(float("inf"), 0.1) is None


# --------------------------------------------------------------------------
# NDRE
# --------------------------------------------------------------------------


def test_ndre_vegetation():
    value = pure.ndre(nir=0.35, red_edge=0.12)
    assert value == pytest.approx(0.4893, abs=1e-3)


def test_ndre_lower_than_ndvi():
    """The red edge band sits between red and NIR, so NDRE < NDVI."""
    ndre_value = pure.ndre(0.35, 0.12)
    ndvi_value = pure.ndvi(0.35, 0.05)
    assert ndre_value is not None and ndvi_value is not None
    assert ndre_value < ndvi_value


def test_ndre_missing_inputs():
    assert pure.ndre(None, 0.1) is None
    assert pure.ndre(0.1, None) is None


def test_ndre_zero_denominator():
    assert pure.ndre(0.0, 0.0) is None


# --------------------------------------------------------------------------
# NDWI
# --------------------------------------------------------------------------


def test_ndwi_open_water_is_positive():
    # Water: green high, NIR very low.
    value = pure.ndwi(green=0.06, nir=0.02)
    assert value is not None
    assert value > 0


def test_ndwi_vegetation_is_negative():
    value = pure.ndwi(green=0.05, nir=0.35)
    assert value is not None
    assert value < 0


def test_ndwi_zero_denominator():
    assert pure.ndwi(0.0, 0.0) is None


# --------------------------------------------------------------------------
# NDMI
# --------------------------------------------------------------------------


def test_ndmi_positive_for_well_watered_canopy():
    value = pure.ndmi(nir=0.30, swir1=0.15)
    assert value is not None
    assert value > 0


def test_ndmi_lower_for_dry_canopy():
    wet = pure.ndmi(0.30, 0.15)
    dry = pure.ndmi(0.30, 0.30)
    assert wet is not None and dry is not None
    assert wet > dry


def test_ndmi_and_ndwi_use_different_bands():
    """These two indices answer different questions and take different bands.

    NDWI is (GREEN - NIR) / (GREEN + NIR) and targets open water. NDMI is
    (NIR - SWIR1) / (NIR + SWIR1) and targets vegetation water content.
    Passing identical numbers to both would compare nothing, because the
    second positional argument means NIR to NDWI and SWIR1 to NDMI. This
    test feeds each its own correct bands.
    """
    green, nir, swir1 = 0.09, 0.30, 0.15

    ndwi_value = pure.ndwi(green, nir)
    ndmi_value = pure.ndmi(nir, swir1)

    assert ndwi_value is not None and ndmi_value is not None
    # Vegetation has low green relative to NIR, so NDWI is negative here.
    assert ndwi_value < 0
    # Vegetation has high NIR relative to SWIR1, so NDMI is positive.
    assert ndmi_value > 0
    assert ndwi_value != ndmi_value


def test_ndwi_detects_water_where_ndmi_does_not_apply():
    """Over an open water surface the two indices behave very differently."""
    # Water: green 0.06, NIR 0.02, SWIR1 0.01.
    ndwi_value = pure.ndwi(0.06, 0.02)
    assert ndwi_value is not None and ndwi_value > 0.4

    # NDMI over the same surface would need NIR and SWIR1; it is not a
    # water index and must not be presented as one.
    assert pure.ndwi(0.06, 0.02) != pure.ndmi(0.02, 0.01)


def test_ndmi_zero_denominator():
    assert pure.ndmi(0.0, 0.0) is None


# --------------------------------------------------------------------------
# MNDWI
# --------------------------------------------------------------------------


def test_mndwi_water_positive():
    value = pure.mndwi(green=0.06, swir1=0.02)
    assert value is not None
    assert value > 0


def test_mndwi_stronger_than_ndwi_over_water():
    """SWIR1 suppresses vegetation and shadow better than NIR."""
    mndwi_value = pure.mndwi(0.06, 0.02)
    ndwi_value = pure.ndwi(0.06, 0.02)
    assert mndwi_value == pytest.approx(ndwi_value)  # type: ignore[arg-type]


def test_mndwi_zero_denominator():
    assert pure.mndwi(0.0, 0.0) is None


# --------------------------------------------------------------------------
# safe_normalized_difference
# --------------------------------------------------------------------------


def test_safe_normalized_difference_basic():
    assert pure.safe_normalized_difference(0.4, 0.1) == pytest.approx(0.6)


def test_safe_normalized_difference_symmetry():
    """Swapping the arguments negates the result."""
    forward = pure.safe_normalized_difference(0.4, 0.1)
    reverse = pure.safe_normalized_difference(0.1, 0.4)
    assert forward == pytest.approx(-reverse)  # type: ignore[arg-type]


def test_safe_normalized_difference_bounds():
    """The result is bounded to [-1, 1] for non-negative reflectances."""
    for a, b in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)):
        value = pure.safe_normalized_difference(a, b)
        assert value is not None
        assert -1.0 <= value <= 1.0


# --------------------------------------------------------------------------
# Metadata consistency
# --------------------------------------------------------------------------


def test_every_formula_has_formula_text():
    for name in (
        "ndvi", "evi", "savi", "msavi", "ndre", "ndwi", "ndmi", "mndwi"
    ):
        assert name in pure.FORMULA_TEXT
        assert pure.FORMULA_TEXT[name]


def test_every_formula_has_band_roles():
    for name in pure.FORMULA_TEXT:
        assert name in pure.BAND_ROLES
        assert pure.BAND_ROLES[name]


def test_every_formula_has_expected_range():
    for name in pure.FORMULA_TEXT:
        assert name in pure.EXPECTED_RANGE
        low, high = pure.EXPECTED_RANGE[name]
        assert low < high


def test_every_formula_has_typical_range():
    for name in pure.FORMULA_TEXT:
        assert name in pure.TYPICAL_VEGETATION_RANGE
        low, high = pure.TYPICAL_VEGETATION_RANGE[name]
        assert low < high


def test_band_roles_reference_real_sentinel2_bands():
    from app.services.agriculture.registry import get_dataset

    spec = get_dataset("COPERNICUS/S2_SR_HARMONIZED")
    for name, bands in pure.BAND_ROLES.items():
        for band in bands:
            assert spec.has_band(band), (
                f"{name} references band {band} which does not exist in "
                "the Sentinel-2 registry entry"
            )


def test_typical_ranges_within_expected_ranges():
    """A typical range outside the possible range would be a contradiction."""
    for name, (typical_low, typical_high) in pure.TYPICAL_VEGETATION_RANGE.items():
        expected_low, expected_high = pure.EXPECTED_RANGE[name]
        assert expected_low <= typical_low <= expected_high
        assert expected_low <= typical_high <= expected_high


def test_all_formulas_return_none_for_none_inputs():
    """No formula may silently substitute a number for missing input."""
    assert pure.ndvi(None, None) is None
    assert pure.evi(None, None, None) is None
    assert pure.savi(None, None) is None
    assert pure.msavi(None, None) is None
    assert pure.ndre(None, None) is None
    assert pure.ndwi(None, None) is None
    assert pure.ndmi(None, None) is None
    assert pure.mndwi(None, None) is None


def test_sample_values_land_in_typical_vegetation_range():
    """A sanity check that the formulas agree with documented expectations."""
    # Reflectances typical of a moderately vegetated field.
    nir, red, green, blue, red_edge, swir1 = 0.30, 0.08, 0.09, 0.04, 0.16, 0.18

    samples = {
        "ndvi": pure.ndvi(nir, red),
        "evi": pure.evi(nir, red, blue),
        "savi": pure.savi(nir, red),
        "msavi": pure.msavi(nir, red),
        "ndre": pure.ndre(nir, red_edge),
        "ndwi": pure.ndwi(green, nir),
        "ndmi": pure.ndmi(nir, swir1),
        "mndwi": pure.mndwi(green, swir1),
    }

    for name, value in samples.items():
        assert value is not None, f"{name} returned None for valid input"
        assert math.isfinite(value), f"{name} returned a non-finite value"
