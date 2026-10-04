"""Cross-pattern validation (P3.3).

A deterministic validation layer over the already-established P3.1
generic Evidence Pattern Engine outputs and P3.2 named non-specific
evidence patterns.  It compares pattern outputs for the same exact
window and reports whether they read as compatible observed
changes, mixed evidence, or insufficient evidence.  It validates;
it never reinterprets.

This layer reads only established pattern outputs — pattern types,
exact windows, categorical source states, qualities, metric and
sensor identities, and provenance.  Raw satellite values are never
re-read to derive a new conclusion, no new thresholds or baselines
are introduced, and no numeric strength, score, confidence,
probability, or risk value is produced anywhere.

The validation status remains descriptive:

* ``CONSISTENT`` — same exact-window patterns describe compatible
  observed changes (including established sensor concordance).
* ``MIXED_EVIDENCE`` — same exact-window patterns describe
  opposing observed directions or carry explicitly divergent source
  evidence; the divergence is preserved, never resolved, and no
  pattern is preferred.
* ``INSUFFICIENT_EVIDENCE`` — no usable pattern exists for the
  exact evaluated window; no negative finding is made.

Temporal contract (reused from P1.4/P2.5 exact-window identity):

* exact calendar-window identity only — no interpolation, no
  nearest-month matching, no shifting, no merging, no zero-fill;
* gaps break temporal relationships; patterns from different
  windows are never combined merely because they are adjacent;
* multi-month spans are preserved verbatim as their exact source
  span and are never split into months.

Overlap handling: ``MULTI_MODAL_CANOPY_CHANGE`` already represents
P2.5 sensor concordance, so shared S1/S2 evidence cited by several
patterns is counted once as independent sensor evidence.  Overlap
is reported for audit with stable evidence, pattern, and metric
identifiers; it is never converted into a numeric strength score.
Five named patterns are never assumed to be five independent
pieces of evidence.

Reused contracts (nothing re-derived, no second engine):

* P3.1 ``EvidencePattern`` output, ``PatternRule`` registry shape,
  status vocabulary, sensor-family semantics, and engine version;
  validation outputs reference these objects without altering them.
* P3.2 named pattern types, deterministic ``FULL_PATTERN_ORDER``
  ordering, and neutral per-pattern limitations.
* P1.3 categorical direction and rapid labels (INCREASE, DECREASE,
  STABLE, RAPID_INCREASE, RAPID_DECREASE) and persistence states,
  read from pattern source states, never recomputed.
* P1.2 anomaly categories (BELOW_BASELINE, ABOVE_BASELINE,
  NORMAL), read from pattern source states, never recomputed.
* P1.4 joint divergence descriptor MOISTURE_DOWN_NDVI_STABLE,
  preserved descriptively with no lag preferred and no causal
  order claimed.
* P2.2 red-edge DECREASE directions, consumed as Sentinel-2
  derived evidence that never forms an independent sensor.
* P2.4 radar persistence records, consumed through the named
  radar-deviation pattern's own span and states.
* P2.5 concordance states (MULTI_SENSOR_CONCORDANT, DIVERGENT,
  MIXED_EVIDENCE, INSUFFICIENT_EVIDENCE), the family registry, and
  the S1/S2 independence mapping; concordance is restated, never
  recomputed.  Red-edge evidence remains Sentinel-2 derived.

Scientific limitations (published on every output): compatible or
mixed observed evidence does not identify a biological cause;
moisture/greenness divergence is descriptive and never a finding
about pests, diseases, or deficiencies of any kind; sensor
concordance evidences compatible observed change, not a common
biological cause.  Biological attribution requires additional
evidence and ground-truth validation.

Non-goals of this phase: new Earth Engine logic, statistics,
thresholds, baselines, correlations, scores, confidence values,
probabilities, risk values, models, biological interpretation,
causal inference, lag selection, thermal data, endpoints,
frontend, visualization, database changes, and cache changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.change_profile import (
    DIRECTION_DECREASE,
    DIRECTION_INCREASE,
    DIRECTION_STABLE,
    RAPID_DECREASE,
    RAPID_INCREASE,
)
from app.services.agriculture.concordance import (
    CONCORDANCE_RULE_ID,
    FAMILY_METRICS,
    STATE_CONCORDANT,
    STATE_DIVERGENT,
    STATE_MIXED,
)
from app.services.agriculture.joint_profile import (
    DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE,
)
from app.services.agriculture.named_patterns import (
    FULL_PATTERN_ORDER,
    NAMED_MOISTURE_DIVERGENCE,
    NAMED_MULTI_MODAL,
    NAMED_RAPID_DECLINE,
    NAMED_RED_EDGE_DECLINE,
)
from app.services.agriculture.pattern_engine import (
    PATTERN_CONCORDANCE,
    PATTERN_DIVERGENCE,
    PATTERN_INSUFFICIENT,
    STATUS_INSUFFICIENT,
    STATUS_OBSERVED,
    EvidencePattern,
    PatternRule,
)

logger = get_logger(__name__)

__all__ = [
    "VALIDATION_VERSION",
    "STATUS_CONSISTENT",
    "STATUS_MIXED",
    "STATUS_INSUFFICIENT",
    "VALIDATION_STATUSES",
    "RULE_COMPATIBLE",
    "RULE_DIVERGENCE",
    "RULE_SENSOR_AGREEMENT",
    "RULE_MOISTURE_DESCRIPTIVE",
    "RULE_MISSING",
    "VALIDATION_RULES",
    "CrossPatternValidation",
    "get_validation_rule",
    "validate_window",
    "validate_all",
    "sort_validations",
]

#: Validation layer version published on every result.
VALIDATION_VERSION = "P33_V1"

#: Descriptive validation status vocabulary.  No numeric reading
#: accompanies any status.
STATUS_CONSISTENT = "CONSISTENT"
STATUS_MIXED = "MIXED_EVIDENCE"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
VALIDATION_STATUSES: Tuple[str, ...] = (
    STATUS_CONSISTENT,
    STATUS_MIXED,
    STATUS_INSUFFICIENT,
)

#: Registry rule identifiers.
RULE_COMPATIBLE = "P33_COMPATIBLE_SAME_DIRECTION_V1"
RULE_DIVERGENCE = "P33_EXPLICIT_DIVERGENCE_V1"
RULE_SENSOR_AGREEMENT = "P33_INDEPENDENT_SENSOR_AGREEMENT_V1"
RULE_MOISTURE_DESCRIPTIVE = "P33_MOISTURE_GREENNESS_DESCRIPTIVE_V1"
RULE_MISSING = "P33_MISSING_INSUFFICIENT_V1"

#: Source states that refuse promotion to usable validation input.
#: Mirrors the P3.1 refusing qualities; restated here so that
#: validation never re-reads raw quality semantics.
_REFUSING_QUALITIES = frozenset({"unavailable", "insufficient", ""})

#: Categorical source states grouped by observed orientation.  The
#: labels are the P1.2/P1.3/P2.5 vocabularies restated for
#: predicate readability, reusing the imported contract constants
#: wherever they exist; raw numeric signs are never consulted.
_DOWN_SOURCE_STATES = frozenset(
    {DIRECTION_DECREASE, RAPID_DECREASE, "BELOW_BASELINE", "DOWN"}
)
_UP_SOURCE_STATES = frozenset(
    {DIRECTION_INCREASE, RAPID_INCREASE, "ABOVE_BASELINE", "UP"}
)
_NEUTRAL_SOURCE_STATES = frozenset({DIRECTION_STABLE, "NORMAL", "NEUTRAL"})
_DIVERGENT_SOURCE_STATES = frozenset(
    {
        STATE_DIVERGENT,
        STATE_MIXED,
        DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE,
        PATTERN_DIVERGENCE,
        NAMED_MOISTURE_DIVERGENCE,
    }
)

#: Internal orientation readings over one pattern's categorical
#: source states.  ``CONCORDANT`` marks an established agreement
#: restatement; ``DIVERGENT`` marks explicitly divergent source
#: evidence; an empty reading marks no directional claim.
_ORIENT_DOWN = "DOWN"
_ORIENT_UP = "UP"
_ORIENT_NEUTRAL = "NEUTRAL"
_ORIENT_DIVERGENT = "DIVERGENT"
_ORIENT_CONCORDANT = "CONCORDANT"

#: Pattern types whose orientation is fixed by definition rather
#: than by per-evidence source states.
_DOWN_BY_DEFINITION = frozenset({NAMED_RAPID_DECLINE, NAMED_RED_EDGE_DECLINE})
_CONCORDANT_BY_DEFINITION = frozenset({NAMED_MULTI_MODAL, PATTERN_CONCORDANCE})
_DIVERGENT_BY_DEFINITION = frozenset(
    {PATTERN_DIVERGENCE, NAMED_MOISTURE_DIVERGENCE}
)

#: Sensor fallback for metric identifiers absent from every
#: registered family.  Sentinel-1 carries radar evidence and
#: Sentinel-2 carries optical evidence per the P2.5 sensor
#: mapping; red-edge identifiers resolve through the family
#: registry above, never through this fallback.
_SENSOR_FALLBACK_FAMILY = {"S1": "radar", "S2": "optical"}

_NOT_A_FINDING_SUFFIX = (
    " This describes observed evidence patterns and does not "
    "identify its cause."
)

_SHARED_LIMITATIONS: Tuple[str, ...] = (
    "Windows align on exact (window_start, window_end) identity; "
    "no interpolation, shifting, merging, or zero-fill is "
    "performed and gaps break temporal relationships.",
    "Overlapping evidence is reported for audit; shared S1/S2 "
    "evidence is counted once and overlap is never a strength "
    "indicator.",
    "Validation reads established pattern states only; raw "
    "satellite values are never re-read to derive a new "
    "conclusion.",
    "Observed compatibility or divergence does not identify a "
    "biological cause; biological attribution requires "
    "additional evidence and ground-truth validation.",
)


# --------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossPatternValidation:
    """One cross-pattern validation statement for one exact window.

    ``status`` is CONSISTENT for compatible observed changes,
    MIXED_EVIDENCE for opposing or explicitly divergent source
    evidence (preserved, never resolved), and
    INSUFFICIENT_EVIDENCE when no usable pattern exists for the
    window (never a negative finding).  ``pattern_count`` and
    ``independent_sensor_count`` are descriptive audit counts, not
    strength readings, and no numeric grade exists anywhere on
    this object.
    """

    validation_id: str
    window_start: str
    window_end: str
    status: str
    contributing_pattern_ids: Tuple[str, ...]
    compatible_pattern_ids: Tuple[str, ...]
    conflicting_pattern_ids: Tuple[str, ...]
    contributing_metric_ids: Tuple[str, ...]
    contributing_sensors: Tuple[str, ...]
    contributing_families: Tuple[str, ...]
    pattern_count: int
    independent_sensor_count: int
    overlapping_evidence: bool
    overlapping_metric_ids: Tuple[str, ...]
    overlapping_evidence_ids: Tuple[str, ...]
    source_pattern_types: Dict[str, str]
    source_pattern_states: Dict[str, str]
    rule_id: str
    rule_version: str
    rule_description: str
    explanation: str
    overlap_explanation: str
    provenance: Dict[str, Any]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form for audit trails and contract models."""
        return {
            "validation_id": self.validation_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "status": self.status,
            "contributing_pattern_ids": list(self.contributing_pattern_ids),
            "compatible_pattern_ids": list(self.compatible_pattern_ids),
            "conflicting_pattern_ids": list(self.conflicting_pattern_ids),
            "contributing_metric_ids": list(self.contributing_metric_ids),
            "contributing_sensors": list(self.contributing_sensors),
            "contributing_families": list(self.contributing_families),
            "pattern_count": self.pattern_count,
            "independent_sensor_count": self.independent_sensor_count,
            "overlapping_evidence": self.overlapping_evidence,
            "overlapping_metric_ids": list(self.overlapping_metric_ids),
            "overlapping_evidence_ids": list(self.overlapping_evidence_ids),
            "source_pattern_types": dict(self.source_pattern_types),
            "source_pattern_states": dict(self.source_pattern_states),
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "rule_description": self.rule_description,
            "explanation": self.explanation,
            "overlap_explanation": self.overlap_explanation,
            "provenance": {
                key: (
                    {
                        inner_key: (
                            list(inner_value)
                            if isinstance(inner_value, tuple)
                            else inner_value
                        )
                        for inner_key, inner_value in value.items()
                    }
                    if isinstance(value, dict)
                    else (list(value) if isinstance(value, tuple) else value)
                )
                for key, value in self.provenance.items()
            },
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossPatternValidation":
        """Rebuild a validation statement from its plain-data form."""
        return cls(
            validation_id=str(payload["validation_id"]),
            window_start=str(payload["window_start"]),
            window_end=str(payload["window_end"]),
            status=str(payload["status"]),
            contributing_pattern_ids=tuple(payload["contributing_pattern_ids"]),
            compatible_pattern_ids=tuple(payload["compatible_pattern_ids"]),
            conflicting_pattern_ids=tuple(payload["conflicting_pattern_ids"]),
            contributing_metric_ids=tuple(payload["contributing_metric_ids"]),
            contributing_sensors=tuple(payload["contributing_sensors"]),
            contributing_families=tuple(payload["contributing_families"]),
            pattern_count=int(payload["pattern_count"]),
            independent_sensor_count=int(payload["independent_sensor_count"]),
            overlapping_evidence=bool(payload["overlapping_evidence"]),
            overlapping_metric_ids=tuple(payload["overlapping_metric_ids"]),
            overlapping_evidence_ids=tuple(payload["overlapping_evidence_ids"]),
            source_pattern_types=dict(payload["source_pattern_types"]),
            source_pattern_states=dict(payload["source_pattern_states"]),
            rule_id=str(payload["rule_id"]),
            rule_version=str(payload["rule_version"]),
            rule_description=str(payload["rule_description"]),
            explanation=str(payload["explanation"]),
            overlap_explanation=str(payload["overlap_explanation"]),
            provenance=dict(payload["provenance"]),
            limitations=tuple(payload["limitations"]),
        )


# --------------------------------------------------------------------------
# Rule registry (deterministic order, Rule 1 through Rule 5)
# --------------------------------------------------------------------------


VALIDATION_RULES: Tuple[PatternRule, ...] = (
    PatternRule(
        rule_id=RULE_COMPATIBLE,
        rule_version=VALIDATION_VERSION,
        name="Compatible same-direction patterns",
        pattern_type=STATUS_CONSISTENT,
        requires=("same exact window", "compatible observed directions",),
        predicate=(
            "Usable same exact-window patterns describe compatible "
            "observed directions with usable source quality; they "
            "are reported as coexisting compatible evidence without "
            "claiming a shared process."
        ),
        limitations=(
            "Compatibility is coexistence of observed changes, not "
            "a shared process.",
            "No direction is read beyond the source states.",
        ),
    ),
    PatternRule(
        rule_id=RULE_DIVERGENCE,
        rule_version=VALIDATION_VERSION,
        name="Explicit divergence preserved",
        pattern_type=STATUS_MIXED,
        requires=("same exact window", "divergent or opposing source states",),
        predicate=(
            "Usable same exact-window patterns carry an explicit "
            "P1.4/P2.5 divergence state or opposing observed "
            "directions for the same period; the window is reported "
            "as mixed evidence with every involved pattern named "
            "and none preferred."
        ),
        limitations=(
            "Mixed evidence is preserved, never resolved.",
            "No pattern is preferred and no winner is selected.",
        ),
    ),
    PatternRule(
        rule_id=RULE_SENSOR_AGREEMENT,
        rule_version=VALIDATION_VERSION,
        name="Independent sensor agreement",
        pattern_type=STATUS_CONSISTENT,
        requires=("concordance_month=MULTI_SENSOR_CONCORDANT", "same exact window",),
        predicate=(
            "Same exact-window evidence includes an established "
            f"P2.5 {STATE_CONCORDANT} restatement with no opposing "
            "or divergent usable pattern; it is reported as sensor "
            "concordance under "
            f"{CONCORDANCE_RULE_ID}."
        ),
        limitations=(
            "Sensor concordance evidences compatible observed "
            "change, not a common biological cause.",
            "S1 and S2 each count once however many metrics cite "
            "them.",
        ),
    ),
    PatternRule(
        rule_id=RULE_MOISTURE_DESCRIPTIVE,
        rule_version=VALIDATION_VERSION,
        name="Moisture greenness divergence stays descriptive",
        pattern_type=STATUS_MIXED,
        requires=(
            "joint_change.divergence=MOISTURE_DOWN_NDVI_STABLE",
            "same exact window",
        ),
        predicate=(
            "Same exact-window evidence includes an established "
            "MOISTURE_GREENNESS_DIVERGENCE pattern; the "
            "moisture/greenness divergence is preserved as a "
            "descriptive divergence and the window is reported as "
            "mixed evidence without causal order."
        ),
        limitations=(
            "A moisture/greenness divergence is descriptive and "
            "does not establish causal order or a biological cause.",
        ),
    ),
    PatternRule(
        rule_id=RULE_MISSING,
        rule_version=VALIDATION_VERSION,
        name="Missing or insufficient sources",
        pattern_type=STATUS_INSUFFICIENT,
        requires=("same exact window",),
        predicate=(
            "No usable pattern exists for the exact evaluated "
            "window — no pattern, or only insufficient or "
            "unavailable sources; the window is reported as "
            "insufficient evidence."
        ),
        limitations=(
            "No evidence is not evidence of no change.",
            "No negative finding is made.",
        ),
    ),
)


def get_validation_rule(rule_id: str) -> PatternRule:
    """Look up a validation rule, with an actionable error if absent."""
    for rule in VALIDATION_RULES:
        if rule.rule_id == rule_id:
            return rule
    available = ", ".join(rule.rule_id for rule in VALIDATION_RULES)
    raise KeyError(
        f"Cross-pattern validation rule {rule_id!r} is not registered. "
        f"Available rules: {available}"
    )


# --------------------------------------------------------------------------
# Pure helpers (established states only; raw values never consulted)
# --------------------------------------------------------------------------


def _quality_usable(quality: Any) -> bool:
    if not isinstance(quality, str):
        return False
    return quality.strip().lower() not in _REFUSING_QUALITIES


def _pattern_usable(pattern: EvidencePattern) -> bool:
    """Whether an established pattern may contribute to validation.

    Only OBSERVED patterns with at least one contributing evidence
    item and at least one usable quality contribute.  Anything
    else — insufficient states, empty contributions, or wholly
    unavailable quality — is preserved as unusable input, never
    promoted and never converted into a negative finding.
    """
    if pattern.status != STATUS_OBSERVED:
        return False
    if not pattern.contributing_evidence_ids:
        return False
    qualities = pattern.quality_by_evidence or {}
    if not qualities:
        return True
    return any(_quality_usable(quality) for quality in qualities.values())


def _orientations_of(pattern: EvidencePattern) -> frozenset:
    """Coarse orientation reading of one pattern from categories only.

    Reads ``pattern_type`` and the categorical ``source_states``
    strings (P1.2 categories, P1.3 directions and rapid labels,
    P1.4/P2.5 divergence states).  Numeric magnitudes, rates, and
    raw values are never consulted.
    """
    if pattern.pattern_type in _DOWN_BY_DEFINITION:
        return frozenset({_ORIENT_DOWN})
    if pattern.pattern_type in _CONCORDANT_BY_DEFINITION:
        return frozenset({_ORIENT_CONCORDANT})
    if pattern.pattern_type in _DIVERGENT_BY_DEFINITION:
        return frozenset({_ORIENT_DIVERGENT})
    if pattern.pattern_type == PATTERN_INSUFFICIENT:
        return frozenset({STATUS_INSUFFICIENT})
    readings = set()
    for state in pattern.source_states.values():
        name = str(state).strip().upper()
        if not name:
            continue
        if name in _DOWN_SOURCE_STATES:
            readings.add(_ORIENT_DOWN)
        elif name in _UP_SOURCE_STATES:
            readings.add(_ORIENT_UP)
        elif name in _NEUTRAL_SOURCE_STATES:
            readings.add(_ORIENT_NEUTRAL)
        elif name in _DIVERGENT_SOURCE_STATES:
            readings.add(_ORIENT_DIVERGENT)
    return frozenset(readings)


def _families_of(pattern: EvidencePattern) -> Tuple[str, ...]:
    """Descriptive families behind one pattern's metric identities.

    Resolves each contributing metric through the P2.5 family
    registry; identifiers absent from every family fall back to
    the pattern's sensor identity (S1 radar, S2 optical).  This
    is a descriptive identity read, not a recomputation.
    """
    families = set()
    sensors = tuple(pattern.contributing_sensors or ())
    for metric_id in pattern.contributing_metric_ids or ():
        resolved: Optional[str] = None
        for family_name, registered in FAMILY_METRICS.items():
            if metric_id in registered:
                resolved = family_name
                break
        if resolved is None and sensors:
            if len(sensors) == 1:
                resolved = _SENSOR_FALLBACK_FAMILY.get(sensors[0])
            else:
                resolved = None
        if resolved is not None:
            families.add(resolved)
    return tuple(sorted(families))


def _order_key(pattern: EvidencePattern) -> Tuple[int, str]:
    order = {name: index for index, name in enumerate(FULL_PATTERN_ORDER)}
    return (order.get(pattern.pattern_type, len(order)), pattern.pattern_id)


def _ordered(patterns: Sequence[EvidencePattern]) -> List[EvidencePattern]:
    """Deterministic pattern order: existing P3.1/P3.2 order first.

    Sorted order is lexical within equal ranks for determinism;
    it carries no priority, severity, or preference meaning.
    """
    return sorted(patterns, key=_order_key)


# --------------------------------------------------------------------------
# Validation (pure, deterministic)
# --------------------------------------------------------------------------


def _describe_objects(patterns: Sequence[EvidencePattern]) -> str:
    parts = []
    for pattern in patterns:
        parts.append(f"{pattern.pattern_type} ({pattern.pattern_id})")
    return "; ".join(parts)


def _overlap_statements(
    usable: Sequence[EvidencePattern],
) -> Tuple[bool, Tuple[str, ...], Tuple[str, ...], str]:
    """Detect shared evidence across patterns without grading it.

    Reports metric and evidence identifiers cited by more than one
    contributing pattern.  Shared identifiers mark overlapping
    observation evidence — notably, MULTI_MODAL_CANOPY_CHANGE
    already represents P2.5 sensor concordance, so its S1/S2
    evidence is never counted again as independent additional
    sensor evidence.  The finding is audit information only.
    """
    evidence_holders: Dict[str, List[str]] = {}
    metric_holders: Dict[str, List[str]] = {}
    for pattern in usable:
        for evidence_id in pattern.contributing_evidence_ids:
            evidence_holders.setdefault(evidence_id, []).append(
                pattern.pattern_id
            )
        for metric_id in pattern.contributing_metric_ids:
            metric_holders.setdefault(metric_id, []).append(pattern.pattern_id)
    shared_evidence = tuple(
        sorted(
            evidence_id
            for evidence_id, holders in evidence_holders.items()
            if len(set(holders)) > 1
        )
    )
    shared_metrics = tuple(
        sorted(
            metric_id
            for metric_id, holders in metric_holders.items()
            if len(set(holders)) > 1
        )
    )
    overlapping = bool(shared_evidence or shared_metrics)
    if not overlapping:
        statement = (
            "No overlapping evidence identifiers were observed across "
            "contributing patterns; each pattern's evidence "
            "identifiers are distinct."
        )
    else:
        details = []
        if shared_metrics:
            details.append(f"shared metrics: {', '.join(shared_metrics)}")
        if shared_evidence:
            details.append(f"shared evidence: {', '.join(shared_evidence)}")
        statement = (
            "Overlapping evidence observed (" + "; ".join(details) + "). "
            "Shared S1/S2 evidence is counted once as independent "
            "sensor evidence; MULTI_MODAL_CANOPY_CHANGE already "
            "represents P2.5 sensor concordance and its evidence is "
            "not counted again as an independent additional sensor. "
            "Overlap is reported for audit and is not a strength "
            "indicator."
        )
    return overlapping, shared_metrics, shared_evidence, statement


def validate_window(
    patterns: Sequence[EvidencePattern],
    window_start: str,
    window_end: str,
) -> CrossPatternValidation:
    """Validate established patterns for one exact window.

    Only patterns whose ``(window_start, window_end)`` exactly
    equals the evaluated window contribute; patterns from any
    other window — including adjacent months — are rejected and
    named in provenance.  Multi-month spans are evaluated on
    their exact source span, never split.  Repeated evaluation of
    equal inputs yields an equal result.
    """
    ordered = _ordered(list(patterns))
    matching = [
        pattern
        for pattern in ordered
        if pattern.window_start == window_start
        and pattern.window_end == window_end
    ]
    rejected = [
        pattern.pattern_id
        for pattern in ordered
        if not (
            pattern.window_start == window_start
            and pattern.window_end == window_end
        )
    ]
    usable = [pattern for pattern in matching if _pattern_usable(pattern)]

    metrics = tuple(
        sorted(
            {
                metric_id
                for pattern in usable
                for metric_id in pattern.contributing_metric_ids
            }
        )
    )
    sensors = tuple(
        sorted(
            {
                sensor
                for pattern in usable
                for sensor in pattern.contributing_sensors
            }
        )
    )
    families = tuple(
        sorted(
            {
                family
                for pattern in usable
                for family in _families_of(pattern)
            }
        )
    )
    overlapping, shared_metrics, shared_evidence, overlap_statement = (
        _overlap_statements(usable)
    )
    orientations = {
        pattern.pattern_id: sorted(_orientations_of(pattern))
        for pattern in matching
    }
    source_types = {
        pattern.pattern_id: pattern.pattern_type for pattern in matching
    }
    source_states = {
        pattern.pattern_id: pattern.status for pattern in matching
    }
    source_provenance = {
        pattern.pattern_id: {
            evidence_id: dict(provenance)
            for evidence_id, provenance in pattern.provenance_by_evidence.items()
        }
        for pattern in matching
    }

    if not usable:
        rule = get_validation_rule(RULE_MISSING)
        explanation = (
            f"Insufficient evidence for {window_start} to {window_end}: "
        )
        if not matching:
            explanation += "no established pattern exists for the exact window."
        else:
            explanation += (
                "the evaluated "
                + ("pattern is" if len(matching) == 1 else "patterns are")
                + f" insufficient or unavailable ({_describe_objects(matching)}); "
                + "no pattern can be established and no negative finding "
                + "is made."
            )
        explanation += _NOT_A_FINDING_SUFFIX
        return CrossPatternValidation(
            validation_id=f"{rule.rule_id}:{window_start}:{window_end}",
            window_start=window_start,
            window_end=window_end,
            status=STATUS_INSUFFICIENT,
            contributing_pattern_ids=tuple(
                pattern.pattern_id for pattern in matching
            ),
            compatible_pattern_ids=(),
            conflicting_pattern_ids=(),
            contributing_metric_ids=(),
            contributing_sensors=(),
            contributing_families=(),
            pattern_count=len(matching),
            independent_sensor_count=0,
            overlapping_evidence=False,
            overlapping_metric_ids=(),
            overlapping_evidence_ids=(),
            source_pattern_types=source_types,
            source_pattern_states=source_states,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            rule_description=rule.predicate,
            explanation=explanation,
            overlap_explanation=(
                "No usable evidence identifiers exist for the exact "
                "window, so no overlap assessment applies."
            ),
            provenance={
                "evaluated_window": {
                    "window_start": window_start,
                    "window_end": window_end,
                },
                "orientation_by_pattern": orientations,
                "rejected_pattern_ids": list(rejected),
                "applied_rules": [rule.rule_id],
                "source_provenance": source_provenance,
            },
            limitations=tuple(rule.limitations) + _SHARED_LIMITATIONS,
        )

    moisture = [
        pattern
        for pattern in usable
        if pattern.pattern_type == NAMED_MOISTURE_DIVERGENCE
    ]
    divergent = [
        pattern
        for pattern in usable
        if _ORIENT_DIVERGENT in _orientations_of(pattern)
        and pattern not in moisture
    ]
    # Opposition is a cross-pattern relation: one pattern reading
    # purely decrease-type against another reading purely
    # increase-type for the same exact window.  A single pattern
    # whose own span mixes point states (for example a sustained
    # deviation established over a multi-month span) is that
    # pattern's own established reading, not cross-pattern
    # opposition.
    directional_down = [
        pattern
        for pattern in usable
        if _ORIENT_DOWN in _orientations_of(pattern)
    ]
    directional_up = [
        pattern
        for pattern in usable
        if _ORIENT_UP in _orientations_of(pattern)
    ]
    purely_down = [
        pattern
        for pattern in directional_down
        if _ORIENT_UP not in _orientations_of(pattern)
    ]
    purely_up = [
        pattern
        for pattern in directional_up
        if _ORIENT_DOWN not in _orientations_of(pattern)
    ]
    opposing = bool(purely_down and purely_up)
    concordant = [
        pattern
        for pattern in usable
        if pattern.pattern_type in _CONCORDANT_BY_DEFINITION
    ]

    if moisture:
        rule = get_validation_rule(RULE_MOISTURE_DESCRIPTIVE)
        status = STATUS_MIXED
        involved = {pattern.pattern_id for pattern in moisture}
        involved.update(pattern.pattern_id for pattern in directional_down)
        involved.update(pattern.pattern_id for pattern in directional_up)
        conflicting = tuple(
            pattern.pattern_id for pattern in usable if pattern.pattern_id in involved
        )
        compatible = tuple(
            pattern.pattern_id
            for pattern in usable
            if pattern.pattern_id not in involved
        )
        explanation = (
            f"Mixed evidence for {window_start} to {window_end}: "
            f"a moisture/greenness divergence pattern "
            f"({'; '.join(pattern.pattern_id for pattern in moisture)}) "
            "remains a descriptive divergence of observed moisture "
            "and greenness evidence and does not establish causal "
            "order. It coexists with "
            f"{_describe_objects(usable)} without reinterpretation."
            + _NOT_A_FINDING_SUFFIX
        )
    elif divergent or opposing:
        rule = get_validation_rule(RULE_DIVERGENCE)
        status = STATUS_MIXED
        involved = {pattern.pattern_id for pattern in divergent}
        involved.update(pattern.pattern_id for pattern in directional_down)
        involved.update(pattern.pattern_id for pattern in directional_up)
        if not involved:
            involved = {pattern.pattern_id for pattern in usable}
        conflicting = tuple(
            pattern.pattern_id for pattern in usable if pattern.pattern_id in involved
        )
        compatible = tuple(
            pattern.pattern_id
            for pattern in usable
            if pattern.pattern_id not in involved
        )
        if divergent and opposing:
            reason = (
                "explicitly divergent source evidence and opposing "
                "observed directions (decrease-type against "
                "increase-type)"
            )
        elif divergent:
            reason = "explicitly divergent source evidence"
        else:
            reason = (
                "opposing observed directions (decrease-type against "
                "increase-type)"
            )
        explanation = (
            f"Mixed evidence for {window_start} to {window_end}: "
            f"{reason} was reported for the same exact window "
            f"({'; '.join(pattern.pattern_id for pattern in usable if pattern.pattern_id in involved)}). "
            "The divergence is preserved without reinterpretation; "
            "no pattern is preferred and no winner is selected."
            + _NOT_A_FINDING_SUFFIX
        )
    elif concordant:
        rule = get_validation_rule(RULE_SENSOR_AGREEMENT)
        status = STATUS_CONSISTENT
        compatible = tuple(pattern.pattern_id for pattern in usable)
        conflicting = ()
        explanation = (
            f"Compatible observed changes for {window_start} to "
            f"{window_end}: multiple sensor families reported "
            "compatible observed directional evidence (sensor "
            f"concordance: {', '.join(sensors) if sensors else 'no sensor'}; "
            f"{_describe_objects(usable)}). Sensor concordance "
            "evidences compatible observed change, not a common "
            "biological cause."
            + _NOT_A_FINDING_SUFFIX
        )
    else:
        rule = get_validation_rule(RULE_COMPATIBLE)
        status = STATUS_CONSISTENT
        compatible = tuple(pattern.pattern_id for pattern in usable)
        conflicting = ()
        explanation = (
            f"Compatible observed changes for {window_start} to "
            f"{window_end}: {_describe_objects(usable)} describe "
            "compatible observed directions for the same exact "
            "window and coexist without claiming a shared process."
            + _NOT_A_FINDING_SUFFIX
        )

    applied = [rule.rule_id]
    for candidate in VALIDATION_RULES:
        if candidate.rule_id != rule.rule_id and candidate.rule_id not in applied:
            applied.append(candidate.rule_id)

    return CrossPatternValidation(
        validation_id=f"{rule.rule_id}:{window_start}:{window_end}",
        window_start=window_start,
        window_end=window_end,
        status=status,
        contributing_pattern_ids=tuple(
            pattern.pattern_id for pattern in matching
        ),
        compatible_pattern_ids=compatible,
        conflicting_pattern_ids=conflicting,
        contributing_metric_ids=metrics,
        contributing_sensors=sensors,
        contributing_families=families,
        pattern_count=len(matching),
        independent_sensor_count=len(sensors),
        overlapping_evidence=overlapping,
        overlapping_metric_ids=shared_metrics,
        overlapping_evidence_ids=shared_evidence,
        source_pattern_types=source_types,
        source_pattern_states=source_states,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        rule_description=rule.predicate,
        explanation=explanation,
        overlap_explanation=overlap_statement,
        provenance={
            "evaluated_window": {
                "window_start": window_start,
                "window_end": window_end,
            },
            "orientation_by_pattern": orientations,
            "rejected_pattern_ids": list(rejected),
            "applied_rules": applied,
            "source_provenance": source_provenance,
        },
        limitations=tuple(rule.limitations) + _SHARED_LIMITATIONS,
    )


def sort_validations(
    validations: Sequence[CrossPatternValidation],
) -> Tuple[CrossPatternValidation, ...]:
    """Deterministic order over validation statements.

    Ordered by exact window and then validation identifier.  The
    order is chronological and lexical for determinism; it carries
    no ranking, priority, or preference meaning.
    """
    return tuple(
        sorted(
            validations,
            key=lambda item: (
                item.window_start,
                item.window_end,
                item.validation_id,
            ),
        )
    )


def validate_all(
    patterns: Sequence[EvidencePattern],
) -> Tuple[CrossPatternValidation, ...]:
    """Validate every exact window present in the pattern outputs.

    Groups established patterns by exact ``(window_start,
    window_end)`` identity — one validation statement per exact
    window, in deterministic window order.  Adjacent windows are
    never merged, gaps break nothing because nothing spans them,
    and multi-month spans keep their exact source span.
    """
    groups: Dict[Tuple[str, str], List[EvidencePattern]] = {}
    for pattern in patterns:
        groups.setdefault(
            (pattern.window_start, pattern.window_end), []
        ).append(pattern)
    validations = [
        validate_window(group, window_start, window_end)
        for (window_start, window_end), group in groups.items()
    ]
    return sort_validations(validations)
