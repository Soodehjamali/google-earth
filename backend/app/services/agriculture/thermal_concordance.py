"""Thermal context concordance (P4.4).

Descriptive same-month directional alignment between the P4.3
thermal analyses and the existing P2.5 multi-sensor concordance,
through an additive layer that changes nothing it consumes.

Two source roles stay explicitly distinct:

* MODIS LST is a remote-sensing land-surface observation and may
  stand beside Sentinel-2 and Sentinel-1 as observational
  evidence;
* ERA5-Land 2 m air temperature is modelled meteorological
  context and is never counted as an independent satellite
  sensor.

What this layer reports, per exact calendar month, is whether the
observed directions are aligned, divergent, or mixed. It does not
identify a cause, does not establish the presence of any
biological condition, and produces no score, ranking, or
biological pattern of any kind.

Reused machinery (nothing re-derived, no formula restated):

* P2.5 months are consumed verbatim: family orientations, sensor
  identities, usable counts, the monthly state, reasons, and rule
  identifiers are restated, never recomputed;
* P4.3 analyses are consumed verbatim: anomaly categories,
  change directions, quality, coverage, values, units, and
  provenance pass through untouched;
* orientation follows the repository's existing vocabularies
  (``UP`` / ``DOWN`` / ``NEUTRAL`` / ``INSUFFICIENT``) with the
  P4.3 state mapping stated on every result.

Non-goals of this phase: cause attribution, cut-off values of any
kind, sensor or thermal weights, confidence or risk scoring,
model inference, canopy-temperature inference, LST-air
differencing, named biological patterns, P3 rule changes, new
datasets, new computation over raw values, endpoints, charts, and
cache changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.concordance import (
    CONCORDANCE_RULE_ID,
    ORIENTATION_DOWN,
    ORIENTATION_INSUFFICIENT,
    ORIENTATION_NEUTRAL,
    ORIENTATION_UP,
    ConcordanceMonth,
)
from app.services.agriculture.thermal_anomaly import ThermalMetricAnalysis
from app.services.agriculture.thermal_profile import (
    THERMAL_PROFILE_KIND_AIR,
    THERMAL_PROFILE_KIND_LST,
)

logger = get_logger(__name__)

__all__ = [
    "THERMAL_CONCORDANCE_RULE_ID",
    "THERMAL_CONCORDANCE_RULE",
    "SOURCE_ROLE_LST",
    "SOURCE_ROLE_AIR",
    "LST_CONCORDANT",
    "LST_DIVERGENT",
    "LST_MIXED",
    "LST_ONLY",
    "AIR_CONCORDANT",
    "AIR_DIVERGENT",
    "AIR_MIXED",
    "AIR_ONLY",
    "RELATIONSHIP_INSUFFICIENT",
    "ORIENTATION_SOURCE_ANOMALY",
    "ORIENTATION_SOURCE_CHANGE",
    "AGREEMENT_SAME",
    "AGREEMENT_OPPOSITE",
    "AGREEMENT_ONE_INSUFFICIENT",
    "AGREEMENT_BOTH_INSUFFICIENT",
    "AGREEMENT_MIXED",
    "ThermalSideEvidence",
    "ThermalConcordanceMonth",
    "ThermalConcordanceAnalysis",
    "thermal_orientation",
    "side_evidence",
    "analyze_thermal_concordance",
]

#: Deterministic rule identifier published on every month.
THERMAL_CONCORDANCE_RULE_ID = "P44_THERMAL_CONCORDANCE_V1"

#: The rule, stated once and referenced by every result.
THERMAL_CONCORDANCE_RULE = (
    "Group thermal and P2.5 evidence by exact (window_start, "
    "window_end). Map each thermal month to UP (ABOVE_BASELINE, "
    "INCREASE, RAPID_INCREASE), DOWN (BELOW_BASELINE, DECREASE, "
    "RAPID_DECREASE), or NEUTRAL (NORMAL, STABLE); anything else "
    "reads INSUFFICIENT. The anomaly category is used first; when "
    "it carries no direction, the month's change direction is used "
    "and recorded. Compare the thermal orientation with the usable "
    "optical and radar family orientations for the same exact "
    "month: all equal reads concordant, opposing reads divergent, "
    "partly matching or unclear reads mixed evidence, usable "
    "thermal evidence without usable P2.5 evidence reads "
    "thermal-only, and unusable thermal evidence reads insufficient "
    "evidence. ERA5 is meteorological context, never an independent "
    "sensor. Raw values are never read."
)

#: Source roles. ERA5 is context, not an observational sensor.
SOURCE_ROLE_LST = "REMOTE_SENSING_LAND_SURFACE"
SOURCE_ROLE_AIR = "METEOROLOGICAL_CONTEXT"

#: Monthly relationship of MODIS LST to optical/radar evidence.
LST_CONCORDANT = "THERMAL_CONCORDANT"
LST_DIVERGENT = "THERMAL_DIVERGENT"
LST_MIXED = "THERMAL_MIXED_EVIDENCE"
LST_ONLY = "THERMAL_ONLY"

#: Monthly relationship of ERA5 context to optical/radar evidence.
AIR_CONCORDANT = "THERMAL_CONTEXT_CONCORDANT"
AIR_DIVERGENT = "THERMAL_CONTEXT_DIVERGENT"
AIR_MIXED = "THERMAL_CONTEXT_MIXED_EVIDENCE"
AIR_ONLY = "THERMAL_CONTEXT_ONLY"

#: Shared insufficient-evidence state (the P2.5 meaning, restated).
RELATIONSHIP_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

#: Which P4.3 state supplied a month's orientation.
ORIENTATION_SOURCE_ANOMALY = "anomaly"
ORIENTATION_SOURCE_CHANGE = "change"

#: Same-month LST/ERA5 directional agreement (orientations only).
AGREEMENT_SAME = "SAME_DIRECTION"
AGREEMENT_OPPOSITE = "OPPOSITE_DIRECTION"
AGREEMENT_ONE_INSUFFICIENT = "ONE_INSUFFICIENT"
AGREEMENT_BOTH_INSUFFICIENT = "BOTH_INSUFFICIENT"
AGREEMENT_MIXED = "MIXED_ORIENTATION"

#: P4.3 anomaly categories mapped to UP.
_UP_ANOMALY_STATES = frozenset({"ABOVE_BASELINE"})
#: P4.3 anomaly categories mapped to DOWN.
_DOWN_ANOMALY_STATES = frozenset({"BELOW_BASELINE"})
#: P4.3 anomaly categories mapped to NEUTRAL.
_NEUTRAL_ANOMALY_STATES = frozenset({"NORMAL"})
#: P4.3 change directions mapped to UP (rapid flags share the sign).
_UP_CHANGE_STATES = frozenset({"INCREASE", "RAPID_INCREASE"})
#: P4.3 change directions mapped to DOWN.
_DOWN_CHANGE_STATES = frozenset({"DECREASE", "RAPID_DECREASE"})
#: P4.3 change directions mapped to NEUTRAL.
_NEUTRAL_CHANGE_STATES = frozenset({"STABLE"})

#: External orientations that count as directional evidence.
_DIRECTIONAL_ORIENTATIONS = frozenset(
    {ORIENTATION_DOWN, ORIENTATION_UP, ORIENTATION_NEUTRAL}
)


@dataclass(frozen=True)
class ThermalSideEvidence:
    """One thermal quantity's oriented evidence for one month.

    ``orientation`` follows the repository orientation vocabulary;
    ``orientation_source`` records whether the P4.3 anomaly
    category or the P4.3 change direction supplied it, and
    ``source_state`` carries that verbatim state. Everything else
    passes through untouched from the P4.3 analysis.
    """

    window_start: str
    window_end: str
    profile_kind: str
    physical_quantity: str
    source_role: str
    metric_id: str
    dataset_id: Optional[str]
    band: str
    orientation: str = ORIENTATION_INSUFFICIENT
    orientation_source: str = ORIENTATION_SOURCE_ANOMALY
    source_state: Optional[str] = None
    source_state_kind: str = "anomaly"
    value: Optional[float] = None
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "profile_kind": self.profile_kind,
            "physical_quantity": self.physical_quantity,
            "source_role": self.source_role,
            "metric_id": self.metric_id,
            "dataset_id": self.dataset_id,
            "band": self.band,
            "orientation": self.orientation,
            "orientation_source": self.orientation_source,
            "source_state": self.source_state,
            "source_state_kind": self.source_state_kind,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalSideEvidence":
        """Rebuild side evidence from :meth:`to_dict` output."""
        return cls(
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            profile_kind=payload.get("profile_kind", ""),
            physical_quantity=payload.get("physical_quantity", ""),
            source_role=payload.get("source_role", ""),
            metric_id=payload.get("metric_id", ""),
            dataset_id=payload.get("dataset_id"),
            band=payload.get("band", ""),
            orientation=payload.get(
                "orientation", ORIENTATION_INSUFFICIENT
            ),
            orientation_source=payload.get(
                "orientation_source", ORIENTATION_SOURCE_ANOMALY
            ),
            source_state=payload.get("source_state"),
            source_state_kind=payload.get("source_state_kind", "anomaly"),
            value=payload.get("value"),
            unit=payload.get("unit", ""),
            quality=payload.get("quality", "unavailable"),
            coverage_percent=payload.get("coverage_percent"),
            image_count=payload.get("image_count"),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class ThermalConcordanceMonth:
    """The thermal-context statement for one exact monthly window."""

    window_start: str
    window_end: str
    rule_id: str
    lst: Optional[ThermalSideEvidence] = None
    air: Optional[ThermalSideEvidence] = None
    p25_state: Optional[str] = None
    p25_rule_id: Optional[str] = None
    optical_orientation: Optional[str] = None
    red_edge_orientation: Optional[str] = None
    radar_orientation: Optional[str] = None
    lst_relationship: str = RELATIONSHIP_INSUFFICIENT
    air_relationship: str = RELATIONSHIP_INSUFFICIENT
    lst_era5_agreement: Optional[str] = None
    observational_sensor_count: int = 0
    meteorological_context_present: bool = False
    explanations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "rule_id": self.rule_id,
            "rule": THERMAL_CONCORDANCE_RULE,
            "lst": self.lst.to_dict() if self.lst is not None else None,
            "air": self.air.to_dict() if self.air is not None else None,
            "p25_state": self.p25_state,
            "p25_rule_id": self.p25_rule_id,
            "optical_orientation": self.optical_orientation,
            "red_edge_orientation": self.red_edge_orientation,
            "radar_orientation": self.radar_orientation,
            "lst_relationship": self.lst_relationship,
            "air_relationship": self.air_relationship,
            "lst_era5_agreement": self.lst_era5_agreement,
            "observational_sensor_count": self.observational_sensor_count,
            "meteorological_context_present": (
                self.meteorological_context_present
            ),
            "explanations": list(self.explanations),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalConcordanceMonth":
        """Rebuild a month from :meth:`to_dict` output."""
        lst_payload = payload.get("lst")
        air_payload = payload.get("air")
        return cls(
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            rule_id=payload.get("rule_id", THERMAL_CONCORDANCE_RULE_ID),
            lst=(
                ThermalSideEvidence.from_dict(lst_payload)
                if lst_payload is not None
                else None
            ),
            air=(
                ThermalSideEvidence.from_dict(air_payload)
                if air_payload is not None
                else None
            ),
            p25_state=payload.get("p25_state"),
            p25_rule_id=payload.get("p25_rule_id"),
            optical_orientation=payload.get("optical_orientation"),
            red_edge_orientation=payload.get("red_edge_orientation"),
            radar_orientation=payload.get("radar_orientation"),
            lst_relationship=payload.get(
                "lst_relationship", RELATIONSHIP_INSUFFICIENT
            ),
            air_relationship=payload.get(
                "air_relationship", RELATIONSHIP_INSUFFICIENT
            ),
            lst_era5_agreement=payload.get("lst_era5_agreement"),
            observational_sensor_count=payload.get(
                "observational_sensor_count", 0
            ),
            meteorological_context_present=payload.get(
                "meteorological_context_present", False
            ),
            explanations=tuple(payload.get("explanations") or ()),
        )


@dataclass(frozen=True)
class ThermalConcordanceAnalysis:
    """Monthly thermal-context statements with a temporal summary."""

    window_start: Optional[str]
    window_end: Optional[str]
    rule_id: str = THERMAL_CONCORDANCE_RULE_ID
    months: Tuple[ThermalConcordanceMonth, ...] = field(
        default_factory=tuple
    )
    n_months: int = 0
    n_lst_concordant: int = 0
    n_lst_divergent: int = 0
    n_lst_mixed: int = 0
    n_lst_only: int = 0
    n_air_concordant: int = 0
    n_air_divergent: int = 0
    n_air_mixed: int = 0
    n_air_only: int = 0
    n_insufficient: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "rule_id": self.rule_id,
            "rule": THERMAL_CONCORDANCE_RULE,
            "months": [month.to_dict() for month in self.months],
            "summary": {
                "n_months": self.n_months,
                "n_lst_concordant": self.n_lst_concordant,
                "n_lst_divergent": self.n_lst_divergent,
                "n_lst_mixed": self.n_lst_mixed,
                "n_lst_only": self.n_lst_only,
                "n_air_concordant": self.n_air_concordant,
                "n_air_divergent": self.n_air_divergent,
                "n_air_mixed": self.n_air_mixed,
                "n_air_only": self.n_air_only,
                "n_insufficient": self.n_insufficient,
            },
            "methods": dict(_ANALYSIS_METHODS),
            "limitations": list(_ANALYSIS_LIMITATIONS),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalConcordanceAnalysis":
        """Rebuild an analysis from :meth:`to_dict` output."""
        summary = payload.get("summary") or {}
        return cls(
            window_start=payload.get("window_start"),
            window_end=payload.get("window_end"),
            rule_id=payload.get("rule_id", THERMAL_CONCORDANCE_RULE_ID),
            months=tuple(
                ThermalConcordanceMonth.from_dict(item)
                for item in payload.get("months") or ()
            ),
            n_months=summary.get("n_months", 0),
            n_lst_concordant=summary.get("n_lst_concordant", 0),
            n_lst_divergent=summary.get("n_lst_divergent", 0),
            n_lst_mixed=summary.get("n_lst_mixed", 0),
            n_lst_only=summary.get("n_lst_only", 0),
            n_air_concordant=summary.get("n_air_concordant", 0),
            n_air_divergent=summary.get("n_air_divergent", 0),
            n_air_mixed=summary.get("n_air_mixed", 0),
            n_air_only=summary.get("n_air_only", 0),
            n_insufficient=summary.get("n_insufficient", 0),
        )


_ANALYSIS_METHODS: Dict[str, str] = {
    "alignment": (
        "Exact (window_start, window_end) identity across P2.5 "
        "months and P4.3 thermal months; no bridging, shifting, "
        "interpolation, or deletion."
    ),
    "orientation": (
        "P4.3 anomaly categories and P1.3 change directions mapped "
        "to UP/DOWN/NEUTRAL per documented meaning (anomaly first, "
        "change recorded as fallback); P2.5 family orientations "
        "restated, never recomputed; raw values never read."
    ),
    "relationship": (
        "Deterministic rule P44_THERMAL_CONCORDANCE_V1 over one "
        "thermal orientation and the usable optical/radar family "
        "orientations of the same exact month."
    ),
    "counting": (
        "Observational sensors counted once each from stored P2.5 "
        "family sensors plus MODIS LST when usable; ERA5 is "
        "meteorological context and is never counted as a sensor."
    ),
}

_ANALYSIS_LIMITATIONS: Tuple[str, ...] = (
    "Thermal concordance reports same-month directional alignment "
    "only; it does not identify a cause and cannot establish the "
    "presence of any biological condition.",
    "LST is a land-surface observation and is NOT canopy "
    "temperature; ERA5 is modelled 2 m air temperature and is NOT "
    "an independent satellite observation.",
    "LST and ERA5 keep separate statistics; their alignment is "
    "reported without differencing and without a combined measure.",
    "Possible influences include weather, irrigation, phenology, "
    "soil and background signals, acquisition geometry, "
    "management, and atmospheric effects; this layer does not "
    "select among them.",
)


# --------------------------------------------------------------------------
# Orientation from established P4.3 states
# --------------------------------------------------------------------------


def _map_anomaly_state(state: Optional[str]) -> Optional[str]:
    if state is None:
        return None
    name = str(state).strip().upper()
    if name in _UP_ANOMALY_STATES:
        return ORIENTATION_UP
    if name in _DOWN_ANOMALY_STATES:
        return ORIENTATION_DOWN
    if name in _NEUTRAL_ANOMALY_STATES:
        return ORIENTATION_NEUTRAL
    return None


def _map_change_state(state: Optional[str]) -> Optional[str]:
    if state is None:
        return None
    name = str(state).strip().upper()
    if name in _UP_CHANGE_STATES:
        return ORIENTATION_UP
    if name in _DOWN_CHANGE_STATES:
        return ORIENTATION_DOWN
    if name in _NEUTRAL_CHANGE_STATES:
        return ORIENTATION_NEUTRAL
    return None


def thermal_orientation(
    analysis: ThermalMetricAnalysis, window_start: str
) -> ThermalSideEvidence:
    """Orient one thermal month from its established P4.3 states.

    The anomaly category is used first; when it carries no
    direction but the month holds a usable observation, the
    month's change direction is used and recorded. A month with
    no usable observation, or with no directional state at all,
    reads INSUFFICIENT. Raw values are never consulted.

    Raises:
        ValueError: when the analysis names an unsupported thermal
            quantity. No substitution is ever performed.
    """
    role = _role_for(analysis)
    change_by_window = {
        change.window_start: change for change in analysis.changes
    }
    for point in analysis.anomalies.points:
        if point.window_start != window_start:
            continue
        return _orient_point(analysis, role, point, change_by_window.get(
            point.window_start
        ))
    raise ValueError(
        f"No thermal month {window_start!r} in analysis "
        f"{analysis.metric_key!r}."
    )


def _role_for(analysis: ThermalMetricAnalysis) -> str:
    if analysis.profile_kind == THERMAL_PROFILE_KIND_LST:
        return SOURCE_ROLE_LST
    if analysis.profile_kind == THERMAL_PROFILE_KIND_AIR:
        return SOURCE_ROLE_AIR
    raise ValueError(
        f"Thermal concordance is not supported for profile kind "
        f"{analysis.profile_kind!r}."
    )


def _orient_point(
    analysis: ThermalMetricAnalysis,
    role: str,
    point: Any,
    change: Any,
) -> ThermalSideEvidence:
    """Map one anomaly point (plus its change fallback) to evidence."""
    base = {
        "window_start": point.window_start,
        "window_end": point.window_end,
        "profile_kind": analysis.profile_kind,
        "physical_quantity": analysis.physical_quantity,
        "source_role": role,
        "metric_id": analysis.metric_key,
        "dataset_id": analysis.dataset_id,
        "band": analysis.band,
        "value": point.value,
        "unit": point.unit,
        "quality": point.quality,
        "coverage_percent": point.coverage_percent,
        "image_count": point.image_count,
        "provenance": dict(
            getattr(point, "thermal_provenance", None)
            or _provenance_for(analysis, point.window_start)
        ),
    }
    oriented = _map_anomaly_state(point.category)
    if oriented is not None and _is_usable_value(point.value):
        return ThermalSideEvidence(
            **base,
            orientation=oriented,
            orientation_source=ORIENTATION_SOURCE_ANOMALY,
            source_state=point.category,
            source_state_kind="anomaly",
        )
    fallback = (
        _map_change_state(change.direction)
        if change is not None and _is_usable_value(point.value)
        else None
    )
    if fallback is not None:
        return ThermalSideEvidence(
            **base,
            orientation=fallback,
            orientation_source=ORIENTATION_SOURCE_CHANGE,
            source_state=change.direction,
            source_state_kind="change",
        )
    return ThermalSideEvidence(
        **base,
        orientation=ORIENTATION_INSUFFICIENT,
        orientation_source=ORIENTATION_SOURCE_ANOMALY,
        source_state=point.category,
        source_state_kind="anomaly",
    )


def _is_usable_value(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    import math

    return math.isfinite(value)


def _provenance_for(
    analysis: ThermalMetricAnalysis, window_start: str
) -> Dict[str, Any]:
    for point in analysis.source.points:
        if point.window_start == window_start:
            return dict(point.provenance)
    return {}


def side_evidence(
    analysis: ThermalMetricAnalysis,
) -> Tuple[ThermalSideEvidence, ...]:
    """Orient every month of one thermal analysis, in order."""
    _role_for(analysis)
    return tuple(
        thermal_orientation(analysis, point.window_start)
        for point in analysis.anomalies.points
    )


# --------------------------------------------------------------------------
# Monthly relationship
# --------------------------------------------------------------------------


def _relate(
    orientation: str,
    externals: List[str],
    ambiguous_present: bool,
    p25_usable: bool,
    concordant: str,
    divergent: str,
    mixed: str,
    only: str,
) -> Tuple[str, str]:
    """Apply the relationship rule; returns (state, explanation core)."""
    if orientation == ORIENTATION_INSUFFICIENT:
        return (
            RELATIONSHIP_INSUFFICIENT,
            "thermal evidence carries no direction",
        )
    if not p25_usable:
        return only, "no usable P2.5 evidence for the exact month"
    if not externals and not ambiguous_present:
        return (
            RELATIONSHIP_INSUFFICIENT,
            "P2.5 evidence carries no directional orientation",
        )
    if ambiguous_present:
        return mixed, "external orientations are partly unclear"
    match = any(item == orientation for item in externals)
    oppose = (
        orientation == ORIENTATION_UP
        and any(item == ORIENTATION_DOWN for item in externals)
    ) or (
        orientation == ORIENTATION_DOWN
        and any(item == ORIENTATION_UP for item in externals)
    )
    if match and oppose:
        return mixed, "external orientations partly align and partly oppose"
    if match:
        return concordant, "orientations are aligned for the same month"
    if oppose:
        return divergent, "orientations oppose for the same month"
    return mixed, "orientations neither align nor oppose"


def _agree(
    lst_orientation: Optional[str], air_orientation: Optional[str]
) -> Optional[str]:
    if lst_orientation is None or air_orientation is None:
        return None
    if (
        lst_orientation == ORIENTATION_INSUFFICIENT
        and air_orientation == ORIENTATION_INSUFFICIENT
    ):
        return AGREEMENT_BOTH_INSUFFICIENT
    if (
        lst_orientation == ORIENTATION_INSUFFICIENT
        or air_orientation == ORIENTATION_INSUFFICIENT
    ):
        return AGREEMENT_ONE_INSUFFICIENT
    if lst_orientation == air_orientation:
        return AGREEMENT_SAME
    if {lst_orientation, air_orientation} == {
        ORIENTATION_UP,
        ORIENTATION_DOWN,
    }:
        return AGREEMENT_OPPOSITE
    return AGREEMENT_MIXED


def analyze_thermal_concordance(
    concordance_months: Sequence[ConcordanceMonth],
    lst_analysis: Optional[ThermalMetricAnalysis] = None,
    air_analysis: Optional[ThermalMetricAnalysis] = None,
) -> ThermalConcordanceAnalysis:
    """Describe same-month alignment between P2.5 and P4.3 evidence.

    P2.5 months are restated verbatim; each supplied thermal
    analysis is oriented month by month; months align by exact
    ``(window_start, window_end)`` identity only. Adjacent months
    stay independent, gaps stay gaps, and missing evidence reads
    insufficient — never a negative finding.
    """
    if lst_analysis is not None:
        _role_for(lst_analysis)
        if lst_analysis.profile_kind != THERMAL_PROFILE_KIND_LST:
            raise ValueError(
                "lst_analysis must be an LST_PROFILE analysis, got "
                f"{lst_analysis.profile_kind!r}."
            )
    if air_analysis is not None:
        _role_for(air_analysis)
        if air_analysis.profile_kind != THERMAL_PROFILE_KIND_AIR:
            raise ValueError(
                "air_analysis must be an AIR_TEMPERATURE_PROFILE "
                f"analysis, got {air_analysis.profile_kind!r}."
            )

    p25_by_window = {
        (month.window_start, month.window_end): month
        for month in concordance_months
    }
    lst_by_window = (
        {item.window_start: item for item in side_evidence(lst_analysis)}
        if lst_analysis is not None
        else {}
    )
    air_by_window = (
        {item.window_start: item for item in side_evidence(air_analysis)}
        if air_analysis is not None
        else {}
    )
    ordered = sorted(
        set(p25_by_window)
        | {(item.window_start, item.window_end) for item in lst_by_window.values()}
        | {(item.window_start, item.window_end) for item in air_by_window.values()}
    )

    months: List[ThermalConcordanceMonth] = []
    for window_start, window_end in ordered:
        p25 = p25_by_window.get((window_start, window_end))
        lst = lst_by_window.get(window_start)
        air = air_by_window.get(window_start)
        months.append(
            _concordance_month(window_start, window_end, p25, lst, air)
        )

    summary = _summarize(months)
    logger.info(
        "Thermal concordance: %d month(s), LST concordant %d, "
        "ERA5 context concordant %d.",
        len(months),
        summary["n_lst_concordant"],
        summary["n_air_concordant"],
    )
    return ThermalConcordanceAnalysis(
        window_start=ordered[0][0] if ordered else None,
        window_end=ordered[-1][1] if ordered else None,
        months=tuple(months),
        **summary,
    )


def _family_orientation(
    month: Optional[ConcordanceMonth], family: str
) -> Optional[str]:
    if month is None:
        return None
    for evidence in month.families:
        if evidence.family == family:
            return evidence.orientation
    return None


def _concordance_month(
    window_start: str,
    window_end: str,
    p25: Optional[ConcordanceMonth],
    lst: Optional[ThermalSideEvidence],
    air: Optional[ThermalSideEvidence],
) -> ThermalConcordanceMonth:
    """Build one month's statement from restated inputs."""
    optical = _family_orientation(p25, "optical")
    red_edge = _family_orientation(p25, "red_edge")
    radar = _family_orientation(p25, "radar")
    externals = [
        orientation
        for orientation in (optical, radar)
        if orientation in _DIRECTIONAL_ORIENTATIONS
    ]
    ambiguous = (
        optical not in _DIRECTIONAL_ORIENTATIONS and optical is not None
        and optical != ORIENTATION_INSUFFICIENT
    ) or (
        radar not in _DIRECTIONAL_ORIENTATIONS and radar is not None
        and radar != ORIENTATION_INSUFFICIENT
    )
    p25_usable = p25 is not None and any(
        evidence.usable_count > 0 for evidence in p25.families
    )

    lst_orientation = (
        lst.orientation if lst is not None else ORIENTATION_INSUFFICIENT
    )
    lst_state, lst_core = _relate(
        lst_orientation,
        externals,
        ambiguous,
        p25_usable,
        LST_CONCORDANT,
        LST_DIVERGENT,
        LST_MIXED,
        LST_ONLY,
    )
    air_orientation = (
        air.orientation if air is not None else ORIENTATION_INSUFFICIENT
    )
    air_state, air_core = _relate(
        air_orientation,
        externals,
        ambiguous,
        p25_usable,
        AIR_CONCORDANT,
        AIR_DIVERGENT,
        AIR_MIXED,
        AIR_ONLY,
    )

    sensors = set()
    if p25 is not None:
        for evidence in p25.families:
            if evidence.usable_count > 0:
                sensors.add(evidence.sensor)
    lst_usable = lst is not None and _is_usable_value(lst.value)
    if lst_usable:
        sensors.add("LST")
    context_present = air is not None and _is_usable_value(air.value)

    explanations = [
        _explain_side("LST", lst, lst_orientation, lst_state, lst_core,
                      window_start, window_end),
        _explain_side("ERA5 2 m air temperature", air, air_orientation,
                      air_state, air_core, window_start, window_end),
    ]
    if p25 is not None:
        explanations.append(
            f"P2.5 state {p25.state} restated unchanged "
            f"(rule {p25.rule_id}); existing multi-sensor agreement "
            "is reported as established, not re-measured."
        )
    else:
        explanations.append(
            "No P2.5 month exists for the exact window; nothing is "
            "borrowed from adjacent months."
        )

    return ThermalConcordanceMonth(
        window_start=window_start,
        window_end=window_end,
        rule_id=THERMAL_CONCORDANCE_RULE_ID,
        lst=lst,
        air=air,
        p25_state=p25.state if p25 is not None else None,
        p25_rule_id=p25.rule_id if p25 is not None else None,
        optical_orientation=optical,
        red_edge_orientation=red_edge,
        radar_orientation=radar,
        lst_relationship=lst_state,
        air_relationship=air_state,
        lst_era5_agreement=_agree(
            lst.orientation if lst is not None else None,
            air.orientation if air is not None else None,
        ),
        observational_sensor_count=len(sensors),
        meteorological_context_present=context_present,
        explanations=tuple(explanations),
    )


