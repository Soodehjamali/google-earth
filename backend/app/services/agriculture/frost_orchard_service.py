"""Per-Orchard Frost Risk Assessment and Batch Evaluation Service (R5).

Coordinates:
1. Input assembly (R1: platform factors, moisture normalization, GFS cell sharing).
2. Local night aggregation (18:00 to 09:00 local time across UTC midnight).
3. Weighted factor model evaluation (R3: 10 factor rows, subscores, GATE, asymmetry floor).
4. Single orchard and multi-orchard risk summary sorting.
5. Recommendation generation (only when category is warning or critical).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.logging import get_logger
from app.services.agriculture.frost_inputs import (
    assemble_orchard_inputs,
    FactorInput,
    OrchardInputs,
)
from app.services.agriculture.frost_risk import (
    aggregate_forecast_by_local_night,
    calculate_interval_duration_run,
    evaluate_duration_rule_category,
    load_frost_threshold_set,
    load_frost_thresholds_config,
    GENERIC_RECOMMENDATIONS_FA,
    RECOMMENDATION_WARNING_FA,
    STAGE_ALIASES,
)
from app.services.agriculture.frost_weighted_model import (
    evaluate_weighted_frost_model,
    load_frost_factor_weights_config,
    EvaluatedFactor,
    FrostWeightedModelConfig,
    WeightedRiskResult,
    RISK_CATEGORY_FA,
    RISK_HIERARCHY,
)

logger = get_logger(__name__)

GUIDANCE_LABEL_FA = "ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)"


@dataclass
class OrchardNightRiskDetail:
    night_date: str
    night_display_fa: str
    start_time_utc: str
    end_time_utc: str
    min_temp_local_time: str
    effective_tmin_c: float
    hours_below_threshold: float
    longest_continuous_hours: float
    risk_index: float
    index_category: str
    gate_category: str
    final_category: str
    final_category_fa: str
    gate_triggered: bool
    gate_reason_fa: Optional[str]
    factors: List[Dict[str, Any]]
    total_weight: float
    total_contribution: float
    wind_speed_mps: Optional[float]
    relative_moisture: Optional[float]
    window_coverage: float = 1.0
    is_partial_night: bool = False
    duration_display_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrchardRiskReport:
    orchard_id: str
    orchard_name: str
    crop: str
    crop_fa: str
    current_stage: str
    stage_fa: str
    stage_is_stale: bool
    critical_temperature_c: float
    threshold_set: str
    thresholds_verified: bool
    evidence_level: str
    index_is_probability: bool
    guidance_risk_label_fa: str
    overall_final_category: str
    overall_final_category_fa: str
    worst_night: Optional[Dict[str, Any]]
    nights: List[OrchardNightRiskDetail]
    recommendations_fa: List[str]
    assembled_at: str

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["nights"] = [n.to_dict() for n in self.nights]
        return res


@dataclass
class OrchardSummaryItem:
    orchard_id: str
    name: str
    crop: str
    current_stage: str
    stage_is_stale: bool
    worst_night_date: Optional[str]
    worst_effective_tmin_c: Optional[float]
    hours_below_threshold: float
    relative_rootzone_moisture: Optional[float]
    wind_speed_mps: Optional[float]
    risk_index: float
    final_category: str
    final_category_fa: str
    gate_triggered: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def assess_single_orchard_risk(
    orchard: Any,
    horizon_h: int = 240,
    threshold_set: str = "published_v1",
    forecast_provider: Optional[Any] = None,
    gfs_cell_cache: Optional[Dict[str, Any]] = None,
    use_cache: bool = True,
    now_utc: Optional[datetime] = None,
    weights_config: Optional[FrostWeightedModelConfig] = None,
) -> OrchardRiskReport:
    """Assess multi-night frost risk for an individual orchard parcel."""
    now_dt = now_utc or datetime.now(timezone.utc)
    weights_cfg = weights_config or load_frost_factor_weights_config()

    # 1. Assemble per-orchard inputs (R1)
    inputs: OrchardInputs = await assemble_orchard_inputs(
        orchard=orchard,
        forecast_provider=forecast_provider,
        gfs_cell_cache=gfs_cell_cache,
        use_cache=use_cache,
        now_utc=now_dt,
        horizon_h=horizon_h,
    )

    crop = inputs.crop
    stage_key = inputs.current_stage

    # 2. Load threshold configuration
    if threshold_set == "published_v1":
        crop_cfg = load_frost_threshold_set(set_name="published_v1", crop=crop)
    else:
        configs = load_frost_thresholds_config()
        crop_cfg = configs.get(crop, configs.get("pistachio"))

    # Resolve stage alias if needed
    resolved_stage = stage_key
    if resolved_stage not in crop_cfg.stages:
        resolved_stage = STAGE_ALIASES.get(stage_key, stage_key)

    if resolved_stage in crop_cfg.stages:
        stage_cfg = crop_cfg.stages[resolved_stage]
        stage_name_fa = stage_cfg.name_fa
    else:
        # Default to most sensitive stage if unrecognized
        stage_cfg = max(crop_cfg.stages.values(), key=lambda s: s.t_critical_10_c if s.t_critical_10_c is not None else -10.0)
        stage_name_fa = stage_cfg.name_fa

    # Critical damage threshold
    tc_crit = stage_cfg.t_critical_c if getattr(stage_cfg, "t_critical_c", None) is not None else stage_cfg.t_critical_10_c
    if tc_crit is None:
        tc_crit = -2.0  # Fallback

    # 3. Group timesteps by local night (18:00 to 09:00 local IRST)
    forecast_series = inputs.orchard_forecast.series if inputs.orchard_forecast else []
    nights_map = aggregate_forecast_by_local_night(forecast_series, local_utc_offset_hours=3.5)

    tz_local = timezone(timedelta(hours=3.5))
    night_results: List[OrchardNightRiskDetail] = []
    worst_level = "none"
    worst_night_detail: Optional[Dict[str, Any]] = None
    worst_risk_index = -1.0

    for night_key in sorted(nights_map.keys()):
        raw_steps = nights_map[night_key]
        steps = [s for s in raw_steps if s.lead_hours <= horizon_h]
        if not steps:
            continue

        steps.sort(key=lambda s: s.timestamp_utc)
        start_utc = steps[0].timestamp_utc
        end_utc = steps[-1].timestamp_utc

        # Find minimum temperature step
        min_step = min(steps, key=lambda s: s.temperature_2m_c)
        t_eff_min = min_step.temperature_2m_c
        t_min_utc = min_step.timestamp_utc
        dt_min = datetime.fromisoformat(t_min_utc.replace("Z", "+00:00")).astimezone(tz_local)
        min_temp_local = dt_min.strftime("%H:%M")

        wind_spd = min_step.wind_speed_10m_mps
        wind_dir = min_step.wind_direction_10m_deg
        cloud_pct = min_step.total_cloud_cover_percent
        rh_pct = min_step.relative_humidity_percent

        # Duration run calculations
        nom_total, nom_longest, nom_start_loc, nom_end_loc, is_resolvable = calculate_interval_duration_run(
            steps,
            reference_temp_c=tc_crit,
            cooling_bump_c=0.0,
            use_pessimistic=False,
            local_utc_offset_hours=3.5,
        )

        level, level_fa, short_dip, duration_escalated, expl_fa = evaluate_duration_rule_category(
            min_temp_adjusted_c=t_eff_min,
            min_temp_pessimistic_c=min_step.lower_bound_c,
            reference_temp_c=tc_crit,
            continuous_hours_nominal=nom_longest,
            continuous_hours_pessimistic=nom_longest,
            duration_rules=stage_cfg.duration_rules,
            duration_resolvable=is_resolvable,
        )

        # 4. Evaluate weighted factor model (R3)
        weighted_res = evaluate_weighted_frost_model(
            inputs=inputs,
            night_tmin_c=t_eff_min,
            critical_temp_c=tc_crit,
            night_wind_speed_mps=wind_spd,
            night_wind_dir_deg=wind_dir,
            night_cloud_pct=cloud_pct,
            night_rh_pct=rh_pct,
            duration_escalated=duration_escalated,
            night_date=night_key,
            config=weights_cfg,
        )

        # Night window coverage calculation (15 bins between 18:00 and 09:00)
        covered_hours = set()
        for s in steps:
            dt_s = datetime.fromisoformat(s.timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local)
            covered_hours.add(dt_s.hour)
        night_bins = {18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8}
        cov_ratio = round(min(1.0, len(covered_hours.intersection(night_bins)) / 15.0), 2)

        dur_text = (
            f"{nom_total:.1f} h below {tc_crit:.1f}°C"
            if nom_total > 0
            else f"0.0 h below {tc_crit:.1f}°C"
        )

        detail = OrchardNightRiskDetail(
            night_date=night_key,
            night_display_fa=f"شب {night_key}",
            start_time_utc=start_utc,
            end_time_utc=end_utc,
            min_temp_local_time=min_temp_local,
            effective_tmin_c=t_eff_min,
            hours_below_threshold=float(nom_total),
            longest_continuous_hours=float(nom_longest),
            risk_index=weighted_res.risk_index,
            index_category=weighted_res.index_category,
            gate_category=weighted_res.gate_category,
            final_category=weighted_res.final_category,
            final_category_fa=weighted_res.final_category_fa,
            gate_triggered=weighted_res.gate_triggered,
            gate_reason_fa=weighted_res.gate_reason_fa,
            factors=[f.to_dict() for f in weighted_res.factors],
            total_weight=weighted_res.total_weight,
            total_contribution=weighted_res.total_contribution,
            wind_speed_mps=wind_spd,
            relative_moisture=inputs.factors["soil_rootzone_moisture"].value if "soil_rootzone_moisture" in inputs.factors else None,
            window_coverage=cov_ratio,
            is_partial_night=cov_ratio < 1.0,
            duration_display_text=dur_text,
        )
        night_results.append(detail)

        # Track worst night by category hierarchy then risk index
        if (
            RISK_HIERARCHY.get(weighted_res.final_category, 0) > RISK_HIERARCHY.get(worst_level, 0)
            or (
                RISK_HIERARCHY.get(weighted_res.final_category, 0) == RISK_HIERARCHY.get(worst_level, 0)
                and weighted_res.risk_index > worst_risk_index
            )
        ):
            worst_level = weighted_res.final_category
            worst_risk_index = weighted_res.risk_index
            worst_night_detail = {
                "night_date": night_key,
                "effective_tmin_c": t_eff_min,
                "risk_index": weighted_res.risk_index,
                "final_category": weighted_res.final_category,
                "final_category_fa": weighted_res.final_category_fa,
                "gate_triggered": weighted_res.gate_triggered,
                "hours_below_threshold": float(nom_total),
            }

    # 5. Recommendations: surfaced ONLY if any night triggers warning or critical
    recs: List[str] = []
    if RISK_HIERARCHY.get(worst_level, 0) >= RISK_HIERARCHY["warning"]:
        recs = list(GENERIC_RECOMMENDATIONS_FA)

    return OrchardRiskReport(
        orchard_id=inputs.orchard_id,
        orchard_name=inputs.orchard_name,
        crop=crop,
        crop_fa=crop_cfg.common_name_fa if hasattr(crop_cfg, "common_name_fa") else "پسته",
        current_stage=stage_key,
        stage_fa=stage_name_fa,
        stage_is_stale=inputs.stage_is_stale,
        critical_temperature_c=tc_crit,
        threshold_set=threshold_set,
        thresholds_verified=getattr(crop_cfg, "verified", False),
        evidence_level=weights_cfg.evidence_level,
        index_is_probability=weights_cfg.index_is_probability,
        guidance_risk_label_fa=GUIDANCE_LABEL_FA,
        overall_final_category=worst_level,
        overall_final_category_fa=RISK_CATEGORY_FA.get(worst_level, worst_level),
        worst_night=worst_night_detail,
        nights=night_results,
        recommendations_fa=recs,
        assembled_at=inputs.assembled_at,
    )


async def assess_orchards_summary(
    orchards: List[Any],
    horizon_h: int = 240,
    threshold_set: str = "published_v1",
    forecast_provider: Optional[Any] = None,
    use_cache: bool = True,
    now_utc: Optional[datetime] = None,
) -> List[OrchardSummaryItem]:
    """Assess multiple orchards with shared GFS cell cache, returning sorted summary items."""
    shared_gfs_cell_cache: Dict[str, Any] = {}
    weights_cfg = load_frost_factor_weights_config()
    now_dt = now_utc or datetime.now(timezone.utc)

    summaries: List[OrchardSummaryItem] = []

    for o in orchards:
        try:
            report = await assess_single_orchard_risk(
                orchard=o,
                horizon_h=horizon_h,
                threshold_set=threshold_set,
                forecast_provider=forecast_provider,
                gfs_cell_cache=shared_gfs_cell_cache,
                use_cache=use_cache,
                now_utc=now_dt,
                weights_config=weights_cfg,
            )

            worst = report.worst_night or {}
            # Extract sample values from worst night if available
            worst_night_obj = next(
                (n for n in report.nights if n.night_date == worst.get("night_date")),
                None,
            )
            spd = worst_night_obj.wind_speed_mps if worst_night_obj else None
            moist = worst_night_obj.relative_moisture if worst_night_obj else None

            item = OrchardSummaryItem(
                orchard_id=report.orchard_id,
                name=report.orchard_name,
                crop=report.crop,
                current_stage=report.current_stage,
                stage_is_stale=report.stage_is_stale,
                worst_night_date=worst.get("night_date"),
                worst_effective_tmin_c=worst.get("effective_tmin_c"),
                hours_below_threshold=worst.get("hours_below_threshold", 0.0),
                relative_rootzone_moisture=moist,
                wind_speed_mps=spd,
                risk_index=worst.get("risk_index", 0.0),
                final_category=report.overall_final_category,
                final_category_fa=report.overall_final_category_fa,
                gate_triggered=bool(worst.get("gate_triggered", False)),
            )
            summaries.append(item)
        except Exception as exc:
            logger.error(f"Failed to assess risk summary for orchard {getattr(o, 'id', 'unknown')}: {exc}")

    # Sort descending by risk severity then risk index
    summaries.sort(
        key=lambda item: (
            RISK_HIERARCHY.get(item.final_category, 0),
            item.risk_index,
        ),
        reverse=True,
    )

    return summaries
