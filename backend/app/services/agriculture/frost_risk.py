"""Frost-Risk Assessment, Phenological Thresholds, and Nightly Aggregation Engine.

THIS MODULE COMPUTES ADVISORY FROST DEFENSE GUIDANCE BASED ON:
1. Hourly weather forecast series (e.g. NOAA GFS with DEM elevation correction and lead-time uncertainty).
2. Phenological frost damage thresholds loaded strictly from ``config/frost_thresholds.yaml``.
3. Topography-derived cold-air-pooling risk proxy (NASADEM 30m).

All recommendations are purely advisory and physical (passive and active cultural methods:
surface irrigation, orchard heaters, wind machines). NO chemical or hormonal treatments.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.core.logging import get_logger
from app.services.agriculture.cold_air_pooling import ColdAirPoolingResult
from app.services.agriculture.forecast import ForecastResult, ForecastTimestep

logger = get_logger(__name__)

# Default search paths for config/frost_thresholds.yaml
_CONFIG_PATHS = [
    Path(os.environ.get("FROST_THRESHOLDS_FILE", "")),
    Path("config/frost_thresholds.yaml"),
    Path("../config/frost_thresholds.yaml"),
    Path(__file__).resolve().parents[4] / "config" / "frost_thresholds.yaml",
]

DEFAULT_LOCAL_UTC_OFFSET_HOURS = 3.5  # Iran Standard Time (IRST = UTC+3:30)

#: Configurable forecast horizon parameters
DEFAULT_FROST_HORIZON_H = int(os.environ.get("FROST_DEFAULT_HORIZON_H", "240"))
FROST_HARD_CAP_HORIZON_H = int(os.environ.get("FROST_HARD_CAP_HORIZON_H", "240"))

RISK_LEVEL_NONE = "none"
RISK_LEVEL_ADVISORY = "advisory"
RISK_LEVEL_WATCH = "watch"
RISK_LEVEL_WARNING = "warning"

RISK_LEVEL_FA = {
    RISK_LEVEL_NONE: "عادی (بدون خطر)",
    RISK_LEVEL_ADVISORY: "اطلاعیه پایش (احتمال سرما)",
    RISK_LEVEL_WATCH: "آماده‌باش سرمازدگی (خطر متوسط)",
    RISK_LEVEL_WARNING: "هشدار سرمازدگی شدید (خطر قطعی خسارت)",
}

# Generic, verified cultural/physical recommendations (NO chemicals, NO hormones)
GENERIC_RECOMMENDATIONS_FA = [
    (
        "آبیاری سطحی یا شیاری باغات در عصر قبل از افت دما جهت افزایش ظرفیت "
        "گرمایی خاک مرطوب و آزادسازی گرمای نهان انجماد آب."
    ),
    (
        "راه‌اندازی ماشین‌های مولد باد (Wind Machines) یا چاهک‌های معکوس در صورت "
        "وجود وارونگی دمایی تشعشعی (هوای گرم‌تر در تراز ۱۰ تا ۱۵ متری)."
    ),
    (
        "روشن کردن بخاری‌های باغی یا سیستم‌های گرمایشی موضعی، به ویژه در نقاط فرودست، "
        "چاله‌ها و فرورفتگی‌های مستعد تجمع هوای سرد."
    ),
    (
        "پرهیز از هرگونه شخم زدن، علف‌تراشی یا زیرورو کردن خاک در آستانه موج سرما "
        "(خاک سفت، مرطوب و متراکم حرارت روز را بهتر در خود ذخیره و در شب بازتابش می‌کند)."
    ),
]

RECOMMENDATION_WARNING_FA = (
    "کلیه راهکارهای حفاظتی ارائه‌شده جنبه مشورتی و عمومی داشته و اجرای آن‌ها "
    "الزاماً باید تحت نظارت و تایید کارشناس باغبانی و متناسب با شرایط میدانی باغ صورت پذیرد."
)


@dataclass
class StageThreshold:
    """Critical temperatures for a single phenological stage."""

    stage_key: str
    name_fa: str
    t_critical_10_c: float
    t_critical_90_c: float
    status: str
    source: Optional[str]
    notes_fa: Optional[str] = None


@dataclass
class CropThresholdConfig:
    """Full thresholds for a crop."""

    crop_key: str
    common_name_fa: str
    scientific_name: str
    status: str
    source: Optional[str]
    verified: bool
    verification_warning_fa: str
    stages: Dict[str, StageThreshold] = field(default_factory=dict)


def load_frost_thresholds_config(config_path: Optional[Path] = None) -> Dict[str, CropThresholdConfig]:
    """Load and strictly validate frost thresholds from YAML.

    Enforces that:
    1. The configuration file exists and parses valid YAML.
    2. Every crop and stage discloses 'status' and 'source'.
    3. If status is 'placeholder', source must be null, and verified must be false.
    4. T_critical_90 < T_critical_10 (physical kill curve requirement).
    """
    resolved_path: Optional[Path] = None
    if config_path and config_path.exists():
        resolved_path = config_path
    else:
        for p in _CONFIG_PATHS:
            if p and p.exists() and p.is_file():
                resolved_path = p
                break

    if not resolved_path:
        raise FileNotFoundError(
            "Could not locate 'config/frost_thresholds.yaml'. Ensure the file exists at project root."
        )

    with open(resolved_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "crops" not in raw:
        raise ValueError(f"Invalid format in {resolved_path}: missing top-level 'crops' key.")

    crops: Dict[str, CropThresholdConfig] = {}
    for crop_id, c_data in raw["crops"].items():
        if not isinstance(c_data, dict):
            raise ValueError(f"Crop '{crop_id}' must be a mapping.")

        # Provenance gating
        status = c_data.get("status")
        source = c_data.get("source")
        verified = c_data.get("verified", False)

        if not status or status not in ("placeholder", "verified"):
            raise ValueError(
                f"Crop '{crop_id}' must disclose 'status' as 'placeholder' or 'verified', got: {status}"
            )

        if status == "placeholder":
            if source is not None:
                raise ValueError(
                    f"Crop '{crop_id}' has status='placeholder' but discloses a non-null source: {source}."
                )
            if verified is not False:
                raise ValueError(
                    f"Crop '{crop_id}' has status='placeholder' but verified is set to True."
                )

        warning_fa = c_data.get("verification_warning_fa", "")
        stages_data = c_data.get("stages", {})
        if not stages_data:
            raise ValueError(f"Crop '{crop_id}' must contain phenological 'stages'.")

        crop_stages: Dict[str, StageThreshold] = {}
        for st_id, st_val in stages_data.items():
            st_status = st_val.get("status")
            st_source = st_val.get("source")
            if not st_status or st_status not in ("placeholder", "verified"):
                raise ValueError(
                    f"Stage '{crop_id}.{st_id}' must disclose 'status' as 'placeholder' or 'verified'."
                )

            tc10 = float(st_val["t_critical_10_c"])
            tc90 = float(st_val["t_critical_90_c"])

            # 90% kill temperature must be strictly lower than 10% kill temperature
            if tc90 >= tc10:
                raise ValueError(
                    f"Stage '{crop_id}.{st_id}' thermodynamic violation: "
                    f"t_critical_90_c ({tc90}) must be colder than t_critical_10_c ({tc10})."
                )

            crop_stages[st_id] = StageThreshold(
                stage_key=st_id,
                name_fa=st_val.get("name_fa", st_id),
                t_critical_10_c=tc10,
                t_critical_90_c=tc90,
                status=st_status,
                source=st_source,
                notes_fa=st_val.get("notes_fa"),
            )

        crops[crop_id] = CropThresholdConfig(
            crop_key=crop_id,
            common_name_fa=c_data.get("common_name_fa", crop_id),
            scientific_name=c_data.get("scientific_name", ""),
            status=status,
            source=source,
            verified=bool(verified),
            verification_warning_fa=warning_fa,
            stages=crop_stages,
        )

    return crops


@dataclass
class ColdAirPoolingAdjustmentConfig:
    """Configurable thresholds for topographically-driven cold-air pooling temperature bump.

    All physical parameters are placeholders marked 'needs calibration' with local meteorological stations.
    """

    status: str = "placeholder"
    notes: str = "Needs calibration against local microclimate station network"
    min_pooling_proxy_threshold: float = 0.40  # Below this proxy, no cooling bump applied
    max_cooling_bump_c: float = 2.5            # Max cooling bump under calm radiative conditions
    wind_speed_calm_mps: float = 1.5           # Speed at or below which full pooling develops
    wind_speed_drain_mps: float = 4.0          # Speed at or above which turbulent mixing drains pool


def load_cold_air_pooling_config(
    config_path: Optional[Path] = None,
) -> ColdAirPoolingAdjustmentConfig:
    """Load cold-air pooling adjustment parameters from config YAML if present."""
    resolved_path: Optional[Path] = None
    if config_path and config_path.exists():
        resolved_path = config_path
    else:
        for p in _CONFIG_PATHS:
            if p and p.exists() and p.is_file():
                resolved_path = p
                break

    if not resolved_path:
        return ColdAirPoolingAdjustmentConfig()

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict) and "cold_air_pooling" in raw:
            p_data = raw["cold_air_pooling"]
            return ColdAirPoolingAdjustmentConfig(
                status=p_data.get("status", "placeholder"),
                notes=p_data.get("notes", "Needs calibration against local microclimate station network"),
                min_pooling_proxy_threshold=float(p_data.get("min_pooling_proxy_threshold", 0.40)),
                max_cooling_bump_c=float(p_data.get("max_cooling_bump_c", 2.5)),
                wind_speed_calm_mps=float(p_data.get("wind_speed_calm_mps", 1.5)),
                wind_speed_drain_mps=float(p_data.get("wind_speed_drain_mps", 4.0)),
            )
    except Exception as exc:
        logger.warning("Could not parse cold_air_pooling section from %s: %s", resolved_path, exc)

    return ColdAirPoolingAdjustmentConfig()


@dataclass
class NightlyFrostRisk:
    """Frost risk and thermal metrics for a single local night."""

    night_date: str                     # e.g. "2026-03-20"
    night_display_fa: str               # e.g. "شب جمعه ۲۹ اسفند به شنبه ۱ فروردین"
    start_time_utc: str
    end_time_utc: str
    tmin_forecast_c: float
    tmin_adjusted_c: float              # After topography cold-air-pooling bump
    tmin_lower_c: float                 # With forecast uncertainty envelope (conservative lower bound)
    tmin_upper_c: float
    min_temp_timestamp_utc: str
    hours_below_tc10: float
    hours_below_tc90: float
    wind_speed_at_tmin_mps: Optional[float]
    pooling_cooling_bump_c: float
    uncertainty_margin_c: float
    risk_level: str
    risk_level_fa: str
    thresholds_verified: bool
    recommendations_fa: List[str]
    recommendations_review_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrostRiskAssessment:
    """Overall frost risk assessment across forecast horizon."""

    crop: str
    phenological_stage: str
    crop_fa: str
    stage_fa: str
    t_critical_10_c: float
    t_critical_90_c: float
    thresholds_status: str
    thresholds_source: Optional[str]
    thresholds_verified: bool
    thresholds_warning_fa: str
    pooling_risk_proxy: float
    overall_risk_level: str
    overall_risk_level_fa: str
    nightly_risks: List[NightlyFrostRisk]
    disclaimer_fa: str
    recommendations_warning_fa: str = RECOMMENDATION_WARNING_FA
    evidence_level: str = "B"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def aggregate_forecast_by_local_night(
    series: List[ForecastTimestep],
    local_utc_offset_hours: float = DEFAULT_LOCAL_UTC_OFFSET_HOURS,
    night_start_local_hour: int = 18,
    night_end_local_hour: int = 9,
) -> Dict[str, List[ForecastTimestep]]:
    """Partition hourly timesteps into local night windows crossing UTC midnight.

    A local night spans from ``night_start_local_hour`` (e.g. 18:00 local) on date D
    to ``night_end_local_hour`` (e.g. 09:00 local) on date D+1.
    Crossing UTC midnight is handled transparently.
    """
    nights: Dict[str, List[ForecastTimestep]] = {}
    tz_local = timezone(timedelta(hours=local_utc_offset_hours))

    for step in series:
        dt_utc = datetime.fromisoformat(step.timestamp_utc.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(tz_local)
        hour = dt_local.hour

        # Determine which calendar night this belongs to:
        # If hour >= 18:00, it belongs to the night of dt_local.date()
        # If hour < 09:00, it belongs to the night that started yesterday (dt_local.date() - 1 day)
        if hour >= night_start_local_hour:
            night_key = dt_local.strftime("%Y-%m-%d")
        elif hour < night_end_local_hour:
            night_key = (dt_local.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # Daytime step (between 09:00 and 18:00 local)
            continue

        if night_key not in nights:
            nights[night_key] = []
        nights[night_key].append(step)

    return nights


def calculate_pooling_cooling_bump(
    pooling_risk_proxy: float,
    wind_speed_mps: Optional[float] = None,
    max_cooling_bump_c: Optional[float] = None,
    config: Optional[ColdAirPoolingAdjustmentConfig] = None,
) -> float:
    """Calculate cold air pooling temperature bump.

    Physical rationale:
    During radiative frost, topography depressions trap cold air, cooling up to
    1.0-3.0 °C below the regional GFS grid forecast.
    High wind speeds disrupt boundary layer stratification and drain
    the pool via mechanical turbulence mixing.

    SAFETY CONSTRAINT:
    The pooling term must NEVER warm: clip the adjustment at 0.0.
    Ridges are not credited with warming; false-safe is the dangerous direction.
    """
    cfg = config or ColdAirPoolingAdjustmentConfig()
    max_bump = max_cooling_bump_c if max_cooling_bump_c is not None else cfg.max_cooling_bump_c
    min_thresh = cfg.min_pooling_proxy_threshold
    w_calm = cfg.wind_speed_calm_mps
    w_drain = cfg.wind_speed_drain_mps

    if pooling_risk_proxy <= min_thresh:
        return 0.0

    # Linear pooling scaling above min_thresh
    scaling_range = max(0.01, 1.0 - min_thresh)
    raw_bump = (pooling_risk_proxy - min_thresh) / scaling_range * max_bump

    # Wind damping: above w_calm, turbulent mixing rapidly breaks cold pools
    if wind_speed_mps is not None:
        if wind_speed_mps >= w_drain:
            wind_factor = 0.0
        elif wind_speed_mps <= w_calm:
            wind_factor = 1.0
        else:
            wind_factor = max(0.0, 1.0 - (wind_speed_mps - w_calm) / max(0.01, (w_drain - w_calm)))
        raw_bump *= wind_factor

    # CRITICAL: Clip adjustment at 0.0 so pooling NEVER warms
    return max(0.0, round(float(raw_bump), 2))


def classify_nightly_risk(
    t_min_adjusted_c: float,
    t_min_lower_c: float,
    hours_below_tc10: float,
    tc10_c: float,
    tc90_c: float,
) -> Tuple[str, str]:
    """Classify frost risk level into none, advisory, watch, or warning."""
    # Definite lethal frost: adjusted minimum drops below 90% kill or long exposure below 10%
    if t_min_adjusted_c <= tc90_c or (t_min_adjusted_c <= tc10_c and hours_below_tc10 >= 2.0):
        return RISK_LEVEL_WARNING, RISK_LEVEL_FA[RISK_LEVEL_WARNING]

    # Probable frost: adjusted min below 10% or lower confidence bound below 10% with exposure
    if t_min_adjusted_c <= tc10_c or (t_min_lower_c <= tc10_c and hours_below_tc10 >= 1.0):
        return RISK_LEVEL_WATCH, RISK_LEVEL_FA[RISK_LEVEL_WATCH]

    # Advisory: marginal proximity (within 2°C of critical) or uncertainty bound touches critical
    if t_min_adjusted_c <= (tc10_c + 2.0) or t_min_lower_c <= tc10_c:
        return RISK_LEVEL_ADVISORY, RISK_LEVEL_FA[RISK_LEVEL_ADVISORY]

    return RISK_LEVEL_NONE, RISK_LEVEL_FA[RISK_LEVEL_NONE]


def assess_frost_risk(
    forecast: ForecastResult,
    crop: str = "pistachio",
    phenological_stage: str = "early_bloom",
    pooling_result: Optional[ColdAirPoolingResult] = None,
    pooling_risk_proxy: Optional[float] = None,
    thresholds_config_path: Optional[Path] = None,
    local_utc_offset_hours: float = DEFAULT_LOCAL_UTC_OFFSET_HOURS,
    hard_cap_horizon_h: Optional[int] = None,
) -> FrostRiskAssessment:
    """Execute complete frost risk evaluation combining forecast, thresholds, and topography.

    Returns:
        FrostRiskAssessment dataclass carrying nightly risks, disclaimers,
        and threshold verification status.
    """
    # 1. Load phenological thresholds
    configs = load_frost_thresholds_config(thresholds_config_path)
    if crop not in configs:
        raise ValueError(f"Crop '{crop}' not found in frost thresholds configuration.")

    crop_cfg = configs[crop]
    unknown_stage_note_fa = ""
    if not phenological_stage or phenological_stage == "unknown":
        # Conservative safety fallback: select the most sensitive phenological stage (highest critical temperature)
        most_sensitive = max(crop_cfg.stages.values(), key=lambda s: s.t_critical_10_c)
        stage_cfg = most_sensitive
        unknown_stage_note_fa = (
            f"مرحله فنولوژیکی نامشخص است؛ بر مبنای اصل احتیاط کشاورزی، حساس‌ترین مرحله رشد "
            f"({stage_cfg.name_fa} با آستانه ۱۰٪ خسارت {stage_cfg.t_critical_10_c}°C) به عنوان مبنای ارزیابی در نظر گرفته شد."
        )
    elif phenological_stage not in crop_cfg.stages:
        raise ValueError(
            f"Stage '{phenological_stage}' not found for crop '{crop}'. "
            f"Available stages: {list(crop_cfg.stages.keys())}"
        )
    else:
        stage_cfg = crop_cfg.stages[phenological_stage]

    tc10 = stage_cfg.t_critical_10_c
    tc90 = stage_cfg.t_critical_90_c

    # 2. Topography pooling proxy & configuration
    pooling_cfg = load_cold_air_pooling_config(thresholds_config_path)
    if pooling_risk_proxy is not None:
        p_proxy = pooling_risk_proxy
    elif pooling_result is not None:
        p_proxy = pooling_result.mean_pooling_risk_proxy
    else:
        p_proxy = 0.50  # Default neutral

    # 3. Aggregate forecast timesteps by local night
    nights_map = aggregate_forecast_by_local_night(
        forecast.series,
        local_utc_offset_hours=local_utc_offset_hours,
    )

    nightly_risks: List[NightlyFrostRisk] = []
    overall_level = RISK_LEVEL_NONE

    risk_hierarchy = {
        RISK_LEVEL_NONE: 0,
        RISK_LEVEL_ADVISORY: 1,
        RISK_LEVEL_WATCH: 2,
        RISK_LEVEL_WARNING: 3,
    }

    hard_cap = hard_cap_horizon_h if hard_cap_horizon_h is not None else FROST_HARD_CAP_HORIZON_H

    for night_key in sorted(nights_map.keys()):
        raw_steps = nights_map[night_key]
        # Beyond the hard cap: return no nightly risk
        steps = [s for s in raw_steps if s.lead_hours <= hard_cap]
        if not steps:
            continue

        # Sort chronologically
        steps.sort(key=lambda s: s.timestamp_utc)
        start_utc = steps[0].timestamp_utc
        end_utc = steps[-1].timestamp_utc

        # Find minimum temperature step
        min_step = min(steps, key=lambda s: s.temperature_2m_c)
        t_raw_min = min_step.temperature_2m_c
        t_min_time = min_step.timestamp_utc
        wind_at_min = min_step.wind_speed_10m_mps
        unc_at_min = min_step.total_uncertainty_c

        # Calculate cold air pooling bump
        cooling_bump = calculate_pooling_cooling_bump(p_proxy, wind_at_min, config=pooling_cfg)
        t_adjusted_min = round(t_raw_min - cooling_bump, 2)
        t_lower = round(t_adjusted_min - unc_at_min, 2)
        t_upper = round(t_adjusted_min + unc_at_min, 2)

        # Count hours below thresholds (approximate 1 hour per step; flag interpolated)
        # We calculate exposure duration based on adjusted temperatures
        hrs_tc10 = sum(1.0 for s in steps if (s.temperature_2m_c - cooling_bump) <= tc10)
        hrs_tc90 = sum(1.0 for s in steps if (s.temperature_2m_c - cooling_bump) <= tc90)

        # Risk level classification
        level, level_fa = classify_nightly_risk(
            t_min_adjusted_c=t_adjusted_min,
            t_min_lower_c=t_lower,
            hours_below_tc10=hrs_tc10,
            tc10_c=tc10,
            tc90_c=tc90,
        )

        if risk_hierarchy[level] > risk_hierarchy[overall_level]:
            overall_level = level

        # Recommendations if risk is elevated
        recs = GENERIC_RECOMMENDATIONS_FA if level != RISK_LEVEL_NONE else []

        nightly_risks.append(
            NightlyFrostRisk(
                night_date=night_key,
                night_display_fa=f"شب {night_key}",
                start_time_utc=start_utc,
                end_time_utc=end_utc,
                tmin_forecast_c=t_raw_min,
                tmin_adjusted_c=t_adjusted_min,
                tmin_lower_c=t_lower,
                tmin_upper_c=t_upper,
                min_temp_timestamp_utc=t_min_time,
                hours_below_tc10=float(hrs_tc10),
                hours_below_tc90=float(hrs_tc90),
                wind_speed_at_tmin_mps=wind_at_min,
                pooling_cooling_bump_c=cooling_bump,
                uncertainty_margin_c=unc_at_min,
                risk_level=level,
                risk_level_fa=level_fa,
                thresholds_verified=crop_cfg.verified,
                recommendations_fa=recs,
                recommendations_review_required=True,
            )
        )

    disclaimer = (
        "هشدار: این مدل بر مبنای پیش‌بینی عددی GFS و شاخص تجمیع توپوگرافی تولید شده است. "
        "با توجه به عدم تایید نهایی آستانه‌های فیزیولوژیک (وضعیت: placeholder)، "
        "ارقام دمایی و سطوح خطر صرفاً برای آماده‌باش مشورتی بوده و اتخاذ تدابیر عملیاتی "
        "باید با نظر مستقیم مروجین کشاورزی صورت گیرد."
    )

    combined_warning = crop_cfg.verification_warning_fa
    if unknown_stage_note_fa:
        combined_warning = f"{combined_warning} {unknown_stage_note_fa}".strip()

    return FrostRiskAssessment(
        crop=crop,
        phenological_stage=stage_cfg.stage_key,
        crop_fa=crop_cfg.common_name_fa,
        stage_fa=stage_cfg.name_fa,
        t_critical_10_c=tc10,
        t_critical_90_c=tc90,
        thresholds_status=crop_cfg.status,
        thresholds_source=crop_cfg.source,
        thresholds_verified=crop_cfg.verified,
        thresholds_warning_fa=combined_warning,
        pooling_risk_proxy=round(p_proxy, 3),
        overall_risk_level=overall_level,
        overall_risk_level_fa=RISK_LEVEL_FA[overall_level],
        nightly_risks=nightly_risks,
        disclaimer_fa=disclaimer,
        recommendations_warning_fa=RECOMMENDATION_WARNING_FA,
        evidence_level="B",
    )
