"""Temporal change and breakpoint detection over agricultural profiles.

P1.3 layer for the Pest & Disease Early Warning work.  Domain-neutral
statistical machinery only: this module detects temporal behavior —
observation-to-observation change, unusually rapid change, persistent
deviation, and conservative breakpoints.  It does NOT identify the
cause of any change.

A temporal decline may have many possible explanations including
phenology, weather, irrigation, management, sensor/coverage effects,
vegetation stress, pests, or disease.  The system must not select
one of these causes at this layer: there are no severity levels, no
risk scores, no probabilities, no ML, and no causal rules here.

Reused architecture (nothing re-derived):

* deviation runs via :func:`history.compute_persistence` over
  P1.2 z-scores against 0.0 — gaps and exact-zero ties break runs,
  per the repository's rule;
* breakpoints via :func:`history.largest_rolling_shift` — the
  largest adjacent rolling-mean difference, with a contiguity guard
  added here so a boundary spanning unobserved months is refused
  rather than bridged;
* the STABLE convention via :data:`history.FLAT_FRACTION` — a step
  smaller than that fraction of the reference spread is
  approximately flat, exactly the engine's existing flatness rule;
* sufficiency floors mirroring the repository's recurring
  three-observation minimum (:data:`history.MIN_BASELINE_GROUP`).

Deliberate P1.3 parameters (structural, configurable, documented —
not biological thresholds):

* ``CHANGE_MAX_GAP_MONTHS = 1`` — at most one missing month may sit
  between two compared observations; longer gaps refuse the change
  instead of connecting across an unobserved interval;
* ``RAPID_STD_MULTIPLE = 2.0`` — a step larger than two reference
  spreads is flagged rapid (the standard two-sigma unusualness
  heuristic, stated as such);
* ``PERSISTENCE_MIN_RUN = 3`` — a deviation run of three consecutive
  valid months counts as persistent;
* ``BREAK_WINDOW_MONTHS = 3`` — rolling means of three months per
  side for breakpoint candidates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.services.agriculture.baseline_anomaly import AnomalyProfile
from app.services.agriculture.history import (
    FLAT_FRACTION,
    ObservationPoint,
    compute_persistence,
    largest_rolling_shift,
)
from app.services.agriculture.temporal_profile import TemporalProfile

logger = get_logger(__name__)

__all__ = [
    "CHANGE_MAX_GAP_MONTHS",
    "RAPID_STD_MULTIPLE",
    "PERSISTENCE_MIN_RUN",
    "BREAK_WINDOW_MONTHS",
    "DIRECTION_INCREASE",
    "DIRECTION_DECREASE",
    "DIRECTION_STABLE",
    "DIRECTION_INSUFFICIENT",
    "RAPID_INCREASE",
    "RAPID_DECREASE",
    "RAPID_NOT_RAPID",
    "RAPID_INSUFFICIENT",
    "PERSISTENCE_NONE",
    "PERSISTENCE_PERSISTENT",
    "PERSISTENCE_INSUFFICIENT",
    "MonthChange",
    "DeviationPersistence",
    "Breakpoint",
    "ChangeProfile",
    "classify_direction",
    "classify_rapid",
    "month_changes",
    "persistence_of",
    "detect_breakpoint",
    "analyze_changes",
]

#: Maximum missing months bridged between two compared observations.
CHANGE_MAX_GAP_MONTHS = 1

#: Step magnitude beyond this multiple of the reference spread flags rapid.
RAPID_STD_MULTIPLE = 2.0

#: Consecutive deviating months that count as persistence.
PERSISTENCE_MIN_RUN = 3

#: Rolling-mean window (months per side) for breakpoint candidates.
BREAK_WINDOW_MONTHS = 3

#: Neutral direction categories.  Descriptions of numbers only.
DIRECTION_INCREASE = "INCREASE"
DIRECTION_DECREASE = "DECREASE"
DIRECTION_STABLE = "STABLE"
DIRECTION_INSUFFICIENT = "INSUFFICIENT"

#: Neutral rapid-change flags.  Statistical unusualness only.
RAPID_INCREASE = "RAPID_INCREASE"
RAPID_DECREASE = "RAPID_DECREASE"
RAPID_NOT_RAPID = "NOT_RAPID"
RAPID_INSUFFICIENT = "INSUFFICIENT"

#: Neutral persistence states.
PERSISTENCE_NONE = "NO_PERSISTENCE"
PERSISTENCE_PERSISTENT = "PERSISTENT"
PERSISTENCE_INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class MonthChange:
    """One observation-to-observation change.

    ``previous_*`` fields are ``None`` when there is no admissible
    predecessor (profile start, missing months, or a gap beyond the
    bridging allowance): the change is then refused with
    ``INSUFFICIENT`` direction rather than connected across the gap.
    """

    window_start: str
    window_end: str
    value: Optional[float]
    previous_window_start: Optional[str] = None
    previous_window_end: Optional[str] = None
    previous_value: Optional[float] = None
    absolute_change: Optional[float] = None
    relative_change: Optional[float] = None
    days_elapsed: Optional[int] = None
    rate_per_day: Optional[float] = None
    direction: str = DIRECTION_INSUFFICIENT
    rapid: str = RAPID_INSUFFICIENT
    z_score: Optional[float] = None
    percentile: Optional[float] = None
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.3 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "previous_window_start": self.previous_window_start,
            "previous_window_end": self.previous_window_end,
            "previous_value": self.previous_value,
            "absolute_change": self.absolute_change,
            "relative_change": self.relative_change,
            "days_elapsed": self.days_elapsed,
            "rate_per_day": self.rate_per_day,
            "direction": self.direction,
            "rapid": self.rapid,
            "z_score": self.z_score,
            "percentile": self.percentile,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
        }


@dataclass(frozen=True)
class DeviationPersistence:
    """How long z-score deviations lasted, with gaps honoured."""

    longest_run_below: int = 0
    longest_run_above: int = 0
    n_anomalous: int = 0
    n_observed: int = 0
    n_missing: int = 0
    state: str = PERSISTENCE_INSUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.3 API contract models."""
        return {
            "longest_run_below": self.longest_run_below,
            "longest_run_above": self.longest_run_above,
            "n_anomalous": self.n_anomalous,
            "n_observed": self.n_observed,
            "n_missing": self.n_missing,
            "state": self.state,
        }


