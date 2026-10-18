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
RISK_LEVEL_CRITICAL = "critical"

RISK_LEVEL_FA = {
    RISK_LEVEL_NONE: "عادی (بدون خطر)",
    RISK_LEVEL_ADVISORY: "اطلاعیه پایش (احتمال سرما)",
    RISK_LEVEL_WATCH: "دیده‌بانی سرما (خطر متوسط / افت کوتاه‌مدت)",
    RISK_LEVEL_WARNING: "هشدار سرمازدگی (خطر جدی خسارت)",
    RISK_LEVEL_CRITICAL: "سرمازدگی بحرانی (خطر نکروز بافت و خسارت شدید)",
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
class DurationRule:
    """Published duration threshold rule for a phenological stage (E8)."""

    reference_temperature_c: float
    min_hours: float
    category: str
    source: str
    description_fa: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DurationExposureResult:
    """Interval-based exposure below reference temperature (E8)."""

    reference_temperature_c: float
    total_hours: float
    longest_continuous_hours: float
    longest_run_start_local: Optional[str] = None
    longest_run_end_local: Optional[str] = None
    active_rule_source: Optional[str] = None
    active_rule_category: Optional[str] = None
    rule_note_fa: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StageThreshold:
    """Critical temperatures and duration rules for a single phenological stage."""

    stage_key: str
    name_fa: str
    t_critical_10_c: float
    t_critical_90_c: float
    status: str
    source: Optional[str]
    t_critical_c: Optional[float] = None
    conflicting_published_value: Optional[float] = None
    conflicting_source: Optional[str] = None
    conflicting_notes_fa: Optional[str] = None
    duration_rules: Optional[List[DurationRule]] = None
    notes_fa: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



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

        if not status or status not in ("placeholder", "verified", "published"):
            raise ValueError(
                f"Crop '{crop_id}' must disclose 'status' as 'placeholder', 'published', or 'verified', got: {status}"
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
            if not st_status or st_status not in ("placeholder", "verified", "published"):
                raise ValueError(
                    f"Stage '{crop_id}.{st_id}' must disclose 'status' as 'placeholder', 'published', or 'verified'."
                )

            tc10 = float(st_val["t_critical_10_c"])
            tc90 = float(st_val["t_critical_90_c"])

            # 90% kill temperature must be strictly lower than 10% kill temperature
            if tc90 >= tc10:
                raise ValueError(
                    f"Stage '{crop_id}.{st_id}' thermodynamic violation: "
                    f"t_critical_90_c ({tc90}) must be colder than t_critical_10_c ({tc10})."
                )

            duration_rules = None
            if "duration_rules" in st_val and st_val["duration_rules"] is not None:
                duration_rules = []
                for dr in st_val["duration_rules"]:
                    duration_rules.append(
                        DurationRule(
                            reference_temperature_c=float(dr["reference_temperature_c"]),
                            min_hours=float(dr["min_hours"]),
                            category=str(dr["category"]),
                            source=str(dr["source"]),
                            description_fa=dr.get("description_fa"),
                        )
                    )

            crop_stages[st_id] = StageThreshold(
                stage_key=st_id,
                name_fa=st_val.get("name_fa", st_id),
                t_critical_10_c=tc10,
                t_critical_90_c=tc90,
                status=st_status,
                source=st_source,
                t_critical_c=float(st_val["t_critical_c"]) if "t_critical_c" in st_val and st_val["t_critical_c"] is not None else None,
                conflicting_published_value=float(st_val["conflicting_published_value"]) if "conflicting_published_value" in st_val and st_val["conflicting_published_value"] is not None else None,
                conflicting_source=st_val.get("conflicting_source"),
                conflicting_notes_fa=st_val.get("conflicting_notes_fa"),
                duration_rules=duration_rules,
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

    # Sourced duration rules & interval-based exposure metrics (E8)
    min_temp_timestamp_local: str = ""
    duration_resolvable: bool = True
    cadence_coarse: bool = False
    short_dip: bool = False
    duration_escalated: bool = False
    duration_display_text: str = ""
    duration_rule_explanation_fa: str = ""
    nominal_exposure: Optional[DurationExposureResult] = None
    pessimistic_exposure: Optional[DurationExposureResult] = None
    conflicting_published_value: Optional[float] = None
    conflicting_value_note_fa: Optional[str] = None

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
    evidence_level: str = "C"
    geometry_type: str = "Polygon"
    location_sampling_method: str = "Polygon: forecast at centroid cell; elevation = polygon mean DEM"

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
    """Classify frost risk level into none, advisory, watch, or warning (legacy helper)."""
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


def calculate_interval_duration_run(
    steps: List[ForecastTimestep],
    reference_temp_c: float,
    cooling_bump_c: float,
    use_pessimistic: bool = False,
    local_utc_offset_hours: float = DEFAULT_LOCAL_UTC_OFFSET_HOURS,
) -> Tuple[float, float, Optional[str], Optional[str], bool]:
    """Calculate interval-based total and longest continuous hours below reference temperature (E8).

    Interval Arithmetic Definition:
    1. Timesteps in hourly series have spacing dt <= 1.5h (nominal dt = 1.0h).
    2. Each step below threshold contributes exactly 1.0 hour of exposure duration.
    3. If any step spacing in the series exceeds 1.5h (e.g. 3-hourly data beyond 120h),
       is_resolvable is set to False ('not resolvable').
    4. Continuous runs are sequences of consecutive steps below threshold with dt <= 1.5h.
    5. Run start and end timestamps are formatted in local Asia/Tehran time (HH:MM).

    Returns:
        (total_hours, longest_continuous_hours, start_local_hhmm, end_local_hhmm, is_resolvable)
    """
    if not steps:
        return 0.0, 0.0, None, None, True

    tz_local = timezone(timedelta(hours=local_utc_offset_hours))

    # Check for coarse cadence (> 1.5h step spacing)
    is_resolvable = True
    for i in range(len(steps) - 1):
        dt_i = datetime.fromisoformat(steps[i].timestamp_utc.replace("Z", "+00:00"))
        dt_next = datetime.fromisoformat(steps[i + 1].timestamp_utc.replace("Z", "+00:00"))
        spacing_h = (dt_next - dt_i).total_seconds() / 3600.0
        if spacing_h > 1.5:
            is_resolvable = False
            break

    # If not resolvable (3-hourly data beyond 120h), duration is not resolvable
    if not is_resolvable:
        return 0.0, 0.0, None, None, False

    below_mask: List[bool] = []
    for s in steps:
        t_eff = s.temperature_2m_c - cooling_bump_c
        if use_pessimistic:
            t_eff -= s.total_uncertainty_c
        below_mask.append(t_eff <= reference_temp_c)

    # Extract contiguous runs
    runs: List[Tuple[int, int]] = []
    in_run = False
    run_start = 0

    for idx, is_below in enumerate(below_mask):
        if is_below and not in_run:
            in_run = True
            run_start = idx
        elif not is_below and in_run:
            in_run = False
            runs.append((run_start, idx - 1))
    if in_run:
        runs.append((run_start, len(below_mask) - 1))

    total_steps = sum((b - a + 1) for a, b in runs)
    total_hours = float(total_steps) * 1.0

    if not runs:
        return 0.0, 0.0, None, None, True

    # Find longest continuous run
    longest_run = max(runs, key=lambda r: (r[1] - r[0] + 1))
    longest_hours = float(longest_run[1] - longest_run[0] + 1) * 1.0

    dt_start = datetime.fromisoformat(steps[longest_run[0]].timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local)
    dt_end = datetime.fromisoformat(steps[longest_run[1]].timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local)

    start_local = dt_start.strftime("%H:%M")
    end_local = dt_end.strftime("%H:%M")

    return total_hours, longest_hours, start_local, end_local, True


def evaluate_duration_rule_category(
    min_temp_adjusted_c: float,
    min_temp_pessimistic_c: float,
    reference_temp_c: float,
    continuous_hours_nominal: float,
    continuous_hours_pessimistic: float,
    duration_rules: Optional[List[DurationRule]],
    duration_resolvable: bool = True,
) -> Tuple[str, str, bool, bool, str]:
    """Evaluate severity category according to the official Decision Table (docs/frost-decision-table.md).

    Returns:
        (category, category_fa, short_dip, duration_escalated, explanation_fa)
    """
    # 1. 3-Hourly data beyond 120h (duration is not resolvable)
    if not duration_resolvable:
        if min_temp_adjusted_c <= reference_temp_c - 2.0:
            cat = RISK_LEVEL_CRITICAL
        elif min_temp_adjusted_c <= reference_temp_c:
            cat = RISK_LEVEL_WARNING
        elif min_temp_pessimistic_c <= reference_temp_c:
            cat = RISK_LEVEL_WATCH
        else:
            cat = RISK_LEVEL_NONE
        expl = "فراتر از ۱۲۰ ساعت: داده‌ها ۳-ساعته بوده و مدت تداوم قابل تفکیک نیست؛ دسته‌بندی صرفاً بر اساس دما صورت گرفت."
        return cat, RISK_LEVEL_FA[cat], False, False, expl

    # 2. Nominal temperature stays above reference threshold
    if min_temp_adjusted_c > reference_temp_c:
        # Check pessimistic temperature (pessimistic-only escalation rule: ONLY raises to watch)
        if min_temp_pessimistic_c <= reference_temp_c:
            cat = RISK_LEVEL_WATCH
            expl = "دمای اسمی بالاتر از آستانه است، اما با احتساب عدم‌قطعیت پیش‌بینی (T - σ) احتمال ورود به محدوده سرمازدگی وجود دارد (دیده‌بانی)."
            return cat, RISK_LEVEL_FA[cat], False, False, expl
        cat = RISK_LEVEL_NONE
        expl = "دمای کمینه پیش‌بینی‌شده در محدوده امن قرار دارد."
        return cat, RISK_LEVEL_FA[cat], False, False, expl

    # 3. Nominal temperature drops below reference threshold (min_temp_adjusted_c <= reference_temp_c)
    # 3A. No published duration rules (duration_rules is None or empty)
    if not duration_rules:
        if min_temp_adjusted_c <= reference_temp_c - 1.5:
            cat = RISK_LEVEL_CRITICAL
        else:
            cat = RISK_LEVEL_WARNING
        expl = "برای این مرحله داده منتشرشده‌ای برای مدت ماندن زیر آستانه وجود ندارد؛ دسته‌بندی فقط بر اساس دما است."
        return cat, RISK_LEVEL_FA[cat], False, False, expl

    # 3B. Active published duration rules present (e.g. S1 p. 72 rules for bud stages at <= -4°C)
    # Check continuous hours nominal:
    if continuous_hours_nominal < 1.0:
        cat = RISK_LEVEL_WATCH
        short_dip = True
        duration_escalated = False
        expl = f"افت کوتاه‌مدت ({continuous_hours_nominal:.1f} ساعت) زیر آستانه {reference_temp_c:.1f}°C؛ ریسک در سطح دیده‌بانی باقی می‌ماند."
    elif continuous_hours_nominal < 2.0:
        cat = RISK_LEVEL_WARNING
        short_dip = False
        duration_escalated = False
        expl = f"تداوم {continuous_hours_nominal:.1f} ساعت زیر آستانه {reference_temp_c:.1f}°C (هشدار سرمازدگی)."
    elif continuous_hours_nominal < 6.0:
        cat = RISK_LEVEL_CRITICAL
        short_dip = False
        duration_escalated = True
        expl = f"تداوم حداقل ۲ ساعت ({continuous_hours_nominal:.1f} ساعت) زیر آستانه {reference_temp_c:.1f}°C منجر به سطح بحرانی خسارت جوانه می‌شود (منبع: حکم‌آبادی ۱۳۸۹، ص ۷۲ [S1])."
    else:
        cat = RISK_LEVEL_CRITICAL
        short_dip = False
        duration_escalated = True
        expl = f"تداوم طولانی ({continuous_hours_nominal:.1f} ساعت) زیر آستانه {reference_temp_c:.1f}°C منجر به نکروز کامل بافت گل و جوانه می‌شود (منبع: حکم‌آبادی ۱۳۸۹، ص ۷۲ [S1])."

    return cat, RISK_LEVEL_FA[cat], short_dip, duration_escalated, expl


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
    if not phenological_stage or phenological_stage == "unknown" or phenological_stage not in crop_cfg.stages:
        # Conservative safety fallback: select the most sensitive phenological stage (highest critical temperature)
        most_sensitive = max(crop_cfg.stages.values(), key=lambda s: s.t_critical_10_c)
        stage_cfg = most_sensitive
        unknown_stage_note_fa = (
            f"مرحله فنولوژیکی نامشخص است؛ بر مبنای اصل احتیاط کشاورزی، حساس‌ترین مرحله رشد "
            f"({stage_cfg.name_fa} با آستانه ۱۰٪ خسارت {stage_cfg.t_critical_10_c}°C) به عنوان مبنای ارزیابی در نظر گرفته شد."
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
        RISK_LEVEL_CRITICAL: 4,
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

        # Local time formatting for minimum temperature
        tz_local = timezone(timedelta(hours=local_utc_offset_hours))
        dt_min = datetime.fromisoformat(t_min_time.replace("Z", "+00:00")).astimezone(tz_local)
        min_temp_timestamp_local = dt_min.strftime("%H:%M")

        # Reference temperature for duration checks
        ref_temp = (
            stage_cfg.duration_rules[0].reference_temperature_c
            if stage_cfg.duration_rules
            else (stage_cfg.t_critical_c if stage_cfg.t_critical_c is not None else tc10)
        )

        # Interval-based duration calculations (E8)
        nom_total, nom_longest, nom_start_loc, nom_end_loc, is_resolvable = calculate_interval_duration_run(
            steps,
            reference_temp_c=ref_temp,
            cooling_bump_c=cooling_bump,
            use_pessimistic=False,
            local_utc_offset_hours=local_utc_offset_hours,
        )

        pess_total, pess_longest, pess_start_loc, pess_end_loc, _ = calculate_interval_duration_run(
            steps,
            reference_temp_c=ref_temp,
            cooling_bump_c=cooling_bump,
            use_pessimistic=True,
            local_utc_offset_hours=local_utc_offset_hours,
        )

        level, level_fa, short_dip, duration_escalated, expl_fa = evaluate_duration_rule_category(
            min_temp_adjusted_c=t_adjusted_min,
            min_temp_pessimistic_c=t_lower,
            reference_temp_c=ref_temp,
            continuous_hours_nominal=nom_longest,
            continuous_hours_pessimistic=pess_longest,
            duration_rules=stage_cfg.duration_rules,
            duration_resolvable=is_resolvable,
        )

        if not is_resolvable:
            duration_display_text = "مدت تداوم نامشخص (داده‌های فراتر از ۱۲۰ ساعت با گام ۳-ساعته)"
        elif nom_total > 0 and nom_start_loc and nom_end_loc:
            duration_display_text = (
                f"{nom_total:.1f} h below {ref_temp:.1f}°C "
                f"(longest continuous {nom_longest:.1f} h, from {nom_start_loc} to {nom_end_loc})"
            )
        else:
            duration_display_text = f"0.0 h below {ref_temp:.1f}°C"

        hrs_tc10 = sum(1.0 for s in steps if (s.temperature_2m_c - cooling_bump) <= tc10)
        hrs_tc90 = sum(1.0 for s in steps if (s.temperature_2m_c - cooling_bump) <= tc90)

        if risk_hierarchy.get(level, 0) > risk_hierarchy.get(overall_level, 0):
            overall_level = level

        # Recommendations if risk is elevated
        recs = GENERIC_RECOMMENDATIONS_FA if level != RISK_LEVEL_NONE else []

        active_rule_src = stage_cfg.duration_rules[0].source if stage_cfg.duration_rules else None
        nominal_exposure = DurationExposureResult(
            reference_temperature_c=ref_temp,
            total_hours=nom_total,
            longest_continuous_hours=nom_longest,
            longest_run_start_local=nom_start_loc,
            longest_run_end_local=nom_end_loc,
            active_rule_source=active_rule_src,
            active_rule_category=level if duration_escalated else None,
            rule_note_fa=expl_fa,
        )

        pessimistic_exposure = DurationExposureResult(
            reference_temperature_c=ref_temp,
            total_hours=pess_total,
            longest_continuous_hours=pess_longest,
            longest_run_start_local=pess_start_loc,
            longest_run_end_local=pess_end_loc,
            active_rule_source=active_rule_src,
            active_rule_category=None,
            rule_note_fa="سناریوی بدبینانه (T_eff - sigma)",
        )

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
                min_temp_timestamp_local=min_temp_timestamp_local,
                duration_resolvable=is_resolvable,
                cadence_coarse=not is_resolvable,
                short_dip=short_dip,
                duration_escalated=duration_escalated,
                duration_display_text=duration_display_text,
                duration_rule_explanation_fa=expl_fa,
                nominal_exposure=nominal_exposure,
                pessimistic_exposure=pessimistic_exposure,
                conflicting_published_value=stage_cfg.conflicting_published_value,
                conflicting_value_note_fa=stage_cfg.conflicting_notes_fa,
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

    geom_type = getattr(forecast, "geometry_type", "Polygon")
    loc_method = getattr(
        forecast,
        "location_sampling_method",
        "Polygon: forecast at centroid cell; elevation = polygon mean DEM",
    )

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
        evidence_level="B" if crop_cfg.verified else "C",
        geometry_type=geom_type,
        location_sampling_method=loc_method,
    )
