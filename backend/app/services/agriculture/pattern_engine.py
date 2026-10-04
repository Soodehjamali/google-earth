"""Evidence Pattern Engine foundation (P3.1).

A reusable, deterministic engine that describes combinations of
already-computed evidence.  It consumes the temporal,
statistical, and concordance states produced by P1/P2 and emits
generic, sensor-agnostic patterns — never a biological cause.

The engine describes observed combinations of measurements and
existing statistical states.  It does not identify biological
causes: a persistent anomaly is not equivalent to pest or
disease presence, rapid change is not equivalent to pest or
disease damage, multi-sensor concordance indicates agreement
between sensor-derived observations rather than a shared
biological cause, and divergence establishes neither absence
nor presence of a biological cause.  Biological attribution
requires additional evidence and ultimately ground-truth
validation.

Consumed contracts (traced, reused verbatim, never recomputed):

* P1.2 anomaly points: value, unit, quality, coverage, image
  count, z-score, percentile, and the neutral categories NORMAL,
  BELOW_BASELINE, ABOVE_BASELINE, INSUFFICIENT_BASELINE, plus
  baselines with mean, spread, population counts, and reference
  range.
* P1.3 month changes: value and previous value, absolute and
  relative change, elapsed days and per-day rate, the direction
  labels INCREASE, DECREASE, STABLE, INSUFFICIENT, and the rapid
  labels RAPID_INCREASE, RAPID_DECREASE, NOT_RAPID,
  INSUFFICIENT — with the one-month gap allowance and the
  zero-denominator refusals exactly as defined there.
* P1.3 deviation persistence: longest runs below and above,
  anomalous/observed/missing counts, and the states PERSISTENT,
  NO_PERSISTENCE, INSUFFICIENT with the established minimum run
  length; gaps and ties break runs.
* P2.2 red-edge changes: per-diagnostic value steps with the
  P1.3 direction labels, consumed as Sentinel-2-derived
  evidence.
* P2.4 radar analyses: per-metric baselines, scored anomaly
  points, month changes, and persistence records.
* P2.5 concordance months: exact-window states
  MULTI_SENSOR_CONCORDANT, DIVERGENT, MIXED_EVIDENCE,
  OPTICAL_ONLY, RADAR_ONLY, INSUFFICIENT_EVIDENCE with reasons
  and contributing families.

No new Earth Engine computation, no new statistics, no new
spectral or radar formulas, no baselines, no anomalies, no
correlation, no models, and no numeric confidence scores exist
here.  Every predicate reads states that earlier phases already
published; every threshold in force (minimum runs, gap
allowance, spread-relative rapid flags) remains owned by P1.3.

Foundation patterns (generic only; named biological patterns
belong to later phases):

* ``PERSISTENT_ANOMALY`` — an existing source reports a valid
  persistent deviation under P1.3 semantics.
* ``RAPID_CHANGE`` — an existing source reports a valid P1.3
  rapid-change label.
* ``MULTI_SENSOR_CONCORDANCE`` — P2.5 already classified the
  exact month concordant (never recomputed).
* ``DIVERGENT_SENSOR_EVIDENCE`` — P2.5 already classified the
  exact month divergent (never recomputed).
* ``SEQUENTIAL_CHANGE`` — consecutive calendar months with the
  same explicit INCREASE or DECREASE direction from existing
  change states; missing or non-matching months break runs.
* ``INSUFFICIENT_EVIDENCE`` — evaluation was attempted but the
  sources cannot establish a pattern (missing is never promoted
  and never converted into negative evidence: no evidence is
  not evidence of no change).

Patterns carry OBSERVED status when established and
INSUFFICIENT_EVIDENCE when sources cannot establish them;
multiple patterns may coexist for one window and are returned
in deterministic rule order.  Sensor-family semantics follow
P2.5: same-family metrics never count as separate sensors and
red-edge evidence remains Sentinel-2-derived.

Non-goals of this phase: named biological patterns, rankings or
priorities, numeric scores, model inference, thermal inputs, new
datasets, endpoints, charts, and cache changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.baseline_anomaly import (
    AnomalyProfile,
)
from app.services.agriculture.change_profile import (
    DIRECTION_DECREASE,
    DIRECTION_INCREASE,
    DeviationPersistence,
    MonthChange,
)
from app.services.agriculture.concordance import (
    CONCORDANCE_RULE_ID,
    FAMILY_SENSOR,
    STATE_CONCORDANT,
    STATE_DIVERGENT,
    STATE_INSUFFICIENT,
    ConcordanceMonth,
)
from app.services.agriculture.temporal_profile import TemporalProfilePoint

logger = get_logger(__name__)

__all__ = [
    "PATTERN_PERSISTENT_ANOMALY",
    "PATTERN_RAPID_CHANGE",
    "PATTERN_CONCORDANCE",
    "PATTERN_DIVERGENCE",
    "PATTERN_SEQUENTIAL",
    "PATTERN_INSUFFICIENT",
    "PATTERN_TYPES",
    "STATUS_OBSERVED",
    "STATUS_NOT_OBSERVED",
    "STATUS_INSUFFICIENT",
    "PATTERN_ORDER",
    "ENGINE_VERSION",
    "PatternEvidence",
    "EvidencePattern",
    "PatternRule",
    "MetricEvidenceBundle",
    "RULES",
    "get_rule",
    "make_evidence",
    "evidence_from_anomaly_point",
    "evidence_from_month_change",
    "evidence_from_red_edge_change",
    "evidence_from_concordance_item",
    "evaluate_persistent_anomaly",
    "evaluate_rapid_changes",
    "evaluate_concordance_month",
    "evaluate_sequential_changes",
    "evaluate_all",
    "sort_patterns",
]

#: Engine version published on every pattern.
ENGINE_VERSION = "P31_V1"

#: Generic pattern types.  The vocabulary is deliberately small
#: and non-biological.
PATTERN_PERSISTENT_ANOMALY = "PERSISTENT_ANOMALY"
PATTERN_RAPID_CHANGE = "RAPID_CHANGE"
PATTERN_CONCORDANCE = "MULTI_SENSOR_CONCORDANCE"
PATTERN_DIVERGENCE = "DIVERGENT_SENSOR_EVIDENCE"
PATTERN_SEQUENTIAL = "SEQUENTIAL_CHANGE"
PATTERN_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
PATTERN_TYPES: Tuple[str, ...] = (
    PATTERN_PERSISTENT_ANOMALY,
    PATTERN_RAPID_CHANGE,
    PATTERN_CONCORDANCE,
    PATTERN_DIVERGENCE,
    PATTERN_SEQUENTIAL,
    PATTERN_INSUFFICIENT,
)

#: Pattern status vocabulary: OBSERVED, NOT_OBSERVED, and
#: INSUFFICIENT_EVIDENCE, all categorical.
STATUS_OBSERVED = "OBSERVED"
STATUS_NOT_OBSERVED = "NOT_OBSERVED"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

#: Deterministic emission order for coexisting patterns.
PATTERN_ORDER: Tuple[str, ...] = (
    PATTERN_PERSISTENT_ANOMALY,
    PATTERN_RAPID_CHANGE,
    PATTERN_CONCORDANCE,
    PATTERN_DIVERGENCE,
    PATTERN_SEQUENTIAL,
    PATTERN_INSUFFICIENT,
)

#: Rapid labels that establish a rapid-change pattern.  Owned by
#: P1.3; restated here for predicate readability, never redefined.
RAPID_ESTABLISHED = ("RAPID_INCREASE", "RAPID_DECREASE")

#: Change directions that can form a sequence.  STABLE is an
#: explicit direction but not a change sequence.
SEQUENCE_DIRECTIONS = (DIRECTION_INCREASE, DIRECTION_DECREASE)

#: Source states that refuse pattern promotion.  Anything else —
#: including poor quality, which upstream already caveats — may
#: still establish a pattern, with its quality preserved on it.
REFUSING_QUALITIES = frozenset({"unavailable", "insufficient", ""})

_NO_CAUSE_SUFFIX = (
    " This describes an observed temporal pattern and does not "
    "establish a biological cause."
)


# --------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternEvidence:
    """Narrow internal evidence item for one metric and one window.

    The original source information travels intact: source module,
    metric, sensor, family, window, value, unit, the verbatim
    source states, quality, coverage, and provenance.  Nothing is
    flattened away, so every pattern can explain where it came
    from without re-running anything.
    """

    evidence_id: str
    source_module: str
    metric_id: str
    sensor: str
    family: str
    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    anomaly_state: Optional[str] = None
    change_direction: Optional[str] = None
    rapid: Optional[str] = None
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form for pattern inputs and audit trails."""
        return {
            "evidence_id": self.evidence_id,
            "source_module": self.source_module,
            "metric_id": self.metric_id,
            "sensor": self.sensor,
            "family": self.family,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "anomaly_state": self.anomaly_state,
            "change_direction": self.change_direction,
            "rapid": self.rapid,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "provenance": dict(self.provenance),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class EvidencePattern:
    """One described evidence pattern.

    ``status`` is OBSERVED when established and
    INSUFFICIENT_EVIDENCE when evaluation was attempted but the
    sources cannot establish the pattern.  Contributing lists
    name every evidence item, metric, and sensor family behind
    the statement.
    """

    pattern_id: str
    pattern_type: str
    window_start: str
    window_end: str
    status: str
    contributing_evidence_ids: Tuple[str, ...]
    contributing_metric_ids: Tuple[str, ...]
    contributing_sensors: Tuple[str, ...]
    source_states: Dict[str, str]
    rule_id: str
    rule_version: str
    rule_description: str
    explanation: str
    quality_by_evidence: Dict[str, str]
    coverage_by_evidence: Dict[str, Optional[float]]
    provenance_by_evidence: Dict[str, Dict[str, Any]]
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P3.1 API contract models."""
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "status": self.status,
            "contributing_evidence_ids": list(self.contributing_evidence_ids),
            "contributing_metric_ids": list(self.contributing_metric_ids),
            "contributing_sensors": list(self.contributing_sensors),
            "source_states": dict(self.source_states),
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "rule_description": self.rule_description,
            "explanation": self.explanation,
            "quality_by_evidence": dict(self.quality_by_evidence),
            "coverage_by_evidence": dict(self.coverage_by_evidence),
            "provenance_by_evidence": {
                key: dict(value)
                for key, value in self.provenance_by_evidence.items()
            },
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class PatternRule:
    """One deterministic registry rule."""

    rule_id: str
    rule_version: str
    name: str
    pattern_type: str
    requires: Tuple[str, ...]
    predicate: str
    limitations: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form for registry inspection."""
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "name": self.name,
            "pattern_type": self.pattern_type,
            "requires": list(self.requires),
            "predicate": self.predicate,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class MetricEvidenceBundle:
    """All existing evidence for one metric over one span.

    The per-metric input to whole-span evaluation: the scored
    anomaly profile with its persistence record, the month-change
    list, and per-window underlying provenance.  Identity
    (metric, sensor, family, source module) is declared once and
    reused by every rule.
    """

    metric_id: str
    sensor: str
    family: str
    source_module: str
    anomalies: AnomalyProfile
    persistence: DeviationPersistence
    changes: Tuple[MonthChange, ...] = ()
    provenance_by_window: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )


