"""Spatial aggregation with honest coverage reporting.

This module converts a raw Earth Engine reduction dictionary into a
:class:`SpatialStats`. Its job is not merely to rename keys: it is to
establish how much of the requested area the statistics actually
describe, and to refuse to present a statistic as representative when it
covers a sliver of the field.

Everything here except :func:`parse_reduction_result` and
:func:`build_reducer` is free of Earth Engine, so the parsing and
coverage logic is unit testable without credentials.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.services.agriculture.types import (
    ClassHistogram,
    ClassHistogramEntry,
    SpatialStats,
)

__all__ = [
    "STAT_KEYS",
    "PERCENTILE_VALUES",
    "build_reducer",
    "build_class_reducer",
    "parse_reduction_result",
    "parse_class_histogram",
    "merge_stats",
    "pixel_area_sq_m",
    "estimate_pixel_count",
]


#: Statistical keys this engine collects. Order is the order they are
#: requested from Earth Engine.
STAT_KEYS = (
    "mean",
    "median",
    "min",
    "max",
    "stdDev",
    "p10",
    "p25",
    "p75",
    "p90",
)

PERCENTILE_VALUES = (10, 25, 75, 90)


def build_reducer(ee_module: Any) -> Any:
    """Build the combined Earth Engine reducer used for spatial statistics.

    The reducer is built from an injected ``ee`` module rather than
    importing Earth Engine at module scope, so this file stays importable
    in environments without credentials.

    The chain leads with a ``count`` reducer, and this is not optional:
    :func:`parse_reduction_result` derives ``valid_pixel_count`` from the
    ``count`` key the combined reducer emits, and coverage — which every
    quality verdict downstream rests on — is a lie without it. A chain
    without ``count`` reduces perfectly good imagery into statistics that
    then report zero valid pixels and are discarded as insufficient.

    Collections include a median and four percentiles in addition to the
    usual mean and standard deviation: for vegetation indices the mean is
    often a poor summary of a field that is partly bare and partly
    cropped, and the percentiles expose that bimodality.
    """
    return (
        ee_module.Reducer.count()
        .combine(ee_module.Reducer.mean(), sharedInputs=True)
        .combine(ee_module.Reducer.median(), sharedInputs=True)
        .combine(ee_module.Reducer.stdDev(), sharedInputs=True)
        .combine(ee_module.Reducer.min(), sharedInputs=True)
        .combine(ee_module.Reducer.max(), sharedInputs=True)
        .combine(
            ee_module.Reducer.percentile(list(PERCENTILE_VALUES)),
            sharedInputs=True,
        )
    )


def _clean(value: Any) -> Optional[float]:
    """Coerce a raw reduction value to a finite float, or None.

    Earth Engine may return ``None``, a non-finite value, or a stringified
    number depending on how the result was serialised. Anything unusable
    becomes ``None`` so it can never be mistaken for a measurement.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def parse_reduction_result(
    raw: Mapping[str, Any],
    band: Optional[str] = None,
    total_pixel_count: int = 0,
    valid_pixel_count: Optional[int] = None,
    pixel_area_sq_m: float = 0.0,
    band_spec: Any = None,
) -> SpatialStats:
    """Convert an Earth Engine reduction dictionary into :class:`SpatialStats`.

    Args:
        raw: The dictionary returned by ``reduceRegion``, either flat or
            namespaced by band.
        band: When provided, statistics are read from keys of the form
            ``"<band>_<stat>"``. When ``None``, flat keys are read.
        total_pixel_count: Number of pixels the geometry covers, including
            masked ones. Used to derive missing percentage.
        valid_pixel_count: Number of unmasked pixels. If ``None``, derived
            from the ``count`` key when present, else left at zero.
        pixel_area_sq_m: Area of one pixel in square metres, used to
            report valid area.
        band_spec: The :class:`BandSpec` for the reduced band. When
            supplied, every statistic is converted from raw stored units
            to physical units using the band's declared ``scale_factor``
            and ``offset``, and raw nodata sentinels are dropped.

            This is the single boundary where that conversion happens, and
            passing it is what makes the returned numbers physical. A
            caller that omits it receives raw stored values, which for a
            MODIS LST band means counts of about 15000 rather than a
            temperature of about 300 K. Two quantities are never
            converted: ``count``, which is a pixel tally, and the spread,
            which does not take an offset.

    Returns:
        A populated :class:`SpatialStats`. A reduction in which every
        statistic is null yields a stats object with ``valid_pixel_count``
        of zero and no values, which callers must treat as insufficient
        data rather than as zero.
    """
    stats = SpatialStats()

    def convert(value: Optional[float]) -> Optional[float]:
        """Apply the band's raw-to-physical conversion, if one was given."""
        if band_spec is None:
            return value
        return band_spec.to_physical(value)

    def lookup(stat: str) -> Optional[float]:
        # Earth Engine combines reducers under suffixed names, and the
        # percentile reducer emits keys like "p10".
        if band is not None:
            for candidate in (
                f"{band}_{stat}",
                f"{band}_{stat}_1km",
                stat,
            ):
                if candidate in raw:
                    return _clean(raw.get(candidate))
            return None
        return _clean(raw.get(stat))

    stats.mean = convert(lookup("mean"))
    stats.median = convert(lookup("median"))
    stats.min = convert(lookup("min"))
    stats.max = convert(lookup("max"))
    # The spread does not take an offset, so it is only converted when the
    # conversion is a pure scale factor.
    std_dev = lookup("stdDev")
    if band_spec is not None and std_dev is not None:
        offset = getattr(band_spec, "offset", 0.0) or 0.0
        scale = getattr(band_spec, "scale_factor", 1.0) or 1.0
        std_dev = std_dev * scale if offset == 0.0 else None
    stats.std_dev = std_dev
    stats.p10 = convert(lookup("p10"))
    stats.p25 = convert(lookup("p25"))
    stats.p75 = convert(lookup("p75"))
    stats.p90 = convert(lookup("p90"))

    # Valid pixel count: prefer what we were told, else read 'count'.
    if valid_pixel_count is None:
        count_value = lookup("count")
        valid_pixel_count = int(count_value) if count_value is not None else 0
    if valid_pixel_count < 0:
        valid_pixel_count = 0

    # If Earth Engine reported no statistics at all, there are no valid
    # pixels regardless of what the caller passed. Trust the data.
    if stats.mean is None and all(
        getattr(stats, key) is None
        for key in ("median", "min", "max", "std_dev")
    ):
        valid_pixel_count = 0 if valid_pixel_count is None else valid_pixel_count

    stats.valid_pixel_count = valid_pixel_count
    stats.total_pixel_count = max(total_pixel_count, valid_pixel_count)
    stats.valid_area_sq_m = valid_pixel_count * float(pixel_area_sq_m or 0.0)

    if stats.total_pixel_count > 0:
        stats.missing_pixel_count = stats.total_pixel_count - valid_pixel_count
        if stats.missing_pixel_count < 0:
            stats.missing_pixel_count = 0
        stats.missing_percent = (
            stats.missing_pixel_count / stats.total_pixel_count * 100.0
        )
    else:
        stats.missing_pixel_count = 0
        stats.missing_percent = 0.0

    return stats


