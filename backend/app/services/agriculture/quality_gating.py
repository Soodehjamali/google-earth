"""Centralized Quality Gating Configuration and Three-State Quality Model (Phase 2).

Rules live in ONE config place (not scattered):
- valid: native resolution is adequate for the polygon (native pixel size <= a configurable
  fraction of the polygon extent, and/or <= 30 m) AND valid pixels exist.
- coarse_context: real, valid data, but native footprint is larger than the polygon.
  Must carry native_resolution_m, a plain description of the support (cell value vs area mean),
  and the cell's mean elevation where relevant.
- unavailable: no valid pixels, masked, failed QC, or a true computation error;
  carries the Phase 1 reason/error code. Expected unavailability must never raise an exception.

Hard invariants:
- coarse_context data is never used for within-field comparison, zone-level claims, or zoning.
- coarse_context cannot raise an evidence level to A for field-level statements.
- coarse_context may support regional-context statements only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from app.core.logging import get_logger

logger = get_logger(__name__)


class QualityState(str, Enum):
    """Three-state quality model for agricultural remote sensing and reanalysis.

    VALID: Native resolution is adequate for field-level analysis and valid pixels exist.
    COARSE_CONTEXT: Real, valid data, but native footprint is larger than the polygon.
                    Usable for regional context, never for within-field zoning or Level A claims.
    UNAVAILABLE: No valid pixels, cloud-masked, failed QC, or true computation error.
    """

    VALID = "valid"
    COARSE_CONTEXT = "coarse_context"
    UNAVAILABLE = "unavailable"

    @property
    def is_usable_data(self) -> bool:
        """Whether this state carries usable real-world data (field or regional)."""
        return self in (QualityState.VALID, QualityState.COARSE_CONTEXT)

    @property
    def is_field_scale(self) -> bool:
        """Whether this state is valid at field/orchard scale."""
        return self is QualityState.VALID


#: Datasets known to have coarse native footprint (>100 m to 11 km)
COARSE_DATASET_IDS: frozenset[str] = frozenset(
    {
        "ECMWF/ERA5_LAND/DAILY_AGGR",
        "ECMWF/ERA5_LAND/HOURLY",
        "NASA/GLDAS/V021/NOAH/G025/T3H",
        "NASA/SMAP/SPL4SMGP/008",
        "NASA/SMAP/SPL3SMP_E/005",
        "IDAHO_EPSCOR/TERRACLIMATE",
        "MODIS/061/MOD11A2",
        "MODIS/061/MOD16A2",
        "MODIS/061/MOD17A2H",
        "MODIS/061/MOD13Q1",
    }
)


@dataclass(frozen=True)
class QualityGatingConfig:
    """Centralized configuration for quality gating and temperature calibration.

    Every parameter carries a 'needs calibration' status and explicit documentation.
    No invented constants: default values are traceable standard tropospheric placeholders.
    """

    #: Native pixel resolution floor in metres considered field-scale (Sentinel-2 10-20m, S1 10m, Landsat 30m).
    field_scale_max_resolution_m: float = 30.0

    #: Maximum ratio of native pixel resolution to polygon bounding extent.
    #: If pixel size <= extent * max_extent_ratio, native grid is adequate for polygon mean.
    max_extent_ratio: float = 0.5

    #: Default environmental temperature lapse rate in °C per km of elevation gain.
    #: Standard ICAO tropospheric lapse rate placeholder (-6.5 °C/km). Marked "needs calibration".
    default_lapse_rate_c_per_km: float = -6.5
    lapse_rate_note: str = "Standard tropospheric lapse rate (-6.5 °C/km); needs calibration with local weather stations"

    #: Configurable uncertainty for daytime temperature elevation correction (°C).
    temp_day_uncertainty_c: float = 1.0
    temp_day_uncertainty_note: str = "Placeholder daytime uncertainty (±1.0 °C); needs calibration"

    #: Configurable uncertainty for nighttime minimum temperature elevation correction (°C).
    #: Higher due to atmospheric inversion and cold air drainage risk.
    temp_night_uncertainty_c: float = 2.0
    temp_night_uncertainty_note: str = (
        "Placeholder nighttime minimum uncertainty (±2.0 °C); "
        "elevated because simple lapse rates are unreliable during clear-sky inversions. Needs calibration."
    )

    #: Growing Degree Days base temperature (°C) for pistachio. Existing config.
    gdd_base_temp_c: float = 10.0
    gdd_base_temp_note: str = "Standard pistachio base temperature (10.0 °C); needs calibration per cultivar"

    #: Growing Degree Days upper temperature cap (°C) for pistachio. Existing config.
    gdd_upper_temp_c: float = 35.0
    gdd_upper_temp_note: str = "Pistachio heat threshold cap (35.0 °C); needs calibration"

    #: Default local timezone for calendar-day aggregation
    local_timezone: str = "Asia/Tehran"


#: Singleton default configuration
DEFAULT_QUALITY_CONFIG = QualityGatingConfig()


def classify_quality_state(
    native_resolution_m: Optional[float],
    polygon_extent_m: Optional[float] = None,
    has_valid_pixels: bool = True,
    qc_passed: bool = True,
    computation_error: bool = False,
    dataset_id: Optional[str] = None,
    config: Optional[QualityGatingConfig] = None,
) -> QualityState:
    """Classify a metric's output into the three-state quality model.

    This is the single centralized authority for assigning QualityState.
    """
    if computation_error or not has_valid_pixels or not qc_passed:
        return QualityState.UNAVAILABLE

    cfg = config or DEFAULT_QUALITY_CONFIG

    # Known coarse dataset check
    if dataset_id and dataset_id in COARSE_DATASET_IDS:
        return QualityState.COARSE_CONTEXT

    # Resolution check
    if native_resolution_m is None:
        return QualityState.VALID

    # If native resolution is <= field scale threshold (30m), it is field-scale valid
    if native_resolution_m <= cfg.field_scale_max_resolution_m:
        return QualityState.VALID

    # If polygon extent is known, check whether resolution fits within polygon extent
    if polygon_extent_m is not None and polygon_extent_m > 0:
        if native_resolution_m <= (polygon_extent_m * cfg.max_extent_ratio):
            return QualityState.VALID

    # Real data exists, but footprint is coarser than polygon
    return QualityState.COARSE_CONTEXT


def describe_support(
    native_resolution_m: Optional[float],
    is_point_queryable: bool = False,
    is_area_mean: bool = False,
) -> str:
    """Plain-language English description of the spatial support."""
    if native_resolution_m is None or native_resolution_m <= 30.0:
        return "Field-scale polygon reduction"
    km = native_resolution_m / 1000.0
    if is_point_queryable:
        return f"Containing cell value (~{km:.1f} km grid cell sampled at parcel location)"
    if is_area_mean:
        return f"Regional area mean over intersecting cell footprint (~{km:.1f} km grid)"
    return f"Regional cell footprint (~{km:.1f} km grid intersecting parcel)"


def describe_support_fa(native_resolution_m: Optional[float]) -> str:
    """Farmer-friendly Persian badge text for coarse context metrics."""
    if native_resolution_m is None or native_resolution_m <= 30.0:
        return "داده دقیق مزرعه"
    km = native_resolution_m / 1000.0
    if km >= 1.0:
        # Format integer if round, else 1 decimal
        km_str = f"{int(km)}" if km.is_integer() else f"{km:.1f}"
        return f"زمینه منطقه‌ای، وضوح ≈ {km_str} کیلومتر"
    return f"زمینه منطقه‌ای، وضوح ≈ {int(native_resolution_m)} متر"


def normalize_legacy_quality_state(
    data: Dict[str, Any],
    default_resolution_m: Optional[float] = None,
) -> str:
    """Normalize legacy stored report dictionary lacking explicit quality_state.

    Explicitly maps legacy PostgreSQL stored reports to the three-state model:
    - If value is None, or status in (unavailable, error, insufficient_data), or quality in (unavailable, insufficient):
      returns 'unavailable'
    - Else if dataset or resolution is known coarse: returns 'coarse_context'
    - Else: returns 'valid'
    """
    if "quality_state" in data and data["quality_state"]:
        state_str = str(data["quality_state"]).lower().strip()
        if state_str in ("valid", "coarse_context", "unavailable"):
            return state_str

    val = data.get("value")
    status = str(data.get("status", "")).lower().strip()
    quality = str(data.get("quality", "") or data.get("quality_level", "")).lower().strip()

    is_item = "metric_key" in data or "value" in data
    if is_item and val is None:
        return QualityState.UNAVAILABLE.value
    if status in ("unavailable", "error", "insufficient_data") or quality in ("unavailable", "insufficient"):
        return QualityState.UNAVAILABLE.value

    # Check dataset / resolution
    dataset = data.get("source_dataset") or data.get("source_dataset_id")
    if dataset and dataset in COARSE_DATASET_IDS:
        return QualityState.COARSE_CONTEXT.value

    metric_key = str(data.get("metric_key", "")).lower()
    coarse_metric_prefixes = ("era5_", "temperature_2m", "dewpoint_", "solar_radiation", "vpd", "gdd", "relative_humidity", "total_precipitation", "wind_speed", "soil_moisture_smap", "soil_moisture_am", "soil_moisture_pm")
    if any(metric_key.startswith(p) or metric_key == p for p in coarse_metric_prefixes):
        return QualityState.COARSE_CONTEXT.value

    spatial_res = str(data.get("spatial_resolution", "")).lower()
    if any(k in spatial_res for k in ("km", "1000 m", "9000 m", "11132 m", "0.1 deg", "0.25 deg")):
        return QualityState.COARSE_CONTEXT.value

    if default_resolution_m and default_resolution_m > 30.0:
        return QualityState.COARSE_CONTEXT.value

    return QualityState.VALID.value


# ---------------------------------------------------------------------------
# Task 2.2: DEM-based Temperature Elevation Correction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ElevationCorrectionResult:
    """Result of DEM-based temperature elevation correction."""

    raw_value: float
    corrected_value: float
    delta_c: float
    uncertainty_c: float
    uncertainty_note_fa: str
    z_cell_m: float
    z_site_m: float
    lapse_rate_c_per_km: float


def correct_temperature_for_elevation(
    t_cell: float,
    z_cell: float,
    z_site: float,
    lapse_rate_c_per_km: Optional[float] = None,
    is_night_minimum: bool = False,
    config: Optional[QualityGatingConfig] = None,
) -> ElevationCorrectionResult:
    """Apply physical lapse-rate elevation correction to air temperature.

    Formula:
        delta_z_km = (z_site - z_cell) / 1000.0
        delta_c = lapse_rate_c_per_km * delta_z_km
        corrected_value = t_cell + delta_c

    A positive delta_z (site is higher than grid cell) with negative lapse rate
    results in a negative delta_c (corrected temperature is cooler).
    Equal elevations yield exactly delta_c = 0.0.
    """
    cfg = config or DEFAULT_QUALITY_CONFIG
    gamma = lapse_rate_c_per_km if lapse_rate_c_per_km is not None else cfg.default_lapse_rate_c_per_km

    delta_z_km = (z_site - z_cell) / 1000.0
    delta_c = gamma * delta_z_km
    corrected = t_cell + delta_c

    if is_night_minimum:
        uncertainty = cfg.temp_night_uncertainty_c
        note_fa = (
            "تصحیح بر اساس نرخ افت دما (-۶.۵ °C/km)؛ توجه: در شب‌های صاف و آرام به دلیل "
            "احتمال وارونگی دمایی (اینورژن) و تجمع هوای سرد در گودی‌ها، این تخمین عدم قطعیت بالاتری دارد (نیاز به کالیبراسیون محلی)."
        )
    else:
        uncertainty = cfg.temp_day_uncertainty_c
        note_fa = (
            f"تصحیح ارتفاعی بر پایه اختلاف تراز توپوگرافی با مدل NASADEM (اختلاف: {z_site - z_cell:+.0f} متر)؛ "
            "برآورد منطقه‌ای نیازمند کالیبراسیون با ایستگاه هواشناسی محلی."
        )

    return ElevationCorrectionResult(
        raw_value=round(t_cell, 2),
        corrected_value=round(corrected, 2),
        delta_c=round(delta_c, 2),
        uncertainty_c=round(uncertainty, 2),
        uncertainty_note_fa=note_fa,
        z_cell_m=round(z_cell, 1),
        z_site_m=round(z_site, 1),
        lapse_rate_c_per_km=round(gamma, 2),
    )


def aggregate_hourly_to_local_days(
    hourly_records: Sequence[Tuple[datetime, float]],
    timezone_str: str = "Asia/Tehran",
) -> Dict[str, Dict[str, float]]:
    """Group hourly timestamped temperatures into local calendar days.

    Computes local-day min, max, and mean temperatures.
    Crucial for frost monitoring: in UTC+03:30, night frost minima (e.g. 04:00 local = 00:30 UTC)
    must fall into the correct local calendar day, never split or attributed to the wrong date.
    """
    tz = ZoneInfo(timezone_str)
    grouped: Dict[str, List[float]] = {}

    for dt, temp in hourly_records:
        if dt.tzinfo is None:
            # Assume UTC if naive
            dt_utc = dt.replace(tzinfo=timezone.utc)
        else:
            dt_utc = dt.astimezone(timezone.utc)

        local_dt = dt_utc.astimezone(tz)
        local_date_str = local_dt.strftime("%Y-%m-%d")

        if local_date_str not in grouped:
            grouped[local_date_str] = []
        grouped[local_date_str].append(float(temp))

    result: Dict[str, Dict[str, float]] = {}
    for date_str, temps in grouped.items():
        if not temps:
            continue
        result[date_str] = {
            "min": min(temps),
            "max": max(temps),
            "mean": sum(temps) / len(temps),
            "count": len(temps),
        }
    return result