def _explain_side(
    label: str,
    side: Optional[ThermalSideEvidence],
    orientation: str,
    relationship: str,
    core: str,
    window_start: str,
    window_end: str,
) -> str:
    """One descriptive sentence per thermal side, no causal content."""
    if side is None:
        return (
            f"{label}: no analysis supplied for {window_start} to "
            f"{window_end}; {core}."
        )
    if side.source_role == SOURCE_ROLE_AIR:
        role_note = (
            "modelled 2 m air temperature (meteorological context, "
            "not an independent satellite observation)"
        )
    else:
        role_note = "land-surface observation"
    return (
        f"{label} ({role_note}) orientation {orientation} from "
        f"{side.orientation_source} state {side.source_state}: "
        f"{relationship} — {core} for {window_start} to {window_end}."
    )


def _summarize(
    months: Sequence[ThermalConcordanceMonth],
) -> Dict[str, int]:
    """Deterministic tallies over monthly relationships (not scores)."""
    lst_states = [month.lst_relationship for month in months]
    air_states = [month.air_relationship for month in months]
    insufficient = sum(
        1
        for month in months
        if month.lst_relationship == RELATIONSHIP_INSUFFICIENT
        and month.air_relationship == RELATIONSHIP_INSUFFICIENT
    )
    return {
        "n_months": len(months),
        "n_lst_concordant": lst_states.count(LST_CONCORDANT),
        "n_lst_divergent": lst_states.count(LST_DIVERGENT),
        "n_lst_mixed": lst_states.count(LST_MIXED),
        "n_lst_only": lst_states.count(LST_ONLY),
        "n_air_concordant": air_states.count(AIR_CONCORDANT),
        "n_air_divergent": air_states.count(AIR_DIVERGENT),
        "n_air_mixed": air_states.count(AIR_MIXED),
        "n_air_only": air_states.count(AIR_ONLY),
        "n_insufficient": insufficient,
    }
