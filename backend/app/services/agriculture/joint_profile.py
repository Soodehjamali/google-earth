"""NDVI–moisture joint temporal analysis (P1.4 foundation).

Reusable, domain-neutral evidence analysis of the relationship and
divergence between vegetation greenness (NDVI) and a vegetation
moisture proxy over aligned monthly observations.  This layer
detects temporal patterns only.  It does NOT identify pests,
diseases, drought, nutrient deficiency, irrigation failure, or any
other cause — and in particular, a moisture decline preceding an
NDVI decline is a temporal association, NOT evidence sufficient to
identify wood-boring insects, vascular pests, or fungal disease.
Multiple mechanisms produce similar remote-sensing trajectories,
and this module must not select one.

Metric identity (terminology contract):

* ``ndvi`` — vegetation greenness.
* ``ndmi`` — Normalized Difference Moisture Index (Gao), the
  repository's vegetation/canopy moisture proxy.  THIS is the
  moisture metric used here.
* ``ndwi`` (McFeeters, green/NIR) exists in the registry but is an
  OPEN-WATER index, not a vegetation moisture signal, and is
  refused by this module.  NDMI is never renamed to NDWI.

Reused architecture (nothing re-derived):

* observation sequences from :mod:`temporal_profile` (P1.1);
* z-scores, ranks, and sufficiency semantics from :mod:`baseline_anomaly`
  (P1.2) — attached, never recomputed;
* month-to-month directions from :mod:`change_profile` (P1.3) —
  attached by window, never recomputed;
* Pearson association needs no new dependency (numpy is already
  used across the engine).

Every joint computation refuses rather than manufactures: missing
months stay missing, mismatched months are explicit, small and
degenerate populations yield no statistic, and zero-variance series
yield no correlation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from app.services.agriculture.baseline_anomaly import AnomalyProfile
from app.services.agriculture.change_profile import ChangeProfile
from app.services.agriculture.temporal_profile import TemporalProfile

__all__ = [
    "NDVI_KEY",
    "SUPPORTED_MOISTURE_KEYS",
    "MIN_LAG_PAIRS",
    "MIN_CORRELATION_PAIRS",
    "JointPoint",
    "JointProfile",
    "JointChange",
    "LagResult",
    "ScatterPoint",
    "ScatterDataset",
    "JointAnalysis",
    "align_profiles",
    "joint_anomaly_state",
    "joint_changes",
    "lead_lag_analysis",
    "divergence_of",
    "divergence_of",
    "scatter_dataset",
    "pearson_correlation",
    "analyze_joint",
]

#: Greenness side of the joint analysis.  Fixed: this layer is
#: defined for NDVI paired with a vegetation moisture proxy.
NDVI_KEY = "ndvi"

#: Accepted moisture-metric keys.  NDMI (Gao) only: the McFeeters
#: NDWI is an open-water index and is refused explicitly.
SUPPORTED_MOISTURE_KEYS = ("ndmi",)

#: Minimum paired months for a lag result to be reported.
MIN_LAG_PAIRS = 3

#: Minimum paired months for a Pearson correlation (same
#: rank-resolution rationale as the existing percentile floor).
MIN_CORRELATION_PAIRS = 8

#: Per-month availability of the two sides.
JointAvailability = str  # BOTH | NDVI_ONLY | MOISTURE_ONLY | NEITHER
AVAILABLE_BOTH = "BOTH"
AVAILABLE_NDVI_ONLY = "NDVI_ONLY"
AVAILABLE_MOISTURE_ONLY = "MOISTURE_ONLY"
AVAILABLE_NEITHER = "NEITHER"

#: Neutral joint-anomaly states.  Directional only.
JOINT_BOTH_BELOW = "BOTH_BELOW_BASELINE"
JOINT_NDVI_BELOW = "NDVI_BELOW_BASELINE"
JOINT_MOISTURE_BELOW = "MOISTURE_BELOW_BASELINE"
JOINT_BOTH_ABOVE = "BOTH_ABOVE_BASELINE"
JOINT_MIXED = "MIXED"
JOINT_NEUTRAL = "NEUTRAL"
JOINT_INSUFFICIENT = "INSUFFICIENT"

#: Neutral joint-change patterns.  Descriptions of co-movement only.
#: (The brief's long form NDVI_DECREASE_MOISTURE_DECREASE denotes the
#: same pattern as BOTH_DECREASE; the short family name is used.)
PATTERN_BOTH_DECREASE = "BOTH_DECREASE"
PATTERN_BOTH_INCREASE = "BOTH_INCREASE"
PATTERN_BOTH_STABLE = "BOTH_STABLE"
PATTERN_NDVI_DOWN_MOISTURE_STABLE = "NDVI_DECREASE_MOISTURE_STABLE"
PATTERN_NDVI_STABLE_MOISTURE_DOWN = "NDVI_STABLE_MOISTURE_DECREASE"
PATTERN_DIVERGENT = "DIVERGENT"
PATTERN_INSUFFICIENT = "INSUFFICIENT"

#: Per-month divergence descriptors.  Observation patterns only.
DIVERGENCE_CONCURRENT_DECLINE = "CONCURRENT_DECLINE"
DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE = "MOISTURE_DOWN_NDVI_STABLE"
DIVERGENCE_NDVI_DOWN_MOISTURE_STABLE = "NDVI_DOWN_MOISTURE_STABLE"
DIVERGENCE_NO_DIVERGENCE = "NO_DIVERGENCE"
DIVERGENCE_INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class JointPoint:
    """One calendar month with both sides aligned.

    Either side may be missing; ``availability`` says which.  Z-scores
    are attached by window when anomaly profiles are supplied, never
    recomputed here.
    """

    window_start: str
    window_end: str
    ndvi: Optional[float]
    moisture: Optional[float]
    ndvi_z: Optional[float] = None
    moisture_z: Optional[float] = None
    availability: str = AVAILABLE_NEITHER
    ndvi_quality: str = "unavailable"
    moisture_quality: str = "unavailable"
    ndvi_coverage: Optional[float] = None
    moisture_coverage: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "ndvi": self.ndvi,
            "moisture": self.moisture,
            "ndvi_z": self.ndvi_z,
            "moisture_z": self.moisture_z,
            "availability": self.availability,
            "ndvi_quality": self.ndvi_quality,
            "moisture_quality": self.moisture_quality,
            "ndvi_coverage": self.ndvi_coverage,
            "moisture_coverage": self.moisture_coverage,
        }


@dataclass(frozen=True)
class JointProfile:
    """NDVI and moisture profiles aligned by exact calendar month."""

    ndvi_key: str
    moisture_key: str
    window_start: str
    window_end: str
    step: str
    points: Tuple[JointPoint, ...] = field(default_factory=tuple)

    @property
    def n_paired(self) -> int:
        """Months with both sides usable."""
        return sum(1 for p in self.points if p.availability == AVAILABLE_BOTH)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "ndvi_key": self.ndvi_key,
            "moisture_key": self.moisture_key,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "points": [p.to_dict() for p in self.points],
        }


@dataclass(frozen=True)
class JointChange:
    """Co-movement of the two sides between consecutive joint months."""

    window_start: str
    window_end: str
    previous_window_start: Optional[str] = None
    ndvi_change: Optional[float] = None
    moisture_change: Optional[float] = None
    ndvi_direction: str = "INSUFFICIENT"
    moisture_direction: str = "INSUFFICIENT"
    pattern: str = PATTERN_INSUFFICIENT
    divergence: str = DIVERGENCE_INSUFFICIENT
    days_elapsed: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "previous_window_start": self.previous_window_start,
            "ndvi_change": self.ndvi_change,
            "moisture_change": self.moisture_change,
            "ndvi_direction": self.ndvi_direction,
            "moisture_direction": self.moisture_direction,
            "pattern": self.pattern,
            "divergence": self.divergence,
            "days_elapsed": self.days_elapsed,
        }


@dataclass(frozen=True)
class LagResult:
    """Moisture-at-t versus NDVI-at-t-plus-lag agreement.

    Agreement is the fraction of paired months whose z-score signs
    match (zeros count as their own sign: both-at-reference agrees).
    Correlation is the Pearson r of the paired z-scores.  Neither
    measures causation; both describe co-movement at a stated lag.
    """

    lag_months: int
    n_paired: int
    agreement: Optional[float] = None
    correlation: Optional[float] = None
    sufficient: bool = False
    method: str = (
        "z-sign agreement and Pearson r of paired z-scores at an "
        "explicit monthly lag; descriptive co-movement only"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "lag_months": self.lag_months,
            "n_paired": self.n_paired,
            "agreement": self.agreement,
            "correlation": self.correlation,
            "sufficient": self.sufficient,
            "method": self.method,
        }


@dataclass(frozen=True)
class ScatterPoint:
    """One paired month in NDVI/moisture space, fully traceable."""

    window_start: str
    ndvi: float
    moisture: float
    ndvi_z: Optional[float] = None
    moisture_z: Optional[float] = None
    ndvi_quality: str = "unavailable"
    moisture_quality: str = "unavailable"

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "window_start": self.window_start,
            "ndvi": self.ndvi,
            "moisture": self.moisture,
            "ndvi_z": self.ndvi_z,
            "moisture_z": self.moisture_z,
            "ndvi_quality": self.ndvi_quality,
            "moisture_quality": self.moisture_quality,
        }


@dataclass(frozen=True)
class ScatterDataset:
    """Paired months in chronological order plus one summary number.

    The ordered points ARE the trajectory a future frontend renders;
    the correlation is an optional summary that never replaces them.
    """

    ndvi_key: str
    moisture_key: str
    points: Tuple[ScatterPoint, ...] = field(default_factory=tuple)
    correlation: Optional[float] = None
    n_paired: int = 0
    method: str = (
        "Pearson r over paired finite values; refused below "
        f"{MIN_CORRELATION_PAIRS} pairs or on zero variance; "
        "descriptive association only, never causal"
    )

    @property
    def trajectory(self) -> Tuple[Tuple[str, float, float], ...]:
        """Chronological (window_start, ndvi, moisture) triples."""
        return tuple((p.window_start, p.ndvi, p.moisture) for p in self.points)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "ndvi_key": self.ndvi_key,
            "moisture_key": self.moisture_key,
            "points": [p.to_dict() for p in self.points],
            "correlation": self.correlation,
            "n_paired": self.n_paired,
            "method": self.method,
        }


@dataclass(frozen=True)
class JointAnalysis:
    """Joint NDVI–moisture temporal analysis for one window."""

    ndvi_key: str
    moisture_key: str
    window_start: str
    window_end: str
    step: str
    joint: JointProfile
    changes: Tuple[JointChange, ...] = field(default_factory=tuple)
    lags: Tuple[LagResult, ...] = field(default_factory=tuple)
    scatter: Optional[ScatterDataset] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.4 API contract models."""
        return {
            "ndvi_key": self.ndvi_key,
            "moisture_key": self.moisture_key,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "joint": self.joint.to_dict(),
            "changes": [c.to_dict() for c in self.changes],
            "lags": [lag.to_dict() for lag in self.lags],
            "scatter": self.scatter.to_dict() if self.scatter is not None else None,
        }


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _check_pair(ndvi: TemporalProfile, moisture: TemporalProfile) -> None:
    """Enforce the joint layer's metric identities."""
    if ndvi.metric_key != NDVI_KEY:
        raise ValueError(
            f"Joint analysis requires {NDVI_KEY!r} greenness; "
            f"got {ndvi.metric_key!r}."
        )
    if moisture.metric_key not in SUPPORTED_MOISTURE_KEYS:
        supported = ", ".join(SUPPORTED_MOISTURE_KEYS)
        raise ValueError(
            f"Joint analysis requires a vegetation moisture proxy "
            f"({supported}); got {moisture.metric_key!r}.  The McFeeters "
            f"NDWI is an open-water index and is not accepted here — "
            f"use NDMI (Gao)."
        )


