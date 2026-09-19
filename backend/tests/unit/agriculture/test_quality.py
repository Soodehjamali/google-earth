"""Tests for the quality policy.

The single most important behaviour under test: missing data must never
become the value zero. A field we could not observe is not a failing
field, and these tests exist to keep that distinction intact.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import pytest

from app.services.agriculture.quality import (
    MODIS_THRESHOLDS,
    REANALYSIS_THRESHOLDS,
    SENTINEL2_THRESHOLDS,
    QualityThresholds,
    assess_quality,
    combine_quality,
    describe_quality,
    quality_from_cloud_fraction,
)
from app.services.agriculture.types import QualityLevel


# --------------------------------------------------------------------------
# Coverage collapse
# --------------------------------------------------------------------------


def test_no_valid_pixels_is_insufficient_never_zero():
    """The core safety property of the whole engine."""
    level = assess_quality(
        image_count=20,
        coverage_percent=0.0,
        valid_pixel_count=0,
    )
    assert level is QualityLevel.INSUFFICIENT
    assert level is not QualityLevel.POOR


def test_zero_coverage_with_pixels_is_insufficient():
    level = assess_quality(
        image_count=10,
        coverage_percent=0.0,
        valid_pixel_count=50,
    )
    assert level is QualityLevel.INSUFFICIENT


def test_below_minimum_valid_pixels_is_insufficient():
    """A handful of pixels cannot support a spatial statistic."""
    level = assess_quality(
        image_count=10,
        coverage_percent=90.0,
        valid_pixel_count=3,  # below SENTINEL2 min of 20
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.INSUFFICIENT


def test_low_coverage_is_insufficient_even_with_many_scenes():
    """Many scenes each seeing a sliver is not the same as seeing the field."""
    level = assess_quality(
        image_count=50,
        coverage_percent=10.0,  # below SENTINEL2 min of 25
        valid_pixel_count=5000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.INSUFFICIENT


def test_zero_images_is_insufficient():
    level = assess_quality(
        image_count=0,
        coverage_percent=100.0,
        valid_pixel_count=1000,
    )
    assert level is QualityLevel.INSUFFICIENT


# --------------------------------------------------------------------------
# Escalation with evidence
# --------------------------------------------------------------------------


def test_healthy_scene_count_and_coverage_is_excellent():
    level = assess_quality(
        image_count=10,
        coverage_percent=95.0,
        valid_pixel_count=50000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.EXCELLENT


def test_mid_scene_count_is_good():
    level = assess_quality(
        image_count=5,
        coverage_percent=90.0,
        valid_pixel_count=40000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.GOOD


def test_two_scenes_is_moderate():
    level = assess_quality(
        image_count=2,
        coverage_percent=90.0,
        valid_pixel_count=40000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.MODERATE


def test_single_scene_is_poor():
    level = assess_quality(
        image_count=1,
        coverage_percent=90.0,
        valid_pixel_count=40000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.POOR


# --------------------------------------------------------------------------
# Coverage can only downgrade, never upgrade
# --------------------------------------------------------------------------


def test_excellent_scene_count_downgraded_by_mediocre_coverage():
    level = assess_quality(
        image_count=20,
        coverage_percent=70.0,  # below excellent_min_coverage of 85
        valid_pixel_count=50000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.GOOD


def test_excellent_scene_count_heavily_downgraded_by_poor_coverage():
    level = assess_quality(
        image_count=20,
        coverage_percent=45.0,  # below good_min_coverage of 60
        valid_pixel_count=50000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.MODERATE


def test_moderate_scene_count_with_thin_coverage_is_poor():
    level = assess_quality(
        image_count=2,
        coverage_percent=30.0,
        valid_pixel_count=5000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.POOR


def test_coverage_alone_cannot_produce_excellent():
    """One clear scene never becomes excellent, however complete."""
    level = assess_quality(
        image_count=1,
        coverage_percent=100.0,
        valid_pixel_count=100000,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    assert level is QualityLevel.POOR


# --------------------------------------------------------------------------
# Cloud influence
# --------------------------------------------------------------------------


def test_heavy_cloud_downgrades_otherwise_good_result():
    level = assess_quality(
        image_count=6,
        coverage_percent=90.0,
        valid_pixel_count=40000,
        thresholds=SENTINEL2_THRESHOLDS,
        mean_cloud_percent=85.0,
    )
    assert level is QualityLevel.MODERATE


def test_very_heavy_cloud_downgrades_moderate_to_poor():
    level = assess_quality(
        image_count=3,
        coverage_percent=80.0,
        valid_pixel_count=40000,
        thresholds=SENTINEL2_THRESHOLDS,
        mean_cloud_percent=95.0,
    )
    assert level is QualityLevel.POOR


def test_clear_scenes_not_downgraded_by_cloud_rule():
    level = assess_quality(
        image_count=10,
        coverage_percent=95.0,
        valid_pixel_count=50000,
        thresholds=SENTINEL2_THRESHOLDS,
        mean_cloud_percent=5.0,
    )
    assert level is QualityLevel.EXCELLENT


# --------------------------------------------------------------------------
# Defensive input handling
# --------------------------------------------------------------------------


def test_negative_image_count_is_unavailable():
    level = assess_quality(-1, 50.0, 100)
    assert level is QualityLevel.UNAVAILABLE


def test_nan_coverage_is_unavailable():
    level = assess_quality(5, float("nan"), 100)
    assert level is QualityLevel.UNAVAILABLE


def test_none_inputs_are_unavailable():
    assert assess_quality(None, 50.0, 100) is QualityLevel.UNAVAILABLE  # type: ignore[arg-type]
    assert assess_quality(5, None, 100) is QualityLevel.UNAVAILABLE  # type: ignore[arg-type]
    assert assess_quality(5, 50.0, None) is QualityLevel.UNAVAILABLE  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Threshold presets behave sensibly
# --------------------------------------------------------------------------


def test_reanalysis_accepts_single_value_at_full_coverage():
    """A reanalysis has exactly one value per timestep by construction.

    Image count is therefore not a meaningful quality signal for these
    sources, which is why REANALYSIS_THRESHOLDS sets the image floor to 1.
    Quality then hinges on coverage rather than scene count.
    """
    level = assess_quality(
        image_count=1,
        coverage_percent=100.0,
        valid_pixel_count=1,
        thresholds=REANALYSIS_THRESHOLDS,
    )
    assert level is QualityLevel.EXCELLENT


def test_reanalysis_at_low_coverage_is_not_excellent():
    """Coverage is what constrains quality for a modelled source."""
    level = assess_quality(
        image_count=1,
        coverage_percent=60.0,
        valid_pixel_count=1,
        thresholds=REANALYSIS_THRESHOLDS,
    )
    # Below the 95% excellent bar, and above the 50% good bar.
    assert level is QualityLevel.GOOD


def test_reanalysis_with_no_coverage_is_insufficient():
    level = assess_quality(
        image_count=1,
        coverage_percent=0.0,
        valid_pixel_count=0,
        thresholds=REANALYSIS_THRESHOLDS,
    )
    assert level is QualityLevel.INSUFFICIENT


def test_modis_thresholds_are_less_demanding_than_sentinel():
    """Coarser products need fewer scenes before they count as good."""
    sentinel_good = assess_quality(
        image_count=3, coverage_percent=90.0, valid_pixel_count=500,
        thresholds=SENTINEL2_THRESHOLDS,
    )
    modis_good = assess_quality(
        image_count=3, coverage_percent=90.0, valid_pixel_count=500,
        thresholds=MODIS_THRESHOLDS,
    )
    # MODIS should reach good on the same evidence where Sentinel is moderate.
    assert sentinel_good is QualityLevel.MODERATE
    assert modis_good is QualityLevel.GOOD


def test_custom_thresholds_are_honoured():
    strict = QualityThresholds(
        excellent_min_images=100,
        good_min_images=50,
        moderate_min_images=25,
        poor_min_images=10,
        min_coverage_percent=50.0,
        min_valid_pixels=100,
        excellent_min_coverage=99.0,
        good_min_coverage=95.0,
    )
    level = assess_quality(
        image_count=10,
        coverage_percent=90.0,
        valid_pixel_count=5000,
        thresholds=strict,
    )
    assert level is QualityLevel.POOR


# --------------------------------------------------------------------------
# Scene-level cloud assessment
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fraction,expected",
    [
        (0.0, QualityLevel.EXCELLENT),
        (0.05, QualityLevel.EXCELLENT),
        (0.10, QualityLevel.GOOD),
        (0.20, QualityLevel.GOOD),
        (0.30, QualityLevel.MODERATE),
        (0.40, QualityLevel.MODERATE),
        (0.50, QualityLevel.POOR),
        (0.60, QualityLevel.POOR),
        (0.70, QualityLevel.INSUFFICIENT),
        (1.0, QualityLevel.INSUFFICIENT),
    ],
)
def test_quality_from_cloud_fraction_bands(fraction: float, expected: QualityLevel):
    assert quality_from_cloud_fraction(fraction) is expected


def test_unknown_cloud_fraction_is_not_assumed_clear():
    """An unknown cloud load must not be treated as a cloud-free scene."""
    assert quality_from_cloud_fraction(None) is QualityLevel.UNAVAILABLE
    assert quality_from_cloud_fraction(float("nan")) is QualityLevel.UNAVAILABLE


def test_out_of_range_cloud_fraction_is_unavailable():
    assert quality_from_cloud_fraction(-0.1) is QualityLevel.UNAVAILABLE
    assert quality_from_cloud_fraction(1.5) is QualityLevel.UNAVAILABLE


# --------------------------------------------------------------------------
# Combining verdicts
# --------------------------------------------------------------------------


def test_combine_takes_the_weakest():
    combined = combine_quality([
        QualityLevel.EXCELLENT,
        QualityLevel.GOOD,
        QualityLevel.POOR,
        QualityLevel.EXCELLENT,
    ])
    assert combined is QualityLevel.POOR


def test_combine_single_element():
    assert combine_quality([QualityLevel.MODERATE]) is QualityLevel.MODERATE


def test_combine_empty_is_unavailable():
    """No evidence is not good evidence."""
    assert combine_quality([]) is QualityLevel.UNAVAILABLE


def test_combine_including_insufficient():
    combined = combine_quality([
        QualityLevel.EXCELLENT,
        QualityLevel.INSUFFICIENT,
    ])
    assert combined is QualityLevel.INSUFFICIENT


def test_combine_all_excellent():
    assert combine_quality([
        QualityLevel.EXCELLENT, QualityLevel.EXCELLENT,
    ]) is QualityLevel.EXCELLENT


# --------------------------------------------------------------------------
# Quality level semantics
# --------------------------------------------------------------------------


def test_only_excellent_good_moderate_are_usable():
    assert QualityLevel.EXCELLENT.is_usable
    assert QualityLevel.GOOD.is_usable
    assert QualityLevel.MODERATE.is_usable
    assert not QualityLevel.POOR.is_usable
    assert not QualityLevel.INSUFFICIENT.is_usable
    assert not QualityLevel.UNAVAILABLE.is_usable


def test_poor_and_moderate_require_a_caveat():
    assert QualityLevel.MODERATE.needs_caveat
    assert QualityLevel.POOR.needs_caveat
    assert not QualityLevel.EXCELLENT.needs_caveat


def test_describe_quality_english_and_persian():
    en = describe_quality(QualityLevel.INSUFFICIENT, "en")
    fa = describe_quality(QualityLevel.INSUFFICIENT, "fa")
    assert en and isinstance(en, str)
    assert fa and isinstance(fa, str)
    assert en != fa
    # The Persian text must contain Persian characters, not transliteration.
    assert any("\u0600" <= ch <= "\u06ff" for ch in fa)


def test_describe_quality_covers_every_level():
    for level in QualityLevel:
        assert describe_quality(level, "en")
        assert describe_quality(level, "fa")


# --------------------------------------------------------------------------
# MODIS LST quality control decoding
# --------------------------------------------------------------------------


from app.services.agriculture.quality import (  # noqa: E402
    MOD11_LST_ERROR_MASK,
    MOD11_LST_ERROR_MAX_KELVIN,
    ModisLstQuality,
    decode_modis_lst_qc,
    qc_bit_value,
)


def test_qc_decode_rejects_missing_input():
    """An absent flag must never be mistaken for a good one."""
    assert decode_modis_lst_qc(None) is None


def test_qc_decode_rejects_booleans():
    """bool is an int subclass, so True would decode as quality 1."""
    assert decode_modis_lst_qc(True) is None
    assert decode_modis_lst_qc(False) is None


def test_qc_decode_rejects_negative_and_non_numeric():
    assert decode_modis_lst_qc(-1) is None
    assert decode_modis_lst_qc("good") is None
    assert decode_modis_lst_qc(object()) is None


def test_qc_bit_extraction():
    # Bits 0-1 = 3
    assert qc_bit_value(0b00000011, 0b11, 0) == 3
    # Bits 2-3 = 2
    assert qc_bit_value(0b00001000, 0b1100, 2) == 2
    # Bits 6-7 = 1
    assert qc_bit_value(0b01000000, MOD11_LST_ERROR_MASK, 6) == 1


def test_qc_all_zero_is_produced_and_good():
    quality = decode_modis_lst_qc(0)
    assert quality.mandatory_qa == 0
    assert quality.data_quality == 0
    assert quality.is_produced is True
    assert quality.is_good is True
    assert quality.is_reliable is True


def test_qc_cloud_pixels_are_not_produced():
    """Mandatory flag 2 means the pixel was not produced due to cloud."""
    quality = decode_modis_lst_qc(2)
    assert quality.mandatory_qa == 2
    assert quality.is_produced is False
    assert quality.is_reliable is False


def test_qc_other_reason_pixels_are_not_produced():
    """Flag 3 means not produced for a non-cloud reason."""
    quality = decode_modis_lst_qc(3)
    assert quality.mandatory_qa == 3
    assert quality.is_produced is False


def test_qc_unreliable_but_produced():
    """Flag 1 means the pixel exists but should be examined further."""
    quality = decode_modis_lst_qc(1)
    assert quality.mandatory_qa == 1
    assert quality.is_produced is True
    assert quality.is_good is False
    # The LST error flag is independent, so it can still be reliable.
    assert quality.is_reliable is True


def test_the_lst_error_flag_is_read_independently_of_the_mandatory_flag():
    """This is the reason the two are decoded separately.

    A pixel can be flagged "produced, good quality" while carrying a 2 K
    error. Trusting the mandatory flag alone would accept it.
    """
    quality = decode_modis_lst_qc(0b01000000)
    assert quality.is_good is True
    assert quality.lst_error == 1
    assert quality.lst_error_kelvin == 2.0
    assert quality.is_reliable is False


def test_qc_lst_error_ladder():
    for index, expected in enumerate((1.0, 2.0, 3.0)):
        quality = decode_modis_lst_qc(index << 6)
        assert quality.lst_error == index
        assert quality.lst_error_kelvin == expected


def test_qc_top_error_flag_is_unbounded():
    """The highest flag means 'greater than 3 K'; the bound is unknown."""
    quality = decode_modis_lst_qc(3 << 6)
    assert quality.lst_error == 3
    assert quality.lst_error_kelvin == float("inf")
    assert quality.is_reliable is False


def test_qc_error_ladder_is_monotonic():
    """A coarser flag must never imply a smaller error."""
    assert list(MOD11_LST_ERROR_MAX_KELVIN) == sorted(MOD11_LST_ERROR_MAX_KELVIN)


def test_qc_data_quality_flag():
    quality = decode_modis_lst_qc(0b00000100)
    assert quality.data_quality == 1
    assert quality.is_good is False
    assert quality.is_produced is True


def test_qc_emissivity_error_flag():
    for index, expected in enumerate((0, 1, 2, 3)):
        quality = decode_modis_lst_qc(index << 4)
        assert quality.emissivity_error == expected


def test_qc_fields_do_not_bleed_into_each_other():
    """A fully packed mask must decode into exactly the four fields."""
    raw = 0b11_10_01_00  # lst=3, emissivity=2, data quality=1, mandatory=0
    quality = decode_modis_lst_qc(raw)
    assert quality.mandatory_qa == 0
    assert quality.data_quality == 1
    assert quality.emissivity_error == 2
    assert quality.lst_error == 3
    assert quality.raw == raw


def test_qc_decoding_is_total_over_the_byte_range():
    """Every value a MODIS byte can hold must decode without raising."""
    for raw in range(256):
        quality = decode_modis_lst_qc(raw)
        assert isinstance(quality, ModisLstQuality)
        assert 0 <= quality.mandatory_qa <= 3
        assert 0 <= quality.emissivity_error <= 3
        assert 0 <= quality.lst_error <= 3


def test_qc_reliable_implies_produced():
    """A pixel that was never produced cannot be reliable."""
    for raw in range(256):
        quality = decode_modis_lst_qc(raw)
        if quality.is_reliable:
            assert quality.is_produced, raw


def test_qc_good_does_not_imply_reliable():
    """The flags are independent; this pairing must be representable."""
    quality = decode_modis_lst_qc(0b11000000)
    assert quality.is_good is True
    assert quality.is_reliable is False
