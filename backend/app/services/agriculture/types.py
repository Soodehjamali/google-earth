"""Core types for the Agricultural Intelligence Engine.

This module defines the shared vocabulary used by every metric provider.
Nothing here touches Earth Engine or the network, so it is fully unit
testable in isolation.

Design principles enforced by these types:

1. Every metric result carries provenance. A number without a source is
   not a result, it is a guess.
2. Every metric result carries a quality level. Missing data is reported
   as ``insufficient_data`` or ``unavailable``, never silently as zero.
3. Proxies are named as proxies. ``CWSI_proxy`` can never be published
   under the name ``CWSI``.
4. Measurement basis is explicit. A reanalysis-modelled temperature is
   never presented as a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "QualityLevel",
    "MeasurementBasis",
    "AggregationMethod",
    "TemporalKind",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_UNAVAILABLE",
    "STATUS_ERROR",
    "NOT_AVAILABLE_REASON_INSUFFICIENT",
    "NOT_AVAILABLE_REASON_OUT_OF_COVERAGE",
    "NOT_AVAILABLE_REASON_UNSUPPORTED",
    "NOT_AVAILABLE_REASON_ERROR",
    "BandSpec",
    "DatasetSpec",
    "SpatialStats",
    "ClassHistogram",
    "ClassHistogramEntry",
    "Provenance",
    "MetricResult",
    "PENDING_VERIFICATION",
]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class QualityLevel(str, Enum):
    """Data quality assessment, as required by the specification.

    Exactly six levels. ``INSUFFICIENT`` and ``UNAVAILABLE`` are distinct
    on purpose: the first means we tried and the data was too sparse, the
    second means we could not attempt the computation at all.
    """

    EXCELLENT = "excellent"
    GOOD = "good"
    MODERATE = "moderate"
    POOR = "poor"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"

    @property
    def is_usable(self) -> bool:
        """Whether a value at this quality level should be surfaced to users."""
        return self in (
            QualityLevel.EXCELLENT,
            QualityLevel.GOOD,
            QualityLevel.MODERATE,
        )

    @property
    def needs_caveat(self) -> bool:
        """Whether a non-null value at this level must be shown with a warning."""
        return self in (QualityLevel.POOR, QualityLevel.MODERATE)


class MeasurementBasis(str, Enum):
    """How a value came to exist.

    This exists so we never present a modelled reanalysis value with the
    same confidence as a direct satellite measurement. The spec requires
    these distinctions to be explicit and visible.
    """

    DIRECT = "direct"
    """Measured by an instrument. e.g. Sentinel-2 surface reflectance."""

    PRODUCT = "product"
    """A derived science product from an agency. e.g. MODIS LAI, MOD16 ET."""

    DERIVED = "derived"
    """Computed from direct inputs by a deterministic formula we control.
    e.g. VPD from temperature and dewpoint, GDD from Tmin/Tmax."""

    MODELLED = "modelled"
    """Output of a physical or statistical model, possibly reanalysis.
    e.g. ERA5-Land temperature, TerraClimate PET."""

    PROXY = "proxy"
    """An indirect stand-in for the quantity of interest. Carries the
    weakest inference. e.g. spectral salinity index as a salinity proxy."""

    INFERENCE = "inference"
    """A qualitative interpretation layered on top of measurements.
    e.g. 'vegetation stress' inferred from a sustained NDVI decline."""

    @property
    def requires_disclaimer(self) -> bool:
        """Bases that must always be accompanied by an explicit caveat."""
        return self in (
            MeasurementBasis.MODELLED,
            MeasurementBasis.PROXY,
            MeasurementBasis.INFERENCE,
        )


class AggregationMethod(str, Enum):
    """Spatial aggregation methods supported for a metric."""

    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    STD_DEV = "stdDev"
    P10 = "p10"
    P25 = "p25"
    P75 = "p75"
    P90 = "p90"


class TemporalKind(str, Enum):
    """What a dataset's declared date range actually means.

    The registry stores two dates for every dataset, but those dates do
    not mean the same thing for every kind of product. A daily satellite
    series is only able to answer questions about days between its first
    and last observation. A static surface — an elevation model, a soil
    map — describes the ground as it was when it was surveyed, and that
    description remains valid for questions asked about any later date.

    Treating both as an observation window makes the engine refuse every
    realistic request against a static product: asking for terrain in 2024
    would fail because the radar flew in 2000. Treating both as always
    valid would be worse, because a request for Sentinel-2 imagery from
    1990 would then be answered with silence instead of an explanation.

    So the distinction is explicit and per-dataset, and it is stored
    beside the dates it qualifies.
    """

    OBSERVATION = "observation"
    """The dates bound when observations exist.

    A request outside them cannot be answered and is rejected as
    out-of-coverage. This is the meaning for every time series, and it is
    the default, so a dataset registered without thinking about it keeps
    the behaviour it has always had.
    """

    STATIC = "static"
    """The dates record when the product was made, not when it is valid.

    The dataset is not a time series. It carries no time dimension, and
    its acquisition or reference date does not restrict which analysis
    dates it can inform. A request for any well-formed period may proceed;
    the requested period is reported as the period the user asked about,
    never as though it were the product's observation window.
    """


# --------------------------------------------------------------------------
# Status constants
# --------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"

# Machine-readable reasons for an ``unavailable`` status.
NOT_AVAILABLE_REASON_INSUFFICIENT = "insufficient_data"
NOT_AVAILABLE_REASON_OUT_OF_COVERAGE = "outside_temporal_coverage"
NOT_AVAILABLE_REASON_UNSUPPORTED = "not_supported"
NOT_AVAILABLE_REASON_ERROR = "computation_error"

#: Sentinel used in the registry for a parameter that is structurally known
#: but whose exact literal value could not be verified against an official
#: source. Never substitute a plausible-looking number for this.
PENDING_VERIFICATION = "__PENDING_VERIFICATION__"


# --------------------------------------------------------------------------
# Dataset specification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BandSpec:
    """A single band of a dataset, with everything needed to read it correctly.

    ``scale_factor`` and ``offset`` convert raw stored values to physical
    units::

        physical = raw * scale_factor + offset
    """

    name: str
    description: str
    unit: str
    scale_factor: float = 1.0
    offset: float = 0.0
    valid_range: Optional[Tuple[float, float]] = None
    nodata_values: Tuple[float, ...] = ()

    def to_physical(self, raw_value: Optional[float]) -> Optional[float]:
        """Convert a raw band value into physical units.

        Returns ``None`` for ``None``, for nodata sentinels, and for
        non-finite input, so callers cannot accidentally treat a nodata
        value as a real measurement.

        Booleans are rejected explicitly. ``bool`` is a subclass of ``int``
        in Python, so without this guard ``to_physical(True)`` would
        silently return ``scale_factor`` as though it were a measurement.
        """
        if raw_value is None:
            return None
        # bool must be rejected before the numeric check, since bool is an int.
        if isinstance(raw_value, bool):
            return None
        if not isinstance(raw_value, (int, float)):
            return None
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            return None
        if raw_value in self.nodata_values:
            return None
        return float(raw_value) * self.scale_factor + self.offset


@dataclass(frozen=True)
class DatasetSpec:
    """A verified dataset in the central registry.

    Every field here must be confirmable against the GEE Data Catalog or
    official agency documentation. Fields that could not be verified carry
    :data:`PENDING_VERIFICATION` or are documented as unverified in
    ``caveats``.
    """

    id: str
    name: str
    name_fa: str
    provider: str
    description: str

    spatial_resolution: str
    temporal_resolution: str
    available_from: str
    available_to: Optional[str] = None

    #: What ``available_from`` and ``available_to`` mean for this dataset.
    #:
    #: Defaults to :attr:`TemporalKind.OBSERVATION`, which is the
    #: behaviour every dataset had before this field existed. A dataset is
    #: never silently reclassified: marking one STATIC is an explicit,
    #: reviewable edit to its registration.
    temporal_kind: TemporalKind = TemporalKind.OBSERVATION

    bands: Dict[str, BandSpec] = field(default_factory=dict)

    measurement_basis: MeasurementBasis = MeasurementBasis.DIRECT

    cloud_mask_method: Optional[str] = None
    cloud_mask_band: Optional[str] = None

    #: Roles this dataset can serve, e.g. {"primary", "fallback", "proxy"}.
    roles: Tuple[str, ...] = ("primary",)

    #: Human-readable limitations. Surfaced verbatim in API responses.
    caveats: Tuple[str, ...] = ()

    citation: str = ""
    docs_url: str = ""

    def __post_init__(self) -> None:
        # A registration that asks for STATIC semantics must say, in its
        # own temporal_resolution string, that it is static. Without this
        # the two descriptions can drift and a reader comparing them would
        # have to guess which one the engine actually obeyed.
        if (
            self.temporal_kind is TemporalKind.STATIC
            and "static" not in (self.temporal_resolution or "").lower()
        ):
            raise ValueError(
                f"Dataset {self.id!r} is declared temporal_kind=STATIC but "
                f"its temporal_resolution is {self.temporal_resolution!r}, "
                "which does not describe it as static. The two must agree "
                "so that a reader cannot be misled about which dates the "
                "engine treats as an observation window."
            )
        # The same rule in the other direction. An OBSERVATION dataset
        # whose temporal_resolution claims to be static is the identical
        # contradiction wearing the opposite sign: the description says
        # the dates are mere provenance while the engine treats them as a
        # coverage gate, and only one of those can be true.
        if (
            self.temporal_kind is TemporalKind.OBSERVATION
            and "static" in (self.temporal_resolution or "").lower()
        ):
            raise ValueError(
                f"Dataset {self.id!r} is declared temporal_kind=OBSERVATION "
                f"but its temporal_resolution is "
                f"{self.temporal_resolution!r}, which describes it as "
                "static. Either the dates are an observation window or "
                "they are provenance; declare the kind that matches."
            )

    @property
    def is_static(self) -> bool:
        """Whether this dataset is a static surface rather than a series."""
        return self.temporal_kind is TemporalKind.STATIC

    def band(self, name: str) -> BandSpec:
        """Look up a band, raising a clear error naming the dataset."""
        try:
            return self.bands[name]
        except KeyError:
            available = ", ".join(sorted(self.bands)) or "(none registered)"
            raise KeyError(
                f"Band {name!r} is not registered for dataset {self.id!r}. "
                f"Available bands: {available}"
            ) from None

    def has_band(self, name: str) -> bool:
        return name in self.bands

    @property
    def is_verified(self) -> bool:
        """False if any band still carries an unverified parameter.

        A dataset is only verified when every band's conversion parameters
        have been confirmed against an official source. This is checked on
        both the band scale factor and the band's own nodata declaration,
        since either can carry the pending sentinel.
        """
        for band in self.bands.values():
            if band.scale_factor == PENDING_VERIFICATION:
                return False
            if band.offset == PENDING_VERIFICATION:
                return False
            if PENDING_VERIFICATION in band.nodata_values:
                return False
        return True


# --------------------------------------------------------------------------
# Spatial statistics
# --------------------------------------------------------------------------


@dataclass
class SpatialStats:
    """Aggregated statistics over a geometry, plus coverage information.

    Coverage fields exist so a caller can distinguish "no vegetation here"
    from "we could not see here". Collapsing those two into a single zero
    is the single most common way satellite analytics mislead people.

    ``missing_pixel_count`` and ``missing_percent`` are derived from
    ``valid_pixel_count`` and ``total_pixel_count``. They are recomputed
    on construction so a hand-built instance cannot sit in a state where
    the numbers contradict each other, for example valid 50 of a total
    100 but missing 0.
    """

    mean: Optional[float] = None
    median: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    std_dev: Optional[float] = None
    p10: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None

    valid_pixel_count: int = 0
    valid_area_sq_m: float = 0.0
    total_pixel_count: int = 0
    missing_pixel_count: int = 0
    missing_percent: float = 0.0

    def __post_init__(self) -> None:
        # Normalise the coverage triple so it is always self-consistent.
        self.valid_pixel_count = max(0, int(self.valid_pixel_count or 0))
        self.total_pixel_count = max(0, int(self.total_pixel_count or 0))

        # A total can never be smaller than the number of valid pixels.
        if self.total_pixel_count < self.valid_pixel_count:
            self.total_pixel_count = self.valid_pixel_count

        if self.total_pixel_count > 0:
            self.missing_pixel_count = (
                self.total_pixel_count - self.valid_pixel_count
            )
            self.missing_percent = (
                self.missing_pixel_count / self.total_pixel_count * 100.0
            )
        else:
            self.missing_pixel_count = 0
            self.missing_percent = 0.0

    @property
    def has_values(self) -> bool:
        return self.valid_pixel_count > 0 and self.mean is not None

    @property
    def coverage_percent(self) -> float:
        """Percentage of the requested geometry with usable data."""
        if self.total_pixel_count <= 0:
            return 0.0
        return 100.0 - self.missing_percent

    def to_dict(self) -> Dict[str, Any]:
        """Serialise, dropping null statistics to keep payloads small."""
        out: Dict[str, Any] = {}
        for key in (
            "mean", "median", "min", "max", "std_dev",
            "p10", "p25", "p75", "p90",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        out["valid_pixel_count"] = self.valid_pixel_count
        out["valid_area_sq_m"] = self.valid_area_sq_m
        out["missing_pixel_count"] = self.missing_pixel_count
        out["total_pixel_count"] = self.total_pixel_count
        out["missing_percent"] = self.missing_percent
        out["coverage_percent"] = self.coverage_percent
        return out


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


@dataclass
class Provenance:
    """The full derivation record for a metric.

    The specification requires every output to state its source dataset,
    bands, formula, unit, resolution, aggregation, and limitations. This
    object is where that lives.
    """

    source_dataset_id: str
    source_dataset_name: str
    bands: List[str] = field(default_factory=list)
    formula: str = ""
    unit: str = ""

    spatial_resolution: str = ""
    temporal_resolution: str = ""
    aggregation_method: str = ""

    measurement_basis: MeasurementBasis = MeasurementBasis.DIRECT
    quality_level: QualityLevel = QualityLevel.UNAVAILABLE

    #: What the source dataset's dates mean, carried through so a reader
    #: of a single result can tell whether ``date_start``/``date_end``
    #: below describe an observation window or merely the period the user
    #: asked about.
    temporal_kind: TemporalKind = TemporalKind.OBSERVATION

    #: The period the *caller* asked about. Always populated, for every
    #: kind of dataset, because it is what the user requested and is
    #: therefore never the thing in doubt.
    requested_start: Optional[str] = None
    requested_end: Optional[str] = None

    #: When the source product was actually produced or acquired.
    #:
    #: Only meaningful for a STATIC dataset, where this is the honest
    #: answer to "when is this from?" and is deliberately *not* the
    #: requested period. Left empty for OBSERVATION datasets, whose
    #: coverage is already described by the requested period and the
    #: dataset's own window.
    product_date: Optional[str] = None

    date_start: Optional[str] = None
    date_end: Optional[str] = None
    image_count: Optional[int] = None

    #: Set when this metric was served by a fallback rather than the
    #: preferred source, naming which source was preferred.
    fallback_from: Optional[str] = None

    limitations: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    citation: str = ""

    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_dataset_id": self.source_dataset_id,
            "source_dataset_name": self.source_dataset_name,
            "bands": list(self.bands),
            "formula": self.formula,
            "unit": self.unit,
            "spatial_resolution": self.spatial_resolution,
            "temporal_resolution": self.temporal_resolution,
            "temporal_kind": self.temporal_kind.value,
            "aggregation_method": self.aggregation_method,
            "measurement_basis": self.measurement_basis.value,
            "quality_level": self.quality_level.value,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "product_date": self.product_date,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "image_count": self.image_count,
            "fallback_from": self.fallback_from,
            "limitations": list(self.limitations),
            "caveats": list(self.caveats),
            "citation": self.citation,
            "computed_at": self.computed_at,
        }


# --------------------------------------------------------------------------
# Categorical results
# --------------------------------------------------------------------------


@dataclass
class ClassHistogramEntry:
    """One class of a categorical product, with its extent.

    A land-cover class code is a *label*, not a quantity. Class 4 is not
    "twice class 2" and a mean of class codes is a number that describes
    nothing. Categorical products therefore cannot be summarised with the
    continuous statistics in :class:`SpatialStats`, and reporting one as
    the other is the categorical equivalent of reporting a temperature in
    the wrong unit.

    This type is the smallest representation that is still honest: the
    class code as published by the product, the number of pixels the
    reduction actually observed, and the two derived fractional measures.
    Area is deliberately not stored, because pixel area depends on the
    reduction scale and is already available to a caller from the pixel
    count and the provenance's declared resolution; storing it here would
    duplicate a number that could then drift out of agreement.
    """

    #: The class code exactly as the product publishes it. Never
    #: remapped, never renumbered, never offset.
    code: int

    #: Human-readable class name from the product's own class table.
    name: str = ""

    #: Pixels of this class the reduction observed.
    pixel_count: int = 0

    #: Share of the valid (classified) area, 0-100. Derived.
    percent: float = 0.0

    #: Share of the *requested* geometry, 0-100, including unclassified
    #: and masked pixels. Distinct from ``percent`` on purpose: a class
    #: covering half the field but only a quarter of what was visible is
    #: two different statements and a caller needs both.
    percent_of_geometry: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "pixel_count": self.pixel_count,
            "percent": self.percent,
            "percent_of_geometry": self.percent_of_geometry,
        }


@dataclass
class ClassHistogram:
    """The full class distribution of a categorical reduction.

    Held separately from :class:`SpatialStats` so that no continuous
    statistic can ever be computed from class codes by accident.
    """

    entries: List[ClassHistogramEntry] = field(default_factory=list)

    #: The class with the largest share of valid area. ``None`` when no
    #: class was observed, which is not the same as "class 0".
    dominant_code: Optional[int] = None
    dominant_name: str = ""

    #: Pixels that carried a class label.
    valid_pixel_count: int = 0

    #: Pixels the geometry covered, including masked and unclassified.
    total_pixel_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "dominant_code": self.dominant_code,
            "dominant_name": self.dominant_name,
            "valid_pixel_count": self.valid_pixel_count,
            "total_pixel_count": self.total_pixel_count,
        }


# --------------------------------------------------------------------------
# Metric result
# --------------------------------------------------------------------------


@dataclass
class MetricResult:
    """The single return type of every metric provider.

    A ``MetricResult`` is always well formed, even when the metric could
    not be computed. That is deliberate: callers never have to guess
    whether a missing key means "zero" or "we don't know".
    """

    metric_key: str
    display_name: str
    display_name_fa: str

    status: str = STATUS_OK
    value: Optional[float] = None
    stats: Optional[SpatialStats] = None

    #: Class distribution for categorical metrics that carry no numeric
    #: value. Optional and defaulted so every existing continuous metric
    #: is unaffected by its presence.
    #:
    #: A metric may populate this *or* ``stats`` or ``value``; a
    #: categorical metric that also reported a mean class code would be
    #: publishing a number with no meaning, so the two are mutually
    #: exclusive and enforced in ``__post_init__``.
    class_histogram: Optional[ClassHistogram] = None

    #: Per-band mean probabilities for the Dynamic World probability
    #: metric, keyed by the canonical band names. Structured computed
    #: data carried alongside the scalar value — never parsed from
    #: warning strings. None for every other metric.
    band_means: Optional[Dict[str, Optional[float]]] = None

    unit: str = ""
    provenance: Optional[Provenance] = None

    #: Why the metric is unavailable, when status is not ``ok``.
    reason: Optional[str] = None
    #: Human-readable explanation, safe to show to an end user.
    message: Optional[str] = None
    #: Non-fatal problems encountered while producing a usable value.
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Guard the core safety property: a usable numeric value must be
        # backed by provenance and must not sit under a quality level that
        # means "we have no value to report".
        #
        # Both UNAVAILABLE and INSUFFICIENT mean "no number exists". The
        # difference between them is why we have no number, not whether we
        # do, so a value under either level is a contradiction.
        if self.value is not None and self.provenance is None:
            raise ValueError(
                f"Metric {self.metric_key!r} carries a value but no "
                "provenance. Refusing to construct an unattributable result."
            )
        if self.value is not None and self.provenance is not None:
            forbidden = (
                QualityLevel.UNAVAILABLE,
                QualityLevel.INSUFFICIENT,
            )
            if self.provenance.quality_level in forbidden:
                raise ValueError(
                    f"Metric {self.metric_key!r} carries a value but its "
                    f"provenance says quality is "
                    f"'{self.provenance.quality_level.value}', which means no "
                    "value should exist. Contradictory result."
                )

        # A class histogram is a result in its own right, so it must be
        # attributable exactly like a numeric value is.
        if self.class_histogram is not None and self.provenance is None:
            raise ValueError(
                f"Metric {self.metric_key!r} carries a class histogram but "
                "no provenance. Refusing to construct an unattributable "
                "result."
            )
        if (
            self.class_histogram is not None
            and self.provenance is not None
            and self.provenance.quality_level
            in (QualityLevel.UNAVAILABLE, QualityLevel.INSUFFICIENT)
        ):
            raise ValueError(
                f"Metric {self.metric_key!r} carries a class histogram but "
                f"its provenance says quality is "
                f"'{self.provenance.quality_level.value}', which means no "
                "result should exist. Contradictory result."
            )

        # Categorical and continuous summaries must not be mixed for the
        # same quantity: a mean of land-cover class codes is meaningless.
        if self.class_histogram is not None and self.value is not None:
            raise ValueError(
                f"Metric {self.metric_key!r} carries both a class histogram "
                "and a numeric value. A categorical product has no numeric "
                "value; pick one representation."
            )

    # -- constructors ------------------------------------------------------

    @classmethod
    def unavailable(
        cls,
        metric_key: str,
        display_name: str,
        display_name_fa: str,
        reason: str = NOT_AVAILABLE_REASON_UNSUPPORTED,
        message: str = "",
        unit: str = "",
        provenance: Optional[Provenance] = None,
    ) -> "MetricResult":
        """Build an explicitly unavailable result.

        If provenance is supplied its quality level is forced to
        ``UNAVAILABLE`` so the record stays self-consistent.
        """
        if provenance is not None:
            provenance.quality_level = QualityLevel.UNAVAILABLE
        return cls(
            metric_key=metric_key,
            display_name=display_name,
            display_name_fa=display_name_fa,
            status=STATUS_UNAVAILABLE,
            value=None,
            unit=unit,
            provenance=provenance,
            reason=reason,
            message=message,
        )

    @classmethod
    def insufficient(
        cls,
        metric_key: str,
        display_name: str,
        display_name_fa: str,
        message: str,
        unit: str = "",
        provenance: Optional[Provenance] = None,
    ) -> "MetricResult":
        """Build a result meaning 'we tried, but there was not enough data'."""
        if provenance is not None:
            provenance.quality_level = QualityLevel.INSUFFICIENT
        return cls(
            metric_key=metric_key,
            display_name=display_name,
            display_name_fa=display_name_fa,
            status=STATUS_INSUFFICIENT_DATA,
            value=None,
            unit=unit,
            provenance=provenance,
            reason=NOT_AVAILABLE_REASON_INSUFFICIENT,
            message=message,
        )

    @classmethod
    def error(
        cls,
        metric_key: str,
        display_name: str,
        display_name_fa: str,
        message: str,
        unit: str = "",
    ) -> "MetricResult":
        """Build a result for a failed computation.

        The message must already be sanitised by the caller; it is returned
        to the client, so it must never contain credentials or stack traces.
        """
        return cls(
            metric_key=metric_key,
            display_name=display_name,
            display_name_fa=display_name_fa,
            status=STATUS_ERROR,
            value=None,
            unit=unit,
            reason=NOT_AVAILABLE_REASON_ERROR,
            message=message,
        )

    # -- derived properties ------------------------------------------------

    @property
    def is_usable(self) -> bool:
        """Whether the result carries a publishable result.

        A categorical result is usable when it carries a populated class
        histogram, just as a continuous one is usable when it carries a
        value. Requiring ``value`` alone would silently mark every
        land-cover result unusable.
        """
        # ``bool(...)`` rather than a bare truthiness test: ``and`` returns
        # the operand, so a histogram with no entries would otherwise make
        # this property return an empty list instead of ``False``.
        has_payload = self.value is not None or bool(
            self.class_histogram is not None
            and self.class_histogram.entries
        )
        return bool(
            self.status in (STATUS_OK, STATUS_PARTIAL)
            and has_payload
            and self.provenance is not None
            and self.provenance.quality_level.is_usable
        )

    @property
    def quality_level(self) -> QualityLevel:
        if self.provenance is None:
            return QualityLevel.UNAVAILABLE
        return self.provenance.quality_level

    @property
    def measurement_basis(self) -> MeasurementBasis:
        if self.provenance is None:
            return MeasurementBasis.DIRECT
        return self.provenance.measurement_basis

    @property
    def is_proxy(self) -> bool:
        return self.measurement_basis in (
            MeasurementBasis.PROXY,
            MeasurementBasis.INFERENCE,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "display_name": self.display_name,
            "display_name_fa": self.display_name_fa,
            "status": self.status,
            "value": self.value,
            "unit": self.unit,
            "stats": self.stats.to_dict() if self.stats else None,
            "class_histogram": (
                self.class_histogram.to_dict() if self.class_histogram else None
            ),
            "band_means": (
                dict(self.band_means) if self.band_means else None
            ),
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "reason": self.reason,
            "message": self.message,
            "warnings": list(self.warnings),
            "is_proxy": self.is_proxy,
            "measurement_basis": self.measurement_basis.value,
            "quality_level": self.quality_level.value,
        }