def _z_by_window(anomalies: Optional[AnomalyProfile]) -> Dict[str, Any]:
    if anomalies is None:
        return {}
    return {
        point.window_start: point
        for point in anomalies.points
        if _is_finite_number(point.z_score)
    }


def align_profiles(
    ndvi: TemporalProfile,
    moisture: TemporalProfile,
    ndvi_anomalies: Optional[AnomalyProfile] = None,
    moisture_anomalies: Optional[AnomalyProfile] = None,
) -> JointProfile:
    """Align two profiles by exact calendar-month window starts.

    The month union, sorted chronologically; each side present only
    where that profile actually emitted the month with a finite
    value.  No nearest-neighbour matching, no interpolation, no
    zero-filling: a side missing for a month is explicitly
    unavailable there.
    """
    _check_pair(ndvi, moisture)
    ndvi_by_month = {p.window_start: p for p in ndvi.points}
    moisture_by_month = {p.window_start: p for p in moisture.points}
    ndvi_z = _z_by_window(ndvi_anomalies)
    moisture_z = _z_by_window(moisture_anomalies)
    months = sorted(set(ndvi_by_month) | set(moisture_by_month))
    points: List[JointPoint] = []
    for month in months:
        ndvi_point = ndvi_by_month.get(month)
        moisture_point = moisture_by_month.get(month)
        ndvi_value = (
            float(ndvi_point.value)
            if ndvi_point is not None and _is_finite_number(ndvi_point.value)
            else None
        )
        moisture_value = (
            float(moisture_point.value)
            if moisture_point is not None and _is_finite_number(moisture_point.value)
            else None
        )
        if ndvi_value is not None and moisture_value is not None:
            availability = AVAILABLE_BOTH
        elif ndvi_value is not None:
            availability = AVAILABLE_NDVI_ONLY
        elif moisture_value is not None:
            availability = AVAILABLE_MOISTURE_ONLY
        else:
            availability = AVAILABLE_NEITHER
        end = (
            (ndvi_point or moisture_point).window_end  # type: ignore[union-attr]
            if (ndvi_point or moisture_point) is not None
            else month
        )
        points.append(
            JointPoint(
                window_start=month,
                window_end=end,
                ndvi=ndvi_value,
                moisture=moisture_value,
                ndvi_z=(
                    ndvi_z[month].z_score if month in ndvi_z else None
                ),
                moisture_z=(
                    moisture_z[month].z_score if month in moisture_z else None
                ),
                availability=availability,
                ndvi_quality=ndvi_point.quality if ndvi_point else "unavailable",
                moisture_quality=moisture_point.quality
                if moisture_point
                else "unavailable",
                ndvi_coverage=ndvi_point.coverage_percent
                if ndvi_point
                else None,
                moisture_coverage=moisture_point.coverage_percent
                if moisture_point
                else None,
            )
        )
    window_starts = [ndvi.window_start, moisture.window_start]
    window_ends = [ndvi.window_end, moisture.window_end]
    return JointProfile(
        ndvi_key=ndvi.metric_key,
        moisture_key=moisture.metric_key,
        window_start=min(window_starts),
        window_end=max(window_ends),
        step=ndvi.step,
        points=tuple(points),
    )


