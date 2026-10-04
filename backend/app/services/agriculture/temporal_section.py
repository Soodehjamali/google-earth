"""Temporal section orchestration for the Agriculture /analysis response.

P5.3 integration phase: assembles already-computed P1-P4 monthly
intelligence into the additive ``temporal`` section of the
analysis response. Transport and orchestration only.

Every payload assembled here is produced by an existing P1-P4
builder and serialized through its canonical ``to_dict``. No
statistical formula lives in this module: no means, no spreads,
no z-scores, no percentiles, no baselines, no changes, no rates,
no persistence runs, no lags, no concordance rules, no thermal
differencing. One metric's failure can never fail the section:
each key is isolated and refusals are recorded as limitations.

Request-driven cost control: only metrics in the resolved request
key set are profiled, radar-family keys travel the radar path
once (never duplicated through the generic path), thermal
quantities build only when the thermal domain was requested, and
windows longer than ``MAX_TEMPORAL_MONTHS`` calendar months yield
an empty section with a stated limitation instead of unbounded
Earth Engine multiplication.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "MAX_TEMPORAL_MONTHS",
    "OPTICAL_PROFILE_KEYS",
    "RADAR_PROFILE_KEYS",
    "build_temporal_section",
]

#: Upper bound on calendar months profiled per request. Longer
#: windows return an empty temporal section with a limitation so
#: one request can never fan out into unbounded monthly evaluation.
MAX_TEMPORAL_MONTHS = 36

#: Generic-path temporal metrics (optical indices). Radar-family
#: keys are excluded even though P1.1 lists some of them: they
#: travel the radar path exactly once.
OPTICAL_PROFILE_KEYS: Tuple[str, ...] = ("ndvi", "ndmi", "ndre", "msi")

#: Radar-path temporal metrics.
RADAR_PROFILE_KEYS: Tuple[str, ...] = ("vv", "vh", "vh_vv", "rvi")

#: Concordance family for the generic optical metrics.
_OPTICAL_FAMILY = "optical"

#: Concordance family for the radar metrics.
_RADAR_FAMILY = "radar"


def _empty_section(
    context: Any, limitations: List[str]
) -> Dict[str, Any]:
    return {
        "window_start": context.start_date,
        "window_end": context.end_date,
        "profiles": {},
        "anomalies": {},
        "changes": {},
        "radar_profiles": {},
        "radar_analyses": {},
        "joint": None,
        "concordance": None,
        "thermal_profiles": {},
        "thermal_analyses": {},
        "thermal_harmonized": None,
        "thermal_pair": None,
        "thermal_concordance": None,
        "limitations": list(limitations),
    }


def build_temporal_section(
    context: Any,
    metric_keys: Sequence[str],
    domains: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Assemble the additive temporal payload for an analysis request.

    Args:
        context: The request's ``MetricContext`` (geometry, dates,
            scale, cloud tolerance, options carried into every
            monthly sub-window by the builders themselves).
        metric_keys: Resolved request metric keys; only eligible
            keys are profiled, nothing is substituted.
        domains: Requested API domains; thermal quantities build
            only when ``"thermal"`` was requested.

    Returns:
        Plain-data payload matching ``TemporalSectionModel``. Never
        raises: failures are isolated per key and recorded in
        ``limitations``.
    """
    from app.services.agriculture.temporal_profile import month_windows

    limitations: List[str] = []
    try:
        n_months = len(month_windows(context.start_date, context.end_date))
    except Exception as exc:  # noqa: BLE001 - transport must not fail analysis
        logger.warning("Temporal section skipped: %s", type(exc).__name__)
        return _empty_section(
            context, ["temporal section unavailable for this window"]
        )
    if n_months > MAX_TEMPORAL_MONTHS:
        logger.info(
            "Temporal section skipped: %d months exceeds the %d-month bound",
            n_months,
            MAX_TEMPORAL_MONTHS,
        )
        return _empty_section(
            context,
            [
                f"requested window spans {n_months} calendar months, "
                f"beyond the {MAX_TEMPORAL_MONTHS}-month temporal bound; "
                "request a shorter window for monthly intelligence"
            ],
        )

    requested = set(metric_keys or ())
    optical_keys = [k for k in OPTICAL_PROFILE_KEYS if k in requested]
    radar_keys = [k for k in RADAR_PROFILE_KEYS if k in requested]
    # Thermal gating (F-CONTRACT-FIX-1 §6): the request contract treats a
    # missing ``domains`` list as "all domains" — the API maps ``None``
    # to the full registry key set and never to a thermal exclusion.  So
    # ``None`` must request thermal temporal processing, an explicit
    # list containing "thermal" must too, and an explicit list without
    # "thermal" must not.  The previous ``bool(domains) and ...`` read
    # dropped thermal for exactly the all-domain requests that implied
    # it, while thermal scalar evidence was still present in the same
    # response.  No thermal value is ever fabricated here: gating only
    # decides whether the existing P4 builders run.
    want_thermal = domains is None or "thermal" in set(domains)

    profiles: Dict[str, Any] = {}
    anomalies: Dict[str, Any] = {}
    changes: Dict[str, Any] = {}
    radar_profiles: Dict[str, Any] = {}
    radar_analyses: Dict[str, Any] = {}
    thermal_profiles: Dict[str, Any] = {}
    thermal_analyses: Dict[str, Any] = {}

    kept_profiles: Dict[str, Any] = {}
    kept_anomalies: Dict[str, Any] = {}
    kept_radar_points: Dict[str, Any] = {}

    for key in optical_keys:
        try:
            profile, anomaly, change = _optical_triplet(context, key)
        except Exception as exc:  # noqa: BLE001 - per-key isolation
            logger.warning(
                "Temporal profile for %s skipped: %s",
                key, type(exc).__name__,
            )
            limitations.append(f"temporal profile unavailable for {key}")
            continue
        profiles[key] = profile.to_dict()
        anomalies[key] = anomaly.to_dict()
        changes[key] = change.to_dict()
        kept_profiles[key] = profile
        kept_anomalies[key] = anomaly

    for key in radar_keys:
        try:
            radar_profile, radar_analysis = _radar_pair(context, key)
        except Exception as exc:  # noqa: BLE001 - per-key isolation
            logger.warning(
                "Radar temporal profile for %s skipped: %s",
                key, type(exc).__name__,
            )
            limitations.append(f"temporal profile unavailable for {key}")
            continue
        radar_profiles[key] = radar_profile.to_dict()
        radar_analyses[key] = radar_analysis.to_dict()
        kept_radar_points[key] = radar_analysis

    joint = _joint_payload(kept_profiles, kept_anomalies, limitations)
    series = _concordance_series(
        kept_profiles, kept_anomalies, kept_radar_points, limitations
    )
    concordance = series.to_dict() if series is not None else None

    thermal_harmonized = None
    thermal_pair = None
    thermal_concordance = None
    if want_thermal:
        try:
            (
                thermal_profiles,
                thermal_analyses,
                thermal_harmonized,
                thermal_pair,
                thermal_concordance,
                thermal_limitations,
            ) = _thermal_payload(
                context,
                series.months if series is not None else (),
            )
            limitations.extend(thermal_limitations)
        except Exception as exc:  # noqa: BLE001 - per-domain isolation
            logger.warning(
                "Thermal temporal payload skipped: %s", type(exc).__name__
            )
            limitations.append("thermal temporal payload unavailable")

    return {
        "window_start": context.start_date,
        "window_end": context.end_date,
        "profiles": profiles,
        "anomalies": anomalies,
        "changes": changes,
        "radar_profiles": radar_profiles,
        "radar_analyses": radar_analyses,
        "joint": joint,
        "concordance": concordance,
        "thermal_profiles": thermal_profiles,
        "thermal_analyses": thermal_analyses,
        "thermal_harmonized": thermal_harmonized,
        "thermal_pair": thermal_pair,
        "thermal_concordance": thermal_concordance,
        "limitations": limitations,
    }


