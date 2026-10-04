"""Historical baselines and standardized anomalies over temporal profiles.

P1.2 layer for the Pest & Disease Early Warning work.  Domain-neutral
infrastructure only: this module detects statistical deviation from a
historical baseline.  It does NOT identify the cause of any
deviation.

Possible causes of a deviation include, but are not limited to:
phenology, weather, irrigation, management, sensor/coverage effects,
vegetation stress, pests, or disease.  None of those causes is
encoded here — there are no severity levels, no risk scores, no
probabilities, no ML, and no causal rules.

Statistical core (all reused, nothing re-derived):

* reference summary via :func:`history.compute_baseline` over the
  profile's usable months as one ``FULL_PERIOD`` group (the profile
  itself is the reference population; seasonal variants belong to a
  later phase, and folding the seasonal cycle into a full-period
  reference is stated on every output);
* z-scores via :func:`history.standardized_anomaly`, which refuses
  missing values and non-positive spreads;
* historical ranks via :func:`history.percentile_context`, which
  refuses small and degenerate populations.  Each observation is
  ranked against the *other* usable months (leave-one-out) so the
  ranked value is never a member of its own reference population,
  per the repository's percentile rule.

Sufficiency floors mirror the repository's existing policy: at
least :data:`MIN_PROFILE_BASELINE_N` usable months (the same floor
as :func:`history.compute_baseline`'s default and
:data:`history.MIN_BASELINE_GROUP`), and at least
:data:`PROFILE_PERCENTILE_MIN_SAMPLES` reference months for a rank
(the same rank-resolution rationale as the existing percentile
floor).  Zero variance makes the baseline insufficient: the mean of
a constant series carries no spread to standardize against, so no
z-score is manufactured from it.

Categories are sign-only on the z-score — zero is the null the
difference anomaly already defines ("indistinguishable from the
reference"), so no threshold is invented:

* ``NORMAL`` — z exactly zero;
* ``BELOW_BASELINE`` / ``ABOVE_BASELINE`` — negative / positive z;
* ``INSUFFICIENT_BASELINE`` — no z could be produced (missing
  observation, insufficient baseline, or zero variance).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.logging import get_logger
from app.services.agriculture.history import (
    BaselineStrategy,
    ObservationPoint,
    compute_baseline,
    percentile_context,
    standardized_anomaly,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    usable_values,
)

logger = get_logger(__name__)

__all__ = [
    "MIN_PROFILE_BASELINE_N",
    "PROFILE_PERCENTILE_MIN_SAMPLES",
    "CATEGORY_NORMAL",
    "CATEGORY_BELOW_BASELINE",
    "CATEGORY_ABOVE_BASELINE",
    "CATEGORY_INSUFFICIENT_BASELINE",
    "ProfileBaseline",
    "AnomalyPoint",
    "AnomalyProfile",
    "build_baseline",
    "score_profile",
    "classify_z",
]

#: Minimum usable months for a baseline.  Mirrors the repository's
#: universal floor (compute_baseline's default, MIN_BASELINE_GROUP).
MIN_PROFILE_BASELINE_N = 3

#: Relative tolerance below which a positive spread is treated as
#: zero variance.  Floating-point summation over many identical
#: monthly values can leave dust (~1e-16) instead of an exact zero;
#: standardizing against that dust manufactures extreme z-scores out
#: of noise (the hazard standardized_anomaly documents).  This is
#: numerical hygiene, not a statistical threshold: any real
#: month-to-month variation exceeds it by orders of magnitude.
NEAR_ZERO_SPREAD_REL_TOL = 1e-9
#: Minimum reference months for a percentile rank.  Same
#: rank-resolution rationale as the existing percentile floor: fewer
#: samples resolve the rank only in coarse steps.
PROFILE_PERCENTILE_MIN_SAMPLES = 8

#: Neutral statistical categories.  Directional only; no severity,
#: no cause, no risk level is encoded or implied.
CATEGORY_NORMAL = "NORMAL"
CATEGORY_BELOW_BASELINE = "BELOW_BASELINE"
CATEGORY_ABOVE_BASELINE = "ABOVE_BASELINE"
CATEGORY_INSUFFICIENT_BASELINE = "INSUFFICIENT_BASELINE"


@dataclass(frozen=True)
class ProfileBaseline:
    """Statistical reference for one temporal profile.

    Computed over usable months only; missing months lower the
    population but never enter it.  ``None`` is returned instead of
    this object whenever the reference is insufficient (too few
    usable months or zero variance), so no downstream z-score can be
    manufactured from it.
    """

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
    quality_counts: Dict[str, int] = field(default_factory=dict)
    mean_coverage_percent: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.2 API contract models."""
        return {
            "metric_key": self.metric_key,
            "strategy": self.strategy,
            "n_observations": self.n_observations,
            "n_usable": self.n_usable,
            "mean": self.mean,
            "std": self.std,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "median": self.median,
            "reference_start": self.reference_start,
            "reference_end": self.reference_end,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "spread_reliable": self.spread_reliable,
            "quality_counts": dict(self.quality_counts),
            "mean_coverage_percent": self.mean_coverage_percent,
        }


