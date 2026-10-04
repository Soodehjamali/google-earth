"""Multi-sensor concordance foundation (P2.5).

Deterministic evidence alignment over the same monthly windows:
for each calendar month, existing optical, red-edge, and radar
evidence is grouped by exact window identity and the month is
described as concordant, divergent, mixed, single-sensor, or
insufficient.  This layer aggregates evidence; it never diagnoses,
scores, or models.

Sentinel-2 optical and red-edge observations respond to different
physical properties than Sentinel-1 radar backscatter, and no two
metrics share units or sensitivities.  Agreement between sensor
families is stronger evidence of a shared observed change than a
single sensor alone, but it does not identify the cause:
divergence is equally informative and may indicate different
physical processes, acquisition effects, moisture and structure
interactions, phenology, management, or other factors.
Multi-sensor concordance is evidence aggregation, not biological
diagnosis — even persistent cross-sensor agreement cannot by
itself establish pest or disease presence, and ground truth is
required for any biological attribution or validation.

Reused patterns (nothing re-derived):

* exact calendar-month alignment with no bridging, shifting, or
  filling, following the P1.4 ``align_profiles`` precedent that
  months align only on identical windows;
* categorical state philosophy following the P1.5 concordance
  vocabulary (single / multi / mixed / none / insufficient),
  restated here for the temporal multi-sensor question;
* directional and anomaly states consumed verbatim from their
  source analyses (P1.2 categories, P1.3 directions, P2.2 change
  directions, P2.4 anomaly categories and change directions);
* quality, coverage, and provenance pass-through from the source
  evidence items, as in every earlier phase.

No new statistical formulas exist here.  Orientation mapping
(category to DOWN / UP / NEUTRAL), family aggregation (counting),
and run detection (counting consecutive calendar months) are
deterministic alignment operations, not statistics — and no
correlation or regression is performed (that machinery already
exists in P1.4 and is out of scope for alignment).

Sensor families and independence:

* ``S2`` — Sentinel-2 optical and spectral evidence, reported in
  two descriptive families: ``optical`` (ndvi, ndmi, ndre, msi)
  and ``red_edge`` (P2.2 diagnostics).  Red-edge diagnostics are
  derived from Sentinel-2 and never count as an independent
  sensor: VV + VH + VH/VV never make three sensors, NDVI + NDMI
  + NDRE + MSI never make four, and red-edge plus optical never
  make two.
* ``S1`` — Sentinel-1 radar evidence: ``radar`` (vv, vh, vh_vv,
  rvi).

A family counts as directional evidence only when the underlying
source already exposes a valid state that is neither missing nor
ambiguous.  Raw availability never counts as directional
agreement, and raw numeric sign is never read: orientation comes
exclusively from the source state's documented meaning, with one
explicit polarity entry — MSI, whose increase indicates rising
moisture stress while NDMI's decrease does (documented in the
water metrics: MSI rises with stress where NDMI falls).  Every
other metric uses its face orientation.

Concordance states (deterministic rule ``P25_CONCORDANCE_V1``):

* ``MULTI_SENSOR_CONCORDANT`` — two independent sensor families
  with compatible directional evidence in the same month.
* ``OPTICAL_ONLY`` — usable Sentinel-2 evidence, radar unusable.
* ``RADAR_ONLY`` — usable radar evidence, Sentinel-2 unusable.
* ``DIVERGENT`` — sensor families with explicitly opposing
  directional evidence.
* ``MIXED_EVIDENCE`` — multiple usable families whose
  directional relationship is not cleanly concordant or
  divergent.
* ``INSUFFICIENT_EVIDENCE`` — not enough usable evidence for a
  concordance statement.

Temporal summary counts months per state and reports the longest
consecutive concordant and divergent runs over exact calendar
months; months absent from the input and non-matching months
break runs.  Spatial multi-sensor concordance is future work:
no new grid is created here and the P1.5 cell contract is
untouched.

Non-goals of this phase: cause attribution, biological labels of
any kind, probabilistic or risk scoring, model inference,
correlation or regression, thermal inputs, new datasets,
endpoints, charts, and cache changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.red_edge import RED_EDGE_DIAGNOSTIC_IDS

logger = get_logger(__name__)

__all__ = [
    "FAMILY_OPTICAL",
    "FAMILY_RED_EDGE",
    "FAMILY_RADAR",
    "EVIDENCE_FAMILIES",
    "FAMILY_METRICS",
    "SENSOR_S2",
    "SENSOR_S1",
    "FAMILY_SENSOR",
    "OPTICAL_METRICS",
    "RADAR_METRICS",
    "ORIENTATION_DOWN",
    "ORIENTATION_UP",
    "ORIENTATION_NEUTRAL",
    "ORIENTATION_AMBIGUOUS",
    "ORIENTATION_INSUFFICIENT",
    "STATE_CONCORDANT",
    "STATE_OPTICAL_ONLY",
    "STATE_RADAR_ONLY",
    "STATE_DIVERGENT",
    "STATE_MIXED",
    "STATE_INSUFFICIENT",
    "CONCORDANCE_STATES",
    "CONCORDANCE_RULE_ID",
    "CONCORDANCE_RULE",
    "ConcordanceEvidence",
    "FamilyEvidence",
    "ConcordanceMonth",
    "ConcordanceSummary",
    "ConcordanceSeries",
    "make_evidence",
    "month_orientation",
    "analyze_concordance",
]

#: Descriptive evidence families.  Optical and red-edge are
#: reporting views over one sensor (Sentinel-2); radar is the
#: second sensor (Sentinel-1).
FAMILY_OPTICAL = "optical"
FAMILY_RED_EDGE = "red_edge"
FAMILY_RADAR = "radar"
EVIDENCE_FAMILIES: Tuple[str, ...] = (
    FAMILY_OPTICAL,
    FAMILY_RED_EDGE,
    FAMILY_RADAR,
)

#: Sensors.  Exactly two independent sensors exist in this layer.
SENSOR_S2 = "S2"
SENSOR_S1 = "S1"

#: Family to independent sensor.  Red-edge maps to Sentinel-2: it
#: is derived evidence and never an independent sensor.
FAMILY_SENSOR: Dict[str, str] = {
    FAMILY_OPTICAL: SENSOR_S2,
    FAMILY_RED_EDGE: SENSOR_S2,
    FAMILY_RADAR: SENSOR_S1,
}

#: Metrics contributing to each family.  Optical indices are the
#: P1 vegetation and water signals; red-edge identifiers are the
#: P2.2 diagnostic registry; radar keys are the P2.3 production
#: metrics.
OPTICAL_METRICS: Tuple[str, ...] = ("ndvi", "ndmi", "ndre", "msi")
RADAR_METRICS: Tuple[str, ...] = ("vv", "vh", "vh_vv", "rvi")
FAMILY_METRICS: Dict[str, Tuple[str, ...]] = {
    FAMILY_OPTICAL: OPTICAL_METRICS,
    FAMILY_RED_EDGE: tuple(RED_EDGE_DIAGNOSTIC_IDS),
    FAMILY_RADAR: RADAR_METRICS,
}

#: Orientation vocabulary for one evidence item or family.
ORIENTATION_DOWN = "DOWN"
ORIENTATION_UP = "UP"
ORIENTATION_NEUTRAL = "NEUTRAL"
ORIENTATION_AMBIGUOUS = "AMBIGUOUS"
ORIENTATION_INSUFFICIENT = "INSUFFICIENT"

#: Concordance states.
STATE_CONCORDANT = "MULTI_SENSOR_CONCORDANT"
STATE_OPTICAL_ONLY = "OPTICAL_ONLY"
STATE_RADAR_ONLY = "RADAR_ONLY"
STATE_DIVERGENT = "DIVERGENT"
STATE_MIXED = "MIXED_EVIDENCE"
STATE_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
CONCORDANCE_STATES: Tuple[str, ...] = (
    STATE_CONCORDANT,
    STATE_OPTICAL_ONLY,
    STATE_RADAR_ONLY,
    STATE_DIVERGENT,
    STATE_MIXED,
    STATE_INSUFFICIENT,
)

#: Deterministic rule identifier published on every month.
CONCORDANCE_RULE_ID = "P25_CONCORDANCE_V1"

#: The rule, stated once and referenced by every result.
CONCORDANCE_RULE = (
    "Group evidence by exact (window_start, window_end). Map each "
    "item's source state to DOWN (BELOW_BASELINE, DECREASE), UP "
    "(ABOVE_BASELINE, INCREASE), or NEUTRAL (NORMAL, STABLE); MSI "
    "is polarity-inverted per its documented meaning; unknown or "
    "missing states read INSUFFICIENT and raw values are never "
    "read. A family reads DOWN when it holds DOWN items and no UP "
    "items, UP symmetrically, AMBIGUOUS when it holds both, "
    "NEUTRAL when it holds only NEUTRAL items, else INSUFFICIENT. "
    "A sensor follows its single family, or, for Sentinel-2, the "
    "shared orientation of its optical and red-edge families "
    "(AMBIGUOUS when they disagree). Both sensors usable with "
    "equal DOWN/UP/NEUTRAL orientations reads "
    "MULTI_SENSOR_CONCORDANT; DOWN against UP reads DIVERGENT; "
    "single-sensor usability reads OPTICAL_ONLY or RADAR_ONLY; "
    "one-sided or unclear direction reads MIXED_EVIDENCE; no "
    "directional evidence on either sensor reads "
    "INSUFFICIENT_EVIDENCE."
)

#: (family, metric) pairs whose face orientation is inverted.
#: The single entry is MSI: its increase corresponds to falling
#: canopy water content while the sibling moisture signal NDMI
#: falls on decrease, as documented by the water metrics
#: themselves (MSI rises where NDMI falls).
INVERTED_ORIENTATION: Tuple[Tuple[str, str], ...] = (
    (FAMILY_OPTICAL, "msi"),
)

#: Source anomaly categories and change directions this layer
#: understands, grouped by coarse orientation.
_DOWN_STATES = frozenset({"BELOW_BASELINE", "DECREASE"})
_UP_STATES = frozenset({"ABOVE_BASELINE", "INCREASE"})
_NEUTRAL_STATES = frozenset({"NORMAL", "STABLE"})


# --------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConcordanceEvidence:
    """One metric's evidence for one monthly window.

    ``state_kind`` names the source analysis vocabulary
    (``"anomaly"``, ``"change"``, or ``"observation"``) and
    ``state`` carries its verbatim category or direction, or
    ``None`` when the source exposes no directional state.  A
    missing value (``None``) marks unusable evidence; it is never
    a zero and is never filled.
    """

    family: str
    metric_id: str
    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    state_kind: str = "observation"
    state: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def sensor(self) -> str:
        """The independent sensor behind this evidence item."""
        return FAMILY_SENSOR[self.family]

    @property
    def is_usable(self) -> bool:
        """Whether a finite observed value exists."""
        return _is_usable_number(self.value)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.5 API contract models."""
        return {
            "family": self.family,
            "sensor": self.sensor,
            "metric_id": self.metric_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "state_kind": self.state_kind,
            "state": self.state,
            "orientation": month_orientation(self),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class FamilyEvidence:
    """One family's aligned evidence for one month."""

    family: str
    sensor: str
    orientation: str
    usable_count: int
    directional_count: int
    metric_ids: Tuple[str, ...]
    items: Tuple[ConcordanceEvidence, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.5 API contract models."""
        return {
            "family": self.family,
            "sensor": self.sensor,
            "orientation": self.orientation,
            "usable_count": self.usable_count,
            "directional_count": self.directional_count,
            "metric_ids": list(self.metric_ids),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class ConcordanceMonth:
    """The concordance statement for one exact monthly window."""

    window_start: str
    window_end: str
    state: str
    rule_id: str
    reasons: Tuple[str, ...]
    families: Tuple[FamilyEvidence, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.5 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "state": self.state,
            "rule_id": self.rule_id,
            "rule": CONCORDANCE_RULE,
            "reasons": list(self.reasons),
            "families": [family.to_dict() for family in self.families],
        }


@dataclass(frozen=True)
class ConcordanceSummary:
    """Deterministic counts and runs over a concordance series."""

    n_months: int
    n_concordant: int
    n_divergent: int
    n_mixed: int
    n_optical_only: int
    n_radar_only: int
    n_insufficient: int
    concordant_months: Tuple[str, ...]
    divergent_months: Tuple[str, ...]
    longest_concordant_run: int
    longest_concordant_run_start: Optional[str]
    longest_concordant_run_end: Optional[str]
    longest_divergent_run: int
    longest_divergent_run_start: Optional[str]
    longest_divergent_run_end: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.5 API contract models."""
        return {
            "n_months": self.n_months,
            "n_concordant": self.n_concordant,
            "n_divergent": self.n_divergent,
            "n_mixed": self.n_mixed,
            "n_optical_only": self.n_optical_only,
            "n_radar_only": self.n_radar_only,
            "n_insufficient": self.n_insufficient,
            "concordant_months": list(self.concordant_months),
            "divergent_months": list(self.divergent_months),
            "longest_concordant_run": self.longest_concordant_run,
            "longest_concordant_run_start": self.longest_concordant_run_start,
            "longest_concordant_run_end": self.longest_concordant_run_end,
            "longest_divergent_run": self.longest_divergent_run,
            "longest_divergent_run_start": self.longest_divergent_run_start,
            "longest_divergent_run_end": self.longest_divergent_run_end,
        }


@dataclass(frozen=True)
class ConcordanceSeries:
    """Monthly concordance statements with a temporal summary."""

    window_start: Optional[str]
    window_end: Optional[str]
    months: Tuple[ConcordanceMonth, ...] = field(default_factory=tuple)
    summary: ConcordanceSummary | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.5 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "rule_id": CONCORDANCE_RULE_ID,
            "rule": CONCORDANCE_RULE,
            "months": [month.to_dict() for month in self.months],
            "summary": self.summary.to_dict() if self.summary else None,
            "methods": dict(_SERIES_METHODS),
            "limitations": list(_SERIES_LIMITATIONS),
        }


_SERIES_METHODS: Dict[str, str] = {
    "alignment": (
        "Exact (window_start, window_end) identity across families; "
        "no bridging, shifting, interpolation, or deletion "
        "(P1.4 alignment precedent)."
    ),
    "orientation": (
        "Source anomaly categories and change directions mapped to "
        "DOWN/UP/NEUTRAL per documented meaning; MSI inverted; raw "
        "values never read."
    ),
    "concordance": (
        "Deterministic rule P25_CONCORDANCE_V1 over two "
        "independent sensors (Sentinel-2 optical/spectral, "
        "Sentinel-1 radar)."
    ),
    "runs": (
        "Consecutive exact-calendar-month runs per state; absent "
        "months and non-matching months break runs."
    ),
}

_SERIES_LIMITATIONS: Tuple[str, ...] = (
    "Concordance aggregates directional evidence; it does not "
    "identify a cause and cannot establish pest or disease presence.",
    "Even persistent cross-sensor agreement cannot by itself "
    "establish pest or disease presence.",
    "Optical and radar respond to different physical properties; "
    "agreement evidences a shared observed change, divergence may "
    "reflect different processes, acquisition effects, moisture or "
    "structure interactions, phenology, or management.",
    "Red-edge diagnostics are derived Sentinel-2 evidence and do "
    "not form an independent sensor.",
    "Biological attribution requires multi-sensor evidence and "
    "ground-truth validation.",
)


# --------------------------------------------------------------------------
# Pure computation (no Earth Engine)
# --------------------------------------------------------------------------


def _is_usable_number(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _clean_coverage(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def make_evidence(
    family: str,
    metric_id: str,
    window_start: str,
    window_end: str,
    value: Optional[float],
    unit: str = "",
    quality: str = "unavailable",
    coverage_percent: Optional[float] = None,
    image_count: Optional[int] = None,
    state_kind: str = "observation",
    state: Optional[str] = None,
    provenance: Optional[Mapping[str, Any]] = None,
) -> ConcordanceEvidence:
    """Build one validated evidence item.

    Raises:
        ValueError: for an unknown family, a metric outside its
            family's registry, or an unknown state kind.  Unknown
            sources are refused, never silently absorbed.
    """
    if family not in FAMILY_METRICS:
        raise ValueError(
            f"Unknown evidence family {family!r}. "
            f"Expected one of {list(FAMILY_METRICS)}."
        )
    if metric_id not in FAMILY_METRICS[family]:
        raise ValueError(
            f"Metric {metric_id!r} is not registered for family "
            f"{family!r}. Family metrics: "
            f"{list(FAMILY_METRICS[family])}."
        )
    if state_kind not in ("anomaly", "change", "observation"):
        raise ValueError(
            f"Unknown state kind {state_kind!r}. Expected 'anomaly', "
            "'change', or 'observation'."
        )
    return ConcordanceEvidence(
        family=family,
        metric_id=metric_id,
        window_start=window_start,
        window_end=window_end,
        value=float(value) if _is_usable_number(value) else None,
        unit=unit,
        quality=quality,
        coverage_percent=_clean_coverage(coverage_percent),
        image_count=image_count,
        state_kind=state_kind,
        state=state,
        provenance=dict(provenance) if provenance else {},
    )


def month_orientation(item: ConcordanceEvidence) -> str:
    """Coarse orientation of one evidence item from its source state.

    DOWN for BELOW_BASELINE/DECREASE, UP for ABOVE_BASELINE/
    INCREASE, NEUTRAL for NORMAL/STABLE, INSUFFICIENT for missing,
    unknown, or non-directional states.  The raw value is never
    consulted: a high reflectance with a BELOW state still reads
    DOWN, because the source analysis owns the meaning.
    """
    if not item.is_usable or item.state is None:
        return ORIENTATION_INSUFFICIENT
    name = str(item.state).strip().upper()
    if name in _DOWN_STATES:
        coarse = ORIENTATION_DOWN
    elif name in _UP_STATES:
        coarse = ORIENTATION_UP
    elif name in _NEUTRAL_STATES:
        return ORIENTATION_NEUTRAL
    else:
        return ORIENTATION_INSUFFICIENT
    if (item.family, item.metric_id) in INVERTED_ORIENTATION:
        return (
            ORIENTATION_UP
            if coarse == ORIENTATION_DOWN
            else ORIENTATION_DOWN
        )
    return coarse


def _family_evidence(
    family: str, items: Sequence[ConcordanceEvidence]
) -> FamilyEvidence:
    usable = [item for item in items if item.is_usable]
    orientations = [month_orientation(item) for item in usable]
    downs = sum(1 for o in orientations if o == ORIENTATION_DOWN)
    ups = sum(1 for o in orientations if o == ORIENTATION_UP)
    neutrals = sum(1 for o in orientations if o == ORIENTATION_NEUTRAL)
    directional = downs + ups + neutrals
    if downs and ups:
        orientation = ORIENTATION_AMBIGUOUS
    elif downs:
        orientation = ORIENTATION_DOWN
    elif ups:
        orientation = ORIENTATION_UP
    elif neutrals:
        orientation = ORIENTATION_NEUTRAL
    else:
        orientation = ORIENTATION_INSUFFICIENT
    ordered = tuple(
        sorted({item.metric_id for item in usable})
    )
    return FamilyEvidence(
        family=family,
        sensor=FAMILY_SENSOR[family],
        orientation=orientation,
        usable_count=len(usable),
        directional_count=directional,
        metric_ids=ordered,
        items=tuple(items),
    )


def _sensor_orientation(
    families: Mapping[str, FamilyEvidence], sensor: str
) -> str:
    member = [
        evidence.orientation
        for evidence in families.values()
        if evidence.sensor == sensor
        and evidence.orientation
        in (ORIENTATION_DOWN, ORIENTATION_UP, ORIENTATION_NEUTRAL)
    ]
    if not member:
        member_families = [
            evidence
            for evidence in families.values()
            if evidence.sensor == sensor
        ]
        if any(
            evidence.orientation == ORIENTATION_AMBIGUOUS
            for evidence in member_families
        ):
            return ORIENTATION_AMBIGUOUS
        return ORIENTATION_INSUFFICIENT
    if len(set(member)) > 1:
        return ORIENTATION_AMBIGUOUS
    return member[0]


def _sensor_usable(
    families: Mapping[str, FamilyEvidence], sensor: str
) -> bool:
    return any(
        evidence.usable_count > 0
        for evidence in families.values()
        if evidence.sensor == sensor
    )


def _describe_item(item: ConcordanceEvidence) -> str:
    state = item.state if item.state is not None else "no state"
    return f"{item.metric_id}({state})"


def analyze_concordance(
    items: Sequence[ConcordanceEvidence],
) -> ConcordanceSeries:
    """Align evidence by exact month and state each month's concordance.

    Input order is irrelevant: months are grouped by exact
    ``(window_start, window_end)`` identity and emitted in
    chronological order.  Windows never merge, shift, or fill.
    """
    windows: Dict[Tuple[str, str], List[ConcordanceEvidence]] = {}
    for item in items:
        windows.setdefault(
            (item.window_start, item.window_end), []
        ).append(item)

    months: List[ConcordanceMonth] = []
    for window_start, window_end in sorted(windows):
        bucket = windows[(window_start, window_end)]
        by_family: Dict[str, List[ConcordanceEvidence]] = {
            family: [] for family in EVIDENCE_FAMILIES
        }
        for item in bucket:
            by_family[item.family].append(item)
        families = {
            family: _family_evidence(family, by_family[family])
            for family in EVIDENCE_FAMILIES
        }
        state, reasons = _classify_month(families)
        months.append(
            ConcordanceMonth(
                window_start=window_start,
                window_end=window_end,
                state=state,
                rule_id=CONCORDANCE_RULE_ID,
                reasons=tuple(reasons),
                families=tuple(
                    families[family] for family in EVIDENCE_FAMILIES
                ),
            )
        )

    series = ConcordanceSeries(
        window_start=months[0].window_start if months else None,
        window_end=months[-1].window_end if months else None,
        months=tuple(months),
    )
    summary = _summarize_months(series.months)
    return ConcordanceSeries(
        window_start=series.window_start,
        window_end=series.window_end,
        months=series.months,
        summary=summary,
    )


def _classify_month(
    families: Mapping[str, FamilyEvidence],
) -> Tuple[str, List[str]]:
    """Apply rule P25_CONCORDANCE_V1 to one month's families."""
    reasons: List[str] = []
    for family in EVIDENCE_FAMILIES:
        evidence = families[family]
        if evidence.usable_count:
            members = ", ".join(
                _describe_item(item)
                for item in evidence.items
                if item.is_usable
            )
            reasons.append(
                f"{family} ({evidence.sensor}): "
                f"{evidence.usable_count} usable [{members}] -> "
                f"{evidence.orientation}"
            )
        else:
            reasons.append(f"{family}: no usable evidence")

    s2_usable = _sensor_usable(families, SENSOR_S2)
    s1_usable = _sensor_usable(families, SENSOR_S1)
    if not s2_usable and not s1_usable:
        reasons.append("no usable evidence in any family")
        return STATE_INSUFFICIENT, reasons
    if s2_usable and not s1_usable:
        reasons.append("usable Sentinel-2 evidence only")
        return STATE_OPTICAL_ONLY, reasons
    if s1_usable and not s2_usable:
        reasons.append("usable radar evidence only")
        return STATE_RADAR_ONLY, reasons

    s2_orientation = _sensor_orientation(families, SENSOR_S2)
    s1_orientation = _sensor_orientation(families, SENSOR_S1)
    reasons.append(
        f"sensor orientations: S2={s2_orientation}, S1={s1_orientation}"
    )
    directional = {
        ORIENTATION_DOWN,
        ORIENTATION_UP,
        ORIENTATION_NEUTRAL,
    }
    if s2_orientation in directional and s1_orientation in directional:
        if s2_orientation == s1_orientation:
            reasons.append(
                "two independent sensors share "
                f"{s2_orientation} orientation"
            )
            return STATE_CONCORDANT, reasons
        if {s2_orientation, s1_orientation} == {
            ORIENTATION_DOWN,
            ORIENTATION_UP,
        }:
            reasons.append("sensors oppose DOWN against UP")
            return STATE_DIVERGENT, reasons
        reasons.append("orientations neither equal nor opposing")
        return STATE_MIXED, reasons
    if (
        s2_orientation == ORIENTATION_INSUFFICIENT
        and s1_orientation == ORIENTATION_INSUFFICIENT
    ):
        reasons.append("no directional evidence on either sensor")
        return STATE_INSUFFICIENT, reasons
    reasons.append("directional evidence on fewer than two sensors")
    return STATE_MIXED, reasons


def _months_between_starts(first: str, second: str) -> Optional[int]:
    try:
        earlier = date.fromisoformat(first)
        later = date.fromisoformat(second)
    except (ValueError, TypeError):
        return None
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _longest_run(
    months: Sequence[ConcordanceMonth], state: str
) -> Tuple[int, Optional[str], Optional[str]]:
    best = 0
    best_start: Optional[str] = None
    best_end: Optional[str] = None
    length = 0
    run_start: Optional[str] = None
    previous_start: Optional[str] = None
    for month in months:
        consecutive = (
            previous_start is not None
            and _months_between_starts(previous_start, month.window_start)
            == 1
        )
        if month.state == state and (length == 0 or consecutive):
            if length == 0:
                run_start = month.window_start
            length += 1
        else:
            if month.state == state and not consecutive:
                run_start = month.window_start
                length = 1
            else:
                length = 0
                run_start = None
        if length > best:
            best = length
            best_start = run_start
            best_end = month.window_end
        previous_start = month.window_start
    return best, best_start, best_end


def _summarize_months(
    months: Sequence[ConcordanceMonth],
) -> ConcordanceSummary:
    states = [month.state for month in months]
    concordant = tuple(
        month.window_start
        for month in months
        if month.state == STATE_CONCORDANT
    )
    divergent = tuple(
        month.window_start
        for month in months
        if month.state == STATE_DIVERGENT
    )
    run_length, run_start, run_end = _longest_run(months, STATE_CONCORDANT)
    div_length, div_start, div_end = _longest_run(months, STATE_DIVERGENT)
    return ConcordanceSummary(
        n_months=len(months),
        n_concordant=states.count(STATE_CONCORDANT),
        n_divergent=states.count(STATE_DIVERGENT),
        n_mixed=states.count(STATE_MIXED),
        n_optical_only=states.count(STATE_OPTICAL_ONLY),
        n_radar_only=states.count(STATE_RADAR_ONLY),
        n_insufficient=states.count(STATE_INSUFFICIENT),
        concordant_months=concordant,
        divergent_months=divergent,
        longest_concordant_run=run_length,
        longest_concordant_run_start=run_start,
        longest_concordant_run_end=run_end,
        longest_divergent_run=div_length,
        longest_divergent_run_start=div_start,
        longest_divergent_run_end=div_end,
    )
