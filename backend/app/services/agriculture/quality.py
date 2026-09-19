"""Quality assessment for agricultural metrics.

This module is deliberately free of any Earth Engine or network
dependency. It takes observations and returns a quality verdict. That
makes the whole quality policy unit testable without credentials, and it
means the rules are stated in exactly one place.

The central idea
----------------
A satellite analytics platform misleads people in one specific way: it
turns "we could not see this field" into the number zero, which then
renders as a red critical alert. Everything in this module exists to make
that impossible.

A metric is only usable if there is genuine, sufficiently cloud-free
coverage of the requested geometry. Otherwise the honest answer is
``insufficient``, not a value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, Sequence

from app.services.agriculture.types import QualityLevel

__all__ = [
    "CoverageInput",
    "QualityThresholds",
    "SENTINEL2_THRESHOLDS",
    "MODIS_THRESHOLDS",
    "LANDSAT_THRESHOLDS",
    "REANALYSIS_THRESHOLDS",
    "assess_quality",
    "assess_from_coverage",
    "quality_from_cloud_fraction",
    "combine_quality",
    "describe_quality",
    # MODIS LST quality control
    "ModisLstQuality",
    "decode_modis_lst_qc",
    "qc_bit_value",
    "MOD11_MANDATORY_QA_MASK",
    "MOD11_DATA_QUALITY_MASK",
    "MOD11_EMISSIVITY_ERROR_MASK",
    "MOD11_LST_ERROR_MASK",
    "MOD11_LST_ERROR_MAX_KELVIN",
    # SMAP soil moisture retrieval quality
    "SmapRetrievalQuality",
    "decode_smap_retrieval_quality",
    "SMAP_RETRIEVAL_QUALITY_MASK",
    "SMAP_RETRIEVAL_RECOMMENDED",
    "SMAP_RETRIEVAL_UNCERTAIN",
    "SMAP_RETRIEVAL_SKIPPED",
    "SMAP_RETRIEVAL_NOT_ATTEMPTED",
]


class CoverageInput(Protocol):
    """Structural type for anything carrying coverage information.

    Lets :func:`assess_from_coverage` accept the statistics layer's
    objects without coupling this module to that layer's concrete class.
    """

    image_count: int
    coverage_percent: float
    valid_pixel_count: int


@dataclass(frozen=True)
class QualityThresholds:
    """Thresholds that map observation counts and coverage to a verdict.

    Attributes:
        excellent_min_images: Minimum usable scenes for ``excellent``.
        good_min_images: Minimum usable scenes for ``good``.
        moderate_min_images: Minimum usable scenes for ``moderate``.
        poor_min_images: Minimum usable scenes for ``poor``. Below this
            the verdict is ``insufficient``.
        min_coverage_percent: Minimum percentage of the geometry that must
            carry valid data for any verdict above ``poor``.
        min_valid_pixels: Absolute floor on valid pixel count. Below this,
            even full coverage is treated as insufficient, because the
            statistics are not meaningful.
        excellent_min_coverage: Coverage needed for ``excellent``.
        good_min_coverage: Coverage needed for ``good``.
    """

    excellent_min_images: int = 10
    good_min_images: int = 5
    moderate_min_images: int = 3
    poor_min_images: int = 1

    min_coverage_percent: float = 20.0
    min_valid_pixels: int = 10

    excellent_min_coverage: float = 85.0
    good_min_coverage: float = 60.0


#: Sentinel-2, 10 to 20 m. A 5-day revisit means a one-month window
#: should yield plenty of scenes when skies cooperate, and Iran's aridity
#: helps far more than it hurts.
SENTINEL2_THRESHOLDS = QualityThresholds(
    excellent_min_images=8,
    good_min_images=4,
    moderate_min_images=2,
    poor_min_images=1,
    min_coverage_percent=25.0,
    min_valid_pixels=20,
    excellent_min_coverage=85.0,
    good_min_coverage=60.0,
)

#: MODIS products. Coarser and with a longer revisit, so the bar for
#: image count is lower but the coverage bar is similar.
MODIS_THRESHOLDS = QualityThresholds(
    excellent_min_images=5,
    good_min_images=3,
    moderate_min_images=1,
    poor_min_images=1,
    min_coverage_percent=20.0,
    min_valid_pixels=5,
    excellent_min_coverage=80.0,
    good_min_coverage=55.0,
)

#: Landsat. A 16-day revisit means the image count is almost always one
#: or two, so the count thresholds are at their floor and the verdict
#: rests on coverage. The pixel floor is low deliberately: a Landsat
#: thermal reduction runs at 100 m, so a smallholder field of a few
#: hectares legitimately contains only a handful of pixels. Requiring the
#: MODIS floor of five would call such a field insufficient.
LANDSAT_THRESHOLDS = QualityThresholds(
    excellent_min_images=2,
    good_min_images=2,
    moderate_min_images=1,
    poor_min_images=1,
    min_coverage_percent=20.0,
    min_valid_pixels=1,
    excellent_min_coverage=85.0,
    good_min_coverage=60.0,
)

#: Reanalysis and modelled sources. There is exactly one value per
#: timestep by construction, so image count is close to meaningless and
#: quality hinges on coverage and on the source's own limitations.
REANALYSIS_THRESHOLDS = QualityThresholds(
    excellent_min_images=1,
    good_min_images=1,
    moderate_min_images=1,
    poor_min_images=1,
    min_coverage_percent=5.0,
    min_valid_pixels=1,
    excellent_min_coverage=95.0,
    good_min_coverage=50.0,
)


def assess_quality(
    image_count: int,
    coverage_percent: float,
    valid_pixel_count: int,
    thresholds: QualityThresholds = SENTINEL2_THRESHOLDS,
    mean_cloud_percent: Optional[float] = None,
) -> QualityLevel:
    """Return a quality verdict from observation counts and coverage.

    Args:
        image_count: Number of usable scenes contributing to the result.
        coverage_percent: Percentage of the geometry with valid data.
        valid_pixel_count: Number of valid pixels aggregated.
        thresholds: The rule set appropriate to the source.
        mean_cloud_percent: Optional mean cloudiness of the contributing
            scenes, used to downgrade otherwise healthy results.

    Returns:
        A :class:`QualityLevel`.

    The function is intentionally conservative. Falling coverage below the
    threshold downgrades the verdict even when the scene count is high,
    because many scenes each seeing half the field is not the same as
    seeing the whole field well.
    """
    # Guard against nonsense inputs rather than propagating them.
    if image_count is None or image_count < 0:
        return QualityLevel.UNAVAILABLE
    if valid_pixel_count is None or valid_pixel_count < 0:
        return QualityLevel.UNAVAILABLE
    if coverage_percent is None or not math.isfinite(coverage_percent):
        return QualityLevel.UNAVAILABLE

    # Absolute floor: no usable pixels means there is nothing to report.
    if valid_pixel_count == 0 or coverage_percent <= 0.0:
        return QualityLevel.INSUFFICIENT

    # Too few pixels for the aggregate statistics to mean anything.
    if valid_pixel_count < thresholds.min_valid_pixels:
        return QualityLevel.INSUFFICIENT

    # Too few observations to be more than a snapshot.
    if image_count < thresholds.poor_min_images:
        return QualityLevel.INSUFFICIENT

    # Barely any coverage: a value exists but describes a sliver of the
    # requested area.
    if coverage_percent < thresholds.min_coverage_percent:
        return QualityLevel.INSUFFICIENT

    # Establish the ceiling from image count.
    if image_count >= thresholds.excellent_min_images:
        level = QualityLevel.EXCELLENT
    elif image_count >= thresholds.good_min_images:
        level = QualityLevel.GOOD
    elif image_count >= thresholds.moderate_min_images:
        level = QualityLevel.MODERATE
    else:
        level = QualityLevel.POOR

    # Coverage can only pull the verdict down, never push it up. A single
    # cloudy scene is not excellent just because one pixel was clear.
    if level is QualityLevel.EXCELLENT and coverage_percent < thresholds.excellent_min_coverage:
        level = QualityLevel.GOOD
    if level in (QualityLevel.EXCELLENT, QualityLevel.GOOD) and coverage_percent < thresholds.good_min_coverage:
        level = QualityLevel.MODERATE
    if level is QualityLevel.MODERATE and coverage_percent < 40.0:
        level = QualityLevel.POOR

    # Heavy cloud across the contributing scenes is a further reason for
    # caution even when the survivors cleared the mask.
    if mean_cloud_percent is not None and math.isfinite(mean_cloud_percent):
        if mean_cloud_percent >= 80.0 and level in (QualityLevel.EXCELLENT, QualityLevel.GOOD):
            level = QualityLevel.MODERATE
        elif mean_cloud_percent >= 90.0 and level is QualityLevel.MODERATE:
            level = QualityLevel.POOR

    return level


def assess_from_coverage(
    coverage: CoverageInput,
    thresholds: QualityThresholds = SENTINEL2_THRESHOLDS,
    mean_cloud_percent: Optional[float] = None,
) -> QualityLevel:
    """Convenience wrapper taking a coverage object.

    Accepts any object exposing ``image_count``, ``coverage_percent`` and
    ``valid_pixel_count``, which keeps this module decoupled from the
    statistics layer.
    """
    return assess_quality(
        image_count=getattr(coverage, "image_count", 0),
        coverage_percent=getattr(coverage, "coverage_percent", 0.0),
        valid_pixel_count=getattr(coverage, "valid_pixel_count", 0),
        thresholds=thresholds,
        mean_cloud_percent=mean_cloud_percent,
    )


def quality_from_cloud_fraction(
    cloud_fraction: Optional[float],
    thresholds: QualityThresholds = SENTINEL2_THRESHOLDS,
) -> QualityLevel:
    """Assess a single scene from its cloud fraction alone.

    ``cloud_fraction`` is expected as a proportion between 0 and 1. This
    is used when filtering candidate scenes before compositing.

    Returns ``UNAVAILABLE`` if the fraction is unknown, because an
    unknown cloud load must not be treated as a clear scene.
    """
    if cloud_fraction is None:
        return QualityLevel.UNAVAILABLE
    if not math.isfinite(cloud_fraction):
        return QualityLevel.UNAVAILABLE
    if cloud_fraction < 0.0 or cloud_fraction > 1.0:
        return QualityLevel.UNAVAILABLE

    if cloud_fraction <= 0.05:
        return QualityLevel.EXCELLENT
    if cloud_fraction <= 0.20:
        return QualityLevel.GOOD
    if cloud_fraction <= 0.40:
        return QualityLevel.MODERATE
    if cloud_fraction <= 0.60:
        return QualityLevel.POOR
    return QualityLevel.INSUFFICIENT


#: Ordering used when combining verdicts. Lower rank is better.
_QUALITY_RANK = {
    QualityLevel.EXCELLENT: 0,
    QualityLevel.GOOD: 1,
    QualityLevel.MODERATE: 2,
    QualityLevel.POOR: 3,
    QualityLevel.INSUFFICIENT: 4,
    QualityLevel.UNAVAILABLE: 5,
}


def combine_quality(levels: Iterable[QualityLevel]) -> QualityLevel:
    """Combine several verdicts by taking the weakest.

    A composite result is only as trustworthy as its worst input. Used
    when a metric draws on multiple datasets or multiple time steps.

    An empty input is ``UNAVAILABLE``: no evidence is not good evidence.
    """
    worst: Optional[QualityLevel] = None
    for level in levels:
        if worst is None or _QUALITY_RANK[level] > _QUALITY_RANK[worst]:
            worst = level
    return worst if worst is not None else QualityLevel.UNAVAILABLE


def describe_quality(level: QualityLevel, language: str = "en") -> str:
    """Return a short human-readable explanation of a quality verdict.

    These strings are user-facing. They say what the level means for the
    reliability of the number, in plain language, without hedging.
    """
    english = {
        QualityLevel.EXCELLENT: (
            "Dense, well-distributed observations with high spatial coverage. "
            "The value is reliable for the requested area and period."
        ),
        QualityLevel.GOOD: (
            "Sufficient observations with good spatial coverage. "
            "The value is reliable, with minor sensitivity to undetected cloud."
        ),
        QualityLevel.MODERATE: (
            "Enough observations to report a value, but coverage or scene count "
            "is limited. Treat the value as indicative rather than precise."
        ),
        QualityLevel.POOR: (
            "Very few observations or low spatial coverage. The value is a weak "
            "indication only and should not drive a decision on its own."
        ),
        QualityLevel.INSUFFICIENT: (
            "Not enough valid observations to produce a trustworthy value. "
            "No value is reported, because reporting zero would be misleading."
        ),
        QualityLevel.UNAVAILABLE: (
            "The computation could not be performed, for example because the "
            "date range falls outside the dataset's coverage."
        ),
    }
    persian = {
        QualityLevel.EXCELLENT: (
            "تعداد مشاهدات زیاد با پوشش مکانی بالا. مقدار برای محدوده و بازه درخواستی قابل اعتماد است."
        ),
        QualityLevel.GOOD: (
            "مشاهدات کافی با پوشش مکانی مناسب. مقدار قابل اعتماد است و حساسیت جزئی به ابر پنهان دارد."
        ),
        QualityLevel.MODERATE: (
            "برای گزارش مقدار، داده کافی وجود دارد اما پوشش یا تعداد تصاویر محدود است. مقدار را تقریبی در نظر بگیرید."
        ),
        QualityLevel.POOR: (
            "مشاهدات بسیار کم یا پوشش مکانی پایین. مقدار فقط یک نشانه ضعیف است و نباید به‌تنهایی مبنای تصمیم باشد."
        ),
        QualityLevel.INSUFFICIENT: (
            "مشاهدات معتبر کافی برای ارائه مقدار قابل اعتماد وجود ندارد. مقداری گزارش نمی‌شود، زیرا گزارش صفر گمراه‌کننده خواهد بود."
        ),
        QualityLevel.UNAVAILABLE: (
            "محاسبه امکان‌پذیر نبود، مثلاً به این دلیل که بازه زمانی خارج از پوشش دیتاست است."
        ),
    }
    table = persian if language.startswith("fa") else english
    return table[level]


# --------------------------------------------------------------------------
# MODIS land surface temperature quality control
# --------------------------------------------------------------------------


#: Bits 0-1. Whether the pixel was produced at all, and how far to trust it.
MOD11_MANDATORY_QA_MASK = 0b11

#: Bits 2-3. Good versus other quality. Values 2 and 3 are undocumented.
MOD11_DATA_QUALITY_MASK = 0b1100

#: Bits 4-5. Average emissivity error.
MOD11_EMISSIVITY_ERROR_MASK = 0b110000

#: Bits 6-7. Average land surface temperature error, in Kelvin.
MOD11_LST_ERROR_MASK = 0b11000000

#: The LST error implied by each value of the bits 6-7 flag, in Kelvin.
#: The last entry is a lower bound: the flag means "greater than 3 K" and
#: the actual error is unknown above that.
MOD11_LST_ERROR_MAX_KELVIN = (1.0, 2.0, 3.0, float("inf"))


def qc_bit_value(qc_value: int, mask: int, shift: int) -> int:
    """Extract an integer from a bitmask field.

    Bit arithmetic on packed quality flags is easy to get subtly wrong and
    impossible to spot by eye, so it is isolated here and tested
    exhaustively rather than inlined at each use.
    """
    return (int(qc_value) & mask) >> shift


@dataclass(frozen=True)
class ModisLstQuality:
    """A decoded MOD11 ``QC_Day`` or ``QC_Night`` value.

    Every field is exposed rather than collapsed into a single verdict, so
    a caller can apply a stricter policy than the default without having
    to re-decode the mask.
    """

    #: Raw packed value.
    raw: int

    #: 0 produced and good, 1 produced but unreliable, 2 not produced
    #: (cloud), 3 not produced (other).
    mandatory_qa: int

    #: 0 good data quality, 1 other quality data, 2 and 3 undocumented.
    data_quality: int

    #: 0 to 3, increasing emissivity error.
    emissivity_error: int

    #: 0 to 3, increasing LST error.
    lst_error: int

    #: Upper bound on the LST error in Kelvin, or infinity for the
    #: unbounded top flag.
    lst_error_kelvin: float

    @property
    def is_produced(self) -> bool:
        """Whether a retrieval exists for this pixel at all."""
        return self.mandatory_qa in (0, 1)

    @property
    def is_good(self) -> bool:
        """Produced with the best available quality on both flags."""
        return self.mandatory_qa == 0 and self.data_quality == 0

    @property
    def is_reliable(self) -> bool:
        """Produced, and no worse than 1 K of LST error.

        The 1 K bound is the documented meaning of ``lst_error == 0``. It
        is a real accuracy statement rather than an arbitrary threshold,
        which is why it is the criterion rather than the mandatory flag
        alone: a pixel can be "produced and good" while still carrying a
        3 K error.
        """
        return self.is_produced and self.lst_error_kelvin <= 1.0


def decode_modis_lst_qc(qc_value: Optional[int]) -> Optional[ModisLstQuality]:
    """Decode a MOD11 quality control value.

    The documented layout, from the MOD11 product user guide as published
    in the Earth Engine data catalog:

    ===========  ==============================
    Bits         Meaning
    ===========  ==============================
    0-1          Mandatory QA: 0 good, 1 unreliable, 2 cloud, 3 other
    2-3          Data quality: 0 good, 1 other
    4-5          Emissivity error: <=0.01, <=0.02, <=0.04, >0.04
    6-7          LST error: <=1 K, <=2 K, <=3 K, >3 K
    ===========  ==============================

    Returns ``None`` for missing input, so an absent flag can never be
    mistaken for a good one.
    """
    if qc_value is None:
        return None
    if isinstance(qc_value, bool):
        return None
    try:
        raw = int(qc_value)
    except (TypeError, ValueError):
        return None
    if raw < 0:
        return None

    lst_error = qc_bit_value(raw, MOD11_LST_ERROR_MASK, 6)

    return ModisLstQuality(
        raw=raw,
        mandatory_qa=qc_bit_value(raw, MOD11_MANDATORY_QA_MASK, 0),
        data_quality=qc_bit_value(raw, MOD11_DATA_QUALITY_MASK, 2),
        emissivity_error=qc_bit_value(raw, MOD11_EMISSIVITY_ERROR_MASK, 4),
        lst_error=lst_error,
        lst_error_kelvin=MOD11_LST_ERROR_MAX_KELVIN[lst_error],
    )


# --------------------------------------------------------------------------
# SMAP soil moisture quality control
# --------------------------------------------------------------------------
#
# The SMAP retrieval quality flag is NOT a simple good/bad integer and the
# two low bits mean different things. Verified against the NSIDC help
# centre article "How do I interpret the surface and quality flag
# information in the Level-2 and -3 passive soil moisture products?":
#
#   bit 0 = 0   Recommended quality
#   bit 0 = 1   Uncertain quality
#   bit 1 = 1   The retrieval was SKIPPED. The soil moisture field for that
#               pixel is not a retrieval at all.
#
# A pixel is therefore only useful when bit 0 = 0 AND bit 1 = 0. Reading
# the flag as "0 means fine" would treat a retrieval that was never
# attempted (flag value 2) as an uncertain but real observation, which is
# the opposite of the truth.

SMAP_RETRIEVAL_QUALITY_MASK = 0b11
SMAP_RETRIEVAL_RECOMMENDED = 0b00
SMAP_RETRIEVAL_UNCERTAIN = 0b01
SMAP_RETRIEVAL_SKIPPED = 0b10
SMAP_RETRIEVAL_NOT_ATTEMPTED = 0b11


@dataclass(frozen=True)
class SmapRetrievalQuality:
    """Decoded SMAP retrieval quality flag.

    Attributes:
        raw: The raw flag value as stored by the product.
        bits: The two low bits, whose joint value is what matters.
    """

    raw: int
    bits: int

    @property
    def is_recommended(self) -> bool:
        """Recommended quality and the retrieval was attempted."""
        return self.bits == SMAP_RETRIEVAL_RECOMMENDED

    @property
    def is_uncertain(self) -> bool:
        """Retrieval attempted, but the surface conditions were marginal."""
        return self.bits == SMAP_RETRIEVAL_UNCERTAIN

    @property
    def was_skipped(self) -> bool:
        """No retrieval was produced for this pixel.

        Either bit 1 is set. A pixel in this state carries a fill value or
        a model guess in the soil moisture band, so it must never be read
        as an observation.
        """
        return self.bits >= SMAP_RETRIEVAL_SKIPPED

    @property
    def is_usable(self) -> bool:
        """Whether the pixel may contribute to a statistic.

        Uncertain retrievals are usable but must be reported as such; a
        skipped retrieval is not usable under any circumstance.
        """
        return not self.was_skipped


def decode_smap_retrieval_quality(
    flag_value: Optional[int],
) -> Optional[SmapRetrievalQuality]:
    """Decode a SMAP retrieval quality flag.

    Returns ``None`` for missing or malformed input, so an absent flag can
    never be mistaken for a good one. Callers that require recommended
    quality should test ``.is_recommended``; callers that merely require a
    real retrieval should test ``.is_usable``.
    """
    if flag_value is None:
        return None
    if isinstance(flag_value, bool):
        return None
    try:
        raw = int(flag_value)
    except (TypeError, ValueError):
        return None
    if raw < 0:
        return None
    return SmapRetrievalQuality(
        raw=raw,
        bits=qc_bit_value(raw, SMAP_RETRIEVAL_QUALITY_MASK, 0),
    )
