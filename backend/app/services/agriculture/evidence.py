"""Cross-metric evidence composition and consistency layer (Phase O).

This module provides a reusable framework for evaluating whether multiple
existing observations can be considered mutually consistent and what
evidence they collectively provide.

**What this module is:**

An evidence-quality layer that answers:

* Are the selected metrics temporally comparable?
* Are they spatially comparable?
* Are their units compatible?
* Are their quality states acceptable?
* Do independent observations point in the same direction?
* Are there contradictions?
* Is there enough evidence to support a descriptive interpretation?
* Which evidence is unavailable or unreliable?

**What this module is NOT:**

* A diagnosis engine
* A prediction system
* A scoring system
* An automatic decision maker

**Scientific boundary:**

Never convert correlation or simultaneous anomalies into causality.
Multiple observations consistent with a condition do not automatically
prove that condition. Every output is descriptive.

**Design principles:**

* Reuse existing enums (QualityLevel, MeasurementBasis, TemporalKind)
* Never convert missing data to zero
* Never silently promote one evidence category into another
* Never force a combined interpretation
* Preserve each metric independently in bundles
* Document every rule and limitation

Architecture:

* ``EvidenceItem`` -- a single metric result with its context
* ``EvidenceBundle`` -- a collection of related evidence items
* ``TemporalAlignment`` / ``SpatialAlignment`` -- alignment assessments
* ``UnitCompatibility`` / ``QualityCompatibility`` -- compatibility checks
* ``RelationshipSpec`` -- an explicit directional relationship
* ``EvidenceConflict`` -- a detected inconsistency
* ``EvidenceSufficiency`` -- whether enough evidence exists
* ``RelationshipRegistry`` -- a catalog of known relationships
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Tuple,
)

from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)


# ---------------------------------------------------------------------------
# 1. Evidence status taxonomy
# ---------------------------------------------------------------------------


class EvidenceStatus(str, Enum):
    """How a metric value was produced, independent of its quality.

    This extends ``MeasurementBasis`` with composition-specific states.
    """

    OBSERVED = "observed"
    DERIVED = "derived"
    MODELLED = "modelled"
    PROXY = "proxy"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"


class AlignmentStatus(str, Enum):
    """Result of a temporal or spatial alignment check."""

    ALIGNED = "aligned"
    PARTIALLY_ALIGNED = "partially_aligned"
    INSUFFICIENT_OVERLAP = "insufficient_overlap"
    INCOMPATIBLE_RESOLUTION = "incompatible_resolution"
    FOOTPRINT_MISMATCH = "footprint_mismatch"
    INSUFFICIENT_VALID_AREA = "insufficient_valid_area"
    UNAVAILABLE = "unavailable"


class ConsistencyStatus(str, Enum):
    """Result of a directional consistency check."""

    CONSISTENT = "consistent"
    PARTIALLY_CONSISTENT = "partially_consistent"
    CONFLICTING = "conflicting"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SufficiencyLevel(str, Enum):
    """Whether enough evidence exists for a descriptive interpretation."""

    SUFFICIENT = "sufficient"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"


class ExpectedRelationship(str, Enum):
    """How two metrics are expected to move relative to each other."""

    SAME_DIRECTION = "same_direction"
    OPPOSITE_DIRECTION = "opposite_direction"
    CONDITIONAL = "conditional"
    NO_ASSUMED_RELATIONSHIP = "no_assumed_relationship"


class UnitCategory(str, Enum):
    """Semantic grouping of compatible unit families."""

    INDEX = "index"
    FRACTION = "fraction"
    LENGTH_MM = "length_mm"
    TEMPERATURE_C = "temperature_c"
    TEMPERATURE_K = "temperature_k"
    PRESSURE_KPA = "pressure_kpa"
    WIND_MS = "wind_ms"
    ENERGY_MJ = "energy_mj"
    Z_SCORE = "z_score"
    PERCENT = "percent"
    DAYS = "days"
    DECIMAL_YEAR = "decimal_year"
    COUNT = "count"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# 2. Evidence item
# ---------------------------------------------------------------------------


def _status_from_basis(basis: MeasurementBasis) -> EvidenceStatus:
    """Map a ``MeasurementBasis`` to an ``EvidenceStatus``."""
    return {
        MeasurementBasis.DIRECT: EvidenceStatus.OBSERVED,
        MeasurementBasis.PRODUCT: EvidenceStatus.OBSERVED,
        MeasurementBasis.DERIVED: EvidenceStatus.DERIVED,
        MeasurementBasis.MODELLED: EvidenceStatus.MODELLED,
        MeasurementBasis.PROXY: EvidenceStatus.PROXY,
        MeasurementBasis.INFERENCE: EvidenceStatus.INFERRED,
    }.get(basis, EvidenceStatus.DERIVED)


@dataclass(frozen=True)
class EvidenceItem:
    """A single metric result wrapped with its evidential context.

    An ``EvidenceItem`` is the atomic unit of the evidence layer. It
    wraps a ``MetricResult`` and adds the semantic metadata needed for
    cross-metric comparison: status, temporal window, spatial context,
    and quality.

    An item is immutable once created.
    """

    metric_key: str
    value: Optional[float]
    unit: str
    status: EvidenceStatus
    temporal_start: Optional[date]
    temporal_end: Optional[date]
    quality_level: QualityLevel
    provenance: Optional[Provenance]
    source_dataset_id: Optional[str]
    display_name: str = ""
    #: Serialized spread statistics (`SpatialStats.to_dict()` output) when
    #: the metric populated `MetricResult.stats`. None otherwise — in
    #: particular never present on unavailable results.
    stats: Optional[Dict[str, Any]] = None
    #: Serialized category distribution (`ClassHistogram.to_dict()` output)
    #: for categorical metrics. None otherwise.
    class_histogram: Optional[Dict[str, Any]] = None
    #: Dynamic World per-band mean probabilities, keyed by canonical band
    #: name. Populated only by the probability metric, from its own
    #: authoritative means structure — never parsed from warning strings.
    band_means: Optional[Dict[str, Optional[float]]] = None

    @classmethod
    def from_result(cls, result: MetricResult) -> EvidenceItem:
        """Create an evidence item from a ``MetricResult``.

        Extracts temporal context from ``provenance.requested_start`` /
        ``provenance.requested_end`` and quality from
        ``provenance.quality_level``.  If provenance is absent, quality
        defaults to ``UNAVAILABLE`` and status to ``DERIVED``.
        """
        prov = result.provenance
        basis = result.measurement_basis
        quality = result.quality_level
        dataset_id: Optional[str] = None
        start: Optional[date] = None
        end: Optional[date] = None
        if prov is not None:
            dataset_id = prov.source_dataset_id
            if prov.requested_start:
                try:
                    start = date.fromisoformat(prov.requested_start)
                except (ValueError, TypeError):
                    pass
            if prov.requested_end:
                try:
                    end = date.fromisoformat(prov.requested_end)
                except (ValueError, TypeError):
                    pass
        if result.status != "ok":
            status = EvidenceStatus.UNAVAILABLE
        else:
            status = _status_from_basis(basis)
        return cls(
            metric_key=result.metric_key,
            value=result.value,
            unit=result.unit,
            status=status,
            temporal_start=start,
            temporal_end=end,
            quality_level=quality,
            provenance=prov,
            source_dataset_id=dataset_id,
            display_name=result.display_name,
            stats=result.stats.to_dict() if result.stats else None,
            class_histogram=(
                result.class_histogram.to_dict()
                if result.class_histogram
                else None
            ),
            band_means=(
                dict(result.band_means) if result.band_means else None
            ),
        )

    @property
    def is_usable(self) -> bool:
        """True when this item carries a usable value."""
        return (
            self.value is not None
            and self.status != EvidenceStatus.UNAVAILABLE
            and self.quality_level.is_usable
        )

    @property
    def is_proxy(self) -> bool:
        return self.status == EvidenceStatus.PROXY

    @property
    def is_modelled(self) -> bool:
        return self.status == EvidenceStatus.MODELLED

    @property
    def spatial_resolution(self) -> Optional[str]:
        if self.provenance is not None:
            return self.provenance.spatial_resolution
        return None

    @property
    def temporal_resolution(self) -> Optional[str]:
        if self.provenance is not None:
            return self.provenance.temporal_resolution
        return None


# ---------------------------------------------------------------------------
# 3. Alignment and compatibility results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemporalAlignment:
    """Result of comparing the temporal windows of two evidence items."""

    status: AlignmentStatus
    overlap_days: int = 0
    total_span_days: int = 0
    overlap_fraction: float = 0.0
    explanation: str = ""

    @property
    def is_aligned(self) -> bool:
        return self.status == AlignmentStatus.ALIGNED


@dataclass(frozen=True)
class SpatialAlignment:
    """Result of comparing the spatial contexts of two evidence items."""

    status: AlignmentStatus
    resolution_a: Optional[str] = None
    resolution_b: Optional[str] = None
    resolution_ratio: Optional[float] = None
    explanation: str = ""

    @property
    def is_aligned(self) -> bool:
        return self.status == AlignmentStatus.ALIGNED


@dataclass(frozen=True)
class UnitCompatibility:
    """Result of comparing the units of two evidence items."""

    compatible: bool
    category_a: UnitCategory = UnitCategory.UNKNOWN
    category_b: UnitCategory = UnitCategory.UNKNOWN
    explanation: str = ""


@dataclass(frozen=True)
class QualityCompatibility:
    """Result of comparing the quality levels of two evidence items."""

    status: str  # "acceptable", "degraded", "insufficient", "unavailable"
    quality_a: QualityLevel = QualityLevel.UNAVAILABLE
    quality_b: QualityLevel = QualityLevel.UNAVAILABLE
    explanation: str = ""

    @property
    def is_acceptable(self) -> bool:
        return self.status == "acceptable"


@dataclass(frozen=True)
class DirectionalCheck:
    """Result of checking whether two values move in the expected direction."""

    consistent: bool
    direction_a: Optional[str] = None  # "positive", "negative", "zero", None
    direction_b: Optional[str] = None
    explanation: str = ""


# ---------------------------------------------------------------------------
# 4. Unit categorisation
# ---------------------------------------------------------------------------


def _categorise_unit(unit: str) -> UnitCategory:
    """Map a metric unit string to a ``UnitCategory``."""
    normalised = unit.lower().strip()
    mapping: Dict[str, UnitCategory] = {
        "index": UnitCategory.INDEX,
        "fraction": UnitCategory.FRACTION,
        "mm": UnitCategory.LENGTH_MM,
        "mm/period": UnitCategory.LENGTH_MM,
        "mm/day": UnitCategory.LENGTH_MM,
        "degc": UnitCategory.TEMPERATURE_C,
        "degc": UnitCategory.TEMPERATURE_C,
        "k": UnitCategory.TEMPERATURE_K,
        "kpa": UnitCategory.PRESSURE_KPA,
        "m/s": UnitCategory.WIND_MS,
        "mj/m2": UnitCategory.ENERGY_MJ,
        "z": UnitCategory.Z_SCORE,
        "percent": UnitCategory.PERCENT,
        "days": UnitCategory.DAYS,
        "decimal_year": UnitCategory.DECIMAL_YEAR,
        "index/day": UnitCategory.INDEX,
        "index.fraction": UnitCategory.INDEX,
        "unit/month": UnitCategory.UNKNOWN,
    }
    return mapping.get(normalised, UnitCategory.UNKNOWN)


# ---------------------------------------------------------------------------
# 5. Temporal alignment
# ---------------------------------------------------------------------------


def _parse_date_safe(value: Optional[str]) -> Optional[date]:
    """Parse an ISO date string, returning None on failure."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _overlap_days(
    start_a: date,
    end_a: date,
    start_b: date,
    end_b: date,
) -> int:
    """Number of days the two closed intervals [start, end] overlap."""
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    delta = (earliest_end - latest_start).days
    return max(delta + 1, 0) if earliest_end >= latest_start else 0