# --------------------------------------------------------------------------
# Rule registry (deterministic order)
# --------------------------------------------------------------------------


RULES: Tuple[PatternRule, ...] = (
    PatternRule(
        rule_id="P31_PERSISTENT_ANOMALY_V1",
        rule_version=ENGINE_VERSION,
        name="Persistent anomaly",
        pattern_type=PATTERN_PERSISTENT_ANOMALY,
        requires=("anomaly_profile", "deviation_persistence",),
        predicate=(
            "The source persistence record reads PERSISTENT under "
            "P1.3 semantics with usable source quality; the "
            "pattern spans the evaluated series and cites the "
            "existing run lengths."
        ),
        limitations=(
            "Run lengths and counts are the P1.3 record's own; no "
            "run-window localization beyond it is performed.",
            "Persistence of a deviation is not presence of a cause.",
        ),
    ),
    PatternRule(
        rule_id="P31_RAPID_CHANGE_V1",
        rule_version=ENGINE_VERSION,
        name="Rapid change",
        pattern_type=PATTERN_RAPID_CHANGE,
        requires=("month_change.rapid",),
        predicate=(
            "A month change carries a P1.3 rapid label "
            "(RAPID_INCREASE or RAPID_DECREASE) with usable source "
            "quality."
        ),
        limitations=(
            "The rapid label and its spread comparison belong to "
            "P1.3; a rapid step describes step size only.",
        ),
    ),
    PatternRule(
        rule_id="P31_CONCORDANCE_V1",
        rule_version=ENGINE_VERSION,
        name="Multi-sensor concordance",
        pattern_type=PATTERN_CONCORDANCE,
        requires=("concordance_month=MULTI_SENSOR_CONCORDANT",),
        predicate=(
            "P2.5 already classified the exact month "
            "MULTI_SENSOR_CONCORDANT; the rule restates that month "
            "without recomputing it."
        ),
        limitations=(
            "Agreement evidences a shared observed change, not a "
            "shared cause.",
        ),
    ),
    PatternRule(
        rule_id="P31_DIVERGENCE_V1",
        rule_version=ENGINE_VERSION,
        name="Divergent sensor evidence",
        pattern_type=PATTERN_DIVERGENCE,
        requires=("concordance_month=DIVERGENT",),
        predicate=(
            "P2.5 already classified the exact month DIVERGENT; "
            "the rule restates that month without recomputing it."
        ),
        limitations=(
            "Divergence establishes neither absence nor presence "
            "of a cause.",
        ),
    ),
    PatternRule(
        rule_id="P31_SEQUENTIAL_CHANGE_V1",
        rule_version=ENGINE_VERSION,
        name="Sequential change",
        pattern_type=PATTERN_SEQUENTIAL,
        requires=("month_change.direction",),
        predicate=(
            "Two or more consecutive calendar months carry the "
            "same explicit INCREASE or DECREASE direction from "
            "existing change states with usable source quality; "
            "missing or non-matching months break runs."
        ),
        limitations=(
            "A directional run is chronological order, not a "
            "process model.",
        ),
    ),
    PatternRule(
        rule_id="P31_INSUFFICIENT_V1",
        rule_version=ENGINE_VERSION,
        name="Insufficient evidence",
        pattern_type=PATTERN_INSUFFICIENT,
        requires=("concordance_month=INSUFFICIENT_EVIDENCE",),
        predicate=(
            "P2.5 classified the exact month INSUFFICIENT_EVIDENCE; "
            "the rule records that no pattern can be established, "
            "never a negative claim."
        ),
        limitations=(
            "No evidence is not evidence of no change.",
        ),
    ),
)


