"""Radar anomaly and change foundation (P2.4).

Statistical deviation and month-to-month change over the P2.3
monthly Sentinel-1 profiles, computed exclusively with the
existing generic temporal-statistical machinery.  No radar-specific
statistical engine exists here: every number below comes out of a
P1.2 or P1.3 function.

Radar anomaly means "different from the historical reference
population".  It does not mean pest load, disease severity,
defoliation, canopy health, or any other biological state.

Radar backscatter is not a direct measurement of leaf water, pest
load, disease severity, or canopy health.  Temporal deviations can
be caused by vegetation structure and biomass, soil moisture,
surface roughness, incidence angle, acquisition geometry,
management, phenology, precipitation, and other environmental or
processing factors.  VV, VH, VH/VV, and RVI anomalies therefore
describe statistical deviation in radar observations, never a
biological diagnosis — and a persistent negative anomaly is still
only a persistent deviation from the historical radar baseline.
Any future biological interpretation must rest on multi-sensor
evidence and, ultimately, ground-truth validation.

Reused machinery (nothing re-derived, no formula restated):

* P2.3 :func:`to_temporal_profile` adapts a radar profile to the
  generic profile shape with zero mismatch, so no new adapter was
  needed;
* P1.2 :func:`score_profile` — internally
  :func:`history.compute_baseline` (mean, sample spread, min, max,
  median over usable months, minimum-population floor),
  :func:`history.standardized_anomaly` (z-scores),
  :func:`history.percentile_context` (leave-one-out ranks), and
  :func:`baseline_anomaly.classify_z` (NORMAL / BELOW_BASELINE /
  ABOVE_BASELINE / INSUFFICIENT_BASELINE);
* P1.3 :func:`analyze_changes` — internally
  :func:`month_changes` (absolute / relative / per-day steps with
  the one-month gap allowance, P1.3 direction and rapid-change
  labels against the baseline spread when one exists) and
  :func:`persistence_of` (deviation runs over z-scores with the
  established minimum run length; gaps and ties break runs).
  The bundled breakpoint output is discarded and never
  serialized: breakpoint detection remains out of scope.

Unit rule: every calculation runs in the metric's own output
unit — decibels for vv, vh, and vh_vv, ratio for rvi.  No
decibel-to-linear conversion is performed for statistics, because
no metric contract defines another statistical domain.  Each of
the four metrics keeps a strictly independent baseline
population; populations are never pooled and no overall score is
produced (multi-metric concordance belongs to a later phase).

Missing data: months without usable values stay missing through
every layer — no interpolation, no zero-fill, no silent deletion,
no window shifting.  Insufficient baselines (too few usable
months, zero or near-zero spread exactly per the P1.2 hardened
behavior) yield ``INSUFFICIENT_BASELINE`` points with no z-score.

Non-goals of this phase: cause attribution, cut-off values of any
kind, probabilistic or risk scoring, model inference, breakpoint
output, thermal inputs, new datasets, endpoints, charts, and
cache changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.baseline_anomaly import (
    AnomalyProfile,
    ProfileBaseline,
    score_profile,
)
from app.services.agriculture.change_profile import (
    DeviationPersistence,
    MonthChange,
    analyze_changes,
)
from app.services.agriculture.radar_profile import (
    SUPPORTED_RADAR_PROFILE_METRICS,
    RadarProfile,
    to_temporal_profile,
    usable_values,
)

logger = get_logger(__name__)

__all__ = [
    "SUPPORTED_RADAR_ANOMALY_METRICS",
    "RadarMetricAnalysis",
    "analyze_radar_metric",
    "analyze_radar_set",
    "usable_months",
]

#: Metrics eligible for radar anomaly/change analysis: exactly the
#: four production-supported P2.3 radar metrics.  Identity and unit
#: travel with each analysis; substitution is refused, not guessed.
SUPPORTED_RADAR_ANOMALY_METRICS: Tuple[str, ...] = tuple(
    SUPPORTED_RADAR_PROFILE_METRICS
)

#: How each serialized section was derived.  Stored on the payload
#: so a reader can tell observation from statistics at a glance.
DERIVATION_OBSERVED = "observed"
DERIVATION_BASELINE = "baseline-derived"
DERIVATION_ANOMALY = "anomaly-derived"
DERIVATION_CHANGE = "change-derived"

#: Statistical methods named in provenance, pointing at the generic
#: implementations rather than restating them.
METHOD_BASELINE = (
    "P1.2 build_baseline over usable monthly values "
    "(history.compute_baseline; minimum-population floor and "
    "near-zero-spread refusal per P1.2)"
)
METHOD_ANOMALY = (
    "P1.2 score_profile (history.standardized_anomaly z-scores, "
    "history.percentile_context leave-one-out ranks, neutral "
    "baseline categories)"
)
METHOD_CHANGE = (
    "P1.3 month_changes via analyze_changes (absolute, relative, "
    "and per-day steps; P1.3 direction and rapid-change labels; "
    "one-month gap allowance)"
)
METHOD_PERSISTENCE = (
    "P1.3 persistence_of via analyze_changes (deviation runs over "
    "z-scores; established minimum run length; gaps and ties "
    "break runs)"
)


@dataclass(frozen=True)
class RadarMetricAnalysis:
    """Baseline, anomaly, change, and persistence for one radar metric.

    The analysis holds the source P2.3 profile, the generic
    anomaly profile scored from it, and the generic change record.
    All three share the metric's own unit and population; nothing
    is pooled across metrics.
    """

    metric_key: str
    unit: str
    dataset_id: str | None
    polarizations: Tuple[str, ...]
    mode: str
    orbit_pass: str
    scale_m: int
    window_start: str
    window_end: str
    step: str
    source: RadarProfile
    anomalies: AnomalyProfile
    changes: Tuple[MonthChange, ...] = field(default_factory=tuple)
    persistence: DeviationPersistence = field(
        default_factory=DeviationPersistence
    )

    @property
    def baseline(self) -> ProfileBaseline | None:
        """The P1.2 reference population, or ``None`` when refused."""
        return self.anomalies.baseline

    def _radar_provenance_by_window(self) -> Dict[str, Dict[str, Any]]:
        return {
            point.window_start: dict(point.provenance)
            for point in self.source.points
        }

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.4 API contract models."""
        radar_by_window = self._radar_provenance_by_window()
        anomalies = []
        for point in self.anomalies.points:
            entry = point.to_dict()
            entry["derivation"] = DERIVATION_ANOMALY
            entry["radar_provenance"] = radar_by_window.get(
                point.window_start, {}
            )
            anomalies.append(entry)
        changes = []
        for change in self.changes:
            entry = change.to_dict()
            entry["derivation"] = DERIVATION_CHANGE
            entry["radar_provenance"] = radar_by_window.get(
                change.window_start, {}
            )
            changes.append(entry)
        return {
            "metric_key": self.metric_key,
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "polarizations": list(self.polarizations),
            "mode": self.mode,
            "orbit_pass": self.orbit_pass,
            "scale_m": self.scale_m,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "observed": {
                "derivation": DERIVATION_OBSERVED,
                "points": [
                    point.to_dict() for point in self.source.points
                ],
            },
            "baseline": (
                {
                    "derivation": DERIVATION_BASELINE,
                    **self.baseline.to_dict(),
                }
                if self.baseline is not None
                else None
            ),
            "anomalies": anomalies,
            "changes": changes,
            "persistence": {
                "derivation": DERIVATION_CHANGE,
                **self.persistence.to_dict(),
            },
            "methods": {
                "baseline": METHOD_BASELINE,
                "anomaly": METHOD_ANOMALY,
                "change": METHOD_CHANGE,
                "persistence": METHOD_PERSISTENCE,
            },
            "limitations": list(_ANALYSIS_LIMITATIONS),
        }


