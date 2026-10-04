"""Middle-Canopy Dryness Proxy (Phase CD-4).

A multi-sensor evidence-concordance proxy answering one question:

"Do independent optical moisture/stress signals show deterioration,
while radar structural signals provide compatible canopy evidence,
within the same analysis context?"

Components (all computed on the proxy's own requested window):

* optical: ``ndmi_anomaly``, ``msi_anomaly``, ``ndre_anomaly``
  (seasonal anomalies from Phase CD-2; sign semantics established
  there: for a difference anomaly, zero already means
  "indistinguishable from the reference")
* radar: ``vv``, ``vh``, ``vh_vv``, ``rvi`` (window signals from
  Phase CD-3; contextual corroboration only, never a stress
  direction)

There are deliberately no weights, no thresholds beyond the sign of
an already-defined difference anomaly, and no composite score. Every
component counts as exactly one qualitative vote; direction logic
replaces coefficients. The individual component evidence is preserved
in the provenance ledger, never hidden behind the state code.

Concordance states (reported as a small integer code with a legend;
the code is an identifier, not a magnitude):

* 1 ``OPTICAL_STRESS_ONLY``
* 2 ``RADAR_STRUCTURAL_CONTEXT_ONLY``
* 3 ``CONCORDANT_STRESS``
* 4 ``MIXED_OR_CONTRADICTORY``
* 5 ``NO_STRESS_EVIDENCE``

No value is reported when there is no evidence at all
(``NO_EVIDENCE``): missing inputs are reported as missing, never as
a zero state.

THIS IS A MULTI-SENSOR EVIDENCE PROXY AND DOES NOT DIRECTLY MEASURE,
ISOLATE, OR QUANTIFY MIDDLE-CANOPY LEAVES. It is non-physical,
non-diagnostic, non-percentage, and not a leaf-layer measurement.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.canopy_moisture import (
    MSIAnomalyMetric,
    NDMIAnomalyMetric,
    NDREAnomalyMetric,
)
from app.services.agriculture.quality import combine_quality
from app.services.agriculture.radar import (
    RVIMetric,
    S1_DATASET_ID,
    VHBackscatterMetric,
    VHVVRatioMetric,
    VVBackscatterMetric,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
)
from app.services.agriculture.vegetation import S2_DATASET_ID

logger = get_logger(__name__)

__all__ = [
    "MiddleCanopyDrynessProxyMetric",
    "CANOPY_PROXY_METRICS",
    "PROXY_STATE_LEGEND",
    "PROXY_STATES",
    "classify_optical",
    "classify_concordance",
    "confidence_for",
]


class ProxyState:
    """Concordance state codes. Identifiers, not magnitudes."""

    OPTICAL_STRESS_ONLY = 1
    RADAR_STRUCTURAL_CONTEXT_ONLY = 2
    CONCORDANT_STRESS = 3
    MIXED_OR_CONTRADICTORY = 4
    NO_STRESS_EVIDENCE = 5


#: State code to state name. The single legend for the proxy value.
PROXY_STATE_LEGEND: Dict[int, str] = {
    ProxyState.OPTICAL_STRESS_ONLY: "OPTICAL_STRESS_ONLY",
    ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY: "RADAR_STRUCTURAL_CONTEXT_ONLY",
    ProxyState.CONCORDANT_STRESS: "CONCORDANT_STRESS",
    ProxyState.MIXED_OR_CONTRADICTORY: "MIXED_OR_CONTRADICTORY",
    ProxyState.NO_STRESS_EVIDENCE: "NO_STRESS_EVIDENCE",
}

#: Backwards-compatible alias used by tests and callers.
PROXY_STATES = PROXY_STATE_LEGEND

#: Optical anomaly keys in evaluation order.
OPTICAL_KEYS: Tuple[str, ...] = ("ndmi_anomaly", "msi_anomaly", "ndre_anomaly")

#: Radar window-signal keys in evaluation order.
RADAR_KEYS: Tuple[str, ...] = ("vv", "vh", "vh_vv", "rvi")

#: Confidence levels. Categorical grades of evidential support, never
#: a statistical probability and never a percentage.
CONFIDENCE_INSUFFICIENT = "INSUFFICIENT"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_MODERATE = "MODERATE"
CONFIDENCE_HIGH = "HIGH"


# --------------------------------------------------------------------------
# Pure evidence logic (no Earth Engine; fully unit testable)
# --------------------------------------------------------------------------


def _optical_vote(key: str, anomaly: float) -> str:
    """One qualitative vote from a seasonal anomaly value.

    Zero is the null the anomaly contract already defines
    ("indistinguishable from the reference"), so the sign alone
    classifies: no invented threshold is involved.
    """
    if key == "msi_anomaly":
        if anomaly > 0:
            return "stress"
        if anomaly < 0:
            return "anti"
        return "neutral"
    # ndmi_anomaly and ndre_anomaly: negative departs downward.
    if anomaly < 0:
        return "stress"
    if anomaly > 0:
        return "anti"
    return "neutral"


def classify_optical(values: Mapping[str, Optional[float]]) -> Dict[str, Any]:
    """Reduce the optical anomaly values to votes and a state.

    ``values`` maps each of the optical keys to its anomaly value or
    ``None`` when that component is missing. Missing components are
    excluded from the votes; they are never counted as negative
    evidence. Returns a record with the per-key votes, the tallies
    and one of ``stress`` / ``no_stress`` / ``contradictory`` /
    ``missing``.
    """
    votes: Dict[str, str] = {}
    for key in OPTICAL_KEYS:
        value = values.get(key)
        if value is None or not isinstance(value, (int, float)):
            continue
        if isinstance(value, bool) or not math.isfinite(value):
            continue
        votes[key] = _optical_vote(key, float(value))
    tally = {"stress": 0, "anti": 0, "neutral": 0}
    for vote in votes.values():
        tally[vote] += 1
    missing = len(OPTICAL_KEYS) - len(votes)
    if not votes:
        state = "missing"
    elif "stress" in votes.values() and "anti" in votes.values():
        state = "contradictory"
    elif "stress" in votes.values():
        state = "stress"
    else:
        state = "no_stress"
    return {"votes": votes, "tally": tally, "missing": missing, "state": state}


def classify_concordance(optical_state: str, radar_usable: bool) -> Optional[int]:
    """Map the optical state plus radar availability to a state code.

    Returns ``None`` for NO_EVIDENCE, which the caller reports as
    insufficient rather than as a zero state. Radar is contextual
    availability only: it corroborates by coexistence, never by
    direction, so radar alone can never yield a stress state.
    """
    if optical_state == "missing" and not radar_usable:
        return None
    if optical_state == "contradictory":
        return ProxyState.MIXED_OR_CONTRADICTORY
    if optical_state == "stress":
        if radar_usable:
            return ProxyState.CONCORDANT_STRESS
        return ProxyState.OPTICAL_STRESS_ONLY
    if optical_state == "no_stress":
        return ProxyState.NO_STRESS_EVIDENCE
    if optical_state == "missing" and radar_usable:
        return ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY
    return None


def confidence_for(
    state_code: Optional[int],
    n_optical_usable: int,
    n_radar_usable: int,
    any_poor_quality: bool,
) -> str:
    """Categorical confidence for a concordance state.

    Deterministic decision list, first match wins. Grades the support
    for the reading, not a probability: single-sensor readings and
    disagreements cap confidence at LOW no matter the counts, and a
    HIGH reading needs the full optical and radar houses with no poor
    input quality.
    """
    if state_code is None:
        return CONFIDENCE_INSUFFICIENT
    if state_code == ProxyState.MIXED_OR_CONTRADICTORY:
        return CONFIDENCE_LOW
    if state_code in (
        ProxyState.OPTICAL_STRESS_ONLY,
        ProxyState.RADAR_STRUCTURAL_CONTEXT_ONLY,
    ):
        return CONFIDENCE_LOW
    if state_code == ProxyState.NO_STRESS_EVIDENCE:
        if n_optical_usable == len(OPTICAL_KEYS):
            return CONFIDENCE_MODERATE
        return CONFIDENCE_LOW
    # CONCORDANT_STRESS from here on.
    if any_poor_quality or n_optical_usable < 2:
        return CONFIDENCE_LOW
    if n_optical_usable == len(OPTICAL_KEYS) and n_radar_usable == len(
        RADAR_KEYS
    ):
        return CONFIDENCE_HIGH
    return CONFIDENCE_MODERATE


# --------------------------------------------------------------------------
# Proxy metric
# --------------------------------------------------------------------------


class MiddleCanopyDrynessProxyMetric(Metric):
    """Middle-canopy dryness proxy from optical/radar concordance.

    Computes the seven component metrics on its own requested window,
    classifies each optical anomaly by sign and each radar signal as
    contextual availability, and reports the concordance state with
    the full component ledger in the provenance. A component that
    fails, mismatches the requested window, or reports no value is
    recorded as missing — never as evidence against dryness and never
    as a synthetic value.
    """

    key = "middle_canopy_dryness_proxy"
    display_name = "Middle-Canopy Dryness Proxy"
    display_name_fa = "پراکسی خشکی میانی کانوپی"
    domain = MetricDomain.VEGETATION
    unit = "state"
    dataset_ids = (S2_DATASET_ID, S1_DATASET_ID)
    measurement_basis = MeasurementBasis.PROXY
    description = (
        "Multi-sensor evidence concordance for canopy dryness, reported "
        "as a state code: 1 OPTICAL_STRESS_ONLY, 2 "
        "RADAR_STRUCTURAL_CONTEXT_ONLY, 3 CONCORDANT_STRESS, 4 "
        "MIXED_OR_CONTRADICTORY, 5 NO_STRESS_EVIDENCE. Optical stress "
        "is classified by anomaly sign (NDMI/NDRE negative, MSI "
        "positive); radar signals corroborate by coexistence only. No "
        "weights, no thresholds beyond the anomaly null at zero, no "
        "dry-leaf fraction, no diagnosis. This is an evidence proxy, "
        "not a measurement of middle-canopy leaves."
    )
    limitations = (
        "This is a multi-sensor evidence proxy and does not directly "
        "measure, isolate, or quantify middle-canopy leaves.",
        "Sentinel-2 observes the canopy top-down and cannot separate "
        "leaf layers; Sentinel-1 C-band does not penetrate to any "
        "specific layer.",
        "Radar signals mix canopy structure, biomass, soil, roughness, "
        "incidence angle, orbit geometry and speckle; radar is "
        "contextual corroboration only and carries no stress direction.",
        "There is no validated conversion to leaf water content, canopy "
        "water content, or a dry-leaf fraction.",
        "The proxy does not diagnose a cause and does not attribute "
        "drying to any driver.",
        "Components with missing or mismatched evidence are excluded, "
        "which weakens the reading; single-sensor and contradictory "
        "readings never exceed LOW confidence.",
    )

    #: Component metric classes in evaluation order.
    optical_metric_classes = (NDMIAnomalyMetric, MSIAnomalyMetric, NDREAnomalyMetric)
    radar_metric_classes = (
        VVBackscatterMetric,
        VHBackscatterMetric,
        VHVVRatioMetric,
        RVIMetric,
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("B8", "B11", "B5", "VV", "VH")

    def _component_result(
        self, metric_cls: Any, context: MetricContext
    ) -> Optional[MetricResult]:
        """Compute one component, returning None when it cannot contribute.

        A raised exception, a missing value, a missing provenance, or a
        provenance window that does not match the requested window all
        mean the same thing: the component is unavailable for this
        analysis, and it is recorded as missing rather than fabricated.
        """
        try:
            result = metric_cls().compute(context)
        except Exception as exc:  # noqa: BLE001 - one failure cannot sink the proxy
            logger.warning(
                "Canopy proxy component %s failed: %s",
                getattr(metric_cls, "key", metric_cls),
                type(exc).__name__,
            )
            return None
        if result is None or result.value is None:
            return None
        if not isinstance(result.value, (int, float)):
            return None
        if isinstance(result.value, bool) or not math.isfinite(result.value):
            return None
        provenance = result.provenance
        if provenance is None:
            return None
        if (
            provenance.requested_start != context.start_date
            or provenance.requested_end != context.end_date
        ):
            logger.warning(
                "Canopy proxy component %s mismatches the requested "
                "window; excluding it rather than mixing periods.",
                result.metric_key,
            )
            return None
        return result

    def compute(self, context: MetricContext) -> MetricResult:
        optical_results: Dict[str, Optional[MetricResult]] = {}
        for metric_cls in self.optical_metric_classes:
            optical_results[metric_cls.key] = self._component_result(
                metric_cls, context
            )
        radar_results: Dict[str, Optional[MetricResult]] = {}
        for metric_cls in self.radar_metric_classes:
            radar_results[metric_cls.key] = self._component_result(
                metric_cls, context
            )

        usable_optical = {
            key: result.value
            for key, result in optical_results.items()
            if result is not None
        }
        usable_radar = {
            key: result.value
            for key, result in radar_results.items()
            if result is not None
        }
        optical = classify_optical(usable_optical)
        radar_ok = len(usable_radar) > 0
        state_code = classify_concordance(optical["state"], radar_ok)

        used_results = [
            result
            for result in list(optical_results.values())
            + list(radar_results.values())
            if result is not None
        ]
        qualities = [
            result.provenance.quality_level
            for result in used_results
            if result.provenance is not None
        ]
        any_poor = QualityLevel.POOR in qualities
        confidence = confidence_for(
            state_code, len(usable_optical), len(usable_radar), any_poor
        )

        ledger = self._ledger(
            context,
            optical_results,
            radar_results,
            optical,
            radar_ok,
            state_code,
            confidence,
        )
        if state_code is None:
            provenance = self.build_provenance(
                context=context,
                dataset=self.primary_dataset(),
                bands=list(self.source_bands),
                formula=self._formula_text(),
                quality=QualityLevel.INSUFFICIENT,
                image_count=None,
                aggregation_method=self._aggregation_text(),
                extra_caveats=tuple(ledger),
            )
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No usable optical or radar component evidence exists "
                    "for the requested window, so no proxy state is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        quality = combine_quality(qualities) if qualities else QualityLevel.MODERATE
        provenance = self.build_provenance(
            context=context,
            dataset=self.primary_dataset(),
            bands=list(self.source_bands),
            formula=self._formula_text(),
            quality=quality,
            image_count=None,
            aggregation_method=self._aggregation_text(),
            extra_caveats=tuple(ledger),
        )
        warnings: List[str] = []
        missing_total = optical["missing"] + (
            len(RADAR_KEYS) - len(usable_radar)
        )
        if missing_total:
            warnings.append(
                f"{missing_total} of 7 component(s) contributed no usable "
                "evidence and were excluded; they are missing, not "
                "negative evidence."
            )
        if any_poor:
            warnings.append(
                "At least one contributing component has poor quality; "
                "confidence is capped at LOW."
            )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=float(state_code),
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _formula_text(self) -> str:
        return (
            "concordance of ndmi/msi/ndre seasonal-anomaly signs with "
            "Sentinel-1 vv/vh/vh_vv/rvi contextual availability on the "
            "requested window; state 1 OPTICAL_STRESS_ONLY, 2 "
            "RADAR_STRUCTURAL_CONTEXT_ONLY, 3 CONCORDANT_STRESS, 4 "
            "MIXED_OR_CONTRADICTORY, 5 NO_STRESS_EVIDENCE; no weights, "
            "no fitted thresholds"
        )

    def _aggregation_text(self) -> str:
        return (
            "per-component published aggregations on the requested "
            "window (optical seasonal anomalies: median composite per "
            "window, spatial mean, baseline of per-year means; radar: "
            "temporal-mean backscatter, spatial mean); votes counted, "
            "never averaged"
        )

    def _ledger(
        self,
        context: MetricContext,
        optical_results: Mapping[str, Optional[MetricResult]],
        radar_results: Mapping[str, Optional[MetricResult]],
        optical: Mapping[str, Any],
        radar_ok: bool,
        state_code: Optional[int],
        confidence: str,
    ) -> List[str]:
        """Component-by-component evidence ledger for the provenance."""
        lines: List[str] = []
        for key in OPTICAL_KEYS:
            result = optical_results.get(key)
            if result is None:
                lines.append(
                    f"optical: {key}=missing (insufficient or mismatched; "
                    "excluded, not negative evidence)"
                )
                continue
            vote = optical["votes"].get(key, "missing")
            quality = (
                result.provenance.quality_level.value
                if result.provenance is not None
                else "unknown"
            )
            lines.append(
                f"optical: {key}={result.value:+.4f} ({vote} vote, "
                f"quality {quality})"
            )
        for key in RADAR_KEYS:
            result = radar_results.get(key)
            if result is None:
                lines.append(
                    f"radar: {key}=missing (insufficient or mismatched; "
                    "excluded, not negative evidence)"
                )
                continue
            quality = (
                result.provenance.quality_level.value
                if result.provenance is not None
                else "unknown"
            )
            lines.append(
                f"radar: {key}={result.value:+.4f} (context, quality "
                f"{quality})"
            )
        tally = optical["tally"]
        lines.append(
            "optical votes: stress={stress}, anti={anti}, neutral={neutral}, "
            "missing={missing}".format(
                stress=tally["stress"],
                anti=tally["anti"],
                neutral=tally["neutral"],
                missing=optical["missing"],
            )
        )
        lines.append(
            f"radar context: {len([r for r in radar_results.values() if r is not None])} "
            f"of {len(RADAR_KEYS)} usable"
        )
        state_name = (
            PROXY_STATE_LEGEND[state_code] if state_code is not None else "NO_EVIDENCE"
        )
        lines.append(
            f"concordance state: {state_name}"
            + (f" ({state_code})" if state_code is not None else " (no value reported)")
        )
        lines.append(
            f"confidence: {confidence} (categorical grade of support, "
            "not a probability)"
        )
        lines.append(
            f"temporal alignment: all components computed on requested "
            f"window {context.start_date} to {context.end_date}; optical "
            f"baselines are same-calendar prior windows, radar is the "
            f"same requested window"
        )
        lines.append(
            "This is a multi-sensor evidence proxy and does not directly "
            "measure, isolate, or quantify middle-canopy leaves."
        )
        return lines


#: Proxy metrics registered with the catalog.
CANOPY_PROXY_METRICS: Tuple[Metric, ...] = (
    MiddleCanopyDrynessProxyMetric(),
)