def get_rule(rule_id: str) -> PatternRule:
    """Look up a registry rule, with an actionable error if absent."""
    for rule in RULES:
        if rule.rule_id == rule_id:
            return rule
    available = ", ".join(rule.rule_id for rule in RULES)
    raise KeyError(
        f"Pattern rule {rule_id!r} is not registered. "
        f"Available rules: {available}"
    )


# --------------------------------------------------------------------------
# Adapters (existing structures to the narrow item)
# --------------------------------------------------------------------------


def _quality_ok(quality: Any) -> bool:
    if not isinstance(quality, str):
        return False
    return quality.strip().lower() not in REFUSING_QUALITIES


def make_evidence(
    evidence_id: str,
    source_module: str,
    metric_id: str,
    sensor: str,
    family: str,
    window_start: str,
    window_end: str,
    value: Optional[float] = None,
    unit: str = "",
    anomaly_state: Optional[str] = None,
    change_direction: Optional[str] = None,
    rapid: Optional[str] = None,
    quality: str = "unavailable",
    coverage_percent: Optional[float] = None,
    image_count: Optional[int] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    limitations: Sequence[str] = (),
) -> PatternEvidence:
    """Build one validated narrow evidence item."""
    return PatternEvidence(
        evidence_id=evidence_id,
        source_module=source_module,
        metric_id=metric_id,
        sensor=sensor,
        family=family,
        window_start=window_start,
        window_end=window_end,
        value=value,
        unit=unit,
        anomaly_state=anomaly_state,
        change_direction=change_direction,
        rapid=rapid,
        quality=quality,
        coverage_percent=coverage_percent,
        image_count=image_count,
        provenance=dict(provenance) if provenance else {},
        limitations=tuple(limitations),
    )