def joint_anomaly_state(
    ndvi_z: Optional[float], moisture_z: Optional[float]
) -> str:
    """Neutral joint category for one month's z-score pair.

    Sign-only on the existing null (zero means at-reference).
    Single-side readings report that side; opposing signs are
    MIXED; anything without a below-baseline signal anywhere
    observed is NEUTRAL; nothing observed at all is INSUFFICIENT.
    """
    ndvi_below = _is_finite_number(ndvi_z) and float(ndvi_z) < 0.0  # type: ignore[arg-type]
    moisture_below = _is_finite_number(moisture_z) and float(moisture_z) < 0.0  # type: ignore[arg-type]
    ndvi_above = _is_finite_number(ndvi_z) and float(ndvi_z) > 0.0  # type: ignore[arg-type]
    moisture_above = _is_finite_number(moisture_z) and float(moisture_z) > 0.0  # type: ignore[arg-type]
    if not _is_finite_number(ndvi_z) and not _is_finite_number(moisture_z):
        return JOINT_INSUFFICIENT
    if ndvi_below and moisture_below:
        return JOINT_BOTH_BELOW
    if ndvi_above and moisture_above:
        return JOINT_BOTH_ABOVE
    if (ndvi_below and moisture_above) or (ndvi_above and moisture_below):
        return JOINT_MIXED
    if ndvi_below:
        return JOINT_NDVI_BELOW
    if moisture_below:
        return JOINT_MOISTURE_BELOW
    return JOINT_NEUTRAL


