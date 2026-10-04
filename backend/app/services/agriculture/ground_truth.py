"""Ground-truth validation contract and foundation (P6.1).

A deterministic, additive foundation for comparing existing
agricultural analysis outputs with independently supplied reference
observations.  CONTRACT + FOUNDATION ONLY.

What this module is:

* a vocabulary for reference observations (identity, location, time,
  variable, value/state, source/method, provenance, quality);
* a vocabulary for validation targets that reference existing
  analysis outputs (scalar evidence, temporal windows, spatial
  cells) alongside one reference observation;
* explicit matching rules (temporal, spatial, metric) with stated
  relationships and descriptive validation states.

What this module is NOT:

* a source of observations — no observation is created here and no
  field data is fabricated;
* a remote-sensing interpreter — analysis states are never mapped
  to biological variables here.  Declines, changes, and anomalies
  in remote-sensing evidence never become reference labels through
  this module.  Pest, disease, stress, and damage entries exist
  here only as reference-side vocabulary, supplied by an external
  observer through explicit source/method metadata;
* a grader — no rates, no matrices, no curves, no numeric readings
  of any kind are produced here;
* a fetcher — no Earth Engine calls, no network, no database use.

A reference observation is treated as a supplied record, not as an
automatic truth: its source, method, quality, and limitations
travel with it verbatim, and linkage states stay descriptive.

Matching never interpolates, shifts, bridges, or fills.  Windows
compare by exact date identity; overlap without identity is
reported as compatible, never reshaped.  When linkage cannot be
established, the result is an insufficient state, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "GROUND_TRUTH_VERSION",
    "KNOWN_SOURCES",
    "REFERENCE_VARIABLES",
    "REFERENCE_STATES",
    "TEMPORAL_MATCHES",
    "SPATIAL_MATCHES",
    "METRIC_MATCHES",
    "VALIDATION_STATUSES",
    "TEMPORAL_EXACT",
    "TEMPORAL_COMPATIBLE",
    "TEMPORAL_INCOMPATIBLE",
    "SPATIAL_EXACT",
    "SPATIAL_MISMATCH",
    "SPATIAL_MISSING_LINKAGE",
    "METRIC_MATCH",
    "METRIC_MISMATCH",
    "STATUS_MATCHED",
    "STATUS_MISMATCHED",
    "STATUS_INSUFFICIENT_REFERENCE",
    "STATUS_INSUFFICIENT_ANALYSIS",
    "STATUS_UNAVAILABLE",
    "STATUS_NOT_VALIDATED",
    "GroundTruthObservation",
    "ValidationTarget",
    "source_is_recognized",
    "reference_window",
    "match_temporal",
    "match_spatial",
    "match_metric",
    "build_target_id",
    "declare_not_validated",
    "link",
    "link_all",
    "sort_targets",
]

#: Contract version carried on every serialized record.
GROUND_TRUTH_VERSION = "P61_V1"

#: Recognized source vocabulary.  External suppliers may use their
#: own source names; unrecognized names are carried verbatim and
#: reported as such, never rejected silently and never rewritten.
KNOWN_SOURCES: Tuple[str, ...] = (
    "field_observation",
    "laboratory_result",
    "agronomist_observation",
    "farmer_observation",
    "uav_derived_observation",
    "manually_verified_reference",
)

#: Variables a reference observation may record.  Biological entries
#: exist only for externally supplied reference records; nothing in
#: this module assigns them from remote-sensing evidence.
REFERENCE_VARIABLES: Tuple[str, ...] = (
    "observed_stress",
    "observed_damage",
    "observed_disease",
    "observed_pest_presence",
    "observed_pest_absence",
    "observed_management_event",
    "unknown",
    "not_assessed",
)

#: Categorical states a reference observation may carry alongside
#: or instead of a numeric value.
REFERENCE_STATES: Tuple[str, ...] = (
    "present",
    "absent",
    "unknown",
    "not_assessed",
)

#: Temporal match vocabulary.
TEMPORAL_EXACT = "EXACT_TEMPORAL_MATCH"
TEMPORAL_COMPATIBLE = "COMPATIBLE_TEMPORAL_WINDOW"
TEMPORAL_INCOMPATIBLE = "INCOMPATIBLE_TEMPORAL_WINDOW"
TEMPORAL_MATCHES: Tuple[str, ...] = (
    TEMPORAL_EXACT,
    TEMPORAL_COMPATIBLE,
    TEMPORAL_INCOMPATIBLE,
)

#: Spatial match vocabulary.
SPATIAL_EXACT = "EXACT_SPATIAL_CELL_MATCH"
SPATIAL_MISMATCH = "SPATIAL_MISMATCH"
SPATIAL_MISSING_LINKAGE = "MISSING_SPATIAL_LINKAGE"
SPATIAL_MATCHES: Tuple[str, ...] = (
    SPATIAL_EXACT,
    SPATIAL_MISMATCH,
    SPATIAL_MISSING_LINKAGE,
)

#: Metric match vocabulary.
METRIC_MATCH = "METRIC_MATCH"
METRIC_MISMATCH = "METRIC_MISMATCH"
METRIC_MATCHES: Tuple[str, ...] = (METRIC_MATCH, METRIC_MISMATCH)

#: Descriptive validation states.  They describe whether linkage
#: could be established and what it showed; they do not judge an
#: analysis output against a reference record.
STATUS_MATCHED = "MATCHED_REFERENCE"
STATUS_MISMATCHED = "MISMATCHED_REFERENCE"
STATUS_INSUFFICIENT_REFERENCE = "INSUFFICIENT_REFERENCE"
STATUS_INSUFFICIENT_ANALYSIS = "INSUFFICIENT_ANALYSIS"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_NOT_VALIDATED = "NOT_VALIDATED"
VALIDATION_STATUSES: Tuple[str, ...] = (
    STATUS_MATCHED,
    STATUS_MISMATCHED,
    STATUS_INSUFFICIENT_REFERENCE,
    STATUS_INSUFFICIENT_ANALYSIS,
    STATUS_UNAVAILABLE,
    STATUS_NOT_VALIDATED,
)


def source_is_recognized(source: str) -> bool:
    """Whether a source name belongs to the recognized vocabulary."""
    return source in KNOWN_SOURCES


def _parse_day(value: Any) -> Optional[date]:
    """Strict YYYY-MM-DD parsing; anything else yields None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class GroundTruthObservation:
    """One independently supplied reference observation.

    Identity, time, variable, and source/method are required.  At
    least one of ``value`` / ``state`` must be present.  Location
    and cell linkage are optional: their absence limits spatial
    matching but never invalidates the record itself.
    """

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
    provenance: Dict[str, Any] = field(default_factory=dict)
    limitations: Tuple[str, ...] = ()

    def refusal_reasons(self) -> Tuple[str, ...]:
        """Machine-readable reasons this record cannot be used."""
        reasons: List[str] = []
        if not isinstance(self.observation_id, str) or not self.observation_id:
            reasons.append("missing_observation_id")
        if self.variable not in REFERENCE_VARIABLES:
            reasons.append("unknown_variable")
        if self.state is not None and self.state not in REFERENCE_STATES:
            reasons.append("unknown_state")
        if self.value is None and self.state is None:
            reasons.append("missing_value_and_state")
        elif self.value is not None and not (
            isinstance(self.value, (int, float)) and isfinite(self.value)
        ):
            reasons.append("non_finite_value")
        if not isinstance(self.observed_on, str) or not self.observed_on:
            reasons.append("missing_observation_time")
        elif _parse_day(self.observed_on) is None:
            reasons.append("invalid_observation_time")
        if not isinstance(self.source, str) or not self.source:
            reasons.append("missing_source")
        if not isinstance(self.method, str) or not self.method:
            reasons.append("missing_method")
        return tuple(reasons)

    @property
    def is_usable(self) -> bool:
        """True when the record may take part in linkage."""
        if self.refusal_reasons():
            return False
        return self.status != "unavailable"

    def has_location(self) -> bool:
        """True only when both coordinates are finite numbers."""
        return (
            isinstance(self.latitude, (int, float))
            and isinstance(self.longitude, (int, float))
            and isfinite(self.latitude)
            and isfinite(self.longitude)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; missing values stay null, never zero."""
        return {
            "observation_id": self.observation_id,
            "variable": self.variable,
            "value": self.value,
            "unit": self.unit,
            "state": self.state,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "observed_on": self.observed_on,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "source": self.source,
            "method": self.method,
            "quality": self.quality,
            "status": self.status,
            "metric_key": self.metric_key,
            "domain": self.domain,
            "cell_id": self.cell_id,
            "contract_version": GROUND_TRUTH_VERSION,
            "provenance": dict(self.provenance),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GroundTruthObservation":
        """Rebuild a record from its plain-data form."""
        return cls(
            observation_id=str(payload.get("observation_id", "")),
            variable=str(payload.get("variable", "")),
            value=payload.get("value"),
            unit=str(payload.get("unit", "")),
            state=payload.get("state"),
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            observed_on=payload.get("observed_on"),
            window_start=payload.get("window_start"),
            window_end=payload.get("window_end"),
            source=str(payload.get("source", "")),
            method=str(payload.get("method", "")),
            quality=str(payload.get("quality", "unknown")),
            status=str(payload.get("status", "available")),
            metric_key=payload.get("metric_key"),
            domain=payload.get("domain"),
            cell_id=payload.get("cell_id"),
            provenance=dict(payload.get("provenance", {})),
            limitations=tuple(payload.get("limitations", ())),
        )


def reference_window(
    observation: GroundTruthObservation,
) -> Tuple[Optional[str], Optional[str]]:
    """The window a reference observation is compared on.

    Explicit rule, stated once: the declared ``window_start`` /
    ``window_end`` when both are present and valid, otherwise the
    single observation date as a one-day window.  Nothing is
    stretched, shifted, or filled to fit an analysis window.
    """
    start = _parse_day(observation.window_start)
    end = _parse_day(observation.window_end)
    if start is not None and end is not None and start <= end:
        return (start.isoformat(), end.isoformat())
    day = _parse_day(observation.observed_on)
    if day is None:
        return (None, None)
    return (day.isoformat(), day.isoformat())


def match_temporal(
    analysis_start: Any,
    analysis_end: Any,
    reference_start: Any,
    reference_end: Any,
) -> str:
    """Compare two windows by date identity only.

    EXACT when both bounds are identical, COMPATIBLE when the
    windows share at least one day, INCOMPATIBLE otherwise —
    including whenever any bound is missing or unparseable.
    """
    a_start = _parse_day(analysis_start)
    a_end = _parse_day(analysis_end)
    r_start = _parse_day(reference_start)
    r_end = _parse_day(reference_end)
    if a_start is None or a_end is None or r_start is None or r_end is None:
        return TEMPORAL_INCOMPATIBLE
    if a_start > a_end or r_start > r_end:
        return TEMPORAL_INCOMPATIBLE
    if a_start == r_start and a_end == r_end:
        return TEMPORAL_EXACT
    if max(a_start, r_start) <= min(a_end, r_end):
        return TEMPORAL_COMPATIBLE
    return TEMPORAL_INCOMPATIBLE


def match_spatial(
    analysis_cell: Any,
    reference_cell: Any,
    reference_has_location: bool,
) -> str:
    """Compare spatial linkage by cell identity only.

    EXACT when both sides name the same non-empty cell.  Missing
    linkage when the reference names no cell and carries no
    coordinates.  Anything else is a mismatch — coordinates alone
    never stand in for a cell, and cells are never remapped.
    """
    a_cell = analysis_cell if isinstance(analysis_cell, str) and analysis_cell else None
    r_cell = reference_cell if isinstance(reference_cell, str) and reference_cell else None
    if a_cell is not None and r_cell is not None:
        return SPATIAL_EXACT if a_cell == r_cell else SPATIAL_MISMATCH
    if r_cell is None and not reference_has_location:
        return SPATIAL_MISSING_LINKAGE
    return SPATIAL_MISMATCH


def match_metric(analysis_metric: Any, reference_metric: Any) -> str:
    """Compare metric identity by exact key equality.

    A reference that declares no metric linkage (None) does not
    mismatch; it simply makes no metric claim.  Distinct keys
    mismatch.  Substring or family similarity never counts.
    """
    if reference_metric is None:
        return METRIC_MATCH
    if (
        isinstance(analysis_metric, str)
        and isinstance(reference_metric, str)
        and analysis_metric
        and analysis_metric == reference_metric
    ):
        return METRIC_MATCH
    return METRIC_MISMATCH


def build_target_id(metric_key: str, window_start: str, window_end: str,
                    cell_id: Optional[str], observation_id: str) -> str:
    """Deterministic target identifier from linkage identity."""
    cell = cell_id if isinstance(cell_id, str) and cell_id else "no-cell"
    return f"{metric_key}:{window_start}:{window_end}:{cell}:{observation_id}"


@dataclass(frozen=True)
class ValidationTarget:
    """One analysis output placed beside one reference observation.

    ``relationship`` names the established comparison relationship
    (temporal, spatial, or metric vocabulary).  ``status`` is one
    of the descriptive validation states.  ``linkage_reason`` states
    in plain words what was compared and what was found, without
    causal verbs.  Only :func:`link` and :func:`declare_not_validated`
    construct meaningful instances.
    """

    target_id: str = ""
    analysis_id: Optional[str] = None
    metric_key: str = ""
    domain: str = ""
    window_start: str = ""
    window_end: str = ""
    cell_id: Optional[str] = None
    observation_id: str = ""
    relationship: str = ""
    status: str = STATUS_NOT_VALIDATED
    linkage_reason: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form for audit trails and contract models."""
        return {
            "target_id": self.target_id,
            "analysis_id": self.analysis_id,
            "metric_key": self.metric_key,
            "domain": self.domain,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "cell_id": self.cell_id,
            "observation_id": self.observation_id,
            "relationship": self.relationship,
            "status": self.status,
            "linkage_reason": self.linkage_reason,
            "contract_version": GROUND_TRUTH_VERSION,
            "provenance": {key: value for key, value in self.provenance.items()},
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationTarget":
        """Rebuild a target from its plain-data form."""
        return cls(
            target_id=str(payload.get("target_id", "")),
            analysis_id=payload.get("analysis_id"),
            metric_key=str(payload.get("metric_key", "")),
            domain=str(payload.get("domain", "")),
            window_start=str(payload.get("window_start", "")),
            window_end=str(payload.get("window_end", "")),
            cell_id=payload.get("cell_id"),
            observation_id=str(payload.get("observation_id", "")),
            relationship=str(payload.get("relationship", "")),
            status=str(payload.get("status", STATUS_NOT_VALIDATED)),
            linkage_reason=str(payload.get("linkage_reason", "")),
            provenance=dict(payload.get("provenance", {})),
            limitations=tuple(payload.get("limitations", ())),
        )


def declare_not_validated(
    target_id: str,
    metric_key: str = "",
    observation_id: str = "",
    reason: str = "linkage has not been evaluated",
) -> ValidationTarget:
    """Book a target awaiting evaluation.  The default state."""
    return ValidationTarget(
        target_id=target_id,
        metric_key=metric_key,
        observation_id=observation_id,
        relationship="NOT_EVALUATED",
        status=STATUS_NOT_VALIDATED,
        linkage_reason=reason,
        limitations=("linkage has not been evaluated",),
    )


def _target_provenance(
    analysis: Mapping[str, Any],
    observation: GroundTruthObservation,
    linkage_reason: str,
) -> Dict[str, Any]:
    """Carry source, method, time, variable, and quality verbatim."""
    kept: Dict[str, Any] = {
        "reference_source": observation.source,
        "reference_method": observation.method,
        "reference_time": observation.observed_on,
        "reference_variable": observation.variable,
        "reference_quality": observation.quality,
        "reference_status": observation.status,
        "linkage_reason": linkage_reason,
    }
    if observation.state is not None:
        kept["reference_state"] = observation.state
    if observation.value is not None:
        kept["reference_value"] = observation.value
        kept["reference_unit"] = observation.unit
    if observation.cell_id:
        kept["reference_cell_id"] = observation.cell_id
    if not source_is_recognized(observation.source):
        kept["source_vocabulary"] = "unrecognized; carried verbatim"
    for key in ("metric_key", "domain", "window_start", "window_end", "cell_id"):
        if analysis.get(key) is not None:
            kept[f"analysis_{key}"] = analysis.get(key)
    kept.update({k: v for k, v in observation.provenance.items() if k not in kept})
    return kept


def link(
    analysis: Mapping[str, Any],
    observation: GroundTruthObservation,
    analysis_id: Optional[str] = None,
) -> ValidationTarget:
    """Place one analysis output beside one reference observation.

    Priority is deterministic: reference usability first, then
    analysis availability, then metric, temporal, and spatial
    identity in that order.  The first established finding decides
    the status; every finding considered is recorded in the
    limitations so nothing is hidden.
    """
    metric = analysis.get("metric_key", "")
    domain = analysis.get("domain", "")
    a_start = analysis.get("window_start", "")
    a_end = analysis.get("window_end", "")
    a_cell = analysis.get("cell_id")
    if not isinstance(metric, str):
        metric = ""
    if not isinstance(domain, str):
        domain = ""
    target_id = build_target_id(
        metric or "unknown-metric",
        a_start if isinstance(a_start, str) else "",
        a_end if isinstance(a_end, str) else "",
        a_cell if isinstance(a_cell, str) else None,
        observation.observation_id or "unknown-observation",
    )
    base_limitations: List[str] = list(observation.limitations)

    reasons = observation.refusal_reasons()
    if reasons:
        linkage_reason = (
            "reference observation cannot be used: " + ", ".join(reasons)
        )
        return ValidationTarget(
            target_id=target_id,
            analysis_id=analysis_id,
            metric_key=metric,
            domain=domain,
            window_start=a_start if isinstance(a_start, str) else "",
            window_end=a_end if isinstance(a_end, str) else "",
            cell_id=a_cell if isinstance(a_cell, str) else None,
            observation_id=observation.observation_id,
            relationship="REFERENCE_UNUSABLE",
            status=STATUS_INSUFFICIENT_REFERENCE,
            linkage_reason=linkage_reason,
            provenance=_target_provenance(analysis, observation, linkage_reason),
            limitations=tuple(base_limitations + [f"reference refused: {r}" for r in reasons]),
        )
    if observation.status == "unavailable":
        linkage_reason = "reference observation is marked unavailable"
        return ValidationTarget(
            target_id=target_id,
            analysis_id=analysis_id,
            metric_key=metric,
            domain=domain,
            window_start=a_start if isinstance(a_start, str) else "",
            window_end=a_end if isinstance(a_end, str) else "",
            cell_id=a_cell if isinstance(a_cell, str) else None,
            observation_id=observation.observation_id,
            relationship="REFERENCE_UNAVAILABLE",
            status=STATUS_INSUFFICIENT_REFERENCE,
            linkage_reason=linkage_reason,
            provenance=_target_provenance(analysis, observation, linkage_reason),
            limitations=tuple(base_limitations + ["reference unavailable"]),
        )

    if not metric or not isinstance(a_start, str) or not a_start \
            or not isinstance(a_end, str) or not a_end:
        linkage_reason = "analysis output identity is incomplete"
        return ValidationTarget(
            target_id=target_id,
            analysis_id=analysis_id,
            metric_key=metric,
            domain=domain,
            window_start=a_start if isinstance(a_start, str) else "",
            window_end=a_end if isinstance(a_end, str) else "",
            cell_id=a_cell if isinstance(a_cell, str) else None,
            observation_id=observation.observation_id,
            relationship="ANALYSIS_IDENTITY_INCOMPLETE",
            status=STATUS_INSUFFICIENT_ANALYSIS,
            linkage_reason=linkage_reason,
            provenance=_target_provenance(analysis, observation, linkage_reason),
            limitations=tuple(base_limitations + ["analysis identity incomplete"]),
        )
    if analysis.get("status") == "unavailable":
        linkage_reason = "analysis output is marked unavailable"
        return ValidationTarget(
            target_id=target_id,
            analysis_id=analysis_id,
            metric_key=metric,
            domain=domain,
            window_start=a_start,
            window_end=a_end,
            cell_id=a_cell if isinstance(a_cell, str) else None,
            observation_id=observation.observation_id,
            relationship="ANALYSIS_UNAVAILABLE",
            status=STATUS_UNAVAILABLE,
            linkage_reason=linkage_reason,
            provenance=_target_provenance(analysis, observation, linkage_reason),
            limitations=tuple(base_limitations + ["analysis unavailable"]),
        )
    if analysis.get("value") is None:
        linkage_reason = "analysis output carries no value"
        return ValidationTarget(
            target_id=target_id,
            analysis_id=analysis_id,
            metric_key=metric,
            domain=domain,
            window_start=a_start,
            window_end=a_end,
            cell_id=a_cell if isinstance(a_cell, str) else None,
            observation_id=observation.observation_id,
            relationship="ANALYSIS_VALUE_MISSING",
            status=STATUS_INSUFFICIENT_ANALYSIS,
            linkage_reason=linkage_reason,
            provenance=_target_provenance(analysis, observation, linkage_reason),
            limitations=tuple(base_limitations + ["analysis value missing"]),
        )

    r_start, r_end = reference_window(observation)
    metric_match = match_metric(metric, observation.metric_key)
    temporal_match = match_temporal(a_start, a_end, r_start, r_end)
    spatial_match = match_spatial(a_cell, observation.cell_id, observation.has_location())

    findings = (
        f"metric {metric_match.lower()}; "
        f"temporal {temporal_match.lower()}; "
        f"spatial {spatial_match.lower()}"
    )
    if metric_match == METRIC_MISMATCH:
        linkage_reason = (
            f"metric mismatch: analysis {metric!r} is not "
            f"the reference linked metric {observation.metric_key!r}; {findings}"
        )
        relationship, status = METRIC_MISMATCH, STATUS_MISMATCHED
    elif temporal_match == TEMPORAL_INCOMPATIBLE:
        linkage_reason = (
            f"temporal windows do not overlap: analysis "
            f"{a_start} to {a_end} beside reference "
            f"{r_start} to {r_end}; {findings}"
        )
        relationship, status = TEMPORAL_INCOMPATIBLE, STATUS_MISMATCHED
    elif spatial_match == SPATIAL_MISMATCH and not (
        not isinstance(a_cell, str) or not a_cell
    ):
        linkage_reason = (
            "spatial cells differ with no remapping applied; "
            f"{findings}"
        )
        relationship, status = SPATIAL_MISMATCH, STATUS_MISMATCHED
    elif spatial_match == SPATIAL_MISSING_LINKAGE:
        linkage_reason = (
            "reference carries no cell and no coordinates, "
            f"so spatial linkage cannot be established; {findings}"
        )
        relationship, status = SPATIAL_MISSING_LINKAGE, STATUS_INSUFFICIENT_REFERENCE
    elif spatial_match == SPATIAL_MISMATCH:
        linkage_reason = (
            "analysis carries no cell while the reference has "
            f"spatial information; {findings}"
        )
        relationship, status = SPATIAL_MISSING_LINKAGE, STATUS_INSUFFICIENT_ANALYSIS
    else:
        linkage_reason = (
            f"analysis and reference share metric, overlapping "
            f"window, and cell; {findings}"
        )
        relationship, status = temporal_match, STATUS_MATCHED

    return ValidationTarget(
        target_id=target_id,
        analysis_id=analysis_id,
        metric_key=metric,
        domain=domain,
        window_start=a_start,
        window_end=a_end,
        cell_id=a_cell if isinstance(a_cell, str) else None,
        observation_id=observation.observation_id,
        relationship=relationship,
        status=status,
        linkage_reason=linkage_reason,
        provenance=_target_provenance(analysis, observation, linkage_reason),
        limitations=tuple(base_limitations + [findings]),
    )


def link_all(
    pairs: Sequence[Tuple[Mapping[str, Any], GroundTruthObservation]],
    analysis_id: Optional[str] = None,
) -> Tuple[ValidationTarget, ...]:
    """Link many pairs deterministically, ordered by target id."""
    return sort_targets(
        tuple(link(analysis, observation, analysis_id) for analysis, observation in pairs)
    )


def sort_targets(targets: Sequence[ValidationTarget]) -> Tuple[ValidationTarget, ...]:
    """Deterministic order over validation targets."""
    return tuple(
        sorted(
            targets,
            key=lambda item: (
                item.window_start,
                item.window_end,
                item.metric_key,
                item.cell_id or "",
                item.observation_id,
                item.target_id,
            ),
        )
    )