def _optical_triplet(context: Any, key: str) -> Tuple[Any, Any, Any]:
    """Generic profile + anomaly + change for one optical metric."""
    from app.services.agriculture.baseline_anomaly import score_profile
    from app.services.agriculture.change_profile import analyze_changes
    from app.services.agriculture.temporal_profile import (
        build_temporal_profile,
    )

    profile = build_temporal_profile(key, context)
    anomaly = score_profile(profile)
    change = analyze_changes(profile, anomaly)
    return profile, anomaly, change


def _radar_pair(context: Any, key: str) -> Tuple[Any, Any]:
    """Radar profile + anomaly analysis for one radar metric."""
    from app.services.agriculture.radar_anomaly import analyze_radar_metric
    from app.services.agriculture.radar_profile import build_radar_profile

    radar_profile = build_radar_profile(key, context)
    return radar_profile, analyze_radar_metric(radar_profile)


def _joint_payload(
    kept_profiles: Dict[str, Any],
    kept_anomalies: Dict[str, Any],
    limitations: List[str],
) -> Optional[Dict[str, Any]]:
    """Joint NDVI-moisture analysis when both sides were profiled."""
    if "ndvi" not in kept_profiles or "ndmi" not in kept_profiles:
        return None
    try:
        from app.services.agriculture.joint_profile import analyze_joint

        record = analyze_joint(
            kept_profiles["ndvi"],
            kept_profiles["ndmi"],
            kept_anomalies.get("ndvi"),
            kept_anomalies.get("ndmi"),
        )
    except Exception as exc:  # noqa: BLE001 - derived step isolation
        logger.warning("Joint analysis skipped: %s", type(exc).__name__)
        limitations.append("joint NDVI-moisture analysis unavailable")
        return None
    return record.to_dict()