def _days_between(start: date, end: date) -> int:
    return max((end - start).days + 1, 0)


# Temporal resolution hierarchy (coarser -> finer)
_TEMPORAL_HIERARCHY: Dict[str, int] = {
    "static": 0,
    "yearly": 1,
    "seasonal": 2,
    "monthly": 3,
    "8-day": 4,
    "daily": 5,
    "sub-daily": 6,
}


def _temporal_rank(resolution: str) -> int:
    normalised = resolution.lower().strip()
    for key, rank in _TEMPORAL_HIERARCHY.items():
        if key in normalised:
            return rank
    return -1


def assess_temporal_alignment(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
    min_overlap_fraction: float = 0.5,
) -> TemporalAlignment:
    """Compare the temporal windows of two evidence items.

    Returns a ``TemporalAlignment`` describing the overlap, the total
    span, and whether the alignment is sufficient for comparison.
    """
    if item_a.temporal_start is None or item_a.temporal_end is None:
        return TemporalAlignment(
            status=AlignmentStatus.UNAVAILABLE,
            explanation="Temporal window unavailable for first item.",
        )
    if item_b.temporal_start is None or item_b.temporal_end is None:
        return TemporalAlignment(
            status=AlignmentStatus.UNAVAILABLE,
            explanation="Temporal window unavailable for second item.",
        )
    overlap = _overlap_days(
        item_a.temporal_start,
        item_a.temporal_end,
        item_b.temporal_start,
        item_b.temporal_end,
    )
    total = _days_between(
        min(item_a.temporal_start, item_b.temporal_start),
        max(item_a.temporal_end, item_b.temporal_end),
    )
    fraction = overlap / total if total > 0 else 0.0

    # Check temporal resolution compatibility
    res_a = item_a.temporal_resolution
    res_b = item_b.temporal_resolution
    if res_a and res_b:
        rank_a = _temporal_rank(res_a)
        rank_b = _temporal_rank(res_b)
        if rank_a >= 0 and rank_b >= 0:
            if abs(rank_a - rank_b) > 2:
                return TemporalAlignment(
                    status=AlignmentStatus.INCOMPATIBLE_RESOLUTION,
                    overlap_days=overlap,
                    total_span_days=total,
                    overlap_fraction=fraction,
                    explanation=(
                        f"Temporal resolutions are incompatible: "
                        f"{res_a} vs {res_b}."
                    ),
                )

    if fraction >= min_overlap_fraction:
        status = AlignmentStatus.ALIGNED
        explanation = (
            f"{overlap} day(s) overlap ({fraction:.0%} of span)."
        )
    elif overlap > 0:
        status = AlignmentStatus.PARTIALLY_ALIGNED
        explanation = (
            f"Only {overlap} day(s) overlap ({fraction:.0%} of span), "
            f"below the {min_overlap_fraction:.0%} threshold."
        )
    else:
        status = AlignmentStatus.INSUFFICIENT_OVERLAP
        explanation = "No temporal overlap."

    return TemporalAlignment(
        status=status,
        overlap_days=overlap,
        total_span_days=total,
        overlap_fraction=fraction,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 6. Spatial alignment
# ---------------------------------------------------------------------------


def _parse_resolution_meters(resolution: Optional[str]) -> Optional[float]:
    """Extract the numeric resolution in metres from a string like '10 m'."""
    if resolution is None:
        return None
    normalised = resolution.lower().strip()
    for suffix in (" m", "m", " meters", " metres"):
        if normalised.endswith(suffix):
            try:
                return float(normalised[: -len(suffix)].strip())
            except ValueError:
                return None
    try:
        return float(normalised)
    except ValueError:
        return None


def assess_spatial_alignment(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
    max_resolution_ratio: float = 10.0,
) -> SpatialAlignment:
    """Compare the spatial resolutions of two evidence items.

    A ratio above ``max_resolution_ratio`` means the coarser metric
    covers too many fine-resolution pixels to be treated as comparable.
    """
    res_a = item_a.spatial_resolution
    res_b = item_b.spatial_resolution
    if res_a is None or res_b is None:
        return SpatialAlignment(
            status=AlignmentStatus.UNAVAILABLE,
            resolution_a=res_a,
            resolution_b=res_b,
            explanation="Spatial resolution unavailable for one or both items.",
        )
    meters_a = _parse_resolution_meters(res_a)
    meters_b = _parse_resolution_meters(res_b)
    if meters_a is None or meters_b is None:
        return SpatialAlignment(
            status=AlignmentStatus.UNAVAILABLE,
            resolution_a=res_a,
            resolution_b=res_b,
            explanation="Could not parse spatial resolution.",
        )
    if meters_a == 0 or meters_b == 0:
        return SpatialAlignment(
            status=AlignmentStatus.UNAVAILABLE,
            resolution_a=res_a,
            resolution_b=res_b,
            explanation="Zero spatial resolution.",
        )
    ratio = max(meters_a / meters_b, meters_b / meters_a)
    finer = min(meters_a, meters_b)
    coarser = max(meters_a, meters_b)
    if ratio <= 1.0:
        status = AlignmentStatus.ALIGNED
        explanation = "Identical spatial resolution."
    elif ratio <= 2.0:
        status = AlignmentStatus.ALIGNED
        explanation = (
            f"Compatible resolutions ({finer:.0f} m vs {coarser:.0f} m, "
            f"ratio {ratio:.1f}x)."
        )
    elif ratio <= max_resolution_ratio:
        status = AlignmentStatus.PARTIALLY_ALIGNED
        explanation = (
            f"Resolution mismatch ({finer:.0f} m vs {coarser:.0f} m, "
            f"ratio {ratio:.1f}x). Coarser metric is contextual."
        )
    else:
        status = AlignmentStatus.FOOTPRINT_MISMATCH
        explanation = (
            f"Resolutions too far apart ({finer:.0f} m vs {coarser:.0f} m, "
            f"ratio {ratio:.1f}x). Not directly comparable."
        )
    return SpatialAlignment(
        status=status,
        resolution_a=res_a,
        resolution_b=res_b,
        resolution_ratio=ratio,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 7. Unit compatibility
# ---------------------------------------------------------------------------


# Which categories can be meaningfully compared
_COMPATIBLE_CATEGORIES: FrozenSet[FrozenSet[UnitCategory]] = frozenset(
    {
        frozenset({UnitCategory.INDEX}),
        frozenset({UnitCategory.INDEX, UnitCategory.FRACTION}),
        frozenset({UnitCategory.FRACTION}),
        frozenset({UnitCategory.LENGTH_MM}),
        frozenset({UnitCategory.TEMPERATURE_C}),
        frozenset({UnitCategory.TEMPERATURE_K}),
        frozenset({UnitCategory.PRESSURE_KPA}),
        frozenset({UnitCategory.WIND_MS}),
        frozenset({UnitCategory.ENERGY_MJ}),
        frozenset({UnitCategory.Z_SCORE}),
        frozenset({UnitCategory.PERCENT}),
        frozenset({UnitCategory.DAYS}),
        frozenset({UnitCategory.DECIMAL_YEAR}),
    }
)


def assess_unit_compatibility(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
) -> UnitCompatibility:
    """Determine whether two evidence items have compatible units."""
    cat_a = _categorise_unit(item_a.unit)
    cat_b = _categorise_unit(item_b.unit)
    if cat_a == UnitCategory.UNKNOWN or cat_b == UnitCategory.UNKNOWN:
        pair = frozenset({cat_a, cat_b}) - {UnitCategory.UNKNOWN}
        if len(pair) <= 1:
            return UnitCompatibility(
                compatible=True,
                category_a=cat_a,
                category_b=cat_b,
                explanation="At least one unit is unclassified; comparison may be valid.",
            )
        return UnitCompatibility(
            compatible=False,
            category_a=cat_a,
            category_b=cat_b,
            explanation=(
                f"Incompatible units: {item_a.unit!r} vs {item_b.unit!r}."
            ),
        )
    if cat_a == cat_b:
        return UnitCompatibility(
            compatible=True,
            category_a=cat_a,
            category_b=cat_b,
            explanation=f"Same unit category: {cat_a.value}.",
        )
    pair = frozenset({cat_a, cat_b})
    if pair in _COMPATIBLE_CATEGORIES:
        return UnitCompatibility(
            compatible=True,
            category_a=cat_a,
            category_b=cat_b,
            explanation=f"Compatible unit categories: {cat_a.value} and {cat_b.value}.",
        )
    return UnitCompatibility(
        compatible=False,
        category_a=cat_a,
        category_b=cat_b,
        explanation=(
            f"Incompatible unit categories: {cat_a.value} ({item_a.unit!r}) "
            f"vs {cat_b.value} ({item_b.unit!r})."
        ),
    )


# ---------------------------------------------------------------------------
# 8. Quality compatibility
# ---------------------------------------------------------------------------


def assess_quality_compatibility(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
) -> QualityCompatibility:
    """Compare the quality levels of two evidence items."""
    qa = item_a.quality_level
    qb = item_b.quality_level
    if not qa.is_usable or not qb.is_usable:
        return QualityCompatibility(
            status="insufficient",
            quality_a=qa,
            quality_b=qb,
            explanation=(
                f"Quality insufficient: {qa.value} vs {qb.value}."
            ),
        )
    worst = max(qa, qb, key=lambda q: list(QualityLevel).index(q))
    if worst.needs_caveat:
        return QualityCompatibility(
            status="degraded",
            quality_a=qa,
            quality_b=qb,
            explanation=(
                f"Quality degraded: worst is {worst.value}."
            ),
        )
    return QualityCompatibility(
        status="acceptable",
        quality_a=qa,
        quality_b=qb,
        explanation=f"Quality acceptable: {qa.value} and {qb.value}.",
    )


# ---------------------------------------------------------------------------
# 9. Directional consistency
# ---------------------------------------------------------------------------


def _value_direction(value: Optional[float], threshold: float = 0.0) -> Optional[str]:
    if value is None:
        return None
    if value > threshold:
        return "positive"
    if value < -threshold:
        return "negative"
    return "zero"


def check_directional_consistency(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
    relationship: ExpectedRelationship,
    anomaly_threshold: float = 0.0,
) -> DirectionalCheck:
    """Check whether two values move in the expected direction."""
    if not item_a.is_usable or not item_b.is_usable:
        return DirectionalCheck(
            consistent=False,
            explanation="One or both items are not usable.",
        )
    dir_a = _value_direction(item_a.value, anomaly_threshold)
    dir_b = _value_direction(item_b.value, anomaly_threshold)
    if dir_a is None or dir_b is None:
        return DirectionalCheck(
            consistent=False,
            direction_a=dir_a,
            direction_b=dir_b,
            explanation="Cannot determine direction: value is None.",
        )
    if relationship == ExpectedRelationship.NO_ASSUMED_RELATIONSHIP:
        return DirectionalCheck(
            consistent=True,
            direction_a=dir_a,
            direction_b=dir_b,
            explanation="No directional relationship assumed.",
        )
    if relationship == ExpectedRelationship.SAME_DIRECTION:
        consistent = dir_a == dir_b
        explanation = (
            "Consistent: both same direction."
            if consistent
            else f"Inconsistent: {dir_a} vs {dir_b}."
        )
    elif relationship == ExpectedRelationship.OPPOSITE_DIRECTION:
        opposite_pairs = {("positive", "negative"), ("negative", "positive")}
        consistent = (dir_a, dir_b) in opposite_pairs
        explanation = (
            "Consistent: opposite directions."
            if consistent
            else f"Inconsistent: both {dir_a}."
        )
    else:
        consistent = True
        explanation = "Conditional relationship; directional check deferred."
    return DirectionalCheck(
        consistent=consistent,
        direction_a=dir_a,
        direction_b=dir_b,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# 10. Relationship registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationshipSpec:
    """An explicit, scientifically justified directional relationship.

    Every relationship must have a documented scientific basis and
    explicit limitations.  Relationships without justification must
    not be registered.
    """

    metric_a: str
    metric_b: str
    expected: ExpectedRelationship
    temporal_rule: str = "same_window"
    spatial_rule: str = "same_geometry"
    unit_rule: str = "compatible"
    quality_rule: str = "both_usable"
    scientific_basis: str = ""
    limitations: Tuple[str, ...] = ()


@dataclass
class RelationshipRegistry:
    """A catalog of known metric relationships.

    Relationships must be registered explicitly with scientific
    justification.  The default registry is populated with
    well-established directional relationships.
    """

    _relationships: Dict[Tuple[str, str], RelationshipSpec] = field(
        default_factory=dict
    )

    def register(self, spec: RelationshipSpec) -> None:
        key = self._key(spec.metric_a, spec.metric_b)
        self._relationships[key] = spec

    def get(
        self, metric_a: str, metric_b: str
    ) -> Optional[RelationshipSpec]:
        key = self._key(metric_a, metric_b)
        return self._relationships.get(key)

    def all_relationships(self) -> List[RelationshipSpec]:
        return list(self._relationships.values())

    def has_relationship(self, metric_a: str, metric_b: str) -> bool:
        return self._key(metric_a, metric_b) in self._relationships

    @staticmethod
    def _key(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a <= b else (b, a)


def _build_default_registry() -> RelationshipRegistry:
    """Populate the default relationship registry."""
    registry = RelationshipRegistry()
    vegetation_indices = ("ndvi", "evi", "lai", "fapar", "fcover")
    for i, a in enumerate(vegetation_indices):
        for b in vegetation_indices[i + 1 :]:
            registry.register(
                RelationshipSpec(
                    metric_a=a,
                    metric_b=b,
                    expected=ExpectedRelationship.SAME_DIRECTION,
                    scientific_basis=(
                        "Vegetation indices derived from similar spectral "
                        "bands respond to canopy greenness in the same "
                        "direction."
                    ),
                    limitations=(
                        "NDVI and EVI share Sentinel-2 NIR band and are "
                        "not fully independent. EVI saturates less at "
                        "high LAI. Indices may diverge under sparse "
                        "canopy or soil背景 influence.",
                    ),
                )
            )

    water_pairs = (
        ("precipitation", "soil_moisture_rootzone"),
        ("precipitation", "soil_moisture_surface"),
        ("precipitation", "evapotranspiration"),
        ("soil_moisture_rootzone", "evapotranspiration"),
        ("soil_moisture_surface", "evapotranspiration"),
        ("ndwi", "soil_moisture_surface"),
        ("ndmi", "soil_moisture_rootzone"),
    )
    for a, b in water_pairs:
        registry.register(
            RelationshipSpec(
                metric_a=a,
                metric_b=b,
                expected=ExpectedRelationship.SAME_DIRECTION,
                scientific_basis=(
                    "Water availability metrics move in the same direction: "
                    "more precipitation increases soil moisture and "
                    "supports more evapotranspiration."
                ),
                limitations=(
                    "Different temporal response lags, spatial resolutions, "
                    "and measurement methods may cause short-term "
                    "divergence. ET depends on atmospheric demand as well "
                    "as water supply.",
                ),
            )
        )

    thermal_veg = (
        ("land_surface_temperature_day", "ndvi"),
        ("land_surface_temperature_day", "evi"),
        ("land_surface_temperature_day", "soil_moisture_surface"),
    )
    for a, b in thermal_veg:
        registry.register(
            RelationshipSpec(
                metric_a=a,
                metric_b=b,
                expected=ExpectedRelationship.OPPOSITE_DIRECTION,
                scientific_basis=(
                    "Higher land surface temperature often accompanies "
                    "lower vegetation cover and soil moisture due to "
                    "reduced evaporative cooling."
                ),
                limitations=(
                    "LST is surface temperature, not canopy temperature. "
                    "The relationship depends on soil moisture status, "
                    "vegetation cover fraction, and atmospheric demand. "
                    "In energy-limited regimes the relationship may "
                    "reverse.",
                ),
            )
        )

    vpd_pairs = (
        ("vpd", "evapotranspiration"),
        ("vpd", "potential_evapotranspiration"),
    )
    for a, b in vpd_pairs:
        registry.register(
            RelationshipSpec(
                metric_a=a,
                metric_b=b,
                expected=ExpectedRelationship.SAME_DIRECTION,
                scientific_basis=(
                    "Higher VPD increases atmospheric demand, driving "
                    "higher potential and actual evapotranspiration when "
                    "water is available."
                ),
                limitations=(
                    "Actual ET may decrease under high VPD if water is "
                    "limiting (stomatal closure). The relationship "
                    "between VPD and ET is conditional on water "
                    "availability.",
                ),
            )
        )

    et_pet = RelationshipSpec(
        metric_a="evapotranspiration",
        metric_b="potential_evapotranspiration",
        expected=ExpectedRelationship.SAME_DIRECTION,
        scientific_basis=(
            "Actual ET tracks potential ET when water is available; "
            "divergence indicates water limitation."
        ),
        limitations=(
            "ET/PET ratio is the evaporative fraction, already computed "
            "by the stress module. The directional relationship holds "
            "but the ratio is a more informative measure.",
        ),
    )
    registry.register(et_pet)

    precip_et = RelationshipSpec(
        metric_a="precipitation",
        metric_b="evapotranspiration",
        expected=ExpectedRelationship.SAME_DIRECTION,
        scientific_basis=(
            "Precipitation is a primary water input; ET is a primary "
            "water output. Both increase in wetter conditions."
        ),
        limitations=(
            "The magnitude of response differs: ET is constrained by "
            "energy and surface conductance, precipitation is episodic. "
            "A cumulative comparison is more meaningful than daily.",
        ),
    )
    registry.register(precip_et)

    return registry


# Module-level default registry
DEFAULT_REGISTRY = _build_default_registry()


# ---------------------------------------------------------------------------
# 11. Evidence conflict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceConflict:
    """A detected inconsistency between two evidence items.

    A conflict is descriptive, not diagnostic.  It reports what is
    inconsistent and lists possible technical explanation categories,
    without claiming to identify the cause.
    """

    metric_a: str
    metric_b: str
    status: ConsistencyStatus
    explanation: str
    possible_explanations: Tuple[str, ...] = ()
    evidence_a: Optional[EvidenceItem] = None
    evidence_b: Optional[EvidenceItem] = None


def detect_conflict(
    item_a: EvidenceItem,
    item_b: EvidenceItem,
    relationship: Optional[RelationshipSpec] = None,
) -> EvidenceConflict:
    """Detect whether two evidence items are consistent.

    If a ``RelationshipSpec`` is provided, directional consistency is
    also evaluated.  Possible explanation categories are descriptive:
    different temporal windows, different spatial scales, retrieval
    differences, or model vs observation differences.
    """
    if not item_a.is_usable or not item_b.is_usable:
        return EvidenceConflict(
            metric_a=item_a.metric_key,
            metric_b=item_b.metric_key,
            status=ConsistencyStatus.INSUFFICIENT_EVIDENCE,
            explanation="One or both items are not usable.",
            evidence_a=item_a,
            evidence_b=item_b,
        )

    explanations: List[str] = []

    temporal = assess_temporal_alignment(item_a, item_b)
    if not temporal.is_aligned:
        explanations.append(
            f"Temporal: {temporal.explanation}"
        )

    spatial = assess_spatial_alignment(item_a, item_b)
    if spatial.status == AlignmentStatus.FOOTPRINT_MISMATCH:
        explanations.append(
            f"Spatial: {spatial.explanation}"
        )

    units = assess_unit_compatibility(item_a, item_b)
    if not units.compatible:
        return EvidenceConflict(
            metric_a=item_a.metric_key,
            metric_b=item_b.metric_key,
            status=ConsistencyStatus.CONFLICTING,
            explanation=f"Incompatible units: {units.explanation}",
            possible_explanations=tuple(explanations),
            evidence_a=item_a,
            evidence_b=item_b,
        )

    quality = assess_quality_compatibility(item_a, item_b)
    if quality.status == "insufficient":
        explanations.append(
            f"Quality: {quality.explanation}"
        )

    if relationship is not None:
        direction = check_directional_consistency(
            item_a,
            item_b,
            relationship.expected,
        )
        if direction.consistent:
            return EvidenceConflict(
                metric_a=item_a.metric_key,
                metric_b=item_b.metric_key,
                status=ConsistencyStatus.CONSISTENT,
                explanation=(
                    f"Consistent: {direction.explanation} "
                    f"({relationship.scientific_basis})"
                ),
                possible_explanations=tuple(explanations),
                evidence_a=item_a,
                evidence_b=item_b,
            )
        else:
            explanations.append(
                f"Directional: {direction.explanation}"
            )

    consistent_metrics = []
    if item_a.value is not None and item_b.value is not None:
        if item_a.value > 0 and item_b.value > 0:
            consistent_metrics.append("both positive")
        elif item_a.value < 0 and item_b.value < 0:
            consistent_metrics.append("both negative")

    if consistent_metrics and not explanations:
        return EvidenceConflict(
            metric_a=item_a.metric_key,
            metric_b=item_b.metric_key,
            status=ConsistencyStatus.CONSISTENT,
            explanation=f"Values are directionally consistent ({', '.join(consistent_metrics)}).",
            evidence_a=item_a,
            evidence_b=item_b,
        )

    if explanations:
        status = ConsistencyStatus.PARTIALLY_CONSISTENT
        explanation = (
            f"Partially consistent: {'; '.join(explanations)}"
        )
    else:
        status = ConsistencyStatus.CONSISTENT
        explanation = "No inconsistency detected."

    return EvidenceConflict(
        metric_a=item_a.metric_key,
        metric_b=item_b.metric_key,
        status=status,
        explanation=explanation,
        possible_explanations=tuple(explanations),
        evidence_a=item_a,
        evidence_b=item_b,
    )


# ---------------------------------------------------------------------------
# 12. Evidence sufficiency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSufficiency:
    """Whether enough evidence exists for a descriptive interpretation.

    Sufficiency is rule-based, not a subjective score.  It is based on:

    * minimum number of independent metrics
    * acceptable quality
    * sufficient temporal overlap
    * sufficient spatial compatibility
    * no unresolved critical conflicts
    """

    level: SufficiencyLevel
    available_count: int
    unavailable_count: int
    distinct_sources: int
    min_quality: Optional[QualityLevel]
    has_conflicts: bool
    key_reasons: Tuple[str, ...]

    @property
    def is_sufficient(self) -> bool:
        return self.level == SufficiencyLevel.SUFFICIENT


def assess_sufficiency(
    items: Sequence[EvidenceItem],
    conflicts: Sequence[EvidenceConflict] = (),
    min_independent_sources: int = 2,
) -> EvidenceSufficiency:
    """Assess whether a set of evidence items provides sufficient basis.

    Rules:
    1. At least ``min_independent_sources`` distinct source datasets.
    2. At least one item with acceptable quality.
    3. No unresolved critical conflicts (CONFLICTING status).
    """
    available = [i for i in items if i.is_usable]
    unavailable = [i for i in items if not i.is_usable]
    sources = {
        i.source_dataset_id
        for i in available
        if i.source_dataset_id is not None
    }
    qualities = [i.quality_level for i in available]
    min_q = max(qualities, key=lambda q: list(QualityLevel).index(q)) if qualities else None
    critical = [
        c for c in conflicts if c.status == ConsistencyStatus.CONFLICTING
    ]
    reasons: List[str] = []

    if len(sources) < min_independent_sources:
        reasons.append(
            f"Need >= {min_independent_sources} independent sources, "
            f"have {len(sources)}."
        )
    if min_q is None or not min_q.is_usable:
        reasons.append("No item with acceptable quality.")
    elif min_q.needs_caveat:
        reasons.append(f"Quality degraded: worst is {min_q.value}.")
    if critical:
        reasons.append(
            f"{len(critical)} unresolved critical conflict(s)."
        )
    if not available:
        reasons.append("No usable evidence items.")

    if not reasons:
        level = SufficiencyLevel.SUFFICIENT
    elif len(reasons) == 1 and "degraded" in reasons[0].lower():
        level = SufficiencyLevel.LIMITED
    else:
        level = SufficiencyLevel.INSUFFICIENT

    return EvidenceSufficiency(
        level=level,
        available_count=len(available),
        unavailable_count=len(unavailable),
        distinct_sources=len(sources),
        min_quality=min_q,
        has_conflicts=bool(critical),
        key_reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# 13. Evidence bundle
# ---------------------------------------------------------------------------


@dataclass
class EvidenceBundle:
    """A collection of related evidence items with consistency analysis.

    A bundle preserves each metric independently and never collapses
    everything into one score.  It reports available evidence, temporal
    and spatial alignment, quality, consistency, conflicts, and
    limitations.
    """

    name: str
    items: List[EvidenceItem] = field(default_factory=list)
    conflicts: List[EvidenceConflict] = field(default_factory=list)
    sufficiency: Optional[EvidenceSufficiency] = None
    limitations: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def available_items(self) -> List[EvidenceItem]:
        return [i for i in self.items if i.is_usable]

    @property
    def unavailable_items(self) -> List[EvidenceItem]:
        return [i for i in self.items if not i.is_usable]

    @property
    def metric_keys(self) -> List[str]:
        return [i.metric_key for i in self.items]

    @property
    def available_keys(self) -> List[str]:
        return [i.metric_key for i in self.items if i.is_usable]

    @property
    def source_datasets(self) -> List[str]:
        return list(
            {
                i.source_dataset_id
                for i in self.items
                if i.source_dataset_id is not None
            }
        )

    @property
    def has_conflicts(self) -> bool:
        return any(
            c.status == ConsistencyStatus.CONFLICTING for c in self.conflicts
        )

    def pairwise_alignment(
        self,
        item_a: EvidenceItem,
        item_b: EvidenceItem,
    ) -> Dict[str, object]:
        """Compute full pairwise alignment between two items."""
        return {
            "temporal": assess_temporal_alignment(item_a, item_b),
            "spatial": assess_spatial_alignment(item_a, item_b),
            "units": assess_unit_compatibility(item_a, item_b),
            "quality": assess_quality_compatibility(item_a, item_b),
        }

    def run_consistency_checks(
        self,
        registry: Optional[RelationshipRegistry] = None,
    ) -> List[EvidenceConflict]:
        """Run pairwise consistency checks on all available item pairs.

        If a ``registry`` is provided, directional relationships are
        evaluated.  Otherwise, only technical consistency (units,
        temporal, spatial, quality) is checked.
        """
        reg = registry or DEFAULT_REGISTRY
        available = self.available_items
        conflicts: List[EvidenceConflict] = []
        for i, a in enumerate(available):
            for b in available[i + 1 :]:
                rel = reg.get(a.metric_key, b.metric_key)
                conflicts.append(detect_conflict(a, b, rel))
        self.conflicts = conflicts
        return conflicts

    def assess_sufficiency(
        self,
        min_independent_sources: int = 2,
    ) -> EvidenceSufficiency:
        """Assess whether the bundle has sufficient evidence."""
        self.sufficiency = assess_sufficiency(
            self.items,
            self.conflicts,
            min_independent_sources,
        )
        return self.sufficiency

    def to_dict(self) -> Dict[str, object]:
        """Serialize the bundle for API responses."""
        return {
            "name": self.name,
            "items": [
                {
                    "metric_key": i.metric_key,
                    "value": i.value,
                    "unit": i.unit,
                    "status": i.status.value,
                    "quality": i.quality_level.value,
                    "source_dataset": i.source_dataset_id,
                }
                for i in self.items
            ],
            "available": self.available_keys,
            "unavailable": [
                i.metric_key for i in self.unavailable_items
            ],
            "source_datasets": self.source_datasets,
            "conflicts": [
                {
                    "metrics": (c.metric_a, c.metric_b),
                    "status": c.status.value,
                    "explanation": c.explanation,
                }
                for c in self.conflicts
            ],
            "sufficiency": {
                "level": self.sufficiency.level.value
                if self.sufficiency
                else "unassessed",
                "available": self.sufficiency.available_count
                if self.sufficiency
                else 0,
                "distinct_sources": self.sufficiency.distinct_sources
                if self.sufficiency
                else 0,
                "key_reasons": self.sufficiency.key_reasons
                if self.sufficiency
                else (),
            },
            "limitations": list(self.limitations),
            "metadata": dict(self.metadata),
        }