def pixel_area_sq_m(scale_m: float) -> float:
    """Area of one pixel at a given scale, in square metres."""
    if scale_m is None or scale_m <= 0:
        return 0.0
    return float(scale_m) * float(scale_m)


def estimate_pixel_count(
    area_sq_m: Optional[float],
    scale_m: float,
) -> int:
    """Estimate how many pixels of a given scale cover an area.

    This is an estimate derived from the geometry's area, not a count of
    pixels Earth Engine actually visited. It is used as the denominator
    for coverage, so it is deliberately conservative: the result is
    rounded down to avoid understating the missing percentage.
    """
    if not area_sq_m or area_sq_m <= 0:
        return 0
    area_per_pixel = pixel_area_sq_m(scale_m)
    if area_per_pixel <= 0:
        return 0
    return int(area_sq_m / area_per_pixel)


def merge_stats(
    stats_list: Sequence[SpatialStats],
    weights: Optional[Sequence[float]] = None,
) -> SpatialStats:
    """Merge several :class:`SpatialStats` into one.

    Used when a metric aggregates across time steps. The mean is combined
    as a weighted average; extremes and percentiles are combined as
    min-of-min and max-of-max, because a percentile of a set of
    percentiles is not a percentile.

    Coverage counts are summed.
    """
    usable = [s for s in stats_list if s is not None]
    if not usable:
        return SpatialStats()

    if weights is None:
        weights = [1.0] * len(usable)
    if len(weights) != len(usable):
        raise ValueError(
            f"weights length {len(weights)} does not match stats count "
            f"{len(usable)}"
        )

    merged = SpatialStats(
        valid_pixel_count=sum(s.valid_pixel_count for s in usable),
        total_pixel_count=sum(s.total_pixel_count for s in usable),
        valid_area_sq_m=sum(s.valid_area_sq_m for s in usable),
    )
    # missing_pixel_count and missing_percent are derived by __post_init__,
    # so they stay consistent with the counts above.

    # Weighted mean over the stats that actually carry a mean.
    pairs = [
        (s.mean, w)
        for s, w in zip(usable, weights)
        if s.mean is not None and w > 0
    ]
    if pairs:
        total_weight = sum(w for _, w in pairs)
        if total_weight > 0:
            merged.mean = sum(m * w for m, w in pairs) / total_weight

    # Medians: average of medians is not a median, so only report one when
    # every input had one, and label it as an approximation by averaging.
    medians = [s.median for s in usable if s.median is not None]
    if medians and len(medians) == len(usable):
        merged.median = sum(medians) / len(medians)

    # Extremes: taken across all inputs.
    mins = [s.min for s in usable if s.min is not None]
    maxes = [s.max for s in usable if s.max is not None]
    merged.min = min(mins) if mins else None
    merged.max = max(maxes) if maxes else None

    # Standard deviation across merged means, as a spread measure.
    if len(pairs) >= 2:
        mean_value = merged.mean
        if mean_value is not None:
            total_weight = sum(w for _, w in pairs)
            variance = (
                sum(w * (m - mean_value) ** 2 for m, w in pairs) / total_weight
            )
            merged.std_dev = math.sqrt(max(variance, 0.0))

    # Percentiles across inputs, only when all inputs supplied them.
    for key in ("p10", "p25", "p75", "p90"):
        values = [getattr(s, key) for s in usable]
        if all(v is not None for v in values):
            setattr(merged, key, sum(values) / len(values))  # type: ignore[arg-type]

    return merged