def _concordance_series(
    kept_profiles: Dict[str, Any],
    kept_anomalies: Dict[str, Any],
    kept_radar_points: Dict[str, Any],
    limitations: List[str],
) -> Optional[Any]:
    """P2.5 concordance series over the profiled optical/radar months.

    Returns the live series object (thermal context consumes its
    months directly); callers serialize with ``to_dict``.
    """
    from app.services.agriculture.concordance import (
        analyze_concordance,
        make_evidence,
    )

    items: List[Any] = []
    for key in kept_profiles:
        anomaly = kept_anomalies.get(key)
        if anomaly is None:
            continue
        for point in anomaly.points:
            items.append(
                make_evidence(
                    family=_OPTICAL_FAMILY,
                    metric_id=key,
                    window_start=point.window_start,
                    window_end=point.window_end,
                    value=point.value,
                    unit=point.unit,
                    quality=point.quality,
                    coverage_percent=point.coverage_percent,
                    image_count=point.image_count,
                    state_kind="anomaly",
                    state=point.category,
                    provenance={},
                )
            )
    for key, radar_analysis in kept_radar_points.items():
        for point in radar_analysis.anomalies.points:
            items.append(
                make_evidence(
                    family=_RADAR_FAMILY,
                    metric_id=key,
                    window_start=point.window_start,
                    window_end=point.window_end,
                    value=point.value,
                    unit=point.unit,
                    quality=point.quality,
                    coverage_percent=point.coverage_percent,
                    image_count=point.image_count,
                    state_kind="anomaly",
                    state=point.category,
                    provenance={},
                )
            )
    if not items:
        return None
    try:
        return analyze_concordance(items)
    except Exception as exc:  # noqa: BLE001 - derived step isolation
        logger.warning("Concordance skipped: %s", type(exc).__name__)
        limitations.append("multi-sensor concordance unavailable")
        return None


def _thermal_payload(
    context: Any,
    concordance_months: Sequence[Any],
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Optional[Dict[str, Any]],
    Optional[Dict[str, Any]],
    Optional[Dict[str, Any]],
    List[str],
]:
    """P4.2-P4.4 thermal payloads for a thermal-domain request."""
    from app.services.agriculture.thermal_anomaly import (
        analyze_thermal_metric,
        analyze_thermal_pair,
    )
    from app.services.agriculture.thermal_concordance import (
        analyze_thermal_concordance,
    )
    from app.services.agriculture.thermal_profile import (
        AIR_METRIC_KEY,
        LST_METRIC_KEY,
        build_air_temperature_profile,
        build_lst_profile,
        harmonize_thermal_monthly,
    )

    thermal_limitations: List[str] = []
    lst_profile = build_lst_profile(context)
    air_profile = build_air_temperature_profile(context)
    lst_analysis = analyze_thermal_metric(lst_profile)
    air_analysis = analyze_thermal_metric(air_profile)
    harmonized = harmonize_thermal_monthly(lst_profile, air_profile)
    pair = analyze_thermal_pair(lst_profile, air_profile)

    period = analyze_thermal_concordance(
        list(concordance_months), lst_analysis, air_analysis
    )
    return (
        {
            LST_METRIC_KEY: lst_profile.to_dict(),
            AIR_METRIC_KEY: air_profile.to_dict(),
        },
        {
            LST_METRIC_KEY: lst_analysis.to_dict(),
            AIR_METRIC_KEY: air_analysis.to_dict(),
        },
        harmonized.to_dict(),
        pair.to_dict(),
        period.to_dict(),
        thermal_limitations,
    )
