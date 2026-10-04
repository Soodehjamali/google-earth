"""Thermal anomaly and change analysis (P4.3).

Descriptive historical anomaly, temporal change, persistence, and
rapid-change information for the two P4.2 thermal quantities, each
strictly independent:

* ``LST_PROFILE`` — land-surface / skin temperature from
  ``MODIS/061/MOD11A2`` via ``land_surface_temperature_day``.
* ``AIR_TEMPERATURE_PROFILE`` — modelled 2 m air temperature from
  ``ECMWF/ERA5_LAND/DAILY_AGGR`` via ``temperature_mean``.

This is an observational/statistical layer only. An anomaly here
means "different from the historical reference population". It
does not mean canopy temperature, thermal stress, heat stress,
pest load, disease, water stress, or any other biological or
agronomic state.

Reused machinery (nothing re-derived, no formula restated):

* P4.2 source profiles are adapted to the generic
  :class:`TemporalProfile` shape field-for-field (windows, values,
  units, quality, coverage, image counts pass through untouched);
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
  serialized: breakpoint detection stays out of scope.

Separation rule: each source keeps its own baseline population in
its own unit (degC on both sides, but different physical
quantities). Populations are never pooled, no shared mean or
spread is ever computed, and no combined score is produced. A
harmonized P4.2 object, if involved at all, is temporal alignment
only: each side is analyzed from its own source profile.

Missing data: months without usable values stay missing through
every layer — no interpolation, no zero-fill, no silent deletion,
no window shifting. Unavailable and insufficient months are never
promoted into statistics. Insufficient baselines (too few usable
months, zero or near-zero spread exactly per the P1.2 hardened
behavior) yield ``INSUFFICIENT_BASELINE`` points with no z-score,
and the refusal reason is recorded rather than fabricated.

Non-goals of this phase: cause attribution, cut-off values of any
kind, severity or risk scoring, probabilities, model inference,
canopy-temperature inference, LST-air differencing, breakpoint
output, new datasets, new GEE computation, endpoints, charts, and
cache changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.baseline_anomaly import (
    MIN_PROFILE_BASELINE_N,
    AnomalyProfile,
    ProfileBaseline,
    score_profile,
)
from app.services.agriculture.change_profile import (
    DeviationPersistence,
    MonthChange,
    analyze_changes,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)
from app.services.agriculture.thermal_profile import (
    AIR_METRIC_KEY,
    LST_METRIC_KEY,
    PHYSICAL_QUANTITY_AIR,
    PHYSICAL_QUANTITY_LST,
    SUPPORTED_THERMAL_PROFILE_METRICS,
    THERMAL_PROFILE_KIND_AIR,
    THERMAL_PROFILE_KIND_LST,
    ThermalSourceProfile,
)

logger = get_logger(__name__)

__all__ = [
    "SUPPORTED_THERMAL_ANOMALY_METRICS",
    "DERIVATION_OBSERVED",
    "DERIVATION_BASELINE",
    "DERIVATION_ANOMALY",
    "DERIVATION_CHANGE",
    "METHOD_BASELINE",
    "METHOD_ANOMALY",
    "METHOD_CHANGE",
    "METHOD_PERSISTENCE",
    "REFUSAL_INSUFFICIENT_MONTHS",
    "REFUSAL_NEAR_ZERO_SPREAD",
    "ThermalMetricAnalysis",
    "ThermalPairAnalysis",
    "to_temporal_profile",
    "analyze_thermal_metric",
    "analyze_thermal_pair",
    "usable_months",
]

#: Metrics eligible for thermal anomaly/change analysis: exactly the
#: two production-supported P4.2 thermal quantities. Identity and
#: unit travel with each analysis; substitution is refused, not guessed.
SUPPORTED_THERMAL_ANOMALY_METRICS: Tuple[str, ...] = tuple(
    SUPPORTED_THERMAL_PROFILE_METRICS
)

#: How each serialized section was derived. Stored on the payload
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

#: Recorded refusal reasons when no baseline can be built. The
#: statistics layer returns ``None``; the reason below says why, in
#: the layer's own terms, so a reader never meets a bare null.
REFUSAL_INSUFFICIENT_MONTHS = "insufficient_usable_months"
REFUSAL_NEAR_ZERO_SPREAD = "near_zero_spread"


@dataclass(frozen=True)
class ThermalMetricAnalysis:
    """Baseline, anomaly, change, and persistence for one quantity.

    The analysis holds the source P4.2 profile, the generic anomaly
    profile scored from it, and the generic change record. All three
    share the quantity's own unit and population; nothing is pooled
    across quantities and no combined score exists.
    """

    profile_kind: str
    physical_quantity: str
    physical_quantity_label: str
    metric_key: str
    dataset_id: Optional[str]
    band: str
    measurement_basis: str
    unit: str
    window_start: str
    window_end: str
    step: str
    source: ThermalSourceProfile
    anomalies: AnomalyProfile
    changes: Tuple[MonthChange, ...] = field(default_factory=tuple)
    persistence: DeviationPersistence = field(
        default_factory=DeviationPersistence
    )
    baseline_refusal_reason: Optional[str] = None

    @property
    def baseline(self) -> Optional[ProfileBaseline]:
        """The P1.2 reference population, or ``None`` when refused."""
        return self.anomalies.baseline

    def _thermal_provenance_by_window(self) -> Dict[str, Dict[str, Any]]:
        return {
            point.window_start: dict(point.provenance)
            for point in self.source.points
        }

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        thermal_by_window = self._thermal_provenance_by_window()
        anomalies = []
        for point in self.anomalies.points:
            entry = point.to_dict()
            entry["derivation"] = DERIVATION_ANOMALY
            entry["profile_kind"] = self.profile_kind
            entry["physical_quantity"] = self.physical_quantity
            entry["thermal_provenance"] = thermal_by_window.get(
                point.window_start, {}
            )
            anomalies.append(entry)
        changes = []
        for change in self.changes:
            entry = change.to_dict()
            entry["derivation"] = DERIVATION_CHANGE
            entry["profile_kind"] = self.profile_kind
            entry["physical_quantity"] = self.physical_quantity
            entry["thermal_provenance"] = thermal_by_window.get(
                change.window_start, {}
            )
            changes.append(entry)
        return {
            "profile_kind": self.profile_kind,
            "physical_quantity": self.physical_quantity,
            "physical_quantity_label": self.physical_quantity_label,
            "metric_key": self.metric_key,
            "dataset_id": self.dataset_id,
            "band": self.band,
            "measurement_basis": self.measurement_basis,
            "unit": self.unit,
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
            "baseline_refusal_reason": self.baseline_refusal_reason,
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

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalMetricAnalysis":
        """Rebuild an analysis from :meth:`to_dict` output."""
        from app.services.agriculture.baseline_anomaly import AnomalyPoint
        from app.services.agriculture.change_profile import MonthChange

        baseline_payload = payload.get("baseline")
        baseline = None
        if baseline_payload is not None:
            items = dict(baseline_payload)
            items.pop("derivation", None)
            baseline = ProfileBaseline(**items)
        anomalies_payload = payload.get("anomalies") or ()
        anomaly_points = []
        for item in anomalies_payload:
            entry = dict(item)
            entry.pop("derivation", None)
            entry.pop("profile_kind", None)
            entry.pop("physical_quantity", None)
            entry.pop("thermal_provenance", None)
            anomaly_points.append(AnomalyPoint(**entry))
        changes_payload = payload.get("changes") or ()
        month_changes = []
        for item in changes_payload:
            entry = dict(item)
            entry.pop("derivation", None)
            entry.pop("profile_kind", None)
            entry.pop("physical_quantity", None)
            entry.pop("thermal_provenance", None)
            month_changes.append(MonthChange(**entry))
        persistence_payload = dict(payload.get("persistence") or {})
        persistence_payload.pop("derivation", None)
        observed_payload = payload.get("observed") or {}
        source = ThermalSourceProfile.from_dict(
            {
                "profile_kind": payload.get("profile_kind", ""),
                "metric_key": payload.get("metric_key", ""),
                "dataset_id": payload.get("dataset_id"),
                "fallback_dataset_id": None,
                "band": payload.get("band", ""),
                "unit": payload.get("unit", ""),
                "physical_quantity": payload.get("physical_quantity", ""),
                "physical_quantity_label": payload.get(
                    "physical_quantity_label", ""
                ),
                "measurement_basis": payload.get("measurement_basis", ""),
                "temporal_resolution": "",
                "aggregation_method": "",
                "window_start": payload.get("window_start", ""),
                "window_end": payload.get("window_end", ""),
                "step": payload.get("step", ""),
                "limitations": (),
                "points": observed_payload.get("points") or (),
            }
        )
        return cls(
            profile_kind=payload.get("profile_kind", ""),
            physical_quantity=payload.get("physical_quantity", ""),
            physical_quantity_label=payload.get(
                "physical_quantity_label", ""
            ),
            metric_key=payload.get("metric_key", ""),
            dataset_id=payload.get("dataset_id"),
            band=payload.get("band", ""),
            measurement_basis=payload.get("measurement_basis", ""),
            unit=payload.get("unit", ""),
            window_start=payload.get("window_start", ""),
            window_end=payload.get("window_end", ""),
            step=payload.get("step", ""),
            source=source,
            anomalies=AnomalyProfile(
                metric_key=payload.get("metric_key", ""),
                unit=payload.get("unit", ""),
                window_start=payload.get("window_start", ""),
                window_end=payload.get("window_end", ""),
                step=payload.get("step", ""),
                baseline=baseline,
                points=tuple(anomaly_points),
            ),
            changes=tuple(month_changes),
            persistence=DeviationPersistence(**persistence_payload)
            if persistence_payload
            else DeviationPersistence(),
            baseline_refusal_reason=payload.get("baseline_refusal_reason"),
        )


@dataclass(frozen=True)
class ThermalPairAnalysis:
    """Two independent quantity analyses sharing only calendar alignment.

    ``lst`` and ``air`` are each a complete
    :class:`ThermalMetricAnalysis` over their own baseline
    population. The pair carries no pooled statistic, no combined
    score, and no cross-quantity difference: the harmonized month is
    temporal alignment only.
    """

    lst: ThermalMetricAnalysis
    air: ThermalMetricAnalysis
    alignment: str = "calendar_month"
    alignment_method: str = (
        "P4.2 monthly profiles paired by calendar month; each side "
        "analyzed independently by P1.2/P1.3 over its own population"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "lst": self.lst.to_dict(),
            "air": self.air.to_dict(),
            "alignment": self.alignment,
            "alignment_method": self.alignment_method,
            "limitations": list(_PAIR_LIMITATIONS),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalPairAnalysis":
        """Rebuild a pair from :meth:`to_dict` output."""
        return cls(
            lst=ThermalMetricAnalysis.from_dict(payload["lst"]),
            air=ThermalMetricAnalysis.from_dict(payload["air"]),
            alignment=payload.get("alignment", "calendar_month"),
            alignment_method=payload.get("alignment_method", ""),
        )


_ANALYSIS_LIMITATIONS: Tuple[str, ...] = (
    "Thermal anomalies describe statistical deviation from the "
    "historical baseline for this quantity only; they do not "
    "identify a biological cause.",
    "LST analysis is land-surface / skin temperature deviation and "
    "is NOT canopy temperature; ERA5 analysis is modelled 2 m air "
    "temperature deviation and is NOT canopy temperature. Neither "
    "is a biological measure.",
    "Each quantity keeps an independent baseline population. "
    "Populations are never pooled and no combined score is produced.",
    "A persistent deviation is still only a persistent statistical "
    "deviation from the historical baseline.",
)

_PAIR_LIMITATIONS: Tuple[str, ...] = (
    "The two sides share calendar alignment only. LST remains "
    "land-surface / skin temperature; ERA5 remains modelled 2 m air "
    "temperature.",
    "No pooled baseline, no shared spread, no combined score, and no "
    "LST-air difference is computed or implied.",
)


def to_temporal_profile(profile: ThermalSourceProfile) -> TemporalProfile:
    """Adapt a P4.2 thermal source profile to the generic shape.

    Windows, values, units, quality, coverage, and image counts pass
    through untouched (missing months stay missing), so the generic
    P1.2/P1.3 machinery consumes the series without any new
    statistical engine. Nothing is scored here; adaptation is not
    analysis.

    Raises:
        ValueError: when the profile's metric is not a supported
            thermal quantity. No substitution is ever performed.
    """
    if profile.metric_key not in SUPPORTED_THERMAL_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_THERMAL_PROFILE_METRICS))
        raise ValueError(
            f"Thermal anomaly analysis is not supported for "
            f"{profile.metric_key!r}. Supported thermal metrics: "
            f"{supported}."
        )
    return TemporalProfile(
        metric_key=profile.metric_key,
        dataset_id=profile.dataset_id,
        unit=profile.unit,
        window_start=profile.window_start,
        window_end=profile.window_end,
        step=profile.step,
        points=tuple(
            TemporalProfilePoint(
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


def _refusal_reason(adapted: TemporalProfile) -> Optional[str]:
    """Name why no baseline exists, using the layer's own terms."""
    n_usable = adapted.n_usable
    if n_usable >= MIN_PROFILE_BASELINE_N:
        return REFUSAL_NEAR_ZERO_SPREAD
    return REFUSAL_INSUFFICIENT_MONTHS