def _joint_pattern(ndvi_direction: str, moisture_direction: str) -> str:
    """Neutral co-movement pattern for one pair of P1.3 directions."""
    if ndvi_direction == "INSUFFICIENT" or moisture_direction == "INSUFFICIENT":
        return PATTERN_INSUFFICIENT
    if ndvi_direction == "DECREASE" and moisture_direction == "DECREASE":
        return PATTERN_BOTH_DECREASE
    if ndvi_direction == "INCREASE" and moisture_direction == "INCREASE":
        return PATTERN_BOTH_INCREASE
    if ndvi_direction == "DECREASE" and moisture_direction == "STABLE":
        return PATTERN_NDVI_DOWN_MOISTURE_STABLE
    if ndvi_direction == "STABLE" and moisture_direction == "DECREASE":
        return PATTERN_NDVI_STABLE_MOISTURE_DOWN
    if ndvi_direction == "STABLE" and moisture_direction == "STABLE":
        return PATTERN_BOTH_STABLE
    return PATTERN_DIVERGENT


def divergence_of(pattern: str) -> str:
    """Per-month divergence descriptor for a joint-change pattern."""
    if pattern == PATTERN_BOTH_DECREASE:
        return DIVERGENCE_CONCURRENT_DECLINE
    if pattern == PATTERN_NDVI_STABLE_MOISTURE_DOWN:
        return DIVERGENCE_MOISTURE_DOWN_NDVI_STABLE
    if pattern == PATTERN_NDVI_DOWN_MOISTURE_STABLE:
        return DIVERGENCE_NDVI_DOWN_MOISTURE_STABLE
    if pattern == PATTERN_INSUFFICIENT:
        return DIVERGENCE_INSUFFICIENT
    return DIVERGENCE_NO_DIVERGENCE