@dataclass(frozen=True)
class AnomalyPoint:
    """One profile observation scored against its baseline.

    Traceability fields (unit, quality, coverage, image count,
    window) are passed through untouched from the source
    observation.  ``z_score`` and ``percentile`` are ``None``
    whenever they could not be produced; ``category`` is then
    ``INSUFFICIENT_BASELINE``.
    """

    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    z_score: Optional[float] = None
    percentile: Optional[float] = None
    category: str = CATEGORY_INSUFFICIENT_BASELINE

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.2 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "z_score": self.z_score,
            "percentile": self.percentile,
            "category": self.category,
        }


@dataclass(frozen=True)
class AnomalyProfile:
    """A temporal profile with every observation scored, or refused."""

    metric_key: str
    unit: str
    window_start: str
    window_end: str
    step: str
    baseline: Optional[ProfileBaseline]
    points: Tuple[AnomalyPoint, ...] = field(default_factory=tuple)

    @property
    def n_scored(self) -> int:
        """Points carrying a z-score (all other points are gaps or refused)."""
        return sum(1 for point in self.points if point.z_score is not None)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.2 API contract models."""
        return {
            "metric_key": self.metric_key,
            "unit": self.unit,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "baseline": self.baseline.to_dict() if self.baseline is not None else None,
            "points": [point.to_dict() for point in self.points],
        }


def _is_usable_value(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _usable_entries(
    profile: TemporalProfile,
) -> List[Tuple[int, Any]]:
    """Indexed profile points carrying finite values, in order.

    The single canonical usable population: baseline statistics,
    quality summaries, reference members, and leave-one-out ranking
    all derive from this list, so they can never disagree about
    membership.
    """
    return [
        (index, point)
        for index, point in enumerate(profile.points)
        if _is_usable_value(point.value)
    ]


def _observation_points(profile: TemporalProfile) -> List[ObservationPoint]:
    """Usable profile months as reference observations.

    Monthly composites are dated to their window start, matching the
    repository's observation-point convention.  Missing months are
    absent, never zero.
    """
    return [
        ObservationPoint(
            day=date.fromisoformat(point.window_start),
            value=float(point.value),
        )
        for _, point in _usable_entries(profile)
    ]


def classify_z(z_score: Optional[float]) -> str:
    """Neutral category for a z-score.

    Sign-only: zero is the existing null ("indistinguishable from the
    reference").  A missing z-score — missing observation,
    insufficient baseline, or zero variance — is
    ``INSUFFICIENT_BASELINE``, never a fabricated normal.
    """
    if z_score is None or isinstance(z_score, bool):
        return CATEGORY_INSUFFICIENT_BASELINE
    if not isinstance(z_score, (int, float)) or not math.isfinite(z_score):
        return CATEGORY_INSUFFICIENT_BASELINE
    if z_score < 0.0:
        return CATEGORY_BELOW_BASELINE
    if z_score > 0.0:
        return CATEGORY_ABOVE_BASELINE
    return CATEGORY_NORMAL


def build_baseline(
    profile: TemporalProfile, min_n: int = MIN_PROFILE_BASELINE_N
) -> Optional[ProfileBaseline]:
    """Summarise a profile's usable months into a reference baseline.

    Core statistics come from :func:`history.compute_baseline`;
    minimum, maximum, median, and the quality/coverage summary are
    computed over the same usable population.  Returns ``None``
    when fewer than ``min_n`` months are usable or when the spread
    is missing or non-positive (zero variance carries no spread to
    standardize against).
    """
    usable = usable_values(profile)
    entries = _usable_entries(profile)
    members = _observation_points(profile)
    quality_counts: Dict[str, int] = {}
    coverages: List[float] = []
    for _, point in entries:
        quality_counts[point.quality] = quality_counts.get(point.quality, 0) + 1
        if isinstance(point.coverage_percent, (int, float)) and math.isfinite(
            point.coverage_percent
        ):
            coverages.append(float(point.coverage_percent))

    summary = compute_baseline(
        members, BaselineStrategy.FULL_PERIOD, "all", min_n=min_n
    )
    if summary is None:
        return None
    if (
        summary.std is None
        or not math.isfinite(summary.std)
        or summary.std <= 0.0
        or summary.std
        <= NEAR_ZERO_SPREAD_REL_TOL * max(1.0, abs(summary.mean))
    ):
        logger.warning(
            "Baseline for %s refused: %d usable month(s) with no usable "
            "spread; no z-score will be manufactured.",
            profile.metric_key,
            summary.n,
        )
        return None

    values = np.asarray(usable, dtype=float)
    reference_days = sorted(
        date.fromisoformat(point.window_start) for _, point in entries
    )
    return ProfileBaseline(
        metric_key=profile.metric_key,
        strategy=summary.strategy.value
        if hasattr(summary.strategy, "value")
        else str(summary.strategy),
        n_observations=profile.n_points,
        n_usable=summary.n,
        mean=summary.mean,
        std=summary.std,
        minimum=float(np.min(values)),
        maximum=float(np.max(values)),
        median=float(np.median(values)),
        reference_start=reference_days[0].isoformat(),
        reference_end=reference_days[-1].isoformat(),
        window_start=profile.window_start,
        window_end=profile.window_end,
        spread_reliable=summary.spread_reliable,
        quality_counts=quality_counts,
        mean_coverage_percent=(
            float(sum(coverages) / len(coverages)) if coverages else None
        ),
    )


def _score_point(
    point: Any,
    population: List[ObservationPoint],
    baseline: ProfileBaseline,
) -> AnomalyPoint:
    """Score one profile month against a sufficient baseline."""
    base = {
        "window_start": point.window_start,
        "window_end": point.window_end,
        "value": point.value,
        "unit": point.unit,
        "quality": point.quality,
        "coverage_percent": point.coverage_percent,
        "image_count": point.image_count,
    }
    if point.value is None:
        return AnomalyPoint(**base)
    z_score = standardized_anomaly(point.value, baseline.mean, baseline.std)
    if z_score is None:
        return AnomalyPoint(**base)
    context = percentile_context(
        point.value, population, PROFILE_PERCENTILE_MIN_SAMPLES
    )
    return AnomalyPoint(
        **base,
        z_score=z_score,
        percentile=context.percentile if context is not None else None,
        category=classify_z(z_score),
    )


def score_profile(profile: TemporalProfile) -> AnomalyProfile:
    """Score every month of a profile against its own baseline.

    The baseline is built from the profile's usable months; each
    usable month is then standardized against it and ranked against
    the other usable months (leave-one-out, so a value never ranks
    within a population containing itself).  Missing months and
    insufficient baselines yield ``INSUFFICIENT_BASELINE`` points
    with no z-score — deviation is reported only where the
    statistics support it.
    """
    baseline = build_baseline(profile)
    if baseline is None:
        return AnomalyProfile(
            metric_key=profile.metric_key,
            unit=profile.unit,
            window_start=profile.window_start,
            window_end=profile.window_end,
            step=profile.step,
            baseline=None,
            points=tuple(
                AnomalyPoint(
                    window_start=point.window_start,
                    window_end=point.window_end,
                    value=point.value,
                    unit=point.unit,
                    quality=point.quality,
                    coverage_percent=point.coverage_percent,
                    image_count=point.image_count,
                )
                for point in profile.points
            ),
        )

    members = _observation_points(profile)
    member_by_index = {
        index: member
        for (index, _), member in zip(_usable_entries(profile), members)
    }
    scored: List[AnomalyPoint] = []
    for index, point in enumerate(profile.points):
        member = member_by_index.get(index)
        if member is None:
            # No usable observation for this month (gap or non-finite
            # value): the stored value passes through untouched and the
            # default category refuses it.  Nothing is coerced to zero.
            scored.append(
                AnomalyPoint(
                    window_start=point.window_start,
                    window_end=point.window_end,
                    value=point.value,
                    unit=point.unit,
                    quality=point.quality,
                    coverage_percent=point.coverage_percent,
                    image_count=point.image_count,
                )
            )
            continue
        population = [m for m in members if m is not member]
        scored.append(_score_point(point, population, baseline))

    return AnomalyProfile(
        metric_key=profile.metric_key,
        unit=profile.unit,
        window_start=profile.window_start,
        window_end=profile.window_end,
        step=profile.step,
        baseline=baseline,
        points=tuple(scored),
    )