@dataclass(frozen=True)
class Breakpoint:
    """One conservative temporal transition, described and nothing more."""

    onset_window_start: str
    onset_window_end: str
    direction: str
    pre_level: float
    post_level: float
    magnitude: float
    window_months: int
    n_usable: int
    method: str

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.3 API contract models."""
        return {
            "onset_window_start": self.onset_window_start,
            "onset_window_end": self.onset_window_end,
            "direction": self.direction,
            "pre_level": self.pre_level,
            "post_level": self.post_level,
            "magnitude": self.magnitude,
            "window_months": self.window_months,
            "n_usable": self.n_usable,
            "method": self.method,
        }


@dataclass(frozen=True)
class ChangeProfile:
    """A temporal profile with change, persistence, and breakpoint analysis."""

    metric_key: str
    unit: str
    window_start: str
    window_end: str
    step: str
    changes: Tuple[MonthChange, ...] = field(default_factory=tuple)
    persistence: DeviationPersistence = field(
        default_factory=DeviationPersistence
    )
    breakpoint: Optional[Breakpoint] = None

    @property
    def n_computed(self) -> int:
        """Changes with a measured magnitude (all others are gaps/refusals)."""
        return sum(
            1 for change in self.changes if change.absolute_change is not None
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.3 API contract models."""
        return {
            "metric_key": self.metric_key,
            "unit": self.unit,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "changes": [change.to_dict() for change in self.changes],
            "persistence": self.persistence.to_dict(),
            "breakpoint": self.breakpoint.to_dict()
            if self.breakpoint is not None
            else None,
        }


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _months_between(earlier: str, later: str) -> Optional[int]:
    """Whole calendar months from one window start to a later one."""
    try:
        first = date.fromisoformat(earlier)
        second = date.fromisoformat(later)
    except (ValueError, TypeError):
        return None
    return (second.year - first.year) * 12 + (second.month - first.month)


def _days_between(earlier: str, later: str) -> Optional[int]:
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except (ValueError, TypeError):
        return None


def classify_direction(
    absolute_change: Optional[float],
    reference_spread: Optional[float] = None,
    stable_fraction: float = FLAT_FRACTION,
) -> str:
    """Neutral direction for a measured step.

    With a reference spread, the engine's flatness contract applies:
    a step at most ``stable_fraction`` of the spread is STABLE.
    Without one, only an exact zero is STABLE.  A missing change is
    INSUFFICIENT, never a fabricated direction.
    """
    if not _is_finite_number(absolute_change):
        return DIRECTION_INSUFFICIENT
    change = float(absolute_change)
    if (
        reference_spread is not None
        and _is_finite_number(reference_spread)
        and reference_spread > 0.0
    ):
        if abs(change) <= stable_fraction * float(reference_spread):
            return DIRECTION_STABLE
    elif change == 0.0:
        return DIRECTION_STABLE
    if change > 0.0:
        return DIRECTION_INCREASE
    if change < 0.0:
        return DIRECTION_DECREASE
    return DIRECTION_STABLE