# --------------------------------------------------------------------------
# Categorical aggregation
# --------------------------------------------------------------------------
#
# A land-cover class code is a label, not a measurement. Class 4 is not
# "twice class 2", so none of the statistics above apply: a mean class
# code is a number that describes nothing, and a median picks an arbitrary
# midpoint of an unordered set.
#
# The only defensible summary of a categorical map is a count of pixels
# per class. Everything below exists to produce that count honestly.


def build_class_reducer(ee_module: Any) -> Any:
    """Build the Earth Engine reducer for a categorical band.

    A histogram, not a set of moments. The histogram's bucket boundaries
    are supplied by the caller through the band's declared class range,
    because the reducer has to be told the full domain up front: a
    histogram built from only the classes present in one field would
    produce a different bucket layout for every field, and the results
    would no longer be comparable between geometries.

    The reducer is built from an injected ``ee`` module so this file stays
    importable without the Earth Engine package.
    """
    return ee_module.Reducer.frequencyHistogram()


def _unwrap_band_nesting(raw_counts: Any, band: Optional[str] = None) -> Any:
    """Peel a band-name wrapper off a histogram payload.

    A histogram over one selected band arrives flat; one that the client
    has nested under the band name arrives as ``{band: {code: count}}``.
    Passing the nested form through as though it were flat produces an
    empty histogram, which is indistinguishable from a genuinely unlabelled
    area. This resolves the shape in one place so a caller cannot forget to.

    Only a dictionary whose *every* value is itself a dictionary is
    unwrapped, and only the single-key case is unwrapped when no band name
    was given. A flat histogram's values are counts, never dictionaries, so
    this cannot mistake one for the other.
    """
    if not isinstance(raw_counts, Mapping):
        return raw_counts

    if band is not None and band in raw_counts:
        inner = raw_counts[band]
        if isinstance(inner, Mapping):
            return inner
        return raw_counts

    # No band name supplied: unwrap only the unambiguous single-wrapper case.
    if len(raw_counts) == 1:
        ((_only_key, only_value),) = raw_counts.items()
        if isinstance(only_value, Mapping):
            return only_value

    return raw_counts