def joint_changes(
    joint: JointProfile,
    ndvi_changes: Mapping[str, Any],
    moisture_changes: Mapping[str, Any],
) -> Tuple[JointChange, ...]:
    """Co-movement for consecutive joint months from P1.3 changes.

    Direction entries come from the two sides' ``MonthChange``
    records matched by exact window start — never recomputed here.
    A joint change exists only where both sides published a change
    for the same two windows; anything else is ``INSUFFICIENT``.
    """
    out: List[JointChange] = []
    for position, point in enumerate(joint.points):
        if position == 0:
            out.append(
                JointChange(
                    window_start=point.window_start,
                    window_end=point.window_end,
                )
            )
            continue
        previous = joint.points[position - 1]
        ndvi_change = ndvi_changes.get(point.window_start)
        moisture_change = moisture_changes.get(point.window_start)
        ndvi_ok = (
            ndvi_change is not None
            and getattr(ndvi_change, "previous_window_start", None)
            == previous.window_start
            and _is_finite_number(getattr(ndvi_change, "absolute_change", None))
        )
        moisture_ok = (
            moisture_change is not None
            and getattr(moisture_change, "previous_window_start", None)
            == previous.window_start
            and _is_finite_number(getattr(moisture_change, "absolute_change", None))
        )
        if not (ndvi_ok and moisture_ok):
            out.append(
                JointChange(
                    window_start=point.window_start,
                    window_end=point.window_end,
                    previous_window_start=previous.window_start,
                )
            )
            continue
        pattern = _joint_pattern(
            ndvi_change.direction, moisture_change.direction
        )
        try:
            days = (
                date.fromisoformat(point.window_start)
                - date.fromisoformat(previous.window_start)
            ).days
        except (ValueError, TypeError):
            days = None
        out.append(
            JointChange(
                window_start=point.window_start,
                window_end=point.window_end,
                previous_window_start=previous.window_start,
                ndvi_change=float(ndvi_change.absolute_change),
                moisture_change=float(moisture_change.absolute_change),
                ndvi_direction=ndvi_change.direction,
                moisture_direction=moisture_change.direction,
                pattern=pattern,
                divergence=divergence_of(pattern),
                days_elapsed=days,
            )
        )
    return tuple(out)


def pearson_correlation(values_x: List[float], values_y: List[float]) -> Optional[float]:
    """Pearson r over paired finite values.

    Refused below ``MIN_CORRELATION_PAIRS`` pairs, on length
    mismatch, on any non-finite input, or on zero variance either
    side.  A descriptive association number, never a causal claim.
    """
    if len(values_x) != len(values_y) or len(values_x) < MIN_CORRELATION_PAIRS:
        return None
    for value in list(values_x) + list(values_y):
        if not _is_finite_number(value):
            return None
    x = np.asarray(values_x, dtype=float)
    y = np.asarray(values_y, dtype=float)
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return None
    covariance = float(np.mean((x - np.mean(x)) * (y - np.mean(y))))
    denominator = float(np.std(x) * np.std(y))
    if denominator == 0.0:
        return None
    return covariance / denominator


