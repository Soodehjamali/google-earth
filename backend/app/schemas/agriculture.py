"""Agricultural Intelligence API schemas (Phase Q).

Pydantic response models for the agricultural analysis API contract.
These models serialize the evidence, synthesis, and provenance layers
into stable JSON contracts for the frontend.

Every model preserves:
- scientific traceability (rule_id, evidence_keys, scientific_basis)
- limitations
- unavailable reasons
- quality/status information
- provenance
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Geometry / request schemas
# ---------------------------------------------------------------------------


class PointGeometry(BaseModel):
    """GeoJSON Point geometry."""

    type: str = Field(default="Point", pattern="^Point$")
    coordinates: List[float] = Field(..., min_length=2, max_length=3)


class PolygonGeometry(BaseModel):
    """GeoJSON Polygon geometry."""

    type: str = Field(default="Polygon", pattern="^Polygon$")
    coordinates: List[List[List[float]]] = Field(..., min_length=1)


class AgricultureAnalysisRequest(BaseModel):
    """Request contract for agricultural analysis.

    Follows existing project conventions from AnalysisCreate.
    """

    geometry: Union[PointGeometry, PolygonGeometry] = Field(
        ...,
        description="GeoJSON geometry (Point or Polygon)",
    )
    start_date: str = Field(
        ...,
        description="Analysis start date (YYYY-MM-DD)",
    )
    end_date: str = Field(
        ...,
        description="Analysis end date (YYYY-MM-DD)",
    )
    domains: Optional[List[str]] = Field(
        None,
        description=(
            "Optional list of domains to analyse. "
            "If None, all available domains are included. "
            "Valid values: vegetation, water, thermal, soil, climate, "
            "crop, phenology, productivity, historical."
        ),
    )
    cloud_max_percent: float = Field(
        default=20.0,
        ge=0.0,
        le=100.0,
        description="Maximum cloud cover percentage for filtering",
    )
    ground_truth: Optional[List[Any]] = Field(
        default=None,
        description=(
            "Optional independently supplied reference observations, "
            "each a GroundTruthObservation-compatible record. Validated "
            "through the P6.2 ingestion boundary; valid records are "
            "linked against this analysis, invalid ones are reported "
            "as rejected. Absent (or empty) means no validation is run."
        ),
    )


class EvidenceItemInput(BaseModel):
    """Input evidence item for synthesis-only endpoint."""

    metric_key: str
    value: Optional[float] = None
    unit: str = ""
    status: str = "derived"
    quality: str = "good"
    source_dataset: Optional[str] = None
    display_name: str = ""


class DomainEvidenceInput(BaseModel):
    """Input evidence bundle for a single domain."""

    items: List[EvidenceItemInput] = Field(default_factory=list)


class SynthesisOnlyRequest(BaseModel):
    """Request contract for synthesis-only endpoint.

    Allows submitting pre-built evidence bundles directly.
    """

    evidence_bundles: Dict[str, DomainEvidenceInput] = Field(
        default_factory=dict,
        description="Evidence bundles keyed by domain name",
    )
    time_start: Optional[str] = Field(
        None,
        description="Analysis start date (YYYY-MM-DD)",
    )
    time_end: Optional[str] = Field(
        None,
        description="Analysis end date (YYYY-MM-DD)",
    )
    spatial_context: Optional[str] = Field(
        None,
        description="Spatial context description",
    )


# ---------------------------------------------------------------------------
# 2. Provenance response
# ---------------------------------------------------------------------------


class ProvenanceResponse(BaseModel):
    """Provenance information for a metric or evidence item.

    Exposes where the data came from without leaking credentials.
    """

    source_dataset_id: Optional[str] = None
    source_dataset_name: Optional[str] = None
    bands: List[str] = Field(default_factory=list)
    formula: str = ""
    unit: str = ""
    spatial_resolution: str = ""
    temporal_resolution: str = ""
    aggregation_method: str = ""
    measurement_basis: str = ""
    quality_level: str = ""
    temporal_kind: str = ""
    requested_start: Optional[str] = None
    requested_end: Optional[str] = None
    product_date: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    image_count: Optional[int] = None
    fallback_from: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    caveats: List[str] = Field(default_factory=list)
    citation: str = ""
    computed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# 3. Quality / status response
# ---------------------------------------------------------------------------


class QualityInfo(BaseModel):
    """Quality information for a metric result."""

    level: str = Field(description="Quality level (excellent, good, moderate, poor, insufficient, unavailable)")
    is_usable: bool = Field(description="Whether this quality level is usable for interpretation")
    needs_caveat: bool = Field(description="Whether a caveat is needed when using this quality level")


class StatusInfo(BaseModel):
    """Status information for an evidence item."""

    status: str = Field(description="Evidence status (observed, derived, modelled, proxy, inferred, unavailable)")
    is_usable: bool = Field(description="Whether this status carries a usable value")
    is_proxy: bool = Field(description="Whether this is a proxy measurement")


# ---------------------------------------------------------------------------
# 4. Evidence response
# ---------------------------------------------------------------------------


class EvidenceItemResponse(BaseModel):
    """A single evidence item with full traceability.

    Preserves metric key, value, unit, temporal window, quality,
    status, provenance, and source dataset.
    """

    metric_key: str
    value: Optional[float] = None
    unit: str
    status: str
    quality: str
    source_dataset: Optional[str] = None
    display_name: str = ""
    temporal_start: Optional[str] = None
    temporal_end: Optional[str] = None
    is_usable: bool = False
    is_proxy: bool = False
    provenance: Optional[ProvenanceResponse] = None
    stats: Optional[Dict[str, Any]] = None
    class_histogram: Optional[Dict[str, Any]] = None
    band_means: Optional[Dict[str, Optional[float]]] = None


class EvidenceConflictResponse(BaseModel):
    """A conflict between two evidence items."""

    metric_a: str
    metric_b: str
    status: str
    explanation: str
    possible_explanations: List[str] = Field(default_factory=list)


class EvidenceSufficiencyResponse(BaseModel):
    """Evidence sufficiency assessment."""

    level: str
    available_count: int
    unavailable_count: int
    distinct_sources: int
    min_quality: Optional[str] = None
    has_conflicts: bool = False
    key_reasons: List[str] = Field(default_factory=list)


class EvidenceBundleResponse(BaseModel):
    """A collection of related evidence items with consistency analysis.

    Preserves each metric independently; never collapses into one score.
    """

    name: str
    items: List[EvidenceItemResponse] = Field(default_factory=list)
    available: List[str] = Field(default_factory=list)
    unavailable: List[str] = Field(default_factory=list)
    source_datasets: List[str] = Field(default_factory=list)
    conflicts: List[EvidenceConflictResponse] = Field(default_factory=list)
    sufficiency: Optional[EvidenceSufficiencyResponse] = None
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5. Synthesis response
# ---------------------------------------------------------------------------


class SynthesisStatementResponse(BaseModel):
    """A single synthesised statement with its evidence and provenance.

    Every statement is traceable to a rule, evidence, scientific basis,
    and limitations.
    """

    rule_id: str
    domain: str
    pattern: str
    statement: str
    evidence_keys: List[str] = Field(default_factory=list)
    evidence_values: Dict[str, Optional[float]] = Field(default_factory=dict)
    scientific_basis: str = ""
    limitations: List[str] = Field(default_factory=list)
    sufficiency: str = "insufficient"
    conflicts: List[str] = Field(default_factory=list)


class DomainSummaryResponse(BaseModel):
    """Per-domain synthesis summary.

    Reports available evidence, statements, conflicts, and limitations
    for a single domain.
    """

    domain: str
    statement_count: int = 0
    statements: List[SynthesisStatementResponse] = Field(default_factory=list)
    unavailable_evidence: List[str] = Field(default_factory=list)
    sufficiency: str = "insufficient"
    limitations: List[str] = Field(default_factory=list)
    #: True when the evaluated bundle held at least one usable evidence
    #: item (finite value, not unavailable, usable quality).  Data
    #: presence only — independent of whether any statement fired.
    has_usable_evidence: bool = False


# ---------------------------------------------------------------------------
# 6. Top-level agricultural analysis response
# ---------------------------------------------------------------------------


class AgriculturalAnalysisResponse(BaseModel):
    """Full agricultural analysis response.

    Contains analysis metadata, domain summaries, synthesis statements,
    and overall sufficiency.  Answers "what is currently observable
    about this field?" without pretending to answer "what should the
    farmer do?"
    """

    # Metadata
    request_id: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    spatial_context: Optional[str] = None
    generated_at: Optional[str] = None

    # Domain summaries
    domain_summaries: Dict[str, DomainSummaryResponse] = Field(
        default_factory=dict,
        description="Per-domain synthesis summaries",
    )

    # Cross-domain synthesis
    cross_domain_statements: List[SynthesisStatementResponse] = Field(
        default_factory=list,
        description="Statements that span multiple domains",
    )

    # Overall assessment
    overall_sufficiency: str = Field(
        default="insufficient",
        description="Overall evidence sufficiency level",
    )

    # Raw evidence bundles (optional, for frontend traceability)
    evidence_bundles: Dict[str, EvidenceBundleResponse] = Field(
        default_factory=dict,
        description="Underlying evidence bundles per domain",
    )

    # Metadata
    available_domains: List[str] = Field(default_factory=list)
    unavailable_domains: List[str] = Field(default_factory=list)
    # Explicit domain semantics (F-CONTRACT-FIX-1 §2): the historical
    # statement-based available_domains above is preserved verbatim;
    # the three lists below carry the unambiguous data/statement split.
    domains_with_data: List[str] = Field(
        default_factory=list,
        description="Domains whose evidence bundles hold at least one "
        "usable evidence item (finite value, not unavailable, usable "
        "quality). Independent of statement generation.",
    )
    domains_with_statements: List[str] = Field(
        default_factory=list,
        description="Domains where at least one synthesis rule actually "
        "fired. Same content as the legacy available_domains field.",
    )
    domains_without_data: List[str] = Field(
        default_factory=list,
        description="Domains whose evidence bundles hold no usable "
        "evidence item at all.",
    )
    # Canonical aggregate unavailability (F-CONTRACT-FIX-1 §4): each
    # unavailable metric key appears exactly once here, in first-seen
    # bundle order.  The per-bundle ``unavailable`` and per-summary
    # ``unavailable_evidence`` lists remain the detailed views; this
    # field is the one semantic source for aggregate counting.
    unavailable_metric_keys: List[str] = Field(
        default_factory=list,
        description="De-duplicated unavailable metric keys across all "
        "domain bundles; each key counts once.",
    )
    limitations: List[str] = Field(default_factory=list)
    metadata: Dict[str, str] = Field(default_factory=dict)

    # Temporal intelligence (P5.3 integration phase)
    temporal: Optional[TemporalSectionModel] = Field(
        default=None,
        description="Monthly temporal profiles and derived analyses, "
        "keyed by metric. Additive: absent (null) on cached responses "
        "produced before the temporal contract existed.",
    )

    # Spatial intelligence (P5.3-S integration phase)
    spatial: Optional[SpatialSectionModel] = Field(
        default=None,
        description="Deterministic grid-cell observations and area "
        "summaries from P1.5. Additive: absent (null) when no "
        "requested metric is spatially supported or when cached "
        "responses predate the spatial contract.",
    )

    # Ground-truth validation (P6.3 integration phase)
    validation: Optional[ValidationSectionModel] = Field(
        default=None,
        description="Deterministic linkage of supplied reference "
        "observations against this analysis via the P6.2 engine. "
        "Additive: absent (null) when no ground truth was supplied.",
    )


# ---------------------------------------------------------------------------
# 7. Error response
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Structured error response.

    Preserves machine-readable reason codes and human-readable
    explanations.  Never leaks credentials, filesystem paths,
    or stack traces.
    """

    error: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    reason_code: Optional[str] = None


