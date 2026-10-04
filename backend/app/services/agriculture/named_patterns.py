"""Named non-specific evidence patterns (P3.2).

Five neutral, agricultural evidence patterns built on the P3.1
engine contract.  Each pattern describes an observed combination
of optical, red-edge, moisture, or radar signals and states
explicitly what is not established.  No pattern here diagnoses
or identifies pests, diseases, pathogens, insects, fungi,
defoliators, vascular or wood-boring damage, chlorosis, nutrient
deficiency, or any other biological cause — those readings are
structurally absent: there is no vocabulary for them anywhere in
this module.

Scientific limitations (per pattern, also published on every
output):

* RAPID_CANOPY_SIGNAL_DECLINE — a rapid NDVI/NDRE decline can
  result from phenology, water stress, heat, management,
  atmospheric or processing effects, or other causes.
* MOISTURE_GREENNESS_DIVERGENCE — a temporal moisture/greenness
  divergence is descriptive and does not establish causal order
  or a biological cause.
* RED_EDGE_DECLINE_PATTERN — red-edge changes may reflect
  chlorophyll, canopy structure, phenology, water status,
  soil/background, management, atmosphere, or biological stress.
* SUSTAINED_RADAR_DEVIATION — radar deviation may reflect
  vegetation structure, soil moisture, roughness, geometry,
  incidence angle, acquisition conditions, and processing.
* MULTI_MODAL_CANOPY_CHANGE — cross-sensor agreement evidences
  compatible observed change, not a common biological cause.

Reused contracts (nothing re-derived, no second engine):

* P3.1 ``EvidencePattern`` output, ``PatternRule`` registry
  entries, status vocabulary, and sensor-family semantics; the
  five evaluators below construct ``EvidencePattern`` objects
  directly, sharing the single P3.1 output contract (no new
  schemas were required).
* P1.3 month changes with their rapid labels, directions,
  absolute/relative/rate arithmetic, and quality fields; the
  existing rapid-decline state is read, never re-thresholded.
* P1.4 joint analyses: the ``MOISTURE_DOWN_NDVI_STABLE``
  divergence descriptor, joint-point qualities, and lag results
  (exposed descriptively; no lag is preferred and moisture
  decline is never said to cause later greenness change).  The
  moisture side must be NDMI — true NDWI is never substituted
  or renamed, following the joint layer's own enforcement.
* P2.2 red-edge changes with their existing DECREASE
  directions; every declining diagnostic in a month is
  preserved individually, and the count is reported, never
  scored.
* P2.4 radar analyses with their persistence records,
  baselines, z-scores, and provenance.
* P2.5 concordance months: the MULTI_SENSOR_CONCORDANT state is
  restated, never recomputed, with S2 and S1 each counting once
  however many metrics they contain.

Multiple named patterns may coexist for one month; they are
returned in deterministic order and never resolved into a
ranking, a biological score, or any numeric or categorical
biological reading.

Non-goals of this phase: biological pattern definitions beyond
these five neutral readings, causal language, probability or
risk scoring, model inference, thermal inputs, new datasets,
endpoints, charts, and cache changes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.change_profile import (
    PERSISTENCE_PERSISTENT,
    MonthChange,
    RAPID_DECREASE,
)
from app.services.agriculture.concordance import (
    STATE_CONCORDANT,
    ConcordanceMonth,
)
from app.services.agriculture.joint_profile import (
    DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE,
    JointAnalysis,
)
from app.services.agriculture.pattern_engine import (
    ENGINE_VERSION,
    PATTERN_ORDER,
    STATUS_OBSERVED,
    EvidencePattern,
    PatternEvidence,
    PatternRule,
)
from app.services.agriculture.radar_anomaly import RadarMetricAnalysis

logger = get_logger(__name__)

__all__ = [
    "NAMED_RAPID_DECLINE",
    "NAMED_MOISTURE_DIVERGENCE",
    "NAMED_RED_EDGE_DECLINE",
    "NAMED_RADAR_DEVIATION",
    "NAMED_MULTI_MODAL",
    "NAMED_PATTERN_TYPES",
    "NAMED_PATTERN_ORDER",
    "FULL_PATTERN_ORDER",
    "NAMED_RULES",
    "RAPID_DECLINE_METRICS",
    "get_named_rule",
    "evaluate_rapid_canopy_decline",
    "evaluate_moisture_greenness_divergence",
    "evaluate_red_edge_decline",
    "evaluate_sustained_radar_deviation",
    "evaluate_multi_modal_change",
    "sort_named_patterns",
]

#: Named pattern types.  Neutral observation readings only.
NAMED_RAPID_DECLINE = "RAPID_CANOPY_SIGNAL_DECLINE"
NAMED_MOISTURE_DIVERGENCE = "MOISTURE_GREENNESS_DIVERGENCE"
NAMED_RED_EDGE_DECLINE = "RED_EDGE_DECLINE_PATTERN"
NAMED_RADAR_DEVIATION = "SUSTAINED_RADAR_DEVIATION"
NAMED_MULTI_MODAL = "MULTI_MODAL_CANOPY_CHANGE"
NAMED_PATTERN_TYPES: Tuple[str, ...] = (
    NAMED_RAPID_DECLINE,
    NAMED_MOISTURE_DIVERGENCE,
    NAMED_RED_EDGE_DECLINE,
    NAMED_RADAR_DEVIATION,
    NAMED_MULTI_MODAL,
)

#: Deterministic emission order for coexisting named patterns:
#: the specification listing order.
NAMED_PATTERN_ORDER: Tuple[str, ...] = NAMED_PATTERN_TYPES

#: Combined deterministic order: generic P3.1 patterns first,
#: then named patterns in specification order.
FULL_PATTERN_ORDER: Tuple[str, ...] = PATTERN_ORDER + NAMED_PATTERN_ORDER

#: Optical metrics eligible for the rapid-decline reading: NDVI,
#: with NDRE where available.
RAPID_DECLINE_METRICS: Tuple[str, ...] = ("ndvi", "ndre")

#: Required moisture key for the divergence reading.  The joint
#: layer enforces this itself; restated here so misuse fails
#: fast with a clear message instead of a silent misreading.
DIVERGENCE_MOISTURE_KEY = "ndmi"
DIVERGENCE_NDVI_KEY = "ndvi"

_NOT_ESTABLISHED_SUFFIX = (
    " This describes an observed evidence pattern and does not "
    "identify its cause."
)


# --------------------------------------------------------------------------
# Named rule registry (additive to the P3.1 registry, same shape)
# --------------------------------------------------------------------------


NAMED_RULES: Tuple[PatternRule, ...] = (
    PatternRule(
        rule_id="P32_RAPID_CANOPY_DECLINE_V1",
        rule_version=ENGINE_VERSION,
        name="Rapid canopy signal decline",
        pattern_type=NAMED_RAPID_DECLINE,
        requires=("month_change.rapid=RAPID_DECREASE", "metric in (ndvi, ndre)",),
        predicate=(
            "An NDVI (or NDRE where available) month change carries "
            "the existing P1.3 RAPID_DECREASE label with usable "
            "source quality; windows, magnitudes, and rates are the "
            "change record's own."
        ),
        limitations=(
            "A rapid NDVI/NDRE decline can result from phenology, "
            "water stress, heat, management, atmospheric or "
            "processing effects, or other causes.",
        ),
    ),
    PatternRule(
        rule_id="P32_MOISTURE_DIVERGENCE_V1",
        rule_version=ENGINE_VERSION,
        name="Moisture greenness divergence",
        pattern_type=NAMED_MOISTURE_DIVERGENCE,
        requires=("joint_change.divergence=MOISTURE_DOWN_NDVI_STABLE",),
        predicate=(
            "A P1.4 joint month carries the existing "
            "MOISTURE_DOWN_NDVI_STABLE divergence descriptor with "
            "usable moisture and greenness quality; lag results, "
            "where present, are exposed descriptively with no lag "
            "preferred."
        ),
        limitations=(
            "A temporal moisture/greenness divergence is "
            "descriptive and does not establish causal order or a "
            "biological cause.",
        ),
    ),
    PatternRule(
        rule_id="P32_RED_EDGE_DECLINE_V1",
        rule_version=ENGINE_VERSION,
        name="Red-edge decline pattern",
        pattern_type=NAMED_RED_EDGE_DECLINE,
        requires=("red_edge_change.direction=DECREASE",),
        predicate=(
            "One month holds one or more P2.2 red-edge diagnostics "
            "with an existing valid DECREASE direction and usable "
            "source quality; every declining diagnostic is "
            "preserved individually with no magnitude cut-off."
        ),
        limitations=(
            "Red-edge changes may reflect chlorophyll, canopy "
            "structure, phenology, water status, soil/background, "
            "management, atmosphere, or biological stress.",
        ),
    ),
    PatternRule(
        rule_id="P32_RADAR_DEVIATION_V1",
        rule_version=ENGINE_VERSION,
        name="Sustained radar deviation",
        pattern_type=NAMED_RADAR_DEVIATION,
        requires=("radar persistence=PERSISTENT",),
        predicate=(
            "A P2.4 radar analysis reports a valid PERSISTENT "
            "deviation for one radar metric; baseline, run "
            "lengths, span, and z-score information are the "
            "analysis record's own with no radar-specific cut-off."
        ),
        limitations=(
            "Radar deviation may reflect vegetation structure, "
            "soil moisture, roughness, geometry, incidence angle, "
            "acquisition conditions, and processing.",
        ),
    ),
    PatternRule(
        rule_id="P32_MULTI_MODAL_V1",
        rule_version=ENGINE_VERSION,
        name="Multi-modal canopy change",
        pattern_type=NAMED_MULTI_MODAL,
        requires=("concordance_month=MULTI_SENSOR_CONCORDANT",),
        predicate=(
            "P2.5 already classified the exact month "
            "MULTI_SENSOR_CONCORDANT; same-month P3.1 rapid or "
            "persistent evidence may be attached as additional "
            "contributors without recomputing anything. S2 and S1 "
            "each count once."
        ),
        limitations=(
            "Cross-sensor agreement is evidence of compatible "
            "observed change, not proof of a common biological "
            "cause.",
        ),
    ),
)


def get_named_rule(rule_id: str) -> PatternRule:
    """Look up a named rule, with an actionable error if absent."""
    for rule in NAMED_RULES:
        if rule.rule_id == rule_id:
            return rule
    available = ", ".join(rule.rule_id for rule in NAMED_RULES)
    raise KeyError(
        f"Named pattern rule {rule_id!r} is not registered. "
        f"Available rules: {available}"
    )


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _source_usable(quality: Any) -> bool:
    """Usable unless explicitly unavailable, insufficient, or empty."""
    if not isinstance(quality, str):
        return False
    return quality.strip().lower() not in ("unavailable", "insufficient", "")


def _build_pattern(
    rule: PatternRule,
    pattern_type: str,
    window_start: str,
    window_end: str,
    items: Sequence[PatternEvidence],
    explanation: str,
    pattern_id: str,
    extra_provenance: Optional[Mapping[str, Any]] = None,
) -> EvidencePattern:
    metrics = tuple(sorted({item.metric_id for item in items}))
    sensors = tuple(sorted({item.sensor for item in items}))
    states: Dict[str, str] = {}
    quality: Dict[str, str] = {}
    coverage: Dict[str, Optional[float]] = {}
    provenance: Dict[str, Dict[str, Any]] = {}
    for item in items:
        states[item.evidence_id] = (
            item.anomaly_state or item.change_direction or item.rapid or ""
        )
        quality[item.evidence_id] = item.quality
        coverage[item.evidence_id] = item.coverage_percent
        merged = dict(item.provenance)
        if extra_provenance:
            merged.update(extra_provenance)
        provenance[item.evidence_id] = merged
    return EvidencePattern(
        pattern_id=pattern_id,
        pattern_type=pattern_type,
        window_start=window_start,
        window_end=window_end,
        status="OBSERVED",
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


def sort_named_patterns(
    patterns: Sequence[EvidencePattern],
) -> Tuple[EvidencePattern, ...]:
    """Deterministic emission order: P3.1 generic first, then named."""
    order = {name: index for index, name in enumerate(FULL_PATTERN_ORDER)}
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


# --------------------------------------------------------------------------
# Named pattern evaluators (pure, deterministic)
# --------------------------------------------------------------------------


def evaluate_rapid_canopy_decline(
    metric_id: str,
    changes: Sequence[MonthChange],
    provenance_by_window: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Tuple[EvidencePattern, ...]:
    """Describe rapid declines in NDVI (or NDRE where available).

    Emits one pattern per month change carrying the existing P1.3
    RAPID_DECREASE label with usable source quality.  Windows,
    magnitudes, rates, and the rapid label itself are the change
    record's own; no magnitude cut-off is introduced.
    """
    if metric_id not in RAPID_DECLINE_METRICS:
        raise ValueError(
            f"Rapid canopy decline supports {list(RAPID_DECLINE_METRICS)}; "
            f"got {metric_id!r}."
        )
    rule = get_named_rule("P32_RAPID_CANOPY_DECLINE_V1")
    provenance_by_window = provenance_by_window or {}
    patterns: List[EvidencePattern] = []
    for change in changes:
        if change.rapid != RAPID_DECREASE:
            continue
        if not _source_usable(change.quality):
            continue
        evidence_id = f"{metric_id}:{change.window_start}:rapid-decline"
        item = PatternEvidence(
            evidence_id=evidence_id,
            source_module="change_profile",
            metric_id=metric_id,
            sensor="S2",
            family="optical",
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
            provenance={
                "change": change.to_dict(),
                **dict(provenance_by_window.get(change.window_start, {})),
            },
            limitations=(),
        )
        parts = [f"{metric_id} showed a rapid decrease under the existing"]
        parts.append("P1.3 rapid-change rule for "
                     f"{change.window_start} to {change.window_end}")
        if change.absolute_change is not None:
            parts.append(f"(absolute {change.absolute_change:.4f}")
            if change.relative_change is not None:
                parts.append(f", relative {change.relative_change:.4f}")
            if change.rate_per_day is not None:
                parts.append(f", rate {change.rate_per_day:.6f}/day")
            parts.append(")")
        explanation = "".join(parts) + "." + _NOT_ESTABLISHED_SUFFIX
        patterns.append(
            _build_pattern(
                rule,
                NAMED_RAPID_DECLINE,
                change.window_start,
                change.window_end,
                (item,),
                explanation,
                f"{rule.rule_id}:{metric_id}:{change.window_start}",
            )
        )
    return tuple(patterns)


def evaluate_moisture_greenness_divergence(
    joint: JointAnalysis,
) -> Tuple[EvidencePattern, ...]:
    """Describe months where moisture declines while NDVI does not.

    Emits one pattern per joint month carrying the existing P1.4
    MOISTURE_DOWN_NDVI_STABLE divergence descriptor with usable
    moisture and greenness quality.  The moisture side must be
    NDMI; anything else — including true NDWI — is refused
    rather than renamed.  Lag results travel descriptively in
    provenance and explanation with no lag preferred and no
    causal order claimed.
    """
    if joint.ndvi_key != DIVERGENCE_NDVI_KEY:
        raise ValueError(
            f"Moisture divergence requires {DIVERGENCE_NDVI_KEY!r} "
            f"greenness; got {joint.ndvi_key!r}."
        )
    if joint.moisture_key != DIVERGENCE_MOISTURE_KEY:
        raise ValueError(
            f"Moisture divergence requires {DIVERGENCE_MOISTURE_KEY!r} "
            f"vegetation moisture; got {joint.moisture_key!r}. True "
            "NDWI is an open-water index and is never substituted here."
        )
    rule = get_named_rule("P32_MOISTURE_DIVERGENCE_V1")
    quality_by_month = {
        point.window_start: (point.ndvi_quality, point.moisture_quality)
        for point in joint.joint.points
    }
    lag_lines = ", ".join(
        f"lag {lag.lag_months}m (n={lag.n_paired}, "
        f"agreement={lag.agreement}, sufficient={lag.sufficient})"
        for lag in joint.lags
    )
    lag_provenance: Dict[str, Any] = {
        "lags": [lag.to_dict() for lag in joint.lags],
    }
    patterns: List[EvidencePattern] = []
    for change in joint.changes:
        if change.divergence != DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE:
            continue
        qualities = quality_by_month.get(change.window_start, ())
        if not qualities or not all(
            _source_usable(quality) for quality in qualities
        ):
            continue
        evidence_id = f"ndmi:{change.window_start}:moisture-divergence"
        item = PatternEvidence(
            evidence_id=evidence_id,
            source_module="joint_profile",
            metric_id="ndmi",
            sensor="S2",
            family="optical",
            window_start=change.window_start,
            window_end=change.window_end,
            value=change.moisture_change,
            unit="index",
            anomaly_state=None,
            change_direction="DECREASE",
            rapid=None,
            quality="/".join(qualities),
            coverage_percent=None,
            image_count=None,
            provenance={
                "joint_change": change.to_dict(),
                "ndvi_key": joint.ndvi_key,
                "moisture_key": joint.moisture_key,
                **lag_provenance,
            },
            limitations=(),
        )
        explanation = (
            f"Moisture ({joint.moisture_key}) declined while NDVI did "
            f"not decline in {change.window_start} to {change.window_end} "
            f"under the existing P1.4 "
            f"{DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE} descriptor."
        )
        if lag_lines:
            explanation += (
                f" Descriptive lag information already available: "
                f"{lag_lines}; no lag is preferred and no causal order "
                "is claimed."
            )
        explanation += _NOT_ESTABLISHED_SUFFIX
        patterns.append(
            _build_pattern(
                rule,
                NAMED_MOISTURE_DIVERGENCE,
                change.window_start,
                change.window_end,
                (item,),
                explanation,
                f"{rule.rule_id}:{change.window_start}",
            )
        )
    return tuple(patterns)


def evaluate_red_edge_decline(
    items: Sequence[PatternEvidence],
) -> Tuple[EvidencePattern, ...]:
    """Describe months where red-edge diagnostics decline.

    Groups declining P2.2 diagnostics by exact month into one
    pattern per month, preserving every contributing diagnostic
    individually.  The diagnostic count is reported, never scored,
    and no magnitude cut-off is introduced.
    """
    rule = get_named_rule("P32_RED_EDGE_DECLINE_V1")
    by_month: Dict[Tuple[str, str], List[PatternEvidence]] = {}
    for item in items:
        if item.family != "red_edge" or item.sensor != "S2":
            continue
        if item.change_direction != "DECREASE":
            continue
        if not _source_usable(item.quality):
            continue
        by_month.setdefault(
            (item.window_start, item.window_end), []
        ).append(item)
    patterns: List[EvidencePattern] = []
    for (window_start, window_end) in sorted(by_month):
        group = tuple(
            sorted(by_month[(window_start, window_end)], key=lambda i: i.metric_id)
        )
        diagnostic_ids = ", ".join(item.metric_id for item in group)
        explanation = (
            f"Red-edge decline was observed across "
            f"{len(group)} diagnostic(s) ({diagnostic_ids}) in "
            f"{window_start} to {window_end} under existing P2.2 "
            f"DECREASE directions." + _NOT_ESTABLISHED_SUFFIX
        )
        patterns.append(
            _build_pattern(
                rule,
                NAMED_RED_EDGE_DECLINE,
                window_start,
                window_end,
                group,
                explanation,
                f"{rule.rule_id}:{window_start}",
            )
        )
    return tuple(patterns)


def evaluate_sustained_radar_deviation(
    analysis: RadarMetricAnalysis,
) -> Tuple[EvidencePattern, ...]:
    """Describe a persistent deviation in one Sentinel-1 metric.

    Emits a single pattern when the P2.4 analysis reports a valid
    PERSISTENT deviation.  Baseline, run lengths, span, z-score
    information, quality, and provenance are the analysis
    record's own; no radar-specific cut-off is introduced and the
    deviation is never read as biomass loss or damage of any kind.
    """
    rule = get_named_rule("P32_RADAR_DEVIATION_V1")
    if analysis.persistence.state != PERSISTENCE_PERSISTENT:
        return ()
    if analysis.baseline is None:
        return ()
    usable = [
        point
        for point in analysis.anomalies.points
        if point.value is not None and _source_usable(point.quality)
    ]
    if not usable:
        return ()
    below = (
        analysis.persistence.longest_run_below
        >= analysis.persistence.longest_run_above
    )
    leaning = "below-baseline" if below else "above-baseline"
    run_length = (
        analysis.persistence.longest_run_below
        if below
        else analysis.persistence.longest_run_above
    )
    radar_by_window = {
        point.window_start: dict(point.provenance)
        for point in analysis.source.points
    }
    items = tuple(
        PatternEvidence(
            evidence_id=f"{analysis.metric_key}:{point.window_start}:radar-deviation",
            source_module="radar_anomaly",
            metric_id=analysis.metric_key,
            sensor="S1",
            family="radar",
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
            provenance={
                "anomaly_point": point.to_dict(),
                "baseline": analysis.baseline.to_dict(),
                **radar_by_window.get(point.window_start, {}),
            },
            limitations=(),
        )
        for point in usable
    )
    explanation = (
        f"Sustained {leaning} deviation was observed in "
        f"{analysis.metric_key} ({analysis.unit}) across "
        f"{len(usable)} usable monthly observations "
        f"({analysis.window_start} to {analysis.window_end}), with "
        f"a longest {leaning} run of {run_length} consecutive months "
        f"under {rule.rule_id}." + _NOT_ESTABLISHED_SUFFIX
    )
    return (
        _build_pattern(
            rule,
            NAMED_RADAR_DEVIATION,
            analysis.window_start,
            analysis.window_end,
            items,
            explanation,
            f"{rule.rule_id}:{analysis.metric_key}:"
            f"{analysis.window_start}:{analysis.window_end}",
        ),
    )


def evaluate_multi_modal_change(
    month: ConcordanceMonth,
    extra: Sequence[PatternEvidence] = (),
) -> Tuple[EvidencePattern, ...]:
    """Describe compatible cross-sensor change for one exact month.

    Emits one pattern when P2.5 already classified the month
    MULTI_SENSOR_CONCORDANT.  Concordance is restated, never
    recomputed; S2 and S1 each count once.  Same-month P3.1 rapid
    or persistent evidence may be attached as additional
    contributors without recomputing anything.
    """
    if month.state != STATE_CONCORDANT:
        return ()
    rule = get_named_rule("P32_MULTI_MODAL_V1")
    items: List[PatternEvidence] = []
    for family in month.families:
        for item in family.items:
            if not item.is_usable:
                continue
            items.append(
                PatternEvidence(
                    evidence_id=f"{item.metric_id}:{item.window_start}:multi-modal",
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
            )
    attached = [
        item
        for item in extra
        if item.window_start == month.window_start
        and item.window_end == month.window_end
        and _source_usable(item.quality)
    ]
    items.extend(attached)
    if not items:
        return ()
    sensors = sorted({item.sensor for item in items})
    explanation = (
        f"Multiple sensor families reported compatible observed "
        f"directional evidence in {month.window_start} to "
        f"{month.window_end} under the existing P2.5 concordance "
        f"state ({', '.join(sensors)})."
    )
    if attached:
        attached_ids = ", ".join(item.evidence_id for item in attached)
        explanation += (
            f" Same-month evidence attached without recomputation: "
            f"{attached_ids}."
        )
    explanation += (
        " This evidences compatible observed change, not a common "
        "biological cause." + _NOT_ESTABLISHED_SUFFIX
    )
    return (
        _build_pattern(
            rule,
            NAMED_MULTI_MODAL,
            month.window_start,
            month.window_end,
            tuple(items),
            explanation,
            f"{rule.rule_id}:{month.window_start}",
        ),
    )