def lead_lag_analysis(
    joint: JointProfile, max_lag_months: int = 2
) -> Tuple[LagResult, ...]:
    """Moisture-at-t versus NDVI-at-t-plus-lag agreement.

    Only explicit monthly lags 0..``max_lag_months`` are evaluated;
    no lag is privileged as biologically correct.  Pairs need finite
    z-scores on both sides; agreement counts matching nonzero signs
    plus jointly-at-reference months.  Correlation needs
    ``MIN_CORRELATION_PAIRS`` pairs.  Fewer than ``MIN_LAG_PAIRS``
    pairs makes the whole lag insufficient.
    """
    by_month = {point.window_start: point for point in joint.points}
    months = sorted(by_month)
    results: List[LagResult] = []
    for lag in range(max_lag_months + 1):
        paired_moisture: List[float] = []
        paired_ndvi: List[float] = []
        for position, month in enumerate(months):
            if position + lag >= len(months):
                continue
            current = by_month[month]
            later = by_month[months[position + lag]]
            if _is_finite_number(current.moisture_z) and _is_finite_number(
                later.ndvi_z
            ):
                paired_moisture.append(float(current.moisture_z))  # type: ignore[arg-type]
                paired_ndvi.append(float(later.ndvi_z))  # type: ignore[arg-type]
        n_paired = len(paired_moisture)
        if n_paired < MIN_LAG_PAIRS:
            results.append(LagResult(lag_months=lag, n_paired=n_paired))
            continue
        matches = sum(
            1
            for moisture_z, ndvi_z in zip(paired_moisture, paired_ndvi)
            if (moisture_z > 0 and ndvi_z > 0)
            or (moisture_z < 0 and ndvi_z < 0)
            or (moisture_z == 0.0 and ndvi_z == 0.0)
        )
        results.append(
            LagResult(
                lag_months=lag,
                n_paired=n_paired,
                agreement=matches / n_paired,
                correlation=pearson_correlation(paired_moisture, paired_ndvi),
                sufficient=True,
            )
        )
    return tuple(results)


def scatter_dataset(joint: JointProfile) -> ScatterDataset:
    """Paired months in chronological order plus one summary number."""
    points: List[ScatterPoint] = []
    for point in joint.points:
        if not _is_finite_number(point.ndvi) or not _is_finite_number(
            point.moisture
        ):
            continue
        points.append(
            ScatterPoint(
                window_start=point.window_start,
                ndvi=float(point.ndvi),  # type: ignore[arg-type]
                moisture=float(point.moisture),  # type: ignore[arg-type]
                ndvi_z=point.ndvi_z,
                moisture_z=point.moisture_z,
                ndvi_quality=point.ndvi_quality,
                moisture_quality=point.moisture_quality,
            )
        )
    return ScatterDataset(
        ndvi_key=joint.ndvi_key,
        moisture_key=joint.moisture_key,
        points=tuple(points),
        correlation=pearson_correlation(
            [p.ndvi for p in points], [p.moisture for p in points]
        ),
        n_paired=len(points),
    )


def analyze_joint(
    ndvi: TemporalProfile,
    moisture: TemporalProfile,
    ndvi_anomalies: Optional[AnomalyProfile] = None,
    moisture_anomalies: Optional[AnomalyProfile] = None,
    ndvi_changes: Optional[Any] = None,
    moisture_changes: Optional[Any] = None,
    max_lag_months: int = 2,
) -> JointAnalysis:
    """Full joint NDVI–moisture analysis for one window.

    Aligns the profiles, attaches anomalies by window, derives
    co-movement from supplied P1.3 change records (never recomputed),
    evaluates explicit monthly lags, and builds the chronological
    scatter/trajectory dataset.  Deterministic throughout.
    """
    joint = align_profiles(ndvi, moisture, ndvi_anomalies, moisture_anomalies)
    for label, anomalies, profile in (
        ("ndvi", ndvi_anomalies, ndvi),
        ("moisture", moisture_anomalies, moisture),
    ):
        if anomalies is not None and anomalies.metric_key != profile.metric_key:
            raise ValueError(
                f"Joint analysis miswired: {label} anomalies describe "
                f"{anomalies.metric_key!r} but the {label} profile is "
                f"{profile.metric_key!r}."
            )
    for label, changes, profile in (
        ("ndvi", ndvi_changes, ndvi),
        ("moisture", moisture_changes, moisture),
    ):
        if changes is not None and changes.metric_key != profile.metric_key:
            raise ValueError(
                f"Joint analysis miswired: {label} changes describe "
                f"{changes.metric_key!r} but the {label} profile is "
                f"{profile.metric_key!r}."
            )
    ndvi_map = (
        {c.window_start: c for c in ndvi_changes.changes}
        if ndvi_changes is not None
        else {}
    )
    moisture_map = (
        {c.window_start: c for c in moisture_changes.changes}
        if moisture_changes is not None
        else {}
    )
    return JointAnalysis(
        ndvi_key=joint.ndvi_key,
        moisture_key=joint.moisture_key,
        window_start=joint.window_start,
        window_end=joint.window_end,
        step=joint.step,
        joint=joint,
        changes=joint_changes(joint, ndvi_map, moisture_map),
        lags=lead_lag_analysis(joint, max_lag_months),
        scatter=scatter_dataset(joint),
    )
