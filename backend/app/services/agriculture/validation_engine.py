"""Deterministic ground-truth validation engine (P6.2).

Pure, in-memory validation over the frozen P6.1 contracts.  Raw
supplied reference records are normalized into
``GroundTruthObservation`` objects, deduplicated by explicit
identity, held in a ``ReferenceCollection``, and placed beside
existing analysis outputs through P6.1 ``link()``.  Each pairing
yields a ``ValidationResult`` that preserves every source value
with its relationships and limitations.

What this module is NOT:

* a source of observations — malformed records are rejected with
  explicit reasons, never repaired or inferred;
* a remote-sensing interpreter — analysis values and states are
  never converted into reference variables.  A numeric analysis
  value beside a biological reference label is reported as
  semantically incompatible, never as a finding;
* a grader — no rates, matrices, curves, or numeric readings;
* a store — no database, no filesystem, no network, no Earth
  Engine calls.  Everything here is bounded by the supplied
  analysis outputs and reference observations.

One malformed reference never invalidates the collection; one
unsupported analysis output never stops the remaining outputs.
Every item carries its own status and limitations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.services.agriculture.ground_truth import (
    GROUND_TRUTH_VERSION,
    STATUS_INSUFFICIENT_ANALYSIS,
    STATUS_INSUFFICIENT_REFERENCE,
    STATUS_MATCHED,
    STATUS_NOT_VALIDATED,
    GroundTruthObservation,
    ValidationTarget,
    build_target_id,
    declare_not_validated,
    link,
    match_metric,
    match_spatial,
    match_temporal,
    reference_window,
    sort_targets,
)

__all__ = [
    "VALIDATION_ENGINE_VERSION",
    "SEMANTICALLY_INCOMPATIBLE",
    "NO_CANDIDATE_REFERENCE",
    "UNSUPPORTED_ANALYSIS_OUTPUT",
    "RejectedRecord",
    "DuplicateRecord",
    "ReferenceCollection",
    "NormalizedAnalysis",
    "SemanticAssessment",
    "ValidationResult",
    "ValidationReport",
    "duplicate_key",
    "deduplicate",
    "ingest_reference_records",
    "from_scalar_evidence",
    "from_temporal_point",
    "from_cell_observation",
    "normalize_analysis",
    "assess_semantics",
    "build_validation_id",
    "make_result",
    "validate",
]

#: Engine version carried on every serialized record.
VALIDATION_ENGINE_VERSION = "P62_V1"

#: Relationship when value/state semantics cannot be compared.
SEMANTICALLY_INCOMPATIBLE = "SEMANTICALLY_INCOMPATIBLE"
#: Relationship when no reference claims the analysis metric.
NO_CANDIDATE_REFERENCE = "NO_CANDIDATE_REFERENCE"
#: Relationship for analysis shapes the engine does not support.
UNSUPPORTED_ANALYSIS_OUTPUT = "UNSUPPORTED_ANALYSIS_OUTPUT"

#: Reference variables that carry no comparable semantics.
_NON_COMPARABLE_VARIABLES: Tuple[str, ...] = ("unknown", "not_assessed")


@dataclass(frozen=True)
class RejectedRecord:
    """One raw record that could not become a reference observation."""

    index: int = 0
    observation_id: str = ""
    reasons: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "observation_id": self.observation_id,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RejectedRecord":
        return cls(
            index=int(payload.get("index", 0)),
            observation_id=str(payload.get("observation_id", "")),
            reasons=tuple(payload.get("reasons", ())),
        )


@dataclass(frozen=True)
class DuplicateRecord:
    """One observation identity seen more than once.

    The first occurrence is kept; later ones are dropped.  Identity
    is the explicit ``observation_id`` only — never approximate
    geography, nearest dates, or shared variable/metric/cell/source.
    """

    observation_id: str = ""
    kept_index: int = 0
    dropped_indices: Tuple[int, ...] = ()
    reason: str = "duplicate observation_id; first occurrence kept"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "kept_index": self.kept_index,
            "dropped_indices": list(self.dropped_indices),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DuplicateRecord":
        return cls(
            observation_id=str(payload.get("observation_id", "")),
            kept_index=int(payload.get("kept_index", 0)),
            dropped_indices=tuple(payload.get("dropped_indices", ())),
            reason=str(payload.get("reason", "")),
        )


def duplicate_key(observation: GroundTruthObservation) -> Optional[str]:
    """Explicit duplicate identity: the observation id, or None.

    Records without an id cannot be matched safely, so they are
    never deduplicated; callers keep them separate and say why.
    """
    if isinstance(observation.observation_id, str) and observation.observation_id:
        return observation.observation_id
    return None


def deduplicate(
    observations: Sequence[GroundTruthObservation],
) -> Tuple[Tuple[GroundTruthObservation, ...], Tuple[DuplicateRecord, ...]]:
    """Keep the first occurrence of each observation id.

    Deterministic in input order.  Records without an id are always
    kept.  Nothing is merged and nothing is compared approximately.
    """
    kept: List[GroundTruthObservation] = []
    dropped: Dict[str, List[int]] = {}
    kept_index_of: Dict[str, int] = {}
    unidentified = 0
    for position, observation in enumerate(observations):
        key = duplicate_key(observation)
        if key is None:
            kept.append(observation)
            unidentified += 1
            continue
        if key in kept_index_of:
            dropped.setdefault(key, []).append(position)
            continue
        kept_index_of[key] = len(kept)
        kept.append(observation)
    duplicates = tuple(
        DuplicateRecord(
            observation_id=key,
            kept_index=kept_index_of[key],
            dropped_indices=tuple(positions),
        )
        for key, positions in dropped.items()
    )
    return tuple(kept), duplicates


@dataclass(frozen=True)
class ReferenceCollection:
    """In-memory reference observations ready for validation.

    Holds usable observations in ingest order plus explicit
    rejection and duplication records.  No storage beyond memory.
    """

    observations: Tuple[GroundTruthObservation, ...] = ()
    rejected: Tuple[RejectedRecord, ...] = ()
    duplicates: Tuple[DuplicateRecord, ...] = ()
    limitations: Tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "ReferenceCollection":
        return cls()

    def by_observation_id(self, observation_id: str) -> Optional[GroundTruthObservation]:
        for observation in self.observations:
            if observation.observation_id == observation_id:
                return observation
        return None

    def for_metric(self, metric_key: str) -> Tuple[GroundTruthObservation, ...]:
        """Usable observations claiming a metric, by exact key."""
        return tuple(
            observation
            for observation in self.observations
            if observation.metric_key == metric_key
        )

    def for_cell(self, cell_id: str) -> Tuple[GroundTruthObservation, ...]:
        """Usable observations naming a cell, by exact identity."""
        return tuple(
            observation
            for observation in self.observations
            if observation.cell_id == cell_id
        )

    def candidates_for(self, metric_key: str) -> Tuple[GroundTruthObservation, ...]:
        """References eligible beside one analysis output.

        An observation is a candidate when it declares no metric
        linkage or declares exactly this metric.  Ordered by
        observation id for determinism.
        """
        eligible = [
            observation
            for observation in self.observations
            if observation.metric_key is None or observation.metric_key == metric_key
        ]
        return tuple(sorted(eligible, key=lambda item: item.observation_id))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "rejected": [item.to_dict() for item in self.rejected],
            "duplicates": [item.to_dict() for item in self.duplicates],
            "limitations": list(self.limitations),
            "contract_version": GROUND_TRUTH_VERSION,
            "engine_version": VALIDATION_ENGINE_VERSION,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReferenceCollection":
        return cls(
            observations=tuple(
                GroundTruthObservation.from_dict(item)
                for item in payload.get("observations", [])
            ),
            rejected=tuple(
                RejectedRecord.from_dict(item) for item in payload.get("rejected", [])
            ),
            duplicates=tuple(
                DuplicateRecord.from_dict(item)
                for item in payload.get("duplicates", [])
            ),
            limitations=tuple(payload.get("limitations", ())),
        )


def ingest_reference_records(
    records: Sequence[Mapping[str, Any]],
) -> ReferenceCollection:
    """Normalize raw supplied records into a reference collection.

    Each record becomes a ``GroundTruthObservation`` through the
    frozen P6.1 mapping; records with refusal reasons are rejected
    with those reasons attached.  Non-mapping entries are rejected
    as malformed.  Usable records are deduplicated by explicit
    observation id.  Nothing is inferred and nothing is repaired.
    """
    usable: List[GroundTruthObservation] = []
    rejected: List[RejectedRecord] = []
    for position, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            rejected.append(
                RejectedRecord(
                    index=position,
                    observation_id="",
                    reasons=("malformed_record",),
                )
            )
            continue
        try:
            observation = GroundTruthObservation.from_dict(raw)
        except (TypeError, ValueError, AttributeError):
            rejected.append(
                RejectedRecord(
                    index=position,
                    observation_id=str(raw.get("observation_id", "")),
                    reasons=("unreadable_record",),
                )
            )
            continue
        reasons = observation.refusal_reasons()
        if reasons:
            rejected.append(
                RejectedRecord(
                    index=position,
                    observation_id=observation.observation_id,
                    reasons=reasons,
                )
            )
            continue
        if observation.status == "unavailable":
            rejected.append(
                RejectedRecord(
                    index=position,
                    observation_id=observation.observation_id,
                    reasons=("reference_unavailable",),
                )
            )
            continue
        usable.append(observation)
    kept, duplicates = deduplicate(usable)
    limitations: List[str] = []
    if rejected:
        limitations.append(f"{len(rejected)} supplied records rejected with reasons")
    if duplicates:
        limitations.append(
            f"{len(duplicates)} duplicate observation identities; "
            "first occurrences kept"
        )
    return ReferenceCollection(
        observations=kept,
        rejected=tuple(rejected),
        duplicates=duplicates,
        limitations=tuple(limitations),
    )


@dataclass(frozen=True)
class NormalizedAnalysis:
    """One supported analysis output in linkage-ready form.

    ``state`` carries the source state's verbatim wording (status,
    category, or direction).  ``supported`` is False only for shapes
    the engine does not cover, with the reason stated.
    """

    kind: str = ""
    metric_key: str = ""
    domain: str = ""
    window_start: str = ""
    window_end: str = ""
    cell_id: Optional[str] = None
    value: Optional[float] = None
    unit: str = ""
    state: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    supported: bool = True
    reason: str = ""

    def to_mapping(self) -> Dict[str, Any]:
        """The mapping P6.1 ``link()`` consumes."""
        mapping: Dict[str, Any] = {
            "metric_key": self.metric_key,
            "domain": self.domain,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
        }
        if self.cell_id is not None:
            mapping["cell_id"] = self.cell_id
        if self.state is not None:
            mapping["status"] = self.state
        return mapping

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "metric_key": self.metric_key,
            "domain": self.domain,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "cell_id": self.cell_id,
            "value": self.value,
            "unit": self.unit,
            "state": self.state,
            "provenance": dict(self.provenance),
            "supported": self.supported,
            "reason": self.reason,
            "engine_version": VALIDATION_ENGINE_VERSION,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NormalizedAnalysis":
        return cls(
            kind=str(payload.get("kind", "")),
            metric_key=str(payload.get("metric_key", "")),
            domain=str(payload.get("domain", "")),
            window_start=str(payload.get("window_start", "")),
            window_end=str(payload.get("window_end", "")),
            cell_id=payload.get("cell_id"),
            value=payload.get("value"),
            unit=str(payload.get("unit", "")),
            state=payload.get("state"),
            provenance=dict(payload.get("provenance", {})),
            supported=bool(payload.get("supported", True)),
            reason=str(payload.get("reason", "")),
        )


def _verbatim_provenance(payload: Mapping[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    """Copy listed provenance fields verbatim when present."""
    return {key: payload[key] for key in keys if key in payload and payload[key] is not None}


def from_scalar_evidence(item: Mapping[str, Any], domain: str = "") -> NormalizedAnalysis:
    """Adapt an evidence-item-shaped record (scalar evidence, §7A)."""
    if not isinstance(item, Mapping):
        return NormalizedAnalysis(
            kind="scalar_evidence", supported=False, reason="unreadable evidence item"
        )
    metric = item.get("metric_key", "")
    if not isinstance(metric, str) or not metric:
        return NormalizedAnalysis(
            kind="scalar_evidence", supported=False, reason="missing metric_key"
        )
    resolved_domain = domain if isinstance(domain, str) and domain else item.get("domain", "")
    return NormalizedAnalysis(
        kind="scalar_evidence",
        metric_key=metric,
        domain=resolved_domain if isinstance(resolved_domain, str) else "",
        window_start=item.get("temporal_start", "") if isinstance(item.get("temporal_start", ""), str) else "",
        window_end=item.get("temporal_end", "") if isinstance(item.get("temporal_end", ""), str) else "",
        value=item.get("value"),
        unit=item.get("unit", "") if isinstance(item.get("unit", ""), str) else "",
        state=item.get("status") if isinstance(item.get("status"), str) else None,
        provenance=_verbatim_provenance(
            item, ("source_dataset", "quality", "display_name", "is_proxy")
        ),
    )


def from_temporal_point(
    point: Mapping[str, Any], metric_key: str, domain: str = ""
) -> NormalizedAnalysis:
    """Adapt a temporal-profile-point-shaped record (§7B)."""
    if not isinstance(point, Mapping):
        return NormalizedAnalysis(
            kind="temporal_point", supported=False, reason="unreadable temporal point"
        )
    if not isinstance(metric_key, str) or not metric_key:
        return NormalizedAnalysis(
            kind="temporal_point", supported=False, reason="missing metric_key"
        )
    window_start = point.get("window_start", "")
    window_end = point.get("window_end", "")
    if not isinstance(window_start, str) or not window_start \
            or not isinstance(window_end, str) or not window_end:
        return NormalizedAnalysis(
            kind="temporal_point", supported=False, reason="missing window"
        )
    state = point.get("category")
    if not isinstance(state, str):
        direction = point.get("direction")
        state = direction if isinstance(direction, str) else None
    return NormalizedAnalysis(
        kind="temporal_point",
        metric_key=metric_key,
        domain=domain if isinstance(domain, str) else "",
        window_start=window_start,
        window_end=window_end,
        value=point.get("value"),
        unit=point.get("unit", "") if isinstance(point.get("unit", ""), str) else "",
        state=state,
        provenance=_verbatim_provenance(
            point, ("quality", "coverage_percent", "image_count")
        ),
    )


def from_cell_observation(observation: Mapping[str, Any]) -> NormalizedAnalysis:
    """Adapt a spatial-cell-observation-shaped record (§7C)."""
    if not isinstance(observation, Mapping):
        return NormalizedAnalysis(
            kind="cell_observation", supported=False, reason="unreadable cell observation"
        )
    metric = observation.get("metric_key", "")
    window_start = observation.get("window_start", "")
    window_end = observation.get("window_end", "")
    if not isinstance(metric, str) or not metric:
        return NormalizedAnalysis(
            kind="cell_observation", supported=False, reason="missing metric_key"
        )
    if not isinstance(window_start, str) or not window_start \
            or not isinstance(window_end, str) or not window_end:
        return NormalizedAnalysis(
            kind="cell_observation", supported=False, reason="missing window"
        )
    cell = observation.get("cell_id")
    category = observation.get("category")
    return NormalizedAnalysis(
        kind="cell_observation",
        metric_key=metric,
        domain=observation.get("domain", "") if isinstance(observation.get("domain", ""), str) else "",
        window_start=window_start,
        window_end=window_end,
        cell_id=cell if isinstance(cell, str) else None,
        value=observation.get("value"),
        unit=observation.get("unit", "") if isinstance(observation.get("unit", ""), str) else "",
        state=category if isinstance(category, str) else None,
        provenance=_verbatim_provenance(
            observation, ("quality", "coverage_percent", "image_count")
        ),
    )


def normalize_analysis(
    kind: str, payload: Mapping[str, Any], **hints: Any
) -> NormalizedAnalysis:
    """Dispatch one analysis record to its adapter by explicit kind.

    Kinds: ``scalar_evidence``, ``temporal_point``,
    ``cell_observation``.  Anything else is unsupported and
    reported, never forced into an adapter.
    """
    if kind == "scalar_evidence":
        domain = hints.get("domain", "")
        return from_scalar_evidence(
            payload, domain if isinstance(domain, str) else ""
        )
    if kind == "temporal_point":
        metric = hints.get("metric_key", "")
        domain = hints.get("domain", "")
        return from_temporal_point(
            payload,
            metric if isinstance(metric, str) else "",
            domain if isinstance(domain, str) else "",
        )
    if kind == "cell_observation":
        return from_cell_observation(payload)
    return NormalizedAnalysis(
        kind=kind if isinstance(kind, str) else "",
        supported=False,
        reason=f"unsupported analysis kind: {kind!r}",
    )


@dataclass(frozen=True)
class SemanticAssessment:
    """Whether two sides may be set beside each other at all.

    ``values_comparable`` is True only when the reference declares
    the exact analysis metric with the exact unit and both sides
    carry finite values.  ``states_agree`` is True only when both
    verbatim state strings exist and are identical.  Anything else
    is ``SEMANTICALLY_INCOMPATIBLE`` — descriptive, never a
    disagreement finding.
    """

    values_comparable: bool = False
    states_agree: Optional[bool] = None
    relationship: str = SEMANTICALLY_INCOMPATIBLE
    limitations: Tuple[str, ...] = ()


def assess_semantics(
    analysis: NormalizedAnalysis, observation: GroundTruthObservation
) -> SemanticAssessment:
    """Decide comparability without comparing magnitudes."""
    if observation.variable in _NON_COMPARABLE_VARIABLES:
        return SemanticAssessment(
            relationship=SEMANTICALLY_INCOMPATIBLE,
            limitations=(
                f"reference variable {observation.variable!r} "
                "carries no comparable semantics",
            ),
        )
    analysis_value = analysis.value
    reference_value = observation.value
    values_comparable = (
        observation.metric_key is not None
        and observation.metric_key == analysis.metric_key
        and isinstance(observation.unit, str)
        and bool(observation.unit)
        and observation.unit == analysis.unit
        and isinstance(analysis_value, (int, float))
        and isinstance(reference_value, (int, float))
    )
    states_agree: Optional[bool] = None
    if analysis.state is not None and observation.state is not None:
        states_agree = analysis.state == observation.state
    if values_comparable or states_agree is True:
        channels = []
        if values_comparable:
            channels.append("values share metric and unit")
        if states_agree is True:
            channels.append("states are identical strings")
        return SemanticAssessment(
            values_comparable=bool(values_comparable),
            states_agree=states_agree,
            relationship="SEMANTICALLY_COMPARABLE",
            limitations=tuple(channels),
        )
    return SemanticAssessment(
        values_comparable=False,
        states_agree=states_agree,
        relationship=SEMANTICALLY_INCOMPATIBLE,
        limitations=(
            "analysis and reference semantics are incompatible for "
            "value or state comparison; values are shown side by side only",
        ),
    )


def build_validation_id(target_id: str) -> str:
    """Deterministic validation identifier from the target identity."""
    return f"v:{target_id}"


@dataclass(frozen=True)
class ValidationResult:
    """One analysis output set beside one reference observation.

    Every source value is preserved; relationships name the
    established comparison; status stays within the P6.1
    descriptive states.  No numeric reading is attached.
    """

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
    status: str = STATUS_NOT_VALIDATED
    linkage_reason: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "target_id": self.target_id,
            "observation_id": self.observation_id,
            "metric_key": self.metric_key,
            "domain": self.domain,
            "analysis_id": self.analysis_id,
            "analysis_window_start": self.analysis_window_start,
            "analysis_window_end": self.analysis_window_end,
            "analysis_cell_id": self.analysis_cell_id,
            "analysis_value": self.analysis_value,
            "analysis_unit": self.analysis_unit,
            "analysis_state": self.analysis_state,
            "reference_variable": self.reference_variable,
            "reference_value": self.reference_value,
            "reference_unit": self.reference_unit,
            "reference_state": self.reference_state,
            "reference_source": self.reference_source,
            "reference_method": self.reference_method,
            "reference_time": self.reference_time,
            "temporal_relationship": self.temporal_relationship,
            "spatial_relationship": self.spatial_relationship,
            "metric_relationship": self.metric_relationship,
            "states_agree": self.states_agree,
            "values_comparable": self.values_comparable,
            "status": self.status,
            "linkage_reason": self.linkage_reason,
            "contract_version": GROUND_TRUTH_VERSION,
            "engine_version": VALIDATION_ENGINE_VERSION,
            "provenance": dict(self.provenance),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationResult":
        return cls(
            validation_id=str(payload.get("validation_id", "")),
            target_id=str(payload.get("target_id", "")),
            observation_id=str(payload.get("observation_id", "")),
            metric_key=str(payload.get("metric_key", "")),
            domain=str(payload.get("domain", "")),
            analysis_id=payload.get("analysis_id"),
            analysis_window_start=str(payload.get("analysis_window_start", "")),
            analysis_window_end=str(payload.get("analysis_window_end", "")),
            analysis_cell_id=payload.get("analysis_cell_id"),
            analysis_value=payload.get("analysis_value"),
            analysis_unit=str(payload.get("analysis_unit", "")),
            analysis_state=payload.get("analysis_state"),
            reference_variable=str(payload.get("reference_variable", "")),
            reference_value=payload.get("reference_value"),
            reference_unit=str(payload.get("reference_unit", "")),
            reference_state=payload.get("reference_state"),
            reference_source=str(payload.get("reference_source", "")),
            reference_method=str(payload.get("reference_method", "")),
            reference_time=payload.get("reference_time"),
            temporal_relationship=str(payload.get("temporal_relationship", "")),
            spatial_relationship=str(payload.get("spatial_relationship", "")),
            metric_relationship=str(payload.get("metric_relationship", "")),
            states_agree=payload.get("states_agree"),
            values_comparable=bool(payload.get("values_comparable", False)),
            status=str(payload.get("status", STATUS_NOT_VALIDATED)),
            linkage_reason=str(payload.get("linkage_reason", "")),
            provenance=dict(payload.get("provenance", {})),
            limitations=tuple(payload.get("limitations", ())),
        )


def make_result(
    analysis: NormalizedAnalysis,
    observation: GroundTruthObservation,
    target: ValidationTarget,
    analysis_id: Optional[str] = None,
) -> ValidationResult:
    """Assemble one result from its linkage and semantic assessment.

    Relationships are recomputed with the P6.1 matchers over the
    same inputs (reuse, not duplication).  When linkage matched
    but semantics are incompatible, the status becomes
    insufficient with an explicit limitation — an arbitrary
    numeric-to-label pairing must never read as a finding.
    """
    r_start, r_end = reference_window(observation)
    temporal_relationship = match_temporal(
        analysis.window_start, analysis.window_end, r_start, r_end
    )
    spatial_relationship = match_spatial(
        analysis.cell_id, observation.cell_id, observation.has_location()
    )
    metric_relationship = match_metric(analysis.metric_key, observation.metric_key)
    assessment = assess_semantics(analysis, observation)

    status = target.status
    relationship_note = target.relationship
    limitations: List[str] = list(target.limitations)
    if status == STATUS_MATCHED and assessment.relationship == SEMANTICALLY_INCOMPATIBLE:
        status = STATUS_INSUFFICIENT_REFERENCE
        relationship_note = SEMANTICALLY_INCOMPATIBLE
        limitations.extend((relationship_note,) + assessment.limitations)
    elif status == STATUS_MATCHED:
        limitations.extend(assessment.limitations)

    provenance: Dict[str, Any] = dict(target.provenance)
    provenance.update(
        {k: v for k, v in analysis.provenance.items() if k not in provenance}
    )

    return ValidationResult(
        validation_id=build_validation_id(target.target_id),
        target_id=target.target_id,
        observation_id=observation.observation_id,
        metric_key=analysis.metric_key,
        domain=analysis.domain,
        analysis_id=analysis_id,
        analysis_window_start=analysis.window_start,
        analysis_window_end=analysis.window_end,
        analysis_cell_id=analysis.cell_id,
        analysis_value=analysis.value,
        analysis_unit=analysis.unit,
        analysis_state=analysis.state,
        reference_variable=observation.variable,
        reference_value=observation.value,
        reference_unit=observation.unit,
        reference_state=observation.state,
        reference_source=observation.source,
        reference_method=observation.method,
        reference_time=observation.observed_on,
        temporal_relationship=temporal_relationship,
        spatial_relationship=spatial_relationship,
        metric_relationship=metric_relationship,
        states_agree=assessment.states_agree,
        values_comparable=assessment.values_comparable,
        status=status,
        linkage_reason=target.linkage_reason
        if relationship_note == target.relationship
        else (
            f"{target.linkage_reason}; semantic finding: "
            f"{relationship_note.lower()}"
        ),
        provenance=provenance,
        limitations=tuple(limitations),
    )


@dataclass(frozen=True)
class ValidationReport:
    """The deterministic outcome of one validation run."""

    results: Tuple[ValidationResult, ...] = ()
    limitations: Tuple[str, ...] = ()

    def results_for_metric(self, metric_key: str) -> Tuple[ValidationResult, ...]:
        return tuple(item for item in self.results if item.metric_key == metric_key)

    def results_with_status(self, status: str) -> Tuple[ValidationResult, ...]:
        return tuple(item for item in self.results if item.status == status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [item.to_dict() for item in self.results],
            "limitations": list(self.limitations),
            "contract_version": GROUND_TRUTH_VERSION,
            "engine_version": VALIDATION_ENGINE_VERSION,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationReport":
        return cls(
            results=tuple(
                ValidationResult.from_dict(item)
                for item in payload.get("results", [])
            ),
            limitations=tuple(payload.get("limitations", ())),
        )


def validate(
    analyses: Sequence[NormalizedAnalysis],
    collection: ReferenceCollection,
    analysis_id: Optional[str] = None,
) -> ValidationReport:
    """Validate supplied analysis outputs against a reference collection.

    Each supported analysis output is placed beside every
    candidate reference (exact metric claim or no metric claim),
    yielding separate relationships — never a single chosen
    reference.  Outputs with no candidates yield one
    not-validated result.  Unsupported outputs yield one result
    each with an explicit limitation.  Failures are isolated per
    item; the run never aborts.
    """
    results: List[ValidationResult] = []
    limitations: List[str] = list(collection.limitations)
    for position, analysis in enumerate(analyses):
        try:
            results.extend(_validate_one(analysis, collection, analysis_id, position))
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            fallback = declare_not_validated(
                target_id=f"unreadable-analysis:{position}",
                reason=f"analysis output could not be read: {type(exc).__name__}",
            )
            results.append(
                ValidationResult(
                    validation_id=build_validation_id(fallback.target_id),
                    target_id=fallback.target_id,
                    status=STATUS_INSUFFICIENT_ANALYSIS,
                    linkage_reason=fallback.linkage_reason,
                    limitations=(fallback.linkage_reason,),
                )
            )
    ordered = tuple(
        sorted(
            results,
            key=lambda item: (
                item.analysis_window_start,
                item.analysis_window_end,
                item.metric_key,
                item.analysis_cell_id or "",
                item.observation_id,
                item.validation_id,
            ),
        )
    )
    return ValidationReport(results=ordered, limitations=tuple(limitations))


def _validate_one(
    analysis: NormalizedAnalysis,
    collection: ReferenceCollection,
    analysis_id: Optional[str],
    position: int,
) -> List[ValidationResult]:
    """Pair one analysis output with its candidate references."""
    if not analysis.supported:
        fallback = declare_not_validated(
            target_id=f"unsupported-analysis:{position}:{analysis.kind or 'unknown'}",
            metric_key=analysis.metric_key,
            reason=f"unsupported analysis output: {analysis.reason}",
        )
        return [
            ValidationResult(
                validation_id=build_validation_id(fallback.target_id),
                target_id=fallback.target_id,
                metric_key=analysis.metric_key,
                domain=analysis.domain,
                status=STATUS_INSUFFICIENT_ANALYSIS,
                linkage_reason=fallback.linkage_reason,
                provenance=dict(analysis.provenance),
                limitations=(fallback.linkage_reason,),
            )
        ]
    candidates = collection.candidates_for(analysis.metric_key)
    if not candidates:
        fallback = declare_not_validated(
            target_id=build_target_id(
                analysis.metric_key or "unknown-metric",
                analysis.window_start,
                analysis.window_end,
                analysis.cell_id,
                "no-reference",
            ),
            metric_key=analysis.metric_key,
            reason="no reference observation claims this metric",
        )
        return [
            ValidationResult(
                validation_id=build_validation_id(fallback.target_id),
                target_id=fallback.target_id,
                metric_key=analysis.metric_key,
                domain=analysis.domain,
                analysis_window_start=analysis.window_start,
                analysis_window_end=analysis.window_end,
                analysis_cell_id=analysis.cell_id,
                analysis_value=analysis.value,
                analysis_unit=analysis.unit,
                analysis_state=analysis.state,
                temporal_relationship=NO_CANDIDATE_REFERENCE,
                status=STATUS_NOT_VALIDATED,
                linkage_reason=fallback.linkage_reason,
                provenance=dict(analysis.provenance),
                limitations=(fallback.linkage_reason,),
            )
        ]
    return [
        make_result(analysis, observation, link(analysis.to_mapping(), observation, analysis_id), analysis_id)
        for observation in candidates
    ]