def classify_rapid(
    absolute_change: Optional[float],
    reference_spread: Optional[float] = None,
    multiple: float = RAPID_STD_MULTIPLE,
) -> str:
    """Flag unusually large steps against the reference spread.

    A step beyond ``multiple`` reference spreads is rapid in the
    stated direction; anything smaller is NOT_RAPID.  Without a
    positive finite spread there is nothing to compare against, so
    the flag is INSUFFICIENT rather than a default calm.
    """
    if not _is_finite_number(absolute_change):
        return RAPID_INSUFFICIENT
    if (
        reference_spread is None
        or not _is_finite_number(reference_spread)
        or float(reference_spread) <= 0.0
    ):
        return RAPID_INSUFFICIENT
    if abs(float(absolute_change)) > multiple * float(reference_spread):
        return (
            RAPID_INCREASE if float(absolute_change) > 0.0 else RAPID_DECREASE
        )
    return RAPID_NOT_RAPID


def month_changes(
    profile: TemporalProfile,
    anomalies: Optional[AnomalyProfile] = None,
    reference_spread: Optional[float] = None,
    stable_fraction: float = FLAT_FRACTION,
    max_gap_months: int = CHANGE_MAX_GAP_MONTHS,
    rapid_multiple: float = RAPID_STD_MULTIPLE,
) -> Tuple[MonthChange, ...]:
    """Observation-to-observation changes for every profile month.

    Each usable month is compared with its nearest preceding usable
    month; at most ``max_gap_months`` missing months may sit between
    them, otherwise the change is refused.  The first month and any
    month without an admissible predecessor carry ``INSUFFICIENT``
    direction.  Z-scores and percentiles are attached by window when
    an anomaly profile is supplied.
    """
    scored_by_window = (
        {point.window_start: point for point in anomalies.points}
        if anomalies is not None
        else {}
    )
    usable_indices = [
        index
        for index, point in enumerate(profile.points)
        if _is_finite_number(point.value)
    ]
    previous_of: Dict[int, int] = {}
    for position, index in enumerate(usable_indices):
        if position == 0:
            continue
        prev_index = usable_indices[position - 1]
        gap = _months_between(
            profile.points[prev_index].window_start,
            profile.points[index].window_start,
        )
        # Adjacent months bridge zero missing months; anything beyond
        # the allowance refuses the change instead of connecting.
        if gap is not None and 0 <= gap - 1 <= max_gap_months:
            previous_of[index] = prev_index

    changes: List[MonthChange] = []
    for index, point in enumerate(profile.points):
        base = {
            "window_start": point.window_start,
            "window_end": point.window_end,
            "value": point.value if _is_finite_number(point.value) else None,
            "unit": point.unit,
            "quality": point.quality,
            "coverage_percent": point.coverage_percent,
            "image_count": point.image_count,
        }
        scored = scored_by_window.get(point.window_start)
        z_score = scored.z_score if scored is not None else None
        percentile = scored.percentile if scored is not None else None
        prev_index = previous_of.get(index)
        if prev_index is None or not _is_finite_number(point.value):
            changes.append(MonthChange(**base, z_score=z_score, percentile=percentile))
            continue
        previous = profile.points[prev_index]
        assert _is_finite_number(previous.value)
        change = float(point.value) - float(previous.value)  # type: ignore[arg-type]
        days = _days_between(previous.window_start, point.window_start)
        if previous.value == 0.0:
            relative: Optional[float] = None
        else:
            relative = change / abs(float(previous.value))  # type: ignore[arg-type]
        changes.append(
            MonthChange(
                **base,
                previous_window_start=previous.window_start,
                previous_window_end=previous.window_end,
                previous_value=float(previous.value),  # type: ignore[arg-type]
                absolute_change=change,
                relative_change=relative,
                days_elapsed=days,
                rate_per_day=(change / days)
                if days is not None and days > 0
                else None,
                direction=classify_direction(
                    change, reference_spread, stable_fraction
                ),
                rapid=classify_rapid(change, reference_spread, rapid_multiple),
                z_score=z_score,
                percentile=percentile,
            )
        )
    return tuple(changes)


def persistence_of(anomalies: AnomalyProfile) -> DeviationPersistence:
    """Deviation persistence for a scored anomaly profile.

    Z-scores are run through the repository's persistence counter
    against 0.0: negative runs are deviation below the
    reference, positive runs above it; gaps and exact zeros break
    runs.  A longest run of at least ``PERSISTENCE_MIN_RUN``
    consecutive valid months in either direction is PERSISTENT.
    Without a usable baseline there is no reference to deviate
    from, so the state is INSUFFICIENT (counts still reported).
    """
    n_missing = sum(1 for point in anomalies.points if point.value is None)
    if anomalies.baseline is None:
        return DeviationPersistence(
            n_observed=sum(
                1 for point in anomalies.points if _is_finite_number(point.value)
            ),
            n_missing=n_missing,
            state=PERSISTENCE_INSUFFICIENT,
        )
    z_series: List[Optional[float]] = [
        point.z_score if _is_finite_number(point.z_score) else None
        for point in anomalies.points
    ]
    record = compute_persistence(z_series, 0.0)
    if record is None:
        return DeviationPersistence(
            n_observed=sum(
                1 for point in anomalies.points if _is_finite_number(point.value)
            ),
            n_missing=n_missing,
            state=PERSISTENCE_INSUFFICIENT,
        )
    longest = max(record.longest_run_below, record.longest_run_above)
    return DeviationPersistence(
        longest_run_below=record.longest_run_below,
        longest_run_above=record.longest_run_above,
        n_anomalous=record.n_anomalous,
        n_observed=record.n_observed,
        n_missing=record.n_missing,
        state=PERSISTENCE_PERSISTENT
        if longest >= PERSISTENCE_MIN_RUN
        else PERSISTENCE_NONE,
    )