# ---------------------------------------------------------------------------
# 8. Health / status response
# ---------------------------------------------------------------------------


class AgricultureHealthResponse(BaseModel):
    """Health status for the agricultural analysis subsystem."""

    status: str = "ok"
    metrics_registered: int = 0
    evidence_layer: str = "available"
    synthesis_layer: str = "available"
    message: str = ""


# ---------------------------------------------------------------------------
# 9. Temporal profile contract (P1.1 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.temporal_profile for a future
# temporal-chart endpoint.  Missing months are explicit nulls; no
# interpolation is ever represented here.


class TemporalProfilePointModel(BaseModel):
    """One monthly observation of a metric."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = Field(
        default=None,
        description="Observed value; null when the month had no usable observation",
    )
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None


class TemporalProfileModel(BaseModel):
    """Chronological monthly observations for one metric."""

    metric_key: str
    dataset_id: Optional[str] = None
    unit: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    points: List[TemporalProfilePointModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 10. Baseline and anomaly contract (P1.2 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.baseline_anomaly for a future
# anomaly endpoint.  Categories are neutral statistics (NORMAL,
# BELOW_BASELINE, ABOVE_BASELINE, INSUFFICIENT_BASELINE) — never a
# diagnosis, severity level, or probability.


class ProfileBaselineModel(BaseModel):
    """Statistical reference for one temporal profile."""

    metric_key: str
    strategy: str = "full_period"
    n_observations: int = 0
    n_usable: int = 0
    mean: float = 0.0
    std: Optional[float] = None
    minimum: float = 0.0
    maximum: float = 0.0
    median: float = 0.0
    reference_start: Optional[str] = None
    reference_end: Optional[str] = None
    window_start: str = ""
    window_end: str = ""
    spread_reliable: bool = False
    quality_counts: Dict[str, int] = Field(default_factory=dict)
    mean_coverage_percent: Optional[float] = None


class AnomalyPointModel(BaseModel):
    """One profile observation scored against its baseline."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = Field(
        default=None,
        description="Observed value; null when the month had no usable observation",
    )
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    z_score: Optional[float] = Field(
        default=None,
        description="Standardized anomaly; null when it could not be produced",
    )
    percentile: Optional[float] = Field(
        default=None,
        description="Historical rank; null when the reference is insufficient",
    )
    category: str = "INSUFFICIENT_BASELINE"