def parse_class_histogram(
    raw_counts: Any,
    class_names: Mapping[int, str],
    total_pixel_count: int = 0,
    drop_codes: Iterable[int] = (),
    band: Optional[str] = None,
) -> ClassHistogram:
    """Convert a frequency-histogram reduction into a :class:`ClassHistogram`.

    Args:
        raw_counts: The ``ee.Dictionary`` returned by a histogram
            reduction, already read back with ``getInfo()``. Earth Engine
            serialises histogram keys as *strings*, so they are parsed
            back to integers here; a key that will not parse is dropped
            rather than coerced, because a silently mangled class code
            would be attributed to the wrong class.

            Two shapes reach this function and both are handled here
            rather than by a caller guessing between them. A reduction over
            a single selected band yields ``{"12": 300, "17": 100}``. A
            reduction that the client nests under the band name yields
            ``{"LC_Type1": {"12": 300}}``. The difference matters: a nested
            dictionary passed through as though it were flat has no
            parseable keys and silently yields an empty histogram, which
            looks exactly like an area with no land cover. Resolving the
            shape here means that failure mode is impossible to reach by
            forgetting an unwrap in a caller.
        class_names: The product's own code-to-name table. A code absent
            from this table is still reported, under a placeholder name,
            because dropping it would hide area that genuinely exists and
            make the percentages disagree with the coverage figures.
        total_pixel_count: Pixels the geometry covered, including masked
            ones. Used for ``percent_of_geometry``.
        drop_codes: Codes to exclude entirely, used for mask sentinels
            that a product stores inside the class band.
        band: The band the histogram was taken over. Used only to recognise
            the nested shape; when omitted, a single-key dictionary whose
            value is itself a dictionary is unwrapped anyway, since a
            histogram of class codes is never a dictionary of dictionaries.

    Returns:
        A :class:`ClassHistogram` with entries sorted by descending pixel
        count, so the dominant class is first and the ordering is stable
        for identical input.

    Percentages are computed against the valid (classified) pixel total,
    not against the geometry, because those are different questions: the
    first says how the classified area is composed, the second says how
    much of the field the classification actually reached. Both are
    reported, and neither is allowed to stand in for the other.
    """
    histogram = ClassHistogram()

    if raw_counts is None:
        return histogram

    raw_counts = _unwrap_band_nesting(raw_counts, band)

    drop = {int(code) for code in drop_codes}
    counted: Dict[int, int] = {}

    if isinstance(raw_counts, Mapping):
        items = raw_counts.items()
    elif isinstance(raw_counts, (list, tuple)):
        # Some serialisations arrive as a list of [value, count] pairs.
        pairs = []
        for item in raw_counts:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((item[0], item[1]))
        items = pairs
    else:
        return histogram

    for raw_code, raw_count in items:
        code = _clean_class_code(raw_code)
        if code is None or code in drop:
            continue
        count = _clean(raw_count)
        if count is None or count <= 0:
            # A class with zero pixels carries no information, and
            # including it would pad the histogram with empty rows.
            continue
        counted[code] = counted.get(code, 0) + int(count)

    valid_total = sum(counted.values())

    entries: List[ClassHistogramEntry] = []
    for code, count in counted.items():
        percent = (count / valid_total * 100.0) if valid_total > 0 else 0.0
        percent_geometry = (
            count / total_pixel_count * 100.0 if total_pixel_count > 0 else 0.0
        )
        entries.append(
            ClassHistogramEntry(
                code=code,
                name=class_names.get(code, f"Unknown class {code}"),
                pixel_count=count,
                percent=percent,
                percent_of_geometry=percent_geometry,
            )
        )

    # Descending by pixel count, then by code, so equal extents produce a
    # deterministic order rather than depending on dict insertion order.
    entries.sort(key=lambda e: (-e.pixel_count, e.code))

    histogram.entries = entries
    histogram.valid_pixel_count = valid_total
    histogram.total_pixel_count = max(int(total_pixel_count or 0), valid_total)
    if entries:
        histogram.dominant_code = entries[0].code
        histogram.dominant_name = entries[0].name

    return histogram


def _clean_class_code(value: Any) -> Optional[int]:
    """Parse a histogram key into an integer class code, or ``None``.

    Accepts ``"12"``, ``12`` and ``12.0``. Rejects booleans explicitly,
    since ``bool`` is an ``int`` subclass and ``True`` would otherwise
    become class 1. A value that is not an exact integer is rejected
    rather than rounded: a fractional class code means the band was not
    categorical, and rounding it would invent a class.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                numeric = float(text)
            except ValueError:
                return None
            if not math.isfinite(numeric) or numeric != int(numeric):
                return None
            return int(numeric)
    return None