def analyze_thermal_metric(
    source_profile: ThermalSourceProfile,
) -> ThermalMetricAnalysis:
    """Score one thermal source profile with generic P1.2/P1.3 machinery.

    The source profile is adapted to the generic shape, scored by
    :func:`score_profile`, and stepped by :func:`analyze_changes`
    (whose breakpoint output is discarded — breakpoint detection
    stays out of scope). The quantity's identity, unit, physical
    quantity, and population pass through untouched.

    Raises:
        ValueError: when the profile's metric is not a supported
            thermal quantity. No substitution is ever performed.
    """
    metric_key = source_profile.metric_key
    if metric_key not in SUPPORTED_THERMAL_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_THERMAL_PROFILE_METRICS))
        raise ValueError(
            f"Thermal anomaly analysis is not supported for "
            f"{metric_key!r}. Supported thermal metrics: {supported}."
        )
    adapted = to_temporal_profile(source_profile)
    anomalies = score_profile(adapted)
    change_record = analyze_changes(adapted, anomalies)
    logger.info(
        "Thermal anomaly analysis for %s: %d usable month(s), "
        "baseline %s, %d scored point(s).",
        metric_key,
        adapted.n_usable,
        "present" if anomalies.baseline is not None else "refused",
        anomalies.n_scored,
    )
    if metric_key == LST_METRIC_KEY:
        physical_quantity = PHYSICAL_QUANTITY_LST
        label = "land-surface / skin temperature"
    else:
        physical_quantity = PHYSICAL_QUANTITY_AIR
        label = "modelled 2 m air temperature"
    probe = SUPPORTED_THERMAL_PROFILE_METRICS[metric_key]()
    return ThermalMetricAnalysis(
        profile_kind=source_profile.profile_kind,
        physical_quantity=physical_quantity,
        physical_quantity_label=label,
        metric_key=metric_key,
        dataset_id=source_profile.dataset_id,
        band=source_profile.band,
        measurement_basis=probe.measurement_basis.value,
        unit=source_profile.unit,
        window_start=source_profile.window_start,
        window_end=source_profile.window_end,
        step=source_profile.step,
        source=source_profile,
        anomalies=anomalies,
        changes=tuple(change_record.changes),
        persistence=change_record.persistence,
        baseline_refusal_reason=(
            None
            if anomalies.baseline is not None
            else _refusal_reason(adapted)
        ),
    )