def _contiguous_months(points: List[Any]) -> bool:
    """True when window starts form an unbroken monthly sequence."""
    try:
        months = [
            (date.fromisoformat(p.window_start).year * 12
             + date.fromisoformat(p.window_start).month)
            for p in points
        ]
    except (ValueError, TypeError):
        return False
    return all(second - first == 1 for first, second in zip(months, months[1:]))


def detect_breakpoint(
    profile: TemporalProfile,
    window_months: int = BREAK_WINDOW_MONTHS,
) -> Optional[Breakpoint]:
    """Conservative breakpoint: largest adjacent rolling-mean shift.

    Candidates come from the repository's rolling-shift utility over
    the usable months; the winning boundary is then required to sit
    inside 2 × ``window_months`` consecutive observed months —
    anything spanning a gap is refused rather than bridged.  A zero
    winning magnitude means no transition exists and is also
    refused.  Direction follows the magnitude sign; it describes the
    numbers, never a biological event.
    """
    usable = [
        (index, point)
        for index, point in enumerate(profile.points)
        if _is_finite_number(point.value)
    ]
    if len(usable) < 2 * window_months or window_months < 1:
        return None
    members = [
        ObservationPoint(
            day=date.fromisoformat(point.window_start),
            value=float(point.value),  # type: ignore[arg-type]
        )
        for _, point in usable
    ]
    record = largest_rolling_shift(members, window_months)
    if record is None or record.magnitude == 0.0:
        return None
    boundary_position = next(
        (
            position
            for position, (_, point) in enumerate(usable)
            if date.fromisoformat(point.window_start) == record.boundary_day
        ),
        None,
    )
    if boundary_position is None:
        return None
    # The utility indexes the usable-only sequence while the span
    # must be contiguous calendar months: rebuild the span from the
    # profile by calendar position instead.
    start_index = usable[boundary_position - window_months][0]
    end_index = usable[boundary_position + window_months - 1][0]
    span = list(profile.points[start_index : end_index + 1])
    if len(span) != 2 * window_months or not _contiguous_months(span):
        return None
    onset = span[window_months]
    direction = (
        DIRECTION_INCREASE
        if record.magnitude > 0.0
        else DIRECTION_DECREASE
        if record.magnitude < 0.0
        else DIRECTION_STABLE
    )
    return Breakpoint(
        onset_window_start=onset.window_start,
        onset_window_end=onset.window_end,
        direction=direction,
        pre_level=record.before,
        post_level=record.after,
        magnitude=record.magnitude,
        window_months=window_months,
        n_usable=len(usable),
        method=record.method,
    )


def analyze_changes(
    profile: TemporalProfile,
    anomalies: Optional[AnomalyProfile] = None,
) -> ChangeProfile:
    """Full change analysis for one temporal profile.

    Month-to-month changes (with anomaly attachment and the
    baseline spread when an anomaly baseline exists), deviation
    persistence over the z-scores, and the conservative breakpoint.
    Deterministic: identical inputs produce identical output.
    """
    spread: Optional[float] = None
    if anomalies is not None and anomalies.baseline is not None:
        candidate = anomalies.baseline.std
        if _is_finite_number(candidate) and float(candidate) > 0.0:  # type: ignore[arg-type]
            spread = float(candidate)  # type: ignore[arg-type]
    changes = month_changes(profile, anomalies, reference_spread=spread)
    if anomalies is not None:
        persistence = persistence_of(anomalies)
    else:
        persistence = DeviationPersistence(
            n_observed=sum(
                1 for point in profile.points if _is_finite_number(point.value)
            ),
            n_missing=sum(
                1 for point in profile.points if not _is_finite_number(point.value)
            ),
            state=PERSISTENCE_INSUFFICIENT,
        )
    return ChangeProfile(
        metric_key=profile.metric_key,
        unit=profile.unit,
        window_start=profile.window_start,
        window_end=profile.window_end,
        step=profile.step,
        changes=changes,
        persistence=persistence,
        breakpoint=detect_breakpoint(profile),
    )