def evidence_from_anomaly_point(
    source_module: str,
    metric_id: str,
    sensor: str,
    family: str,
    point: TemporalProfilePoint,
    category: Optional[str] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> PatternEvidence:
    """Adapt a scored anomaly point (P1.2 shape) to the narrow item."""
    return PatternEvidence(
        evidence_id=f"{metric_id}:{point.window_start}:anomaly",
        source_module=source_module,
        metric_id=metric_id,
        sensor=sensor,
        family=family,
        window_start=point.window_start,
        window_end=point.window_end,
        value=point.value,
        unit=point.unit,
        anomaly_state=category,
        change_direction=None,
        rapid=None,
        quality=point.quality,
        coverage_percent=point.coverage_percent,
        image_count=point.image_count,
        provenance=dict(provenance) if provenance else {},
        limitations=(),
    )


def evidence_from_month_change(
    source_module: str,
    metric_id: str,
    sensor: str,
    family: str,
    change: MonthChange,
    provenance: Optional[Mapping[str, Any]] = None,
) -> PatternEvidence:
    """Adapt a P1.3 month change to the narrow item."""
    return PatternEvidence(
        evidence_id=f"{metric_id}:{change.window_start}:change",
        source_module=source_module,
        metric_id=metric_id,
        sensor=sensor,
        family=family,
        window_start=change.window_start,
        window_end=change.window_end,
        value=change.value,
        unit=change.unit,
        anomaly_state=None,
        change_direction=change.direction,
        rapid=change.rapid,
        quality=change.quality,
        coverage_percent=change.coverage_percent,
        image_count=change.image_count,
        provenance=dict(provenance) if provenance else {},
        limitations=(),
    )


def evidence_from_red_edge_change(
    diagnostic_id: str,
    change: Any,
    provenance: Optional[Mapping[str, Any]] = None,
) -> PatternEvidence:
    """Adapt a P2.2 red-edge change to the narrow item.

    Red-edge diagnostics remain Sentinel-2-derived evidence: the
    sensor resolves through the P2.5 family mapping, never as an
    independent sensor.
    """
    return PatternEvidence(
        evidence_id=f"{diagnostic_id}:{change.window_start}:change",
        source_module="red_edge",
        metric_id=diagnostic_id,
        sensor=FAMILY_SENSOR["red_edge"],
        family="red_edge",
        window_start=change.window_start,
        window_end=change.window_end,
        value=change.value,
        unit=change.unit,
        anomaly_state=None,
        change_direction=change.direction,
        rapid=None,
        quality=getattr(change, "quality", "unavailable"),
        coverage_percent=getattr(change, "coverage_percent", None),
        image_count=getattr(change, "image_count", None),
        provenance=dict(provenance) if provenance else {},
        limitations=(),
    )


def evidence_from_concordance_item(
    item: Any,
    provenance: Optional[Mapping[str, Any]] = None,
) -> PatternEvidence:
    """Adapt a P2.5 concordance evidence item to the narrow item."""
    merged = dict(item.provenance)
    if provenance:
        merged.update(provenance)
    return PatternEvidence(
        evidence_id=(
            f"{item.metric_id}:{item.window_start}:{item.state_kind}"
        ),
        source_module="concordance",
        metric_id=item.metric_id,
        sensor=item.sensor,
        family=item.family,
        window_start=item.window_start,
        window_end=item.window_end,
        value=item.value,
        unit=item.unit,
        anomaly_state=item.state if item.state_kind == "anomaly" else None,
        change_direction=item.state if item.state_kind == "change" else None,
        rapid=None,
        quality=item.quality,
        coverage_percent=item.coverage_percent,
        image_count=item.image_count,
        provenance=merged,
        limitations=(),
    )


# --------------------------------------------------------------------------
# Rule evaluation (pure, deterministic)
# --------------------------------------------------------------------------


def _pattern_shell(
    rule: PatternRule,
    pattern_type: str,
    window_start: str,
    window_end: str,
    status: str,
    items: Sequence[PatternEvidence],
    explanation: str,
    pattern_id: str,
) -> EvidencePattern:
    metrics = tuple(sorted({item.metric_id for item in items}))
    sensors = tuple(sorted({item.sensor for item in items}))
    states: Dict[str, str] = {}
    quality: Dict[str, str] = {}
    coverage: Dict[str, Optional[float]] = {}
    provenance: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if item.rapid in RAPID_ESTABLISHED:
            states[item.evidence_id] = item.rapid
        else:
            states[item.evidence_id] = (
                item.anomaly_state or item.change_direction or item.rapid or ""
            )
        quality[item.evidence_id] = item.quality
        coverage[item.evidence_id] = item.coverage_percent
        provenance[item.evidence_id] = dict(item.provenance)
    return EvidencePattern(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        window_start=window_start,
        window_end=window_end,
        status=status,
        contributing_evidence_ids=tuple(item.evidence_id for item in items),
        contributing_metric_ids=metrics,
        contributing_sensors=sensors,
        source_states=states,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        rule_description=rule.predicate,
        explanation=explanation,
        quality_by_evidence=quality,
        coverage_by_evidence=coverage,
        provenance_by_evidence=provenance,
        limitations=rule.limitations,
    )


def evaluate_persistent_anomaly(
    metric_id: str,
    sensor: str,
    family: str,
    source_module: str,
    anomalies: AnomalyProfile,
    persistence: DeviationPersistence,
    provenance_by_window: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[EvidencePattern]:
    """Emit PERSISTENT_ANOMALY when the P1.3 record reads PERSISTENT.

    The pattern spans the evaluated series and cites the existing
    run lengths and counts; no run-window localization beyond the
    record is performed.  Anything but a valid persistent record
    with usable source quality yields no pattern.
    """
    rule = get_rule("P31_PERSISTENT_ANOMALY_V1")
    if persistence.state != "PERSISTENT":
        return None
    usable = [
        point
        for point in anomalies.points
        if point.value is not None and _quality_ok(point.quality)
    ]
    if not usable:
        return None
    below = persistence.longest_run_below >= persistence.longest_run_above
    run_length = (
        persistence.longest_run_below if below else persistence.longest_run_above
    )
    leaning = "below-baseline" if below else "above-baseline"
    items = tuple(
        PatternEvidence(
            evidence_id=f"{metric_id}:{point.window_start}:anomaly",
            source_module=source_module,
            metric_id=metric_id,
            sensor=sensor,
            family=family,
            window_start=point.window_start,
            window_end=point.window_end,
            value=point.value,
            unit=point.unit,
            anomaly_state=point.category,
            change_direction=None,
            rapid=None,
            quality=point.quality,
            coverage_percent=point.coverage_percent,
            image_count=point.image_count,
            provenance=dict((provenance_by_window or {}).get(point.window_start, {})),
            limitations=(),
        )
        for point in usable
    )
    explanation = (
        f"Persistent {leaning} deviation was observed in {metric_id} "
        f"across {len(usable)} usable monthly observations "
        f"({anomalies.window_start} to {anomalies.window_end}), with "
        f"a longest {leaning} run of {run_length} consecutive months "
        f"under {rule.rule_id}." + _NO_CAUSE_SUFFIX
    )
    return _pattern_shell(
        rule,
        PATTERN_PERSISTENT_ANOMALY,
        anomalies.window_start,
        anomalies.window_end,
        STATUS_OBSERVED,
        items,
        explanation,
        f"{rule.rule_id}:{metric_id}:{anomalies.window_start}:{anomalies.window_end}",
    )


def evaluate_rapid_changes(
    items: Sequence[PatternEvidence],
) -> Tuple[EvidencePattern, ...]:
    """Emit RAPID_CHANGE for items with a valid P1.3 rapid label."""
    rule = get_rule("P31_RAPID_CHANGE_V1")
    patterns: List[EvidencePattern] = []
    for item in items:
        if item.rapid not in RAPID_ESTABLISHED:
            continue
        if not _quality_ok(item.quality):
            continue
        heading = "increase" if "INCREASE" in str(item.rapid) else "decrease"
        explanation = (
            f"Rapid {heading} was reported for {item.metric_id} in "
            f"{item.window_start} to {item.window_end} by the existing "
            f"{item.rapid} label under {rule.rule_id}." + _NO_CAUSE_SUFFIX
        )
        patterns.append(
            _pattern_shell(
                rule,
                PATTERN_RAPID_CHANGE,
                item.window_start,
                item.window_end,
                STATUS_OBSERVED,
                (item,),
                explanation,
                f"{rule.rule_id}:{item.metric_id}:{item.window_start}",
            )
        )
    return tuple(patterns)


def _concordance_items(
    month: ConcordanceMonth,
) -> Tuple[PatternEvidence, ...]:
    return tuple(
        PatternEvidence(
            evidence_id=f"{item.metric_id}:{item.window_start}:concordance",
            source_module="concordance",
            metric_id=item.metric_id,
            sensor=item.sensor,
            family=item.family,
            window_start=item.window_start,
            window_end=item.window_end,
            value=item.value,
            unit=item.unit,
            anomaly_state=None,
            change_direction=None,
            rapid=None,
            quality=item.quality,
            coverage_percent=item.coverage_percent,
            image_count=item.image_count,
            provenance=dict(item.provenance),
            limitations=(),
        )
        for family in month.families
        for item in family.items
        if item.is_usable
    )


def evaluate_concordance_month(
    month: ConcordanceMonth,
) -> Tuple[EvidencePattern, ...]:
    """Restate a P2.5 month as engine patterns without recomputing."""
    if month.state == STATE_CONCORDANT:
        rule = get_rule("P31_CONCORDANCE_V1")
        items = _concordance_items(month)
        explanation = (
            f"Multi-sensor concordance was already established for "
            f"{month.window_start} to {month.window_end} under "
            f"{CONCORDANCE_RULE_ID}: " + "; ".join(month.reasons)
            + "." + _NO_CAUSE_SUFFIX
        )
        return (
            _pattern_shell(
                rule,
                PATTERN_CONCORDANCE,
                month.window_start,
                month.window_end,
                STATUS_OBSERVED,
                items,
                explanation,
                f"{rule.rule_id}:{month.window_start}",
            ),
        )
    if month.state == STATE_DIVERGENT:
        rule = get_rule("P31_DIVERGENCE_V1")
        items = _concordance_items(month)
        explanation = (
            f"Divergent sensor evidence was already established for "
            f"{month.window_start} to {month.window_end} under "
            f"{CONCORDANCE_RULE_ID}: " + "; ".join(month.reasons)
            + "." + _NO_CAUSE_SUFFIX
        )
        return (
            _pattern_shell(
                rule,
                PATTERN_DIVERGENCE,
                month.window_start,
                month.window_end,
                STATUS_OBSERVED,
                items,
                explanation,
                f"{rule.rule_id}:{month.window_start}",
            ),
        )
    if month.state == STATE_INSUFFICIENT:
        rule = get_rule("P31_INSUFFICIENT_V1")
        explanation = (
            f"No pattern can be established for {month.window_start} "
            f"to {month.window_end}: the sources report "
            f"insufficient evidence under {CONCORDANCE_RULE_ID}."
        )
        return (
            _pattern_shell(
                rule,
                PATTERN_INSUFFICIENT,
                month.window_start,
                month.window_end,
                STATUS_INSUFFICIENT,
                (),
                explanation,
                f"{rule.rule_id}:{month.window_start}",
            ),
        )
    return ()


def _months_between(first: str, second: str) -> Optional[int]:
    try:
        earlier = date.fromisoformat(first)
        later = date.fromisoformat(second)
    except (ValueError, TypeError):
        return None
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def evaluate_sequential_changes(
    items: Sequence[PatternEvidence],
) -> Tuple[EvidencePattern, ...]:
    """Emit SEQUENTIAL_CHANGE for directional runs of two or more.

    Items group by metric; within a metric, consecutive calendar
    months sharing one explicit INCREASE or DECREASE direction
    form maximal runs.  Missing months, unusable quality, and
    non-matching directions break runs.  The run minimum of two
    is definitional (a sequence needs a pair), not a statistical
    cut-off.
    """
    rule = get_rule("P31_SEQUENTIAL_CHANGE_V1")
    by_metric: Dict[str, List[PatternEvidence]] = {}
    for item in items:
        if item.change_direction not in SEQUENCE_DIRECTIONS:
            continue
        if not _quality_ok(item.quality):
            continue
        by_metric.setdefault(item.metric_id, []).append(item)
    patterns: List[EvidencePattern] = []
    for metric_id in sorted(by_metric):
        ordered = sorted(by_metric[metric_id], key=lambda i: i.window_start)
        run: List[PatternEvidence] = []
        for item in ordered:
            if (
                run
                and _months_between(run[-1].window_start, item.window_start) == 1
                and run[-1].change_direction == item.change_direction
            ):
                run.append(item)
                continue
            if len(run) >= 2:
                patterns.append(_sequential_pattern(rule, run))
            run = [item]
        if len(run) >= 2:
            patterns.append(_sequential_pattern(rule, run))
    return tuple(patterns)


def _sequential_pattern(
    rule: PatternRule, run: Sequence[PatternEvidence]
) -> EvidencePattern:
    direction = run[0].change_direction
    heading = "increase" if direction == DIRECTION_INCREASE else "decrease"
    months = ", ".join(item.window_start for item in run)
    explanation = (
        f"Sequential {heading} was observed in {run[0].metric_id} "
        f"across {len(run)} consecutive months ({months}) under "
        f"{rule.rule_id}." + _NO_CAUSE_SUFFIX
    )
    return _pattern_shell(
        rule,
        PATTERN_SEQUENTIAL,
        run[0].window_start,
        run[-1].window_end,
        STATUS_OBSERVED,
        tuple(run),
        explanation,
        f"{rule.rule_id}:{run[0].metric_id}:{direction}:"
        f"{run[0].window_start}:{run[-1].window_end}",
    )


def sort_patterns(
    patterns: Sequence[EvidencePattern],
) -> Tuple[EvidencePattern, ...]:
    """Deterministic emission order across coexisting patterns."""
    order = {name: index for index, name in enumerate(PATTERN_ORDER)}
    return tuple(
        sorted(
            patterns,
            key=lambda p: (
                order.get(p.pattern_type, len(order)),
                p.window_start,
                p.window_end,
                p.pattern_id,
            ),
        )
    )


def evaluate_all(
    bundles: Sequence[MetricEvidenceBundle],
    concordance_months: Sequence[ConcordanceMonth] = (),
) -> Tuple[EvidencePattern, ...]:
    """Evaluate every foundation rule over per-metric bundles.

    Converts each bundle's month changes to narrow items for the
    rapid and sequential rules, runs the persistent rule from its
    anomaly profile and persistence record, restates each
    concordance month, and returns all established patterns in
    deterministic rule order.
    """
    collected: List[EvidencePattern] = []
    for bundle in bundles:
        items = tuple(
            evidence_from_month_change(
                bundle.source_module,
                bundle.metric_id,
                bundle.sensor,
                bundle.family,
                change,
                (bundle.provenance_by_window or {}).get(change.window_start),
            )
            for change in bundle.changes
        )
        collected.extend(evaluate_rapid_changes(items))
        collected.extend(evaluate_sequential_changes(items))
        persistent = evaluate_persistent_anomaly(
            bundle.metric_id,
            bundle.sensor,
            bundle.family,
            bundle.source_module,
            bundle.anomalies,
            bundle.persistence,
            bundle.provenance_by_window,
        )
        if persistent is not None:
            collected.append(persistent)
    for month in concordance_months:
        collected.extend(evaluate_concordance_month(month))
    return sort_patterns(collected)