_ANALYSIS_LIMITATIONS: Tuple[str, ...] = (
    "Radar anomalies describe statistical deviation from the "
    "historical radar baseline for this metric only; they do not "
    "identify a biological cause.",
    "Each metric keeps an independent baseline population in its "
    "own unit (decibels for vv, vh, vh_vv; ratio for rvi). "
    "Populations are never pooled.",
    "A persistent negative anomaly is still only a persistent "
    "deviation from the historical radar baseline.",
    "Acquisition, geometry, incidence-angle, and seasonality "
    "effects enter every value; future interpretation must "
    "combine radar with other evidence and ground-truth validation.",
)


def analyze_radar_metric(radar_profile: RadarProfile) -> RadarMetricAnalysis:
    """Score one radar profile with the generic P1.2/P1.3 machinery.

    The P2.3 profile is adapted to the generic shape, scored by
    :func:`score_profile`, and stepped by :func:`analyze_changes`
    (whose breakpoint output is discarded — breakpoint detection
    stays out of scope).  The metric's identity, unit, and
    population pass through untouched.

    Raises:
        ValueError: when the profile's metric is not one of the
            four supported radar metrics.  No substitution is ever
            performed.
    """
    metric_key = radar_profile.metric_key
    if metric_key not in SUPPORTED_RADAR_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_RADAR_PROFILE_METRICS))
        raise ValueError(
            f"Radar anomaly analysis is not supported for "
            f"{metric_key!r}. Supported radar metrics: {supported}."
        )
    adapted = to_temporal_profile(radar_profile)
    anomalies = score_profile(adapted)
    change_record = analyze_changes(adapted, anomalies)
    logger.info(
        "Radar anomaly analysis for %s: %d usable month(s), "
        "baseline %s, %d scored point(s).",
        metric_key,
        adapted.n_usable,
        "present" if anomalies.baseline is not None else "refused",
        anomalies.n_scored,
    )
    return RadarMetricAnalysis(
        metric_key=metric_key,
        unit=radar_profile.unit,
        dataset_id=radar_profile.dataset_id,
        polarizations=tuple(radar_profile.polarizations),
        mode=radar_profile.mode,
        orbit_pass=radar_profile.orbit_pass,
        scale_m=radar_profile.scale_m,
        window_start=radar_profile.window_start,
        window_end=radar_profile.window_end,
        step=radar_profile.step,
        source=radar_profile,
        anomalies=anomalies,
        changes=tuple(change_record.changes),
        persistence=change_record.persistence,
    )


def analyze_radar_set(
    radar_profiles: Sequence[RadarProfile],
) -> Tuple[RadarMetricAnalysis, ...]:
    """Analyze several radar profiles, each strictly independently.

    Input order is preserved.  Every profile must name a supported
    radar metric; an unsupported entry refuses the whole set rather
    than being skipped or substituted, so a caller can never
    receive a silently partial multi-metric answer.
    """
    for radar_profile in radar_profiles:
        if radar_profile.metric_key not in SUPPORTED_RADAR_PROFILE_METRICS:
            supported = ", ".join(
                sorted(SUPPORTED_RADAR_PROFILE_METRICS)
            )
            raise ValueError(
                f"Radar anomaly analysis is not supported for "
                f"{radar_profile.metric_key!r}. Supported radar "
                f"metrics: {supported}."
            )
    return tuple(
        analyze_radar_metric(radar_profile)
        for radar_profile in radar_profiles
    )


def usable_months(analysis: RadarMetricAnalysis) -> List[float]:
    """Finite monthly values behind an analysis, in order (hook)."""
    return usable_values(analysis.source)