class AnomalyProfileModel(BaseModel):
    """A temporal profile with every observation scored, or refused."""

    metric_key: str
    unit: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    baseline: Optional[ProfileBaselineModel] = None
    points: List[AnomalyPointModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 11. Change and breakpoint contract (P1.3 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.change_profile for a future
# change-analysis endpoint.  Directions and flags are neutral
# statistics (INCREASE/DECREASE/STABLE, RAPID_*/NOT_RAPID,
# PERSISTENT/NO_PERSISTENCE) — never a diagnosis, severity level, or
# probability.


class MonthChangeModel(BaseModel):
    """One observation-to-observation change."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = None
    previous_window_start: Optional[str] = None
    previous_window_end: Optional[str] = None
    previous_value: Optional[float] = None
    absolute_change: Optional[float] = None
    relative_change: Optional[float] = Field(
        default=None,
        description="Change relative to |previous|; null when previous is zero or missing",
    )
    days_elapsed: Optional[int] = None
    rate_per_day: Optional[float] = None
    direction: str = "INSUFFICIENT"
    rapid: str = "INSUFFICIENT"
    z_score: Optional[float] = None
    percentile: Optional[float] = None
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None


class DeviationPersistenceModel(BaseModel):
    """How long z-score deviations lasted, with gaps honoured."""

    longest_run_below: int = 0
    longest_run_above: int = 0
    n_anomalous: int = 0
    n_observed: int = 0
    n_missing: int = 0
    state: str = "INSUFFICIENT"


class BreakpointModel(BaseModel):
    """One conservative temporal transition, described and nothing more."""

    onset_window_start: str = ""
    onset_window_end: str = ""
    direction: str = "INSUFFICIENT"
    pre_level: float = 0.0
    post_level: float = 0.0
    magnitude: float = 0.0
    window_months: int = 3
    n_usable: int = 0
    method: str = ""


class ChangeProfileModel(BaseModel):
    """A temporal profile with change, persistence, and breakpoint analysis."""

    metric_key: str
    unit: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    changes: List[MonthChangeModel] = Field(default_factory=list)
    persistence: DeviationPersistenceModel = Field(
        default_factory=DeviationPersistenceModel
    )
    breakpoint: Optional[BreakpointModel] = None


# ---------------------------------------------------------------------------
# 12. Joint NDVI-moisture contract (P1.4 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.joint_profile for a future joint
# endpoint.  Patterns and states are neutral statistics — never a
# diagnosis, severity level, or probability.  The moisture side is
# NDMI (Gao); the McFeeters NDWI is an open-water index and has no
# place in this contract.


class JointPointModel(BaseModel):
    """One calendar month with NDVI and moisture sides aligned."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    ndvi: Optional[float] = None
    moisture: Optional[float] = None
    ndvi_z: Optional[float] = None
    moisture_z: Optional[float] = None
    availability: str = "NEITHER"
    ndvi_quality: str = "unavailable"
    moisture_quality: str = "unavailable"
    ndvi_coverage: Optional[float] = None
    moisture_coverage: Optional[float] = None


class JointProfileModel(BaseModel):
    """NDVI and moisture profiles aligned by exact calendar month."""

    ndvi_key: str
    moisture_key: str
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    points: List[JointPointModel] = Field(default_factory=list)


class JointChangeModel(BaseModel):
    """Co-movement of the two sides between consecutive joint months."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    previous_window_start: Optional[str] = None
    ndvi_change: Optional[float] = None
    moisture_change: Optional[float] = None
    ndvi_direction: str = "INSUFFICIENT"
    moisture_direction: str = "INSUFFICIENT"
    pattern: str = "INSUFFICIENT"
    divergence: str = "INSUFFICIENT"
    days_elapsed: Optional[int] = None


class LagResultModel(BaseModel):
    """Moisture-at-t versus NDVI-at-t-plus-lag agreement."""

    lag_months: int = 0
    n_paired: int = 0
    agreement: Optional[float] = None
    correlation: Optional[float] = None
    sufficient: bool = False
    method: str = ""


class ScatterPointModel(BaseModel):
    """One paired month in NDVI/moisture space, fully traceable."""

    window_start: str = ""
    ndvi: float = 0.0
    moisture: float = 0.0
    ndvi_z: Optional[float] = None
    moisture_z: Optional[float] = None
    ndvi_quality: str = "unavailable"
    moisture_quality: str = "unavailable"


class ScatterDatasetModel(BaseModel):
    """Paired months in chronological order plus one summary number."""

    ndvi_key: str
    moisture_key: str
    points: List[ScatterPointModel] = Field(default_factory=list)
    correlation: Optional[float] = None
    n_paired: int = 0
    method: str = ""


class JointAnalysisModel(BaseModel):
    """Joint NDVI-moisture temporal analysis for one window."""

    ndvi_key: str
    moisture_key: str
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    joint: JointProfileModel
    changes: List[JointChangeModel] = Field(default_factory=list)
    lags: List[LagResultModel] = Field(default_factory=list)
    scatter: Optional[ScatterDatasetModel] = None


# ---------------------------------------------------------------------------
# 13. Spatial anomaly and hotspot contract (P1.5 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.spatial_profile for a future
# spatial endpoint.  Area and concordance states are neutral spatial
# posture (NORMAL_AREA, ANOMALOUS_AREA, CONCENTRATED_ANOMALY,
# SINGLE/MULTI_METRIC_ANOMALY, MIXED_METRICS, NO_CONCORDANCE) —
# never a diagnosis, severity level, or probability.


class SpatialCellModel(BaseModel):
    """One deterministic grid cell with WGS84 lon/lat bounds."""

    cell_id: str
    row: int = 0
    col: int = 0
    west: float = 0.0
    south: float = 0.0
    east: float = 0.0
    north: float = 0.0
    geometry: Dict[str, Any] = Field(default_factory=dict)


class CellObservationModel(BaseModel):
    """One cell's observation for one metric and window."""

    cell_id: str
    metric_key: str
    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = Field(
        default=None,
        description="Observed value; null when the cell had no usable observation",
    )
    unit: str = ""
    z_score: Optional[float] = None
    category: Optional[str] = None
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None


class SpatialSummaryModel(BaseModel):
    """Area-level aggregation over one metric's cell observations."""

    metric_key: str
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    n_cells: int = 0
    n_usable: int = 0
    n_missing: int = 0
    mean: Optional[float] = None
    median: Optional[float] = None
    anomalous_count: int = 0
    anomalous_fraction: Optional[float] = None
    min_coverage_percent: Optional[float] = None
    mean_coverage_percent: Optional[float] = None
    quality_counts: Dict[str, int] = Field(default_factory=dict)
    state: str = "INSUFFICIENT"
    method: str = ""


class CellConcordanceModel(BaseModel):
    """Multi-metric agreement for one cell and window."""

    cell_id: str
    window_start: str = ""
    window_end: str = ""
    metrics: List[str] = Field(default_factory=list)
    anomalous_metrics: List[str] = Field(default_factory=list)
    state: str = "INSUFFICIENT"


class CellPersistenceModel(BaseModel):
    """Per-cell deviation runs across consecutive valid periods."""

    cell_id: str
    longest_run_below: int = 0
    longest_run_above: int = 0
    n_anomalous: int = 0
    n_observed: int = 0
    n_missing: int = 0
    state: str = "INSUFFICIENT"


# ---------------------------------------------------------------------------
# 14. Spectral-profile contract (P2.1 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.spectral_profile for a future
# spectral endpoint.  Samples are discrete multispectral reflectance
# observations (never interpolated, never zero-filled); statuses are
# neutral availability states (available, insufficient, unavailable) —
# never a cause attribution, threshold, score, or probability.


class SpectralBandSampleModel(BaseModel):
    """One band's reflectance observation within a window."""

    band: str = Field(description="Sentinel-2 band identifier (e.g. B4)")
    wavelength_nm: float = Field(
        description="Nominal band centre wavelength in nanometres"
    )
    value: Optional[float] = Field(
        default=None,
        description="Reflectance (0-1); null when the band had no usable observation",
    )
    unit: str = "reflectance"
    status: str = "unavailable"
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None


class SpectralSlopeModel(BaseModel):
    """Observed slope between two adjacent observed bands."""

    from_band: str = ""
    to_band: str = ""
    wavelength_from_nm: float = 0.0
    wavelength_to_nm: float = 0.0
    value_from: Optional[float] = None
    value_to: Optional[float] = None
    slope_per_nm: Optional[float] = Field(
        default=None,
        description="Per-nanometre slope; null when either end is missing",
    )


class SpectralObservationModel(BaseModel):
    """The multispectral reflectance observed for one window."""

    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    dataset_id: Optional[str] = None
    unit: str = "reflectance"
    composite_method: str = ""
    image_count: Optional[int] = None
    coverage_percent: Optional[float] = None
    quality: str = "unavailable"
    samples: List[SpectralBandSampleModel] = Field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None


class SpectralProfileModel(BaseModel):
    """Chronological spectral observations sharing one band set."""

    band_set: List[str] = Field(default_factory=list)
    dataset_id: Optional[str] = None
    unit: str = "reflectance"
    composite_method: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    observations: List[SpectralObservationModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 15. Red-edge diagnostics contract (P2.2 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.red_edge for a future red-edge
# endpoint.  Diagnostics describe red-edge spectral behavior only
# (slopes in reflectance/nm, normalized differences as indices);
# statuses and directions are neutral availability/change states
# (available, insufficient, unavailable / INCREASE, DECREASE,
# STABLE, INSUFFICIENT) — never a cause attribution, cut-off,
# score, or probability.


class RedEdgeDiagnosticModel(BaseModel):
    """One red-edge diagnostic value for one window."""

    diagnostic_id: str = Field(description="Diagnostic identifier (e.g. re_slope_b4_b5)")
    formula: str = ""
    input_bands: List[str] = Field(default_factory=list)
    wavelengths_nm: List[float] = Field(default_factory=list)
    value: Optional[float] = Field(
        default=None,
        description="Diagnostic value; null when inputs were missing or the computation was undefined",
    )
    unit: str = ""
    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    dataset_id: Optional[str] = None
    status: str = "unavailable"
    limitations: List[str] = Field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None


class RedEdgeObservationDiagnosticsModel(BaseModel):
    """One month's full red-edge diagnostic set."""

    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    dataset_id: Optional[str] = None
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    diagnostics: List[RedEdgeDiagnosticModel] = Field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None


class RedEdgeChangeModel(BaseModel):
    """One diagnostic's step between consecutive monthly windows."""

    diagnostic_id: str = ""
    unit: str = ""
    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    previous_window_start: Optional[str] = None
    previous_window_end: Optional[str] = None
    value: Optional[float] = None
    previous_value: Optional[float] = None
    absolute_change: Optional[float] = None
    relative_change: Optional[float] = Field(
        default=None,
        description="Change relative to |previous|; null when previous is zero or missing",
    )
    days_elapsed: Optional[int] = None
    rate_per_day: Optional[float] = None
    direction: str = "INSUFFICIENT"


class RedEdgeSeriesModel(BaseModel):
    """Monthly red-edge diagnostics with consecutive-month steps."""

    diagnostic_ids: List[str] = Field(default_factory=list)
    dataset_id: Optional[str] = None
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    monthly: List[RedEdgeObservationDiagnosticsModel] = Field(default_factory=list)
    changes: List[RedEdgeChangeModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 16. Radar temporal profile contract (P2.3 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.radar_profile for a future radar
# endpoint.  Points are monthly Sentinel-1 observations in
# chronological order with explicit missing months (null values, no
# interpolation, no zero-fill); acquisition metadata (polarizations,
# mode, orbit pass, scale) restates the production composite
# contract — never a cause attribution, anomaly category, score, or
# probability.


class RadarProfilePointModel(BaseModel):
    """One monthly observation of a radar metric."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = Field(
        default=None,
        description="Observed value; null when the month had no usable observation",
    )
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Optional[Dict[str, Any]] = None


class RadarProfileModel(BaseModel):
    """Chronological monthly radar observations for one metric."""

    metric_key: str
    dataset_id: Optional[str] = None
    unit: str = ""
    polarizations: List[str] = Field(default_factory=list)
    mode: str = ""
    orbit_pass: str = ""
    scale_m: Optional[int] = None
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    points: List[RadarProfilePointModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 17. Radar anomaly/change contract (P2.4 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.radar_anomaly, which itself only
# orchestrates the generic P1.2 baseline/anomaly and P1.3
# change/persistence machinery over P2.3 monthly radar profiles.
# Categories, directions, and states are the existing neutral
# statistics (NORMAL, BELOW_BASELINE, ABOVE_BASELINE,
# INSUFFICIENT_BASELINE / INCREASE, DECREASE, STABLE, INSUFFICIENT /
# PERSISTENT, NO_PERSISTENCE, INSUFFICIENT) — never a cause
# attribution, score, or probability.  Each section is labelled by
# how it was derived (observed, baseline-derived, anomaly-derived,
# change-derived).


class RadarAnomalyAnalysisModel(BaseModel):
    """Baseline, anomaly, change, and persistence for one radar metric."""

    metric_key: str
    dataset_id: Optional[str] = None
    unit: str = ""
    polarizations: List[str] = Field(default_factory=list)
    mode: str = ""
    orbit_pass: str = ""
    scale_m: Optional[int] = None
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    observed: Dict[str, Any] = Field(default_factory=dict)
    baseline: Optional[ProfileBaselineModel] = None
    anomalies: List[AnomalyPointModel] = Field(default_factory=list)
    changes: List[MonthChangeModel] = Field(default_factory=list)
    persistence: DeviationPersistenceModel = Field(
        default_factory=DeviationPersistenceModel
    )
    methods: Dict[str, str] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 18. Multi-sensor concordance contract (P2.5 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.concordance, which only aligns
# existing optical, red-edge, and radar evidence by exact monthly
# window and reports deterministic categorical states
# (MULTI_SENSOR_CONCORDANT, OPTICAL_ONLY, RADAR_ONLY, DIVERGENT,
# MIXED_EVIDENCE, INSUFFICIENT_EVIDENCE) — never a cause
# attribution, score, or probability.  Every month carries the rule
# identifier and human-readable reasons so the statement is
# answerable without recomputing hidden logic.


class ConcordanceEvidenceModel(BaseModel):
    """One metric's evidence for one monthly window."""

    family: str = ""
    sensor: str = ""
    metric_id: str = ""
    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    value: Optional[float] = None
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    state_kind: str = "observation"
    state: Optional[str] = None
    orientation: str = "INSUFFICIENT"
    provenance: Optional[Dict[str, Any]] = None


class FamilyEvidenceModel(BaseModel):
    """One family's aligned evidence for one month."""

    family: str = ""
    sensor: str = ""
    orientation: str = "INSUFFICIENT"
    usable_count: int = 0
    directional_count: int = 0
    metric_ids: List[str] = Field(default_factory=list)
    items: List[ConcordanceEvidenceModel] = Field(default_factory=list)


class ConcordanceMonthModel(BaseModel):
    """The concordance statement for one exact monthly window."""

    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    state: str = "INSUFFICIENT_EVIDENCE"
    rule_id: str = ""
    rule: str = ""
    reasons: List[str] = Field(default_factory=list)
    families: List[FamilyEvidenceModel] = Field(default_factory=list)


class ConcordanceSummaryModel(BaseModel):
    """Deterministic counts and runs over a concordance series."""

    n_months: int = 0
    n_concordant: int = 0
    n_divergent: int = 0
    n_mixed: int = 0
    n_optical_only: int = 0
    n_radar_only: int = 0
    n_insufficient: int = 0
    concordant_months: List[str] = Field(default_factory=list)
    divergent_months: List[str] = Field(default_factory=list)
    longest_concordant_run: int = 0
    longest_concordant_run_start: Optional[str] = None
    longest_concordant_run_end: Optional[str] = None
    longest_divergent_run: int = 0
    longest_divergent_run_start: Optional[str] = None
    longest_divergent_run_end: Optional[str] = None


class ConcordanceSeriesModel(BaseModel):
    """Monthly concordance statements with a temporal summary."""

    window_start: Optional[str] = None
    window_end: Optional[str] = None
    rule_id: str = ""
    rule: str = ""
    months: List[ConcordanceMonthModel] = Field(default_factory=list)
    summary: Optional[ConcordanceSummaryModel] = None
    methods: Dict[str, str] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 19. Evidence pattern engine contract (P3.1 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.pattern_engine, which only
# describes combinations of already-computed P1/P2 evidence with
# generic, sensor-agnostic pattern types (PERSISTENT_ANOMALY,
# RAPID_CHANGE, MULTI_SENSOR_CONCORDANCE, DIVERGENT_SENSOR_EVIDENCE,
# SEQUENTIAL_CHANGE, INSUFFICIENT_EVIDENCE) and a small status
# vocabulary (OBSERVED, NOT_OBSERVED, INSUFFICIENT_EVIDENCE) —
# never a cause attribution, score, or probability.  No numeric
# confidence exists anywhere in this contract.


class PatternEvidenceModel(BaseModel):
    """Narrow internal evidence item for one metric and one window."""

    evidence_id: str = ""
    source_module: str = ""
    metric_id: str = ""
    sensor: str = ""
    family: str = ""
    window_start: str = Field(description="Observation window start (YYYY-MM-DD)")
    window_end: str = Field(description="Observation window end (YYYY-MM-DD)")
    value: Optional[float] = None
    unit: str = ""
    anomaly_state: Optional[str] = None
    change_direction: Optional[str] = None
    rapid: Optional[str] = None
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Optional[Dict[str, Any]] = None
    limitations: List[str] = Field(default_factory=list)


class EvidencePatternModel(BaseModel):
    """One described evidence pattern."""

    pattern_id: str = ""
    pattern_type: str = ""
    window_start: str = Field(description="Pattern window start (YYYY-MM-DD)")
    window_end: str = Field(description="Pattern window end (YYYY-MM-DD)")
    status: str = "INSUFFICIENT_EVIDENCE"
    contributing_evidence_ids: List[str] = Field(default_factory=list)
    contributing_metric_ids: List[str] = Field(default_factory=list)
    contributing_sensors: List[str] = Field(default_factory=list)
    source_states: Dict[str, str] = Field(default_factory=dict)
    rule_id: str = ""
    rule_version: str = ""
    rule_description: str = ""
    explanation: str = ""
    quality_by_evidence: Dict[str, str] = Field(default_factory=dict)
    coverage_by_evidence: Dict[str, Optional[float]] = Field(default_factory=dict)
    provenance_by_evidence: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class PatternRuleModel(BaseModel):
    """One deterministic registry rule."""

    rule_id: str = ""
    rule_version: str = ""
    name: str = ""
    pattern_type: str = ""
    requires: List[str] = Field(default_factory=list)
    predicate: str = ""
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 20. Cross-pattern validation contract (P3.3 validation layer)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.cross_pattern_validation, which
# only validates already-established P3.1/P3.2 pattern outputs for
# one exact window with a descriptive status vocabulary
# (CONSISTENT, MIXED_EVIDENCE, INSUFFICIENT_EVIDENCE) — never a
# cause attribution, score, confidence, probability, or risk value.
# ``pattern_count`` and ``independent_sensor_count`` are descriptive
# audit counts, not strength readings.  No numeric grade exists
# anywhere in this contract.


class CrossPatternValidationModel(BaseModel):
    """One cross-pattern validation statement for one exact window."""

    validation_id: str = ""
    window_start: str = Field(description="Evaluated window start (YYYY-MM-DD)")
    window_end: str = Field(description="Evaluated window end (YYYY-MM-DD)")
    status: str = "INSUFFICIENT_EVIDENCE"
    contributing_pattern_ids: List[str] = Field(default_factory=list)
    compatible_pattern_ids: List[str] = Field(default_factory=list)
    conflicting_pattern_ids: List[str] = Field(default_factory=list)
    contributing_metric_ids: List[str] = Field(default_factory=list)
    contributing_sensors: List[str] = Field(default_factory=list)
    contributing_families: List[str] = Field(default_factory=list)
    pattern_count: int = 0
    independent_sensor_count: int = 0
    overlapping_evidence: bool = False
    overlapping_metric_ids: List[str] = Field(default_factory=list)
    overlapping_evidence_ids: List[str] = Field(default_factory=list)
    source_pattern_types: Dict[str, str] = Field(default_factory=dict)
    source_pattern_states: Dict[str, str] = Field(default_factory=dict)
    rule_id: str = ""
    rule_version: str = ""
    rule_description: str = ""
    explanation: str = ""
    overlap_explanation: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class ValidationRuleModel(BaseModel):
    """One deterministic cross-pattern validation rule."""

    rule_id: str = ""
    rule_version: str = ""
    name: str = ""
    pattern_type: str = ""
    requires: List[str] = Field(default_factory=list)
    predicate: str = ""
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 21. Thermal visualization contract (P4.2-P4.4 layers)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.thermal_profile,
# thermal_anomaly, and thermal_concordance for future thermal-chart
# and thermal-evidence views.  Missing months are explicit nulls;
# no interpolation is ever represented here.  MODIS LST
# (land-surface / skin temperature) and ERA5-Land 2 m air
# temperature keep separate models and separate fields
# (``lst_celsius`` vs ``air_temperature_celsius``) — they are never
# collapsed into one generic temperature, never averaged, and
# neither is presented as canopy temperature.


class ThermalProfilePointModel(BaseModel):
    """One monthly observation of one thermal quantity."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    value: Optional[float] = Field(
        default=None,
        description="Observed value; null when the month had no usable observation",
    )
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    source_dataset_id: str = ""
    source_band: str = ""
    physical_quantity: str = ""
    aggregation_method: str = ""
    temporal_resolution: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ThermalSourceProfileModel(BaseModel):
    """A chronological sequence of monthly observations, one quantity."""

    profile_kind: str = Field(
        description="LST_PROFILE or AIR_TEMPERATURE_PROFILE, never generic"
    )
    metric_key: str
    dataset_id: Optional[str] = None
    fallback_dataset_id: Optional[str] = None
    band: str = ""
    unit: str = ""
    physical_quantity: str = ""
    physical_quantity_label: str = ""
    measurement_basis: str = ""
    temporal_resolution: str = ""
    aggregation_method: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    limitations: List[str] = Field(default_factory=list)
    points: List[ThermalProfilePointModel] = Field(default_factory=list)


class ThermalHarmonizedPeriodModel(BaseModel):
    """One calendar month holding two independent observations."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    lst_celsius: Optional[float] = Field(
        default=None,
        description="LST observation; null when the source had none",
    )
    lst: Optional[ThermalProfilePointModel] = None
    air_temperature_celsius: Optional[float] = Field(
        default=None,
        description="ERA5 2 m air-temperature observation; kept separate from LST",
    )
    air: Optional[ThermalProfilePointModel] = None
    harmonization_method: str = ""
    contributing_lst_windows: List[List[str]] = Field(default_factory=list)
    contributing_air_windows: List[List[str]] = Field(default_factory=list)


class ThermalHarmonizedProfileModel(BaseModel):
    """Chronological monthly pairing of LST with air temperature."""

    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    harmonization: str = "MONTHLY"
    harmonization_method: str = ""
    limitations: List[str] = Field(default_factory=list)
    periods: List[ThermalHarmonizedPeriodModel] = Field(default_factory=list)


class ThermalAnomalyPointModel(AnomalyPointModel):
    """One thermal month scored against its own baseline.

    Inherits the backend-owned anomaly shape (value, z-score,
    percentile, neutral category) and adds only identity and
    derivation metadata.  No frontend scoring is representable.
    """

    derivation: str = ""
    profile_kind: str = ""
    physical_quantity: str = ""
    thermal_provenance: Dict[str, Any] = Field(default_factory=dict)


class ThermalChangeModel(MonthChangeModel):
    """One thermal observation-to-observation change.

    Inherits the backend-owned change shape (absolute, relative,
    per-day, direction, rapid flag) and adds only identity and
    derivation metadata.  No frontend recomputation is
    representable.
    """

    derivation: str = ""
    profile_kind: str = ""
    physical_quantity: str = ""
    thermal_provenance: Dict[str, Any] = Field(default_factory=dict)


class ThermalMetricAnalysisModel(BaseModel):
    """Baseline, anomaly, change, and persistence for one quantity."""

    profile_kind: str = ""
    physical_quantity: str = ""
    physical_quantity_label: str = ""
    metric_key: str
    dataset_id: Optional[str] = None
    band: str = ""
    measurement_basis: str = ""
    unit: str = ""
    window_start: str = Field(description="Requested window start (YYYY-MM-DD)")
    window_end: str = Field(description="Requested window end (YYYY-MM-DD)")
    step: str = "calendar_month"
    observed: Dict[str, Any] = Field(default_factory=dict)
    baseline: Optional[ProfileBaselineModel] = None
    baseline_refusal_reason: Optional[str] = None
    anomalies: List[ThermalAnomalyPointModel] = Field(default_factory=list)
    changes: List[ThermalChangeModel] = Field(default_factory=list)
    persistence: DeviationPersistenceModel = Field(
        default_factory=DeviationPersistenceModel
    )
    methods: Dict[str, str] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class ThermalPairAnalysisModel(BaseModel):
    """Two independent quantity analyses sharing calendar alignment only."""

    lst: ThermalMetricAnalysisModel
    air: ThermalMetricAnalysisModel
    alignment: str = "calendar_month"
    alignment_method: str = ""
    limitations: List[str] = Field(default_factory=list)


class ThermalSideEvidenceModel(BaseModel):
    """One thermal quantity's oriented evidence for one month."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    profile_kind: str = ""
    physical_quantity: str = ""
    source_role: str = Field(
        description="REMOTE_SENSING_LAND_SURFACE or METEOROLOGICAL_CONTEXT"
    )
    metric_id: str = ""
    dataset_id: Optional[str] = None
    band: str = ""
    orientation: str = "INSUFFICIENT"
    orientation_source: str = "anomaly"
    source_state: Optional[str] = None
    source_state_kind: str = "anomaly"
    value: Optional[float] = None
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ThermalConcordanceMonthModel(BaseModel):
    """The thermal-context statement for one exact monthly window."""

    window_start: str = Field(description="Sub-window start (YYYY-MM-DD)")
    window_end: str = Field(description="Sub-window end (YYYY-MM-DD)")
    rule_id: str = ""
    rule: str = ""
    lst: Optional[ThermalSideEvidenceModel] = None
    air: Optional[ThermalSideEvidenceModel] = None
    p25_state: Optional[str] = None
    p25_rule_id: Optional[str] = None
    optical_orientation: Optional[str] = None
    red_edge_orientation: Optional[str] = None
    radar_orientation: Optional[str] = None
    lst_relationship: str = "INSUFFICIENT_EVIDENCE"
    air_relationship: str = "INSUFFICIENT_EVIDENCE"
    lst_era5_agreement: Optional[str] = None
    observational_sensor_count: int = 0
    meteorological_context_present: bool = False
    explanations: List[str] = Field(default_factory=list)


class ThermalConcordanceAnalysisModel(BaseModel):
    """Monthly thermal-context statements with a temporal summary."""

    window_start: Optional[str] = None
    window_end: Optional[str] = None
    rule_id: str = ""
    rule: str = ""
    months: List[ThermalConcordanceMonthModel] = Field(default_factory=list)
    summary: Dict[str, int] = Field(default_factory=dict)
    methods: Dict[str, str] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 22. Analysis temporal section (P5.3 integration phase)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  This
# section carries already-computed P1-P4 monthly intelligence inside
# the existing Agriculture /analysis response so visualizations can
# render backend monthly data.  Every payload below is produced by
# an existing P1-P4 builder and serialized through its canonical
# to_dict/model; the API layer orchestrates and transports only.
# Months keep exact windows, nulls stay null, states stay verbatim,
# and LST never merges with ERA5 air temperature.


class TemporalSectionModel(BaseModel):
    """Monthly temporal intelligence for one analysis request."""

    window_start: str = ""
    window_end: str = ""
    profiles: Dict[str, TemporalProfileModel] = Field(default_factory=dict)
    anomalies: Dict[str, AnomalyProfileModel] = Field(default_factory=dict)
    changes: Dict[str, ChangeProfileModel] = Field(default_factory=dict)
    radar_profiles: Dict[str, RadarProfileModel] = Field(default_factory=dict)
    radar_analyses: Dict[str, RadarAnomalyAnalysisModel] = Field(
        default_factory=dict
    )
    joint: Optional[JointAnalysisModel] = None
    concordance: Optional[ConcordanceSeriesModel] = None
    thermal_profiles: Dict[str, ThermalSourceProfileModel] = Field(
        default_factory=dict
    )
    thermal_analyses: Dict[str, ThermalMetricAnalysisModel] = Field(
        default_factory=dict
    )
    thermal_harmonized: Optional[ThermalHarmonizedProfileModel] = None
    thermal_pair: Optional[ThermalPairAnalysisModel] = None
    thermal_concordance: Optional[ThermalConcordanceAnalysisModel] = Field(
        default=None
    )
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 23. Analysis spatial section (P5.3-S integration phase)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  This
# section carries already-computed P1.5 grid intelligence inside the
# existing Agriculture /analysis response so visualizations can
# render backend cells.  Every payload below is produced by an
# existing P1.5 builder and serialized through its canonical
# to_dict; the API layer orchestrates and transports only.  Cell
# geometry travels verbatim (WGS84 lon/lat, closed rings), nulls
# stay null, and states stay verbatim.


class SpatialSectionModel(BaseModel):
    """Deterministic grid intelligence for one analysis request."""

    window_start: str = ""
    window_end: str = ""
    grid_rows: int = 0
    grid_cols: int = 0
    bbox: List[float] = Field(default_factory=list)
    cells: List[SpatialCellModel] = Field(default_factory=list)
    observations: List[CellObservationModel] = Field(default_factory=list)
    summaries: Dict[str, SpatialSummaryModel] = Field(default_factory=dict)
    concordance: List[CellConcordanceModel] = Field(default_factory=list)
    persistence: List[CellPersistenceModel] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 24. Ground-truth validation contract (P6.1 foundation)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.ground_truth, which only describes
# independently supplied reference observations and their linkage to
# existing analysis outputs.  Reference records are carried verbatim
# (source, method, time, variable, quality, limitations); linkage
# states are descriptive only.  Nothing here is wired into the
# /analysis response in this phase.


class GroundTruthObservationModel(BaseModel):
    """One independently supplied reference observation."""

    observation_id: str = ""
    variable: str = ""
    value: Optional[float] = None
    unit: str = ""
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    observed_on: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    source: str = ""
    method: str = ""
    quality: str = "unknown"
    status: str = "available"
    metric_key: Optional[str] = None
    domain: Optional[str] = None
    cell_id: Optional[str] = None
    contract_version: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class ValidationTargetModel(BaseModel):
    """One analysis output placed beside one reference observation."""

    target_id: str = ""
    analysis_id: Optional[str] = None
    metric_key: str = ""
    domain: str = ""
    window_start: str = ""
    window_end: str = ""
    cell_id: Optional[str] = None
    observation_id: str = ""
    relationship: str = ""
    status: str = "NOT_VALIDATED"
    linkage_reason: str = ""
    contract_version: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 25. Validation result contract (P6.2 engine)
# ---------------------------------------------------------------------------
# Additive models only: no existing response model is touched.  These
# mirror app.services.agriculture.validation_engine, which only sets
# supplied analysis outputs beside supplied reference observations
# through the frozen P6.1 linkage.  Every source value stays
# traceable; relationships and states stay descriptive.  No numeric
# reading is attached to any record below.


class RejectedRecordModel(BaseModel):
    """One raw record that could not become a reference observation."""

    index: int = 0
    observation_id: str = ""
    reasons: List[str] = Field(default_factory=list)


class DuplicateRecordModel(BaseModel):
    """One observation identity seen more than once."""

    observation_id: str = ""
    kept_index: int = 0
    dropped_indices: List[int] = Field(default_factory=list)
    reason: str = ""


class ReferenceCollectionModel(BaseModel):
    """In-memory reference observations ready for validation."""

    observations: List[GroundTruthObservationModel] = Field(default_factory=list)
    rejected: List[RejectedRecordModel] = Field(default_factory=list)
    duplicates: List[DuplicateRecordModel] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    contract_version: str = ""
    engine_version: str = ""


class ValidationResultModel(BaseModel):
    """One analysis output set beside one reference observation."""
    validation_id: str = ""
    target_id: str = ""
    observation_id: str = ""
    metric_key: str = ""
    domain: str = ""
    analysis_id: Optional[str] = None
    analysis_window_start: str = ""
    analysis_window_end: str = ""
    analysis_cell_id: Optional[str] = None
    analysis_value: Optional[float] = None
    analysis_unit: str = ""
    analysis_state: Optional[str] = None
    reference_variable: str = ""
    reference_value: Optional[float] = None
    reference_unit: str = ""
    reference_state: Optional[str] = None
    reference_source: str = ""
    reference_method: str = ""
    reference_time: Optional[str] = None
    temporal_relationship: str = ""
    spatial_relationship: str = ""
    metric_relationship: str = ""
    states_agree: Optional[bool] = None
    values_comparable: bool = False
    status: str = "NOT_VALIDATED"
    linkage_reason: str = ""
    contract_version: str = ""
    engine_version: str = ""
    provenance: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class ValidationSectionModel(BaseModel):
    """Deterministic ground-truth validation for one analysis response.

    Additive P6.3 section: present only when reference observations
    were supplied with the request.  Reuses the P6.2 result and
    collection schemas without duplication.
    """

    results: List[ValidationResultModel] = Field(default_factory=list)
    rejected_references: List[RejectedRecordModel] = Field(default_factory=list)
    duplicates: List[DuplicateRecordModel] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    contract_version: str = ""
    engine_version: str = ""
