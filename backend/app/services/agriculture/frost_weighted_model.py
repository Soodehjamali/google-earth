"""Weighted Factor Model Engine per Orchard (R3).

Implements Phase 3 Redesign v2 Model Engine:
1. Loads factor weights from config/frost_factor_weights.yaml and rejects configs
   whose weights do not sum to exactly 100.0.
2. Computes subscores s_i in [0, 1] (0 favorable, 1 adverse; 0.5 neutral / missing)
   using piecewise-linear and categorical breakpoints.
3. Asymmetric conservatism: rows tagged protective_capable cannot score below 0.5
   when derived from coarse_context data. Only verified 'valid' inputs can score favorable.
   Floor NEVER applies to the temperature row.
4. Total index = sum(weight_i * s_i) in 0-100.
5. Absolute Safety Gate (GATE):
   - If effective Tmin <= stage critical temperature: at least 'warning'.
   - If duration rule met: 'critical'.
   - final_category = max(index_category, gate_category).
   The gate guarantees a lethal temperature is NEVER diluted by favorable modifiers.
6. Evidence level stays 'C'; response flags index_is_probability=False and thresholds_verified=False.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml

from app.core.logging import get_logger
from app.services.agriculture.frost_inputs import (
    FactorInput,
    OrchardInputs,
    FACTOR_RESOLUTION_MAP,
    FACTOR_SOURCE_FA_MAP,
)

STAGE_NAME_FA: Dict[str, str] = {
    "dormant": "خواب زمستانه",
    "unopened_bud": "جوانه بازنشده",
    "swelling_bud": "جوانه در حال تورم",
    "bud_burst": "باز شدن جوانه",
    "bloom": "گلدهی / شکوفه بازشده",
    "early_bloom": "اوایل گلدهی",
    "full_bloom": "گل کامل",
    "fruit_set": "تشکیل میوه اولیه",
}

logger = get_logger(__name__)

_DEFAULT_WEIGHTS_PATH = [
    Path(os.environ.get("FROST_FACTOR_WEIGHTS_FILE", "")),
    Path("config/frost_factor_weights.yaml"),
    Path("../config/frost_factor_weights.yaml"),
    Path(__file__).resolve().parents[4] / "config" / "frost_factor_weights.yaml",
]

RISK_HIERARCHY = {
    "none": 0,
    "watch": 1,
    "warning": 2,
    "critical": 3,
}

RISK_CATEGORY_FA = {
    "none": "عادی (بدون خطر)",
    "watch": "دیده‌بانی سرما",
    "warning": "هشدار سرمازدگی",
    "critical": "سرمازدگی بحرانی",
}


@dataclass
class FrostFactorRow:
    id: str
    label_fa: str
    weight: float
    input_source: str
    source_module: str
    protective_capable: bool
    quality_rule: str
    status_placeholder: str
    source_note: str
    margin_safe_c: float = 3.0
    stage_subscores: Dict[str, float] = field(default_factory=dict)
    texture_subscores: Dict[str, float] = field(default_factory=dict)
    breakpoints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FrostWeightedModelConfig:
    factors: List[FrostFactorRow]
    category_bands: Dict[str, float]
    cold_advection_sectors: List[List[float]]
    illustrative_only: bool = True
    evidence_level: str = "C"
    index_is_probability: bool = False
    thresholds_verified: bool = False

    temperature_necessity: Dict[str, Any] = field(default_factory=dict)

    def get_factor(self, factor_id: str) -> Optional[FrostFactorRow]:
        for f in self.factors:
            if f.id == factor_id:
                return f
        return None


def load_frost_factor_weights_config(
    config_path: Optional[Union[str, Path]] = None,
) -> FrostWeightedModelConfig:
    """Load and validate frost factor weights configuration.

    Rejects configuration files if weights do not sum to exactly 100.0%.
    """
    path_to_try: Optional[Path] = None
    if config_path:
        path_to_try = Path(config_path)
    else:
        for p in _DEFAULT_WEIGHTS_PATH:
            if p and p.exists() and p.is_file():
                path_to_try = p
                break

    if not path_to_try or not path_to_try.exists():
        raise FileNotFoundError(f"Frost factor weights config file not found: {path_to_try}")

    with open(path_to_try, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML content in {path_to_try}")

    raw_factors = data.get("factors", [])
    if not raw_factors:
        raise ValueError("Missing 'factors' list in frost factor weights config")

    parsed_factors: List[FrostFactorRow] = []
    total_weight = 0.0

    for item in raw_factors:
        fid = item.get("id")
        lbl = item.get("label_fa", fid)
        w = float(item.get("weight", 0.0))
        total_weight += w

        row = FrostFactorRow(
            id=fid,
            label_fa=lbl,
            weight=w,
            input_source=item.get("input_source", ""),
            source_module=item.get("source_module", ""),
            protective_capable=bool(item.get("protective_capable", False)),
            quality_rule=item.get("quality_rule", ""),
            status_placeholder=item.get("status_placeholder", "placeholder"),
            source_note=item.get("source_note", ""),
            margin_safe_c=float(item.get("margin_safe_c", 3.0)),
            stage_subscores=item.get("stage_subscores", {}),
            texture_subscores=item.get("texture_subscores", {}),
            breakpoints=item.get("breakpoints", {}),
        )
        parsed_factors.append(row)

    # Loader rejects configuration if sum != 100.0
    if abs(total_weight - 100.0) > 1e-4:
        raise ValueError(
            f"Frost factor weights must sum to exactly 100.0%, got {total_weight:.2f}%"
        )

    bands = data.get("category_bands", {
        "none_max": 25.0,
        "watch_max": 45.0,
        "warning_max": 70.0,
    })
    cold_sectors = data.get("cold_advection_sectors", [])
    temp_necessity = data.get("temperature_necessity_attenuation", {
        "label_fa": "تعدیل‌گر شرط لازم دما (placeholder کالیبره‌نشده)",
        "status": "placeholder کالیبره‌نشده",
        "source_note": "برآورد کارشناسی کالیبره‌نشده",
        "margin_safe_c": 4.0,
        "margin_warm_c": 10.0,
        "m_min": 0.10,
    })

    return FrostWeightedModelConfig(
        factors=parsed_factors,
        category_bands=bands,
        cold_advection_sectors=cold_sectors,
        illustrative_only=bool(data.get("illustrative_only", True)),
        evidence_level=str(data.get("evidence_level", "C")),
        index_is_probability=bool(data.get("index_is_probability", False)),
        thresholds_verified=bool(data.get("thresholds_verified", False)),
        temperature_necessity=temp_necessity,
    )


@dataclass
class EvaluatedFactor:
    """Evaluated single factor row for API responses and table rendering."""

    id: str
    label_fa: str
    raw_value: Any
    unit: str
    source_module: str
    quality_state: str
    as_of: Optional[str]
    status: str          # مطلوب / خنثی / نامطلوب / ناموجود / نامشخص
    weight: float        # e.g. 40.0, 25.0, etc.
    subscore: float      # in [0, 1]
    contribution: float  # round(weight * subscore, 2)
    applied: bool
    source_note: str
    is_stale: bool = False
    static: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    spatial_resolution_fa: str = ""
    source_name_fa: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WeightedRiskResult:
    """Overall evaluated weighted risk result for an orchard on a specific night."""

    night_date: str
    risk_index: float              # 0.0 to 100.0 (sum of contributions)
    index_category: str            # none, watch, warning, critical
    gate_category: str             # none, warning, critical
    final_category: str            # max(index_category, gate_category)
    final_category_fa: str
    gate_triggered: bool
    gate_reason_fa: Optional[str]
    factors: List[EvaluatedFactor]
    total_weight: float            # Exactly 100.0
    total_contribution: float      # Exactly matches risk_index
    effective_tmin_c: float
    critical_temperature_c: float
    raw_risk_index: float = 0.0
    necessity_multiplier: float = 1.0
    necessity_margin_c: float = 0.0
    illustrative_only: bool = True
    index_is_probability: bool = False
    thresholds_verified: bool = False
    evidence_level: str = "C"

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["factors"] = [f.to_dict() for f in self.factors]
        return res


def _resolve_status_from_subscore(
    subscore: float, is_missing: bool = False, is_unavailable: bool = False
) -> str:
    """Map subscore in [0, 1] to Persian status label."""
    if is_unavailable:
        return "ناموجود"
    if is_missing:
        return "نامشخص"
    if subscore < 0.40:
        return "مطلوب"
    if subscore <= 0.60:
        return "خنثی"
    return "نامطلوب"


def _evaluate_temperature_subscore(
    t_effective_min: float,
    t_critical: float,
    duration_escalated_to_critical: bool,
    margin_safe_c: float = 3.0,
) -> float:
    """Evaluate temperature + duration subscore in [0, 1].

    - If duration rule triggered critical -> s = 1.0
    - If margin <= 0 -> s = 1.0 (at or below critical)
    - If margin >= margin_safe_c -> s = 0.0 (safe)
    - Linear interpolation between 0 and margin_safe_c
    """
    if duration_escalated_to_critical:
        return 1.0

    margin = t_effective_min - t_critical
    if margin <= 0.0:
        return 1.0
    if margin >= margin_safe_c:
        return 0.0
    return round(1.0 - (margin / margin_safe_c), 3)


def _evaluate_stage_subscore(stage_key: str, subscores_map: Dict[str, float]) -> float:
    """Evaluate phenological stage vulnerability ordering per S2."""
    clean_key = stage_key.lower().strip()
    if clean_key in subscores_map:
        return float(subscores_map[clean_key])

    # Fallbacks and aliases
    aliases = {
        "bloom": "full_bloom",
        "opening_bud": "bud_burst",
        "unopened_bud": "unopened_bud",
        "fruit": "fruit_set",
        "dormant": "dormant",
    }
    target = aliases.get(clean_key, clean_key)
    return float(subscores_map.get(target, 0.50))


def _evaluate_moisture_subscore(
    relative_moisture: Optional[float],
    dry_thresh: float = 0.30,
    moist_thresh: float = 0.70,
) -> Tuple[float, bool]:
    """Evaluate relative root-zone moisture subscore.

    Dry is adverse (0.85); moist is favorable (0.20).
    Returns (subscore, is_missing).
    """
    if relative_moisture is None or math.isnan(relative_moisture):
        return 0.50, True

    rel = max(0.0, min(1.0, float(relative_moisture)))
    if rel <= dry_thresh:
        return 0.85, False
    if rel >= moist_thresh:
        return 0.20, False

    # Linear interpolation: 0.85 at dry_thresh down to 0.20 at moist_thresh
    fraction = (rel - dry_thresh) / (moist_thresh - dry_thresh)
    subscore = 0.85 - fraction * (0.85 - 0.20)
    return round(subscore, 3), False


def _evaluate_texture_subscore(
    texture_class_fa: str,
    sand_pct: Optional[float],
    subscores_map: Dict[str, float],
) -> float:
    """Evaluate soil texture subscore. Light sandy soil is adverse per S2."""
    if sand_pct is not None and sand_pct > 70.0:
        return float(subscores_map.get("light_sandy", 0.80))
    if sand_pct is not None and sand_pct < 35.0:
        return float(subscores_map.get("heavy_clay", 0.20))

    if "شن" in texture_class_fa or "ماسه" in texture_class_fa:
        return float(subscores_map.get("light_sandy", 0.80))
    if "رس" in texture_class_fa:
        return float(subscores_map.get("heavy_clay", 0.20))
    return float(subscores_map.get("medium_loam", 0.50))


def _evaluate_wind_speed_subscore(
    speed_mps: Optional[float],
    calm_max: float = 1.0,
    mild_min: float = 1.5,
    mild_max: float = 4.0,
    strong_min: float = 6.0,
) -> Tuple[float, bool]:
    """Evaluate wind speed subscore.

    Calm radiative (<1.0) adverse (0.85); mild mixing (1.5-4.0) favorable (0.20);
    strong advective (>6.0) adverse (0.85).
    """
    if speed_mps is None or math.isnan(speed_mps):
        return 0.50, True

    v = float(speed_mps)
    if v <= calm_max:
        return 0.85, False
    if mild_min <= v <= mild_max:
        return 0.20, False
    if v >= strong_min:
        return 0.85, False

    if calm_max < v < mild_min:
        frac = (v - calm_max) / (mild_min - calm_max)
        return round(0.85 - frac * 0.65, 3), False
    # mild_max < v < strong_min
    frac = (v - mild_max) / (strong_min - mild_max)
    return round(0.20 + frac * 0.65, 3), False


def _evaluate_wind_direction_subscore(
    wind_dir_deg: Optional[float],
    aspect_deg: Optional[float],
    slope_deg: Optional[float],
    cold_sectors: List[List[float]],
) -> Tuple[float, bool]:
    """Evaluate wind direction vs terrain aspect drainage alignment."""
    if wind_dir_deg is None:
        return 0.50, True

    # Flat terrain check
    if slope_deg is not None and slope_deg < 1.0:
        return 0.50, False

    # Cold advection sectors check
    if cold_sectors:
        for sector in cold_sectors:
            if len(sector) == 2:
                s_min, s_max = sector
                if s_min <= s_max and s_min <= wind_dir_deg <= s_max:
                    return 0.85, False
                if s_min > s_max and (wind_dir_deg >= s_min or wind_dir_deg <= s_max):
                    return 0.85, False

    if aspect_deg is None:
        return 0.50, False

    diff = abs(wind_dir_deg - aspect_deg) % 360.0
    delta = min(diff, 360.0 - diff)

    if delta <= 45.0:
        return 0.30, False  # Along downslope drainage: favorable
    if delta >= 135.0:
        return 0.80, False  # Opposing downslope drainage: adverse

    frac = (delta - 45.0) / 90.0
    return round(0.30 + frac * 0.50, 3), False


def _evaluate_cloud_subscore(
    cloud_pct: Optional[float],
    clear_max: float = 20.0,
    overcast_min: float = 70.0,
) -> Tuple[float, bool]:
    """Evaluate cloud cover subscore. Clear sky is adverse (0.90); overcast favorable (0.10)."""
    if cloud_pct is None or math.isnan(cloud_pct):
        return 0.50, True

    c = max(0.0, min(100.0, float(cloud_pct)))
    if c <= clear_max:
        return 0.90, False
    if c >= overcast_min:
        return 0.10, False
    frac = (c - clear_max) / (overcast_min - clear_max)
    return round(0.90 - frac * 0.80, 3), False


def _evaluate_humidity_subscore(
    rh_pct: Optional[float],
    dry_max: float = 30.0,
    humid_min: float = 70.0,
) -> Tuple[float, bool]:
    """Evaluate relative humidity subscore. Dry air is adverse (0.85); humid favorable (0.20)."""
    if rh_pct is None or math.isnan(rh_pct):
        return 0.50, True

    rh = max(0.0, min(100.0, float(rh_pct)))
    if rh <= dry_max:
        return 0.85, False
    if rh >= humid_min:
        return 0.20, False
    frac = (rh - dry_max) / (humid_min - dry_max)
    return round(0.85 - frac * 0.65, 3), False


def _evaluate_pooling_subscore(
    pooling_proxy: Optional[float],
    adverse_min: float = 0.60,
    favorable_max: float = 0.30,
) -> Tuple[float, bool]:
    """Evaluate cold-air pooling proxy subscore."""
    if pooling_proxy is None or math.isnan(pooling_proxy):
        return 0.50, True

    p = max(0.0, min(1.0, float(pooling_proxy)))
    if p >= adverse_min:
        return 0.90, False
    if p <= favorable_max:
        return 0.10, False
    frac = (p - favorable_max) / (adverse_min - favorable_max)
    return round(0.10 + frac * 0.80, 3), False


def _evaluate_slope_subscore(
    slope_deg: Optional[float],
    steep_min: float = 5.0,
    flat_max: float = 1.5,
) -> Tuple[float, bool]:
    """Evaluate terrain slope subscore."""
    if slope_deg is None or math.isnan(slope_deg):
        return 0.50, True

    s = max(0.0, float(slope_deg))
    if s >= steep_min:
        return 0.20, False
    if s <= flat_max:
        return 0.80, False
    frac = (s - flat_max) / (steep_min - flat_max)
    return round(0.80 - frac * 0.60, 3), False


def evaluate_weighted_frost_model(
    inputs: OrchardInputs,
    night_tmin_c: float,
    critical_temp_c: float,
    night_wind_speed_mps: Optional[float],
    night_wind_dir_deg: Optional[float],
    night_cloud_pct: Optional[float],
    night_rh_pct: Optional[float],
    duration_escalated: bool = False,
    night_date: str = "",
    config: Optional[FrostWeightedModelConfig] = None,
) -> WeightedRiskResult:
    """Evaluate weighted factor model per orchard for a given night.

    Follows R3 specifications:
    - Piecewise / categorical subscores s_i in [0, 1]
    - Asymmetry floor (0.50) on protective_capable rows for coarse_context data
    - Sum of contributions equals total risk_index in [0, 100]
    - Absolute Safety Gate (GATE) enforces lethal temperatures never diluted
    """
    cfg = config or load_frost_factor_weights_config()

    evaluated_factors: List[EvaluatedFactor] = []
    total_contribution = 0.0

    # -------------------------------------------------------------------------
    # 1. Temperature + Duration
    # -------------------------------------------------------------------------
    f_temp = cfg.get_factor("temperature_duration")
    if f_temp:
        margin_safe = f_temp.margin_safe_c
        s_temp = _evaluate_temperature_subscore(
            t_effective_min=night_tmin_c,
            t_critical=critical_temp_c,
            duration_escalated_to_critical=duration_escalated,
            margin_safe_c=margin_safe,
        )
        contrib_temp = round(f_temp.weight * s_temp, 2)
        total_contribution += contrib_temp
        status_temp = _resolve_status_from_subscore(s_temp)
        evaluated_factors.append(
            EvaluatedFactor(
                id="temperature_duration",
                label_fa=f_temp.label_fa,
                raw_value=f"{night_tmin_c:.1f} °C (آستانه {critical_temp_c:.1f} °C)",
                unit="°C",
                source_module=f_temp.source_module,
                quality_state="coarse_context",
                as_of=inputs.assembled_at,
                status=status_temp,
                weight=f_temp.weight,
                subscore=s_temp,
                contribution=contrib_temp,
                applied=True,
                source_note=f_temp.source_note,
                is_stale=False,
                details={
                    "effective_tmin_c": night_tmin_c,
                    "critical_temperature_c": critical_temp_c,
                    "margin_c": round(night_tmin_c - critical_temp_c, 2),
                    "duration_escalated": duration_escalated,
                },
            )
        )

    # -------------------------------------------------------------------------
    # 2. Phenological Stage
    # -------------------------------------------------------------------------
    f_stage = cfg.get_factor("phenological_stage")
    if f_stage:
        stage_input = inputs.factors.get("phenological_stage")
        stage_val = stage_input.value if stage_input else inputs.current_stage
        stage_stale = stage_input.is_stale if stage_input else inputs.stage_is_stale
        stage_qstate = stage_input.quality_state if stage_input else "valid"
        stage_asof = stage_input.as_of if stage_input else inputs.assembled_at

        # If stage is stale (> 14 days), treat as unknown and use most sensitive configured stage (R4)
        stage_name_fa = STAGE_NAME_FA.get(stage_val, stage_val)
        if stage_stale or stage_qstate == "unknown":
            s_stage = 1.0  # Most sensitive (full_bloom)
            display_stage = f"{stage_name_fa} (مرحله قدیمی/نامشخص)"
            status_stage = "نامشخص"
        else:
            s_stage = _evaluate_stage_subscore(stage_val, f_stage.stage_subscores)
            display_stage = stage_name_fa
            status_stage = _resolve_status_from_subscore(s_stage)

        contrib_stage = round(f_stage.weight * s_stage, 2)
        total_contribution += contrib_stage
        evaluated_factors.append(
            EvaluatedFactor(
                id="phenological_stage",
                label_fa=f_stage.label_fa,
                raw_value=display_stage,
                unit="مرحله فنولوژی",
                source_module=f_stage.source_module,
                quality_state=stage_qstate,
                as_of=stage_asof,
                status=status_stage,
                weight=f_stage.weight,
                subscore=s_stage,
                contribution=contrib_stage,
                applied=True,
                source_note=f_stage.source_note,
                is_stale=stage_stale,
                details={
                    "stage_key": stage_val,
                    "is_stale": stage_stale,
                },
            )
        )

    # -------------------------------------------------------------------------
    # 3. Soil Root-Zone Moisture
    # -------------------------------------------------------------------------
    f_moist = cfg.get_factor("soil_rootzone_moisture")
    if f_moist:
        moist_input = inputs.factors.get("soil_rootzone_moisture")
        rel_moist = moist_input.value if moist_input else None
        moist_qstate = moist_input.quality_state if moist_input else "unavailable"
        moist_asof = moist_input.as_of if moist_input else None
        moist_stale = moist_input.is_stale if moist_input else False
        moist_static = getattr(moist_input, "static", False) if moist_input else False

        if moist_qstate == "unavailable":
            s_moist = 0.50
            status_moist = "ناموجود"
            display_moist = "داده این باغ موجود نیست"
        elif rel_moist is None:
            s_moist = 0.50
            status_moist = "نامشخص"
            display_moist = "نامشخص"
        else:
            s_moist, is_missing = _evaluate_moisture_subscore(rel_moist)
            # Asymmetry Floor: coarse_context cannot score below 0.50
            if f_moist.protective_capable and moist_qstate != "valid" and s_moist < 0.50:
                s_moist = 0.50
            status_moist = _resolve_status_from_subscore(s_moist, is_missing=is_missing)

            # V3: Check if dry below wilting point (real aridity vs nodata)
            is_dry_below_wp = bool(
                moist_input and (
                    (moist_input.details or {}).get("below_wilting_point") or
                    (
                        (moist_input.details or {}).get("theta_rootzone_m3m3") is not None
                        and (moist_input.details or {}).get("wilting_point_m3m3") is not None
                        and float((moist_input.details or {}).get("theta_rootzone_m3m3")) < float((moist_input.details or {}).get("wilting_point_m3m3"))
                    )
                )
            )
            if is_dry_below_wp and rel_moist <= 0.001:
                display_moist = "خشک‌تر از نقطه پژمردگی (برآورد درشت‌مقیاس، نامطمئن)"
            else:
                display_moist = f"{rel_moist:.2f}"

        contrib_moist = round(f_moist.weight * s_moist, 2)
        total_contribution += contrib_moist

        evaluated_factors.append(
            EvaluatedFactor(
                id="soil_rootzone_moisture",
                label_fa=f_moist.label_fa,
                raw_value=display_moist,
                unit="نسبی [۰-۱]",
                source_module=f_moist.source_module,
                quality_state=moist_qstate,
                as_of=moist_asof,
                status=status_moist,
                weight=f_moist.weight,
                subscore=s_moist,
                contribution=contrib_moist,
                applied=True,
                source_note=f_moist.source_note,
                is_stale=moist_stale,
                static=moist_static,
                details=moist_input.details if moist_input else {},
            )
        )

    # -------------------------------------------------------------------------
    # 4. Soil Texture & Depth
    # -------------------------------------------------------------------------
    f_texture = cfg.get_factor("soil_texture_depth")
    if f_texture:
        tex_input = inputs.factors.get("soil_texture_depth")
        tex_val = tex_input.value if tex_input else None
        tex_qstate = tex_input.quality_state if tex_input else "unavailable"
        tex_asof = tex_input.as_of if tex_input else None
        tex_static = getattr(tex_input, "static", True) if tex_input else True
        sand_pct = (tex_input.details or {}).get("sand_percent") if tex_input else None

        if tex_qstate == "unavailable" or tex_val is None:
            s_tex = 0.50
            status_tex = "ناموجود"
            display_tex = "داده این باغ موجود نیست"
            tex_qstate = "unavailable"
        else:
            s_tex = _evaluate_texture_subscore(str(tex_val), sand_pct, f_texture.texture_subscores)
            # Asymmetry Floor: coarse_context cannot score below 0.50
            if f_texture.protective_capable and tex_qstate != "valid" and s_tex < 0.50:
                s_tex = 0.50
            status_tex = _resolve_status_from_subscore(s_tex)
            display_tex = f"{tex_val} (شن {sand_pct:.0f}٪)" if sand_pct is not None else str(tex_val)

        contrib_tex = round(f_texture.weight * s_tex, 2)
        total_contribution += contrib_tex

        evaluated_factors.append(
            EvaluatedFactor(
                id="soil_texture_depth",
                label_fa=f_texture.label_fa,
                raw_value=display_tex,
                unit="رده بافت خاک",
                source_module=f_texture.source_module,
                quality_state=tex_qstate,
                as_of=tex_asof,
                status=status_tex,
                weight=f_texture.weight,
                subscore=s_tex,
                contribution=contrib_tex,
                applied=True,
                source_note=f_texture.source_note,
                is_stale=False,
                static=tex_static,
                details=tex_input.details if tex_input else {},
            )
        )

    # -------------------------------------------------------------------------
    # 5. Wind Speed
    # -------------------------------------------------------------------------
    f_wind = cfg.get_factor("wind_speed")
    if f_wind:
        s_wind, is_missing_wind = _evaluate_wind_speed_subscore(night_wind_speed_mps)
        status_wind = _resolve_status_from_subscore(s_wind, is_missing=is_missing_wind)
        contrib_wind = round(f_wind.weight * s_wind, 2)
        total_contribution += contrib_wind

        display_wind = f"{night_wind_speed_mps:.1f} m/s" if night_wind_speed_mps is not None else "نامشخص"
        evaluated_factors.append(
            EvaluatedFactor(
                id="wind_speed",
                label_fa=f_wind.label_fa,
                raw_value=display_wind,
                unit="m/s",
                source_module=f_wind.source_module,
                quality_state="coarse_context",
                as_of=inputs.assembled_at,
                status=status_wind,
                weight=f_wind.weight,
                subscore=s_wind,
                contribution=contrib_wind,
                applied=True,
                source_note=f_wind.source_note,
                is_stale=False,
                details={"wind_speed_mps": night_wind_speed_mps},
            )
        )

    # -------------------------------------------------------------------------
    # 6. Wind Direction vs Slope Aspect
    # -------------------------------------------------------------------------
    f_wind_dir = cfg.get_factor("wind_direction")
    if f_wind_dir:
        terrain_input = inputs.factors.get("topography_slope_aspect")
        slope_deg = (terrain_input.details or {}).get("slope_deg") if terrain_input else 2.0
        aspect_deg = (terrain_input.details or {}).get("aspect_deg") if terrain_input else 180.0

        s_wdir, is_missing_wdir = _evaluate_wind_direction_subscore(
            wind_dir_deg=night_wind_dir_deg,
            aspect_deg=aspect_deg,
            slope_deg=slope_deg,
            cold_sectors=cfg.cold_advection_sectors,
        )
        status_wdir = _resolve_status_from_subscore(s_wdir, is_missing=is_missing_wdir)
        contrib_wdir = round(f_wind_dir.weight * s_wdir, 2)
        total_contribution += contrib_wdir

        display_wdir = f"{night_wind_dir_deg:.0f}°" if night_wind_dir_deg is not None else "نامشخص"
        evaluated_factors.append(
            EvaluatedFactor(
                id="wind_direction",
                label_fa=f_wind_dir.label_fa,
                raw_value=display_wdir,
                unit="درجه",
                source_module=f_wind_dir.source_module,
                quality_state="coarse_context",
                as_of=inputs.assembled_at,
                status=status_wdir,
                weight=f_wind_dir.weight,
                subscore=s_wdir,
                contribution=contrib_wdir,
                applied=True,
                source_note=f_wind_dir.source_note,
                is_stale=False,
                details={
                    "wind_dir_deg": night_wind_dir_deg,
                    "aspect_deg": aspect_deg,
                    "slope_deg": slope_deg,
                },
            )
        )

    # -------------------------------------------------------------------------
    # 7. Cloud Cover
    # -------------------------------------------------------------------------
    f_cloud = cfg.get_factor("cloud_cover")
    if f_cloud:
        s_cloud, is_missing_cloud = _evaluate_cloud_subscore(night_cloud_pct)
        status_cloud = _resolve_status_from_subscore(s_cloud, is_missing=is_missing_cloud)
        contrib_cloud = round(f_cloud.weight * s_cloud, 2)
        total_contribution += contrib_cloud

        display_cloud = f"{night_cloud_pct:.0f}٪" if night_cloud_pct is not None else "نامشخص"
        evaluated_factors.append(
            EvaluatedFactor(
                id="cloud_cover",
                label_fa=f_cloud.label_fa,
                raw_value=display_cloud,
                unit="درصد",
                source_module=f_cloud.source_module,
                quality_state="coarse_context",
                as_of=inputs.assembled_at,
                status=status_cloud,
                weight=f_cloud.weight,
                subscore=s_cloud,
                contribution=contrib_cloud,
                applied=True,
                source_note=f_cloud.source_note,
                is_stale=False,
                details={"cloud_percent": night_cloud_pct},
            )
        )

    # -------------------------------------------------------------------------
    # 8. Humidity & Dew Point
    # -------------------------------------------------------------------------
    f_rh = cfg.get_factor("humidity_dewpoint")
    if f_rh:
        s_rh, is_missing_rh = _evaluate_humidity_subscore(night_rh_pct)
        status_rh = _resolve_status_from_subscore(s_rh, is_missing=is_missing_rh)
        contrib_rh = round(f_rh.weight * s_rh, 2)
        total_contribution += contrib_rh

        display_rh = f"{night_rh_pct:.0f}٪" if night_rh_pct is not None else "نامشخص"
        evaluated_factors.append(
            EvaluatedFactor(
                id="humidity_dewpoint",
                label_fa=f_rh.label_fa,
                raw_value=display_rh,
                unit="درصد",
                source_module=f_rh.source_module,
                quality_state="coarse_context",
                as_of=inputs.assembled_at,
                status=status_rh,
                weight=f_rh.weight,
                subscore=s_rh,
                contribution=contrib_rh,
                applied=True,
                source_note=f_rh.source_note,
                is_stale=False,
                details={"relative_humidity_percent": night_rh_pct},
            )
        )

    # -------------------------------------------------------------------------
    # 9. Topography: Cold-Air Pooling Proxy
    # -------------------------------------------------------------------------
    f_pool = cfg.get_factor("topography_pooling")
    if f_pool:
        pool_input = inputs.factors.get("topography_pooling")
        pool_val = pool_input.value if pool_input else None
        pool_qstate = pool_input.quality_state if pool_input else "unavailable"
        pool_asof = pool_input.as_of if pool_input else None
        pool_static = getattr(pool_input, "static", True) if pool_input else True

        if pool_qstate == "unavailable" or pool_val is None:
            s_pool = 0.50
            status_pool = "ناموجود"
            display_pool = "داده این باغ موجود نیست"
            pool_qstate = "unavailable"
        else:
            s_pool, is_missing_pool = _evaluate_pooling_subscore(pool_val)
            status_pool = _resolve_status_from_subscore(s_pool, is_missing=is_missing_pool)
            display_pool = f"{pool_val:.2f}"

        contrib_pool = round(f_pool.weight * s_pool, 2)
        total_contribution += contrib_pool

        evaluated_factors.append(
            EvaluatedFactor(
                id="topography_pooling",
                label_fa=f_pool.label_fa,
                raw_value=display_pool,
                unit="شاخص [۰-۱]",
                source_module=f_pool.source_module,
                quality_state=pool_qstate,
                as_of=pool_asof,
                status=status_pool,
                weight=f_pool.weight,
                subscore=s_pool,
                contribution=contrib_pool,
                applied=True,
                source_note=f_pool.source_note,
                is_stale=False,
                static=pool_static,
                details=pool_input.details if pool_input else {},
            )
        )

    # -------------------------------------------------------------------------
    # 10. Topography: Slope & Aspect
    # -------------------------------------------------------------------------
    f_slope = cfg.get_factor("topography_slope_aspect")
    if f_slope:
        slope_input = inputs.factors.get("topography_slope_aspect")
        slope_val = slope_input.value if slope_input else None
        slope_qstate = slope_input.quality_state if slope_input else "unavailable"
        slope_asof = slope_input.as_of if slope_input else None
        slope_static = getattr(slope_input, "static", True) if slope_input else True

        if slope_qstate == "unavailable" or slope_val is None:
            s_slope = 0.50
            status_slope = "ناموجود"
            display_slope = "داده این باغ موجود نیست"
            slope_qstate = "unavailable"
        else:
            s_slope, is_missing_slope = _evaluate_slope_subscore(slope_val)
            status_slope = _resolve_status_from_subscore(s_slope, is_missing=is_missing_slope)
            display_slope = f"{slope_val:.1f}°"

        contrib_slope = round(f_slope.weight * s_slope, 2)
        total_contribution += contrib_slope

        evaluated_factors.append(
            EvaluatedFactor(
                id="topography_slope_aspect",
                label_fa=f_slope.label_fa,
                raw_value=display_slope,
                unit="درجه",
                source_module=f_slope.source_module,
                quality_state=slope_qstate,
                as_of=slope_asof,
                status=status_slope,
                weight=f_slope.weight,
                subscore=s_slope,
                contribution=contrib_slope,
                applied=True,
                source_note=f_slope.source_note,
                is_stale=False,
                static=slope_static,
                details=slope_input.details if slope_input else {},
            )
        )

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # S3: Temperature as a Necessary Condition (تعدیل‌گر شرط لازم دما)
    # margin = Tmin_eff - T_crit
    # m = 1.0 when margin <= margin_safe_c (4.0 °C)
    # Linear attenuation from 1.0 down to m_min (0.10) between 4.0 °C and 10.0 °C
    # m = 0.10 when margin >= margin_warm_c (10.0 °C)
    # index_final = index * m
    # -------------------------------------------------------------------------
    margin_c = round(night_tmin_c - critical_temp_c, 2)
    t_nec_cfg = cfg.temperature_necessity or {}
    safe_margin = float(t_nec_cfg.get("margin_safe_c", 4.0))
    warm_margin = float(t_nec_cfg.get("margin_warm_c", 10.0))
    m_min = float(t_nec_cfg.get("m_min", 0.10))

    if margin_c <= safe_margin:
        m_attenuation = 1.0
    elif margin_c >= warm_margin:
        m_attenuation = m_min
    else:
        frac = (margin_c - safe_margin) / (warm_margin - safe_margin)
        m_attenuation = 1.0 - frac * (1.0 - m_min)

    m_attenuation = round(max(m_min, min(1.0, m_attenuation)), 4)
    raw_risk_index = round(total_contribution, 2)

    if m_attenuation < 1.0:
        for ef in evaluated_factors:
            ef.details["raw_contribution"] = ef.contribution
            ef.details["necessity_multiplier"] = m_attenuation
            ef.contribution = round(ef.contribution * m_attenuation, 2)
        total_contribution = round(sum(ef.contribution for ef in evaluated_factors), 2)
    else:
        total_contribution = raw_risk_index

    risk_index = max(0.0, min(100.0, total_contribution))

    # Evaluate Index Category from Category Bands
    bands = cfg.category_bands
    none_max = float(bands.get("none_max", 25.0))
    watch_max = float(bands.get("watch_max", 45.0))
    warn_max = float(bands.get("warning_max", 70.0))

    if risk_index < none_max:
        index_cat = "none"
    elif risk_index < watch_max:
        index_cat = "watch"
    elif risk_index < warn_max:
        index_cat = "warning"
    else:
        index_cat = "critical"

    # -------------------------------------------------------------------------
    # Absolute Safety Gate (GATE) Enforcement
    # -------------------------------------------------------------------------
    gate_cat = "none"
    gate_reason_fa = None

    if duration_escalated:
        gate_cat = "critical"
        gate_reason_fa = (
            "دیرش تداوم دما زیر آستانه بحرانی خسارت محقق شده است (ارتقای قطعی به بحرانی)."
        )
    elif night_tmin_c <= critical_temp_c:
        gate_cat = "warning"
        gate_reason_fa = (
            f"دمای مؤثر ({night_tmin_c:.1f} °C) در یا زیر آستانه آسیب فیزیولوژیک "
            f"({critical_temp_c:.1f} °C) است؛ مدل اجازه تقلیل خطر به زیر سطح هشدار را نمی‌دهد."
        )

    # Final Category = max(index_category, gate_category)
    final_cat = (
        gate_cat
        if RISK_HIERARCHY[gate_cat] > RISK_HIERARCHY[index_cat]
        else index_cat
    )
    gate_triggered = (gate_cat != "none")

    # Populate canonical metadata mappings on all evaluated factors
    for ef in evaluated_factors:
        if not ef.spatial_resolution_fa:
            ef.spatial_resolution_fa = FACTOR_RESOLUTION_MAP.get(ef.id, "")
        if not ef.source_name_fa:
            ef.source_name_fa = FACTOR_SOURCE_FA_MAP.get(ef.id, "")

    return WeightedRiskResult(
        night_date=night_date,
        risk_index=risk_index,
        index_category=index_cat,
        gate_category=gate_cat,
        final_category=final_cat,
        final_category_fa=RISK_CATEGORY_FA.get(final_cat, final_cat),
        gate_triggered=gate_triggered,
        gate_reason_fa=gate_reason_fa if gate_triggered else None,
        factors=evaluated_factors,
        total_weight=100.0,
        total_contribution=total_contribution,
        effective_tmin_c=night_tmin_c,
        critical_temperature_c=critical_temp_c,
        raw_risk_index=raw_risk_index,
        necessity_multiplier=m_attenuation,
        necessity_margin_c=margin_c,
        illustrative_only=cfg.illustrative_only,
        index_is_probability=cfg.index_is_probability,
        thresholds_verified=cfg.thresholds_verified,
        evidence_level=cfg.evidence_level,
    )