def analyze_thermal_pair(
    lst_profile: ThermalSourceProfile,
    air_profile: ThermalSourceProfile,
) -> ThermalPairAnalysis:
    """Analyze an LST profile and an air-temperature profile independently.

    Each side keeps its own baseline population, spread, ranks,
    changes, and persistence. The pair shares calendar alignment
    and nothing else.

    Raises:
        ValueError: when either profile is not the expected thermal
            source kind. A swapped or foreign profile refuses the
            whole pair rather than being skipped or substituted.
    """
    if lst_profile.profile_kind != THERMAL_PROFILE_KIND_LST:
        raise ValueError(
            f"Thermal pair analysis expects an "
            f"{THERMAL_PROFILE_KIND_LST} profile for lst, got "
            f"{lst_profile.profile_kind!r}."
        )
    if air_profile.profile_kind != THERMAL_PROFILE_KIND_AIR:
        raise ValueError(
            f"Thermal pair analysis expects an "
            f"{THERMAL_PROFILE_KIND_AIR} profile for air, got "
            f"{air_profile.profile_kind!r}."
        )
    if lst_profile.metric_key != LST_METRIC_KEY:
        raise ValueError(
            f"Thermal pair analysis expects {LST_METRIC_KEY!r} for lst, "
            f"got {lst_profile.metric_key!r}."
        )
    if air_profile.metric_key != AIR_METRIC_KEY:
        raise ValueError(
            f"Thermal pair analysis expects {AIR_METRIC_KEY!r} for air, "
            f"got {air_profile.metric_key!r}."
        )
    return ThermalPairAnalysis(
        lst=analyze_thermal_metric(lst_profile),
        air=analyze_thermal_metric(air_profile),
    )


def usable_months(analysis: ThermalMetricAnalysis) -> List[float]:
    """Finite monthly values behind an analysis, in order (hook)."""
    from app.services.agriculture.thermal_profile import usable_values

    return usable_values(analysis.source)


def analyze_thermal_set(
    source_profiles: Sequence[ThermalSourceProfile],
) -> Tuple[ThermalMetricAnalysis, ...]:
    """Analyze several thermal source profiles, each strictly independently.

    Input order is preserved. Every profile must name a supported
    thermal metric; an unsupported entry refuses the whole set
    rather than being skipped or substituted, so a caller can never
    receive a silently partial multi-quantity answer.
    """
    for source_profile in source_profiles:
        if source_profile.metric_key not in SUPPORTED_THERMAL_PROFILE_METRICS:
            supported = ", ".join(sorted(SUPPORTED_THERMAL_PROFILE_METRICS))
            raise ValueError(
                f"Thermal anomaly analysis is not supported for "
                f"{source_profile.metric_key!r}. Supported thermal "
                f"metrics: {supported}."
            )
    return tuple(
        analyze_thermal_metric(source_profile)
        for source_profile in source_profiles
    )
